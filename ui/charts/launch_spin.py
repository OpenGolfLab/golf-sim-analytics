"""Launch & Spin Optimization — actual shots vs. a speed-adjusted ideal
launch angle / spin rate target per club.

Each shot is colored by square_point_colors(): a quantized 2D color field
that is green at the club's ideal launch/spin and steps out, in discrete
blocks, to four corner colors (spin low→high left→right, launch low→high
bottom→top). draw_color_square() draws the matching block-grid legend key.

The panel defaults to the driver and carries its own single-club selector
in app_window (independent of the global Club Filter). This renderer still
handles a multi-club frame gracefully — each point is scored against its
own club's ideal — so it stays correct for tests and any caller that hands
it more than one club.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import REFERENCE_PROFILES, Colors, optimal_launch_spin
from data.columns import CLUB_SPEED_ALIASES, LAUNCH_ANGLE_ALIASES, SPIN_RATE_ALIASES, find_col
from ui.charts._shared import (
    GREEN_TARGET, SQUARE_SCALE_TOLS, attach_hover_tooltip, draw_color_square,
    plot_benchmarks, square_point_colors, style_axes,
)
from ui.empty_state import show_message

NAME = "Launch & Spin Optimization"
CATEGORY = "Optimization"
COLUMN = "left"
HAS_COLOR = False
BENCHMARK_FIELDS = ("spin_rate", "launch_angle")


def render(fig, df, club_colors, font_scale, config, **extra):
    vla_col = find_col(df, LAUNCH_ANGLE_ALIASES)
    spin_col = find_col(df, SPIN_RATE_ALIASES)
    cs_col = find_col(df, CLUB_SPEED_ALIASES)

    if df.empty or not (vla_col and spin_col and "club" in df.columns):
        show_message(fig, "Missing Launch Angle / Spin data", font_scale,
                     tone="muted" if df.empty else "error")
        return

    df = df.dropna(subset=[vla_col, spin_col]).copy()
    if df.empty:
        show_message(fig, "Insufficient data for scoring", font_scale)
        return

    ax = fig.add_subplot(111)

    vla = df[vla_col].to_numpy(float)
    spin = df[spin_col].to_numpy(float)

    # Per-club optimal launch/spin (config.optimal_launch_spin), scaled off
    # the TrackMan tour baseline by the player's own speed for that club.
    # Each club's shots are scored against one ideal — the same point its
    # green target marker sits on — computed from its mean clubhead speed.
    club_avg_speed = df.groupby("club")[cs_col].mean() if cs_col else pd.Series(dtype=float)

    def _club_ideal(club):
        speed_avg = float(club_avg_speed.get(club, 100.0)) if not club_avg_speed.empty else 100.0
        return optimal_launch_spin(club, speed_avg)

    ideal = {club: _club_ideal(club) for club in df["club"].unique()}
    clubs = df["club"].tolist()
    ideal_launch = np.array([ideal[c][0] for c in clubs])
    ideal_spin = np.array([ideal[c][1] for c in clubs])
    # Driver held to a tighter window than the (more forgiving) irons.
    launch_tol = np.array([3.0 if c == "Dr" else 4.0 for c in clubs])
    spin_tol = np.array([500.0 if c == "Dr" else 1200.0 for c in clubs])

    point_colors = square_point_colors(
        vla, spin, ideal_launch, ideal_spin,
        launch_tol * SQUARE_SCALE_TOLS, spin_tol * SQUARE_SCALE_TOLS,
    )
    shots_sc = ax.scatter(spin, vla, c=point_colors, s=55, alpha=0.9,
                          edgecolor="black", linewidth=0.5, zorder=2)

    # spin/vla arrays are built row-for-row off `df`, so df maps positionally
    # to the scatter's points for hover lookup.
    def _tooltip(row):
        lines = [
            str(row["club"]),
            f"Spin: {row[spin_col]:.0f} rpm",
            f"Launch: {row[vla_col]:.1f}°",
        ]
        if cs_col and pd.notna(row.get(cs_col)):
            lines.append(f"Club speed: {row[cs_col]:.1f} mph")
        if "session_date" in row.index and pd.notna(row["session_date"]):
            lines.append(pd.to_datetime(row["session_date"]).strftime("%b %d, %Y"))
        return "\n".join(lines)

    attach_hover_tooltip(fig, shots_sc, df, _tooltip, font_scale)

    # Green (= optimal) target marker per club, labels alternating above/below.
    targets = sorted((float(s), float(l), str(club)) for club, (l, s) in ideal.items())
    for i, (t_spin, t_launch, club) in enumerate(targets):
        # Green (= optimal) with a white outline, matching the color square's
        # green center block.
        ax.scatter(t_spin, t_launch, s=240, color=GREEN_TARGET,
                   edgecolor="white", linewidth=2.0, zorder=3)
        above = i % 2 == 0
        ax.annotate(
            club, (t_spin, t_launch), textcoords="offset points",
            xytext=(0, 13 if above else -13), ha="center",
            va="bottom" if above else "top", fontsize=font_scale - 2,
            color=Colors.TEXT_ACTIVE, fontweight="bold", zorder=4,
        )

    def _ls_points(profile):
        prof = REFERENCE_PROFILES.get(profile, {})
        pts = []
        for c in df["club"].dropna().unique():
            m = prof.get(c)
            if m is not None and m.spin_rate is not None and m.launch_angle is not None:
                pts.append((m.spin_rate, m.launch_angle))
        return pts

    # Benchmark stars still draw on the plot when toggled on; the color
    # square is the only key this chart needs, so no separate legend box.
    plot_benchmarks(ax, extra.get("benchmarks", []), _ls_points, size=150)

    draw_color_square(ax, font_scale)

    ax.set_xlabel("Spin Rate (RPM)", fontsize=font_scale)
    ax.set_ylabel("Launch Angle (°)", fontsize=font_scale)
    ax.set_title("How do your shots compare to the ideal launch and spin conditions "
                 "for your swing speed?",
                 fontsize=font_scale - 1, color=Colors.TEXT_MUTED, loc="left", pad=10)
    style_axes(ax, font_scale)
