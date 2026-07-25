"""
"This is what you sent to OpenGolfLab" — the post-contribution snapshot.

Shown the moment an upload succeeds, before the user goes anywhere else. It
exists because contributing is the one action in this app that publishes
something: everything else is local, reversible, and private. A user who has
just made data public deserves to see exactly what became public, at the moment
it happened, without having to opt in to finding out.

Two things are on screen:

  * the identity block — the public name their data is attributed to, plus the
    handicap / age bands, launch monitor, ball and equipment that go with it.
    These are the fields that describe *them*, so they're the ones worth
    double-checking.
  * the per-club medians. The upload carries per-shot rows, but The Lab plots one
    dot per contributor per club (ui/charts/community.py), so the median is the
    number that actually shows up publicly with their name on it. Showing the raw
    shot count alone would technically be "what was sent" while hiding the thing
    a user would recognise as theirs on the site.

Everything rendered here comes from contribute.summarize_bundle(), which reads
the medians back out of the shots.csv *text* that was POSTed — not from the
DataFrame it was built from. So this is a description of the bytes that left the
machine, and it cannot drift from them.
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

import contribute
from config import Colors, SPACING, get_club_color
from ui import theme
from ui.dialogs import show_toast

# Column widths in characters, for the medians table. Fixed so the header and
# every row land on the same grid without a real table widget.
_CLUB_W = 6
_N_W = 5
_VAL_W = 12


def _row_text(cells: list[str], widths: list[int]) -> str:
    return "".join(text.rjust(w) for text, w in zip(cells, widths))


def show_sent_snapshot(root, manifest: dict, shots_csv: str, *, on_save_receipt=None):
    """Modal snapshot of a completed contribution.

    ``on_save_receipt`` is the dialog's "Save the full bundle" action — wired to
    the existing receipt export so this screen doesn't grow a second, parallel
    way of writing the same zip.
    """
    summary = contribute.summarize_bundle(manifest, shots_csv)

    win = ctk.CTkToplevel(root)
    win.title("What was sent to OpenGolfLab")
    win.configure(fg_color=Colors.BG_BASE)
    win.transient(root)
    # Modal: this is a confirmation of something irreversible, so it shouldn't be
    # possible to lose it behind the main window and never read it.
    try:
        win.grab_set()
    except tk.TclError:
        pass

    outer = ctk.CTkFrame(win, fg_color="transparent")
    outer.pack(fill="both", expand=True, padx=SPACING["lg"], pady=SPACING["lg"])

    ctk.CTkLabel(outer, text="✓  Sent to OpenGolfLab", font=theme.font("title", "bold"),
                 text_color=Colors.SUCCESS, anchor="w").pack(fill="x")
    ctk.CTkLabel(
        outer,
        text=f"{summary['shot_count']} shots are now part of the community data set. "
             "This is exactly what left your machine — read back from the upload "
             "itself, not rebuilt from your files.",
        font=theme.font("caption"), text_color=Colors.TEXT_MUTED,
        wraplength=620, justify="left", anchor="w",
    ).pack(fill="x", pady=(SPACING["xs"], SPACING["md"]))

    # Tall enough that a full bag plus the identity block clears the fold on a
    # normal display — a 13-club bag at 380px put the wedges below it, and the
    # wedges are exactly what someone checks. Still scrolls when it has to.
    body = ctk.CTkScrollableFrame(outer, fg_color="transparent", width=640, height=470,
                                  scrollbar_button_color=Colors.BG_HOVER,
                                  scrollbar_button_hover_color=Colors.BORDER_HOVER)
    body.pack(fill="both", expand=True)

    # ---- identity -------------------------------------------------------
    id_card, id_body = theme.section_card(body, "Attributed to you")
    id_card.pack(fill="x", pady=(0, SPACING["sm"]))
    for label, value in summary["identity"]:
        row = ctk.CTkFrame(id_body, fg_color="transparent")
        row.pack(fill="x", pady=SPACING["xxs"])
        ctk.CTkLabel(row, text=label, font=theme.font("caption"),
                     text_color=Colors.TEXT_MUTED, width=130, anchor="w").pack(side="left")
        ctk.CTkLabel(row, text=str(value), font=theme.font("body"),
                     text_color=Colors.TEXT_PRIMARY, anchor="w",
                     wraplength=440, justify="left").pack(side="left", fill="x", expand=True)

    # ---- per-club medians ----------------------------------------------
    med_card, med_body = theme.section_card(body, "Per-club medians on The Lab")
    med_card.pack(fill="x", pady=(0, SPACING["sm"]))

    if not summary["clubs"]:
        ctk.CTkLabel(med_body, text="No clubs in this bundle.", font=theme.font("body"),
                     text_color=Colors.TEXT_MUTED, anchor="w").pack(fill="x")
    else:
        widths = [_CLUB_W, _N_W] + [_VAL_W] * len(summary["fields"])
        header = _row_text(["Club", "n"] + [label for _f, label, _u in summary["fields"]],
                           widths)
        # A monospaced font so the character-width columns actually line up; the
        # UI font is proportional and would leave the numbers ragged.
        mono = ctk.CTkFont(family="Consolas", size=12)
        mono_bold = ctk.CTkFont(family="Consolas", size=12, weight="bold")

        ctk.CTkLabel(med_body, text=header, font=mono_bold, text_color=Colors.TEXT_MUTED,
                     anchor="w", justify="left").pack(fill="x")
        theme.divider(med_body).pack(fill="x", pady=(SPACING["xxs"], SPACING["xs"]))

        for row in summary["clubs"]:
            cells = [row["club"], str(row["n"])]
            for field, _label, _unit in summary["fields"]:
                v = row["medians"].get(field)
                cells.append("—" if v is None else f"{v:.1f}")
            line = ctk.CTkFrame(med_body, fg_color="transparent")
            line.pack(fill="x")
            # The club's own colour on the name, matching every chart in the app,
            # so a user can tie a row here to the dot they'll see on the site.
            ctk.CTkLabel(line, text=row["club"].rjust(_CLUB_W), font=mono_bold,
                         text_color=get_club_color(row["club"]), anchor="w").pack(side="left")
            ctk.CTkLabel(line, text=_row_text(cells[1:], widths[1:]), font=mono,
                         text_color=Colors.TEXT_PRIMARY, anchor="w").pack(side="left")

        ctk.CTkLabel(
            med_body,
            text="Units: yards, mph, degrees, rpm. Medians are computed from the "
                 "shots in this upload — the site derives its own from the same rows.",
            font=theme.font("caption"), text_color=Colors.TEXT_MUTED,
            wraplength=560, justify="left", anchor="w",
        ).pack(fill="x", pady=(SPACING["sm"], 0))

    # ---- actions --------------------------------------------------------
    actions = ctk.CTkFrame(outer, fg_color="transparent")
    actions.pack(fill="x", pady=(SPACING["md"], 0))

    def _copy():
        try:
            win.clipboard_clear()
            win.clipboard_append(contribute.summary_text(summary))
            show_toast(root, "Snapshot copied to the clipboard.", tone="success")
        except tk.TclError:
            show_toast(root, "Couldn't reach the clipboard.", tone="warning")

    def _close():
        try:
            win.grab_release()
        except tk.TclError:
            pass
        win.destroy()

    theme.primary_button(actions, text="Done", command=_close, width=110).pack(side="right")
    if on_save_receipt is not None:
        theme.ghost_button(actions, text="Save the full bundle…",
                           command=on_save_receipt, width=170).pack(
            side="right", padx=(SPACING["sm"], 0))
    theme.ghost_button(actions, text="Copy as text", command=_copy, width=130).pack(
        side="right", padx=(SPACING["sm"], 0))

    win.protocol("WM_DELETE_WINDOW", _close)
    win.update_idletasks()
    # Centre on the app window rather than the screen — with a multi-monitor sim
    # setup the app is often not on the primary display.
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    x = root.winfo_rootx() + (root.winfo_width() - w) // 2
    y = root.winfo_rooty() + (root.winfo_height() - h) // 3
    win.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
    win.focus_set()
    return win
