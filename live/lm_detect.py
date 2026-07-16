"""Detect which launch monitor GSPro is actually talking to.

GSPro's Unity log (``Player.log``, same folder as ``currentRound.dat``)
writes a line like::

    LM Type {"connectType":"FlightScope","LMType":"33"}

immediately before every " * ------- Shot Fired! ------- *" entry. That
makes it the only on-disk record of the connected device — neither
currentRound.dat nor GSPro.db carries one.

This is used purely as a cross-check on the launch monitor the user
*claims* in the contribute dialog (see contribute.verification_block):
the user's selection is still the source of truth for model; the log's
connectType just tells us the manufacturer GSPro actually heard from, so
a claim of "Trackman" against a FlightScope connectType can be flagged
server-side as bad data. It is never shown to the user and never blocks
anything locally.

Practicalities:

- Player.log rotates to Player-prev.log every time GSPro launches, so
  detection must happen while the session's log is still current. The
  round watcher calls this at finalize time, when GSPro is (all but
  certainly) still running; Player-prev.log is checked as a fallback for
  the app-shutdown flush case where GSPro restarted in between.
- The log can grow to tens of MB in a long session, so only the tail is
  read; the LM Type line repeats per shot, so the last occurrence is
  always within the tail of any session that had shots.
- Best-effort everywhere: any missing file, decode error, or malformed
  line returns {} — a live round simply archives without LM info, same
  as before this existed.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_LM_LINE = re.compile(r"LM Type (\{.*?\})")

# How much of the log tail to scan. The LM Type line recurs on every shot,
# so this only needs to cover the trailing chunk of a session — 512 KiB is
# hundreds of shots' worth of log.
_TAIL_BYTES = 512 * 1024

LOG_NAMES = ("Player.log", "Player-prev.log")


def _read_tail(path: Path) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > _TAIL_BYTES:
                f.seek(size - _TAIL_BYTES)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def detect_lm(log_dir: Path) -> dict:
    """Return {"connect_type": str, "lm_type_code": str} from the newest
    ``LM Type`` line in GSPro's Player.log (falling back to
    Player-prev.log), or {} when none is found."""
    log_dir = Path(log_dir)
    for name in LOG_NAMES:
        tail = _read_tail(log_dir / name)
        if not tail:
            continue
        matches = _LM_LINE.findall(tail)
        for blob in reversed(matches):  # newest occurrence wins
            try:
                d = json.loads(blob)
            except ValueError:
                continue
            ct = str(d.get("connectType") or "").strip()
            if not ct:
                continue
            return {
                "connect_type": ct,
                "lm_type_code": str(d.get("LMType") or "").strip(),
            }
    return {}
