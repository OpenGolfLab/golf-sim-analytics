"""Golf-ball flight physics for the "Theoretical Maximum Drive" sidebar stat.

This is a deliberately simplified drag+lift (Magnus) trajectory model, not a
scientific-grade aerodynamics simulator — it exists to turn "my fastest
recorded driver clubhead speed" into a single "what's the ceiling" yardage.
By design this is an *idealistic* ceiling, not a "what would TrackMan
actually measure" estimate: real TrackMan Tour Averages data (113mph
clubhead speed -> 167mph ball speed, 10.9deg launch, 2686rpm spin -> 275yd
carry — trackman.com/blog/golf/introducing-updated-tour-averages) describes
a *typical good tour shot*, optimized for consistency/control, not the
literal physical maximum for that swing speed. The coefficients here are
instead calibrated to a more aspirational ceiling (~350yd carry at a 125mph
clubhead speed), so the number this feature reports sits above what a
real-world "great shot" at that speed would show on a launch monitor.

Simplifications, all standard for this class of estimate:

- Ball speed = clubhead speed * a fixed smash factor (1.50), the widely-cited
  ceiling for a legal/modern driver (USGA/R&A COR limits effectively cap
  smash factor around there). We don't use the player's own recorded smash
  factor because the whole point of "theoretical maximum" is the ceiling for
  their fastest swing, not whatever contact quality that particular swing
  happened to have.
- Drag/lift coefficients (Cd, Cl) are derived once from the initial spin
  ratio and held constant for the whole flight, rather than recomputed
  continuously or decayed over time.
- Launch angle / spin rate are searched only within realistic driver ranges
  (see _LAUNCH_ANGLES_DEG / _SPIN_RATES_RPM below) — an unconstrained search
  degenerates toward unrealistically flat launch angles chasing Magnus lift,
  which no real swing produces.
- 2D vertical-plane flight only (no sidespin/curve) — irrelevant to a
  straight-ahead max-distance figure.
- Carry distance only (no roll) — roll depends on turf/course conditions
  this app has no way to know, whereas carry is a clean physics quantity.
"""
from __future__ import annotations

import math
from functools import lru_cache

# Ball constants (USGA-spec golf ball).
_BALL_MASS_KG = 0.0459
_BALL_RADIUS_M = 0.02135
_BALL_AREA_M2 = math.pi * _BALL_RADIUS_M ** 2

_GRAVITY = 9.81
_AIR_DENSITY_SEA_LEVEL = 1.225  # kg/m^3, ISA 15C

_MPH_TO_MS = 0.44704
_M_TO_YD = 1.09361
_FT_TO_M = 0.3048

# "Optimal" launch/spin isn't a single known value — it shifts with ball
# speed — so it's found by grid search rather than assumed up front. Bounded
# to realistic driver launch conditions (see module docstring) so the search
# can't wander off into launch angles no real swing would ever produce.
_LAUNCH_ANGLES_DEG = range(6, 25)          # 6-24 degrees, 1 degree steps
_SPIN_RATES_RPM = range(1000, 3401, 100)   # 1000-3400 rpm, 100 rpm steps
_TIME_STEP_S = 0.005


def air_density_at_elevation(elevation_ft: float) -> float:
    """Air density (kg/m^3) at the given elevation, via the standard
    troposphere barometric formula. Thinner air -> less drag -> longer carry,
    which is why this app's fixed 1000ft assumption matters at all."""
    h_m = elevation_ft * _FT_TO_M
    return _AIR_DENSITY_SEA_LEVEL * (1 - 2.25577e-5 * h_m) ** 5.25588


# ISA sea-level reference temperature (15C) — the temperature baked into
# _AIR_DENSITY_SEA_LEVEL and air_density_at_elevation.
_ISA_SEA_LEVEL_K = 288.15


def _fahrenheit_to_kelvin(temp_f: float) -> float:
    return (temp_f - 32.0) * 5.0 / 9.0 + 273.15


def air_density_at(temp_f: float, elevation_ft: float = 0.0) -> float:
    """Air density (kg/m^3) at a given surface temperature and elevation.

    Starts from the standard-atmosphere density at ``elevation_ft`` and applies
    the ideal-gas temperature correction (density ~ 1/T at fixed pressure), so
    a warmer-than-standard day comes out thinner (less drag, more carry). This
    is the density term the environmental normalizer divides through; it is a
    deliberately simplified surface model (no humidity, no per-elevation lapse
    beyond the barometric formula), consistent with the rest of this module.
    """
    return air_density_at_elevation(elevation_ft) * (_ISA_SEA_LEVEL_K / _fahrenheit_to_kelvin(temp_f))


def _carry_meters(ball_speed_ms: float, launch_deg: float, spin_rpm: float, air_density: float) -> float:
    """Numerically integrate one trajectory (forward Euler) and return carry
    distance in meters, i.e. horizontal distance until the ball returns to
    launch height."""
    theta = math.radians(launch_deg)
    vx = ball_speed_ms * math.cos(theta)
    vy = ball_speed_ms * math.sin(theta)

    omega = spin_rpm * 2 * math.pi / 60
    spin_ratio = _BALL_RADIUS_M * omega / ball_speed_ms
    # Coefficients calibrated (within _LAUNCH_ANGLES_DEG / _SPIN_RATES_RPM's
    # bounds) so this exact integrator's own optimum lands around 350yd
    # carry for a 125mph clubhead speed — see module docstring.
    drag_coef = min(0.5, 0.18 + 0.5 * spin_ratio)
    lift_coef = min(0.5, 0.05 + 3.0 * spin_ratio)

    k = 0.5 * air_density * _BALL_AREA_M2 / _BALL_MASS_KG

    x, y = 0.0, 0.0
    dt = _TIME_STEP_S
    for _ in range(int(20 / dt)):  # 20s hard cap — safety net, never reached in practice
        speed = math.hypot(vx, vy)
        ax = -k * drag_coef * speed * vx - k * lift_coef * speed * vy
        ay = -_GRAVITY - k * drag_coef * speed * vy + k * lift_coef * speed * vx

        x_new = x + vx * dt
        y_new = y + vy * dt

        if y_new < 0 <= y:
            frac = y / (y - y_new)
            return x + frac * (x_new - x)

        x, y = x_new, y_new
        vx, vy = vx + ax * dt, vy + ay * dt

    return x


# Cached: the grid search below integrates ~475 trajectories (~1s of pure
# Python) and runs on the Tk main thread every time the landing page renders,
# with an input (the all-time max driver speed) that almost never changes.
@lru_cache(maxsize=32)
def theoretical_max_drive_yards(
    clubhead_speed_mph: float,
    elevation_ft: float = 1000.0,
    smash_factor: float = 1.50,
) -> float:
    """Best-case carry distance (yards) for a given clubhead speed: the
    ball speed it implies at the smash-factor ceiling, flown at whichever
    launch angle / spin rate (within realistic driver ranges) carries
    furthest at the given elevation."""
    ball_speed_ms = clubhead_speed_mph * smash_factor * _MPH_TO_MS
    air_density = air_density_at_elevation(elevation_ft)

    best_meters = 0.0
    for launch_deg in _LAUNCH_ANGLES_DEG:
        for spin_rpm in _SPIN_RATES_RPM:
            best_meters = max(best_meters, _carry_meters(ball_speed_ms, launch_deg, spin_rpm, air_density))

    return best_meters * _M_TO_YD
