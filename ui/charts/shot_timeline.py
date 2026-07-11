"""Shot & Club Trends — shots per club per calendar day across your whole
history (a club-colored stacked bar, one bar per day you practiced), plus a
row of summary tiles beneath it.

Ignores the global Time filter on purpose: it's the "back to the beginning of
time" view. Uses the same per-club colors as every other chart.
"""
from __future__ import annotations

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.patches import FancyBboxPatch

from config import Colors, get_club_color, get_club_rank
from data.columns import CARRY_ALIASES, TOTAL_ALIASES, find_col
from ui.charts._shared import club_legend, style_axes
from ui.empty_state import show_message

NAME = "Shot & Club Trends"
CATEGORY = "Metrics"
COLUMN = "left"
HAS_COLOR = False
WIDE = True  # a calendar-day timeline across the x-axis — needs full width


def render(fig, df, club_colors, font_scale, config, **extra):
    if df.empty or "club" not in df.columns or "session_date" not in df.columns:
        show_message(fig, "No dated shot data yet", font_scale,
                     hint="Shots need a session date to appear on the timeline.")
        return

    d = df[["club", "session_date"]].copy()
    d["_day"] = pd.to_datetime(d["session_date"], errors="coerce").dt.normalize()
    d = d[d["_day"].notna() & d["club"].notna()]
    if d.empty:
        show_message(fig, "No dated shots to plot", font_scale)
        return

    gs = fig.add_gridspec(2, 1, height_ratios=[3.1, 1.0], hspace=0.36)
    ax = fig.add_subplot(gs[0])
    ax_tiles = fig.add_subplot(gs[1])

    counts = d.groupby(["_day", "club"]).size().unstack(fill_value=0)
    clubs = sorted(counts.columns, key=get_club_rank)
    days = counts.index.to_pydatetime()

    bottom = np.zeros(len(days))
    for club in clubs:
        vals = counts[club].to_numpy()
        ax.bar(days, vals, bottom=bottom, width=0.9,
               color=club_colors.get(club) or get_club_color(club),
               edgecolor="none", label=str(club))
        bottom += vals

    ax.set_ylabel("Shots", fontsize=font_scale)
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.margins(x=0.01)
    style_axes(ax, font_scale, grid="y")
    ax.set_title(f"{int(bottom.sum()):,} shots · {len(days)} days practiced",
                 fontsize=font_scale - 1, color=Colors.TEXT_MUTED, pad=6)
    if config.get("num_plots", 1) < 3:
        club_legend(ax, club_colors, clubs, font_scale, loc="upper left")

    _draw_tiles(ax_tiles, df, counts, len(days), font_scale)


def _draw_tiles(ax, df, counts, n_days, font_scale):
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    club_totals = counts.sum(axis=0).sort_values(ascending=False)
    most_club = str(club_totals.index[0]) if not club_totals.empty else "—"

    carry_col = find_col(df, CARRY_ALIASES)
    total_col = find_col(df, TOTAL_ALIASES) or carry_col

    def _dr_stat(col, agg):
        if not col:
            return None
        v = pd.to_numeric(df.loc[df["club"].astype(str) == "Dr", col], errors="coerce").dropna()
        return getattr(v, agg)() if not v.empty else None

    dr_carry = _dr_stat(carry_col, "mean")
    longest = _dr_stat(total_col, "max")
    sessions = df["session_id"].nunique() if "session_id" in df.columns else n_days

    tiles = [
        ("Total shots", f"{len(df):,}", Colors.TEXT_ACTIVE),
        ("Sessions", f"{sessions}", Colors.TEXT_ACTIVE),
        ("Days practiced", f"{n_days}", Colors.TEXT_ACTIVE),
        ("Most-hit club", most_club, get_club_color(most_club)),
        ("Avg driver carry", f"{dr_carry:.0f} yds" if dr_carry else "—", get_club_color("Dr")),
        ("Longest drive", f"{longest:.0f} yds" if longest else "—", Colors.SUCCESS),
    ]

    n = len(tiles)
    gap = 0.012
    w = (1 - gap * (n - 1)) / n
    for i, (label, value, color) in enumerate(tiles):
        x0 = i * (w + gap)
        ax.add_patch(FancyBboxPatch(
            (x0 + 0.006, 0.06), w - 0.012, 0.86,
            boxstyle="round,pad=0.002,rounding_size=0.018", mutation_aspect=0.32,
            facecolor=Colors.BG_HOVER, edgecolor=Colors.BORDER, linewidth=1.0, clip_on=False))
        ax.text(x0 + 0.028, 0.64, label, fontsize=max(9, font_scale - 3),
                color=Colors.TEXT_MUTED, va="center", ha="left")
        ax.text(x0 + 0.028, 0.30, value, fontsize=max(13, font_scale + 1), fontweight="bold",
                color=color, va="center", ha="left")
