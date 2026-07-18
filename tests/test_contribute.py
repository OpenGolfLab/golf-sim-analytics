"""Contribution bundling: round selection + putt exclusion.

Guards the "app sent the wrong / far more shots than I hit" fix — only the
sessions the user picks are bundled, and putter strokes never ship.
"""
import io
import zipfile

import pandas as pd

import contribute


def _df():
    return pd.DataFrame({
        "session_id": ["s1", "s1", "s1", "s2", "s2"],
        "club": ["Dr", "7I", "Putter", "Dr", "Sw"],
        "ballspeed": [170.0, 120.0, 20.0, 168.0, 60.0],
        "launch_angle": [12.0, 17.0, 4.0, 13.0, 30.0],
        "backspin": [2600.0, 6200.0, 3000.0, 2700.0, 7500.0],
        "carry": [270.0, 165.0, 10.0, 265.0, 60.0],
    })


def test_selecting_a_session_excludes_other_sessions(tmp_path):
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)

    manifest, out = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1, session_ids=["s2"])

    # Only s2's two shots — s1 (three shots) is excluded entirely.
    assert manifest["shot_count"] == 2
    assert set(out["club"]) == {"Dr", "Sw"}


def test_putts_are_never_contributed(tmp_path):
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)

    manifest, out = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1)  # whole history, no selection

    # The lone Putter row is dropped even without a session filter.
    assert "Putter" not in set(out["club"])
    assert manifest["shot_count"] == 4


def test_whole_history_default_still_includes_every_session(tmp_path):
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)

    manifest, _out = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1)

    # 5 rows minus the 1 putt = 4 across both sessions.
    assert manifest["shot_count"] == 4


# --------------------------------------------------------------- display name
def test_display_name_validation():
    ok = contribute.normalize_display_name
    assert ok("Big Rig") == "Big Rig"
    assert ok("  Big   Rig  ") == "Big Rig"      # trimmed + collapsed
    assert ok("SteadyFade-3fa2") == "SteadyFade-3fa2"
    assert ok("ab") is None                       # under min
    assert ok("x" * 25) is None                   # over max
    assert ok("bad!name") is None                 # illegal char
    assert ok("") is None
    assert ok(None) is None


def test_generated_name_is_deterministic_and_valid():
    u = "b3f1c2a4-7e9d-4c11-9a2b-000000000000"
    a = contribute.generated_display_name(u)
    b = contribute.generated_display_name(u)
    assert a == b, "same uuid must always give the same name (stable public identity)"
    assert contribute.normalize_display_name(a) == a, "generated names must be valid"
    assert contribute.generated_display_name("different") != a


def test_resolve_prefers_configured_then_falls_back(tmp_path):
    app_dir = str(tmp_path)
    name, generated = contribute.resolve_display_name(app_dir, "My Name")
    assert (name, generated) == ("My Name", False)
    # Blank or invalid -> a generated name, and the flag says so.
    name, generated = contribute.resolve_display_name(app_dir, "")
    assert generated is True and contribute.normalize_display_name(name) == name
    name2, _ = contribute.resolve_display_name(app_dir, "!!")
    assert name2 == name, "fallback is stable for one contributor"


def test_manifest_always_carries_a_name(tmp_path):
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)
    # Even with no configured name, the bundle is never nameless.
    manifest, _ = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1, display_name="")
    assert contribute.normalize_display_name(manifest["display_name"]) is not None

    manifest2, _ = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1, display_name="Chosen Name")
    assert manifest2["display_name"] == "Chosen Name"


def test_schema_version_is_1_5():
    assert contribute.SCHEMA_VERSION == "1.5"


# ------------------------------------------------------------------- receipt
def test_receipt_zip_is_byte_identical_to_what_prepare_built(tmp_path):
    """write_receipt_zip must serialize the SAME bytes the send path does — the
    receipt is only a receipt if it's the actual payload, not a re-derivation."""
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)
    manifest, out = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1, display_name="Rec Eipt")
    shots_csv = contribute._shots_csv(out)

    path = contribute.write_receipt_zip(manifest, shots_csv, str(tmp_path))
    with zipfile.ZipFile(path) as z:
        assert z.read("shots.csv").decode("utf-8") == shots_csv
        got_manifest = z.read("manifest.json").decode("utf-8")
    assert got_manifest == contribute._manifest_bytes(manifest)


# ---------------------------------------------------------- v1.4: age + gear
def test_normalize_equipment_keeps_valid_drops_invalid():
    import contribute
    out = contribute.normalize_equipment({
        "driver": {"brand": "TaylorMade", "model": "Qi10 Max"},
        "irons": {"brand": "NotABrand", "model": "P790"},   # brand dropped
        "wedges": {"brand": "Cleveland", "model": "<xss>"},  # model dropped
        "putter": {"brand": "PING", "model": "Anser"},       # unknown slot
    })
    assert out["driver"] == {"brand": "TaylorMade", "model": "Qi10 Max"}
    assert out["irons"] == {"brand": "", "model": "P790"}
    assert out["wedges"] == {"brand": "Cleveland", "model": ""}
    assert "putter" not in out
    assert contribute.normalize_equipment(None) == {}
    assert contribute.normalize_equipment({"driver": {"brand": "", "model": ""}}) == {}


def test_manifest_v14_carries_age_and_equipment(tmp_path):
    import contribute
    contribute.record_consent(str(tmp_path), True)
    manifest, _ = contribute._prepare(
        _df(), app_dir=str(tmp_path), handicap_band="10-14",
        launch_monitor="", app_version="t", round_dp=1,
        age_band="40-49",
        equipment={"driver": {"brand": "PING", "model": "G430"}})
    assert manifest["schema_version"] == "1.5"
    assert manifest["self_report"]["age_band"] == "40-49"
    assert manifest["equipment"] == {"driver": {"brand": "PING", "model": "G430"}}


def test_manifest_v14_defaults_omit_gear_and_use_unknown_age(tmp_path):
    import contribute
    contribute.record_consent(str(tmp_path), True)
    manifest, _ = contribute._prepare(
        _df(), app_dir=str(tmp_path), handicap_band="unknown",
        launch_monitor="", app_version="t", round_dp=1)
    assert manifest["self_report"]["age_band"] == "unknown"
    assert "equipment" not in manifest


def test_invalid_age_band_normalizes_to_unknown(tmp_path):
    import contribute
    contribute.record_consent(str(tmp_path), True)
    manifest, _ = contribute._prepare(
        _df(), app_dir=str(tmp_path), handicap_band="unknown",
        launch_monitor="", app_version="t", round_dp=1, age_band="43")
    assert manifest["self_report"]["age_band"] == "unknown"


# ------------------------------------------------------- v1.5: provenance
def test_manifest_carries_provenance_split(tmp_path):
    import pandas as pd
    contribute.record_consent(str(tmp_path), True)
    df = _df()
    # Half the shots from a live-tracked round, half imported.
    n = len(df)
    df = df.copy()
    df["session_id"] = ["live-07-17-26-10-00-00"] * (n // 2) + ["s-imported"] * (n - n // 2)
    manifest, out = contribute._prepare(
        df, app_dir=str(tmp_path), handicap_band="unknown",
        launch_monitor="", app_version="t", round_dp=1)
    assert manifest["schema_version"] == "1.5"
    prov = manifest["provenance"]
    assert prov["live_tracked"] + prov["imported"] == len(out)
    assert prov["live_tracked"] > 0 and prov["imported"] > 0


def test_provenance_defaults_to_imported_without_session_ids(tmp_path):
    contribute.record_consent(str(tmp_path), True)
    manifest, out = contribute._prepare(
        _df(), app_dir=str(tmp_path), handicap_band="unknown",
        launch_monitor="", app_version="t", round_dp=1)
    assert manifest["provenance"] == {"live_tracked": 0, "imported": len(out)}


# ---------------------------------------------------- public-name check
def _names_payload(payload):
    import json as _json
    from unittest import mock

    class _Resp:
        def read(self): return _json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    return mock.patch("urllib.request.urlopen", return_value=_Resp())


def test_check_public_name_predicts_the_suffix(tmp_path):
    mine = contribute.uuid_prefix(str(tmp_path))
    with _names_payload({"names": {"tom": ["zzzz"]}}):  # another golfer's claim
        name, collided = contribute.check_public_name(str(tmp_path), "Tom", "https://x.example")
    assert collided and name == f"Tom-{mine}"


def test_check_public_name_own_claim_is_not_a_collision(tmp_path):
    mine = contribute.uuid_prefix(str(tmp_path))
    with _names_payload({"names": {"tom": [mine]}}):    # that's us
        name, collided = contribute.check_public_name(str(tmp_path), "Tom", "https://x.example")
    assert not collided and name == "Tom"


def test_check_public_name_survives_network_failure(tmp_path):
    from unittest import mock
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        name, collided = contribute.check_public_name(str(tmp_path), "Tom", "https://x.example")
    assert not collided and name == "Tom"
    # Unconfigured URL: no network attempted at all.
    name, collided = contribute.check_public_name(str(tmp_path), "Tom", "")
    assert not collided and name == "Tom"
