"""Render-path tests for Session Comparison and Club Comparison charts."""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ui.charts import club_compare, session_compare


class FakeVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


def _df():
    rng = np.random.default_rng(5)
    rows = []
    for sid in ("s1", "s2", "s3"):
        for club in ("Dr", "7I"):
            n = 15
            rows.append(pd.DataFrame({
                "club": [club] * n,
                "session_id": [sid] * n,
                "carry": rng.normal(250 if club == "Dr" else 150, 8, n),
                "offline": rng.normal(0, 12, n),
                "ballspeed": rng.normal(150, 6, n),
                "clubspeed": rng.normal(105, 4, n),
                "vla": rng.normal(12, 1.5, n),
                "backspin": rng.normal(2600, 300, n),
                "smashfactor": rng.normal(1.45, 0.02, n),
            }))
    return pd.concat(rows, ignore_index=True)


def _render(module, config, df=None):
    df = _df() if df is None else df
    fig = plt.figure(figsize=(8, 5), dpi=80, layout="constrained")
    try:
        module.render(fig, df, {}, 12, config)
        fig.canvas.draw()
    finally:
        plt.close(fig)


# --- Session Comparison ---

def _session_cfg(club="Dr", picked=("s1", "s2")):
    labels = {f"Session {s}": s for s in ("s1", "s2", "s3")}
    svars = {lbl: FakeVar(sid in picked) for lbl, sid in labels.items()}
    return {"sc_club_var": FakeVar(club), "sc_session_vars": svars,
            "sc_session_labels": labels, "num_plots": 1}


def test_session_compare_two_sessions_renders():
    _render(session_compare, _session_cfg("Dr", ("s1", "s2")))


def test_session_compare_four_sessions_capped():
    # More than 4 selected must still render (capped at 4).
    _render(session_compare, _session_cfg("7I", ("s1", "s2", "s3")))


def test_session_compare_no_selection_shows_message():
    _render(session_compare, _session_cfg("Dr", ()))


# --- Club Comparison ---

def test_club_compare_configs_render():
    cfg = {"cc_session_id": "s1", "num_plots": 1, "cc_configs": [
        {"club": "Dr", "brand": "TSR3", "adapter": "+1 Draw", "start": 1, "end": 8},
        {"club": "Dr", "brand": "Qi10", "adapter": "Neutral", "start": 9, "end": 15},
    ]}
    _render(club_compare, cfg)


def test_club_compare_no_configs_shows_message():
    _render(club_compare, {"cc_session_id": None, "cc_configs": [], "num_plots": 1})


def test_club_compare_summary_frame_for_export():
    shots_a = [{"club": "Dr", "carry": 250 + i, "ballspeed": 168, "clubspeed": 115,
                "vla": 12, "backspin": 2500, "offline": 1} for i in range(6)]
    frames = [({"brand": "TSR3", "club": "Dr", "adapter": "+1 Draw"}, pd.DataFrame(shots_a))]
    out = club_compare.summary_frame(frames)
    assert list(out["Brand"]) == ["TSR3"]
    assert list(out["Adapter"]) == ["+1 Draw"]
    assert out["Shots"].iloc[0] == 6
    assert out["ClubSpeed"].iloc[0] == 115.0
    # smash derived from ball/club speed when no smash column present
    assert round(out["Smash"].iloc[0], 2) == round(168 / 115, 2)


def test_club_compare_config_frames_capture_mode():
    cfg = {"cc_configs": [{"club": "Dr", "brand": "A", "adapter": ""},
                          {"club": "Dr", "brand": "B", "adapter": ""}],
           "cc_capture": {0: [{"club": "Dr", "carry": 250}], 1: []}}
    frames = club_compare.config_frames(pd.DataFrame(), cfg)
    assert len(frames) == 2
    assert len(frames[0][1]) == 1 and frames[1][1].empty


def test_club_compare_configured_no_session_no_capture_starts_empty():
    # Configs set but no session chosen and nothing captured yet -> empty
    # "start hitting" state, not pre-filled with a session's shots.
    _render(club_compare, {"cc_session_id": None, "num_plots": 1,
                           "cc_configs": [{"club": "Dr", "brand": "A", "adapter": ""}],
                           "cc_capture": {}})


def test_club_compare_live_capture_renders_from_captured_shots():
    # Capture mode takes precedence over archived sessions — works even with an
    # empty master frame (no session picked yet).
    shots_a = [{"club": "Dr", "carry": 250 + i, "offline": i - 4, "ballspeed": 150,
                "vla": 12.0, "backspin": 2500} for i in range(8)]
    shots_b = [{"club": "Dr", "carry": 258 + i, "offline": i - 3, "ballspeed": 155,
                "vla": 12.5, "backspin": 2600} for i in range(9)]
    cfg = {"num_plots": 1,
           "cc_configs": [{"club": "Dr", "brand": "A", "adapter": "+1"},
                          {"club": "Dr", "brand": "B", "adapter": "neutral"}],
           "cc_capture": {0: shots_a, 1: shots_b}}
    _render(club_compare, cfg, df=_df().iloc[0:0])


def test_club_compare_range_beyond_data_is_safe():
    cfg = {"cc_session_id": "s1", "num_plots": 1, "cc_configs": [
        {"club": "Dr", "brand": "A", "adapter": "", "start": 1, "end": 999},
    ]}
    _render(club_compare, cfg)
