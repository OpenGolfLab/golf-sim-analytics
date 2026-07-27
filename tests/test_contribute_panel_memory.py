"""The Contribute panel remembers your profile between opens.

Handicap and launch monitor used to be built as fresh `tk.StringVar`s with
hard-coded defaults, so every visit to the panel started at "unknown" / blank no
matter what the user had picked last time — and re-picking them is exactly the
step a returning contributor skips, which is how a golfer's own bundles end up
disagreeing about their handicap and monitor.

These tests drive the real panel: build it, edit a field the way the widget
would, rebuild it, and check the value came back.
"""
import tkinter as tk

import customtkinter as ctk
import pytest

import config
import contribute
from data import settings as settings_mod
from ui.contribute_dialog import build_contribute_body


@pytest.fixture
def root(tmp_path, monkeypatch):
    # BASE_DIR is both the settings.json home and the panel's app_dir, so this
    # keeps the test off the developer's real settings and contributor id.
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
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


def _open_panel(root):
    """Build the panel fresh, as reopening the dropdown does."""
    card = ctk.CTkFrame(root)
    card.pack()
    build_contribute_body(card, lambda: None, configured_name="Tester")
    root.update()
    return card


def _values(card) -> list[str]:
    """Every value currently displayed by a control in the panel."""
    out = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, (ctk.CTkComboBox, ctk.CTkEntry)):
                out.append(str(c.get()))
            walk(c)

    walk(card)
    return out


@pytest.mark.parametrize("key, value", [
    ("handicap_band", "10-14"),
    ("launch_monitor", "SkyTrak+"),
    ("age_band", "40-49"),
    ("ball_model", "Pro V1"),
])
def test_a_saved_profile_field_is_prefilled_on_the_next_open(root, key, value):
    settings_mod.set(key, value)

    shown = _values(_open_panel(root))

    # Age is displayed by its label ("Prefer not to say" for unknown); every
    # other field displays the stored value verbatim.
    expected = "40-49" if key == "age_band" else value
    assert expected in shown


def test_an_unset_profile_opens_on_the_undeclared_defaults(root):
    shown = _values(_open_panel(root))

    assert "unknown" in shown              # handicap
    assert "Prefer not to say" in shown    # age
    # Nothing invented for the monitor or the ball.
    assert settings_mod.get("launch_monitor") == ""
    assert settings_mod.get("ball_model") == ""


def test_hand_edited_junk_is_not_prefilled(root):
    """settings.json is editable by hand; a value that isn't on the wire
    format's allowlist must not appear pre-selected (or get sent)."""
    settings_mod.set("handicap_band", "plus-4")        # not a HANDICAP_BAND
    settings_mod.set("launch_monitor", "Homemade Rig")  # not a LAUNCH_MONITOR

    shown = _values(_open_panel(root))

    assert "plus-4" not in shown
    assert "Homemade Rig" not in shown
    assert "unknown" in shown  # fell back to the safe default


def test_editing_a_field_persists_it_immediately(root):
    """No Save button in this panel — a change has to stick as it's made, or a
    user who edits and then closes loses it."""
    card = _open_panel(root)
    combos = [w for w in _all(card) if isinstance(w, ctk.CTkComboBox)]
    handicap = combos[0]  # first dropdown in the panel

    handicap.set("15-19")
    root.update()

    assert settings_mod.get("handicap_band") == "15-19"
    # And it survives to the next open.
    assert "15-19" in _values(_open_panel(root))


def _all(w) -> list:
    found = []
    for c in w.winfo_children():
        found.append(c)
        found.extend(_all(c))
    return found


def test_the_locked_id_is_shown_with_the_name(root):
    """The panel says which parts of your identity move and which don't."""
    card = _open_panel(root)
    texts = " ".join(str(w.cget("text")) for w in _all(card)
                     if "text" in getattr(w, "keys", lambda: [])())

    assert contribute.get_contributor_uuid(str(config.BASE_DIR))[:8] in texts
    assert "permanent" in texts
