import json
import math

import pandas as pd

from live.shot_data import archive_round, flatten_shot, round_type_for

SAMPLE_SHOT = {
    "ShotID": "f3fe6977-a3c0-452d-bca9-d63a91edb477",
    "RoundID": -1,
    "PlayerName": "Practice",
    "Hole": 0,
    "HolePar": 4,
    "DistanceToPin": 392.000031,
    "TotalDistance": 80.56164,
    "ClubIndex": 24,
    "BallSpeed": 71.69733428955078,
    "GhostData": {
        "sp": 71.69733428955078,
        "el": 25.967784881591797,
        "az": -2.5715584754943848,
        "ts": 8048.3623,
        "sa": 4.084731578826904,
        "cy": 74.80894470214844,
    },
}


def test_flatten_shot_maps_core_fields():
    flat = flatten_shot(SAMPLE_SHOT)

    assert flat["ballspeed"] == SAMPLE_SHOT["BallSpeed"]
    assert flat["carry"] == SAMPLE_SHOT["GhostData"]["cy"]
    assert flat["totaldistance"] == SAMPLE_SHOT["TotalDistance"]
    assert flat["vla"] == SAMPLE_SHOT["GhostData"]["el"]
    assert flat["hole"] == 0
    assert flat["holepar"] == 4
    assert flat["distancetopin"] == SAMPLE_SHOT["DistanceToPin"]
    assert flat["shot_id"] == SAMPLE_SHOT["ShotID"]
    assert flat["club_index"] == 24
    # ClubIndex 24 is this bag's Sand Wedge (config.CLUB_INDEX_MAP).
    assert flat["club"] == "Sw"


def test_flatten_shot_derives_offline_from_carry_and_azimuth():
    flat = flatten_shot(SAMPLE_SHOT)
    carry = SAMPLE_SHOT["GhostData"]["cy"]
    az = SAMPLE_SHOT["GhostData"]["az"]
    assert flat["offline"] == carry * math.sin(math.radians(az))


def test_flatten_shot_derives_backspin_from_total_spin_and_spin_axis():
    flat = flatten_shot(SAMPLE_SHOT)
    ts = SAMPLE_SHOT["GhostData"]["ts"]
    sa = SAMPLE_SHOT["GhostData"]["sa"]
    assert flat["backspin"] == ts * math.cos(math.radians(sa))


def test_flatten_shot_handles_missing_ghost_data_gracefully():
    flat = flatten_shot({"ShotID": "x", "ClubIndex": None})
    assert flat["carry"] is None
    assert flat["offline"] is None
    assert flat["backspin"] is None
    assert flat["club"] == "Unknown"


def test_round_type_for_practice_when_round_id_is_negative_one():
    assert round_type_for([{"RoundID": -1}]) == "practice"


def test_round_type_for_on_course_when_round_id_is_real():
    assert round_type_for([{"RoundID": 42}]) == "on_course"


def test_round_type_for_empty_list_defaults_practice():
    assert round_type_for([]) == "practice"


def test_archive_round_writes_flattened_parquet_and_raw_json(tmp_path):
    data_dir = tmp_path / "parquet_data"
    raw_dir = tmp_path / "live_rounds_raw"
    data_dir.mkdir()
    raw_dir.mkdir()

    shots = [SAMPLE_SHOT, {**SAMPLE_SHOT, "ShotID": "second-shot"}]
    info = archive_round(shots, data_dir, raw_dir)

    assert info["shot_count"] == 2
    assert info["round_type"] == "practice"
    assert info["parquet_path"].exists()
    assert info["raw_path"].exists()

    df = pd.read_parquet(info["parquet_path"])
    assert len(df) == 2
    assert (df["round_type"] == "practice").all()
    assert (df["session_id"] == info["session_id"]).all()
    assert "club" in df.columns
    assert "club_index" in df.columns

    raw = json.loads(info["raw_path"].read_text())
    assert len(raw) == 2
    assert raw[0]["ShotID"] == SAMPLE_SHOT["ShotID"]


def test_archive_round_session_id_embeds_a_parseable_date(tmp_path):
    from data.io import extract_date_from_filename

    data_dir = tmp_path / "parquet_data"
    raw_dir = tmp_path / "live_rounds_raw"
    data_dir.mkdir()
    raw_dir.mkdir()

    finalized_at = pd.Timestamp("2026-07-08 14:30:05").to_pydatetime()
    info = archive_round([SAMPLE_SHOT], data_dir, raw_dir, finalized_at=finalized_at)

    parsed = extract_date_from_filename(info["session_id"])
    assert parsed == pd.Timestamp("2026-07-08 14:30:05")
