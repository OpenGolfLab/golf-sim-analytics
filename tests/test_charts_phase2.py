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
