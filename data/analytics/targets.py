"""Per-club optimal windows (launch angle, spin, angle of attack).

This module deliberately does NOT hold its own launch/spin reference table.
Those numbers already live in ``config`` — ``REFERENCE_PROFILES["PGA Tour"]``
plus ``optimal_launch_spin(club, speed)``, which scales the tour baseline by
the player's clubhead speed (flatten launch / cut spin above the baseline,
add below). We wrap that point target and widen it into a *tolerance band*,
because the Shot Quality Score (Phase 1) needs "how close to optimal" rather
than a single number.

Angle of attack is the one metric the tour reference tables don't publish, so
``_AOA_WINDOWS`` below is a small, explicitly heuristic (coach-consensus) table
rather than a cited dataset: driver ideally slightly up, irons and wedges
descending, steeper for the short clubs.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import normalize_club_name, optimal_launch_spin

# Half-width of each tolerance band, as a fraction of the point target. A shot
# exactly on target scores best; the score falls off to zero at roughly one
# band-width away (the scorer defines the exact falloff — this is just the
# "how wide is good" knob). Kept here so all three metrics share one place.
_LAUNCH_TOL_FRAC = 0.20   # ±20% of optimal launch angle
_SPIN_TOL_FRAC = 0.18     # ±18% of optimal spin
# Smash is a much tighter number than launch or spin — the whole usable range
# for a driver is about 1.35–1.50 — so its band is proportionally narrower.
_SMASH_TOL_FRAC = 0.045   # ±4.5% of optimal smash factor

# Heuristic per-club angle-of-attack windows (degrees), (low, high). NOT from a
# tour dataset — attack angle isn't in REFERENCE_PROFILES. Driver rewards a
# positive (upward) strike; everything else is a descending blow that steepens
# toward the wedges. Clubs with no explicit entry fall back by bag rank in
# get_targets(), so this only needs the anchors.
_AOA_WINDOWS: dict[str, tuple[float, float]] = {
    "Dr": (1.0, 5.0),
    "3W": (-3.0, 1.0),
    "5W": (-3.5, 0.0),
    "3I": (-4.0, -1.0),
    "5I": (-4.0, -1.5),
    "7I": (-4.5, -2.0),
    "9I": (-5.0, -2.5),
    "Pw": (-6.0, -3.0),
    "Sw": (-7.0, -3.5),
}

# Physical clamp so a widened band can never imply a nonsensical target.
_LAUNCH_BOUNDS = (5.0, 35.0)
_SPIN_BOUNDS = (1500.0, 12000.0)
# 1.5 is the COR limit a conforming driver face can't exceed; anything above it
# is a measurement artifact, not a better strike. The floor is a whiff-ish
# bottom so the band stays meaningful for the wedges (tour PW is ~1.23).
_SMASH_BOUNDS = (0.80, 1.50)


@dataclass(frozen=True)
class ClubTargets:
    """Optimal windows for one club at one clubhead speed. Each ``*_window``
    is an inclusive ``(low, high)`` band; ``*_optimal`` is the center."""
    club: str
    launch_optimal: float
    launch_window: tuple[float, float]
    spin_optimal: float
    spin_window: tuple[float, float]
    aoa_window: tuple[float, float]
    # Smash factor (ball speed / club speed). Unlike launch and spin this does
    # NOT scale with the player's clubhead speed — smash is an efficiency
    # ratio, and a 95mph driver swing and a 113mph one are both trying to hit
    # the same ~1.48. So it comes straight off the club's tour baseline.
    #
    # The band is deliberately two-sided even though "more smash" sounds
    # strictly better: above the club's number means the ball came off the
    # face hotter than that loft can produce, which in practice is a thin
    # strike low on the face (or a mislabeled club), not a good one.
    smash_optimal: float
    smash_window: tuple[float, float]


def _band(center: float, frac: float, bounds: tuple[float, float]) -> tuple[float, float]:
    half = abs(center) * frac
    lo = max(bounds[0], center - half)
    hi = min(bounds[1], center + half)
    return (lo, hi)


def _aoa_window(club: str) -> tuple[float, float]:
    """AoA band for a club, falling back to the nearest explicit anchor by bag
    position (reusing config's club ranking) when the club has no entry."""
    from config import get_club_rank  # local import: config is heavy at module load

    canon = normalize_club_name(club)
    if canon in _AOA_WINDOWS:
        return _AOA_WINDOWS[canon]
    rank = get_club_rank(canon)
    nearest = min(_AOA_WINDOWS, key=lambda k: abs(get_club_rank(k) - rank))
    return _AOA_WINDOWS[nearest]


def _smash_optimal(club: str) -> float:
    """The club's tour smash factor, straight from the published ball-speed /
    club-speed pair in ``REFERENCE_PROFILES["PGA Tour"]`` (TrackMan Tour
    Averages) — driver ~1.48, 7-iron ~1.33, PW ~1.23. Clubs with no tour row
    borrow their nearest bag neighbour, same as every other target here."""
    from config import _tour_baseline  # local import: config is heavy at load

    base = _tour_baseline(club)
    if not base.club_speed or not base.ball_speed:
        return 1.35  # unreachable with today's table; a mid-iron-ish default
    return base.ball_speed / base.club_speed


def get_targets(club, speed: float = 100.0) -> ClubTargets:
    """Optimal launch/spin/AoA/smash windows for ``club`` at the player's
    clubhead ``speed``. Launch and spin centers come from
    ``config.optimal_launch_spin`` (speed-scaled off the tour baseline); the
    bands, AoA and smash are added here.
    """
    canon = normalize_club_name(club)
    launch, spin = optimal_launch_spin(canon, speed)
    smash = _smash_optimal(canon)
    return ClubTargets(
        club=canon,
        launch_optimal=launch,
        launch_window=_band(launch, _LAUNCH_TOL_FRAC, _LAUNCH_BOUNDS),
        spin_optimal=spin,
        spin_window=_band(spin, _SPIN_TOL_FRAC, _SPIN_BOUNDS),
        aoa_window=_aoa_window(canon),
        smash_optimal=smash,
        smash_window=_band(smash, _SMASH_TOL_FRAC, _SMASH_BOUNDS),
    )
