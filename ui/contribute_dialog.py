"""Modal dialog for opting in to the OpenGolfLab community dataset.

Themed to match the rest of the app (see ui/adapter_dialog.py for the same
pattern). It owns no data: consent + the persisted contributor id live in
``contribute`` (BASE_DIR), and the shot history is loaded on demand via
``data.store.load_master_dataframe``. Export is opt-in — the buttons do nothing
until the consent box is ticked, which is exactly what contribute.build_bundle
enforces too.

The user picks *which rounds* to send from a session list, rather than shipping
their entire history in one bundle. This is the fix for the "the app sent the
wrong / far more shots than I hit" report: nothing goes out except the sessions
explicitly checked here, and the exact shot count that will be sent is shown
before submitting.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk
import pandas as pd

import config
from config import Colors, get_club_rank  # noqa: F401 (get_club_rank kept for parity)
from ui import theme

import contribute
from data.store import load_master_dataframe


# Consent copy — mirrors what contribute.build_bundle actually does, and the
# data-use policy on opengolflab.com (raw stays private, only aggregates ship).
_INTRO = (
    "Help build open, community golf data. Pick the rounds you want to share and "
    "Golf Sim Analytics sends an anonymized copy of just those shots to OpenGolfLab."
)
_POINTS = [
    ("Shared", "club, ball & club speed, launch, spin, carry and similar per-shot numbers — plus an optional handicap band you pick."),
    ("Shown publicly", "your display name (below) is published next to your data on opengolflab.org. Nothing else identifies you."),
    ("Never shared", "your real name, email, files, or anything identifying. No account, no tracking."),
    ("How it's used", "only combined community averages are ever published on opengolflab.com. Your raw shots stay private and are never sold."),
    ("Your choice", "sharing is off unless you turn it on, you pick which rounds go, and you can stop anytime."),
]

_PUTTER = "putter"


def _session_rows(df: pd.DataFrame) -> list[tuple[str, str, int]]:
    """(session_id, human label, contributable shot count) per session, newest
    first. The count excludes putts (club == "Putter") because those never get
    contributed — so the number shown here matches what actually ships."""
    if df is None or df.empty or "session_id" not in df.columns:
        return []

    contributable = df
    if "club" in df.columns:
        contributable = df[df["club"].astype(str).str.strip().str.casefold() != _PUTTER]

    dates = (pd.to_datetime(df["session_date"], errors="coerce")
             if "session_date" in df.columns else pd.Series(pd.NaT, index=df.index))
    date_by_sid = dates.groupby(df["session_id"]).max()
    counts = contributable.groupby("session_id").size() if "session_id" in contributable.columns \
        else pd.Series(dtype=int)

    rows = []
    for sid in df["session_id"].dropna().unique():
        n = int(counts.get(sid, 0))
        if n <= 0:
            continue  # a putts-only / empty session has nothing to send
        d = date_by_sid.get(sid)
        when = d.strftime("%b %d, %Y") if pd.notna(d) else "Undated"
        kind = "On-course" if str(sid).endswith("on_course") or "on_course" in str(sid) else "Practice"
        label = f"{when}  ·  {kind}  ·  {n} shot{'s' if n != 1 else ''}"
        rows.append((str(sid), label, n))

    order = {sid: (date_by_sid.get(sid) or pd.Timestamp.min) for sid, *_ in rows}
    rows.sort(key=lambda r: order[r[0]], reverse=True)
    return rows


def build_contribute_body(card, close, configured_name: str | None = None):
    """Fill the Contribute dropdown panel. ``card`` is an already-scrollable
    body (see ui.components.DropdownPanel); ``close`` dismisses the panel.

    ``configured_name`` is the user's display name as currently held by the
    app (the live Settings var). Passing it beats re-reading settings.json:
    the persisted copy can lag or fail, and the live value cannot. None falls
    back to the persisted setting (standalone callers, tests).
    """
    root = card.winfo_toplevel()

    theme.section_label(
        card, "Contribute to OpenGolfLab", color=Colors.ACCENT,
        font=theme.font("subheading", "bold"),
    ).pack(anchor="w", pady=(2, 8))

    theme.body_label(
        card, _INTRO, color=Colors.TEXT_PRIMARY,
        wraplength=420, justify="left", anchor="w",
    ).pack(anchor="w", pady=(0, 10))

    for title, detail in _POINTS:
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", pady=(0, 4))
        theme.section_label(row, f"{title}:", color=Colors.INFO).pack(anchor="w")
        theme.body_label(
            row, detail, color=Colors.TEXT_MUTED, font=theme.font("caption"),
            wraplength=420, justify="left", anchor="w",
        ).pack(anchor="w")

    theme.divider(card).pack(fill="x", pady=12)

    app_dir = str(config.BASE_DIR)

    # ---- who you're contributing as ----
    # The name that will appear publicly, shown *before* anything is sent. If the
    # user never set one, this is where they find out a name was generated for
    # them — and are pointed at Settings to change it — rather than discovering
    # it after the fact on the website.
    if configured_name is None:
        from data import settings as settings_mod
        configured_name = settings_mod.get("display_name")
    active_name, was_generated = contribute.resolve_display_name(app_dir, configured_name)

    theme.section_label(card, "Contributing as", color=Colors.SUCCESS).pack(anchor="w", pady=(2, 2))
    theme.body_label(card, active_name, color=Colors.TEXT_ACTIVE,
                     font=theme.font("subheading", "bold")).pack(anchor="w")
    if was_generated:
        who_note = ("A name was generated for you. Set your own in "
                    "Settings → Display name — it's shown publicly on opengolflab.org.")
    else:
        who_note = "Shown publicly next to your data on opengolflab.org."
    theme.body_label(card, who_note, color=Colors.TEXT_MUTED, font=theme.font("caption"),
                     wraplength=420, justify="left", anchor="w").pack(anchor="w", pady=(2, 10))

    theme.divider(card).pack(fill="x", pady=12)

    # ---- opt-in ----
    consent_var = tk.BooleanVar(value=contribute.has_consent(app_dir))

    def _toggle_consent():
        contribute.record_consent(app_dir, consent_var.get())
        _refresh_button()

    theme.nav_checkbox(
        card, text="I opt in to contribute anonymized shot data",
        variable=consent_var, command=_toggle_consent,
    ).pack(anchor="w", pady=(0, 10))

    # ---- round picker ----
    theme.section_label(card, "Rounds to share", color=Colors.SUCCESS).pack(anchor="w", pady=(2, 2))

    try:
        df = load_master_dataframe(config.DATA_DIR)
    except Exception:  # noqa: BLE001
        df = pd.DataFrame()
    sessions = _session_rows(df)

    session_vars: dict[str, tk.BooleanVar] = {}
    counts: dict[str, int] = {sid: n for sid, _lbl, n in sessions}

    picker = ctk.CTkFrame(card, fg_color=Colors.BG_BASE, corner_radius=theme.SURFACE_RADIUS)
    picker.pack(fill="x", pady=(2, 4))

    selected_label = theme.body_label(card, "", color=Colors.TEXT_MUTED,
                                      font=theme.font("caption"), anchor="w", justify="left")

    def _update_selected():
        chosen = [sid for sid, v in session_vars.items() if v.get()]
        shots = sum(counts.get(sid, 0) for sid in chosen)
        if not chosen:
            selected_label.configure(
                text="No rounds selected — pick at least one round to share.")
        else:
            selected_label.configure(
                text=f"Sending {shots} shot{'s' if shots != 1 else ''} "
                     f"from {len(chosen)} round{'s' if len(chosen) != 1 else ''}.")
        _refresh_button()

    if not sessions:
        theme.body_label(picker, "No rounds recorded yet — play a session first.",
                         color=Colors.TEXT_MUTED, font=theme.font("caption")).pack(
            anchor="w", padx=10, pady=10)
    else:
        actions = ctk.CTkFrame(picker, fg_color="transparent")
        actions.pack(fill="x", padx=8, pady=(8, 2))

        def _set_all(value: bool):
            for v in session_vars.values():
                v.set(value)
            _update_selected()

        theme.solid_button(actions, color=Colors.BG_HOVER, hover=Colors.BORDER, text="All",
                           width=56, height=24, font=theme.font("caption"),
                           command=lambda: _set_all(True)).pack(side="left", padx=(0, 4))
        theme.solid_button(actions, color=Colors.BG_HOVER, hover=Colors.BORDER, text="None",
                           width=56, height=24, font=theme.font("caption"),
                           command=lambda: _set_all(False)).pack(side="left")

        list_height = min(220, max(1, len(sessions)) * 32 + 8)
        scroll = ctk.CTkScrollableFrame(picker, height=list_height, fg_color="transparent",
                                        scrollbar_button_color=Colors.BG_HOVER)
        scroll.pack(fill="x", padx=6, pady=(2, 8))
        for sid, label, _n in sessions:
            var = tk.BooleanVar(value=False)
            session_vars[sid] = var
            theme.nav_checkbox(scroll, text=label, variable=var,
                               command=_update_selected).pack(anchor="w", pady=2, fill="x")

    selected_label.pack(anchor="w", pady=(2, 10))

    # ---- optional handicap band ----
    theme.section_label(card, "Your handicap (optional)", color=Colors.WARNING).pack(anchor="w", pady=(2, 2))
    band_var = tk.StringVar(value="unknown")
    theme.dropdown(card, list(contribute.HANDICAP_BANDS), band_var, width=200).pack(anchor="w", pady=(0, 10))

    # ---- optional launch monitor (drives the data-quality tier) ----
    theme.section_label(card, "Your launch monitor (optional)", color=Colors.WARNING).pack(anchor="w", pady=(2, 2))
    monitor_var = tk.StringVar(value="")
    theme.dropdown(card, list(contribute.LAUNCH_MONITORS), monitor_var, width=200).pack(anchor="w", pady=(0, 2))
    theme.body_label(
        card, "Tells us how your spin was captured (measured vs. modeled), so "
        "high-accuracy sessions can be weighted appropriately. Optional.",
        color=Colors.TEXT_MUTED, font=theme.font("caption"),
        wraplength=420, justify="left", anchor="w",
    ).pack(anchor="w", pady=(0, 12))

    # ---- optional age band (v1.4) ----
    # Banded on purpose (never an exact age next to a public name), defaulting
    # to "Prefer not to say". Persisted: age doesn't change per contribution.
    from data import settings as settings_mod
    _AGE_LABELS = {"unknown": "Prefer not to say"}
    _age_display = [_AGE_LABELS.get(b, b) for b in contribute.AGE_BANDS]

    def _age_to_band(display: str) -> str:
        return next((b for b in contribute.AGE_BANDS
                     if _AGE_LABELS.get(b, b) == display), "unknown")

    saved_band = settings_mod.get("age_band")
    theme.section_label(card, "Your age (optional)", color=Colors.WARNING).pack(anchor="w", pady=(2, 2))
    age_var = tk.StringVar(value=_AGE_LABELS.get(saved_band, saved_band)
                           if saved_band in contribute.AGE_BANDS else "Prefer not to say")
    age_var.trace_add("write", lambda *_a: settings_mod.set("age_band", _age_to_band(age_var.get())))
    theme.dropdown(card, _age_display, age_var, width=200).pack(anchor="w", pady=(0, 10))

    # ---- optional bag (v1.4): driver / irons / wedges, brand + model ----
    # Powers the site's equipment filters. Persisted for the same reason as age:
    # a bag changes rarely, a contribution happens often. Leaving everything
    # blank is a first-class choice — the filters have a "Not specified" bucket.
    theme.section_label(card, "Your bag (optional)", color=Colors.WARNING).pack(anchor="w", pady=(2, 2))
    theme.body_label(
        card, "Helps other golfers filter community data by gear. Leave blank "
        "to skip — shots still count either way.",
        color=Colors.TEXT_MUTED, font=theme.font("caption"),
        wraplength=420, justify="left", anchor="w",
    ).pack(anchor="w", pady=(0, 4))

    saved_equip = settings_mod.get("equipment") or {}
    bag = ctk.CTkFrame(card, fg_color="transparent")
    bag.pack(fill="x", pady=(0, 12))
    equip_vars: dict[str, tuple[tk.StringVar, tk.StringVar]] = {}

    def _persist_equipment(*_a):
        settings_mod.set("equipment", {
            slot: {"brand": bvar.get().strip(), "model": mvar.get().strip()}
            for slot, (bvar, mvar) in equip_vars.items()
            if bvar.get().strip() or mvar.get().strip()
        })

    for row, (slot, label) in enumerate((("driver", "Driver"), ("irons", "Irons"),
                                         ("wedges", "Wedges"))):
        prev = saved_equip.get(slot) or {}
        bvar = tk.StringVar(value=prev.get("brand", ""))
        mvar = tk.StringVar(value=prev.get("model", ""))
        equip_vars[slot] = (bvar, mvar)
        theme.body_label(bag, label, color=Colors.TEXT_PRIMARY).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        theme.dropdown(bag, list(contribute.EQUIPMENT_BRANDS), bvar, width=130).grid(
            row=row, column=1, padx=(0, 6), pady=3)
        entry = ctk.CTkEntry(bag, textvariable=mvar, width=170,
                             height=theme.CONTROL_HEIGHT, corner_radius=theme.CONTROL_RADIUS,
                             font=theme.font("body"), fg_color="transparent",
                             border_color=Colors.BORDER, border_width=1,
                             placeholder_text="Model")
        entry.grid(row=row, column=2, pady=3, sticky="w")
        bvar.trace_add("write", _persist_equipment)
        mvar.trace_add("write", _persist_equipment)

    def _current_equipment() -> dict:
        return {slot: {"brand": bvar.get().strip(), "model": mvar.get().strip()}
                for slot, (bvar, mvar) in equip_vars.items()}

    # ---- status line ----
    status = theme.body_label(card, "", color=Colors.TEXT_MUTED, font=theme.font("caption"),
                              wraplength=420, justify="left", anchor="w")
    status.pack(anchor="w", pady=(0, 8))

    def _set_status(msg, color=Colors.TEXT_MUTED):
        status.configure(text=msg, text_color=color)

    def _selected_ids() -> list[str]:
        return [sid for sid, v in session_vars.items() if v.get()]

    # ---- actions ----
    def _guard() -> list[str] | None:
        if not consent_var.get():
            _set_status("Turn on the opt-in above to share.", Colors.WARNING)
            return None
        chosen = _selected_ids()
        if not chosen:
            _set_status("Pick at least one round to share.", Colors.WARNING)
            return None
        return chosen

    def _export():
        chosen = _guard()
        if chosen is None:
            return
        out_root = filedialog.askdirectory(
            parent=root, title="Choose where to save your contribution file",
        )
        if not out_root:
            return
        try:
            path = contribute.build_zip(
                df, out_root, app_dir=app_dir,
                handicap_band=band_var.get(),
                launch_monitor=monitor_var.get(),
                app_version=getattr(config, "APP_VERSION", ""),
                session_ids=chosen, display_name=configured_name,
                age_band=_age_to_band(age_var.get()),
                equipment=_current_equipment(),
            )
        except Exception as exc:  # noqa: BLE001
            _set_status(f"Couldn't save: {exc}", Colors.WARNING)
            return
        _set_status(
            f"Saved:\n{path}\n\nEmail or upload that .zip to submit it. "
            "Thank you for contributing!",
            Colors.SUCCESS,
        )

    # After a successful upload we hold onto exactly what was sent, so the two
    # receipt buttons below export the real payload rather than rebuilding it.
    sent_payload: dict = {}

    def _send():
        chosen = _guard()
        if chosen is None:
            return
        url = getattr(config, "OPENGOLFLAB_INTAKE_URL", "")
        if not url:
            _set_status("Direct upload isn't set up in this build — use “Save a copy” instead.",
                        Colors.WARNING)
            return
        _set_status("Sending to OpenGolfLab…", Colors.TEXT_MUTED)
        root.update_idletasks()
        try:
            res = contribute.send_bundle(
                df, app_dir=app_dir, url=url,
                key=getattr(config, "OPENGOLFLAB_INTAKE_KEY", "") or None,
                handicap_band=band_var.get(),
                launch_monitor=monitor_var.get(),
                app_version=getattr(config, "APP_VERSION", ""),
                session_ids=chosen, display_name=configured_name,
                age_band=_age_to_band(age_var.get()),
                equipment=_current_equipment(),
            )
        except Exception as exc:  # noqa: BLE001
            _set_status(f"Upload failed: {exc}", Colors.WARNING)
            return
        n = res.get("shot_count", "your")
        sent_payload["manifest"] = res.get("manifest")
        sent_payload["shots_csv"] = res.get("shots_csv")
        _set_status(
            f"Sent {n} shots to OpenGolfLab as “{active_name}” — thank you for "
            "contributing!\nUse the buttons below to save a receipt of exactly "
            "what was sent, and what the site will show for you.",
            Colors.SUCCESS)
        _refresh_receipts()

    btns = ctk.CTkFrame(card, fg_color="transparent")
    btns.pack(fill="x", pady=(4, 0))

    send_btn = theme.primary_button(btns, text="Send to OpenGolfLab",
                                    command=_send, width=180)
    send_btn.pack(side="right", padx=(6, 0))
    save_btn = theme.ghost_button(btns, text="Save a copy…",
                                  command=_export, width=120)
    save_btn.pack(side="right", padx=(6, 0))
    theme.ghost_button(btns, text="Close",
                       command=close, width=90).pack(side="right")

    # ---- receipts (the verification loop) ----
    # Two exports offered only after a successful send: the exact bytes that were
    # posted, and what opengolflab.org will publish for this contributor once it
    # aggregates them. The second is computed with the same rules as the site
    # (site_preview, a port of aggregate.py) so a person can reconcile the public
    # number against their own machine. See site_preview.py.
    theme.divider(card).pack(fill="x", pady=(12, 8))
    theme.section_label(card, "After sending — save a receipt",
                        color=Colors.INFO).pack(anchor="w", pady=(0, 2))
    theme.body_label(
        card, "Keep a record of exactly what you contributed, and check it "
        "against what the site publishes for you.",
        color=Colors.TEXT_MUTED, font=theme.font("caption"),
        wraplength=420, justify="left", anchor="w").pack(anchor="w", pady=(0, 6))

    receipt_btns = ctk.CTkFrame(card, fg_color="transparent")
    receipt_btns.pack(fill="x", pady=(0, 4))

    def _save_sent_payload():
        m, csv_text = sent_payload.get("manifest"), sent_payload.get("shots_csv")
        if not m:
            return
        out_root = filedialog.askdirectory(
            parent=root, title="Save a copy of exactly what was sent")
        if not out_root:
            return
        try:
            path = contribute.write_receipt_zip(m, csv_text, out_root)
        except Exception as exc:  # noqa: BLE001
            _set_status(f"Couldn't save the receipt: {exc}", Colors.WARNING)
            return
        _set_status(f"Saved what was sent:\n{path}", Colors.SUCCESS)

    def _save_site_preview():
        m, csv_text = sent_payload.get("manifest"), sent_payload.get("shots_csv")
        if not m:
            return
        import site_preview
        path = filedialog.asksaveasfilename(
            parent=root, title="Save the site preview",
            defaultextension=".json",
            initialfile=f"opengolflab_site_preview_{m.get('created_date', '')}.json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(site_preview.preview_json(csv_text, m))
        except Exception as exc:  # noqa: BLE001
            _set_status(f"Couldn't save the preview: {exc}", Colors.WARNING)
            return
        _set_status(f"Saved the site preview:\n{path}", Colors.SUCCESS)

    sent_btn = theme.ghost_button(receipt_btns, text="Export what was sent",
                                  command=_save_sent_payload, width=180)
    sent_btn.pack(side="left", padx=(0, 6))
    preview_btn = theme.ghost_button(receipt_btns, text="Export site preview",
                                     command=_save_site_preview, width=170)
    preview_btn.pack(side="left")

    def _refresh_receipts():
        state = "normal" if sent_payload.get("manifest") else "disabled"
        sent_btn.configure(state=state)
        preview_btn.configure(state=state)

    def _refresh_button():
        # Enable the action buttons only once consent is on AND at least one
        # round is selected — so nothing can be sent by accident.
        ready = consent_var.get() and bool(_selected_ids())
        state = "normal" if ready else "disabled"
        send_btn.configure(state=state)
        save_btn.configure(state=state)

    _refresh_receipts()
    _update_selected()
