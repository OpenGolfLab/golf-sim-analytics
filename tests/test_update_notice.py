"""The Settings footer's update notice.

Drives the real widget path: run the check, let the Tk callback land, and look
at what the footer actually says. The rule being guarded is that this feature
can only ever ADD something — an unreachable GitHub has to leave the version
line exactly as it was, because nobody opens Settings to check for updates and
a failed check is not news.

The check is delivered on the main thread here rather than on the real worker
thread: widget.after() from a worker needs a running mainloop, which the app
has and a test does not. The threading itself is covered by
test_version_check's check_async tests; what these assert is what the footer
does with a result once it arrives.

_build_update_check doesn't touch self, so it's called unbound rather than
standing up a whole SimAnalyticsApp.
"""
import tkinter as tk

import customtkinter as ctk
import pytest

import config
import version_check
from ui import theme
from ui.app_window import SimAnalyticsApp


@pytest.fixture(autouse=True)
def clear_cache():
    version_check._cache = None
    yield
    version_check._cache = None


@pytest.fixture
def footer():
    try:
        ctk.deactivate_automatic_dpi_awareness()
    except Exception:
        pass
    ctk.set_widget_scaling(1.0)
    ctk.set_window_scaling(1.0)
    try:
        root = ctk.CTk()
    except tk.TclError:
        pytest.skip("no display available for Tk")
    frame = ctk.CTkFrame(root)
    frame.pack()
    label = theme.body_label(frame, "Golf Sim Analytics v1.3.0")
    label.pack(side="left")
    yield root, frame, label
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def checked(monkeypatch):
    """Deliver the check's result inline. Returns the list of versions asked
    about, so a test can assert the check didn't run at all."""
    asked = []

    def _sync(current, callback, **kwargs):
        asked.append(current)
        callback(version_check.check(current, **kwargs))
        return "ran"

    monkeypatch.setattr(version_check, "check_async", _sync)
    return asked


def _run(root, frame, label):
    SimAnalyticsApp._build_update_check(None, frame, label)
    root.update()


def _buttons(frame):
    return [w for w in frame.winfo_children() if isinstance(w, ctk.CTkButton)]


def test_an_available_update_is_announced_with_a_download_button(footer, checked, monkeypatch):
    root, frame, label = footer
    monkeypatch.setattr(version_check, "fetch_latest_tag", lambda *a, **k: "v9.9.9")

    _run(root, frame, label)

    assert "v9.9.9 available" in label.cget("text")
    assert [b.cget("text") for b in _buttons(frame)] == ["Download"]


def test_being_up_to_date_says_nothing_new(footer, checked, monkeypatch):
    """No badge, no button, no "you're on the latest!" — the absence of news
    is the message."""
    root, frame, label = footer
    before = label.cget("text")
    monkeypatch.setattr(version_check, "fetch_latest_tag",
                        lambda *a, **k: f"v{config.APP_VERSION}")

    _run(root, frame, label)

    assert label.cget("text") == before
    assert _buttons(frame) == []


def test_an_unreachable_github_leaves_the_footer_untouched(footer, checked, monkeypatch):
    root, frame, label = footer
    before = label.cget("text")
    monkeypatch.setattr(version_check, "fetch_latest_tag", lambda *a, **k: None)

    _run(root, frame, label)

    assert label.cget("text") == before
    assert _buttons(frame) == []


def test_a_reply_arriving_after_the_panel_closed_does_not_raise(footer, monkeypatch):
    """Settings is a dropdown — it's routinely dismissed inside the second the
    request takes. The late reply must find its widget gone and shrug."""
    root, frame, label = footer
    captured = {}
    monkeypatch.setattr(version_check, "check_async",
                        lambda current, cb, **k: captured.update(cb=cb))

    SimAnalyticsApp._build_update_check(None, frame, label)
    frame.destroy()                                    # user closed Settings
    captured["cb"]((version_check.UPDATE, "v9.9.9"))   # reply lands late
    root.update()                                      # no exception


def test_the_button_opens_the_browser_and_downloads_nothing(footer, checked, monkeypatch):
    """The app must never fetch or run the installer itself — it hands off."""
    from ui import app_window as app_window_mod

    root, frame, label = footer
    monkeypatch.setattr(version_check, "fetch_latest_tag", lambda *a, **k: "v9.9.9")
    opened = []
    monkeypatch.setattr(app_window_mod.webbrowser, "open_new_tab", opened.append)

    _run(root, frame, label)
    _buttons(frame)[0].invoke()

    assert opened == [config.LATEST_DOWNLOAD_URL]


def test_no_download_url_configured_means_no_check_at_all(footer, checked, monkeypatch):
    root, frame, label = footer
    monkeypatch.setattr(config, "LATEST_DOWNLOAD_URL", "")

    _run(root, frame, label)

    assert checked == []          # never even asked
    assert _buttons(frame) == []
