import pandas as pd

from data import units


def test_is_metric():
    assert units.is_metric("Meters")
    assert units.is_metric("meters")
    assert not units.is_metric("Yards")


def test_to_display_yards_is_identity():
    assert units.to_display(100.0, "Yards") == 100.0


def test_to_display_meters_converts():
    assert round(units.to_display(100.0, "Meters"), 3) == 91.44


def test_suffixes():
    assert units.dist_suffix("Yards") == "Yds"
    assert units.dist_suffix("Meters") == "m"
    assert units.dist_suffix_lower("Yards") == "yds"
    assert units.height_suffix("Meters") == "m"


def test_to_display_frame_converts_distance_and_height_columns():
    df = pd.DataFrame({
        "carry": [100.0], "total": [110.0], "offline": [10.0],
        "distancetopin": [5.0], "apex": [90.0],  # apex is feet
        "ballspeed": [150.0], "backspin": [3000.0],  # untouched
    })
    out = units.to_display_frame(df, "Meters")

    assert round(out["carry"].iloc[0], 2) == 91.44
    assert round(out["offline"].iloc[0], 3) == 9.144
    assert round(out["apex"].iloc[0], 3) == round(90 * 0.3048, 3)  # feet -> m
    # Speed / spin never convert.
    assert out["ballspeed"].iloc[0] == 150.0
    assert out["backspin"].iloc[0] == 3000.0


def test_to_display_frame_yards_returns_input_unchanged():
    df = pd.DataFrame({"carry": [100.0]})
    assert units.to_display_frame(df, "Yards") is df
