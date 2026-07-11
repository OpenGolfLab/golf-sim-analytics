"""Headless smoke tests: every dashboard renderer must draw without raising,
both with plausible data and with an empty frame. Catches chart-code
regressions that unit tests on the data layer can't see.
"""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from ui.charts.registry import DASHBOARDS


class FakeVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


def _sample_df(n=40):
    rng = np.random.default_rng(7)
    clubs = ["Dr", "7I", "Pw", "3W"] * (n // 4)
    return pd.DataFrame({
        "club": clubs,
        "carry": rng.uniform(80, 280, n),
        "totaldistance": rng.uniform(90, 300, n),
        "offline": rng.uniform(-30, 30, n),
        "ballspeed": rng.uniform(90, 175, n),
        "clubspeed": rng.uniform(60, 120, n),
        "backspin": rng.uniform(1800, 9000, n),
        "vla": rng.uniform(8, 30, n),
        "decent": rng.uniform(30, 55, n),
        "peakheight": rng.uniform(15, 55, n),
        "smashfactor": rng.uniform(1.2, 1.5, n),
        "hla": rng.uniform(-6, 6, n),
        "rawspinaxis": rng.uniform(-25, 25, n),
        "session_date": pd.Timestamp("2026-01-01"),
        "session_id": "s1",
    })


def _entry(num_plots=1):
    return {
        "ind_var": FakeVar(True),
        "color_var": FakeVar("Club"), "dist_var": FakeVar("Carry"),
        "num_plots": num_plots,
    }


@pytest.mark.parametrize("dash", DASHBOARDS, ids=lambda d: d.name)
def test_every_dashboard_renders_without_error(dash):
    df = _sample_df()
    club_colors = {c: (0.5, 0.5, 0.5, 1.0) for c in df["club"].unique()}
    fig = plt.figure(figsize=(8, 6), dpi=80, layout="constrained")
    try:
        # Pass reference benchmarks so the overlay path is exercised too.
        dash.render(fig, df, club_colors, 12, _entry(),
                    benchmarks=["PGA Tour", "10 Handicap"])
        fig.canvas.draw()
    finally:
        plt.close(fig)


@pytest.mark.parametrize("dash", DASHBOARDS, ids=lambda d: d.name)
def test_every_dashboard_handles_empty_df(dash):
    df = _sample_df().iloc[0:0]
    fig = plt.figure(figsize=(6, 4), dpi=80, layout="constrained")
    try:
        dash.render(fig, df, {}, 12, _entry())
        fig.canvas.draw()
    finally:
        plt.close(fig)


@pytest.mark.parametrize("dash", DASHBOARDS, ids=lambda d: d.name)
def test_every_dashboard_renders_compact_four_up(dash):
    df = _sample_df()
    club_colors = {c: (0.5, 0.5, 0.5, 1.0) for c in df["club"].unique()}
    fig = plt.figure(figsize=(5, 3.5), dpi=80, layout="constrained")
    try:
        dash.render(fig, df, club_colors, 9, _entry(num_plots=4))
        fig.canvas.draw()
    finally:
        plt.close(fig)
