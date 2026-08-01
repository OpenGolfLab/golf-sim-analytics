# Roadmap

Written 2026-07-25. Two inputs: a feature review from the perspective of a
4-handicap GSPro sim user, and a competitive read against the two apps in this
space. Items are grouped by what they're worth, not by effort.

Findings marked **verified** were checked against the real 1,257-shot history in
`parquet_data/` at the time of writing, not inferred from reading code. Re-check
before acting on any of them — they describe the data as it was.

---

## The one thing

**One screen that opens with the app and answers "what should I hit today, and
why", driven by strokes gained computed from the on-course rounds already on
disk.**

Not a strokes-gained dashboard — a prescription. SG-approach bucketed by distance
and lie; the worst bucket named in plain language; the club that covers that
distance pulled from practice data; one sentence at the top of the app:

> You've lost 1.8 strokes per round from 150–175 out of the fairway across your
> last 12 rounds. Your 7I from that range is your widest club in practice, ±13
> yards. Hit 7-irons today.

Then the post-session debrief says whether it moved.

Why this and not something else:

- The data is **already archived**. `parquet_data/live_rounds_raw/*.json` carries
  `StartingSurface`, `EndingSurface`, `DistanceToPin`, `HolePar`, `Hole`,
  `HoleShot`, 3D `StartingPOS`/`EndingPOS`, `waterhit`/`HazardNumber`, and
  `isPutt`/`isHoled`/`isGimme`. So this is retroactive across every round ever
  tracked, not "starts collecting today".
  `live/shot_data.py::flatten_shot` currently discards the surface fields;
  `heal_missing_holeshot` in the same module is a working precedent for
  backfilling from the raw JSON by `ShotID`.
- Distance-before-the-shot: for any shot after the first on a hole it's the
  previous record's `DistanceToPin` exactly. For tee shots, solve the pin
  position per hole by least squares from the `(EndingPOS, DistanceToPin)` pairs
  already present, then take a straight-line distance from `StartingPOS`. Fall
  back to `TotalDistance + DistanceToPin` on holes with too few shots.
- Baseline table: hardcode a documented expected-strokes table keyed by
  (distance, lie), in the spirit of `data/analytics/targets.py` wrapping
  `config.REFERENCE_PROFILES`. Do **not** derive it from the user's own data —
  that's circular. A coarse table (10-yard steps, 4 lies) is accurate enough to
  rank buckets, which is all that's needed.
- Scope discipline: three distance buckets done right beats twelve done vaguely.
  Any bucket under ~15 shots says "not enough yet" instead of drawing a number.
  Ship the sentence even if the chart behind it is ugly.

Effort: **L** for the engine, but zero new capture.

---

## Wire up what's already built

The highest value-per-hour work in the repo. These are computed and then thrown
away.

| What | Where it's computed | Status |
|---|---|---|
| `focus` (widest club, tightest club, worst bag gap) | `data/store.py::compute_home_trends` | **verified** — `home_page.py` mentions `focus` only inside its own docstring layout diagram |
| `weekly_shots`, `streak_weeks`, `driver_distance` | `compute_home_trends` | **verified** unused |
| `last_clubs`, `last_best_smash`, `delta_club`, `delta_carry` | `compute_home_stats` | **verified** unused |
| `DiagnosticsEngine` | `data/analytics/diagnostics.py` | **verified** — written, tested, exported from `data/analytics/__init__.py`, called nowhere outside `tests/` |

`home_page.py::_redraw` renders only `shot_quality_series`. Its docstring draws a
layout (`[last session | trends]`, `[focus areas | rhythm]`) the code doesn't
build. Replace the "Shots logged / Sessions" trivia row with a "Today's focus"
card fed from `trends.focus` + `DiagnosticsEngine.flags()`, move records to a
collapsed row.

Effort: **S**. It's rendering over data that exists.

While in `DiagnosticsEngine`, add two rules: wedge spin far below the club
window (thin strikes / dirty ball), and a persistent one-way offline bias per
club with ≥20 shots ("your 7I averages 6 yds right — that's aim, not
dispersion").

---

## Data traps

Do not build on these.

- **Nine columns are present-but-all-zero.** **verified**: `path`,
  `facetotarget`, `facetopath`, `lie`, `loft`, `dynamicloft`, `cr`, `hi`, `vi` —
  781 non-null rows each, **zero** non-zero values. They're ingested, so they
  autocomplete and look real in a DataFrame forever. `hi`/`vi` are especially
  tempting (reads like face impact location). `ui/charts/shot_shape.py` already
  works around this correctly using start-line + curve; keep that discipline.
  Consider dropping them at ingest so nobody rediscovers them in six months.
  **This rules out D-plane / face-to-path fault detection entirely.**
- **Putt records are clones.** Putt rows carry the preceding shot's ball data —
  on one round, hole 0 strokes 2, 3 and 4 all read `DistanceToPin = 4.2`. There
  is no real putt distance in this data, and GSPro concedes gimmes (`isGimme`),
  so putt *counts* are systematically low too. **Never compute strokes-gained
  putting.** Count putts, caveat the gimmes, stop there. SG-putting is precisely
  the number a golfer would trust most, which is what makes faking it worst.
- **Implausible launch-monitor reads are unfiltered.** **verified**: smash factor
  in the real history ranges **0.78 to 1.68**. 1.68 is physically impossible;
  0.78 is a whiff or a bad read. `compute_home_stats` clamps to (0.5, 2.0) for
  its own use but the charts don't filter, so those reads sit in dispersion,
  gapping medians and the quality distribution. Add a shared plausibility mask in
  `data/filters.py` (smash outside 0.9–1.6 for full swings, spin outside
  500–15000, carry outside the club's plausible band). Never destroy data — flag
  and exclude, with a "3 implausible reads excluded" note on affected panels.
  Effort: **S**.
- **AoA coverage is partial.** **verified**: non-zero on 488 of 1257 shots (~39%).
  The driver-spin-leak rule fires on `MIN_FLAG_SHOTS = 3`, which could be 3 of 6
  measured shots in a 60-shot session. Show coverage ("based on 12 of 41 driver
  shots with attack-angle data") or the flag reads as more certain than it is.
- **"Theoretical max drive" sits beside measured records.** `data/physics.py`
  says plainly it's calibrated to an *aspirational* ceiling (~350 yd at 125 mph),
  deliberately above what a monitor would show. On the home page it has the same
  styling as "Longest drive" and "Max ball speed", which are facts. Every golfer
  who sees it will quote it as their potential. Move it into Speed Training or
  label it "physics ceiling, not a measurement".
- **Sim carry is not outdoor carry.** `EnvironmentalNormalizer` /
  `air_density_at` / "Today's Temp" are framed as "normalize to standard
  conditions", which implies these numbers travel outdoors. They don't — GSPro
  applies its own ball model and the mat lie is perfect every time. One line on
  the gapping and community panels. This gets more important the moment a Sim
  Index or community percentiles exist.

---

## Feature work, ranked

### 1. Post-session debrief card — **M**
The 90 seconds after you stop hitting is the highest-leverage moment in the loop
and it's currently empty (just a toast: "Archived 63 live-tracked shot(s)"). On
archive, replace the grid with a one-screen debrief: shot count by club; per club
carry median and offline sigma vs the trailing 5 sessions (that's
`live_trends.compute_trends` generalized past the single active club); best and
worst 3 shots by quality; `DiagnosticsEngine` flags for *this session only*; and
one sentence. For an on-course round, scoring-first with the SG line and the two
holes that cost most. All inputs exist.

### 2. Full scorecard stats — **S / M**
Currently: rounds, holes, birdies/eagles, longest drive, best round, scoring
buckets, to-par bars. Missing the five numbers any single-figure golfer can
recite: **GIR, fairways hit, scrambling, putts per round, penalties**, plus
par-3/4/5 splits.
- **S today**: putts (`Putter` rows survive into `_full_df` — that's why
  `exclude_putts` exists separately), penalties (`shot_result == 2`, plus
  `waterhit`/`HazardNumber`), par splits (`holepar`).
- **M, wants the surface columns** from the SG work: GIR exact via
  `ending_surface == 5`, fairways via the tee shot's `ending_surface`, scrambling
  from missed-green holes scored ≤ par.

Also give `on_course_dashboard` a round-range selector — it reads
`on_course.on_course_view(self._full_df)` and ignores every global filter, so
"how have I scored this month" is unanswerable.

### 3. Playable gapping numbers — **S**
The even-gap target dot answers a question nobody asks; a bag *shouldn't* be
evenly gapped. What's needed on the course is the number you trust the club to
cover — roughly the 30th percentile of carry, not the mean. Add a
"Playable / Average" toggle (same pattern as the existing Carry/Total and
Simple/In-Depth toggles): **cover** (p30), **stock** (median), **flush** (p80).
Label the gap between consecutive clubs' *cover* numbers, because that's the gap
that matters. Add a "Copy yardage book" button — `_export_club_compare` is the
`to_csv` precedent. Gate each club at ≥20 shots.

### 4. Dispersion in strokes, with sample-size honesty — **M**
A KDE cloud isn't a decision. Add a "Pattern" mode: one-sigma ellipse per club
with a stats block (carry sigma, offline sigma, average proximity to a notional
pin at stock carry, ellipse dimensions in yards). Under 20 shots, draw the points
but not the ellipse, and say why.

⚠️ **Careful**: `flatten_shot` derives live offline as `carry * sin(az)` — carry-line
offline, no roll. CSV offline is measured and includes roll. Mixing them in one
sigma silently changes what's being measured. Label or exclude live-derived rows
from pattern stats.

### 5. Practice → course transfer — **M**
The question no tool can answer and this app uniquely can: does the range work
show up on the course? `round_type` already tags every shot
(`live/shot_data.py::round_type_for`), and `exclude_on_course_from_practice`
already keeps them apart — good default, but it means the two halves never get
compared. Per club, practice carry median and offline sigma next to on-course
full-swing equivalents. *"7I: 168 practice / 163 on course, spread ±7 vs ±13.
Your irons don't travel."*

### 6. Session shape / generalized fatigue curve — **S**
The within-session fatigue curve is one of the best panels in the app and it's
driver-only, latest-session-only. Pool across all sessions, per club group, vs
shot-number-within-session. `drop_warmup_shots` already uses
`groupby(session_id).cumcount()` — the exact index needed. End in a sentence:
*"Across 34 sessions your quality drops below your session average after about
shot 38. Consider stopping there."* That's a respect-my-time insight worth more
than most charts.

### 7. Sim Index (never "handicap") — ✅ **shipped 2026-07-26**
Shipped as `data/analytics/handicap.py`, on the landing page beside Shot Quality.
WHS-style differential per completed round, best N of the last 20 on WHS's own
table, ≥5 eligible rounds, and the shortfall stated as a path ("5 more rounds
needed, 2 so far") rather than a dash. Marked **verified** once the minimum is
met.

One deviation from this entry, decided by the product owner: it's called **Sim
Handicap**, not Sim Index. The guardrail this entry exists to protect is
enforced by printing "Not a USGA index" permanently under the number rather
than by hiding it in a tooltip, which is stronger than what was asked for
here — a hover can't travel with a number someone quotes to a friend.

Rounds that used a mulligan are excluded outright and marked with an asterisk
across the on-course dashboard (`data/on_course.py::mulligan_flags`), which
removes one of the three caveats this entry listed rather than just disclosing
it. Gimmes and wind settings remain, hence the standing caveat line.

### 8. Community percentiles instead of a cloud — **M**
One dot per contributor per club is the statistically correct unit, but users
want one number: *"your 7I carry is 61st percentile among 0–5 handicaps; your
offline spread is 34th."* The spread number is the useful one.
`contribute.py::_prepare` already sends `handicap_band`, but
`ui/charts/community.py::_FIELD_TO_COLUMN` maps no handicap field back, so the
published aggregate doesn't carry it. Needs a pipeline change outside this repo.
Grey out any band under ~15 contributors and say so.

⚠️ **Before promoting the community layer at all**: the pool is currently seeded
with 11 synthetic contributors (see `SEED_SUBMISSIONS.md`). If a user works that
out while the site presents it as community data, the credibility hit lands on
everything else. Real or clearly labelled first.

### 9. Explain the Shot Quality number — **S** (still open, but reshaped)
A 0–100 with no breakdown is a number users learn to ignore by week two.
`ShotScorer` computes the component scores internally and discards them; return
them and show "78 — strike 92, proximity 61" on hover.

Reshaped by the 2026-07-26 scoring rework. The components are now **strike**
(smash / launch / spin / AoA), **shape** (distance vs your stock number, offline
vs your spread) and **proximity**, and which of them count depends on the shot's
context — so a hover breakdown has to name the context too, or a range shot and
an approach will look like they were scored the same way when they weren't. The
public explanation of all of this now lives in the website user guide
(`opengolflab/src/pages/golf-sim-analytics/guide.astro`, "The numbers"); this
item is what's left to surface *in the app*.

(The carry-direction bug is fixed as of 2026-07-25 — the term is now symmetric
about the club's stock number for every club except driver.)

### 10. Session notes and tags — **S**
In six weeks nobody remembers that the session where start line got tight was the
one where the ball moved back. Without it, every historical trend is a trend with
no explanation. Note + tags per session in Manage Sessions, with a pin marker on
the timelines. `data/adapter_tags.py` is already exactly this pattern — a
`{session_id: label}` JSON sidecar merged in as a column, degrading to "no tags"
on a missing file. Generalize to `{session_id: {note, tags[]}}`.

### 11. Filters that match how people slice — **S / M**
Add "Last 10 Sessions", "Last 90 Days", and a custom date range to
`TIME_FILTER_OPTIONS`. Persist the last-used Time/Club/Quality selections
(`data/settings.py` already does this for scale and units). A-vs-B range compare
on Dispersion and Gapping is the most common spreadsheet operation and has no
equivalent here; `session_compare.py` already does the multi-overlay drawing.

### 12. Fitting report — **S**
Up to 4 configs per session with live capture is uncontested — neither competitor
does fitting at all, and it's where the AGPL "commercial use is fine" license is
a selling point rather than a footnote. The output is currently a bare CSV. Make
it a one-page report a fitter can hand a customer.

### 13. Speed Training as a mode — **M**
Also uncontested. Currently the 9th of 14 sidebar checkboxes. Make it a named
mode: pick a protocol, it counts sets, tells you when speed decayed enough to
stop, shows the week-over-week curve. A product inside the product, and a reason
to open the app on a non-golf day.

---

## Competitive position

Researched 2026-07-25. **Caveat that matters**: everything about GS Caddie comes
from their own marketing site and FAQ. No independent user coverage was reachable
— Reddit blocked the crawler entirely — so treat their feature list as claims,
not verified behaviour.

### GS Caddie — the real competitor
Windows tray app + phone "caddie view", read-only against GSPro, signed
installer, background auto-update, **$12/mo or $99/yr**. Pulls ball data locally
*and* club-delivery data (path, AoA, face-to-target) from the **GSPro Web
Portal**. Ships: strokes gained across tee/approach/short-game/putting on a
Broadie-derived baseline with a handicap-aware shift; 68%/95% dispersion
ellipses; club gapping with dead zones; rule-based insights paired with
hand-vetted drills that collapse across clubs; live per-shot SG and approach
reads; per-club trend alerts; import of your last 10 Portal rounds; share cards;
multi-player attribution. **Your shot data lives in their cloud**; export and
deletion are by email request. Mac/Linux explicitly not planned.

### Golf Shot Analytics — discontinued
Acquired by Nuco LLC 21 Nov 2025, rebuilt as **shotdata.io** (browser SaaS). New
development on the free Windows tool **ended 9 May 2026**; golfshotanalytics.com
is now a redirect funnel whose own comparison table lists the desktop app as
"Stuck at v2.26.4 / Discontinued (was free)". shotdata.io: web-only, 15+ monitors
by CSV, one direct integration (Garmin Golf Premium API), Shotty AI, global
leaderboards. Free tier caps visible shots at **200**; paid $7–$14/mo. Their own
device table lists **GSPro as CSV-only, practice range only** — no on-course
data, no live tracking, structurally.

### What they have that this doesn't
1. **Strokes gained.** Now table stakes, not differentiation. Needed to be in the
   conversation; won't win anything alone.
2. **A phone view.** The biggest *experience* gap. Nobody walks to the PC between
   swings. The best live feature in this app is trapped on the sim screen.
3. **Club-delivery data via the GSPro Web Portal** — a second data source in the
   GSPro ecosystem this app doesn't touch, and the only route to the fields that
   are all zeros in the CSV. ⚠️ **Unverified**: whether the Portal actually
   exposes path/AoA/face-to-target, for which monitors, and whether it's a
   documented API or a scrape. The confirmed GSPro *Open Connect* API is inbound
   only (monitor → GSPro), not a round-data read API. Verify before building.
4. **Insights that end in a drill**, de-duplicated across clubs.
5. **Cold start solved** — they import 10 real rounds; this app offers synthetic
   sample data.
6. **Install trust** — signed installer vs. an unsigned exe and a documented
   SmartScreen "More info → Run anyway" in the README. Losing users at the door.
7. **A live interactive demo on the marketing site** — try before download.
8. **Trend alerting** rather than trend charting. Same data, opposite ergonomics.

### Where this app already wins
- **Capture is in a different class, and nobody knows.** Desktop CSV auto-pickup,
  folder watching, drag-and-drop, live `currentRound.dat` polling, `GSPro.db`
  backfill, *and* `data/reconcile.py` folding a later CSV export into an
  already-live-tracked round instead of duplicating it. **Nobody else has that
  reconcile step.** It's bullet one of nine in a README. Ship a 20-second loop —
  swing, chart moves, zero clicks — as the top of the site. "You will never
  import a file again."
- **Local-first, no subscription.** Competitors: your data in their cloud with
  export by email request; or your own history behind a 200-shot free cap and
  $70–140/yr. Against that, *"your data never leaves your PC, and there is no
  subscription — ever"* is decisive, and it appears nowhere in the marketing.
- **On-course scoring correctness** — `max(holeshot)` mulligan handling and the
  holed-out inference in `hole_summary`. Currently a draw only because they get
  scorecard stats handed to them by the Portal; item 2 above wins it outright.
- **Live in-session trends are more rigorous** than anything either describes:
  median not mean, offline sigma, noise floors so a 0.4-yard change doesn't flash
  green. Wrong screen, though.
- **Speed training and the fitting bay are uncontested.**
- **Practice-depth on GSPro data** is currently the best available, since the one
  tool with comparable depth is discontinued and its cloud successor is thinner.

### The cheap growth window
Golf Shot Analytics' free local Windows tool was killed ~11 weeks ago and its
users are being funnelled to a cloud subscription with a 200-shot free cap. Those
users are exactly this app's profile: free, local, Windows, CSV, privacy-minded.
Two small things capture them: a "coming from Golf Shot Analytics?" page that
says *local, free, no account, no cap*; and two or three more CSV dialects so
they can bring their history (Garmin R10, FlightScope, Uneekor were theirs — and
`data/columns.py`'s alias-group design is already built for exactly this).
Effort: **S** plus an afternoon. The window closes as those users settle.

### Traps — do not copy
1. **Global leaderboards for longest drive / ball speed.** Sim numbers are
   uncalibrated across monitors, altitude, ball models and mats. Meaningless, and
   it recruits the users who don't care about improving. The per-contributor-median
   design is the correct restraint.
2. **A free tier that caps the user's own shots.** The most resentable pattern in
   the category, and it costs this app its best argument.
3. **An LLM as the headline.** Take the output format — one sentence, one focus —
   and reject the mechanism. An AI wrapper buys per-user cost, non-deterministic
   coaching advice, and a privacy story that contradicts "your data never leaves
   your PC". The existing rule engine gets the same sentence, offline, free.
   (Note the market does price the *sentence* at ~$2/mo.)
4. **Mandatory accounts / portal connections.** This app works the moment it's
   installed. That's half the positioning.
5. ~~**Multi-player household support this quarter.**~~ **Shipped** — and it
   turned out not to be the data-model change this entry feared. Attribution
   rides a `{session_id: player}` sidecar (`data/players.py`), the same isolated
   pattern as adapter tags, so Parquet was never touched and the views needed
   one filter argument rather than a rewrite. GSPro names the golfer on course
   rounds; everything else is stamped with the active player.

---

## Beyond GSPro: supporting all launch monitors

Not scheduled — thinking only. Today the app is effectively one CSV dialect plus
GSPro's local files. That's a defensible focus, but it caps the addressable market
hard and it's why competitors get magazine features.

Three tiers, increasing cost:

**Tier 1 — more CSV dialects. Cheap, do this first.**
`data/columns.py` is already alias-group based, which is 80% of the work: adding a
monitor is mostly adding alias spellings. Garmin R10, FlightScope, Uneekor View,
Awesome Golf, Rapsodo, SkyTrak, Bushnell. The real work isn't the columns, it's
the per-monitor semantics — which is already the known hazard here: GSPro's live
offline is derived (`carry * sin(az)`, no roll) while CSV offline is measured;
units differ (`data/io._detect_csv_distance_unit` exists for a reason); "carry"
means different things across firmware. Each new dialect needs a fixture CSV in
`tests/fixtures/` and an explicit note on what each column actually measures,
or the community aggregate quietly mixes incompatible definitions.
**Effort: S per monitor.** This alone captures the orphaned-competitor users.

**Tier 2 — decouple "live tracking" from "GSPro".**
Live tracking is currently GSPro-shaped end to end: `LiveRoundWatcher` polls
`currentRound.dat`, `ClubDataLookup` reads `GSPro.db`, `lm_detect` parses GSPro's
Unity `Player.log`, and `round_type_for` keys off GSPro's `RoundID`. The
abstraction that would generalize it is narrow and already implied by the
`on_new_shot(flat_shot)` callback: a **shot source** that emits flattened shots
plus round boundaries. GSPro's file poller becomes one implementation. Others:

- **GSPro Open Connect** (confirmed: inbound only, monitor → GSPro, port 921).
  Interesting inverted: the app could *present itself as* a GSPro-compatible
  endpoint and have the monitor connect to it directly, with no GSPro at all.
  That would make this a launch-monitor app rather than a GSPro companion — the
  single biggest strategic option available, and worth a spike.
- **Awesome Golf / E6 / TGC** each have their own local stores.
- **Garmin Golf API** — the one direct cloud integration a competitor already
  has, and the only route to R10/R50 auto-sync.

**Effort: M** for the interface refactor, then S–M per source. Do it when there's
a second source actually worth writing, not speculatively.

**Tier 3 — direct launch-monitor SDKs.** Uneekor and Foresight have SDKs behind
developer agreements; most others have nothing public. High cost, per-vendor
legal surface, and it competes with the monitors' own software. Probably never.

**The recommendation**: do Tier 1 now (it's nearly free and there's a time-boxed
audience for it), spike the Open Connect inversion in Tier 2 to find out whether
this can be a launch-monitor app rather than a GSPro app, and skip Tier 3.
