import pandas as pd

from data.store import (
    compute_home_stats, compute_home_trends, compute_player_records, unique_clubs,
)


def test_compute_player_records_empty_df_returns_placeholders():
    records = compute_player_records(pd.DataFrame())
    assert records.longest_drive == "--- Yds"
    assert records.max_club_speed == "--- MPH"


def test_compute_player_records_finds_max_driver_carry_and_speed():
    df = pd.DataFrame({
        "club": ["Dr", "Dr", "7I"],
        "total": [280, 260, 150],
        "clubspeed": [112.0, 108.0, 90.0],
        "ballspeed": [168.0, 160.0, 120.0],
    })
    records = compute_player_records(df)
    assert records.longest_drive == "280.0 Yds"
    assert records.max_club_speed == "112.0 MPH"
    assert records.max_ball_speed == "168.0 MPH"


def test_compute_player_records_ball_speed_placeholder_without_data():
    assert compute_player_records(pd.DataFrame()).max_ball_speed == "--- MPH"


def test_unique_clubs_sorted_by_bag_order():
    df = pd.DataFrame({"club": ["7I", "Dr", "Dr", "3W"]})
    assert unique_clubs(df) == ["Dr", "3W", "7I"]


def test_unique_clubs_no_club_column_returns_empty_list():
    assert unique_clubs(pd.DataFrame({"carry": [1, 2]})) == []


# --- compute_home_stats: landing-page recency/trend summary ---

def test_compute_home_stats_empty_df_returns_safe_defaults():
    stats = compute_home_stats(pd.DataFrame())
    assert stats.total_shots == 0
    assert stats.session_count == 0
    assert stats.days_since_last is None
    assert stats.delta_club is None
    assert stats.avg_shot_quality is None


def _two_session_df():
    now = pd.Timestamp.now().normalize()
    prior = pd.DataFrame({
        "club": ["7I"] * 12,
        "carry": [150.0] * 12,
        "smashfactor": [1.30] * 12,
        "session_date": [now - pd.Timedelta(days=10)] * 12,
        "session_id": ["old"] * 12,
    })
    last = pd.DataFrame({
        "club": ["7I"] * 6 + ["Dr"] * 2,
        "carry": [155.0] * 6 + [260.0, 255.0],
        "smashfactor": [1.40] * 6 + [1.48, 5.0],  # 5.0 = sensor glitch, ignored
        "session_date": [now - pd.Timedelta(days=2)] * 8,
        "session_id": ["new"] * 8,
    })
    return pd.concat([prior, last], ignore_index=True)


def test_compute_home_stats_last_session_summary_and_carry_delta():
    stats = compute_home_stats(_two_session_df())
    assert stats.total_shots == 20
    assert stats.session_count == 2
    assert stats.days_since_last == 2
    assert stats.shots_this_week == 8
    assert stats.last_shots == 8
    assert stats.last_clubs == ["Dr", "7I"]  # bag order
    assert stats.last_best_smash == 1.48  # the 5.0 glitch row is excluded
    # 7I is the most-hit club last session with enough prior shots:
    # 155 avg vs 150 prior -> +5.
    assert stats.delta_club == "7I"
    assert stats.delta_carry == 5.0
    assert stats.delta_last_mean == 155.0


def test_compute_home_stats_includes_shot_quality():
    stats = compute_home_stats(_two_session_df())
    # 7I has enough shots for the scorer's self-consistency component.
    assert stats.avg_shot_quality is not None
    assert 0 <= stats.avg_shot_quality <= 100


def test_compute_home_stats_all_nat_dates_still_counts_shots():
    df = pd.DataFrame({
        "club": ["Dr"] * 3,
        "carry": [250.0] * 3,
        "session_date": [pd.NaT] * 3,
        "session_id": ["a"] * 3,
    })
    stats = compute_home_stats(df)
    assert stats.total_shots == 3
    assert stats.session_count == 1
    assert stats.days_since_last is None  # no dated session to be "last"
    assert stats.last_shots == 0
    assert stats.shots_this_week == 0


def test_compute_home_stats_derives_smash_from_speeds_when_no_smash_column():
    now = pd.Timestamp.now().normalize()
    df = pd.DataFrame({
        "club": ["Dr"] * 2,
        "carry": [250.0, 255.0],
        "ballspeed": [150.0, 165.0],
        "clubspeed": [100.0, 110.0],
        "session_date": [now] * 2,
        "session_id": ["a"] * 2,
    })
    stats = compute_home_stats(df)
    assert stats.last_best_smash == 1.5


# --- compute_home_trends: sparkline series, weekly rhythm, focus areas ---

def test_compute_home_trends_empty_df_returns_safe_defaults():
    trends = compute_home_trends(pd.DataFrame())
    assert trends.series == []
    assert trends.weekly_shots == []
    assert trends.streak_weeks == 0
    assert trends.focus == []


def _trend_df():
    """Three dated sessions (20, 13, 6 days ago) with rising driver carry,
    a wide-offline 7I and a tight Sw."""
    now = pd.Timestamp.now().normalize()
    frames = []
    for i, dr_carry in enumerate([240.0, 245.0, 250.0]):
        frames.append(pd.DataFrame({
            "club": ["Dr"] * 5 + ["7I"] * 6 + ["Sw"] * 6,
            "carry": [dr_carry] * 5 + [150.0] * 6 + [80.0] * 6,
            "offline": [5, -5, 5, -5, 5] + [25, -25] * 3 + [2, -2] * 3,
            "session_date": [now - pd.Timedelta(days=20 - 7 * i)] * 17,
            "session_id": [f"s{i}"] * 17,
        }))
    return pd.concat(frames, ignore_index=True)


def test_compute_home_trends_carry_series_and_rhythm():
    trends = compute_home_trends(_trend_df())
    dr = next(s for s in trends.series if s[0] == "Dr carry")
    assert dr[1] == [240.0, 245.0, 250.0]
    assert dr[2] == "+10 yds"
    assert dr[3] is True  # improving
    assert len(trends.weekly_shots) == 8
    assert sum(trends.weekly_shots) == 51  # every shot lands in some bucket
    assert trends.streak_weeks == 3  # sessions 6/13/20 days ago = 3 straight weeks


def test_compute_home_trends_driver_distance_series_oldest_to_newest():
    now = pd.Timestamp.now().normalize()
    frames = []
    for i, dr_total in enumerate([275.0, 280.0, 285.0]):
        frames.append(pd.DataFrame({
            "club": ["Dr"] * 5 + ["7I"] * 6,
            "carry": [dr_total - 20] * 5 + [150.0] * 6,
            "total": [dr_total] * 5 + [165.0] * 6,
            "session_date": [now - pd.Timedelta(days=20 - 7 * i)] * 11,
            "session_id": [f"s{i}"] * 11,
        }))
    trends = compute_home_trends(pd.concat(frames, ignore_index=True))
    # Per-session driver total median, oldest -> newest; kept out of `series`.
    assert trends.driver_distance == [275.0, 280.0, 285.0]
    assert not any(s[0] == "Dr total" for s in trends.series)


def test_compute_home_trends_driver_distance_empty_without_total_column():
    # _trend_df has carry only — no total-distance column to read.
    assert compute_home_trends(_trend_df()).driver_distance == []


def test_compute_home_trends_focus_flags_widest_and_tightest_clubs():
    trends = compute_home_trends(_trend_df())
    tags = {tag: text for tag, text, _tone in trends.focus}
    assert "7I" in tags["Dispersion"]  # +/-25 offline = widest
    assert "Sw" in tags["Strength"]    # +/-2 offline = tightest


def test_compute_home_trends_flags_gapping_outlier():
    now = pd.Timestamp.now().normalize()
    # Dr->7I gap 60 yds vs 7I->Pw gap 15: a clear outlier vs the bag average.
    df = pd.DataFrame({
        "club": ["Dr"] * 8 + ["7I"] * 8 + ["Pw"] * 8,
        "carry": [235.0] * 8 + [175.0] * 8 + [160.0] * 8,
        "session_date": [now] * 24,
        "session_id": ["a"] * 24,
    })
    trends = compute_home_trends(df)
    gapping = [text for tag, text, _t in trends.focus if tag == "Gapping"]
    assert gapping and "Dr → 7I" in gapping[0]


def test_load_master_drops_missing_clubs_and_future_dates(tmp_path):
    from data.store import load_master_dataframe

    df = pd.DataFrame({
        "club": ["Dr", None, "7i"],
        "carry": [250.0, 200.0, 150.0],
        "clubspeed": [110.0, 100.0, 90.0],
        "session_date": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-01"),
                         pd.Timestamp("2031-01-01")],
        "session_id": ["a", "a", "b"],
    })
    df.to_parquet(tmp_path / "s.parquet", index=False)

    out = load_master_dataframe(tmp_path)

    # None club dropped. The future-dated 7i row is kept (real shots),
    # but its bogus session_date is cleared so recency filters ignore it.
    assert sorted(out["club"]) == ["7I", "Dr"]
    assert out.loc[out["club"] == "7I", "session_date"].isna().all()


def test_load_master_normalizes_launch_monitor_club_spelling(tmp_path):
    # Reproduces real archived data: the same physical clubs recorded
    # under multiple raw spellings ("I9" vs "9I", "DR" vs "Dr", "W3" vs
    # "3W") must collapse into one canonical name on load, even for
    # Parquet files written before normalization existed.
    from data.store import load_master_dataframe

    df = pd.DataFrame({
        "club": ["I9", "9I", "DR", "Dr", "W3", "3W"],
        "carry": [140.0, 142.0, 250.0, 255.0, 210.0, 212.0],
        "clubspeed": [80.0, 81.0, 110.0, 111.0, 95.0, 96.0],
        "session_date": [pd.Timestamp("2026-01-01")] * 6,
        "session_id": ["a"] * 6,
    })
    df.to_parquet(tmp_path / "s.parquet", index=False)

    out = load_master_dataframe(tmp_path)

    assert sorted(out["club"].unique()) == ["3W", "9I", "Dr"]


def test_load_master_self_heals_session_date_from_filename(tmp_path):
    # Some sessions were archived under an older code version where
    # filename-date parsing failed and fell back to file ctime, storing
    # an imprecise session_date that doesn't match the actual play time
    # embedded in the filename. On every load, re-derive the date from
    # session_id (the original filename stem) so this self-heals without
    # needing a migration step.
    from data.store import load_master_dataframe

    stale_ctime_date = pd.Timestamp("2026-02-08 18:57:10.778033")
    df = pd.DataFrame({
        "club": ["Dr"],
        "carry": [250.0],
        "clubspeed": [110.0],
        "session_date": [stale_ctime_date],
        "session_id": ["gspro-export02-08-26-12-57-10"],
    })
    df.to_parquet(tmp_path / "s.parquet", index=False)

    out = load_master_dataframe(tmp_path)

    assert out["session_date"].iloc[0] == pd.Timestamp("2026-02-08 12:57:10")


def test_load_master_keeps_stored_date_when_session_id_isnt_a_filename(tmp_path):
    # session_id values that don't match the gspro-export filename
    # pattern (e.g. hand-crafted test fixtures) have no filename date to
    # derive, so the stored session_date must be left alone.
    from data.store import load_master_dataframe

    df = pd.DataFrame({
        "club": ["Dr"],
        "carry": [250.0],
        "clubspeed": [110.0],
        "session_date": [pd.Timestamp("2026-01-01 10:00:00")],
        "session_id": ["not-a-filename"],
    })
    df.to_parquet(tmp_path / "s.parquet", index=False)

    out = load_master_dataframe(tmp_path)

    assert out["session_date"].iloc[0] == pd.Timestamp("2026-01-01 10:00:00")


def test_load_master_keeps_rows_missing_clubspeed_when_other_files_have_it(tmp_path):
    # Live-tracked rows (see live/shot_data.py) legitimately have no club
    # speed at all — GSPro's currentRound.dat doesn't expose it. Mixing
    # them with CSV-sourced rows (which do have clubspeed) must not cause
    # the live rows to be silently dropped by a blanket dropna.
    from data.store import load_master_dataframe

    csv_sourced = pd.DataFrame({
        "club": ["Dr"],
        "carry": [250.0],
        "clubspeed": [110.0],
        "session_date": [pd.Timestamp("2026-01-01")],
        "session_id": ["a"],
    })
    csv_sourced.to_parquet(tmp_path / "csv.parquet", index=False)

    live_sourced = pd.DataFrame({
        "club": ["Club24"],
        "carry": [200.0],
        "session_date": [pd.Timestamp("2026-01-02")],
        "session_id": ["live-01-02-26-10-00-00-practice"],
        "round_type": ["practice"],
    })
    live_sourced.to_parquet(tmp_path / "live.parquet", index=False)

    out = load_master_dataframe(tmp_path)

    assert len(out) == 2
    assert set(out["club"]) == {"Dr", "Club24"}


def test_load_master_still_drops_rows_missing_carry(tmp_path):
    from data.store import load_master_dataframe

    df = pd.DataFrame({
        "club": ["Dr", "7I"],
        "carry": [250.0, None],
        "session_date": [pd.Timestamp("2026-01-01")] * 2,
        "session_id": ["a", "a"],
    })
    df.to_parquet(tmp_path / "s.parquet", index=False)

    out = load_master_dataframe(tmp_path)

    assert list(out["club"]) == ["Dr"]


def test_load_master_self_heals_club_from_club_index(tmp_path):
    # Filling in a real CLUB_INDEX_MAP entry after the fact should update
    # already-archived live rounds on the very next load, without needing
    # to re-ingest anything.
    from data.store import load_master_dataframe
    import config

    df = pd.DataFrame({
        "club": ["Club24"],
        "club_index": [24],
        "carry": [250.0],
        "session_date": [pd.Timestamp("2026-01-01")],
        "session_id": ["live-01-01-26-10-00-00-practice"],
    })
    df.to_parquet(tmp_path / "live.parquet", index=False)

    original = dict(config.CLUB_INDEX_MAP)
    try:
        config.CLUB_INDEX_MAP[24] = "Dr"
        out = load_master_dataframe(tmp_path)
        assert out["club"].iloc[0] == "Dr"
    finally:
        config.CLUB_INDEX_MAP.clear()
        config.CLUB_INDEX_MAP.update(original)


def test_load_master_defaults_missing_round_type_to_practice(tmp_path):
    from data.store import load_master_dataframe

    df = pd.DataFrame({
        "club": ["Dr"],
        "carry": [250.0],
        "clubspeed": [110.0],
        "session_date": [pd.Timestamp("2026-01-01")],
        "session_id": ["a"],
    })
    df.to_parquet(tmp_path / "s.parquet", index=False)

    out = load_master_dataframe(tmp_path)

    assert out["round_type"].iloc[0] == "practice"


def test_load_master_preserves_on_course_round_type(tmp_path):
    from data.store import load_master_dataframe

    df = pd.DataFrame({
        "club": ["Dr"],
        "carry": [250.0],
        "session_date": [pd.Timestamp("2026-01-01")],
        "session_id": ["live-01-01-26-10-00-00-on_course"],
        "round_type": ["on_course"],
    })
    df.to_parquet(tmp_path / "live.parquet", index=False)

    out = load_master_dataframe(tmp_path)

    assert out["round_type"].iloc[0] == "on_course"
