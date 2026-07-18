"""
Themed in-app notifications (replaces native tkinter.messagebox).

Native OS dialogs pop up stark white against the dark UI. show_toast()
renders a small dark card in the bottom-right corner of the app window
instead: color-coded accent bar + icon per tone, fade in/out where the
platform supports window alpha, auto-dismiss, click-to-dismiss, and
stacking when several fire in a row.
"""
from __future__ import annotations

import sys
import tkinter as tk

import customtkinter as ctk

from config import Colors
from ui import theme

_TONE_COLORS = {
    "success": Colors.SUCCESS,
    "info": Colors.INFO,
    "warning": Colors.WARNING,
    "error": Colors.DANGER,
}
_TONE_ICONS = {"success": "✓", "info": "ℹ", "warning": "⚠", "error": "✕"}

_active_toasts: list = []
_FADE_STEPS = 6
_FADE_INTERVAL_MS = 25


def _set_alpha(win, value: float) -> None:
    try:
        win.attributes("-alpha", value)
    except tk.TclError:
        pass  # platform without per-window alpha: toast just appears/disappears


def _make_noactivate(win) -> None:
    """Stop this toast from ever becoming the active window (Windows).

    Toasts are topmost, so they appear over whatever application is foreground
    — including GSPro mid-round, where any focus loss can stop shots from
    registering. WS_EX_NOACTIVATE means neither showing the toast nor clicking
    it activates it: the game keeps keyboard focus, and click-to-dismiss still
    works because the window still receives mouse input. WS_EX_TOOLWINDOW
    keeps it out of Alt-Tab (belt-and-braces alongside overrideredirect).

    Best-effort: on any failure (or non-Windows platform) the toast behaves
    exactly as before.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080
        user32 = ctypes.windll.user32
        # Tk parents a Toplevel's client window inside a WM frame; the frame is
        # what Windows activates. overrideredirect windows may have no frame,
        # in which case the client hwnd is the top-level one.
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    except Exception:
        pass


def show_toast(root, message: str, tone: str = "info", duration_ms: int = 4500) -> None:
    accent = _TONE_COLORS.get(tone, Colors.INFO)

    win = ctk.CTkToplevel(root)
    win.overrideredirect(True)
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass
    _set_alpha(win, 0.0)
    win.configure(fg_color=Colors.BG_SURFACE)

    # Same surface treatment (radius, border) as every other floating card in
    # the app — dropdown panels, tooltips, the shot-edit popup — by going
    # through the one factory rather than restating the numbers here.
    card = theme.card_frame(win)
    card.pack(fill="both", expand=True)

    # height=8 so the bar's 200px CTkFrame default doesn't inflate the card;
    # fill="y" stretches it to the final card height anyway
    bar = ctk.CTkFrame(card, fg_color=accent, width=4, height=8, corner_radius=2)
    bar.pack(side="left", fill="y", padx=(10, 0), pady=10)
    icon = ctk.CTkLabel(card, text=_TONE_ICONS.get(tone, "ℹ"), text_color=accent,
                        font=theme.font("subheading", "bold"), width=26)
    icon.pack(side="left", padx=(8, 2), pady=12)
    lbl = ctk.CTkLabel(card, text=message, text_color=Colors.TEXT_PRIMARY,
                       font=theme.font("body"), wraplength=300, justify="left")
    lbl.pack(side="left", padx=(4, 16), pady=12)

    win.update_idletasks()
    _make_noactivate(win)  # after update_idletasks so the hwnd exists
    # measure the card, not the toplevel — a fresh CTkToplevel reports its
    # 200x200 default before geometry is applied, inflating the toast
    w, h = card.winfo_reqwidth(), card.winfo_reqheight()

    _active_toasts[:] = [t for t in _active_toasts if t.winfo_exists()]
    offset = sum(t.winfo_height() + 10 for t in _active_toasts)
    x = root.winfo_rootx() + root.winfo_width() - w - 24
    y = root.winfo_rooty() + root.winfo_height() - h - 24 - offset
    win.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
    _active_toasts.append(win)

    state = {"dismissing": False}

    def _fade(step: int, direction: int, on_done=None) -> None:
        if not win.winfo_exists():
            return
        _set_alpha(win, max(0.0, min(1.0, step / _FADE_STEPS)))
        nxt = step + direction
        if 0 <= nxt <= _FADE_STEPS:
            win.after(_FADE_INTERVAL_MS, lambda: _fade(nxt, direction, on_done))
        elif on_done is not None:
            on_done()

    def _destroy() -> None:
        if win.winfo_exists():
            win.destroy()
        if win in _active_toasts:
            _active_toasts.remove(win)

    def _dismiss(_event=None) -> None:
        if state["dismissing"]:
            return
        state["dismissing"] = True
        _fade(_FADE_STEPS, -1, _destroy)

    for widget in (card, bar, icon, lbl):
        widget.bind("<Button-1>", _dismiss)
    _fade(0, +1)
    win.after(duration_ms, _dismiss)
