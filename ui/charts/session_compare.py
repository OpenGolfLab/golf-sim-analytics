"""Session Comparison — put up to 4 recent sessions side by side for one club.

The panel's Club menu picks the club; the Sessions menu picks which of your last
10 sessions to overlay (up to 4), colored by session. Shots come straight from
each session, so it's unaffected by the global Time filter.
"""
from __future__ import annotations

from data import units as units_mod
from ui.charts._compare import PALETTE, render_comparison
from ui.empty_state import show_message

NAME = "Session Comparison"
CATEGORY = "Optimization"
COLUMN = "right"
HAS_COLOR = False
MAX_SESSIONS = 4


def render(fig, df, club_colors, font_scale, config, **extra):
    if df.empty or "club" not in df.columns or "session_id" not in df.columns:
        show_message(fig, "No session data yet", font_scale)
        return

    club = config.get("sc_club_var").get() if "sc_club_var" in config else ""
    session_vars = config.get("sc_session_vars", {})
    label_to_sid = config.get("sc_session_labels", {})
    selected = [(lbl, label_to_sid.get(lbl)) for lbl, var in session_vars.items()
                if var.get() and label_to_sid.get(lbl)][:MAX_SESSIONS]

    if not club or not selected:
        show_message(fig, "Pick a club and up to 4 sessions", font_scale,
                     hint="Use the Club and Sessions menus above.")
        return

    groups = []
    for i, (lbl, sid) in enumerate(selected):
        sub = df[(df["session_id"] == sid) & (df["club"].astype(str) == str(club))]
        # Short label for the legend/table header (drop the year + shot count).
        short = lbl.split(",")[0].split(" · ")[0]
        groups.append((short, sub, PALETTE[i % len(PALETTE)]))

    render_comparison(fig, groups, font_scale,
                      empty_msg=f"No {club} shots in the selected sessions",
                      subtitle=f"Club: {club}",
                      unit=extra.get("units", units_mod.YARDS))
