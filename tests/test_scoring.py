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
