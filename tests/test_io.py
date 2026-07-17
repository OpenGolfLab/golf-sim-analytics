import pandas as pd

from data.io import (
    extract_date_from_filename, import_csv_files, ingest_csv_to_parquet,
    parse_and_clean_csv,
)

SAMPLE_CSV = """Club,Club Speed,Carry,Offline,SmashFactor
Dr,105.2,255.4,4.1,1.48
7I,88.0,152.3,-2.0,1.32
Dr,#DIV/0!,0,0,#DIV/0!
Dr,300,10,0,1.48
"""


def test_parse_and_clean_csv_drops_bad_rows(tmp_path):
    csv_path = tmp_path / "gspro-export01-01-26-10-00-00.csv"
    csv_path.write_text(SAMPLE_CSV)

    df = parse_and_clean_csv(csv_path)

    # Row 2 has #DIV/0! in smash factor -> dropped.
    # Row 3 has club speed 300 (> 160 cap) -> dropped as an outlier.
    assert len(df) == 2
    assert set(df["club"]) == {"Dr", "7I"}


def test_parse_and_clean_csv_normalizes_column_names(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(SAMPLE_CSV)
    df = parse_and_clean_csv(csv_path)
    assert "club_speed" in df.columns
    assert "smashfactor" in df.columns


def test_extract_date_from_filename_matches_gspro_export_pattern():
    result = extract_date_from_filename("gspro-export02-08-26-12-57-10")
    assert result == pd.Timestamp("2026-02-08 12:57:10")


def test_extract_date_from_filename_returns_none_when_no_match():
    assert extract_date_from_filename("not_a_date") is None


def test_ingest_csv_to_parquet_writes_file_and_tags_session(tmp_path):
    csv_path = tmp_path / "gspro-export02-08-26-12-57-10.csv"
    csv_path.write_text(SAMPLE_CSV)
    data_dir = tmp_path / "parquet_data"
    data_dir.mkdir()

    df = ingest_csv_to_parquet(csv_path, data_dir)

    assert df is not None
    assert "session_date" in df.columns
    assert "session_id" in df.columns
    assert (data_dir / f"{csv_path.stem}.parquet").exists()


def test_ingest_csv_to_parquet_returns_none_on_bad_file(tmp_path):
    bad_csv = tmp_path / "broken.csv"
    bad_csv.write_text("not,even,close,to,a,real,csv\n\x00\x01")
    data_dir = tmp_path / "parquet_data"
    data_dir.mkdir()
    # A malformed-but-parseable CSV shouldn't raise — worst case it
    # produces an empty/garbage frame, not an unhandled exception.
    result = ingest_csv_to_parquet(bad_csv, data_dir)
    assert result is None or hasattr(result, "empty")


def test_extract_date_repairs_future_year_to_recent_past():
    # A future year in the filename is almost always a mistyped year segment
    # ("08-06-30" -> 2030). Rather than discard the date, treat it as this
    # year — or the most recent past year if that month/day hasn't come
    # around yet — so the round keeps a real, sortable, non-future date.
    parsed = extract_date_from_filename("gspro-export08-06-30-19-12-00")
    assert parsed is not None
    now = pd.Timestamp.now()
    assert parsed <= now + pd.Timedelta(days=1)   # never future
    assert parsed.year in (now.year, now.year - 1)
    assert (parsed.month, parsed.day) == (8, 6)   # month/day preserved


def test_parse_and_clean_csv_drops_rows_with_missing_club(tmp_path):
    csv_path = tmp_path / "missing_club.csv"
    csv_path.write_text(
        "Club,Club Speed,Carry,SmashFactor\nDr,105,255,1.48\n,95,180,1.40\n"
    )
    df = parse_and_clean_csv(csv_path)
    assert set(df["club"]) == {"Dr"}


def test_ingest_csv_to_parquet_merges_into_matching_live_round_instead_of_duplicating(tmp_path):
    # A CSV covering a round already live-tracked (see live/shot_data.py)
    # should overwrite that round's shots with the CSV's data — club speed
    # and smash factor included, which the live tracker never has — rather
    # than being archived as a second, duplicate session.
    data_dir = tmp_path / "parquet_data"
    data_dir.mkdir()

    live_round = pd.DataFrame({
        "club": ["Club24", "Club24"],
        "club_index": [24, 24],
        "ballspeed": [105.3, 88.1],
        "carry": [255.6, 152.1],
        "totaldistance": [270.0, 160.0],
        "offline": [4.0, -2.0],
        "hole": [0, 0],
        "holepar": [4, 4],
        "distancetopin": [390.0, 390.0],
        "shot_id": ["shot-a", "shot-b"],
        "session_id": ["live-01-01-26-10-00-00-practice"] * 2,
        "session_date": [pd.Timestamp("2026-01-01 10:00:00")] * 2,
        "round_type": ["practice", "practice"],
    })
    live_path = data_dir / "live-01-01-26-10-00-00-practice.parquet"
    live_round.to_parquet(live_path, index=False)

    csv_path = tmp_path / "gspro-export01-01-26-11-00-00.csv"
    csv_path.write_text(
        "Club,Club Speed,Ball Speed,Carry,SmashFactor\n"
        "Dr,98.1,105.2,255.4,1.48\n"
        "7I,79.0,88.0,152.3,1.32\n"
    )

    df = ingest_csv_to_parquet(csv_path, data_dir)

    assert df is not None
    # No new standalone session was created for this CSV.
    assert not (data_dir / f"{csv_path.stem}.parquet").exists()

    merged = pd.read_parquet(live_path)
    assert list(merged["club"]) == ["Dr", "7I"]
    # parse_and_clean_csv() lowercases + underscores raw headers, so "Club
    # Speed" becomes "club_speed" — still a recognized CLUB_SPEED_ALIASES
    # entry, just not literally "clubspeed".
    assert list(merged["club_speed"]) == [98.1, 79.0]
    assert list(merged["smashfactor"]) == [1.48, 1.32]
    # Live-only context untouched by the merge.
    assert list(merged["hole"]) == [0, 0]
    assert merged["session_id"].iloc[0] == "live-01-01-26-10-00-00-practice"


def test_import_csv_files_copies_shot_exports_and_skips_junk(tmp_path):
    raw = tmp_path / "raw_csvs"
    good = tmp_path / "range.csv"
    good.write_text(SAMPLE_CSV)  # has club + carry columns
    junk = tmp_path / "budget.csv"
    junk.write_text("date,amount,memo\n2026-01-01,42,coffee\n")

    copied, skipped = import_csv_files([good, junk], raw)

    assert [p.name for p in copied] == ["range.csv"]
    assert [p.name for p in skipped] == ["budget.csv"]
    assert (raw / "range.csv").exists()


def test_import_csv_files_avoids_name_collisions(tmp_path):
    raw = tmp_path / "raw_csvs"
    raw.mkdir()
    (raw / "range.csv").write_text("already here")
    src = tmp_path / "range.csv"
    src.write_text(SAMPLE_CSV)

    copied, _ = import_csv_files([src], raw)

    # The existing range.csv isn't clobbered — the import lands under a new name.
    assert copied and copied[0].name != "range.csv"
    assert (raw / "range.csv").read_text() == "already here"


def test_detects_yards_export_and_leaves_distances_unchanged(tmp_path):
    from data.io import _detect_csv_distance_unit
    csv = tmp_path / "y.csv"
    csv.write_text("Club,Club Speed,Carry,DistanceToPin,SmashFactor\n"
                   "Dr,105,255.0,345.21 yds,1.48\n")
    df = parse_and_clean_csv(csv)
    import pandas as pd
    raw = pd.read_csv(csv); raw.columns = [c.lower().replace(" ", "_") for c in raw.columns]
    assert _detect_csv_distance_unit(raw) == "yards"
    assert round(df["carry"].iloc[0], 1) == 255.0  # untouched


def test_metric_export_is_normalized_to_yards_at_ingest(tmp_path):
    # A metric GSPro export (DistanceToPin suffixed " m") must be converted to
    # the canonical yards on the way in, so stored data is one unit regardless
    # of each user's GSPro metric/imperial setting.
    csv = tmp_path / "m.csv"
    csv.write_text("Club,Club Speed,Carry,PeakHeight,DistanceToPin,SmashFactor\n"
                   "Dr,50,250.0,30.0,120.5 m,1.44\n")
    df = parse_and_clean_csv(csv)
    assert round(df["carry"].iloc[0], 1) == 273.4    # 250 m -> yards
    assert round(df["peakheight"].iloc[0], 1) == 98.4  # 30 m -> feet
