"""
Motivational meter bars for the Live view (task 5).

Two vertical "how am I doing right now" gauges drawn beside the live
dispersion scatter, updated as each shot lands:

- Club-speed bar: the top of the track is your all-time record club speed, so
  the fill visibly chases your PB. The fill color heats up as you approach it
  — green when you're well under, ramping through blue and yellow to red as
  you close in — and busts into bright pink, overfilling above the record
  line with a "+X mph" callout, when you beat it.
- Shot-quality bar: the last shot's 0-100 Shot Quality Score, red at 0 ramping
  to green at 100.

Kept deliberately self-contained (no app state) — the caller passes plain
numbers, so these are trivial to unit-test and reuse.
"""
from __future__ import annotations

import numpy as np
from matplotlib.colors import LinearSegmentedColormap

from config import Colors

# Club-speed "heat" ramp: cool green far from the record, red as it nears it.
# (Deliberately not the usual green=good mapping — here hot = close to your PB.)
_SPEED_CMAP = LinearSegmentedColormap.from_list(
    "speed_heat",
    [(0.0, "#2ECC71"), (0.40, "#3498DB"), (0.72, "#F1C40F"), (1.0, "#E74C3C")],
)
_OVER_RECORD = "#FF3FC7"  # bright pink — a new record

# Shot-quality ramp: red (0) -> yellow (50) -> green (100).
_QUALITY_CMAP = LinearSegmentedColormap.from_list(
    "shot_quality", [(0.0, "#E74C3C"), (0.5, "#F1C40F"), (1.0, "#2ECC71")],
)

_TRACK_COLOR = Colors.BG_HOVER
_BAR_WIDTH = 0.5


def _prime_axis(ax, top: float, title: str, font_scale: float) -> None:
    """Shared chrome: a faint full-height track, a clean single-bar axis."""
    ax.bar(0, top, width=_BAR_WIDTH, color=_TRACK_COLOR, edgecolor="none", zorder=0)
    ax.set_xlim(-0.6, 0.6)
    ax.set_ylim(0, top)
    ax.set_xticks([])
    ax.set_title(title, fontsize=max(10, font_scale - 2), color=Colors.TEXT_MUTED, pad=8)
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(Colors.BORDER)
    ax.tick_params(axis="y", labelsize=max(8, font_scale - 3), colors=Colors.TEXT_MUTED)


def draw_speed_bar(ax, value, record, font_scale: float) -> None:
    """Club-speed gauge. `value` = the latest shot's club speed (mph, or None),
    `record` = all-time best club speed (mph, or None)."""
    if not value or value <= 0:
        _prime_axis(ax, top=max(record or 100.0, 1.0), title="Club\nSpeed", font_scale=font_scale)
        ax.text(0, (record or 100.0) * 0.5, "waiting\nfor a\nswing", ha="center", va="center",
                color=Colors.TEXT_MUTED, fontsize=max(8, font_scale - 3))
        return

    record = record if (record and record > 0) else value
    over = value > record
    top = max(record, value) * 1.08  # headroom so the top label/line isn't clipped

    _prime_axis(ax, top=top, title="Club\nSpeed", font_scale=font_scale)

    frac = min(value / record, 1.0)
    color = _OVER_RECORD if over else _SPEED_CMAP(frac)
    ax.bar(0, value, width=_BAR_WIDTH, color=color, edgecolor="black", linewidth=0.6, zorder=2)

    # Record (PB) marker line across the track.
    ax.axhline(record, color=Colors.TEXT_ACTIVE, linestyle="--", linewidth=1.3, zorder=3)
    ax.text(0.42, record, "PB", ha="left", va="center", color=Colors.TEXT_ACTIVE,
            fontsize=max(8, font_scale - 3))

    if over:
        # Emphasize the overshoot: a pink cap above the line + the delta.
        ax.text(0, value + (top - value) * 0.35, f"+{value - record:.1f}", ha="center",
                va="bottom", color=_OVER_RECORD, fontsize=max(10, font_scale - 1),
                fontweight="bold")

    # Current value label inside the bar top.
    ax.text(0, value * 0.5, f"{value:.0f}\nmph", ha="center", va="center",
            color=Colors.TEXT_ON_LIGHT if not over else Colors.TEXT_ACTIVE,
            fontsize=max(9, font_scale - 2), fontweight="bold")


def draw_quality_bar(ax, value, font_scale: float) -> None:
    """Shot-quality gauge, 0-100. `value` = latest shot's score (or None)."""
    _prime_axis(ax, top=100.0, title="Shot\nQuality", font_scale=font_scale)
    ax.set_yticks([0, 25, 50, 75, 100])

    if value is None or (isinstance(value, float) and np.isnan(value)):
        ax.text(0, 50, "no\nscore\nyet", ha="center", va="center",
                color=Colors.TEXT_MUTED, fontsize=max(8, font_scale - 3))
        return

    value = float(max(0.0, min(100.0, value)))
    color = _QUALITY_CMAP(value / 100.0)
    ax.bar(0, value, width=_BAR_WIDTH, color=color, edgecolor="black", linewidth=0.6, zorder=2)
    ax.text(0, value + 3, f"{value:.0f}", ha="center", va="bottom",
            color=Colors.TEXT_PRIMARY, fontsize=max(10, font_scale - 1), fontweight="bold")
