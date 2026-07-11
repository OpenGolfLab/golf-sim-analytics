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


class ClubDataLookup:
    """Matches a live shot to its GSPro.db DrivingRangeShot row and returns the
    club data (clubspeed / smashfactor / aoa) that row carries."""

    def __init__(self, db_path, max_rows: int = 60):
        self.db_path = Path(db_path)
        self.max_rows = max_rows

    def _recent_shotdata(self) -> list[dict]:
        if not self.db_path.exists():
            return []
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=0.5)
        except sqlite3.Error:
            return []
        try:
            rows = con.execute(
                "SELECT ShotData FROM DrivingRangeShot ORDER BY ID DESC LIMIT ?",
                (self.max_rows,),
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
        """Club data for the shot matching ``ball_speed``, or ``{}`` when there's
        no match. Ball speed is the same float in both files, so it's the primary
        key; carry only breaks ties when several recent shots share a ball speed
        (and is checked against all three carry fields, since currentRound.dat's
        carry equals DrivingRangeShot's rawCarryLM, not its Carry)."""
        if ball_speed is None:
            return {}
        # _recent_shotdata is newest-first, so this list preserves that order.
        cands = [d for d in self._recent_shotdata()
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
