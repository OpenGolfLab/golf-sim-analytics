"""Environmental normalization (data.analytics.normalizer + physics.air_density_at)."""
from __future__ import annotations

import pandas as pd

from data.analytics.normalizer import EnvironmentalNormalizer
from data.physics import air_density_at


def test_air_density_falls_as_temperature_rises():
    # Warmer air is thinner at the same elevation.
    assert air_density_at(40) > air_density_at(80) > air_density_at(110)


def test_air_density_falls_with_elevation():
    assert air_density_at(70, 0) > air_density_at(70, 5000)


def test_scale_factor_is_one_at_standard_temp():
    n = EnvironmentalNormalizer(standard_temp_f=80)
    assert round(n.scale_factor(80), 6) == 1.0


def test_colder_shots_normalize_longer_warmer_shots_shorter():
    n = EnvironmentalNormalizer(standard_temp_f=80)
    assert n.scale_factor(40) > 1.0   # cold day -> would fly farther in warm std
    assert n.scale_factor(100) < 1.0  # hot day -> would fly shorter in cooler std


def test_normalize_scales_carry_and_total():
    n = EnvironmentalNormalizer(standard_temp_f=80)
    df = pd.DataFrame({"carry": [270.0], "total": [290.0], "club": ["Dr"]})
    out = n.normalize(df, temp_f=40)
    factor = n.scale_factor(40)
    assert round(out["carry"].iloc[0], 4) == round(270.0 * factor, 4)
    assert round(out["total"].iloc[0], 4) == round(290.0 * factor, 4)


def test_normalize_is_nondestructive():
    n = EnvironmentalNormalizer()
    df = pd.DataFrame({"carry": [270.0]})
    n.normalize(df, temp_f=40)
    assert df["carry"].iloc[0] == 270.0  # original untouched


def test_normalize_skips_missing_columns_safely():
    n = EnvironmentalNormalizer()
    df = pd.DataFrame({"club": ["Dr"], "backspin": [2600]})
    out = n.normalize(df, temp_f=40)
    assert out.equals(df)


def test_realistic_magnitude_roughly_two_yards_per_ten_degrees():
    # 60F -> 80F on a 275yd driver should move a few yards, not tens.
    n = EnvironmentalNormalizer(standard_temp_f=80)
    gain = 275.0 * n.scale_factor(60) - 275.0
    assert 2.0 < gain < 8.0
