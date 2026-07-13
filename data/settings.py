"""
Persistent app-level preferences (settings.json in BASE_DIR).

Until now every Settings toggle (temperature normalization, ignore warm-up,
demo mode) lived only in in-memory Tk variables and reset to its default on
every launch. That's fine for throwaway view toggles, but some preferences
really should stick between sessions — the display scale a user dials in for
their projector, whether on-course rounds are kept out of the practice
dashboards. This module is the single place that reads/writes those.

Design mirrors data/edits.py's sidecar pattern: a small JSON file, load()
tolerates a missing/corrupt file by returning defaults, save() rewrites the
whole file. It lives in BASE_DIR (not DATA_DIR) on purpose — these are
app/display preferences, independent of which data folder is active (real
vs. the demo sample set, which the "Use sample data" toggle swaps).
"""
from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path

import config

log = logging.getLogger(__name__)

_SETTINGS_FILE = "settings.json"

# One flat dict of defaults. Keep keys stable — they're the on-disk schema.
DEFAULTS: dict = {
    # Display scale. "Auto" derives a factor from the display's OS DPI setting
    # and physical size so the app is sized appropriately on anything from a
    # 10" laptop to a wall TV — see auto_scale_for() below. Any explicit
    # percentage string ("100%", "125%", ...) overrides Auto.
    "ui_scale": "Auto",
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
#
# The app's look is tuned on the developer's panel: a 16" 2560x1600 laptop
# running Windows at 150% scaling (OS DPI factor 1.5, physical diagonal 16").
# "Auto" reproduces that exact factor there — so that machine is unchanged —
# then adapts to other displays along two independent axes:
#
#   * OS scaling (Windows' own DPI %). The user/OS already picked it to suit
#     the panel's pixel density, so we take it as the readability baseline: it
#     keeps a dense 4K laptop legible and a low-DPI monitor from ballooning.
#     Reliable wherever Windows runs.
#   * Physical screen size. Layered on top as a gentle preference — shrink a
#     little toward a floor on tiny 10-11" laptop panels so the whole app still
#     fits, grow on big screens, but SATURATE past ~40" so a wall-sized TV maxes
#     out instead of scaling text to absurd sizes.
#
# auto_scale_for() stays pure (it takes the measured numbers, so it's unit
# testable); detect_display_metrics() does the platform probing.
# ---------------------------------------------------------------------------
_REF_HEIGHT = 1080          # fallback baseline when OS scaling can't be read
_REF_DIAGONAL_IN = 16.0     # developer panel; the size multiplier is 1.0 here
_FLOOR_DIAGONAL_IN = 10.5   # a 10" laptop — the smallest well-supported panel
_FLOOR_MULT = 0.80          # size multiplier at/below the floor diagonal
_MIN_SCALE, _MAX_SCALE = 0.8, 2.25


def _size_multiplier(diagonal_in) -> float:
    """Physical-size preference, normalized to 1.0 at the 16" reference panel.

    Flat at _FLOOR_MULT for tiny screens, linear up to 1.0 at the reference,
    then a gentle +0.0125/inch that saturates at +0.30 so very large displays
    stop growing. Returns a neutral 1.0 when the diagonal is unknown or clearly
    bogus (some monitors report no/garbage EDID physical size)."""
    try:
        d = float(diagonal_in)
    except (TypeError, ValueError):
        return 1.0
    if not 7.0 <= d <= 120.0:
        return 1.0
    if d <= _FLOOR_DIAGONAL_IN:
        return _FLOOR_MULT
    if d <= _REF_DIAGONAL_IN:
        span = _REF_DIAGONAL_IN - _FLOOR_DIAGONAL_IN
        return _FLOOR_MULT + (d - _FLOOR_DIAGONAL_IN) * (1.0 - _FLOOR_MULT) / span
    return min(1.30, 1.0 + (d - _REF_DIAGONAL_IN) * 0.0125)


def auto_scale_for(screen_height, diagonal_in=None, os_scaling=None) -> float:
    """Resolve a concrete UI scale from measured display metrics.

    ``os_scaling`` (Windows' DPI factor, e.g. 1.5 for 150%) is the readability
    baseline when known; otherwise we fall back to the old screen-height ratio
    against a 1080p reference. ``diagonal_in`` (physical inches) then applies
    the gentle size preference. Clamped to a sane range and rounded to 0.05 so
    the result is stable across launches.
    """
    try:
        base = float(os_scaling) if os_scaling else float(screen_height) / _REF_HEIGHT
    except (TypeError, ValueError, ZeroDivisionError):
        base = 1.0
    if base <= 0:
        base = 1.0
    scale = base * _size_multiplier(diagonal_in)
    scale = max(_MIN_SCALE, min(_MAX_SCALE, scale))
    return round(scale / 0.05) * 0.05


def resolve_scale(ui_scale, screen_height, diagonal_in=None, os_scaling=None) -> float:
    """Turn a stored ui_scale ("Auto" or a "125%"-style string / number) plus
    the measured display metrics into a concrete float scale factor."""
    if ui_scale in (None, "", "Auto", "auto"):
        return auto_scale_for(screen_height, diagonal_in, os_scaling)
    try:
        if isinstance(ui_scale, str):
            return max(0.5, min(3.0, float(ui_scale.strip().rstrip("%")) / 100.0))
        return max(0.5, min(3.0, float(ui_scale)))
    except (TypeError, ValueError):
        return auto_scale_for(screen_height, diagonal_in, os_scaling)


def detect_display_metrics() -> tuple[int, float | None, float | None]:
    """(primary screen height px, physical diagonal inches, OS scaling factor).

    Real values on Windows; neutral fallbacks (1080, None, None) elsewhere or
    if any query fails, so auto_scale_for() still degrades gracefully. Physical
    size comes from the monitor's EDID via GDI's GetDeviceCaps. Call only after
    the process is DPI-aware, so the pixel/DPI numbers are truthful.
    """
    height, diagonal_in, os_scaling = _REF_HEIGHT, None, None
    if sys.platform != "win32":
        return height, diagonal_in, os_scaling
    try:
        import ctypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        height = int(user32.GetSystemMetrics(1)) or height  # SM_CYSCREEN
        hdc = user32.GetDC(0)
        try:
            mm_w = gdi32.GetDeviceCaps(hdc, 4)   # HORZSIZE — physical width, mm
            mm_h = gdi32.GetDeviceCaps(hdc, 6)   # VERTSIZE — physical height, mm
        finally:
            user32.ReleaseDC(0, hdc)
        if mm_w > 0 and mm_h > 0:
            diagonal_in = math.hypot(mm_w, mm_h) / 25.4
        try:
            os_scaling = user32.GetDpiForSystem() / 96.0  # Win10 1607+
        except Exception:
            os_scaling = None
    except Exception:
        log.debug("Could not read display metrics", exc_info=True)
    return height, diagonal_in, os_scaling
