"""
CSV ingestion.

raw_csvs/ is polled in the background (ui.app_window._poll_raw_csv_dir)
and anything the Desktop export watcher copies in is ingested through the
same path, so parse_and_clean_csv() is the single source of truth every
caller uses.

If a CSV turns out to cover a round that was already live-tracked (see
live/round_watcher.py), ingest_csv_to_parquet() overwrites that round's
shots with the CSV's data (club speed / smash factor included — data the
live tracker never has) instead of archiving a duplicate session. See
data/reconcile.py for the matching logic.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from config import normalize_club_name
from data.columns import (
    CARRY_ALIASES,
    CLUB_SPEED_ALIASES,
    SMASH_FACTOR_ALIASES,
    find_col,
)
# extract_date_from_filename lives in data/dates.py (not here) because
# data/reconcile.py needs it too, and reconcile.py is imported below —
# keeping it in its own module avoids a circular import between the two.
from data.dates import extract_date_from_filename
from data.reconcile import find_matching_live_round, merge_csv_into_live_round

log = logging.getLogger(__name__)

NA_VALUES = ["#DIV/0!", "#DIV/0", "DIV/0!", "#div/0!", "div/0!"]
NON_NUMERIC_COLUMNS = {"club", "session_id", "session_date", "timestamp"}

# Distance / height columns to normalize to yards/feet when a CSV turns out to
# be a metric GSPro export (see _detect_csv_distance_unit). Kept lowercase to
# match parse_and_clean_csv's normalized headers.
_CSV_DISTANCE_COLS = {"carry", "carrydistance", "total", "totaldistance",
                      "offline", "distancetopin"}
_CSV_HEIGHT_COLS = {"peakheight", "height", "apex", "max_height", "maxheight"}


def _detect_csv_distance_unit(df: pd.DataFrame) -> str:
    """Read the unit GSPro actually wrote this export in — "meters" or "yards".

    GSPro honors its in-game metric/imperial setting when it exports, and the
    only self-describing column is DistanceToPin, which it writes with a
    localized suffix ("345.21 yds" imperial, "315.5 m" metric). Every other
    distance column is a bare number, so this suffix is the one on-disk signal
    of the file's unit. currentRound.dat (live tracking) carries no such marker
    at all — it's GSPro's fixed internal store, always yards — so only CSV
    ingestion needs this. Defaults to "yards" when there's no suffix to read
    (older exports, or a column without the unit), so imperial exports and all
    existing data are unaffected.
    """
    for col in df.columns:
        if "distancetopin" in col.replace("_", ""):
            joined = " ".join(df[col].astype(str).str.lower().head(25))
            if "yd" in joined or "yard" in joined:
                return "yards"
            if re.search(r"(?<!c)\bm\b|meter|metre", joined):
                return "meters"
            break
    return "yards"


def parse_and_clean_csv(path: Path) -> pd.DataFrame:
    """Read a raw GSPro export CSV and return a cleaned DataFrame.

    Does NOT assign session_date/session_id and does NOT touch the
    filesystem — callers decide whether this is a one-off live read or a
    file to be archived to Parquet.
    """
    df = pd.read_csv(path, na_values=NA_VALUES)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Detect the unit GSPro exported in BEFORE the numeric scrub below strips the
    # DistanceToPin suffix that carries it (see _detect_csv_distance_unit). This
    # replaces assuming yards with reading the file's own signal.
    source_unit = _detect_csv_distance_unit(df)

    for col in df.columns:
        if col not in NON_NUMERIC_COLUMNS:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r"[^\d\.-]", "", regex=True),
                errors="coerce",
            )

    if source_unit == "meters":
        # A metric export — normalize distances to the app's canonical yards
        # (and heights to feet) so everything downstream, including the
        # OpenGolfLab contribution, stays in one unit regardless of each user's
        # GSPro setting. The Settings yards/meters toggle then converts purely
        # for display. Speeds/spin are left as-is (mph/rpm).
        from data.units import FOOT_TO_M, YARD_TO_M
        log.info("%s looks like a metric GSPro export — converting distances to yards", path.name)
        for col in df.columns:
            if col in _CSV_DISTANCE_COLS:
                df[col] = df[col] / YARD_TO_M
            elif col in _CSV_HEIGHT_COLS:
                df[col] = df[col] / FOOT_TO_M

    sf_col = find_col(df, SMASH_FACTOR_ALIASES)
    cs_col = find_col(df, CLUB_SPEED_ALIASES)
    carry_col = find_col(df, CARRY_ALIASES)

    drop_subset = [c for c in (sf_col, cs_col, carry_col) if c is not None]
    if drop_subset:
        df = df.dropna(subset=drop_subset)

    if cs_col:
        df = df[(df[cs_col] > 10) & (df[cs_col] < 160)]
    if carry_col:
        df = df[df[carry_col] > 0]

    if "club" in df.columns:
        # Rows with no club recorded are unusable in every dashboard, and
        # stringifying missing values used to produce a literal "Nan" club
        # that polluted legends and axes.
        df = df[df["club"].notna()]
        df["club"] = df["club"].astype(str).str.strip()
        df = df[~df["club"].str.lower().isin(("", "nan", "none"))]
        # Reconcile launch-monitor spelling differences (e.g. "I9" vs "9I")
        # into one canonical name per club — see normalize_club_name().
        df["club"] = df["club"].apply(normalize_club_name)

    return df


def ingest_csv_to_parquet(csv_path: Path, data_dir: Path) -> pd.DataFrame | None:
    """Clean one CSV and archive it — either merged into an already-archived
    live-tracked round it matches (see data/reconcile.py), or tagged with
    its own session id/date and written as a new standalone session.

    Returns the cleaned DataFrame on success, or None on failure (logged).
    Caller is responsible for renaming the source CSV once this returns.
    """
    try:
        df = parse_and_clean_csv(csv_path)

        parsed_date = extract_date_from_filename(csv_path.stem)
        if parsed_date is None:
            parsed_date = pd.to_datetime(csv_path.stat().st_ctime, unit="s")

        matched_round = find_matching_live_round(df, data_dir, csv_date=parsed_date)
        if matched_round is not None:
            overwritten = merge_csv_into_live_round(df, matched_round)
            log.info(
                "%s matches already-archived live round %s — overwrote %d "
                "shot(s) with the CSV's data instead of archiving a "
                "duplicate session",
                csv_path.name, matched_round.name, overwritten,
            )
            return df

        df["session_date"] = parsed_date
        df["session_id"] = csv_path.stem

        output_file = data_dir / f"{csv_path.stem}.parquet"
        df.to_parquet(output_file, engine="pyarrow", index=False)
        return df
    except Exception:
        log.exception("Failed to process %s", csv_path.name)
        return None


def _unique_dest(raw_csv_dir: Path, name: str) -> Path:
    """A collision-free path in raw_csv_dir for a file called ``name``, also
    dodging an existing ``.csv.processed`` twin (same scheme the Desktop export
    watcher uses) so re-importing the same file makes a new session rather than
    silently overwriting one."""
    dest = raw_csv_dir / name
    stem = dest.stem
    suffix = 2
    while dest.exists() or dest.with_suffix(dest.suffix + ".processed").exists():
        dest = raw_csv_dir / f"{stem}-{suffix}.csv"
        suffix += 1
    return dest


def import_csv_files(paths, raw_csv_dir: Path) -> tuple[list[Path], list[Path]]:
    """Copy user-supplied CSVs (drag-and-drop, or the Import CSV file picker)
    into raw_csv_dir so the normal ingest pipeline archives them.

    Each file is header-sniffed with the same check the Desktop export watcher
    uses, so a stray non-launch-monitor CSV is skipped rather than failing
    ingestion. Returns (copied, skipped) as two lists of paths. The caller runs
    ingest_all_csvs() afterwards (or lets the raw_csvs/ poll pick them up)."""
    import shutil
    from data.export_watcher import _is_shot_export  # lazy: avoids import cycle

    raw_csv_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    skipped: list[Path] = []
    for p in paths:
        src = Path(p)
        if src.suffix.lower() != ".csv" or not src.exists() or not _is_shot_export(src):
            skipped.append(src)
            continue
        dest = _unique_dest(raw_csv_dir, src.name)
        try:
            shutil.copy2(src, dest)
            copied.append(dest)
        except OSError:
            log.exception("Could not import CSV %s", src)
            skipped.append(src)
    return copied, skipped


def ingest_all_csvs(raw_csv_dir: Path, data_dir: Path) -> int:
    """Process every *.csv in raw_csv_dir, archiving each to Parquet and
    renaming it to *.csv.processed. Returns the number successfully processed.
    """
    csv_files = list(raw_csv_dir.glob("*.csv"))
    processed_count = 0
    for file in csv_files:
        df = ingest_csv_to_parquet(file, data_dir)
        if df is not None:
            file.rename(file.with_suffix(".csv.processed"))
            processed_count += 1
    return processed_count
