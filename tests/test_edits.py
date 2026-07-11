"""Reversible session/shot edits (data.edits)."""
from __future__ import annotations

import pandas as pd

from data import edits


def _df():
    return pd.DataFrame({
        "session_id": ["s1", "s1", "s1", "s2", "s2"],
        "club": ["Dr", "Dr", "7I", "Dr", "Pw"],
        "carry": [250.0, 255.0, 150.0, 248.0, 110.0],
    })


def test_add_shot_uid_uses_session_and_position():
    out = edits.add_shot_uid(_df())
    assert list(out["shot_uid"]) == ["s1#0", "s1#1", "s1#2", "s2#0", "s2#1"]


def test_add_shot_uid_prefers_gspro_shot_id():
    df = pd.DataFrame({"session_id": ["s1", "s1"], "shot_id": ["guid-A", None],
                       "club": ["Dr", "Dr"]})
    out = edits.add_shot_uid(df)
    assert list(out["shot_uid"]) == ["guid-A", "s1#1"]  # falls back when no id


def test_apply_edits_deletes_session():
    df = edits.add_shot_uid(_df())
    out = edits.apply_edits(df, {"deleted_sessions": ["s2"]})
    assert set(out["session_id"]) == {"s1"}
    assert len(out) == 3


def test_apply_edits_deletes_individual_shot():
    df = edits.add_shot_uid(_df())
    out = edits.apply_edits(df, {"deleted_shots": ["s1#2"]})
    assert len(out) == 4
    assert "7I" not in list(out["club"])


def test_apply_edits_club_override():
    df = edits.add_shot_uid(_df())
    # The "7I" at s1#2 was really a Pw; reassign it.
    out = edits.apply_edits(df, {"club_overrides": {"s1#2": "Pw"}})
    assert out.loc[out["shot_uid"] == "s1#2", "club"].iloc[0] == "Pw"


def test_apply_edits_is_nondestructive():
    df = edits.add_shot_uid(_df())
    edits.apply_edits(df, {"deleted_sessions": ["s2"]})
    assert len(df) == 5  # original untouched


def test_mutators_round_trip(tmp_path):
    edits.delete_session(tmp_path, "s2")
    edits.delete_shot(tmp_path, "s1#0")
    edits.set_club_override(tmp_path, "s1#2", "pw")
    e = edits.load_edits(tmp_path)
    assert e["deleted_sessions"] == ["s2"]
    assert e["deleted_shots"] == ["s1#0"]
    assert e["club_overrides"] == {"s1#2": "Pw"}  # normalized
    # Toggling a delete back off removes it.
    edits.delete_session(tmp_path, "s2", deleted=False)
    assert edits.load_edits(tmp_path)["deleted_sessions"] == []


def test_load_missing_file_is_empty(tmp_path):
    assert edits.load_edits(tmp_path) == {"deleted_sessions": [], "deleted_shots": [],
                                          "club_overrides": {}}
