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


def test_exclude_putts_drops_only_putter_rows():
    df = pd.DataFrame({"club": ["Dr", "Putter", "7I", "Putter"]})
    out = on_course.exclude_putts(df)
    assert list(out["club"]) == ["Dr", "7I"]


def test_exclude_putts_noop_without_club_column():
    df = pd.DataFrame({"carry": [200.0, 150.0]})
    assert len(on_course.exclude_putts(df)) == 2


def test_exclude_putts_drops_penalty_stroke_records():
    # A water drop writes its own record (shot_result == 2) with ball data
    # cloned from the hazard ball — a scorecard stroke, not a swing. Left in,
    # it would double the hazard shot in every dispersion view.
    df = pd.DataFrame({
        "club": ["Dr", "Lw", "Lw", "Putter"],
        "shot_result": [0, 0, 2, 0],
    })
    out = on_course.exclude_putts(df)
    assert list(out["club"]) == ["Dr", "Lw"]
    assert (out["shot_result"] != 2).all()


def test_scorecard_counts_putts_as_strokes():
    # A par-4 played driver, wedge, then two putts = 4 strokes. The putts MUST
    # count (that's why exclude_putts is not applied to the scorecard's source).
    df = _hole("s", 0, 4, [280.0, 20.0, 3.0, 0.0],
               clubs=["Dr", "Pw", "Putter", "Putter"])
    holes = on_course.hole_summary(df)
    assert int(holes.loc[0, "strokes"]) == 4
    assert int(holes.loc[0, "to_par"]) == 0


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


def test_hole_summary_scores_by_holeshot_not_record_count():
    # Mulligans: GSPro keeps the superseded record and the re-hit repeats the
    # same HoleShot. Real case (2026-07-19 Highlands round, hole 18): 7 records
    # but stroke numbers 1,1,1,1,2,3,4 — three re-teed drives. GSPro scored 4;
    # counting records said 7.
    df = _hole("r1", 17, 5, [320, 281, 333, 260, 47, 2.2, 0])
    df["holeshot"] = [1, 1, 1, 1, 2, 3, 4]
    hs = on_course.hole_summary(df).set_index("hole")
    assert int(hs.loc[17, "strokes"]) == 4


def test_hole_summary_holeshot_rescues_undercounted_holes():
    # The reverse failure also exists in real archives: a file kept only the
    # final record of a hole (1 record, HoleShot 6) — record count says 1,
    # GSPro's stroke numbering says 6.
    df = _hole("r1", 0, 5, [0.0])
    df["holeshot"] = [6]
    hs = on_course.hole_summary(df).set_index("hole")
    assert int(hs.loc[0, "strokes"]) == 6


def test_hole_summary_falls_back_to_record_count_without_holeshot_values():
    # Rounds archived before the holeshot column existed load with NaN there
    # (or no column at all) and must keep the old records-per-hole behavior.
    with_nan = _hole("old", 1, 4, [410, 150, 20, 0])
    with_nan["holeshot"] = float("nan")
    hs = on_course.hole_summary(with_nan).set_index("hole")
    assert int(hs.loc[1, "strokes"]) == 4


def test_hole_summary_mixed_old_and_new_sessions():
    # One healed/new round with real stroke numbers alongside one legacy round
    # without them — each scores by its own rule in a single frame.
    new = _hole("new", 1, 4, [410, 150, 150, 20, 0])   # mulligan on stroke 2
    new["holeshot"] = [1, 2, 2, 3, 4]
    old = _hole("old", 1, 4, [400, 8, 0])
    old["holeshot"] = float("nan")
    hs = on_course.hole_summary(pd.concat([new, old], ignore_index=True))
    by_sid = hs.set_index("session_id")["strokes"]
    assert int(by_sid["new"]) == 4
    assert int(by_sid["old"]) == 3


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


def test_hole_summary_counts_gimme_hole_when_a_later_hole_follows():
    # A conceded putt: GSPro picks up the ball a few feet out, so the last
    # record on the hole is ~2 yds from the pin (never <= HOLED_OUT_YDS) and no
    # holing stroke at 0 is logged. Because a later hole was still played, the
    # hole must count as completed rather than being dropped as abandoned.
    df = pd.concat([
        _hole("r1", 1, 4, [410, 150, 20, 2.0]),   # conceded ~6 ft, no 0 record
        _hole("r1", 2, 4, [400, 8, 0]),            # next hole, holed out
    ], ignore_index=True)
    hs = on_course.hole_summary(df).set_index("hole")
    assert bool(hs.loc[1, "holed"]) is True
    # And it flows through to the round scorecard as a real, scored hole.
    row = on_course.round_summary(df).iloc[0]
    assert row["holes"] == 2


def test_round_summary_still_drops_abandoned_final_hole():
    # The safety net only rescues holes with a successor; a truly abandoned
    # last hole (nothing played after it) is still excluded and marks the
    # round as a DNF.
    df = pd.concat([
        _hole("r1", 1, 4, [410, 150, 20, 0]),
        _hole("r1", 2, 4, [400, 72]),   # last hole, abandoned mid-play
    ], ignore_index=True)
    row = on_course.round_summary(df).iloc[0]
    assert row["holes"] == 1
    assert bool(row["finished"]) is False


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


# --- mulligans -----------------------------------------------------------------

def test_mulligan_flags_marks_every_attempt_but_the_last():
    # Real shape (2026-07-19 Highlands, hole 17): stroke 1 was played three
    # times. The last attempt is the one the following stroke continues from,
    # so the two before it are the mulligans.
    df = _hole("r1", 17, 5, [281, 333, 260, 47, 2.2, 0])
    df["holeshot"] = [1, 1, 1, 2, 3, 4]
    flags = on_course.mulligan_flags(df)
    assert list(flags) == [True, True, False, False, False, False]


def test_mulligan_flags_ignores_practice_rows():
    df = _hole("r1", 0, 4, [392, 392, 392])
    df["round_type"] = "practice"
    df["holeshot"] = [1, 1, 1]
    assert not on_course.mulligan_flags(df).any()


def test_mulligan_flags_false_without_stroke_numbers():
    # No holeshot column means no signal at all — the honest answer is "none
    # detected", not a guess from record counts.
    df = _hole("old", 1, 4, [410, 150, 20, 0])
    assert not on_course.mulligan_flags(df).any()


def test_mulligan_flags_empty_frame():
    assert on_course.mulligan_flags(pd.DataFrame()).empty


def test_hole_and_round_summary_count_mulligans():
    df = _hole("r1", 1, 4, [410, 150, 150, 20, 0])
    df["holeshot"] = [1, 2, 2, 3, 4]
    assert int(on_course.hole_summary(df).loc[0, "mulligans"]) == 1
    assert int(on_course.round_summary(df).iloc[0]["mulligans"]) == 1


def test_round_summary_reports_zero_mulligans_for_a_clean_round():
    df = _hole("r1", 1, 4, [410, 150, 20, 0])
    df["holeshot"] = [1, 2, 3, 4]
    assert int(on_course.round_summary(df).iloc[0]["mulligans"]) == 0


def test_round_mulligan_count_includes_unscored_holes():
    # A mulligan on an abandoned last hole still means the round was played
    # with do-overs available, which is what the asterisk is about — even
    # though that hole never reaches the scorecard.
    df = pd.concat([
        _hole("r1", 1, 4, [410, 150, 20, 0]),
        _hole("r1", 2, 3, [180, 180, 60]),  # never holed out
    ], ignore_index=True)
    df["holeshot"] = [1, 2, 3, 4, 1, 1, 2]
    row = on_course.round_summary(df).iloc[0]
    assert row["holes"] == 1           # only the completed hole is scored
    assert int(row["mulligans"]) == 1  # but the mulligan is still counted
