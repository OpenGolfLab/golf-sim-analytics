"""Rule-based coaching diagnostics (data.analytics.diagnostics)."""
from __future__ import annotations

import pandas as pd

from data.analytics.diagnostics import DiagnosticsEngine


def _driver(n, spin, aoa, club="DR"):
    return pd.DataFrame({"club": [club] * n, "backspin": [spin] * n, "aoa": [aoa] * n})


def test_fires_on_driver_high_spin_and_negative_aoa():
    flags = DiagnosticsEngine().flags(_driver(5, spin=3500, aoa=-2.0))
    assert len(flags) == 1
    assert flags[0].tag == "Driver"
    assert flags[0].tone == "warn"


def test_silent_when_attack_angle_is_positive():
    assert DiagnosticsEngine().flags(_driver(5, spin=3500, aoa=1.5)) == []


def test_silent_when_spin_is_low():
    assert DiagnosticsEngine().flags(_driver(5, spin=2200, aoa=-2.0)) == []


def test_below_threshold_count_does_not_fire():
    # Only 2 offending shots (< MIN_FLAG_SHOTS) — not a pattern yet.
    assert DiagnosticsEngine().flags(_driver(2, spin=3500, aoa=-2.0)) == []


def test_ignores_non_driver_clubs():
    # A 7-iron hitting down with spin is normal, not a leak.
    df = _driver(6, spin=6000, aoa=-4.0, club="7I")
    assert DiagnosticsEngine().flags(df) == []


def test_normalizes_club_spelling():
    # "Driver" must be treated as the driver by the rule.
    flags = DiagnosticsEngine().flags(_driver(5, spin=3500, aoa=-2.0, club="Driver"))
    assert len(flags) == 1


def test_missing_aoa_column_is_safe():
    df = pd.DataFrame({"club": ["DR"] * 5, "backspin": [3500] * 5})
    assert DiagnosticsEngine().flags(df) == []


def test_empty_frame_is_safe():
    assert DiagnosticsEngine().flags(pd.DataFrame()) == []
