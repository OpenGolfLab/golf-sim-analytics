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

# The fields only GSPro.db can supply (see live/gspro_db.py). A flattened shot
# carrying none of them either lost a write race with GSPro or genuinely has no
# club data available; _retry_club_data tells the two apart.
_CLUB_DATA_FIELDS = ("clubspeed", "smashfactor", "aoa")


def _has_club_data(flat: dict) -> bool:
    return any(flat.get(k) not in (None, 0, 0.0) for k in _CLUB_DATA_FIELDS)


class LiveRoundWatcher:
    def __init__(
        self,
        round_file: Path,
        data_dir: Path,
        raw_archive_dir: Path,
        on_new_shot: Callable[[dict], None] | None = None,
        on_round_archived: Callable[[dict], None] | None = None,
        on_shot_updated: Callable[[dict], None] | None = None,
        schedule_on_main_thread: Callable[[Callable[[], None]], None] | None = None,
        poll_interval: float = 2.0,
        club_lookup=None,
        lm_log_dir: Path | None = None,
        club_data_retries: int = 0,
        club_data_retry_interval: float = 0.4,
    ):
        self.round_file = round_file
        self.data_dir = data_dir
        self.raw_archive_dir = raw_archive_dir
        self.on_new_shot = on_new_shot
        self.on_round_archived = on_round_archived
        # Fired (on the main thread) when a shot already handed to on_new_shot
        # has had its club data backfilled in place — see _retry_club_data.
        self.on_shot_updated = on_shot_updated
        self.schedule_on_main_thread = schedule_on_main_thread
        self.poll_interval = poll_interval
        # Retry budget for the GSPro.db write race. Defaults to 0 (no retries),
        # so existing callers and tests keep the old single-lookup behavior; the
        # app passes config.LIVE_CLUB_DATA_RETRIES.
        self.club_data_retries = club_data_retries
        self.club_data_retry_interval = club_data_retry_interval
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
        # Shots reported to the UI before GSPro.db had their club data — see
        # _retry_club_data. Entries are {"flat", "ball_speed", "carry",
        # "attempts", "next_at"}; touched only from the poll thread.
        self._pending_club_data: list[dict] = []
        # ShotID -> club fields resolved from GSPro.db while the round was in
        # progress. Handed to archive_round so a finished round keeps the club
        # data that was read at shot time, instead of depending on GSPro.db
        # still holding those rows once the round is over — it usually doesn't.
        # See archive_round's docstring.
        self._club_data_by_shot: dict[str, dict] = {}

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
            try:
                self._retry_club_data()
            except Exception:
                log.exception("Live round watcher club-data retry failed")
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
            # Capture their club data anyway, even though they're not announced
            # as new. This is the "app opened partway through a range session"
            # case: these shots are still going to be archived, and right now is
            # the best chance GSPro.db will still hold their rows — by archive
            # time it very likely won't (see archive_round). Without this they
            # keep the old behaviour of silently landing with no club speed.
            if self.club_lookup is not None:
                for shot in raw:
                    try:
                        self._remember_club_data(
                            shot.get("ShotID"), flatten_shot(shot, self.club_lookup))
                    except Exception:
                        log.debug("Could not baseline club data for a shot",
                                  exc_info=True)
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
            # Cleared only AFTER _finalize_buffer above has used it, so the round
            # being archived keeps its club data and the new one starts clean.
            self._club_data_by_shot = {}
            self._pending_club_data = []
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
        # Club-mapping diagnostic: every non-trajectory field, so you can hit a
        # known club, read logs/simanalytics.log, and see which field (ClubIndex
        # or otherwise) actually identifies it — then fill in
        # config.CLUB_INDEX_MAP accordingly. At debug level: this fires on every
        # shot and each line is ~1-2KB, so at info it dominated the log file and
        # put a synchronous disk write on the poll path.
        log.debug(
            "Live shot ClubIndex=%s | raw fields=%s",
            raw_shot.get("ClubIndex"),
            {k: v for k, v in raw_shot.items() if k != "GhostData"},
        )
        # Flatten unconditionally, not just when there's a UI listening: this is
        # where club data gets read close enough to the shot for GSPro.db to
        # still have it, and that result now has to survive to the archive.
        flat = flatten_shot(raw_shot, self.club_lookup)
        self._remember_club_data(raw_shot.get("ShotID"), flat)
        if not _has_club_data(flat):
            self._queue_club_data_retry(flat, raw_shot.get("ShotID"))
        if self.on_new_shot:
            if self.schedule_on_main_thread:
                self.schedule_on_main_thread(lambda f=flat: self.on_new_shot(f))
            else:
                self.on_new_shot(flat)

    def _remember_club_data(self, shot_id, flat: dict) -> None:
        """Stash whatever club fields this shot resolved, for archive time."""
        if shot_id is None:
            return
        captured = {k: flat.get(k) for k in _CLUB_DATA_FIELDS
                    if flat.get(k) not in (None, 0, 0.0)}
        # The club NAME is club data too, and on monitors where ClubIndex is
        # always 0 it's the only thing that identifies the club at all.
        if flat.get("club_index") is None and flat.get("club"):
            captured["club"] = flat["club"]
        if captured:
            self._club_data_by_shot.setdefault(shot_id, {}).update(captured)

    # -----------------------------------------------------------------------
    # Club-data backfill.
    #
    # currentRound.dat and GSPro.db are written independently, so polling fast
    # enough to feel instant (config.LIVE_POLL_SECONDS) means we regularly see a
    # shot in the .dat file a beat before its DrivingRangeShot row exists — and
    # that row is the only source of club speed / smash / AoA, and on monitors
    # where ClubIndex is always 0, of the real club name too.
    #
    # Rather than delay every shot to the slowest case, the shot goes to the UI
    # immediately (that's the whole point of the fast poll) and its club data is
    # filled in a few tenths of a second later. The flat dict handed to
    # on_new_shot is the SAME object the UI keeps in its live buffer, so patching
    # it in place updates what's already on screen; on_shot_updated then asks for
    # a redraw.
    #
    # The archive path is unaffected either way: archive_round re-flattens the
    # raw buffer against a fresh DB snapshot when the round finalizes, long after
    # any write race has settled.
    # -----------------------------------------------------------------------
    def _queue_club_data_retry(self, flat: dict, shot_id=None) -> None:
        if self.club_lookup is None or self.club_data_retries <= 0:
            return
        self._pending_club_data.append({
            "flat": flat,
            "shot_id": shot_id,
            "ball_speed": flat.get("ballspeed"),
            "carry": flat.get("carry"),
            "attempts": 0,
            "next_at": time.monotonic() + self.club_data_retry_interval,
        })

    def _retry_club_data(self) -> None:
        """Re-check GSPro.db for any shot that arrived without club data."""
        if not self._pending_club_data:
            return
        now = time.monotonic()
        still_pending = []
        for item in self._pending_club_data:
            if now < item["next_at"]:
                still_pending.append(item)
                continue
            item["attempts"] += 1
            extra = self.club_lookup.lookup(item["ball_speed"], item["carry"])
            if extra:
                flat = item["flat"]
                if "club" in extra:
                    # See flatten_shot: GSPro.db knows the real club, so the
                    # ClubIndex has to be dropped or a later reload re-resolves
                    # it back to the wrong club.
                    flat["club"] = extra.pop("club")
                    flat["club_index"] = None
                flat.update(extra)
                # Keep the archive's copy in step with the backfill, or a round
                # whose club data arrived late would still archive without it.
                self._remember_club_data(item.get("shot_id"), flat)
                log.debug("Backfilled club data for shot %s after %d attempt(s)",
                          flat.get("shot_id"), item["attempts"])
                if self.on_shot_updated:
                    if self.schedule_on_main_thread:
                        self.schedule_on_main_thread(lambda f=flat: self.on_shot_updated(f))
                    else:
                        self.on_shot_updated(flat)
                continue
            if item["attempts"] < self.club_data_retries:
                item["next_at"] = now + self.club_data_retry_interval
                still_pending.append(item)
            else:
                # Genuinely absent, not a race — an on-course shot (never in
                # DrivingRangeShot) or a monitor that doesn't report club data.
                log.debug("No GSPro.db club data for shot %s after %d attempts",
                          item["flat"].get("shot_id"), item["attempts"])
        self._pending_club_data = still_pending

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

    def _finalize_buffer(self) -> dict | None:
        """Archive the current buffer if there's anything new to archive.
        Returns the archive-summary dict (same shape as archive_round's) when
        a round was actually written, or None when there was nothing to do
        (empty buffer, or this exact file state was already archived)."""
        if not self._buffer or self._already_archived_current:
            return None
        lm_info = detect_lm(self.lm_log_dir) if self.lm_log_dir else {}
        info = archive_round(self._buffer, self.data_dir, self.raw_archive_dir,
                             club_lookup=self.club_lookup, lm_info=lm_info,
                             club_data_by_shot=self._club_data_by_shot)
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
        return info

    def finalize_now(self) -> dict | None:
        """Best-effort flush of whatever's currently buffered — call this on
        app shutdown, or from an explicit "End Round" action, so a finished
        round is archived (and shows up in the historical dashboards +
        contribution) without waiting for GSPro to start the next round or the
        app to close.

        Returns the archive-summary dict when a round was written, or None
        when there was nothing new to archive. Safe to call repeatedly: the
        ``_already_archived_current`` guard means a second call (e.g. an
        explicit End Round followed by app shutdown) never double-archives the
        same round, and a genuinely new GSPro round still archives normally
        because the round-boundary path resets that guard.
        """
        info = self._finalize_buffer()
        self._buffer = []
        return info
