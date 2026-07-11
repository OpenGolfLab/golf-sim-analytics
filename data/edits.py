"""Reversible session/shot edits — soft delete + club overrides.

Like the adapter-tag sidecar, this never touches the archived Parquet. Edits
live in ``edits.json`` in the data dir and are applied on load:

    {"deleted_sessions": [...],       # whole sessions hidden
     "deleted_shots": [...],          # individual shots hidden, by shot_uid
     "club_overrides": {uid: club}}   # a shot's club reassigned

Every shot gets a stable ``shot_uid``: its GSPro ShotID (GUID) when it has one
(live-tracked shots), else ``"<session_id>#<position>"`` — stable across loads
because a session's archived rows never change order. Anything here is
undoable and no real data is ever lost.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from config import normalize_club_name

log = logging.getLogger(__name__)

_EDITS_FILE = "edits.json"
SHOT_UID = "shot_uid"
_EMPTY = {"deleted_sessions": [], "deleted_shots": [], "club_overrides": {}}


def _path(data_dir) -> Path:
    return Path(data_dir) / _EDITS_FILE


def load_edits(data_dir) -> dict:
    path = _path(data_dir)
    if not path.exists():
        return {k: (list(v) if isinstance(v, list) else dict(v)) for k, v in _EMPTY.items()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Could not read %s — ignoring edits", path, exc_info=True)
        data = {}
    return {
        "deleted_sessions": list(data.get("deleted_sessions", [])),
        "deleted_shots": list(data.get("deleted_shots", [])),
        "club_overrides": dict(data.get("club_overrides", {})),
    }


def save_edits(data_dir, edits: dict) -> None:
    path = _path(data_dir)
    try:
        path.write_text(json.dumps(edits, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        # e.g. a transient OneDrive/AV lock on the file. The UI reloads edits
        # from disk after every mutation, so a failed save shows up as the
        # edit visibly not sticking — never as a crash in a click handler.
        log.exception("Failed to save edits to %s", path)


def add_shot_uid(df: pd.DataFrame) -> pd.DataFrame:
    """Add a stable ``shot_uid`` column (GSPro ShotID when present, else
    ``session_id#position``)."""
    if df.empty:
        return df
    df = df.copy()
    if "session_id" in df.columns:
        pos = df.groupby("session_id").cumcount().astype(str)
        base = df["session_id"].astype(str) + "#" + pos
    else:
        base = pd.Series([f"row#{i}" for i in range(len(df))], index=df.index)
    if "shot_id" in df.columns:
        sid = df["shot_id"].astype(str)
        valid = df["shot_id"].notna() & ~sid.str.lower().isin(("", "nan", "none"))
        df[SHOT_UID] = sid.where(valid, base)
    else:
        df[SHOT_UID] = base
    return df


def apply_edits(df: pd.DataFrame, edits: dict) -> pd.DataFrame:
    """Hide deleted sessions/shots and apply club overrides. Expects a
    ``shot_uid`` column (see add_shot_uid); non-destructive."""
    if df.empty:
        return df
    df = df.copy()
    dsessions = set(map(str, edits.get("deleted_sessions", [])))
    dshots = set(edits.get("deleted_shots", []))
    overrides = edits.get("club_overrides", {})

    if dsessions and "session_id" in df.columns:
        df = df[~df["session_id"].astype(str).isin(dsessions)]
    if dshots and SHOT_UID in df.columns:
        df = df[~df[SHOT_UID].isin(dshots)]
    if overrides and SHOT_UID in df.columns and "club" in df.columns:
        mapped = df[SHOT_UID].map(overrides)
        hit = mapped.notna()
        if hit.any():
            df.loc[hit, "club"] = mapped[hit].map(normalize_club_name)
    return df


# --- mutators (load, change, save) ------------------------------------------

def _toggle_in_list(data_dir, key, value, on: bool):
    edits = load_edits(data_dir)
    lst = edits[key]
    value = str(value)
    if on and value not in lst:
        lst.append(value)
    elif not on and value in lst:
        lst.remove(value)
    save_edits(data_dir, edits)
    return edits


def delete_session(data_dir, session_id, deleted: bool = True):
    return _toggle_in_list(data_dir, "deleted_sessions", session_id, deleted)


def delete_shot(data_dir, shot_uid, deleted: bool = True):
    return _toggle_in_list(data_dir, "deleted_shots", shot_uid, deleted)


def set_club_override(data_dir, shot_uid, club):
    edits = load_edits(data_dir)
    if club:
        edits["club_overrides"][str(shot_uid)] = normalize_club_name(club)
    else:
        edits["club_overrides"].pop(str(shot_uid), None)
    save_edits(data_dir, edits)
    return edits
