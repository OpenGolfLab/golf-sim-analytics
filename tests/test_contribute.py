"""Contribution bundling: round selection + putt exclusion.

Guards the "app sent the wrong / far more shots than I hit" fix — only the
sessions the user picks are bundled, and putter strokes never ship.
"""
import io
import zipfile

import pandas as pd
import pytest

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


# ------------------------------------------------------------- declared ball
def test_normalize_ball_model_keeps_valid_drops_invalid():
    ok = contribute.normalize_ball_model
    assert ok("Pro V1") == "Pro V1"
    assert ok("  TP5x  ") == "TP5x"          # trimmed
    assert ok("Q-Star  Tour") == "Q-Star Tour"  # runs of whitespace collapsed
    assert ok("<script>") == ""              # charset
    assert ok("") == "" and ok(None) == ""


def test_declared_ball_fills_in_when_the_export_has_no_ball_column(tmp_path):
    contribute.record_consent(str(tmp_path), True)
    _manifest, out = contribute._prepare(
        _df(), app_dir=str(tmp_path), handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1, ball_model="Pro V1")
    assert set(out["ball_model"]) == {"Pro V1"}


def test_per_shot_ball_beats_the_declared_one(tmp_path):
    """The recorded ball is what was actually hit; the profile only fills gaps."""
    contribute.record_consent(str(tmp_path), True)
    df = _df()
    df["ball"] = ["Chrome Soft", "", None, "Chrome Soft", ""]

    _manifest, out = contribute._prepare(
        df, app_dir=str(tmp_path), handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1, ball_model="Pro V1")

    # The putt (row 3) is dropped; of the four contributed shots, the two that
    # named a ball keep it and the two blanks — including the NaN that becomes
    # the string "nan" — take the declared one.
    assert sorted(out["ball_model"]) == ["Chrome Soft", "Chrome Soft", "Pro V1", "Pro V1"]


def test_no_declared_ball_leaves_the_column_alone(tmp_path):
    contribute.record_consent(str(tmp_path), True)
    _manifest, out = contribute._prepare(
        _df(), app_dir=str(tmp_path), handicap_band="unknown", launch_monitor="",
        app_version="t", round_dp=1)
    assert "ball_model" not in out.columns


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


# ---------------------------------------------------------------------------
# summarize_bundle — the "this is what you sent" snapshot.
#
# The point of these is the integrity property: the summary must describe the
# bytes that were uploaded, not a parallel calculation over the source data.
# ---------------------------------------------------------------------------
_SNAP_CSV = (
    "club,ball_speed,club_speed,smash,launch_angle,back_spin,carry,total,offline,ball_model\n"
    "7I,118.0,88.0,1.34,19.0,6800,160.0,168.0,2.0,Pro V1\n"
    "7I,120.0,89.0,1.35,18.5,6600,170.0,176.0,-4.0,Pro V1\n"
    "Dr,165.0,113.0,1.46,12.0,2500,270.0,295.0,5.0,Pro V1\n"
    "Dr,168.0,114.0,1.47,11.5,2400,280.0,305.0,-9.0,Pro V1\n"
)


def _snap_manifest(**over):
    m = {
        "schema_version": "1.5",
        "display_name": "BriskApex-264d",
        "contributor_uuid": "abcd1234-5678-90ab-cdef-1234567890ab",
        "shot_count": 4,
        "self_report": {"handicap_band": "5-9", "age_band": "40-49"},
        "environment": {"instrument": {"maker": "Uneekor", "model": "EYE XO2"}},
        "provenance": {"live_tracked": 3, "imported": 1},
    }
    m.update(over)
    return m


def _identity(summary):
    return dict(summary["identity"])


def test_snapshot_medians_come_from_the_uploaded_csv():
    """Medians are read back out of the shots.csv text, so they describe what was
    actually posted. 7I carries of 160 and 170 must median to 165."""
    s = contribute.summarize_bundle(_snap_manifest(), _SNAP_CSV)
    by_club = {row["club"]: row for row in s["clubs"]}
    assert by_club["7I"]["medians"]["carry"] == 165.0
    assert by_club["Dr"]["medians"]["carry"] == 275.0
    assert by_club["7I"]["n"] == 2


def test_snapshot_surfaces_every_self_reported_field():
    """These are the fields that describe the user publicly, so all of them have
    to be on screen for the snapshot to be a real verification."""
    ident = _identity(contribute.summarize_bundle(_snap_manifest(), _SNAP_CSV))
    assert ident["Public name"] == "BriskApex-264d"
    assert ident["Handicap band"] == "5-9"
    assert ident["Age band"] == "40-49"
    assert ident["Launch monitor"] == "Uneekor EYE XO2"
    assert ident["Ball"] == "Pro V1"
    assert "3 live-tracked" in ident["Rounds"]


def test_snapshot_shows_equipment_only_when_given():
    without = _identity(contribute.summarize_bundle(_snap_manifest(), _SNAP_CSV))
    assert "Driver" not in without
    with_equip = _identity(contribute.summarize_bundle(
        _snap_manifest(equipment={"driver": {"brand": "Ping", "model": "G430 LST"}}),
        _SNAP_CSV))
    assert with_equip["Driver"] == "Ping G430 LST"


def test_snapshot_never_exposes_the_full_contributor_uuid():
    """The id is non-identifying but it's still the dedup key; the snapshot is a
    screenshot-and-share surface, so it shows a prefix only."""
    s = contribute.summarize_bundle(_snap_manifest(), _SNAP_CSV)
    full = _snap_manifest()["contributor_uuid"]
    assert full not in str(s["identity"])


def test_snapshot_clubs_are_in_bag_order():
    s = contribute.summarize_bundle(_snap_manifest(), _SNAP_CSV)
    assert [r["club"] for r in s["clubs"]] == ["Dr", "7I"]


def test_snapshot_handles_a_bundle_with_no_optional_columns():
    """A minimal bundle (only the REQUIRED fields) must still summarize."""
    csv = ("club,ball_speed,launch_angle,back_spin,carry\n"
           "Pw,95.0,28.0,9000,110.0\n")
    s = contribute.summarize_bundle(_snap_manifest(shot_count=1), csv)
    fields = [f for f, _l, _u in s["fields"]]
    assert "carry" in fields and "club_speed" not in fields
    assert s["clubs"][0]["medians"]["carry"] == 110.0
    assert contribute.summary_text(s)  # must not raise


def test_snapshot_text_renders_all_clubs_and_the_name():
    text = contribute.summary_text(
        contribute.summarize_bundle(_snap_manifest(), _SNAP_CSV))
    assert "BriskApex-264d" in text
    for club in ("Dr", "7I"):
        assert club in text


def test_snapshot_reflects_a_sent_payload_end_to_end(tmp_path):
    """The real guarantee: build a bundle the way the app does, then summarize
    the manifest+csv pair that came back — the snapshot must agree with what was
    prepared for upload, not with the input frame.

    _df() carries a Putter row, which _prepare strips (putts are on-course
    scoring artifacts with launch data cloned from the preceding shot). So the
    input has 5 rows and the bundle has 4, and a snapshot that re-derived from
    the DataFrame instead of the CSV would report the wrong number here — which
    is exactly the drift this design exists to prevent."""
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)
    df = _df()
    assert len(df) == 5
    manifest, out = contribute._prepare(
        df, app_dir=app_dir, handicap_band="5-9", launch_monitor="Uneekor EYE XO2",
        app_version="test", round_dp=1)
    s = contribute.summarize_bundle(manifest, contribute._shots_csv(out))
    assert s["shot_count"] == manifest["shot_count"] == 4
    assert sum(row["n"] for row in s["clubs"]) == 4
    assert "Putter" not in {row["club"] for row in s["clubs"]}


# ---------------------------------------------------------------------------
# On-course rounds are never contributable.
# ---------------------------------------------------------------------------
def _mixed_round_type_df():
    return pd.DataFrame({
        "session_id": ["live-1-practice", "live-1-practice",
                       "live-2-on_course", "live-2-on_course"],
        "round_type": ["practice", "practice", "on_course", "on_course"],
        "club": ["Dr", "7I", "Dr", "7I"],
        "ballspeed": [170.0, 120.0, 168.0, 118.0],
        "launch_angle": [12.0, 17.0, 13.0, 18.0],
        "backspin": [2600.0, 6200.0, 2700.0, 6300.0],
        "carry": [270.0, 165.0, 265.0, 160.0],
    })


def test_on_course_rounds_are_stripped_from_a_bundle(tmp_path):
    """A per-club median over on-course shots doesn't describe how far someone
    hits a club — it's chips, punch-outs, layups and recoveries — so it must
    never reach the community set, whatever the caller asks for."""
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)
    manifest, out = contribute._prepare(
        _mixed_round_type_df(), app_dir=app_dir, handicap_band="5-9",
        launch_monitor="Uneekor EYE XO2", app_version="test", round_dp=1)
    assert manifest["shot_count"] == 2
    assert manifest["provenance"]["live_tracked"] == 2


def test_selecting_only_an_on_course_round_is_refused(tmp_path):
    """Belt and braces: the picker doesn't offer them, but if a caller passes
    on-course session ids anyway it must fail loudly rather than send them."""
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)
    with pytest.raises(ValueError, match="practice"):
        contribute._prepare(
            _mixed_round_type_df(), app_dir=app_dir, handicap_band="5-9",
            launch_monitor="Uneekor EYE XO2", app_version="test", round_dp=1,
            session_ids=["live-2-on_course"])


def test_frames_without_round_type_are_unaffected(tmp_path):
    """CSV-imported history predates round_type; those sessions must still be
    contributable exactly as before."""
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)
    manifest, _out = contribute._prepare(
        _df(), app_dir=app_dir, handicap_band="5-9",
        launch_monitor="Uneekor EYE XO2", app_version="test", round_dp=1)
    assert manifest["shot_count"] == 4  # 5 rows less the Putter
