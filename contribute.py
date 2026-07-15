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
import os, json, uuid, datetime, zipfile
import urllib.request, urllib.error
import pandas as pd

from data.columns import (
    find_col, CARRY_ALIASES, TOTAL_ALIASES, CLUB_SPEED_ALIASES, BALL_SPEED_ALIASES,
    SMASH_FACTOR_ALIASES, OFFLINE_ALIASES, HEIGHT_ALIASES, LAUNCH_ANGLE_ALIASES,
    DESCENT_ANGLE_ALIASES, SPIN_RATE_ALIASES, START_DIR_ALIASES, SPIN_AXIS_ALIASES,
)

SCHEMA_VERSION = "1.1"   # 1.1 = structured environment.instrument (see instrument_block)
CONSENT_POLICY_VERSION = "1.0"
HANDICAP_BANDS = ["scratch", "1-4", "5-9", "10-14", "15-19", "20-24", "25+", "unknown"]

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
             app_version: str, round_dp: int):
    """Return (manifest_dict, clean_shots_dataframe). Requires consent."""
    if not has_consent(app_dir):
        raise PermissionError("Contribution is opt-in — call record_consent(app_dir, True) first.")

    club_col = find_col(df, CLUB_ALIASES)
    if club_col is None:
        raise ValueError("No club column found in the shot data.")

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
        "created_date": datetime.date.today().isoformat(),
        "consent": {"policy_version": CONSENT_POLICY_VERSION, "accepted": True},
        "environment": {"platform": "GSPro", "instrument": instrument_block(launch_monitor)},
        "self_report": {"handicap_band": handicap_band if handicap_band in HANDICAP_BANDS else "unknown"},
        "shot_count": int(len(out)),
    }
    return manifest, out


def build_bundle(df: pd.DataFrame, out_root: str, *, app_dir: str,
                 handicap_band: str = "unknown", launch_monitor: str = "",
                 app_version: str = "", round_dp: int = 1) -> str:
    """Write an anonymized bundle folder to ``out_root`` and return its path."""
    manifest, out = _prepare(df, app_dir=app_dir, handicap_band=handicap_band,
                             launch_monitor=launch_monitor, app_version=app_version, round_dp=round_dp)
    bundle_dir = os.path.join(out_root, f"{manifest['contributor_uuid'][:8]}_{manifest['created_date']}")
    os.makedirs(bundle_dir, exist_ok=True)
    with open(os.path.join(bundle_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    out.to_csv(os.path.join(bundle_dir, "shots.csv"), index=False)
    return bundle_dir


def build_zip(df: pd.DataFrame, out_root: str, *, app_dir: str,
              handicap_band: str = "unknown", launch_monitor: str = "",
              app_version: str = "", round_dp: int = 1) -> str:
    """Write a single self-contained .zip bundle into out_root; return its path."""
    manifest, out = _prepare(df, app_dir=app_dir, handicap_band=handicap_band,
                             launch_monitor=launch_monitor, app_version=app_version, round_dp=round_dp)
    name = f"opengolflab_{manifest['contributor_uuid'][:8]}_{manifest['created_date']}.zip"
    path = os.path.abspath(os.path.join(out_root, name))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("shots.csv", out.to_csv(index=False))
    return path


def send_bundle(df: pd.DataFrame, *, app_dir: str, url: str, key: str | None = None,
                handicap_band: str = "unknown", launch_monitor: str = "",
                app_version: str = "", round_dp: int = 1, timeout: int = 30) -> dict:
    """POST an anonymized bundle to the intake Worker. Returns the parsed reply
    (with shot_count). Raises RuntimeError on a network/server problem."""
    if not url or not url.startswith("https://"):
        raise ValueError("Intake URL is not configured.")
    manifest, out = _prepare(df, app_dir=app_dir, handicap_band=handicap_band,
                             launch_monitor=launch_monitor, app_version=app_version, round_dp=round_dp)
    payload = json.dumps({"manifest": manifest, "shots_csv": out.to_csv(index=False)}).encode("utf-8")
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Server rejected the upload ({e.code}): {detail[:200]}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach the server: {e.reason}") from None
    return {"shot_count": manifest["shot_count"], **(data if isinstance(data, dict) else {})}
