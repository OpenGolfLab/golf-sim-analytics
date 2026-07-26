"""Column-name lookup helpers.

GSPro CSV exports use inconsistent column naming across versions
(e.g. "ClubSpeed" vs "Club Speed" vs "club_speed"). find_col() is the one
place that knows the list of accepted aliases for each metric, instead of
that list being retyped at every call site.
"""
from __future__ import annotations

import pandas as pd


def find_col(df: pd.DataFrame, possible_names: list[str]) -> str | None:
    for name in possible_names:
        if name in df.columns:
            return name
    return None


# Canonical alias groups, reused across ingestion, filtering, and charts.
CARRY_ALIASES = ["carry", "carrydistance"]
TOTAL_ALIASES = ["total", "totaldistance"]
CLUB_SPEED_ALIASES = ["clubspeed", "club_speed"]
BALL_SPEED_ALIASES = ["ballspeed", "ball_speed"]
SMASH_FACTOR_ALIASES = ["smashfactor", "smash_factor"]
OFFLINE_ALIASES = ["offline"]
# Angle of attack. Present in GSPro exports with real values (driver ~-0.6°,
# wedges ~-3 to -5°) and already numericized by ingestion — this group just
# gives downstream code (analytics engines) a canonical way to find it.
AOA_ALIASES = ["aoa", "angleofattack", "attackangle", "attack_angle"]
HEIGHT_ALIASES = ["peakheight", "height", "apex", "max_height", "maxheight"]
LAUNCH_ANGLE_ALIASES = ["vla", "launchangle", "launch_angle", "verticallaunch"]
DESCENT_ANGLE_ALIASES = ["decent", "descent", "land_angle", "landing_angle", "descentangle"]
SPIN_RATE_ALIASES = [
    "spinrate", "spin_rate", "totalspin", "total_spin", "backspin", "back_spin", "spin",
]
# Start direction (horizontal launch angle) and curve (spin-axis tilt), used
# by the Shot Shape chart. Club path / face angle aren't exported by this
# app's launch monitor (always zero), so start-line + curve stand in for
# them: start direction is ~85% face-driven, and spin-axis tilt is the curve
# produced by the face-to-path relationship.
START_DIR_ALIASES = ["hla", "launchdirection", "launch_direction", "horizontal_launch", "azimuth"]
SPIN_AXIS_ALIASES = ["rawspinaxis", "spinaxis", "spin_axis"]
# Where the ball finished relative to the hole, in yards. On-course only:
# GSPro writes this AFTER the shot resolves, so it is the shot's proximity,
# not the distance it was played from (live/shot_data.py's note on the field).
DISTANCE_TO_PIN_ALIASES = ["distancetopin", "distance_to_pin", "proximity"]
# Practice-range only: how far away the target the player selected in GSPro
# is, in yards. Same raw field as distancetopin, opposite meaning — on the
# range the ball is replaced on the tee after every shot, so GSPro keeps
# reporting the unchanged tee-to-target distance. See
# data.analytics.scoring's "Targets on the range" note.
TARGET_DISTANCE_ALIASES = ["target_distance", "targetdistance"]
