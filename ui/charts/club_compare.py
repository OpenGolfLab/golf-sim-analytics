"""Club Comparison — compare clubs / driver adapter configs hit in one session.

A fitting session usually means hitting several drivers or adapter settings
back-to-back, all logged as "Dr". Here you pick the session and define up to 4
configs — each is a club plus the brand + adapter you were testing and the shot
range it covers — so each config is plotted and summarized separately. That way
you have hard data instead of trying to remember which shots were which.

Configs live on the panel entry as ``cc_session_id`` + ``cc_configs`` (a list of
{club, brand, adapter, start, end}); the Configure… dialog writes them.
"""
from __future__ import annotations

import pandas as pd

from data.columns import (
    BALL_SPEED_ALIASES, CARRY_ALIASES, CLUB_SPEED_ALIASES, LAUNCH_ANGLE_ALIASES,
    OFFLINE_ALIASES, SMASH_FACTOR_ALIASES, SPIN_RATE_ALIASES, TOTAL_ALIASES, find_col,
)
from ui.charts._compare import PALETTE, render_comparison
from ui.empty_state import show_message

# (column label, alias group) for the export summary, in order.
_SUMMARY_METRICS = [
    ("Shots", None), ("Carry", CARRY_ALIASES), ("Total", TOTAL_ALIASES),
    ("BallSpeed", BALL_SPEED_ALIASES), ("ClubSpeed", CLUB_SPEED_ALIASES),
    ("Launch", LAUNCH_ANGLE_ALIASES), ("Spin", SPIN_RATE_ALIASES),
    ("Smash", SMASH_FACTOR_ALIASES), ("Offline", OFFLINE_ALIASES),
]

NAME = "Club Comparison"
CATEGORY = "Club Fitting"
COLUMN = "right"
HAS_COLOR = False


def _label(cfg):
    parts = [str(cfg.get("brand", "")).strip(), str(cfg.get("club", "")).strip(),
             str(cfg.get("adapter", "")).strip()]
    return " ".join(p for p in parts if p) or "Config"


def config_frames(df, config):
    """[(cfg, sub_df)] per configured slot — from live capture when any shots
    have been logged, else the chosen archived session sliced by each config's
    range. Shared by render() and the export button so they stay in sync."""
    configs = config.get("cc_configs", [])
    if not configs:
        return []
    capture = config.get("cc_capture") or {}
    if any(capture.get(i) for i in range(len(configs))):
        return [(cfg, pd.DataFrame(capture.get(i) or []))
                for i, cfg in enumerate(configs[:4])]
    session_id = config.get("cc_session_id")
    if df.empty or "club" not in df.columns or "session_id" not in df.columns or not session_id:
        return [(cfg, pd.DataFrame()) for cfg in configs[:4]]
    sdf = df[df["session_id"] == session_id]
    out = []
    for cfg in configs[:4]:
        sub = sdf[sdf["club"].astype(str) == str(cfg.get("club"))]
        start = max(1, int(cfg.get("start") or 1))
        end = int(cfg.get("end") or len(sub))
        out.append((cfg, sub.iloc[start - 1:end]))
    return out


def summary_frame(frames):
    """Per-config average metrics as a DataFrame, for the fitting export."""
    rows = []
    for cfg, sub in frames:
        row = {"Brand": cfg.get("brand", ""), "Club": cfg.get("club", ""),
               "Adapter": cfg.get("adapter", "")}
        for label, aliases in _SUMMARY_METRICS:
            if aliases is None:  # "Shots"
                row[label] = len(sub)
                continue
            col = find_col(sub, aliases) if not sub.empty else None
            vals = pd.to_numeric(sub[col], errors="coerce").dropna() if col else pd.Series(dtype=float)
            if label == "Smash" and vals.empty and not sub.empty:
                bs, cs = find_col(sub, BALL_SPEED_ALIASES), find_col(sub, CLUB_SPEED_ALIASES)
                if bs and cs:
                    s = pd.to_numeric(sub[bs], errors="coerce") / pd.to_numeric(
                        sub[cs], errors="coerce").where(lambda x: x > 0)
                    vals = s[(s > 0.5) & (s < 2.0)].dropna()
            row[label] = round(float(vals.mean()), 2) if not vals.empty else None
        rows.append(row)
    return pd.DataFrame(rows)


def render(fig, df, club_colors, font_scale, config, **extra):
    configs = config.get("cc_configs", [])
    if not configs:
        show_message(fig, "Configure clubs to compare", font_scale,
                     hint="Click “Configure…” to set up the clubs/adapters you're testing.")
        return

    live = bool(config.get("cc_capture") and any(
        config["cc_capture"].get(i) for i in range(len(configs))))
    if not live and not config.get("cc_session_id"):
        show_message(fig, "Start hitting to log shots", font_scale,
                     hint="Pick a club under “Now hitting”, then swing. (Or choose a "
                          "session in Configure… to review past shots.)")
        return

    frames = config_frames(df, config)
    groups = []
    for i, (cfg, sub) in enumerate(frames):
        label = f"{_label(cfg)} ({len(sub)})" if live and not sub.empty else _label(cfg)
        groups.append((label, sub, PALETTE[i % len(PALETTE)]))
    render_comparison(
        fig, groups, font_scale,
        empty_msg=("Start hitting to log shots for each club" if live
                   else "No shots match the configured ranges"),
        subtitle=("Live capture · shots logged per club" if live
                  else "One session · configs by brand / adapter"))
