"""Speed Training — a driver clubhead-speed development dashboard.

Four panels, all driver-only:
  * Metrics — top-10% "cruising" speed (ignores warm-up drag) + the
    speed-to-smash penalty (how much smash drops per +1 mph of club speed).
  * Velocity vs Efficiency — club speed vs ball speed, colored by smash, with
    smash isolines (1.40 / 1.45 / 1.50) so the "break point" where strike
    quality falls off is visible.
  * Fatigue Curve — club speed by shot number within the latest session, with
    a 5-shot rolling average, to spot speed decay from overtraining.
  * Macro Progression — per-session club-speed boxplots over time; the box
    should physically climb the y-axis across weeks.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import Colors, normalize_club_name
from data.columns import BALL_SPEED_ALIASES, CLUB_SPEED_ALIASES, find_col
from ui.charts._shared import attach_label_tooltip, style_axes
from ui.empty_state import show_message

NAME = "Speed Training"
CATEGORY = "Speed Training"
COLUMN = "left"
HAS_COLOR = False

_ISOLINES = [1.40, 1.45, 1.50]
_MAX_SESSIONS = 10
_GOLD = "#F4B740"  # dashboard accent — a rich gold that pops on the dark theme


def render(fig, df, club_colors, font_scale, config, **extra):
    cs_col = find_col(df, CLUB_SPEED_ALIASES)
    bs_col = find_col(df, BALL_SPEED_ALIASES)
    if df.empty or "club" not in df.columns or not cs_col:
        show_message(fig, "No club-speed data yet", font_scale,
                     hint="Speed Training needs driver shots with club speed "
                          "(live-tracked range shots or CSV imports).")
        return

    dr = df[df["club"].map(lambda c: normalize_club_name(c) == "Dr")].copy()
    dr[cs_col] = pd.to_numeric(dr[cs_col], errors="coerce")
    dr = dr[dr[cs_col].notna()]
    if dr.empty:
        show_message(fig, "No driver shots with club speed", font_scale)
        return

    color = _GOLD
    # Tighter vertical gap between the two rows (~half of before) so each of the
    # four panels gets a little more height.
    gs = fig.add_gridspec(2, 2, width_ratios=[1.0, 1.25], hspace=0.22, wspace=0.28)
    _metrics_panel(fig.add_subplot(gs[0, 0]), dr, cs_col, bs_col, color, font_scale)
    _velocity_efficiency(fig.add_subplot(gs[0, 1]), dr, cs_col, bs_col, font_scale)
    _fatigue_curve(fig.add_subplot(gs[1, 0]), dr, cs_col, color, font_scale)
    _macro_progression(fig.add_subplot(gs[1, 1]), dr, cs_col, color, font_scale)


def _metrics_panel(ax, dr, cs_col, bs_col, color, font_scale):
    ax.set_axis_off()
    cs = dr[cs_col].dropna()
    cruise = float(cs[cs >= cs.quantile(0.9)].mean()) if len(cs) >= 5 else float(cs.max())

    penalty = None
    if bs_col:
        bs = pd.to_numeric(dr[bs_col], errors="coerce")
        m = cs.notna() & bs.notna()
        x, sm = cs[m], (bs[m] / cs[m].where(cs[m] > 0))
        valid = (sm > 0.5) & (sm < 2.0)
        x, sm = x[valid], sm[valid]
        if len(x) >= 8 and x.nunique() > 1:
            penalty = float(np.polyfit(x, sm, 1)[0])

    label_fs = max(8, font_scale - 2)
    value_fs = max(9, font_scale - 1)

    # "Cruising speed" (the top-10% mean) is baked into the title now, with the
    # old explanatory caption line dropped — the definition moves to a hover
    # tooltip instead (attached below).
    ax.text(0.0, 0.95, "DRIVER CRUISING SPEED", color=Colors.TEXT_MUTED,
            fontsize=label_fs, fontweight="bold", va="top")
    ax.text(0.0, 0.74, f"{cruise:.1f}", color=color, fontsize=font_scale + 10,
            fontweight="bold", va="center", ha="left")
    # "mph" sits on the same line, just right of the big number (a unit label),
    # with the following stat rows left well below it — see the gap before y.
    ax.text(0.40, 0.72, "mph", color=Colors.TEXT_MUTED, fontsize=label_fs,
            va="center", ha="left")
    # Hover target: an invisible scatter grid over the title + number band
    # (mplcursors only hit-tests collections, not bare Text). Hovering the
    # label or the big number surfaces the definition of "cruising speed".
    gx = np.linspace(0.03, 0.62, 7)
    gy = np.array([0.93, 0.83, 0.74])
    hit = ax.scatter(np.repeat(gx, len(gy)), np.tile(gy, len(gx)),
                     s=1200, alpha=0, zorder=5)
    attach_label_tooltip(
        ax.figure, hit,
        "Cruising speed = the average of your top 10% fastest\n"
        "driver swings — your repeatable speed ceiling, not\n"
        "one-off mishits or warm-up swings.",
        font_scale,
    )

    rows = [("Average swing", f"{cs.mean():.1f} mph"),
            ("Fastest", f"{cs.max():.1f} mph")]
    if penalty is not None:
        rows.append(("Strike quality per +1 mph", f"{penalty:+.3f}"))
    y = 0.44
    for label, val in rows:
        ax.text(0.0, y, label, color=Colors.TEXT_MUTED, fontsize=label_fs, va="center")
        ax.text(1.0, y, val, color=Colors.TEXT_PRIMARY, fontsize=value_fs,
                fontweight="bold", ha="right", va="center")
        y -= 0.15
    if penalty is not None and penalty < 0:
        ax.text(0.0, y, "Smash drops as you swing faster —\nfind your playable ceiling.",
                color=Colors.WARNING, fontsize=label_fs, va="top")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)


def _velocity_efficiency(ax, dr, cs_col, bs_col, font_scale):
    if not bs_col:
        ax.text(0.5, 0.5, "Missing ball speed", ha="center", va="center",
                color=Colors.TEXT_MUTED, fontsize=font_scale - 1)
        ax.set_axis_off()
        return
    cs = dr[cs_col]
    bs = pd.to_numeric(dr[bs_col], errors="coerce")
    m = cs.notna() & bs.notna() & (cs > 0)
    x, y = cs[m], bs[m]
    if x.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", color=Colors.TEXT_MUTED)
        ax.set_axis_off()
        return
    smash = (y / x).clip(1.2, 1.55)
    sc = ax.scatter(x, y, c=smash, cmap="RdYlGn", vmin=1.30, vmax=1.52,
                    s=32, edgecolor="black", linewidth=0.3, zorder=3)
    xr = np.array([x.min() - 1, x.max() + 1])
    for sf in _ISOLINES:
        ax.plot(xr, sf * xr, "--", color=Colors.TEXT_MUTED, linewidth=1.0, alpha=0.7, zorder=1)
        ax.text(xr[1], sf * xr[1], f" {sf:.2f}", color=Colors.TEXT_MUTED,
                fontsize=max(9, font_scale - 3), va="center")
    ax.set_xlim(xr)
    ax.set_title("Speed vs. Strike Quality", fontsize=font_scale, color=Colors.TEXT_PRIMARY, pad=6)
    ax.set_xlabel("Club Speed (mph)", fontsize=max(11, font_scale - 1))
    ax.set_ylabel("Ball Speed (mph)", fontsize=max(11, font_scale - 1))
    style_axes(ax, font_scale - 1)


def _fatigue_curve(ax, dr, cs_col, color, font_scale):
    s = dr
    if "session_id" in dr.columns and "session_date" in dr.columns:
        dates = pd.to_datetime(dr["session_date"], errors="coerce")
        if dates.notna().any():
            latest = dates.groupby(dr["session_id"]).max().idxmax()
            s = dr[dr["session_id"] == latest]
    cs = s[cs_col].reset_index(drop=True)
    x = range(1, len(cs) + 1)
    ax.plot(x, cs, marker="o", markersize=3, linewidth=0.8, color=color, alpha=0.4, zorder=2)
    if len(cs) >= 2:
        roll = cs.rolling(5, min_periods=1).mean()
        ax.plot(x, roll, color=color, linewidth=2.2, zorder=3, label="5-shot average")
        # Upper-left is clear (club speed ramps up left→right), so the legend
        # sits there instead of covering the early shots.
        ax.legend(loc="upper left", fontsize=max(10, font_scale - 2), facecolor=Colors.BG_SURFACE,
                  edgecolor=Colors.BORDER, framealpha=0.9, labelcolor=Colors.TEXT_PRIMARY)
    ax.set_title("Fatigue Curve", fontsize=font_scale, color=Colors.TEXT_PRIMARY, pad=6)
    ax.set_xlabel("Shot number", fontsize=max(11, font_scale - 1))
    ax.set_ylabel("Club Speed (mph)", fontsize=max(11, font_scale - 1))
    style_axes(ax, font_scale - 1, grid="y")


def _macro_progression(ax, dr, cs_col, color, font_scale):
    if "session_id" not in dr.columns or "session_date" not in dr.columns:
        ax.text(0.5, 0.5, "No dated sessions", ha="center", va="center", color=Colors.TEXT_MUTED)
        ax.set_axis_off()
        return
    dates = pd.to_datetime(dr["session_date"], errors="coerce")
    order = dates.groupby(dr["session_id"]).max().dropna().sort_values()
    sids = list(order.index)[-_MAX_SESSIONS:]
    data, labels = [], []
    for sid in sids:
        v = dr.loc[dr["session_id"] == sid, cs_col].dropna()
        if not v.empty:
            data.append(v.to_numpy())
            labels.append(order[sid].strftime("%b %d"))
    if not data:
        ax.text(0.5, 0.5, "Not enough sessions", ha="center", va="center", color=Colors.TEXT_MUTED)
        ax.set_axis_off()
        return
    bp = ax.boxplot(data, positions=range(len(data)), widths=0.6, showfliers=False,
                    patch_artist=True)
    for box in bp["boxes"]:
        box.set(facecolor=color, alpha=0.35, edgecolor=Colors.TEXT_PRIMARY, linewidth=1.1)
    for part in ("whiskers", "caps", "medians"):
        for artist in bp[part]:
            artist.set(color=Colors.TEXT_PRIMARY, linewidth=1.1)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=max(10, font_scale - 3))
    ax.set_title("Speed by Session", fontsize=font_scale, color=Colors.TEXT_PRIMARY, pad=6)
    ax.set_ylabel("Club Speed (mph)", fontsize=max(11, font_scale - 1))
    style_axes(ax, font_scale - 1, grid="y")
