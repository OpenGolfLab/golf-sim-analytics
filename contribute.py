"""
Golf Sim Analytics — OpenGolfLab contribution export / upload.

Turns the app's shot history (a pandas DataFrame) into an anonymized,
schema-compliant bundle and either:
  * build_bundle(): writes it to a folder (manual submit), or
  * send_bundle():  POSTs it to the OpenGolfLab intake Worker (automatic).

Only mapped metric columns are included — names, file paths, timestamps and any
other PII are dropped by construction. Contribution is opt-in: both paths refuse
without recorded consent.

Reuses the app's own column-alias resolution (data.columns) so it maps correctly
regardless of how the launch monitor spelled each field.
"""
from __future__ import annotations
import os, re, io, json, uuid, hashlib, datetime, zipfile
import urllib.request, urllib.error
import pandas as pd

from config import get_club_rank
from data import on_course

from data.columns import (
    find_col, CARRY_ALIASES, TOTAL_ALIASES, CLUB_SPEED_ALIASES, BALL_SPEED_ALIASES,
    SMASH_FACTOR_ALIASES, OFFLINE_ALIASES, HEIGHT_ALIASES, LAUNCH_ANGLE_ALIASES,
    DESCENT_ANGLE_ALIASES, SPIN_RATE_ALIASES, START_DIR_ALIASES, SPIN_AXIS_ALIASES,
)

SCHEMA_VERSION = "1.5"   # 1.1 = structured environment.instrument (see instrument_block)
                         # 1.2 = + instrument.verification (claimed monitor vs
                         #       the connectType GSPro's own log reported)
                         # 1.3 = + display_name (the public name shown beside a
                         #       contribution on opengolflab.org)
                         # 1.4 = + self_report.age_band and equipment
                         #       {driver,irons,wedges}{brand,model} — all
                         #       optional, all self-declared, for the site's
                         #       community filters
                         # 1.5 = + provenance {live_tracked, imported} shot
                         #       counts (live rounds never exist as a
                         #       user-editable CSV — a trust signal for
                         #       showcase surfaces, never an acceptance gate)
CONSENT_POLICY_VERSION = "1.0"
HANDICAP_BANDS = ["scratch", "1-4", "5-9", "10-14", "15-19", "20-24", "25+", "unknown"]

# Age is collected as a BAND, never an exact number — it's published in the
# manifest next to a public display name, and "42" next to a name is a lot more
# identifying than "40-49". "unknown" (shown as "Prefer not to say") is the
# default; contribution never requires it.
AGE_BANDS = ["under 30", "30-39", "40-49", "50-59", "60-69", "70+", "unknown"]

# Equipment is bag-level: one optional brand+model for the driver, the iron set,
# and the wedges. Brands come from the Gear Guide's own lineup data
# (opengolflab public/data/*-lineups.json) so community filter spellings stay
# consistent; "Other" catches everything else and "" means not specified.
EQUIPMENT_BRANDS = [
    "", "Callaway", "Cleveland", "Cobra", "Honma", "Mizuno", "PING", "PXG",
    "Srixon", "Sub70", "Takomo", "TaylorMade", "Titleist", "Tour Edge",
    "Wilson", "XXIO", "Other",
]
EQUIPMENT_SLOTS = ("driver", "irons", "wedges")
_EQUIP_MODEL_MAX = 32
# Model names are free text ("Qi10 Max", "P·790" typed as P-790, "Stealth 2+").
# Same philosophy as display names: a tight allowlist the server re-checks.
_EQUIP_MODEL_RE = re.compile(r"^[A-Za-z0-9 .+/'-]+$")


def normalize_equipment(raw: dict | None) -> dict:
    """Clean a {slot: {brand, model}} mapping down to the valid, non-empty
    entries. Unknown slots, unknown brands, and invalid models are dropped —
    equipment is a nicety, never a reason to fail a contribution."""
    out = {}
    for slot in EQUIPMENT_SLOTS:
        entry = (raw or {}).get(slot) or {}
        brand = str(entry.get("brand") or "").strip()
        model = " ".join(str(entry.get("model") or "").split())[:_EQUIP_MODEL_MAX]
        if brand not in EQUIPMENT_BRANDS or not brand:
            brand = ""
        if model and not _EQUIP_MODEL_RE.match(model):
            model = ""
        if brand or model:
            out[slot] = {"brand": brand, "model": model}
    return out

# ---------------------------------------------------------------------------
# Launch-monitor / instrument metadata (manifest v1.1).
#
# `measures_spin` marks monitors that MEASURE spin directly (camera/photometric
# or high-end radar) versus those that model/estimate it. It is DECLARED by the
# user, so it's spoofable — on the aggregation side it only gates whether a
# contribution can reach the "Verified" trust tier, never whether it's accepted.
# Keep this list conservative; it's the maintained allowlist referenced by
# opengolflab-data/AGGREGATION.md §1.
# ---------------------------------------------------------------------------
SPIN_MEASURING = {
    "Trackman", "Foresight GCQuad", "Foresight GC3", "Foresight GCHawk",
    "Bushnell Launch Pro", "Uneekor EYE XO", "Uneekor QED", "Uneekor EYE MINI",
    "Full Swing KIT", "SkyTrak+", "Garmin Approach R50",
}
_MONITOR_KIND = {
    "Trackman": "radar", "Full Swing KIT": "radar", "Garmin Approach R10": "radar",
    "Mevo+": "radar", "FlightScope Mevo": "radar", "PRGR": "radar",
    "Foresight GCQuad": "camera", "Foresight GC3": "camera",
    "Foresight GCHawk": "camera", "Bushnell Launch Pro": "camera",
    "Uneekor EYE XO": "camera", "Uneekor QED": "camera", "Uneekor EYE MINI": "camera",
    "Garmin Approach R50": "photometric", "SkyTrak+": "photometric",
    "SkyTrak": "photometric", "Rapsodo MLM2PRO": "photometric", "Square Golf": "photometric",
}
# Dropdown order for the contribute dialog: blank (undeclared) first, spin-measuring
# units, then modeled-spin units, then a catch-all.
LAUNCH_MONITORS = [
    "", "Trackman", "Foresight GCQuad", "Foresight GC3", "Foresight GCHawk",
    "Bushnell Launch Pro", "Uneekor EYE XO", "Uneekor QED", "Uneekor EYE MINI",
    "Full Swing KIT", "SkyTrak+", "Garmin Approach R50",
    "SkyTrak", "Garmin Approach R10", "Mevo+", "FlightScope Mevo",
    "Rapsodo MLM2PRO", "Square Golf", "PRGR", "Other",
]


# Manufacturer keys for the mismatch check. Two independent maps resolve to
# the same key space: the model the user *claims* in the dropdown, and the
# connectType GSPro's Player.log *observed* (via live/lm_detect.py, stamped on
# live-tracked sessions as an lm_connect_type column). "Bushnell Launch Pro"
# maps to foresight deliberately — it's Foresight-built hardware that connects
# through Foresight's software stack.
_MODEL_MAKER = {
    "Trackman": "trackman",
    "Foresight GCQuad": "foresight", "Foresight GC3": "foresight",
    "Foresight GCHawk": "foresight", "Bushnell Launch Pro": "foresight",
    "Uneekor EYE XO": "uneekor", "Uneekor QED": "uneekor", "Uneekor EYE MINI": "uneekor",
    "Full Swing KIT": "fullswing",
    "SkyTrak+": "skytrak", "SkyTrak": "skytrak",
    "Garmin Approach R50": "garmin", "Garmin Approach R10": "garmin",
    "Mevo+": "flightscope", "FlightScope Mevo": "flightscope",
    "Rapsodo MLM2PRO": "rapsodo",
    "Square Golf": "square",
    "PRGR": "prgr",
}
# connectType -> manufacturer by keyword, not exact string: only "FlightScope"
# has been observed in a real Player.log so far, so substring matching keeps
# this robust to GSPro's exact naming for other vendors. An unrecognized
# connectType resolves to None -> "unverified", never a false mismatch.
# Generic bridge connects (GSPro Connect / OpenAPI) carry no manufacturer, so
# they intentionally have no keyword here.
_CONNECT_TYPE_KEYWORDS = [
    ("flightscope", "flightscope"), ("mevo", "flightscope"),
    ("foresight", "foresight"), ("bushnell", "foresight"), ("launch pro", "foresight"),
    ("trackman", "trackman"),
    ("uneekor", "uneekor"),
    ("full swing", "fullswing"), ("fullswing", "fullswing"),
    ("skytrak", "skytrak"),
    ("garmin", "garmin"), ("r10", "garmin"), ("r50", "garmin"),
    ("rapsodo", "rapsodo"), ("mlm2", "rapsodo"),
    ("square", "square"),
    ("prgr", "prgr"),
]


def _maker_from_connect_type(connect_type: str) -> str | None:
    ct = (connect_type or "").strip().lower()
    for kw, maker in _CONNECT_TYPE_KEYWORDS:
        if kw in ct:
            return maker
    return None


def verification_block(model: str, observed_connect_types) -> dict:
    """Cross-check the user's claimed launch monitor against the connectType(s)
    GSPro's own log reported for the contributed sessions.

    The claim stays the source of truth for model/kind/spin; this only judges
    manufacturer. Statuses:

    - "match": every observed connectType that resolves to a manufacturer
      agrees with the claimed model's manufacturer.
    - "mismatch": any resolvable observed connectType names a *different*
      manufacturer than the claim — the intake side treats this as bad data.
    - "unverified": nothing to check — no live-tracked sessions in the bundle,
      no claim ("", "Other"), or only connectTypes we can't attribute (e.g. a
      generic GSPro Connect bridge).
    """
    observed = sorted({str(ct).strip() for ct in (observed_connect_types or [])
                       if str(ct).strip() and str(ct).lower() != "nan"})
    claimed_maker = _MODEL_MAKER.get((model or "").strip())
    observed_makers = {m for m in (_maker_from_connect_type(ct) for ct in observed)
                       if m is not None}
    if not claimed_maker or not observed_makers:
        status = "unverified"
    elif observed_makers - {claimed_maker}:
        status = "mismatch"
    else:
        status = "match"
    return {"status": status, "observed_connect_types": observed}


def instrument_block(model: str) -> dict:
    """Structured environment.instrument for the v1.1 manifest. Unknown/blank
    models resolve to kind 'unknown', measures_spin False (Community tier only)."""
    model = (model or "").strip()
    return {
        "model": model,
        "kind": _MONITOR_KIND.get(model, "unknown"),
        "measures_spin": model in SPIN_MEASURING,
    }

CLUB_ALIASES = ["club", "clubname", "club_name"]
BALL_MODEL_ALIASES = ["ball_model", "ballmodel", "ball"]
SHOT_QUALITY_ALIASES = ["shot_quality", "shotquality", "quality"]

# schema field -> app alias group (units already match the app's display units:
# yds / mph / ft / deg / rpm)
_FIELD_ALIASES = {
    "ball_speed": BALL_SPEED_ALIASES,
    "club_speed": CLUB_SPEED_ALIASES,
    "smash": SMASH_FACTOR_ALIASES,
    "launch_angle": LAUNCH_ANGLE_ALIASES,
    "start_dir": START_DIR_ALIASES,
    "back_spin": SPIN_RATE_ALIASES,
    "spin_axis": SPIN_AXIS_ALIASES,
    "carry": CARRY_ALIASES,
    "total": TOTAL_ALIASES,
    "offline": OFFLINE_ALIASES,
    "apex": HEIGHT_ALIASES,
    "descent_angle": DESCENT_ANGLE_ALIASES,
}
_NUMERIC_ORDER = [
    "ball_speed", "club_speed", "smash", "launch_angle", "start_dir",
    "back_spin", "spin_axis", "carry", "total", "offline", "apex", "descent_angle",
]
REQUIRED = ["ball_speed", "launch_angle", "back_spin", "carry"]  # + club


# ---------------------------------------------------------------- consent / id
def get_contributor_uuid(app_dir: str) -> str:
    """Random, persisted, non-identifying id used only to de-duplicate."""
    path = os.path.join(app_dir, ".contributor_id")
    if os.path.exists(path):
        return open(path).read().strip()
    u = str(uuid.uuid4())
    with open(path, "w") as f:
        f.write(u)
    return u

# ---------------------------------------------------------------------------
# Display name — the ONE thing about a contribution that is deliberately public.
#
# Everything else in a bundle is anonymized by construction; this is the name a
# contributor chooses to put on their data, shown next to it on opengolflab.org.
# It is never derived from anything personal: either the user typed it, or it is
# generated from the (random, non-identifying) contributor_uuid.
#
# There is intentionally no "anonymous" path. A contribution always carries a
# name, because the feed is the verification loop — a contributor has to be able
# to find their own row and check the numbers against what the app told them it
# sent. A nameless row can't be found, and can't be checked.
# ---------------------------------------------------------------------------
DISPLAY_NAME_MIN = 3
DISPLAY_NAME_MAX = 24
# Letters, digits, space, hyphen, underscore. Deliberately no punctuation that
# means anything in HTML/markup — the server sanitizes too (defense in depth),
# but the app should never send something the server would have to clean up.
_DISPLAY_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$")

# Short words so adjective+noun+"-abcd" always fits DISPLAY_NAME_MAX.
_NAME_ADJECTIVES = [
    "Steady", "Smooth", "Lofty", "Crisp", "Bold", "Quiet", "Swift", "Solid",
    "Pure", "Keen", "Brisk", "Calm", "Sharp", "Bright", "Deft", "Easy",
]
_NAME_NOUNS = [
    "Fade", "Draw", "Divot", "Wedge", "Mashie", "Niblick", "Birdie", "Eagle",
    "Bunker", "Fairway", "Apex", "Spin", "Carry", "Loft", "Sweep", "Strike",
]


def normalize_display_name(raw: str) -> str | None:
    """Return the cleaned display name, or None if it isn't a valid one.

    Trims, collapses runs of whitespace (so " Big   Rig " and "Big Rig" are the
    same name rather than two), then enforces length + charset.
    """
    name = " ".join(str(raw or "").split())
    if not (DISPLAY_NAME_MIN <= len(name) <= DISPLAY_NAME_MAX):
        return None
    if not _DISPLAY_NAME_RE.match(name):
        return None
    return name


def generated_display_name(contributor_uuid: str) -> str:
    """A stable, friendly name derived from the contributor's own uuid, e.g.
    'SteadyFade-3fa2'.

    Deterministic on purpose: the same contributor gets the same generated name
    on every contribution, so their rows in the public feed group under one
    identity instead of scattering across a new random name each time. Uses
    sha256 rather than hash() because hash() is salted per process and would
    give a different name every launch.
    """
    h = hashlib.sha256(str(contributor_uuid).encode("utf-8")).hexdigest()
    adj = _NAME_ADJECTIVES[int(h[0:8], 16) % len(_NAME_ADJECTIVES)]
    noun = _NAME_NOUNS[int(h[8:16], 16) % len(_NAME_NOUNS)]
    return f"{adj}{noun}-{h[16:20]}"


def resolve_display_name(app_dir: str, configured: str = "") -> tuple[str, bool]:
    """The name this contribution will actually carry: (name, was_generated).

    `configured` is whatever the user has set in Settings. If it's blank or
    invalid we fall back to the generated name rather than sending nothing —
    see the module note above on why there's no nameless path. Callers show the
    returned name to the user *before* they confirm, and use was_generated to
    tell them where it came from.
    """
    name = normalize_display_name(configured)
    if name is not None:
        return name, False
    return generated_display_name(get_contributor_uuid(app_dir)), True


def uuid_prefix(app_dir: str) -> str:
    """The 4-hex prefix of this machine's contributor uuid — the same value
    the aggregator appends when disambiguating a collided display name."""
    return get_contributor_uuid(app_dir).replace("-", "")[:4]


def check_public_name(app_dir: str, configured: str, url: str,
                      timeout: int = 6) -> tuple[str, bool]:
    """Best-effort answer to "what will my name actually look like on the site?"

    Fetches the public claimed-name index (names.json, published by the
    aggregator) and applies the SAME disambiguation rule the aggregator uses:
    if another contributor already claims this name, ours gets a stable
    "-<uuid4hex>" suffix. Because the suffix comes from our own uuid, the app
    can predict it exactly — no server round-trip at aggregation time, no
    registration step.

    Returns (public_name, collided). On any network/parse failure it returns
    the locally-resolved name with collided=False: the check is a courtesy,
    never a gate, and the suffix rule self-corrects on the site regardless.
    """
    name, _generated = resolve_display_name(app_dir, configured)
    if not url or not str(url).startswith("https://"):
        return name, False
    try:
        import netutil
        req = urllib.request.Request(
            str(url).rstrip("/") + "/names.json",
            headers={"Accept": "application/json",
                     "User-Agent": "GolfSimAnalytics (+https://opengolflab.com)"})
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=netutil.ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        holders = (data.get("names") or {}).get(name.lower(), [])
    except Exception:
        return name, False
    mine = uuid_prefix(app_dir)
    if any(h != mine for h in holders):
        return f"{name}-{mine}", True
    return name, False


def has_consent(app_dir: str) -> bool:
    return os.path.exists(os.path.join(app_dir, ".contribute_consent"))

def record_consent(app_dir: str, accepted: bool) -> None:
    path = os.path.join(app_dir, ".contribute_consent")
    if accepted:
        with open(path, "w") as f:
            json.dump({"policy_version": CONSENT_POLICY_VERSION,
                       "accepted_utc": datetime.datetime.utcnow().isoformat()}, f)
    elif os.path.exists(path):
        os.remove(path)


# ------------------------------------------------------- build the clean bundle
def _prepare(df: pd.DataFrame, *, app_dir: str, handicap_band: str, launch_monitor: str,
             app_version: str, round_dp: int, session_ids=None, display_name: str = "",
             age_band: str = "unknown", equipment: dict | None = None):
    """Return (manifest_dict, clean_shots_dataframe). Requires consent.

    ``session_ids`` (an iterable of session_id values) restricts the bundle to
    just those rounds — this is what lets the Contribute dialog send only the
    rounds the user explicitly picked, instead of their entire history. None
    (the default) keeps every session, preserving the old whole-history
    behaviour for any caller that wants it.

    ``display_name`` is the user's configured name; blank or invalid resolves to
    the generated one (see resolve_display_name), so the manifest always carries
    a name.
    """
    if not has_consent(app_dir):
        raise PermissionError("Contribution is opt-in — call record_consent(app_dir, True) first.")

    if session_ids is not None:
        wanted = {str(s) for s in session_ids}
        if "session_id" not in df.columns:
            raise ValueError("Can't select rounds — this data has no session_id column.")
        df = df[df["session_id"].astype(str).isin(wanted)]
        if df.empty:
            raise ValueError("None of the selected rounds have any shots to contribute.")

    # On-course rounds never go to the community set. They're full of chips,
    # punch-outs, layups and recovery shots, so a per-club median over them
    # doesn't describe how far the user hits that club — which is the only
    # question the community data answers. Enforced here as well as in the
    # picker UI so it's a property of the wire format, not of one dialog.
    df = on_course.practice_view(df, exclude_on_course=True)
    if df.empty:
        raise ValueError("Only practice sessions can be contributed, and the "
                         "selected rounds are all on-course.")

    # Putts (and any other non-swing strokes tagged "Putter") are on-course
    # scoring artifacts with launch data copied from the preceding shot — never
    # real launch-monitor shots — so they must never reach the community set.
    club_col = find_col(df, CLUB_ALIASES)
    if club_col is None:
        raise ValueError("No club column found in the shot data.")
    df = df[df[club_col].astype(str).str.strip().str.casefold() != "putter"]

    out = pd.DataFrame()
    out["club"] = df[club_col].astype(str).str.strip()
    for field in _NUMERIC_ORDER:
        src = find_col(df, _FIELD_ALIASES[field])
        if src is not None:
            out[field] = pd.to_numeric(df[src], errors="coerce").round(round_dp)

    bm = find_col(df, BALL_MODEL_ALIASES)
    if bm is not None:
        out["ball_model"] = df[bm].astype(str).str.strip()
    sq = find_col(df, SHOT_QUALITY_ALIASES)
    if sq is not None:
        out["shot_quality"] = pd.to_numeric(df[sq], errors="coerce").round().astype("Int64")

    req_present = [c for c in REQUIRED if c in out.columns]
    out = out.dropna(subset=req_present)
    out = out[out["club"].str.len() > 0].reset_index(drop=True)
    if out.empty:
        raise ValueError("No shots with the required metrics (club, ball_speed, launch_angle, back_spin, carry).")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "app": {"name": "GolfSimAnalytics", "version": app_version},
        "contributor_uuid": get_contributor_uuid(app_dir),
        # The only deliberately-public field in the bundle (v1.3).
        "display_name": resolve_display_name(app_dir, display_name)[0],
        "created_date": datetime.date.today().isoformat(),
        "consent": {"policy_version": CONSENT_POLICY_VERSION, "accepted": True},
        "environment": {"platform": "GSPro", "instrument": {
            **instrument_block(launch_monitor),
            # Silent honesty check: live-tracked sessions carry the
            # connectType GSPro's log actually reported (lm_connect_type,
            # stamped by live/shot_data.archive_round). A manufacturer
            # conflict with the claimed model -> "mismatch", which the intake
            # side treats as bad data. Never surfaced in the UI.
            "verification": verification_block(
                launch_monitor,
                df["lm_connect_type"].dropna().unique()
                if "lm_connect_type" in df.columns else [],
            ),
        }},
        "self_report": {
            "handicap_band": handicap_band if handicap_band in HANDICAP_BANDS else "unknown",
            # v1.4: banded, optional, self-declared — powers the site's age filter.
            "age_band": age_band if age_band in AGE_BANDS else "unknown",
        },
        "shot_count": int(len(out)),
    }
    # v1.4: bag-level equipment, only if anything was actually specified.
    equip = normalize_equipment(equipment)
    if equip:
        manifest["equipment"] = equip

    # v1.5: provenance. Live-tracked rounds are archived app-internally (their
    # session ids carry the "live-" prefix from live/shot_data) and never exist
    # as a user-editable CSV; everything else arrived as an import. Counted
    # over the shots actually contributed, after all filtering above.
    if "session_id" in df.columns:
        live_mask = df["session_id"].astype(str).str.startswith("live-")
        live_n = int(live_mask.sum())
        manifest["provenance"] = {"live_tracked": live_n,
                                  "imported": int(len(df) - live_n)}
    else:
        manifest["provenance"] = {"live_tracked": 0, "imported": int(len(df))}

    return manifest, out


# ---------------------------------------------------------------------------
# The wire format, in one place.
#
# A bundle is exactly two files: manifest.json and shots.csv. Every path that
# emits one — folder, zip, HTTP POST — serializes through these two helpers, so
# "the .zip I saved" and "the bytes that were POSTed" are the same bytes by
# construction rather than by two call sites happening to agree. That is what
# makes the contribution receipt (write_receipt_zip) a real receipt: it is not a
# re-derivation of what was probably sent, it is the thing that was sent.
# ---------------------------------------------------------------------------
def _manifest_bytes(manifest: dict) -> str:
    return json.dumps(manifest, indent=2)


def _shots_csv(out: pd.DataFrame) -> str:
    return out.to_csv(index=False)


def _write_zip(manifest: dict, shots_csv: str, path: str) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", _manifest_bytes(manifest))
        z.writestr("shots.csv", shots_csv)
    return path


def _zip_name(manifest: dict) -> str:
    return f"opengolflab_{manifest['contributor_uuid'][:8]}_{manifest['created_date']}.zip"


def write_receipt_zip(manifest: dict, shots_csv: str, out_root: str) -> str:
    """Write the exact bundle described by (manifest, shots_csv) to out_root.

    Takes the already-built payload rather than a DataFrame precisely so the
    receipt can't drift from the upload: callers pass back what send_bundle
    reported it sent. See the note above.
    """
    path = os.path.abspath(os.path.join(out_root, _zip_name(manifest)))
    return _write_zip(manifest, shots_csv, path)


# ---------------------------------------------------------------------------
# "This is what you sent" — the human-readable view of a bundle.
#
# summarize_bundle() takes the manifest and the shots.csv *string*, i.e. exactly
# what send_bundle reports it POSTed, and reads the medians back out of that CSV
# text. That indirection is the whole point: it makes the summary a description
# of the bytes that left the machine rather than a second, parallel calculation
# over the original DataFrame that could agree with the upload by luck and
# disagree after any future change to _prepare. Same reasoning as
# write_receipt_zip — see the wire-format note above.
#
# The medians matter because per-shot rows are what gets uploaded, but per-club
# MEDIANS are what appears on The Lab: the site plots one dot per contributor per
# club (see ui/charts/community.py). So the median is the number a user will
# actually see attributed to them publicly, and it's the number they should get
# to check before agreeing to publish.
# ---------------------------------------------------------------------------
# Fields worth showing per club, in display order, with their units. A subset of
# _NUMERIC_ORDER on purpose: this is a verification screen, not a data dump.
SUMMARY_FIELDS = [
    ("carry", "Carry", "yds"),
    ("total", "Total", "yds"),
    ("ball_speed", "Ball speed", "mph"),
    ("club_speed", "Club speed", "mph"),
    ("smash", "Smash", ""),
    ("launch_angle", "Launch", "deg"),
    ("back_spin", "Back spin", "rpm"),
    ("offline", "Offline", "yds"),
]


def summarize_bundle(manifest: dict, shots_csv: str) -> dict:
    """A plain-data summary of a bundle, for showing the user what they sent.

    Returns::

        {"identity": [(label, value), ...],
         "clubs": [{"club": str, "n": int, "medians": {field: float|None}}, ...],
         "fields": [(field, label, unit), ...],
         "shot_count": int,
         "schema_version": str}

    ``clubs`` is ordered by the app's own club ranking so it reads like a bag.
    """
    inst = (manifest.get("environment", {}).get("instrument") or {})
    self_report = manifest.get("self_report") or {}
    prov = manifest.get("provenance") or {}

    monitor = inst.get("model") or inst.get("maker") or "not specified"
    if inst.get("maker") and inst.get("model") and inst["maker"] not in inst["model"]:
        monitor = f"{inst['maker']} {inst['model']}"

    identity = [
        ("Public name", manifest.get("display_name") or "—"),
        ("Contributor ID", f"{str(manifest.get('contributor_uuid', ''))[:8]}…"),
        ("Handicap band", self_report.get("handicap_band", "unknown")),
        ("Age band", self_report.get("age_band", "unknown")),
        ("Launch monitor", monitor),
    ]

    equip = manifest.get("equipment") or {}
    for slot in ("driver", "irons", "wedges"):
        item = equip.get(slot) or {}
        text = " ".join(x for x in (item.get("brand"), item.get("model")) if x).strip()
        if text:
            identity.append((slot.capitalize(), text))

    df = pd.read_csv(io.StringIO(shots_csv)) if shots_csv.strip() else pd.DataFrame()

    # Ball model lives per-shot in the CSV, not in the manifest, so report the
    # distinct values actually being sent rather than claiming a single one.
    if "ball_model" in df.columns:
        balls = sorted({str(b).strip() for b in df["ball_model"].dropna() if str(b).strip()})
        if balls:
            identity.append(("Ball", ", ".join(balls[:3]) + ("…" if len(balls) > 3 else "")))

    if prov:
        identity.append(("Rounds", f"{prov.get('live_tracked', 0)} live-tracked, "
                                   f"{prov.get('imported', 0)} imported"))

    present = [(f, label, unit) for f, label, unit in SUMMARY_FIELDS if f in df.columns]
    clubs = []
    if not df.empty and "club" in df.columns:
        for club in sorted(df["club"].dropna().unique(), key=get_club_rank):
            sub = df[df["club"] == club]
            medians = {}
            for field, _label, _unit in present:
                vals = pd.to_numeric(sub[field], errors="coerce").dropna()
                medians[field] = float(vals.median()) if not vals.empty else None
            clubs.append({"club": str(club), "n": int(len(sub)), "medians": medians})

    return {
        "identity": identity,
        "clubs": clubs,
        "fields": present,
        "shot_count": int(manifest.get("shot_count", len(df))),
        "schema_version": str(manifest.get("schema_version", "")),
    }


def summary_text(summary: dict) -> str:
    """The same summary as plain text, for saving or pasting somewhere."""
    lines = ["What was sent to OpenGolfLab", "=" * 44, ""]
    for label, value in summary["identity"]:
        lines.append(f"{label + ':':<18}{value}")
    lines += ["", f"{'Shots:':<18}{summary['shot_count']}",
              f"{'Schema:':<18}v{summary['schema_version']}", "",
              "Per-club medians (what appears on The Lab)", "-" * 44]
    header = f"{'Club':<6}{'n':>5}  " + "".join(
        f"{label:>13}" for _f, label, _u in summary["fields"])
    lines.append(header)
    for row in summary["clubs"]:
        cells = ""
        for field, _label, _unit in summary["fields"]:
            v = row["medians"].get(field)
            cells += f"{'—':>13}" if v is None else f"{v:>13.1f}"
        lines.append(f"{row['club']:<6}{row['n']:>5}  {cells}")
    return "\n".join(lines) + "\n"


def build_bundle(df: pd.DataFrame, out_root: str, *, app_dir: str,
                 handicap_band: str = "unknown", launch_monitor: str = "",
                 app_version: str = "", round_dp: int = 1, session_ids=None,
                 display_name: str = "", age_band: str = "unknown",
                 equipment: dict | None = None) -> str:
    """Write an anonymized bundle folder to ``out_root`` and return its path."""
    manifest, out = _prepare(df, app_dir=app_dir, handicap_band=handicap_band,
                             launch_monitor=launch_monitor, app_version=app_version,
                             round_dp=round_dp, session_ids=session_ids,
                             display_name=display_name, age_band=age_band,
                             equipment=equipment)
    bundle_dir = os.path.join(out_root, f"{manifest['contributor_uuid'][:8]}_{manifest['created_date']}")
    os.makedirs(bundle_dir, exist_ok=True)
    with open(os.path.join(bundle_dir, "manifest.json"), "w") as f:
        f.write(_manifest_bytes(manifest))
    with open(os.path.join(bundle_dir, "shots.csv"), "w", newline="") as f:
        f.write(_shots_csv(out))
    return bundle_dir


def build_zip(df: pd.DataFrame, out_root: str, *, app_dir: str,
              handicap_band: str = "unknown", launch_monitor: str = "",
              app_version: str = "", round_dp: int = 1, session_ids=None,
              display_name: str = "", age_band: str = "unknown",
              equipment: dict | None = None) -> str:
    """Write a single self-contained .zip bundle into out_root; return its path."""
    manifest, out = _prepare(df, app_dir=app_dir, handicap_band=handicap_band,
                             launch_monitor=launch_monitor, app_version=app_version,
                             round_dp=round_dp, session_ids=session_ids,
                             display_name=display_name, age_band=age_band,
                             equipment=equipment)
    return write_receipt_zip(manifest, _shots_csv(out), out_root)


def send_bundle(df: pd.DataFrame, *, app_dir: str, url: str, key: str | None = None,
                handicap_band: str = "unknown", launch_monitor: str = "",
                app_version: str = "", round_dp: int = 1, timeout: int = 30,
                session_ids=None, display_name: str = "", age_band: str = "unknown",
                equipment: dict | None = None) -> dict:
    """POST an anonymized bundle to the intake Worker.

    Returns the parsed reply, plus ``shot_count`` and — so the caller can offer
    a receipt of exactly what left the machine — the ``manifest`` dict and
    ``shots_csv`` string that were actually posted. Raises RuntimeError on a
    network/server problem.
    """
    if not url or not url.startswith("https://"):
        raise ValueError("Intake URL is not configured.")
    manifest, out = _prepare(df, app_dir=app_dir, handicap_band=handicap_band,
                             launch_monitor=launch_monitor, app_version=app_version,
                             round_dp=round_dp, session_ids=session_ids,
                             display_name=display_name, age_band=age_band,
                             equipment=equipment)
    shots_csv = _shots_csv(out)
    payload = json.dumps({"manifest": manifest, "shots_csv": shots_csv}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        # A real user-agent — Cloudflare's bot filter (error 1010) blocks the
        # default "Python-urllib/x" signature.
        "User-Agent": f"GolfSimAnalytics/{app_version or '1.0'} (+https://opengolflab.com)",
    }
    if key:
        headers["X-OGL-Key"] = key
    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        import netutil
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=netutil.ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Server rejected the upload ({e.code}): {detail[:200]}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach the server: {e.reason}") from None
    return {
        "shot_count": manifest["shot_count"],
        **(data if isinstance(data, dict) else {}),
        # The exact payload, for the receipt. Last so a server reply can never
        # overwrite our own record of what we sent.
        "manifest": manifest,
        "shots_csv": shots_csv,
    }
