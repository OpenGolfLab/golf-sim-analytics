# UI Overhaul — Golf Sim Analytics

You are overhauling the user interface of a Windows desktop app (Python 3.13, customtkinter + matplotlib/TkAgg, dark "deep bronze" theme). The goal is a UI that looks deliberate and professional and functions flawlessly at any window size and display scale. **Do not change the color scheme** — the bronze/charcoal palette in `config.Colors` and the warm-to-cool `CLUB_COLORS` ramp stay exactly as they are. Everything else about layout, sizing, typography, and polish is in scope.

Repo: `C:\dev\golf-sim-analytics`. Run `pytest` before and after. Real data lives in `parquet_data/` (some export filenames have future dates that get scrubbed on load — the warnings are expected).

## How to verify your work (do this, don't skip it)

The app can be audited without launching it:

- **Charts:** render on the Agg backend with real data — `load_master_dataframe(config.DATA_DIR)` — then `fig.savefig()` and inspect the PNG. Chart render functions take `(fig, df, club_colors, font_scale, config, **extra)` where `config` is dict-like; pass fake objects with a `.get()` method for the Tk vars (`ind_var`, `dist_var`, `num_plots`, etc.).
- **Widgets:** build them in a standalone CTk root and screenshot with PIL `ImageGrab.grab(bbox=...)` over `winfo_rootx/y/width/height` (set `-topmost` and `lift()` first).
- **Size matrix:** verify every chart at these figure sizes (px, at dpi 125): solo `2100×1360`, side-by-side `1040×1360`, stacked-wide `2100×620`, and a small-laptop solo `1300×760` at dpi 100. A chart is "done" only when all its text is legible and nothing overlaps or clips at every applicable size.

Produce before/after PNGs for every chart you touch.

## Architecture rules — do not regress these

These are hard-won fixes with explanatory comments at each site. Read the comments before touching anything nearby:

1. **`app_window._destroy_panel`** — the Tk PhotoImage leak fix (Tcl `image delete` after `panel.destroy()`, cursor removal, `after`-job cancellation). Any panel-lifecycle change must keep this intact. Verify with a toggle loop watching `len(root.tk.call('image','names'))` and RSS — both must stay flat.
2. **`app_window._bind_figure_autosize`** — resizes must go through `canvas.resize(...)`, never `fig.set_size_inches()` alone (white-panel bug on matplotlib ≥ 3.8).
3. **`ui/components._PopupDropdownBase`** — popup dismissal works via `add="+"` bindings on the parent toplevel, never unbind-by-funcid, because overrideredirect popups never get focus on Windows.
4. **Per-figure hover state** — one `fig._hover_cursor` slot, cleaned up in `_shared.attach_hover_tooltip` / `attach_label_tooltip` and `_destroy_panel`.
5. **Stale widget refs**: `_destroy_panel` only pops `_PANEL_STATE_KEYS`; per-panel widget refs (e.g. `sc_session_dd`) survive on the entry. Any helper reaching into panel widgets must gate on `"canvas" in entry` (see `_sc_sync_sessions` and `tests/test_session_sync_guard.py`).
6. **Scaling authority**: one factor from `data/settings.resolve_scale()` drives `ctk.set_widget_scaling/set_window_scaling` and `chart_dpi` (half-compensated, clamped 80–180). Extend this system; do not add a second one.

---

## Priority 1 — Trajectory chart layout (`ui/charts/trajectory.py`)

This is the worst offender and the motivating complaint.

**Current behavior:** a fixed `gridspec(2, 3, height_ratios=[1.7, 1.0], hspace=0.21)` — flight-path arcs on top, three boxplots (Launch Angle / Peak Height / Descent Angle) below, plus a `fig.legend` row at the bottom. Trajectory is a `WIDE` chart, so with two panels active it stacks and gets the full width but roughly **620px of height**. At that size the arc panel is ~230px tall and the boxplot row is an unreadable ~150px sliver. Even solo there is a large dead band between the arcs and the boxplot row.

**Required outcome:**

1. **Make the arc panel taller everywhere.** Solo, the arcs should get clearly more vertical share than today (something like 2.2–2.5 : 1 instead of 1.7 : 1). Kill the dead band between the rows — the gap between arcs and boxplots should be a normal title-height gap, not a quarter of the figure.
2. **Make the layout height-aware, not panel-count-aware.** Measure the real canvas size (`fig.get_size_inches() * fig.dpi`) at render time. Below a height threshold (the stacked case), the chart must degrade gracefully instead of shrinking everything proportionally. The right degradation is your call, but acceptable options are: arcs-only with the boxplot row dropped; or arcs + a single condensed strip. Whatever you choose, every remaining label must be fully legible at 2100×620.
3. **Fix the legend.** The in-axes club legend (up to 2 columns, upper-right) sits on top of driver arcs. Move it out of the data area or make it compact enough not to collide (e.g. a single horizontal row above the arcs, or merge with the zone legend row). The zone legend ("Ideal / Acceptable / Outside range") currently costs a full row of figure height — fold it into the same line as the club legend or into the boxplot titles.
4. **Stop rotating club tick labels.** Club names are at most three characters ("Dr", "3W", "Pw") — the 55° rotation is pure noise. Keep them horizontal; only rotate if measurement shows genuine collision.
5. **Unknown clubs** (e.g. a "Club8" passthrough from an unrecognized CSV label) currently get a full boxplot column with fitting-window bands that don't apply, and clubs missing a metric (Lw in Peak Height) leave silent empty slots. Decide and implement a consistent rule — e.g. drop clubs from a subplot when they have no data for that metric, and skip fitting bands for clubs without a real window.

## Priority 2 — Size-aware chart typography (all of `ui/charts/`)

`app_window.update_single_plot` scales fonts by **panel count** (`{1: 0, 2: 1, 3: 3}` point reduction), which is wrong twice over: a stacked half-height panel and a side-by-side half-width panel get identical fonts despite radically different geometry, and the 3+/4-up cases are dead code (`MAX_ACTIVE_PLOTS = 2`, solos always render alone).

Replace the bucket system with sizing derived from the actual figure dimensions at render time, so charts adapt to their true pixel budget. Keep the existing `font_scale` parameter flowing into renderers so their internal relative sizing (`font_scale - 2` etc.) keeps working — change what feeds it, not every call site. Then delete the vestigial paths: `_font_bucket`, the `num_plots >= 3` "compact" branches (trajectory's legend suppression, gapping's 3-4-up declutter), and anything else that only fires above two panels. `entry["bucket"]`'s role in avoiding needless re-renders must be preserved or replaced with an equivalent (re-render when the size class changes).

## Priority 3 — One scale system for every hard-coded dimension

The Settings "Display scale" factor scales CTk widgets and chart DPI, but a lot of UI bypasses it:

- **Home page (`ui/home_page.py`)**: everything is drawn on a raw `tk.Canvas` with hard-coded pixel metrics — hero text at 46pt, the shot-quality number at 50pt, tile heights 100/176, `content_w` cap 1320, gap 14. None of it tracks `ui_scale`, so on a projector at 1.5× the landing page stays small while the rest of the app grows. Thread the scale factor (or a shared helper) through the canvas layout and font sizes.
- **Panel headers** (`_place_single_plot_panel`): title font is a raw `size=19` — route through `theme.font()` / `FONT_SCALE`.
- **Sidebar banner** (`course_banner`): fixed `(316, 84)` image inside a fixed `width=340` sidebar. Derive the banner size from the sidebar width so they can't drift apart.
- **Dropdown popups (`ui/components.py`)**: option rows are fixed `width=180` and the checklist scroll frame `width=170`. Session Comparison labels like `"Jul 08, 2026 · 42 shots [stiff-tip]"` truncate. Size popups to their longest item (with a sane max) instead.
- Audit the remaining magic numbers (`padx=(60, 20)` on the trajectory toggle, Settings window offset `+260+140`, toast `wraplength=300`, tooltip `wraplength=240`) and either derive them or move them to named constants in `config.SPACING` / theme.

The test: change Display scale between 80% and 200% — every piece of text and imagery in the app, including the landing page and chart text, should grow or shrink together, with no fixed-size islands.

## Priority 4 — Interaction & layout correctness

1. **Settings dialog (`app_window._open_settings`)**: clicking Settings repeatedly opens multiple stacked windows. Make it a singleton (focus the existing one). Position it relative to the window but clamp on-screen; the `win.after(120, ...)` focus hack suggests it should probably use `grab_set()`/proper transient handling. It's also a fixed-height card — verify it fits at the 1000×640 minimum window and make it scrollable if not.
2. **Top bar at minimum width**: at the 1000px floor, the left buttons (Go Live / Contribute Data / ⚙ Settings) and the right-side filter cluster (Time / Club / Shot Quality / optional Today's Temp) may collide. Verify at 1000×640 with temp normalization enabled; if they collide, let the filter cluster wrap or compress.
3. **Tooltips (`ui/tooltip.py`)**: popups always open to the right of the widget — a tooltip on a right-edge widget (the Today's Temp label) can extend off-screen. Clamp to the screen/window and flip sides when needed.
4. **Panel header consistency**: each chart scatters its controls differently — Trajectory's toggle sits on the left at an arbitrary offset, Dispersion's dropdowns hang right, Session/Club Comparison stack left. Standardize: title on the left, all controls in one right-aligned group, consistent spacing, labels styled identically. While there, give the Trajectory "All Shots" switch a clearer name or a tooltip (it toggles the per-shot arc texture behind the club averages).
5. **Temp entry**: `placeholder_text="off"` never shows because the entry has a `textvariable` (CTk limitation). Either fix the affordance (e.g. a real label / empty-state hint) or drop the placeholder.

## Priority 5 — De-slop pass (visual polish, no palette change)

Flagging things that read as generic/AI-generated rather than designed:

1. **Emoji as iconography**: sidebar section headers use 📊 🎯 ⛳ ⚡ 🏌️, the Settings button uses ⚙, dropdowns append ▾, toasts use ✓ ℹ ⚠ ✕. On Windows these render as full-color Segoe UI Emoji at inconsistent sizes and clash with the muted bronze aesthetic. Replace with restrained monochrome glyphs (unicode shapes that render in text style), simple drawn markers, or nothing — section headers in the accent bronze with the divider already carry the hierarchy. Keep whatever you do consistent across all of them.
2. **"Master your game"** hero on the landing page — 46pt italic "Light" faux-elegance. Either give the landing page a real hero treatment (the app name, or a data-driven greeting) or tone it down; italic display text over a stock golf photo is the single sloppiest note in the app.
3. **Rainbow section accents**: the sidebar section headers all render bronze (good), but the top-bar filter labels are each a different semantic color (green/blue/gold) and `CATEGORY_HEADER_COLOR` tints every panel title by category. That's a lot of unrelated accent colors doing no informational work. Consider quieting these to one or two accents — this is *usage* of the existing palette, not a palette change; keep the change minimal and tasteful.
4. **Trajectory wedge arcs**: Pw/Gw/Sw/Lw are four adjacent blues (deliberate ramp — do not change the hex values). In the arc chart they're indistinguishable. Differentiate by means other than hue where it matters: distinct dash patterns or markers on the average arcs, or direct end-of-line labels instead of a legend.
5. **Boxplot styling**: all-white boxes on every subplot read as unfinished against the otherwise color-coded app. Consider tinting each club's box edge with its club color at subdued alpha (this uses the existing CLUB_COLORS, not new ones).
6. Sweep every chart with the size matrix and fix the same classes of issue found in Trajectory: legends overlapping data, tick-label rotation where labels are short, dead bands from gridspec-vs-constrained-layout fights, and text below ~9pt effective.

## Acceptance checklist

- [ ] Trajectory readable and well-proportioned at all four matrix sizes; arcs panel visibly taller solo; stacked mode degrades gracefully, nothing unreadable.
- [ ] All charts pass the size matrix with no overlap/clipping/sub-9pt text.
- [ ] Display scale 80%→200% scales *everything* including landing page and chart text; no fixed-size islands.
- [ ] Settings is a singleton, fits at 1000×640; top bar doesn't collide at minimum width; tooltips never open off-screen.
- [ ] Panel headers follow one layout convention.
- [ ] No emoji iconography (or a single consistent, deliberately chosen icon treatment).
- [ ] `pytest` green; panel toggle loop shows flat Tcl image count and flat RSS.
- [ ] Before/after PNGs for every chart touched.

Work in this priority order and commit in reviewable slices (Trajectory first — it's the user's explicit pain point).
