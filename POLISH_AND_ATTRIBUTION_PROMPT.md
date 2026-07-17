# Top-Bar Polish, Contributor Attribution & Pro Pass — Golf Sim Analytics + OpenGolfLab

You are working across three sibling repos:

- `C:\dev\golf-sim-analytics` — Windows desktop app (Python 3.13, customtkinter + matplotlib/TkAgg, dark bronze/charcoal theme in `config.Colors`).
- `C:\dev\opengolflab` — the Astro website ("The Lab" lives at `src/pages/lab/`, community page is `src/pages/lab/community.astro`). Builds statically from data in the data repo.
- `C:\dev\opengolflab-data` — intake Cloudflare Worker (`worker/src/index.js`), `aggregate.py`, `SCHEMA.md`, `AGGREGATION.md`, `submissions/`.

Run `pytest` in the app repo before and after. Real data lives in `parquet_data/`. **Do not change the color palette** — `config.Colors` and `CLUB_COLORS` stay as they are; everything else about treatment, layout, and typography is in scope.

## Verification (do this, don't skip it)

- **Widgets:** build in a standalone CTk root and screenshot with PIL `ImageGrab.grab(bbox=...)` over `winfo_rootx/y/width/height` (`-topmost` + `lift()` first). Produce before/after PNGs for everything you touch.
- **Charts:** render on the Agg backend with `load_master_dataframe(config.DATA_DIR)`, `fig.savefig()`, inspect the PNG.
- **Website:** `npm run build` in `opengolflab` must pass; screenshot the community page at desktop and mobile widths.

## Architecture guardrails — do not regress

Read the "Architecture rules" section of `UI_OVERHAUL_PROMPT.md` in this repo and honor all six (panel lifecycle / PhotoImage cleanup in `app_window._destroy_panel`, `canvas.resize` not `set_size_inches`, popup dismissal via `add="+"` binds in `ui/components._PopupDropdownBase`, per-figure hover state, stale-widget-ref gating, single scale authority via `data/settings.resolve_scale()`).

---

## Priority 1 — Top bar: professional restyle + information architecture

**Current state:** the top bar is a row of `theme.outline_button` pills, each with a 2px border in a *different* accent color (bronze, blue, green…). It reads as toy-like. The right side mixes labeled filter dropdowns (Time / Club / Shot Quality) styled the same way as action buttons.

**Required outcome:**

1. **One coherent button language.** Kill the multi-color outline treatment. Actions become quiet, flat/ghost buttons: transparent fill, neutral text (`Colors.TEXT`), subtle hover fill (`Colors.BG_HOVER`), at most a 1px neutral border (`Colors.BORDER`) or none. At most **one** visually primary element in the bar. `Go Live` keeps its stateful treatment (filled accent when live — see `app_window.py:469-471`) but its idle state matches the quiet style.
2. **Consolidate data actions into a single `Data` menu.** Nest `Import CSV` there — *not* under Settings (Settings is configuration; import/contribute are actions). The `Data` dropdown contains: Import CSV…, Contribute Data…, Manage Sessions…. Reuse `ui.components.DropdownPanel` / the existing menu primitives. Window drag-and-drop CSV import must keep working. Result: top-left is `Go Live · Data · Settings` (plus the sidebar toggle).
3. **Separate filters from actions visually.** The right-side filter group (Time / Club / Shot Quality) should read as filters: smaller/quieter chips or labeled selects with a shared neutral treatment, visually grouped (consistent spacing, maybe a hairline separator from the action side). Filter labels ("Time Filter", "Club Filter") can shrink or fold into the control itself.
4. Consistent heights, corner radii, font (through `theme.font()`), and gaps for everything in the bar — audit `theme.outline_button` callers so no orphaned styles remain.

## Priority 2 — Dropdown panel height

**Root cause:** `DropdownPanel._create` (`ui/components.py`) packs content into a `CTkScrollableFrame` with no height, so it reports the CTk default (~200px). `_reposition` then sizes the popup to `winfo_reqheight()`, so every panel — Settings especially — opens ~200px tall and immediately scrolls.

**Required outcome:** a panel opens at `min(natural content height, window bottom − anchor bottom − margin)`. Short content hugs its natural height (no dead space); tall content (Settings) extends down to near the bottom edge of the *app window* and only then scrolls. Applies to all `DropdownPanel` users (Settings, Contribute, Manage Sessions). Measure natural content height from the inner content frame's reqheight, not the scrollframe's. Verify with screenshots: Settings open on a 1080p window should show substantially more rows than today; a short panel (e.g. a filter) must not balloon.

## Priority 3 — Contributor identity, verification loop, and the live feed board

The goal: a contributor can put a name on their data, see exactly what they pushed, see exactly what the site will show next to that name, and find themselves on the community page.

### 3a. Display name in the app

- New Settings field **Display name** persisted in `settings.json` (alongside `ui_scale`, `units`). Validate: trimmed, 3–24 chars, letters/digits/space/`-`/`_` only.
- If unset at contribution time, **generate one deterministically from `contributor_uuid`** (`contribute.get_contributor_uuid`) — e.g. adjective+noun+4 hex chars: `SteadyFade-3fa2`. Deterministic so it's stable across contributions. The contribute flow must *tell the user*: "Contributing as **SteadyFade-3fa2** — set your own name in Settings." Never contribute with no name attached.
- The contribute panel shows the active name before the user confirms; the consent copy must state the name is displayed publicly on opengolflab.org.

### 3b. Manifest + intake worker

- Add `display_name` to the manifest (bump manifest version 1.1 → 1.2) in `contribute._prepare`; update `SCHEMA.md`.
- `worker/src/index.js` validates/sanitizes server-side (length, charset, strip anything HTML-ish) and rejects or normalizes bad values. Remember re-submits overwrite the same per-day folder, so a name change + re-contribute self-corrects that day's submission.

### 3c. Contribution receipts (the verification loop)

After a successful push, offer two exports (both, individually saveable):

1. **"Export what was sent"** — the exact pushed payload. Reuse `contribute.build_zip` (manifest.json + shots CSV); it must be byte-equivalent to what `send_bundle` posted.
2. **"Export site preview"** — what the website will show for *this contributor*: per-club aggregates (medians, counts, any trims/thresholds) computed over the pushed shots using **exactly the rules in `opengolflab-data/AGGREGATION.md` / `aggregate.py`**. This is the reconciliation artifact: if the site shows a median next to their name, this file shows the same number. Do not re-derive the math loosely — port it faithfully and add a cross-repo test fixture (same input CSV → same aggregate JSON in both the app's implementation and `aggregate.py`) so they can't drift.

### 3d. Live feed board on The Lab community page

- Add a **Contributions feed** to `opengolflab/src/pages/lab/community.astro`: most recent contributions with display name, date, shot count, clubs contributed, and launch monitor model. No UUIDs, no filenames, nothing beyond the display name identifies a person.
- The site builds statically from `opengolflab-data`; have `aggregate.py` (or a sibling script) emit a `feed.json` the Astro build consumes. "Live" means fresh as of the last build/deploy — note in the page copy when the feed was last updated. If a per-contributor stat (e.g. their median carry per club) is shown next to a name, it must be computed by the same aggregation code as 3c so it matches the user's exported site preview.

## Priority 4 — Hover detail in the Community tab (app)

`ui/charts/community.py` already attaches a hover tooltip (`attach_hover_tooltip`, line ~86). Extend it to a rich per-point card: club, carry/total, ball model, launch monitor, and contribution date. The data comes from the community read API — which does not exist yet (`docs/COMMUNITY_API.md` is the contract; the dashboard currently shows an offline state without `config.OPENGOLFLAB_COMMUNITY_URL`). So:

- Extend the contract in `docs/COMMUNITY_API.md` with the per-shot fields the tooltip needs (contributed date, ball, device, display name if the shot pool carries it).
- Make the client parsing and tooltip render those fields, degrading gracefully when a field is absent.
- Keep the offline state intact. Test the tooltip against a fixture payload matching the extended contract.

## Priority 5 — Professional hard pass (app-wide)

Do an audit-then-fix pass over the whole app for anything that still reads as amateur. Deliver a short findings list with before/after screenshots, then implement. Look specifically at:

- **Typography hierarchy** — one scale of sizes/weights through `theme.font()`; no raw font sizes.
- **Spacing rhythm** — consistent padding/gap values (move magic numbers to named constants); aligned edges between the top bar, sidebar, and content grid.
- **Consistency across surfaces** — dialogs, dropdown panels, toasts, tooltips, and the shot-edit popup should share corner radius, border, and shadow/elevation treatment.
- **Home page (`ui/home_page.py`)** and any leftovers from `UI_OVERHAUL_PROMPT.md` Priorities 2–3 (size-aware chart typography, scale-system stragglers) — finish what's unfinished there.
- **States** — hover/pressed/disabled/focus on every interactive control; empty states (`ui/empty_state.py`) consistent with the rest.
- **Sidebar + banner** — proportions, alignment, and how the active item is indicated.

For each finding, prefer deriving from existing theme primitives over inventing new ones. Anything you decide *not* to fix, list with a one-line reason.

---

## Order of work

1 and 2 first (small, high-visibility), then 3 end-to-end (app → worker → site), then 4, then 5. Commit nothing — leave the working tree for review. Run `pytest` (app), `npm run build` (site), and produce the screenshot evidence for every priority.
