"""
Background polling of GSPro's currentRound.dat for near-real-time shot
tracking — this app's live-tracking mechanism (see config.GSPRO_ROUND_FILE
for why this file, not GSPro's Open Connect socket API, is used).

LiveRoundWatcher never writes to currentRound.dat, only reads it: every
poll_interval seconds it re-reads the file and diffs against the last
poll by ShotID (a real GUID GSPro assigns per shot), so:

- a genuinely new shot fires on_new_shot() immediately, usable by the
  live dispersion panel without waiting for the round to finish;
- a change in the very first ShotID in the file — the reliable signal
  that GSPro reset the log for a new round/range session — finalizes and
  archives whatever was buffered for the previous session via
  live.shot_data.archive_round(), then starts a fresh buffer.

RoundID alone isn't a reliable round-boundary signal: GSPro reuses -1
across every separate practice-range session, so two back-to-back range
sessions would never look different by RoundID even though they're
clearly different sessions. The first-ShotID check catches that case
because ShotIDs are unique GUIDs — a fresh session never reuses one.

Stale-file dedup across app restarts: currentRound.dat is whatever GSPro
last wrote, even if that was yesterday and GSPro isn't running right now.
Every time this app starts, the watcher's in-memory state is blank, so
without extra care it would treat that same leftover file as "a round in
progress," buffer it, and finalize_now() would re-archive it — as a brand
new duplicate session — on every single app close, for as long as GSPro
stays idle. To prevent that, the mtime of the file at the moment of the
*last successful archive* is persisted to a small state file in
raw_archive_dir (survives app restarts); if the file's mtime on the next
startup matches that exactly, nothing has changed since it was already
archived, so it's baselined for new-shot/new-round tracking as usual but
not re-archived. Any real change — GSPro appends a shot, or starts a new
round — updates the mtime and clears this, so it archives normally.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from live.lm_detect import detect_lm
from live.shot_data import archive_round, flatten_shot

log = logging.getLogger(__name__)


class LiveRoundWatcher:
    def __init__(
        self,
        round_file: Path,
        data_dir: Path,
        raw_archive_dir: Path,
        on_new_shot: Callable[[dict], None] | None = None,
        on_round_archived: Callable[[dict], None] | None = None,
        schedule_on_main_thread: Callable[[Callable[[], None]], None] | None = None,
        poll_interval: float = 2.0,
        club_lookup=None,
        lm_log_dir: Path | None = None,
    ):
        self.round_file = round_file
        self.data_dir = data_dir
        self.raw_archive_dir = raw_archive_dir
        self.on_new_shot = on_new_shot
        self.on_round_archived = on_round_archived
        self.schedule_on_main_thread = schedule_on_main_thread
        self.poll_interval = poll_interval
        # Optional live.gspro_db.ClubDataLookup — enriches shots with the club
        # speed / smash / AoA currentRound.dat lacks (see live/gspro_db.py).
        self.club_lookup = club_lookup
        # Where GSPro's Unity Player.log lives (normally the same folder as
        # round_file). At finalize time the newest "LM Type" line in it names
        # the connected launch monitor — stamped onto the archived session so
        # contribute.verification_block can cross-check the user's claimed
        # monitor. None disables detection.
        self.lm_log_dir = lm_log_dir

        self._first_shot_id = None
        self._seen_shot_ids: set = set()
        self._buffer: list[dict] = []
        self._last_mtime: float | None = None

        # See module docstring's "Stale-file dedup" note.
        self._state_file = self.raw_archive_dir / ".watcher_state.json"
        self._last_archived_mtime = self._load_last_archived_mtime()
        self._already_archived_current = False

        self._running = False
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        log.info("Live round watcher started — watching %s", self.round_file)
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._running:
            log.info("Live round watcher stopped")
        self._running = False

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self.check_now()
            except Exception:
                log.exception("Live round watcher poll failed")
            time.sleep(self.poll_interval)

    def check_now(self) -> None:
        """One poll cycle. Safe to call directly (e.g. from tests)
        without starting the background thread.
        """
        if not self.round_file.exists():
            return
        try:
            mtime = self.round_file.stat().st_mtime
        except OSError:
            return
        if self._last_mtime is not None and mtime == self._last_mtime:
            return
        self._last_mtime = mtime

        try:
            # utf-8-sig, not the locale default (cp1252 on Windows): GSPro is a
            # Unity app and writes UTF-8, optionally with a BOM. Decoding UTF-8
            # course names through cp1252 corrupts them (or fails the poll
            # forever on bytes cp1252 can't map).
            raw = json.loads(self.round_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            # GSPro may be mid-write; just try again next poll.
            return
        if not isinstance(raw, list) or not raw:
            return

        first_id = raw[0].get("ShotID")

        if self._first_shot_id is None:
            # First observation since this watcher started: baseline
            # silently. These shots still count toward the eventual
            # archive (a round already in progress when the app opened
            # shouldn't lose its earlier shots), but don't fire
            # on_new_shot — they aren't new, just already there.
            self._first_shot_id = first_id
            self._buffer = list(raw)
            self._seen_shot_ids = {s.get("ShotID") for s in raw}
            # Stale-file dedup (see module docstring): if this exact file
            # state was already archived in a previous app run, don't
            # re-archive it just because the app restarted and GSPro
            # hasn't touched the file since.
            self._already_archived_current = (
                self._last_archived_mtime is not None and mtime == self._last_archived_mtime
            )
            return

        if first_id != self._first_shot_id:
            # GSPro reset the log for a new round/range session.
            self._finalize_buffer()
            self._first_shot_id = first_id
            self._buffer = []
            self._seen_shot_ids = set()
            self._already_archived_current = False
            for shot in raw:
                self._add_new_shot(shot)
            return

        for shot in raw:
            shot_id = shot.get("ShotID")
            if shot_id not in self._seen_shot_ids:
                self._add_new_shot(shot)

    def _add_new_shot(self, raw_shot: dict) -> None:
        self._seen_shot_ids.add(raw_shot.get("ShotID"))
        self._buffer.append(raw_shot)
        # Club-mapping diagnostic: log every non-trajectory field so you can
        # hit a known club, read logs/simanalytics.log, and see which field
        # (ClubIndex or otherwise) actually identifies it — then fill in
        # config.CLUB_INDEX_MAP accordingly.
        log.info(
            "Live shot ClubIndex=%s | raw fields=%s",
            raw_shot.get("ClubIndex"),
            {k: v for k, v in raw_shot.items() if k != "GhostData"},
        )
        if self.on_new_shot:
            flat = flatten_shot(raw_shot, self.club_lookup)
            if self.schedule_on_main_thread:
                self.schedule_on_main_thread(lambda f=flat: self.on_new_shot(f))
            else:
                self.on_new_shot(flat)

    def _load_last_archived_mtime(self) -> float | None:
        try:
            return json.loads(self._state_file.read_text()).get("last_archived_mtime")
        except (OSError, ValueError):
            return None

    def _persist_last_archived_mtime(self) -> None:
        try:
            self._state_file.write_text(json.dumps({"last_archived_mtime": self._last_mtime}))
        except OSError:
            log.exception("Failed to persist live round watcher archive state")

    def _finalize_buffer(self) -> None:
        if not self._buffer or self._already_archived_current:
            return
        lm_info = detect_lm(self.lm_log_dir) if self.lm_log_dir else {}
        info = archive_round(self._buffer, self.data_dir, self.raw_archive_dir,
                             club_lookup=self.club_lookup, lm_info=lm_info)
        self._already_archived_current = True
        self._last_archived_mtime = self._last_mtime
        self._persist_last_archived_mtime()
        log.info(
            "Live round watcher: archived %d shot(s) as %s",
            info["shot_count"], info["session_id"],
        )
        if self.on_round_archived:
            if self.schedule_on_main_thread:
                self.schedule_on_main_thread(lambda i=info: self.on_round_archived(i))
            else:
                self.on_round_archived(info)

    def finalize_now(self) -> None:
        """Best-effort flush of whatever's currently buffered — call this
        on app shutdown so an in-progress round isn't lost if GSPro is
        still running when this app closes.
        """
        self._finalize_buffer()
        self._buffer = []
