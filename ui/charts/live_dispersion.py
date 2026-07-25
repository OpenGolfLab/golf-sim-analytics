"""Live Dispersion — a real-time overlay panel for whichever round is
currently in progress in GSPro: historical shots faded into a light-grey
background for context, with shots detected via live.round_watcher
plotted brightly on top as they land, so dispersion builds up visibly
during a round instead of waiting to export/ingest a CSV afterward.

Toggled by the "Go Live" button in the top bar (ui/app_window.py), not a
sidebar checkbox — see registry.py's docstring for why this dashboard is
excluded from the normal sidebar loop.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from matplotlib.lines import Line2D

from config import Colors, get_club_color, get_club_rank
from data import units as units_mod
from data.columns import CARRY_ALIASES, OFFLINE_ALIASES, find_col
from ui.charts import live_trends, motivation_bars
from ui.charts._shared import (
    attach_hover_tooltip, club_legend, diagnostic_cols, diagnostic_lines,
    offline_limit, style_axes,
)
from ui.empty_state import show_message

NAME = "Live Dispersion"
CATEGORY = "Live"
COLUMN = "left"
HAS_COLOR = False


def _latest_club_speed(live_shots):
    """Most recent live shot's club speed (mph), or None if none carry it."""
    for shot in reversed(live_shots):
        cs = shot.get("clubspeed")
        if cs is not None:
            try:
                return float(cs)
            except (TypeError, ValueError):
                return None
    return None


def _draw_motivation_bars(ax_speed, ax_quality, live_shots, config, font_scale):
    """The two Live-view motivation gauges (see ui/charts/motivation_bars).
    Values come from the live buffer + app-supplied record/quality on the
    panel's config entry."""
    motivation_bars.draw_speed_bar(
        ax_speed, _latest_club_speed(live_shots), config.get("record_club_speed"), font_scale)
    motivation_bars.draw_quality_bar(ax_quality, config.get("latest_quality"), font_scale)


def render(fig, df, club_colors, font_scale, config, **extra):
    # Main dispersion scatter on the left; the right side stacks the
    # active-club session-trends card (top) over the two motivation gauges
    # (bottom, at roughly half the panel height) — see live_trends and
    # motivation_bars. A flat 2x4 gridspec (scatter | spacer | speed |
    # quality) with a uniform wspace: the scatter spans both rows of column
    # 0, the trends card spans columns 2-3 of the top row, and the unused
    # spacer column supplies the extra gap that sets the scatter off from
    # the right stack. (A nested subgridspec was tried for this but
    # collapses to zero-width axes in very small/compact panels.)
    unit = extra.get("units", units_mod.YARDS)
    raw_history_df = df
    df = units_mod.to_display_frame(df, unit)
    u = units_mod.dist_suffix_lower(unit)
    # Column widths: the trends card used to get 2.4 of 9.4 units (~25%) behind
    # a 0.5-unit spacer, which left it jammed against the right edge and too
    # narrow for its own content — "Spread ±29 yds" and a "+22.2 ▲" delta had to
    # share it. Widening the two right-hand columns and halving the spacer pulls
    # the whole stack left and gives the card ~33%, which is what it needs to lay
    # its deltas out without collisions (see live_trends.draw_trends). The
    # scatter loses ~6% of width and gets it back from autoscaling to the data.
    gs = fig.add_gridspec(2, 4, width_ratios=[5.9, 0.25, 1.5, 1.5],
                          height_ratios=[1.05, 1.0], wspace=0.15, hspace=0.4)
    ax = fig.add_subplot(gs[:, 0])
    ax_trends = fig.add_subplot(gs[0, 2:])
    ax_speed = fig.add_subplot(gs[1, 2])
    ax_quality = fig.add_subplot(gs[1, 3])
    ax.axvline(x=0, color=Colors.TEXT_MUTED, linestyle="--", linewidth=1.5, alpha=0.6, zorder=0.5)

    offline_col = find_col(df, OFFLINE_ALIASES)
    carry_col = find_col(df, CARRY_ALIASES)
    has_history = not df.empty and offline_col and carry_col

    if has_history:
        ax.scatter(
            df[offline_col], df[carry_col], s=28, alpha=0.35,
            color=Colors.TEXT_MUTED, edgecolor="none", zorder=1,
        )

    # The live buffer is raw dicts in yards; convert to the display unit so
    # live points, per-club KDEs and tooltips match the historical background.
    _c = lambda v: units_mod.to_display(v, unit)
    live_shots = config.get("live_shots") or []
    live_points = [
        (_c(s["offline"]), _c(s["carry"])) for s in live_shots
        if s.get("offline") is not None and s.get("carry") is not None
    ]

    # Per-club heatmaps once a club has 3+ shots this round — same fade-KDE
    # style and per-club colors (config.CLUB_COLORS, same fixed palette the
    # historical Dispersion chart uses) as the historical Dispersion chart,
    # so a club's color is identical whether it's shown live or after export.
    live_df = units_mod.to_display_frame(
        pd.DataFrame(live_shots) if live_shots else pd.DataFrame(), unit)
    live_clubs = []
    if not live_df.empty and "club" in live_df.columns:
        live_clubs = sorted(live_df["club"].dropna().unique(), key=get_club_rank)
        for club in live_clubs:
            club_colors.setdefault(club, get_club_color(club))
            cd = live_df[(live_df["club"] == club) & live_df["offline"].notna() & live_df["carry"].notna()]
            if len(cd) >= 3:
                r = to_rgba(club_colors[club])
                fade = LinearSegmentedColormap.from_list(
                    f"live_{club}", [(r[0], r[1], r[2], 0.0), (r[0], r[1], r[2], 0.65)])
                try:
                    sns.kdeplot(data=cd, x="offline", y="carry", cmap=fade, fill=True,
                                levels=8, thresh=0.05, warn_singular=False, ax=ax,
                                zorder=1, gridsize=80)
                except Exception:
                    pass

    if live_points:
        live_offline, live_carry = zip(*live_points)
        plotted = [
            s for s in live_shots
            if s.get("offline") is not None and s.get("carry") is not None
        ]
        point_colors = [
            club_colors.get(s.get("club"), get_club_color(s.get("club")))
            for s in plotted
        ]
        sc = ax.scatter(
            live_offline, live_carry, s=70, alpha=0.95, color=point_colors,
            edgecolor="black", linewidth=0.6, zorder=3,
        )
        # Ring around the most recent shot so it's easy to spot as it lands.
        ax.scatter(
            [live_offline[-1]], [live_carry[-1]], s=160, alpha=1.0,
            facecolor="none", edgecolor=Colors.WARNING, linewidth=2, zorder=4,
        )

        # `plotted` is the exact list (and order) behind the scatter points.
        live_rows = units_mod.to_display_frame(
            pd.DataFrame(plotted).reset_index(drop=True), unit)
        live_diag_cols = diagnostic_cols(live_rows)

        def _tooltip(row):
            lines = [str(row.get("club", "?"))]
            if pd.notna(row.get("carry")):
                lines.append(f"Carry: {row['carry']:.0f} {u}")
            if pd.notna(row.get("offline")):
                lines.append(f"Offline: {row['offline']:+.1f} {u}")
            if "ballspeed" in row.index and pd.notna(row.get("ballspeed")):
                lines.append(f"Ball speed: {row['ballspeed']:.0f} mph")
            # Launch/descent/spin/smash — what went right or wrong, flagged
            # against this club's optimal window. currentRound.dat doesn't
            # carry descent angle, so that line just won't appear live.
            lines.extend(diagnostic_lines(row, live_diag_cols, club=row.get("club")))
            return "\n".join(lines)

        attach_hover_tooltip(fig, sc, live_rows, _tooltip, font_scale)

        # Click-to-edit: clicking near a live point hands the underlying shot
        # dict (a live-buffer reference) to the app to reassign its club/delete.
        on_click = config.get("on_shot_click")
        if on_click is not None:
            old = getattr(fig, "_shot_pick_cid", None)
            if old is not None:
                try:
                    fig.canvas.mpl_disconnect(old)
                except Exception:
                    pass

            def _on_press(event, ax=ax, plotted=plotted, on_click=on_click):
                if event.inaxes is not ax or event.x is None:
                    return
                px = ax.transData.transform([(s["offline"], s["carry"]) for s in plotted])
                d = np.hypot(px[:, 0] - event.x, px[:, 1] - event.y)
                i = int(d.argmin())
                if d[i] <= 22:  # within ~22px of a point
                    on_click(plotted[i])
            fig._shot_pick_cid = fig.canvas.mpl_connect("button_press_event", _on_press)
    else:
        live_offline, live_carry = (), ()

    if not has_history and not live_points:
        show_message(
            fig, "Waiting for shots…", font_scale,
            hint="Hit a shot in GSPro — this updates automatically from currentRound.dat",
        )
        return

    all_offline = (list(df[offline_col]) if has_history else []) + list(live_offline)
    all_carry = (list(df[carry_col]) if has_history else []) + list(live_carry)

    if all_offline:
        # This session's shots are must-show: framing the axis off the history
        # percentile is fine, hiding a miss the user just hit is not.
        limit = offline_limit(all_offline, must_show=live_offline)
        ax.set_xlim(-limit, limit)

    if all_carry:
        y_min, y_max = max(0, min(all_carry) - 25), max(all_carry) + 25
        ax.set_ylim(y_min, y_max)

    if config.get("num_plots", 1) == 1:
        extra_handles = []
        if has_history:
            extra_handles.append(Line2D(
                [0], [0], marker="o", linestyle="None", markersize=6,
                markerfacecolor=Colors.TEXT_MUTED, markeredgecolor="none", label="Past shots",
            ))
        if live_clubs:
            club_legend(ax, club_colors, live_clubs, font_scale, loc="upper left", extra_handles=extra_handles)
        elif extra_handles:
            ax.legend(
                handles=extra_handles, loc="upper left", fontsize=max(8, font_scale - 3),
                facecolor=Colors.BG_SURFACE, edgecolor=Colors.BORDER, framealpha=0.85,
                labelcolor=Colors.TEXT_PRIMARY,
            )

    if live_shots:
        last = live_shots[-1]
        bits = [f"Latest: {last.get('club', '?')}"]
        if last.get("carry") is not None:
            bits.append(f"{_c(last['carry']):.0f} {u}")
        if last.get("clubspeed") is not None:
            bits.append(f"{last['clubspeed']:.0f} mph")
        ax.set_title("  ·  ".join(bits), fontsize=max(11, font_scale - 1),
                     color=Colors.TEXT_MUTED, loc="left", pad=8)

    ax.set_xlabel(f"Offline ({units_mod.dist_suffix(unit)})", fontsize=font_scale)
    ax.set_ylabel(f"Carry ({units_mod.dist_suffix(unit)})", fontsize=font_scale)
    style_axes(ax, font_scale)

    _draw_motivation_bars(ax_speed, ax_quality, live_shots, config, font_scale)

    # Active-club session trends, top-right. Baselines come from the FULL
    # practice history (config["trend_history"], in yards — unconverted), not
    # the globally-filtered frame: a Club Filter or Time filter shouldn't be
    # able to erase the club you're currently hitting from its own baseline.
    trend_history = config.get("trend_history")
    if trend_history is None:
        trend_history = raw_history_df
    live_trends.draw_trends(ax_trends, live_shots, trend_history, font_scale, unit)
