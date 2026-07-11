"""Generate a second demo dataset: a bad golfer's 2-year speed journey.

Story arc (driver club speed 95 -> 130 mph over ~24 months, all clubs
improving along with it):

  months  0-3   newbie gains + first lessons        95 -> 101 mph
  months  4-8   plateau (life gets busy)            ~102 mph
  months  9-12  speed-training block #1             -> 112 mph
  months 12-14  winter layoff, slight regression    -> 109 mph
  months 15-20  speed-training block #2             -> 123 mph
  months 21-24  grind to the goal                   -> 130 mph

Realism baked in, beyond the speed curve itself:
  - Contact quality (smash) improves separately and more steadily
    (1.38 -> 1.49 driver), so ball speed gains outpace club speed early on.
  - Dispersion tightens ~45% overall but temporarily WIDENS ~25% during the
    two speed blocks (swinging out of your shoes costs accuracy short-term).
  - A beginner's slice: offline is biased right early and the bias fades to
    neutral as the face control improves.
  - Driver AoA migrates from -3° (hitting down, ballooning spin ~3300 rpm)
    to +3° with ~2450 rpm — the classic speed-training launch optimization.
  - Mishit rate (chunks/tops with terrible smash and huge offline) starts at
    ~12% of shots and falls to ~2%.
  - Session cadence varies: sparser in winter, denser + driver-heavier during
    speed blocks; every session starts with a few warm-up swings.
  - Iron/wedge speeds gain a partial fraction of the driver's relative gain
    (speed training transfers ~70-90% down the bag).

Output: sample_data_progression/gspro-export<MM-DD-YY-HH-MM-SS>.csv — same
filename shape + column schema as tools/generate_sample_data.py.

To view it in the app: Settings -> "Use sample data (demo)" ON, then pick
"2-Year Progression" in the Sample dataset dropdown (config.SAMPLE_DATASETS
maps that entry to this folder). Don't drop these CSVs into raw_csvs/ — that
would mix demo shots into your real history.

Run:  python tools/generate_progression_data.py
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent.parent / "sample_data_progression"
RNG = np.random.default_rng(413)

MONTHS = 24.0
START_DR_CS = 95.0
END_DR_CS = 130.0

# Driver club-speed progression keyframes: (month, fraction of the 95->130
# journey). Plateau months 4-8, winter dip 12-14, two training blocks.
_SPEED_KEYFRAMES = [
    (0, 0.00), (3, 0.17), (8, 0.23), (12, 0.49),
    (14, 0.40), (20, 0.80), (22, 0.86), (24, 1.00),
]
# The two aggressive speed blocks, when dispersion temporarily widens.
_SPEED_BLOCKS = [(9.0, 12.0), (15.0, 20.0)]

# Per-club start-state (a genuinely bad golfer) and end-state deltas.
#   cs       start club speed        smash / smash_end   contact arc
#   carry    start carry             spin / spin_end     (driver de-spins)
#   vla/vla_end, aoa/aoa_end         launch optimization
#   off_sd   start offline std       slice: starting rightward offline bias
#   rel      fraction of the driver's *relative* speed gain this club gets
#   ceff     extra carry efficiency (launch/spin optimization) gained by the end
CLUBS = {
    "DR": dict(cs=95, cs_sd=3.6, smash=1.38, smash_end=1.49, carry=198, carry_sd=14,
               spin=3300, spin_end=2450, spin_sd=420, vla=11.5, vla_end=14.5, vla_sd=1.9,
               decent=34, apex=24, apex_end=35, off_sd=24, roll=0.09, aoa=-3.0, aoa_end=3.0,
               aoa_sd=2.2, slice=14, rel=1.00, ceff=0.10),
    "3W": dict(cs=89, cs_sd=3.2, smash=1.37, smash_end=1.47, carry=180, carry_sd=13,
               spin=4300, spin_end=3500, spin_sd=430, vla=11.0, vla_end=12.5, vla_sd=1.7,
               decent=40, apex=24, apex_end=31, off_sd=20, roll=0.06, aoa=-2.8, aoa_end=-1.2,
               aoa_sd=1.9, slice=11, rel=0.90, ceff=0.08),
    "5W": dict(cs=86, cs_sd=3.1, smash=1.36, smash_end=1.46, carry=170, carry_sd=12,
               spin=4800, spin_end=4100, spin_sd=440, vla=12.0, vla_end=13.5, vla_sd=1.7,
               decent=43, apex=25, apex_end=31, off_sd=18, roll=0.05, aoa=-3.0, aoa_end=-1.8,
               aoa_sd=1.8, slice=9, rel=0.88, ceff=0.07),
    "4I": dict(cs=80, cs_sd=3.0, smash=1.32, smash_end=1.44, carry=145, carry_sd=12,
               spin=5300, spin_end=4800, spin_sd=460, vla=13.0, vla_end=15.0, vla_sd=1.7,
               decent=44, apex=24, apex_end=29, off_sd=16, roll=0.04, aoa=-2.8, aoa_end=-2.5,
               aoa_sd=1.7, slice=8, rel=0.78, ceff=0.06),
    "5I": dict(cs=77, cs_sd=2.8, smash=1.33, smash_end=1.44, carry=140, carry_sd=11,
               spin=6000, spin_end=5600, spin_sd=470, vla=15.0, vla_end=17.0, vla_sd=1.6,
               decent=46, apex=25, apex_end=30, off_sd=14, roll=0.03, aoa=-3.0, aoa_end=-2.9,
               aoa_sd=1.6, slice=7, rel=0.77, ceff=0.06),
    "6I": dict(cs=74, cs_sd=2.7, smash=1.34, smash_end=1.44, carry=135, carry_sd=11,
               spin=6600, spin_end=6200, spin_sd=480, vla=17.0, vla_end=19.0, vla_sd=1.6,
               decent=47, apex=26, apex_end=30, off_sd=13, roll=0.03, aoa=-3.2, aoa_end=-3.1,
               aoa_sd=1.6, slice=6, rel=0.76, ceff=0.05),
    "7I": dict(cs=71, cs_sd=2.6, smash=1.34, smash_end=1.44, carry=128, carry_sd=10,
               spin=7300, spin_end=7000, spin_sd=500, vla=19.0, vla_end=21.0, vla_sd=1.7,
               decent=48, apex=26, apex_end=31, off_sd=12, roll=0.02, aoa=-3.5, aoa_end=-3.4,
               aoa_sd=1.6, slice=5, rel=0.75, ceff=0.05),
    "8I": dict(cs=68, cs_sd=2.6, smash=1.33, smash_end=1.43, carry=118, carry_sd=10,
               spin=8200, spin_end=7950, spin_sd=520, vla=21.0, vla_end=22.8, vla_sd=1.8,
               decent=49, apex=26, apex_end=31, off_sd=11, roll=0.02, aoa=-3.8, aoa_end=-3.7,
               aoa_sd=1.6, slice=4, rel=0.74, ceff=0.04),
    "9I": dict(cs=65, cs_sd=2.7, smash=1.32, smash_end=1.41, carry=105, carry_sd=9,
               spin=9200, spin_end=9100, spin_sd=540, vla=23.0, vla_end=25.5, vla_sd=1.9,
               decent=50, apex=25, apex_end=30, off_sd=10, roll=0.01, aoa=-4.2, aoa_end=-4.1,
               aoa_sd=1.7, slice=4, rel=0.73, ceff=0.04),
    "PW": dict(cs=62, cs_sd=2.8, smash=1.30, smash_end=1.39, carry=95, carry_sd=9,
               spin=9400, spin_end=9300, spin_sd=560, vla=24.0, vla_end=26.0, vla_sd=2.1,
               decent=51, apex=24, apex_end=29, off_sd=9, roll=0.0, aoa=-4.5, aoa_end=-4.4,
               aoa_sd=1.8, slice=3, rel=0.72, ceff=0.03),
    "GW": dict(cs=58, cs_sd=2.9, smash=1.27, smash_end=1.36, carry=80, carry_sd=8,
               spin=10000, spin_end=10200, spin_sd=580, vla=26.0, vla_end=28.0, vla_sd=2.3,
               decent=52, apex=23, apex_end=28, off_sd=8, roll=0.0, aoa=-5.0, aoa_end=-4.9,
               aoa_sd=1.9, slice=2, rel=0.71, ceff=0.03),
    "SW": dict(cs=55, cs_sd=3.0, smash=1.24, smash_end=1.32, carry=68, carry_sd=8,
               spin=10300, spin_end=10600, spin_sd=620, vla=29.0, vla_end=31.0, vla_sd=2.5,
               decent=53, apex=22, apex_end=27, off_sd=8, roll=0.0, aoa=-5.5, aoa_end=-5.4,
               aoa_sd=2.0, slice=2, rel=0.70, ceff=0.02),
}
_IRONS = ["4I", "5I", "6I", "7I", "8I", "9I", "PW", "GW", "SW", "3W", "5W"]

COLUMNS = ["Carry", "TotalDistance", "BallSpeed", "BackSpin", "SideSpin", "HLA", "VLA",
           "Decent", "DistanceToPin", "PeakHeight", "Offline", "rawSpinAxis", "rawCarryGame",
           "rawCarryLM", "Club", "ClubSpeed", "Path", "AoA", "FaceToTarget", "FaceToPath",
           "Lie", "Loft", "DynamicLoft", "CR", "HI", "VI", "SmashFactor"]

_DR_REL_GAIN = END_DR_CS / START_DR_CS - 1.0  # +36.8% over the journey


def _speed_frac(month: float) -> float:
    """Piecewise-linear fraction of the 95->130 journey at a given month."""
    ks = _SPEED_KEYFRAMES
    for (m0, f0), (m1, f1) in zip(ks, ks[1:]):
        if m0 <= month <= m1:
            return f0 + (f1 - f0) * (month - m0) / (m1 - m0)
    return ks[-1][1]


def _contact_frac(month: float) -> float:
    """Skill/contact improvement 0..1 — steadier than raw speed (lessons and
    reps keep paying off through plateaus), front-loaded slightly."""
    return min(1.0, month / MONTHS) ** 0.8


def _in_speed_block(month: float) -> bool:
    return any(lo <= month <= hi for lo, hi in _SPEED_BLOCKS)


def _shot(club: str, month: float, warmup: bool, session_jitter: float) -> dict:
    p = CLUBS[club]
    f = np.clip(_speed_frac(month) + session_jitter, 0.0, 1.05)  # good/bad days
    q = _contact_frac(month)

    # Club speed: this club's share of the driver's relative gain.
    gain = 1.0 + p["rel"] * _DR_REL_GAIN * f
    wu_speed = RNG.uniform(0.92, 0.97) if warmup else 1.0
    cs = RNG.normal(p["cs"] * gain * wu_speed, p["cs_sd"])

    # Contact: smash improves with q; dips slightly during warm-up.
    smash = RNG.normal(p["smash"] + (p["smash_end"] - p["smash"]) * q, 0.025)
    if warmup:
        smash -= 0.05

    # Mishits (tops/chunks/shanks): common early, rare late.
    mishit = RNG.random() < (0.12 - 0.10 * q)
    if mishit:
        smash *= RNG.uniform(0.72, 0.88)
    smash = float(np.clip(smash, 0.7, 1.52))
    ball = cs * smash

    # Carry tracks ball speed off the start-state baseline, plus a growing
    # launch/spin-optimization efficiency bonus.
    base_ball = p["cs"] * p["smash"]
    eff = 1.0 + p["ceff"] * q
    tighten = 1.0 - 0.45 * q
    carry = RNG.normal(p["carry"] * (ball / base_ball) * eff, p["carry_sd"] * tighten)
    if mishit:
        carry *= RNG.uniform(0.55, 0.85)
    carry = max(5.0, carry)
    total = carry * (1 + p["roll"] + RNG.uniform(-0.01, 0.02))

    # Dispersion: tightens with skill, temporarily widens in speed blocks,
    # and a beginner slice bias (rightward) fades as face control improves.
    widen = 1.25 if _in_speed_block(month) else 1.0
    wu_spread = 1.5 if warmup else 1.0
    slice_bias = p["slice"] * (1.0 - q)
    offline = RNG.normal(slice_bias, p["off_sd"] * tighten * widen * wu_spread)
    if mishit:
        offline *= RNG.uniform(1.6, 2.6)
    side_spin = -offline * RNG.uniform(35, 55) + slice_bias * RNG.uniform(15, 30)

    spin = max(1200, RNG.normal(p["spin"] + (p["spin_end"] - p["spin"]) * q, p["spin_sd"]))
    if mishit:
        spin *= RNG.uniform(1.1, 1.5)
    vla = RNG.normal(p["vla"] + (p["vla_end"] - p["vla"]) * q, p["vla_sd"])
    hla = RNG.normal(slice_bias * 0.18, 1.6 * wu_spread)
    aoa = RNG.normal(p["aoa"] + (p["aoa_end"] - p["aoa"]) * q, p["aoa_sd"])
    apex = RNG.normal(p["apex"] + (p["apex_end"] - p["apex"]) * q, 3)
    if mishit:
        apex *= RNG.uniform(0.4, 0.75)

    row = {c: 0.0 for c in COLUMNS}
    row.update({
        "Carry": round(carry, 2), "TotalDistance": round(total, 2), "BallSpeed": round(ball, 2),
        "BackSpin": round(spin), "SideSpin": round(side_spin), "HLA": round(hla, 2),
        "VLA": round(vla, 2), "Decent": round(RNG.normal(p["decent"] + 3 * q, 2), 2),
        "DistanceToPin": round(max(0, 300 - carry), 1), "PeakHeight": round(max(6.0, apex) * 3, 1),
        "Offline": round(offline, 2), "rawSpinAxis": round(RNG.normal(slice_bias * 0.4, 4), 2),
        "rawCarryGame": round(carry, 2), "rawCarryLM": round(carry * RNG.uniform(1.0, 1.05), 2),
        "Club": club, "ClubSpeed": round(cs, 2), "AoA": round(aoa, 2),
        "SmashFactor": round(smash, 3),
    })
    return row


def _session(month: float) -> list[dict]:
    """One range session. Speed-day probability (driver-heavy) grows as the
    speed obsession takes hold; sessions run 45-75 shots."""
    speed_day_p = 0.15 + 0.45 * _speed_frac(month)
    if _in_speed_block(month):
        speed_day_p = 0.7
    speed_day = RNG.random() < speed_day_p
    n = int(RNG.integers(45, 76))
    dr_frac = 0.75 if speed_day else 0.30
    clubs = ["DR"] * int(n * dr_frac) + list(RNG.choice(_IRONS, size=n - int(n * dr_frac)))
    RNG.shuffle(clubs)
    session_jitter = float(RNG.normal(0, 0.02))  # whole-session good/bad day
    return [_shot(c, month, warmup=(i < 5), session_jitter=session_jitter)
            for i, c in enumerate(clubs)]


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    for stale in OUT_DIR.glob("*.csv"):
        stale.unlink()

    end = datetime.now() - timedelta(days=3)
    start = end - timedelta(days=int(MONTHS * 30.44))

    # Walk the two years week by week; winter (months 12-14) is sparse and
    # speed blocks are denser than the base cadence.
    dates: list[datetime] = []
    day = start
    while day <= end:
        month = (day - start).days / 30.44
        if 12.0 <= month <= 14.0:
            p = 0.25          # winter layoff: barely playing
        elif _in_speed_block(month):
            p = 0.85          # training blocks: near-weekly grind
        else:
            p = 0.62
        if RNG.random() < p:
            dates.append(day + timedelta(hours=int(RNG.integers(8, 20)),
                                         minutes=int(RNG.integers(0, 60)),
                                         seconds=int(RNG.integers(0, 60))))
        day += timedelta(days=7)

    for dt in dates:
        month = (dt - start).days / 30.44
        rows = _session(month)
        fname = f"gspro-export{dt.strftime('%m-%d-%y-%H-%M-%S')}.csv"
        with open(OUT_DIR / fname, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)

    print(f"Wrote {len(dates)} sessions to {OUT_DIR}")
    print("View in the app: Settings -> Use sample data (demo) ON, then pick "
          "'2-Year Progression' in the Sample dataset dropdown.")


if __name__ == "__main__":
    main()
