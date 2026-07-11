"""Shared scatter + summary-table rendering for the comparison charts
(Session Comparison and Club Comparison).

Each caller builds a list of ``(label, sub_df, color)`` groups. The left axes
render like the Dispersion chart — offline-vs-carry, a per-group KDE heat map
(once a group has >= 3 shots) plus a scatter and mean crosshair, with yardage
gridlines. The right panel tabulates carry / ball speed / launch / spin (and
smash only when the data has it), one column per group.
"""
from __future__ import annotations

import math

import pandas as pd
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap, to_rgba

from config import Colors
from data.columns import (
    BALL_SPEED_ALIASES, CARRY_ALIASES, CLUB_SPEED_ALIASES, LAUNCH_ANGLE_ALIASES,
    OFFLINE_ALIASES, SMASH_FACTOR_ALIASES, SPIN_RATE_ALIASES, find_col,
)
from ui.charts._shared import style_axes
from ui.empty_state import show_message

# Distinct colors for up to 4 compared groups.
PALETTE = [Colors.INFO, Colors.WARNING, Colors.SUCCESS, "#9B59B6"]
_KDE_MIN_SHOTS = 5  # start heat-mapping a group once it has this many shots


def _short(val, limit=14):
    s = str(val) if val not in (None, "") else "—"
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _header_label(lbl, width=12):
    """Table-column header: wrap a long config label onto two short lines
    instead of one hard truncation. Long labels (brand + club + adapter)
    used to spill into the neighbouring column AND truncate identically —
    "Ventus Blue Dr A1 · 9.0°" and "…C4 · 10.5°" both became "Ventus Bl…",
    so the columns were indistinguishable exactly when comparing mattered.
    The distinctive part of a config label is its tail, so the second line
    (which keeps the tail) is what stays readable."""
    words = str(lbl).split()
    first, rest = "", ""
    for w in words:
        cand = (first + " " + w).strip()
        if not rest and len(cand) <= width:
            first = cand
        else:
            rest = (rest + " " + w).strip()
    if not first:
        return _short(str(lbl), width)
    return first if not rest else first + "\n" + _short(rest, width)


def _smash(df, smash_col, bs_col, cs_col):
    if smash_col:
        s = pd.to_numeric(df[smash_col], errors="coerce")
    elif bs_col and cs_col:
        cs = pd.to_numeric(df[cs_col], errors="coerce")
        s = pd.to_numeric(df[bs_col], errors="coerce") / cs.where(cs > 0)
    else:
        return None
    s = s[(s > 0.5) & (s < 2.0)]
    return float(s.mean()) if not s.empty else None


def render_comparison(fig, groups, font_scale, empty_msg, subtitle=None):
    """groups: list of (label, sub_df, color). Empty groups are dropped."""
    groups = [(lbl, sub, col) for (lbl, sub, col) in groups
              if sub is not None and not sub.empty]
    if not groups:
        show_message(fig, empty_msg, font_scale)
        return

    all_df = pd.concat([g[1] for g in groups], ignore_index=True)
    offline_col = find_col(all_df, OFFLINE_ALIASES)
    carry_col = find_col(all_df, CARRY_ALIASES)
    bs_col = find_col(all_df, BALL_SPEED_ALIASES)
    vla_col = find_col(all_df, LAUNCH_ANGLE_ALIASES)
    spin_col = find_col(all_df, SPIN_RATE_ALIASES)
    smash_col = find_col(all_df, SMASH_FACTOR_ALIASES)
    cs_col = find_col(all_df, CLUB_SPEED_ALIASES)

    gs = fig.add_gridspec(1, 2, width_ratios=[1.3, 1.1])
    ax = fig.add_subplot(gs[0, 0])
    ax_t = fig.add_subplot(gs[0, 1])
    ax_t.set_axis_off()

    ax.axvline(x=0, color=Colors.TEXT_MUTED, linestyle="--", linewidth=1.3, alpha=0.6, zorder=0.5)
    if offline_col and carry_col:
        for i, (lbl, sub, col) in enumerate(groups):
            pts = sub[sub[offline_col].notna() & sub[carry_col].notna()]
            if pts.empty:
                continue
            if len(pts) >= _KDE_MIN_SHOTS:
                r, g, b, _a = to_rgba(col)
                cmap = LinearSegmentedColormap.from_list(
                    f"fade_{i}", [(r, g, b, 0.0), (r, g, b, 0.7)])
                try:
                    sns.kdeplot(data=pts, x=offline_col, y=carry_col, cmap=cmap, fill=True,
                                levels=8, thresh=0.05, warn_singular=False, ax=ax,
                                zorder=0, gridsize=100)
                except Exception:
                    pass
            # limit=18, not the default 14: config labels share a long prefix
            # (brand + club) and only differ at the tail, so truncating at 14
            # produced two identical legend entries.
            ax.scatter(pts[offline_col], pts[carry_col], color=col, alpha=0.75, s=42,
                       edgecolor="black", linewidth=0.4, zorder=1, label=_short(lbl, 18))
            mx, my = pts[offline_col].mean(), pts[carry_col].mean()
            if pd.notna(mx) and pd.notna(my):
                ax.scatter([mx], [my], marker="X", s=220, color=col,
                           edgecolor="white", linewidth=1.4, zorder=5)

        _axes_like_dispersion(ax, all_df, offline_col, carry_col, font_scale)
        handles, _labels = ax.get_legend_handles_labels()
        if handles:
            leg = ax.legend(loc="lower right", fontsize=max(8, font_scale - 2),
                            facecolor=Colors.BG_SURFACE, edgecolor=Colors.BORDER,
                            framealpha=0.92, labelcolor=Colors.TEXT_PRIMARY)
            leg.set_zorder(20)

    _draw_table(ax_t, groups, font_scale, carry_col, bs_col, vla_col, spin_col,
                smash_col, cs_col, subtitle)


def _axes_like_dispersion(ax, all_df, offline_col, carry_col, font_scale):
    # Zoom out for a birds-eye view — more fairway around the shots rather
    # than cropping tight to them.
    max_off = all_df[offline_col].abs().max()
    limit = max(max_off * 1.6, 45) if pd.notna(max_off) else 45
    ax.set_xlim(-limit, limit)

    y_min = max(0, all_df[carry_col].min() - 45)
    y_max = all_df[carry_col].max() + 45
    if pd.notna(y_min) and pd.notna(y_max):
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
        ax.set_yticks(range(y_start, y_end + 25, 25))

    ax.set_xlabel("Offline (Yards)", fontsize=font_scale)
    ax.set_ylabel("Carry (Yards)", fontsize=font_scale)
    style_axes(ax, font_scale, grid=None)
    ax.grid(axis="x", linestyle=":", alpha=0.3, zorder=0)


def _draw_table(ax, groups, font_scale, carry_col, bs_col, vla_col, spin_col,
                smash_col, cs_col, subtitle):
    def mean(sub, col):
        if not col or sub.empty:
            return None
        v = pd.to_numeric(sub[col], errors="coerce").dropna()
        return float(v.mean()) if not v.empty else None

    smash_vals = [_smash(sub, smash_col, bs_col, cs_col) for (_l, sub, _c) in groups]
    # (label, unit, column, format)
    metrics = [
        ("Carry", "yds", carry_col, "{:.0f}"),
        ("Ball Spd", "mph", bs_col, "{:.0f}"),
        ("Launch", "°", vla_col, "{:.1f}"),
        ("Spin", "rpm", spin_col, "{:.0f}"),
    ]
    if any(v is not None for v in smash_vals):  # drop Smash entirely with no data
        metrics.append(("Smash", "", None, "{:.2f}"))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    n = len(groups)
    # Columns packed left (4 fit the width at step 0.19), so 2 sessions sit
    # close together instead of stranded at opposite edges — but with only
    # 1-2 groups there's unused width to the right, so spread wider and give
    # each header room to breathe instead of colliding.
    col0 = 0.42
    step_x = 0.28 if n <= 2 else 0.19
    xs = [col0 + i * step_x for i in range(n)]
    fs = max(8, font_scale - 1)
    hfs = max(7, font_scale - 2)

    # Header row: "Averages" as the first-column label, in line with the config
    # headers (so every value below reads as a per-shot average). Config
    # headers wrap to two lines (see _header_label) rather than colliding.
    y = 0.88
    ax.text(0.0, y, "Averages", color=Colors.TEXT_MUTED, fontsize=hfs,
            fontweight="bold", va="center")
    for (lbl, _sub, col), x in zip(groups, xs):
        ax.text(x, y, _header_label(lbl), color=col, fontsize=hfs, fontweight="bold",
                ha="center", va="center", linespacing=1.25)
    right_edge = max(xs[-1] + step_x / 2, 0.6) if xs else 1.0
    ax.plot([0.0, right_edge], [0.79, 0.79], color=Colors.BORDER, linewidth=1.0)

    # Metric rows.
    y = 0.70
    step = min(0.135, (y - 0.10) / max(len(metrics), 1))
    for name, unit, col, spec in metrics:
        ax.text(0.0, y, name, color=Colors.TEXT_PRIMARY, fontsize=fs, va="center")
        if unit:
            ax.text(0.0, y - 0.052, unit, color=Colors.TEXT_MUTED,
                    fontsize=max(7, font_scale - 4), va="center")
        for j, ((_lbl, sub, _gcol), x) in enumerate(zip(groups, xs)):
            v = smash_vals[j] if name == "Smash" else mean(sub, col)
            ax.text(x, y, "—" if v is None else spec.format(v),
                    color=Colors.TEXT_PRIMARY, fontsize=fs, ha="center", va="center")
        y -= step

    if subtitle:
        ax.text(0.0, max(y, 0.02), subtitle, color=Colors.TEXT_MUTED,
                fontsize=max(7, font_scale - 3), va="center")
