"""
On-course round handling: keeping course play separate from practice data,
and detecting mulligans (re-hit shots).

Two distinct concerns the app cares about (see data/settings.py toggles):

- ``exclude_on_course_from_practice``: on-course rounds are full of shots
  that would pollute the "pure your swing" practice dashboards — chips,
  punch-outs, layups, recovery shots, half-swing pitches. round_type already
  tags every shot "practice" vs "on_course" (see live/shot_data.py), so
  splitting them is just a filter. ``practice_view`` / ``on_course_view``
  are the two halves.

- ``drop_mulligans``: a mulligan is a shot you re-hit from the same spot
  because the first attempt was bad. GSPro's currentRound.dat has no explicit
  "this was a mulligan / shot 2 from here" flag (the record only carries
  Hole / HolePar / DistanceToPin / club / ball data — see the SAMPLE_SHOT in
  tests), so this infers them from geometry: within one hole, if the very
  next shot was hit from essentially the same distance-to-the-pin, the earlier
  shot didn't advance the ball — it was re-hit. The re-hit (later) attempt is
  kept; the earlier one(s) are the mulligans.

  DistanceToPin is measured at each shot's *starting* position (a 74-yd wedge
  in the sample sits 392 yds from a par-4 pin — i.e. where the ball lay, not
  where it finished), which is exactly what makes "same start distance twice
  in a row" a reliable re-hit signal. The last shot on a hole (the holed
  putt / tap-in) has no successor on that hole, so it's never mis-flagged.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

ON_COURSE = "on_course"
PRACTICE = "practice"

# A hole counts as completed (holed out) once a shot's distance-to-pin drops to
# ~this (yards). GSPro logs every stroke including the holing putt, whose record
# lands at 0 — so the minimum distance-to-pin on a hole tells us it was finished
# (vs. a last hole abandoned when the round ended mid-play).
HOLED_OUT_YDS = 1.0

# Scorecard buckets, best → worst, by strokes relative to par.
SCORE_BUCKETS = ["Eagle+", "Birdie", "Par", "Bogey", "Double+"]

# Two consecutive shots on one hole whose starting distance-to-pin differs by
# no more than this (yards) count as "the same spot" — i.e. a re-hit/mulligan.
# Small on purpose: a genuine advancing shot moves the ball much farther than
# this, so real play is never swept up, only near-stationary re-hits.
MULLIGAN_TOLERANCE_YDS = 6.0


def _round_type_mask(df: pd.DataFrame) -> pd.Series:
    if "round_type" in df.columns:
        return df["round_type"].astype(str) == ON_COURSE
    return pd.Series(True, index=df.index)


def practice_view(df: pd.DataFrame, exclude_on_course: bool = True) -> pd.DataFrame:
    """The practice-analytics frame: everything, minus on-course rounds when
    ``exclude_on_course`` is set. No-op if there's no round_type column (pure
    CSV-sourced history is all practice anyway)."""
    if df.empty or not exclude_on_course or "round_type" not in df.columns:
        return df
    return df[df["round_type"].astype(str) != ON_COURSE]


def on_course_view(df: pd.DataFrame) -> pd.DataFrame:
    """Just the on-course rounds (empty frame if none / no round_type)."""
    if df.empty or "round_type" not in df.columns:
        return df.iloc[0:0]
    return df[df["round_type"].astype(str) == ON_COURSE]


def flag_mulligans(df: pd.DataFrame, tolerance: float = MULLIGAN_TOLERANCE_YDS) -> pd.Series:
    """Boolean Series (aligned to df.index) marking on-course mulligan shots —
    the earlier attempt when a shot was re-hit from the same spot on the same
    hole. Returns all-False when the columns needed to detect them are absent.
    """
    flags = pd.Series(False, index=df.index)
    if df.empty or not {"session_id", "hole", "distancetopin"} <= set(df.columns):
        return flags

    sub = df[_round_type_mask(df)]
    if sub.empty:
        return flags

    dist = pd.to_numeric(sub["distancetopin"], errors="coerce")
    # Distance-to-pin of the *next* shot on the same session+hole, in row order
    # (rows are stored chronologically). sort=False keeps that order intact.
    next_dist = dist.groupby([sub["session_id"], sub["hole"]], sort=False).shift(-1)
    # A shot is a mulligan if the next shot on the hole started ~the same
    # distance out (the ball didn't move). NaN (last shot on the hole) -> False.
    is_mulligan = (dist - next_dist).abs() <= tolerance
    flags.loc[sub.index] = is_mulligan.fillna(False)
    return flags


def drop_mulligans(df: pd.DataFrame, tolerance: float = MULLIGAN_TOLERANCE_YDS) -> pd.DataFrame:
    """Return df without on-course mulligan (re-hit) shots."""
    if df.empty:
        return df
    return df[~flag_mulligans(df, tolerance)]


# ---------------------------------------------------------------------------
# Scoring — turn the shot stream into per-hole and per-round scorecards.
#
# There's no explicit stroke count in the data, so strokes-per-hole is the
# number of shots logged on that hole (GSPro logs every stroke, putts included;
# drop mulligans first via drop_mulligans if you don't want re-hits counted).
# ---------------------------------------------------------------------------
_HOLE_COLS = {"session_id", "hole", "holepar"}


def bucket_for(to_par) -> str | None:
    """Scorecard bucket name for a strokes-minus-par value (None if unknown)."""
    if to_par is None or pd.isna(to_par):
        return None
    to_par = int(round(to_par))
    if to_par <= -2:
        return "Eagle+"
    if to_par == -1:
        return "Birdie"
    if to_par == 0:
        return "Par"
    if to_par == 1:
        return "Bogey"
    return "Double+"


def humanize_course(raw) -> str:
    """GSPro's internal course slug (its "CourseKey" field, e.g.
    "paynes_valley_gsp") to a readable display name ("Paynes Valley").
    Missing/blank input reads as "Unknown Course" rather than showing
    nothing, since that's a normal case (practice-range shots and any
    round archived before this field was captured have no course key)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "Unknown Course"
    text = re.sub(r"(?i)_gsp$", "", str(raw).strip())
    text = re.sub(r"[_\-]+", " ", text).strip()
    return text.title() if text else "Unknown Course"


def hole_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per (session_id, hole) scorecard row for on-course play: strokes, par,
    whether the hole was completed (holed out), and to_par. Empty frame when
    the needed columns are absent."""
    cols = ["session_id", "hole", "strokes", "par", "holed", "to_par"]
    oc = on_course_view(df)
    if oc.empty or not _HOLE_COLS <= set(oc.columns):
        return pd.DataFrame(columns=cols)

    grp = oc.groupby(["session_id", "hole"], sort=False)
    strokes = grp.size().rename("strokes")
    par = pd.to_numeric(grp["holepar"].first(), errors="coerce").rename("par")
    if "distancetopin" in oc.columns:
        min_dtp = (pd.to_numeric(oc["distancetopin"], errors="coerce")
                   .groupby([oc["session_id"], oc["hole"]], sort=False).min())
        holed = (min_dtp <= HOLED_OUT_YDS).rename("holed")
    else:
        holed = pd.Series(True, index=strokes.index, name="holed")

    out = pd.concat([strokes, par, holed], axis=1).reset_index()
    out["to_par"] = out["strokes"] - out["par"]
    return out


def round_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-round scorecard, oldest → newest. One row per on-course session with
    the course played, holes completed, strokes, par, to_par, whether the
    round was finished, longest drive, and a count per score bucket. Only
    completed (holed) holes with a known par count toward scoring.

    ``finished`` is False when the LAST hole the round attempted (which may
    be past the scored holes) was never holed out — i.e. play stopped
    mid-hole. A deliberate short round that holes out its last hole (e.g. a
    quick 3-hole loop) is NOT flagged; only an abandoned last hole is, since
    there's no reliable signal here for the course's intended hole count.
    """
    cols = (["session_id", "date", "course", "holes", "strokes", "par", "to_par",
            "finished", "longest_drive"] + SCORE_BUCKETS)
    all_holes = hole_summary(df)
    if all_holes.empty:
        return pd.DataFrame(columns=cols)
    scored = all_holes[all_holes["holed"] & all_holes["par"].notna()]
    if scored.empty:
        return pd.DataFrame(columns=cols)

    oc = on_course_view(df)
    dates = (pd.to_datetime(oc["session_date"], errors="coerce")
             if "session_date" in oc.columns else pd.Series(pd.NaT, index=oc.index))
    date_by_sid = dates.groupby(oc["session_id"]).max()

    course_by_sid: dict = {}
    if "course" in oc.columns:
        for sid, sub in oc.groupby("session_id"):
            vals = [str(v) for v in sub["course"].dropna() if str(v).strip()]
            course_by_sid[sid] = humanize_course(vals[0]) if vals else "Unknown Course"

    finished_by_sid = {
        sid: bool(sub.loc[sub["hole"].idxmax(), "holed"])
        for sid, sub in all_holes.groupby("session_id")
    }

    total_col = "totaldistance" if "totaldistance" in oc.columns else (
        "carry" if "carry" in oc.columns else None)

    rows = []
    for sid, sub in scored.groupby("session_id", sort=False):
        buckets = sub["to_par"].map(bucket_for).value_counts()
        drive = np.nan
        if total_col and "club" in oc.columns:
            drv = pd.to_numeric(
                oc.loc[(oc["session_id"] == sid) & (oc["club"] == "Dr"), total_col],
                errors="coerce").dropna()
            drive = float(drv.max()) if not drv.empty else np.nan
        row = {
            "session_id": sid,
            "date": date_by_sid.get(sid, pd.NaT),
            "course": course_by_sid.get(sid, "Unknown Course"),
            "holes": int(len(sub)),
            "strokes": int(sub["strokes"].sum()),
            "par": int(sub["par"].sum()),
            "to_par": int(sub["strokes"].sum() - sub["par"].sum()),
            "finished": finished_by_sid.get(sid, True),
            "longest_drive": drive,
        }
        for b in SCORE_BUCKETS:
            row[b] = int(buckets.get(b, 0))
        rows.append(row)

    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("date", na_position="first").reset_index(drop=True)
