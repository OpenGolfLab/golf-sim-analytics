"""
Golf Sim Analytics — OpenGolfLab contribution export.

Turns the app's shot history (a pandas DataFrame) into an anonymized,
schema-compliant bundle (manifest.json + shots.csv) ready to submit to the
opengolflab-data repo. See that repo's SCHEMA.md for the format.

Only mapped metric columns are written — names, file paths, timestamps and any
other PII are dropped by construction. Contribution is opt-in: build_bundle()
refuses to run without recorded consent.

Reuses the app's own column-alias resolution (data.columns) so it maps correctly
regardless of how the launch monitor spelled each field.
"""
from __future__ import annotations
import os, json, uuid, datetime
import pandas as pd

from data.columns import (
    find_col, CARRY_ALIASES, TOTAL_ALIASES, CLUB_SPEED_ALIASES, BALL_SPEED_ALIASES,
    SMASH_FACTOR_ALIASES, OFFLINE_ALIASES, HEIGHT_ALIASES, LAUNCH_ANGLE_ALIASES,
    DESCENT_ANGLE_ALIASES, SPIN_RATE_ALIASES, START_DIR_ALIASES, SPIN_AXIS_ALIASES,
)

SCHEMA_VERSION = "1.0"
CONSENT_POLICY_VERSION = "1.0"
HANDICAP_BANDS = ["scratch", "1-4", "5-9", "10-14", "15-19", "20-24", "25+", "unknown"]

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
# final CSV column order (only those present get written)
_NUMERIC_ORDER = [
    "ball_speed", "club_speed", "smash", "launch_angle", "start_dir",
    "back_spin", "spin_axis", "carry", "total", "offline", "apex", "descent_angle",
]
REQUIRED = ["ball_speed", "launch_angle", "back_spin", "carry"]  # + club


# ---------------------------------------------------------------- consent / id
def _p(app_dir, name):
    return os.path.join(app_dir, name)

def get_contributor_uuid(app_dir: str) -> str:
    """Random, persisted, non-identifying id used only to de-duplicate."""
    path = _p(app_dir, ".contributor_id")
    if os.path.exists(path):
        return open(path).read().strip()
    u = str(uuid.uuid4())
    with open(path, "w") as f:
        f.write(u)
    return u

def has_consent(app_dir: str) -> bool:
    return os.path.exists(_p(app_dir, ".contribute_consent"))

def record_consent(app_dir: str, accepted: bool) -> None:
    path = _p(app_dir, ".contribute_consent")
    if accepted:
        with open(path, "w") as f:
            json.dump({"policy_version": CONSENT_POLICY_VERSION,
                       "accepted_utc": datetime.datetime.utcnow().isoformat()}, f)
    elif os.path.exists(path):
        os.remove(path)


# ----------------------------------------------------------------- the export
def build_bundle(df: pd.DataFrame, out_root: str, *, app_dir: str,
                 handicap_band: str = "unknown", launch_monitor: str = "",
                 app_version: str = "", round_dp: int = 1) -> str:
    """
    Write an anonymized bundle folder to ``out_root`` and return its path.

    df          : the app's full shot history (any of the aliased column names).
    out_root    : where to create the bundle folder (e.g. a chosen export dir).
    app_dir     : the app's data dir, for the persisted uuid + consent marker.
    """
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
            vals = pd.to_numeric(df[src], errors="coerce")
            out[field] = vals.round(round_dp)

    bm = find_col(df, BALL_MODEL_ALIASES)
    if bm is not None:
        out["ball_model"] = df[bm].astype(str).str.strip()
    sq = find_col(df, SHOT_QUALITY_ALIASES)
    if sq is not None:
        out["shot_quality"] = pd.to_numeric(df[sq], errors="coerce").round().astype("Int64")

    # drop rows missing any required metric, and blank clubs
    req_present = [c for c in REQUIRED if c in out.columns]
    out = out.dropna(subset=req_present)
    out = out[out["club"].str.len() > 0].reset_index(drop=True)
    if out.empty:
        raise ValueError("No shots with the required metrics (club, ball_speed, launch_angle, back_spin, carry).")

    contributor_uuid = get_contributor_uuid(app_dir)
    date = datetime.date.today().isoformat()
    bundle_dir = os.path.join(out_root, f"{contributor_uuid[:8]}_{date}")
    os.makedirs(bundle_dir, exist_ok=True)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "app": {"name": "GolfSimAnalytics", "version": app_version},
        "contributor_uuid": contributor_uuid,
        "created_date": date,
        "consent": {"policy_version": CONSENT_POLICY_VERSION, "accepted": True},
        "environment": {"platform": "GSPro", "launch_monitor": launch_monitor},
        "self_report": {"handicap_band": handicap_band if handicap_band in HANDICAP_BANDS else "unknown"},
        "shot_count": int(len(out)),
    }
    with open(os.path.join(bundle_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    out.to_csv(os.path.join(bundle_dir, "shots.csv"), index=False)
    return bundle_dir
