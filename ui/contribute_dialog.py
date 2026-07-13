"""Modal dialog for opting in to the OpenGolfLab community dataset.

Themed to match the rest of the app (see ui/adapter_dialog.py for the same
pattern). It owns no data: consent + the persisted contributor id live in
``contribute`` (BASE_DIR), and the shot history is loaded on demand via
``data.store.load_master_dataframe``. Export is opt-in — the button does nothing
until the consent box is ticked, which is exactly what contribute.build_bundle
enforces too.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

import config
from config import Colors
from ui import theme

import contribute
from data.store import load_master_dataframe


# Consent copy — mirrors what contribute.build_bundle actually does, and the
# data-use policy on opengolflab.com (raw stays private, only aggregates ship).
_INTRO = (
    "Help build open, community golf data. If you opt in, Golf Sim Analytics "
    "exports an anonymized copy of your shot metrics to share with OpenGolfLab."
)
_POINTS = [
    ("Shared", "club, ball & club speed, launch, spin, carry and similar per-shot numbers — plus an optional handicap band you pick."),
    ("Never shared", "your name, email, files, or anything identifying. No account, no tracking."),
    ("How it's used", "only combined community averages are ever published on opengolflab.com. Your raw shots stay private and are never sold."),
    ("Your choice", "sharing is off unless you turn it on, and you can stop anytime."),
]


def open_contribute_dialog(root):
    """Open the contribution dialog. Returns the Toplevel."""
    win = ctk.CTkToplevel(root)
    win.title("Contribute to OpenGolfLab")
    win.configure(fg_color=Colors.BG_SURFACE)
    win.transient(root)
    win.geometry(f"+{root.winfo_rootx() + 220}+{root.winfo_rooty() + 120}")

    card = theme.card_frame(win)
    card.pack(fill="both", expand=True, padx=16, pady=16)

    theme.section_label(
        card, "Contribute to OpenGolfLab", color=Colors.ACCENT,
        font=theme.font("subheading", "bold"),
    ).pack(anchor="w", pady=(2, 8))

    theme.body_label(
        card, _INTRO, color=Colors.TEXT_PRIMARY,
        wraplength=460, justify="left", anchor="w",
    ).pack(anchor="w", pady=(0, 10))

    for title, detail in _POINTS:
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", pady=(0, 4))
        theme.section_label(row, f"{title}:", color=Colors.INFO).pack(anchor="w")
        theme.body_label(
            row, detail, color=Colors.TEXT_MUTED, font=theme.font("caption"),
            wraplength=460, justify="left", anchor="w",
        ).pack(anchor="w")

    theme.divider(card).pack(fill="x", pady=12)

    # ---- opt-in ----
    app_dir = str(config.BASE_DIR)
    consent_var = tk.BooleanVar(value=contribute.has_consent(app_dir))

    def _toggle_consent():
        contribute.record_consent(app_dir, consent_var.get())
        _refresh_button()

    theme.nav_checkbox(
        card, text="I opt in to contribute anonymized shot data",
        variable=consent_var, command=_toggle_consent,
    ).pack(anchor="w", pady=(0, 10))

    # ---- optional handicap band ----
    theme.section_label(card, "Your handicap (optional)", color=Colors.WARNING).pack(anchor="w", pady=(2, 2))
    band_var = tk.StringVar(value="unknown")
    theme.dropdown(card, list(contribute.HANDICAP_BANDS), band_var, width=200).pack(anchor="w", pady=(0, 12))

    # ---- status line ----
    status = theme.body_label(card, "", color=Colors.TEXT_MUTED, font=theme.font("caption"),
                              wraplength=460, justify="left", anchor="w")
    status.pack(anchor="w", pady=(0, 8))

    def _set_status(msg, color=Colors.TEXT_MUTED):
        status.configure(text=msg, text_color=color)

    # ---- actions ----
    def _export():
        if not consent_var.get():
            _set_status("Turn on the opt-in above to export.", Colors.WARNING)
            return
        try:
            df = load_master_dataframe(config.DATA_DIR)
        except Exception as exc:  # noqa: BLE001
            _set_status(f"Couldn't read your shot history: {exc}", Colors.WARNING)
            return
        if df is None or df.empty:
            _set_status("No shots recorded yet — play a session first.", Colors.WARNING)
            return
        out_root = filedialog.askdirectory(
            parent=win, title="Choose where to save your contribution bundle",
        )
        if not out_root:
            return
        try:
            path = contribute.build_bundle(
                df, out_root, app_dir=app_dir,
                handicap_band=band_var.get(),
                app_version=getattr(config, "APP_VERSION", ""),
            )
        except Exception as exc:  # noqa: BLE001
            _set_status(f"Couldn't export: {exc}", Colors.WARNING)
            return
        _set_status(
            f"Saved to:\n{path}\n\nEmail or upload that folder to submit it. "
            "Thank you for contributing!",
            Colors.SUCCESS,
        )

    btns = ctk.CTkFrame(card, fg_color="transparent")
    btns.pack(fill="x", pady=(4, 0))

    export_btn = theme.outline_button(btns, accent=Colors.SUCCESS, text="Export bundle",
                                      command=_export, width=140)
    export_btn.pack(side="right", padx=(6, 0))
    theme.outline_button(btns, accent=Colors.TEXT_MUTED, text="Close",
                         command=win.destroy, width=100).pack(side="right")

    def _refresh_button():
        # Subtle affordance: dim the export button until consent is on.
        export_btn.configure(state="normal" if consent_var.get() else "disabled")

    _refresh_button()
    win.after(120, lambda: (win.winfo_exists() and (win.lift(), win.focus_force())))
    return win
