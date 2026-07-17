"""
Display-unit conversion for distances (yards ↔ meters).

This app stores every distance in YARDS (and every speed in mph) as its single
canonical unit. That unit is not assumed — it's established at the source:

- CSV exports: GSPro honors its in-game metric/imperial setting when exporting,
  and writes the unit into DistanceToPin's suffix ("345.21 yds" / "315.5 m").
  data.io._detect_csv_distance_unit reads that suffix at ingest and normalizes a
  metric export back to yards, so what lands in Parquet is always yards.
- Live tracking (currentRound.dat + GSPro.db): carry NO unit marker anywhere.
  GSPro applies its metric/imperial localization only when it *formats the CSV
  export* — that's why the export's DistanceToPin has a " yds"/" m" suffix while
  GSPro.db's DistanceToPin is a bare float and currentRound.dat has no unit field
  at all. The internal files are GSPro's fixed store (yards by magnitude), so
  live-archived data is already yards and needs no detection/conversion.
  (Only unverified against a metric-configured GSPro — no metric capture on
  hand — but nothing in either internal file varies with the display setting.)

The Meters option here is therefore a *display-only* conversion applied at
render time — nothing in the Parquet files, the analytics, or the OpenGolfLab
contribution ever changes (the community dataset stays in one unit). Only linear
distances (carry, total, offline, distance-to-pin) and apex height convert;
speeds (mph) and spin (rpm) are left alone. Because ingestion normalizes to
yards, display conversion never double-converts.
"""
from __future__ import annotations

YARDS = "Yards"
METERS = "Meters"
UNIT_OPTIONS = [YARDS, METERS]

YARD_TO_M = 0.9144   # exact
FOOT_TO_M = 0.3048   # exact — apex height is stored in feet


def is_metric(unit) -> bool:
    """True for the meters display unit (tolerant of case / stray text)."""
    return str(unit).strip().lower().startswith("m")


def to_display(value_yards, unit):
    """Convert a yard value (scalar, numpy array, or pandas Series) to the
    chosen display unit. Yards passes straight through."""
    return value_yards * YARD_TO_M if is_metric(unit) else value_yards


def feet_to_display(value_feet, unit):
    """Convert a height stored in feet to the display unit (meters when
    metric, else unchanged feet)."""
    return value_feet * FOOT_TO_M if is_metric(unit) else value_feet


# Per-shot columns to convert, by kind. Distances are stored in yards; apex /
# peak height in feet. Kept lowercase — callers match case-insensitively.
_DISTANCE_COLS = {"carry", "carrydistance", "total", "totaldistance",
                  "offline", "distancetopin"}
_HEIGHT_COLS = {"peakheight", "height", "apex", "max_height", "maxheight"}


def to_display_frame(df, unit):
    """Return a copy of ``df`` with every recognized distance column converted
    to the display unit (a no-op that returns ``df`` unchanged for yards, or an
    empty frame). Lets a chart convert once at the top of render() and then plot
    the frame as-is — the axis labels are the only other thing to switch.

    Distances (carry/total/offline/distance-to-pin) convert yd→m; apex/peak
    height converts ft→m. Everything else (speeds, spin, angles) is untouched.
    """
    if not is_metric(unit) or df is None or df.empty:
        return df
    from pandas.api.types import is_numeric_dtype
    df = df.copy()
    for col in df.columns:
        low = str(col).lower()
        # Skip non-numeric columns: some sources store e.g. distancetopin as
        # "135.5 yds" strings, which no chart plots directly — converting them
        # would raise. Numeric distance/height columns are what charts plot.
        if not is_numeric_dtype(df[col]):
            continue
        if low in _DISTANCE_COLS:
            df[col] = df[col] * YARD_TO_M
        elif low in _HEIGHT_COLS:
            df[col] = df[col] * FOOT_TO_M
    return df


def dist_suffix(unit) -> str:
    """Axis/label distance unit, title-case ("Yds"/"m")."""
    return "m" if is_metric(unit) else "Yds"


def dist_suffix_lower(unit) -> str:
    return "m" if is_metric(unit) else "yds"


def height_suffix(unit) -> str:
    return "m" if is_metric(unit) else "ft"
