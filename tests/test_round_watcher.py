import json
import time

import pandas as pd

from live.round_watcher import LiveRoundWatcher


def _shot(shot_id, round_id=-1, player="Practice", **extra):
    shot = {
        "ShotID": shot_id,
        "RoundID": round_id,
        "PlayerName": player,
        "Hole": 0,
        "HolePar": 4,
        "ClubIndex": 24,
        "BallSpeed": 70.0,
        "TotalDistance": 80.0,
        "DistanceToPin": 300.0,
        "GhostData": {"sp": 70.0, "el": 20.0, "az": 1.0, "ts": 8000.0, "sa": 2.0, "cy": 75.0},
    }
    shot.update(extra)
    return shot


def _write(path, shots):
    path.write_text(json.dumps(shots))


def _make_watcher(tmp_path, **kwargs):
    round_file = tmp_path / "currentRound.dat"
    data_dir = tmp_path / "parquet_data"
    raw_dir = tmp_path / "live_rounds_raw"
    data_dir.mkdir(exist_ok=True)
    raw_dir.mkdir(exist_ok=True)
    new_shots = []
    archived = []
    watcher = LiveRoundWatcher(
        round_file=round_file,
        data_dir=data_dir,
        raw_archive_dir=raw_dir,
        on_new_shot=new_shots.append,
        on_round_archived=archived.append,
        **kwargs,
    )
    return watcher, round_file, data_dir, raw_dir, new_shots, archived


def test_missing_file_is_a_silent_noop(tmp_path):
    watcher, round_file, *_ , new_shots, archived = _make_watcher(tmp_path)
    watcher.check_now()
    assert new_shots == []
    assert archived == []


def test_first_poll_baselines_without_firing_new_shot(tmp_path):
    watcher, round_file, *_ , new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a"), _shot("b")])

    watcher.check_now()

    # Shots already present when the watcher starts count toward the
    # eventual archive but aren't "new" — they were already there.
    assert new_shots == []
    assert archived == []
    assert len(watcher._buffer) == 2


def test_appended_shot_fires_on_new_shot(tmp_path):
    watcher, round_file, *_ , new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a")])
    watcher.check_now()

    time.sleep(0.01)
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()

    assert len(new_shots) == 1
    assert new_shots[0]["shot_id"] == "b"
    assert archived == []


def test_unchanged_file_does_not_reprocess(tmp_path):
    watcher, round_file, *_ , new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a")])
    watcher.check_now()
    watcher.check_now()
    watcher.check_now()

    assert new_shots == []  # baseline shot never re-fires


def test_first_shot_id_change_finalizes_previous_round(tmp_path):
    watcher, round_file, data_dir, raw_dir, new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()

    time.sleep(0.01)
    # A completely different session: the log was reset (a fresh first
    # ShotID), even though RoundID/PlayerName are identical to before —
    # this is exactly the practice-range case (RoundID always -1).
    _write(round_file, [_shot("c"), _shot("d")])
    watcher.check_now()

    assert len(archived) == 1
    assert archived[0]["shot_count"] == 2
    assert archived[0]["parquet_path"].exists()

    # Every shot in the fresh session is treated as new for the live panel.
    assert {s["shot_id"] for s in new_shots} == {"c", "d"}


def test_on_course_round_id_tags_archive_as_on_course(tmp_path):
    watcher, round_file, *_ , new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a", round_id=555, player="Tyler")])
    watcher.check_now()
    watcher.finalize_now()

    assert len(archived) == 1
    assert archived[0]["round_type"] == "on_course"


def test_finalize_now_flushes_in_progress_buffer(tmp_path):
    watcher, round_file, *_ , new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()

    assert archived == []  # nothing archived yet — round still "in progress"

    watcher.finalize_now()

    assert len(archived) == 1
    assert archived[0]["shot_count"] == 2
    # Buffer is cleared after flushing so a later real finalize doesn't
    # re-archive the same shots.
    assert watcher._buffer == []


def test_finalize_now_returns_summary_or_none(tmp_path):
    # The explicit "End Round" UI action relies on this return value to tell
    # the user whether anything was actually archived.
    watcher, round_file, *_ , new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()

    info = watcher.finalize_now()
    assert info is not None and info["shot_count"] == 2

    # Nothing new buffered -> a second call reports "nothing to do".
    assert watcher.finalize_now() is None


def test_explicit_finalize_then_new_round_does_not_double_archive(tmp_path):
    # "End Round" (explicit finalize) mid-session, then GSPro starts a fresh
    # round: the ended round must archive exactly once, and the new round
    # archives on its own — never the old one a second time.
    watcher, round_file, data_dir, raw_dir, new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()

    assert watcher.finalize_now()["shot_count"] == 2  # explicit End Round
    assert len(archived) == 1
    assert watcher.finalize_now() is None  # e.g. later app-shutdown flush: no-op
    assert len(archived) == 1

    time.sleep(0.01)
    _write(round_file, [_shot("c"), _shot("d")])  # fresh first ShotID => new round
    watcher.check_now()
    watcher.finalize_now()

    assert len(archived) == 2
    assert archived[1]["shot_count"] == 2
    assert {s["shot_id"] for s in new_shots} == {"c", "d"}


def test_restarting_watcher_does_not_rearchive_unchanged_stale_round(tmp_path):
    # Simulates: app closes (archiving whatever was buffered), then the app
    # is relaunched later while GSPro is idle and currentRound.dat hasn't
    # been touched since. A brand-new LiveRoundWatcher instance (blank
    # in-memory state, same on-disk dirs) must not re-archive that same
    # file as a second, duplicate session.
    watcher, round_file, data_dir, raw_dir, new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()
    watcher.finalize_now()
    assert len(archived) == 1

    # New watcher instance, same round_file/data_dir/raw_dir — the file's
    # mtime is unchanged (GSPro never touched it again).
    watcher2, *_, archived2 = _make_watcher(tmp_path)
    watcher2.check_now()
    watcher2.finalize_now()

    assert archived2 == []


def test_restarting_watcher_still_archives_if_file_changed_since(tmp_path):
    # If GSPro *did* append a shot (or start a new round) while the app was
    # closed, the file's mtime moves — a restarted watcher must still pick
    # that up and archive it normally.
    watcher, round_file, data_dir, raw_dir, new_shots, archived = _make_watcher(tmp_path)
    _write(round_file, [_shot("a")])
    watcher.check_now()
    watcher.finalize_now()
    assert len(archived) == 1

    time.sleep(0.01)
    _write(round_file, [_shot("a"), _shot("b")])

    watcher2, *_ , archived2 = _make_watcher(tmp_path)
    watcher2.check_now()
    watcher2.finalize_now()

    assert len(archived2) == 1
    assert archived2[0]["shot_count"] == 2


def test_malformed_json_is_ignored_until_next_valid_poll(tmp_path):
    watcher, round_file, *_ , new_shots, archived = _make_watcher(tmp_path)
    round_file.write_text("{not valid json")
    watcher.check_now()  # must not raise

    assert new_shots == []
    assert archived == []


# ---------------------------------------------------------------------------
# Club-data backfill (the GSPro.db write race the fast poll interval exposes).
# ---------------------------------------------------------------------------
class _LateLookup:
    """A ClubDataLookup stand-in that has no data for the first ``misses``
    calls, mimicking GSPro.db not having written the DrivingRangeShot row yet."""

    def __init__(self, misses, payload=None):
        self.misses = misses
        self.payload = payload or {"clubspeed": 95.0, "smashfactor": 1.42, "club": "7I"}
        self.calls = 0

    def reset(self, misses=None):
        """Zero the call counter after baselining, so a test can measure only the
        lookups it cares about. Baselining consumes one lookup per shot already in
        currentRound.dat — see check_now's first-observation branch."""
        self.calls = 0
        if misses is not None:
            self.misses = misses

    def lookup(self, ball_speed, carry):
        self.calls += 1
        if self.calls <= self.misses:
            return {}
        return dict(self.payload)


def test_shot_arriving_without_club_data_is_backfilled(tmp_path):
    lookup = _LateLookup(misses=1)
    updated = []
    watcher, round_file, *_, new_shots, _archived = _make_watcher(
        tmp_path, club_lookup=lookup, club_data_retries=3,
        club_data_retry_interval=0.0, on_shot_updated=updated.append)

    _write(round_file, [_shot("a")])
    watcher.check_now()                      # baseline
    lookup.reset()                           # ignore the baseline shot's lookup
    time.sleep(0.01)                         # distinct mtime, or the poll no-ops
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()                      # shot b arrives, lookup misses

    assert len(new_shots) == 1
    assert new_shots[0].get("clubspeed") is None, "should surface immediately, club data pending"
    assert updated == []

    watcher._retry_club_data()               # GSPro.db has caught up

    assert len(updated) == 1
    # Patched in place: the dict the UI already holds is the one that changed.
    assert updated[0] is new_shots[0]
    assert new_shots[0]["clubspeed"] == 95.0
    assert new_shots[0]["club"] == "7I"
    # The real club name from the DB must clear club_index, or a later reload
    # re-resolves the club back to whatever ClubIndex said.
    assert new_shots[0]["club_index"] is None


def test_backfill_gives_up_after_the_retry_budget(tmp_path):
    lookup = _LateLookup(misses=99)          # never resolves (e.g. on-course shot)
    updated = []
    watcher, round_file, *_, new_shots, _archived = _make_watcher(
        tmp_path, club_lookup=lookup, club_data_retries=2,
        club_data_retry_interval=0.0, on_shot_updated=updated.append)

    _write(round_file, [_shot("a")])
    watcher.check_now()
    lookup.reset()                           # ignore the baseline shot's lookup
    time.sleep(0.01)                         # distinct mtime, or the poll no-ops
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()

    for _ in range(5):
        watcher._retry_club_data()

    assert updated == []
    assert watcher._pending_club_data == [], "must stop retrying, not queue forever"
    assert lookup.calls == 1 + 2, "one live lookup plus exactly the retry budget"


def test_shot_that_already_has_club_data_is_never_queued(tmp_path):
    lookup = _LateLookup(misses=0)           # resolves on the first call
    watcher, round_file, *_, new_shots, _archived = _make_watcher(
        tmp_path, club_lookup=lookup, club_data_retries=3,
        club_data_retry_interval=0.0)

    _write(round_file, [_shot("a")])
    watcher.check_now()
    lookup.reset()                           # ignore the baseline shot's lookup
    time.sleep(0.01)                         # distinct mtime, or the poll no-ops
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()

    assert new_shots[0]["clubspeed"] == 95.0
    assert watcher._pending_club_data == []


def test_retries_default_off_so_existing_callers_are_unchanged(tmp_path):
    lookup = _LateLookup(misses=1)
    watcher, round_file, *_, new_shots, _archived = _make_watcher(
        tmp_path, club_lookup=lookup)

    _write(round_file, [_shot("a")])
    watcher.check_now()
    lookup.reset()                           # ignore the baseline shot's lookup
    time.sleep(0.01)                         # distinct mtime, or the poll no-ops
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()

    assert watcher._pending_club_data == []
    watcher._retry_club_data()
    assert lookup.calls == 1


class _ClearingLookup:
    """A ClubDataLookup that answers while the round is live and then goes empty,
    the way GSPro clears DrivingRangeShot when a range session ends."""

    def __init__(self):
        self.cleared = False

    def lookup(self, ball_speed, carry):
        if self.cleared:
            return {}
        return {"clubspeed": 95.0, "smashfactor": 1.42, "aoa": -2.1, "club": "7I"}


def test_club_data_survives_gspro_clearing_the_table_before_archive(tmp_path):
    """The regression this guards cost 6 of 9 real practice sessions their club
    speed: archive_round re-derived every row with a fresh GSPro.db read, and by
    then GSPro had wiped the range shots — even though the lookup had already
    succeeded during play."""
    lookup = _ClearingLookup()
    watcher, round_file, data_dir, *_ = _make_watcher(tmp_path, club_lookup=lookup)

    _write(round_file, [_shot("a")])
    watcher.check_now()                      # baseline (shot a is buffered)
    time.sleep(0.01)
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()                      # shot b arrives, club data resolves

    lookup.cleared = True                    # GSPro tears down the range session
    info = watcher.finalize_now()
    assert info is not None

    df = pd.read_parquet(info["parquet_path"])
    assert "clubspeed" in df.columns, "club speed column vanished at archive time"
    assert df["clubspeed"].notna().all()
    assert (df["clubspeed"] == 95.0).all()
    assert (df["club"] == "7I").all()
    # The DB's club name is authoritative, so the index must be dropped or
    # load_master_dataframe re-resolves the club back to the ClubIndex one.
    assert df["club_index"].isna().all()


def test_archive_keeps_club_data_even_with_no_ui_listener(tmp_path):
    """Club data is captured on the poll thread regardless of whether anything is
    listening for live shots — the archive needs it either way."""
    lookup = _ClearingLookup()
    round_file = tmp_path / "currentRound.dat"
    data_dir = tmp_path / "parquet_data"
    raw_dir = tmp_path / "live_rounds_raw"
    data_dir.mkdir()
    raw_dir.mkdir()
    watcher = LiveRoundWatcher(
        round_file=round_file, data_dir=data_dir, raw_archive_dir=raw_dir,
        on_new_shot=None, club_lookup=lookup)

    _write(round_file, [_shot("a")])
    watcher.check_now()
    time.sleep(0.01)
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()

    lookup.cleared = True
    info = watcher.finalize_now()
    df = pd.read_parquet(info["parquet_path"])
    assert (df["clubspeed"] == 95.0).all()


def test_a_new_round_does_not_inherit_the_previous_rounds_club_data(tmp_path):
    lookup = _ClearingLookup()
    watcher, round_file, *_ = _make_watcher(tmp_path, club_lookup=lookup)

    _write(round_file, [_shot("a")])
    watcher.check_now()
    time.sleep(0.01)
    _write(round_file, [_shot("a"), _shot("b")])
    watcher.check_now()
    assert watcher._club_data_by_shot

    time.sleep(0.01)
    _write(round_file, [_shot("z")])         # GSPro reset -> new session
    watcher.check_now()

    assert set(watcher._club_data_by_shot) == {"z"}, "stale shots carried over"
