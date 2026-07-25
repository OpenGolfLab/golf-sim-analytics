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
from matplotlib.colors import LinearSegmentedColormap, to_rgba

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


def render(fig, df, club_colors, font_scale, config, **extra):
    if df.empty:
        show_message(fig, "No data matching filters", font_scale)
        return
    unit = extra.get("units", units_mod.YARDS)
    df = units_mod.to_display_frame(df, unit)
    u = units_mod.dist_suffix_lower(unit)  # tooltip suffix ("yds"/"m")
    ax = fig.add_subplot(111)
    color_pref = config["color_var"].get()
    dist_pref = config.get("dist_var").get() if "dist_var" in config else "Carry"
    detail = config.get("detail_var").get() if "detail_var" in config else "In-Depth"

    offline_col = find_col(df, OFFLINE_ALIASES)
    if dist_pref == "Total":
        y_col = find_col(df, TOTAL_ALIASES) or find_col(df, CARRY_ALIASES)
    else:
        y_col = find_col(df, CARRY_ALIASES)

    ax.axvline(x=0, color=Colors.TEXT_MUTED, linestyle="--", linewidth=1.5, alpha=0.6, zorder=0.5)

    if "club" in df.columns and offline_col and y_col:
        order = sorted(df["club"].dropna().unique(), key=get_club_rank)
        if detail == "Simple":
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
        # Launch/descent/spin/smash — what went right or wrong on this shot,
        # each angle flagged against this club's optimal window.
        lines.extend(diagnostic_lines(row, diag_cols, club=row["club"]))
        if "session_date" in row.index and pd.notna(row["session_date"]):
            lines.append(pd.to_datetime(row["session_date"]).strftime("%b %d, %Y"))
        return "\n".join(lines)

    if color_pref == "Date (Timeline)" and "session_date" in df.columns:
        norm, cmap = get_timeline_colormap(df)
        pts_dates = pd.to_numeric(pd.to_datetime(pts["session_date"]))
        sc = ax.scatter(
            pts[offline_col], pts[y_col], c=pts_dates, cmap=cmap, norm=norm,
            s=40, alpha=0.9, edgecolor="black", linewidth=0.5, zorder=1,
        )
        cbar = styled_colorbar(fig, sc, ax, "Oldest → Newest", font_scale)
        cbar.set_ticks([])
    else:
        sc = ax.scatter(
            pts[offline_col], pts[y_col],
            c=[to_rgba(club_colors.get(c, Colors.CLUB_FALLBACK)) for c in pts["club"]],
            s=40, alpha=0.9, edgecolor="black", linewidth=0.5, zorder=1,
        )
        if config.get("num_plots", 1) == 1:
            club_legend(ax, club_colors, order, font_scale, loc=_LEGEND_LOC)

    attach_hover_tooltip(fig, sc, pts, _tooltip, font_scale)

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
