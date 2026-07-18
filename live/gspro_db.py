"""Read the club data GSPro logs to its own SQLite DB.

GSPro's ``currentRound.dat`` (what live/round_watcher.py polls) is ball-flight
state and strips out club data. But GSPro *also* logs every practice-range shot
to ``GSPro.db`` -> table ``DrivingRangeShot``, as a ``ShotData`` JSON blob that
keeps the full shot — including ClubSpeed, SmashFactor and AoA, which the
launch monitor measures but currentRound.dat drops.

The two files record the same shots with identical BallSpeed/Carry values, so a
live-tracked shot can be matched to its DrivingRangeShot row by those and have
its club data filled in. This is read-only and tolerant of GSPro holding the DB
open (short read-only connections, best-effort — a miss just leaves club data
blank, same as before). On-course shots aren't in DrivingRangeShot, so they
never match and stay unchanged.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from config import normalize_club_name

log = logging.getLogger(__name__)

# DrivingRangeShot.ShotData field -> this app's per-shot column name.
_CLUB_FIELDS = {"ClubSpeed": "clubspeed", "SmashFactor": "smashfactor", "AoA": "aoa"}

_BALLSPEED_TOL = 0.1  # mph — same source value in both files, so near-exact


def _match(rows: list[dict], ball_speed, carry) -> dict:
    """Club data for the shot in ``rows`` (newest-first) matching
    ``ball_speed``, or ``{}`` when there's no match. Ball speed is the same
    float in both files, so it's the primary key; carry only breaks ties when
    several recent shots share a ball speed (and is checked against all three
    carry fields, since currentRound.dat's carry equals DrivingRangeShot's
    rawCarryLM, not its Carry)."""
    if ball_speed is None:
        return {}
    # rows is newest-first, so this list preserves that order.
    cands = [d for d in rows
             if d.get("BallSpeed") is not None
             and abs(d["BallSpeed"] - ball_speed) < _BALLSPEED_TOL]
    if not cands:
        return {}
    if len(cands) > 1 and carry is not None:
        def _carry_dist(d):
            cs = [d.get(k) for k in ("Carry", "rawCarryLM", "rawCarryGame")]
            return min((abs(c - carry) for c in cs if c is not None), default=1e9)
        cands.sort(key=_carry_dist)  # stable: keeps newest-first among ties
    best = cands[0]
    out = {dst: best[src] for src, dst in _CLUB_FIELDS.items()
           if best.get(src) not in (None, 0, 0.0)}
    # GSPro.db records the real club name; currentRound.dat's ClubIndex is
    # always 0 on this monitor, so this is the only reliable club source.
    club = best.get("club")
    if club:
        out["club"] = normalize_club_name(club)
    return out


class ClubDataLookup:
    """Matches a live shot to its GSPro.db DrivingRangeShot row and returns the
    club data (clubspeed / smashfactor / aoa) that row carries."""

    def __init__(self, db_path, max_rows: int = 60):
        self.db_path = Path(db_path)
        self.max_rows = max_rows

    def _recent_shotdata(self, max_rows: int | None = None) -> list[dict]:
        if not self.db_path.exists():
            return []
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=0.5)
        except sqlite3.Error:
            return []
        try:
            rows = con.execute(
                "SELECT ShotData FROM DrivingRangeShot ORDER BY ID DESC LIMIT ?",
                (max_rows or self.max_rows,),
            ).fetchall()
        except sqlite3.Error:
            return []  # DB busy/locked or table absent — just skip this shot
        finally:
            con.close()
        out = []
        for (sd,) in rows:
            try:
                out.append(json.loads(sd))
            except (ValueError, TypeError):
                pass
        return out

    def lookup(self, ball_speed, carry) -> dict:
        """One live shot's club data, read fresh from GSPro.db.

        Fine at live-play cadence (one short read per detected shot). For the
        archive-time burst — every shot of a finished round at once — use
        snapshot() so the whole round costs one read instead of one per shot;
        GSPro is busy writing its own round data at that exact moment, and
        each open/SELECT here briefly shared-locks a database GSPro is using.
        """
        return _match(self._recent_shotdata(), ball_speed, carry)

    def snapshot(self, expected_shots: int = 0) -> "SnapshotLookup":
        """A cached, zero-further-I/O lookup for archive-time bursts.

        Reads DrivingRangeShot once — sized to cover the round being archived
        (``expected_shots``), never less than the live default — and answers
        every subsequent lookup() from memory. Also a small matching upgrade
        for long sessions: per-shot lookups only ever saw the newest
        ``max_rows`` rows, so rounds longer than that couldn't match their
        earliest shots."""
        rows = self._recent_shotdata(max_rows=max(self.max_rows, expected_shots + 10))
        return SnapshotLookup(rows)


class SnapshotLookup:
    """Same lookup() API as ClubDataLookup, over rows already in memory —
    created by ClubDataLookup.snapshot(); touches the database never."""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    def lookup(self, ball_speed, carry) -> dict:
        return _match(self._rows, ball_speed, carry)
