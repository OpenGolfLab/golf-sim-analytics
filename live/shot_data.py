"""
Turns GSPro's raw currentRound.dat shot records into this app's per-shot
schema, and archives a finished round to disk.

Two things get written per finalized round:

- A flattened Parquet file under DATA_DIR, using the exact same per-shot
  column names every CSV-ingested session already uses (club / carry /
  totaldistance / offline / ballspeed / backspin / vla / session_date /
  session_id / round_type). That's deliberate: it means a live-tracked
  round shows up in every existing dashboard exactly like a manually
  exported CSV would, with zero special-casing needed to read it back —
  data/store.py's load_master_dataframe() just globs *.parquet like always.
- A raw JSON snapshot under LIVE_ROUNDS_RAW_DIR with every field GSPro
  wrote for that round (full ball-flight trajectories included), in case
  something beyond today's flattened schema turns out to be useful later.
  This is the "our own file with a date, all the data, and a practice/
  on-course tag" archive.

Two data gaps versus a real CSV export are baked into the source data
itself, not something this ingestion code can work around:

- No club speed or smash factor anywhere in currentRound.dat, so those
  columns are always NaN for live-tracked shots — the Swing Efficiency
  dashboard simply won't have live-tracked points.
- ClubIndex is a raw internal number, not a name (see config.py's note on
  CLUB_INDEX_MAP for why, and how the mapping self-heals later).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import normalize_club_name, resolve_club_index

log = logging.getLogger(__name__)

# Matches the "<verb>-MM-DD-YY-HH-MM-SS" shape data.io.extract_date_from_filename()
# already looks for in any session_id (see gspro-export%m-%d-%y-%H-%M-%S.csv),
# so a live-archived round's date self-heals through that exact same path.
SESSION_ID_FORMAT = "live-%m-%d-%y-%H-%M-%S"


def flatten_shot(raw_shot: dict, club_lookup=None) -> dict:
    """Map one raw currentRound.dat shot record to this app's per-shot
    column names (see data/columns.py's alias lists for what each chart
    actually looks for).

    ``club_lookup`` (a live.gspro_db.ClubDataLookup) optionally fills in the
    club data currentRound.dat lacks — clubspeed / smashfactor / aoa — by
    matching this shot to its GSPro.db DrivingRangeShot row.
    """
    gd = raw_shot.get("GhostData") or {}

    club_index = raw_shot.get("ClubIndex")
    club = normalize_club_name(resolve_club_index(club_index))

    # currentRound.dat is GSPro's fixed internal store — always yards, no unit
    # marker (GSPro localizes to metric only when it formats a CSV export, not
    # here; see data/units.py). So live-tracked distances need no unit detection,
    # unlike CSV ingest (data.io._detect_csv_distance_unit).
    carry = gd.get("cy")  # carry yardage
    az = gd.get("az")  # side/azimuth angle in degrees (GSPro's HLA equivalent)
    # Approximation: real launch-monitor CSVs report a measured "offline"
    # that includes roll; GSPro's internal file doesn't expose that
    # directly, so this derives it from carry + side angle instead — close
    # for airborne carry dispersion, just doesn't account for roll-out
    # curving further offline after landing.
    offline = carry * math.sin(math.radians(az)) if carry is not None and az is not None else None

    total_spin = gd.get("ts")  # total spin magnitude, rpm
    spin_axis = gd.get("sa")  # spin axis, degrees
    backspin = (
        total_spin * math.cos(math.radians(spin_axis))
        if total_spin is not None and spin_axis is not None
        else None
    )

    flat = {
        "club": club,
        "club_index": club_index,
        "ballspeed": raw_shot.get("BallSpeed", gd.get("sp")),
        "carry": carry,
        "totaldistance": raw_shot.get("TotalDistance"),
        "offline": offline,
        "vla": gd.get("el"),
        "backspin": backspin,
        "hole": raw_shot.get("Hole"),
        "holepar": raw_shot.get("HolePar"),
        # GSPro's own stroke number within the hole — the authoritative score
        # source. Mulligans re-hit the SAME HoleShot (the superseded record
        # stays in the file), so records-per-hole overcounts every mulligan;
        # max(holeshot) matches GSPro's scorecard. Penalty strokes get their
        # own record (holeshot advances) with shot_result == 2 and ball data
        # cloned from the hazard ball — countable for score, but not a swing
        # (see data.on_course.exclude_putts).
        "holeshot": raw_shot.get("HoleShot"),
        "shot_result": raw_shot.get("ShotResult"),
        # Written by GSPro AFTER the shot resolves, so on course this is the
        # shot's proximity to the flag, not the distance it was played from.
        "distancetopin": raw_shot.get("DistanceToPin"),
        # Same raw field, opposite meaning, which is why it gets its own
        # column. On the practice range the ball is replaced on the tee after
        # every shot, so the play position never moves and GSPro keeps
        # reporting the unchanged tee-to-target distance — i.e. how far away
        # the target the player selected is. That's the only signal GSPro
        # exposes for the range target, and the Shot Quality score needs it to
        # score proximity on the range (see data.analytics.scoring).
        "target_distance": (raw_shot.get("DistanceToPin")
                            if raw_shot.get("RoundID") in (None, -1) else None),
        "shot_id": raw_shot.get("ShotID"),
        # GSPro's internal course slug for on-course rounds (e.g.
        # "paynes_valley_gsp"); None for practice-range shots, which don't
        # carry it. See data/on_course.humanize_course() for the display name.
        "course": raw_shot.get("CourseKey"),
    }
    if club_lookup is not None:
        # Fill in clubspeed / smashfactor / aoa (and the real club name) from
        # GSPro.db when this shot matches a DrivingRangeShot row.
        extra = club_lookup.lookup(flat["ballspeed"], flat["carry"])
        if "club" in extra:
            # GSPro.db knows the actual club; currentRound.dat's ClubIndex is
            # always 0 here (-> everything looked like a driver). Drop the index
            # too, or load_master_dataframe's club_index re-resolution would
            # clobber this good name back to the ClubIndex-0 club on reload.
            flat["club"] = extra.pop("club")
            flat["club_index"] = None
        flat.update(extra)
    return flat


def heal_missing_holeshot(data_dir: Path, raw_archive_dir: Path) -> int:
    """One-time startup repair: backfill holeshot / shot_result onto on-course
    Parquet archives written before those columns existed.

    Every live-archived round keeps a raw JSON snapshot alongside its Parquet
    (see archive_round), so the missing columns can be joined back in by
    ShotID without touching anything else in the file. Only on-course
    archives need it (practice ranges have no scorecard), and files that
    already carry the column are skipped, so reruns are free. Returns how
    many files were repaired.
    """
    healed = 0
    for pq_path in data_dir.glob("live-*-on_course.parquet"):
        raw_path = raw_archive_dir / f"{pq_path.stem}.json"
        if not raw_path.exists():
            continue
        try:
            df = pd.read_parquet(pq_path)
        except Exception:
            log.exception("heal_missing_holeshot: unreadable %s — skipping", pq_path)
            continue
        if "holeshot" in df.columns or "shot_id" not in df.columns:
            continue
        try:
            raw_shots = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("heal_missing_holeshot: unreadable %s — skipping", raw_path)
            continue
        by_id = {s.get("ShotID"): s for s in raw_shots}
        df["holeshot"] = df["shot_id"].map(lambda i: by_id.get(i, {}).get("HoleShot"))
        df["shot_result"] = df["shot_id"].map(lambda i: by_id.get(i, {}).get("ShotResult"))
        try:
            df.to_parquet(pq_path, engine="pyarrow", index=False)
        except Exception:
            log.exception("heal_missing_holeshot: could not rewrite %s", pq_path)
            continue
        healed += 1
    if healed:
        log.info("heal_missing_holeshot: backfilled %d on-course archive(s)", healed)
    return healed


def round_type_for(raw_shots: list[dict]) -> str:
    """GSPro sets RoundID to -1 for Practice Range / driving-range
    sessions and a real positive id for an actual on-course round — no
    guessing needed, the file already tells us directly.
    """
    if not raw_shots:
        return "practice"
    round_id = raw_shots[0].get("RoundID")
    return "practice" if round_id in (None, -1) else "on_course"


def archive_round(
    raw_shots: list[dict],
    data_dir: Path,
    raw_archive_dir: Path,
    finalized_at: datetime | None = None,
    club_lookup=None,
    lm_info: dict | None = None,
    club_data_by_shot: dict[str, dict] | None = None,
) -> dict:
    """Archive one finished round: a flattened Parquet file (joins every
    other archived session in every dashboard) plus a raw JSON snapshot
    with every field GSPro wrote. Returns a small summary dict for the
    caller's UI toast/refresh.

    ``lm_info`` (from live.lm_detect.detect_lm) stamps the launch monitor
    GSPro actually reported — session-level columns used only to
    cross-check the contribute dialog's claimed monitor (see
    contribute.verification_block). None/{} just leaves the columns out,
    exactly like every pre-existing archive.

    ``club_data_by_shot`` maps ShotID -> the club fields (clubspeed /
    smashfactor / aoa / club) that were read from GSPro.db *at the time each
    shot happened*, and it takes precedence over anything the archive-time
    lookup below finds. This exists because the archive-time lookup is
    fundamentally unreliable and the live one isn't:

    GSPro clears DrivingRangeShot when a range session ends — and the end of a
    range session is exactly what triggers this function. So the archive races
    GSPro's teardown, and loses often. Measured across 9 real archived practice
    sessions, only 3 came out with club speed; the other 6 have no clubspeed
    column at all, because every shot's lookup missed. Two sessions on the same
    range course, six days apart, landed on opposite sides of that race.

    The club data was never actually unavailable — it was read successfully
    during play and then discarded, because this function re-derives every row
    from raw_shots instead of keeping what the live path already resolved.
    """
    finalized_at = finalized_at or datetime.now()
    round_type = round_type_for(raw_shots)
    session_id = f"{finalized_at.strftime(SESSION_ID_FORMAT)}-{round_type}"

    # Archive-time club lookups come as a burst — one per shot, all within
    # milliseconds. Collapse that to a single GSPro.db read via snapshot()
    # (see live/gspro_db.py: GSPro is busy writing its own round data right
    # now, so don't open its database once per shot). On-course rounds skip
    # the database entirely: DrivingRangeShot only ever holds range shots,
    # so no on-course shot can match — identical result, zero contention.
    if club_lookup is not None:
        if round_type == "on_course":
            club_lookup = None
        elif hasattr(club_lookup, "snapshot"):
            club_lookup = club_lookup.snapshot(expected_shots=len(raw_shots))

    rows = [flatten_shot(shot, club_lookup) for shot in raw_shots]

    # Live-captured club data wins over the archive-time lookup (see the
    # docstring). Applied per field rather than wholesale so a shot that got
    # some of its club data from each source keeps both.
    if club_data_by_shot:
        for row, raw in zip(rows, raw_shots):
            captured = club_data_by_shot.get(raw.get("ShotID"))
            if not captured:
                continue
            for key, value in captured.items():
                if value in (None, 0, 0.0):
                    continue
                if key == "club":
                    # Overrides rather than fills. A captured club name can only
                    # have come from GSPro.db, which is authoritative, whereas the
                    # row always already has a name resolved from ClubIndex — so
                    # a fill-only rule would never apply it. The index has to be
                    # dropped alongside it or load_master_dataframe re-resolves
                    # the club straight back to the ClubIndex one.
                    row["club"] = value
                    row["club_index"] = None
                elif row.get(key) in (None, 0, 0.0):
                    row[key] = value

    df = pd.DataFrame(rows)
    df["session_date"] = finalized_at
    df["session_id"] = session_id
    df["round_type"] = round_type
    if lm_info and lm_info.get("connect_type"):
        df["lm_connect_type"] = lm_info["connect_type"]
        df["lm_type_code"] = lm_info.get("lm_type_code") or None

    parquet_path = data_dir / f"{session_id}.parquet"
    df.to_parquet(parquet_path, engine="pyarrow", index=False)

    raw_path = raw_archive_dir / f"{session_id}.json"
    try:
        raw_path.write_text(json.dumps(raw_shots))
    except OSError:
        log.exception("Failed to write raw live-round archive %s", raw_path)

    # How many shots ended up with club speed. Reported so the app can tell the
    # user when a practice round archived without it, instead of the round just
    # quietly landing with an empty Swing Efficiency panel — which is how six
    # real sessions went by unnoticed before anyone looked.
    club_data_shots = sum(
        1 for r in rows if r.get("clubspeed") not in (None, 0, 0.0))

    return {
        "session_id": session_id,
        "round_type": round_type,
        "shot_count": len(raw_shots),
        "club_data_shots": club_data_shots,
        "parquet_path": parquet_path,
        "raw_path": raw_path,
    }
