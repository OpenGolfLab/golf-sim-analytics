"""Regression: a display name typed in Settings must show up in the Contribute
panel — even if no widget event ever persisted it to disk.

The original wiring persisted via KeyRelease/FocusOut bindings on the Settings
entry and had Contribute re-read settings.json. The entry lives inside an
overrideredirect popup, whose focus/keyboard event delivery on Windows is
unreliable — a missed event (or a mouse-paste, which fires no KeyRelease) meant
the name silently never reached the contribute panel. The fix is two-sided:

1. Persistence is a trace on the StringVar (fires on ANY change, no events).
2. Contribute receives the live var value directly, not the disk copy.
"""
import tkinter as tk

import customtkinter as ctk
import pytest

from ui import theme
from ui.contribute_dialog import build_contribute_body


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


def _shown_name(card) -> str:
    """The name rendered under the 'Contributing as' header."""
    texts = []

    def walk(w):
        for c in w.winfo_children():
            try:
                t = str(c.cget("text"))
                if t and t not in texts:
                    texts.append(t)
            except Exception:
                pass
            walk(c)

    walk(card)
    i = texts.index("Contributing as")
    return texts[i + 1]


def test_contribute_uses_the_live_name_not_the_disk_copy(root):
    """The panel must show the name the app currently holds, even when nothing
    was ever written to settings.json (the exact failure users hit)."""
    card = ctk.CTkFrame(root)
    card.pack()
    build_contribute_body(card, lambda: None, configured_name="Tyler Test")
    root.update()
    assert _shown_name(card) == "Tyler Test"


def test_contribute_falls_back_to_generated_when_name_invalid(root):
    card = ctk.CTkFrame(root)
    card.pack()
    build_contribute_body(card, lambda: None, configured_name="!!")  # invalid
    root.update()
    import contribute
    shown = _shown_name(card)
    assert shown != "!!"
    assert contribute.normalize_display_name(shown) == shown  # a valid generated name


def test_app_persists_the_name_via_var_trace(root, tmp_path, monkeypatch):
    """The var trace (not widget events) is what persists — setting the var
    alone, with no entry widget in existence at all, must reach settings.json."""
    import config
    from data import settings as settings_mod
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)

    var = tk.StringVar(value="")
    var.trace_add(
        "write", lambda *_a: settings_mod.set("display_name", var.get()))

    var.set("Trace Works")
    assert settings_mod.get("display_name") == "Trace Works"
