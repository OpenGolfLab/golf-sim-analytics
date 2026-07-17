"""Community — the community's median shots, plotted like your own data.

Each point is ONE golfer's MEDIAN for a club (fetched by
community.fetch_community_shots as aggregate points — never raw shots — and
handed in as ``df``), shown on the same offline-vs-carry axes the personal
Dispersion chart uses, colored by club, next to a per-club table. So a dot reads
as "where this golfer's typical 7I lands", and the cloud is the spread of golfers
rather than the spread of one person's shots — the correct community unit (see
opengolflab-data/AGGREGATION.md §0). Club is both the color tag and the filter
(the global Club Filter narrows what's plotted, same as every dashboard).

The data source and fetch live outside the chart: the app passes an empty frame
plus a ``community_status`` hint ("offline" / "loading" / "empty" / "ok") so this
renders the right message when there's nothing to draw.
"""
from __future__ import annotations

import pandas as pd
from matplotlib.colors import to_rgba

from config import Colors, get_club_color, get_club_rank
from data import units as units_mod
from data.columns import (
    BALL_SPEED_ALIASES, CARRY_ALIASES, OFFLINE_ALIASES, find_col,
)
from ui.charts._shared import attach_hover_tooltip, club_legend, style_axes
from ui.empty_state import show_message


def _clean(value) -> str:
    """A descriptive metadata value as a display string, or "" when it's absent
    in any of its spellings (None, NaN, the literal 'nan'/'none'). Lets the
    tooltip test presence with a plain truthiness check."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    return "" if s.lower() in ("nan", "none", "null") else s

NAME = "Community"
CATEGORY = "Community"
COLUMN = "left"
HAS_COLOR = False
WIDE = True
DESCRIPTION = ("Anonymized shots shared by the OpenGolfLab community — dispersion "
               "and per-club averages, filterable by club.")

_STATUS_MESSAGES = {
    "offline": ("Community data isn't set up in this build",
                "Set OPENGOLFLAB_COMMUNITY_URL once the read API is deployed "
                "(see docs/COMMUNITY_API.md)."),
    "loading": ("Loading community shots…", "Fetching the latest shared shots."),
    "empty": ("No community shots yet", "Be the first to share a round from the "
              "Contribute panel."),
}


def render(fig, df, club_colors, font_scale, config, **extra):
    status = extra.get("community_status", "ok")
    if df is None or df.empty or status != "ok":
        title, hint = _STATUS_MESSAGES.get(
            status if status in _STATUS_MESSAGES else "empty",
            _STATUS_MESSAGES["empty"])
        show_message(fig, title, font_scale, hint=hint)
        return

    unit = extra.get("units", units_mod.YARDS)
    df = units_mod.to_display_frame(df, unit)
    u = units_mod.dist_suffix_lower(unit)

    offline_col = find_col(df, OFFLINE_ALIASES)
    carry_col = find_col(df, CARRY_ALIASES)
    bs_col = find_col(df, BALL_SPEED_ALIASES)
    if not (offline_col and carry_col and "club" in df.columns):
        show_message(fig, "Community data is missing carry/offline", font_scale, tone="error")
        return

    gs = fig.add_gridspec(1, 2, width_ratios=[1.5, 1.0], wspace=0.28)
    ax = fig.add_subplot(gs[0, 0])
    ax_t = fig.add_subplot(gs[0, 1])
    ax_t.set_axis_off()

    order = sorted(df["club"].dropna().unique(), key=get_club_rank)
    for c in order:
        club_colors.setdefault(c, get_club_color(c))

    ax.axvline(x=0, color=Colors.TEXT_MUTED, linestyle="--", linewidth=1.3, alpha=0.6, zorder=0.5)
    pts = df[df[offline_col].notna() & df[carry_col].notna() & df["club"].notna()].reset_index(drop=True)
    sc = ax.scatter(
        pts[offline_col], pts[carry_col],
        c=[to_rgba(club_colors.get(c, Colors.CLUB_FALLBACK)) for c in pts["club"]],
        s=32, alpha=0.85, edgecolor="black", linewidth=0.4, zorder=1,
    )

    def _tooltip(row):
        # A per-GOLFER card: each dot is one contributor's median for the club,
        # not a single shot. Every line past the first is conditional — a point
        # may or may not carry ball model, monitor, or a contributed date (see
        # docs/COMMUNITY_API.md) — so each shows only when present, degrading to
        # club + median carry rather than printing "None".
        club = str(row["club"])
        who = _clean(row.get("display_name"))
        head = f"{club}  ·  {who}" if who else club
        lines = [head, f"Median carry: {row[carry_col]:.0f} {u}"]
        lines.append(f"Median offline: {row[offline_col]:+.1f} {u}")
        if bs_col and pd.notna(row.get(bs_col)):
            lines.append(f"Ball speed: {row[bs_col]:.0f} mph")

        n = row.get("n")
        if pd.notna(n):
            lines.append(f"From {int(n)} shots")
        ball = _clean(row.get("ball_model"))
        device = _clean(row.get("launch_monitor"))
        when = _clean(row.get("contributed"))
        if ball:
            lines.append(f"Ball: {ball}")
        if device:
            lines.append(f"Monitor: {device}")
        if when:
            lines.append(f"Contributed: {str(when)[:10]}")
        return "\n".join(lines)

    attach_hover_tooltip(fig, sc, pts, _tooltip, font_scale)
    club_legend(ax, club_colors, order, font_scale, loc="lower left")

    ax.set_xlabel(f"Offline ({units_mod.dist_suffix(unit)})", fontsize=font_scale)
    ax.set_ylabel(f"Carry ({units_mod.dist_suffix(unit)})", fontsize=font_scale)
    style_axes(ax, font_scale)

    _draw_metrics(ax_t, df, order, club_colors, font_scale, carry_col, bs_col, u,
                  extra.get("community_as_of"))


def _draw_metrics(ax, df, order, club_colors, font_scale, carry_col, bs_col, u, as_of):
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Each row of df is one golfer's per-club median, with `n` shots behind it —
    # so "how many shots" is the sum of n, and "how many golfers hit this club"
    # is the number of rows, not len(df).
    n_all = pd.to_numeric(df["n"], errors="coerce") if "n" in df.columns else None
    total_shots = int(n_all.fillna(0).sum()) if n_all is not None else 0

    header = "Community medians"
    if total_shots:
        header += f"  ·  {total_shots:,} shots"
    if as_of:
        header += f"  ·  as of {str(as_of)[:10]}"
    ax.text(0, 1.0, header, fontsize=max(9, font_scale - 2),
            color=Colors.TEXT_MUTED, va="top", ha="left")
    ax.text(0, 0.955, "each dot is one golfer's median", fontsize=max(8, font_scale - 4),
            color=Colors.TEXT_MUTED, va="top", ha="left")

    rows = []
    for c in order:
        cd = df[df["club"] == c]
        if cd.empty:
            continue
        carry = cd[carry_col].mean()   # average of the golfers' medians
        golfers = len(cd)
        shots = int(pd.to_numeric(cd["n"], errors="coerce").fillna(0).sum()) \
            if "n" in cd.columns else 0
        rows.append((c, golfers, shots, carry))

    y = 0.86
    dy = min(0.075, 0.82 / max(1, len(rows)))
    for club, golfers, shots, carry in rows:
        color = club_colors.get(club, Colors.CLUB_FALLBACK)
        ax.text(0.0, y, club, fontsize=max(9, font_scale - 2), color=color,
                fontweight="bold", va="center")
        stat = f"{carry:.0f} {u} · {golfers} golfer{'s' if golfers != 1 else ''}"
        if shots:
            stat += f" · {shots} shots"
        ax.text(0.20, y, stat, fontsize=max(8, font_scale - 3),
                color=Colors.TEXT_PRIMARY, va="center")
        y -= dy
