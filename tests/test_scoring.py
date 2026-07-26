"""Shot Quality Score (data.analytics.scoring.ShotScorer)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data.analytics.scoring import LONGER_IS_BETTER_CLUBS, ShotScorer


def _frame(n=12, carry=270.0, offline=0.0, vla=11.0, spin=2600.0, club="Dr", speed=113.0):
    return pd.DataFrame({
        "club": [club] * n,
        "carry": [carry] * n,
        "offline": [offline] * n,
        "vla": [vla] * n,
        "backspin": [spin] * n,
        "clubspeed": [speed] * n,
    })


def test_scores_stay_in_0_100():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "club": ["Dr"] * 30,
        "carry": rng.uniform(230, 300, 30),
        "offline": rng.uniform(-25, 25, 30),
        "vla": rng.uniform(6, 20, 30),
        "backspin": rng.uniform(1800, 5000, 30),
        "clubspeed": rng.uniform(105, 120, 30),
    })
    s = ShotScorer().score(df).dropna()
    assert len(s) == 30
    assert s.between(0, 100).all()


def test_on_target_shot_beats_mishit():
    # Two driver populations: one long/straight/in-window, one short/wild/out.
    good = _frame(carry=290, offline=2, vla=12, spin=2500)
    bad = _frame(carry=210, offline=28, vla=26, spin=6000)
    df = pd.concat([good, bad], ignore_index=True)
    s = ShotScorer().score(df)
    assert s.iloc[:12].mean() > s.iloc[12:].mean()
    assert s.iloc[:12].mean() > 60  # a genuinely good driver shot scores high


def test_sparse_club_degrades_to_target_only_without_crashing():
    # Below MIN_SHOTS: no self-consistency stats, but launch/spin still score.
    df = _frame(n=2)
    s = ShotScorer(min_shots=5).score(df)
    assert s.notna().all()
    assert s.between(0, 100).all()


def test_missing_all_scoreable_columns_yields_na():
    df = pd.DataFrame({"club": ["Dr"] * 6, "peakheight": [30.0] * 6})
    s = ShotScorer().score(df)
    assert s.isna().all()


def test_empty_frame_returns_empty_series():
    s = ShotScorer().score(pd.DataFrame())
    assert s.empty


def test_index_is_preserved():
    df = _frame(n=6)
    df.index = [10, 11, 12, 13, 14, 15]
    s = ShotScorer().score(df)
    assert list(s.index) == [10, 11, 12, 13, 14, 15]


# ---------------------------------------------------------------------------
# The carry term's direction. Long is a miss for a scoring club.
# ---------------------------------------------------------------------------
def _mixed_carry_frame(club, carries, vla=20.0, spin=6000.0, speed=85.0):
    """One club, a spread of carries, everything else held constant so the only
    thing moving the score is carry."""
    n = len(carries)
    return pd.DataFrame({
        "club": [club] * n,
        "carry": list(carries),
        "offline": [0.0] * n,
        "vla": [vla] * n,
        "backspin": [spin] * n,
        "clubspeed": [speed] * n,
    })


def test_iron_hit_long_does_not_beat_a_stock_iron():
    """The bug this guards: the carry term was monotonically increasing, so an
    iron flushed well past its stock number outscored a perfect stock one."""
    carries = [165.0] * 10 + [185.0]      # ten stock 7-irons, one 20 yds long
    scores = ShotScorer().score(_mixed_carry_frame("7I", carries))
    stock, long_one = scores.iloc[:10].mean(), scores.iloc[10]
    assert long_one < stock, (
        f"a 7I hit 20 yds long scored {long_one:.1f} vs {stock:.1f} for stock")


def test_iron_carry_term_is_symmetric_about_the_stock_number():
    """Equally long and equally short should score the same — neither is closer
    to the number you were trying to hit."""
    base = [165.0] * 12
    long_scores = ShotScorer().score(_mixed_carry_frame("7I", base + [180.0]))
    short_scores = ShotScorer().score(_mixed_carry_frame("7I", base + [150.0]))
    assert long_scores.iloc[12] == pytest.approx(short_scores.iloc[12], abs=0.5)


def test_driver_still_rewards_extra_distance():
    """Driver is the documented exception: longer genuinely is better."""
    carries = [270.0] * 10 + [295.0]
    scores = ShotScorer().score(
        _mixed_carry_frame("Dr", carries, vla=12.0, spin=2500.0, speed=113.0))
    assert scores.iloc[10] > scores.iloc[:10].mean()


def test_driver_is_the_only_longer_is_better_club():
    """A 3-wood is longer-is-better off a tee and not when laying up, and the
    data doesn't say which — so it must not be on the one-sided path."""
    assert "Dr" in LONGER_IS_BETTER_CLUBS
    for club in ("3W", "5W", "7I", "Pw", "Sw"):
        assert club not in LONGER_IS_BETTER_CLUBS


# ---------------------------------------------------------------------------
# Context: what "quality" means depends on what the shot was trying to do.
# ---------------------------------------------------------------------------
def _range_frame(n=10, club="7I", carry=150.0, total=155.0, offline=0.0,
                 target=None, vla=17.0, spin=6800.0, speed=88.0, smash=1.33):
    df = pd.DataFrame({
        "club": [club] * n,
        "carry": [carry] * n,
        "totaldistance": [total] * n,
        "offline": [offline] * n,
        "vla": [vla] * n,
        "backspin": [spin] * n,
        "clubspeed": [speed] * n,
        "smashfactor": [smash] * n,
        "round_type": ["practice"] * n,
    })
    if target is not None:
        df["target_distance"] = target
    return df


def _course_frame(distances, holeshots, clubs=None, totals=None):
    n = len(distances)
    return pd.DataFrame({
        "session_id": ["r1"] * n,
        "hole": [1] * n,
        "holeshot": holeshots,
        "distancetopin": distances,
        "totaldistance": totals or [200.0] * n,
        "carry": totals or [200.0] * n,
        "offline": [0.0] * n,
        "vla": [16.0] * n,
        "backspin": [6500.0] * n,
        "clubspeed": [90.0] * n,
        "smashfactor": [1.33] * n,
        "club": clubs or ["7I"] * n,
        "round_type": ["on_course"] * n,
    })


def test_range_target_shot_beats_the_same_strike_missing_the_target():
    """Same contact, same club, same everything — one finishes on the target
    distance and one 40 yards past it. Only the proximity differs."""
    on_it = _range_frame(total=150.0, carry=147.0, target=150.0)
    past_it = _range_frame(total=190.0, carry=187.0, target=150.0)
    both = pd.concat([on_it, past_it], ignore_index=True)
    scores = ShotScorer().score(both)
    assert scores.iloc[:10].mean() > scores.iloc[10:].mean() + 15


def test_offline_costs_a_shot_that_flew_the_right_distance():
    straight = _range_frame(total=150.0, offline=1.0, target=150.0)
    pushed = _range_frame(total=150.0, offline=45.0, target=150.0)
    both = pd.concat([straight, pushed], ignore_index=True)
    scores = ShotScorer().score(both)
    assert scores.iloc[:10].mean() > scores.iloc[10:].mean()


def test_unreachable_default_range_pin_is_not_treated_as_a_target():
    """GSPro's practice range reports a default pin at ~392 yards that no club
    reaches. Scoring a 7-iron on its proximity to that would make every range
    session look like a disaster, so it must fall back to strike + shape."""
    df = _range_frame(n=12, club="7I", total=155.0, carry=150.0, target=392.0)
    scores = ShotScorer().score(df)
    # A well-struck, perfectly repeatable 7-iron. If the 392 pin were being
    # scored as a target, every one of these would be near zero.
    assert scores.min() > 60


def test_a_reachable_target_is_used():
    """The plausibility gate rejects the unreachable default pin, not targets.
    The identical shot, 40 yards past a target it WAS aimed at, has to be
    marked down for it."""
    missed = _range_frame(n=12, total=190.0, carry=185.0, target=150.0)
    no_target = _range_frame(n=12, total=190.0, carry=185.0, target=392.0)
    assert ShotScorer().score(missed).iloc[0] < ShotScorer().score(no_target).iloc[0]


def test_on_course_shot_is_scored_on_proximity_to_the_flag():
    """Two approaches from the same distance: one to 4 yards, one to 45."""
    close = _course_frame([200.0, 4.0], [1, 2], totals=[250.0, 196.0])
    poor = _course_frame([200.0, 45.0], [1, 2], totals=[250.0, 160.0])
    close_score = ShotScorer().score(close).iloc[1]
    poor_score = ShotScorer().score(poor).iloc[1]
    assert close_score > poor_score


def test_on_course_proximity_is_judged_against_the_distance_played_from():
    """Six yards from the flag is a poor pitch from 30 out and a fine approach
    from 200 — so the same proximity must not score the same from both."""
    from_short = _course_frame([30.0, 6.0], [1, 2], totals=[250.0, 24.0])
    from_long = _course_frame([200.0, 6.0], [1, 2], totals=[250.0, 194.0])
    assert ShotScorer().score(from_long).iloc[1] > ShotScorer().score(from_short).iloc[1]


def test_mulligan_attempts_reference_the_same_starting_distance():
    """Three tee shots at stroke 1 all played from the tee, then the approach.

    A positional shift would hand the second attempt the first attempt's
    result as its starting distance, quietly rescoring a re-teed drive as a
    short approach it missed by 300 yards.
    """
    df = _course_frame([281.0, 333.0, 260.0, 47.0], [1, 1, 1, 2],
                       totals=[161.0, 99.0, 174.0, 216.0])
    scores = ShotScorer().score(df)
    assert scores.notna().all()
    # None of the three tee shots was played at the flag, so all three score on
    # strike and shape — and none is dragged to zero by a proximity it was
    # never trying to achieve.
    assert (scores.iloc[:3] > 20).all()


def test_a_tee_shot_is_not_scored_on_its_distance_from_the_flag():
    """A tour-spec drive on a 442-yard par 4 finishes ~280 yards from the hole
    however well it is struck. Scoring that on proximity rated it 40/100."""
    df = pd.DataFrame({
        "session_id": ["r1"] * 2, "hole": [1] * 2, "holeshot": [1, 2],
        "distancetopin": [281.0, 20.0], "totaldistance": [161.0, 261.0],
        "carry": [161.0, 261.0], "offline": [0.0, 0.0],
        "vla": [11.0, 16.0], "backspin": [2700.0, 6500.0],
        "clubspeed": [113.0, 90.0], "smashfactor": [1.478, 1.333],
        "club": ["Dr", "7I"], "round_type": ["on_course"] * 2,
    })
    scores = ShotScorer().score(df)
    assert scores.iloc[0] > 85, f"flushed tour drive scored {scores.iloc[0]}"


def test_putts_and_penalty_strokes_are_not_scored():
    df = _course_frame([200.0, 4.0, 0.0], [1, 2, 3],
                       clubs=["Dr", "7I", "Putter"], totals=[250.0, 196.0, 4.0])
    scores = ShotScorer().score(df)
    assert pd.isna(scores.iloc[2])
    assert scores.iloc[:2].notna().all()

    penalty = _course_frame([200.0, 190.0], [1, 2], totals=[250.0, 10.0])
    penalty["shot_result"] = [0, 2]
    assert pd.isna(ShotScorer().score(penalty).iloc[1])


def test_range_without_a_target_still_scores_gapping_for_irons():
    """No target means no proximity, so the score falls back to strike plus
    how repeatable the shot was — an iron 25 yards off its own stock number is
    a worse shot than one on it, in either direction."""
    carries = [150.0] * 11 + [175.0]
    df = _range_frame(n=12)
    df["carry"] = carries
    df["totaldistance"] = [c + 5 for c in carries]
    scores = ShotScorer().score(df)
    assert scores.iloc[11] < scores.iloc[:11].mean()


def test_a_pured_strike_still_scores_without_any_distance_data():
    """Strike is measured on contact alone, so a frame with no carry, offline
    or target at all still produces a score rather than NA."""
    df = pd.DataFrame({
        "club": ["7I"] * 6, "vla": [16.3] * 6, "backspin": [7097.0] * 6,
        "clubspeed": [90.0] * 6, "smashfactor": [1.333] * 6,
    })
    scores = ShotScorer().score(df)
    assert scores.notna().all()
    assert scores.min() > 85  # tour launch, tour spin, tour smash


def test_thin_strike_scores_below_a_flush_one():
    """Smash above the club's own number is a thin strike low on the face, not
    a better one — the window is two-sided on purpose."""
    flush = _range_frame(smash=1.33)
    thin = _range_frame(smash=1.48)
    both = pd.concat([flush, thin], ignore_index=True)
    scores = ShotScorer().score(both)
    assert scores.iloc[:10].mean() > scores.iloc[10:].mean()
