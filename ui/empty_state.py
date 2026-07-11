"""
Consistent empty / awaiting-data / error states for chart panels.

One helper, one look, reused everywhere. Supports an optional muted hint
line under the main message (e.g. which folder live mode is watching).
"""
from __future__ import annotations

from matplotlib.figure import Figure

from config import Colors


def show_message(fig: Figure, message: str, font_scale: float, tone: str = "muted",
                 hint: str | None = None) -> None:
    """Clear the figure and show a centered status message.

    tone: "muted" (no data yet / awaiting data) or "error" (something's wrong).
    hint: optional smaller second line with next-step guidance.
    """
    color = Colors.DANGER if tone == "error" else Colors.TEXT_PRIMARY
    fig.clf()
    ax = fig.add_subplot(111)
    ax.set_axis_off()
    # wrap=True so long hint/message lines fold at the panel edge instead of
    # running off narrow figures (e.g. a 3-4 panel grid).
    if hint:
        ax.text(0.5, 0.55, message, ha="center", va="center", color=color,
                fontsize=font_scale + 1, wrap=True)
        ax.text(0.5, 0.45, hint, ha="center", va="center",
                color=Colors.TEXT_MUTED, fontsize=max(8, font_scale - 2), wrap=True)
    else:
        ax.text(0.5, 0.5, message, ha="center", va="center", color=color,
                fontsize=font_scale, wrap=True)
