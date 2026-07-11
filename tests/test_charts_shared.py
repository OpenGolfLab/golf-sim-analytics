import pandas as pd

from ui.charts._shared import diagnostic_cols, diagnostic_lines


def test_diagnostic_cols_resolves_known_aliases():
    df = pd.DataFrame({"vla": [1], "decent": [1], "backspin": [1], "smashfactor": [1],
                       "clubspeed": [1], "ballspeed": [1]})
    cols = diagnostic_cols(df)
    assert cols == {"vla": "vla", "desc": "decent", "spin": "backspin",
                    "smash": "smashfactor", "cs": "clubspeed", "bs": "ballspeed"}


def test_diagnostic_cols_missing_metrics_are_none():
    df = pd.DataFrame({"club": ["Dr"]})
    cols = diagnostic_cols(df)
    assert all(v is None for v in cols.values())


def test_diagnostic_lines_flags_launch_and_descent_outside_window():
    # Driver's fitting window: launch 10-14, descent 35-42 (config.py).
    df = pd.DataFrame({"vla": [30.0], "decent": [25.0]})
    cols = diagnostic_cols(df)
    lines = diagnostic_lines(df.iloc[0], cols, club="Dr")
    assert any("Launch: 30.0" in l and "high" in l for l in lines)
    assert any("Descent: 25.0" in l and "low" in l for l in lines)


def test_diagnostic_lines_no_flag_when_inside_window():
    df = pd.DataFrame({"vla": [12.0], "decent": [38.0]})
    cols = diagnostic_cols(df)
    lines = diagnostic_lines(df.iloc[0], cols, club="Dr")
    assert any(l == "Launch: 12.0°" for l in lines)
    assert any(l == "Descent: 38.0°" for l in lines)


def test_diagnostic_lines_uses_recorded_smash_factor_when_present():
    df = pd.DataFrame({"smashfactor": [1.48]})
    cols = diagnostic_cols(df)
    lines = diagnostic_lines(df.iloc[0], cols)
    assert lines == ["Smash: 1.48"]


def test_diagnostic_lines_derives_smash_from_speeds_when_no_column():
    df = pd.DataFrame({"clubspeed": [100.0], "ballspeed": [145.0]})
    cols = diagnostic_cols(df)
    lines = diagnostic_lines(df.iloc[0], cols)
    assert lines == ["Smash: 1.45"]


def test_diagnostic_lines_rejects_implausible_derived_smash():
    # 0 club speed would divide-by-zero-ish / garbage smash — must not appear.
    df = pd.DataFrame({"clubspeed": [0.0], "ballspeed": [145.0]})
    cols = diagnostic_cols(df)
    assert diagnostic_lines(df.iloc[0], cols) == []


def test_diagnostic_lines_includes_spin():
    df = pd.DataFrame({"backspin": [2500.0]})
    cols = diagnostic_cols(df)
    assert diagnostic_lines(df.iloc[0], cols) == ["Spin: 2500 rpm"]


def test_diagnostic_lines_omits_missing_metrics_without_guessing():
    df = pd.DataFrame({"club": ["Dr"]})
    cols = diagnostic_cols(df)
    assert diagnostic_lines(df.iloc[0], cols, club="Dr") == []


def test_diagnostic_lines_no_window_flag_without_club():
    # Without a club, there's no fitting window to compare against — the
    # value should still show, just unflagged.
    df = pd.DataFrame({"vla": [30.0]})
    cols = diagnostic_cols(df)
    lines = diagnostic_lines(df.iloc[0], cols, club=None)
    assert lines == ["Launch: 30.0°"]
