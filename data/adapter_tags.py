"""Driver adapter tagging — a small, isolated sidecar store.

GSPro exports have no field for driver adapter settings (e.g. "+1 Loft, Draw
Bias"), so tags live in their own JSON file (``adapter_tags.json`` in the data
dir) keyed by ``session_id`` — the same stable id every archived session already
carries. Tagging is per-session: you set the driver, hit a range session, tag
that session.

Nothing here touches the Parquet history. ``apply_tags`` merges the sidecar into
a DataFrame as an ``adapter`` column, defaulting untagged rows to "" so shots
with no tag are never altered or dropped. Missing or corrupt sidecar files
degrade to "no tags", never an exception.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

_TAGS_FILE = "adapter_tags.json"
ADAPTER_COLUMN = "adapter"
UNTAGGED = ""


def _tags_path(data_dir) -> Path:
    return Path(data_dir) / _TAGS_FILE


def load_tags(data_dir) -> dict[str, str]:
    """Return the {session_id: label} map, or {} when the file is absent,
    unreadable, or malformed. Blank labels are dropped."""
    path = _tags_path(data_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Could not read %s — ignoring adapter tags", path, exc_info=True)
        return {}
    if not isinstance(data, dict):
        log.warning("%s is not a JSON object — ignoring adapter tags", path)
        return {}
    return {str(k): str(v).strip() for k, v in data.items() if str(v).strip()}


def save_tag(data_dir, session_id: str, label: str) -> dict[str, str]:
    """Set (or, with a blank label, clear) the adapter tag for one session and
    persist. Returns the updated tag map."""
    tags = load_tags(data_dir)
    label = (label or "").strip()
    if label:
        tags[str(session_id)] = label
    else:
        tags.pop(str(session_id), None)
    _tags_path(data_dir).write_text(json.dumps(tags, indent=2, sort_keys=True), encoding="utf-8")
    return tags


def apply_tags(df: pd.DataFrame, tags: dict[str, str]) -> pd.DataFrame:
    """Return a copy of ``df`` with an ``adapter`` column populated from
    ``tags`` (by session_id). Untagged rows get "" — existing data is never
    mutated in place, and no row is dropped."""
    if df.empty:
        return df
    out = df.copy()
    if "session_id" not in out.columns:
        out[ADAPTER_COLUMN] = UNTAGGED
        return out
    out[ADAPTER_COLUMN] = out["session_id"].astype(str).map(tags).fillna(UNTAGGED)
    return out


def available_tags(df: pd.DataFrame) -> list[str]:
    """Distinct non-empty adapter labels present in ``df``, sorted."""
    if df.empty or ADAPTER_COLUMN not in df.columns:
        return []
    vals = {str(v).strip() for v in df[ADAPTER_COLUMN].dropna() if str(v).strip()}
    return sorted(vals)
