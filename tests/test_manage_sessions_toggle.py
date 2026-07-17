"""Regression: the Manage Sessions row button toggles Delete↔Restore and must
keep its semantic color (red delete / green restore) through a hover.

theme.danger_button installs Enter/Leave handlers that force its label back to
red on mouse-leave — correct for a fixed destructive button, but it would wipe
the green "Restore" state on this *toggle*. So the row uses a plain ghost button
and owns its own colors; this pins that it survives a hover cycle.
"""
import tkinter as tk

import customtkinter as ctk
import pytest

from config import Colors
from ui.manage_sessions_dialog import build_manage_sessions_body


@pytest.fixture
def root():
    try:
        ctk.deactivate_automatic_dpi_awareness()
    except Exception:
        pass
    ctk.set_widget_scaling(1.0)
    ctk.set_window_scaling(1.0)
    try:
        r = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available for Tk")
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def _toggle_button(card):
    row = card.winfo_children()[-2]  # last session row (before the Close button)
    return next(w for w in row.winfo_children() if isinstance(w, ctk.CTkButton))


def _hover_cycle(btn, root):
    """Fire an Enter→Leave hover the way it actually reaches a CTkButton.

    CTkButton.bind() forwards bindings to its internal `_canvas`/`_text_label`,
    not the outer frame — so generating the event on the button itself would
    miss the very handlers this test exists to exercise (that was a real trap:
    the test passed against the buggy version because the event never landed).
    """
    for target in (btn._canvas, getattr(btn, "_text_label", None)):
        if target is not None:
            target.event_generate("<Enter>")
    root.update()
    for target in (btn._canvas, getattr(btn, "_text_label", None)):
        if target is not None:
            target.event_generate("<Leave>")
    root.update()


def test_restore_stays_green_through_hover(root):
    card = ctk.CTkFrame(root)
    card.pack()
    build_manage_sessions_body(
        card, lambda: None,
        [("s2", "Jul 15 · 42 shots", True)],  # already deleted → shows "Restore"
        lambda *a: None)
    root.update()

    btn = _toggle_button(card)
    assert btn.cget("text") == "Restore"
    assert btn.cget("text_color") == Colors.SUCCESS

    _hover_cycle(btn, root)

    # The bug this guards: a mouse-leave reverting the label to danger red.
    assert btn.cget("text_color") == Colors.SUCCESS


def test_delete_is_red(root):
    card = ctk.CTkFrame(root)
    card.pack()
    build_manage_sessions_body(
        card, lambda: None,
        [("s1", "Jul 16 · 58 shots", False)],  # live → shows "Delete"
        lambda *a: None)
    root.update()

    btn = _toggle_button(card)
    assert btn.cget("text") == "Delete"
    assert btn.cget("text_color") == Colors.DANGER
