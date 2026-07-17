"""
Entry point. Kept as app.py (rather than renaming to main.py) so
build_exe.bat doesn't need to change.

Everything that used to live in this file — the god class, the chart
renderers, the data plumbing — now lives in config.py, data/, live/, and
ui/. This file just does startup plumbing: DPI awareness, logging, window
icon, and a short fade-in so launch doesn't start with a blank white
window popping into existence.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import tkinter as tk

import customtkinter as ctk

from logging_setup import setup_logging
from ui import theme
from ui.app_window import SimAnalyticsApp


def _set_windows_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _apply_ui_scaling() -> float:
    """Resolve the display scale (a single, size/DPI-driven authority) and
    apply it to customtkinter, returning the factor so the app can scale its
    matplotlib charts to match.

    The scale blends the display's OS DPI setting (readability baseline) with
    its physical size (a gentle size preference) — see data.settings. Physical
    metrics are read after DPI awareness is set so they're truthful.

    customtkinter's own automatic per-monitor DPI scaling is deactivated here
    on purpose: leaving it on top of our derived factor double-counts on
    high-DPI panels. This becomes the ONE thing that decides how big everything
    is, so the UI looks appropriately sized on any display.
    """
    from data import settings as settings_mod

    height, diagonal_in, os_scaling = settings_mod.detect_display_metrics()
    scale = settings_mod.resolve_scale(
        settings_mod.get("ui_scale"), height, diagonal_in, os_scaling)
    try:
        ctk.deactivate_automatic_dpi_awareness()
    except Exception:
        logging.getLogger(__name__).debug("Could not deactivate CTk auto DPI", exc_info=True)
    ctk.set_widget_scaling(scale)
    ctk.set_window_scaling(scale)
    return scale


def _create_root() -> ctk.CTk:
    """The main window, drag-and-drop enabled when tkinterdnd2 is available.

    tkinterdnd2's file-drop support lives in a mixin (DnDWrapper) that needs the
    tkdnd Tcl package loaded into the interpreter. We fold it onto customtkinter's
    CTk so the existing app keeps its theming and scaling, and fall back to a
    plain CTk (no drops, everything else identical) if the library or its native
    tkdnd binaries aren't present — so a missing optional dependency never stops
    the app from launching.
    """
    try:
        from tkinterdnd2 import TkinterDnD

        class _DnDRoot(ctk.CTk, TkinterDnD.DnDWrapper):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.TkdndVersion = TkinterDnD._require(self)

        root = _DnDRoot()
        root._dnd_enabled = True
        return root
    except Exception:
        logging.getLogger(__name__).info(
            "Drag-and-drop unavailable (tkinterdnd2/tkdnd not loaded) — "
            "CSV import via the file picker still works", exc_info=True)
        root = ctk.CTk()
        root._dnd_enabled = False
        return root


def _set_app_icon(root: ctk.CTk) -> None:
    try:
        import config

        ico = config.BASE_DIR / "assets" / "icon.ico"
        png = config.BASE_DIR / "assets" / "icon.png"
        if sys.platform == "win32" and ico.exists():
            root.iconbitmap(str(ico))
        elif png.exists():
            root.iconphoto(True, tk.PhotoImage(file=str(png)))
    except Exception:
        logging.getLogger(__name__).debug("Could not set app icon", exc_info=True)


def main() -> None:
    setup_logging()
    log = logging.getLogger(__name__)
    log.info("Starting Golf Sim Analytics")

    _set_windows_dpi_awareness()
    theme.apply_global_theme()
    ui_scale = _apply_ui_scaling()

    try:
        root = _create_root()
    except tk.TclError:
        log.exception("Failed to create the main window")
        raise

    # Build the UI invisible, then fade in once everything is laid out.
    fade_supported = True
    try:
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        fade_supported = False

    _set_app_icon(root)
    SimAnalyticsApp(root, ui_scale=ui_scale)

    if fade_supported:
        def _fade_in(step: int = 0) -> None:
            try:
                root.attributes("-alpha", min(1.0, step / 8))
            except tk.TclError:
                return
            if step < 8:
                root.after(25, lambda: _fade_in(step + 1))

        root.after(80, _fade_in)

    root.mainloop()


if __name__ == "__main__":
    main()
