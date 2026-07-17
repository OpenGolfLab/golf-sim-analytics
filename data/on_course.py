"""
On-course round handling: keeping course play separate from practice data.

``exclude_on_course_from_practice`` (see data/settings.py): on-course rounds
are full of shots that would pollute the "pure your swing" practice dashboards
— chips, punch-outs, layups, recovery shots, half-swing pitches. round_type
already tags every shot "practice" vs "on_course" (see live/shot_data.py), so
splitting them is just a filter. ``practice_view`` / ``on_course_view`` are the
two halves.

Mulligans (re-hit shots) are intentionally NOT filtered here: GSPro already
handles re-hits on its own scorecard, so stripping them again would
double-count the correction.
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


def exclude_putts(df: pd.DataFrame) -> pd.DataFrame:
    """Drop putter strokes (club == "Putter") from a frame.

    Putts are kept in the stored data so the scorecard can count strokes, but
    they are not launch-monitor shots — their ball data is copied from the
    preceding shot (see config.CLUB_INDEX_MAP's note on ClubIndex 26) — so
    every swing-analytics view and the contribution export drop them here. No-op
    when there's no club column."""
    from config import NON_SWING_CLUBS
    if df.empty or "club" not in df.columns:
        return df
    return df[~df["club"].astype(str).str.strip().isin(NON_SWING_CLUBS)]


# ---------------------------------------------------------------------------
# Scoring — turn the shot stream into per-hole and per-round scorecards.
#
# There's no explicit stroke count in the data, so strokes-per-hole is the
# number of shots logged on that hole (GSPro logs every stroke, putts included,
# and already resolves re-hits on its own scorecard — see the module docstring
# on why mulligans aren't filtered here).
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
    # A hole also counts as completed if a LATER hole in the same round was
    # started — you can't tee off hole N+1 without having finished hole N. This
    # rescues holes where GSPro logged no holing stroke at the pin: a conceded
    # gimme (the sim picks up your ball inside the concede radius) leaves the
    # last record a few feet out, so the distance-to-pin signal alone would miss
    # it and wrongly drop the hole from the scorecard (an 18-hole round showing
    # 17). Only the final hole of a round still relies on the holed-out distance.
    session_max_hole = out.groupby("session_id")["hole"].transform("max")
    out["holed"] = out["holed"] | (out["hole"] < session_max_hole)
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
