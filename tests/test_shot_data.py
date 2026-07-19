import json
import math

import pandas as pd

from live.shot_data import (
    archive_round, flatten_shot, heal_missing_holeshot, round_type_for,
)

SAMPLE_SHOT = {
    "ShotID": "f3fe6977-a3c0-452d-bca9-d63a91edb477",
    "RoundID": -1,
    "PlayerName": "Practice",
    "Hole": 0,
    "HolePar": 4,
    "HoleShot": 1,
    "ShotResult": 0,
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
    # GSPro's stroke numbering — the scorecard's stroke source (mulligans
    # repeat a HoleShot, so records-per-hole overcounts; see data/on_course).
    assert flat["holeshot"] == 1
    assert flat["shot_result"] == 0


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


def test_archive_round_snapshots_the_club_lookup_once(tmp_path):
    """The archive burst must cost ONE GSPro.db read (snapshot), never a
    fresh connection per shot — GSPro is writing its own round data at the
    exact moment rounds archive (see live/gspro_db.py)."""
    data_dir = tmp_path / "parquet_data"
    raw_dir = tmp_path / "live_rounds_raw"
    data_dir.mkdir()
    raw_dir.mkdir()

    class _Snap:
        def __init__(self):
            self.lookups = 0

        def lookup(self, ball_speed, carry):
            self.lookups += 1
            return {"clubspeed": 110.0}

    class _Lookup:
        def __init__(self):
            self.snapshots = 0
            self.direct_lookups = 0
            self.snap = _Snap()

        def snapshot(self, expected_shots=0):
            self.snapshots += 1
            return self.snap

        def lookup(self, ball_speed, carry):
            self.direct_lookups += 1
            return {}

    lk = _Lookup()
    shots = [SAMPLE_SHOT, {**SAMPLE_SHOT, "ShotID": "second-shot"}]
    archive_round(shots, data_dir, raw_dir, club_lookup=lk)

    assert lk.snapshots == 1       # one DB read for the whole round
    assert lk.direct_lookups == 0  # never once-per-shot against the DB
    assert lk.snap.lookups == 2    # every shot still matched, from memory


def test_archive_round_on_course_never_touches_the_club_lookup(tmp_path):
    """DrivingRangeShot only holds range shots, so on-course rounds can't
    match — archiving one must not open GSPro.db at all."""
    data_dir = tmp_path / "parquet_data"
    raw_dir = tmp_path / "live_rounds_raw"
    data_dir.mkdir()
    raw_dir.mkdir()

    class _Explodes:
        def snapshot(self, expected_shots=0):
            raise AssertionError("on-course archive must not touch GSPro.db")

        def lookup(self, ball_speed, carry):
            raise AssertionError("on-course archive must not touch GSPro.db")

    shots = [{**SAMPLE_SHOT, "RoundID": 42}]
    info = archive_round(shots, data_dir, raw_dir, club_lookup=_Explodes())

    assert info["round_type"] == "on_course"
    df = pd.read_parquet(info["parquet_path"])
    assert "clubspeed" not in df.columns  # nothing enriched, same as before


def test_heal_missing_holeshot_backfills_from_raw_json(tmp_path):
    """On-course Parquet archived before the holeshot column existed gains
    holeshot/shot_result from its raw JSON snapshot, joined by ShotID —
    everything else in the file untouched."""
    data_dir = tmp_path / "parquet_data"
    raw_dir = tmp_path / "live_rounds_raw"
    data_dir.mkdir()
    raw_dir.mkdir()

    shots = [
        {**SAMPLE_SHOT, "RoundID": 42, "ShotID": "a", "HoleShot": 1},
        {**SAMPLE_SHOT, "RoundID": 42, "ShotID": "b", "HoleShot": 1},  # mulligan re-hit
        {**SAMPLE_SHOT, "RoundID": 42, "ShotID": "c", "HoleShot": 2, "ShotResult": 2},
    ]
    info = archive_round(shots, data_dir, raw_dir)
    # Simulate the pre-holeshot schema by stripping the new columns.
    df = pd.read_parquet(info["parquet_path"])
    df.drop(columns=["holeshot", "shot_result"]).to_parquet(
        info["parquet_path"], engine="pyarrow", index=False)

    assert heal_missing_holeshot(data_dir, raw_dir) == 1

    healed = pd.read_parquet(info["parquet_path"])
    assert list(healed["holeshot"]) == [1, 1, 2]
    assert list(healed["shot_result"]) == [0, 0, 2]
    assert list(healed["club"]) == list(df["club"])  # rest of the file intact

    # Second run finds nothing to do — the column is there now.
    assert heal_missing_holeshot(data_dir, raw_dir) == 0


def test_heal_missing_holeshot_skips_files_without_raw_snapshot(tmp_path):
    data_dir = tmp_path / "parquet_data"
    raw_dir = tmp_path / "live_rounds_raw"
    data_dir.mkdir()
    raw_dir.mkdir()
    pd.DataFrame({"shot_id": ["a"], "club": ["Dr"]}).to_parquet(
        data_dir / "live-01-01-26-00-00-00-on_course.parquet", index=False)
    assert heal_missing_holeshot(data_dir, raw_dir) == 0


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
