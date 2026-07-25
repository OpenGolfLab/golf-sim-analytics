"""
Live session trends for the Live view: how the club you're hitting RIGHT NOW
compares to your own recent history with that same club.

Shown top-right of the Live Dispersion panel (the motivation gauges sit
below it). One club only — whichever club the latest swing used — with two
baselines side by side:

- vs last:   your previous session containing that club
- vs last 3: your last three such sessions, pooled

Two metrics per baseline:

- Carry: the session MEDIAN carry, not the mean, so one flushed drive (or
  one cold top) can't fake a trend — the same discipline the home-page
  trend series uses (see data/store.compute_home_trends).
- Spread: the +/-1 sigma offline dispersion. Smaller is tighter, so a
  negative delta renders green.

Computation is pure (plain dicts + a DataFrame in, plain dict out) and kept
separate from drawing, so it's unit-testable without a figure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import Colors, NON_SWING_CLUBS, get_club_color
from data import units as units_mod

# A club needs this many measurable live shots before a trend shows —
# a median of one or two swings isn't a trend, it's a shot.
MIN_LIVE_SHOTS = 3
# ...and a historical session only counts as a baseline if it gave the
# club at least this many shots.
MIN_BASELINE_SHOTS = 3

# Deltas smaller than these render neutral instead of green/red: changes
# inside the noise floor shouldn't flash a verdict.
CARRY_NOISE_YDS = 1.0
SPREAD_NOISE_YDS = 0.5

_GOOD = "#2ECC71"
_BAD = "#E74C3C"


def _is_swing(shot: dict) -> bool:
    """A live-buffer record that represents an actual swing of a club —
    excludes putter strokes and penalty records (see data.on_course
    .exclude_putts for the same rule on stored data)."""
    club = str(shot.get("club") or "").strip()
    if not club or club in NON_SWING_CLUBS:
        return False
    return shot.get("shot_result") != 2


def active_club(live_shots: list[dict]) -> str | None:
    """The club currently being hit: the most recent live swing's club
    (putts and penalty records don't change the active club)."""
    for shot in reversed(live_shots or []):
        if _is_swing(shot):
            return str(shot["club"]).strip()
    return None


def _live_values(live_shots: list[dict], club: str, key: str) -> list[float]:
    out = []
    for s in live_shots:
        if _is_swing(s) and str(s.get("club")).strip() == club and s.get(key) is not None:
            try:
                out.append(float(s[key]))
            except (TypeError, ValueError):
                pass
    return out


def _baseline_sessions(history_df: pd.DataFrame, club: str) -> list[pd.DataFrame]:
    """Prior sessions containing >= MIN_BASELINE_SHOTS measurable shots of
    ``club``, newest first."""
    if history_df is None or history_df.empty:
        return []
    need = {"club", "session_id", "carry"}
    if not need <= set(history_df.columns):
        return []
    cd = history_df[history_df["club"].astype(str).str.strip() == club]
    cd = cd[pd.to_numeric(cd["carry"], errors="coerce").notna()]
    if cd.empty:
        return []
    dates = (pd.to_datetime(cd["session_date"], errors="coerce")
             if "session_date" in cd.columns else pd.Series(pd.NaT, index=cd.index))
    order = dates.groupby(cd["session_id"]).max().sort_values(na_position="first")
    out = []
    for sid in reversed(list(order.index)):
        sub = cd[cd["session_id"] == sid]
        if len(sub) >= MIN_BASELINE_SHOTS:
            out.append(sub)
    return out


def _pooled(sessions: list[pd.DataFrame], col: str, stat: str) -> float | None:
    vals = pd.concat(sessions)[col] if sessions else pd.Series(dtype=float)
    vals = pd.to_numeric(vals, errors="coerce").dropna()
    if len(vals) < MIN_BASELINE_SHOTS:
        return None
    return float(vals.median() if stat == "median" else vals.std())


def compute_trends(live_shots: list[dict], history_df: pd.DataFrame,
                   club: str | None = None) -> dict | None:
    """Trend summary for the active club, or None when no club is active.

    All values in yards (the live buffer's native unit); the caller converts
    for display. ``carry``/``spread`` are None until the club has
    MIN_LIVE_SHOTS measurable live shots; each baseline delta is None when
    the corresponding history doesn't exist.
    """
    club = club or active_club(live_shots)
    if not club:
        return None

    carries = _live_values(live_shots, club, "carry")
    offlines = _live_values(live_shots, club, "offline")
    carry = float(np.median(carries)) if len(carries) >= MIN_LIVE_SHOTS else None
    spread = float(np.std(offlines, ddof=1)) if len(offlines) >= MIN_LIVE_SHOTS else None

    sessions = _baseline_sessions(history_df, club)

    def _vs(n: int) -> dict:
        subset = sessions[:n]
        base_carry = _pooled(subset, "carry", "median")
        base_spread = (_pooled(subset, "offline", "std")
                       if subset and "offline" in subset[0].columns else None)
        return {
            "sessions": len(subset),
            "carry": (carry - base_carry
                      if carry is not None and base_carry is not None else None),
            "spread": (spread - base_spread
                       if spread is not None and base_spread is not None else None),
        }

    return {
        "club": club,
        "shots": len(carries),
        "carry": carry,
        "spread": spread,
        "vs_last": _vs(1),
        "vs_last3": _vs(3),
    }


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Card layout, in axes fractions. Named because the two "not enough data yet"
# branches have to sit on the same grid as the full card — otherwise the text
# jumps vertically the moment the third swing lands.
# ---------------------------------------------------------------------------
_Y_HEADER = 0.95      # club name / shot count line
_Y_RULE = 0.86        # hairline under the header
_ROW_TOP = 0.72       # first metric's value line
_ROW_PITCH = 0.42     # vertical distance to the next metric block
_DELTA_DROP = 0.19    # value line -> its delta row
_DELTA_INDENT = 0.30  # caption -> its number, within a delta cell
_Y_BODY = 0.42        # centre of the area below the rule, for placeholder text


def _delta_text_color(delta, noise: float, lower_is_better: bool):
    """(text, color) for one delta cell. '—' when there's no baseline."""
    if delta is None:
        return "—", Colors.TEXT_MUTED
    if abs(delta) < noise:
        return f"≈ {delta:+.1f}", Colors.TEXT_MUTED
    improved = (delta < 0) if lower_is_better else (delta > 0)
    arrow = "▼" if delta < 0 else "▲"
    return f"{delta:+.1f} {arrow}", (_GOOD if improved else _BAD)


def draw_trends(ax, live_shots: list[dict], history_df: pd.DataFrame,
                font_scale: float, unit: str = units_mod.YARDS) -> None:
    """The top-right Live-view trends card for the active club."""
    ax.set_axis_off()
    small = max(8, font_scale - 3)
    mid = max(9, font_scale - 2)
    big = max(11, font_scale - 1)

    t = compute_trends(live_shots, history_df)
    if t is None:
        ax.text(0.5, 0.5, "Session trends\nappear after\nyour first swing",
                ha="center", va="center", color=Colors.TEXT_MUTED, fontsize=small,
                transform=ax.transAxes)
        return

    u = units_mod.dist_suffix_lower(unit)
    _c = lambda v: units_mod.to_display(v, unit) if v is not None else None

    club_color = get_club_color(t["club"])
    ax.text(0.0, _Y_HEADER, t["club"], ha="left", va="center", color=club_color,
            fontsize=big, fontweight="bold", transform=ax.transAxes)
    ax.text(1.0, _Y_HEADER, f"{t['shots']} shot{'s' if t['shots'] != 1 else ''} this session",
            ha="right", va="center", color=Colors.TEXT_MUTED, fontsize=small,
            transform=ax.transAxes)
    # Hairline under the header, so the club/shot-count line reads as a title
    # for the numbers below rather than floating above them.
    # plot() rather than axhline(), which insists on generating its own
    # transform and so can't be placed in axes fractions.
    ax.plot([0.0, 1.0], [_Y_RULE, _Y_RULE], color=Colors.BORDER, linewidth=1,
            transform=ax.transAxes, clip_on=False, zorder=1)

    if t["carry"] is None:
        ax.text(0.5, _Y_BODY,
                f"Need {MIN_LIVE_SHOTS} swings with {t['club']}\nfor session trends",
                ha="center", va="center", color=Colors.TEXT_MUTED, fontsize=small,
                transform=ax.transAxes)
        return

    if t["vs_last"]["sessions"] == 0:
        # Same stacked rows as the full card, minus the delta lines there's no
        # baseline for yet, so nothing shifts once one exists.
        ax.text(0.0, _ROW_TOP, f"Carry {_c(t['carry']):.0f} {u}", ha="left",
                va="center", color=Colors.TEXT_PRIMARY, fontsize=mid,
                fontweight="bold", transform=ax.transAxes)
        if t["spread"] is not None:
            ax.text(0.0, _ROW_TOP - _ROW_PITCH, f"Spread ±{_c(t['spread']):.0f} {u}",
                    ha="left", va="center", color=Colors.TEXT_PRIMARY, fontsize=mid,
                    fontweight="bold", transform=ax.transAxes)
        ax.text(0.0, _ROW_TOP - 2 * _ROW_PITCH,
                f"First tracked session with {t['club']} —\n"
                "trends appear next time out", ha="left", va="top",
                color=Colors.TEXT_MUTED, fontsize=small, transform=ax.transAxes)
        return

    # One metric block per row (carry, then spread), each a full-width value
    # line with its two baseline deltas side by side underneath.
    #
    # These used to sit side by side in two half-width columns, which fought the
    # shape of the card: it's tall and narrow, so the horizontal split left each
    # block ~45% of an already narrow axes to fit a label and a signed delta,
    # while most of the vertical space went unused. Stacking them spends the axis
    # that has room to spare and gives each label the full width.
    #
    # Deltas convert like distances: they ARE distances (a difference of two).
    blocks = [
        (f"Carry {_c(t['carry']):.0f} {u}",
         _delta_text_color(_c(t["vs_last"]["carry"]), CARRY_NOISE_YDS, False),
         _delta_text_color(_c(t["vs_last3"]["carry"]), CARRY_NOISE_YDS, False)),
    ]
    if t["spread"] is not None:
        blocks.append(
            (f"Spread ±{_c(t['spread']):.0f} {u}",
             _delta_text_color(_c(t["vs_last"]["spread"]), SPREAD_NOISE_YDS, True),
             _delta_text_color(_c(t["vs_last3"]["spread"]), SPREAD_NOISE_YDS, True)))

    for row, (label, (txt1, col1), (txt3, col3)) in enumerate(blocks):
        y_value = _ROW_TOP - row * _ROW_PITCH
        y_delta = y_value - _DELTA_DROP
        ax.text(0.0, y_value, label, ha="left", va="center",
                color=Colors.TEXT_PRIMARY, fontsize=mid, fontweight="bold",
                transform=ax.transAxes)
        for x_cap, cap, txt, col in ((0.0, "vs last", txt1, col1),
                                     (0.52, "vs last 3", txt3, col3)):
            ax.text(x_cap, y_delta, cap, ha="left", va="center",
                    color=Colors.TEXT_MUTED, fontsize=small, transform=ax.transAxes)
            ax.text(x_cap + _DELTA_INDENT, y_delta, txt, ha="left", va="center",
                    color=col, fontsize=mid, transform=ax.transAxes)
