"""
Landing page — the course background image with a frosted-glass stats
dashboard composited over it, plus the sidebar's course-photo banner.

Tk/customtkinter has no per-widget alpha, so true translucent tiles over an
image aren't possible with CTkFrames. Instead the "frosted glass" effect is
composited in PIL: each tile crops its own patch from a *blurred* copy of
the background, blends it toward Colors.BG_SURFACE, masks rounded corners,
and is drawn onto the canvas as a plain image. Because every tile's pixels
come from the exact region of background it covers, the image genuinely
shows through — resize the window and the frost tracks the photo.

Everything is drawn on one tk.Canvas and fully redrawn on resize (debounced,
same pattern as the chart panels' autosize binding in app_window).

Layout (data present):        Layout (no data yet):
  hero title                     hero title
  [4 stat tiles]                 [single hint card]
  [4 record tiles]
  [shot quality | sim handicap]

Dashboards are launched from the sidebar checkboxes and the top-bar "Go
Live" button, so the landing page is a read-only summary — no navigation
controls of its own.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageTk

from config import FONT_FAMILY, FONT_SCALE, SPACING, Colors
from data.store import HomeStats, HomeTrends, PlayerRecords
from ui import theme

# How strongly tiles blend toward the solid surface color (1.0 = opaque
# card, 0.0 = pure blurred photo). Chips sit a touch clearer than tiles.
_TILE_TINT = 0.78
_CHIP_TINT = 0.60
_BLUR_RADIUS = 7
_BG_DIM = 0.85  # slight darken of the full photo so white text stays legible

def _quality_color(q) -> str:
    if q is None:
        return Colors.TEXT_ACTIVE
    return Colors.SUCCESS if q >= 70 else Colors.INFO if q >= 50 else Colors.WARNING


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _frosted(blurred: Image.Image, box: tuple[int, int, int, int], radius: int,
             tint: float = _TILE_TINT, outline: str = Colors.BORDER) -> ImageTk.PhotoImage:
    """One frosted tile: the tile's own patch of the blurred background,
    blended toward BG_SURFACE, with rounded corners and a hairline border."""
    crop = blurred.crop(box).convert("RGB")
    overlay = Image.new("RGB", crop.size, _hex_rgb(Colors.BG_SURFACE))
    tile = Image.blend(crop, overlay, tint).convert("RGBA")
    w, h = tile.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    tile.putalpha(mask)
    ImageDraw.Draw(tile).rounded_rectangle(
        (0, 0, w - 1, h - 1), radius, outline=_hex_rgb(outline) + (230,), width=1)
    return ImageTk.PhotoImage(tile)


def _rounded_cover(src: Image.Image, size: tuple[int, int], radius: int,
                   dim_toward: str, dim: float) -> Image.Image:
    """Cover-crop `src` to `size`, blend toward a solid color for legibility,
    and round the corners. Used by the sidebar banner."""
    tw, th = size
    scale = max(tw / src.width, th / src.height)
    img = src.resize((max(tw, int(src.width * scale)), max(th, int(src.height * scale))),
                     Image.Resampling.LANCZOS)
    left, top = (img.width - tw) // 2, (img.height - th) // 2
    img = img.crop((left, top, left + tw, top + th)).convert("RGB")
    img = Image.blend(img, Image.new("RGB", img.size, _hex_rgb(dim_toward)), dim)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def course_banner(master, image_path, title: str, scale: float = 1.0) -> ctk.CTkLabel | None:
    """Sidebar header: a rounded strip of the course photo with the app
    title overlaid. Returns None when the photo is missing so the caller
    can simply skip it. `scale` is the app's display-scale factor: the CTk
    sidebar width tracks it, and this raw PIL image would otherwise not, so
    the banner is sized up/down to stay flush with the sidebar."""
    if not image_path:
        return None
    try:
        src = Image.open(image_path)
    except Exception:
        return None
    # CTkImage multiplies its display `size` by the widget scaling itself, so
    # size stays unscaled here; the *source* PIL is rendered at the scaled
    # resolution so it stays sharp (not upscaled) on a hi-DPI / scaled display.
    disp_size = (316, 84)
    src_size = (round(316 * scale), round(84 * scale))
    img = _rounded_cover(src, src_size, radius=round(10 * scale),
                         dim_toward=Colors.BG_SIDEBAR, dim=0.45)
    banner = ctk.CTkImage(light_image=img, dark_image=img, size=disp_size)
    label = ctk.CTkLabel(
        master, image=banner, text=title, compound="center",
        font=theme.font("subheading", "bold"),
        text_color=Colors.TEXT_ACTIVE, fg_color="transparent",
    )
    label._banner_image = banner  # keep a strong ref alongside the widget
    return label


def build_home_page(parent, stats: HomeStats, image_path,
                    empty_hint: str = "", trends: HomeTrends | None = None,
                    records: PlayerRecords | None = None,
                    scale: float = 1.0) -> ctk.CTkFrame:
    """The landing page. `empty_hint` is shown instead of the stats when
    there's no data yet.

    This is drawn on a raw tk.Canvas, which (unlike CTk widgets) doesn't
    inherit the app's display scaling — so every font size and fixed pixel
    metric here is multiplied by `scale` (via sc()) to keep the landing page
    sized in step with the rest of the app on a projector or hi-DPI panel.
    Positions derived from the live canvas w/h are already in real pixels and
    are left proportional.
    """
    frame = ctk.CTkFrame(parent, fg_color=Colors.BG_BASE, corner_radius=0)
    canvas = tk.Canvas(frame, highlightthickness=0, bg=Colors.BG_BASE)
    canvas.pack(fill=tk.BOTH, expand=True)
    trends = trends or HomeTrends()
    records = records or PlayerRecords()

    def sc(v) -> int:
        """Scale a fixed pixel/point metric by the display factor."""
        return max(1, int(round(v * scale)))

    try:
        src = Image.open(image_path) if image_path else None
    except Exception:
        src = None

    state = {"job": None, "size": (0, 0), "photos": []}

    def _font(scale_name: str, weight: str | None = None):
        spec = (FONT_FAMILY, sc(FONT_SCALE[scale_name]))
        return spec + (weight,) if weight else spec

    def _card(blurred, box, title, title_color):
        """Frosted card with a bold title; content is drawn by the caller."""
        photo = _frosted(blurred, box, radius=sc(14))
        state["photos"].append(photo)
        canvas.create_image(box[0], box[1], image=photo, anchor="nw")
        if title:
            canvas.create_text(box[0] + sc(18), box[1] + sc(24), text=title, anchor="w",
                               font=_font("label", "bold"), fill=title_color)

    def _tile(blurred, box, label, value, value_color=Colors.TEXT_ACTIVE):
        _card(blurred, box, None, None)
        x = box[0] + sc(18)
        canvas.create_text(x, box[1] + sc(24), text=label, anchor="w",
                           font=_font("caption"), fill=Colors.TEXT_MUTED)
        # Shrink the value to fit the tile so long records ("183.3 MPH") don't
        # overflow into the next tile.
        inner = (box[2] - box[0]) - sc(34)
        size = sc(FONT_SCALE["heading"])
        floor = sc(FONT_SCALE["body"])
        while size > floor and tkfont.Font(
                family=FONT_FAMILY, size=size, weight="bold").measure(value) > inner:
            size -= 1
        canvas.create_text(x, box[3] - sc(30), text=value, anchor="w",
                           font=(FONT_FAMILY, size, "bold"), fill=value_color)

    def _sparkline(x, y, w, h, values, color):
        vmin, vmax = min(values), max(values)
        span = (vmax - vmin) or 1.0
        pts = []
        for i, v in enumerate(values):
            pts.append(x + w * i / (len(values) - 1))
            pts.append(y + h - h * (v - vmin) / span)
        canvas.create_line(*pts, fill=color, width=sc(2), smooth=True)

    def _shot_quality_panel(blurred, box):
        """Full-width panel: the current average Shot Quality score on the left,
        its per-session trend line (last 10 sessions) on the right."""
        x0, y0, x1, y1 = box
        _card(blurred, box, "Shot quality", Colors.SUCCESS)
        q = stats.avg_shot_quality
        q_color = _quality_color(q)
        cx = x0 + sc(26)
        cyc = (y0 + y1) / 2 + sc(10)
        q_text = "---" if q is None else str(q)
        big_size = sc(FONT_SCALE["display"])
        canvas.create_text(cx, cyc, text=q_text, anchor="w",
                           font=(FONT_FAMILY, big_size, "bold"), fill=q_color)
        big = tkfont.Font(family=FONT_FAMILY, size=big_size, weight="bold")
        canvas.create_text(cx + big.measure(q_text) + sc(8), cyc + sc(8), text="/ 100",
                           anchor="w", font=_font("body"), fill=Colors.TEXT_MUTED)
        canvas.create_text(cx, y1 - sc(24), text="Average score", anchor="w",
                           font=_font("caption"), fill=Colors.TEXT_MUTED)

        series = trends.shot_quality_series
        sx0 = x0 + int((x1 - x0) * 0.34)
        sx1, sy0, sy1 = x1 - sc(30), y0 + sc(56), y1 - sc(44)
        if len(series) >= 2:
            _sparkline(sx0, sy0, sx1 - sx0, sy1 - sy0, series, q_color)
            vmin, vmax = min(series), max(series)
            span = (vmax - vmin) or 1.0
            ly = sy0 + (sy1 - sy0) - (sy1 - sy0) * (series[-1] - vmin) / span
            r = sc(4)
            canvas.create_oval(sx1 - r, ly - r, sx1 + r, ly + r, fill=q_color, outline="")
            canvas.create_text(sx1, ly - sc(12), text=f"{series[-1]:.0f}", anchor="s",
                               font=_font("caption", "bold"), fill=Colors.TEXT_PRIMARY)
            canvas.create_text(sx0, sy1 + sc(16), text=f"{len(series)} sessions ago",
                               anchor="w", font=_font("caption"), fill=Colors.TEXT_MUTED)
            canvas.create_text(sx1, sy1 + sc(16), text="latest", anchor="e",
                               font=_font("caption"), fill=Colors.TEXT_MUTED)
        else:
            canvas.create_text((sx0 + sx1) / 2, (sy0 + sy1) / 2,
                               text="Not enough sessions for a trend yet",
                               font=_font("body"), fill=Colors.TEXT_MUTED)

    def _handicap_panel(blurred, box):
        """The Sim Handicap: the number, whether it's verified, and — when
        there isn't one yet — how many more clean rounds it needs.

        The caveat is printed rather than tucked into a hover tooltip. This is
        a number people will quote to other golfers, and "it's not a USGA
        index" has to travel with it, which it can't do from behind a hover.
        """
        x0, y0, x1, y1 = box
        h_data = records.handicap
        _card(blurred, box, "Sim handicap", Colors.ACCENT)
        cx = x0 + sc(22)
        value = h_data.label
        verified = h_data.verified
        color = Colors.SUCCESS if verified else Colors.TEXT_MUTED

        # Laid out bottom-up from their own measured heights, because the
        # status line still wraps in a card this narrow (a still-building
        # handicap that also lost rounds to mulligans runs to three lines).
        # The fixed offsets this replaces assumed one line each, so the moment
        # either wrapped they drew straight through each other and the last
        # line fell out of the bottom of the card.
        wrap = (x1 - x0) - sc(40)

        def _top_of(item, fallback):
            bb = canvas.bbox(item)
            return bb[1] if bb else fallback

        disclaimer = canvas.create_text(
            cx, y1 - sc(18), text="Not a USGA index",
            anchor="sw", font=_font("caption"), fill=Colors.TEXT_MUTED, width=wrap)
        status = canvas.create_text(
            cx, _top_of(disclaimer, y1 - sc(18)) - sc(8), text=h_data.status,
            anchor="sw", font=_font("caption"), fill=Colors.TEXT_MUTED, width=wrap)

        # The number gets whatever the title and the captions left, and is
        # sized to fit it in BOTH directions. Width alone was the old test,
        # which is why nothing caught this: "---" and "12.4" are narrow at any
        # size, so the loop never ran and a 48pt number simply overlapped
        # whatever was beneath it.
        top = y0 + sc(46)  # clear of the card title
        band_bottom = _top_of(status, y1 - sc(60)) - sc(10)
        band = max(sc(20), band_bottom - top)
        inner = (x1 - x0) - sc(90)

        # Starts at the hero size and comes down to whatever actually fits.
        # That single rule also settles the empty state: "---" is never too
        # wide, so on the old width-only test it stayed at 48pt and rendered
        # as three heavy bars dominating the card — but it's just as tall as
        # any number, so fitting the height brings it back down with
        # everything else. No special case for it.
        size = sc(FONT_SCALE["display"])
        floor = sc(FONT_SCALE["body"])
        while size > floor:
            probe = tkfont.Font(family=FONT_FAMILY, size=size, weight="bold")
            if probe.measure(value) <= inner and probe.metrics("linespace") <= band:
                break
            size -= 1

        # Centred in the band when there's room, but never lower than sitting
        # directly on top of it. The clamp is what holds when there ISN'T room:
        # a still-building handicap that also lost rounds to mulligans has a
        # three-line status, and at 150% scale that plus the caveat fills the
        # card outright. The number then gets whatever is left rather than
        # being centred into the text below it.
        line = tkfont.Font(family=FONT_FAMILY, size=size, weight="bold").metrics("linespace")
        cy = min((top + band_bottom) / 2, band_bottom - line / 2)
        cy = max(cy, top + line / 2)  # ...and never up into the card's title
        canvas.create_text(cx, cy, text=value, anchor="w",
                           font=(FONT_FAMILY, size, "bold"), fill=color)

        if verified:
            big = tkfont.Font(family=FONT_FAMILY, size=size, weight="bold")
            canvas.create_text(cx + big.measure(value) + sc(10), cy + sc(6),
                               text="✓ Verified", anchor="w",
                               font=_font("caption", "bold"), fill=Colors.SUCCESS)

    def _redraw(w, h):
        canvas.delete("all")
        state["photos"] = []

        if src is not None:
            bg = src.resize((w, h), Image.Resampling.LANCZOS)
            bg = ImageEnhance.Brightness(bg).enhance(_BG_DIM)
            bg_photo = ImageTk.PhotoImage(bg)
            state["photos"].append(bg_photo)
            canvas.create_image(0, 0, image=bg_photo, anchor="nw")
            blurred = bg.filter(ImageFilter.GaussianBlur(_BLUR_RADIUS))
        else:
            blurred = Image.new("RGB", (w, h), _hex_rgb(Colors.BG_BASE))

        content_w = min(w - sc(64), sc(1320))
        x0 = (w - content_w) // 2
        gap = sc(SPACING["lg"])   # was a bare 14 — off the spacing scale

        canvas.create_text(
            w / 2, h * 0.13, text="Master your game", justify="center",
            # "display" rather than a bare 46: this and the big Shot Quality
            # score are the app's only hero-sized type, and they were two
            # unrelated magic numbers (46 and 50) that happened to look similar.
            font=(FONT_FAMILY + " Light", sc(FONT_SCALE["display"]), "italic"),
            fill=Colors.TEXT_ACTIVE,
        )

        if stats.total_shots == 0:
            y = int(h * 0.30)
            box = (x0, y, x0 + content_w, y + sc(130))
            _card(blurred, box, None, None)
            canvas.create_text(w / 2, y + sc(50), text="No shot data yet",
                               font=_font("subheading", "bold"), fill=Colors.TEXT_PRIMARY)
            if empty_hint:
                canvas.create_text(w / 2, y + sc(86), text=empty_hint,
                                   font=_font("body"), fill=Colors.TEXT_MUTED,
                                   width=content_w - sc(40), justify="center")
            return

        # Vertically center the whole block in the space below the hero.
        tile_h, rec_h, sq_h = sc(100), sc(100), sc(176)
        total_h = tile_h + rec_h + sq_h + 2 * gap
        y = max(int(h * 0.22), int(h * 0.18 + (h * 0.82 - total_h) / 2))

        # Row 1 — recency/summary tiles.
        tile_w = (content_w - 3 * gap) / 4
        days = stats.days_since_last
        last_val = "---" if days is None else ("Today" if days == 0 else f"{days}d ago")
        summary = [
            ("Shots logged", f"{stats.total_shots:,}", Colors.TEXT_ACTIVE),
            ("Sessions", f"{stats.session_count}", Colors.TEXT_ACTIVE),
            ("Last session", last_val, Colors.TEXT_ACTIVE),
            ("Shots this week", f"{stats.shots_this_week}",
             Colors.SUCCESS if stats.shots_this_week else Colors.TEXT_ACTIVE),
        ]
        for i, (label, value, color) in enumerate(summary):
            tx = int(x0 + i * (tile_w + gap))
            _tile(blurred, (tx, y, int(tx + tile_w), y + tile_h), label, value, color)
        y += tile_h + gap

        # Row 2 — Player Records (moved here from the sidebar).
        #
        # Four tiles, matching row 1, so both rows sit on the same four-column
        # grid instead of a 4-over-5 split whose internal edges never lined up.
        #
        # The handicap deliberately isn't a fifth tile here. It now has a real
        # number behind it (data.analytics.handicap), but it also needs a
        # verified badge, a progress line while it's still building, and a
        # standing caveat that it is not a USGA index — none of which fit in a
        # tile this size. It shares row 3 with Shot Quality instead.
        rec_w = (content_w - 3 * gap) / 4
        record_tiles = [
            ("Longest drive", records.longest_drive, Colors.SUCCESS),
            ("Max club speed", records.max_club_speed, Colors.DANGER),
            ("Max ball speed", records.max_ball_speed, Colors.ACCENT),
            ("Theoretical max", records.theoretical_max_drive, Colors.WARNING),
        ]
        for i, (label, value, color) in enumerate(record_tiles):
            tx = int(x0 + i * (rec_w + gap))
            _tile(blurred, (tx, y, int(tx + rec_w), y + rec_h), label, value, color)
        y += rec_h + gap

        # Row 3 — Shot Quality score + trend line, alongside the Sim Handicap.
        # The split is uneven on purpose: the quality panel carries a sparkline
        # that needs the width, the handicap panel carries three short lines.
        sq_w = int((content_w - gap) * 0.66)
        _shot_quality_panel(blurred, (x0, y, x0 + sq_w, y + sq_h))
        _handicap_panel(blurred, (x0 + sq_w + gap, y, x0 + content_w, y + sq_h))

    def _on_configure(event):
        if event.width < 60 or event.height < 60:
            return
        if state["job"] is not None:
            canvas.after_cancel(state["job"])
        size = (event.width, event.height)

        def _go():
            state["job"] = None
            if size != state["size"]:
                state["size"] = size
                _redraw(*size)

        state["job"] = canvas.after(90, _go)

    canvas.bind("<Configure>", _on_configure)
    return frame
