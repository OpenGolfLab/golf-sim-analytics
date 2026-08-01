"""Assign past sessions to golfers — the manual half of multi-player support.

GSPro only names the golfer on course rounds (see data/players.py), so range
and CSV sessions are attributed by whoever the app thought was hitting. This
dialog is the correction path for when that guess was wrong, and the bulk tool
for splitting a shared history the first time a second golfer appears.

Nothing here writes Parquet. Every change goes to the players.json sidecar via
the caller's on_apply, so a mis-click costs an undo, never shot data.
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from config import Colors
from data import players as players_mod
from ui import theme
from ui.components import SingleSelectDropdown
from ui.dialogs import show_toast

_UNASSIGNED_CHOICE = players_mod.UNASSIGNED_LABEL
_NEW_CHOICE = "+ New golfer…"

# Enough rows to cover a season of weekly sessions without the dialog becoming
# a scrolling chore. Older sessions are reachable by assigning newer ones first
# — the list is newest-first — and this is a tidy-up tool, not an archive
# browser.
_MAX_ROWS = 60


class PlayerAssignmentDialog:
    """One row per session: its date/shot count, and who it belongs to.

    ``sessions`` is [(session_id, label)] newest-first, ``players`` the known
    names, ``current`` the {session_id: player} map as it stands. ``on_apply``
    receives ONLY the rows the user actually changed — an untouched session is
    never rewritten, so opening this dialog and pressing Save is a no-op.
    """

    def __init__(self, root, sessions, players, current, on_apply):
        self.root = root
        self.on_apply = on_apply
        self.sessions = list(sessions)[:_MAX_ROWS]
        self.truncated = len(sessions) - len(self.sessions)
        # Names offered in every row's dropdown. Rebuilt whenever a new golfer
        # is typed, so a name invented on row 1 is pickable on row 2.
        self.names = list(players)
        self.original = {sid: current.get(sid, players_mod.UNASSIGNED)
                         for sid, _ in self.sessions}
        self.vars: dict[str, tk.StringVar] = {}
        self.dropdowns: dict[str, SingleSelectDropdown] = {}

        self.win = ctk.CTkToplevel(root)
        self.win.title("Assign sessions to golfers")
        self.win.configure(fg_color=Colors.BG_SURFACE)
        self.win.transient(root)
        self.win.geometry(f"+{root.winfo_rootx() + root.winfo_width() // 2 - 280}"
                          f"+{root.winfo_rooty() + 100}")
        self._build()
        self.win.after(120, lambda: (self.win.winfo_exists()
                                     and (self.win.lift(), self.win.focus_force())))

    # -- construction ---------------------------------------------------
    def _build(self):
        card = theme.card_frame(self.win)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        theme.section_label(card, "Who hit these sessions?",
                            color=Colors.INFO).pack(anchor="w", pady=(2, 2))
        theme.body_label(
            card, "Sessions are filed under whoever was set as “Who's hitting” "
            "when they landed. Change any that went to the wrong golfer — this "
            "only re-labels sessions, it never edits your shots.",
            color=Colors.TEXT_MUTED, font=theme.font("caption"),
            wraplength=520, justify="left").pack(anchor="w", pady=(0, 10))

        scroller = ctk.CTkScrollableFrame(
            card, width=540, height=320, fg_color="transparent")
        scroller.pack(fill="both", expand=True)

        for session_id, label in self.sessions:
            row = ctk.CTkFrame(scroller, fg_color="transparent")
            row.pack(fill="x", pady=3)
            theme.body_label(row, label, color=Colors.TEXT_PRIMARY,
                             font=theme.font("body")).pack(side="left")
            var = tk.StringVar(value=self.original[session_id] or _UNASSIGNED_CHOICE)
            self.vars[session_id] = var
            dd = SingleSelectDropdown(
                row, self._choices(), var, accent=Colors.INFO, width=170,
                on_change=lambda sid=session_id: self._on_pick(sid),
            )
            dd.pack(side="right")
            self.dropdowns[session_id] = dd

        if self.truncated > 0:
            theme.body_label(
                card, f"Showing the {len(self.sessions)} most recent sessions "
                      f"({self.truncated} older not listed).",
                color=Colors.TEXT_MUTED, font=theme.font("caption")).pack(
                anchor="w", pady=(8, 0))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", pady=(12, 0))
        theme.primary_button(btns, text="Save", command=self._save,
                             width=110).pack(side="right", padx=(6, 0))
        theme.ghost_button(btns, text="Cancel", command=self.win.destroy,
                           width=100).pack(side="right")
        # Bulk path for the common first-run case: one household, one history,
        # everything actually belongs to the same person.
        theme.ghost_button(btns, text="All to one golfer…", width=150,
                           command=self._assign_all).pack(side="left")

    def _choices(self):
        return [_UNASSIGNED_CHOICE, *self.names, _NEW_CHOICE]

    # -- interaction ----------------------------------------------------
    def _on_pick(self, session_id):
        if self.vars[session_id].get() == _NEW_CHOICE:
            self._prompt_new_name(lambda name: self._set_row(session_id, name))

    def _set_row(self, session_id, name):
        # A cancelled "new golfer" prompt must not leave the literal
        # "+ New golfer…" sitting in the row as if it were a person.
        self.vars[session_id].set(name or self.original[session_id] or _UNASSIGNED_CHOICE)
        self._refresh_choices()

    def _refresh_choices(self):
        for dd in self.dropdowns.values():
            dd.set_options(self._choices())

    def _prompt_new_name(self, on_name):
        """Small modal for typing a golfer's name. Its own window rather than an
        inline entry so it can be cancelled cleanly from any row."""
        top = ctk.CTkToplevel(self.win)
        top.title("New golfer")
        top.configure(fg_color=Colors.BG_SURFACE)
        top.transient(self.win)
        top.geometry(f"+{self.win.winfo_rootx() + 120}+{self.win.winfo_rooty() + 140}")
        card = theme.card_frame(top)
        card.pack(fill="both", expand=True, padx=16, pady=16)
        theme.body_label(card, "Golfer's name", color=Colors.TEXT_PRIMARY,
                         font=theme.font("label")).pack(anchor="w")
        entry = ctk.CTkEntry(card, width=240, height=theme.CONTROL_HEIGHT)
        entry.pack(anchor="w", pady=(6, 12))
        entry.focus_set()

        def _ok(_event=None):
            name = players_mod.normalize_name(entry.get())
            if not name:
                show_toast(self.root, "That name is blank — nothing added.", tone="warning")
                top.destroy()
                on_name("")
                return
            if name not in self.names:
                self.names.append(name)
                self.names.sort()
            top.destroy()
            on_name(name)

        def _cancel():
            top.destroy()
            on_name("")

        entry.bind("<Return>", _ok)
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x")
        theme.primary_button(btns, text="Add", command=_ok, width=90).pack(
            side="right", padx=(6, 0))
        theme.ghost_button(btns, text="Cancel", command=_cancel, width=90).pack(side="right")
        top.after(120, lambda: (top.winfo_exists() and (top.lift(), top.focus_force())))

    def _assign_all(self):
        def _apply(name):
            if not name:
                return
            for var in self.vars.values():
                var.set(name)
            self._refresh_choices()

        if self.names:
            # Existing golfers are the likely target; "+ New golfer…" in the
            # same prompt covers the rest, so this is one decision either way.
            self._prompt_pick_existing(_apply)
        else:
            self._prompt_new_name(_apply)

    def _prompt_pick_existing(self, on_name):
        top = ctk.CTkToplevel(self.win)
        top.title("Assign all")
        top.configure(fg_color=Colors.BG_SURFACE)
        top.transient(top.master)
        top.geometry(f"+{self.win.winfo_rootx() + 120}+{self.win.winfo_rooty() + 140}")
        card = theme.card_frame(top)
        card.pack(fill="both", expand=True, padx=16, pady=16)
        theme.body_label(card, "Assign every listed session to",
                         color=Colors.TEXT_PRIMARY, font=theme.font("label")).pack(anchor="w")
        var = tk.StringVar(value=self.names[0])
        SingleSelectDropdown(card, [*self.names, _NEW_CHOICE], var,
                             accent=Colors.INFO, width=220).pack(anchor="w", pady=(6, 12))

        def _ok():
            choice = var.get()
            top.destroy()
            if choice == _NEW_CHOICE:
                self._prompt_new_name(on_name)
            else:
                on_name(choice)

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x")
        theme.primary_button(btns, text="Apply", command=_ok, width=90).pack(
            side="right", padx=(6, 0))
        theme.ghost_button(btns, text="Cancel", command=top.destroy, width=90).pack(side="right")
        top.after(120, lambda: (top.winfo_exists() and (top.lift(), top.focus_force())))

    # -- save -----------------------------------------------------------
    def _save(self):
        changes = {}
        for session_id, var in self.vars.items():
            choice = var.get()
            if choice in (_NEW_CHOICE,):
                continue  # never resolved to a real name; leave it alone
            name = players_mod.UNASSIGNED if choice == _UNASSIGNED_CHOICE else choice
            if name != self.original[session_id]:
                changes[session_id] = name
        self.win.destroy()
        if changes:
            self.on_apply(changes)
        else:
            show_toast(self.root, "Nothing changed.", tone="info")
