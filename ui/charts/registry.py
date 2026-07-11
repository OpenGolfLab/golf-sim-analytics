"""
Dashboard registry — metadata for every chart, decoupled from Tkinter.

This mirrors the old app's `plot_configs` dict, which was actually a good
pattern (a single data-driven registry the sidebar and grid builder both
read from). What's changed: the render functions now live in their own
modules instead of being bound methods on the god-class, and this table
has zero Tkinter dependency (no BooleanVar/StringVar) so it can be
imported and inspected in tests. ui/app_window.py wraps each entry with
the Tk variables it needs at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ui.charts import (
    carry_efficiency,
    club_compare,
    dispersion,
    efficiency,
    gapping,
    iron_stopping,
    launch_spin,
    live_dispersion,
    on_course_dashboard,
    session_compare,
    shot_quality,
    shot_shape,
    shot_timeline,
    speed_training,
    trajectory,
)


@dataclass(frozen=True)
class DashboardDef:
    name: str
    category: str  # "Metrics" | "Optimization" | "Live"
    column: str  # "left" | "right"
    has_color: bool
    render: Callable
    # True for charts whose x-axis is inherently wide (many club columns, a
    # date timeline, ...) so that when two panels share the screen they stack
    # (each keeps full width) instead of splitting side by side. Default False
    # (scatter/square charts, which are fine at half width). Read from the
    # chart module's optional WIDE constant.
    wide: bool = False
    # Reference-benchmark metric field(s) this chart can overlay (empty =
    # chart has no benchmark selector). app_window pairs these with
    # config.profiles_with() to build each chart's own benchmark control,
    # offering only the profiles that actually have data for it.
    benchmark_fields: tuple = ()
    benchmark_mode: str = "all"
    # One-line "what is this" help, shown as a sidebar hover tooltip. Sourced
    # from each chart module's DESCRIPTION, falling back to _DESCRIPTIONS below.
    description: str = ""


# Short menu help per dashboard (hover tooltip). Kept here so all the menu
# copy lives in one place rather than scattered across chart modules.
_DESCRIPTIONS = {
    "Trajectory": "Flight-path arcs with launch angle, peak height and descent "
                  "angle boxplots against each club's optimal window.",
    "Dispersion": "Your shot pattern — left/right offline vs distance — per club, "
                  "switchable between Carry and Total.",
    "Club Gapping": "Carry-distance gaps between clubs, to spot overlaps or holes "
                    "in your bag.",
    "Swing Efficiency": "Ball speed vs club speed with smash-factor reference lines "
                        "— how well you transfer speed to the ball.",
    "Launch & Spin Optimization": "Launch angle vs spin for one club against its "
                                  "speed-scaled optimal window.",
    "Iron Stopping Power": "Descent angle and peak height — how steeply iron shots "
                           "land and hold greens.",
    "Carry Efficiency": "Carry distance relative to ball speed, per club.",
    "Shot Shape": "Start direction vs curve — your draw/fade shape bias.",
    "Shot Quality": "A 0-100 quality score per shot, averaged per session and "
                    "trended over time.",
    "Live Dispersion": "Live shot pattern for the round currently in progress.",
    "Session Comparison": "Compare up to 4 of your recent sessions for one club, "
                          "side by side with a summary table.",
    "Club Comparison": "Compare clubs/adapter configs hit in a session — enter brand "
                       "and adapter for each, plotted and summarized.",
    "Shot & Club Trends": "Shots per club per calendar day across your whole "
                          "history, stacked by club, with summary tiles.",
    "Speed Training": "Driver speed development — cruising speed, fatigue curve, "
                      "velocity-vs-efficiency, and session-over-session progression.",
    "On-Course Play": "Scorecard for rounds you play on the course — score to par, "
                      "birdies/eagles, scoring breakdown and longest drives.",
}


def _dashboard(module) -> DashboardDef:
    return DashboardDef(
        name=module.NAME,
        category=module.CATEGORY,
        column=module.COLUMN,
        has_color=module.HAS_COLOR,
        render=module.render,
        wide=getattr(module, "WIDE", False),
        benchmark_fields=getattr(module, "BENCHMARK_FIELDS", ()),
        benchmark_mode=getattr(module, "BENCHMARK_MODE", "all"),
        description=getattr(module, "DESCRIPTION", "") or _DESCRIPTIONS.get(module.NAME, ""),
    )


DASHBOARDS: list[DashboardDef] = [
    _dashboard(m) for m in (
        dispersion,
        trajectory,
        gapping,
        efficiency,
        launch_spin,
        iron_stopping,
        carry_efficiency,
        shot_quality,
        session_compare,
        club_compare,
        speed_training,
        shot_timeline,
        shot_shape,
        on_course_dashboard,
        # Category "Live" is deliberately excluded from
        # app_window._build_sidebar_sections()'s loop — it's toggled by the
        # dedicated "Go Live" top-bar button instead of a sidebar checkbox,
        # since it's the one dashboard tied to a background watcher rather
        # than just the global filters.
        live_dispersion,
    )
]

CATEGORIES = ["Metrics", "Optimization", "Club Fitting", "Speed Training", "On Course", "Live"]
