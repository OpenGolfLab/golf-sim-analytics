"""
Golf Sim Analytics — OpenGolfLab community read client.

The Contribute flow (contribute.py) writes anonymized shots to OpenGolfLab. This
is the read side: it fetches the community's published data back so the Community
dashboard can plot it alongside the metrics the app shows for your own data.

What's fetched is **aggregate, not raw**: one MEDIAN point per (contributor,
club) — each golfer's typical carry/offline/etc. for a club — never anyone's
individual shots. Raw points never leave OpenGolfLab's private data repo; only
these medians are published, as a static JSON file on the website
(community_points.json, built by the data repo's aggregate.py). So this client
just GETs a static file — no API, no query params, no auth.

Deliberately tiny and defensive: a blank/misconfigured URL or an unreachable
server yields an empty frame, never an exception, so the dashboard degrades to an
"offline / not configured" state instead of breaking the app. See
docs/COMMUNITY_API.md for the response shape.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

import pandas as pd

import netutil

log = logging.getLogger(__name__)

# The published file is named this; the config URL points at the directory that
# serves it (the website's public data), and the client appends the filename.
_POINTS_FILE = "community_points.json"

# Points are keyed by the OpenGolfLab schema field names; the app's charts read
# their own canonical column names (see data/columns.py). This maps one to the
# other so a fetched community frame plots exactly like the user's own data with
# no special-casing in the chart code. Each value is a per-contributor median.
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
    # How many shots stand behind this contributor's median for the club — the
    # chart shows it so a point reads as "N shots' worth", and the table counts
    # golfers vs shots correctly. Kept under its own name.
    "n": "n",
    # Descriptive per-shot metadata (all optional) that the Community hover card
    # shows so a point isn't just an anonymous dot — see docs/COMMUNITY_API.md.
    # These map to the same internal names the app's own ingest uses where one
    # exists (ball_model), and stay as-is otherwise. Non-numeric; preserved as
    # strings below rather than coerced.
    "ball_model": "ball_model",
    "launch_monitor": "launch_monitor",
    "contributed": "contributed",
    "display_name": "display_name",
}

# The descriptive columns above, once mapped. Kept as clean strings so the
# tooltip can render them and gracefully skip the ones a given pool omits.
_META_COLUMNS = ("ball_model", "launch_monitor", "contributed", "display_name")


def is_configured(url: str | None) -> bool:
    return bool(url) and str(url).startswith("https://")


def fetch_community_shots(url: str | None, timeout: int = 20,
                          app_version: str = "") -> pd.DataFrame:
    """Fetch the community median points as a DataFrame with the app's own column
    names.

    ``url`` is the directory that serves community_points.json (the website's
    public data); the filename is appended here. Returns an empty DataFrame when
    ``url`` isn't configured or on any network/parse error (all logged) — callers
    render an offline/empty state from that. No club/limit narrowing: the file is
    small (one point per golfer per club) and the chart filters locally.
    """
    if not is_configured(url):
        return pd.DataFrame()

    endpoint = url.rstrip("/") + "/" + _POINTS_FILE

    req = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            # A real user-agent — Cloudflare's bot filter blocks the default
            # "Python-urllib/x" signature (same reason as contribute.send_bundle).
            "User-Agent": f"GolfSimAnalytics/{app_version or '1.0'} (+https://opengolflab.com)",
        },
    )
    log.info("Community fetch: GET %s", endpoint)
    try:
        # ssl_context() verifies against a bundled CA file rather than the OS
        # store — the OS-store load hangs in a frozen build (see netutil).
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=netutil.ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        log.info("Community fetch failed (%s) — showing empty state", exc)
        return pd.DataFrame()

    as_of = payload.get("as_of") if isinstance(payload, dict) else None
    # "points" is the current key; tolerate "shots" and a bare list for
    # robustness against an older/hand-made file.
    points = None
    if isinstance(payload, dict):
        points = payload.get("points")
        if points is None:
            points = payload.get("shots")
    elif isinstance(payload, list):
        points = payload
    if not isinstance(points, list) or not points:
        return pd.DataFrame()

    df = pd.DataFrame(points)
    df = df.rename(columns={k: v for k, v in _FIELD_TO_COLUMN.items() if k in df.columns})
    # Coerce the metric columns the charts read to numeric; drop rows with no
    # club or carry (nothing to place on a dispersion plot).
    for col in ("ballspeed", "clubspeed", "vla", "backspin", "carry",
                "totaldistance", "offline", "smashfactor", "peakheight", "n"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "club" in df.columns:
        df["club"] = df["club"].astype(str).str.strip()
    # Descriptive metadata: strip to clean plain-`object` strings, normalizing
    # every "absent" spelling to "". The sources of "absent" are: a missing key
    # (NaN), a JSON null (None/NA), and the literal strings "None"/"nan"/"null".
    # fillna("") handles the first two — needed because pandas' StringDtype
    # carries real NA *through* astype(str), so string-matching alone misses it —
    # and the isin mask handles the literals. Result is a uniform "" so the
    # tooltip's presence check is a plain truthiness test.
    for col in _META_COLUMNS:
        if col in df.columns:
            s = df[col].fillna("").astype("object").astype(str).str.strip()
            df[col] = s.mask(s.str.lower().isin(("nan", "none", "null")), "")
    if "carry" in df.columns:
        df = df.dropna(subset=["carry"])
    df = df.reset_index(drop=True)
    # The pool's build time, for the dashboard's "as of <date>" line. Set last so
    # the frame transformations above can't drop it; stashed on .attrs so the
    # return type stays a plain DataFrame (callers/tests wanting only the shots
    # are unaffected).
    if as_of:
        df.attrs["as_of"] = as_of
    log.info("Community fetch: %d points loaded (as_of %s)", len(df), as_of)
    return df
