"""Club Gapping — carry distance box+strip plot per club, filtered by the
per-club checkboxes in the sidebar menu (handled upstream in app_window).

Two overlays sit on top of the per-club boxes:
- an "Even-Gap Target" red dot to the right of each box, showing where that
  club's carry *would* land if the whole bag were spaced perfectly evenly
  between your longest and shortest club (a quick read on gap consistency);
- any reference-benchmark stars selected in the top-bar Benchmarks dropdown.
"""
from __future__ import annotations

import numpy as np
import seaborn as sns
from matplotlib.lines import Line2D

from config import Colors, get_club_rank
from data import units as units_mod
from data.columns import CARRY_ALIASES, find_col
from ui.charts._shared import attach_hover_tooltip, carry_points, plot_benchmarks, style_axes
from ui.empty_state import show_message

NAME = "Club Gapping"
CATEGORY = "Metrics"
COLUMN = "right"
HAS_COLOR = False
WIDE = True  # one box per club across the x-axis — needs full width when paired
BENCHMARK_FIELDS = ("carry",)

_GAP_DOT_OFFSET = 0.30  # x-offset (in club-index units) placing the dot right of the box


def render(fig, df, club_colors, font_scale, config, **extra):
    if df.empty:
        show_message(fig, "No clubs selected", font_scale,
                     hint="Pick clubs from the menu in this panel's header")
        return
    unit = extra.get("units", units_mod.YARDS)
    df = units_mod.to_display_frame(df, unit)
    u = units_mod.dist_suffix_lower(unit)
    y_scale = units_mod.YARD_TO_M if units_mod.is_metric(unit) else 1.0
    ax = fig.add_subplot(111)
    carry_col = find_col(df, CARRY_ALIASES)
    legend_handles = []
    # This chart's per-club "+/- vs even spacing" labels (one per club, up to
    # 15) are the first thing to overlap when the panel gets tight. Drop just
    # those text labels once the panel shrinks enough that the font is small —
    # the target dots and connectors stay, and the exact delta is still on each
    # club's hover. font_scale tracks the panel's real geometry.
    compact = font_scale <= 10
    if "club" in df.columns and carry_col:
        order = sorted(df["club"].dropna().unique(), key=get_club_rank)

        # Manual jittered strip (was sns.stripplot): one ax.scatter in a
        # single collection whose point order matches `pts`, so the hover
        # tooltip can map each dot back to its club. Visually the same small
        # jittered dots seaborn drew.
        idx_of = {c: i for i, c in enumerate(order)}
        pts = df[df["club"].isin(order) & df[carry_col].notna()].reset_index(drop=True)
        strip_x = pts["club"].map(idx_of).to_numpy(float) + np.random.uniform(-0.08, 0.08, len(pts))
        strip_sc = ax.scatter(
            strip_x, pts[carry_col],
            c=[club_colors.get(c, Colors.CLUB_FALLBACK) for c in pts["club"]],
            s=25, alpha=0.8, edgecolor="none", zorder=1,
        )
        sns.boxplot(
            data=df, x="club", y=carry_col, order=order, ax=ax, showfliers=False, width=0.25, zorder=2,
            boxprops=dict(facecolor="none", edgecolor=Colors.TEXT_PRIMARY, linewidth=1.2),
            whiskerprops=dict(color=Colors.TEXT_PRIMARY, linewidth=1.2),
            capprops=dict(color=Colors.TEXT_PRIMARY, linewidth=1.2),
            medianprops=dict(color=Colors.TEXT_PRIMARY, linewidth=1.2),
        )

        # Even-Gap Target: mean carry per club, linearly spaced between the
        # longest and shortest club's actual mean — i.e. what each club's
        # carry would be with perfectly consistent gapping across your bag.
        # A red dot marks that target; a capped connector drops to your
        # current mean carry and the yardage gap is annotated.
        stats = df.groupby("club")[carry_col].agg(["mean", "median", "count"])
        means = stats["mean"]

        # Per-club summary text shown on hover (aggregate stats, not per-shot,
        # which is what a gapping view is actually about). The even-gap Δ line
        # is appended below, where that number is computed for the overlay.
        summary_lines = {}
        for i, c in enumerate(order):
            if c not in stats.index:
                continue
            s = stats.loc[c]
            lines = [
                c,
                f"Shots: {int(s['count'])}",
                f"Avg carry: {s['mean']:.0f} {u}",
                f"Typical (median): {s['median']:.0f} {u}",
            ]
            if i + 1 < len(order) and order[i + 1] in stats.index:
                gap = s["mean"] - stats.loc[order[i + 1], "mean"]
                lines.append(f"Gap to {order[i + 1]}: {gap:+.0f} {u}")
            summary_lines[c] = lines

        ordered_means = [means.get(c, np.nan) for c in order]
        finite = [m for m in ordered_means if np.isfinite(m)]
        if len(finite) >= 2:
            ideal = np.linspace(finite[0], finite[-1], len(order))
            cap = 0.07  # half-width of the connector's end cap, in club-index units
            for i, cur in enumerate(ordered_means):
                if not np.isfinite(cur):
                    continue
                x = i + _GAP_DOT_OFFSET
                target = ideal[i]
                # Capped connector from the even-gap target dot down/up to
                # your current mean carry.
                ax.plot([x, x], [target, cur], color=Colors.DANGER, linewidth=1.4, zorder=4)
                ax.plot([x - cap, x + cap], [cur, cur], color=Colors.DANGER, linewidth=1.4, zorder=4)
                ax.plot(x, target, marker="o", markersize=6, markerfacecolor=Colors.DANGER,
                        markeredgecolor="white", markeredgewidth=1.0, zorder=5)
                delta = cur - target  # + = you carry past the target, - = short of it
                if order[i] in summary_lines:
                    summary_lines[order[i]].append(f"vs even spacing: {delta:+.0f} {u}")
                if abs(delta) >= 0.5 and not compact:
                    ax.annotate(
                        f"{delta:+.0f}", (x, (target + cur) / 2),
                        textcoords="offset points", xytext=(6, 0),
                        ha="left", va="center", fontsize=max(8, font_scale - 1),
                        color=Colors.SUCCESS if delta > 0 else Colors.WARNING,
                        fontweight="bold", zorder=6,
                    )
            legend_handles.append(Line2D(
                [0], [0], marker="o", linestyle="None", markersize=8,
                markerfacecolor=Colors.DANGER, markeredgecolor="white", markeredgewidth=1.0,
                label="Target Gap",
            ))

        # Benchmark stars sit just left of each box (the even-gap target dot
        # is on the right), drawn a bit larger than the default marker.
        legend_handles += plot_benchmarks(
            ax, extra.get("benchmarks", []),
            lambda p: carry_points(p, order, x_of_index=lambda i, c: i - _GAP_DOT_OFFSET,
                                   y_scale=y_scale),
            size=95,
        )

        # Hovering any of a club's strip dots shows that club's summary.
        def _tooltip(row):
            return "\n".join(summary_lines.get(str(row["club"]), [str(row["club"])]))

        attach_hover_tooltip(fig, strip_sc, pts, _tooltip, font_scale)

    if legend_handles:
        leg = ax.legend(handles=legend_handles, loc="upper right", fontsize=font_scale - 1,
                        facecolor=Colors.BG_SURFACE, edgecolor=Colors.BORDER,
                        framealpha=0.85, labelcolor=Colors.TEXT_PRIMARY)
        leg.set_zorder(20)

    ax.set_xlabel("", fontsize=font_scale)
    ax.set_ylabel(f"Carry ({units_mod.dist_suffix(unit)})", fontsize=font_scale)
    style_axes(ax, font_scale, grid="y")
