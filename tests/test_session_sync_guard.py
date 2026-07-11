"""Regression: _sc_sync_sessions must not touch the Session Comparison
dropdown widget once its panel has been destroyed (no live "canvas" key).

Toggling that panel off left a stale (destroyed) dropdown reference on the
entry; the next build_grid called into it and raised a TclError that aborted
the whole layout and cascaded into every later rebuild — read by the user as
the app "crashing" and needing a reload.
"""
import tkinter as tk

import pandas as pd
import pytest

from ui.app_window import SimAnalyticsApp
from ui.charts.session_compare import NAME as SC_NAME


class _Stub:
    # Borrow just the two methods under test; no Tk root / real app needed.
    _sc_sync_sessions = SimAnalyticsApp._sc_sync_sessions
    _session_options = SimAnalyticsApp._session_options


class _BoomDropdown:
    """Stands in for a destroyed CTk widget: touching it raises, like a real
    dead widget's TclError."""
    def refresh_options(self):
        raise AssertionError("touched a destroyed Session Comparison dropdown")


def _stub_with(entry):
    s = _Stub()
    s.master_df = pd.DataFrame({
        "session_id": ["a"], "session_date": [pd.Timestamp("2026-07-01")],
    })
    s.plot_state = {SC_NAME: entry}
    return s


def test_sync_skips_when_panel_destroyed():
    # Panel toggled off: "canvas" gone, but stale sc_session_vars/dd remain.
    s = _stub_with({"sc_session_vars": {}, "sc_session_dd": _BoomDropdown()})
    s._sc_sync_sessions()  # must return early, never call into the dead widget


def test_sync_skips_when_panel_never_opened():
    s = _stub_with({})  # no SC-specific keys at all
    s._sc_sync_sessions()


def test_sync_runs_when_panel_is_live():
    # With a live "canvas", the sync proceeds and refreshes the dropdown.
    try:
        root = tk.Tk()  # needed: sync creates tk.BooleanVars for new sessions
    except tk.TclError:
        pytest.skip("no display available for Tk")
    root.withdraw()
    try:
        calls = []

        class _LiveDropdown:
            def refresh_options(self):
                calls.append(1)

        s = _stub_with({
            "canvas": object(),  # marks the panel as on screen
            "sc_session_vars": {},
            "sc_session_labels": {},
            "sc_session_dd": _LiveDropdown(),
        })
        s._sc_sync_sessions()
        assert calls == [1]
    finally:
        root.destroy()
