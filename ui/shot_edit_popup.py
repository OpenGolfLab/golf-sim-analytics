"""Small popup for editing a single shot — reassign its club or delete it.

Used by the Live Dispersion panel's click-to-edit (fix a mis-clubbed live shot
before it archives).
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from config import Colors
from ui import theme
from ui.components import SingleSelectDropdown


def open_shot_edit_popup(root, current_club, clubs, on_pick_club, on_delete):
    win = ctk.CTkToplevel(root)
    win.title("Edit shot")
    win.configure(fg_color=Colors.BG_SURFACE)
    win.transient(root)
    win.geometry(f"+{root.winfo_rootx() + root.winfo_width() // 2 - 120}"
                 f"+{root.winfo_rooty() + root.winfo_height() // 2 - 80}")

    card = theme.card_frame(win)
    card.pack(fill="both", expand=True, padx=16, pady=16)
    theme.section_label(card, "Edit shot", color=Colors.INFO).pack(anchor="w", pady=(2, 8))

    theme.body_label(card, "Club", color=Colors.TEXT_MUTED).pack(anchor="w")
    var = tk.StringVar(value=current_club or (clubs[0] if clubs else ""))

    def _pick():
        on_pick_club(var.get())
        win.destroy()

    SingleSelectDropdown(card, clubs, var, on_change=_pick, accent=Colors.INFO,
                         width=200).pack(anchor="w", pady=(2, 12))

    btns = ctk.CTkFrame(card, fg_color="transparent")
    btns.pack(fill="x")

    def _delete():
        on_delete()
        win.destroy()

    theme.danger_button(btns, text="Delete shot",
                         command=_delete, width=110).pack(side="left")
    theme.ghost_button(btns, text="Cancel",
                         command=win.destroy, width=90).pack(side="right")
    win.after(120, lambda: (win.winfo_exists() and (win.lift(), win.focus_force())))
    return win
