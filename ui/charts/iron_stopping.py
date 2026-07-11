"""Iron Stopping Power — spin rate vs. descent angle, with a "Tour Stop"
reference window (45-50°).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba

from config import REFERENCE_PROFILES, Colors, get_club_rank
from data.columns import DESCENT_ANGLE_ALIASES, SPIN_RATE_ALIASES, find_col
from ui.charts._shared import (
    attach_hover_tooltip, club_legend, get_timeline_colormap, plot_benchmarks,
    style_axes, styled_colorbar,
)
from ui.empty_state import show_message

NAME = "Iron Stopping Power"
CATEGORY = "Optimization"
COLUMN = "right"
HAS_COLOR = True
BENCHMARK_FIELDS = ("spin_rate", "land_angle")


def render(fig, df, club_colors, font_scale, config, **extra):
    desc_col = find_col(df, DESCENT_ANGLE_ALIASES)
    spin_col = find_col(df, SPIN_RATE_ALIASES)
    num_plots = config.get("num_plots", 1)

    if df.empty or not (desc_col and spin_col and "club" in df.columns):
        show_message(fig, "Missing Descent Angle or Spin data", font_scale,
                     tone="muted" if df.empty else "error")
        return

    ax = fig.add_subplot(111)
    color_pref = config.get("color_var").get() if "color_var" in config else "Club"

    pts = df[df[spin_col].notna() & df[desc_col].notna() & df["club"].notna()].reset_index(drop=True)

    def _tooltip(row):
        lines = [
            str(row["club"]),
            f"Spin: {row[spin_col]:.0f} rpm",
            f"Descent: {row[desc_col]:.1f}°",
        ]
        if "session_date" in row.index and pd.notna(row["session_date"]):
            lines.append(pd.to_datetime(row["session_date"]).strftime("%b %d, %Y"))
        return "\n".join(lines)

    if color_pref == "Date (Timeline)" and "session_date" in df.columns:
        norm, cmap = get_timeline_colormap(df)
        pts_dates = pd.to_numeric(pd.to_datetime(pts["session_date"]))
        sc = ax.scatter(
            pts[spin_col], pts[desc_col], c=pts_dates, cmap=cmap, norm=norm,
            s=60, alpha=0.8, edgecolor="black", zorder=2,
        )
        cbar = styled_colorbar(fig, sc, ax, "Oldest → Newest", font_scale)
        cbar.set_ticks([])
    else:
        # Single-collection scatter (was sns.scatterplot hue="club"): identical
        # look, but one PathCollection whose order matches pts, for hover lookup.
        sc = ax.scatter(
            pts[spin_col], pts[desc_col],
            c=[to_rgba(club_colors.get(c, Colors.CLUB_FALLBACK)) for c in pts["club"]],
            s=60, alpha=0.8, edgecolor="black", zorder=2,
        )
        def _stop_points(profile):
            prof = REFERENCE_PROFILES.get(profile, {})
            pts = []
            for c in df["club"].dropna().unique():
                m = prof.get(c)
                if m is not None and m.spin_rate is not None and m.land_angle is not None:
                    pts.append((m.spin_rate, m.land_angle))
            return pts

        bench_handles = plot_benchmarks(ax, extra.get("benchmarks", []), _stop_points)
        if num_plots == 1:
            order = sorted(df["club"].dropna().unique(), key=get_club_rank)
            club_legend(ax, club_colors, order, font_scale, loc="upper left",
                        extra_handles=bench_handles or None)

    attach_hover_tooltip(fig, sc, pts, _tooltip, font_scale)

    s_min, s_max = df[spin_col].min(), df[spin_col].max()
    if not np.isnan(s_min) and s_min > 0:
        ax.set_xlim(max(0, s_min - 500), s_max + 2500)
        ax.axhline(45, color=Colors.SUCCESS, linestyle="--", alpha=0.7, zorder=1)
        ax.axhline(50, color=Colors.SUCCESS, linestyle="--", alpha=0.7, zorder=1)
        ax.fill_between(x=[-5000, 20000], y1=45, y2=50, color=Colors.SUCCESS, alpha=0.1, zorder=0)
        ax.text(s_max + 2400, 47.5, "Tour stopping window (45°–50°)", color=Colors.SUCCESS,
                va="center", ha="right", fontsize=font_scale - 1)

    ax.set_xlabel("Spin Rate (RPM)", fontsize=font_scale)
    ax.set_ylabel("Descent Angle (°)", fontsize=font_scale)
    style_axes(ax, font_scale)
