"""
Automatic pickup of GSPro's own "Export CSV" files.

GSPro's Practice Range shot list has an "Export CSV" button that always
saves to the user's Desktop — there's no setting to redirect it, and no
guarantee about what GSPro names the file or whether it reuses the same
name across sessions. Historically this app needed a manual copy into
raw_csvs/ before anything would see the file; raw_csvs/ is now polled
directly too (see ui.app_window._poll_raw_csv_dir), but this watcher
still saves the extra step of copying the export off the Desktop.

ExportWatcher polls the Desktop (or wherever `watch_dir` points) for
*.csv files, and for anything it hasn't handled yet:

1. Copies it into raw_csvs/ under a name this app controls, derived from
   the source file's own modification time (gspro-export<MM-DD-YY-HH-MM-SS>.csv)
   — this sidesteps needing to know GSPro's real naming convention *and*
   guarantees data.io.extract_date_from_filename() can always recover an
   accurate session date, the same as every other archived session.
2. Records (filename, mtime) in a small local state file so a re-export
   under the same name (GSPro overwriting its own file) is still picked
   up as new, and an already-seen file is never re-copied.
3. When auto_ingest=True, immediately runs the normal ingest_all_csvs()
   pipeline so the shots are archived to Parquet with no further clicks.

The Desktop file itself is only ever read, never renamed or deleted —
this stays out of the way of however the user wants to manage their own
files.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from data.columns import BALL_SPEED_ALIASES, CARRY_ALIASES
from data.io import ingest_all_csvs

log = logging.getLogger(__name__)

STATE_FILENAME = "export_watcher_state.json"
DEST_NAME_FORMAT = "gspro-export%m-%d-%y-%H-%M-%S.csv"


def _is_shot_export(csv_path: Path) -> bool:
    """Cheap header sniff: does this CSV look like a launch-monitor shot
    export? The Desktop is the user's own space and can hold any number of
    unrelated CSVs (bank exports, spreadsheets, downloads); copying those
    into raw_csvs/ would make the ingest pipeline fail noisily on every
    poll. Every GSPro export has a club column plus per-shot ball data, so
    require a club column and a carry/ball-speed column — using the same
    header normalization ingestion applies (data.io.parse_and_clean_csv).
    """
    try:
        with open(csv_path, encoding="utf-8-sig", errors="replace") as fh:
            header = fh.readline()
    except OSError:
        return False
    cols = {c.strip().strip('"').lower().replace(" ", "_") for c in header.split(",")}
    ball_cols = (*CARRY_ALIASES, *BALL_SPEED_ALIASES)
    return "club" in cols and any(a in cols for a in ball_cols)


class ExportWatcher:
    def __init__(
        self,
        watch_dir: Path,
        raw_csv_dir: Path,
        data_dir: Path,
        on_new_data: Callable[[int], None] | None = None,
        schedule_on_main_thread: Callable[[Callable[[], None]], None] | None = None,
        is_paused: Callable[[], bool] | None = None,
        poll_interval: float = 5.0,
        auto_ingest: bool = True,
    ):
        self.watch_dir = watch_dir
        self.raw_csv_dir = raw_csv_dir
        self.data_dir = data_dir
        self.on_new_data = on_new_data
        self.schedule_on_main_thread = schedule_on_main_thread
        self.is_paused = is_paused or (lambda: False)
        self.poll_interval = poll_interval
        self.auto_ingest = auto_ingest

        self._state_path = data_dir / STATE_FILENAME
        self._seen: dict[str, float] = self._load_state()

        self._running = False
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        log.info("Export watcher started — watching %s for new GSPro CSV exports", self.watch_dir)
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._running:
            log.info("Export watcher stopped")
        self._running = False

    # ------------------------------------------------------------------
    # State persistence — survives app restarts, needs no raw_csvs/ scan.
    # ------------------------------------------------------------------
    def _load_state(self) -> dict[str, float]:
        try:
            return json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        try:
            self._state_path.write_text(json.dumps(self._seen))
        except OSError:
            log.exception("Export watcher: could not persist state to %s", self._state_path)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    def _poll_loop(self) -> None:
        while self._running:
            try:
                if not self.is_paused():
                    self._check_for_new_exports()
            except Exception:
                log.exception("Export watcher poll failed")
            time.sleep(self.poll_interval)

    def _dest_name_for(self, mtime: float) -> Path:
        stamp = datetime.fromtimestamp(mtime).strftime(DEST_NAME_FORMAT)
        dest = self.raw_csv_dir / stamp
        suffix = 2
        while dest.exists() or (dest.with_suffix(dest.suffix + ".processed")).exists():
            dest = self.raw_csv_dir / f"{stamp[:-4]}-{suffix}.csv"
            suffix += 1
        return dest

    def _check_for_new_exports(self) -> None:
        if not self.watch_dir.exists():
            return

        copied = []
        state_dirty = False
        for csv_path in self.watch_dir.glob("*.csv"):
            try:
                mtime = csv_path.stat().st_mtime
            except OSError:
                continue

            last_seen = self._seen.get(csv_path.name)
            if last_seen is not None and mtime <= last_seen:
                continue  # already handled this exact file state

            if not _is_shot_export(csv_path):
                # Not a launch-monitor export — leave it alone, but record its
                # mtime so it isn't re-sniffed on every poll tick. Editing or
                # replacing the file bumps the mtime and re-checks it.
                self._seen[csv_path.name] = mtime
                state_dirty = True
                log.info(
                    "Export watcher: %s doesn't look like a launch-monitor "
                    "export (no club/carry columns) — ignoring it",
                    csv_path.name,
                )
                continue

            dest = self._dest_name_for(mtime)
            try:
                shutil.copy2(csv_path, dest)
            except OSError:
                log.exception("Export watcher: failed to copy %s", csv_path.name)
                continue

            self._seen[csv_path.name] = mtime
            copied.append(dest)
            log.info("Export watcher: picked up new GSPro export %s -> %s",
                      csv_path.name, dest.name)

        if state_dirty and not copied:
            self._save_state()  # skip marks persist too, or restarts re-sniff
        if not copied:
            return
        self._save_state()

        processed_count = 0
        if self.auto_ingest:
            processed_count = ingest_all_csvs(self.raw_csv_dir, self.data_dir)
            log.info("Export watcher: auto-ingested %d new session(s)", processed_count)

        if self.on_new_data and self.schedule_on_main_thread:
            self.schedule_on_main_thread(lambda: self.on_new_data(processed_count))
