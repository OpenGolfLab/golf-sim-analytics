import pandas as pd

from data import on_course


def _round(distances, hole=1, session="live-1", round_type="on_course"):
    """Build a small on-course round from a list of start distance-to-pin
    values (one per shot, in play order)."""
    return pd.DataFrame({
        "session_id": session,
        "hole": hole,
        "distancetopin": distances,
        "round_type": round_type,
        "club": ["Dr"] * len(distances),
    })


def test_practice_view_excludes_on_course_when_asked():
    df = pd.concat([
        _round([392, 74, 8], round_type="practice"),
        _round([410, 150, 12], round_type="on_course"),
    ], ignore_index=True)
    out = on_course.practice_view(df, exclude_on_course=True)
    assert (out["round_type"] == "practice").all()
    assert len(out) == 3


def test_practice_view_keeps_on_course_when_not_excluding():
    df = _round([410, 150, 12], round_type="on_course")
    assert len(on_course.practice_view(df, exclude_on_course=False)) == 3


def test_practice_view_noop_without_round_type_column():
    df = pd.DataFrame({"club": ["Dr"], "carry": [250]})
    pd.testing.assert_frame_equal(on_course.practice_view(df), df)


def test_on_course_view_selects_only_course_rounds():
    df = pd.concat([
        _round([392, 74], round_type="practice"),
        _round([410, 150], round_type="on_course"),
    ], ignore_index=True)
    out = on_course.on_course_view(df)
    assert len(out) == 2
    assert (out["round_type"] == "on_course").all()


def test_flag_mulligans_marks_the_re_hit_shot():
    # Tee shot from 410, a mulligan re-teed from ~the same spot (409), then a
    # good drive that advances to 150, then an approach to 8. The first shot
    # (410, immediately followed by 409) is the mulligan.
    df = _round([410, 409, 150, 8])
    flags = on_course.flag_mulligans(df)
    assert list(flags) == [True, False, False, False]


def test_drop_mulligans_removes_only_the_re_hit():
    df = _round([410, 409, 150, 8])
    out = on_course.drop_mulligans(df)
    assert list(out["distancetopin"]) == [409, 150, 8]


def test_multiple_consecutive_mulligans():
    df = _round([300, 301, 299, 120])  # three tries from ~300, then advance
    flags = on_course.flag_mulligans(df)
    assert list(flags) == [True, True, False, False]


def test_holed_out_shot_is_never_a_mulligan():
    # A short chip to 3 yds then a tap-in from 3: the last shot has no
    # successor on the hole, so it can't be flagged; the 3-yd chip advanced
    # from 30, so it isn't either.
    df = _round([30, 3])
    assert not on_course.flag_mulligans(df).any()


def test_mulligans_are_scoped_per_hole():
    # Same distance across a hole boundary must NOT count as a re-hit.
    df = pd.concat([
        _round([120], hole=1),
        _round([120], hole=2),
    ], ignore_index=True)
    assert not on_course.flag_mulligans(df).any()


def test_practice_shots_are_ignored_by_mulligan_detection():
    # Range balls hit repeatedly from the same mat (hole 0, constant distance)
    # must not be treated as mulligans.
    df = _round([250, 250, 250], hole=0, round_type="practice")
    assert not on_course.flag_mulligans(df).any()


def test_flag_mulligans_safe_without_required_columns():
    df = pd.DataFrame({"club": ["Dr", "7I"], "carry": [250, 170]})
    assert not on_course.flag_mulligans(df).any()


# --- scoring -----------------------------------------------------------------

def _hole(session, hole, par, distances, clubs=None):
    """A hole's worth of shots; final distance-to-pin 0 = holed out."""
    n = len(distances)
    return pd.DataFrame({
        "session_id": session, "hole": hole, "holepar": par,
        "distancetopin": distances, "round_type": "on_course",
        "club": clubs or (["Dr"] + ["7I"] * (n - 1)),
        "totaldistance": [280] + [150] * (n - 1),
        "session_date": pd.Timestamp("2026-07-01"),
    })


def test_bucket_for_classifies_scores():
    assert on_course.bucket_for(-3) == "Eagle+"
    assert on_course.bucket_for(-2) == "Eagle+"
    assert on_course.bucket_for(-1) == "Birdie"
    assert on_course.bucket_for(0) == "Par"
    assert on_course.bucket_for(1) == "Bogey"
    assert on_course.bucket_for(4) == "Double+"
    assert on_course.bucket_for(None) is None


def test_hole_summary_strokes_par_and_completion():
    df = pd.concat([
        _hole("r1", 1, 4, [410, 150, 20, 0]),      # 4 strokes, holed, par
        _hole("r1", 2, 3, [180, 60]),               # incomplete (min dtp 60)
    ], ignore_index=True)
    hs = on_course.hole_summary(df).set_index("hole")
    assert hs.loc[1, "strokes"] == 4 and hs.loc[1, "par"] == 4
    assert bool(hs.loc[1, "holed"]) is True and hs.loc[1, "to_par"] == 0
    assert bool(hs.loc[2, "holed"]) is False


def test_round_summary_excludes_incomplete_holes_and_counts_buckets():
    df = pd.concat([
        _hole("r1", 1, 4, [410, 150, 20, 0]),       # par
        _hole("r1", 2, 4, [400, 8, 0]),             # birdie (3 on a par 4)
        _hole("r1", 3, 4, [400, 200, 90, 30, 8, 0]),  # double+ (6 on a par 4)
        _hole("r1", 4, 3, [180, 40]),               # incomplete -> excluded
    ], ignore_index=True)
    rs = on_course.round_summary(df)
    assert len(rs) == 1
    row = rs.iloc[0]
    assert row["holes"] == 3                 # incomplete 4th hole dropped
    assert row["strokes"] == 4 + 3 + 6
    assert row["par"] == 12
    assert row["to_par"] == 1
    assert row["Par"] == 1 and row["Birdie"] == 1 and row["Double+"] == 1
    assert row["longest_drive"] == 280


def test_round_summary_orders_rounds_by_date():
    late = _hole("late", 1, 4, [400, 8, 0])
    late["session_date"] = pd.Timestamp("2026-07-05")
    early = _hole("early", 1, 4, [400, 150, 8, 0])
    early["session_date"] = pd.Timestamp("2026-07-01")
    rs = on_course.round_summary(pd.concat([late, early], ignore_index=True))
    assert list(rs["session_id"]) == ["early", "late"]


def test_round_summary_empty_without_on_course_rows():
    df = pd.DataFrame({"session_id": ["p"], "hole": [0], "holepar": [4],
                       "round_type": ["practice"], "distancetopin": [0]})
    assert on_course.round_summary(df).empty


# --- humanize_course ----------------------------------------------------------

def test_humanize_course_strips_gsp_suffix_and_underscores():
    assert on_course.humanize_course("paynes_valley_gsp") == "Paynes Valley"


def test_humanize_course_handles_missing_input():
    assert on_course.humanize_course(None) == "Unknown Course"
    assert on_course.humanize_course("") == "Unknown Course"


# --- finished / DNF detection --------------------------------------------------

def test_round_summary_finished_true_when_last_hole_holed_out():
    df = pd.concat([
        _hole("r1", 1, 4, [410, 150, 20, 0]),
        _hole("r1", 2, 3, [180, 60, 0]),  # last hole, holed
    ], ignore_index=True)
    row = on_course.round_summary(df).iloc[0]
    assert bool(row["finished"]) is True


def test_round_summary_finished_false_when_last_hole_abandoned():
    df = pd.concat([
        _hole("r1", 1, 4, [410, 150, 20, 0]),
        _hole("r1", 2, 3, [180, 60]),  # last hole, never holed -> DNF
    ], ignore_index=True)
    row = on_course.round_summary(df).iloc[0]
    assert bool(row["finished"]) is False
    # The completed hole still counts toward the score even though the round
    # as a whole didn't finish.
    assert row["holes"] == 1


def test_round_summary_short_but_complete_round_is_not_a_dnf():
    # Only 1 hole played, but it was holed out — a deliberate short session,
    # not an abandoned one.
    df = _hole("r1", 1, 4, [410, 150, 20, 0])
    row = on_course.round_summary(df).iloc[0]
    assert bool(row["finished"]) is True


# --- course attribution --------------------------------------------------------

def test_round_summary_attaches_course_name():
    df = _hole("r1", 1, 4, [410, 150, 20, 0])
    df["course"] = "cda_national_gsp"
    row = on_course.round_summary(df).iloc[0]
    assert row["course"] == "Cda National"


def test_round_summary_course_defaults_to_unknown_without_data():
    df = _hole("r1", 1, 4, [410, 150, 20, 0])
    row = on_course.round_summary(df).iloc[0]
    assert row["course"] == "Unknown Course"
