"""Swing Efficiency — ball speed vs. club speed, with smash-factor
reference lines.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba

from config import REFERENCE_PROFILES, Colors, get_club_rank
from data.columns import BALL_SPEED_ALIASES, CLUB_SPEED_ALIASES, find_col
from ui.charts._shared import (
    attach_hover_tooltip, club_legend, get_timeline_colormap, plot_benchmarks,
    style_axes, styled_colorbar,
)
from ui.empty_state import show_message

NAME = "Swing Efficiency"
CATEGORY = "Metrics"
COLUMN = "left"
HAS_COLOR = True
BENCHMARK_FIELDS = ("club_speed", "ball_speed")


def render(fig, df, club_colors, font_scale, config, **extra):
    ax = fig.add_subplot(111)
    color_pref = config["color_var"].get()
    bs_col = find_col(df, BALL_SPEED_ALIASES)
    cs_col = find_col(df, CLUB_SPEED_ALIASES)
    num_plots = config.get("num_plots", 1)

    if df.empty or not (bs_col and cs_col and "club" in df.columns):
        show_message(fig, "Missing speed data", font_scale,
                     tone="muted" if df.empty else "error")
        return

    pts = df[df[cs_col].notna() & df[bs_col].notna() & df["club"].notna()].reset_index(drop=True)

    def _tooltip(row):
        lines = [
            str(row["club"]),
            f"Club speed: {row[cs_col]:.1f} mph",
            f"Ball speed: {row[bs_col]:.1f} mph",
        ]
        if row[cs_col]:
            lines.append(f"Smash: {row[bs_col] / row[cs_col]:.2f}")
        if "session_date" in row.index and pd.notna(row["session_date"]):
            lines.append(pd.to_datetime(row["session_date"]).strftime("%b %d, %Y"))
        return "\n".join(lines)

    if color_pref == "Date (Timeline)" and "session_date" in df.columns:
        norm, cmap = get_timeline_colormap(df)
        pts_dates = pd.to_numeric(pd.to_datetime(pts["session_date"]))
        sc = ax.scatter(
            pts[cs_col], pts[bs_col], c=pts_dates, cmap=cmap, norm=norm,
            s=70, alpha=0.9, edgecolor="black", linewidth=0.5,
        )
        cbar = styled_colorbar(fig, sc, ax, "Oldest → Newest", font_scale)
        cbar.set_ticks([])
    else:
        # Single-collection scatter (was sns.scatterplot hue="club"): identical
        # look, but one PathCollection whose order matches pts, for hover lookup.
        sc = ax.scatter(
            pts[cs_col], pts[bs_col],
            c=[to_rgba(club_colors.get(c, Colors.CLUB_FALLBACK)) for c in pts["club"]],
            s=70, alpha=0.9, edgecolor="black", linewidth=0.5,
        )
        if num_plots == 1:
            order = sorted(df["club"].dropna().unique(), key=get_club_rank)
            leg = club_legend(ax, club_colors, order, font_scale, loc="upper left")
            if leg:
                ax.add_artist(leg)

    attach_hover_tooltip(fig, sc, pts, _tooltip, font_scale)

    clubs_present = df["club"].dropna().unique()

    def _speed_points(profile):
        prof = REFERENCE_PROFILES.get(profile, {})
        pts = []
        for c in clubs_present:
            m = prof.get(c)
            if m is not None and m.club_speed is not None and m.ball_speed is not None:
                pts.append((m.club_speed, m.ball_speed))
        return pts

    bench_handles = plot_benchmarks(ax, extra.get("benchmarks", []), _speed_points)

    smash_lines = []
    x_min, x_max = df[cs_col].min(), df[cs_col].max()
    if not np.isnan(x_min) and x_min > 0:
        ax.set_xlim(x_min - 2, x_max + 12)
        for sf, color in zip([1.3, 1.4, 1.5], [Colors.TEXT_MUTED, Colors.INFO, Colors.SUCCESS]):
            (line,) = ax.plot(
                [x_min, x_max + 10], [x_min * sf, (x_max + 10) * sf],
                linestyle="--", color=color, alpha=0.7, linewidth=1.2, label=f"{sf} Smash",
            )
            smash_lines.append(line)

    legend_handles = smash_lines + bench_handles
    if legend_handles:
        leg2 = ax.legend(handles=legend_handles, loc="lower right", fontsize=font_scale - 2,
                         facecolor=Colors.BG_SURFACE, edgecolor=Colors.BORDER,
                         framealpha=0.85, labelcolor=Colors.TEXT_PRIMARY)
        leg2.set_zorder(20)

    ax.set_xlabel("Club Speed (MPH)", fontsize=font_scale)
    ax.set_ylabel("Ball Speed (MPH)", fontsize=font_scale)
    style_axes(ax, font_scale)
