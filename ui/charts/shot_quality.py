"""Shot Quality — the per-shot 0-100 quality score (data.analytics.scoring)
averaged per session and plotted over time, so improving contact/consistency
shows up as a rising line.

What the score measures shifts with what the shot was trying to do — strike
plus proximity when there was a target to hit, strike plus repeatability when
there wasn't. The scorer decides that per shot; this chart just averages it.
"""
from __future__ import annotations

import pandas as pd

from config import Colors
from data.analytics import ShotScorer
from ui.charts._shared import attach_hover_tooltip, style_axes
from ui.empty_state import show_message

NAME = "Shot Quality"
CATEGORY = "Metrics"
COLUMN = "right"
HAS_COLOR = False
WIDE = True  # a per-session trend line along the x-axis — needs full width


def render(fig, df, club_colors, font_scale, config, **extra):
    ax = fig.add_subplot(111)

    if df.empty or "club" not in df.columns:
        show_message(fig, "No shot data", font_scale,
                     tone="muted" if df.empty else "error")
        return

    scored = df.assign(_score=ShotScorer().score(df)).dropna(subset=["_score"])
    if scored.empty:
        show_message(fig, "Not enough data to score shots", font_scale,
                     hint="Scoring needs contact data (smash, launch, spin) or "
                          "carry and offline for each club.")
        return

    if "session_id" in scored.columns:
        date_col = "session_date" if "session_date" in scored.columns else "session_id"
        g = (scored.groupby("session_id")
             .agg(score=("_score", "mean"), shots=("_score", "size"),
                  when=(date_col, "max"))
             .sort_values("when")
             .reset_index(drop=True))
    else:  # no session structure — collapse to a single point
        g = pd.DataFrame({"score": [scored["_score"].mean()],
                          "shots": [len(scored)], "when": [pd.NaT]})

    x = list(range(len(g)))
    ax.plot(x, g["score"], color=Colors.SUCCESS, linewidth=2, zorder=2)
    sc = ax.scatter(x, g["score"], s=60, color=Colors.SUCCESS,
                    edgecolor="black", linewidth=0.5, zorder=3)

    def _tooltip(row):
        lines = []
        if pd.notna(row["when"]):
            lines.append(pd.to_datetime(row["when"]).strftime("%b %d, %Y"))
        lines.append(f"Quality: {row['score']:.0f} / 100")
        lines.append(f"{int(row['shots'])} shots")
        return "\n".join(lines)

    attach_hover_tooltip(fig, sc, g, _tooltip, font_scale)

    ax.set_ylim(0, 100)
    ax.set_xlim(-0.5, max(len(g) - 0.5, 0.5))
    ax.set_xticks(x)
    labels = [pd.to_datetime(w).strftime("%b %d") if pd.notna(w) else "" for w in g["when"]]
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Quality Score (0–100)", fontsize=font_scale)
    ax.set_xlabel("Session", fontsize=font_scale)
    ax.set_title("How well are your shots doing their job?", fontsize=font_scale - 1,
                 color=Colors.TEXT_MUTED, loc="left", pad=10)
    style_axes(ax, font_scale, grid="y")
