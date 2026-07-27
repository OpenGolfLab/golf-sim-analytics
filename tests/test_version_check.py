"""The update check: version comparison, and never failing at the user.

The comparison is pure and gets the bulk of the attention, because it's the
part that can be wrong in a way nobody notices — a check that quietly never
fires looks identical to being up to date, and one that fires on every launch
for a version that doesn't exist is worse than no check at all.

Nothing here touches the network: fetch_latest_tag is stubbed. The one thing
worth asserting about the real request is what it does when it fails, which is
exercised by making it fail.
"""
import pytest

import version_check


@pytest.fixture(autouse=True)
def clear_cache():
    """The once-per-launch cache is module state — reset it per test."""
    version_check._cache = None
    yield
    version_check._cache = None


# ------------------------------------------------------------- parsing tags
@pytest.mark.parametrize("text, expected", [
    ("v1.4.0", (1, 4, 0)),      # how the tags are actually written
    ("1.4.0", (1, 4, 0)),
    ("V1.4", (1, 4)),
    ("v2.0.0-beta.1", (2, 0, 0)),  # pre-release suffix dropped
    ("release-3.1.2", (3, 1, 2)),
    ("", None),
    (None, None),
    ("latest", None),           # no number at all
])
def test_parse_version(text, expected):
    assert version_check.parse_version(text) == expected


# ---------------------------------------------------------------- comparing
@pytest.mark.parametrize("latest, current", [
    ("v1.4.0", "1.3.0"),
    ("v1.3.1", "1.3.0"),
    ("v2.0.0", "1.99.99"),
    ("v1.4", "1.3.9"),
    ("v1.3.1", "1.3"),       # padded compare: 1.3.1 > 1.3.0
])
def test_a_higher_version_is_newer(latest, current):
    assert version_check.is_newer(latest, current)


@pytest.mark.parametrize("latest, current", [
    ("v1.3.0", "1.3.0"),   # same
    ("v1.3.0", "1.3"),     # zero-padded equal, not newer
    ("v1.3", "1.3.0"),
    ("v1.2.9", "1.3.0"),   # older
    ("v1.3.0", "2.0.0"),   # user is ahead (a dev build)
])
def test_same_or_older_is_not_newer(latest, current):
    assert not version_check.is_newer(latest, current)


@pytest.mark.parametrize("latest, current", [
    ("nightly", "1.3.0"),
    ("v1.4.0", "unreleased"),
    ("", "1.3.0"),
    (None, "1.3.0"),
])
def test_an_unparseable_version_is_never_newer(latest, current):
    """An unreadable tag must not nag every user to 'update' to it."""
    assert not version_check.is_newer(latest, current)


# ------------------------------------------------------------- check() flow
def test_check_reports_an_available_update(monkeypatch):
    monkeypatch.setattr(version_check, "fetch_latest_tag", lambda *a, **k: "v1.4.0")
    assert version_check.check("1.3.0") == (version_check.UPDATE, "v1.4.0")


def test_check_reports_up_to_date(monkeypatch):
    monkeypatch.setattr(version_check, "fetch_latest_tag", lambda *a, **k: "v1.3.0")
    assert version_check.check("1.3.0") == (version_check.CURRENT, "v1.3.0")


def test_a_failed_fetch_is_unknown_not_up_to_date(monkeypatch):
    """Offline, rate-limited or GitHub down must never be reported as 'you're
    on the latest' — that's a claim made on no evidence."""
    monkeypatch.setattr(version_check, "fetch_latest_tag", lambda *a, **k: None)

    status, tag = version_check.check("1.3.0")

    assert status == version_check.UNKNOWN
    assert tag is None


def test_the_answer_is_fetched_once_per_launch(monkeypatch):
    """Settings can be opened all day; the rate limit is 60/hour."""
    calls = []
    monkeypatch.setattr(version_check, "fetch_latest_tag",
                        lambda *a, **k: calls.append(1) or "v1.4.0")

    for _ in range(5):
        version_check.check("1.3.0")

    assert len(calls) == 1


def test_an_unknown_result_is_not_cached(monkeypatch):
    """A failure usually means 'offline right now' — the next open deserves a
    real chance at an answer, unlike a successful result."""
    answers = [None, "v1.4.0"]
    monkeypatch.setattr(version_check, "fetch_latest_tag",
                        lambda *a, **k: answers.pop(0))

    assert version_check.check("1.3.0")[0] == version_check.UNKNOWN
    assert version_check.check("1.3.0") == (version_check.UPDATE, "v1.4.0")


def test_force_refetches(monkeypatch):
    monkeypatch.setattr(version_check, "fetch_latest_tag", lambda *a, **k: "v1.4.0")
    version_check.check("1.3.0")
    calls = []
    monkeypatch.setattr(version_check, "fetch_latest_tag",
                        lambda *a, **k: calls.append(1) or "v1.5.0")

    assert version_check.check("1.3.0", force=True) == (version_check.UPDATE, "v1.5.0")
    assert len(calls) == 1


# ------------------------------------------------------------- the transport
def test_a_broken_response_does_not_raise(monkeypatch):
    """Anything at all from the network — a 403 rate-limit body, HTML from a
    captive portal, truncated JSON — resolves to None rather than an
    exception, because this runs on a thread nobody is watching."""
    import urllib.request

    class _Boom:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"<html>not json</html>"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Boom())
    assert version_check.fetch_latest_tag() is None


def test_a_network_error_does_not_raise(monkeypatch):
    import urllib.error
    import urllib.request

    def _fail(*_a, **_k):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", _fail)
    assert version_check.fetch_latest_tag() is None


def test_a_response_without_a_tag_is_none(monkeypatch):
    import json
    import urllib.request

    class _Empty:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"message": "Not Found"}).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Empty())
    assert version_check.fetch_latest_tag() is None


def test_check_async_delivers_the_result(monkeypatch):
    monkeypatch.setattr(version_check, "fetch_latest_tag", lambda *a, **k: "v1.4.0")
    got = []

    version_check.check_async("1.3.0", got.append).join(timeout=5)

    assert got == [(version_check.UPDATE, "v1.4.0")]


def test_check_async_survives_a_raising_callback(monkeypatch):
    """A callback that blows up (a destroyed widget, say) must not take the
    thread — or the app — down with it."""
    monkeypatch.setattr(version_check, "fetch_latest_tag", lambda *a, **k: "v1.4.0")

    def _boom(_result):
        raise RuntimeError("widget is gone")

    version_check.check_async("1.3.0", _boom).join(timeout=5)  # no exception escapes


def test_the_download_url_and_the_api_agree_on_the_repo():
    """The button and the check must follow the same repo, or the app can
    offer a version it then fails to download."""
    import config
    repo = "OpenGolfLab/golf-sim-analytics"
    assert repo in version_check.RELEASES_API
    assert repo in config.LATEST_DOWNLOAD_URL
    assert config.LATEST_DOWNLOAD_URL.startswith("https://")
