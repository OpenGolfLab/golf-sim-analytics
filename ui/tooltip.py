"""Lightweight hover tooltip for CTk/Tk widgets.

customtkinter has no built-in tooltip, so this shows a small themed popup card
to the right of a widget after a short hover delay, and hides it on leave. Used
for the sidebar's menu help.
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from config import Colors
from ui import theme


def attach_tooltip(widget, text: str, delay_ms: int = 450, wraplength: int = 240) -> None:
    if not text:
        return
    state: dict = {"tip": None, "job": None}

    def _show():
        state["job"] = None
        if state["tip"] is not None or not widget.winfo_exists():
            return
        tip = ctk.CTkToplevel(widget)
        tip.overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = ctk.CTkFrame(tip, fg_color=Colors.BG_SURFACE, border_width=1,
                             border_color=Colors.BORDER, corner_radius=8)
        frame.pack(fill="both", expand=True)
        ctk.CTkLabel(frame, text=text, text_color=Colors.TEXT_PRIMARY,
                     font=theme.font("body"), wraplength=wraplength,
                     justify="left").pack(padx=10, pady=6)
        tip.update_idletasks()
        x = widget.winfo_rootx() + widget.winfo_width() + 8
        y = widget.winfo_rooty() + 4
        tip.geometry(f"+{x}+{y}")
        state["tip"] = tip

    def _hide():
        if state["job"] is not None:
            widget.after_cancel(state["job"])
            state["job"] = None
        if state["tip"] is not None:
            if state["tip"].winfo_exists():
                state["tip"].destroy()
            state["tip"] = None

    def _enter(_event):
        _hide()
        state["job"] = widget.after(delay_ms, _show)

    widget.bind("<Enter>", _enter, add="+")
    widget.bind("<Leave>", lambda _e: _hide(), add="+")
    widget.bind("<Destroy>", lambda _e: _hide(), add="+")
    # Click the item to dismiss its help popup right away (and cancel a pending
    # one), rather than having to move the mouse off it.
    widget.bind("<Button>", lambda _e: _hide(), add="+")
