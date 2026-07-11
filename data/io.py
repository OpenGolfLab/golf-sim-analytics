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


def parse_and_clean_csv(path: Path) -> pd.DataFrame:
    """Read a raw GSPro export CSV and return a cleaned DataFrame.

    Does NOT assign session_date/session_id and does NOT touch the
    filesystem — callers decide whether this is a one-off live read or a
    file to be archived to Parquet.
    """
    df = pd.read_csv(path, na_values=NA_VALUES)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    for col in df.columns:
        if col not in NON_NUMERIC_COLUMNS:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r"[^\d\.-]", "", regex=True),
                errors="coerce",
            )

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
