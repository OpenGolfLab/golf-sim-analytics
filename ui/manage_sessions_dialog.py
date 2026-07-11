"""Manage Sessions dialog — soft-delete / restore whole sessions.

Reversible: deleting hides a session everywhere (via data/edits.py); restoring
brings it back. The archived Parquet is never touched.
"""
from __future__ import annotations

import customtkinter as ctk

from config import Colors
from ui import theme


def open_manage_sessions_dialog(root, sessions, on_toggle):
    """sessions: list of (session_id, label, is_deleted), newest first.
    on_toggle(session_id, delete: bool) persists the change."""
    win = ctk.CTkToplevel(root)
    win.title("Manage Sessions")
    win.configure(fg_color=Colors.BG_SURFACE)
    win.transient(root)
    win.geometry(f"460x560+{root.winfo_rootx() + 200}+{root.winfo_rooty() + 120}")

    card = theme.card_frame(win)
    card.pack(fill="both", expand=True, padx=14, pady=14)
    theme.section_label(card, "Sessions", color=Colors.INFO).pack(anchor="w", pady=(2, 2))
    theme.body_label(card, "Deleting hides a session everywhere — it's reversible "
                     "and never touches your files.", color=Colors.TEXT_MUTED,
                     font=theme.font("caption"), wraplength=410, justify="left").pack(
        anchor="w", pady=(0, 8))

    scroll = ctk.CTkScrollableFrame(card, fg_color="transparent")
    scroll.pack(fill="both", expand=True)

    if not sessions:
        theme.body_label(scroll, "No sessions yet.", color=Colors.TEXT_MUTED).pack(pady=20)

    for sid, label, is_deleted in sessions:
        row = ctk.CTkFrame(scroll, fg_color=Colors.BG_HOVER, corner_radius=8)
        row.pack(fill="x", pady=3)
        lbl = theme.body_label(row, label, color=Colors.TEXT_PRIMARY)
        lbl.pack(side="left", padx=12, pady=8)
        btn = theme.outline_button(row, accent=Colors.DANGER, text="", width=90)

        def _make(sid=sid, lbl=lbl, btn=btn, state={"deleted": is_deleted}):
            def _refresh():
                deleted = state["deleted"]
                lbl.configure(text_color=Colors.TEXT_MUTED if deleted else Colors.TEXT_PRIMARY)
                btn.configure(text="Restore" if deleted else "Delete",
                              text_color=Colors.SUCCESS if deleted else Colors.DANGER)

            def _click():
                state["deleted"] = not state["deleted"]
                on_toggle(sid, state["deleted"])
                _refresh()
            _refresh()
            return _click
        btn.configure(command=_make())
        btn.pack(side="right", padx=10, pady=6)

    theme.outline_button(card, accent=Colors.TEXT_MUTED, text="Close",
                         command=win.destroy, width=100).pack(side="right", pady=(10, 0))
    win.after(120, lambda: (win.winfo_exists() and (win.lift(), win.focus_force())))
    return win
