import pandas as pd
import pytest

from data.filters import (
    filter_master_data, drop_warmup_shots, TIME_ALL, TIME_LAST_SESSION,
    CLUB_ALL, QUALITY_ALL, QUALITY_DROP_WORST_10,
    WARMUP_OFF, WARMUP_SESSION, WARMUP_CLUB,
)


def test_drop_warmup_shots_removes_first_n_per_session():
    df = pd.DataFrame({
        "session_id": ["a"] * 8 + ["b"] * 3,
        "carry": list(range(8)) + list(range(3)),
    })
    out = drop_warmup_shots(df, n=5)
    # a: 8 shots -> 3 kept; b: only 3 shots (all warm-up) -> 0 kept.
    assert list(out["session_id"]) == ["a", "a", "a"]
    assert list(out["carry"]) == [5, 6, 7]


def test_drop_warmup_shots_no_session_column_is_noop():
    df = pd.DataFrame({"carry": [1, 2, 3]})
    assert len(drop_warmup_shots(df)) == 3


def test_drop_warmup_off_keeps_everything():
    df = pd.DataFrame({
        "session_id": ["a"] * 8,
        "club": ["Dr"] * 8,
        "carry": list(range(8)),
    })
    out = drop_warmup_shots(df, WARMUP_OFF)
    assert len(out) == 8


def test_drop_warmup_per_club_drops_first_of_each_club():
    # Mixed bag within one session: Dr x3, then 7I x2, then back to Dr x2.
    df = pd.DataFrame({
        "session_id": ["s1"] * 7,
        "club": ["Dr", "Dr", "Dr", "7I", "7I", "Dr", "Dr"],
        "carry": [250, 240, 245, 150, 140, 248, 242],
    })
    out = drop_warmup_shots(df, WARMUP_CLUB)
    # First Dr (250) and first 7I (150) dropped; the later Dr run is not a
    # new club, so its shots stay.
    assert out["carry"].tolist() == [240, 245, 140, 248, 242]


def test_drop_warmup_per_club_needs_club_column():
    df = pd.DataFrame({"session_id": ["a"] * 3, "carry": [1, 2, 3]})
    assert len(drop_warmup_shots(df, WARMUP_CLUB)) == 3


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "club": ["Dr", "Dr", "7I", "7I", "7I"],
        "carry": [250, 240, 150, 140, 100],
        "session_id": ["s1", "s1", "s2", "s2", "s2"],
        "session_date": pd.to_datetime(
            ["2026-01-01", "2026-01-01", "2026-02-01", "2026-02-01", "2026-02-01"]
        ),
    })


def test_filter_master_data_empty_df_returns_empty():
    result = filter_master_data(pd.DataFrame(), TIME_ALL, CLUB_ALL, QUALITY_ALL)
    assert result.empty


def test_time_filter_last_session_keeps_only_latest_session(sample_df):
    result = filter_master_data(sample_df, TIME_LAST_SESSION, CLUB_ALL, QUALITY_ALL)
    assert set(result["session_id"]) == {"s2"}


def test_club_filter_matches_substring(sample_df):
    result = filter_master_data(sample_df, TIME_ALL, "7I", QUALITY_ALL)
    assert set(result["club"]) == {"7I"}


def test_club_filter_all_clubs_is_noop(sample_df):
    result = filter_master_data(sample_df, TIME_ALL, CLUB_ALL, QUALITY_ALL)
    assert len(result) == len(sample_df)


def test_quality_filter_drops_worst_10_percent_per_club(sample_df):
    result = filter_master_data(sample_df, TIME_ALL, CLUB_ALL, QUALITY_DROP_WORST_10)
    assert 100 not in result.loc[result["club"] == "7I", "carry"].tolist()


def test_ignore_global_club_used_by_gapping_dashboard(sample_df):
    result = filter_master_data(sample_df, TIME_ALL, "7I", QUALITY_ALL, ignore_global_club=True)
    assert set(result["club"]) == {"Dr", "7I"}


def test_club_filter_accepts_a_set_of_exact_names(sample_df):
    # The multi-select Club Filter dropdown passes a set of checked club
    # names rather than a single string.
    result = filter_master_data(sample_df, TIME_ALL, {"Dr"}, QUALITY_ALL)
    assert set(result["club"]) == {"Dr"}


def test_club_filter_set_with_multiple_clubs(sample_df):
    df = sample_df.copy()
    df.loc[len(df)] = ["3W", 220, "s1", pd.Timestamp("2026-01-01")]
    result = filter_master_data(df, TIME_ALL, {"Dr", "3W"}, QUALITY_ALL)
    assert set(result["club"]) == {"Dr", "3W"}


def test_club_filter_empty_set_returns_no_rows(sample_df):
    result = filter_master_data(sample_df, TIME_ALL, set(), QUALITY_ALL)
    assert result.empty
