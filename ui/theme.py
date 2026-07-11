"""
CustomTkinter theme setup and shared widget factories.

The old app mixed ttkbootstrap and customtkinter, which is a big part of
why it didn't feel visually consistent (different corner radii, fonts,
and hover behavior sitting side by side). This module is the single place
that knows how a button/label/card is supposed to look, built entirely on
customtkinter, so every screen shares the same design language.
"""
from __future__ import annotations

import customtkinter as ctk

from config import Colors, FONT_FAMILY, FONT_SCALE, SPACING


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
        corner_radius=10,
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


def primary_button(master, **kwargs) -> ctk.CTkButton:
    defaults = dict(
        fg_color=Colors.ACCENT,
        hover_color=Colors.ACCENT_HOVER,
        text_color=Colors.TEXT_ACTIVE,
        font=font("label", "bold"),
        corner_radius=8,
    )
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def outline_button(master, accent: str = Colors.SUCCESS, **kwargs) -> ctk.CTkButton:
    defaults = dict(
        fg_color="transparent",
        hover_color=Colors.BG_HOVER,
        border_width=2,
        border_color=accent,
        text_color=accent,
        font=font("label", "bold"),
        corner_radius=8,
    )
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def solid_button(master, color: str, hover: str, **kwargs) -> ctk.CTkButton:
    defaults = dict(
        fg_color=color,
        hover_color=hover,
        text_color=Colors.TEXT_ACTIVE,
        font=font("label", "bold"),
        corner_radius=8,
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


def divider(master, **kwargs) -> ctk.CTkFrame:
    defaults = dict(height=1, fg_color=Colors.BORDER)
    defaults.update(kwargs)
    return ctk.CTkFrame(master, **defaults)


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

    header = ctk.CTkFrame(card, fg_color="transparent")
    header.pack(fill="x", padx=12, pady=(10, 4))
    title_text = f"{icon}  {title}".strip() if icon else title
    ctk.CTkLabel(
        header, text=title_text, font=font("subheading", "bold"),
        text_color=Colors.ACCENT, fg_color="transparent", anchor="w",
    ).pack(side="left")

    divider(card).pack(fill="x", padx=12, pady=(0, 2))

    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=8, pady=(4, 10))
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
