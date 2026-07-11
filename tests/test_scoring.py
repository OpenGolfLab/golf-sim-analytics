"""Shot Quality Score (data.analytics.scoring.ShotScorer)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.analytics.scoring import ShotScorer


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
