"""The locked contributor id, and the persisted contributor profile.

Two guarantees the community pool depends on:

  * one golfer keeps one id forever, so repeat contributions update that
    golfer's row instead of adding another equally-weighted "golfer" to the
    aggregate;
  * the profile a golfer fills in (handicap, launch monitor, age, bag, ball)
    survives to the next contribution, so it isn't silently re-published as
    "unknown" every other time.
"""
import os
import uuid

import pytest

import config
import contribute
from data import settings


def _mirror() -> str:
    """The per-user mirror path, redirected to a tmp dir by conftest."""
    return contribute._user_id_path()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ------------------------------------------------------------------ the lock
def test_first_run_mints_one_id_and_keeps_it(tmp_path):
    app_dir = str(tmp_path)
    first = contribute.get_contributor_uuid(app_dir)
    assert contribute._is_valid_id(first)
    # Every subsequent call — and every subsequent contribution — is the same id.
    assert [contribute.get_contributor_uuid(app_dir) for _ in range(3)] == [first] * 3


def test_an_existing_id_is_never_regenerated(tmp_path):
    app_dir = str(tmp_path)
    existing = str(uuid.uuid4())
    _write(os.path.join(app_dir, contribute._ID_FILENAME), existing + "\n")

    assert contribute.get_contributor_uuid(app_dir) == existing


def test_a_wiped_app_folder_recovers_the_id_from_the_user_mirror(tmp_path):
    """A reinstall — new app folder, same machine — must not mint a new id."""
    original = contribute.get_contributor_uuid(str(tmp_path / "install_one"))

    reinstalled = contribute.get_contributor_uuid(str(tmp_path / "install_two"))

    assert reinstalled == original


def test_the_mirror_is_seeded_from_a_pre_existing_app_folder_id(tmp_path):
    """Upgrading an install that predates the mirror keeps its original id and
    back-fills the mirror with it — never the other way round."""
    app_dir = str(tmp_path)
    existing = str(uuid.uuid4())
    _write(os.path.join(app_dir, contribute._ID_FILENAME), existing)

    assert contribute.get_contributor_uuid(app_dir) == existing
    assert contribute._read_id(_mirror()) == existing


@pytest.mark.parametrize("junk", ["", "   ", "not-a-uuid", "\x00\x00"])
def test_a_corrupt_id_file_is_repaired_from_the_mirror(tmp_path, junk):
    """The old code returned the file's contents verbatim, so a truncated or
    hand-edited file put an empty/garbage contributor_uuid on the wire — which
    would merge every broken install into one server-side contributor."""
    seeded = contribute.get_contributor_uuid(str(tmp_path / "first"))

    app_dir = str(tmp_path / "second")
    _write(os.path.join(app_dir, contribute._ID_FILENAME), junk)

    assert contribute.get_contributor_uuid(app_dir) == seeded


def test_a_corrupt_id_with_no_mirror_mints_a_valid_one(tmp_path, monkeypatch):
    monkeypatch.setattr(contribute, "_user_id_path", lambda: None)
    app_dir = str(tmp_path)
    _write(os.path.join(app_dir, contribute._ID_FILENAME), "garbage")

    resolved = contribute.get_contributor_uuid(app_dir)

    assert contribute._is_valid_id(resolved)
    assert contribute._read_id(os.path.join(app_dir, contribute._ID_FILENAME)) == resolved


def test_an_install_never_overwrites_another_installs_mirror(tmp_path):
    """Two installs sharing a machine each keep their own id rather than
    fighting over the mirror — write-once means write-once."""
    app_dir = str(tmp_path / "portable")
    mine = str(uuid.uuid4())
    _write(os.path.join(app_dir, contribute._ID_FILENAME), mine)
    theirs = str(uuid.uuid4())
    _write(_mirror(), theirs)

    assert contribute.get_contributor_uuid(app_dir) == mine   # app folder wins
    assert contribute._read_id(_mirror()) == theirs           # left alone


def test_an_unwritable_location_still_resolves_a_stable_id(tmp_path, monkeypatch):
    """A full disk or a read-only install folder must not stop a contribution,
    and must not change the id."""
    seeded = contribute.get_contributor_uuid(str(tmp_path / "first"))
    monkeypatch.setattr(contribute, "_write_id", lambda *_a, **_k: False)

    assert contribute.get_contributor_uuid(str(tmp_path / "unwritable")) == seeded


def test_the_id_is_not_a_user_editable_setting():
    """It must never travel in settings.json, which the app rewrites wholesale
    and the user edits by hand."""
    assert not [k for k in settings.DEFAULTS if "uuid" in k or "contributor" in k]


def test_the_generated_name_follows_the_locked_id(tmp_path):
    app_dir = str(tmp_path)
    locked = contribute.get_contributor_uuid(app_dir)

    name, was_generated = contribute.resolve_display_name(app_dir, "")

    assert was_generated
    assert name == contribute.generated_display_name(locked)
    assert contribute.uuid_prefix(app_dir) == locked.replace("-", "")[:4]


def test_a_renamed_contributor_keeps_the_same_id(tmp_path):
    """Contribute as whoever you want — the identity underneath doesn't move."""
    app_dir = str(tmp_path)
    contribute.record_consent(app_dir, True)
    locked = contribute.get_contributor_uuid(app_dir)

    import pandas as pd
    df = pd.DataFrame({"club": ["Dr"], "ballspeed": [170.0], "launch_angle": [12.0],
                       "backspin": [2600.0], "carry": [270.0]})
    first, _ = contribute._prepare(df, app_dir=app_dir, handicap_band="unknown",
                                   launch_monitor="", app_version="t", round_dp=1,
                                   display_name="Big Rig")
    second, _ = contribute._prepare(df, app_dir=app_dir, handicap_band="unknown",
                                    launch_monitor="", app_version="t", round_dp=1,
                                    display_name="Someone Else")

    assert first["display_name"] != second["display_name"]
    assert first["contributor_uuid"] == second["contributor_uuid"] == locked


# ------------------------------------------------------------- profile memory
@pytest.fixture
def settings_dir(tmp_path, monkeypatch):
    """Point settings.json at a tmp dir — never the developer's real one."""
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    return tmp_path


def test_profile_fields_survive_a_restart(settings_dir):
    """Fill them in once: handicap, monitor, age, bag and ball all come back."""
    profile = {
        "handicap_band": "10-14",
        "launch_monitor": "SkyTrak+",
        "age_band": "40-49",
        "ball_model": "Pro V1",
        "equipment": {"driver": {"brand": "PING", "model": "G430 Max"}},
        "display_name": "Big Rig",
    }
    for key, value in profile.items():
        settings.set(key, value)

    reloaded = settings.load()  # a fresh read, as the next launch would do

    for key, value in profile.items():
        assert reloaded[key] == value


def test_profile_defaults_are_the_undeclared_values(settings_dir):
    fresh = settings.load()
    assert fresh["handicap_band"] == "unknown"
    assert fresh["launch_monitor"] == ""
    assert fresh["ball_model"] == ""


def test_saved_profile_values_are_valid_for_the_wire(settings_dir):
    """What's persisted has to be something the bundle will actually accept —
    the dropdowns are populated from these same allowlists."""
    settings.set("handicap_band", "5-9")
    settings.set("launch_monitor", "Trackman")
    settings.set("ball_model", "TP5x")
    saved = settings.load()

    assert saved["handicap_band"] in contribute.HANDICAP_BANDS
    assert saved["launch_monitor"] in contribute.LAUNCH_MONITORS
    assert contribute.normalize_ball_model(saved["ball_model"]) == "TP5x"
