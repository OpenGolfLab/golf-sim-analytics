"""Render-path tests for Dispersion's Simple / In-Depth view modes."""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ui.charts import dispersion


class FakeVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


def _df(session="s1", n=40, seed=7):
    rng = np.random.default_rng(seed)
    clubs = ["Dr", "7I", "Pw", "3W"] * (n // 4)
    return pd.DataFrame({
        "club": clubs,
        "carry": rng.uniform(80, 280, n),
        "totaldistance": rng.uniform(90, 300, n),
        "offline": rng.uniform(-30, 30, n),
        "peakheight": rng.uniform(15, 55, n),
        "vla": rng.uniform(8, 30, n),
        "decent": rng.uniform(30, 55, n),
        "ballspeed": rng.uniform(90, 175, n),
        "session_date": pd.Timestamp("2026-01-01"),
        "session_id": session,
    })


def _cfg(detail="In-Depth"):
    return {"color_var": FakeVar("Club"), "dist_var": FakeVar("Carry"),
            "detail_var": FakeVar(detail), "num_plots": 1}


def _render(detail):
    df = _df()
    club_colors = {c: (0.5, 0.5, 0.5, 1.0) for c in df["club"].unique()}
    fig = plt.figure(figsize=(7, 5), dpi=80, layout="constrained")
    try:
        dispersion.render(fig, df, club_colors, 12, _cfg(detail))
        fig.canvas.draw()
    finally:
        plt.close(fig)


def test_dispersion_simple_mode_renders():
    _render("Simple")


def test_dispersion_indepth_mode_renders():
    _render("In-Depth")


# --- Effort terciles + Compare bands ---

def _df_with_speed(clubs):
    n = len(clubs)
    rng = np.random.default_rng(3)
    df = pd.DataFrame({
        "club": clubs,
        "carry": rng.uniform(200, 280, n),
        "offline": rng.uniform(-30, 30, n),
        "session_date": pd.Timestamp("2026-01-01"),
        "session_id": "s1",
    })
    # speed_pct per club: an even ramp, so terciles are unambiguous.
    df["speed_pct"] = df.groupby("club").cumcount() * 2.0 + 70.0
    return df


def _render_effort(df, effort, detail="In-Depth", color="Club"):
    cfg = _cfg(detail)
    cfg["effort_var"] = FakeVar(effort)
    cfg["color_var"] = FakeVar(color)
    club_colors = {c: (0.5, 0.5, 0.5, 1.0) for c in df["club"].unique()}
    fig = plt.figure(figsize=(7, 5), dpi=80, layout="constrained")
    try:
        dispersion.render(fig, df, club_colors, 12, cfg)
        fig.canvas.draw()
    finally:
        plt.close(fig)


def test_effort_bands_are_per_club_terciles():
    df = _df_with_speed(["Dr"] * 30)
    bands = dispersion.effort_bands(df)
    counts = bands.value_counts()
    assert counts[dispersion.EFFORT_SMOOTH] == 10
    assert counts[dispersion.EFFORT_MID] == 10
    assert counts[dispersion.EFFORT_FLAT] == 10
    # The slowest shot is Smooth, the fastest is Flat out.
    assert bands[df["speed_pct"].idxmin()] == dispersion.EFFORT_SMOOTH
    assert bands[df["speed_pct"].idxmax()] == dispersion.EFFORT_FLAT


def test_effort_bands_never_empty_for_a_tight_swinger():
    # The v1.5.0 bug: a golfer whose every swing sits 93-100% of max had
    # nearly nothing under the old fixed 90% cutoff. Terciles must split
    # even that tight range three ways.
    df = _df_with_speed(["Dr"] * 30)
    df["speed_pct"] = np.linspace(93.0, 100.0, 30)
    bands = dispersion.effort_bands(df)
    assert set(bands.unique()) == {
        dispersion.EFFORT_SMOOTH, dispersion.EFFORT_MID, dispersion.EFFORT_FLAT}


def test_effort_band_filter_renders(tmp_path=None):
    _render_effort(_df_with_speed(["Dr"] * 30), dispersion.EFFORT_SMOOTH)


def test_compare_bands_renders_single_club_both_details():
    _render_effort(_df_with_speed(["Dr"] * 30), dispersion.EFFORT_COMPARE, "In-Depth")
    _render_effort(_df_with_speed(["Dr"] * 30), dispersion.EFFORT_COMPARE, "Simple")


def test_compare_bands_multi_club_shows_message_not_crash():
    _render_effort(_df_with_speed(["Dr", "7I"] * 15), dispersion.EFFORT_COMPARE)


def test_effort_without_speed_data_shows_message_not_crash():
    df = _df_with_speed(["Dr"] * 30).drop(columns=["speed_pct"])
    _render_effort(df, dispersion.EFFORT_FLAT)


# --- Rings detail mode + trend eras ---

def _df_sessions(n_sessions, per_session=12, clubs=("Dr",)):
    rng = np.random.default_rng(5)
    frames = []
    for s in range(n_sessions):
        n = per_session * len(clubs)
        frames.append(pd.DataFrame({
            "club": list(clubs) * per_session,
            "carry": rng.normal(240, 15, n),
            "offline": rng.normal(0, 12, n),
            "session_id": f"s{s}",
            "session_date": pd.Timestamp("2026-01-05") + pd.Timedelta(days=7 * s),
        }))
    return pd.concat(frames, ignore_index=True)


def test_era_groups_ring_each_session_up_to_five():
    groups = dispersion._era_groups(_df_sessions(4))
    assert len(groups) == 4
    # Oldest first, one session each.
    assert all(sub["session_id"].nunique() == 1 for _lbl, sub in groups)


def test_era_groups_pool_long_histories():
    groups = dispersion._era_groups(_df_sessions(12))
    assert len(groups) == dispersion._ERA_POOL_GROUPS
    assert all(sub["session_id"].nunique() == 3 for _lbl, sub in groups)
    # Labels carry the date span.
    assert "–" in groups[0][0]


def test_draw_ring_adds_an_ellipse():
    rng = np.random.default_rng(2)
    fig, ax = plt.subplots()
    try:
        assert dispersion._draw_ring(ax, rng.normal(0, 10, 50), rng.normal(230, 12, 50),
                                     "red")
        assert len(ax.patches) == 1
        # Too few points: no ring, no crash.
        assert not dispersion._draw_ring(ax, [1.0, 2.0], [1.0, 2.0], "red")
        assert len(ax.patches) == 1
    finally:
        plt.close(fig)


def test_rings_per_club_renders_multi_club():
    _render_effort(_df_sessions(3, clubs=("Dr", "7I")), dispersion.EFFORT_ALL,
                   detail=dispersion.DETAIL_RINGS, color=dispersion.COLOR_CLUB)


def test_trend_rings_render_single_club():
    _render_effort(_df_sessions(12), dispersion.EFFORT_ALL,
                   detail=dispersion.DETAIL_RINGS, color=dispersion.COLOR_TIMELINE)


def test_trend_rings_multi_club_shows_message_not_crash():
    _render_effort(_df_sessions(3, clubs=("Dr", "7I")), dispersion.EFFORT_ALL,
                   detail=dispersion.DETAIL_RINGS, color=dispersion.COLOR_TIMELINE)


def test_effort_rings_render_single_club():
    df = _df_sessions(3)
    df["speed_pct"] = np.linspace(85.0, 100.0, len(df))
    _render_effort(df, dispersion.EFFORT_ALL,
                   detail=dispersion.DETAIL_RINGS, color=dispersion.COLOR_EFFORT)
