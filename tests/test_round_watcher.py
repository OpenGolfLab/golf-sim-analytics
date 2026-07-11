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
