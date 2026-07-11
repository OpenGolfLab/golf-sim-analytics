"""Phase 0 foundation tests: AoA ingestion round-trip + target-window lookup."""
from __future__ import annotations

import pandas as pd

from config import CLUB_ORDER, optimal_launch_spin
from data.analytics import DiagnosticsEngine, EnvironmentalNormalizer, ShotScorer, get_targets
from data.columns import AOA_ALIASES, find_col
from data.io import parse_and_clean_csv


# --- AoA ingestion round-trip -------------------------------------------------

def _write_csv(tmp_path, rows_extra=""):
    # Minimal GSPro-shaped export: the columns ingestion needs to keep a row
    # (Carry, ClubSpeed, SmashFactor, Club) plus AoA in the launch monitor's
    # original "AoA" spelling and casing.
    csv = tmp_path / "gspro-export.csv"
    csv.write_text(
        "Carry,ClubSpeed,SmashFactor,Club,AoA\n"
        "275,113,1.48,DR,-0.618\n"
        "150,90,1.33,PW,-3.867\n" + rows_extra
    )
    return csv


def test_aoa_alias_resolves_after_ingestion(tmp_path):
    df = parse_and_clean_csv(_write_csv(tmp_path))
    col = find_col(df, AOA_ALIASES)
    assert col == "aoa"  # "AoA" -> lowercased/underscored by ingestion


def test_aoa_negative_values_survive_ingestion(tmp_path):
    df = parse_and_clean_csv(_write_csv(tmp_path))
    aoa = df[find_col(df, AOA_ALIASES)]
    # Real driver/wedge attack angles are negative here; the numeric cleanup
    # must not strip the minus sign.
    assert (aoa < 0).all()
    assert round(float(aoa.iloc[0]), 3) == -0.618


# --- target windows -----------------------------------------------------------

def test_get_targets_covers_every_bag_club():
    for club in CLUB_ORDER:
        t = get_targets(club, speed=100.0)
        assert t.launch_window[0] <= t.launch_optimal <= t.launch_window[1]
        assert t.spin_window[0] <= t.spin_optimal <= t.spin_window[1]
        lo, hi = t.aoa_window
        assert lo < hi


def test_get_targets_normalizes_aliases():
    assert get_targets("driver").club == "Dr"
    assert get_targets("9i").club == "9I"
    # Same physical club via different spellings -> identical targets.
    assert get_targets("I7") == get_targets("7I")


def test_get_targets_launch_center_matches_config_scaling():
    # targets.py must wrap config's speed-scaled optimum, not reinvent it.
    launch, spin = optimal_launch_spin("Dr", 120.0)
    t = get_targets("Dr", speed=120.0)
    assert t.launch_optimal == launch
    assert t.spin_optimal == spin


def test_target_windows_shift_with_club_speed():
    # Phase 2 item 3: faster than the tour baseline -> flatter launch, less
    # spin (anti-balloon). The scorer consumes these speed-scaled windows.
    slow = get_targets("Dr", speed=95)
    fast = get_targets("Dr", speed=125)
    assert fast.launch_optimal < slow.launch_optimal
    assert fast.spin_optimal < slow.spin_optimal


def test_driver_aoa_window_rewards_upward_strike():
    # Sanity on the heuristic table: driver ideal AoA is positive (hitting up),
    # a mid-iron's is negative (descending) — the Phase 1 diagnostic leans on
    # this sign convention.
    assert get_targets("Dr").aoa_window[1] > 0
    assert get_targets("7I").aoa_window[1] < 0


# --- engine interfaces are importable & stable --------------------------------
# (ShotScorer / DiagnosticsEngine behavior is covered in test_scoring.py and
# test_diagnostics.py; here we just pin the shared package surface and the
# still-stubbed normalizer.)

def test_engines_expose_expected_interface():
    df = pd.DataFrame({"club": ["Dr"], "aoa": [-0.6], "backspin": [3200]})
    assert isinstance(ShotScorer().score(df), pd.Series)
    assert isinstance(DiagnosticsEngine().flags(df), list)


def test_normalizer_is_nondestructive():
    # Behavior lives in test_normalizer.py; here we just pin that it never
    # mutates the caller's frame in place.
    df = pd.DataFrame({"club": ["Dr"], "carry": [250.0]})
    out = EnvironmentalNormalizer().normalize(df, temp_f=50.0)
    assert out is not df
    assert df["carry"].iloc[0] == 250.0
