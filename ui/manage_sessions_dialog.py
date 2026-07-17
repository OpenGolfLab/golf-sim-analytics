"""Manage Sessions panel — soft-delete / restore whole sessions.

Reversible: deleting hides a session everywhere (via data/edits.py); restoring
brings it back. The archived Parquet is never touched. Rendered as a drop-down
panel body (see ui.components.DropdownPanel), not a floating window.
"""
from __future__ import annotations

import customtkinter as ctk

from config import Colors
from ui import theme


def build_manage_sessions_body(card, close, sessions, on_toggle):
    """Fill the Manage Sessions dropdown panel.

    ``card`` is an already-scrollable body; ``close`` dismisses the panel.
    sessions: list of (session_id, label, is_deleted), newest first.
    on_toggle(session_id, delete: bool) persists the change."""
    theme.section_label(card, "Sessions", color=Colors.INFO).pack(anchor="w", pady=(2, 2))
    theme.body_label(card, "Deleting hides a session everywhere — it's reversible "
                     "and never touches your files.", color=Colors.TEXT_MUTED,
                     font=theme.font("caption"), wraplength=410, justify="left").pack(
        anchor="w", pady=(0, 8))

    if not sessions:
        theme.body_label(card, "No sessions yet.", color=Colors.TEXT_MUTED).pack(pady=20)

    for sid, label, is_deleted in sessions:
        row = ctk.CTkFrame(card, fg_color=Colors.BG_HOVER, corner_radius=8)
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
                         command=close, width=100).pack(side="right", pady=(10, 0))
