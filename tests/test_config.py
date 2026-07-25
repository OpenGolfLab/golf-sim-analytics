from config import get_club_rank, get_fitting_window, normalize_club_name, resolve_club_index


def test_get_club_rank_orders_driver_before_wedges():
    assert get_club_rank("Dr") < get_club_rank("Sw")


def test_get_club_rank_unknown_club_sorts_last():
    assert get_club_rank("Putter") == 99


def test_club_index_26_resolves_to_putter_not_lob_wedge():
    # ClubIndex 26 is the putter (its ball data is copied from the prior shot),
    # not a lob wedge — 25 is the real lob wedge.
    assert resolve_club_index(26) == "Putter"
    assert resolve_club_index(25) == "Lw"


def test_putter_is_non_swing_but_not_a_canonical_club():
    import config
    assert "Putter" in config.NON_SWING_CLUBS
    assert "Putter" not in config.CANONICAL_CLUBS


def test_get_fitting_window_driver():
    launch, height, descent = get_fitting_window("DR")
    assert launch == (10, 14)


def test_get_fitting_window_matches_full_word_driver():
    launch, _, _ = get_fitting_window("DRIVER")
    assert launch == (10, 14)


def test_get_fitting_window_wedge():
    launch, _, _ = get_fitting_window("SW")
    assert launch == (28, 33)


def test_fitting_windows_progress_through_the_bag():
    # Launch climbs and landing angle steepens steadily from driver to lob
    # wedge, with no repeated values; peak height is one shared window.
    from config import CLUB_ORDER
    clubs = sorted(CLUB_ORDER, key=CLUB_ORDER.get)
    launches = [get_fitting_window(c)[0] for c in clubs]
    descents = [get_fitting_window(c)[2] for c in clubs]
    heights = {get_fitting_window(c)[1] for c in clubs}
    assert all(a[0] < b[0] and a[1] < b[1] for a, b in zip(launches, launches[1:]))
    assert all(a[0] < b[0] and a[1] < b[1] for a, b in zip(descents, descents[1:]))
    assert heights == {(90, 110)}


def test_get_fitting_window_unknown_club_returns_default():
    from config import DEFAULT_FITTING_WINDOW
    assert get_fitting_window("PUTTER") == DEFAULT_FITTING_WINDOW


# --- normalize_club_name: reconciling launch-monitor spelling variants ---

def test_normalize_iron_letter_prefix_format():
    # The launch monitor sends irons as "I9"/"I8" (letter-then-number)
    # instead of this app's "9I"/"8I" convention.
    assert normalize_club_name("I9") == "9I"
    assert normalize_club_name("I8") == "8I"
    assert normalize_club_name("i2") == "2I"


def test_normalize_iron_already_canonical_is_a_noop():
    assert normalize_club_name("9I") == "9I"
    assert normalize_club_name("7i") == "7I"


def test_normalize_iron_spelled_out_variants():
    assert normalize_club_name("9 Iron") == "9I"
    assert normalize_club_name("iron9") == "9I"
    assert normalize_club_name("9IRON") == "9I"


def test_normalize_wood_letter_prefix_format():
    assert normalize_club_name("W3") == "3W"
    assert normalize_club_name("3 Wood") == "3W"
    assert normalize_club_name("wood3") == "3W"


def test_normalize_driver_variants():
    assert normalize_club_name("Driver") == "Dr"
    assert normalize_club_name("DRIVER") == "Dr"
    assert normalize_club_name("DR") == "Dr"
    assert normalize_club_name("dr") == "Dr"


def test_normalize_wedge_word_variants():
    assert normalize_club_name("Pitching Wedge") == "Pw"
    assert normalize_club_name("Gap Wedge") == "Gw"
    assert normalize_club_name("Approach Wedge") == "Gw"
    assert normalize_club_name("AW") == "Gw"
    assert normalize_club_name("Sand Wedge") == "Sw"
    assert normalize_club_name("Lob Wedge") == "Lw"


def test_normalize_hybrid_folds_onto_same_numbered_iron():
    # This bag doesn't carry a hybrid, so hybrid readings are treated as
    # the same-numbered iron rather than getting their own bucket.
    assert normalize_club_name("4H") == "4I"
    assert normalize_club_name("H4") == "4I"
    assert normalize_club_name("4 Hybrid") == "4I"
    assert normalize_club_name("Hybrid 4") == "4I"
    assert get_club_rank("4H") == get_club_rank("4I")
    assert get_fitting_window("4H") == get_fitting_window("4I")


def test_normalize_feeds_get_club_rank_regardless_of_raw_spelling():
    # "I9" and "9I" are the same physical club and must sort identically.
    assert get_club_rank("I9") == get_club_rank("9I")
    assert get_club_rank("I9") != 99


def test_normalize_feeds_get_fitting_window_regardless_of_raw_spelling():
    # Previously "I9" fell through to the generic default window because
    # the substring match only ever looked for "9I", never "I9".
    assert get_fitting_window("I9") == get_fitting_window("9I")
    from config import DEFAULT_FITTING_WINDOW
    assert get_fitting_window("I9") != DEFAULT_FITTING_WINDOW


def test_normalize_none_and_empty_pass_through_safely():
    assert normalize_club_name(None) is None
    assert normalize_club_name("") == ""


# --- resolve_club_index: GSPro's currentRound.dat ClubIndex -> a label ---

def test_resolve_club_index_unmapped_falls_back_to_placeholder():
    # 999 is not a real GSPro ClubIndex (see config.CLUB_INDEX_MAP) — an
    # unrecognized index still shows up, just ungrouped, rather than
    # vanishing.
    assert resolve_club_index(999) == "Club999"


def test_resolve_club_index_accepts_string_digits():
    assert resolve_club_index("999") == "Club999"


def test_resolve_club_index_none_is_unknown():
    assert resolve_club_index(None) == "Unknown"


def test_resolve_club_index_non_numeric_is_unknown():
    assert resolve_club_index("not-a-number") == "Unknown"


def test_resolve_club_index_uses_map_when_present(monkeypatch):
    import config
    monkeypatch.setitem(config.CLUB_INDEX_MAP, 999, "Dr")
    assert resolve_club_index(999) == "Dr"


def test_resolve_club_index_known_bag_mapping():
    # Real mappings confirmed against this bag's clubs (config.CLUB_INDEX_MAP).
    assert resolve_club_index(0) == "Dr"
    assert resolve_club_index(24) == "Sw"


# "Live" is deliberately absent from the sidebar: the Live Dispersion panel is
# reached with the top-bar Go Live button, which owns starting/stopping live
# tracking, not with a dashboard checkbox.
_CATEGORIES_WITHOUT_A_SIDEBAR_SECTION = {"Live"}


def test_every_dashboard_category_has_a_sidebar_section():
    """A dashboard whose category is missing from _SIDEBAR_SECTIONS builds no nav
    item at all — the panel exists and is unreachable. The sidebar is driven by
    that table, so it has to cover the registry apart from the documented
    exceptions above."""
    from ui.app_window import _SIDEBAR_SECTIONS
    from ui.charts.registry import DASHBOARDS

    listed = {category for category, _title in _SIDEBAR_SECTIONS}
    listed |= _CATEGORIES_WITHOUT_A_SIDEBAR_SECTION
    missing = sorted({d.category for d in DASHBOARDS} - listed)
    assert not missing, f"dashboard categories with no sidebar section: {missing}"


def test_sidebar_sections_are_not_empty():
    """Conversely, a section with no dashboards renders an empty titled card."""
    from ui.app_window import _SIDEBAR_SECTIONS
    from ui.charts.registry import DASHBOARDS

    categories = {d.category for d in DASHBOARDS}
    empty = [c for c, _t in _SIDEBAR_SECTIONS if c not in categories]
    assert not empty, f"sidebar sections with no dashboards: {empty}"
