"""
Golf Sim Analytics — "is there a newer build?"

Asks GitHub for the latest published release and compares its tag to
config.APP_VERSION. That's the whole feature: it tells you, and then hands you
to the browser to download. It deliberately does NOT fetch or run an installer
itself — Windows can't cleanly replace a running exe, a packaged binary that
downloads and executes another binary is exactly the shape antivirus
heuristics flag, and doing it properly means owning signature verification.
The browser already solves all three.

GitHub Releases is the source of truth rather than a version file on the
website because publishing the release IS the update (see RELEASING.md): the
site's download button resolves to `releases/latest/download/...`, so the check
reads the same thing the download link follows. Nothing extra to remember at
release time, and no way for the two to disagree.

Network behaviour follows contribute.check_public_name: off the UI thread, a
short timeout, and any failure at all — offline, rate-limited, GitHub down,
garbage JSON — resolves to UNKNOWN rather than an error. A version check is
never why someone opened Settings, so it must never be something that can
fail at them.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

# What the check concluded. UNKNOWN is a first-class answer, not a failure —
# the UI says nothing rather than claiming you're up to date on no evidence.
CURRENT = "current"
UPDATE = "update"
UNKNOWN = "unknown"

# Unauthenticated GitHub API: 60 requests/hour/IP. One check per launch (see
# the cache below) is nowhere near it, but a check per Settings open would be
# on a machine left running for days.
RELEASES_API = "https://api.github.com/repos/OpenGolfLab/golf-sim-analytics/releases/latest"
_TIMEOUT = 6

_VERSION_RE = re.compile(r"^\D*(\d+(?:\.\d+)*)")


def parse_version(text) -> tuple[int, ...] | None:
    """Version string -> comparable tuple, or None if there's no version in it.

    Tolerant of what release tags actually look like: "v1.4.0", "1.4.0",
    "V1.4", "1.4.0-beta.2" (the pre-release suffix is ignored — see
    is_newer). Anything with no leading number at all is None.
    """
    m = _VERSION_RE.match(str(text or "").strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(latest, current) -> bool:
    """True when ``latest`` is a strictly higher version than ``current``.

    Pads the shorter tuple with zeros so "1.4" and "1.4.0" compare equal
    rather than by length. A version we can't parse on either side is never
    newer: an unreadable tag must not nag every user to "update" to it.

    Pre-release suffixes are dropped by parse_version, so v1.4.0-beta reads as
    1.4.0. That's the conservative direction here — releases are never marked
    pre-release (RELEASING.md), so a suffixed tag showing up at all is
    unexpected, and treating it as its base version at worst offers an update
    that exists.
    """
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def fetch_latest_tag(url: str = RELEASES_API, timeout: int = _TIMEOUT) -> str | None:
    """The newest published release's tag, or None if we couldn't find out.

    /releases/latest is the right endpoint rather than /releases[0]: GitHub
    excludes drafts and pre-releases from it, which matches what the website's
    download button follows.
    """
    try:
        import netutil
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "GolfSimAnalytics (+https://opengolflab.com)",
        })
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=netutil.ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        log.debug("Update check failed", exc_info=True)
        return None
    tag = (data or {}).get("tag_name") if isinstance(data, dict) else None
    return str(tag).strip() if tag else None


# Checked once per launch and remembered. Settings can be opened repeatedly;
# the answer can't meaningfully change while the app is running, and a request
# per open is what would eventually meet the rate limit.
_cache: tuple[str, str | None] | None = None
_lock = threading.Lock()


def check(current_version: str, *, url: str = RELEASES_API,
          timeout: int = _TIMEOUT, force: bool = False) -> tuple[str, str | None]:
    """(status, latest_tag) — blocking. Call it off the UI thread.

    status is CURRENT, UPDATE or UNKNOWN; latest_tag is whatever GitHub said,
    for display, or None when the check didn't get an answer.
    """
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
    tag = fetch_latest_tag(url, timeout)
    if tag is None:
        result = (UNKNOWN, None)
    elif is_newer(tag, current_version):
        result = (UPDATE, tag)
    else:
        result = (CURRENT, tag)
    with _lock:
        # An UNKNOWN isn't worth remembering — it usually means "offline right
        # now", and the next open is a free chance to get a real answer.
        if result[0] != UNKNOWN:
            _cache = result
    return result


def check_async(current_version: str, callback, **kwargs) -> threading.Thread:
    """Run check() on a daemon thread and hand (status, latest_tag) to
    ``callback``. The callback runs on that thread — a Tk caller must marshal
    back with widget.after(0, ...), the same as contribute's name check.
    """
    def _work():
        try:
            result = check(current_version, **kwargs)
        except Exception:  # noqa: BLE001
            log.debug("Update check raised", exc_info=True)
            result = (UNKNOWN, None)
        try:
            callback(result)
        except Exception:  # noqa: BLE001
            log.debug("Update-check callback raised", exc_info=True)

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    return t
