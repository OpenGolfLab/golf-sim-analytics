"""GSPro.db club-data lookup + flatten_shot enrichment (live/gspro_db.py)."""
from __future__ import annotations

import json
import sqlite3

from live.gspro_db import ClubDataLookup
from live.shot_data import flatten_shot


def _make_db(path, rows):
    """rows: list of dicts merged into a full ShotData blob, newest last."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE DrivingRangeShot (ID INTEGER PRIMARY KEY AUTOINCREMENT, "
                "DateCreated TEXT, ShotData TEXT)")
    for r in rows:
        blob = {"BallSpeed": 150.0, "Carry": 200.0, "ClubSpeed": 110.0,
                "SmashFactor": 1.4, "AoA": 1.0, "club": "DR"}
        blob.update(r)
        con.execute("INSERT INTO DrivingRangeShot (DateCreated, ShotData) VALUES (?, ?)",
                    ("2026-07-09", json.dumps(blob)))
    con.commit()
    con.close()


def test_lookup_matches_by_ball_speed(tmp_path):
    db = tmp_path / "GSPro.db"
    _make_db(db, [{"BallSpeed": 154.07, "Carry": 218.6, "ClubSpeed": 123.0,
                   "SmashFactor": 1.25, "AoA": 0.54}])
    out = ClubDataLookup(db).lookup(154.07, 218.6)
    assert out == {"clubspeed": 123.0, "smashfactor": 1.25, "aoa": 0.54, "club": "Dr"}


def test_lookup_no_match_returns_empty(tmp_path):
    db = tmp_path / "GSPro.db"
    _make_db(db, [{"BallSpeed": 154.07, "Carry": 218.6}])
    assert ClubDataLookup(db).lookup(120.0, 150.0) == {}


def test_lookup_carry_disambiguates_same_ball_speed(tmp_path):
    db = tmp_path / "GSPro.db"
    _make_db(db, [{"BallSpeed": 150.0, "Carry": 180.0, "ClubSpeed": 100.0},
                  {"BallSpeed": 150.0, "Carry": 250.0, "ClubSpeed": 130.0}])
    assert ClubDataLookup(db).lookup(150.0, 250.0)["clubspeed"] == 130.0


def test_lookup_missing_db_is_safe(tmp_path):
    assert ClubDataLookup(tmp_path / "nope.db").lookup(150.0, 200.0) == {}


def test_lookup_skips_zero_club_speed(tmp_path):
    db = tmp_path / "GSPro.db"
    _make_db(db, [{"BallSpeed": 150.0, "Carry": 200.0, "ClubSpeed": 0.0,
                   "SmashFactor": 0.0, "AoA": 2.5}])
    # Zeroed club/smash dropped; a real AoA (and the club name) still come through.
    assert ClubDataLookup(db).lookup(150.0, 200.0) == {"aoa": 2.5, "club": "Dr"}


def test_flatten_shot_enriches_with_club_data(tmp_path):
    db = tmp_path / "GSPro.db"
    _make_db(db, [{"BallSpeed": 154.07, "Carry": 218.6, "ClubSpeed": 123.0,
                   "SmashFactor": 1.25, "AoA": 0.54}])
    raw = {"BallSpeed": 154.07, "ClubIndex": 0, "TotalDistance": 227.6,
           "GhostData": {"cy": 218.6, "el": 23.2, "az": 0.16, "ts": 5800, "sa": 6.1}}
    flat = flatten_shot(raw, ClubDataLookup(db))
    assert flat["clubspeed"] == 123.0
    assert flat["smashfactor"] == 1.25
    assert round(flat["aoa"], 2) == 0.54


def test_flatten_shot_without_lookup_has_no_club_speed():
    raw = {"BallSpeed": 154.07, "ClubIndex": 0, "GhostData": {"cy": 218.6, "el": 23.2}}
    flat = flatten_shot(raw)
    assert "clubspeed" not in flat


def test_lookup_returns_real_club_name(tmp_path):
    db = tmp_path / "GSPro.db"
    _make_db(db, [{"BallSpeed": 95.0, "Carry": 130.0, "club": "PW", "ClubSpeed": 84.0}])
    out = ClubDataLookup(db).lookup(95.0, 130.0)
    assert out["club"] == "Pw"  # normalized from GSPro.db's "PW"


def test_flatten_shot_uses_gspro_club_and_drops_clubindex(tmp_path):
    # ClubIndex 0 would make this look like a driver; GSPro.db says it's a Pw.
    db = tmp_path / "GSPro.db"
    _make_db(db, [{"BallSpeed": 95.0, "Carry": 130.0, "club": "PW", "ClubSpeed": 84.0}])
    raw = {"BallSpeed": 95.0, "ClubIndex": 0, "GhostData": {"cy": 130.0, "el": 28.0}}
    flat = flatten_shot(raw, ClubDataLookup(db))
    assert flat["club"] == "Pw"
    # club_index dropped so load-time re-resolution can't clobber it back to Dr.
    assert flat["club_index"] is None
