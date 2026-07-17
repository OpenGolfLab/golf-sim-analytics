"""The Community dashboard's rich hover card.

Renders the chart against a fixture payload matching the extended
docs/COMMUNITY_API.md contract and asserts the per-point tooltip text — that it
shows club / carry / total / ball / monitor / date / name when present, and
degrades to just club + carry when the descriptive fields are absent.

The tooltip text is produced by the `_tooltip` closure inside
community.render, so the test captures it via the seam every chart uses:
_shared.attach_hover_tooltip. Patching that lets us grab the real closure and
the exact rows it will be called with, without needing a live mouse.
"""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

import config
import community as community_client
from ui.charts import community as community_chart


def _rows_from_payload(payload):
    """Run the payload through the real read client (schema→column mapping +
    metadata normalization), exactly as the app would before rendering."""
    import json
    from unittest import mock

    class _Resp:
        def read(self): return json.dumps(payload).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False

    with mock.patch("urllib.request.urlopen", return_value=_Resp()):
        return community_client.fetch_community_shots("https://api.example.com")


def _render_and_capture(df):
    """Render the Community chart and return {club_of_first_point: tooltip_text}
    for every point, by intercepting attach_hover_tooltip."""
    captured = {}

    def _spy(fig, sc, pts, tooltip_fn, font_scale, **kw):
        for _i, row in pts.reset_index(drop=True).iterrows():
            captured[str(row["club"]) + f"#{_i}"] = tooltip_fn(row)

    orig = community_chart.attach_hover_tooltip
    community_chart.attach_hover_tooltip = _spy
    try:
        fig = plt.figure(figsize=(10, 6))
        community_chart.render(fig, df, {}, 12, config, community_status="ok",
                               units="Yards")
        plt.close(fig)
    finally:
        community_chart.attach_hover_tooltip = orig
    return captured


def test_rich_card_shows_every_present_field():
    df = _rows_from_payload({"points": [{
        "club": "7I", "n": 41, "carry": 153.2, "offline": 1.1,
        "ball_speed": 115.4, "ball_model": "Pro V1", "launch_monitor": "Trackman",
        "contributed": "2026-07-15", "display_name": "SteadyFade-3fa2",
    }]})
    card = next(iter(_render_and_capture(df).values()))

    assert "7I" in card and "SteadyFade-3fa2" in card
    # Values are medians now — the labels say so.
    assert "Median carry: 153 yds" in card
    assert "Median offline: +1.1 yds" in card
    assert "Ball speed: 115 mph" in card
    assert "From 41 shots" in card
    assert "Ball: Pro V1" in card
    assert "Monitor: Trackman" in card
    assert "Contributed: 2026-07-15" in card


def test_card_degrades_when_metadata_absent():
    # A minimal point: only the required numeric fields. The card must not print
    # "None"/"nan" for the missing descriptive lines — it just omits them.
    df = _rows_from_payload({"points": [
        {"club": "Dr", "carry": 265.0, "offline": -3.0},
    ]})
    card = next(iter(_render_and_capture(df).values()))

    assert card.startswith("Dr")
    assert "Median carry: 265 yds" in card
    for absent in ("Ball:", "Monitor:", "Contributed:", "From ", "None", "nan"):
        assert absent not in card


def test_card_shows_partial_metadata():
    # Some fields present, others not — each line is independent.
    df = _rows_from_payload({"points": [{
        "club": "PW", "n": 12, "carry": 118.0, "offline": 0.4,
        "ball_model": "Chrome Soft",   # present
        # launch_monitor / contributed / display_name absent
    }]})
    card = next(iter(_render_and_capture(df).values()))

    assert "Ball: Chrome Soft" in card
    assert "From 12 shots" in card
    assert "Monitor:" not in card
    assert "Contributed:" not in card
    # No public name → the header is just the club, no trailing separator.
    assert card.splitlines()[0] == "PW"


def test_offline_state_is_untouched():
    # The graceful offline state must still render when unconfigured.
    fig = plt.figure(figsize=(10, 6))
    # Empty frame + offline status → the message path, no exception.
    community_chart.render(fig, pd.DataFrame(), {}, 12, config,
                           community_status="offline", units="Yards")
    plt.close(fig)
