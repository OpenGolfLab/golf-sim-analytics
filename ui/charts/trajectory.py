"""Trajectory — flight-path arcs plus launch angle / peak
height / descent angle box plots with club-fitting "optimal window" bands.

Perf note: the per-shot arcs used to be drawn with one ax.plot() call per
row inside df.iterrows() (~1.1s for ~700 shots). They're now computed as
numpy arrays in one shot and drawn as a single LineCollection, which is
roughly 5-10x faster.

Layout note: the old GridSpec(hspace=0.6, wspace=0.3) fought the figure's
constrained layout and collapsed the boxplot row into unreadable slivers
with a large dead band above. The grid now leaves spacing to constrained
layout, and the zone legend hangs below the axes via fig.legend.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

from config import REFERENCE_PROFILES, Colors, get_club_rank, get_fitting_window
from data.columns import (
    CARRY_ALIASES, DESCENT_ANGLE_ALIASES, HEIGHT_ALIASES, LAUNCH_ANGLE_ALIASES, find_col,
)
from ui.charts._shared import plot_benchmarks, style_axes
from ui.empty_state import show_message

NAME = "Trajectory"
CATEGORY = "Metrics"
COLUMN = "left"
HAS_COLOR = True
WIDE = True  # wide flight-path arcs + a 3-across boxplot row — needs full width
BENCHMARK_FIELDS = ("launch_angle", "max_height", "land_angle")
BENCHMARK_MODE = "any"


def _apex_ft(values: np.ndarray) -> np.ndarray:
    """Heuristic the app has always used: heights < 60 are meters -> feet."""
    return np.where(values < 60, values * 3.0, values)


def render(fig, df, club_colors, font_scale, config, **extra):
    if df.empty or "club" not in df.columns:
        show_message(fig, "No club data available", font_scale)
        return

    show_ind = config["ind_var"].get()
    num_plots = config.get("num_plots", 1)
    compact = num_plots >= 3

    height_col = find_col(df, HEIGHT_ALIASES)
    carry_col = find_col(df, CARRY_ALIASES)
    vla_col = find_col(df, LAUNCH_ANGLE_ALIASES)
    desc_col = find_col(df, DESCENT_ANGLE_ALIASES)

    if not (height_col and carry_col):
        show_message(fig, "Missing height/carry data", font_scale, tone="error")
        return

    gs = fig.add_gridspec(2, 3, height_ratios=[1.7, 1.0], hspace=0.21)
    ax_traj = fig.add_subplot(gs[0, :])
    ax_vla = fig.add_subplot(gs[1, 0])
    ax_height = fig.add_subplot(gs[1, 1])
    ax_desc = fig.add_subplot(gs[1, 2])

    order = sorted(df["club"].dropna().unique(), key=get_club_rank)
    summary = df.groupby("club").agg({carry_col: "mean", height_col: "mean"}).reset_index()

    d = df[(df[carry_col] > 0) & df[height_col].notna()]
    carry = d[carry_col].to_numpy(float)
    apex = _apex_ft(d[height_col].to_numpy(float))
    clubs = d["club"].astype(str).to_numpy()

    # ------------------------------------------------------------------
    # Per-shot arcs, vectorized.
    # ------------------------------------------------------------------
    t = np.linspace(0, 1, 60)
    X = carry[:, None] * t ** 0.85
    Y = apex[:, None] * np.sin(np.pi * t ** 1.25)

    if show_ind and len(d):
        segments = np.stack([X, Y], axis=2)
        colors = [club_colors.get(c, "gray") for c in clubs]
        # Alpha kept low so hundreds of overlapping per-shot arcs read as a
        # soft density texture rather than drowning out the per-club
        # average arcs drawn on top of them below.
        ax_traj.add_collection(
            LineCollection(segments, colors=colors, linewidths=1.0, alpha=0.05, zorder=1)
        )

    # ------------------------------------------------------------------
    # Per-club average arcs — drawn last/highest zorder so they read
    # clearly in front of the individual-shot arc texture above.
    # ------------------------------------------------------------------
    t2 = np.linspace(0, 1, 120)
    for _, row in summary.iterrows():
        c_val, a_val = row[carry_col], row[height_col]
        if not (c_val > 0 and pd.notna(a_val)):
            continue
        a_val = a_val * 3.0 if a_val < 60 else a_val
        x = c_val * t2 ** 0.85
        y = a_val * np.sin(np.pi * t2 ** 1.25)
        color = club_colors.get(row["club"], "gray")
        ax_traj.plot(x, y, color=color, label=str(row["club"]), linewidth=3.2,
                     linestyle="--", alpha=1.0, zorder=5)
        k = int(np.argmax(y))
        ax_traj.plot(x[k], y[k], marker="o", color=color, markersize=5,
                     markeredgecolor=Colors.BG_SURFACE, markeredgewidth=1.0, zorder=6)

    max_x = float(np.max(carry)) if len(carry) else 100.0
    max_y = float(np.max(apex)) if len(apex) else 100.0
    ax_traj.set_xlim(0, max(max_x * 1.03, 10))
    ax_traj.set_ylim(0, max(max_y * 1.12, 10))
    ax_traj.set_ylabel("Height (Feet)", fontsize=font_scale)
    ax_traj.set_xlabel("Carry (Yards)", fontsize=font_scale)
    style_axes(ax_traj, font_scale)

    if not compact:
        handles, labels = ax_traj.get_legend_handles_labels()
        combined = sorted(zip(handles, labels), key=lambda item: get_club_rank(item[1]))
        if combined:
            hs, ls = zip(*combined)
            leg = ax_traj.legend(
                hs, ls, fontsize=max(8, font_scale - 3), loc="upper right",
                ncol=2 if len(ls) > 7 else 1, facecolor=Colors.BG_SURFACE,
                edgecolor=Colors.BORDER, framealpha=0.9, labelcolor=Colors.TEXT_PRIMARY,
                handlelength=1.6, columnspacing=0.8, handletextpad=0.4,
            )
            leg.set_zorder(20)

    # ------------------------------------------------------------------
    # Launch / height / descent boxplots with fitting-window bands.
    # ------------------------------------------------------------------
    if not (vla_col and desc_col):
        for a in (ax_vla, ax_height, ax_desc):
            a.text(0.5, 0.5, "Missing VLA/Desc data", ha="center", va="center",
                   fontsize=font_scale - 1, color=Colors.TEXT_MUTED)
            a.set_axis_off()
        return

    df = df.copy()
    df["height_ft"] = _apex_ft(df[height_col].to_numpy(float))

    # Peak Height's tour figure (max_height) is in yards, not feet — this
    # subplot's own axis; every other field lines up with its column as-is.
    _FIELD = {"vla": "launch_angle", "height": "max_height", "desc": "land_angle"}
    benchmarks = extra.get("benchmarks", [])
    bench_handles: dict[str, object] = {}  # label -> handle, deduped across subplots

    for ax_sub, y_col, metric_name, title in zip(
        [ax_vla, ax_height, ax_desc],
        [vla_col, "height_ft", desc_col],
        ["vla", "height", "desc"],
        ["Launch Angle (°)", "Peak Height (Feet)", "Descent Angle (°)"],
    ):
        zone_mins, zone_maxs = [], []
        if metric_name == "height":
            # The ideal flight window is the same for every club, so draw one
            # clean set of full-width bands instead of per-club blocks:
            # green 90-110 ft, amber 80-90 / 110-120, red beyond.
            lo, hi = get_fitting_window("Dr")[1]
            marg = (lo - 10, hi + 10)
            ax_sub.axhspan(marg[0] - 200, marg[0], color=Colors.ZONE_BAD, alpha=0.16, zorder=0)
            ax_sub.axhspan(marg[1], marg[1] + 200, color=Colors.ZONE_BAD, alpha=0.16, zorder=0)
            ax_sub.axhspan(marg[0], lo, color=Colors.ZONE_WARN, alpha=0.20, zorder=1)
            ax_sub.axhspan(hi, marg[1], color=Colors.ZONE_WARN, alpha=0.20, zorder=1)
            ax_sub.axhspan(lo, hi, color=Colors.ZONE_GOOD, alpha=0.34, zorder=2)
            for edge in (lo, hi):
                ax_sub.axhline(edge, color=Colors.ZONE_GOOD, linewidth=1.0, alpha=0.8, zorder=3)
            zone_mins, zone_maxs = [marg[0]], [marg[1]]
        else:
            # Launch / landing windows step steadily through the bag, so the
            # per-club bands tile into one continuous ascending ribbon.
            for i, club in enumerate(order):
                v_opt, _h_opt, d_opt = get_fitting_window(str(club) if club else "Dr")
                opt = v_opt if metric_name == "vla" else d_opt
                marg = (opt[0] - 3, opt[1] + 3)
                zone_mins.append(marg[0])
                zone_maxs.append(marg[1])
                x_min, x_max = (i - 0.5, i + 0.5) if len(order) > 1 else (-0.5, 0.5)
                ax_sub.fill_between([x_min, x_max], marg[0] - 200, marg[0],
                                    color=Colors.ZONE_BAD, alpha=0.13, zorder=0)
                ax_sub.fill_between([x_min, x_max], marg[1], marg[1] + 200,
                                    color=Colors.ZONE_BAD, alpha=0.13, zorder=0)
                ax_sub.fill_between([x_min, x_max], marg[0], opt[0],
                                    color=Colors.ZONE_WARN, alpha=0.18, zorder=1)
                ax_sub.fill_between([x_min, x_max], opt[1], marg[1],
                                    color=Colors.ZONE_WARN, alpha=0.18, zorder=1)
                ax_sub.fill_between([x_min, x_max], opt[0], opt[1],
                                    color=Colors.ZONE_GOOD, alpha=0.34, zorder=2)
                for edge in opt:
                    ax_sub.plot([x_min, x_max], [edge, edge], color=Colors.ZONE_GOOD,
                                linewidth=1.0, alpha=0.75, zorder=3)

        sns.boxplot(
            data=df, x="club", y=y_col, order=order, ax=ax_sub, showfliers=False,
            width=0.25, zorder=4,
            boxprops=dict(facecolor="none", edgecolor=Colors.TEXT_PRIMARY, linewidth=1.3),
            whiskerprops=dict(color=Colors.TEXT_PRIMARY, linewidth=1.3),
            capprops=dict(color=Colors.TEXT_PRIMARY, linewidth=1.3),
            medianprops=dict(color=Colors.TEXT_PRIMARY, linewidth=1.3),
        )

        # Reference benchmark stars. Peak Height's published figure is in
        # yards while this subplot's column (height_ft) is in feet, so scale
        # to match. Only profiles that actually carry this metric (currently
        # just PGA Tour) contribute points.
        unit_scale = 3.0 if metric_name == "height" else 1.0
        field = _FIELD[metric_name]

        def _points(profile, field=field, scale=unit_scale):
            prof = REFERENCE_PROFILES.get(profile, {})
            pts = []
            for i, c in enumerate(order):
                m = prof.get(c)
                if m is not None and getattr(m, field) is not None:
                    pts.append((i, getattr(m, field) * scale))
            return pts

        for handle in plot_benchmarks(ax_sub, benchmarks, _points, size=95):
            bench_handles.setdefault(handle.get_label(), handle)

        # Y-limits are fixed by the data + fitting bands only — NOT by the
        # benchmark stars — so toggling a benchmark never rescales the axes.
        y_vals = df[y_col].dropna()
        if not y_vals.empty:
            q1, q3 = y_vals.quantile(0.25), y_vals.quantile(0.75)
            iqr = q3 - q1
            whisker_low, whisker_high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            target_min = min(zone_mins) if zone_mins else whisker_low
            target_max = max(zone_maxs) if zone_maxs else whisker_high
            ax_sub.set_ylim(max(0, min(whisker_low, target_min) - 3),
                            max(whisker_high, target_max) + 3)

        ax_sub.set_title(title, fontsize=font_scale, color=Colors.TEXT_PRIMARY, pad=8)
        ax_sub.set_xlabel("")
        ax_sub.set_ylabel("")
        style_axes(ax_sub, font_scale, grid="y")
        ax_sub.tick_params(axis="x", labelsize=max(10, font_scale - 2))
        if len(order) > 6:
            plt.setp(ax_sub.get_xticklabels(), rotation=55, ha="right")

    legend_elements = [
        Line2D([0], [0], color=Colors.ZONE_GOOD, lw=8, alpha=0.6, label="Ideal"),
        Line2D([0], [0], color=Colors.ZONE_WARN, lw=8, alpha=0.5, label="Acceptable"),
        Line2D([0], [0], color=Colors.ZONE_BAD, lw=8, alpha=0.45, label="Outside range"),
    ]
    legend_elements += list(bench_handles.values())
    ncol = len(legend_elements)
    try:
        fig.legend(handles=legend_elements, loc="outside lower center", ncol=ncol,
                   fontsize=font_scale - 1, frameon=False, labelcolor=Colors.TEXT_PRIMARY)
    except (ValueError, TypeError):
        # matplotlib < 3.7 doesn't know "outside" locations
        fig.legend(handles=legend_elements, loc="lower center", ncol=ncol,
                   fontsize=font_scale - 1, frameon=False, labelcolor=Colors.TEXT_PRIMARY)
