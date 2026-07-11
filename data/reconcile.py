"""
Reconciles a CSV export against already-archived live-tracked rounds.

Live-tracked shots (see live/shot_data.py) are approximations in a few
ways GSPro's currentRound.dat just doesn't cover: no club speed or smash
factor at all, and offline/backspin are derived from carry + angles
rather than measured directly. A real CSV export from the same round has
the authoritative numbers. If that CSV shows up later, this module
detects that it covers a round already sitting in parquet_data/ as a
live-tracked session and overwrites those shots with the CSV's data,
instead of archiving the CSV as a second, duplicate session.

If no matching CSV ever comes in, nothing changes here — the live-tracked
approximation is what stays in the dataset, which is the whole point of
live tracking existing at all.

There's no shared ID between the two sources (GSPro's ShotID never
appears in a CSV export), so matching runs three checks, each narrowing
the field before the next:

1. Round type: GSPro's "Export CSV" button only ever exports the Practice
   Range shot list, so a CSV can only ever correspond to a live round
   whose filename says "-practice" — an "-on_course" round is skipped
   without even opening its Parquet file.
2. Same calendar day: cheap, filename-only check (both live rounds and
   CSV exports embed a date in their filename) that rules out an
   unrelated round from a different day.
3. Shot-level alignment: every live-tracked shot must line up, in order,
   with a ball-speed/carry-matching shot in the CSV (see _align_live_to_csv).
   This does NOT require equal shot counts — the CSV is treated as the
   complete, authoritative record and the live round as a possibly
   incomplete subsequence of it (a missed poll means the live tracker
   captured fewer shots than actually happened, never extra ones), so a
   live round that missed a shot mid-round can still match a CSV that has
   it. What it can't tolerate is the reverse: a live-tracked shot with no
   matching shot anywhere ahead of it in the CSV means this isn't the
   same round.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from data.columns import BALL_SPEED_ALIASES, CARRY_ALIASES, find_col
from data.dates import extract_date_from_filename

log = logging.getLogger(__name__)

MATCH_TOLERANCE_BALLSPEED = 1.0  # mph
MATCH_TOLERANCE_CARRY = 1.0  # yards

# Columns a CSV export has no equivalent for at all, so there's nothing to
# overwrite them with — these always stay from the live-tracked row (or,
# for a CSV shot with no matching live-tracked shot at all — see the
# missed-shot handling above — are simply left blank, since there's no
# live-tracked context to pull from).
PROTECTED_LIVE_COLUMNS = {
    "club_index", "shot_id", "hole", "holepar", "distancetopin",
    "session_id", "session_date", "round_type",
}
# Of those, these three are session-level rather than per-shot, so they
# apply uniformly to every merged row regardless of per-shot alignment.
SESSION_LEVEL_COLUMNS = ("session_id", "session_date", "round_type")


def _shots_match(a_speed, a_carry, b_speed, b_carry) -> bool:
    return (
        abs(a_speed - b_speed) <= MATCH_TOLERANCE_BALLSPEED
        and abs(a_carry - b_carry) <= MATCH_TOLERANCE_CARRY
    )


def _align_live_to_csv(live_speed, live_carry, csv_speed, csv_carry) -> dict[int, int] | None:
    """Try to align every live-tracked shot, in order, to a matching CSV
    shot (pointer only moves forward through the CSV, so shots already
    matched can't be reused and order is preserved). The CSV is allowed to
    have extra, unmatched shots in between (shots the live tracker missed)
    — but every live shot must find *some* forward match, or this isn't
    considered the same round.

    Returns {live_index: csv_index} covering every live shot, or None.
    """
    alignment: dict[int, int] = {}
    j = 0
    for i in range(len(live_speed)):
        found = None
        while j < len(csv_speed):
            if _shots_match(live_speed[i], live_carry[i], csv_speed[j], csv_carry[j]):
                found = j
                j += 1
                break
            j += 1
        if found is None:
            return None
        alignment[i] = found
    return alignment


def _live_round_candidates(data_dir: Path, csv_date: pd.Timestamp | None) -> list[Path]:
    candidates = []
    for path in data_dir.glob("live-*-practice.parquet"):
        # CSV exports only ever come from GSPro's Practice Range shot
        # list, so an "-on_course" round (already excluded by the glob
        # pattern above) could never be what a CSV covers.
        if csv_date is not None:
            live_date = extract_date_from_filename(path.stem)
            if live_date is not None and live_date.date() != csv_date.date():
                continue
        candidates.append(path)
    return candidates


def find_matching_live_round(
    csv_df: pd.DataFrame, data_dir: Path, csv_date: pd.Timestamp | None = None,
) -> Path | None:
    """Return the path of the already-archived live round this CSV covers,
    or None if nothing matches closely enough to be confident.
    """
    if csv_df.empty:
        return None

    bs_col = find_col(csv_df, BALL_SPEED_ALIASES)
    carry_col = find_col(csv_df, CARRY_ALIASES)
    if not bs_col or not carry_col:
        return None

    csv_speed = csv_df[bs_col].tolist()
    csv_carry = csv_df[carry_col].tolist()

    best_path, best_score = None, None
    for path in _live_round_candidates(data_dir, csv_date):
        try:
            live_df = pd.read_parquet(path)
        except Exception:
            log.exception("Reconcile: could not read candidate live round %s", path)
            continue

        if live_df.empty or "ballspeed" not in live_df.columns or "carry" not in live_df.columns:
            continue

        live_speed = live_df["ballspeed"].tolist()
        live_carry = live_df["carry"].tolist()

        alignment = _align_live_to_csv(live_speed, live_carry, csv_speed, csv_carry)
        if alignment is None:
            continue

        diffs = [
            abs(live_speed[i] - csv_speed[j]) + abs(live_carry[i] - csv_carry[j])
            for i, j in alignment.items()
        ]
        avg_diff = sum(diffs) / len(diffs)
        leftover = len(csv_speed) - len(live_speed)  # CSV shots the live round never saw
        score = (avg_diff, leftover)
        if best_score is None or score < best_score:
            best_score, best_path = score, path

    return best_path


def merge_csv_into_live_round(csv_df: pd.DataFrame, live_round_path: Path) -> int:
    """Overwrite the matched live round with the CSV's data.

    The merged round has one row per CSV shot — the CSV is treated as the
    complete record, so any shot the live tracker missed still ends up in
    the merged data, just without live-only context (hole, holepar, ...)
    since there's no live-tracked shot to pull that from. Every shot the
    live tracker *did* catch keeps its context, carried over to whichever
    CSV row it aligned to. Returns the number of shots overwritten.
    """
    live_df = pd.read_parquet(live_round_path).reset_index(drop=True)
    csv_df = csv_df.reset_index(drop=True)

    bs_col = find_col(csv_df, BALL_SPEED_ALIASES)
    carry_col = find_col(csv_df, CARRY_ALIASES)
    live_speed = live_df["ballspeed"].tolist() if "ballspeed" in live_df.columns else []
    live_carry = live_df["carry"].tolist() if "carry" in live_df.columns else []
    csv_speed = csv_df[bs_col].tolist()
    csv_carry = csv_df[carry_col].tolist()

    alignment = _align_live_to_csv(live_speed, live_carry, csv_speed, csv_carry) or {}

    live_only_cols = [c for c in live_df.columns if c in PROTECTED_LIVE_COLUMNS]
    merged = csv_df.copy()
    for col in live_only_cols:
        merged[col] = None

    # Session-level metadata (which round this is, when, practice/on_course)
    # applies to every row uniformly, whether or not that particular shot
    # was one the live tracker actually caught.
    for col in SESSION_LEVEL_COLUMNS:
        if col in live_df.columns and not live_df.empty:
            merged[col] = live_df[col].iloc[0]

    per_shot_cols = [c for c in live_only_cols if c not in SESSION_LEVEL_COLUMNS]
    for live_idx, csv_idx in alignment.items():
        for col in per_shot_cols:
            merged.at[csv_idx, col] = live_df.at[live_idx, col]

    merged.to_parquet(live_round_path, engine="pyarrow", index=False)
    return len(csv_df)
