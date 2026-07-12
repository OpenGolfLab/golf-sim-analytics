"""
Main application window — orchestration only.

This class owns the Tkinter widget tree and wires the config/data/ui
modules together. Notable mechanics that live here:

- build_grid() is *diff-based*: toggling one dashboard adds/removes only
  that panel instead of destroying and re-rendering every active chart
  (which is what made clicking around feel slow).
- _bind_figure_autosize() routes resizes through matplotlib's own
  FigureCanvasTk.resize(), because binding <Configure> directly (as this
  used to) silently REPLACES the backend's internal binding — the only
  code that resizes the Tk photoimage backing the canvas. On matplotlib
  >= 3.8 that left panels blitting into a stale 200x200 image (mostly
  white). The debounce is kept so a drag still costs one redraw, not one
  per pixel.
- All user feedback goes through themed toasts (ui.dialogs), never native
  OS messageboxes.

Historical data has no manual "ingest" step: raw_csvs/ is polled in the
background (see _poll_raw_csv_dir) and anything dropped there, whether by
hand or by data.export_watcher copying it in from the Desktop, is
ingested automatically.

Live tracking (see live.round_watcher.LiveRoundWatcher) polls GSPro's own
currentRound.dat for the round/range session currently in progress and
runs continuously in the background regardless of whether the "Go Live"
panel is on screen — the panel just controls whether you're *watching*
shots land in the Live Dispersion dashboard, not whether they're being
tracked and archived.
"""
from __future__ import annotations

import logging
import sys
import tkinter as tk
from types import SimpleNamespace

import customtkinter as ctk
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import config
from config import Colors, get_club_rank
from data import filters as filters_mod
from data import adapter_tags, edits as edits_mod, on_course, settings as settings_mod
from data.analytics import EnvironmentalNormalizer, ShotScorer
from data.columns import BALL_SPEED_ALIASES, CLUB_SPEED_ALIASES, find_col
from data.export_watcher import ExportWatcher
from data.io import ingest_all_csvs
from data.store import (
    compute_home_stats, compute_home_trends, compute_player_records, load_master_dataframe,
)
from live.gspro_db import ClubDataLookup
from live.round_watcher import LiveRoundWatcher
from ui import theme
from ui.club_config_dialog import open_club_config_dialog
from ui.manage_sessions_dialog import open_manage_sessions_dialog
from ui.shot_edit_popup import open_shot_edit_popup
from ui.tooltip import attach_tooltip
from ui.charts import session_compare
from ui.charts.club_compare import NAME as CLUB_COMPARE_NAME
from ui.charts.session_compare import NAME as SESSION_COMPARE_NAME
from ui.charts.shot_timeline import NAME as TIMELINE_NAME
from ui.charts.speed_training import NAME as TRAINING_NAME
from ui.charts.dispersion import NAME as DISPERSION_NAME
from ui.charts.gapping import NAME as GAPPING_NAME
from ui.charts.launch_spin import NAME as LAUNCH_SPIN_NAME
from ui.charts.live_dispersion import NAME as LIVE_NAME
from ui.charts.on_course_dashboard import NAME as ONCOURSE_NAME
from ui.charts.registry import DASHBOARDS
from ui.charts.trajectory import NAME as TRAJECTORY_NAME
from ui.components import MultiSelectDropdown, SingleSelectDropdown
from ui.dialogs import show_toast
from ui.empty_state import show_message
from ui.home_page import build_home_page, course_banner

log = logging.getLogger(__name__)

MAX_ACTIVE_PLOTS = 2
MAX_GRID_ROWS = 10  # generous upper bound used to fully reset row weights each rebuild

# "Solo" dashboards are dense, multi-panel composites that only read well
# filling the whole screen, so they take over the grid alone (like Live) —
# selecting one clears everything else, and they can't be paired with another.
SOLO_DASHBOARDS = frozenset({TRAINING_NAME, CLUB_COMPARE_NAME, ONCOURSE_NAME})

# Club Comparison "Now hitting" sentinel: not logging to any config.
_CC_OFF = "Off"

CATEGORY_HEADER_COLOR = {
    "Metrics": Colors.SUCCESS,
    "Optimization": Colors.INFO,
    "Club Fitting": Colors.WARNING,
    "Speed Training": Colors.DANGER,
    "On Course": Colors.SUCCESS,
    "Live": Colors.WARNING,
}

# Panel-entry keys that belong to a chart figure and must be dropped when
# the panel is destroyed.
_PANEL_STATE_KEYS = ("panel", "fig", "canvas", "rendered_once", "bucket")


class SimAnalyticsApp:
    def __init__(self, root: ctk.CTk, ui_scale: float = 1.0):
        self.root = root
        self.ui_scale = ui_scale
        self.root.title("Golf Sim Analytics")
        self.root.configure(fg_color=Colors.BG_BASE)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Persistent app-level preferences (display scale, on-course handling).
        # In-memory-only view toggles (temp norm, warm-up, demo) still live in
        # their own Tk vars below — only the settings that should survive a
        # restart are backed by this.
        self._settings = settings_mod.load()
        self.settings_ui_scale = tk.StringVar(value=self._settings.get("ui_scale", "Auto"))
        # On-course play handling (persisted).
        self.settings_drop_mulligans = tk.BooleanVar(
            value=self._settings.get("drop_mulligans", False))
        self.settings_exclude_on_course = tk.BooleanVar(
            value=self._settings.get("exclude_on_course_from_practice", True))

        self.master_df = pd.DataFrame()  # practice-analytics view (populated below)
        # Full history including on-course rounds — the practice dashboards read
        # master_df (course play filtered out), but records/live PBs and the
        # on-course dashboard need the complete set.
        self._full_df = pd.DataFrame()

        # Watches GSPro's own CSV export folder (Desktop by default — see
        # config.EXPORT_WATCH_DIR) and auto-copies + auto-ingests anything
        # new, so a round exported from GSPro shows up here with zero
        # manual steps. Runs continuously in the background for the life
        # of the app.
        self.export_watcher = ExportWatcher(
            watch_dir=config.EXPORT_WATCH_DIR,
            raw_csv_dir=config.RAW_CSV_DIR,
            data_dir=config.DATA_DIR,
            on_new_data=self._on_export_watcher_data,
            schedule_on_main_thread=lambda fn: self.root.after(0, fn),
            poll_interval=config.EXPORT_WATCH_POLL_SECONDS,
        )

        # Shots for whatever round is currently in progress, per
        # live.round_watcher — same list object as
        # plot_state[LIVE_NAME]["live_shots"] (set up in
        # _build_plot_state), so appending here is all the live panel
        # needs to pick up the next shot. Cleared once the round archives.
        self.live_shot_buffer: list[dict] = []
        self.round_watcher = LiveRoundWatcher(
            round_file=config.GSPRO_ROUND_FILE,
            data_dir=config.DATA_DIR,
            raw_archive_dir=config.LIVE_ROUNDS_RAW_DIR,
            on_new_shot=self._on_new_live_shot,
            on_round_archived=self._on_round_archived,
            schedule_on_main_thread=lambda fn: self.root.after(0, fn),
            poll_interval=config.LIVE_POLL_SECONDS,
            # Enriches live/archived range shots with club speed, smash and AoA
            # from GSPro.db (currentRound.dat doesn't carry them).
            club_lookup=ClubDataLookup(config.GSPRO_DB_FILE),
        )

        self.global_time_var = tk.StringVar(value=filters_mod.TIME_ALL)
        self.global_quality_var = tk.StringVar(value=filters_mod.QUALITY_ALL)
        # Environmental normalization: opt-in via Settings (off by default so
        # the "Today's Temp" box stays hidden and out of the way). When the
        # feature is on, distances normalize whenever the temp field holds a
        # valid number.
        self.settings_temp_norm_enabled = tk.BooleanVar(value=False)
        self.global_temp_var = tk.StringVar(value="")
        self._normalizer = EnvironmentalNormalizer()
        # Ignore each session's first few shots (warm-up swings) in the
        # dashboards — a Settings toggle, off by default.
        self.settings_ignore_warmup = tk.BooleanVar(value=False)
        # Demo mode: show a generated sample dataset instead of real data.
        # Which dataset is chosen from config.SAMPLE_DATASETS via a Settings
        # dropdown; both vars are in-memory-only by design (demo state
        # shouldn't survive a restart).
        self.settings_use_sample = tk.BooleanVar(value=False)
        self.settings_sample_set = tk.StringVar(value=next(iter(config.SAMPLE_DATASETS)))
        # All-time speed bests, tracked live so a new PB flashes a toast.
        self._record_club_speed: float | None = None
        self._record_ball_speed: float | None = None

        self.show_landing_page = True
        self._home_frame: ctk.CTkFrame | None = None
        # Both of these are populated once real data loads (see
        # load_master_data). Club Filter is global (affects every
        # dashboard); gapping_club_vars is scoped to the Club Gapping
        # panel alone so it can show any club regardless of the global
        # filter, matching the original app's behavior.
        self.global_club_vars: dict[str, tk.BooleanVar] = {}
        self.gapping_club_vars: dict[str, tk.BooleanVar] = {}

        # Chart sizing tracks the UI scale factor (see app._apply_ui_scaling),
        # but only *half* of it. Matplotlib figures aren't scaled by CTk's
        # widget scaling, so bumping chart DPI with the scale keeps chart text
        # from shrinking on a hi-res panel — but matching the full factor made
        # axis labels/annotations too large. Half-compensation is the middle
        # ground: readable on the projector, not oversized. Font *point* sizes
        # stay constant; only DPI moves.
        self.root.geometry("1450x955")
        # Floor on the window size (in unscaled units — CustomTkinter multiplies
        # these by the window scaling, so on a small laptop the real floor
        # shrinks with the UI). Sized to still fit a ~10" 1366x768 panel while
        # keeping the sidebar + at least one chart panel usable.
        try:
            self.root.minsize(1000, 640)
        except tk.TclError:
            pass
        self.chart_dpi = max(80, min(180, int(round(100 * (1 + (self.ui_scale - 1) * 0.5)))))
        self.plot_font_scale = 14
        # Open maximized (title bar + taskbar stay visible). F11 still toggles a
        # borderless full-screen if wanted, and Escape leaves it.
        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.attributes("-zoomed", True)
        self.root.bind("<F11>", self._toggle_fullscreen)
        self.root.bind("<Escape>", self._exit_fullscreen)

        self.plot_state = self._build_plot_state()

        plt.style.use("dark_background")
        plt.rcParams.update({
            "figure.facecolor": Colors.BG_SURFACE,
            "axes.facecolor": Colors.BG_SURFACE,
            "axes.edgecolor": Colors.BORDER,
            "axes.labelcolor": Colors.TEXT_PRIMARY,
            "axes.titlesize": self.plot_font_scale + 2,
            "axes.labelsize": self.plot_font_scale,
            "text.color": Colors.TEXT_PRIMARY,
            "xtick.color": Colors.TEXT_MUTED,
            "ytick.color": Colors.TEXT_MUTED,
            "xtick.labelsize": self.plot_font_scale - 1,
            "ytick.labelsize": self.plot_font_scale - 1,
            "grid.color": Colors.GRID,
            "grid.alpha": 0.5,
            "legend.facecolor": Colors.BG_SURFACE,
            "legend.edgecolor": Colors.BORDER,
        })

        self._build_ui()
        self._apply_titlebar_theme()
        self.load_master_data()
        self.build_grid()
        self.export_watcher.start()
        self.round_watcher.start()
        self._poll_raw_csv_dir()

    # ------------------------------------------------------------------
    # Runtime dashboard state (Tk variables layered over the static registry)
    # ------------------------------------------------------------------
    def _build_plot_state(self) -> dict:
        state = {}
        for d in DASHBOARDS:
            entry = {"def": d, "var": tk.BooleanVar(value=False)}
            if d.has_color:
                entry["color_var"] = tk.StringVar(value="Club")
            if d.benchmark_fields:
                # Per-panel benchmark selector, offering only profiles that
                # actually have data for this chart's metric(s); all off by
                # default so nothing overlays until the user opts in.
                available = config.profiles_with(*d.benchmark_fields, mode=d.benchmark_mode)
                entry["benchmark_vars"] = {p: tk.BooleanVar(value=False) for p in available}
            if d.name == TRAJECTORY_NAME:
                entry["ind_var"] = tk.BooleanVar(value=True)
            if d.name == LAUNCH_SPIN_NAME:
                # Single-club focus (default driver), independent of the
                # global Club Filter — see _place_single_plot_panel.
                entry["ls_club_var"] = tk.StringVar(value="Dr")
            if d.name == DISPERSION_NAME:
                entry["dist_var"] = tk.StringVar(value="Carry")
                entry["detail_var"] = tk.StringVar(value="In-Depth")
                entry["on_shot_click"] = self._edit_historical_shot
            if d.name == SESSION_COMPARE_NAME:
                # One club; the session checklist is (re)built per-panel in
                # _place_single_plot_panel from the last 10 sessions.
                entry["sc_club_var"] = tk.StringVar(value="Dr")
            if d.name == CLUB_COMPARE_NAME:
                # Configs are entered via the Configure… dialog; cc_capture
                # holds live shots logged per config index via "Now hitting".
                entry["cc_session_id"] = None
                entry["cc_configs"] = []
                entry["cc_capture"] = {}
                entry["cc_record_var"] = tk.StringVar(value=_CC_OFF)
                entry["cc_record_labels"] = {}
            if d.name == LIVE_NAME:
                entry["live_shots"] = self.live_shot_buffer
                entry["on_shot_click"] = self._edit_live_shot
            state[d.name] = entry
        return state

    def on_closing(self):
        self.export_watcher.stop()
        self.round_watcher.stop()
        # Best-effort flush: if GSPro is still mid-round when this app
        # closes, archive whatever's been tracked so far rather than
        # losing it. Guarded — a failed archive (disk full, file lock)
        # must never leave the window refusing to close.
        try:
            self.round_watcher.finalize_now()
        except Exception:
            log.exception("Could not archive the in-progress round during shutdown")
        self.root.quit()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Native title-bar theming (Windows) + full-screen toggle
    # ------------------------------------------------------------------
    @staticmethod
    def _hex_to_colorref(hex_color: str) -> int:
        """#RRGGBB -> Win32 COLORREF (0x00BBGGRR)."""
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return r | (g << 8) | (b << 16)

    def _apply_titlebar_theme(self):
        """Tint the native Windows title bar to match the app's dark theme so
        it blends with the top bar instead of the default light caption.
        Windows-only; needs Win10 1809+ for dark mode and Win11 22H2+ for the
        exact caption color. Silently no-ops elsewhere / on older builds."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            self.root.update_idletasks()  # ensure the native window exists
            get_parent = ctypes.windll.user32.GetParent
            get_parent.restype = wintypes.HWND
            get_parent.argtypes = [wintypes.HWND]
            # Tk's winfo_id() is the client frame; its parent owns the caption.
            hwnd = get_parent(self.root.winfo_id())

            dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
            dwm.restype = ctypes.c_long  # HRESULT (0 == S_OK)
            dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

            def _set(attr: int, value: int) -> int:
                v = ctypes.c_int(value)
                return dwm(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

            # Dark caption (light text + window buttons). Attribute 20 on
            # current builds; 19 on early Win10 1809/1903.
            if _set(20, 1) != 0:
                _set(19, 1)
            # Exact caption color matching the sidebar/top bar (Win11 22H2+);
            # harmless failure on older builds, where dark mode already darkens it.
            _set(35, self._hex_to_colorref(Colors.BG_SIDEBAR))
        except Exception:
            log.debug("Could not theme the native title bar", exc_info=True)

    def _is_fullscreen(self) -> bool:
        try:
            return bool(self.root.attributes("-fullscreen"))
        except tk.TclError:
            return False

    def _toggle_fullscreen(self, _event=None):
        try:
            self.root.attributes("-fullscreen", not self._is_fullscreen())
        except tk.TclError:
            pass
        # Leaving full-screen keeps the window maximized rather than snapping
        # back to the small default geometry.
        if not self._is_fullscreen():
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass

    def _exit_fullscreen(self, _event=None):
        if self._is_fullscreen():
            self._toggle_fullscreen()

    # ------------------------------------------------------------------
    # Sidebar toggle behavior: plot cap enforcement
    # ------------------------------------------------------------------
    def make_toggle_cmd(self, entry):
        def cmd():
            self.show_landing_page = False
            name = entry["def"].name

            # Picking any sidebar dashboard leaves live mode (it owns the grid).
            if self.plot_state[LIVE_NAME]["var"].get():
                self.plot_state[LIVE_NAME]["var"].set(False)
                self._update_go_live_button()

            # The checkbox has already flipped this entry's var; act on the new
            # state. Turning one OFF never needs cap/solo enforcement.
            if entry["var"].get():
                if name in SOLO_DASHBOARDS:
                    # Solo dashboards fill the screen: clear every other panel.
                    for n, e in self.plot_state.items():
                        if n != name:
                            e["var"].set(False)
                else:
                    # A normal dashboard can't share the screen with a solo one.
                    for n in SOLO_DASHBOARDS:
                        self.plot_state[n]["var"].set(False)
                    active_normal = [
                        n for n, e in self.plot_state.items()
                        if e["var"].get() and n not in SOLO_DASHBOARDS and n != LIVE_NAME
                    ]
                    if len(active_normal) > MAX_ACTIVE_PLOTS:
                        show_toast(
                            self.root,
                            f"You can view at most {MAX_ACTIVE_PLOTS} dashboards at "
                            f"once — uncheck one first.",
                            tone="warning",
                        )
                        entry["var"].set(False)
                        return

            self.build_grid()
            self._update_nav_highlights()

        return cmd

    def toggle_live(self):
        """"Go Live" top-bar button: shows/hides the Live Dispersion panel.

        Doesn't start or stop tracking itself — self.round_watcher polls
        currentRound.dat and archives finished rounds continuously from
        app startup regardless of this button's state (see __init__).
        This just controls whether you're currently watching it.
        """
        entry = self.plot_state[LIVE_NAME]
        going_on = not entry["var"].get()
        self.show_landing_page = False

        # Live mode takes over the whole grid: only the Live Dispersion
        # panel is shown while it's on.
        for e in self.plot_state.values():
            e["var"].set(False)
        entry["var"].set(going_on)

        self.build_grid()
        self._update_nav_highlights()
        self._update_go_live_button()

    def _update_go_live_button(self):
        is_on = self.plot_state[LIVE_NAME]["var"].get()
        if is_on:
            self.go_live_button.configure(text="Live: ON", fg_color=Colors.ACCENT, text_color=Colors.TEXT_ON_LIGHT)
        else:
            self.go_live_button.configure(text="Go Live", fg_color="transparent", text_color=Colors.ACCENT)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        top_bar = theme.sidebar_frame(self.root, height=64)
        top_bar.pack(side=tk.TOP, fill=tk.X)

        self.go_live_button = theme.outline_button(
            top_bar, accent=Colors.ACCENT, text="Go Live", command=self.toggle_live,
        )
        self.go_live_button.pack(side=tk.LEFT, padx=(15, 6), pady=12)

        self.settings_button = theme.outline_button(
            top_bar, accent=Colors.ACCENT, text="⚙ Settings", command=self._open_settings,
        )
        self.settings_button.pack(side=tk.LEFT, padx=(0, 6), pady=12)

        filter_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        filter_frame.pack(side=tk.RIGHT, padx=15, pady=10)

        theme.section_label(filter_frame, "Shot Quality", color=Colors.WARNING).grid(row=0, column=4, padx=(15, 5))
        SingleSelectDropdown(
            filter_frame, filters_mod.QUALITY_FILTER_OPTIONS, self.global_quality_var,
            on_change=self._on_filter_changed, accent=Colors.WARNING, width=190,
        ).grid(row=0, column=5)

        # "Today's Temp": type the temperature to normalize distances to
        # standard conditions. Shown only when enabled in Settings; the value
        # in the box is the switch (blank = no normalization).
        self.temp_norm_label = theme.section_label(filter_frame, "Today's Temp", color=Colors.INFO)
        self.temp_norm_label.grid(row=0, column=6, padx=(15, 5))
        attach_tooltip(self.temp_norm_label,
                       "Enter today's temperature — this normalizes your carry/total "
                       "distances to standard conditions so sessions hit on different "
                       "days compare fairly.")
        self.temp_norm_frame = ctk.CTkFrame(filter_frame, fg_color="transparent")
        self.temp_norm_frame.grid(row=0, column=7)
        temp_entry = ctk.CTkEntry(self.temp_norm_frame, textvariable=self.global_temp_var,
                                  width=54, justify="center", placeholder_text="off")
        temp_entry.pack(side=tk.LEFT)
        theme.body_label(self.temp_norm_frame, "°F", color=Colors.TEXT_MUTED).pack(side=tk.LEFT, padx=(4, 0))
        temp_entry.bind("<Return>", self._on_filter_changed)
        temp_entry.bind("<FocusOut>", self._on_filter_changed)
        if not self.settings_temp_norm_enabled.get():
            self.temp_norm_label.grid_remove()
            self.temp_norm_frame.grid_remove()

        theme.section_label(filter_frame, "Club Filter", color=Colors.INFO).grid(row=0, column=2, padx=(15, 5))
        self.global_club_selector = MultiSelectDropdown(
            filter_frame, self.global_club_vars, on_change=self._on_filter_changed,
            accent=Colors.INFO, width=140, item_label="Clubs", item_colors=config.CLUB_COLORS,
        )
        self.global_club_selector.grid(row=0, column=3)

        theme.section_label(filter_frame, "Time Filter", color=Colors.SUCCESS).grid(row=0, column=0, padx=(0, 5))
        SingleSelectDropdown(
            filter_frame, filters_mod.TIME_FILTER_OPTIONS, self.global_time_var,
            on_change=self._on_filter_changed, accent=Colors.SUCCESS, width=150,
        ).grid(row=0, column=1)

        main_body = ctk.CTkFrame(self.root, fg_color=Colors.BG_BASE, corner_radius=0)
        main_body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        sidebar = theme.sidebar_frame(main_body, width=340)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        self._build_sidebar_sections(sidebar)

        self.grid_frame = ctk.CTkFrame(main_body, fg_color=Colors.BG_BASE, corner_radius=0)
        self.grid_frame.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True,
            padx=config.SPACING["sm"], pady=config.SPACING["sm"],
        )

    def _build_sidebar_sections(self, sidebar):
        # Sections live in a scrollable container so the menu keeps working once
        # there are more dashboards than fit the window height (mouse wheel
        # scrolls it). Reassigning `sidebar` to the scroll frame means every
        # section below packs into it with no further changes.
        sidebar = ctk.CTkScrollableFrame(
            sidebar, fg_color=Colors.BG_SIDEBAR, corner_radius=0,
            scrollbar_button_color=Colors.BG_HOVER,
            scrollbar_button_hover_color=Colors.BORDER_HOVER,
        )
        sidebar.pack(fill=tk.BOTH, expand=True)

        # Course-photo banner reusing the landing page's background image as
        # the sidebar's header; skipped silently if the photo is missing.
        banner = course_banner(sidebar, self._find_background_image(), "Golf Sim Analytics")
        if banner is not None:
            banner.pack(fill=tk.X, padx=12, pady=(12, 4))

        metrics_card, metrics_body = theme.section_card(
            sidebar, "Metrics Dashboards", accent=Colors.INFO, icon="📊",
        )
        metrics_card.pack(fill=tk.X, padx=12, pady=(8, 8))
        for d in DASHBOARDS:
            if d.category == "Metrics":
                self._nav_item(metrics_body, d)

        opt_card, opt_body = theme.section_card(
            sidebar, "Optimization Dashboards", accent=Colors.WARNING, icon="🎯",
        )
        opt_card.pack(fill=tk.X, padx=12, pady=(0, 8))
        for d in DASHBOARDS:
            if d.category == "Optimization":
                self._nav_item(opt_body, d)

        fitting_card, fitting_body = theme.section_card(
            sidebar, "Club Fitting", accent=Colors.SUCCESS, icon="⛳",
        )
        fitting_card.pack(fill=tk.X, padx=12, pady=(0, 8))
        for d in DASHBOARDS:
            if d.category == "Club Fitting":
                self._nav_item(fitting_body, d)

        speed_card, speed_body = theme.section_card(
            sidebar, "Speed Training", accent=Colors.DANGER, icon="⚡",
        )
        speed_card.pack(fill=tk.X, padx=12, pady=(0, 8))
        for d in DASHBOARDS:
            if d.category == "Speed Training":
                self._nav_item(speed_body, d)

        course_card, course_body = theme.section_card(
            sidebar, "On-Course Play", accent=Colors.SUCCESS, icon="🏌️",
        )
        course_card.pack(fill=tk.X, padx=12, pady=(0, 8))
        for d in DASHBOARDS:
            if d.category == "On Course":
                self._nav_item(course_body, d)

    def _nav_item(self, sidebar, d):
        entry = self.plot_state[d.name]
        row = ctk.CTkFrame(sidebar, fg_color="transparent", corner_radius=6)
        row.pack(side=tk.TOP, fill=tk.X, padx=4, pady=1)
        cb = theme.nav_checkbox(
            row, text=d.name, variable=entry["var"], command=self.make_toggle_cmd(entry),
            font=theme.font("subheading"), text_color=Colors.TEXT_MUTED,
        )
        cb.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
        entry["nav_row"] = row
        entry["nav_cb"] = cb
        self._style_nav_item(entry)
        if d.description:
            attach_tooltip(row, d.description)

        def _enter(_event, r=row):
            r.configure(fg_color=Colors.BG_HOVER)

        def _leave(_event, r=row, e=entry):
            r.configure(fg_color=Colors.BG_HOVER if e["var"].get() else "transparent")

        for widget in (row, cb):
            widget.bind("<Enter>", _enter, add="+")
            widget.bind("<Leave>", _leave, add="+")

    def _style_nav_item(self, entry):
        """Active items get the bronze highlight + bronze text; inactive stay
        muted grey — the deep-bronze menu look."""
        active = entry["var"].get()
        row, cb = entry.get("nav_row"), entry.get("nav_cb")
        if row is not None and row.winfo_exists():
            row.configure(fg_color=Colors.BG_HOVER if active else "transparent")
        if cb is not None and cb.winfo_exists():
            cb.configure(text_color=Colors.ACCENT if active else Colors.TEXT_MUTED)

    def _update_nav_highlights(self):
        for entry in self.plot_state.values():
            self._style_nav_item(entry)

    def _on_filter_changed(self, _value=None):
        self.refresh_all_active_plots()

    def _selected_global_clubs(self):
        """CLUB_ALL when every known club is checked (i.e. no real
        filtering), otherwise the set of specifically-checked club names.
        """
        if not self.global_club_vars or all(v.get() for v in self.global_club_vars.values()):
            return filters_mod.CLUB_ALL
        return {c for c, v in self.global_club_vars.items() if v.get()}

    # ------------------------------------------------------------------
    # Driver adapter tagging + A/B compare selectors
    # ------------------------------------------------------------------
    def _session_options(self):
        """(session_id, label) per dated session, newest first, for the adapter
        dialog. Label = date + shot count (+ current tag), disambiguated."""
        if self.master_df.empty or "session_id" not in self.master_df.columns:
            return []
        info = []
        for sid, sub in self.master_df.groupby("session_id"):
            date = (pd.to_datetime(sub["session_date"], errors="coerce").max()
                    if "session_date" in sub.columns else pd.NaT)
            date_lbl = date.strftime("%b %d, %Y") if pd.notna(date) else "undated"
            tag = ""
            if "adapter" in sub.columns:
                vals = [str(v) for v in sub["adapter"].dropna() if str(v).strip()]
                tag = vals[0] if vals else ""
            label = f"{date_lbl} · {len(sub)} shots" + (f"  [{tag}]" if tag else "")
            info.append((sid, date if pd.notna(date) else pd.Timestamp.min, label))
        info.sort(key=lambda t: t[1], reverse=True)
        seen: dict[str, int] = {}
        out = []
        for sid, _dt, label in info:
            n = seen.get(label, 0)
            seen[label] = n + 1
            out.append((sid, label if n == 0 else f"{label} ({n + 1})"))
        return out

    def _open_club_config(self, name):
        sessions = self._session_options()[:10]
        if not sessions:
            show_toast(self.root, "No sessions to compare yet.", tone="info")
            return
        clubs = (sorted(self.master_df["club"].dropna().unique(), key=get_club_rank)
                 if "club" in self.master_df.columns else [])
        entry = self.plot_state[name]
        current = {"session_id": entry.get("cc_session_id"), "configs": entry.get("cc_configs", [])}

        def _apply(session_id, configs):
            entry["cc_session_id"] = session_id
            entry["cc_configs"] = configs
            # New config set — reset any captured shots and the record target.
            entry["cc_capture"] = {}
            entry["cc_record_var"].set(_CC_OFF)
            self._cc_refresh_record_dd(entry)
            if "canvas" in entry:
                self.update_single_plot(name, self._active_count())

        open_club_config_dialog(self.root, sessions, clubs, current, _apply)

    def _active_count(self):
        return sum(1 for e in self.plot_state.values() if e["var"].get()) or 1

    def _cc_config_labels(self, entry):
        """Ordered, unique "Now hitting" labels + a {label: config_index} map."""
        from ui.charts.club_compare import _label
        labels, mapping = [], {}
        for i, cfg in enumerate(entry.get("cc_configs", [])):
            lbl = f"{i + 1}. {_label(cfg)}"
            labels.append(lbl)
            mapping[lbl] = i
        return labels, mapping

    def _cc_refresh_record_dd(self, entry):
        """Repoint the record dropdown at the current configs, keeping the
        selection valid."""
        labels, mapping = self._cc_config_labels(entry)
        entry["cc_record_labels"] = mapping
        dd = entry.get("cc_record_dd")
        if dd is not None:
            dd.options = [_CC_OFF] + labels
            if entry["cc_record_var"].get() not in ([_CC_OFF] + labels):
                entry["cc_record_var"].set(_CC_OFF)
            dd._refresh_button_label()

    def _cc_record_index(self, entry):
        """The config index currently being logged to, or None."""
        val = entry["cc_record_var"].get()
        if val == _CC_OFF:
            return None
        return entry.get("cc_record_labels", {}).get(val)

    def _cc_on_record_change(self, name):
        entry = self.plot_state[name]
        idx = self._cc_record_index(entry)
        if idx is not None:
            from ui.charts.club_compare import _label
            cfg = entry["cc_configs"][idx]
            show_toast(self.root, f"Logging shots for {_label(cfg)}. Hit away — "
                       f"each shot lands in this club.", tone="success")

    def _export_club_compare(self, name):
        from tkinter import filedialog

        from ui.charts import club_compare
        entry = self.plot_state[name]
        frames = club_compare.config_frames(self._comparison_frame(), entry)
        frames = [(cfg, sub) for cfg, sub in frames if not sub.empty]
        if not frames:
            show_toast(self.root, "Nothing to export yet — log or configure some shots first.",
                       tone="info")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".csv",
            filetypes=[("CSV", "*.csv")], initialfile="club_comparison.csv",
            title="Export club comparison")
        if not path:
            return
        try:
            club_compare.summary_frame(frames).to_csv(path, index=False)
        except OSError:
            log.exception("Club comparison export failed")
            show_toast(self.root, "Couldn't write the export file.", tone="error")
            return
        show_toast(self.root, f"Exported {len(frames)} configs to {path.split('/')[-1]}",
                   tone="success")

    def _cc_clear(self, name):
        entry = self.plot_state[name]
        entry["cc_capture"] = {}
        entry["cc_record_var"].set(_CC_OFF)
        self._cc_refresh_record_dd(entry)
        if "canvas" in entry:
            self.update_single_plot(name, self._active_count())

    def _comparison_frame(self):
        """All shots (every session/club, ignoring the global Time/Club
        filters) with normalization applied — the comparison panels do their
        own session/club selection."""
        df = self._drop_warmup(self.master_df)
        temp = self._normalize_temp()
        return self._normalizer.normalize(df, temp) if temp is not None else df

    def _drop_warmup(self, df):
        """Strip each session's warm-up shots when the Settings toggle is on."""
        return filters_mod.drop_warmup_shots(df) if self.settings_ignore_warmup.get() else df

    def _column_max(self, aliases):
        # Seeds the all-time speed PBs from the *full* history (incl. on-course
        # rounds): a drive striped on the course is still a real personal best,
        # so a later practice swing shouldn't falsely flash "new record."
        df = self._full_df
        col = find_col(df, aliases) if not df.empty else None
        if not col:
            return None
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        return float(vals.max()) if not vals.empty else None

    def _check_speed_record(self, shot):
        """Flash a toast when a live shot beats the all-time club or ball speed."""
        for key, label, attr in (("clubspeed", "club speed", "_record_club_speed"),
                                  ("ballspeed", "ball speed", "_record_ball_speed")):
            val = shot.get(key)
            if val is None:
                continue
            rec = getattr(self, attr)
            if rec is not None and val > rec + 0.05:
                show_toast(self.root, f"New {label} record!  {val:.1f} mph  (+{val - rec:.1f})",
                           tone="success")
            if rec is None or val > rec:
                setattr(self, attr, val)  # track the running best either way

    def _live_shot_quality(self, shot):
        """0-100 Shot Quality Score for a single live shot, scored against that
        club's practice history so the live-view gauge has a distribution to
        compare against. None when the shot can't be scored (e.g. a chip with
        no launch/spin and too little same-club history)."""
        if not shot:
            return None
        hist = self.master_df
        club = shot.get("club")
        if not hist.empty and club and "club" in hist.columns:
            peers = hist[hist["club"] == club]
        else:
            peers = hist
        combined = pd.concat([peers, pd.DataFrame([shot])], ignore_index=True)
        try:
            score = ShotScorer().score(combined).iloc[-1]
        except Exception:
            return None
        return float(score) if pd.notna(score) else None

    @staticmethod
    def _selected_benchmarks(entry):
        """Reference-profile names checked in this panel's own benchmark
        selector, in canonical order (empty when the chart has no selector
        or nothing is checked)."""
        return [name for name, var in entry.get("benchmark_vars", {}).items() if var.get()]

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def _sample_dir(self):
        """Folder of the demo dataset currently picked in Settings."""
        return config.SAMPLE_DATASETS.get(
            self.settings_sample_set.get(), config.SAMPLE_DATA_DIR)

    def _data_dir(self):
        """Active data folder — the chosen sample set in demo mode, else real data."""
        return self._sample_dir() if self.settings_use_sample.get() else config.DATA_DIR

    def load_master_data(self):
        data_dir = self._data_dir()
        # In sample mode, ingest the bundled demo CSVs to Parquet once.
        if (self.settings_use_sample.get() and data_dir.exists()
                and not list(data_dir.glob("*.parquet")) and list(data_dir.glob("*.csv"))):
            try:
                ingest_all_csvs(data_dir, data_dir)
            except Exception:
                log.exception("Failed to prepare sample data")

        full = load_master_dataframe(data_dir)
        # Merge in driver adapter tags (isolated sidecar; see data/adapter_tags).
        # Keeps the core loader untouched — untagged rows just get adapter="".
        full = adapter_tags.apply_tags(full, adapter_tags.load_tags(data_dir))
        # Reversible edits: stable shot_uid, then hide deleted sessions/shots
        # and apply club overrides (data/edits.py — Parquet never touched).
        full = edits_mod.add_shot_uid(full)
        full = edits_mod.apply_edits(full, edits_mod.load_edits(data_dir))
        # Drop on-course mulligans (re-hit shots) when enabled — touches only
        # on_course rounds; practice range data is never affected.
        if self.settings_drop_mulligans.get():
            full = on_course.drop_mulligans(full)
        self._full_df = full
        # Practice-analytics view every dashboard reads: on-course rounds (chips,
        # punches, recoveries) filtered out when enabled so they don't taint the
        # "pure your swing" historical data.
        self.master_df = on_course.practice_view(
            full, exclude_on_course=self.settings_exclude_on_course.get())
        if "club" in self.master_df.columns:
            clubs = sorted(self.master_df["club"].dropna().unique().tolist(), key=get_club_rank)
            for c in clubs:
                self.global_club_vars.setdefault(c, tk.BooleanVar(value=True))
                self.gapping_club_vars.setdefault(c, tk.BooleanVar(value=True))
            self.global_club_selector.refresh_options()

        # Seed the all-time speed records from history so live PBs are measured
        # against the real best, not just this session.
        self._record_club_speed = self._column_max(CLUB_SPEED_ALIASES)
        self._record_ball_speed = self._column_max(BALL_SPEED_ALIASES)

        # The landing page's stats are computed at render time, so a stale
        # frame would keep showing old numbers after new data lands. Drop it
        # here so the next build_grid re-renders it — this is what makes a
        # just-finished live round show up as the latest session.
        if self._home_frame is not None:
            if self._home_frame.winfo_exists():
                self._home_frame.destroy()
            self._home_frame = None

    def _poll_raw_csv_dir(self):
        """Background replacement for the old "Ingest CSVs" button.

        Runs on a Tk-scheduled timer for the life of the app: any *.csv
        sitting in raw_csvs/ (dropped there by hand, or copied in by
        data.export_watcher from the Desktop) gets picked up with zero
        clicks. ingest_all_csvs() only ever globs *.csv and renames each
        file to *.csv.processed once archived, so re-running this on a
        timer is naturally idempotent — nothing is ever double-ingested.
        """
        try:
            if list(config.RAW_CSV_DIR.glob("*.csv")):
                processed_count = ingest_all_csvs(config.RAW_CSV_DIR, config.DATA_DIR)
                if processed_count:
                    plural = "s" if processed_count != 1 else ""
                    self._on_new_csv_data(f"Auto-ingested {processed_count} CSV file{plural}.")
        except Exception:
            log.exception("Automatic raw_csvs ingest failed")
        finally:
            self.root.after(int(config.RAW_CSV_POLL_SECONDS * 1000), self._poll_raw_csv_dir)

    def _on_export_watcher_data(self, processed_count: int) -> None:
        """Called (on the main thread) after data.export_watcher picks up
        and ingests one or more new GSPro exports from the Desktop — same
        refresh _poll_raw_csv_dir() does, just triggered by a Desktop
        export instead of a raw_csvs/ poll tick."""
        if processed_count <= 0:
            return
        plural = "s" if processed_count != 1 else ""
        self._on_new_csv_data(f"Picked up {processed_count} new GSPro export{plural} automatically.")

    def _on_new_csv_data(self, message: str) -> None:
        """Shared refresh after any automatic ingest (raw_csvs/ poll tick
        or the Desktop export watcher) — reloads data and repaints active
        charts, and shows one themed toast describing what happened."""
        show_toast(self.root, message, tone="success")
        self.load_master_data()
        self.build_grid()
        self.refresh_all_active_plots()

    def _on_new_live_shot(self, flat_shot: dict) -> None:
        """Called (on the main thread) by self.round_watcher the moment a
        new shot shows up in currentRound.dat. Just appends and, if the
        Live Dispersion panel is currently visible, redraws it — nothing
        else changes yet (the shot isn't archived to Parquet until the
        round finalizes, see _on_round_archived)."""
        self.live_shot_buffer.append(flat_shot)
        self._check_speed_record(flat_shot)

        # Club Comparison live capture: if a config is armed via "Now hitting",
        # this shot belongs to that club — log it and redraw the panel.
        self._capture_club_compare_shot(flat_shot)

        entry = self.plot_state[LIVE_NAME]
        if entry["var"].get() and "canvas" in entry:
            active_count = sum(1 for e in self.plot_state.values() if e["var"].get())
            self.update_single_plot(LIVE_NAME, active_count)
        # If other panels are viewing "Current Session", refresh them too so
        # this new shot shows up everywhere immediately.
        elif self.global_time_var.get() == filters_mod.TIME_CURRENT_SESSION:
            self.refresh_all_active_plots()

    def _edit_live_shot(self, shot: dict) -> None:
        """Click-to-edit on a Live Dispersion point: reassign the shot's club
        (fix a mis-clubbed shot) or delete it, in the in-memory buffer before it
        archives. `shot` is a live_shot_buffer reference, so edits stick."""
        clubs = sorted(config.CLUB_COLORS, key=get_club_rank)

        def _pick(club):
            shot["club"] = club
            self._rerender_live()

        def _delete():
            try:
                self.live_shot_buffer.remove(shot)
            except ValueError:
                pass
            self._rerender_live()

        open_shot_edit_popup(self.root, shot.get("club", ""), clubs, _pick, _delete)

    def _edit_historical_shot(self, info: dict) -> None:
        """Click-to-edit on a historical Dispersion point: reassign the shot's
        club or delete it via the reversible edits sidecar, then reload."""
        uid = info.get("shot_uid")
        if not uid:
            return
        clubs = sorted(config.CLUB_COLORS, key=get_club_rank)

        def _reload():
            self.load_master_data()
            self.build_grid()
            self.refresh_all_active_plots()

        def _pick(club):
            edits_mod.set_club_override(self._data_dir(), uid, club)
            _reload()

        def _delete():
            edits_mod.delete_shot(self._data_dir(), uid)
            show_toast(self.root, "Shot hidden (kept in your data, just excluded).", tone="info")
            _reload()

        open_shot_edit_popup(self.root, info.get("club", ""), clubs, _pick, _delete)

    def _rerender_live(self):
        entry = self.plot_state[LIVE_NAME]
        if entry["var"].get() and "canvas" in entry:
            self.update_single_plot(LIVE_NAME, self._active_count())
        if self.global_time_var.get() == filters_mod.TIME_CURRENT_SESSION:
            self.refresh_all_active_plots()

    def _open_manage_sessions(self):
        raw = load_master_dataframe(self._data_dir())
        if raw.empty or "session_id" not in raw.columns:
            show_toast(self.root, "No sessions to manage yet.", tone="info")
            return
        deleted = set(edits_mod.load_edits(self._data_dir())["deleted_sessions"])
        info = []
        for sid, sub in raw.groupby("session_id"):
            date = (pd.to_datetime(sub["session_date"], errors="coerce").max()
                    if "session_date" in sub.columns else pd.NaT)
            dl = date.strftime("%b %d, %Y") if pd.notna(date) else "undated"
            info.append((sid, date if pd.notna(date) else pd.Timestamp.min,
                         f"{dl}  ·  {len(sub)} shots"))
        info.sort(key=lambda t: t[1], reverse=True)
        sessions = [(sid, label, str(sid) in deleted) for sid, _dt, label in info]

        def _on_toggle(sid, delete):
            edits_mod.delete_session(self._data_dir(), sid, delete)
            self.load_master_data()
            self.build_grid()
            self.refresh_all_active_plots()

        open_manage_sessions_dialog(self.root, sessions, _on_toggle)

    def _capture_club_compare_shot(self, flat_shot: dict) -> None:
        cc = self.plot_state.get(CLUB_COMPARE_NAME)
        if cc is None or not cc["var"].get():
            return
        idx = self._cc_record_index(cc)
        if idx is None:
            return
        cc.setdefault("cc_capture", {}).setdefault(idx, []).append(flat_shot)
        self._cc_refresh_record_dd(cc)
        if "canvas" in cc:
            self.update_single_plot(CLUB_COMPARE_NAME, self._active_count())

    def _on_round_archived(self, info: dict) -> None:
        """Called (on the main thread) once self.round_watcher detects the
        round/range session has ended and has archived it — both to the
        normal Parquet history (so it joins every dashboard like a
        CSV-ingested session would) and to a raw JSON snapshot tagged with
        round_type, under config.LIVE_ROUNDS_RAW_DIR."""
        self.live_shot_buffer.clear()
        label = "practice" if info["round_type"] == "practice" else "on-course"
        plural = "s" if info["shot_count"] != 1 else ""
        show_toast(
            self.root,
            f"Archived {info['shot_count']} live-tracked shot{plural} from your {label} round.",
            tone="success",
        )
        self.load_master_data()
        self.build_grid()
        self.refresh_all_active_plots()

    # ------------------------------------------------------------------
    # Grid / chart panels
    # ------------------------------------------------------------------
    def _filtered_frames(self):
        """Compute the two filtered views every panel needs, once per refresh."""
        time_val = self.global_time_var.get()
        # "Current Session" pulls from the in-progress live buffer (not yet
        # archived to master_df), so every panel can view this round's shots.
        if time_val == filters_mod.TIME_CURRENT_SESSION:
            src, time_val = pd.DataFrame(self.live_shot_buffer), filters_mod.TIME_ALL
        else:
            src = self.master_df
        base = filters_mod.filter_master_data(
            src, time_val, self._selected_global_clubs(), self.global_quality_var.get(),
        )
        gap = filters_mod.filter_master_data(
            src, time_val, None, self.global_quality_var.get(), ignore_global_club=True,
        )
        base, gap = self._drop_warmup(base), self._drop_warmup(gap)
        temp = self._normalize_temp()
        if temp is not None:
            base = self._normalizer.normalize(base, temp)
            gap = self._normalizer.normalize(gap, temp)
        return base, gap

    def _normalize_temp(self):
        """The manually-entered temperature to normalize from, or None when the
        feature is disabled in Settings or the field is blank/invalid."""
        if not self.settings_temp_norm_enabled.get():
            return None
        try:
            return float(self.global_temp_var.get())
        except (TypeError, ValueError):
            return None

    def _open_settings(self):
        win = ctk.CTkToplevel(self.root)
        win.title("Settings")
        win.configure(fg_color=Colors.BG_SURFACE)
        win.transient(self.root)
        win.geometry(f"+{self.root.winfo_rootx() + 260}+{self.root.winfo_rooty() + 140}")

        card = theme.card_frame(win)
        card.pack(fill="both", expand=True, padx=16, pady=16)
        theme.section_label(card, "Settings", color=Colors.INFO).pack(anchor="w", pady=(2, 10))

        # Display scale — persists across launches (see data/settings.py). Lets
        # the app be sized up on a projector / external display without
        # everything shrinking, and back down on a laptop panel.
        scale_row = ctk.CTkFrame(card, fg_color="transparent")
        scale_row.pack(fill="x")
        theme.body_label(scale_row, "Display scale",
                         color=Colors.TEXT_PRIMARY).pack(side="left", padx=(0, 24))
        SingleSelectDropdown(
            scale_row, settings_mod.UI_SCALE_OPTIONS, self.settings_ui_scale,
            on_change=self._apply_ui_scale_setting, accent=Colors.INFO, width=110,
        ).pack(side="right")
        theme.body_label(card, "Sizes the whole app up or down. “Auto” fits your "
                         "display — smaller on a compact laptop, larger on a big monitor "
                         "or TV. Pick a percentage to override it.", color=Colors.TEXT_MUTED,
                         font=theme.font("caption"), wraplength=300, justify="left").pack(
            anchor="w", pady=(6, 12))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x")
        theme.body_label(row, "Temperature normalization",
                         color=Colors.TEXT_PRIMARY).pack(side="left", padx=(0, 24))
        theme.toggle_switch(
            row, accent=Colors.INFO, text="", variable=self.settings_temp_norm_enabled,
            command=self._apply_settings, onvalue=True, offvalue=False,
        ).pack(side="right")
        theme.body_label(card, "Shows a “Today's Temp” box in the top bar to normalize "
                         "distances to standard conditions.", color=Colors.TEXT_MUTED,
                         font=theme.font("caption"), wraplength=300, justify="left").pack(
            anchor="w", pady=(6, 12))

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x")
        theme.body_label(row2, "Ignore warm-up shots",
                         color=Colors.TEXT_PRIMARY).pack(side="left", padx=(0, 24))
        theme.toggle_switch(
            row2, accent=Colors.INFO, text="", variable=self.settings_ignore_warmup,
            command=self._apply_settings, onvalue=True, offvalue=False,
        ).pack(side="right")
        theme.body_label(card, "Drops the first 5 shots of each session from the "
                         "dashboards (records and totals still count every shot).",
                         color=Colors.TEXT_MUTED, font=theme.font("caption"),
                         wraplength=300, justify="left").pack(anchor="w", pady=(6, 12))

        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x")
        theme.body_label(row3, "Use sample data (demo)",
                         color=Colors.TEXT_PRIMARY).pack(side="left", padx=(0, 24))
        theme.toggle_switch(
            row3, accent=Colors.WARNING, text="", variable=self.settings_use_sample,
            command=self._apply_sample_toggle, onvalue=True, offvalue=False,
        ).pack(side="right")
        theme.body_label(card, "Shows the generated demo sessions instead of your real "
                         "data. Your data is untouched — toggle off to return to it.",
                         color=Colors.TEXT_MUTED, font=theme.font("caption"),
                         wraplength=300, justify="left").pack(anchor="w", pady=(6, 12))

        # Which demo dataset to show (only meaningful while the toggle above
        # is on; changing it while on swaps datasets immediately).
        row3b = ctk.CTkFrame(card, fg_color="transparent")
        row3b.pack(fill="x")
        theme.body_label(row3b, "Sample dataset",
                         color=Colors.TEXT_PRIMARY).pack(side="left", padx=(0, 24))
        SingleSelectDropdown(
            row3b, list(config.SAMPLE_DATASETS), self.settings_sample_set,
            on_change=self._apply_sample_set, accent=Colors.WARNING, width=190,
        ).pack(side="right")
        theme.body_label(card, "Baseline: a decent player's 6 months. 2-Year "
                         "Progression: a beginner's speed journey from 95 to 130 mph.",
                         color=Colors.TEXT_MUTED, font=theme.font("caption"),
                         wraplength=300, justify="left").pack(anchor="w", pady=(6, 12))

        theme.divider(card).pack(fill="x", pady=(0, 10))
        theme.section_label(card, "On-course play", color=Colors.WARNING).pack(
            anchor="w", pady=(0, 8))

        row4 = ctk.CTkFrame(card, fg_color="transparent")
        row4.pack(fill="x")
        theme.body_label(row4, "Keep on-course rounds out of practice data",
                         color=Colors.TEXT_PRIMARY).pack(side="left", padx=(0, 24))
        theme.toggle_switch(
            row4, accent=Colors.WARNING, text="", variable=self.settings_exclude_on_course,
            command=self._apply_on_course_settings, onvalue=True, offvalue=False,
        ).pack(side="right")
        theme.body_label(card, "Excludes course play (chips, punch-outs, recoveries) from "
                         "the practice dashboards so it doesn't taint the swing data you're "
                         "trying to pure. On-course rounds are still saved.",
                         color=Colors.TEXT_MUTED, font=theme.font("caption"),
                         wraplength=300, justify="left").pack(anchor="w", pady=(6, 12))

        row5 = ctk.CTkFrame(card, fg_color="transparent")
        row5.pack(fill="x")
        theme.body_label(row5, "Drop mulligans (re-hit shots)",
                         color=Colors.TEXT_PRIMARY).pack(side="left", padx=(0, 24))
        theme.toggle_switch(
            row5, accent=Colors.WARNING, text="", variable=self.settings_drop_mulligans,
            command=self._apply_on_course_settings, onvalue=True, offvalue=False,
        ).pack(side="right")
        theme.body_label(card, "Removes a shot when the next shot on the same hole was hit "
                         "from the same spot — i.e. you re-teed after a bad one. The re-hit "
                         "is kept.", color=Colors.TEXT_MUTED, font=theme.font("caption"),
                         wraplength=300, justify="left").pack(anchor="w", pady=(6, 12))

        theme.outline_button(card, accent=Colors.INFO, text="Manage sessions…",
                             command=lambda: (win.destroy(), self._open_manage_sessions()),
                             width=170).pack(anchor="w", pady=(0, 12))

        theme.outline_button(card, accent=Colors.TEXT_MUTED, text="Close",
                             command=win.destroy, width=100).pack(side="right")
        win.after(120, lambda: (win.winfo_exists() and (win.lift(), win.focus_force())))

    def _sample_set_available(self) -> bool:
        """True if the selected demo dataset's folder exists with data in it;
        otherwise toast which generator script produces it."""
        d = self._sample_dir()
        if d.exists() and (list(d.glob("*.csv")) or list(d.glob("*.parquet"))):
            return True
        script = ("tools/generate_sample_data.py" if d == config.SAMPLE_DATA_DIR
                  else "tools/generate_progression_data.py")
        show_toast(self.root, f"'{self.settings_sample_set.get()}' isn't generated "
                   f"yet — run {script}.", tone="warning")
        return False

    def _apply_sample_toggle(self):
        """Swap between real and sample datasets and repaint everything."""
        on = self.settings_use_sample.get()
        if on and not self._sample_set_available():
            self.settings_use_sample.set(False)
            return
        self.load_master_data()
        self.build_grid()
        self.refresh_all_active_plots()
        show_toast(self.root, f"Showing sample data: {self.settings_sample_set.get()}."
                   if on else "Back to your data.", tone="info")

    def _apply_sample_set(self, _value=None):
        """Dataset picked in the Sample dataset dropdown. Only reloads when
        demo mode is currently on; otherwise the choice just waits for the
        toggle."""
        if not self.settings_use_sample.get():
            return
        if not self._sample_set_available():
            return
        self.load_master_data()
        self.build_grid()
        self.refresh_all_active_plots()
        show_toast(self.root, f"Showing sample data: {self.settings_sample_set.get()}.",
                   tone="info")

    def _apply_on_course_settings(self):
        """Persist the on-course toggles and reload so the practice dashboards
        pick up the new mulligan / exclude-on-course filtering."""
        settings_mod.set("drop_mulligans", self.settings_drop_mulligans.get())
        settings_mod.set("exclude_on_course_from_practice",
                         self.settings_exclude_on_course.get())
        self.load_master_data()
        self.build_grid()
        self.refresh_all_active_plots()

    def _apply_ui_scale_setting(self, _value=None):
        """Persist the chosen display scale and apply it live: customtkinter
        widgets rescale immediately, and the chart panels are rebuilt so their
        matplotlib figures pick up the matching DPI (figure DPI is fixed at
        creation, so existing panels have to be recreated)."""
        choice = self.settings_ui_scale.get()
        settings_mod.set("ui_scale", choice)
        height, diagonal_in, os_scaling = settings_mod.detect_display_metrics()
        scale = settings_mod.resolve_scale(choice, height, diagonal_in, os_scaling)
        self.ui_scale = scale
        try:
            ctk.set_widget_scaling(scale)
            ctk.set_window_scaling(scale)
        except Exception:
            log.debug("Could not apply live UI scaling", exc_info=True)
        self.chart_dpi = max(80, min(180, int(round(100 * (1 + (scale - 1) * 0.5)))))
        # Rebuild every panel so new figures render at the new DPI.
        for entry in self.plot_state.values():
            self._destroy_panel(entry)
        self.build_grid()
        show_toast(self.root, f"Display scale set to {choice}.", tone="info")

    def _apply_settings(self):
        """Show/hide the Today's Temp control per the settings toggle and
        re-apply normalization to the active charts."""
        if self.settings_temp_norm_enabled.get():
            self.temp_norm_label.grid()
            self.temp_norm_frame.grid()
        else:
            self.temp_norm_label.grid_remove()
            self.temp_norm_frame.grid_remove()
        self.refresh_all_active_plots()

    def refresh_all_active_plots(self, event=None):
        current_active = sum(1 for e in self.plot_state.values() if e["var"].get())
        if self.show_landing_page:
            self.build_grid()
            return
        frames = self._filtered_frames()
        for name, entry in self.plot_state.items():
            if entry["var"].get() and "canvas" in entry:
                self.update_single_plot(name, current_active, frames=frames)

    def _destroy_panel(self, entry):
        # IMPORTANT: release the canvas's Tk PhotoImage explicitly. matplotlib's
        # FigureCanvasTkAgg blits into a Tcl image ("pyimageN") that plain
        # widget destruction does NOT free — the Tcl image object outlives the
        # widget until the (possibly never-collected) Python PhotoImage is GC'd.
        # Each such image is width*height*4 bytes; on a hi-res/scaled display
        # that's ~10 MB apiece, so toggling dashboards slowly leaks Tk memory
        # until Tcl can't allocate a new image and panels stop painting (the
        # "black screen / freeze" after a while). Deleting it by name frees it
        # immediately. Also cancel the panel's pending debounced-resize job so
        # its `after` callback doesn't fire on a half-torn-down canvas.
        state = entry.get("_resize_state")
        if state is not None and state.get("job") is not None:
            try:
                self.root.after_cancel(state["job"])
            except Exception:
                pass
        # Capture the leaked Tcl image name BEFORE teardown, but delete it AFTER
        # the widget is gone — deleting it out from under a live canvas corrupts
        # matplotlib's blit path.
        canvas = entry.get("canvas")
        photo_name = None
        if canvas is not None:
            photo_name = getattr(getattr(canvas, "_tkphoto", None), "name", None)
        panel = entry.get("panel")
        if panel is not None and panel.winfo_exists():
            try:
                panel.destroy()
            except Exception:
                log.debug("panel destroy raised during teardown", exc_info=True)
        if photo_name is not None:
            try:
                self.root.tk.call("image", "delete", photo_name)
            except Exception:
                pass
        fig = entry.get("fig")
        if fig is not None:
            # Release the mplcursors hover cursor and the click-to-edit event
            # connection this figure may hold — both keep references to the
            # figure's artists/canvas, so dropping them lets the figure and its
            # (large) render buffers actually be collected on close.
            cursor = getattr(fig, "_hover_cursor", None)
            if cursor is not None:
                try:
                    cursor.remove()
                except Exception:
                    pass
                fig._hover_cursor = None
            for cid_attr in ("_shot_pick_cid", "_tooltip_click_cid"):
                cid = getattr(fig, cid_attr, None)
                if cid is not None:
                    try:
                        fig.canvas.mpl_disconnect(cid)
                    except Exception:
                        pass
                    setattr(fig, cid_attr, None)
            plt.close(fig)
        for key in _PANEL_STATE_KEYS:
            entry.pop(key, None)
        entry.pop("_resize_state", None)

    @staticmethod
    def _font_bucket(count: int) -> int:
        return 3 if count >= 3 else count

    def _panel_placement(self, active):
        """Grid placement for up to two panels: returns
        (placement {name: (row, col)}, rows_used, cols_used).

        One panel fills the screen. Two panels sit side by side, UNLESS either
        is a "wide" chart (registry `wide` — many club columns, a timeline),
        in which case they stack so the wide one keeps its full width instead
        of being squeezed to half. (The panel cap is enforced in the toggle
        handler, so `active` is at most two here.)
        """
        active = active[:MAX_ACTIVE_PLOTS]
        if len(active) <= 1:
            return ({active[0]: (0, 0)} if active else {}), 1, 1
        a, b = active[0], active[1]
        if any(self.plot_state[n]["def"].wide for n in (a, b)):
            return {a: (0, 0), b: (1, 0)}, 2, 1   # stacked
        return {a: (0, 0), b: (0, 1)}, 1, 2       # side by side

    def _sc_sync_sessions(self):
        """Keep the Session Comparison panel's session checklist in sync with
        the current master_df: sessions that no longer exist (deleted via
        Manage Sessions, or newly excluded by an on-course setting change)
        are dropped from the checklist, and any newly-eligible sessions are
        added — un-checked, so an existing selection never silently changes.

        Only runs while the panel is actually on screen. Once it's toggled off,
        _destroy_panel drops "canvas" but the entry keeps its (now destroyed)
        dropdown widget reference; calling into that dead widget would raise a
        TclError that aborts the whole build_grid and cascades into every later
        rebuild — which reads to the user as the app "crashing".
        """
        entry = self.plot_state.get(SESSION_COMPARE_NAME)
        if entry is None or "canvas" not in entry or "sc_session_vars" not in entry:
            return
        recent = self._session_options()[:10]
        valid_labels = {label for _sid, label in recent}
        svars = entry["sc_session_vars"]
        # Mutate the existing dict in place (not a fresh one) — the
        # MultiSelectDropdown instance holds a reference to this exact dict,
        # so in-place changes are what it'll actually pick up on refresh.
        for label in [lbl for lbl in svars if lbl not in valid_labels]:
            del svars[label]
        for sid, label in recent:
            svars.setdefault(label, tk.BooleanVar(value=False))
        entry["sc_session_labels"] = {label: sid for sid, label in recent}
        dd = entry.get("sc_session_dd")
        if dd is not None:
            dd.refresh_options()

    def build_grid(self):
        """Diff-based layout: only panels whose active state changed are
        created/destroyed; persisting panels are just re-gridded (and only
        re-rendered when the panel-count font bucket changes). Unconditional
        row-weight resets are kept from the previous fix — grid_size() is
        unreliable once widgets are destroyed.
        """
        any_active = any(e["var"].get() for e in self.plot_state.values())

        if not any_active or self.show_landing_page:
            for entry in self.plot_state.values():
                self._destroy_panel(entry)
            for i in range(MAX_GRID_ROWS):
                self.grid_frame.rowconfigure(i, weight=0)
            self.grid_frame.rowconfigure(0, weight=1)
            self.grid_frame.columnconfigure(0, weight=1)
            self.grid_frame.columnconfigure(1, weight=0)
            if self._home_frame is None or not self._home_frame.winfo_exists():
                self._render_home_page()
            return

        if self._home_frame is not None:
            if self._home_frame.winfo_exists():
                self._home_frame.destroy()
            self._home_frame = None

        # A persisting Session Comparison panel isn't recreated by the
        # diff-based logic below, so its session checklist would otherwise
        # keep showing sessions that got deleted (or excluded by an on-course
        # setting change) after master_df reloads. Sync it on every rebuild.
        # Guarded: this is a non-essential sidebar refresh, so a failure here
        # must never abort the actual panel layout below.
        try:
            self._sc_sync_sessions()
        except Exception:
            log.exception("Session Comparison sync failed; continuing layout")

        active = [name for name, e in self.plot_state.items() if e["var"].get()]
        placement, rows_used, cols_used = self._panel_placement(active)

        for name, entry in self.plot_state.items():
            if name not in placement:
                self._destroy_panel(entry)

        for i in range(MAX_GRID_ROWS):
            self.grid_frame.rowconfigure(i, weight=0)
        for i in range(rows_used):
            self.grid_frame.rowconfigure(i, weight=1)

        # Plain weight (no `uniform=`) on purpose — see git history: mixing
        # weight-0 and weight>0 columns in one uniform group misbehaves
        # across Tk versions. Two side-by-side panels split 50/50.
        self.grid_frame.columnconfigure(0, weight=1)
        self.grid_frame.columnconfigure(1, weight=1 if cols_used == 2 else 0)

        bucket = self._font_bucket(len(placement))
        frames = None
        for name, (r, c) in placement.items():
            entry = self.plot_state[name]
            if "panel" in entry:
                entry["panel"].grid_configure(row=r, column=c)
                if entry.get("bucket") != bucket and entry.get("rendered_once"):
                    entry["bucket"] = bucket
                    if frames is None:
                        frames = self._filtered_frames()
                    self.update_single_plot(name, len(placement), frames=frames)
                else:
                    entry["bucket"] = bucket
            else:
                entry["bucket"] = bucket
                self._place_single_plot_panel(name, r, c)

    def _render_home_page(self):
        """Landing page: the course photo with a frosted-glass stats summary
        composited over it (see ui/home_page.py) — recency and trend info the
        always-visible sidebar records deliberately don't cover."""
        home_frame = build_home_page(
            self.grid_frame, compute_home_stats(self.master_df),
            self._find_background_image(),
            empty_hint=(f"Drop GSPro CSV exports into {config.RAW_CSV_DIR.name}/ — "
                        "they're picked up automatically"),
            trends=compute_home_trends(self.master_df),
            records=compute_player_records(self.master_df),
        )
        home_frame.grid(row=0, column=0, sticky="nsew")
        self._home_frame = home_frame

    @staticmethod
    def _find_background_image():
        if config.BACKGROUND_IMAGE.exists():
            return config.BACKGROUND_IMAGE
        for candidate in config.BASE_DIR.glob("course_bg.*"):
            return candidate
        return None

    def _place_single_plot_panel(self, name, r, c):
        entry = self.plot_state[name]
        d = entry["def"]
        panel = theme.card_frame(self.grid_frame)
        panel.grid(row=r, column=c, sticky="nsew",
                   padx=config.SPACING["md"], pady=config.SPACING["md"])
        theme.add_hover_border(panel)

        top_bar = ctk.CTkFrame(panel, fg_color="transparent")
        top_bar.pack(side=tk.TOP, fill=tk.X, padx=15, pady=8)

        header_color = CATEGORY_HEADER_COLOR.get(d.category, Colors.TEXT_PRIMARY)
        theme.section_label(
            top_bar, name, color=header_color,
            font=ctk.CTkFont(family=config.FONT_FAMILY, size=19, weight="bold"),
        ).pack(side=tk.LEFT)

        def update_local(*_a, n=name):
            current_active = 2 if self.show_landing_page else sum(1 for e in self.plot_state.values() if e["var"].get())
            self.update_single_plot(n, current_active)

        if name == TRAJECTORY_NAME:
            toggle_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
            toggle_frame.pack(side=tk.LEFT, padx=(60, 20))
            theme.toggle_switch(toggle_frame, accent=Colors.SUCCESS, text="All Shots", variable=entry["ind_var"], command=update_local, onvalue=True, offvalue=False).pack(side=tk.LEFT)

        if name == DISPERSION_NAME:
            SingleSelectDropdown(
                top_bar, ["Carry", "Total"], entry["dist_var"], on_change=update_local,
                accent=Colors.INFO, width=110,
            ).pack(side=tk.RIGHT, padx=(10, 5))
            theme.body_label(top_bar, "Distance:", color=Colors.TEXT_MUTED).pack(side=tk.RIGHT)
            SingleSelectDropdown(
                top_bar, ["In-Depth", "Simple"], entry["detail_var"], on_change=update_local,
                accent=Colors.INFO, width=120,
            ).pack(side=tk.RIGHT, padx=(10, 5))
            theme.body_label(top_bar, "Detail:", color=Colors.TEXT_MUTED).pack(side=tk.RIGHT)

        if name == SESSION_COMPARE_NAME:
            clubs = sorted(self.master_df["club"].dropna().unique(), key=get_club_rank) \
                if "club" in self.master_df.columns else []
            if clubs and entry["sc_club_var"].get() not in clubs:
                entry["sc_club_var"].set("Dr" if "Dr" in clubs else clubs[0])
            theme.body_label(top_bar, "Club:", color=Colors.TEXT_MUTED).pack(side=tk.LEFT, padx=(20, 4))
            SingleSelectDropdown(
                top_bar, clubs or ["Dr"], entry["sc_club_var"], on_change=update_local,
                accent=Colors.INFO, width=90,
            ).pack(side=tk.LEFT, padx=(0, 8))
            # Session checklist from the last 10 sessions; default the two most
            # recent selected so the panel shows something immediately.
            recent = self._session_options()[:10]
            labels = {}
            svars: dict[str, tk.BooleanVar] = {}
            for i, (sid, label) in enumerate(recent):
                svars[label] = tk.BooleanVar(value=i < 2)
                labels[label] = sid
            entry["sc_session_vars"], entry["sc_session_labels"] = svars, labels
            theme.body_label(top_bar, "Sessions:", color=Colors.TEXT_MUTED).pack(side=tk.LEFT, padx=(0, 4))
            sc_dd = MultiSelectDropdown(
                top_bar, svars, on_change=update_local, accent=Colors.SUCCESS,
                width=150, item_label="Sessions",
                max_selected=session_compare.MAX_SESSIONS,
                on_limit_exceeded=lambda: show_toast(
                    self.root, f"Session Comparison shows up to "
                    f"{session_compare.MAX_SESSIONS} sessions at once — uncheck one first.",
                    tone="info"),
            )
            sc_dd.pack(side=tk.LEFT, padx=(0, 4))
            entry["sc_session_dd"] = sc_dd

        if name == CLUB_COMPARE_NAME:
            theme.outline_button(
                top_bar, accent=Colors.WARNING, text="Configure…",
                command=lambda n=name: self._open_club_config(n), width=120,
            ).pack(side=tk.LEFT, padx=(20, 6))
            theme.body_label(top_bar, "Now hitting:", color=Colors.TEXT_MUTED).pack(side=tk.LEFT, padx=(0, 4))
            rec_dd = SingleSelectDropdown(
                top_bar, [_CC_OFF], entry["cc_record_var"],
                on_change=lambda n=name: self._cc_on_record_change(n),
                accent=Colors.SUCCESS, width=150,
            )
            rec_dd.pack(side=tk.LEFT, padx=(0, 6))
            entry["cc_record_dd"] = rec_dd
            self._cc_refresh_record_dd(entry)
            theme.outline_button(
                top_bar, accent=Colors.TEXT_MUTED, text="Clear",
                command=lambda n=name: self._cc_clear(n), width=70,
            ).pack(side=tk.LEFT, padx=(0, 4))
            theme.outline_button(
                top_bar, accent=Colors.SUCCESS, text="Export",
                command=lambda n=name: self._export_club_compare(n), width=80,
            ).pack(side=tk.LEFT, padx=(0, 4))

        if name == GAPPING_NAME and "club" in self.master_df.columns:
            for club_name in sorted(self.master_df["club"].dropna().unique()):
                self.gapping_club_vars.setdefault(club_name, tk.BooleanVar(value=True))
            MultiSelectDropdown(
                top_bar, self.gapping_club_vars, on_change=update_local,
                accent=Colors.SUCCESS, width=170, item_label="Clubs", item_colors=config.CLUB_COLORS,
            ).pack(side=tk.RIGHT, padx=(10, 5))

        if name == LAUNCH_SPIN_NAME and "club" in self.master_df.columns:
            clubs = sorted(self.master_df["club"].dropna().unique(), key=get_club_rank)
            if clubs:
                ls_var = entry["ls_club_var"]
                if ls_var.get() not in clubs:
                    ls_var.set("Dr" if "Dr" in clubs else clubs[0])
                SingleSelectDropdown(
                    top_bar, clubs, ls_var, on_change=update_local,
                    accent=Colors.INFO, width=110,
                ).pack(side=tk.RIGHT, padx=(10, 5))
                theme.body_label(top_bar, "Club:", color=Colors.TEXT_MUTED).pack(side=tk.RIGHT)

        # Per-panel benchmark selector (only on charts that declare
        # benchmark_fields) — always a consistent "Benchmarks" checklist
        # dropdown, offering only the reference profiles that actually have
        # data for this chart's metric(s). Writes into entry["benchmark_vars"],
        # read back in update_single_plot.
        bvars = entry.get("benchmark_vars")
        if bvars:
            MultiSelectDropdown(
                top_bar, bvars, on_change=update_local,
                accent=Colors.WARNING, width=160, item_label="Benchmarks",
            ).pack(side=tk.RIGHT, padx=(10, 5))

        # Chart canvas. The figure starts tiny on purpose (see
        # _bind_figure_autosize) so its "natural size" doesn't fight the
        # grid's weight-based column split. The first real <Configure>
        # event triggers exactly one full render at the settled size.
        fig = plt.figure(figsize=(2, 2), dpi=self.chart_dpi, layout="constrained")
        canvas = FigureCanvasTkAgg(fig, master=panel)
        canvas_widget = canvas.get_tk_widget()
        # Dark background so any transient unpainted region during a resize
        # is invisible instead of flashing white.
        canvas_widget.configure(bg=Colors.BG_SURFACE, highlightthickness=0)
        canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        entry["panel"] = panel
        entry["fig"] = fig
        entry["canvas"] = canvas
        self._bind_figure_autosize(canvas_widget, fig, entry, name)

    def _bind_figure_autosize(self, canvas_widget, fig, entry, name):
        """Debounced size sync between the Tk widget and the figure.

        IMPORTANT: binding <Configure> here replaces FigureCanvasTk's own
        internal binding — the only code that resizes the photoimage the
        canvas blits into. So the debounced handler must go through
        canvas.resize() (which resizes figure + photoimage + schedules a
        redraw) rather than fig.set_size_inches() alone, or panels end up
        mostly white on matplotlib >= 3.8.
        """
        state = {"job": None}
        entry["_resize_state"] = state  # so _destroy_panel can cancel a pending job

        def _apply_resize(width, height):
            if width < 20 or height < 20 or "canvas" not in entry:
                return
            canvas = entry["canvas"]
            try:
                canvas.resize(SimpleNamespace(width=width, height=height))
            except Exception:  # very old matplotlib: fall back to figure-only resize
                dpi = fig.get_dpi()
                fig.set_size_inches(width / dpi, height / dpi, forward=True)
                canvas.draw_idle()

            if not entry.get("rendered_once"):
                entry["rendered_once"] = True
                count = sum(1 for e in self.plot_state.values() if e["var"].get()) or 1
                self.update_single_plot(name, count)

        def on_configure(event):
            if state["job"] is not None:
                canvas_widget.after_cancel(state["job"])
            w, h = event.width, event.height
            state["job"] = canvas_widget.after(60, lambda: _apply_resize(w, h))

        canvas_widget.bind("<Configure>", on_configure)

    def update_single_plot(self, name, num_plots=1, frames=None):
        entry = self.plot_state[name]
        if "fig" not in entry or "canvas" not in entry:
            return
        entry["num_plots"] = num_plots

        if name == LIVE_NAME:
            # Feed the Live-view motivation gauges: the all-time club-speed PB
            # (the bar's ceiling) and the latest shot's Shot Quality Score.
            entry["record_club_speed"] = self._record_club_speed
            entry["latest_quality"] = self._live_shot_quality(
                self.live_shot_buffer[-1] if self.live_shot_buffer else None)

        # Fonts shrink as more panels share the grid (each panel gets smaller).
        # 4-up panels are the tightest — especially dense ones like Club Gapping
        # with a label per club — so they step down hardest to avoid overlap.
        base_scale = self.plot_font_scale
        reduction = {1: 0, 2: 1, 3: 3}.get(num_plots, 5)  # 4+ -> base - 5
        font_scale = max(8, base_scale - reduction)

        fig = entry["fig"]

        # Live Dispersion (self.live_shot_buffer) and On-Course Play
        # (self._full_df's course rounds) both have their own data source and
        # can render with zero *practice* history, so they're exempted from
        # this method's "no data" short-circuits below.
        if self.master_df.empty and name not in (LIVE_NAME, ONCOURSE_NAME):
            show_message(
                fig, "No shot data yet", font_scale,
                hint=f"Drop GSPro CSV exports into {config.RAW_CSV_DIR.name}/ — they're picked up automatically",
            )
            entry["canvas"].draw()
            return

        if frames is None:
            frames = self._filtered_frames()
        df_base, df_gap = frames
        # Gapping and Launch & Spin both carry their own club selector and
        # so use the club-filter-ignoring frame (df_gap) instead of df_base.
        if name in (SESSION_COMPARE_NAME, CLUB_COMPARE_NAME):
            df_filtered = self._comparison_frame()
        elif name == TIMELINE_NAME:
            df_filtered = self.master_df  # whole history, ignore the Time filter
        elif name == TRAINING_NAME:
            df_filtered = self._drop_warmup(self.master_df)  # all history, driver focus
        elif name == ONCOURSE_NAME:
            # Course rounds only — this dashboard scores actual play, which
            # practice-only master_df deliberately excludes (see _full_df).
            df_filtered = on_course.on_course_view(self._full_df)
        elif name in (GAPPING_NAME, LAUNCH_SPIN_NAME):
            df_filtered = df_gap
        else:
            df_filtered = df_base

        if name == GAPPING_NAME and "club" in df_filtered.columns:
            active_clubs = [c for c, var in self.gapping_club_vars.items() if var.get()]
            df_filtered = df_filtered[df_filtered["club"].isin(active_clubs)]
        elif name == LAUNCH_SPIN_NAME and "club" in df_filtered.columns:
            ls_var = entry.get("ls_club_var")
            if ls_var is not None and ls_var.get():
                df_filtered = df_filtered[df_filtered["club"] == ls_var.get()]

        fig.clf()

        if "club" in df_filtered.columns:
            unique_clubs = [str(c) for c in df_filtered["club"].dropna().unique()]
            club_colors = {c: config.get_club_color(c) for c in unique_clubs}
        else:
            club_colors = {}

        try:
            if df_filtered.empty and name not in (LIVE_NAME, ONCOURSE_NAME):
                show_message(fig, "No data matching filters", font_scale,
                             hint="Loosen the Time / Club / Shot Quality filters above")
            else:
                entry["def"].render(fig, df_filtered, club_colors, font_scale, entry,
                                    benchmarks=self._selected_benchmarks(entry))
        except Exception:
            log.exception("Chart render failed for %s", name)
            show_message(fig, "Something went wrong rendering this chart.", font_scale,
                         tone="error", hint="See logs/simanalytics.log for details")

        entry["canvas"].draw()
