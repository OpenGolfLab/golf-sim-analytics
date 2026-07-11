"""Environmental normalization.

Normalizes ball-flight distances to a standard environment (80F, sea level) so
sessions hit in different conditions compare fairly. There is no temperature or
altitude column in the export, so the *actual* temperature the shots were hit in
is supplied manually by the caller.

The air-density term comes from ``data.physics.air_density_at``. Rather than
re-integrating every shot's trajectory (far too slow to run in the UI's filter
hot path), carry/total are scaled by the density ratio raised to an empirical
exponent, tuned so a ~40F swing moves a driver a few yards -- the standard
"~2 yards per 10F" rule of thumb. The scaling is non-destructive: it returns a
copy and never mutates the caller's frame.
"""
from __future__ import annotations

import pandas as pd

from data.columns import CARRY_ALIASES, TOTAL_ALIASES, find_col
from data.physics import air_density_at

STANDARD_TEMP_F = 80.0
STANDARD_ALTITUDE_FT = 0.0

# Carry responds to air density sub-linearly (drag scales with density, but the
# distance response is damped). ~0.4 reproduces roughly 2 yds / 10F on a driver.
_DENSITY_CARRY_EXPONENT = 0.4


class EnvironmentalNormalizer:
    """Adjusts carry/total to a standard environment given the temperature the
    shots were actually hit in."""

    def __init__(self, standard_temp_f: float = STANDARD_TEMP_F,
                 exponent: float = _DENSITY_CARRY_EXPONENT):
        self.standard_temp_f = standard_temp_f
        self.exponent = exponent

    def scale_factor(self, temp_f: float) -> float:
        """Multiplier applied to carry/total to move a shot hit at ``temp_f`` to
        the standard environment. >1 when the actual air was denser (colder)
        than standard, since the shot would have carried farther in standard
        conditions."""
        rho_actual = air_density_at(temp_f, STANDARD_ALTITUDE_FT)
        rho_std = air_density_at(self.standard_temp_f, STANDARD_ALTITUDE_FT)
        return (rho_actual / rho_std) ** self.exponent

    def normalize(self, df: pd.DataFrame, temp_f: float) -> pd.DataFrame:
        """Return a copy of ``df`` with carry/total distances normalized from
        ``temp_f`` to the standard environment. Columns that aren't present are
        simply skipped; the frame is never mutated in place."""
        out = df.copy()
        if temp_f is None:
            return out
        factor = self.scale_factor(temp_f)
        for aliases in (CARRY_ALIASES, TOTAL_ALIASES):
            col = find_col(out, aliases)
            if col is not None:
                out[col] = pd.to_numeric(out[col], errors="coerce") * factor
        return out
