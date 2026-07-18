"""Regression tests for the shared dropdown surfaces (ui/components.py) and the
two theme primitives they lean on.

Two real bugs are pinned here, both of which were invisible to the eye until you
measured pixels:

1. DropdownPanel opened at CTk's default CTkScrollableFrame height (~200px), so
   every panel — Settings worst — opened tiny and immediately scrolled. The fix
   sizes from the *content* frame and clamps to the app window.
2. theme.divider() was a CTkFrame(height=1), and a CTkFrame paints nothing at
   all below 2px on either axis. Every rule in the app was invisible.
"""
import time
import tkinter as tk

import customtkinter as ctk
import pytest

from ui import theme
from ui.components import DropdownPanel

WINDOW_H = 700


@pytest.fixture(scope="module")
def root():
    """One CTk root for the whole module — customtkinter does not tolerate a
    second CTk() in the same process, so a function-scoped root makes every
    test after the first skip."""
    # Pin scaling *before* creating the root, and for the same reason app.py
    # does it: customtkinter's automatic per-monitor DPI watcher re-applies
    # geometry to the root on a timer, and each re-apply fires a root
    # <Configure> — which DropdownPanel correctly reads as "the window moved,
    # dismiss". Left on, it closes the panel mid-test at random. A root created
    # before this call keeps its own watcher, so the order matters.
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
    r.geometry(f"900x{WINDOW_H}+0+0")
    # Drain the window's own start-up <Configure> events before any test opens
    # a panel. DropdownPanel deliberately dismisses on a root <Configure>, so a
    # single leftover from window creation would close the panel mid-assertion
    # (and only ever for the first test in the process, which is a miserable
    # way to find out).
    for _ in range(5):
        r.update()
        time.sleep(0.02)
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


@pytest.fixture(autouse=True)
def _foreground(monkeypatch):
    """Pretend the app is the OS foreground window for every test here.

    DropdownPanel's minimize/app-switch watchdog closes the panel when another
    process owns the foreground window — and during a test run the pytest
    terminal usually does, which would slam every panel shut mid-measurement.
    Tests that specifically exercise the app-switch behaviour re-stub this to
    return False themselves."""
    import ui.components as components
    monkeypatch.setattr(components, "_foreground_is_this_app", lambda: True)


@pytest.fixture
def make_panel(root):
    """Open a DropdownPanel whose content is `n_rows` fixed-height rows,
    anchored at the top-left of the window. Anchors are placed (not packed) so
    successive tests don't stack them down the window and steal the vertical
    room the clamping test needs."""
    opened = []

    def _make(n_rows, row_h=30, **kw):
        anchor = theme.ghost_button(root, text="anchor")
        anchor.place(x=0, y=0)
        root.update()

        def build(card, _close):
            for i in range(n_rows):
                ctk.CTkLabel(card, text=f"row {i}", height=row_h).pack(fill="x")

        p = DropdownPanel(anchor, build, **kw)
        p.open()
        # The popup needs one event pass of its own before winfo_* reports the
        # geometry _reposition asked for (until then it reports CTk's 200x200
        # default — which is the very number this suite exists to catch).
        p._popup.update()
        assert p.is_open(), "panel closed before it could be measured"
        opened.append((p, anchor))
        return p

    yield _make

    for p, anchor in opened:
        p.close()
        anchor.destroy()
    root.update()


def _viewport(panel):
    return panel._body._parent_canvas.winfo_height()


def test_short_panel_hugs_content_and_does_not_scroll(make_panel):
    """A short panel must not balloon to CTk's ~200px default, and must not
    scroll content that fits."""
    p = make_panel(n_rows=3)
    content = p._content.winfo_reqheight()

    assert content <= _viewport(p), "content that fits must not be clipped"
    # The whole panel is content + a small, measured amount of chrome.
    assert p._popup.winfo_height() - content < 40
    # The old bug: ~200px of scroll viewport for ~90px of content.
    assert p._popup.winfo_height() < 150


def test_tall_panel_caps_at_two_thirds_and_scrolls(make_panel, root):
    """Tall content stops at ~2/3 of the window height and scrolls from there —
    a full-height drape reads as a page, not a menu."""
    p = make_panel(n_rows=60)
    content = p._content.winfo_reqheight()
    cap_bottom = (root.winfo_rooty()
                  + int(root.winfo_height() * DropdownPanel._MAX_FRACTION))
    panel_bottom = p._popup.winfo_rooty() + p._popup.winfo_height()

    assert content > _viewport(p), "content this tall must scroll"
    assert panel_bottom <= cap_bottom, "panel must respect the 2/3 cap"
    # ...but it should use nearly all of the room under the cap, not a
    # 200px default.
    assert cap_bottom - panel_bottom <= DropdownPanel._MARGIN_BOTTOM + 4


def test_switching_to_another_app_closes_the_panel(make_panel, root, monkeypatch):
    """The failure users actually hit: clicking another application leaves the
    root window "normal" (no Unmap, no state change), while the topmost popup
    keeps floating above the other app. The watchdog must catch it via the
    foreground-process check. The Win32 call is stubbed so the test doesn't
    depend on juggling real OS windows; the call itself was verified live."""
    import ui.components as components

    p = make_panel(n_rows=3)
    assert p.is_open()
    monkeypatch.setattr(components, "_foreground_is_this_app", lambda: False)

    deadline = time.time() + 2
    while p.is_open() and time.time() < deadline:
        root.update()
        time.sleep(0.05)
    assert not p.is_open(), "panel must close when another app takes the foreground"


def test_minimizing_the_window_closes_the_panel(make_panel, root):
    """The panel is an overrideredirect+topmost toplevel the window manager
    doesn't tie to the app — minimizing must not leave it floating over other
    applications."""
    p = make_panel(n_rows=3)
    assert p.is_open()
    try:
        root.withdraw()   # fires <Unmap> on the root, like minimizing does
        root.update()
        assert not p.is_open(), "panel must close when the app is hidden"
    finally:
        root.deiconify()
        for _ in range(5):
            root.update()
            time.sleep(0.02)


def test_panel_height_tracks_content_not_scrollframe_default(make_panel):
    """The regression itself: two panels with very different content must get
    very different heights. Before the fix both were ~200px."""
    short_h = make_panel(n_rows=2)._popup.winfo_height()
    tall_h = make_panel(n_rows=12)._popup.winfo_height()

    assert tall_h > short_h + 100


def test_divider_paints_a_real_hairline(root):
    """A CTkFrame paints nothing below 2px, so the dividers must not be one.
    Guards the fix rather than the symptom: assert a real, mapped 1px widget."""
    d = theme.divider(root)
    d.pack(fill="x")
    v = theme.vdivider(root)
    v.pack(fill="y")
    root.update()

    try:
        assert not isinstance(d, ctk.CTkFrame), "CTkFrame does not render at 1px"
        assert not isinstance(v, ctk.CTkFrame)
        assert d.winfo_height() == 1 and d.winfo_width() > 1
        assert v.winfo_width() == 1 and v.winfo_height() >= 1
    finally:
        d.destroy()
        v.destroy()
