"""Small helpers shared by more than one chart renderer."""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

from config import Colors, REFERENCE_PROFILE_COLORS, REFERENCE_PROFILES, get_fitting_window
from data.columns import (
    BALL_SPEED_ALIASES, CLUB_SPEED_ALIASES, DESCENT_ANGLE_ALIASES, LAUNCH_ANGLE_ALIASES,
    SMASH_FACTOR_ALIASES, SPIN_RATE_ALIASES, find_col,
)


def get_timeline_colormap(df: pd.DataFrame):
    """Normalize session_date into a 0..1 range plus a colormap, so shots
    can be tinted oldest -> newest. Mutates df in place by adding
    'date_numeric', matching the original behavior callers rely on.
    """
    df["date_numeric"] = pd.to_numeric(pd.to_datetime(df["session_date"]))
    vmin, vmax = df["date_numeric"].min(), df["date_numeric"].max()
    if vmin == vmax:
        vmin -= 1
        vmax += 1
    return plt.Normalize(vmin, vmax), plt.get_cmap("plasma", 15)


def _dismiss_cursor_on_click(fig, cursor):
    """Let a click anywhere on the chart clear the current hover tooltip.

    mplcursors hover annotations normally vanish once the pointer moves off
    the point, but can get 'stuck' when the mouse leaves the canvas without a
    final motion event — a click then clears them (clicking *off* the point
    means it won't immediately re-appear). One cid is kept per figure so
    re-renders don't stack handlers.
    """
    old_cid = getattr(fig, "_tooltip_click_cid", None)
    if old_cid is not None:
        try:
            fig.canvas.mpl_disconnect(old_cid)
        except Exception:
            pass
        fig._tooltip_click_cid = None
    if cursor is None:
        return

    def _clear(_event):
        for sel in list(getattr(cursor, "selections", ()) or ()):
            try:
                cursor.remove_selection(sel)
            except Exception:
                pass

    fig._tooltip_click_cid = fig.canvas.mpl_connect("button_press_event", _clear)


def attach_hover_tooltip(fig, artist, rows, format_row, font_scale):
    """Attach an mplcursors hover tooltip to a scatter `artist`.

    Each hovered point is mapped back to its source row by *positional*
    index (``rows.iloc[sel.index]``), so the caller must pass the exact
    DataFrame — in the same row order — that produced `artist`'s points.
    `format_row(row)` returns the tooltip text.

    We keep at most one live cursor per Figure: the app reuses each panel's
    Figure across re-renders (see app_window.update_single_plot, which only
    fig.clf()s), so without removing the previous cursor its motion-notify
    callback would linger on the shared canvas and stack up on every redraw.
    The cursor is stashed on the Figure so it stays referenced (an
    unreferenced mplcursors Cursor can be garbage-collected mid-session).
    """
    import mplcursors

    old = getattr(fig, "_hover_cursor", None)
    if old is not None:
        try:
            old.remove()
        except Exception:
            pass
        fig._hover_cursor = None

    if artist is None or rows is None or len(rows) == 0:
        _dismiss_cursor_on_click(fig, None)  # clear any stale click handler
        return None

    cursor = mplcursors.cursor(artist, hover=True)

    @cursor.connect("add")
    def _on_add(sel):
        try:
            row = rows.iloc[int(sel.index)]
        except (IndexError, TypeError, ValueError):
            return
        ann = sel.annotation
        ann.set_text(format_row(row))
        ann.set_fontsize(max(8, font_scale - 2))
        ann.set_color(Colors.TEXT_PRIMARY)
        bbox = ann.get_bbox_patch()
        if bbox is not None:
            bbox.set(facecolor=Colors.BG_SURFACE, edgecolor=Colors.BORDER, alpha=0.96)
        if getattr(ann, "arrow_patch", None) is not None:
            ann.arrow_patch.set(color=Colors.BORDER)

    fig._hover_cursor = cursor
    _dismiss_cursor_on_click(fig, cursor)
    return cursor


def attach_label_tooltip(fig, artists, text, font_scale):
    """Show a fixed explanatory `text` on hover over `artists` (a single artist
    or list — e.g. a stat tile's label + big number). Unlike attach_hover_tooltip
    (per-point, data-driven), this is one static message. Shares and manages the
    figure's single `_hover_cursor` slot the same way, so it's cleaned up on
    re-render/destroy."""
    import mplcursors

    old = getattr(fig, "_hover_cursor", None)
    if old is not None:
        try:
            old.remove()
        except Exception:
            pass
        fig._hover_cursor = None

    if not artists:
        _dismiss_cursor_on_click(fig, None)  # clear any stale click handler
        return None
    cursor = mplcursors.cursor(artists, hover=True)

    @cursor.connect("add")
    def _on_add(sel):
        ann = sel.annotation
        ann.set_text(text)
        ann.set_fontsize(max(8, font_scale - 2))
        ann.set_color(Colors.TEXT_PRIMARY)
        bbox = ann.get_bbox_patch()
        if bbox is not None:
            bbox.set(facecolor=Colors.BG_SURFACE, edgecolor=Colors.BORDER, alpha=0.96)
        if getattr(ann, "arrow_patch", None) is not None:
            ann.arrow_patch.set(color=Colors.BORDER)

    fig._hover_cursor = cursor
    _dismiss_cursor_on_click(fig, cursor)
    return cursor


def style_axes(ax, font_scale, grid="both"):
    """App-wide axes chrome: no top/right spines, muted ticks, dotted grid."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(Colors.BORDER)
    ax.tick_params(labelsize=font_scale - 1, colors=Colors.TEXT_MUTED)
    if grid:
        ax.grid(True, axis=grid, linestyle=":", linewidth=0.8, alpha=0.35, zorder=0)
    else:
        ax.grid(False)


_STAR_AREA = 190 / 4  # default scatter `s` (marker area in points^2)


def _reference_star(ax, points, color, label, zorder=6, size=_STAR_AREA):
    """Draw a star marker in `color` at each (x, y) and return a matching
    legend handle (or None if there are no points). `size` is scatter area
    (points^2); the legend marker uses its square root so diameters match."""
    if not points:
        return None
    xs, ys = zip(*points)
    ax.scatter(xs, ys, marker="*", s=size, color=color,
               edgecolor="black", linewidths=0.8, zorder=zorder)
    return Line2D(
        [0], [0], marker="*", linestyle="None", markersize=size ** 0.5,
        markerfacecolor=color, markeredgecolor="black", markeredgewidth=0.8,
        label=label,
    )


def plot_benchmarks(ax, benchmarks, point_fn, zorder=6, size=_STAR_AREA):
    """Overlay each selected reference profile as colored stars.

    `benchmarks` is the list of profile names chosen in this chart's own
    benchmark selector; `point_fn(profile_name)` returns the [(x, y), ...]
    this chart wants to mark for that profile (empty if the profile has no
    data for this chart's metric). Returns a list of legend handles, one per
    profile that actually plotted something, so the caller can fold them into
    whatever legend it already builds.
    """
    handles = []
    for name in benchmarks:
        if name not in REFERENCE_PROFILES:
            continue
        handle = _reference_star(
            ax, point_fn(name), REFERENCE_PROFILE_COLORS.get(name, "#FFD700"), name,
            zorder=zorder, size=size,
        )
        if handle:
            handles.append(handle)
    return handles


def carry_points(profile_name, order, x_of_index=lambda i, c: i):
    """Convenience point_fn builder for carry-vs-club charts: yields
    (x, carry) for each club in `order` that this profile has a carry for.
    `x_of_index(index, club)` maps a club's ordinal position to its x."""
    prof = REFERENCE_PROFILES.get(profile_name, {})
    pts = []
    for i, club in enumerate(order):
        m = prof.get(club)
        if m is not None and m.carry is not None:
            pts.append((x_of_index(i, club), m.carry))
    return pts


def club_legend(ax, club_colors, order, font_scale, loc="upper left", extra_handles=None):
    """Compact swatch legend mapping club -> color, consistent everywhere.
    extra_handles lets a caller (e.g. a tour-average marker) share this same
    legend box instead of fighting it for space with a second one — ax.legend()
    replaces any prior unstyled legend, so two independent calls would clobber
    each other unless the first is anchored via ax.add_artist().
    """
    handles = [
        Line2D([0], [0], marker="o", linestyle="None", markersize=6,
               markerfacecolor=club_colors[c], markeredgecolor="none", label=str(c))
        for c in order if c in club_colors
    ]
    if extra_handles:
        handles.extend(extra_handles)
    if not handles:
        return None
    leg = ax.legend(
        handles=handles, loc=loc, ncol=2 if len(handles) > 7 else 1,
        fontsize=max(10, font_scale - 2), facecolor=Colors.BG_SURFACE,
        edgecolor=Colors.BORDER, framealpha=0.85, labelcolor=Colors.TEXT_PRIMARY,
        borderpad=0.6, handletextpad=0.3, columnspacing=0.8,
    )
    leg.set_zorder(20)
    return leg


def styled_colorbar(fig, mappable, ax, label, font_scale):
    cbar = fig.colorbar(mappable, ax=ax, fraction=0.046, pad=0.03)
    cbar.set_label(label, fontsize=font_scale - 1, labelpad=10, color=Colors.TEXT_MUTED)
    cbar.ax.tick_params(labelsize=font_scale - 2, colors=Colors.TEXT_MUTED)
    cbar.outline.set_visible(False)
    return cbar


# Launch & Spin 2D color square (see ui/charts/launch_spin.py). Each shot is
# colored by its position relative to the club's ideal launch/spin: green at
# the ideal (center) stepping out to four corner colors — spin low→high maps
# left→right, launch low→high maps bottom→top. The field is quantized into
# SQUARE_LEVELS discrete blocks per axis so both the shots and the legend key
# read as clear color blocks rather than a continuous gradient.
GREEN_TARGET = Colors.SUCCESS
_SQUARE_CORNERS = {
    "bl": Colors.WARNING,  # low spin,  low launch  -> orange
    "br": Colors.DANGER,   # high spin, low launch  -> red
    "tl": Colors.INFO,     # low spin,  high launch -> blue
    "tr": "#9B59B6",       # high spin, high launch -> purple (square-only)
}
# How many tolerances out (in launch/spin) map to a fully-saturated corner.
SQUARE_SCALE_TOLS = 3.0
# Number of discrete color blocks along each axis of the square. Odd, so a
# single block sits dead-center on the optimal and renders pure green.
SQUARE_LEVELS = 11


def _square_field(sx, sy, center=GREEN_TARGET, corners=_SQUARE_CORNERS):
    """RGB for normalized offsets sx, sy each in [-1, 1]: `center` color at the
    middle (0, 0), bilinearly blending to the four `corners`, with the center
    weighting falling off by radial distance. Works elementwise, so it serves
    both per-shot points and the legend grid."""
    from matplotlib.colors import to_rgb

    sx = np.asarray(sx, float)
    sy = np.asarray(sy, float)
    u = ((sx + 1) / 2)[..., None]
    v = ((sy + 1) / 2)[..., None]
    bl = np.array(to_rgb(corners["bl"]))
    br = np.array(to_rgb(corners["br"]))
    tl = np.array(to_rgb(corners["tl"]))
    tr = np.array(to_rgb(corners["tr"]))
    corner = (1 - u) * (1 - v) * bl + u * (1 - v) * br + (1 - u) * v * tl + u * v * tr
    t = np.clip(np.hypot(sx, sy), 0, 1)[..., None]
    return np.array(to_rgb(center)) * (1 - t) + corner * t


def _quantize_unit(v, levels=SQUARE_LEVELS):
    """Snap value(s) in [-1, 1] to the center of one of `levels` equal-width
    bins, so continuous offsets collapse onto discrete color blocks."""
    v = np.clip(np.asarray(v, float), -1, 1)
    idx = np.clip(((v + 1) / 2 * levels).astype(int), 0, levels - 1)
    return (idx + 0.5) / levels * 2 - 1


def square_point_colors(vla, spin, ideal_launch, ideal_spin, launch_scale, spin_scale,
                        center=GREEN_TARGET, corners=_SQUARE_CORNERS):
    """RGBA per shot from the 2D color square — `center` color on the ideal,
    stepping toward a corner color (in discrete SQUARE_LEVELS blocks) as the two
    metrics drift from ideal."""
    sx = _quantize_unit((np.asarray(spin, float) - ideal_spin) / spin_scale)
    sy = _quantize_unit((np.asarray(vla, float) - ideal_launch) / launch_scale)
    out = np.ones((len(sx), 4))
    out[:, :3] = _square_field(sx, sy, center, corners)
    return out


def draw_color_square(ax, font_scale, x_label="Spin →", y_label="Launch →",
                      title="Green = ideal", center=GREEN_TARGET, corners=_SQUARE_CORNERS):
    """Legend key for square_point_colors(): the quantized 2D color field drawn
    as a small SQUARE_LEVELS×SQUARE_LEVELS block grid inset in the plot's
    upper-right corner (center color = ideal)."""
    cax = ax.inset_axes([0.80, 0.70, 0.18, 0.27])
    centers = (np.arange(SQUARE_LEVELS) + 0.5) / SQUARE_LEVELS * 2 - 1
    sx, sy = np.meshgrid(centers, centers)
    cax.imshow(_square_field(sx, sy, center, corners), origin="lower", extent=(-1, 1, -1, 1),
               aspect="auto", interpolation="nearest", zorder=0)
    cax.plot(0, 0, marker="o", markersize=4, markerfacecolor="none",
             markeredgecolor="white", markeredgewidth=1.2, zorder=2)
    cax.set_xticks([])
    cax.set_yticks([])
    cax.set_xlabel(x_label, fontsize=max(10, font_scale - 3), color=Colors.TEXT_MUTED, labelpad=2)
    cax.set_ylabel(y_label, fontsize=max(10, font_scale - 3), color=Colors.TEXT_MUTED, labelpad=2)
    cax.set_title(title, fontsize=max(10, font_scale - 3), color=Colors.TEXT_MUTED, pad=3)
    for spine in cax.spines.values():
        spine.set_color(Colors.BORDER)


# ---------------------------------------------------------------------------
# Per-shot diagnostic tooltip lines — launch/descent/spin/smash, each read
# against that club's fitting window so a hovered shot tells you not just
# "what happened" but "was that good or bad" (see config.get_fitting_window).
# Used by Dispersion and Live Dispersion's hover tooltips.
# ---------------------------------------------------------------------------
def diagnostic_cols(df: pd.DataFrame) -> dict:
    """Resolve the column names a diagnostic tooltip needs, once per render
    (not once per hovered row)."""
    return {
        "vla": find_col(df, LAUNCH_ANGLE_ALIASES),
        "desc": find_col(df, DESCENT_ANGLE_ALIASES),
        "spin": find_col(df, SPIN_RATE_ALIASES),
        "smash": find_col(df, SMASH_FACTOR_ALIASES),
        "cs": find_col(df, CLUB_SPEED_ALIASES),
        "bs": find_col(df, BALL_SPEED_ALIASES),
    }


def _range_flag(value: float, window) -> str:
    """'' inside the club's ideal window, else a short over/under marker."""
    if window is None or value is None:
        return ""
    lo, hi = window
    if lo <= value <= hi:
        return ""
    return " ↓ low" if value < lo else " ↑ high"


def diagnostic_lines(row, cols: dict, club=None) -> list[str]:
    """Extra hover-tooltip lines for one shot: launch angle and descent angle
    (each flagged against that club's optimal window), spin rate, and smash
    factor (its own column if present, else derived from ball/club speed).
    A metric simply doesn't appear when the shot/source data doesn't have
    it — nothing here is guessed.
    """
    lines: list[str] = []
    window = get_fitting_window(club) if club else None  # (launch, height, descent)

    vla_col = cols.get("vla")
    if vla_col and pd.notna(row.get(vla_col)):
        v = float(row[vla_col])
        rng = window[0] if window else None
        lines.append(f"Launch: {v:.1f}°{_range_flag(v, rng)}")

    desc_col = cols.get("desc")
    if desc_col and pd.notna(row.get(desc_col)):
        v = float(row[desc_col])
        rng = window[2] if window else None
        lines.append(f"Descent: {v:.1f}°{_range_flag(v, rng)}")

    spin_col = cols.get("spin")
    if spin_col and pd.notna(row.get(spin_col)):
        lines.append(f"Spin: {float(row[spin_col]):.0f} rpm")

    smash = None
    smash_col = cols.get("smash")
    if smash_col and pd.notna(row.get(smash_col)):
        smash = float(row[smash_col])
    else:
        cs_col, bs_col = cols.get("cs"), cols.get("bs")
        if cs_col and bs_col and pd.notna(row.get(cs_col)) and pd.notna(row.get(bs_col)):
            cs = float(row[cs_col])
            if cs > 0:
                smash = float(row[bs_col]) / cs
    if smash is not None and 0.5 < smash < 2.0:  # outside this window is a sensor glitch, not golf
        lines.append(f"Smash: {smash:.2f}")

    return lines
