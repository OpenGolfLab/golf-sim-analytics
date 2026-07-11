"""
Persistent app-level preferences (settings.json in BASE_DIR).

Until now every Settings toggle (temperature normalization, ignore warm-up,
demo mode) lived only in in-memory Tk variables and reset to its default on
every launch. That's fine for throwaway view toggles, but some preferences
really should stick between sessions — the display scale a user dials in for
their projector, whether mulligans are dropped on-course, whether on-course
rounds are kept out of the practice dashboards. This module is the single
place that reads/writes those.

Design mirrors data/edits.py's sidecar pattern: a small JSON file, load()
tolerates a missing/corrupt file by returning defaults, save() rewrites the
whole file. It lives in BASE_DIR (not DATA_DIR) on purpose — these are
app/display preferences, independent of which data folder is active (real
vs. the demo sample set, which the "Use sample data" toggle swaps).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import config

log = logging.getLogger(__name__)

_SETTINGS_FILE = "settings.json"

# One flat dict of defaults. Keep keys stable — they're the on-disk schema.
DEFAULTS: dict = {
    # Display scale. "Auto" derives a factor from the screen resolution so the
    # app fills a similar fraction of the screen (and text stays a similar
    # relative size) regardless of panel resolution — see ui scaling in app.py.
    # Any explicit percentage string ("100%", "125%", ...) overrides Auto.
    "ui_scale": "Auto",
    # Drop mulligan (re-hit) shots from on-course rounds — see
    # live/shot_data.py's mulligan detection.
    "drop_mulligans": False,
    # Keep on-course rounds (which include chips, punches, recovery shots)
    # out of the practice-analytics dashboards so they don't taint the
    # "pure your swing" historical data. On by default: the whole point of
    # separate on-course tracking is that it shouldn't pollute practice.
    "exclude_on_course_from_practice": True,
}

# Display-scale dropdown choices, in menu order.
UI_SCALE_OPTIONS = ["Auto", "80%", "90%", "100%", "110%", "125%", "150%", "175%", "200%"]


def _path() -> Path:
    return config.BASE_DIR / _SETTINGS_FILE


def load() -> dict:
    """Return the saved settings merged over DEFAULTS (so a new key added to
    DEFAULTS in a later version is picked up even for old files)."""
    data = {}
    path = _path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Could not read %s — using default settings", path, exc_info=True)
            data = {}
    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def save(settings: dict) -> None:
    """Persist the given settings (only known keys are written)."""
    out = {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}
    try:
        _path().write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        log.exception("Failed to save settings to %s", _path())


def get(key: str):
    return load().get(key, DEFAULTS.get(key))


def set(key: str, value) -> dict:
    """Update one setting and persist. Returns the full settings dict."""
    settings = load()
    settings[key] = value
    save(settings)
    return settings


# ---------------------------------------------------------------------------
# Display-scale resolution.
# ---------------------------------------------------------------------------
_REF_HEIGHT = 1080  # design baseline: a 1920x1080 panel renders at scale 1.0


def auto_scale_for(screen_height: int) -> float:
    """Resolution-derived UI scale so the app looks about the same size on a
    1080p laptop, a 1440p monitor, and a 2048x1536 projector.

    Anchored to a 1080p baseline (scale 1.0) and snapped to quarter steps so
    the value is predictable; clamped to a sane range so a tiny netbook or a
    huge 8K wall can't produce an unusable UI.
    """
    try:
        raw = float(screen_height) / _REF_HEIGHT
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0
    snapped = round(raw / 0.25) * 0.25
    return max(0.8, min(2.0, snapped))


def resolve_scale(ui_scale, screen_height: int) -> float:
    """Turn a stored ui_scale ("Auto" or a "125%"-style string / number) plus
    the current screen height into a concrete float scale factor."""
    if ui_scale in (None, "", "Auto", "auto"):
        return auto_scale_for(screen_height)
    try:
        if isinstance(ui_scale, str):
            return max(0.5, min(3.0, float(ui_scale.strip().rstrip("%")) / 100.0))
        return max(0.5, min(3.0, float(ui_scale)))
    except (TypeError, ValueError):
        return auto_scale_for(screen_height)
