"""Sim Handicap — a scoring index built from this app's own archived rounds.

It is **not** a USGA/WHS Handicap Index and the app says so wherever it shows
the number. The reason is not modesty, it's that the inputs are different in
ways that move the answer by several strokes: GSPro concedes short putts, the
wind and green speed are whatever was selected that day, sim courses carry no
official rating or slope, and nothing stops a player re-hitting a bad one.
What it *is* is a consistent measure of your own scoring in your own sim,
which is the thing that's actually useful for tracking whether you're getting
better. Calling it a Handicap Index would be the most misleading thing this
app could do; calling it nothing at all would waste real data.

How it's computed
-----------------
The shape follows WHS so the number lands in a familiar range:

  * a **differential** per round — score to par, normalized to 18 holes.
    Without a course rating and slope there is nothing else to normalize
    against, so this is deliberately a plain to-par figure rather than a
    rating-adjusted one dressed up to look like something it isn't.
  * the **best few** differentials from the last ``SCORING_WINDOW`` eligible
    rounds, averaged. How many count scales with how many rounds exist, using
    WHS's own table (``_DIFFERENTIALS_USED``) so the index isn't set by a
    single hot round early on. WHS's extra small-sample adjustments are not
    applied — they're calibrated against rated courses, and applying them here
    would be false precision.

Which rounds count
------------------
A round has to be a real, complete, honest attempt at a score:

  * **finished** — play didn't stop mid-hole (``round_summary``'s flag);
  * at least ``MIN_HOLES`` scored holes, so a 3-hole warm-up can't set an index;
  * **no mulligans**. This is the strict one, and it's the point: the strokes
    a player re-hits are precisely the ones that would have hurt, so a round
    with do-overs has a score but not a comparable one. Those rounds still
    appear everywhere in the app, marked with an asterisk (see
    ``data.on_course.MULLIGAN_MARK``) — they just don't set the number.

Verification
------------
Once ``MIN_ROUNDS`` eligible rounds exist there's enough history for the index
to mean something, and it's marked **verified** — the same idea as the
data-quality tier a contribution earns when its launch monitor can be
corroborated (see ``contribute.verification_block``). Below that the app shows
the shortfall as a path ("5 rounds needed, 2 so far") rather than a dash.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from data.on_course import round_summary

# How many eligible rounds are needed before there's an index at all — and,
# once reached, before it counts as verified.
MIN_ROUNDS = 5

# Only the most recent this many eligible rounds are considered, so an index
# tracks current form rather than averaging in a season that's over.
SCORING_WINDOW = 20

# A round needs at least this many scored holes to say anything about scoring
# ability. Nine is the smallest score WHS itself will accept.
MIN_HOLES = 9

# WHS's own table: eligible rounds available -> how many of the best
# differentials are averaged. Read as "from N rounds up to the next entry".
_DIFFERENTIALS_USED = {5: 1, 7: 2, 9: 3, 12: 4, 15: 5, 17: 6, 19: 7, 20: 8}

# Display for an index that doesn't exist yet, matching the other landing-page
# record tiles.
BLANK = "---"


def _differentials_used(n_rounds: int) -> int:
    """How many of the best differentials to average, per the WHS table."""
    used = 1
    for threshold, count in sorted(_DIFFERENTIALS_USED.items()):
        if n_rounds >= threshold:
            used = count
    return used


@dataclass(frozen=True)
class SimHandicap:
    """The player's Sim Handicap and everything the UI needs to explain it."""
    value: float | None = None
    verified: bool = False
    # Rounds that met every eligibility rule, and how many of them actually
    # set the number (the "best N of M" the status line quotes).
    eligible_rounds: int = 0
    rounds_used: int = 0
    # Rounds thrown out, split by reason, so the UI can tell a player *why*
    # their round didn't count instead of silently dropping it.
    excluded_mulligans: int = 0
    excluded_incomplete: int = 0

    @property
    def label(self) -> str:
        """The number as shown on a tile — e.g. "+2.1", "12.4", or "---"."""
        if self.value is None:
            return BLANK
        return f"{self.value:+.1f}" if self.value < 0 else f"{self.value:.1f}"

    @property
    def status(self) -> str:
        """One line of context under the number: what it's built from, or what
        it's still waiting for."""
        if self.value is None:
            need = MIN_ROUNDS - self.eligible_rounds
            have = f"{self.eligible_rounds} so far"
            if self.excluded_mulligans:
                have += f", {self.excluded_mulligans} with mulligans"
            return f"{need} more round{'s' if need != 1 else ''} needed ({have})"
        return f"Verified · best {self.rounds_used} of {self.eligible_rounds}"


def compute_sim_handicap(df: pd.DataFrame) -> SimHandicap:
    """The player's Sim Handicap over their archived on-course rounds.

    Returns a ``SimHandicap`` with ``value`` None until there are
    ``MIN_ROUNDS`` eligible rounds — the counts come back populated either
    way, so the UI can show progress toward the index rather than a dash.
    """
    rounds = round_summary(df)
    if rounds.empty:
        return SimHandicap()

    holes = pd.to_numeric(rounds["holes"], errors="coerce")
    par = pd.to_numeric(rounds["par"], errors="coerce")
    to_par = pd.to_numeric(rounds["to_par"], errors="coerce")
    mulligans = (pd.to_numeric(rounds["mulligans"], errors="coerce").fillna(0)
                 if "mulligans" in rounds.columns else pd.Series(0, index=rounds.index))
    finished = (rounds["finished"].astype(bool)
                if "finished" in rounds.columns else pd.Series(True, index=rounds.index))

    complete = finished & (holes >= MIN_HOLES) & (par > 0) & to_par.notna()
    clean = complete & (mulligans == 0)

    excluded_mulligans = int((complete & (mulligans > 0)).sum())
    excluded_incomplete = int((~complete).sum())

    eligible = rounds[clean]
    if len(eligible) < MIN_ROUNDS:
        return SimHandicap(
            eligible_rounds=len(eligible),
            excluded_mulligans=excluded_mulligans,
            excluded_incomplete=excluded_incomplete,
        )

    # round_summary is already oldest -> newest, so the tail is current form.
    recent = eligible.tail(SCORING_WINDOW)
    differentials = (pd.to_numeric(recent["to_par"], errors="coerce")
                     * 18.0 / pd.to_numeric(recent["holes"], errors="coerce"))
    used = _differentials_used(len(recent))
    value = float(differentials.nsmallest(used).mean())

    return SimHandicap(
        value=round(value, 1),
        verified=True,
        eligible_rounds=len(recent),
        rounds_used=used,
        excluded_mulligans=excluded_mulligans,
        excluded_incomplete=excluded_incomplete,
    )
