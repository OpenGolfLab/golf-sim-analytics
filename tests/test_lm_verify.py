"""Launch-monitor detection (live/lm_detect.py) + the contribute-manifest
honesty check (contribute.verification_block) it feeds."""
from __future__ import annotations

import json

import pandas as pd
import pytest

import contribute
from contribute import verification_block
from live.lm_detect import detect_lm
from live.shot_data import archive_round

LM_LINE = 'LM Type {"connectType":"FlightScope","LMType":"33"}\n'


# ------------------------------------------------------------------ detect_lm
def test_detect_lm_reads_last_lm_type_line(tmp_path):
    (tmp_path / "Player.log").write_text(
        'noise\nLM Type {"connectType":"Uneekor","LMType":"7"}\nnoise\n' + LM_LINE + "more noise\n"
    )
    assert detect_lm(tmp_path) == {"connect_type": "FlightScope", "lm_type_code": "33"}


def test_detect_lm_falls_back_to_prev_log(tmp_path):
    # GSPro relaunched: current log has no LM line yet, rotated log does.
    (tmp_path / "Player.log").write_text("fresh boot, no shots\n")
    (tmp_path / "Player-prev.log").write_text(LM_LINE)
    assert detect_lm(tmp_path)["connect_type"] == "FlightScope"


def test_detect_lm_missing_logs_returns_empty(tmp_path):
    assert detect_lm(tmp_path) == {}


def test_detect_lm_malformed_json_is_skipped(tmp_path):
    (tmp_path / "Player.log").write_text("LM Type {not json}\n" + LM_LINE)
    assert detect_lm(tmp_path)["connect_type"] == "FlightScope"


def test_detect_lm_only_reads_tail_of_huge_log(tmp_path):
    # LM line buried past the tail window is invisible; one inside it wins.
    pad = "x" * 200 + "\n"
    (tmp_path / "Player.log").write_text(
        'LM Type {"connectType":"Uneekor","LMType":"7"}\n' + pad * 5000 + LM_LINE
    )
    assert detect_lm(tmp_path)["connect_type"] == "FlightScope"


# ------------------------------------------------------- archive stamping
def _shots():
    return [{"BallSpeed": 150.0, "ClubIndex": 0, "RoundID": -1, "ShotID": "a",
             "GhostData": {"cy": 200.0, "el": 15.0}}]


def test_archive_round_stamps_lm_columns(tmp_path):
    info = archive_round(_shots(), tmp_path, tmp_path,
                         lm_info={"connect_type": "FlightScope", "lm_type_code": "33"})
    df = pd.read_parquet(info["parquet_path"])
    assert set(df["lm_connect_type"]) == {"FlightScope"}
    assert set(df["lm_type_code"]) == {"33"}


def test_archive_round_without_lm_info_has_no_lm_columns(tmp_path):
    info = archive_round(_shots(), tmp_path, tmp_path, lm_info={})
    df = pd.read_parquet(info["parquet_path"])
    assert "lm_connect_type" not in df.columns


# ------------------------------------------------------ verification_block
def test_verification_match():
    out = verification_block("Mevo+", ["FlightScope"])
    assert out == {"status": "match", "observed_connect_types": ["FlightScope"]}


def test_verification_mismatch_flags_lie():
    # Claimed a Trackman, but GSPro heard a FlightScope -> bad data.
    assert verification_block("Trackman", ["FlightScope"])["status"] == "mismatch"


def test_verification_unverified_without_observations():
    assert verification_block("Trackman", [])["status"] == "unverified"


def test_verification_unverified_for_unattributable_connect_type():
    # A generic bridge connect names no manufacturer — can't judge the claim.
    assert verification_block("Trackman", ["OpenAPI"])["status"] == "unverified"


def test_verification_unverified_for_blank_or_other_claim():
    assert verification_block("", ["FlightScope"])["status"] == "unverified"
    assert verification_block("Other", ["FlightScope"])["status"] == "unverified"


def test_verification_mixed_observations_with_any_conflict_is_mismatch():
    out = verification_block("Mevo+", ["FlightScope", "Uneekor"])
    assert out["status"] == "mismatch"


def test_verification_bushnell_counts_as_foresight():
    assert verification_block("Bushnell Launch Pro", ["Foresight"])["status"] == "match"


def test_verification_ignores_nan_strings():
    assert verification_block("Mevo+", ["nan", "FlightScope"]) == {
        "status": "match", "observed_connect_types": ["FlightScope"]}


# ------------------------------------------------- manifest wiring (_prepare)
def _contrib_df(connect_type=None):
    df = pd.DataFrame({
        "club": ["Dr"] * 3,
        "ballspeed": [150.0, 151.0, 152.0],
        "vla": [13.0, 13.5, 14.0],
        "backspin": [2500.0, 2600.0, 2400.0],
        "carry": [250.0, 252.0, 254.0],
    })
    if connect_type is not None:
        df["lm_connect_type"] = connect_type
    return df


@pytest.mark.parametrize("connect_type,claim,expected", [
    ("FlightScope", "Mevo+", "match"),
    ("FlightScope", "Trackman", "mismatch"),
    (None, "Trackman", "unverified"),  # CSV-only history: nothing observed
])
def test_manifest_carries_verification(tmp_path, connect_type, claim, expected):
    contribute.record_consent(str(tmp_path), True)
    bundle = contribute.build_bundle(
        _contrib_df(connect_type), str(tmp_path), app_dir=str(tmp_path),
        launch_monitor=claim)
    manifest = json.loads(open(f"{bundle}/manifest.json").read())
    ver = manifest["environment"]["instrument"]["verification"]
    assert ver["status"] == expected
    # The claim is still recorded as-is; verification never rewrites it.
    assert manifest["environment"]["instrument"]["model"] == claim
