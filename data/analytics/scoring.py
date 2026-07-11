"""Shot Quality Score engine.

Scores each shot 0-100 against a blend of two components, each in [0, 1]:

  * self-consistency — how the shot compares to that club's *own* distribution
    in the frame: a longer-than-usual carry and a tighter-than-usual offline
    both read as quality. Rewards repeatable, well-struck shots for that club.
  * target — whether launch and spin land inside that club's optimal window
    (``data.analytics.targets.get_targets``, itself speed-scaled off the tour
    baseline). Full marks inside the band, linear falloff outside.

The blend weight is a tunable module constant, not a magic number buried in the
loop. The score degrades gracefully: a club with too few shots to characterize
its own spread falls back to the target component alone; a shot missing every
scoreable metric returns ``NA`` rather than a misleading 0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.analytics.targets import get_targets
from data.columns import (
    CARRY_ALIASES,
    CLUB_SPEED_ALIASES,
    LAUNCH_ANGLE_ALIASES,
    OFFLINE_ALIASES,
    SPIN_RATE_ALIASES,
    find_col,
)

# Blend weights for the two score components; exposed here so the mix is one
# edit, not a hunt through the scoring body. Normalized internally, so they
# need not sum to 1.
SELF_WEIGHT = 0.5    # weight on "consistent with your own recent shots"
TARGET_WEIGHT = 0.5  # weight on "inside the tour-reference launch/spin window"

# A club needs at least this many shots in the frame before its own mean/spread
# is trustworthy enough to drive the self-consistency component. Below it, the
# shot is scored on the target component alone.
MIN_SHOTS = 5


def _clip01(x):
    return float(np.clip(x, 0.0, 1.0))


def _window_score(value: float, window: tuple[float, float]) -> float | None:
    """1.0 inside the band, falling linearly to 0 one half-width beyond either
    edge. None when the value is missing."""
    if value is None or pd.isna(value):
        return None
    lo, hi = window
    if lo <= value <= hi:
        return 1.0
    half = (hi - lo) / 2 or 1.0
    dist = (lo - value) if value < lo else (value - hi)
    return _clip01(1.0 - dist / half)


def _mean_of_present(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


class ShotScorer:
    """Assigns a 0-100 quality score per shot."""

    def __init__(self, self_weight: float = SELF_WEIGHT, target_weight: float = TARGET_WEIGHT,
                 min_shots: int = MIN_SHOTS):
        self.self_weight = self_weight
        self.target_weight = target_weight
        self.min_shots = min_shots

    def score(self, df: pd.DataFrame) -> pd.Series:
        """Return a per-row quality score (0-100), indexed like ``df``. Rows
        that can't be scored at all come back as ``NA``."""
        out = pd.Series(pd.NA, index=df.index, dtype="Float64")
        if df.empty or "club" not in df.columns:
            return out

        carry_col = find_col(df, CARRY_ALIASES)
        off_col = find_col(df, OFFLINE_ALIASES)
        vla_col = find_col(df, LAUNCH_ANGLE_ALIASES)
        spin_col = find_col(df, SPIN_RATE_ALIASES)
        cs_col = find_col(df, CLUB_SPEED_ALIASES)

        # Per-club loop over plain numpy arrays rather than per-row .loc
        # scalar access — this runs over the entire history on every landing
        # page render, and scalar .loc made it the slowest step of that render.
        for _club, sub in df.groupby("club"):
            # Per-club self-consistency stats (only when the sample is big
            # enough for its own mean/spread to mean something).
            carry = pd.to_numeric(sub[carry_col], errors="coerce") if carry_col else None
            off = pd.to_numeric(sub[off_col], errors="coerce") if off_col else None
            enough = len(sub) >= self.min_shots
            carry_mean = carry_std = off_std = None
            if enough and carry is not None:
                carry_mean, carry_std = carry.mean(), carry.std()
            if enough and off is not None:
                off_std = off.std()

            carry_vals = carry.to_numpy(dtype=float) if carry is not None else None
            off_vals = off.to_numpy(dtype=float) if off is not None else None
            vla_vals = (pd.to_numeric(sub[vla_col], errors="coerce").to_numpy(dtype=float)
                        if vla_col else None)
            spin_vals = (pd.to_numeric(sub[spin_col], errors="coerce").to_numpy(dtype=float)
                         if spin_col else None)
            cs_vals = (pd.to_numeric(sub[cs_col], errors="coerce").to_numpy(dtype=float)
                       if cs_col else None)
            # get_targets varies only with (club, speed); within one club the
            # speeds repeat (and are all 100.0 when club speed is absent), so
            # memoize instead of recomputing the windows per shot.
            targets_at: dict[float, object] = {}

            scores: list = []
            for pos in range(len(sub)):
                self_parts: list[float | None] = []
                if carry_mean is not None and carry_std and not pd.isna(carry_vals[pos]):
                    # +/-2 sigma spans the 0..1 range; at/above the club mean is good.
                    z = (carry_vals[pos] - carry_mean) / carry_std
                    self_parts.append(_clip01(0.5 + z / 4.0))
                if off_std and off_vals is not None and not pd.isna(off_vals[pos]):
                    self_parts.append(_clip01(1.0 - abs(off_vals[pos]) / (2 * off_std)))
                self_score = _mean_of_present(self_parts)

                target_parts: list[float | None] = []
                if vla_vals is not None or spin_vals is not None:
                    speed = 100.0
                    if cs_vals is not None and not pd.isna(cs_vals[pos]):
                        speed = float(cs_vals[pos])
                    t = targets_at.get(speed)
                    if t is None:
                        t = targets_at[speed] = get_targets(_club, speed)
                    if vla_vals is not None:
                        target_parts.append(_window_score(vla_vals[pos], t.launch_window))
                    if spin_vals is not None:
                        target_parts.append(_window_score(spin_vals[pos], t.spin_window))
                target_score = _mean_of_present(target_parts)

                combined = self._blend(self_score, target_score)
                scores.append(round(100.0 * combined, 1) if combined is not None else pd.NA)
            out.loc[sub.index] = scores
        return out

    def _blend(self, self_score: float | None, target_score: float | None) -> float | None:
        """Weighted blend of the two components, reweighting onto whichever is
        present. None when neither could be computed."""
        parts, weights = [], []
        if self_score is not None:
            parts.append(self_score)
            weights.append(self.self_weight)
        if target_score is not None:
            parts.append(target_score)
            weights.append(self.target_weight)
        total = sum(weights)
        if not parts or total == 0:
            return None
        return sum(p * w for p, w in zip(parts, weights)) / total
