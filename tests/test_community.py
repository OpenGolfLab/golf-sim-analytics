"""Community read client: config gating, empty-on-error, and field mapping."""
import json
from unittest import mock

import community


def test_is_configured():
    assert not community.is_configured("")
    assert not community.is_configured(None)
    assert not community.is_configured("http://insecure.example")  # must be https
    assert community.is_configured("https://api.example.com")


def test_blank_url_returns_empty_frame_without_network():
    df = community.fetch_community_shots("")
    assert df.empty


def test_maps_schema_fields_to_app_columns():
    # The published points carry MEDIAN values under schema field names, plus
    # `n` (shots behind each median).
    df = _fetch({
        "count": 2, "as_of": "2026-07-16T00:00:00Z",
        "points": [
            {"club": "7I", "n": 41, "ball_speed": 115.4, "launch_angle": 18.7,
             "back_spin": 6280, "carry": 153.2, "offline": 1.1},
            {"club": "Dr", "n": 22, "ball_speed": 168.0, "launch_angle": 13.0,
             "back_spin": 2600, "carry": 265.0, "offline": -3.0},
        ],
    })
    assert list(df["club"]) == ["7I", "Dr"]
    assert "ballspeed" in df.columns and "vla" in df.columns
    assert "backspin" in df.columns
    assert df["carry"].tolist() == [153.2, 265.0]
    assert df["n"].tolist() == [41, 22]   # shot counts preserved


def test_fetches_the_static_points_file():
    captured = {}

    class _Resp:
        def read(self): return json.dumps({"points": []}).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _spy(req, *a, **k):
        captured["url"] = req.full_url
        return _Resp()

    with mock.patch("urllib.request.urlopen", side_effect=_spy):
        community.fetch_community_shots("https://opengolflab.com/data")
    # A plain static file — no /shots, no query string.
    assert captured["url"] == "https://opengolflab.com/data/community_points.json"


def test_tolerates_trailing_slash_on_url():
    class _Resp:
        def read(self): return json.dumps({"points": []}).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False
    captured = {}

    def _spy(req, *a, **k):
        captured["url"] = req.full_url
        return _Resp()

    with mock.patch("urllib.request.urlopen", side_effect=_spy):
        community.fetch_community_shots("https://opengolflab.com/data/")
    assert captured["url"] == "https://opengolflab.com/data/community_points.json"


def test_network_error_returns_empty_frame():
    import urllib.error
    with mock.patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("boom")):
        df = community.fetch_community_shots("https://api.example.com")
    assert df.empty


def _fetch(payload):
    class _Resp:
        def read(self): return json.dumps(payload).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False
    with mock.patch("urllib.request.urlopen", return_value=_Resp()):
        return community.fetch_community_shots("https://api.example.com")


def test_maps_descriptive_metadata_fields():
    df = _fetch({"points": [{
        "club": "7I", "carry": 153.2, "offline": 1.1,
        "ball_model": "Pro V1", "launch_monitor": "Trackman",
        "contributed": "2026-07-15", "display_name": "SteadyFade-3fa2",
    }]})
    row = df.iloc[0]
    assert row["ball_model"] == "Pro V1"
    assert row["launch_monitor"] == "Trackman"
    assert row["contributed"] == "2026-07-15"
    assert row["display_name"] == "SteadyFade-3fa2"


def test_absent_metadata_normalizes_to_empty_string():
    # A pool that carries the columns but leaves some null on a shot: the client
    # normalizes every "absent" spelling to "" so the tooltip's presence check
    # is a plain truthiness test.
    df = _fetch({"points": [
        {"club": "7I", "carry": 150.0, "offline": 0.0,
         "ball_model": None, "launch_monitor": "", "display_name": "nan"},
        {"club": "Dr", "carry": 265.0, "offline": -2.0,
         "ball_model": "Chrome Soft", "launch_monitor": "SkyTrak+"},
    ]})
    assert df.loc[0, "ball_model"] == ""
    assert df.loc[0, "launch_monitor"] == ""
    assert df.loc[0, "display_name"] == ""
    assert df.loc[1, "ball_model"] == "Chrome Soft"


def test_metadata_absent_entirely_still_parses():
    # The whole descriptive block is optional — a minimal pool must still work.
    df = _fetch({"points": [{"club": "7I", "carry": 150.0, "offline": 0.0}]})
    assert not df.empty
    assert "ball_model" not in df.columns


def test_as_of_is_carried_on_frame_attrs():
    # The pool's build time reaches the dashboard via df.attrs (so the return
    # type stays a plain DataFrame) — powers the "as of <date>" header.
    df = _fetch({"as_of": "2026-07-17T16:00:00Z",
                 "points": [{"club": "7I", "carry": 150.0, "offline": 0.0}]})
    assert df.attrs.get("as_of") == "2026-07-17T16:00:00Z"


def test_missing_as_of_leaves_no_attr():
    df = _fetch({"points": [{"club": "7I", "carry": 150.0, "offline": 0.0}]})
    assert "as_of" not in df.attrs


def test_tolerates_legacy_shots_key_and_bare_list():
    # Robustness: an older or hand-made file that used "shots", or a bare list,
    # still parses rather than showing empty.
    df = _fetch({"shots": [{"club": "7I", "carry": 150.0, "offline": 0.0}]})
    assert not df.empty and df.loc[0, "club"] == "7I"
    df2 = _fetch([{"club": "Dr", "carry": 265.0, "offline": 0.0}])
    assert not df2.empty and df2.loc[0, "club"] == "Dr"
