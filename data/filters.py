"""
Filtering logic for the global Time / Club / Shot-Quality filters.

Pulled out of the god-class untouched in behavior, just relocated and
given real parameter names, so it can be unit tested without a Tkinter
event loop.
"""
from __future__ import annotations

import pandas as pd

from data.columns import CARRY_ALIASES, find_col

TIME_ALL = "All Time"
TIME_CURRENT_SESSION = "Current Session"
TIME_LAST_SESSION = "Last Session"
TIME_LAST_3_SESSIONS = "Last 3 Sessions"
TIME_LAST_5_SESSIONS = "Last 5 Sessions"
TIME_LAST_30_DAYS = "Last 30 Days"

# "Current Session" is sourced from the in-progress live buffer, not
# master_df, so it's handled specially in app_window._filtered_frames();
# _apply_time_filter treats it as a no-op if it ever reaches here.
TIME_FILTER_OPTIONS = [
    TIME_CURRENT_SESSION, TIME_ALL, TIME_LAST_SESSION,
    TIME_LAST_3_SESSIONS, TIME_LAST_5_SESSIONS, TIME_LAST_30_DAYS,
]

CLUB_ALL = "All Clubs"

QUALITY_ALL = "All Shots"
QUALITY_DROP_WORST_10 = "Drop Worst 10%"
QUALITY_PEAK_10 = "Peak Potential (Top 10%)"

QUALITY_FILTER_OPTIONS = [QUALITY_ALL, QUALITY_DROP_WORST_10, QUALITY_PEAK_10]

WARMUP_SHOTS = 5


def drop_warmup_shots(df: pd.DataFrame, n: int = WARMUP_SHOTS) -> pd.DataFrame:
    """Drop the first ``n`` shots of each session (warm-up swings), by row order
    within session_id. No-op when there's no session column."""
    if df.empty or "session_id" not in df.columns:
        return df
    return df[df.groupby("session_id").cumcount() >= n]


def _apply_time_filter(df: pd.DataFrame, time_filter: str) -> pd.DataFrame:
    if "session_date" not in df.columns or time_filter == TIME_ALL:
        return df

    df = df.copy()
    # coerce, matching every other session_date parse in the app — one corrupt
    # date must not raise in the filter hot path and blank every dashboard.
    df["session_date"] = pd.to_datetime(df["session_date"], errors="coerce")

    if time_filter in (TIME_LAST_SESSION, TIME_LAST_3_SESSIONS, TIME_LAST_5_SESSIONS):
        n_sessions = {
            TIME_LAST_SESSION: 1,
            TIME_LAST_3_SESSIONS: 3,
            TIME_LAST_5_SESSIONS: 5,
        }[time_filter]
        session_dates = df.groupby("session_id")["session_date"].max().sort_values(ascending=False)
        keep = session_dates.index.tolist()[:n_sessions]
        return df[df["session_id"].isin(keep)]

    if time_filter == TIME_LAST_30_DAYS:
        return df[df["session_date"] >= (pd.Timestamp.now() - pd.Timedelta(days=30))]

    return df


def _apply_club_filter(df: pd.DataFrame, club_filter) -> pd.DataFrame:
    """club_filter accepts either:
    - CLUB_ALL (no filtering), or
    - a single club-name string (legacy substring match, e.g. "7I"), or
    - a set/list/tuple of exact club names — used by the multi-select
      Club Filter dropdown, which lets you pick several specific clubs
      at once rather than only one.
    """
    if club_filter is None or club_filter == CLUB_ALL or "club" not in df.columns:
        return df

    if isinstance(club_filter, (set, frozenset, list, tuple)):
        return df[df["club"].isin(club_filter)]

    search_term = club_filter.upper()
    if search_term == "DRIVER":
        search_term = "DR"
    return df[
        df["club"].astype(str).str.upper().str.contains(search_term)
        | (df["club"].astype(str).str.upper() == club_filter.upper())
    ]


def _apply_quality_filter(df: pd.DataFrame, quality_filter: str) -> pd.DataFrame:
    if quality_filter == QUALITY_ALL or "club" not in df.columns:
        return df
    carry_col = find_col(df, CARRY_ALIASES)
    if not carry_col:
        return df
    if quality_filter == QUALITY_DROP_WORST_10:
        return df[df.groupby("club")[carry_col].transform(lambda x: x >= x.quantile(0.10))]
    if quality_filter == QUALITY_PEAK_10:
        return df[df.groupby("club")[carry_col].transform(lambda x: x >= x.quantile(0.90))]
    return df


def filter_master_data(
    df: pd.DataFrame,
    time_filter: str,
    club_filter: str,
    quality_filter: str,
    ignore_global_club: bool = False,
) -> pd.DataFrame:
    """Apply the global Time / Club / Shot-Quality filters to a DataFrame.

    ignore_global_club=True is used by the Club Gapping dashboard, which
    has its own per-club checkbox menu instead of the global club filter.
    """
    if df.empty:
        return df

    df = _apply_time_filter(df, time_filter)
    if not ignore_global_club:
        df = _apply_club_filter(df, club_filter)
    df = _apply_quality_filter(df, quality_filter)
    return df
