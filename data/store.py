"""
Parquet-backed data store for historical shots.

Previously `load_master_data()` concatenated every Parquet file in
parquet_data/ on every call with no caching — fine at today's data volume,
but it re-reads the entire history from disk on every ingest/refresh. This
module keeps that same simple concat-all approach (still the right choice
at this data scale) but isolates it from Tkinter so it's unit-testable, and
gives it a clear seam to add caching later if history grows large enough
to matter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from data.columns import (
    BALL_SPEED_ALIASES, CARRY_ALIASES, CLUB_SPEED_ALIASES, OFFLINE_ALIASES,
    SMASH_FACTOR_ALIASES, TOTAL_ALIASES, find_col,
)
from data.analytics import ShotScorer
from data.io import extract_date_from_filename
from data.physics import theoretical_max_drive_yards
from config import get_club_rank, normalize_club_name, resolve_club_index

log = logging.getLogger(__name__)


def load_master_dataframe(data_dir: Path) -> pd.DataFrame:
    """Load and lightly clean every archived session into one DataFrame."""
    files = list(data_dir.glob("*.parquet"))
    if not files:
        return pd.DataFrame()

    frames = []
    for f in files:
        try:
            frames.append(pd.read_parquet(f))
        except Exception:
            log.exception("Failed to read %s — skipping", f)
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    # DIV/0 sensor glitches only ever appear as text, so scrub just the
    # string columns — running the regex over every numeric cell too made
    # this the most expensive line of the load at larger histories.
    obj_cols = [c for c in df.columns if df[c].dtype == object]
    if obj_cols:
        df[obj_cols] = df[obj_cols].replace(
            to_replace=r"(?i).*div/0.*", value=np.nan, regex=True)

    # Only carry is required. clubspeed used to be required too, back when
    # every archived row came from a CSV export that always had it — but
    # live-tracked rows (see live/shot_data.py) legitimately have no club
    # speed at all (GSPro's currentRound.dat doesn't expose it), so
    # requiring it here would silently drop every live-tracked shot from
    # the whole app the moment any CSV-sourced file in the mix has a
    # clubspeed column. Individual charts that need club speed (Swing
    # Efficiency, Carry Efficiency) already skip rows missing it on their
    # own — that per-chart handling is the right place for this, not a
    # blanket drop here.
    carry_col = find_col(df, CARRY_ALIASES)
    if carry_col:
        df = df.dropna(subset=[carry_col])

    if "club" in df.columns:
        df = df[df["club"].notna()]
        df["club"] = df["club"].astype(str).str.strip()
        df = df[~df["club"].str.lower().isin(("", "nan", "none"))]
        # Self-heals older archived Parquet data written before club-name
        # normalization existed (e.g. "I9"/"9I"/"DR"/"Dr" all collapse to
        # one canonical "9I"/"Dr" here on every load), not just new ingests.
        df["club"] = df["club"].apply(normalize_club_name)

    if "club_index" in df.columns:
        # Live-tracked rows also carry GSPro's raw numeric ClubIndex
        # alongside the already-resolved "club" name. Re-resolving it here
        # on every load (rather than only at archive time) means filling
        # in real mappings in config.CLUB_INDEX_MAP later self-heals every
        # already-archived live round automatically, the same pattern used
        # above for club-name normalization.
        has_index = df["club_index"].notna()
        resolved = df.loc[has_index, "club_index"].apply(
            lambda i: normalize_club_name(resolve_club_index(i))
        )
        df.loc[has_index, "club"] = resolved

    if "round_type" not in df.columns:
        # Every CSV export is sourced from GSPro's Practice Range shot
        # list (see data/export_watcher.py) — "on_course" only ever comes
        # from a live-tracked round where GSPro reports a real RoundID.
        df["round_type"] = "practice"
    else:
        df["round_type"] = df["round_type"].fillna("practice")

    if "session_id" in df.columns and "session_date" in df.columns:
        # Some sessions archived under older code versions have a
        # session_date that fell back to file ctime (off by several hours
        # from the actual play time, occasionally rolling onto the wrong
        # calendar day) because filename parsing failed or didn't exist
        # yet at ingest time. session_id is always the original filename
        # stem, so re-derive the date from it here on every load — this
        # self-heals stale/imprecise dates in already-archived data, not
        # just newly-ingested sessions, without needing a migration step.
        stored = pd.to_datetime(df["session_date"], errors="coerce")
        session_ids = df["session_id"].astype(str)
        # Resolve once per unique session rather than once per row (a
        # session can be hundreds of shots) — cheaper, and avoids spamming
        # the log with a repeated warning per row for any corrupt filename.
        id_to_date = {sid: extract_date_from_filename(sid) for sid in session_ids.unique()}
        from_filename = session_ids.map(id_to_date)
        df = df.copy()
        df["session_date"] = from_filename.where(from_filename.notna(), stored)

    if "session_date" in df.columns:
        dates = pd.to_datetime(df["session_date"], errors="coerce")
        future = dates > (pd.Timestamp.now() + pd.Timedelta(days=2))
        if future.any():
            # Corrupt filename date (e.g. a year segment of "30" -> 2030).
            # Keep the shots — they're real data — but blank the date so a
            # phantom "future" session can't sit permanently at the top of
            # every Last-N-Sessions / Last-30-Days filter.
            log.warning(
                "%d rows have a session_date in the future (corrupt source "
                "filename?); clearing their date so recency filters ignore them",
                int(future.sum()),
            )
            df = df.copy()
            df.loc[future, "session_date"] = pd.NaT

    return df


def unique_clubs(df: pd.DataFrame) -> list[str]:
    if "club" not in df.columns:
        return []
    return sorted(df["club"].dropna().unique().tolist(), key=get_club_rank)


class PlayerRecords:
    """Longest drive / max club speed / handicap / theoretical max drive
    summary shown in the sidebar."""

    def __init__(self, longest_drive: str = "--- Yds", max_club_speed: str = "--- MPH",
                 handicap: str = "---", theoretical_max_drive: str = "--- Yds",
                 max_ball_speed: str = "--- MPH"):
        # handicap stays "---" until handicap tracking lands (deferred — see
        # FEATURE_ROADMAP_PROMPT.md); nothing computes it yet, so showing a
        # number here would be fabricated data on the landing page.
        self.longest_drive = longest_drive
        self.max_club_speed = max_club_speed
        self.handicap = handicap
        self.theoretical_max_drive = theoretical_max_drive
        self.max_ball_speed = max_ball_speed


def compute_player_records(df: pd.DataFrame) -> PlayerRecords:
    if df.empty:
        return PlayerRecords()

    total_col = find_col(df, ["total", "totaldistance"]) or find_col(df, CARRY_ALIASES)
    cs_col = find_col(df, CLUB_SPEED_ALIASES)

    r_speed = "--- MPH"
    if cs_col and not df[cs_col].dropna().empty:
        r_speed = f"{df[cs_col].max():.1f} MPH"

    bs_col = find_col(df, BALL_SPEED_ALIASES)
    r_ball = "--- MPH"
    if bs_col and not df[bs_col].dropna().empty:
        r_ball = f"{df[bs_col].max():.1f} MPH"

    r_drive = "--- Yds"
    r_theoretical_max = "--- Yds"
    if "club" in df.columns:
        dr_df = df[df["club"].astype(str).str.upper().str.contains("DR", na=False)]
        if total_col and not dr_df.empty:
            r_drive = f"{dr_df[total_col].max():.1f} Yds"
        if cs_col and not dr_df.empty:
            dr_speeds = dr_df[cs_col].dropna()
            if not dr_speeds.empty:
                yards = theoretical_max_drive_yards(dr_speeds.max())
                r_theoretical_max = f"{yards:.0f} Yds"

    return PlayerRecords(longest_drive=r_drive, max_club_speed=r_speed,
                          theoretical_max_drive=r_theoretical_max, max_ball_speed=r_ball)


@dataclass
class HomeStats:
    """Recency/trend summary for the landing page (ui/home_page.py) —
    complements the sidebar's all-time PlayerRecords, which deliberately has
    no notion of "recent". Every field has a safe default so the home page
    renders sensibly for an empty install or a frame with no usable dates.
    """
    total_shots: int = 0
    session_count: int = 0
    shots_this_week: int = 0
    # None when no session has a real date (session_date can be NaT for
    # rows whose corrupt source filename produced a future date — see
    # load_master_dataframe, which clears those rather than dropping them).
    days_since_last: int | None = None
    last_date_label: str = ""            # e.g. "Jul 6"
    last_shots: int = 0
    last_clubs: list[str] = field(default_factory=list)  # bag order
    last_best_smash: float | None = None
    # Carry trend for the most-hit club of the last session: last-session
    # mean vs. that club's mean over all prior sessions. Both None unless
    # there's enough data on each side for the comparison to mean anything.
    delta_club: str | None = None
    delta_carry: float | None = None
    delta_last_mean: float | None = None  # that club's mean carry last session
    # Mean Shot Quality Score (0-100) over all shots, via analytics.ShotScorer.
    # None when nothing is scoreable (missing carry/launch/spin columns).
    avg_shot_quality: int | None = None


def compute_home_stats(df: pd.DataFrame) -> HomeStats:
    stats = HomeStats()
    if df.empty:
        return stats
    stats.total_shots = len(df)
    quality = ShotScorer().score(df).dropna()
    if not quality.empty:
        stats.avg_shot_quality = int(round(quality.mean()))
    if "session_id" in df.columns:
        stats.session_count = int(df["session_id"].nunique())

    if "session_date" in df.columns:
        dates = pd.to_datetime(df["session_date"], errors="coerce")
    else:
        dates = pd.Series(pd.NaT, index=df.index)
    now = pd.Timestamp.now()
    stats.shots_this_week = int((dates >= now - pd.Timedelta(days=7)).sum())

    if "session_id" not in df.columns:
        return stats
    per_session_date = dates.groupby(df["session_id"]).max().dropna()
    if per_session_date.empty:
        return stats

    last_sid = per_session_date.idxmax()
    last_date = per_session_date.max()
    stats.days_since_last = max(0, (now.normalize() - last_date.normalize()).days)
    stats.last_date_label = f"{last_date.strftime('%b')} {last_date.day}"

    last_df = df[df["session_id"] == last_sid]
    stats.last_shots = len(last_df)
    if "club" in df.columns:
        stats.last_clubs = sorted(last_df["club"].dropna().unique(), key=get_club_rank)

    # Best smash of the last session: prefer a recorded smash-factor column,
    # else derive from ball/club speed. Values outside (0.5, 2.0) are sensor
    # glitches (e.g. DIV/0 rows), not golf.
    smash_col = find_col(df, SMASH_FACTOR_ALIASES)
    if smash_col:
        smash = pd.to_numeric(last_df[smash_col], errors="coerce")
    else:
        bs_col, cs_col = find_col(df, BALL_SPEED_ALIASES), find_col(df, CLUB_SPEED_ALIASES)
        if bs_col and cs_col:
            cs = pd.to_numeric(last_df[cs_col], errors="coerce")
            smash = pd.to_numeric(last_df[bs_col], errors="coerce") / cs.where(cs > 0)
        else:
            smash = pd.Series(dtype=float)
    smash = smash[(smash > 0.5) & (smash < 2.0)].dropna()
    if not smash.empty:
        stats.last_best_smash = float(smash.max())

    carry_col = find_col(df, CARRY_ALIASES)
    if carry_col and "club" in df.columns and not last_df.empty:  # carry delta
        prior_df = df[df["session_id"] != last_sid]
        for club in last_df["club"].value_counts().index:
            last_c = pd.to_numeric(
                last_df.loc[last_df["club"] == club, carry_col], errors="coerce").dropna()
            prior_c = pd.to_numeric(
                prior_df.loc[prior_df["club"] == club, carry_col], errors="coerce").dropna()
            if len(last_c) >= 5 and len(prior_c) >= 10:
                stats.delta_club = str(club)
                stats.delta_last_mean = float(last_c.mean())
                stats.delta_carry = float(last_c.mean() - prior_c.mean())
                break

    return stats


@dataclass
class HomeTrends:
    """Phase-2/3 landing-page content: per-session trend series, weekly
    practice rhythm, and rule-based focus-area callouts. Same philosophy as
    HomeStats: every field defaults safe, sessions without dates simply
    don't participate in anything time-ordered."""
    # (label, values oldest->newest, delta_text, improving) — a series only
    # exists when it has >= 3 usable sessions, so sparklines never lie with
    # a two-point "trend".
    series: list = field(default_factory=list)
    weekly_shots: list = field(default_factory=list)  # oldest -> newest
    streak_weeks: int = 0
    focus: list = field(default_factory=list)  # (tag, text, tone: "warn"|"good")
    # Per-session driver TOTAL-distance median (carry + roll), oldest -> newest,
    # >= 5 driver shots per session. Complements the "Dr carry" entry in
    # `series` with the full driver-distance picture. Computed here but not yet
    # rendered — the landing-page driver card wires it in when the tile
    # cleanup resumes (see ui/home_page.py).
    driver_distance: list = field(default_factory=list)
    # Per-session mean Shot Quality Score (0-100), oldest -> newest, over the
    # same recent sessions as `series`. Drives the landing page's Shot Quality
    # trend line.
    shot_quality_series: list = field(default_factory=list)


def _session_smash(sub: pd.DataFrame, smash_col, bs_col, cs_col) -> pd.Series:
    """Plausible smash values for one session's rows (recorded column if
    present, else derived from speeds), filtered to the (0.5, 2.0) window
    compute_home_stats also uses."""
    if smash_col:
        s = pd.to_numeric(sub[smash_col], errors="coerce")
    elif bs_col and cs_col:
        cs = pd.to_numeric(sub[cs_col], errors="coerce")
        s = pd.to_numeric(sub[bs_col], errors="coerce") / cs.where(cs > 0)
    else:
        s = pd.Series(dtype=float)
    return s[(s > 0.5) & (s < 2.0)].dropna()


def compute_home_trends(df: pd.DataFrame, max_sessions: int = 10, weeks: int = 8) -> HomeTrends:
    trends = HomeTrends()
    if df.empty or "session_id" not in df.columns:
        return trends

    dates = (pd.to_datetime(df["session_date"], errors="coerce")
             if "session_date" in df.columns else pd.Series(pd.NaT, index=df.index))
    ordered_sids = list(
        dates.groupby(df["session_id"]).max().dropna().sort_values().index[-max_sessions:])

    carry_col = find_col(df, CARRY_ALIASES)

    # Per-session carry for the two anchor clubs peers also trend (longest
    # club + a mid iron). Median, not mean, and >= 5 shots per session: real
    # data contains live-tracked rounds where a handful of ~80yd shots got
    # labeled "Dr" via the guesswork CLUB_INDEX_MAP — a mean over 3 such
    # rows turns an improving driver trend into a -200yd cliff.
    if carry_col and "club" in df.columns:
        for club in ("Dr", "7I"):
            vals = []
            for sid in ordered_sids:
                c = pd.to_numeric(
                    df.loc[(df["session_id"] == sid) & (df["club"] == club), carry_col],
                    errors="coerce").dropna()
                if len(c) >= 5:
                    vals.append(float(c.median()))
            if len(vals) >= 3:
                d = vals[-1] - vals[0]
                trends.series.append((f"{club} carry", vals, f"{d:+.0f} yds", d >= 0))

    # Driver TOTAL distance per session (carry + roll), same >= 5-shot / median
    # discipline as the carry series above. Kept in its own field, not appended
    # to `series`, so nothing renders until the landing-page driver card opts in.
    total_col = find_col(df, TOTAL_ALIASES)
    if total_col and "club" in df.columns:
        tvals = []
        for sid in ordered_sids:
            t = pd.to_numeric(
                df.loc[(df["session_id"] == sid) & (df["club"] == "Dr"), total_col],
                errors="coerce").dropna()
            if len(t) >= 5:
                tvals.append(float(t.median()))
        trends.driver_distance = tvals

    # Per-session mean Shot Quality, oldest -> newest, for the landing-page
    # trend line. Scored per session so each point reflects that day's contact.
    scorer = ShotScorer()
    sq = []
    for sid in ordered_sids:
        s = scorer.score(df[df["session_id"] == sid]).dropna()
        if not s.empty:
            sq.append(round(float(s.mean()), 1))
    trends.shot_quality_series = sq

    # Driver-only smash: an all-club smash median tracks which clubs were
    # practiced that day (wedges sit ~1.1, driver ~1.45), not contact
    # quality, so it swings wildly with session club mix.
    smash_col = find_col(df, SMASH_FACTOR_ALIASES)
    bs_col, cs_col = find_col(df, BALL_SPEED_ALIASES), find_col(df, CLUB_SPEED_ALIASES)
    vals = []
    if "club" in df.columns:
        for sid in ordered_sids:
            sub = df[(df["session_id"] == sid) & (df["club"] == "Dr")]
            s = _session_smash(sub, smash_col, bs_col, cs_col)
            if len(s) >= 3:
                vals.append(float(s.median()))
    if len(vals) >= 3:
        trends.series.append(
            ("Dr smash", vals, f"{vals[0]:.2f} → {vals[-1]:.2f}", vals[-1] >= vals[0]))

    # Practice rhythm: shots per trailing 7-day bucket, oldest first.
    now = pd.Timestamp.now()
    for k in range(weeks, 0, -1):
        lo, hi = now - pd.Timedelta(days=7 * k), now - pd.Timedelta(days=7 * (k - 1))
        trends.weekly_shots.append(int(((dates > lo) & (dates <= hi)).sum()))
    for n in reversed(trends.weekly_shots):
        if n <= 0:
            break
        trends.streak_weeks += 1

    # Focus areas — deliberately rule-based, not clever. Thresholds exist so
    # a callout only appears when the data actually supports it.
    off_col = find_col(df, OFFLINE_ALIASES)
    if off_col and "club" in df.columns:
        stds = {}
        for club, sub in df.groupby("club"):
            o = pd.to_numeric(sub[off_col], errors="coerce").dropna()
            if len(o) >= 15:
                stds[str(club)] = float(o.std())
        if len(stds) >= 2:
            worst = max(stds, key=stds.get)
            best = min(stds, key=stds.get)
            trends.focus.append(
                ("Dispersion", f"{worst} widest — ±{stds[worst]:.0f} yds offline", "warn"))
            trends.focus.append(
                ("Strength", f"{best} tightest — ±{stds[best]:.0f} yds offline", "good"))

    if carry_col and "club" in df.columns:
        means = {}
        for club, sub in df.groupby("club"):
            c = pd.to_numeric(sub[carry_col], errors="coerce").dropna()
            if len(c) >= 8:
                means[str(club)] = float(c.mean())
        order = sorted(means, key=get_club_rank)
        if len(order) >= 3:
            gaps = [(order[i], order[i + 1], means[order[i]] - means[order[i + 1]])
                    for i in range(len(order) - 1)]
            avg = sum(g for _a, _b, g in gaps) / len(gaps)
            a, b, g = max(gaps, key=lambda item: item[2])
            if avg > 0 and g >= avg * 1.6 and g - avg >= 6:
                trends.focus.insert(
                    0, ("Gapping", f"{a} → {b} gap {g:.0f} yds (bag avg {avg:.0f})", "warn"))

    trends.focus = trends.focus[:3]
    return trends
