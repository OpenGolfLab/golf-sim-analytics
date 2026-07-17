"""
Central configuration for Golf Sim Analytics.

Everything that used to be scattered module-level constants in app.py
(paths, colors, club-fitting benchmark tables) lives here so the rest of
the app has one place to look, and the design system (colors/fonts) can
be changed without touching business logic.
"""
from __future__ import annotations

import re
import sys
from collections import namedtuple
from pathlib import Path


# App version — bump this each release. Stamped into OpenGolfLab contribution
# bundles (see contribute.py) so shared data is traceable to a build.
APP_VERSION = "1.0.0"

# OpenGolfLab intake Worker. Paste your deployed Cloudflare Worker URL here to
# enable one-click "Send to OpenGolfLab" in the Contribute dialog. Leave blank
# and only local "Save a copy" is offered. APP_KEY is optional (set it if you
# configured the matching Worker secret).
OPENGOLFLAB_INTAKE_URL = "https://opengolflab-intake.etsmith1414.workers.dev"
OPENGOLFLAB_INTAKE_KEY = ""

# OpenGolfLab community data — powers the Community dashboard (see community.py +
# docs/COMMUNITY_API.md). This is the directory that serves the PUBLIC aggregate
# file community_points.json (per-contributor-club medians, built by the data
# repo's aggregate.py and published to the website's public data). The app
# appends the filename. It's a plain static file — no API, no auth. Until the
# aggregator has published a pool, the fetch 404s and the dashboard shows its
# empty state — never an error. Leave blank to force the offline state.
OPENGOLFLAB_COMMUNITY_URL = "https://opengolflab.com/data"


# ---------------------------------------------------------------------------
# Base paths
# ---------------------------------------------------------------------------
def _resolve_base_dir() -> Path:
    """Where the app's data folders (raw_csvs/, parquet_data/) should live.

    Using Path.cwd() breaks for a packaged --onefile exe: the current
    working directory depends on how the user launches the exe (double
    click vs. shortcut with a custom "Start in" folder vs. launched from
    a terminal), so data can end up scattered in unexpected places.

    Instead, anchor to the directory containing the actual executable
    (frozen build) or this source file (running from source with
    `python app.py`), which is stable regardless of launch method.
    """
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller-built exe.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _resolve_base_dir()
RAW_CSV_DIR = BASE_DIR / "raw_csvs"
DATA_DIR = BASE_DIR / "parquet_data"
LOG_DIR = BASE_DIR / "logs"
# Generated demo data (tools/generate_sample_data.py). The "Use sample data"
# setting points the app here instead of DATA_DIR — real data is never touched.
SAMPLE_DATA_DIR = BASE_DIR / "sample_data"
# Demo datasets selectable in Settings when "Use sample data" is on. Each maps
# a display name to its folder of generated CSVs (ingested to Parquet in-place
# on first use). Keys are the dropdown labels; the first entry is the default.
SAMPLE_DATASETS = {
    "Baseline (6 months)": SAMPLE_DATA_DIR,          # tools/generate_sample_data.py
    "2-Year Progression": BASE_DIR / "sample_data_progression",  # tools/generate_progression_data.py
}

RAW_CSV_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "simanalytics.log"

BACKGROUND_IMAGE = BASE_DIR / "course_bg.jpg"

# ---------------------------------------------------------------------------
# Automatic GSPro CSV export pickup (data/export_watcher.py). GSPro's own
# "Export CSV" button in the Practice Range shot list always saves to the
# Desktop with no way to redirect it, so that's watched by default. This
# is a historical-analytics app — CSVs are the only data path in or out.
# ---------------------------------------------------------------------------
EXPORT_WATCH_DIR = Path.home() / "Desktop"
EXPORT_WATCH_POLL_SECONDS = 5.0

# There is no manual "Ingest CSVs" button — raw_csvs/ itself is polled on
# this interval and any *.csv dropped there (by hand, by a script, or by
# the export watcher above) is ingested automatically.
RAW_CSV_POLL_SECONDS = 5.0

# ---------------------------------------------------------------------------
# Live round tracking (live/round_watcher.py).
#
# GSPro continuously rewrites a small internal file with every shot in the
# round/range session currently in progress. This is NOT part of GSPro's
# documented Open Connect API (checked gsprogolf.com, the Open Connect v1
# docs, GSPro's GitBook knowledge base, and every community connector
# project on GitHub as of July 2026 — none of them reference this file or
# its internal club-index scheme), so treat it as an undocumented internal
# format that could change in a future GSPro update without notice.
#
# It's still a safe, low-risk source to build on: this app only ever reads
# it, on a plain timer, like any other file on disk — no socket connection
# to GSPro, nothing written back. Path follows Unity's standard per-user
# persistent-data convention (%USERPROFILE%\AppData\LocalLow\<Company>\
# <Product>\), the same reasoning as EXPORT_WATCH_DIR above.
# ---------------------------------------------------------------------------
# GSPro's per-user Unity data folder — where GSPro writes currentRound.dat,
# GSPro.db and Player.log. This is Unity's fixed persistent-data location
# (AppData\LocalLow\<Company>\<Product>\), which is independent of where the
# GSPro *executable* is installed, so it's the same for a standard install
# regardless of install drive/folder. It can be overridden at runtime from
# Settings for non-standard setups (a differently-branded build, a redirected
# AppData profile) — see ui.app_window._gspro_data_dir; this is just the default.
GSPRO_DEFAULT_DATA_DIR = Path.home() / "AppData" / "LocalLow" / "GSPro" / "GSPro"
GSPRO_ROUND_FILE = GSPRO_DEFAULT_DATA_DIR / "currentRound.dat"
# GSPro's SQLite DB in the same folder. Its DrivingRangeShot table logs each
# range shot with the club data (ClubSpeed / SmashFactor / AoA) that
# currentRound.dat strips out — read live to enrich live-tracked shots.
GSPRO_DB_FILE = GSPRO_DEFAULT_DATA_DIR / "GSPro.db"
LIVE_POLL_SECONDS = 2.0

# Full-fidelity raw JSON snapshot of every finalized live-tracked round
# (every field GSPro wrote, including full ball-flight trajectories) lives
# here, one file per round — see live/shot_data.py's archive_round().
LIVE_ROUNDS_RAW_DIR = DATA_DIR / "live_rounds_raw"
LIVE_ROUNDS_RAW_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Color tokens — one source of truth for the whole UI + charts.
# Values match the app's existing Discord-inspired dark palette; this just
# formalizes it into a single table instead of scattered hex strings and
# duplicate aliases (the old BG_PANEL = BG_MAIN, BG_DARK = BG_MAIN, etc).
# ---------------------------------------------------------------------------
class Colors:
    # Bronze/copper "deep bronze" scheme — warm dark charcoal backgrounds, a
    # copper-bronze accent, warm greys, and semantic colors pulled into the
    # same warm/earthy family (with a brick red kept for errors/targets).
    # Neutral dark-charcoal surfaces (no brown tint) — the plot panes read as
    # clean charcoal; the warmth comes from the bronze accent + club colors.
    BG_BASE = "#161616"      # window background — dark charcoal
    BG_SURFACE = "#1c1c1c"   # cards / chart panels — dark charcoal
    BG_SIDEBAR = "#0e0e0e"   # sidebar — very dark, almost black
    BG_HOVER = "#2c2519"     # hover / selected state — warm bronze-dark (accent)

    ACCENT = "#a38c71"       # deep copper-bronze — primary actions, active nav
    ACCENT_HOVER = "#b6a081"  # warmer/lighter bronze on hover

    TEXT_PRIMARY = "#c4c2bd"  # light grey — body/labels
    TEXT_ACTIVE = "#f0efea"   # near-white — active/selected
    TEXT_MUTED = "#8f8d88"    # muted grey — axis ticks, secondary text
    TEXT_ON_LIGHT = "#161311"  # dark text for bronze/light accent fills

    SUCCESS = "#8a9a6f"      # sage green — good shots, live indicators
    INFO = "#6f8b9c"         # blue-grey — carry / neutral metrics
    WARNING = "#c0a878"      # warm gold — ball speed, marginal zones
    DANGER = "#9a4242"       # brick red — errors, target gap

    # Fitting-window "zone" fills (trajectory, iron stopping, ...) — kept
    # clearly green / amber / red (more saturated than the muted UI semantics
    # above) so the ideal/acceptable/outside bands pop on the dark charcoal.
    ZONE_GOOD = "#3fae5a"    # clear green — inside the ideal window
    ZONE_WARN = "#d1a340"    # amber — acceptable margin
    ZONE_BAD = "#d24b4b"     # clear red — outside range

    BORDER = "#333333"       # neutral dark border
    BORDER_HOVER = "#575043"  # warm border highlight on hover
    GRID = "#2b2b2b"
    GRID_MAJOR = "#555555"   # emphasized gridlines (e.g. 50-yd dispersion lines)

    CLUB_FALLBACK = "#909090"  # neutral gray for clubs not in CLUB_COLORS


FONT_FAMILY = "Segoe UI"

# Typographic scale (points): caption / body / label / subheading / heading / display
FONT_SCALE = {
    "caption": 12,
    "body": 13,
    "label": 15,
    "subheading": 16,
    "title": 19,      # chart-panel headers
    "heading": 20,
    "display": 28,
}

# Spacing rhythm (pixels)
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}

# ---------------------------------------------------------------------------
# Club-name normalization.
#
# GSPro / launch-monitor CSV exports are inconsistent about how they label
# clubs across devices and firmware versions. In particular, irons show up
# either as "9I" (number-then-letter — what this app has always sorted by)
# or as "I9" (letter-then-number), plus spelled-out variants like "9 Iron"
# or "PITCHING WEDGE". normalize_club_name() is the single place that
# reconciles all of that into one canonical name per club, so sorting
# (get_club_rank), fitting-window lookups, filters, and chart legends never
# see two different labels for the same physical club.
#
# Canonical bag: Dr, 3W, 5W, 2I-9I, Pw, Gw, Sw, Lw. There is no separate
# hybrid slot — this bag doesn't carry a hybrid, so any hybrid reading
# ("4H", "H4", "4 Hybrid", ...) is folded onto the same-numbered iron
# (e.g. "4H" -> "4I") rather than getting its own bucket.
# ---------------------------------------------------------------------------
_CLUB_WORD_ALIASES = {
    "DRIVER": "DR",
    "PITCHINGWEDGE": "PW",
    "PITCHING": "PW",
    "GAPWEDGE": "GW",
    "GAP": "GW",
    "APPROACHWEDGE": "GW",
    "APPROACH": "GW",
    "AW": "GW",
    "SANDWEDGE": "SW",
    "SAND": "SW",
    "LOBWEDGE": "LW",
    "LOB": "LW",
}

_IRON_PREFIX_RE = re.compile(r"^I(?:RON)?(\d)$")            # "I9", "IRON9"
_IRON_SUFFIX_RE = re.compile(r"^(\d)I(?:RON)?$")            # "9I", "9IRON"
_WOOD_PREFIX_RE = re.compile(r"^W(?:OOD)?(\d)$")             # "W3", "WOOD3"
_WOOD_SUFFIX_RE = re.compile(r"^(\d)W(?:OOD)?$")             # "3W", "3WOOD"
_HYBRID_PREFIX_RE = re.compile(r"^H(?:Y|YBRID)?(\d)$")       # "H4", "HY4", "HYBRID4"
_HYBRID_SUFFIX_RE = re.compile(r"^(\d)H(?:Y|YBRID)?$")       # "4H", "4HY", "4HYBRID"


def normalize_club_name(raw) -> str:
    """Map any raw club-name spelling to this app's canonical format
    (e.g. "I9", "9 Iron", "iron9" all -> "9I"; "W3"/"3 Wood" -> "3W";
    "PITCHING WEDGE" -> "Pw"; "4H"/"H4"/"4 Hybrid" -> "4I" — this bag
    doesn't carry a hybrid, so hybrid shots are treated as the
    same-numbered iron). Unrecognized input is title-cased and passed
    through rather than dropped, so it still shows up (just ungrouped)
    rather than silently vanishing.
    """
    if raw is None:
        return raw
    text = str(raw).strip()
    if not text:
        return text

    cleaned = re.sub(r"[\s\-_]+", "", text.upper())
    cleaned = _CLUB_WORD_ALIASES.get(cleaned, cleaned)

    for pattern in (_IRON_PREFIX_RE, _IRON_SUFFIX_RE, _HYBRID_PREFIX_RE, _HYBRID_SUFFIX_RE):
        m = pattern.match(cleaned)
        if m:
            return f"{m.group(1)}I"

    for pattern in (_WOOD_PREFIX_RE, _WOOD_SUFFIX_RE):
        m = pattern.match(cleaned)
        if m:
            return f"{m.group(1)}W"

    return cleaned.title()


# ---------------------------------------------------------------------------
# Club ordering (driver -> lob wedge) used to sort chart axes/legends.
# ---------------------------------------------------------------------------
CLUB_ORDER = {
    "Dr": 1, "3W": 2, "5W": 3,
    "2I": 4, "3I": 5, "4I": 6, "5I": 7, "6I": 8, "7I": 9, "8I": 10, "9I": 11,
    "Pw": 12, "Gw": 13, "Sw": 14, "Lw": 15,
}


def get_club_rank(club_name) -> int:
    return CLUB_ORDER.get(normalize_club_name(club_name), 99)


# The canonical bag: every real club this app knows how to place, color, and
# fit. normalize_club_name() maps all real spellings onto one of these, so a
# label that still isn't in here after normalization is junk — a spreadsheet
# error ("#Div/0!", "#Ref!") or an unmapped launch-monitor slot ("Club8") — not
# a real club.
CANONICAL_CLUBS = frozenset(CLUB_ORDER)

# The putter is deliberately NOT a CANONICAL (swing-analytics) club: on-course
# putts have launch data copied from the preceding shot (GSPro generates no
# real ball flight for a putt), so they'd poison every dispersion / gapping /
# launch axis and inflate contributed shot counts. They ARE kept in the data
# though (tagged "Putter"), because the on-course scorecard counts strokes as
# shots-per-hole — dropping putts would mis-score every round. So this is a
# recognized-but-non-swing label: store.py keeps these rows, and the swing
# dashboards / contribution filter them out (see data.on_course.exclude_putts).
PUTTER_CLUB = "Putter"
NON_SWING_CLUBS = frozenset({PUTTER_CLUB})


def is_bag_club(club_name) -> bool:
    """True only for a label that resolves to a real club in the bag."""
    return normalize_club_name(club_name) in CANONICAL_CLUBS


# ---------------------------------------------------------------------------
# Per-club color assignment — one fixed hex per canonical club name, used
# everywhere a chart or control needs to color-code by club (Dispersion,
# Live Dispersion, Gapping, the club-filter checkmarks, ...).
#
# This used to be computed on the fly from a turbo colormap indexed by each
# club's position in whatever subset of clubs happened to be present in that
# particular chart's filtered data — so the same club could land on a
# different color in different charts (or even the same chart after a filter
# change), since its index in the "present clubs" list wasn't stable. Fixing
# the color per club name here makes it stable everywhere, independent of
# which other clubs are present.
#
# Colors are grouped by bag category so the whole set reads as one system
# rather than an arbitrary rainbow:
#   - Woods (Dr, 3W, 5W): purple ramping to bright pink for the driver.
#   - Irons (2I-9I): dark green (9I) -> light green -> yellow -> orange ->
#     dark orange -> lighter red -> darker red (2I), each step a distinct
#     named color rather than a smooth gradient, so 7I-4I in particular
#     stay easy to tell apart at a glance.
#   - Wedges (Pw, Gw, Sw, Lw): a light blue -> darker blue -> bright violet
#     ramp, so wedges read as their own family distinct from the irons.
# ---------------------------------------------------------------------------
# Sequential copper -> gold -> blue-grey progression across the bag (Dr = rich
# dark copper, wedges cooling into blue-grey), matching the "deep bronze" scheme.
# Interpolated through the mockup's per-club anchor colors so the whole set
# reads as one warm-to-cool ramp rather than a rainbow.
CLUB_COLORS = {
    "Dr": "#844834",
    "3W": "#8c6238",
    "5W": "#99713e",
    "2I": "#a68545",
    "3I": "#b39a52",
    "4I": "#bcab5c",
    "5I": "#c1a84f",
    "6I": "#9ea96a",
    "7I": "#7f9f69",
    "8I": "#6b9a70",
    "9I": "#619490",
    "Pw": "#5a8ba4",
    "Gw": "#4d759d",
    "Sw": "#43617c",
    "Lw": "#385069",
}


def get_club_color(club_name) -> str:
    """Fixed hex color for a club, keyed by its canonical name. Unrecognized
    clubs fall back to a neutral gray rather than raising, matching
    normalize_club_name()'s "show it, don't drop it" philosophy."""
    return CLUB_COLORS.get(normalize_club_name(club_name), Colors.CLUB_FALLBACK)


# ---------------------------------------------------------------------------
# Club-fitting "ideal window" benchmarks, one row per club in bag order.
#
# Anchored to published launch-monitor benchmarks (upyourclub.com "Optimal
# launch monitor numbers for every club"), then smoothed so the bag reads as
# one clean progression rather than repeated bucket values:
#   - Launch angle climbs steadily from the driver to the lob wedge (each
#     club distinct — a driver launches lowest, wedges highest).
#   - Peak height is the SAME target for every club: ~90-110 ft is the ideal
#     flight window regardless of club (the trajectory chart draws it as one
#     set of full-width bands: 80-90 / 110-120 acceptable, red beyond).
#   - Descent (landing) angle climbs steadily from driver (~35-42, per the
#     reference) into the wedges (~53-58) — steeper landings stop faster.
#
# Each value: club -> (launch_range_deg, height_range_ft, descent_range_deg)
# ---------------------------------------------------------------------------
_HEIGHT_WINDOW_FT = (90, 110)
CLUB_FITTING_WINDOWS: dict[str, tuple] = {
    "Dr": ((10.0, 14.0), _HEIGHT_WINDOW_FT, (35.0, 42.0)),
    "3W": ((12.0, 15.0), _HEIGHT_WINDOW_FT, (40.0, 46.0)),
    "5W": ((13.0, 16.0), _HEIGHT_WINDOW_FT, (42.0, 48.0)),
    "2I": ((13.5, 16.5), _HEIGHT_WINDOW_FT, (42.5, 48.5)),
    "3I": ((14.0, 17.0), _HEIGHT_WINDOW_FT, (43.0, 49.0)),
    "4I": ((14.5, 17.5), _HEIGHT_WINDOW_FT, (43.5, 49.5)),
    "5I": ((15.0, 18.5), _HEIGHT_WINDOW_FT, (44.0, 50.0)),
    "6I": ((16.0, 20.0), _HEIGHT_WINDOW_FT, (44.5, 50.5)),
    "7I": ((17.0, 21.0), _HEIGHT_WINDOW_FT, (45.0, 51.0)),
    "8I": ((18.5, 22.5), _HEIGHT_WINDOW_FT, (46.0, 52.0)),
    "9I": ((20.0, 24.0), _HEIGHT_WINDOW_FT, (47.0, 52.5)),
    "Pw": ((25.0, 30.0), _HEIGHT_WINDOW_FT, (50.0, 55.0)),
    "Gw": ((26.5, 31.5), _HEIGHT_WINDOW_FT, (51.0, 56.0)),
    "Sw": ((28.0, 33.0), _HEIGHT_WINDOW_FT, (52.0, 57.0)),
    "Lw": ((29.5, 35.0), _HEIGHT_WINDOW_FT, (53.0, 58.0)),
}
DEFAULT_FITTING_WINDOW = ((12, 16), _HEIGHT_WINDOW_FT, (44, 50))


# ---------------------------------------------------------------------------
# GSPro's currentRound.dat identifies clubs by a raw internal number
# ("ClubIndex"), not a name, and that mapping isn't documented anywhere
# public (see the note above GSPRO_ROUND_FILE). Fill this in as real
# samples come in — hit a known club in GSPro, check the ClubIndex that
# shows up for it in currentRound.dat, add the entry here.
#
# Every live-archived shot also stores its raw ClubIndex in a club_index
# column (see live/shot_data.py), and data/store.py re-resolves "club"
# from club_index on every load — so improving this map later self-heals
# every already-archived live round automatically, the same self-healing
# pattern normalize_club_name() already uses for CSV-sourced data.
# ---------------------------------------------------------------------------
CLUB_INDEX_MAP: dict[int, str] = {
    0: "Dr",
    2: "3W",
    15: "3I",
    16: "4I",
    17: "5I",
    18: "6I",
    19: "7I",
    20: "8I",
    21: "9I",
    22: "Pw",
    23: "Gw",
    24: "Sw",
    25: "Lw",       # lob wedge — confirmed from a live-tracked shot showing ClubIndex 25
    26: PUTTER_CLUB,  # PUTTER — not a lob wedge (an earlier guess). On-course putts
                      # log under ClubIndex 26 with ball data COPIED from the preceding
                      # shot (a putter produces no launch-monitor ball flight), so their
                      # carry/spin/ball-speed are meaningless. Verified across every
                      # archived on-course round: ~all ClubIndex-26 records duplicate a
                      # prior shot's numbers. Tagged "Putter" and excluded from swing
                      # analytics + contribution, but kept so scorecards still count the
                      # stroke (see config.NON_SWING_CLUBS, data.on_course.exclude_putts).
}


def resolve_club_index(index) -> str:
    """Map GSPro's internal numeric ClubIndex to a club label.

    Falls back to a distinguishable "ClubN" placeholder for anything not
    yet in CLUB_INDEX_MAP, rather than dropping the shot — it still shows
    up (just ungrouped, sorted last) instead of silently vanishing, same
    philosophy as normalize_club_name()'s handling of unrecognized text.
    """
    if index is None:
        return "Unknown"
    try:
        index = int(index)
    except (TypeError, ValueError):
        return "Unknown"
    return CLUB_INDEX_MAP.get(index, f"Club{index}")


# ---------------------------------------------------------------------------
# Reference benchmark profiles — per-club averages a user can overlay on
# charts to see "how do I compare?" against different skill levels. Chosen
# from the top-bar Benchmarks dropdown (off by default), keyed by canonical
# club name (see normalize_club_name).
#
# ReferenceMetrics fields default to None; a chart only draws a marker for a
# (profile, club, metric) combination where that field is actually filled
# in, so partially-populated profiles degrade gracefully rather than
# plotting guessed values.
#
# Data availability is uneven, and deliberately so — we only store numbers
# that come from a real published source:
#
# - "PGA Tour" has the full launch-monitor breakdown (club/ball speed,
#   launch, spin, height, descent, carry) from TrackMan's own Tour Averages
#   table (trackman.com/blog/golf/introducing-updated-tour-averages), so it
#   can appear on every chart.
# - The amateur / handicap profiles only have published *carry distances*
#   per club (aggregated Shot Scope / Arccos / TrackMan amateur data via
#   proyardages.com). Per-club launch/spin/descent/ball-speed by handicap
#   isn't published anywhere reliable, so those fields stay None and those
#   profiles only show up on the Club Gapping (carry) chart.
#
# TrackMan doesn't publish tour averages for 2I/5W-gap clubs the amateur
# tables do (or vice-versa) and this bag has no separate hybrid slot, so
# per-profile club coverage varies; missing clubs simply get no marker.
# ---------------------------------------------------------------------------
ReferenceMetrics = namedtuple(
    "ReferenceMetrics",
    "club_speed ball_speed launch_angle spin_rate max_height land_angle carry",
    defaults=(None, None, None, None, None, None, None),
)


def _carry_only(carries: dict[str, float]) -> dict[str, "ReferenceMetrics"]:
    """Build a profile that only knows per-club carry distance."""
    return {club: ReferenceMetrics(carry=yds) for club, yds in carries.items()}


REFERENCE_PROFILES: dict[str, dict[str, ReferenceMetrics]] = {
    "PGA Tour": {
        "Dr": ReferenceMetrics(113, 167, 10.9, 2686, 32, 38, 275),
        "3W": ReferenceMetrics(107, 158, 9.2, 3655, 30, 43, 243),
        "5W": ReferenceMetrics(103, 152, 9.4, 4350, 31, 47, 230),
        "3I": ReferenceMetrics(98, 142, 10.4, 4630, 27, 46, 212),
        "4I": ReferenceMetrics(96, 137, 11.0, 4836, 28, 48, 203),
        "5I": ReferenceMetrics(94, 132, 12.1, 5361, 31, 49, 194),
        "6I": ReferenceMetrics(92, 127, 14.1, 6231, 30, 50, 183),
        "7I": ReferenceMetrics(90, 120, 16.3, 7097, 32, 50, 172),
        "8I": ReferenceMetrics(87, 115, 18.1, 7998, 31, 50, 160),
        "9I": ReferenceMetrics(85, 109, 20.4, 8647, 30, 51, 148),
        "Pw": ReferenceMetrics(83, 102, 24.2, 9304, 29, 52, 136),
    },
    # Average male amateur (~12-13 handicap): the midpoint of the 10- and
    # 15-handicap carry columns below, which lands its driver at ~213yds —
    # matching the widely-cited ~93mph / ~214yd average-golfer figure.
    "Average Golfer": _carry_only({
        "Dr": 213, "3W": 194, "4I": 165, "5I": 156, "6I": 149,
        "7I": 142, "8I": 132, "9I": 122, "Pw": 112, "Gw": 99, "Sw": 83, "Lw": 66,
    }),
    "5 Handicap": _carry_only({
        "Dr": 235, "3W": 212, "4I": 180, "5I": 170, "6I": 162,
        "7I": 155, "8I": 145, "9I": 133, "Pw": 122, "Gw": 108, "Sw": 90, "Lw": 72,
    }),
    "10 Handicap": _carry_only({
        "Dr": 220, "3W": 200, "4I": 170, "5I": 160, "6I": 152,
        "7I": 145, "8I": 135, "9I": 125, "Pw": 115, "Gw": 102, "Sw": 85, "Lw": 68,
    }),
    "15 Handicap": _carry_only({
        "Dr": 205, "3W": 188, "4I": 160, "5I": 151, "6I": 145,
        "7I": 138, "8I": 128, "9I": 118, "Pw": 108, "Gw": 96, "Sw": 80, "Lw": 64,
    }),
    "20 Handicap": _carry_only({
        "Dr": 195, "3W": 178, "4I": 150, "5I": 142, "6I": 136,
        "7I": 130, "8I": 120, "9I": 110, "Pw": 100, "Gw": 89, "Sw": 74, "Lw": 60,
    }),
}

# Dropdown order + a distinct star color per profile (shapes are all stars,
# so color is the only discriminator — kept clear of green/red, which the
# charts reserve for "optimal" and the gapping target dot).
REFERENCE_PROFILE_ORDER = [
    "PGA Tour", "Average Golfer", "5 Handicap", "10 Handicap", "15 Handicap", "20 Handicap",
]
REFERENCE_PROFILE_COLORS = {
    "PGA Tour": "#FFD700",        # gold
    "Average Golfer": "#E67E22",  # carrot orange
    "5 Handicap": "#1ABC9C",      # teal
    "10 Handicap": "#3498DB",     # blue
    "15 Handicap": "#9B59B6",     # purple
    "20 Handicap": "#EC4899",     # magenta
}


def profiles_with(*fields: str, mode: str = "all") -> list[str]:
    """Reference-profile names (in canonical order) that actually have data
    for the given metric field(s) on at least one club — used to populate
    each chart's own benchmark selector with only the profiles it can plot,
    so e.g. Trajectory never offers "Average Golfer" (which has no launch
    angle). mode='all' requires every field present together on some club;
    mode='any' requires at least one of the fields present on some club.
    """
    def has(metrics) -> bool:
        checks = [getattr(metrics, f) is not None for f in fields]
        return all(checks) if mode == "all" else any(checks)

    return [
        name for name in REFERENCE_PROFILE_ORDER
        if any(has(m) for m in REFERENCE_PROFILES[name].values())
    ]


def get_fitting_window(club_name: str):
    """Return (launch_range, height_range_ft, descent_range) for a club.

    club_name is run through normalize_club_name() first so this resolves
    correctly regardless of which raw spelling the launch monitor sent
    (e.g. "I9" and "9 Iron" both resolve to the 9I row, not the default).
    """
    return CLUB_FITTING_WINDOWS.get(normalize_club_name(club_name), DEFAULT_FITTING_WINDOW)


# ---------------------------------------------------------------------------
# Optimal launch angle (deg) + spin (rpm) target per club, scaled to the
# player's own clubhead speed rather than fixed per club. We start from the
# 2024 TrackMan PGA Tour baseline for that club (its tour clubhead speed +
# launch + spin, reused from REFERENCE_PROFILES["PGA Tour"]) and adjust by
# how the player's speed compares to that baseline:
#   - faster than the tour baseline -> flatten launch and cut spin, to avoid
#     ballooning and hold distance;
#   - slower -> add launch and spin, to keep the ball airborne and preserve
#     carry.
# The slower-side gains are steeper than the faster-side reductions (an
# asymmetric fit): low-speed players lose carry to too-little launch/spin
# faster than high-speed players lose it to ballooning.
# ---------------------------------------------------------------------------
_LAUNCH_PER_MPH_FAST = 0.10   # deg removed per mph above the tour baseline
_SPIN_PER_MPH_FAST = 40.0     # rpm removed per mph above the tour baseline
_LAUNCH_PER_MPH_SLOW = 0.15   # deg added per mph below the tour baseline
_SPIN_PER_MPH_SLOW = 60.0     # rpm added per mph below the tour baseline


def _tour_baseline(club_name: str):
    """TrackMan PGA Tour (club_speed, launch_angle, spin_rate) baseline for a
    club — or the nearest club by bag position when that club has no
    published tour numbers (wedges below PW borrow PW; an unrecognized name
    falls back to 7I)."""
    pga = REFERENCE_PROFILES["PGA Tour"]
    club_n = normalize_club_name(club_name)
    metrics = pga.get(club_n)
    if metrics is not None and metrics.club_speed is not None:
        return metrics
    rank = get_club_rank(club_n)
    if rank == 99:  # name we don't recognize at all
        return pga["7I"]
    # Nearest baseline by bag position; on a tie prefer the longer-numbered
    # neighbour (rank >= target) so a 2I borrows 3I, not the 5W a rank away.
    return pga[min(pga, key=lambda k: (abs(get_club_rank(k) - rank), get_club_rank(k) < rank))]


def optimal_launch_spin(club, speed: float = 100.0) -> tuple[float, float]:
    """(optimal launch angle°, optimal spin rpm) for a club at the player's
    own clubhead `speed`, via piecewise-linear scaling off the club's
    TrackMan Tour baseline (see the block comment above). Clamped to physical
    bounds so the chart can never produce a negative or absurd target.
    """
    base = _tour_baseline(club)
    delta_v = speed - base.club_speed
    if delta_v > 0:
        launch = base.launch_angle - delta_v * _LAUNCH_PER_MPH_FAST
        spin = base.spin_rate - delta_v * _SPIN_PER_MPH_FAST
    else:
        launch = base.launch_angle + (-delta_v) * _LAUNCH_PER_MPH_SLOW
        spin = base.spin_rate + (-delta_v) * _SPIN_PER_MPH_SLOW
    launch = min(35.0, max(5.0, launch))
    spin = min(12000.0, max(1500.0, spin))
    return launch, spin
