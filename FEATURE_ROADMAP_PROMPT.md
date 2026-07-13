# Golf Sim Analytics — Multi-Phase Feature Expansion

## Role & working agreement

You are extending an existing Python golf-simulator analytics app (Tkinter/customtkinter + matplotlib). **Do not rewrite the app.** Integrate into the existing architecture. Work **one phase at a time**: for each phase, first propose a short architecture/plan and wait for approval, then implement, then run the test suite, then report exactly which files you changed and why. Do not start the next phase until told to.

New analytics logic goes in **dedicated engine modules/classes** (e.g. `data/analytics/diagnostics.py`, `data/analytics/normalizer.py`, `data/analytics/scoring.py`), never dumped into `app.py` or `ui/`.

## Ground truth about this codebase (verified — do not re-derive)

- **Data source:** GSPro CSV exports, ingested via `data/io.py`, column lookup centralized in `data/columns.py` (`find_col` + `*_ALIASES` groups). Charts are registered in `ui/charts/registry.py` (one module per chart). Landing-page summaries live in `data/store.py` (`HomeStats`, `HomeTrends`) and render in `ui/home_page.py`. Physics helpers are in `data/physics.py`. Filtering in `data/filters.py`. There is a real `tests/` suite — add to it.
- **Available per-shot columns:** `Carry, TotalDistance, BallSpeed, BackSpin, SideSpin, HLA, VLA, Decent (descent angle), DistanceToPin, PeakHeight, Offline, rawSpinAxis, Club, ClubSpeed, AoA, Loft, DynamicLoft, SmashFactor`.
- **`AoA` (angle of attack) is present with real values** (driver ~-0.6°, wedges ~-3 to -5°) **but is NOT currently ingested** — there is no alias for it in `data/columns.py`. Any feature using it must add ingestion first.
- **`Path`, `FaceToTarget`, `FaceToPath` are present but ALWAYS 0** in this launch monitor. Do not build any feature on them.
- **No temperature/altitude columns exist.** Environmental normalization is manual-input only.
- **No round/scoring/course/handicap data model exists.** `DistanceToPin` is per-shot only. Handicap tracking is a new data domain (see deferred track).
- A `Dr carry` per-session trend already exists in `data/store.py::compute_home_trends` and renders on the landing page — **extend it, don't duplicate it.**
- The app ships a packaged build under `dist/`. Be conservative about new heavy dependencies (they bloat the package).

## Global constraints

- Keep everything working for empty/partial data (the store already defaults every field safely — preserve that discipline).
- Match existing style, naming, and the chart-registry pattern.
- Every new engine class gets unit tests; every new chart gets a smoke test alongside the existing ones in `tests/`.

---

## Phase 0 — Data & engine foundation (unblocks everything)

**Goal:** plumbing, no user-visible features yet.

1. Add an `AOA_ALIASES` group to `data/columns.py` (`["aoa", "angleofattack", "attackangle", "attack_angle"]`) and wire AoA through ingestion (`data/io.py`) and filtering (`data/filters.py`) exactly like the other numeric metrics.
2. Create `data/analytics/` package with skeletons for the engines used later: `DiagnosticsEngine`, `EnvironmentalNormalizer`, `ShotScorer`, and a `targets.py` holding per-club optimal windows (launch/spin/AoA) — a small, documented, hardcoded tour-reference table that later phases scale.
3. Tests: AoA round-trips through ingestion; `targets.py` returns sane windows for every club in the bag.

**Acceptance:** suite green; AoA visible to downstream code; no UI change.

---

## Phase 1 — Practice Analytics

**Goal:** Shot Quality Score + diagnostic coaching flags + extended driver trend.

1. **Shot Quality Score (0–100)** in `ShotScorer`. **Baseline definition:** score each shot against a blend of (a) the *user's own* recent per-club distribution (carry/dispersion consistency) and (b) the fixed tour-reference launch/spin windows from `targets.py`. Not against a single hardcoded ideal. Expose the weighting as constants so it's tunable. Add a score-trend-over-time view (reuse the sparkline/chart patterns already in the app).
2. **Diagnostic flags** in `DiagnosticsEngine` — rule-based, like the existing `focus` logic in `compute_home_trends`. First rule: driver shot with `BackSpin > 3000` **and** `AoA < 0` → "distance leak: hitting down on driver with high spin." Structure it so more rules drop in trivially.
3. **Driver trends:** extend the existing `Dr carry` trend/metric card — do not create a parallel one.

**Acceptance:** score computes on real sessions and degrades gracefully on sparse data; flag fires only when both conditions hold; tests for the scorer and each rule.

---

## Phase 2 — Global chart & UX features

1. **Simple / In-Depth toggle:** Simple = single average marker; In-Depth = boxplots overlaid on the scatter. One toggle, applied to the dispersion/trajectory charts via the registry.
2. **Session-over-session overlay:** dropdown to overlay the previous session against the current on dispersion/trajectory.
3. **Speed-scaled launch windows:** refactor the `targets.py` windows to scale with `ClubSpeed` — above tour-average club speed (~115 mph driver), the target launch angle decreases to prevent ballooning. The scorer and diagnostics must consume the scaled windows.
4. **Environmental normalization** in `EnvironmentalNormalizer`: normalize ball flight to a standard environment (80°F, sea level) using `data/physics.py`. **Manual temperature input only** — there is no env column. Make it a toggle so raw data is never silently altered.

**Acceptance:** toggles are non-destructive (raw data preserved); scaled windows verified at two club-speed regimes; normalizer has a unit test against known deltas.

---

## Phase 3 — Club Fitting

1. **A/B club comparison:** pick club A, plot it, overlay club B for direct comparison. **Compare carry, dispersion, launch, spin, smash — NOT path/face (dead columns).**
2. **Driver adapter tracking:** let the user tag shots/sessions with an adapter setting (e.g. "+1 Loft, Draw Bias") and view performance per setting. This needs a small persisted tag store (new sidecar/metadata, since the CSVs have no such field) — keep it isolated and optional.

**Acceptance:** A/B overlay reads clearly with two clubs; adapter tags persist across restart and never corrupt shots that have no tag.

---

## Deferred / separate tracks (do NOT bundle into the above)

- **Handicap tracking (own project):** there is no round/scoring/course model. This means designing a new data domain (what constitutes a round, how it's scored, how a handicap is estimated) — spec and build it separately, not alongside chart tweaks.
- **Voice Caddy — parked.** Explicitly out of scope for this expansion; revisit another day. Do not add any TTS dependency (`pyttsx3`/Silero) or audio threading in these phases.

---

When done with each phase, list the files you modified and the tests you added.
