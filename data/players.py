"""Multi-player support — which golfer hit each session.

A household shares one sim, so one Parquet history can hold several golfers'
swings. Attribution lives in its own JSON sidecar (``players.json`` in the data
dir) keyed by ``session_id``, exactly like data/adapter_tags.py: the Parquet
archive is never rewritten, and a missing or corrupt sidecar degrades to "one
unnamed golfer" rather than an exception.

WHY A SIDECAR AND NOT A COLUMN FROM GSPRO
=========================================
GSPro only names the golfer on *course* rounds. Measured against real archives:

  * on-course live rounds  — every shot carries ``PlayerName``, and it tracks
    the active GSPro profile (renaming the profile renames it here).
  * practice-range rounds  — ``PlayerName`` is the constant sentinel
    ``"Practice"``. The range has no player concept in GSPro at all.
  * CSV exports            — 27 numeric columns, no identity field of any kind.
    (And data/io.py force-coerces unknown columns to numeric, so a name column
    would be silently turned into NaN even if one appeared.)

``UserGuid`` is no help either: it identifies the GSPro *install*, one constant
per machine, not who is standing on the mat.

So attribution is hybrid, and this module is the single place that resolves it:
on-course rounds self-attribute from ``PlayerName`` (see ``player_from_shots``),
and everything else is stamped with whoever the app's Player selector said was
hitting at capture time. Both paths land in the same sidecar, so downstream
there is exactly one rule — read the sidecar — and the dashboards never need to
know which way a session was attributed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

_PLAYERS_FILE = "players.json"
PLAYER_COLUMN = "player"
# Per-shot name as GSPro wrote it, carried through from live/shot_data.py.
SHOT_NAME_COLUMN = "player_name"

# Sessions with no attribution. Shown in the UI as a real, selectable bucket
# rather than hidden — a user who never opens the Player menu still sees all
# of their data, which is what makes this feature additive instead of a wall.
UNASSIGNED = ""
UNASSIGNED_LABEL = "Unassigned"

# GSPro writes this as PlayerName for every practice-range shot. It is a mode,
# not a person, so it must never become a player.
_RANGE_SENTINEL = "practice"

PLAYER_ALL = "All Players"

# Same shape rule as contribute.normalize_display_name — a player name is
# typed by a human, shown in a dropdown, and used in filenames-adjacent JSON.
NAME_MAX = 24


def normalize_name(name: str) -> str:
    """Trim and length-cap a player name. Returns "" for anything blank or
    for GSPro's practice-range sentinel, which is never a real golfer."""
    # NaN check before the falsy check, because NaN is TRUTHY: a missing name
    # read out of a DataFrame column would otherwise sail through
    # `name or ""` and come back as the literal string "nan" — a golfer called
    # nan appearing in the Player menu.
    if name is None or name != name:
        return ""
    cleaned = " ".join(str(name).split())
    if not cleaned or cleaned.lower() == _RANGE_SENTINEL:
        return ""
    return cleaned[:NAME_MAX]


def _players_path(data_dir) -> Path:
    return Path(data_dir) / _PLAYERS_FILE


def load_players(data_dir) -> dict[str, str]:
    """Return the {session_id: player} map, or {} when the file is absent,
    unreadable, or malformed. Blank names are dropped."""
    path = _players_path(data_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Could not read %s — treating every session as unassigned",
                    path, exc_info=True)
        return {}
    if not isinstance(data, dict):
        log.warning("%s is not a JSON object — ignoring player assignments", path)
        return {}
    out = {}
    for key, value in data.items():
        name = normalize_name(value)
        if name:
            out[str(key)] = name
    return out


def _write(data_dir, players: dict[str, str]) -> dict[str, str]:
    _players_path(data_dir).write_text(
        json.dumps(players, indent=2, sort_keys=True), encoding="utf-8")
    return players


def save_player(data_dir, session_id: str, name: str) -> dict[str, str]:
    """Assign (or, with a blank name, unassign) one session and persist.
    Returns the updated map."""
    players = load_players(data_dir)
    name = normalize_name(name)
    if name:
        players[str(session_id)] = name
    else:
        players.pop(str(session_id), None)
    return _write(data_dir, players)


def save_players(data_dir, assignments: dict[str, str]) -> dict[str, str]:
    """Apply several {session_id: name} assignments at once and persist —
    one file write for a bulk re-assignment instead of one per session."""
    players = load_players(data_dir)
    for session_id, name in assignments.items():
        name = normalize_name(name)
        if name:
            players[str(session_id)] = name
        else:
            players.pop(str(session_id), None)
    return _write(data_dir, players)


def rename_player(data_dir, old: str, new: str) -> dict[str, str]:
    """Rename a golfer across every session they own. A blank ``new`` would
    orphan those sessions, so it's rejected as a no-op."""
    old, new = normalize_name(old), normalize_name(new)
    if not old or not new or old == new:
        return load_players(data_dir)
    players = load_players(data_dir)
    for session_id, name in list(players.items()):
        if name == old:
            players[session_id] = new
    return _write(data_dir, players)


def apply_players(df: pd.DataFrame, players: dict[str, str]) -> pd.DataFrame:
    """Return a copy of ``df`` with a ``player`` column.

    Two sources, in priority order:

    1. **The shot's own ``player_name``**, captured from GSPro. On course,
       GSPro stamps every single shot with whoever hit it, so a fourball
       resolves per shot with nobody touching a control — which is the only
       workable answer, since players alternate constantly and no human is
       going to flip a selector between drives.
    2. **The session sidecar**, for everything shot 1 can't answer: the
       practice range (GSPro writes the constant "Practice" there) and CSV
       imports (no identity field at all).

    Unattributed rows get "". No row is dropped, and Parquet is never touched.
    """
    if df.empty:
        return df
    out = df.copy()
    by_session = (out["session_id"].astype(str).map(players).fillna(UNASSIGNED)
                  if "session_id" in out.columns
                  else pd.Series(UNASSIGNED, index=out.index))
    if SHOT_NAME_COLUMN in out.columns:
        per_shot = out[SHOT_NAME_COLUMN].map(normalize_name)
        # Per-shot wins wherever GSPro actually named somebody; the sidecar
        # fills every other row (including the "Practice" sentinel, which
        # normalize_name deliberately blanks).
        out[PLAYER_COLUMN] = per_shot.where(per_shot.astype(bool), by_session)
    else:
        out[PLAYER_COLUMN] = by_session
    return out


def available_players(df: pd.DataFrame) -> list[str]:
    """Distinct named golfers present in ``df``, sorted. Excludes the
    unassigned bucket — callers add that separately when it's non-empty, so
    it always sorts last instead of into the middle of the names."""
    if df.empty or PLAYER_COLUMN not in df.columns:
        return []
    vals = {str(v).strip() for v in df[PLAYER_COLUMN].dropna() if str(v).strip()}
    return sorted(vals)


def has_unassigned(df: pd.DataFrame) -> bool:
    """True when any row is still unattributed — the UI uses this to decide
    whether the Unassigned bucket is worth offering."""
    if df.empty or PLAYER_COLUMN not in df.columns:
        return False
    return bool((df[PLAYER_COLUMN].fillna(UNASSIGNED) == UNASSIGNED).any())


def players_in_shots(raw_shots: list[dict]) -> list[str]:
    """Every distinct golfer GSPro named across a round's raw records, sorted.

    A GSPro round can hold several players alternating shot for shot, so this
    is a list rather than a single answer. The practice range contributes
    nothing (its ``"Practice"`` sentinel is rejected by normalize_name).
    """
    names = {normalize_name(s.get("PlayerName")) for s in raw_shots or []}
    return sorted(n for n in names if n)


def player_from_shots(raw_shots: list[dict]) -> str:
    """The one golfer this round belongs to, or "" if that's ambiguous.

    Deliberately empty for a multi-player round: a session-level tag can only
    name one person, so applying one to a fourball would be a lie. Those rounds
    are attributed per shot instead (see apply_players), which is both accurate
    and the only thing that scales to players swapping every shot.
    """
    names = players_in_shots(raw_shots)
    return names[0] if len(names) == 1 else ""


def backfill_from_archives(data_dir, raw_archive_dir) -> int:
    """One-time startup repair: attribute already-archived on-course rounds
    from the raw JSON snapshot every live round keeps beside its Parquet.

    This is what makes the feature retroactive rather than "starts counting
    today" — the name was in the file all along, it just wasn't read. Only
    fills sessions the sidecar doesn't already have (a manual assignment
    always wins), so reruns are free. Returns how many were attributed.
    """
    raw_archive_dir = Path(raw_archive_dir)
    if not raw_archive_dir.exists():
        return 0
    players = load_players(data_dir)
    found = {}
    for raw_path in raw_archive_dir.glob("live-*-on_course.json"):
        session_id = raw_path.stem
        if session_id in players:
            continue
        try:
            raw_shots = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("backfill_from_archives: unreadable %s — skipping", raw_path)
            continue
        shots = raw_shots if isinstance(raw_shots, list) else []
        # Multi-player rounds are left out on purpose — they resolve per shot
        # from the archived player_name column, and a session-level tag would
        # hand the whole fourball to whoever happened to tee off first.
        name = player_from_shots(shots)
        if name:
            found[session_id] = name
    if found:
        players.update(found)
        _write(data_dir, players)
        log.info("backfill_from_archives: attributed %d on-course round(s) from "
                 "GSPro's PlayerName", len(found))
    return len(found)


def primary_player(data_dir) -> str:
    """The golfer who owns the most already-attributed sessions, or "".

    Used once, at upgrade time, to answer "whose history is this?" without
    asking: after backfill_from_archives has read the on-course rounds, the
    most frequent name there is overwhelmingly likely to be the person who
    also hit every untagged range session. Ties break alphabetically so the
    answer is deterministic rather than dict-order.
    """
    counts: dict[str, int] = {}
    for name in load_players(data_dir).values():
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return ""
    return sorted(counts, key=lambda n: (-counts[n], n))[0]


def claim_unassigned(data_dir, session_ids, name: str) -> int:
    """Assign every listed session that has no player yet to ``name``.

    Used once at upgrade time so an existing single-golfer history keeps
    showing up exactly as it did before the app knew what a player was —
    without this, every dashboard would silently reset to "Unassigned" on
    first launch after the update. Returns how many sessions were claimed.
    """
    name = normalize_name(name)
    if not name:
        return 0
    players = load_players(data_dir)
    claimed = {str(s): name for s in session_ids if str(s) not in players}
    if claimed:
        players.update(claimed)
        _write(data_dir, players)
    return len(claimed)
