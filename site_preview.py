"""
Golf Sim Analytics — "what will the site show for me?" preview.

This is the reconciliation half of the contribution loop. `contribute.py` says
what you sent; this says what opengolflab.org will publish next to your name
once it aggregates that. If the site shows a median carry beside your display
name, the file this module writes shows the same number — so a contributor can
check the public record against their own machine instead of trusting it.

THIS IS A PORT, NOT A REIMPLEMENTATION.
=======================================
Every rule below is transcribed from `opengolflab-data/aggregate.py` and
specified in `opengolflab-data/AGGREGATION.md`:

  * QC §2.1 global sanity ranges       -> RANGES         (aggregate.RANGES)
  * QC §2.2 per-club physics envelopes -> CLUB_ENVELOPES (aggregate.CLUB_ENVELOPES)
  * QC §2.3 smash bound                -> SMASH_MIN/MAX  (aggregate.SMASH_*)
  * §3 per-(contributor, club) summary -> summarize()    (aggregate._summarize)
  * §3 MIN_CLUB_SHOTS floor            -> MIN_CLUB_SHOTS (aggregate.MIN_CLUB_SHOTS)

The two copies are pinned together by a shared fixture: the same input CSV must
produce the same JSON here and in `opengolflab-data/test_aggregate.py`. See
tests/test_site_preview.py and tests/fixtures/site_preview/. If you change a
threshold or a rule on either side without the other, that fixture fails — which
is the entire point, because a preview that quietly disagrees with the site is
worse than no preview at all.

Why a port instead of importing aggregate.py: the app ships as a standalone .exe
to people who do not have the data repo. Vendoring the whole aggregator would
drag its submission/tier/reputation machinery (none of which a single
contributor's preview needs) into the app. What a preview needs is only the
per-contributor half — QC plus one contributor's own per-club summaries — which
is what this is. Everything downstream of that (cross-contributor medians, trust
tiers, MIN_CONTRIBUTORS) is by definition not knowable from your data alone.
"""
from __future__ import annotations

import csv
import io
import json
import statistics
from collections import defaultdict

# --- QC §2.1: global sanity ranges — rows outside these are dropped ----------
RANGES = {
    "ball_speed": (30, 220), "carry": (5, 400), "launch_angle": (-5, 60),
    "back_spin": (300, 14000), "club_speed": (20, 160), "offline": (-150, 150),
}

# --- QC §2.2: per-club plausibility envelopes (the mislabel catcher) ----------
CLUB_ENVELOPES = {
    "DR": {"carry": (150, 340), "ball_speed": (105, 205)},
    "3W": {"carry": (140, 305), "ball_speed": (100, 190)},
    "5W": {"carry": (130, 290), "ball_speed": (95, 180)},
    "7W": {"carry": (120, 275), "ball_speed": (90, 175)},
    "2H": {"carry": (130, 280), "ball_speed": (95, 178)},
    "3H": {"carry": (125, 270), "ball_speed": (92, 172)},
    "4H": {"carry": (118, 258), "ball_speed": (88, 166)},
    "2I": {"carry": (120, 265), "ball_speed": (90, 168)},
    "3I": {"carry": (115, 255), "ball_speed": (88, 162)},
    "4I": {"carry": (108, 240), "ball_speed": (84, 152)},
    "5I": {"carry": (100, 225), "ball_speed": (80, 146)},
    "6I": {"carry": (92, 212),  "ball_speed": (76, 140)},
    "7I": {"carry": (85, 200),  "ball_speed": (72, 134)},
    "8I": {"carry": (75, 188),  "ball_speed": (66, 126)},
    "9I": {"carry": (65, 172),  "ball_speed": (60, 118)},
    "PW": {"carry": (55, 158),  "ball_speed": (54, 110)},
    "GW": {"carry": (45, 142),  "ball_speed": (48, 103)},
    "SW": {"carry": (28, 128),  "ball_speed": (42, 96)},
    "LW": {"carry": (18, 112),  "ball_speed": (36, 90)},
}

# --- QC §2.3: smash-factor bound (ball_speed / club_speed) -------------------
SMASH_MAX = 1.53
SMASH_MIN = 0.90

# --- §3 thresholds -----------------------------------------------------------
MIN_CLUB_SHOTS = 5     # min shots before a club earns a summary (i.e. a vote)

REQUIRED_SHOT_COLS = {"club", "ball_speed", "launch_angle", "back_spin", "carry"}

PREVIEW_SCHEMA_VERSION = "1.0"

# Thresholds the *site* applies that a single contributor's data cannot satisfy
# alone. Reported in the preview so the honest answer to "why isn't my 4I on the
# site?" is in the file rather than a support question.
MIN_CONTRIBUTORS = 8   # aggregate.MIN_CONTRIBUTORS


def _mad(vals):
    """Median absolute deviation — a robust stand-in for standard deviation."""
    if not vals:
        return None
    m = statistics.median(vals)
    return statistics.median([abs(v - m) for v in vals])


def _med(vals):
    return statistics.median(vals) if vals else None


def valid_shot(r):
    """Clean + QC one CSV row. Returns a shot dict, or None if it fails a
    drop-level check. Port of aggregate._valid_shot — keep them identical."""
    if not REQUIRED_SHOT_COLS.issubset(r.keys()):
        return None
    club = (r.get("club") or "").strip()
    if not club:
        return None
    out = {"club": club, "ball_model": (r.get("ball_model") or "").strip()}
    for k in ("ball_speed", "club_speed", "launch_angle", "back_spin", "carry", "offline"):
        v = r.get(k, "")
        if v in ("", None):
            out[k] = None
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        lo, hi = RANGES.get(k, (-1e9, 1e9))
        if not (lo <= fv <= hi):
            return None
        out[k] = fv

    env = CLUB_ENVELOPES.get(club.upper())
    if env:
        for field in ("carry", "ball_speed"):
            val = out.get(field)
            if val is not None:
                lo, hi = env[field]
                if not (lo <= val <= hi):
                    return None

    bs, cs = out.get("ball_speed"), out.get("club_speed")
    if bs is not None and cs:
        smash = bs / cs
        if smash > SMASH_MAX or smash < SMASH_MIN:
            return None
    return out


def summarize(shots):
    """Robust summary of one club's shots for one contributor.
    Port of aggregate._summarize — keep them identical."""
    carry = [s["carry"] for s in shots if s.get("carry") is not None]
    if not carry:
        return None
    ball = [s["ball_speed"] for s in shots if s.get("ball_speed") is not None]
    launch = [s["launch_angle"] for s in shots if s.get("launch_angle") is not None]
    spin = [s["back_spin"] for s in shots if s.get("back_spin") is not None]
    offline = [s["offline"] for s in shots if s.get("offline") is not None]
    return {
        "n": len(carry),
        "carry_med": statistics.median(carry), "carry_mad": _mad(carry),
        "ball_med": _med(ball), "launch_med": _med(launch), "spin_med": _med(spin),
        "offline_med": _med(offline), "offline_mad": _mad(offline),
    }


def club_summaries(shots):
    """{club: summary} for every club with >= MIN_CLUB_SHOTS valid shots.
    Port of aggregate.contributor_club_summaries."""
    by_club = defaultdict(list)
    for s in shots:
        by_club[s["club"]].append(s)
    out = {}
    for club, club_shots in by_club.items():
        if len(club_shots) >= MIN_CLUB_SHOTS:
            summ = summarize(club_shots)
            if summ:
                out[club] = summ
    return out


# Presentation rounding. The summary maths (summarize()) stays in raw floats so
# it matches aggregate.py exactly; rounding happens only on the way out, because
# this file is read by a person and "carry_spread_mad": 2.700000000000017 is not
# a number anyone asked for. The cross-repo fixture test applies the same
# rounding to aggregate.py's output, so this can't hide a real disagreement.
_SPIN_DP = 0      # rpm — the site publishes whole rpm
_DEFAULT_DP = 1   # yds / mph / degrees


def _round(value, dp=_DEFAULT_DP):
    if value is None:
        return None
    return round(float(value), dp) if dp else int(round(float(value)))


def build_preview(shots_csv: str, manifest: dict) -> dict:
    """The site-preview document for one contribution.

    `shots_csv` and `manifest` are exactly what was sent (see
    contribute.send_bundle's return), so the preview describes the real upload
    rather than a re-derivation of it.
    """
    rows = list(csv.DictReader(io.StringIO(shots_csv)))
    valid = [s for s in (valid_shot(r) for r in rows) if s]
    summaries = club_summaries(valid)

    # Clubs that survived QC but don't have enough shots to earn a summary. The
    # user hit them and they still won't appear — say so plainly rather than
    # letting them wonder where the club went.
    counted = defaultdict(int)
    for s in valid:
        counted[s["club"]] += 1
    below_floor = sorted(c for c, n in counted.items()
                         if c not in summaries and n < MIN_CLUB_SHOTS)

    inst = (manifest.get("environment") or {}).get("instrument") or {}
    clubs = {
        club: {
            "shots_used": s["n"],
            "carry_median": _round(s["carry_med"]),
            "carry_spread_mad": _round(s["carry_mad"]),
            "ball_speed_median": _round(s["ball_med"]),
            "launch_median": _round(s["launch_med"]),
            # Spin is aggregated but only ever *published* at Verified+ — see
            # AGGREGATION.md §4.4. Shown here with that caveat attached rather
            # than hidden, so the number can still be reconciled.
            "spin_median": _round(s["spin_med"], _SPIN_DP),
            "spin_published_only_if": "instrument measures spin (Verified tier)",
            "offline_bias_median": _round(s["offline_med"]),
            "offline_spread_mad": _round(s["offline_mad"]),
        }
        for club, s in sorted(summaries.items())
    }

    return {
        "preview_schema_version": PREVIEW_SCHEMA_VERSION,
        "generated_from": {
            "manifest_schema_version": manifest.get("schema_version"),
            "created_date": manifest.get("created_date"),
            "display_name": manifest.get("display_name"),
            "instrument_model": inst.get("model") or "",
            "instrument_measures_spin": bool(inst.get("measures_spin", False)),
        },
        "shots": {
            "submitted": len(rows),
            "passed_quality_checks": len(valid),
            "dropped_by_quality_checks": len(rows) - len(valid),
        },
        "clubs": clubs,
        "clubs_below_shot_floor": below_floor,
        "rules": {
            "min_club_shots": MIN_CLUB_SHOTS,
            "min_contributors_to_publish": MIN_CONTRIBUTORS,
            "note": (
                "Per-club numbers above are computed from your shots with the "
                "same rules opengolflab.org uses (AGGREGATION.md §2-§3). The "
                "site publishes the median ACROSS contributors, so a club only "
                f"appears once at least {MIN_CONTRIBUTORS} people have "
                f"contributed {MIN_CLUB_SHOTS}+ shots of it. Your numbers are "
                "one vote in each of those medians."
            ),
        },
    }


def preview_json(shots_csv: str, manifest: dict) -> str:
    return json.dumps(build_preview(shots_csv, manifest), indent=2, sort_keys=True)
