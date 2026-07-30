"""Send Feedback dialog — a bug or an idea, typed and gone in ten seconds.

Network runs on a daemon thread with the result marshalled back via
root.after, same as the contribute panel's name check; outcomes surface as
toasts, never native message boxes (see app_window.py's import note).
"""
from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

import config
import feedback
from config import Colors
from ui import theme
from ui.components import SingleSelectDropdown
from ui.dialogs import show_toast

KIND_IDEA = "An improvement idea"
KIND_BUG = "Something's broken"
_KIND_KEYS = {KIND_IDEA: "idea", KIND_BUG: "bug"}


def open_feedback_dialog(root):
    win = ctk.CTkToplevel(root)
    win.title("Send feedback")
    win.configure(fg_color=Colors.BG_SURFACE)
    win.transient(root)
    win.geometry(f"+{root.winfo_rootx() + root.winfo_width() // 2 - 230}"
                 f"+{root.winfo_rooty() + 140}")

    card = theme.card_frame(win)
    card.pack(fill="both", expand=True, padx=16, pady=16)

    theme.section_label(card, "Send feedback", color=Colors.INFO).pack(
        anchor="w", pady=(2, 2))
    theme.body_label(
        card, "Bugs and ideas both land in the same inbox, and every one gets read.",
        color=Colors.TEXT_MUTED, font=theme.font("caption"),
    ).pack(anchor="w", pady=(0, 10))

    kind_var = tk.StringVar(value=KIND_IDEA)
    SingleSelectDropdown(card, [KIND_IDEA, KIND_BUG], kind_var,
                         accent=Colors.INFO, width=230).pack(anchor="w", pady=(0, 10))

    box = ctk.CTkTextbox(card, width=440, height=140, wrap="word",
                         font=theme.font("body"))
    box.pack(anchor="w", pady=(0, 10))
    box.focus_set()

    theme.body_label(card, "Email or handle — optional, only if you want a reply",
                     color=Colors.TEXT_MUTED, font=theme.font("caption")).pack(anchor="w")
    contact = ctk.CTkEntry(card, width=300, placeholder_text="you@example.com")
    contact.pack(anchor="w", pady=(2, 6))

    theme.body_label(
        card, "Sends your words, the type, that contact, and the app version. Nothing else.",
        color=Colors.TEXT_MUTED, font=theme.font("caption"),
    ).pack(anchor="w", pady=(0, 12))

    btns = ctk.CTkFrame(card, fg_color="transparent")
    btns.pack(fill="x")

    def _ok():
        if win.winfo_exists():
            win.destroy()
        show_toast(root, "Feedback sent — thank you.", tone="success")

    def _fail(msg):
        if win.winfo_exists():
            send_btn.configure(state="normal", text="Send")
        show_toast(root, msg, tone="warning")

    def _send():
        message = box.get("1.0", "end").strip()
        if len(message) < 3:
            show_toast(root, "Say a little more — the message is the feedback.",
                       tone="warning")
            return
        payload = feedback.build_payload(
            _KIND_KEYS.get(kind_var.get(), "idea"), message,
            contact=contact.get(), app_version=config.APP_VERSION)
        send_btn.configure(state="disabled", text="Sending…")

        def worker():
            try:
                feedback.send_feedback(config.OPENGOLFLAB_FEEDBACK_URL, payload)
            except Exception as e:  # noqa: BLE001 — anything here is "didn't send"
                root.after(0, _fail, str(e))
            else:
                root.after(0, _ok)

        threading.Thread(target=worker, daemon=True).start()

    send_btn = theme.primary_button(btns, text="Send", command=_send, width=110)
    send_btn.pack(side="right", padx=(6, 0))
    theme.ghost_button(btns, text="Cancel", command=win.destroy, width=100).pack(side="right")

    win.after(120, lambda: (win.winfo_exists() and (win.lift(), win.focus_force())))
    return win
