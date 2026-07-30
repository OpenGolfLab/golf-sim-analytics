"""Client for the OpenGolfLab feedback inbox (the website's /api/feedback).

Kept UI-free, like contribute.py and community.py, so the payload and the
send can be unit tested without a Tk event loop. The dialog half lives in
ui/feedback_dialog.py.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 15

# The server stores anything longer only after truncating; trimming here too
# keeps what the user sees as "sent" identical to what actually lands.
MESSAGE_MAX = 4000
CONTACT_MAX = 200


def build_payload(kind: str, message: str, contact: str = "",
                  app_version: str = "") -> dict:
    """Exactly what leaves the machine, as a dict — separated from the send so
    tests (and anyone auditing the app's network behavior) can state it
    precisely: the words, the type, an optional contact, the app version.
    No identifiers, no shot data."""
    return {
        "kind": "bug" if kind == "bug" else "idea",
        "message": (message or "").strip()[:MESSAGE_MAX],
        "contact": (contact or "").strip()[:CONTACT_MAX],
        "source": "app",
        "app_version": (app_version or "").strip(),
    }


def send_feedback(url: str, payload: dict, timeout: int = DEFAULT_TIMEOUT) -> None:
    """POST the payload; raises RuntimeError with a sayable message on any
    failure (same contract as contribute.send_bundle)."""
    if not url:
        raise RuntimeError("No feedback endpoint is configured.")
    if len(payload.get("message", "")) < 3:
        raise RuntimeError("Say a little more — the message is the feedback.")

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Cloudflare blocks urllib's default signature (error 1010), and the
        # default OS-cert SSL context hangs in the frozen exe — hence the
        # explicit User-Agent and netutil.ssl_context(), matching contribute.py.
        "User-Agent": (f"GolfSimAnalytics/{payload.get('app_version') or '1.0'}"
                       " (+https://opengolflab.com)"),
    }
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        import netutil
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=netutil.ssl_context()) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"The server turned the feedback away ({e.code}). "
                           "Please try again in a minute.") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach OpenGolfLab: {e.reason}") from e
