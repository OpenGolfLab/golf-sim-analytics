"""Multi-player attribution: the sidecar, GSPro name extraction, backfill,
and the player filter."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from data import filters as filters_mod
from data import players


def _df(session_ids):
    return pd.DataFrame({
        "session_id": session_ids,
        "club": ["Dr"] * len(session_ids),
        "carry": range(len(session_ids)),
    })


# --- normalize_name -------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Tyler", "Tyler"),
    ("  Tyler  ", "Tyler"),
    ("Ty   ler", "Ty ler"),      # inner whitespace collapses
    ("", ""),
    (None, ""),
    ("Practice", ""),            # GSPro's range sentinel is not a golfer
    ("practice", ""),
    ("PRACTICE", ""),
])
def test_normalize_name(raw, expected):
    assert players.normalize_name(raw) == expected


def test_normalize_name_caps_length():
    assert len(players.normalize_name("x" * 100)) == players.NAME_MAX


# --- sidecar round-trip ---------------------------------------------------

def test_save_and_load(tmp_path):
    players.save_player(tmp_path, "s1", "Tyler")
    players.save_player(tmp_path, "s2", "Sam")
    assert players.load_players(tmp_path) == {"s1": "Tyler", "s2": "Sam"}


def test_blank_name_unassigns(tmp_path):
    players.save_player(tmp_path, "s1", "Tyler")
    players.save_player(tmp_path, "s1", "")
    assert players.load_players(tmp_path) == {}


def test_load_missing_file_is_empty(tmp_path):
    assert players.load_players(tmp_path) == {}


def test_load_corrupt_file_degrades(tmp_path):
    (tmp_path / "players.json").write_text("{not json", encoding="utf-8")
    assert players.load_players(tmp_path) == {}


def test_load_non_object_degrades(tmp_path):
    (tmp_path / "players.json").write_text('["Tyler"]', encoding="utf-8")
    assert players.load_players(tmp_path) == {}


def test_save_players_bulk(tmp_path):
    players.save_player(tmp_path, "s1", "Tyler")
    players.save_players(tmp_path, {"s2": "Sam", "s3": "Alex", "s1": ""})
    assert players.load_players(tmp_path) == {"s2": "Sam", "s3": "Alex"}


def test_rename_player(tmp_path):
    players.save_players(tmp_path, {"s1": "Tyler", "s2": "Tyler", "s3": "Sam"})
    players.rename_player(tmp_path, "Tyler", "Ty")
    assert players.load_players(tmp_path) == {"s1": "Ty", "s2": "Ty", "s3": "Sam"}


def test_rename_to_blank_is_rejected(tmp_path):
    """A blank rename would orphan every session that golfer owns."""
    players.save_player(tmp_path, "s1", "Tyler")
    players.rename_player(tmp_path, "Tyler", "   ")
    assert players.load_players(tmp_path) == {"s1": "Tyler"}


# --- apply / query --------------------------------------------------------

def test_apply_players_adds_column():
    out = players.apply_players(_df(["s1", "s2", "s3"]), {"s1": "Tyler", "s3": "Sam"})
    assert list(out[players.PLAYER_COLUMN]) == ["Tyler", players.UNASSIGNED, "Sam"]


def test_apply_players_never_drops_rows():
    df = _df(["s1", "s2"])
    assert len(players.apply_players(df, {})) == len(df)


def test_apply_players_without_session_id():
    df = pd.DataFrame({"club": ["Dr"], "carry": [250]})
    out = players.apply_players(df, {"s1": "Tyler"})
    assert list(out[players.PLAYER_COLUMN]) == [players.UNASSIGNED]


def test_available_players_excludes_unassigned():
    out = players.apply_players(_df(["s1", "s2", "s3"]), {"s1": "Tyler", "s3": "Sam"})
    assert players.available_players(out) == ["Sam", "Tyler"]


def test_has_unassigned():
    tagged = players.apply_players(_df(["s1"]), {"s1": "Tyler"})
    assert not players.has_unassigned(tagged)
    mixed = players.apply_players(_df(["s1", "s2"]), {"s1": "Tyler"})
    assert players.has_unassigned(mixed)


# --- GSPro name extraction ------------------------------------------------

def test_player_from_shots_on_course():
    assert players.player_from_shots(
        [{"PlayerName": "Tyler", "RoundID": 7}]) == "Tyler"


def test_player_from_shots_range_sentinel_is_not_a_player():
    assert players.player_from_shots(
        [{"PlayerName": "Practice", "RoundID": -1}]) == ""


def test_player_from_shots_scans_past_malformed_first_record():
    shots = [{"RoundID": 7}, {"PlayerName": "Sam", "RoundID": 7}]
    assert players.player_from_shots(shots) == "Sam"


def test_player_from_shots_empty():
    assert players.player_from_shots([]) == ""
    assert players.player_from_shots(None) == ""


# --- backfill -------------------------------------------------------------

def _write_raw(raw_dir, session_id, name, round_id=7):
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{session_id}.json").write_text(
        json.dumps([{"PlayerName": name, "RoundID": round_id, "ShotID": "a"}]),
        encoding="utf-8")


def test_backfill_attributes_on_course_rounds(tmp_path):
    raw = tmp_path / "live_rounds_raw"
    _write_raw(raw, "live-07-19-26-13-12-04-on_course", "Tyler")
    _write_raw(raw, "live-07-26-26-12-12-56-on_course", "Sam")
    assert players.backfill_from_archives(tmp_path, raw) == 2
    assert players.load_players(tmp_path) == {
        "live-07-19-26-13-12-04-on_course": "Tyler",
        "live-07-26-26-12-12-56-on_course": "Sam",
    }


def test_backfill_never_overwrites_a_manual_assignment(tmp_path):
    raw = tmp_path / "live_rounds_raw"
    _write_raw(raw, "live-07-19-26-13-12-04-on_course", "Tyler")
    players.save_player(tmp_path, "live-07-19-26-13-12-04-on_course", "Sam")
    assert players.backfill_from_archives(tmp_path, raw) == 0
    assert players.load_players(tmp_path)["live-07-19-26-13-12-04-on_course"] == "Sam"


def test_backfill_is_idempotent(tmp_path):
    raw = tmp_path / "live_rounds_raw"
    _write_raw(raw, "live-07-19-26-13-12-04-on_course", "Tyler")
    assert players.backfill_from_archives(tmp_path, raw) == 1
    assert players.backfill_from_archives(tmp_path, raw) == 0


def test_backfill_skips_practice_archives(tmp_path):
    """Practice files aren't even globbed — and carry only the sentinel anyway."""
    raw = tmp_path / "live_rounds_raw"
    _write_raw(raw, "live-07-08-26-10-08-07-practice", "Practice", round_id=-1)
    assert players.backfill_from_archives(tmp_path, raw) == 0
    assert players.load_players(tmp_path) == {}


def test_backfill_survives_corrupt_json(tmp_path):
    raw = tmp_path / "live_rounds_raw"
    raw.mkdir(parents=True)
    (raw / "live-07-19-26-13-12-04-on_course.json").write_text("{bad", encoding="utf-8")
    _write_raw(raw, "live-07-26-26-12-12-56-on_course", "Sam")
    assert players.backfill_from_archives(tmp_path, raw) == 1


def test_backfill_missing_dir(tmp_path):
    assert players.backfill_from_archives(tmp_path, tmp_path / "nope") == 0


# --- claim_unassigned (the upgrade migration) -----------------------------

def test_claim_unassigned_takes_only_untagged(tmp_path):
    players.save_player(tmp_path, "s2", "Sam")
    claimed = players.claim_unassigned(tmp_path, ["s1", "s2", "s3"], "Tyler")
    assert claimed == 2
    assert players.load_players(tmp_path) == {"s1": "Tyler", "s2": "Sam", "s3": "Tyler"}


def test_claim_unassigned_needs_a_name(tmp_path):
    assert players.claim_unassigned(tmp_path, ["s1"], "") == 0
    assert players.load_players(tmp_path) == {}


def test_primary_player_is_the_most_frequent(tmp_path):
    players.save_players(tmp_path, {"a": "Tyler", "b": "Tyler", "c": "Sam"})
    assert players.primary_player(tmp_path) == "Tyler"


def test_primary_player_breaks_ties_alphabetically(tmp_path):
    players.save_players(tmp_path, {"a": "Tyler", "b": "Sam"})
    assert players.primary_player(tmp_path) == "Sam"


def test_primary_player_empty(tmp_path):
    assert players.primary_player(tmp_path) == ""


def test_upgrade_path_adopts_gspro_name_then_claims(tmp_path):
    """End-to-end migration: an existing history with on-course rounds ends up
    fully attributed without the user typing anything."""
    raw = tmp_path / "live_rounds_raw"
    _write_raw(raw, "live-07-19-26-13-12-04-on_course", "Tyler")
    _write_raw(raw, "live-07-26-26-12-12-56-on_course", "Tyler")
    players.backfill_from_archives(tmp_path, raw)

    adopted = players.primary_player(tmp_path)
    assert adopted == "Tyler"

    all_sessions = ["live-07-19-26-13-12-04-on_course",
                    "live-07-26-26-12-12-56-on_course",
                    "gspro-export01-20-26-18-56-42",     # a range CSV session
                    "live-07-08-26-10-08-07-practice"]
    players.claim_unassigned(tmp_path, all_sessions, adopted)
    tagged = players.apply_players(_df(all_sessions), players.load_players(tmp_path))
    assert not players.has_unassigned(tagged)
    assert players.available_players(tagged) == ["Tyler"]


# --- the filter -----------------------------------------------------------

def _tagged():
    return players.apply_players(
        _df(["s1", "s2", "s3", "s4"]), {"s1": "Tyler", "s2": "Sam", "s3": "Tyler"})


def test_filter_by_player():
    out = filters_mod.filter_master_data(
        _tagged(), filters_mod.TIME_ALL, filters_mod.CLUB_ALL,
        filters_mod.QUALITY_ALL, player_filter="Tyler")
    assert list(out["session_id"]) == ["s1", "s3"]


def test_filter_player_all_keeps_everything():
    out = filters_mod.filter_master_data(
        _tagged(), filters_mod.TIME_ALL, filters_mod.CLUB_ALL,
        filters_mod.QUALITY_ALL, player_filter=filters_mod.PLAYER_ALL)
    assert len(out) == 4


def test_filter_none_keeps_everything():
    """Default (no player argument) must behave exactly as before the feature."""
    out = filters_mod.filter_master_data(
        _tagged(), filters_mod.TIME_ALL, filters_mod.CLUB_ALL, filters_mod.QUALITY_ALL)
    assert len(out) == 4


def test_filter_unassigned_bucket_is_selectable():
    out = filters_mod.filter_master_data(
        _tagged(), filters_mod.TIME_ALL, filters_mod.CLUB_ALL,
        filters_mod.QUALITY_ALL, player_filter=players.UNASSIGNED)
    assert list(out["session_id"]) == ["s4"]


def test_filter_without_player_column_is_a_noop():
    out = filters_mod.filter_master_data(
        _df(["s1", "s2"]), filters_mod.TIME_ALL, filters_mod.CLUB_ALL,
        filters_mod.QUALITY_ALL, player_filter="Tyler")
    assert len(out) == 2


def test_player_filter_runs_before_time_filter():
    """"Last Session" must mean the SELECTED golfer's last session, not the
    household's — otherwise picking someone who last played in March shows
    somebody else's Tuesday."""
    df = pd.DataFrame({
        "session_id": ["mar", "jul", "aug"],
        "session_date": pd.to_datetime(["2026-03-01", "2026-07-01", "2026-08-01"]),
        "club": ["Dr"] * 3,
        "carry": [250, 260, 270],
    })
    df = players.apply_players(df, {"mar": "Tyler", "jul": "Sam", "aug": "Sam"})
    out = filters_mod.filter_master_data(
        df, filters_mod.TIME_LAST_SESSION, filters_mod.CLUB_ALL,
        filters_mod.QUALITY_ALL, player_filter="Tyler")
    assert list(out["session_id"]) == ["mar"]
