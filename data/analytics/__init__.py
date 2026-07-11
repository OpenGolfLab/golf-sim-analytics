"""Analytics engines for the feature-expansion roadmap.

Each engine is a self-contained class so the math stays out of ``app.py``
and ``ui/``. Phase 0 lands the scaffolding (signatures + the target-window
lookup); later phases fill in the bodies:

    - targets.py            per-club optimal launch/spin/AoA windows
    - scoring.py            ShotScorer          (Phase 1)
    - diagnostics.py        DiagnosticsEngine   (Phase 1)
    - normalizer.py         EnvironmentalNormalizer (Phase 2)
"""
from __future__ import annotations

from data.analytics.diagnostics import DiagnosticsEngine
from data.analytics.normalizer import EnvironmentalNormalizer
from data.analytics.scoring import ShotScorer
from data.analytics.targets import ClubTargets, get_targets

__all__ = [
    "DiagnosticsEngine",
    "EnvironmentalNormalizer",
    "ShotScorer",
    "ClubTargets",
    "get_targets",
]
