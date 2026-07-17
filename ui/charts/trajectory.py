"""Trajectory — flight-path arcs plus launch angle / peak
height / descent angle box plots with club-fitting "optimal window" bands.

Perf note: the per-shot arcs used to be drawn with one ax.plot() call per
row inside df.iterrows() (~1.1s for ~700 shots). They're now computed as
numpy arrays in one shot and drawn as a single LineCollection, which is
roughly 5-10x faster.

Layout note: the layout is *height-aware*, measured from the figure's real
pixel size at render time (not the panel count). A tall figure (Trajectory
solo) gets the full arcs-over-boxplots composite with the arcs taking the
clear majority of the height. A short figure (Trajectory stacked under a
second panel) drops the boxplot row entirely and gives the arcs the whole
canvas, because a ~180px boxplot strip is unreadable. The old
GridSpec(hspace=0.6) fought constrained layout and collapsed the boxplot
row into slivers with a dead band above; spacing is now left to constrained
layout with a small explicit hspace.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

from config import (
    CLUB_FITTING_WINDOWS, REFERENCE_PROFILES, Colors, get_club_rank, get_fitting_window,
    normalize_club_name,
)
from data import units as units_mod
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

# Below this figure height (px) the boxplot row would be an unreadable strip,
# so the chart degrades to arcs-only and hands them the whole canvas. Chosen
# so Trajectory solo (~1360px) and small-laptop solo (~760px) keep the
# boxplots, while Trajectory stacked under a second panel (~620px) drops them.
_BOXPLOT_MIN_FIG_PX = 690

# Apex markers cycled per club so the four adjacent wedge blues (Pw/Gw/Sw/Lw)
# — a deliberate color ramp we don't alter — are still tellable apart by shape
# on the average arcs and in the legend.
_APEX_MARKERS = ("o", "s", "^", "D", "v", "P", "X", ">", "<", "*", "h")


def _apex_ft(values: np.ndarray) -> np.ndarray:
    """Heuristic the app has always used: heights < 60 are meters -> feet."""
    return np.where(values < 60, values * 3.0, values)


def _real_window(club):
    """The club's fitting window, or None for a club we don't have a real
    window for (e.g. an unnormalized 'Club8' passthrough) — so we never draw
    default-window bands that don't actually describe that club."""
    if not club:
        return None
    if normalize_club_name(str(club)) in CLUB_FITTING_WINDOWS:
        return get_fitting_window(str(club))
    return None


def render(fig, df, club_colors, font_scale, config, **extra):
    if df.empty or "club" not in df.columns:
        show_message(fig, "No club data available", font_scale)
        return

    show_ind = config["ind_var"].get()

    height_col = find_col(df, HEIGHT_ALIASES)
    carry_col = find_col(df, CARRY_ALIASES)
    vla_col = find_col(df, LAUNCH_ANGLE_ALIASES)
    desc_col = find_col(df, DESCENT_ANGLE_ALIASES)

    if not (height_col and carry_col):
        show_message(fig, "Missing height/carry data", font_scale, tone="error")
        return

    fig_w_px, fig_h_px = fig.get_size_inches() * fig.dpi
    show_boxplots = fig_h_px >= _BOXPLOT_MIN_FIG_PX and bool(vla_col and desc_col)

    if show_boxplots:
        # Arcs take ~2.4x the height of the boxplot row (was 1.7) — the flight
        # paths are the story; the boxplots are the supporting detail. A small
        # hspace lets constrained layout own the spacing instead of a dead band.
        gs = fig.add_gridspec(2, 3, height_ratios=[2.4, 1.0], hspace=0.16)
        ax_traj = fig.add_subplot(gs[0, :])
        ax_vla = fig.add_subplot(gs[1, 0])
        ax_height = fig.add_subplot(gs[1, 1])
        ax_desc = fig.add_subplot(gs[1, 2])
    else:
        ax_traj = fig.add_subplot(1, 1, 1)
        ax_vla = ax_height = ax_desc = None

    order = sorted(df["club"].dropna().unique(), key=get_club_rank)
    marker_of = {c: _APEX_MARKERS[i % len(_APEX_MARKERS)] for i, c in enumerate(order)}
    summary = df.groupby("club").agg({carry_col: "mean", height_col: "mean"}).reset_index()

    # Only carry (the distance axis) switches unit; apex/height stays in feet —
    # its fitting-window bands below are calibrated in feet, and the request is
    # about distances, not height.
    unit = extra.get("units", units_mod.YARDS)
    d = df[(df[carry_col] > 0) & df[height_col].notna()]
    carry = units_mod.to_display(d[carry_col].to_numpy(float), unit)
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
    # clearly in front of the individual-shot arc texture above. Each gets a
    # distinct apex marker shape so same-family colors stay tellable apart.
    # ------------------------------------------------------------------
    t2 = np.linspace(0, 1, 120)
    handle_of = {}  # club -> legend handle, so the legend can emit in rank order
    for _, row in summary.iterrows():
        c_val, a_val = units_mod.to_display(row[carry_col], unit), row[height_col]
        club = row["club"]
        if not (c_val > 0 and pd.notna(a_val)):
            continue
        a_val = a_val * 3.0 if a_val < 60 else a_val
        x = c_val * t2 ** 0.85
        y = a_val * np.sin(np.pi * t2 ** 1.25)
        color = club_colors.get(club, "gray")
        marker = marker_of.get(club, "o")
        ax_traj.plot(x, y, color=color, linewidth=3.2, linestyle="--", alpha=1.0, zorder=5)
        k = int(np.argmax(y))
        ax_traj.plot(x[k], y[k], marker=marker, color=color, markersize=7,
                     markeredgecolor=Colors.BG_SURFACE, markeredgewidth=1.0, zorder=6)
        handle_of[club] = Line2D(
            [0], [0], color=color, linewidth=3.0, linestyle="--", marker=marker,
            markersize=7, markeredgecolor=Colors.BG_SURFACE, label=str(club))
    # Emit the legend in canonical bag order (Dr, 3W, ... wedges), not the
    # alphabetical order groupby happened to produce.
    legend_handles = [handle_of[c] for c in order if c in handle_of]

    max_x = float(np.max(carry)) if len(carry) else 100.0
    max_y = float(np.max(apex)) if len(apex) else 100.0
    ax_traj.set_xlim(0, max(max_x * 1.03, 10))
    ax_traj.set_ylim(0, max(max_y * 1.12, 10))
    ax_traj.set_ylabel("Height (Feet)", fontsize=font_scale)
    ax_traj.set_xlabel(f"Carry ({units_mod.dist_suffix(unit)})", fontsize=font_scale)
    style_axes(ax_traj, font_scale)

    # Club legend as a horizontal strip along the top of the arc axes, outside
    # the data area (was a 2-col box in the upper-right that sat on the driver
    # arcs). ncol sized so it stays one or two shallow rows.
    if legend_handles:
        ncol = min(len(legend_handles), max(6, int(fig_w_px // 150)))
        leg = ax_traj.legend(
            handles=legend_handles, loc="lower center", bbox_to_anchor=(0.5, 1.005),
            ncol=ncol, fontsize=max(9, font_scale - 3), facecolor=Colors.BG_SURFACE,
            edgecolor=Colors.BORDER, framealpha=0.9, labelcolor=Colors.TEXT_PRIMARY,
            handlelength=1.8, columnspacing=1.0, handletextpad=0.4, borderpad=0.5,
        )
        leg.set_zorder(20)

    if not show_boxplots:
        return

    # ------------------------------------------------------------------
    # Launch / height / descent boxplots with fitting-window bands.
    # ------------------------------------------------------------------
    df = df.copy()
    df["height_ft"] = _apex_ft(df[height_col].to_numpy(float))

    # Peak Height's tour figure (max_height) is in yards, not feet — this
    # subplot's own axis; every other field lines up with its column as-is.
    _FIELD = {"vla": "launch_angle", "height": "max_height", "desc": "land_angle"}
    benchmarks = extra.get("benchmarks", [])
    bench_handles: dict[str, object] = {}  # label -> handle, deduped across subplots
    zone_handles = [
        Line2D([0], [0], color=Colors.ZONE_GOOD, lw=8, alpha=0.6, label="Ideal"),
        Line2D([0], [0], color=Colors.ZONE_WARN, lw=8, alpha=0.5, label="Acceptable"),
        Line2D([0], [0], color=Colors.ZONE_BAD, lw=8, alpha=0.45, label="Outside range"),
    ]

    for ax_sub, y_col, metric_name, title in zip(
        [ax_vla, ax_height, ax_desc],
        [vla_col, "height_ft", desc_col],
        ["vla", "height", "desc"],
        ["Launch Angle (°)", "Peak Height (Feet)", "Descent Angle (°)"],
    ):
        # Only clubs that actually have data for THIS metric get a column, so a
        # club missing a metric (e.g. Lw with no peak-height reading) doesn't
        # leave a silent empty slot.
        sub_order = [c for c in order if df.loc[df["club"] == c, y_col].notna().any()]
        if not sub_order:
            ax_sub.set_axis_off()
            ax_sub.text(0.5, 0.5, "No data", ha="center", va="center",
                        fontsize=font_scale - 1, color=Colors.TEXT_MUTED)
            continue

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
            # per-club bands tile into one continuous ascending ribbon. Clubs
            # without a real fitting window (unknown passthroughs) get a column
            # but no band, rather than a misleading default-window block.
            for i, club in enumerate(sub_order):
                window = _real_window(club)
                if window is None:
                    continue
                v_opt, _h_opt, d_opt = window
                opt = v_opt if metric_name == "vla" else d_opt
                marg = (opt[0] - 3, opt[1] + 3)
                zone_mins.append(marg[0])
                zone_maxs.append(marg[1])
                x_min, x_max = (i - 0.5, i + 0.5) if len(sub_order) > 1 else (-0.5, 0.5)
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

        # Box edges tinted with each club's own color (subdued) so the boxplots
        # belong to the same color-coded system as the arcs above, rather than
        # reading as a row of anonymous white boxes.
        sns.boxplot(
            data=df, x="club", y=y_col, order=sub_order, ax=ax_sub, showfliers=False,
            width=0.55, zorder=4, linewidth=1.3,
            boxprops=dict(facecolor="none"),
        )
        for patch, club in zip(ax_sub.patches, sub_order):
            col = club_colors.get(club, Colors.TEXT_PRIMARY)
            patch.set_edgecolor(col)
        # Whiskers/caps/medians come as Line2D children; tint them per club in
        # the same club order (seaborn draws them grouped left-to-right).
        _tint_box_lines(ax_sub, sub_order, club_colors)

        # Reference benchmark stars. Peak Height's published figure is in
        # yards while this subplot's column (height_ft) is in feet, so scale
        # to match. Only profiles that actually carry this metric (currently
        # just PGA Tour) contribute points.
        unit_scale = 3.0 if metric_name == "height" else 1.0
        field = _FIELD[metric_name]

        def _points(profile, field=field, scale=unit_scale, sub_order=sub_order):
            prof = REFERENCE_PROFILES.get(profile, {})
            pts = []
            for i, c in enumerate(sub_order):
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
        # Club names are 2-3 chars; keep them horizontal. Only rotate if there
        # genuinely isn't room (measured: available px per tick vs a rough
        # label width), rather than always rotating past 6 clubs.
        px_per_tick = (fig_w_px / 3.0) / max(1, len(sub_order))
        if px_per_tick < 34:
            plt.setp(ax_sub.get_xticklabels(), rotation=45, ha="right")
        ax_sub.tick_params(axis="x", labelsize=max(9, font_scale - 2))

    # Combined legend: zone bands + any benchmark stars, one compact row below
    # the boxplots. (The club legend lives above the arcs.)
    legend_elements = zone_handles + list(bench_handles.values())
    ncol = len(legend_elements)
    try:
        fig.legend(handles=legend_elements, loc="outside lower center", ncol=ncol,
                   fontsize=max(9, font_scale - 1), frameon=False,
                   labelcolor=Colors.TEXT_PRIMARY)
    except (ValueError, TypeError):
        # matplotlib < 3.7 doesn't know "outside" locations
        fig.legend(handles=legend_elements, loc="lower center", ncol=ncol,
                   fontsize=max(9, font_scale - 1), frameon=False,
                   labelcolor=Colors.TEXT_PRIMARY)


def _tint_box_lines(ax, sub_order, club_colors):
    """Color each box's whisker/cap/median lines with its club color.

    seaborn draws, per box, a group of Line2D objects (2 whiskers, 2 caps,
    1 median) in left-to-right club order. We recolor them in that same order
    so every box reads in its club's color instead of flat white.
    """
    lines = ax.lines
    per_box = 6  # 2 whiskers + 2 caps + 1 median + (matplotlib may add fliers=0)
    # seaborn (showfliers=False) emits 5 lines per box; guard by slicing evenly.
    n = len(sub_order)
    if n == 0 or not lines:
        return
    group = max(1, len(lines) // n)
    for i, club in enumerate(sub_order):
        col = club_colors.get(club, Colors.TEXT_PRIMARY)
        for ln in lines[i * group:(i + 1) * group]:
            ln.set_color(col)
