import pandas as pd

from data.reconcile import find_matching_live_round, merge_csv_into_live_round


def _live_round_df(session_id="live-01-01-26-10-00-00-practice", round_type="practice"):
    return pd.DataFrame({
        "club": ["Club24", "Club24"],
        "club_index": [24, 24],
        "ballspeed": [110.0, 108.5],
        "carry": [250.0, 245.0],
        "totaldistance": [265.0, 260.0],
        "offline": [3.2, -1.1],
        "backspin": [2600.0, 2500.0],
        "vla": [14.0, 13.5],
        "hole": [1, 1],
        "holepar": [4, 4],
        "distancetopin": [400.0, 400.0],
        "shot_id": ["shot-a", "shot-b"],
        "session_id": [session_id] * 2,
        "session_date": [pd.Timestamp("2026-01-01 10:00:00")] * 2,
        "round_type": [round_type, round_type],
    })


def _matching_csv_df():
    # Same physical shots — ballspeed/carry line up within rounding, but
    # now with clubspeed/smashfactor the live tracker never has.
    return pd.DataFrame({
        "club": ["Dr", "Dr"],
        "ballspeed": [110.2, 108.3],
        "carry": [250.4, 244.7],
        "totaldistance": [266.0, 261.0],
        "offline": [3.0, -1.0],
        "clubspeed": [98.1, 97.4],
        "smashfactor": [1.48, 1.47],
    })


CSV_DATE = pd.Timestamp("2026-01-01 12:00:00")


def test_find_matching_live_round_returns_none_when_no_candidates(tmp_path):
    assert find_matching_live_round(_matching_csv_df(), tmp_path, csv_date=CSV_DATE) is None


def test_find_matching_live_round_returns_none_for_empty_csv(tmp_path):
    _live_round_df().to_parquet(tmp_path / "live-01-01-26-10-00-00-practice.parquet", index=False)
    assert find_matching_live_round(pd.DataFrame(), tmp_path, csv_date=CSV_DATE) is None


def test_find_matching_live_round_ignores_values_outside_tolerance(tmp_path):
    _live_round_df().to_parquet(tmp_path / "live-01-01-26-10-00-00-practice.parquet", index=False)
    csv_df = _matching_csv_df()
    csv_df["ballspeed"] = [200.0, 5.0]  # nowhere close to the live round
    assert find_matching_live_round(csv_df, tmp_path, csv_date=CSV_DATE) is None


def test_find_matching_live_round_finds_match_within_tolerance(tmp_path):
    path = tmp_path / "live-01-01-26-10-00-00-practice.parquet"
    _live_round_df().to_parquet(path, index=False)

    match = find_matching_live_round(_matching_csv_df(), tmp_path, csv_date=CSV_DATE)

    assert match == path


def test_find_matching_live_round_ignores_non_live_parquet_files(tmp_path):
    # A regular CSV-sourced session shouldn't be a merge candidate at all —
    # only files with the "live-" prefix are.
    csv_shaped = pd.DataFrame({
        "club": ["Dr", "Dr"], "ballspeed": [110.0, 108.5], "carry": [250.0, 245.0],
    })
    csv_shaped.to_parquet(tmp_path / "gspro-export01-01-26-10-00-00.parquet", index=False)

    assert find_matching_live_round(_matching_csv_df(), tmp_path, csv_date=CSV_DATE) is None


def test_find_matching_live_round_still_matches_when_live_round_missed_a_shot(tmp_path):
    # The live tracker dropped the middle shot (e.g. a brief polling gap),
    # so the live round has only 2 shots but the CSV — the complete,
    # authoritative record — has 3. This must still match: shot count is
    # no longer an exact-equality gate.
    path = tmp_path / "live-01-01-26-10-00-00-practice.parquet"
    live_df = pd.DataFrame({
        "club": ["Club24", "Club24"],
        "club_index": [24, 24],
        "ballspeed": [110.0, 95.0],   # missing the 108.5 shot from the CSV
        "carry": [250.0, 170.0],
        "hole": [1, 1],
        "holepar": [4, 4],
        "distancetopin": [400.0, 400.0],
        "shot_id": ["shot-a", "shot-c"],
        "session_id": ["live-01-01-26-10-00-00-practice"] * 2,
        "session_date": [pd.Timestamp("2026-01-01 10:00:00")] * 2,
        "round_type": ["practice", "practice"],
    })
    live_df.to_parquet(path, index=False)

    csv_df = pd.DataFrame({
        "club": ["Dr", "7I", "PW"],
        "ballspeed": [110.2, 108.3, 95.1],
        "carry": [250.4, 244.7, 170.2],
        "clubspeed": [98.1, 97.4, 80.0],
        "smashfactor": [1.48, 1.47, 1.20],
    })

    match = find_matching_live_round(csv_df, tmp_path, csv_date=CSV_DATE)
    assert match == path


def test_find_matching_live_round_rejects_live_shot_with_no_csv_match(tmp_path):
    # Every live shot must find a match — if one doesn't (not just
    # "missing from the CSV" but numerically absent), this isn't the same
    # round, regardless of how many other shots line up.
    path = tmp_path / "live-01-01-26-10-00-00-practice.parquet"
    live_df = pd.DataFrame({
        "club": ["Club24", "Club24"],
        "ballspeed": [110.0, 999.0],  # second shot has no CSV counterpart
        "carry": [250.0, 999.0],
        "session_id": ["live-01-01-26-10-00-00-practice"] * 2,
        "session_date": [pd.Timestamp("2026-01-01 10:00:00")] * 2,
        "round_type": ["practice", "practice"],
    })
    live_df.to_parquet(path, index=False)

    csv_df = pd.DataFrame({
        "club": ["Dr", "7I"],
        "ballspeed": [110.2, 108.3],
        "carry": [250.4, 244.7],
        "clubspeed": [98.1, 97.4],
        "smashfactor": [1.48, 1.47],
    })

    assert find_matching_live_round(csv_df, tmp_path, csv_date=CSV_DATE) is None


def test_find_matching_live_round_excludes_on_course_rounds(tmp_path):
    # GSPro's CSV export only ever comes from the Practice Range shot
    # list, so an on-course live round can never be what a CSV covers,
    # even if the numbers happen to line up.
    _live_round_df(
        session_id="live-01-01-26-10-00-00-on_course", round_type="on_course",
    ).to_parquet(tmp_path / "live-01-01-26-10-00-00-on_course.parquet", index=False)

    assert find_matching_live_round(_matching_csv_df(), tmp_path, csv_date=CSV_DATE) is None


def test_find_matching_live_round_excludes_different_calendar_day(tmp_path):
    # Numerically similar values from an unrelated round on a different
    # day must not match just because the shot data happens to be close.
    _live_round_df().to_parquet(tmp_path / "live-01-01-26-10-00-00-practice.parquet", index=False)

    different_day = pd.Timestamp("2026-03-15 12:00:00")
    assert find_matching_live_round(_matching_csv_df(), tmp_path, csv_date=different_day) is None


def test_find_matching_live_round_matches_without_csv_date_provided(tmp_path):
    # csv_date is optional — if the caller doesn't have one, fall back to
    # matching on round-type + shot alignment alone.
    path = tmp_path / "live-01-01-26-10-00-00-practice.parquet"
    _live_round_df().to_parquet(path, index=False)

    assert find_matching_live_round(_matching_csv_df(), tmp_path) == path


def test_merge_overwrites_measurable_columns_with_csv_data(tmp_path):
    path = tmp_path / "live-01-01-26-10-00-00-practice.parquet"
    _live_round_df().to_parquet(path, index=False)

    merge_csv_into_live_round(_matching_csv_df(), path)

    merged = pd.read_parquet(path)
    assert list(merged["club"]) == ["Dr", "Dr"]  # overwritten from CSV
    assert list(merged["ballspeed"]) == [110.2, 108.3]
    assert list(merged["clubspeed"]) == [98.1, 97.4]  # new column, added
    assert list(merged["smashfactor"]) == [1.48, 1.47]


def test_merge_preserves_live_only_context_columns(tmp_path):
    path = tmp_path / "live-01-01-26-10-00-00-practice.parquet"
    _live_round_df().to_parquet(path, index=False)

    merge_csv_into_live_round(_matching_csv_df(), path)

    merged = pd.read_parquet(path)
    # None of these exist in the CSV — they must survive the merge intact.
    assert list(merged["hole"]) == [1, 1]
    assert list(merged["holepar"]) == [4, 4]
    assert list(merged["distancetopin"]) == [400.0, 400.0]
    assert list(merged["shot_id"]) == ["shot-a", "shot-b"]
    assert list(merged["round_type"]) == ["practice", "practice"]
    assert merged["session_id"].iloc[0] == "live-01-01-26-10-00-00-practice"
    assert list(merged["club_index"]) == [24, 24]


def test_merge_keeps_csv_only_shot_the_live_tracker_missed(tmp_path):
    # Merge output is CSV-row-count-based: a shot the live tracker missed
    # still shows up in the merged data (with the CSV's measurements), just
    # without live-only context (nothing to pull it from).
    path = tmp_path / "live-01-01-26-10-00-00-practice.parquet"
    live_df = pd.DataFrame({
        "club": ["Club24", "Club24"],
        "club_index": [24, 24],
        "ballspeed": [110.0, 95.0],
        "carry": [250.0, 170.0],
        "hole": [1, 1],
        "holepar": [4, 4],
        "distancetopin": [400.0, 400.0],
        "shot_id": ["shot-a", "shot-c"],
        "session_id": ["live-01-01-26-10-00-00-practice"] * 2,
        "session_date": [pd.Timestamp("2026-01-01 10:00:00")] * 2,
        "round_type": ["practice", "practice"],
    })
    live_df.to_parquet(path, index=False)

    csv_df = pd.DataFrame({
        "club": ["Dr", "7I", "PW"],
        "ballspeed": [110.2, 108.3, 95.1],
        "carry": [250.4, 244.7, 170.2],
        "clubspeed": [98.1, 97.4, 80.0],
        "smashfactor": [1.48, 1.47, 1.20],
    })

    overwritten = merge_csv_into_live_round(csv_df, path)
    assert overwritten == 3

    merged = pd.read_parquet(path)
    assert len(merged) == 3
    # The middle CSV shot (7I) has no live-tracked counterpart.
    assert merged["shot_id"].iloc[0] == "shot-a"
    assert pd.isna(merged["shot_id"].iloc[1])
    assert merged["shot_id"].iloc[2] == "shot-c"
    # Session-level metadata still applies uniformly to every row.
    assert list(merged["session_id"]) == ["live-01-01-26-10-00-00-practice"] * 3
    assert list(merged["round_type"]) == ["practice", "practice", "practice"]
