"""Rule-based coaching diagnostics.

Same philosophy as the ``focus`` callouts in ``data/store.compute_home_trends``:
deliberately simple, thresholded rules that only fire when the data supports
them. Each rule is a function that inspects one club's rows and optionally
returns a ``DiagnosticFlag``; new rules drop into ``DiagnosticsEngine._RULES``
without touching the engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from config import normalize_club_name
from data.columns import AOA_ALIASES, SPIN_RATE_ALIASES, find_col

# tone matches the landing page's focus tones ("warn" | "good" | "info").
Tone = str

# A club's rows must have at least this many shots meeting a rule's condition
# before it fires — one stray shot isn't a pattern worth coaching on.
MIN_FLAG_SHOTS = 3

# Driver spin/attack thresholds for the distance-leak rule.
_DRIVER_HIGH_SPIN = 3000.0


@dataclass(frozen=True)
class DiagnosticFlag:
    tag: str
    text: str
    tone: Tone


# A rule inspects one club's rows (already grouped by canonical club name) and
# optionally returns a flag.
Rule = Callable[[str, pd.DataFrame], "DiagnosticFlag | None"]


def _driver_spin_leak(club: str, sub: pd.DataFrame) -> DiagnosticFlag | None:
    """Driver shots hit with a downward attack angle AND high spin bleed carry
    to a ballooning, spinny flight — the classic "hitting down on the driver"
    distance leak. Fires only for the driver, and only when it's a pattern."""
    if club != "Dr":
        return None
    spin_col = find_col(sub, SPIN_RATE_ALIASES)
    aoa_col = find_col(sub, AOA_ALIASES)
    if not spin_col or not aoa_col:
        return None
    spin = pd.to_numeric(sub[spin_col], errors="coerce")
    aoa = pd.to_numeric(sub[aoa_col], errors="coerce")
    offending = sub[(spin > _DRIVER_HIGH_SPIN) & (aoa < 0)]
    if len(offending) < MIN_FLAG_SHOTS:
        return None
    aoa_med = pd.to_numeric(offending[aoa_col], errors="coerce").median()
    spin_med = pd.to_numeric(offending[spin_col], errors="coerce").median()
    return DiagnosticFlag(
        tag="Driver",
        text=(f"Distance leak — hitting down ({aoa_med:.1f}°) with high spin "
              f"({spin_med:.0f} rpm). Hit up on it to add carry."),
        tone="warn",
    )


class DiagnosticsEngine:
    """Runs the registered coaching rules over a shot frame."""

    _RULES: list[Rule] = [_driver_spin_leak]

    def flags(self, df: pd.DataFrame) -> list[DiagnosticFlag]:
        """Return the coaching flags raised by ``df`` (one per rule that
        fires). Empty when there's no data or nothing crosses threshold."""
        if df.empty or "club" not in df.columns:
            return []
        work = df.copy()
        work["_canon"] = work["club"].map(normalize_club_name)
        out: list[DiagnosticFlag] = []
        for rule in self._RULES:
            for canon, sub in work.groupby("_canon"):
                flag = rule(canon, sub)
                if flag is not None:
                    out.append(flag)
        return out
