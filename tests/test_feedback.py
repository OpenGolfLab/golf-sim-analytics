"""Feedback client (feedback.py) — payload shape and failure wording.

The payload test doubles as the app's privacy statement for this feature:
exactly five keys leave the machine, none of them identifying, none of them
shot data.
"""
import pytest

import feedback


def test_payload_is_exactly_the_five_stated_fields():
    p = feedback.build_payload("bug", "  the thing broke  ",
                               contact=" me@example.com ", app_version="1.4.2")
    assert p == {
        "kind": "bug",
        "message": "the thing broke",
        "contact": "me@example.com",
        "source": "app",
        "app_version": "1.4.2",
    }


def test_unknown_kind_falls_back_to_idea():
    assert feedback.build_payload("elephant", "msg")["kind"] == "idea"


def test_message_and_contact_are_capped():
    p = feedback.build_payload("idea", "x" * 10_000, contact="y" * 1_000)
    assert len(p["message"]) == feedback.MESSAGE_MAX
    assert len(p["contact"]) == feedback.CONTACT_MAX


def test_send_requires_a_url_and_a_real_message():
    with pytest.raises(RuntimeError):
        feedback.send_feedback("", feedback.build_payload("bug", "long enough"))
    with pytest.raises(RuntimeError):
        feedback.send_feedback("https://example.com",
                               feedback.build_payload("bug", "hi"))


def test_send_posts_json_with_real_user_agent(monkeypatch):
    seen = {}

    class _Resp:
        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None, context=None):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["body"] = req.data
        seen["ua"] = req.get_header("User-agent")
        seen["context"] = context
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload = feedback.build_payload("idea", "make it better", app_version="9.9")
    feedback.send_feedback("https://example.com/api/feedback", payload)

    assert seen["url"] == "https://example.com/api/feedback"
    assert seen["method"] == "POST"
    assert b'"source": "app"' in seen["body"]
    # Cloudflare rejects urllib's default UA, and the frozen exe hangs without
    # the certifi SSL context — both are load-bearing, not niceties.
    assert seen["ua"].startswith("GolfSimAnalytics/9.9")
    assert seen["context"] is not None
