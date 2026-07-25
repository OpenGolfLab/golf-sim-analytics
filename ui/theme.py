"""
CustomTkinter theme setup and shared widget factories.

The old app mixed ttkbootstrap and customtkinter, which is a big part of
why it didn't feel visually consistent (different corner radii, fonts,
and hover behavior sitting side by side). This module is the single place
that knows how a button/label/card is supposed to look, built entirely on
customtkinter, so every screen shares the same design language.
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from config import Colors, FONT_FAMILY, FONT_SCALE, SPACING

# ---------------------------------------------------------------------------
# Control metrics — the one set of numbers every interactive control is built
# from, so heights, corner radii and gaps line up by construction instead of
# by each call site guessing. Anything that reads as a "control" (button,
# dropdown chip, entry) uses CONTROL_HEIGHT/CONTROL_RADIUS; containers that
# read as a "surface" (cards, popups, panels) use SURFACE_RADIUS.
# ---------------------------------------------------------------------------
CONTROL_HEIGHT = 30
CONTROL_HEIGHT_SM = 24     # compact controls inside popups (All / None / Done)
CONTROL_RADIUS = 6
SURFACE_RADIUS = 10        # cards, dropdown panels, dialogs, toasts, tooltips
ICON_BUTTON_WIDTH = 36


def apply_global_theme() -> None:
    ctk.set_appearance_mode("dark")
    # Start from CTk's built-in "dark-blue" base and override the specific
    # colors we care about via widget kwargs below — a full custom theme
    # JSON is more brittle across customtkinter versions than overriding
    # per-widget, for the handful of widget types this app actually uses.
    ctk.set_default_color_theme("dark-blue")


def font(scale: str = "body", weight: str = "normal", italic: bool = False) -> ctk.CTkFont:
    size = FONT_SCALE.get(scale, FONT_SCALE["body"])
    slant = "italic" if italic else "roman"
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight, slant=slant)


# ---------------------------------------------------------------------------
# Widget factories — keep every screen visually consistent by construction.
# ---------------------------------------------------------------------------
def card_frame(master, **kwargs) -> ctk.CTkFrame:
    defaults = dict(
        fg_color=Colors.BG_SURFACE,
        border_width=1,
        border_color=Colors.BORDER,
        corner_radius=SURFACE_RADIUS,
    )
    defaults.update(kwargs)
    return ctk.CTkFrame(master, **defaults)


def sidebar_frame(master, **kwargs) -> ctk.CTkFrame:
    defaults = dict(fg_color=Colors.BG_SIDEBAR, corner_radius=0)
    defaults.update(kwargs)
    return ctk.CTkFrame(master, **defaults)


def section_label(master, text: str, color: str = Colors.TEXT_MUTED, **kwargs) -> ctk.CTkLabel:
    defaults = dict(
        text=text,
        font=font("label", "bold"),
        text_color=color,
        fg_color="transparent",
        anchor="w",
    )
    defaults.update(kwargs)
    return ctk.CTkLabel(master, **defaults)


def body_label(master, text: str, color: str = Colors.TEXT_PRIMARY, **kwargs) -> ctk.CTkLabel:
    defaults = dict(text=text, font=font("body"), text_color=color, fg_color="transparent")
    defaults.update(kwargs)
    return ctk.CTkLabel(master, **defaults)


# ---------------------------------------------------------------------------
# Button language.
#
# There are exactly three kinds of button, and the choice is driven by what the
# button *means*, never by wanting some color on screen:
#
#   ghost_button   — the default. Every ordinary action.
#   primary_button — the single most important action on a surface. At most one
#                    per surface (one per dialog; at most one in the top bar).
#   danger_button  — destructive and irreversible (delete a shot, delete a
#                    session). Red here is semantic, not decorative.
#
# This replaces the old `outline_button(accent=...)`, where each call site
# picked its own 2px accent border — so the top bar was a row of bronze / blue /
# green / gold pills that implied six unrelated categories where there was really
# just "things you can click". Color in this app now belongs to *state* (Go Live
# while live) and to *data* (CLUB_COLORS, semantic chart zones) only.
# ---------------------------------------------------------------------------
def ghost_button(master, **kwargs) -> ctk.CTkButton:
    """Quiet, flat action button — transparent until hovered."""
    defaults = dict(
        fg_color="transparent",
        hover_color=Colors.BG_HOVER,
        border_width=0,
        text_color=Colors.TEXT_PRIMARY,
        font=font("label"),
        corner_radius=CONTROL_RADIUS,
        height=CONTROL_HEIGHT,
    )
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def primary_button(master, **kwargs) -> ctk.CTkButton:
    defaults = dict(
        fg_color=Colors.ACCENT,
        hover_color=Colors.ACCENT_HOVER,
        text_color=Colors.TEXT_ON_LIGHT,
        font=font("label", "bold"),
        corner_radius=CONTROL_RADIUS,
        height=CONTROL_HEIGHT,
    )
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def danger_button(master, **kwargs) -> ctk.CTkButton:
    """Destructive action. Quiet like a ghost button until hovered, at which
    point it commits to red — the weight matches the consequence without the
    button shouting at you the whole time it's on screen."""
    defaults = dict(
        fg_color="transparent",
        hover_color=Colors.DANGER,
        border_width=1,
        border_color=Colors.DANGER,
        text_color=Colors.DANGER,
        font=font("label"),
        corner_radius=CONTROL_RADIUS,
        height=CONTROL_HEIGHT,
    )
    defaults.update(kwargs)
    btn = ctk.CTkButton(master, **defaults)
    # Red-on-red is unreadable once the hover fill lands, so lift the label to
    # near-white for the duration of the hover.
    btn.bind("<Enter>", lambda _e: btn.configure(text_color=Colors.TEXT_ACTIVE), add="+")
    btn.bind("<Leave>", lambda _e: btn.configure(text_color=Colors.DANGER), add="+")
    return btn


def chip_button(master, **kwargs) -> ctk.CTkButton:
    """A filter control: a hairline-bordered neutral chip. Distinct from
    ghost_button (which has no border) so the eye can separate "things that
    narrow what you're looking at" from "things that do something", while both
    stay in the same quiet neutral family."""
    defaults = dict(
        fg_color="transparent",
        hover_color=Colors.BG_HOVER,
        border_width=1,
        border_color=Colors.BORDER,
        text_color=Colors.TEXT_PRIMARY,
        font=font("body"),
        corner_radius=CONTROL_RADIUS,
        height=CONTROL_HEIGHT,
    )
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def solid_button(master, color: str, hover: str, **kwargs) -> ctk.CTkButton:
    defaults = dict(
        fg_color=color,
        hover_color=hover,
        text_color=Colors.TEXT_ACTIVE,
        font=font("label", "bold"),
        corner_radius=CONTROL_RADIUS,
    )
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def nav_checkbox(master, **kwargs) -> ctk.CTkCheckBox:
    defaults = dict(
        font=font("body"),
        text_color=Colors.TEXT_PRIMARY,
        fg_color=Colors.ACCENT,
        hover_color=Colors.ACCENT_HOVER,
        checkmark_color=Colors.TEXT_ACTIVE,
        border_color=Colors.BORDER,
    )
    defaults.update(kwargs)
    return ctk.CTkCheckBox(master, **defaults)


def toggle_switch(master, accent: str = Colors.SUCCESS, **kwargs) -> ctk.CTkSwitch:
    defaults = dict(
        font=font("body"),
        text_color=Colors.TEXT_PRIMARY,
        progress_color=accent,
        button_color=Colors.TEXT_ACTIVE,
    )
    defaults.update(kwargs)
    return ctk.CTkSwitch(master, **defaults)


def dropdown(master, values, variable, command=None, **kwargs) -> ctk.CTkComboBox:
    defaults = dict(
        values=values,
        variable=variable,
        command=command,
        font=font("body"),
        dropdown_font=font("body"),
        fg_color=Colors.BG_HOVER,
        border_color=Colors.BORDER,
        button_color=Colors.BG_HOVER,
        button_hover_color=Colors.ACCENT,
        text_color=Colors.TEXT_PRIMARY,
        dropdown_fg_color=Colors.BG_SURFACE,
        state="readonly",
    )
    defaults.update(kwargs)
    return ctk.CTkComboBox(master, **defaults)


# ---------------------------------------------------------------------------
# Rules / dividers.
#
# These are plain tk.Frames, and they are the one deliberate exception to this
# module's "everything is customtkinter" rule. A CTkFrame paints nothing at all
# below 2px on either axis — its canvas draw engine rounds the rounded-rect
# geometry away — so `CTkFrame(height=1)`, which is what divider() used to be,
# was invisible everywhere it was used: every section-card rule, every Settings
# and Contribute separator. A plain tk.Frame paints a true 1px hairline.
#
# There's no theming cost: a 1px rule has no font, hover, or corner radius to be
# inconsistent about — only a color, which still comes from Colors.BORDER.
# ---------------------------------------------------------------------------
def divider(master, **kwargs) -> tk.Frame:
    """A horizontal hairline rule. Pack/grid it with fill="x"."""
    defaults = dict(height=1, bg=Colors.BORDER, bd=0, highlightthickness=0)
    defaults.update(kwargs)
    return tk.Frame(master, **defaults)


def vdivider(master, **kwargs) -> tk.Frame:
    """A vertical hairline rule, for separating groups within a row. Pack it
    with fill="y"."""
    defaults = dict(width=1, bg=Colors.BORDER, bd=0, highlightthickness=0)
    defaults.update(kwargs)
    return tk.Frame(master, **defaults)


def readable_text_on(hex_color: str) -> str:
    """Black-ish or white text, whichever reads better on a solid `hex_color`
    fill. Lets section-card headers use any accent color and still keep the
    title legible (dark text on amber, white on indigo, etc.)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return Colors.TEXT_ON_LIGHT if luminance > 0.6 else Colors.TEXT_ACTIVE


def section_card(master, title: str, accent: str = Colors.ACCENT, icon: str = "", **kwargs):
    """A titled sidebar section. Header is flat bronze (the core accent) text
    with an icon, over a thin divider — matching the deep-bronze scheme — rather
    than a filled color band. `accent` is accepted for call-site compatibility
    but the header always uses the app accent so sections read uniformly.
    Returns (card, body); callers pack content into body.
    """
    card = card_frame(master, corner_radius=12, **kwargs)

    # Padding comes from SPACING rather than literals so every section card sits
    # on the same rhythm. The vertical values are deliberately the tight end of
    # the scale: the sidebar stacks six of these, and the old 10/4/2/4/10 spent
    # ~30px per card on padding alone — roughly a whole extra nav row's worth of
    # height across the menu, for chrome rather than content.
    header = ctk.CTkFrame(card, fg_color="transparent")
    header.pack(fill="x", padx=SPACING["md"], pady=(SPACING["sm"], SPACING["xs"] // 2))
    title_text = f"{icon}  {title}".strip() if icon else title
    # An eyebrow label, not a peer of the rows beneath it. This used to be
    # "subheading" bold — the same size the sidebar's nav items use — so
    # "Metrics Dashboards" and "Dispersion" rendered identically sized and the
    # header read as another item in the list rather than as the thing naming it.
    # Smaller + bold + bronze puts it clearly above the content in the hierarchy
    # while taking less vertical space, which the six-card sidebar needs.
    ctk.CTkLabel(
        header, text=title_text, font=font("caption", "bold"),
        text_color=Colors.ACCENT, fg_color="transparent", anchor="w",
    ).pack(side="left")

    divider(card).pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["xs"] // 2))

    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=SPACING["sm"],
              pady=(SPACING["xs"] // 2, SPACING["sm"]))
    # Exposed so a caller can add a trailing widget on the title row (packed
    # side="right"), e.g. the Community section's Fuel-the-Lab link.
    card.header = header
    return card, body


def add_hover_border(widget, hover_border: str = Colors.BORDER_HOVER, normal_border: str = Colors.BORDER) -> None:
    """Subtle border highlight on hover for card-style frames."""
    def _enter(_event):
        try:
            widget.configure(border_color=hover_border)
        except Exception:
            pass

    def _leave(_event):
        try:
            widget.configure(border_color=normal_border)
        except Exception:
            pass

    widget.bind("<Enter>", _enter, add="+")
    widget.bind("<Leave>", _leave, add="+")
