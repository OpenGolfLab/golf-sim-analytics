"""On-Course Play — a scoring dashboard for rounds played on the course
(as opposed to the practice range).

Reads the on-course rounds the app keeps separate from practice data (see
data/on_course.py), and summarizes them the way a golfer actually thinks about
a round: score vs par, birdies and eagles, blow-up holes, and longest drives.

Three panels:
  * Scorecard KPIs — rounds/holes played, birdies & eagles, longest drive,
    best round.
  * Scoring breakdown — how every completed hole shook out (eagle → double+).
  * Full round scores — each completed 18-hole round's score to par over time
    (partial rounds are excluded here; they still count in the totals above).

Only completed (holed-out) holes count toward scoring; a last hole abandoned
when the round ended is ignored rather than logged as an unrealistic score.

Rounds that used a mulligan are marked with an asterisk here and in the KPI
tiles. They still count toward every total on this dashboard — they're rounds
you played — but they're excluded from the Sim Handicap, because the strokes a
player re-hits are exactly the ones that would have cost them (see
data.on_course and data.analytics.handicap).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import Colors
from data import on_course
from data import units as units_mod
from ui.charts._shared import style_axes
from ui.empty_state import show_message

NAME = "On-Course Play"
CATEGORY = "On Course"
COLUMN = "left"
HAS_COLOR = False

# Good → bad, so the scoring breakdown reads as one intuitive ramp.
_BUCKET_COLORS = {
    "Eagle+": "#20E3B2",       # bright mint — rare and great
    "Birdie": Colors.SUCCESS,  # green
    "Par": Colors.INFO,        # neutral blue
    "Bogey": Colors.WARNING,   # amber
    "Double+": Colors.DANGER,  # red
}
_ACCENT = "#20E3B2"

# Per-round score bars (bottom subplot): show at most this many recent rounds,
# left-anchored, and reserve at least this many slots so a few rounds still
# render as narrow bars rather than stretching across the whole panel.
_MAX_ROUND_BARS = 10
_MIN_ROUND_SLOTS = 6


def _mark(row) -> str:
    """The mulligan asterisk for one round row, or an empty string."""
    count = pd.to_numeric(row.get("mulligans", 0), errors="coerce")
    return on_course.MULLIGAN_MARK if pd.notna(count) and count > 0 else ""


def render(fig, df, club_colors, font_scale, config, **extra):
    rounds = on_course.round_summary(df)
    if rounds.empty:
        show_message(
            fig, "No on-course rounds yet", font_scale,
            hint="Play a round in GSPro (not the practice range) — on-course "
                 "rounds are tracked and scored here automatically.",
        )
        return

    # Taller top row so the scorecard tiles (KPI + breakdown) get real vertical
    # room and read as a matched pair; the per-round bars sit below.
    gs = fig.add_gridspec(2, 2, height_ratios=[1.35, 1.0], width_ratios=[1.05, 1.0],
                          hspace=0.5, wspace=0.3)
    _kpi_panel(fig.add_subplot(gs[0, 0]), rounds, font_scale,
               extra.get("units", units_mod.YARDS))
    _scoring_breakdown(fig.add_subplot(gs[0, 1]), rounds, font_scale)
    _round_scores(fig.add_subplot(gs[1, :]), rounds, font_scale)


def _kpi_panel(ax, rounds, font_scale, unit=units_mod.YARDS):
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    n_rounds = len(rounds)
    total_holes = int(rounds["holes"].sum())
    birdies = int(rounds["Birdie"].sum())
    eagles = int(rounds["Eagle+"].sum())
    ld = rounds["longest_drive"].dropna()
    longest = (f"{units_mod.to_display(ld.max(), unit):.0f} {units_mod.dist_suffix_lower(unit)}"
               if not ld.empty else "—")
    # Best round by score per hole (fair across partial rounds), shown as its
    # raw to-par with hole count, asterisked if it took a mulligan to get there.
    per_hole = rounds["to_par"] / rounds["holes"].where(rounds["holes"] > 0)
    best = rounds.loc[per_hole.idxmin()] if per_hole.notna().any() else None
    best_txt = "—"
    if best is not None:
        best_txt = f"{best['to_par']:+d} · {int(best['holes'])}h{_mark(best)}"

    label_fs = max(9, font_scale - 1)
    # Header row: a big rounds count with "rounds played" in small print on the
    # same line (e.g. "2 rounds played") — the panel title was redundant with
    # the dashboard name, so it's dropped.
    ax.text(0.0, 0.90, f"{n_rounds}", color=_ACCENT, fontsize=font_scale + 12,
            fontweight="bold", va="center", ha="left")
    ax.text(0.04 + 0.075 * len(str(n_rounds)), 0.88, "rounds played",
            color=Colors.TEXT_MUTED, fontsize=label_fs, va="center", ha="left")

    rows = [
        ("Holes played", f"{total_holes}"),
        ("Birdies / Eagles", f"{birdies} / {eagles}"),
        ("Longest drive", longest),
        ("Best round", best_txt),
    ]
    # A gap below the header, then the stat rows spread across the lower panel
    # (all four fit — the last one used to spill below the axes and get clipped).
    #
    # A fifth "rounds with a mulligan" row was tried here and dropped: at the
    # compact four-up panel size these four rows are already close to touching,
    # and a fifth pushed them into each other. The asterisk on each affected
    # round bar and the note under the chart already say it.
    ys = [0.60, 0.44, 0.28, 0.12]
    for (label, val), y in zip(rows, ys):
        ax.text(0.0, y, label, color=Colors.TEXT_MUTED, fontsize=label_fs, va="center")
        ax.text(1.0, y, val, color=Colors.TEXT_PRIMARY, fontsize=label_fs,
                fontweight="bold", ha="right", va="center")


def _scoring_breakdown(ax, rounds, font_scale):
    totals = [int(rounds[b].sum()) for b in on_course.SCORE_BUCKETS]
    colors = [_BUCKET_COLORS[b] for b in on_course.SCORE_BUCKETS]
    x = range(len(on_course.SCORE_BUCKETS))
    bars = ax.bar(x, totals, color=colors, edgecolor="black", linewidth=0.5, zorder=3, width=0.7)
    top = max(totals) if any(totals) else 1
    for rect, val in zip(bars, totals):
        if val:
            ax.text(rect.get_x() + rect.get_width() / 2, val + top * 0.02, str(val),
                    ha="center", va="bottom", color=Colors.TEXT_PRIMARY,
                    fontsize=max(9, font_scale - 2), fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(on_course.SCORE_BUCKETS, fontsize=max(9, font_scale - 3))
    ax.set_ylim(0, top * 1.18)
    ax.set_title("Scoring Breakdown (holes)", fontsize=font_scale, color=Colors.TEXT_PRIMARY, pad=6)
    ax.set_ylabel("Holes", fontsize=max(10, font_scale - 1))
    style_axes(ax, font_scale - 1, grid="y")


def _round_scores(ax, rounds, font_scale):
    # This bottom panel is "full rounds only": a to-par bar is only a fair,
    # comparable score when all 18 holes were played, so drop any partial
    # round here (they still count in the KPI/breakdown totals above).
    rounds = rounds[rounds["holes"] >= 18]
    if rounds.empty:
        ax.set_axis_off()
        ax.text(0.5, 0.5, "No full 18-hole rounds yet",
                ha="center", va="center", color=Colors.TEXT_MUTED,
                fontsize=max(10, font_scale - 1), transform=ax.transAxes)
        ax.set_title("Full Round Scores (vs par)", fontsize=font_scale,
                     color=Colors.TEXT_PRIMARY, pad=6)
        return
    # Show only the most recent rounds, and keep them anchored to the left so a
    # constant-width bar is added on the right as each new round comes in (the
    # axis doesn't stretch old bars wider). Newest rounds are the ones a golfer
    # cares about; older ones stay in the KPI/breakdown totals above.
    rounds = rounds.tail(_MAX_ROUND_BARS).reset_index(drop=True)
    n = len(rounds)
    x = range(n)
    to_par = rounds["to_par"].to_numpy()
    # Green under par, neutral at even, red over par — the at-a-glance read.
    colors = [Colors.SUCCESS if v < 0 else (Colors.INFO if v == 0 else Colors.DANGER)
              for v in to_par]
    bars = ax.bar(x, to_par, color=colors, edgecolor="black", linewidth=0.5, zorder=3,
                  width=0.62)
    ax.axhline(0, color=Colors.TEXT_MUTED, linewidth=1.0, zorder=2)

    finished = rounds["finished"] if "finished" in rounds.columns else pd.Series(True, index=rounds.index)
    marks = [_mark(r) for _i, r in rounds.iterrows()]
    span = max(abs(to_par.min()), abs(to_par.max()), 1)
    for rect, v, was_finished, mark in zip(bars, to_par, finished, marks):
        off = span * 0.04
        # The bar still shows the real to-par accumulated before the round was
        # abandoned (useful context — "+2 through 6" isn't nothing), but the
        # label reads DNF so it's not mistaken for a completed round's score.
        label = f"{v:+d}{mark}" + ("" if was_finished else " (DNF)")
        color = Colors.WARNING if not was_finished else Colors.TEXT_PRIMARY
        ax.text(rect.get_x() + rect.get_width() / 2,
                v + (off if v >= 0 else -off), label,
                ha="center", va="bottom" if v >= 0 else "top",
                color=color, fontsize=max(9, font_scale - 2), fontweight="bold")

    # Course names crowd the tick labels once several rounds are shown, so
    # only include the course when there's room (a handful of rounds).
    show_course = "course" in rounds.columns and n <= 5
    labels = []
    for _, r in rounds.iterrows():
        d = r["date"]
        base = pd.to_datetime(d).strftime("%b %d") if pd.notna(d) else "—"
        course = r.get("course") if show_course else None
        course_line = f"\n{course}" if course and course != "Unknown Course" else ""
        labels.append(f"{base}\n{int(r['holes'])}h{course_line}")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=max(9, font_scale - 3))
    ax.set_ylim(min(to_par.min() - span * 0.25, -1), max(to_par.max() + span * 0.25, 1))
    ax.set_title("Full Round Scores (vs par)", fontsize=font_scale, color=Colors.TEXT_PRIMARY, pad=6)
    ax.set_ylabel("Score to par", fontsize=max(10, font_scale - 1))
    style_axes(ax, font_scale - 1, grid="y")
    if any(marks):
        # Only when an asterisk is actually on screen — a legend for a mark
        # nobody can see is just noise. As the x-label rather than free text at
        # a hand-picked offset, so matplotlib lays it out below the (three-line)
        # tick labels itself and it can't be clipped when this panel is sharing
        # the screen with three others.
        ax.set_xlabel(on_course.MULLIGAN_NOTE, fontsize=max(8, font_scale - 3),
                      color=Colors.TEXT_MUTED, loc="left")
    # Left-anchor the bars at a constant width: fix the x-range to a minimum
    # number of slots so a couple of rounds render as narrow bars on the left
    # (not stretched across the panel) with room to grow rightward up to the
    # last-10 cap.
    ax.set_xlim(-0.7, max(n, _MIN_ROUND_SLOTS) - 0.3)
