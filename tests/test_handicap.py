"""Sim Handicap (data.analytics.handicap)."""
from __future__ import annotations

import pandas as pd
import pytest

from data.analytics.handicap import (
    MIN_HOLES, MIN_ROUNDS, SCORING_WINDOW, SimHandicap, compute_sim_handicap,
)


def _round_of(session, to_par, holes=18, mulligans=0, day=1, finished=True):
    """An on-course round that scores exactly ``to_par`` over ``holes`` holes.

    Built from real shot rows rather than a fake round_summary so the test
    exercises the whole path — mulligan detection included.
    """
    rows = []
    # Every hole is a par 4. Spend the round's to-par one stroke at a time on
    # the opening holes and play the rest level, so the total lands exactly on
    # ``to_par``.
    adjust = 1 if to_par >= 0 else -1
    adjusted_holes = min(abs(to_par), holes)
    for hole in range(1, holes + 1):
        strokes = 4 + (adjust if hole <= adjusted_holes else 0)
        for shot in range(1, strokes + 1):
            rows.append({
                "session_id": session,
                "session_date": pd.Timestamp("2026-07-01") + pd.Timedelta(days=day),
                "hole": hole,
                "holepar": 4,
                "holeshot": shot,
                "round_type": "on_course",
                "club": "Dr" if shot == 1 else "7I",
                "totaldistance": 250.0,
                # Last shot of the hole is holed out unless the round is a DNF
                # on its final hole.
                "distancetopin": 0.0 if shot == strokes else 40.0,
            })
    df = pd.DataFrame(rows)
    if not finished:
        df.loc[df.index[-1], "distancetopin"] = 30.0
    if mulligans:
        # Re-tee the first hole: extra records repeating HoleShot 1.
        extra = df.iloc[[0]].copy()
        df = pd.concat([extra] * mulligans + [df], ignore_index=True)
    return df


def _history(n, to_par=6, **kw):
    return pd.concat(
        [_round_of(f"r{i}", to_par, day=i, **kw) for i in range(n)],
        ignore_index=True)


def test_no_rounds_gives_a_blank_index():
    h = compute_sim_handicap(pd.DataFrame())
    assert h.value is None and h.verified is False
    assert h.label == "---"


def test_index_is_blank_until_the_minimum_round_count():
    h = compute_sim_handicap(_history(MIN_ROUNDS - 1))
    assert h.value is None
    assert h.verified is False
    assert h.eligible_rounds == MIN_ROUNDS - 1
    # A path, not a dash: the status says exactly what's missing.
    assert "1 more round needed" in h.status


def test_index_appears_and_is_verified_at_the_minimum():
    h = compute_sim_handicap(_history(MIN_ROUNDS))
    assert h.value is not None
    assert h.verified is True
    assert h.eligible_rounds == MIN_ROUNDS
    assert "Verified" in h.status


def test_index_equals_score_to_par_for_level_rounds():
    # Every round +6 over 18 holes -> every differential is 6.0, so whichever
    # subset is averaged, the index is 6.0.
    h = compute_sim_handicap(_history(MIN_ROUNDS, to_par=6))
    assert h.value == pytest.approx(6.0, abs=0.05)


def test_index_uses_the_best_rounds_not_the_average():
    # Four bad rounds and one good one: at five rounds WHS averages the single
    # best differential, so the good round sets the number.
    df = pd.concat(
        [_round_of(f"bad{i}", 12, day=i) for i in range(4)]
        + [_round_of("good", 2, day=9)],
        ignore_index=True)
    h = compute_sim_handicap(df)
    assert h.rounds_used == 1
    assert h.value == pytest.approx(2.0, abs=0.05)


def test_rounds_with_a_mulligan_are_excluded():
    clean = _history(MIN_ROUNDS, to_par=10)
    # One outstanding round, but it took a mulligan to get there — it must not
    # drag the index down to its score.
    cheated = _round_of("cheat", 0, mulligans=2, day=50)
    h = compute_sim_handicap(pd.concat([clean, cheated], ignore_index=True))
    assert h.excluded_mulligans == 1
    assert h.eligible_rounds == MIN_ROUNDS
    assert h.value == pytest.approx(10.0, abs=0.05)


def test_mulligan_rounds_alone_never_produce_an_index():
    df = pd.concat(
        [_round_of(f"m{i}", 4, mulligans=1, day=i) for i in range(MIN_ROUNDS + 3)],
        ignore_index=True)
    h = compute_sim_handicap(df)
    assert h.value is None
    assert h.eligible_rounds == 0
    assert h.excluded_mulligans == MIN_ROUNDS + 3
    assert "with mulligans" in h.status


def test_short_rounds_are_excluded():
    df = pd.concat(
        [_round_of(f"s{i}", 4, holes=MIN_HOLES - 1, day=i) for i in range(MIN_ROUNDS + 2)],
        ignore_index=True)
    h = compute_sim_handicap(df)
    assert h.value is None
    assert h.excluded_incomplete == MIN_ROUNDS + 2


def test_nine_hole_rounds_are_eligible_and_scale_to_eighteen():
    # +3 over 9 holes is a +6 pace over 18, so the differential is 6.0.
    df = pd.concat(
        [_round_of(f"n{i}", 3, holes=MIN_HOLES, day=i) for i in range(MIN_ROUNDS)],
        ignore_index=True)
    h = compute_sim_handicap(df)
    assert h.value == pytest.approx(6.0, abs=0.05)


def test_only_the_most_recent_window_counts():
    # An old great streak must not hold the index down forever once there are
    # a full window's worth of newer rounds.
    old = pd.concat([_round_of(f"old{i}", 0, day=i) for i in range(5)], ignore_index=True)
    new = pd.concat(
        [_round_of(f"new{i}", 14, day=100 + i) for i in range(SCORING_WINDOW)],
        ignore_index=True)
    h = compute_sim_handicap(pd.concat([old, new], ignore_index=True))
    assert h.eligible_rounds == SCORING_WINDOW
    assert h.value == pytest.approx(14.0, abs=0.05)


def test_label_formats_plus_handicaps_with_a_sign():
    assert SimHandicap(value=12.4, verified=True).label == "12.4"
    assert SimHandicap(value=-2.1, verified=True).label == "-2.1"
    assert SimHandicap().label == "---"


def test_practice_only_history_has_no_index():
    practice = pd.DataFrame({
        "session_id": ["p1"] * 20, "club": ["7I"] * 20, "carry": [150.0] * 20,
        "round_type": ["practice"] * 20,
    })
    h = compute_sim_handicap(practice)
    assert h.value is None and h.eligible_rounds == 0
