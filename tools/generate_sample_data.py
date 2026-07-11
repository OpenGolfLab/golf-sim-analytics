"""Generate realistic sample GSPro-export CSVs for demo/testing.

Per-club parameters were fit from the real exports in raw_csvs/ (club speed,
carry, smash, spin, launch, dispersion). The generator lays down 25 sessions
over ~6 months with a gradual improvement curve (speed up, dispersion tightens,
smash sharpens), a warm-up ramp at the start of each session, and physically
consistent shots (ball speed = club speed x smash, carry tracks ball speed).

Output: sample_data/gspro-export<MM-DD-YY-HH-MM-SS>.csv — the exact filename
shape + column schema the app already ingests. Drop them in raw_csvs/ to load.

Run:  python tools/generate_sample_data.py
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent.parent / "sample_data"
N_SESSIONS = 25
RNG = np.random.default_rng(2026)

# Per-club baselines fit from raw_csvs/. (cs = club speed, sd = std dev,
# roll = roll fraction of carry, off_sd = offline dispersion std.)
CLUBS = {
    "DR": dict(cs=113, cs_sd=3.2, smash=1.46, carry=268, carry_sd=9, spin=2650, spin_sd=300,
               vla=13.5, vla_sd=1.4, decent=37, apex=32, off_sd=13, roll=0.07, aoa=0.5, aoa_sd=1.8),
    "3W": dict(cs=106, cs_sd=2.6, smash=1.47, carry=240, carry_sd=8, spin=3500, spin_sd=300,
               vla=12.5, vla_sd=1.2, decent=42, apex=30, off_sd=11, roll=0.05, aoa=-1.5, aoa_sd=1.5),
    "5W": dict(cs=103, cs_sd=2.6, smash=1.46, carry=228, carry_sd=8, spin=4100, spin_sd=320,
               vla=13.5, vla_sd=1.2, decent=45, apex=31, off_sd=10, roll=0.04, aoa=-2.0, aoa_sd=1.5),
    "4I": dict(cs=95, cs_sd=2.4, smash=1.45, carry=202, carry_sd=7, spin=4800, spin_sd=350,
               vla=15.0, vla_sd=1.2, decent=46, apex=28, off_sd=9, roll=0.03, aoa=-2.5, aoa_sd=1.4),
    "5I": dict(cs=90, cs_sd=2.2, smash=1.45, carry=184, carry_sd=7, spin=5600, spin_sd=380,
               vla=17.0, vla_sd=1.2, decent=48, apex=30, off_sd=8, roll=0.03, aoa=-3.0, aoa_sd=1.3),
    "6I": dict(cs=85, cs_sd=2.1, smash=1.45, carry=171, carry_sd=7, spin=6200, spin_sd=400,
               vla=19.0, vla_sd=1.3, decent=49, apex=30, off_sd=8, roll=0.02, aoa=-3.2, aoa_sd=1.3),
    "7I": dict(cs=81, cs_sd=2.0, smash=1.45, carry=153, carry_sd=6, spin=7000, spin_sd=420,
               vla=21.0, vla_sd=1.4, decent=50, apex=31, off_sd=7, roll=0.02, aoa=-3.5, aoa_sd=1.3),
    "8I": dict(cs=75, cs_sd=2.1, smash=1.44, carry=141, carry_sd=6, spin=7950, spin_sd=450,
               vla=22.8, vla_sd=1.5, decent=50, apex=31, off_sd=6, roll=0.01, aoa=-3.8, aoa_sd=1.3),
    "9I": dict(cs=71, cs_sd=2.3, smash=1.42, carry=127, carry_sd=6, spin=9100, spin_sd=500,
               vla=25.5, vla_sd=1.6, decent=51, apex=30, off_sd=6, roll=0.01, aoa=-4.2, aoa_sd=1.4),
    "PW": dict(cs=70, cs_sd=2.4, smash=1.40, carry=113, carry_sd=6, spin=9300, spin_sd=520,
               vla=26.0, vla_sd=1.8, decent=52, apex=29, off_sd=5, roll=0.0, aoa=-4.5, aoa_sd=1.5),
    "GW": dict(cs=65, cs_sd=2.6, smash=1.37, carry=100, carry_sd=6, spin=10200, spin_sd=560,
               vla=28.0, vla_sd=2.0, decent=52, apex=28, off_sd=5, roll=0.0, aoa=-5.0, aoa_sd=1.6),
    "SW": dict(cs=60, cs_sd=2.8, smash=1.33, carry=84, carry_sd=6, spin=10600, spin_sd=600,
               vla=31.0, vla_sd=2.3, decent=53, apex=27, off_sd=5, roll=0.0, aoa=-5.5, aoa_sd=1.7),
}
_IRONS = ["4I", "5I", "6I", "7I", "8I", "9I", "PW", "GW", "SW", "3W", "5W"]

COLUMNS = ["Carry", "TotalDistance", "BallSpeed", "BackSpin", "SideSpin", "HLA", "VLA",
           "Decent", "DistanceToPin", "PeakHeight", "Offline", "rawSpinAxis", "rawCarryGame",
           "rawCarryLM", "Club", "ClubSpeed", "Path", "AoA", "FaceToTarget", "FaceToPath",
           "Lie", "Loft", "DynamicLoft", "CR", "HI", "VI", "SmashFactor"]


def _shot(club, t, warmup):
    """One realistic shot. t in [0,1] is the progression fraction; warmup
    slightly slows and widens the first few shots of a session."""
    p = CLUBS[club]
    gain = 1 + 0.045 * t           # ~+4.5% club speed over the 25 sessions
    smash_gain = 0.02 * t          # contact sharpens over time
    tighten = 1 - 0.28 * t         # dispersion tightens ~28%
    wu_speed = RNG.uniform(0.93, 0.98) if warmup else 1.0
    wu_spread = 1.5 if warmup else 1.0

    cs = RNG.normal(p["cs"] * gain * wu_speed, p["cs_sd"])
    smash = np.clip(RNG.normal(p["smash"] + smash_gain, 0.02) - (0.05 if warmup else 0), 0.7, 1.52)
    ball = cs * smash
    base_ball = p["cs"] * p["smash"]
    carry = max(5.0, RNG.normal(p["carry"] * (ball / base_ball), p["carry_sd"] * tighten))
    total = carry * (1 + p["roll"] + RNG.uniform(-0.01, 0.02))
    offline = RNG.normal(0, p["off_sd"] * tighten * wu_spread)
    side_spin = -offline * RNG.uniform(35, 55)
    spin = max(1200, RNG.normal(p["spin"], p["spin_sd"]))
    vla = RNG.normal(p["vla"], p["vla_sd"])
    hla = RNG.normal(0, 1.4 * wu_spread)
    row = {c: 0.0 for c in COLUMNS}
    row.update({
        "Carry": round(carry, 2), "TotalDistance": round(total, 2), "BallSpeed": round(ball, 2),
        "BackSpin": round(spin), "SideSpin": round(side_spin), "HLA": round(hla, 2),
        "VLA": round(vla, 2), "Decent": round(RNG.normal(p["decent"], 2), 2),
        "DistanceToPin": round(max(0, 300 - carry), 1), "PeakHeight": round(RNG.normal(p["apex"], 3) * 3, 1),
        "Offline": round(offline, 2), "rawSpinAxis": round(RNG.normal(0, 4), 2),
        "rawCarryGame": round(carry, 2), "rawCarryLM": round(carry * RNG.uniform(1.0, 1.05), 2),
        "Club": club, "ClubSpeed": round(cs, 2), "AoA": round(RNG.normal(p["aoa"], p["aoa_sd"]), 2),
        "SmashFactor": round(smash, 3),
    })
    return row


def _session(t):
    """A session's shots. Some are driver-heavy 'speed' days, others full bag."""
    speed_day = RNG.random() < 0.4
    n = RNG.integers(50, 71)
    if speed_day:
        clubs = ["DR"] * int(n * 0.7) + list(RNG.choice(_IRONS, size=n - int(n * 0.7)))
    else:
        clubs = ["DR"] * int(n * 0.35) + list(RNG.choice(_IRONS, size=n - int(n * 0.35)))
    RNG.shuffle(clubs)
    return [_shot(c, t, warmup=(i < 5)) for i, c in enumerate(clubs)]


def main():
    OUT_DIR.mkdir(exist_ok=True)
    base = datetime.now()
    # 25 sessions ending a few days ago, ~7 days apart.
    dates = sorted(base - timedelta(days=(N_SESSIONS - 1 - i) * 7 + int(RNG.integers(-2, 3)),
                                    hours=int(RNG.integers(0, 6)), minutes=int(RNG.integers(0, 60)))
                   for i in range(N_SESSIONS))
    for i, dt in enumerate(dates):
        rows = _session(i / (N_SESSIONS - 1))
        fname = f"gspro-export{dt.strftime('%m-%d-%y-%H-%M-%S')}.csv"
        with open(OUT_DIR / fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
    print(f"Wrote {N_SESSIONS} sessions ({sum(1 for _ in OUT_DIR.glob('*.csv'))} files) to {OUT_DIR}")


if __name__ == "__main__":
    main()
