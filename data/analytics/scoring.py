"""Shot Quality Score engine.

Scores each shot 0-100. What "quality" means depends on what the golfer was
actually trying to do, which the data already tells us, so the score is built
from three independent components and the *context* decides which ones count:

  * **strike** — how well the ball came off the face, judged only on contact
    and launch: smash factor, launch angle, spin, angle of attack, each
    against that club's own optimal window (``data.analytics.targets``, itself
    speed-scaled off the tour baseline). Nothing about where the ball went.
  * **shape** — the shot's own dispersion signature, judged against the
    player's own history with that club: carry against their stock number and
    offline against their usual spread. Club-aware — see ``_shape``.
  * **proximity** — how close the ball finished to the target it was aimed at.

Three contexts, three blends:

    on course, going at the flag   strike + proximity  (the result is what counts)
    range, target picked           strike + proximity
    anything else                  strike + shape

The rationale for the split: when a shot is being played *at* something, there
is a real answer to "did that do its job" and proximity is it. When it isn't,
there's no such answer — hitting a 7-iron 150 yards is neither good nor bad in
isolation — so the score falls back to contact plus how repeatable the shot
was for that club, which is the only thing the data can honestly say.

"Going at the flag" is a real distinction and not a hedge. A tee shot on a
442-yard par 4 finishes ~280 yards from the hole no matter how well it is
struck, and scoring it on proximity means a tour-spec drive rates 40/100
forever. So proximity only applies to a shot that actually covered most of the
distance to the hole (``ON_COURSE_REACH``); tee shots and lay-ups are scored
on strike and shape instead, which for a driver is precisely the right pair —
distance and straightness. A chunked approach escapes proximity scoring under
this rule too, but not the score: a chunk is a bad strike and lands nowhere
near that club's stock number, so both remaining components catch it.

Targets on the range
--------------------
GSPro reports one number for both jobs and this trips people up, so it is
worth stating once. ``distancetopin`` is written *after* a shot resolves:

  * on course it is therefore the shot's **proximity** (a drive that leaves
    200 yards in reports 200);
  * on the range the ball is replaced on the tee after every shot, so the
    play position never moves and GSPro keeps reporting the unchanged
    **tee-to-target distance** instead. That is the range target, and
    ingestion copies it to ``target_distance`` to keep the two meanings from
    ever being confused downstream (live/shot_data.py, and the self-heal in
    data.store for rounds archived before the column existed).

A target only counts as *in play* when it is plausibly the thing being aimed
at — see ``_target_in_play``. GSPro's range has a default pin at ~392 yards
that no club reaches, and scoring a wedge on its proximity to that would be
nonsense, so a target well outside the club's reach is treated as "no target
selected" and the shot scores on strike + shape instead.

Non-swing records (putts, penalty-stroke records) score ``NA``: they are
strokes, not shots, and their ball data is cloned from the preceding record
(see ``data.on_course.exclude_putts``).

A shot missing every scoreable metric returns ``NA`` rather than a misleading
0, and a component that can't be computed drops out of the blend rather than
counting as zero.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from data.analytics.targets import get_targets
from data.columns import (
    AOA_ALIASES,
    CARRY_ALIASES,
    CLUB_SPEED_ALIASES,
    BALL_SPEED_ALIASES,
    DISTANCE_TO_PIN_ALIASES,
    LAUNCH_ANGLE_ALIASES,
    OFFLINE_ALIASES,
    SMASH_FACTOR_ALIASES,
    SPIN_RATE_ALIASES,
    TARGET_DISTANCE_ALIASES,
    TOTAL_ALIASES,
    find_col,
)

# Blend weights per context, exposed here so the mix is one edit rather than a
# hunt through the scoring body. Normalized internally, so they need not sum
# to 1, and a component that couldn't be computed is dropped and the rest
# reweighted onto what's left.
#
# On course leans on proximity rather than splitting evenly: a flushed 7-iron
# that finishes 40 yards from the flag did not do its job, and the scorecard
# agrees. On the range with a target the two are even — you are there to work
# on the strike as much as the result.
WEIGHTS: dict[str, dict[str, float]] = {
    "on_course_target": {"strike": 0.40, "proximity": 0.60},
    "practice_target":  {"strike": 0.50, "proximity": 0.50},
    "no_target":        {"strike": 0.50, "shape": 0.50},
}

# Within the shape component: how the carry/gapping term and the offline
# straightness term trade off, per club type.
#
# Irons and wedges are gapping clubs — the entire job is hitting your number,
# so carry carries the weight. The driver is a distance-and-fairway club, so
# its two terms are even.
SHAPE_MIX_GAPPING = {"distance": 0.65, "offline": 0.35}
SHAPE_MIX_DRIVER = {"distance": 0.50, "offline": 0.50}

# A club needs at least this many shots in the frame before its own mean/spread
# is trustworthy enough to drive the shape component. Below it, the shot is
# scored on the components that don't need a history.
MIN_SHOTS = 5

# Clubs where carrying it further than usual is genuinely better, so the
# distance term stays one-sided.
#
# For everything else it isn't, and this used to score every club as though it
# were: the carry term was `0.5 + z/4`, monotonically increasing, so an 8-iron
# flushed 12 yards past its stock number scored HIGHER than a perfect stock
# 8-iron. On the course long is a miss — frequently a worse one than short,
# since it's the side with the trouble behind the green — and this number is the
# headline stat on the landing page and the live gauge, so it was quietly
# rewarding the exact thing that costs shots. The distance term is now symmetric
# about the club's own mean for every club not listed here.
#
# Driver only, deliberately. A 3-wood is longer-is-better off a tee and
# absolutely not when it's a lay-up, and nothing in the data says which one a
# given swing was.
LONGER_IS_BETTER_CLUBS = frozenset({"Dr"})

# ---------------------------------------------------------------------------
# Proximity scoring.
#
# Raw yards-from-the-hole can't be scored on its own: two yards from 180 out is
# a career approach, two yards from 30 out is a poor pitch. So proximity is
# always judged against the distance the shot was played from — full marks at
# or inside the expected proximity for that distance, falling linearly to zero
# at PROXIMITY_FALLOFF times it.
#
# PROXIMITY_FRAC ≈ tour approach proximity, which runs about 6-7% of the
# distance across the bag (~7 yards from 100, ~13 from 190). Full marks needs a
# tour-grade result, which is the point — it's the same standard the launch and
# spin windows use.
# ---------------------------------------------------------------------------
PROXIMITY_FRAC = 0.07
# Floor on the expected proximity, in yards. Without it, a 6-yard chip would
# demand a 15-inch result for full marks, and short-game noise would dominate
# the whole score.
PROXIMITY_FLOOR_YDS = 3.0
PROXIMITY_FALLOFF = 4.0

# How far off the club's own stock carry a range target can sit and still be
# treated as the thing being aimed at (see the module docstring). The upper
# bound is what rejects GSPro's unreachable default range pin; the lower bound
# rejects a stale short target left selected while the player moved to a longer
# club. Deliberately tight — the cost of guessing wrong is scoring a shot
# against a target the player never had in mind, and the fallback (strike +
# shape) is a perfectly good score, not a penalty.
TARGET_REACH_LO = 0.50
TARGET_REACH_HI = 1.25

# On course, the fraction of the distance to the hole a shot has to cover
# before proximity is the right way to judge it — i.e. before it counts as a
# shot played at the flag rather than one played up the hole. See the module
# docstring on why tee shots must not be scored on proximity.
ON_COURSE_REACH = 0.80

_ON_COURSE = "on_course"


def _nans(n: int) -> np.ndarray:
    return np.full(n, np.nan, dtype=float)


def _num(df: pd.DataFrame, col: str | None) -> np.ndarray | None:
    """A float array for one column, or None when the column is absent."""
    if not col or col not in df.columns:
        return None
    return pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)


def _window_scores(values, lo, hi) -> np.ndarray:
    """1.0 inside the band, falling linearly to 0 one half-width beyond either
    edge. NaN in, NaN out — a missing metric must not read as a perfect one,
    which a bare comparison would do (every comparison against NaN is False,
    so it would look like "inside the band")."""
    values = np.asarray(values, dtype=float)
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    half = (hi - lo) / 2.0
    half = np.where(half > 0, half, 1.0)
    dist = np.where(values < lo, lo - values, np.where(values > hi, values - hi, 0.0))
    out = np.clip(1.0 - dist / half, 0.0, 1.0)
    return np.where(np.isnan(values), np.nan, out)


def _mean_of_present(parts: list[np.ndarray | None], length: int) -> np.ndarray:
    """Row-wise mean over whichever component arrays are present, NaN where a
    row has none of them."""
    stack = [p for p in parts if p is not None]
    if not stack:
        return np.full(length, np.nan)
    with warnings.catch_warnings():
        # An all-NaN row is the documented "nothing scoreable here" case and
        # comes back as NaN, which is exactly what's wanted — numpy just warns.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmean(np.vstack(stack), axis=0)


def _mean_std(values: np.ndarray) -> tuple[float, float]:
    """``(mean, sample std)`` ignoring NaN, with ``(nan, 0.0)`` for a slice
    with nothing usable in it — so callers can gate on ``std > 0`` alone."""
    usable = values[~np.isnan(values)]
    if len(usable) < 2:
        return (float(usable[0]) if len(usable) else np.nan), 0.0
    return float(usable.mean()), float(usable.std(ddof=1))


def _weighted_blend(parts: dict[str, np.ndarray], weights: dict[str, float],
                    length: int) -> np.ndarray:
    """Weighted blend, reweighted per row onto whichever components that row
    actually has. NaN where a row has none."""
    total = np.zeros(length)
    wsum = np.zeros(length)
    for name, weight in weights.items():
        values = parts.get(name)
        if values is None or weight <= 0:
            continue
        present = ~np.isnan(values)
        total = np.where(present, total + weight * np.nan_to_num(values), total)
        wsum = np.where(present, wsum + weight, wsum)
    return np.where(wsum > 0, total / np.where(wsum > 0, wsum, 1.0), np.nan)


class ShotScorer:
    """Assigns a 0-100 quality score per shot."""

    def __init__(self, weights: dict[str, dict[str, float]] | None = None,
                 min_shots: int = MIN_SHOTS):
        self.weights = weights or WEIGHTS
        self.min_shots = min_shots

    # -- public ------------------------------------------------------------
    def score(self, df: pd.DataFrame) -> pd.Series:
        """Return a per-row quality score (0-100), indexed like ``df``. Rows
        that can't be scored at all come back as ``NA``."""
        out = pd.Series(pd.NA, index=df.index, dtype="Float64")
        if df.empty or "club" not in df.columns:
            return out

        n = len(df)
        strike = self._strike(df)
        shape = self._shape(df)
        proximity, on_course_mask, target_mask = self._proximity(df)

        parts = {"strike": strike, "shape": shape, "proximity": proximity}
        combined = np.full(n, np.nan)
        contexts = {
            "on_course_target": on_course_mask,
            "practice_target": target_mask,
            # Everything with nothing to be close to: range shots with no
            # target selected, and shots up the hole that were never going at
            # the flag. Both are judged on contact and repeatability.
            "no_target": ~(on_course_mask | target_mask),
        }
        for context, mask in contexts.items():
            if not mask.any():
                continue
            blended = _weighted_blend(
                {k: v[mask] for k, v in parts.items()},
                self.weights.get(context, {}),
                int(mask.sum()),
            )
            combined[mask] = blended

        combined[~self._is_swing(df)] = np.nan
        scored = np.round(100.0 * combined, 1)
        return pd.Series(pd.array(scored, dtype="Float64"), index=df.index)

    # -- components --------------------------------------------------------
    def _strike(self, df: pd.DataFrame) -> np.ndarray:
        """Contact and launch quality: smash, launch angle, spin, AoA against
        the club's optimal windows. Says nothing about where the ball went."""
        n = len(df)
        smash = self._smash(df)
        vla = _num(df, find_col(df, LAUNCH_ANGLE_ALIASES))
        spin = _num(df, find_col(df, SPIN_RATE_ALIASES))
        aoa = _num(df, find_col(df, AOA_ALIASES))
        if smash is None and vla is None and spin is None and aoa is None:
            return np.full(n, np.nan)

        speed = _num(df, find_col(df, CLUB_SPEED_ALIASES))
        windows = self._club_windows(df, speed)

        parts = []
        for values, key in ((smash, "smash"), (vla, "launch"),
                            (spin, "spin"), (aoa, "aoa")):
            if values is None:
                continue
            lo, hi = windows[key]
            parts.append(_window_scores(values, lo, hi))
        return _mean_of_present(parts, n)

    def _shape(self, df: pd.DataFrame) -> np.ndarray:
        """The shot against the player's own history with that club: distance
        vs their stock number, offline vs their usual spread.

        Club-aware in both terms. For an iron or wedge the distance term is
        symmetric about the club's own mean — that is what gapping means, and
        20 yards long is as much a miss as 20 short. For the driver it is
        one-sided (see LONGER_IS_BETTER_CLUBS) and reads TOTAL distance rather
        than carry, because roll is part of what a driver is for.
        """
        n = len(df)
        carry = _num(df, find_col(df, CARRY_ALIASES))
        total = _num(df, find_col(df, TOTAL_ALIASES))
        offline = _num(df, find_col(df, OFFLINE_ALIASES))
        if carry is None and total is None and offline is None:
            return np.full(n, np.nan)

        clubs = df["club"].astype(str).str.strip().to_numpy()
        out = np.full(n, np.nan)
        for club in pd.unique(clubs):
            mask = clubs == club
            if mask.sum() < self.min_shots:
                continue  # too few shots for this club's own spread to mean anything
            longer_is_better = club in LONGER_IS_BETTER_CLUBS
            # Driver spends its life being measured in total distance; every
            # other club in carry.
            distance = (total if longer_is_better and total is not None else carry)
            mix = SHAPE_MIX_DRIVER if longer_is_better else SHAPE_MIX_GAPPING

            parts: dict[str, np.ndarray] = {}
            if distance is not None:
                sub = distance[mask]
                mean, std = _mean_std(sub)
                if std > 0:
                    z = (sub - mean) / std
                    parts["distance"] = np.clip(
                        # +/-2 sigma spans the 0..1 range either way.
                        0.5 + z / 4.0 if longer_is_better else 1.0 - np.abs(z) / 2.0,
                        0.0, 1.0)
            if offline is not None:
                sub = offline[mask]
                _, std = _mean_std(sub)
                if std > 0:
                    parts["offline"] = np.clip(1.0 - np.abs(sub) / (2 * std), 0.0, 1.0)
            if parts:
                out[mask] = _weighted_blend(parts, mix, int(mask.sum()))
        return out

    def _proximity(self, df: pd.DataFrame):
        """``(proximity_score, on_course_target_mask, practice_target_mask)``.

        The masks are what the context blend keys off, and they're computed
        here because both come down to the same question: did this shot have a
        target it can be measured against? A row that was on course but not
        going at the flag comes back False in both, and is scored on strike
        and shape like any other targetless shot.
        """
        n = len(df)
        if "round_type" in df.columns:
            on_course = (df["round_type"].astype(str) == _ON_COURSE).to_numpy()
        else:
            # Pure CSV-sourced history is all practice — the column only ever
            # comes from a live-tracked round (see data.store).
            on_course = np.zeros(n, dtype=bool)

        prox, reference = _nans(n), _nans(n)
        course_mask = np.zeros(n, dtype=bool)
        target_mask = np.zeros(n, dtype=bool)

        if on_course.any():
            p, r, ok = self._on_course_proximity(df, on_course)
            idx = np.flatnonzero(on_course)
            prox[idx[ok]], reference[idx[ok]] = p[ok], r[ok]
            course_mask[idx[ok]] = True

        if not on_course.all():
            p, r, ok = self._range_proximity(df, ~on_course)
            idx = np.flatnonzero(~on_course)
            prox[idx[ok]], reference[idx[ok]] = p[ok], r[ok]
            target_mask[idx[ok]] = True

        # Full marks at or inside the expected proximity for that distance,
        # falling linearly to zero at PROXIMITY_FALLOFF times it.
        with np.errstate(invalid="ignore"):
            expected = np.maximum(PROXIMITY_FLOOR_YDS, PROXIMITY_FRAC * reference)
            span = expected * (PROXIMITY_FALLOFF - 1.0)
            score = np.clip(1.0 - np.maximum(0.0, prox - expected) / span, 0.0, 1.0)
            unusable = np.isnan(prox) | np.isnan(reference) | (reference <= 0)
        score = np.where(unusable, np.nan, score)
        # A mask can only claim a context the blend can actually honor.
        return score, course_mask & ~unusable, target_mask & ~unusable

    # -- helpers -----------------------------------------------------------
    def _smash(self, df: pd.DataFrame) -> np.ndarray | None:
        """Smash factor: the recorded column when the monitor reports one,
        else derived from ball and club speed. Values outside (0.5, 2.0) are
        sensor glitches, not golf — same window data.store uses."""
        smash = _num(df, find_col(df, SMASH_FACTOR_ALIASES))
        if smash is None:
            ball = _num(df, find_col(df, BALL_SPEED_ALIASES))
            club_speed = _num(df, find_col(df, CLUB_SPEED_ALIASES))
            if ball is None or club_speed is None:
                return None
            with np.errstate(divide="ignore", invalid="ignore"):
                smash = np.where(club_speed > 0, ball / club_speed, np.nan)
        return np.where((smash > 0.5) & (smash < 2.0), smash, np.nan)

    def _club_windows(self, df: pd.DataFrame, speed: np.ndarray | None) -> dict:
        """Per-row ``(low, high)`` arrays for each windowed metric.

        ``get_targets`` varies only with (club, clubhead speed), and within one
        club the speeds repeat heavily (and are all 100.0 when club speed is
        absent), so the lookup is memoized on the club and the speed rounded to
        the nearest mph rather than recomputed per shot — this runs over the
        entire history on every landing-page render.
        """
        n = len(df)
        clubs = df["club"].astype(str).str.strip().to_numpy()
        if speed is None:
            speeds = np.full(n, 100.0)
        else:
            speeds = np.where(np.isnan(speed), 100.0, np.round(speed))

        keys = ["launch", "spin", "aoa", "smash"]
        bounds = {k: (np.empty(n), np.empty(n)) for k in keys}
        memo: dict[tuple, object] = {}
        for i, (club, sp) in enumerate(zip(clubs, speeds)):
            key = (club, sp)
            targets = memo.get(key)
            if targets is None:
                targets = memo[key] = get_targets(club, float(sp))
            for name, window in (("launch", targets.launch_window),
                                 ("spin", targets.spin_window),
                                 ("aoa", targets.aoa_window),
                                 ("smash", targets.smash_window)):
                bounds[name][0][i], bounds[name][1][i] = window
        return bounds

    def _on_course_proximity(self, df: pd.DataFrame, mask: np.ndarray):
        """``(proximity, distance_played_from, was_going_at_the_flag)`` in
        yards for on-course rows.

        ``distancetopin`` is written after the shot resolves, so it IS the
        proximity. What it has to be judged against is the distance the shot
        was played from, which is the distance-to-pin the PREVIOUS stroke on
        that hole left — so the reference is looked up by stroke number rather
        than by row order.

        Going through stroke numbers rather than a positional shift is what
        makes this correct across mulligans: a re-hit repeats its HoleShot, so
        a positional shift would hand the second attempt the first attempt's
        result as its starting distance. Every attempt at stroke N instead
        references the final position of stroke N-1, which is where each of
        them genuinely was played from.

        The first stroke of a hole has no predecessor, so its starting distance
        is reconstructed as proximity + the distance the shot travelled. That's
        exact for a shot straight at the flag and slightly short for one that
        wasn't, which is the right direction: it never flatters a wild tee shot.
        """
        sub = df.loc[mask]
        dtp_col = find_col(sub, DISTANCE_TO_PIN_ALIASES)
        if not dtp_col:
            return _nans(len(sub)), _nans(len(sub)), np.zeros(len(sub), dtype=bool)
        dtp = pd.to_numeric(sub[dtp_col], errors="coerce")

        total_col = find_col(sub, TOTAL_ALIASES) or find_col(sub, CARRY_ALIASES)
        travelled = (pd.to_numeric(sub[total_col], errors="coerce")
                     if total_col else pd.Series(np.nan, index=sub.index))

        have_keys = {"session_id", "hole"} <= set(sub.columns)
        if have_keys and "holeshot" in sub.columns:
            holeshot = pd.to_numeric(sub["holeshot"], errors="coerce")
            keys = [sub["session_id"], sub["hole"], holeshot]
            final_at = dtp.groupby(keys, sort=False).last()
            previous = pd.MultiIndex.from_arrays(
                [sub["session_id"], sub["hole"], holeshot - 1])
            reference = pd.Series(final_at.reindex(previous).to_numpy(), index=sub.index)
        elif have_keys:
            # Rounds archived before the holeshot column existed: row order
            # within a hole is play order, so a positional shift is the best
            # available reference (and mulligans are rare enough in that old
            # data to be worth the slight overstatement).
            reference = dtp.groupby([sub["session_id"], sub["hole"]], sort=False).shift(1)
        else:
            reference = pd.Series(np.nan, index=sub.index)

        reference = reference.fillna(dtp + travelled)
        prox = dtp.to_numpy(dtype=float)
        ref = reference.to_numpy(dtype=float)
        with np.errstate(invalid="ignore"):
            # Only a shot that covered most of the way to the hole was being
            # played at it — see the module docstring on ON_COURSE_REACH.
            going_at_it = travelled.to_numpy(dtype=float) >= ON_COURSE_REACH * ref
        return prox, ref, going_at_it & ~np.isnan(prox)

    def _range_proximity(self, df: pd.DataFrame, mask: np.ndarray):
        """``(proximity, target_distance, target_in_play)`` for practice rows.

        The range never moves the ball, so there is no measured proximity to
        read — it is reconstructed from where the shot finished relative to a
        target assumed to sit straight down the aim line: how far past or short
        of the target distance the ball came to rest, and how far offline.
        """
        sub = df.loc[mask]
        n = len(sub)
        none = (_nans(n), _nans(n), np.zeros(n, dtype=bool))

        target_col = find_col(sub, TARGET_DISTANCE_ALIASES)
        if not target_col:
            return none
        target = pd.to_numeric(sub[target_col], errors="coerce").to_numpy(dtype=float)

        distance = _num(sub, find_col(sub, TOTAL_ALIASES))
        if distance is None:
            distance = _num(sub, find_col(sub, CARRY_ALIASES))
        if distance is None:
            return none
        # A missing offline contributes nothing rather than voiding the shot,
        # so proximity falls back to the distance error alone. That flatters a
        # shot that was wide, which is why it's a fallback and not the model —
        # every launch monitor this app reads reports offline.
        offline = _num(sub, find_col(sub, OFFLINE_ALIASES))
        offline = np.zeros(n) if offline is None else np.nan_to_num(offline)

        in_play = self._target_in_play(sub, target, distance)
        prox = np.hypot(distance - target, offline)
        return prox, target, in_play & ~np.isnan(prox)

    def _target_in_play(self, sub: pd.DataFrame, target: np.ndarray,
                        distance: np.ndarray) -> np.ndarray:
        """Whether the selected range target is plausibly what this shot was
        aimed at — see the module docstring on targets.

        Judged against the club's own stock distance in this frame when there
        are enough shots to know it, and against the shot's own distance
        otherwise. The latter is the weaker test (a shot can't be far from a
        target it defines), but it only ever applies to a club with fewer than
        MIN_SHOTS on record, and it still rejects the unreachable default pin.
        """
        clubs = sub["club"].astype(str).str.strip().to_numpy()
        stock = np.array(distance, dtype=float)
        for club in pd.unique(clubs):
            club_mask = clubs == club
            if club_mask.sum() >= self.min_shots:
                mean = np.nanmean(distance[club_mask])
                if not np.isnan(mean):
                    stock[club_mask] = mean
        with np.errstate(invalid="ignore"):
            return ((target >= TARGET_REACH_LO * stock)
                    & (target <= TARGET_REACH_HI * stock)
                    & (target > 0))

    @staticmethod
    def _is_swing(df: pd.DataFrame) -> np.ndarray:
        """Putts and penalty-stroke records are strokes, not shots — their ball
        data is cloned from the preceding record, so scoring them would score
        the same swing twice (data.on_course.exclude_putts)."""
        from config import NON_SWING_CLUBS

        keep = np.ones(len(df), dtype=bool)
        if "club" in df.columns:
            keep &= ~df["club"].astype(str).str.strip().isin(NON_SWING_CLUBS).to_numpy()
        if "shot_result" in df.columns:
            keep &= (pd.to_numeric(df["shot_result"], errors="coerce")
                     .fillna(0).to_numpy() != 2)
        return keep
