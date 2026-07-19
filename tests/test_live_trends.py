import numpy as np
import pandas as pd

from ui.charts.live_trends import active_club, compute_trends


def _shot(club="Dr", carry=250.0, offline=5.0, **kw):
    return {"club": club, "carry": carry, "offline": offline, **kw}


def _session(sid, date, club="Dr", carries=(240, 245, 250), offlines=None):
    offlines = offlines or tuple(np.linspace(-8, 8, len(carries)))
    return pd.DataFrame({
        "session_id": sid,
        "session_date": pd.Timestamp(date),
        "club": club,
        "carry": list(carries),
        "offline": list(offlines),
    })


def test_active_club_is_latest_swing():
    shots = [_shot("7I"), _shot("Dr")]
    assert active_club(shots) == "Dr"


def test_active_club_skips_putts_and_penalty_records():
    shots = [
        _shot("Dr"),
        _shot("Putter"),                 # copied ball data, not a swing
        _shot("Lw", shot_result=2),      # water-penalty phantom record
    ]
    assert active_club(shots) == "Dr"


def test_active_club_none_without_swings():
    assert active_club([]) is None
    assert active_club([_shot("Putter")]) is None


def test_compute_trends_needs_three_live_shots():
    t = compute_trends([_shot(), _shot()], pd.DataFrame())
    assert t["club"] == "Dr" and t["shots"] == 2
    assert t["carry"] is None and t["spread"] is None


def test_compute_trends_deltas_vs_last_and_last3():
    history = pd.concat([
        _session("s1", "2026-07-01", carries=(230, 232, 234)),  # oldest
        _session("s2", "2026-07-05", carries=(238, 240, 242)),
        _session("s3", "2026-07-10", carries=(244, 246, 248)),  # most recent
    ], ignore_index=True)
    live = [_shot(carry=c, offline=o) for c, o in
            zip((250, 252, 254), (-3, 0, 3))]

    t = compute_trends(live, history)
    assert t["carry"] == 252.0
    # vs last: pooled median of s3 = 246
    assert t["vs_last"]["sessions"] == 1
    assert t["vs_last"]["carry"] == 252.0 - 246.0
    # vs last 3: pooled median of all nine baseline carries = 240
    assert t["vs_last3"]["sessions"] == 3
    assert t["vs_last3"]["carry"] == 252.0 - 240.0
    # spread deltas exist and are finite
    assert np.isfinite(t["vs_last"]["spread"])
    assert np.isfinite(t["vs_last3"]["spread"])


def test_compute_trends_first_session_with_club_has_no_baseline():
    live = [_shot("3W", carry=c) for c in (210, 212, 214)]
    history = _session("s1", "2026-07-01", club="Dr")  # different club only
    t = compute_trends(live, history)
    assert t["carry"] == 212.0
    assert t["vs_last"]["sessions"] == 0
    assert t["vs_last"]["carry"] is None
    assert t["vs_last3"]["carry"] is None


def test_compute_trends_ignores_thin_baseline_sessions():
    # A prior session with only 2 shots of the club doesn't qualify as a
    # baseline (MIN_BASELINE_SHOTS), so the one before it is "last".
    history = pd.concat([
        _session("full", "2026-07-01", carries=(240, 242, 244)),
        _session("thin", "2026-07-10", carries=(300, 300)),
    ], ignore_index=True)
    live = [_shot(carry=c) for c in (250, 252, 254)]
    t = compute_trends(live, history)
    assert t["vs_last"]["carry"] == 252.0 - 242.0


def test_compute_trends_only_counts_the_active_club():
    live = ([_shot("7I", carry=c) for c in (150, 152, 154)]
            + [_shot("Dr", carry=280)])
    t = compute_trends(live, pd.DataFrame(), club="7I")
    assert t["club"] == "7I"
    assert t["shots"] == 3
    assert t["carry"] == 152.0
