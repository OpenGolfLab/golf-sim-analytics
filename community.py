"""
Golf Sim Analytics — OpenGolfLab community read client.

The Contribute flow (contribute.py) writes anonymized shots to OpenGolfLab. This
is the read side: it fetches the community's shared shots back so the Community
dashboard can plot them alongside the same metrics the app shows for your own
data. It is deliberately tiny and defensive — a blank/misconfigured URL or an
unreachable server yields an empty frame, never an exception, so the dashboard
degrades to an "offline / not configured" state instead of breaking the app.

The read API itself (the `/shots` endpoint and the public pool it serves) lives
OUTSIDE this repo — it must be built and deployed separately on the OpenGolfLab
Worker. See docs/COMMUNITY_API.md for the exact request/response contract this
client expects.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

log = logging.getLogger(__name__)

# The read API returns shots keyed by the OpenGolfLab schema field names; the
# app's charts read their own canonical column names (see data/columns.py). This
# maps one to the other so a fetched community frame plots exactly like the
# user's own data with no special-casing in the chart code.
_FIELD_TO_COLUMN = {
    "club": "club",
    "ball_speed": "ballspeed",
    "club_speed": "clubspeed",
    "launch_angle": "vla",
    "back_spin": "backspin",
    "carry": "carry",
    "total": "totaldistance",
    "offline": "offline",
    "smash": "smashfactor",
    "apex": "peakheight",
}


def is_configured(url: str | None) -> bool:
    return bool(url) and str(url).startswith("https://")


def fetch_community_shots(url: str | None, club: str | None = None,
                          limit: int = 2000, timeout: int = 20,
                          app_version: str = "") -> pd.DataFrame:
    """Fetch community shots as a DataFrame with the app's own column names.

    Returns an empty DataFrame when ``url`` isn't configured or on any network/
    parse error (all logged) — callers render an offline/empty state from that.
    ``club`` optionally narrows the request to one club server-side.
    """
    if not is_configured(url):
        return pd.DataFrame()

    params = {"limit": str(limit)}
    if club:
        params["club"] = club
    endpoint = url.rstrip("/") + "/shots?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            # A real user-agent — Cloudflare's bot filter blocks the default
            # "Python-urllib/x" signature (same reason as contribute.send_bundle).
            "User-Agent": f"GolfSimAnalytics/{app_version or '1.0'} (+https://opengolflab.com)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        log.info("Community fetch failed (%s) — showing empty state", exc)
        return pd.DataFrame()

    shots = payload.get("shots") if isinstance(payload, dict) else payload
    if not isinstance(shots, list) or not shots:
        return pd.DataFrame()

    df = pd.DataFrame(shots)
    df = df.rename(columns={k: v for k, v in _FIELD_TO_COLUMN.items() if k in df.columns})
    # Coerce the metric columns the charts read to numeric; drop rows with no
    # club or carry (nothing to place on a dispersion plot).
    for col in ("ballspeed", "clubspeed", "vla", "backspin", "carry",
                "totaldistance", "offline", "smashfactor", "peakheight"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "club" in df.columns:
        df["club"] = df["club"].astype(str).str.strip()
    if "carry" in df.columns:
        df = df.dropna(subset=["carry"])
    return df.reset_index(drop=True)
