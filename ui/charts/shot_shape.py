"""Shot Shape — start direction vs. curve, to separate a face problem from a
path problem at a glance.

The plot the user originally sketched used club path vs. face angle, but this
app's launch monitor never records either (both columns are all-zero). The
ball-flight equivalent, built from data that *is* recorded, is just as
diagnostic:

- x-axis = start direction (HLA). Start line is ~85% determined by face
  angle at impact, so this stands in for "where the face pointed."
- y-axis = curve (spin-axis tilt). Curve comes from the face-to-path
  relationship, so this stands in for "path relative to face."
- color = where the ball actually finished (offline yards), blue→red = L→R.

The two zero-lines split the plane into the four classic miss patterns, so a
cluster's quadrant tells you the cause: e.g. bottom-left = starts left AND
curves left (pull-hook), top-right = starts right AND curves right
(push-slice). All sign conventions verified against the data: +x/+y/+color
all mean rightward.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import Colors
from data.columns import OFFLINE_ALIASES, SPIN_AXIS_ALIASES, START_DIR_ALIASES, find_col
from ui.charts._shared import (
    attach_hover_tooltip, draw_color_square, square_point_colors, style_axes,
)
from ui.empty_state import show_message

NAME = "Shot Shape"
CATEGORY = "Optimization"
COLUMN = "right"
HAS_COLOR = False

# (x_sign, y_sign, label, corner ha/va) — x = start dir, y = curve; +=right.
_QUADRANT_LABELS = [
    (-1, +1, "Pull + Slice", "left", "top"),
    (+1, +1, "Push + Slice", "right", "top"),
    (-1, -1, "Pull + Hook", "left", "bottom"),
    (+1, -1, "Push + Hook", "right", "bottom"),
]

# 2D color field: blue = dead straight (center), warming to the four miss
# corners so any wayward cluster reads warm at a glance.
_STRAIGHT_BLUE = Colors.INFO
_SHAPE_CORNERS = {
    "bl": "#F39C12",  # pull + hook   — amber
    "br": "#E74C3C",  # push + hook   — red
    "tl": "#E67E22",  # pull + slice  — orange
    "tr": "#D35400",  # push + slice  — deep orange
}


def render(fig, df, club_colors, font_scale, config, **extra):
    start_col = find_col(df, START_DIR_ALIASES)
    curve_col = find_col(df, SPIN_AXIS_ALIASES)
    offline_col = find_col(df, OFFLINE_ALIASES)

    if df.empty or not (start_col and curve_col):
        show_message(fig, "Missing start-direction / spin-axis data", font_scale,
                     tone="muted" if df.empty else "error")
        return

    d = df.dropna(subset=[start_col, curve_col]).copy()
    # Rows with no direction data at all are recorded as 0/0 by this monitor;
    # drop those so the plot isn't a fake pile on the origin.
    d = d[(d[start_col] != 0) | (d[curve_col] != 0)]
    if d.empty:
        show_message(fig, "No start-direction data on these shots", font_scale,
                     hint="Older CSV exports didn't record start line / spin axis")
        return

    ax = fig.add_subplot(111)
    x = d[start_col].to_numpy(float)
    y = d[curve_col].to_numpy(float)

    ax.axvline(0, color=Colors.TEXT_MUTED, linestyle="--", linewidth=1.3, alpha=0.7, zorder=1)
    ax.axhline(0, color=Colors.TEXT_MUTED, linestyle="--", linewidth=1.3, alpha=0.7, zorder=1)

    # Symmetric limits so the origin sits dead center and quadrants read evenly;
    # the color square's scale spans exactly to these edges.
    xlim = max(np.abs(x).max(), 2.0) * 1.15
    ylim = max(np.abs(y).max(), 2.0) * 1.15
    ax.set_xlim(-xlim, xlim)
    ax.set_ylim(-ylim, ylim)

    # Color by position in the (start, curve) plane: blue when dead straight,
    # warming toward whichever miss corner. (spin arg = x/start, vla arg = y/curve.)
    colors = square_point_colors(y, x, 0.0, 0.0, ylim, xlim,
                                 center=_STRAIGHT_BLUE, corners=_SHAPE_CORNERS)
    sc = ax.scatter(x, y, c=colors, s=48, alpha=0.9, edgecolor="black",
                    linewidth=0.4, zorder=2)

    # x/y (and offline) are numpy views of `d` in row order, so d maps
    # positionally to the scatter's points for hover lookup.
    def _tooltip(row):
        lines = []
        if "club" in row.index and pd.notna(row.get("club")):
            lines.append(str(row["club"]))
        lines.append(f"Start dir: {row[start_col]:+.1f}°")
        lines.append(f"Curve: {row[curve_col]:+.1f}°")
        if offline_col and pd.notna(row.get(offline_col)):
            lines.append(f"Offline: {row[offline_col]:+.1f} yds")
        if "session_date" in row.index and pd.notna(row["session_date"]):
            lines.append(pd.to_datetime(row["session_date"]).strftime("%b %d, %Y"))
        return "\n".join(lines)

    attach_hover_tooltip(fig, sc, d, _tooltip, font_scale)

    for x_sign, y_sign, label, ha, va in _QUADRANT_LABELS:
        ax.text(
            x_sign * xlim * 0.96, y_sign * ylim * 0.94, label,
            ha=ha, va=va, fontsize=max(11, font_scale - 1), fontweight="bold",
            color=Colors.TEXT_MUTED, alpha=0.8, zorder=1,
        )

    draw_color_square(ax, font_scale, x_label="Start →", y_label="Curve →",
                      title="Blue = straight", center=_STRAIGHT_BLUE, corners=_SHAPE_CORNERS)

    ax.set_xlabel("Start Direction — left ← → right (°)", fontsize=font_scale)
    ax.set_title("Where your shots start vs. how they curve",
                 fontsize=font_scale - 1, color=Colors.TEXT_MUTED, loc="left", pad=10)
    style_axes(ax, font_scale)
