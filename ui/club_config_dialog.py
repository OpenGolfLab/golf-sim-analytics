"""Configuration dialog for the Club Comparison chart.

Pick a session, then define up to 4 configs — each a club (from the bag) plus
the brand and adapter you were testing and the shot range (1-indexed, within
that club's shots in the session) those shots cover. The caller owns the data;
this just collects input and hands back (session_id, configs) via on_apply.
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from config import Colors
from ui import theme
from ui.components import SingleSelectDropdown

_ROWS = 4
_NO_CLUB = "—"
_NO_SESSION = "(none — live capture)"


def open_club_config_dialog(root, sessions, clubs, current, on_apply):
    """sessions: [(session_id, label)] newest first. clubs: list of club names.
    current: {"session_id":..., "configs":[{club,brand,adapter,start,end}]} or None.
    on_apply(session_id, configs)."""
    current = current or {}
    # Session is optional: "(none)" means live-capture only, so the chart
    # starts empty and fills as you hit rather than pre-filling a past session.
    labels = [_NO_SESSION] + [lbl for _sid, lbl in sessions]
    label_to_sid = {lbl: sid for sid, lbl in sessions}
    label_to_sid[_NO_SESSION] = None
    sid_to_label = {sid: lbl for sid, lbl in sessions}

    win = ctk.CTkToplevel(root)
    win.title("Configure Club Comparison")
    win.configure(fg_color=Colors.BG_SURFACE)
    win.transient(root)
    win.geometry(f"+{root.winfo_rootx() + 200}+{root.winfo_rooty() + 120}")

    card = theme.card_frame(win)
    card.pack(fill="both", expand=True, padx=16, pady=16)

    cur_label = sid_to_label.get(current.get("session_id"), _NO_SESSION)
    session_var = tk.StringVar(value=cur_label)
    theme.section_label(card, "Session (optional — for reviewing past shots)",
                        color=Colors.INFO).pack(anchor="w", pady=(2, 2))
    SingleSelectDropdown(card, labels, session_var, accent=Colors.INFO, width=320).pack(anchor="w", pady=(0, 12))

    grid = ctk.CTkFrame(card, fg_color="transparent")
    grid.pack(fill="x")
    for c, head in enumerate(("Club", "Brand", "Adapter", "First", "Last")):
        theme.body_label(grid, head, color=Colors.TEXT_MUTED,
                         font=theme.font("caption", "bold")).grid(row=0, column=c, padx=4, pady=(0, 4), sticky="w")

    club_opts = [_NO_CLUB] + list(clubs)
    existing = current.get("configs", [])
    rows = []
    for i in range(_ROWS):
        cfg = existing[i] if i < len(existing) else {}
        club_var = tk.StringVar(value=cfg.get("club") or _NO_CLUB)
        brand_var = tk.StringVar(value=cfg.get("brand", ""))
        adapter_var = tk.StringVar(value=cfg.get("adapter", ""))
        start_var = tk.StringVar(value=str(cfg.get("start", "") or ""))
        end_var = tk.StringVar(value=str(cfg.get("end", "") or ""))

        SingleSelectDropdown(grid, club_opts, club_var, accent=Colors.INFO, width=90).grid(
            row=i + 1, column=0, padx=4, pady=4)
        ctk.CTkEntry(grid, textvariable=brand_var, width=120,
                     placeholder_text="e.g. TSR3").grid(row=i + 1, column=1, padx=4, pady=4)
        ctk.CTkEntry(grid, textvariable=adapter_var, width=130,
                     placeholder_text="+1 Loft, Draw").grid(row=i + 1, column=2, padx=4, pady=4)
        ctk.CTkEntry(grid, textvariable=start_var, width=52, justify="center",
                     placeholder_text="1").grid(row=i + 1, column=3, padx=4, pady=4)
        ctk.CTkEntry(grid, textvariable=end_var, width=52, justify="center",
                     placeholder_text="all").grid(row=i + 1, column=4, padx=4, pady=4)
        rows.append((club_var, brand_var, adapter_var, start_var, end_var))

    theme.body_label(card, "Ranges are 1-indexed over that club's shots in the session "
                     "(blank First/Last = all).", color=Colors.TEXT_MUTED,
                     font=theme.font("caption")).pack(anchor="w", pady=(10, 8))

    btns = ctk.CTkFrame(card, fg_color="transparent")
    btns.pack(fill="x")

    def _int_or_none(s):
        try:
            return int(s)
        except (TypeError, ValueError):
            return None

    def _apply():
        configs = []
        for club_var, brand_var, adapter_var, start_var, end_var in rows:
            club = club_var.get()
            if club == _NO_CLUB or not club:
                continue
            configs.append({
                "club": club,
                "brand": brand_var.get().strip(),
                "adapter": adapter_var.get().strip(),
                "start": _int_or_none(start_var.get()),
                "end": _int_or_none(end_var.get()),
            })
        on_apply(label_to_sid.get(session_var.get()), configs)
        win.destroy()

    theme.primary_button(btns, text="Apply", command=_apply, width=100).pack(side="right", padx=(6, 0))
    theme.ghost_button(btns, text="Cancel", command=win.destroy, width=100).pack(side="right")

    win.after(120, lambda: (win.winfo_exists() and (win.lift(), win.focus_force())))
    return win
