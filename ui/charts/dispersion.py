"""Dispersion — shot-shape density (KDE) per club plus a scatter overlay,
switchable between Carry and Total distance.

Two view modes (the panel's Detail toggle):
  * In-Depth (default): per-club KDE + scatter.
  * Simple: each club collapses to a single mean marker with std whiskers.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import colormaps
from matplotlib.colors import LinearSegmentedColormap, Normalize, to_rgba
from matplotlib.patches import Ellipse

from config import Colors, get_club_rank
from data import units as units_mod
from data.columns import (
    BALL_SPEED_ALIASES, CARRY_ALIASES, OFFLINE_ALIASES, TOTAL_ALIASES, find_col,
)
from ui.charts._shared import (
    attach_hover_tooltip, club_legend, diagnostic_cols, diagnostic_lines,
    get_timeline_colormap, offline_limit, style_axes, styled_colorbar,
)
from ui.empty_state import show_message

# An 11-club legend is a big box, and both corners of a dispersion cloud are
# plausible places for real shots to be — this used to be pinned "lower left",
# where it sat on top of the wedge data. "best" makes matplotlib pick the corner
# with the least overlap for the pattern actually on screen, which varies per
# user (someone who misses everything left needs the opposite corner from
# someone who blocks it right).
_LEGEND_LOC = "best"

NAME = "Dispersion"
CATEGORY = "Metrics"
COLUMN = "right"
HAS_COLOR = True

# ---- Effort (% of max club speed) ------------------------------------------
# Each shot's club speed as a percent of that club's all-time max
# (data/store.py::add_speed_pct). The bands test the "swinging past your
# optimal speed widens the cloud" theory: pick Smooth, then Flat out, and
# watch whether the cloud blooms — or pick Compare bands and see all three
# clouds at once.
#
# Bands are per-club TERCILES of the golfer's own swings, not fixed percent
# cutoffs. Fixed cutoffs (v1.5.0 shipped <90 / 90-97 / 97+) looked sensible
# and were wrong in practice: a consistent golfer's entire history sits
# within ~6-8% of their max, so "under 90% of max" matched almost nothing —
# their easiest swing of the year is still ~94% of max. Relative thirds are
# always populated and self-calibrate to any golfer.
EFFORT_ALL = "All effort"
EFFORT_SMOOTH = "Smooth (easiest ⅓)"
EFFORT_MID = "Cruising (middle ⅓)"
EFFORT_FLAT = "Flat out (hardest ⅓)"
EFFORT_COMPARE = "Compare bands"
EFFORT_OPTIONS = [EFFORT_ALL, EFFORT_SMOOTH, EFFORT_MID, EFFORT_FLAT, EFFORT_COMPARE]
EFFORT_BAND_COLORS = {
    EFFORT_SMOOTH: Colors.INFO,
    EFFORT_MID: Colors.WARNING,
    EFFORT_FLAT: Colors.DANGER,
}


def effort_bands(df: "pd.DataFrame") -> "pd.Series":
    """Label each shot with its per-club effort tercile (or None when the
    shot has no speed_pct). Terciles are computed over the frame it's given,
    so a time-filtered view bands against the swings actually on screen."""
    pct = df["speed_pct"]
    by_club = pct.groupby(df["club"])
    lo = by_club.transform(lambda s: s.quantile(1 / 3))
    hi = by_club.transform(lambda s: s.quantile(2 / 3))
    return pd.Series(
        np.select(
            [pct <= lo, pct <= hi, pct.notna()],
            [EFFORT_SMOOTH, EFFORT_MID, EFFORT_FLAT],
            default=None,
        ),
        index=df.index,
    )

# Color-by modes for the scatter overlay. COLOR_EFFORT paints each shot by its
# effort percent, which shows the speed/dispersion relationship in one view
# without slicing the data thin.
COLOR_CLUB = "Club"
COLOR_TIMELINE = "Date (Timeline)"
COLOR_EFFORT = "Effort (% max)"
COLOR_OPTIONS = [COLOR_CLUB, COLOR_TIMELINE, COLOR_EFFORT]

# Detail modes. "Rings" swaps the KDE heat maps for one solid covariance
# ellipse per group — the group being whatever the Color dropdown says
# (per club / per era / per effort band) — because overlapping clouds stop
# reading past two or three groups, while rings stay legible.
DETAIL_INDEPTH = "In-Depth"
DETAIL_RINGS = "Rings"
DETAIL_SIMPLE = "Simple"
DETAIL_OPTIONS = [DETAIL_INDEPTH, DETAIL_RINGS, DETAIL_SIMPLE]

# Every ring drawn anywhere on this chart contains ~80% of that group's
# shots: the golf-dispersion convention — honest about spread, but one shank
# doesn't balloon it. k = sqrt(chi²₂(0.80)) scales the covariance ellipse.
RING_COVERAGE = 0.80
_RING_K = float(np.sqrt(-2.0 * np.log(1.0 - RING_COVERAGE)))


def _draw_ring(ax, xs, ys, color, linewidth=2.2, zorder=6):
    """Solid covariance ellipse around ~RING_COVERAGE of the points, with a
    small dot at the mean. Needs 3+ points to say anything; returns whether
    it drew."""
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 3:
        return False
    cov = np.cov(x, y)
    vals, vecs = np.linalg.eigh(cov)
    vals = np.maximum(vals, 0.0)[::-1]
    vecs = vecs[:, ::-1]
    angle = float(np.degrees(np.arctan2(vecs[1, 0], vecs[0, 0])))
    ax.add_patch(Ellipse(
        (x.mean(), y.mean()),
        width=2 * _RING_K * np.sqrt(vals[0]),
        height=2 * _RING_K * np.sqrt(vals[1]),
        angle=angle, fill=False, edgecolor=color,
        linewidth=linewidth, zorder=zorder,
    ))
    ax.plot(x.mean(), y.mean(), marker="o", markersize=5, markerfacecolor=color,
            markeredgecolor="black", markeredgewidth=0.6, zorder=zorder + 1)
    return True


def render(fig, df, club_colors, font_scale, config, **extra):
    if df.empty:
        show_message(fig, "No data matching filters", font_scale)
        return
    unit = extra.get("units", units_mod.YARDS)
    df = units_mod.to_display_frame(df, unit)
    u = units_mod.dist_suffix_lower(unit)  # tooltip suffix ("yds"/"m")
    color_pref = config["color_var"].get()
    dist_pref = config.get("dist_var").get() if "dist_var" in config else "Carry"
    detail = config.get("detail_var").get() if "detail_var" in config else DETAIL_INDEPTH
    effort = config.get("effort_var").get() if "effort_var" in config else EFFORT_ALL

    # Effort banding, before any axes exist so its empty states render as
    # a clean message rather than a message over blank axes.
    if effort != EFFORT_ALL:
        if "speed_pct" not in df.columns or not df["speed_pct"].notna().any():
            show_message(
                fig, "No club-speed data for the Effort filter", font_scale,
                hint="Effort needs shots with club speed — CSV exports carry it; "
                     "live-tracked shots may not, and a club needs 10+ readings",
            )
            return
        bands = effort_bands(df)
        if effort == EFFORT_COMPARE:
            df = df[bands.notna()].copy()
            df["effort_band"] = bands
            # One club at a time: bands are relative to each club's own max,
            # and 3 clouds x N clubs is unreadable anyway.
            if df["club"].nunique() > 1:
                show_message(
                    fig, "Compare bands reads one club at a time", font_scale,
                    hint="Pick a single club in the Club filter above — effort "
                         "is relative to each club's own swings",
                )
                return
        else:
            df = df[bands == effort]
        if df.empty:
            show_message(fig, f"No shots in the {effort} band", font_scale,
                         hint="Loosen the Effort filter above")
            return

    # Rings grouped by era or effort band read one club at a time (the same
    # rule as Compare bands): the "trend" of a mixed bag mostly tracks which
    # clubs were hit that day, not how the golfer is trending.
    if detail == DETAIL_RINGS and effort != EFFORT_COMPARE and color_pref != COLOR_CLUB:
        if "club" in df.columns and df["club"].nunique() > 1:
            show_message(fig, "Trend and effort rings read one club at a time",
                         font_scale,
                         hint="Pick a single club in the Club filter above")
            return
        if color_pref == COLOR_EFFORT and (
                "speed_pct" not in df.columns or not df["speed_pct"].notna().any()):
            show_message(
                fig, "No club-speed data for effort rings", font_scale,
                hint="Effort needs shots with club speed — CSV exports carry it; "
                     "live-tracked shots may not, and a club needs 10+ readings",
            )
            return

    ax = fig.add_subplot(111)

    offline_col = find_col(df, OFFLINE_ALIASES)
    if dist_pref == "Total":
        y_col = find_col(df, TOTAL_ALIASES) or find_col(df, CARRY_ALIASES)
    else:
        y_col = find_col(df, CARRY_ALIASES)

    ax.axvline(x=0, color=Colors.TEXT_MUTED, linestyle="--", linewidth=1.5, alpha=0.6, zorder=0.5)

    if "club" in df.columns and offline_col and y_col:
        order = sorted(df["club"].dropna().unique(), key=get_club_rank)
        if effort == EFFORT_COMPARE:
            _render_compare(fig, ax, df, font_scale, offline_col, y_col,
                            dist_pref, detail, u)
        elif detail == DETAIL_RINGS:
            _render_rings(fig, ax, df, club_colors, font_scale, order, offline_col,
                          y_col, dist_pref, color_pref, u)
        elif detail == DETAIL_SIMPLE:
            _render_simple(ax, df, club_colors, font_scale, order, offline_col, y_col,
                           dist_pref, config, u)
        else:
            _render_indepth(fig, ax, df, club_colors, font_scale, order, offline_col, y_col,
                            dist_pref, color_pref, config, u)

        limit = offline_limit(df[offline_col])
        ax.set_xlim(-limit, limit)

        y_min, y_max = max(0, df[y_col].min() - 25), df[y_col].max() + 25
        ax.set_ylim(y_min, y_max)

        y_start = int(math.floor(y_min / 25.0)) * 25
        y_end = int(math.ceil(y_max / 25.0)) * 25
        for yd in range(y_start, y_end + 25, 25):
            if yd <= 0:
                continue
            if yd % 50 == 0:
                ax.axhline(y=yd, color=Colors.GRID_MAJOR, linestyle="-", linewidth=1.2, alpha=0.6, zorder=0.2)
            else:
                ax.axhline(y=yd, color=Colors.GRID, linestyle="-", linewidth=0.8, alpha=0.5, zorder=0.1)
        # Label only the emphasized 50-yd lines. The 25-yd lines above stay —
        # they're useful reference — but numbering every one of them put ~15 tick
        # labels down the axis, which read as clutter and crowded the y-label off
        # the plot. The unlabeled 25s are still obviously the midpoints.
        tick_start = int(math.ceil(y_start / 50.0)) * 50
        ax.set_yticks(range(tick_start, y_end + 50, 50))

    ax.set_xlabel(f"Offline ({units_mod.dist_suffix(unit)})", fontsize=font_scale)
    ax.set_ylabel(f"{dist_pref} ({units_mod.dist_suffix(unit)})", fontsize=font_scale)
    style_axes(ax, font_scale, grid=None)
    ax.grid(axis="x", linestyle=":", alpha=0.3, zorder=0)


# Trend rings: the global Time filter is the era picker. A view of up to 5
# sessions rings each session individually; a longer window pools sessions
# (ordered by date) into up to _ERA_POOL_GROUPS near-equal groups, each
# labeled by its date span — "Jan 12 – Mar 30".
_ERA_MAX_INDIVIDUAL = 5
_ERA_POOL_GROUPS = 4


def _era_groups(df):
    """Split the frame into (label, sub_df) eras, oldest first."""
    if "session_id" not in df.columns or "session_date" not in df.columns:
        return [("All shots", df)]
    dates = pd.to_datetime(df["session_date"], errors="coerce")
    per_session = dates.groupby(df["session_id"]).max()
    ordered = per_session.sort_values(na_position="first").index.tolist()
    if not ordered:
        return [("All shots", df)]

    if len(ordered) <= _ERA_MAX_INDIVIDUAL:
        chunks = [[sid] for sid in ordered]
    else:
        chunks = [list(c) for c in
                  np.array_split(np.array(ordered, dtype=object), _ERA_POOL_GROUPS)]

    def _label(sids, i):
        d0, d1 = per_session[sids[0]], per_session[sids[-1]]
        if pd.isna(d0) or pd.isna(d1):
            return f"Era {i + 1}"
        a, b = d0.strftime("%b %d"), d1.strftime("%b %d")
        return a if a == b else f"{a} – {b}"

    out = []
    for i, sids in enumerate(chunks):
        if not sids:
            continue
        sub = df[df["session_id"].isin(sids)]
        if not sub.empty:
            out.append((_label(sids, i), sub))
    return out


def _render_rings(fig, ax, df, club_colors, font_scale, order, offline_col, y_col,
                  dist_pref, color_pref, u="yds"):
    """One solid 80% covariance ring per group over a faded scatter. The
    group is whatever the Color dropdown says: per club (bag view), per era
    (trend view — watch the centers climb and the rings tighten), or per
    effort band. The legend carries each group's mean distance and offline
    spread, so the trend is numbers as well as geometry."""
    groups = []  # (label, sub, color)
    if color_pref == COLOR_TIMELINE:
        eras = _era_groups(df)
        cmap = colormaps["plasma"]
        n = len(eras)
        for i, (label, sub) in enumerate(eras):
            frac = 0.5 if n == 1 else 0.15 + 0.7 * (i / (n - 1))
            groups.append((label, sub, cmap(frac)))
    elif color_pref == COLOR_EFFORT:
        bands = effort_bands(df)
        for band in (EFFORT_SMOOTH, EFFORT_MID, EFFORT_FLAT):
            sub = df[bands == band]
            if not sub.empty:
                groups.append((band, sub, EFFORT_BAND_COLORS[band]))
    else:
        for club in order:
            sub = df[df["club"] == club]
            if not sub.empty:
                groups.append((str(club), sub, club_colors.get(club, Colors.CLUB_FALLBACK)))

    legend_colors: dict[str, object] = {}
    legend_order: list[str] = []
    for label, sub, color in groups:
        sub = sub[sub[offline_col].notna() & sub[y_col].notna()].reset_index(drop=True)
        if sub.empty:
            continue
        sc = ax.scatter(sub[offline_col], sub[y_col], c=[to_rgba(color)] * len(sub),
                        s=26, alpha=0.35, edgecolor="none", zorder=1)

        def _tooltip(row, label=label):
            club = str(row.get("club", ""))
            lines = [f"{club} — {label}" if club and club != label else label,
                     f"{dist_pref}: {row[y_col]:.0f} {u}",
                     f"Offline: {row[offline_col]:+.1f} {u}"]
            if pd.notna(row.get("speed_pct")):
                lines.append(f"Effort: {row['speed_pct']:.0f}% of your max")
            if "session_date" in row.index and pd.notna(row["session_date"]):
                lines.append(pd.to_datetime(row["session_date"]).strftime("%b %d, %Y"))
            return "\n".join(lines)

        attach_hover_tooltip(fig, sc, sub, _tooltip, font_scale)
        _draw_ring(ax, sub[offline_col], sub[y_col], color)

        spread = sub[offline_col].std()
        spread_txt = f"±{spread:.0f} {u}" if pd.notna(spread) else "n/a"
        leg = f"{label} · {sub[y_col].mean():.0f} {u} · {spread_txt} offline"
        legend_colors[leg] = color
        legend_order.append(leg)

    club_legend(ax, legend_colors, legend_order, font_scale, loc=_LEGEND_LOC)


def _render_compare(fig, ax, df, font_scale, offline_col, y_col, dist_pref, detail, u="yds"):
    """One club, three heat maps — a KDE cloud per effort tercile, so "does
    swinging harder widen my misses?" is answered by shapes AND numbers: the
    legend carries each band's offline spread. Simple detail mode collapses
    each band to a mean marker with std whiskers instead of clouds."""
    bands = [b for b in (EFFORT_SMOOTH, EFFORT_MID, EFFORT_FLAT)
             if (df["effort_band"] == b).any()]
    legend_colors: dict[str, str] = {}
    legend_order: list[str] = []

    for band in bands:
        sub = df[df["effort_band"] == band].reset_index(drop=True)
        color = EFFORT_BAND_COLORS[band]
        c_rgba = to_rgba(color)

        if detail == "Simple":
            mx, my = sub[offline_col].mean(), sub[y_col].mean()
            sx = sub[offline_col].std() if len(sub) > 1 else 0.0
            sy = sub[y_col].std() if len(sub) > 1 else 0.0
            ax.errorbar(mx, my, xerr=sx, yerr=sy, fmt="none", ecolor=color,
                        alpha=0.6, elinewidth=1.6, capsize=4, zorder=2)
            ax.scatter([mx], [my], s=150, c=[c_rgba], edgecolor="black",
                       linewidth=0.8, zorder=3)
        else:
            # One bold ring per band over faded dots — with three bands the
            # KDE clouds this used to draw just muddied each other; the ring
            # IS the dispersion, so it gets the ink.
            sc = ax.scatter(sub[offline_col], sub[y_col], c=[c_rgba] * len(sub),
                            s=28, alpha=0.4, edgecolor="none", zorder=1)
            _draw_ring(ax, sub[offline_col], sub[y_col], color)

            def _tooltip(row, band=band):
                lines = [f"{row['club']} — {band}",
                         f"{dist_pref}: {row[y_col]:.0f} {u}",
                         f"Offline: {row[offline_col]:+.1f} {u}"]
                if pd.notna(row.get("speed_pct")):
                    lines.append(f"Effort: {row['speed_pct']:.0f}% of your max")
                return "\n".join(lines)

            attach_hover_tooltip(fig, sc, sub, _tooltip, font_scale)

        # The legend is where the comparison becomes a number: offline spread
        # per band, so a widening cloud can be read off without squinting.
        spread = sub[offline_col].std()
        spread_txt = f"±{spread:.0f} {u} offline" if pd.notna(spread) else "spread n/a"
        label = f"{band} · {spread_txt} · {len(sub)} shots"
        legend_colors[label] = color
        legend_order.append(label)

    club_legend(ax, legend_colors, legend_order, font_scale, loc=_LEGEND_LOC)


def _render_simple(ax, df, club_colors, font_scale, order, offline_col, y_col, dist_pref, config, u="yds"):
    """Each club as a single mean marker with std whiskers."""
    means = []
    for club in order:
        cd = df[df["club"] == club]
        if cd.empty:
            continue
        mx, my = cd[offline_col].mean(), cd[y_col].mean()
        sx, sy = cd[offline_col].std() or 0.0, cd[y_col].std() or 0.0
        color = club_colors.get(club, Colors.CLUB_FALLBACK)
        ax.errorbar(mx, my, xerr=sx, yerr=sy, fmt="none", ecolor=color, alpha=0.5,
                    elinewidth=1.4, capsize=3, zorder=2)
        means.append({"club": club, "x": mx, "y": my, "n": len(cd)})
    if not means:
        return
    mdf = pd.DataFrame(means)
    sc = ax.scatter(mdf["x"], mdf["y"], s=140,
                    c=[to_rgba(club_colors.get(c, Colors.CLUB_FALLBACK)) for c in mdf["club"]],
                    edgecolor="black", linewidth=0.8, zorder=3)

    def _tooltip(row):
        return f"{row['club']}\nMean {dist_pref}: {row['y']:.0f} {u}\nMean offline: {row['x']:+.1f} {u}\n{int(row['n'])} shots"

    attach_hover_tooltip(ax.figure, sc, mdf, _tooltip, font_scale)
    if config.get("num_plots", 1) == 1:
        club_legend(ax, club_colors, order, font_scale, loc=_LEGEND_LOC)


def _render_indepth(fig, ax, df, club_colors, font_scale, order, offline_col, y_col,
                    dist_pref, color_pref, config, u="yds"):
    """Per-club KDE + scatter."""
    for club in order:
        club_data = df[df["club"] == club]
        if len(club_data) > 3:
            c_rgba = to_rgba(club_colors.get(club, Colors.CLUB_FALLBACK))
            transparent = (c_rgba[0], c_rgba[1], c_rgba[2], 0.0)
            solid = (c_rgba[0], c_rgba[1], c_rgba[2], 0.7)
            custom_cmap = LinearSegmentedColormap.from_list(f"fade_{club}", [transparent, solid])
            try:
                sns.kdeplot(
                    data=club_data, x=offline_col, y=y_col, cmap=custom_cmap, fill=True,
                    levels=8, thresh=0.05, warn_singular=False, ax=ax, zorder=0,
                    gridsize=100,  # half the default: visually identical, ~4x cheaper
                )
            except Exception:
                pass

    # Drop rows the scatter can't place, and reset the index, so the
    # collection's point order is a clean 0..N-1 positional match to `pts`.
    pts = df[df[offline_col].notna() & df[y_col].notna() & df["club"].notna()].reset_index(drop=True)
    bs_col = find_col(df, BALL_SPEED_ALIASES)
    diag_cols = diagnostic_cols(df)

    def _tooltip(row):
        lines = [
            str(row["club"]),
            f"{dist_pref}: {row[y_col]:.0f} {u}",
            f"Offline: {row[offline_col]:+.1f} {u}",
        ]
        if bs_col and pd.notna(row.get(bs_col)):
            lines.append(f"Ball speed: {row[bs_col]:.0f} mph")
        if "speed_pct" in row.index and pd.notna(row["speed_pct"]):
            lines.append(f"Effort: {row['speed_pct']:.0f}% of your max")
        # Launch/descent/spin/smash — what went right or wrong on this shot,
        # each angle flagged against this club's optimal window.
        lines.extend(diagnostic_lines(row, diag_cols, club=row["club"]))
        if "session_date" in row.index and pd.notna(row["session_date"]):
            lines.append(pd.to_datetime(row["session_date"]).strftime("%b %d, %Y"))
        return "\n".join(lines)

    # Which frame the trailing hover attach pairs with `sc` — the effort
    # branch scatters a subset of pts and swaps this to match.
    tooltip_pts = pts

    if color_pref == COLOR_TIMELINE and "session_date" in df.columns:
        norm, cmap = get_timeline_colormap(df)
        pts_dates = pd.to_numeric(pd.to_datetime(pts["session_date"]))
        sc = ax.scatter(
            pts[offline_col], pts[y_col], c=pts_dates, cmap=cmap, norm=norm,
            s=40, alpha=0.9, edgecolor="black", linewidth=0.5, zorder=1,
        )
        cbar = styled_colorbar(fig, sc, ax, "Oldest → Newest", font_scale)
        cbar.set_ticks([])
    elif (color_pref == COLOR_EFFORT and "speed_pct" in pts.columns
          and pts["speed_pct"].notna().any()):
        # Calm blue-grey at an easy swing through gold to brick red at the
        # ceiling — the question this mode answers is "are my wild ones the
        # fast ones?", so heat = effort. Shots with no club speed can't answer
        # it; they stay on the plot as faded grey context rather than
        # silently vanishing.
        known = pts[pts["speed_pct"].notna()].reset_index(drop=True)
        unknown = pts[pts["speed_pct"].isna()].reset_index(drop=True)
        if not unknown.empty:
            sc_u = ax.scatter(
                unknown[offline_col], unknown[y_col], c=Colors.CLUB_FALLBACK,
                s=40, alpha=0.35, edgecolor="black", linewidth=0.5, zorder=1,
            )
            attach_hover_tooltip(fig, sc_u, unknown, _tooltip, font_scale)
        effort_cmap = LinearSegmentedColormap.from_list(
            "effort", [Colors.INFO, Colors.WARNING, Colors.DANGER])
        # Fixed 70-100% range so the colors mean the same thing across
        # sessions and filters; the rare sub-70% shot clamps to the calm end.
        sc = ax.scatter(
            known[offline_col], known[y_col], c=known["speed_pct"],
            cmap=effort_cmap, norm=Normalize(70, 100),
            s=40, alpha=0.9, edgecolor="black", linewidth=0.5, zorder=1.1,
        )
        styled_colorbar(fig, sc, ax, "% of your max club speed", font_scale)
        tooltip_pts = known
    else:
        sc = ax.scatter(
            pts[offline_col], pts[y_col],
            c=[to_rgba(club_colors.get(c, Colors.CLUB_FALLBACK)) for c in pts["club"]],
            s=40, alpha=0.9, edgecolor="black", linewidth=0.5, zorder=1,
        )
        if config.get("num_plots", 1) == 1:
            club_legend(ax, club_colors, order, font_scale, loc=_LEGEND_LOC)

    attach_hover_tooltip(fig, sc, tooltip_pts, _tooltip, font_scale)

    # Click-to-edit: clicking near a shot hands its stable shot_uid to the app
    # to reassign the club or delete it (via the reversible edits sidecar).
    on_click = config.get("on_shot_click")
    if on_click is not None and "shot_uid" in pts.columns and not pts.empty:
        old = getattr(fig, "_shot_pick_cid", None)
        if old is not None:
            try:
                fig.canvas.mpl_disconnect(old)
            except Exception:
                pass

        def _press(event, ax=ax, pts=pts, xcol=offline_col, ycol=y_col, on_click=on_click):
            if event.inaxes is not ax or event.x is None:
                return
            px = ax.transData.transform(pts[[xcol, ycol]].to_numpy(float))
            d = np.hypot(px[:, 0] - event.x, px[:, 1] - event.y)
            i = int(d.argmin())
            if d[i] <= 22:
                row = pts.iloc[i]
                on_click({"shot_uid": row["shot_uid"], "club": str(row.get("club", ""))})
        fig._shot_pick_cid = fig.canvas.mpl_connect("button_press_event", _press)
