"""Carry Efficiency — carry yards per MPH of club speed, with driver/iron
optimal reference lines.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba

from config import REFERENCE_PROFILES, Colors, get_club_rank
from data.columns import CARRY_ALIASES, CLUB_SPEED_ALIASES, find_col
from ui.charts._shared import (
    attach_hover_tooltip, club_legend, get_timeline_colormap, plot_benchmarks,
    style_axes, styled_colorbar,
)
from ui.empty_state import show_message

NAME = "Carry Efficiency"
CATEGORY = "Optimization"
COLUMN = "left"
HAS_COLOR = True
BENCHMARK_FIELDS = ("club_speed", "carry")


def render(fig, df, club_colors, font_scale, config, **extra):
    cs_col = find_col(df, CLUB_SPEED_ALIASES)
    carry_col = find_col(df, CARRY_ALIASES)
    num_plots = config.get("num_plots", 1)

    if df.empty or not (cs_col and carry_col and "club" in df.columns):
        show_message(fig, "Missing Club Speed or Carry data", font_scale,
                     tone="muted" if df.empty else "error")
        return

    df = df.copy()
    df["efficiency"] = df[carry_col] / df[cs_col]

    ax = fig.add_subplot(111)
    color_pref = config.get("color_var").get() if "color_var" in config else "Club"

    pts = df[df[cs_col].notna() & df["efficiency"].notna() & df["club"].notna()].reset_index(drop=True)

    def _tooltip(row):
        lines = [
            str(row["club"]),
            f"Club speed: {row[cs_col]:.1f} mph",
            f"Carry: {row[carry_col]:.0f} yds",
            f"Efficiency: {row['efficiency']:.2f} yds/mph",
        ]
        if "session_date" in row.index and pd.notna(row["session_date"]):
            lines.append(pd.to_datetime(row["session_date"]).strftime("%b %d, %Y"))
        return "\n".join(lines)

    if color_pref == "Date (Timeline)" and "session_date" in df.columns:
        norm, cmap = get_timeline_colormap(df)
        pts_dates = pd.to_numeric(pd.to_datetime(pts["session_date"]))
        sc = ax.scatter(
            pts[cs_col], pts["efficiency"], c=pts_dates, cmap=cmap, norm=norm,
            s=60, alpha=0.8, edgecolor="black", zorder=2,
        )
        cbar = styled_colorbar(fig, sc, ax, "Oldest → Newest", font_scale)
        cbar.set_ticks([])
    else:
        # Single-collection scatter (was sns.scatterplot hue="club"): identical
        # look, but one PathCollection whose order matches pts, for hover lookup.
        sc = ax.scatter(
            pts[cs_col], pts["efficiency"],
            c=[to_rgba(club_colors.get(c, Colors.CLUB_FALLBACK)) for c in pts["club"]],
            s=60, alpha=0.8, edgecolor="black", zorder=2,
        )
        def _eff_points(profile):
            prof = REFERENCE_PROFILES.get(profile, {})
            pts = []
            for c in df["club"].dropna().unique():
                m = prof.get(c)
                if m is not None and m.carry is not None and m.club_speed:
                    pts.append((m.club_speed, m.carry / m.club_speed))
            return pts

        bench_handles = plot_benchmarks(ax, extra.get("benchmarks", []), _eff_points)
        if num_plots == 1:
            order = sorted(df["club"].dropna().unique(), key=get_club_rank)
            club_legend(ax, club_colors, order, font_scale, loc="upper left",
                        extra_handles=bench_handles or None)

    attach_hover_tooltip(fig, sc, pts, _tooltip, font_scale)

    x_min, x_max = df[cs_col].min(), df[cs_col].max()
    if not np.isnan(x_min) and x_min > 0:
        ax.set_xlim(x_min - 2, x_max + 12)
        ax.axhline(2.6, linestyle="--", color=Colors.SUCCESS, alpha=0.7, zorder=1)
        ax.axhline(2.0, linestyle="--", color=Colors.INFO, alpha=0.7, zorder=1)
        ax.text(x_max + 11, 2.6, "Driver target (~2.6)", color=Colors.SUCCESS,
                va="bottom", ha="right", fontsize=font_scale - 1)
        ax.text(x_max + 11, 2.0, "Iron target (~2.0)", color=Colors.INFO,
                va="bottom", ha="right", fontsize=font_scale - 1)

    ax.set_xlabel("Club Speed (MPH)", fontsize=font_scale)
    ax.set_ylabel("Yards of Carry per MPH", fontsize=font_scale)
    style_axes(ax, font_scale)
