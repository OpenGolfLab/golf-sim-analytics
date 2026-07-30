"""Club Gapping — raincloud view: per-club carry density curves over rows of
raw shot dots, all on one shared yardage axis. The same gaps read two ways at
once: where the clouds overlap (two clubs doing the same job), and how the
big median dots space out row to row.

The "Even-Gap Target" overlay survives from the old vertical box view, now
anchored to medians (the big dot IS the median, so the target, connector and
delta all speak the same statistic): a red dot on each club's row marks where
its median carry *would* land if the whole bag were spaced perfectly evenly
between your longest and shortest club, and the yardage delta sits in a
tidy column at the right edge of the plot. Reference-benchmark stars from
the Benchmarks dropdown plot on the row centers.
"""
from __future__ import annotations

import numpy as np
import seaborn as sns
from matplotlib.lines import Line2D
from matplotlib.transforms import blended_transform_factory

from config import Colors, get_club_rank
from data import units as units_mod
from data.columns import CARRY_ALIASES, find_col
from ui.charts._shared import attach_hover_tooltip, carry_points, plot_benchmarks, style_axes
from ui.empty_state import show_message

NAME = "Club Gapping"
CATEGORY = "Metrics"
COLUMN = "right"
HAS_COLOR = False
WIDE = True  # a shared yardage axis across the whole bag — needs full width when paired
BENCHMARK_FIELDS = ("carry",)

_RAIN_JITTER = 0.15  # vertical jitter of the raw-shot dots around their row


def render(fig, df, club_colors, font_scale, config, **extra):
    if df.empty:
        show_message(fig, "No clubs selected", font_scale,
                     hint="Pick clubs from the menu in this panel's header")
        return
    unit = extra.get("units", units_mod.YARDS)
    df = units_mod.to_display_frame(df, unit)
    u = units_mod.dist_suffix_lower(unit)
    y_scale = units_mod.YARD_TO_M if units_mod.is_metric(unit) else 1.0
    carry_col = find_col(df, CARRY_ALIASES)
    if "club" not in df.columns or not carry_col:
        show_message(fig, "No carry data matching filters", font_scale)
        return

    order = sorted(df["club"].dropna().unique(), key=get_club_rank)
    data = df[df["club"].isin(order) & df[carry_col].notna()]
    if data.empty:
        show_message(fig, "No carry data matching filters", font_scale)
        return

    # Densities on top, shot rows below, one shared yardage axis. The density
    # panel keeps a slight edge; the row panel needs its share so a full
    # 10-club bag's rows don't crowd.
    gs = fig.add_gridspec(2, 1, height_ratios=(11, 9), hspace=0.06)
    ax_density = fig.add_subplot(gs[0])
    ax_rows = fig.add_subplot(gs[1], sharex=ax_density)
    legend_handles = []

    # ---- Top panel: one carry density per club -----------------------------
    for club in order:
        sub = data[data["club"] == club]
        color = club_colors.get(club, Colors.CLUB_FALLBACK)
        if len(sub) > 3 and sub[carry_col].nunique() > 1:
            try:
                sns.kdeplot(x=sub[carry_col], ax=ax_density, fill=True, color=color,
                            alpha=0.35, linewidth=1.4, warn_singular=False)
            except Exception:
                continue
            # Name each cloud at its peak — ten unlabeled colors would send
            # the eye bouncing to the rows below to decode them. With
            # fill=True seaborn draws no Line2D, only a fill collection, so
            # the peak is read off the fill polygon's vertices.
            coll = ax_density.collections[-1] if ax_density.collections else None
            if coll is not None and coll.get_paths():
                verts = coll.get_paths()[0].vertices
                k = int(np.argmax(verts[:, 1]))
                ax_density.annotate(
                    club, (float(verts[k, 0]), float(verts[k, 1])),
                    textcoords="offset points", xytext=(0, 4),
                    ha="center", va="bottom", fontsize=max(8, font_scale - 1),
                    color=color, fontweight="bold", zorder=10,
                )
        # Clubs with too few shots for a curve still show below in the row
        # panel; drawing a fake spike here would just lie about the data.

    ax_density.set_ylabel("Shot Frequency", fontsize=font_scale)
    ax_density.set_yticks([])  # density units mean nothing to a golfer
    ax_density.tick_params(labelbottom=False)
    ax_density.set_xlabel("")

    # ---- Bottom panel: a row of raw shots + a solid median dot per club ----
    idx_of = {c: i for i, c in enumerate(order)}
    pts = data.reset_index(drop=True)
    rain_y = (pts["club"].map(idx_of).to_numpy(float)
              + np.random.uniform(-_RAIN_JITTER, _RAIN_JITTER, len(pts)))
    strip_sc = ax_rows.scatter(
        pts[carry_col], rain_y,
        c=[club_colors.get(c, Colors.CLUB_FALLBACK) for c in pts["club"]],
        s=20, alpha=0.55, edgecolor="none", zorder=1,
    )

    stats = data.groupby("club")[carry_col].agg(["mean", "median", "count"])
    medians = stats["median"]
    med_xy = [(medians[c], idx_of[c]) for c in order if c in medians.index]
    ax_rows.scatter(
        [x for x, _ in med_xy], [y for _, y in med_xy],
        c=[club_colors.get(c, Colors.CLUB_FALLBACK) for c in order if c in medians.index],
        s=130, edgecolor="black", linewidth=0.9, zorder=5,
    )

    summary_lines = {}
    for i, c in enumerate(order):
        if c not in stats.index:
            continue
        s = stats.loc[c]
        lines = [
            c,
            f"Shots: {int(s['count'])}",
            f"Typical (median): {s['median']:.0f} {u}",
            f"Avg carry: {s['mean']:.0f} {u}",
        ]
        if i + 1 < len(order) and order[i + 1] in stats.index:
            gap = s["median"] - stats.loc[order[i + 1], "median"]
            lines.append(f"Gap to {order[i + 1]}: {gap:+.0f} {u}")
        summary_lines[c] = lines

    # ---- Even-Gap Target: median-anchored, delta in a right-edge column ----
    ordered_medians = [medians.get(c, np.nan) for c in order]
    finite = [m for m in ordered_medians if np.isfinite(m)]
    targets = []
    # x in axes coords (a clean right-aligned column), y in data coords (the row).
    col_tf = blended_transform_factory(ax_rows.transAxes, ax_rows.transData)
    if len(finite) >= 2:
        ideal = np.linspace(finite[0], finite[-1], len(order))
        for i, cur in enumerate(ordered_medians):
            if not np.isfinite(cur):
                continue
            target = ideal[i]
            targets.append(target)
            ax_rows.plot([target, cur], [i, i], color=Colors.DANGER,
                         linewidth=1.3, alpha=0.9, zorder=3)
            ax_rows.plot(target, i, marker="o", markersize=6, markerfacecolor=Colors.DANGER,
                         markeredgecolor="white", markeredgewidth=1.0, zorder=4)
            delta = cur - target  # + = you carry past the target, - = short of it
            if order[i] in summary_lines:
                summary_lines[order[i]].append(f"vs even spacing: {delta:+.0f} {u}")
            ax_rows.text(
                0.995, i, f"{delta:+.0f}", transform=col_tf,
                ha="right", va="center", fontsize=max(8, font_scale - 1),
                color=Colors.SUCCESS if delta > 0 else Colors.WARNING,
                fontweight="bold", zorder=6, clip_on=False,
            )
        legend_handles.append(Line2D(
            [0], [0], marker="o", linestyle="None", markersize=8,
            markerfacecolor=Colors.DANGER, markeredgecolor="white", markeredgewidth=1.0,
            label="Target Gap",
        ))

    # Benchmark stars sit on each club's row center. carry_points yields
    # (row_index, carry) for the old vertical layout; swapped here because
    # yardage is now the x-axis.
    bench_pts = {
        p: [(carry, i) for (i, carry) in carry_points(p, order, y_scale=y_scale)]
        for p in extra.get("benchmarks", [])
    }
    legend_handles += plot_benchmarks(
        ax_rows, extra.get("benchmarks", []), lambda p: bench_pts.get(p, []), size=95,
    )

    # Hovering any of a club's rain dots shows that club's summary.
    def _tooltip(row):
        return "\n".join(summary_lines.get(str(row["club"]), [str(row["club"])]))

    attach_hover_tooltip(fig, strip_sc, pts, _tooltip, font_scale)

    if legend_handles:
        leg = ax_density.legend(handles=legend_handles, loc="upper right",
                                fontsize=font_scale - 1, facecolor=Colors.BG_SURFACE,
                                edgecolor=Colors.BORDER, framealpha=0.85,
                                labelcolor=Colors.TEXT_PRIMARY)
        leg.set_zorder(20)

    # ---- Shared x-limits hugged to the data ---------------------------------
    # Autoscale spans whatever got drawn; explicit limits keep a 220-yd bag
    # from renting a 350-yd axis. Everything visible participates — shots,
    # even-gap targets, benchmark stars — plus asymmetric padding: a sliver on
    # the left, room on the right for the delta column.
    xs = [float(pts[carry_col].min()), float(pts[carry_col].max()), *targets]
    xs += [x for p_pts in bench_pts.values() for (x, _y) in p_pts]
    lo, hi = min(xs), max(xs)
    rng = max(hi - lo, 1.0)
    ax_rows.set_xlim(lo - max(0.04 * rng, 4.0), hi + max(0.12 * rng, 12.0))

    ax_rows.set_xlabel(f"Carry ({units_mod.dist_suffix(unit)})", fontsize=font_scale)
    ax_rows.set_ylabel("")
    ax_rows.set_yticks(range(len(order)))
    ax_rows.set_yticklabels(order)
    # First club (longest) on top; headroom so jittered dots don't clip.
    ax_rows.set_ylim(len(order) - 1 + 0.55, -0.55)
    style_axes(ax_density, font_scale, grid="x")
    style_axes(ax_rows, font_scale, grid="x")
