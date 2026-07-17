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
    payload = {
        "count": 2, "as_of": "2026-07-16T00:00:00Z",
        "shots": [
            {"club": "7I", "ball_speed": 115.4, "launch_angle": 18.7,
             "back_spin": 6280, "carry": 153.2, "total": 162.0, "offline": 1.1},
            {"club": "Dr", "ball_speed": 168.0, "launch_angle": 13.0,
             "back_spin": 2600, "carry": 265.0, "total": 285.0, "offline": -3.0},
        ],
    }

    class _Resp:
        def read(self): return json.dumps(payload).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False

    with mock.patch("urllib.request.urlopen", return_value=_Resp()):
        df = community.fetch_community_shots("https://api.example.com")

    # Schema names mapped to the app's canonical column names.
    assert list(df["club"]) == ["7I", "Dr"]
    assert "ballspeed" in df.columns and "vla" in df.columns
    assert "backspin" in df.columns and "totaldistance" in df.columns
    assert df["carry"].tolist() == [153.2, 265.0]


def test_network_error_returns_empty_frame():
    import urllib.error
    with mock.patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("boom")):
        df = community.fetch_community_shots("https://api.example.com")
    assert df.empty
