"""Modal dialog for assigning a driver adapter setting to a session.

Kept separate from ui/dialogs.py (which is toast-only) since this is the app's
one real input dialog. Themed to match the dark UI rather than a native
messagebox. The caller supplies the session list, the current tag map, and an
``on_save(session_id, label)`` callback — this module owns none of the data.
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from config import Colors
from ui import theme
from ui.components import SingleSelectDropdown


def open_adapter_dialog(root, sessions, tags, on_save):
    """Open the tagging dialog.

    sessions : list of (session_id, display_label), newest first.
    tags     : {session_id: current_label}.
    on_save  : called with (session_id, label) when Save is clicked; a blank
               label clears the tag.
    Returns the Toplevel (or None when there are no sessions to tag).
    """
    if not sessions:
        return None
    labels = [lbl for _sid, lbl in sessions]
    label_to_sid = {lbl: sid for sid, lbl in sessions}

    win = ctk.CTkToplevel(root)
    win.title("Tag Driver Adapter")
    win.configure(fg_color=Colors.BG_SURFACE)
    win.transient(root)
    win.geometry(f"+{root.winfo_rootx() + 240}+{root.winfo_rooty() + 160}")

    card = theme.card_frame(win)
    card.pack(fill="both", expand=True, padx=16, pady=16)

    session_var = tk.StringVar(value=labels[0])
    entry_var = tk.StringVar(value=tags.get(label_to_sid[labels[0]], ""))

    def _on_session_change():
        sid = label_to_sid.get(session_var.get())
        entry_var.set(tags.get(sid, ""))

    theme.section_label(card, "Session", color=Colors.INFO).pack(anchor="w", pady=(2, 2))
    SingleSelectDropdown(
        card, labels, session_var, on_change=_on_session_change,
        accent=Colors.INFO, width=300,
    ).pack(anchor="w", pady=(0, 10))

    theme.section_label(card, "Adapter setting", color=Colors.WARNING).pack(anchor="w", pady=(2, 2))
    entry = ctk.CTkEntry(card, textvariable=entry_var, width=300,
                         placeholder_text="e.g. +1 Loft, Draw Bias")
    entry.pack(anchor="w", pady=(0, 4))
    theme.body_label(card, "Leave blank to clear a session's tag.",
                     color=Colors.TEXT_MUTED, font=theme.font("caption")).pack(anchor="w", pady=(0, 12))

    btns = ctk.CTkFrame(card, fg_color="transparent")
    btns.pack(fill="x")

    def _save():
        sid = label_to_sid.get(session_var.get())
        if sid is not None:
            on_save(sid, entry_var.get())
        win.destroy()

    theme.primary_button(btns, text="Save", command=_save, width=100).pack(side="right", padx=(6, 0))
    theme.ghost_button(btns, text="Cancel", command=win.destroy, width=100).pack(side="right")

    win.after(120, lambda: (win.winfo_exists() and (win.lift(), win.focus_force())))
    return win
