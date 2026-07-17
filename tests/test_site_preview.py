"""The app's site-preview port must agree with opengolflab-data/aggregate.py.

This suite owns the app half of that contract; test_aggregate.py in the data repo
owns the other half. Both run the SAME fixture and assert the SAME answer, so a
threshold or rule changed on one side without the other turns red instead of
turning into a receipt that quietly disagrees with the website.

See tests/fixtures/site_preview/README.md (and its twin in opengolflab-data).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import site_preview

FIXTURE = Path(__file__).parent / "fixtures" / "site_preview"
SIBLING_FIXTURE = (Path(__file__).resolve().parents[2]
                   / "opengolflab-data" / "fixtures" / "site_preview")


@pytest.fixture(scope="module")
def bundle():
    return (
        (FIXTURE / "shots.csv").read_text(encoding="utf-8"),
        json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8")),
    )


def test_preview_matches_expected_fixture(bundle):
    shots_csv, manifest = bundle
    expected = json.loads((FIXTURE / "expected_preview.json").read_text(encoding="utf-8"))
    assert site_preview.build_preview(shots_csv, manifest) == expected


def test_fixture_matches_sibling_repo():
    """The app's copy of the fixture and the data repo's must be identical —
    otherwise each repo happily passes against its own private idea of the
    answer and the whole cross-repo guarantee evaporates."""
    if not SIBLING_FIXTURE.exists():
        pytest.skip("opengolflab-data is not checked out alongside this repo")
    for name in ("shots.csv", "manifest.json", "expected_preview.json"):
        assert (FIXTURE / name).read_bytes() == (SIBLING_FIXTURE / name).read_bytes(), (
            f"{name} has drifted between the two repos — regenerate with "
            f"tools/regen_site_preview_fixture.py after deciding which is right"
        )


# --- the QC rules the fixture is built to exercise --------------------------
def test_drops_shots_failing_each_quality_rule(bundle):
    shots_csv, _ = bundle
    preview = site_preview.build_preview(shots_csv, json.loads("{}"))
    # One over the global ball_speed ceiling, one over the 7I carry envelope,
    # one over the smash bound.
    assert preview["shots"]["dropped_by_quality_checks"] == 3
    assert preview["shots"]["submitted"] == 28
    assert preview["shots"]["passed_quality_checks"] == 25


def test_global_range_rule():
    assert site_preview.valid_shot(_row(ball_speed=300)) is None
    assert site_preview.valid_shot(_row(ball_speed=118)) is not None


def test_per_club_envelope_rule():
    # 320 yds passes the global carry ceiling (400) but not a 7I's envelope.
    assert site_preview.valid_shot(_row(club="7I", carry=320)) is None
    # ...and the same carry is fine for a driver (club_speed kept realistic so
    # this exercises the envelope, not the smash bound).
    assert site_preview.valid_shot(
        _row(club="Dr", carry=320, ball_speed=170, club_speed=116)) is not None


def test_smash_bound_rule():
    assert site_preview.valid_shot(_row(ball_speed=118, club_speed=60)) is None   # 1.97
    assert site_preview.valid_shot(_row(ball_speed=118, club_speed=84)) is not None  # 1.40


def test_club_below_shot_floor_earns_no_summary_but_is_reported(bundle):
    shots_csv, manifest = bundle
    preview = site_preview.build_preview(shots_csv, manifest)
    # PW has 4 valid shots; the floor is 5.
    assert "PW" not in preview["clubs"]
    assert "PW" in preview["clubs_below_shot_floor"]
    # 5I has exactly the floor and does earn one.
    assert preview["clubs"]["5I"]["shots_used"] == site_preview.MIN_CLUB_SHOTS


def test_preview_reports_the_name_the_site_will_show(bundle):
    shots_csv, manifest = bundle
    preview = site_preview.build_preview(shots_csv, manifest)
    assert preview["generated_from"]["display_name"] == manifest["display_name"]


def _row(**over):
    row = {"club": "7I", "ball_speed": "118", "club_speed": "84",
           "launch_angle": "17.9", "back_spin": "6870", "carry": "157.8",
           "offline": "-1.6"}
    row.update({k: str(v) for k, v in over.items()})
    return row
