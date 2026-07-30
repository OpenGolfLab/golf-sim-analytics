"""Effort (% of max club speed) — data/store.py::add_speed_pct.

Guards the Dispersion panel's Effort filter: percents are per club against
that club's own max, sensor glitches can't set the max, and thin clubs
(fewer than MIN_SPEED_READINGS readings) stay NaN rather than pretending
four swings define a personal max.
"""
import numpy as np
import pandas as pd

from data.store import MIN_SPEED_READINGS, add_speed_pct


def _df(clubs, speeds):
    return pd.DataFrame({"club": clubs, "clubspeed": speeds, "carry": 200.0})


def test_speed_pct_is_percent_of_that_clubs_max():
    n = MIN_SPEED_READINGS
    df = _df(["Dr"] * n + ["7I"] * n,
             [100.0] * (n - 1) + [110.0] + [80.0] * (n - 1) + [88.0])
    out = add_speed_pct(df)
    # Driver max is 110: the 100mph swings sit at 100/110, not against 7I's max.
    assert np.isclose(out.loc[0, "speed_pct"], 100.0 / 110.0 * 100.0)
    assert np.isclose(out.loc[n - 1, "speed_pct"], 100.0)
    # 7I percents are against 88, independently of the driver.
    assert np.isclose(out.loc[n, "speed_pct"], 80.0 / 88.0 * 100.0)


def test_glitch_readings_do_not_set_the_max():
    n = MIN_SPEED_READINGS
    speeds = [100.0] * n + [400.0]  # one 400mph misread
    out = add_speed_pct(_df(["Dr"] * (n + 1), speeds))
    # The glitch row gets no percent, and the real swings still read 100%.
    assert np.isnan(out.loc[n, "speed_pct"])
    assert np.isclose(out.loc[0, "speed_pct"], 100.0)


def test_thin_clubs_get_no_percents():
    out = add_speed_pct(_df(["Dr"] * 3, [100.0, 101.0, 99.0]))
    assert out["speed_pct"].isna().all()


def test_rows_without_club_speed_get_nan_not_dropped():
    n = MIN_SPEED_READINGS
    speeds = [100.0] * n + [np.nan]
    out = add_speed_pct(_df(["Dr"] * (n + 1), speeds))
    assert len(out) == n + 1
    assert np.isnan(out.loc[n, "speed_pct"])


def test_missing_speed_column_is_a_noop():
    df = pd.DataFrame({"club": ["Dr"], "carry": [250.0]})
    out = add_speed_pct(df)
    assert "speed_pct" not in out.columns


def test_empty_frame_is_a_noop():
    out = add_speed_pct(pd.DataFrame())
    assert out.empty
