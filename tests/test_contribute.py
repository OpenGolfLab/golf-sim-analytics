"""Contribution bundling: round selection + putt exclusion.

Guards the "app sent the wrong / far more shots than I hit" fix — only the
sessions the user picks are bundled, and putter strokes never ship.
"""
import pandas as pd

import contribute


def _df():
    return pd.DataFrame({
        "session_id": ["s1", "s1", "s1", "s2", "s2"],
        "club": ["Dr", "7I", "Putter", "Dr", "Sw"],
        "ballspeed": [170.0, 120.0, 20.0, 168.0, 60.0],
        "launch_angle": [12.0, 17.0, 4.0, 13.0, 30.0],
        "backspin": [2600.0, 6200.0, 3000.0, 2700.0, 7500.0],
        "carry": [270.0, 165.0, 10.0, 265.0, 60.0],
    })


def test_selecting_a_session_excludes_other_sessions(tmp_path):
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)

    manifest, out = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1, session_ids=["s2"])

    # Only s2's two shots — s1 (three shots) is excluded entirely.
    assert manifest["shot_count"] == 2
    assert set(out["club"]) == {"Dr", "Sw"}


def test_putts_are_never_contributed(tmp_path):
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)

    manifest, out = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1)  # whole history, no selection

    # The lone Putter row is dropped even without a session filter.
    assert "Putter" not in set(out["club"])
    assert manifest["shot_count"] == 4


def test_whole_history_default_still_includes_every_session(tmp_path):
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)

    manifest, _out = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1)

    # 5 rows minus the 1 putt = 4 across both sessions.
    assert manifest["shot_count"] == 4
