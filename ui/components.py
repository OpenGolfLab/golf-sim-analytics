"""
Reusable popup-dropdown widgets shared across the app.

CTkComboBox's default interaction (a small arrow-only click target,
single-select only) didn't match what we wanted once the Club Gapping
panel got a "click the whole button, checklist popup, All/None" pattern
for picking clubs. This module generalizes that pattern into two pieces
so every dropdown in the app — Time Filter, Club Filter, Shot Quality,
Dispersion's Carry/Total, and both club checklists — looks and behaves
the same way:

- SingleSelectDropdown: pick exactly one option from a fixed list
  (Time Filter, Shot Quality, Carry/Total). Clicking any row selects it
  and closes the popup immediately.
- MultiSelectDropdown: pick any subset of a checklist, with All/None
  quick actions and a Done button (the global Club Filter, and the Club
  Gapping panel's own per-club toggle).
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from config import Colors, FONT_FAMILY, FONT_SCALE
from ui import theme


def _fit_width(texts, extra: int = 24, min_w: int = 120, max_w: int = 360,
               size_name: str = "body") -> int:
    """Width (unscaled CTk units) that fits the widest of `texts` at the
    `size_name` font, plus `extra` px of chrome (checkbox, padding), clamped to
    [min_w, max_w]. Keeps dropdown popups from truncating long items (e.g.
    'Jul 08, 2026 · 42 shots [stiff-tip]') while never running off-screen."""
    try:
        f = tkfont.Font(family=FONT_FAMILY, size=FONT_SCALE[size_name])
        widest = max((f.measure(str(t)) for t in texts), default=0)
    except tk.TclError:
        widest = 0
    return max(min_w, min(max_w, widest + extra))


class _PopupDropdownBase(ctk.CTkFrame):
    """Shared plumbing: a button that opens/closes a small popup card
    positioned just below it, and closes on click-away, Escape, or the
    parent window moving/resizing.

    Dismissal is driven by bindings on the parent *toplevel*, not on the
    popup: the popup is an overrideredirect window, which on Windows never
    receives keyboard focus, so its own Escape/FocusOut bindings never fire
    — and a plain click on a label/frame doesn't move focus anyway. Every
    widget's default bindtags include its toplevel, so one add="+" binding
    on the toplevel sees clicks on any widget in the window, which is what
    makes click-away work regardless of focus.
    """

    def __init__(self, master, accent=Colors.INFO, width=170, **kwargs):
        # `accent` is accepted and ignored. Every dropdown used to draw its own
        # 2px accent border in whatever color the call site felt like, which is
        # what made a screen of filters read as unrelated toys. They're all one
        # neutral chip now; the parameter stays so the ~20 existing call sites
        # don't need churn, and so a caller can't accidentally reintroduce a
        # per-dropdown color by passing it.
        super().__init__(master, fg_color="transparent")
        self._popup: ctk.CTkToplevel | None = None
        self._root_binds_installed = False
        self.button = theme.chip_button(self, command=self._toggle_popup, width=width)
        self.button.pack()

    def _toggle_popup(self):
        if self._popup_open():
            self._close_popup()
        else:
            self._open_popup()

    def _popup_open(self) -> bool:
        return self._popup is not None and self._popup.winfo_exists()

    def _install_root_binds(self):
        """One-time add="+" bindings on the parent toplevel (see class
        docstring). Installed lazily on first open and left in place — each
        handler no-ops unless this dropdown's popup is currently open, so
        there's nothing to unbind (Tkinter's unbind-by-funcid is unreliable
        across versions and would risk removing other handlers)."""
        if self._root_binds_installed:
            return
        self._root_binds_installed = True
        root = self.winfo_toplevel()
        root.bind("<ButtonPress>", self._on_root_click, add="+")
        root.bind("<Escape>", lambda _e: self._close_popup(), add="+")
        root.bind("<Configure>", self._on_root_configure, add="+")
        # Minimizing the app must take the popup with it: the popup is an
        # overrideredirect+topmost toplevel the window manager doesn't tie to
        # the main window, so without this it stays floating over other apps.
        root.bind("<Unmap>", self._on_root_unmap, add="+")

    def _on_root_unmap(self, event):
        # Children also fire <Unmap> (e.g. pack_forget) — only the toplevel's
        # own unmap means the app was minimized/hidden.
        if self._popup_open() and str(event.widget) == str(self.winfo_toplevel()):
            self._close_popup()

    def _on_root_click(self, event):
        """Click-away: any press in the parent window closes the popup.
        Clicks *inside* the popup land on the popup's own toplevel and never
        reach this handler; a press on the opener button is excluded so the
        button's own command handles the toggle (otherwise this would close
        on press and the command would immediately reopen on release)."""
        if not self._popup_open():
            return
        bx, by = self.button.winfo_rootx(), self.button.winfo_rooty()
        if (bx <= event.x_root < bx + self.button.winfo_width()
                and by <= event.y_root < by + self.button.winfo_height()):
            return
        self._close_popup()

    def _on_root_configure(self, event):
        # The popup is positioned absolutely, so it would float detached if
        # the window moves or resizes underneath it — just dismiss it. Only
        # the toplevel's own Configure counts (children fire this too).
        if self._popup_open() and str(event.widget) == str(self.winfo_toplevel()):
            self._close_popup()

    def _open_popup_shell(self) -> ctk.CTkFrame:
        """Create the popup window + card frame; subclasses fill in the card."""
        self._install_root_binds()
        self._popup = ctk.CTkToplevel(self)
        self._popup.overrideredirect(True)
        self._popup.attributes("-topmost", True)
        self._popup.configure(fg_color=Colors.BG_SURFACE)

        x = self.button.winfo_rootx()
        y = self.button.winfo_rooty() + self.button.winfo_height() + 2
        self._popup.geometry(f"+{x}+{y}")

        card = theme.card_frame(self._popup, corner_radius=theme.SURFACE_RADIUS)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        # Kept for platforms where the popup does take focus (harmless
        # elsewhere): Escape / focus-loss inside the popup still dismiss.
        self._popup.bind("<Escape>", lambda e: self._close_popup())
        self._popup.bind("<FocusOut>", self._on_popup_focus_out)
        return card

    def _on_popup_focus_out(self, event):
        # A child widget (e.g. the scrollbar) taking focus within the same
        # popup also fires FocusOut — only actually close if focus left
        # the popup entirely.
        self.after(50, self._close_if_unfocused)

    def _close_if_unfocused(self):
        if self._popup is None or not self._popup.winfo_exists():
            return
        if self._popup.focus_get() is None:
            self._close_popup()

    def _close_popup(self):
        if self._popup is not None:
            self._popup.destroy()
            self._popup = None

    def _open_popup(self):
        raise NotImplementedError


class DropdownPanel:
    """A large dropdown *surface* — a scrollable panel that drops down anchored
    beneath an existing trigger widget (a top-bar button), instead of opening as
    a separate floating window you have to drag around.

    Same dismissal model as the small select popups (_PopupDropdownBase): the
    panel closes on a click anywhere else in the window, on Escape, or when the
    window moves/resizes underneath it. Unlike _PopupDropdownBase it doesn't own
    its own button — the caller passes the trigger widget to anchor under and a
    ``build_content(parent, close)`` callback that fills the scrollable body.

    Used for Settings / Contribute / Manage Sessions, which used to each open a
    CTkToplevel window.
    """

    def __init__(self, anchor, build_content, *, width: int = 460,
                 on_close=None):
        self.anchor = anchor
        self.build_content = build_content
        self.width = width
        self.on_close = on_close
        self._popup: ctk.CTkToplevel | None = None
        self._root_binds_installed = False

    def is_open(self) -> bool:
        return self._popup is not None and self._popup.winfo_exists()

    def toggle(self):
        if self.is_open():
            self.close()
        else:
            self.open()

    def open(self):
        if self.is_open():
            self.anchor.after(10, self._reposition)
            return
        root = self.anchor.winfo_toplevel()
        self._install_root_binds(root)

        self._popup = ctk.CTkToplevel(self.anchor)
        self._popup.overrideredirect(True)
        self._popup.attributes("-topmost", True)
        self._popup.configure(fg_color=Colors.BG_SURFACE)
        self._popup.bind("<Escape>", lambda _e: self.close())

        outer = theme.card_frame(self._popup, corner_radius=theme.SURFACE_RADIUS)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        self._body = ctk.CTkScrollableFrame(
            outer, fg_color="transparent", width=self.width,
            scrollbar_button_color=Colors.BG_HOVER)
        self._body.pack(fill="both", expand=True, padx=4, pady=4)

        # Content goes into a plain frame inside the scroll body, not into the
        # scroll body itself, purely so we have something whose reqheight is the
        # *natural* height of the content. A CTkScrollableFrame always reports
        # its own fixed height (CTk's ~200px default when none is given), which
        # is why every panel used to open 200px tall and immediately scroll —
        # Settings worst of all. See _reposition.
        self._content = ctk.CTkFrame(self._body, fg_color="transparent")
        self._content.pack(fill="both", expand=True)

        self.build_content(self._content, self.close)
        self._reposition()

    _MARGIN_BOTTOM = 12
    _MIN_H = 80    # floor for a pathologically short window; below this, scroll
    _CHROME_FALLBACK = 22  # only used before the popup has been laid out once
    # Tall panels stop at ~2/3 of the window height and scroll from there,
    # rather than running to the window's bottom edge — a panel that drapes the
    # full height reads as a page, not a menu, and the content near the bottom
    # ended up cramped against the window edge.
    _MAX_FRACTION = 2 / 3

    def _chrome(self) -> int:
        """Pixels the popup needs *on top of* the content height: our card
        border and pads, plus CTkScrollableFrame's own internal padding.

        Measured rather than hard-coded, because part of it comes from CTk
        internals and a wrong guess is exactly the bug this class had — being
        8px short is what clips the last line of a panel and leaves a scrollbar
        on content that would otherwise fit. Falls back to a constant if CTk's
        private canvas attribute ever moves.
        """
        canvas = getattr(self._body, "_parent_canvas", None)
        if canvas is None or canvas.winfo_height() <= 1:
            return self._CHROME_FALLBACK
        return max(0, self._popup.winfo_height() - canvas.winfo_height())

    def _reposition(self):
        if not self.is_open():
            return
        popup = self._popup
        popup.update_idletasks()

        ax, ay = self.anchor.winfo_rootx(), self.anchor.winfo_rooty()
        below = ay + self.anchor.winfo_height() + 2

        # Room available: capped at _MAX_FRACTION of the app window's height
        # (and never past the window or screen). The app window — not the
        # screen — is the bound on purpose: a panel hanging past the window
        # onto the desktop behind it looks broken.
        root = self.anchor.winfo_toplevel()
        window_bottom = root.winfo_rooty() + root.winfo_height()
        cap_bottom = root.winfo_rooty() + int(root.winfo_height() * self._MAX_FRACTION)
        available = (min(cap_bottom, window_bottom, popup.winfo_screenheight())
                     - below - self._MARGIN_BOTTOM)

        sw = popup.winfo_screenwidth()
        w = min(max(self.width + 24, popup.winfo_reqwidth()), sw - 16)
        x = min(ax, max(0, sw - w - 8))

        # Two passes: _chrome() can only be measured once the popup has been
        # laid out at some height, so size it, look at what actually
        # materialized, then size it for real.
        for _ in range(2):
            # Natural height of the *content*, never the scroll viewport — a
            # CTkScrollableFrame always reports its own fixed height.
            natural = self._content.winfo_reqheight() + self._chrome()
            # Short content hugs its natural height (no dead space); tall
            # content stops at the window edge and scrolls from there.
            h = max(self._MIN_H, min(natural, available))
            popup.geometry(f"{w}x{h}+{x}+{below}")
            popup.update_idletasks()

    def _install_root_binds(self, root):
        if self._root_binds_installed:
            return
        self._root_binds_installed = True
        root.bind("<ButtonPress>", self._on_root_click, add="+")
        root.bind("<Escape>", lambda _e: self.close(), add="+")
        root.bind("<Configure>", self._on_root_configure, add="+")
        # Minimizing the app must take the panel with it (overrideredirect +
        # topmost windows otherwise keep floating over other applications).
        root.bind("<Unmap>", self._on_root_unmap, add="+")

    def _on_root_unmap(self, event):
        if self.is_open() and str(event.widget) == str(self.anchor.winfo_toplevel()):
            self.close()

    def _on_root_click(self, event):
        # A click inside the panel lands on the panel's own toplevel and never
        # reaches this handler; a press on the trigger widget is excluded so its
        # command can toggle us (otherwise we'd close on press and immediately
        # reopen on release). Any other press in the window dismisses.
        if not self.is_open():
            return
        ax, ay = self.anchor.winfo_rootx(), self.anchor.winfo_rooty()
        if (ax <= event.x_root < ax + self.anchor.winfo_width()
                and ay <= event.y_root < ay + self.anchor.winfo_height()):
            return
        self.close()

    def _on_root_configure(self, event):
        if self.is_open() and str(event.widget) == str(self.anchor.winfo_toplevel()):
            self.close()

    def close(self):
        if self._popup is not None:
            self._popup.destroy()
            self._popup = None
        if self.on_close:
            self.on_close()


def menu_item(parent, text: str, command, *, width: int = 240) -> ctk.CTkButton:
    """One row of a dropdown menu (see DropdownPanel).

    A full-width, left-aligned ghost button — a button rather than a bound label
    so it inherits the standard hover / pressed / disabled states instead of
    reimplementing them per menu. One step up from the default control font
    ("subheading" vs "label") so menu rows read as their own list, a touch
    larger than the top-bar triggers that open them.
    """
    btn = theme.ghost_button(parent, text=text, command=command, anchor="w",
                             width=width, font=theme.font("subheading"),
                             height=theme.CONTROL_HEIGHT + 4)
    btn.pack(fill="x", pady=1)
    return btn


class SingleSelectDropdown(_PopupDropdownBase):
    """Exactly one choice from a fixed list of mutually-exclusive options.

    There's no All/None here on purpose — "All Time" + "Last Session" at
    once isn't a meaningful combination, so this stays single-select.
    """

    def __init__(self, master, options: list[str], variable: tk.StringVar,
                 on_change=None, accent=Colors.INFO, width=170, **kwargs):
        super().__init__(master, accent=accent, width=width, **kwargs)
        self.options = options
        self.variable = variable
        self.on_change = on_change
        self._refresh_button_label()

    def _refresh_button_label(self):
        self.button.configure(text=f"{self.variable.get()} ▾")

    def _open_popup(self):
        card = self._open_popup_shell()
        list_frame = ctk.CTkFrame(card, fg_color="transparent")
        list_frame.pack(padx=4, pady=4)

        # Option rows read at "label" size — a step up from body text, so the
        # things you're choosing between are the most legible part of the popup.
        opt_w = _fit_width(self.options, extra=28, size_name="label")
        current = self.variable.get()
        for option in self.options:
            is_selected = option == current
            ctk.CTkButton(
                list_frame,
                text=option,
                anchor="w",
                fg_color=Colors.BG_HOVER if is_selected else "transparent",
                hover_color=Colors.BG_HOVER,
                text_color=Colors.TEXT_ACTIVE if is_selected else Colors.TEXT_PRIMARY,
                font=theme.font("label", "bold" if is_selected else "normal"),
                corner_radius=6,
                width=opt_w,
                height=theme.CONTROL_HEIGHT,
                command=lambda o=option: self._select(o),
            ).pack(fill="x", pady=1)

    def _select(self, option):
        self.variable.set(option)
        self._refresh_button_label()
        self._close_popup()
        if self.on_change:
            self.on_change()


class MultiSelectDropdown(_PopupDropdownBase):
    """Any subset of a checklist, with All / None quick actions and Done.

    `variables` is a dict of {item_name: tk.BooleanVar}. Toggling a
    checkbox (or All/None) fires `on_change` immediately — there's no
    separate "Apply"; Done just closes the popup.
    """

    def __init__(self, master, variables: dict[str, tk.BooleanVar], on_change=None,
                 accent=Colors.SUCCESS, width=170, item_label="Items", item_colors=None,
                 max_selected: int | None = None, on_limit_exceeded=None, **kwargs):
        super().__init__(master, accent=accent, width=width, **kwargs)
        self.variables = variables
        self.on_change = on_change
        self.item_label = item_label
        # Optional {item_name: hex_color} so each checkbox can tick in the
        # same color as that item's series in the chart (e.g. Club Filter
        # checkmarks matching each club's dispersion-chart color).
        self.item_colors = item_colors or {}
        # Optional cap on how many items can be checked at once (e.g. Session
        # Comparison's 4-session limit) — checking one more than the cap
        # allows reverts that checkbox and calls on_limit_exceeded (e.g. a
        # toast), rather than silently accepting a selection the chart would
        # just truncate anyway.
        self.max_selected = max_selected
        self.on_limit_exceeded = on_limit_exceeded
        self._refresh_button_label()

    def refresh_options(self):
        """Call after `variables` has entries added/removed (e.g. new data
        ingested) so the button label and any open popup stay accurate.
        """
        self._refresh_button_label()
        if self._popup is not None and self._popup.winfo_exists():
            self._close_popup()
            self._open_popup()

    def _refresh_button_label(self):
        total = len(self.variables)
        selected = sum(1 for v in self.variables.values() if v.get())
        if total == 0:
            label = f"No {self.item_label}"
        elif selected == total:
            label = f"All {total} {self.item_label} ▾"
        elif selected == 0:
            label = f"No {self.item_label} ▾"
        else:
            label = f"{selected}/{total} {self.item_label} ▾"
        self.button.configure(text=label)

    def _open_popup(self):
        card = self._open_popup_shell()

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=8, pady=(8, 4))
        # All / None are secondary shortcuts; Done is the one primary action in
        # this popup — the same one-primary-per-surface rule the top bar follows.
        theme.chip_button(
            actions, text="All", width=60, height=theme.CONTROL_HEIGHT_SM,
            font=theme.font("caption"), command=self._select_all,
        ).pack(side="left", padx=(0, 4))
        theme.chip_button(
            actions, text="None", width=60, height=theme.CONTROL_HEIGHT_SM,
            font=theme.font("caption"), command=self._select_none,
        ).pack(side="left")
        theme.primary_button(
            actions, text="Done", width=60, height=theme.CONTROL_HEIGHT_SM,
            font=theme.font("caption", "bold"), command=self._close_popup,
        ).pack(side="right")

        list_height = min(360, max(1, len(self.variables)) * 32 + 10)
        # Fit the widest item label (plus the checkbox + scrollbar chrome) so
        # long labels don't truncate inside the checklist.
        scroll_w = _fit_width(self.variables.keys(), extra=54, size_name="label")
        scroll = ctk.CTkScrollableFrame(
            card, width=scroll_w, height=list_height, fg_color="transparent",
        )
        scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        for item_name, var in self.variables.items():
            color = self.item_colors.get(item_name)
            extra = dict(fg_color=color, hover_color=color, border_color=color) if color else {}
            theme.nav_checkbox(
                scroll, text=item_name, variable=var, font=theme.font("label"),
                command=lambda n=item_name: self._on_check(n), **extra,
            ).pack(anchor="w", pady=2, fill="x")

    def _select_all(self):
        if self.max_selected is not None:
            over = len(self.variables) > self.max_selected
            for i, var in enumerate(self.variables.values()):
                var.set(i < self.max_selected)
            if over and self.on_limit_exceeded:
                self.on_limit_exceeded()
        else:
            for var in self.variables.values():
                var.set(True)
        self._refresh_button_label()
        if self.on_change:
            self.on_change()

    def _select_none(self):
        for var in self.variables.values():
            var.set(False)
        self._refresh_button_label()
        if self.on_change:
            self.on_change()

    def _on_check(self, item_name=None):
        if (self.max_selected is not None and item_name is not None
                and self.variables[item_name].get()):
            selected = sum(1 for v in self.variables.values() if v.get())
            if selected > self.max_selected:
                self.variables[item_name].set(False)
                self._refresh_button_label()
                if self.on_limit_exceeded:
                    self.on_limit_exceeded()
                return
        self._refresh_button_label()
        if self.on_change:
            self.on_change()
