"""Display-scale resolution: physical-size + OS-DPI aware auto scaling."""
import pytest
from data import settings


REF = settings._REF_DIAGONAL_IN  # 16.0
MIN, MAX = settings._MIN_SCALE, settings._MAX_SCALE


def test_reference_panel_reproduces_the_developer_look():
    # 16" 2560x1600 laptop at 150% Windows scaling -> exactly 1.5, unchanged
    # from what the old resolution-only formula produced for this machine.
    assert settings.auto_scale_for(1600, diagonal_in=16.0, os_scaling=1.5) == 1.5


def test_size_multiplier_is_one_at_reference():
    assert settings._size_multiplier(REF) == 1.0


def test_small_laptop_shrinks_to_the_floor():
    # A 10" 1366x768 laptop at 100% scaling: base 1.0 x floor 0.80.
    scale = settings.auto_scale_for(768, diagonal_in=10.1, os_scaling=1.0)
    assert scale == round(settings._FLOOR_MULT / 0.05) * 0.05
    assert scale >= MIN


def test_below_floor_diagonal_does_not_go_lower():
    assert settings._size_multiplier(9.0) == settings._FLOOR_MULT


def test_large_tv_saturates_rather_than_scaling_linearly():
    # A 75" 4K TV at 100% scaling caps at the +0.30 size ceiling, not 75/16 —
    # the physical-size term must never scale linearly with inches.
    big = settings._size_multiplier(75.0)
    assert big == 1.30
    # End to end, that ceiling is what you get AT A DESK. This used to be the
    # unconditional result, which was the bug: 1.30 on a 75" screen is fine two
    # feet away and unreadable from the hitting mat. A panel this size is now
    # assumed to be viewed from across the room unless told otherwise, so the
    # saturated size term gets the distance multiplier on top of it.
    assert settings.auto_scale_for(2160, diagonal_in=75.0, os_scaling=1.0,
                                   viewing_distance=settings.DISTANCE_DESK) == 1.30
    assert settings.auto_scale_for(2160, diagonal_in=75.0, os_scaling=1.0) > 2.0


def test_bigger_screen_scales_up_relative_to_reference():
    assert settings._size_multiplier(27.0) > settings._size_multiplier(REF)
    assert settings._size_multiplier(REF) > settings._size_multiplier(12.0)


def test_missing_diagonal_falls_back_to_os_scaling():
    # No EDID physical size -> neutral multiplier, so OS DPI drives it alone.
    assert settings.auto_scale_for(1440, diagonal_in=None, os_scaling=1.25) == 1.25


def test_bogus_diagonal_is_ignored():
    assert settings._size_multiplier(0) == 1.0
    assert settings.auto_scale_for(1080, diagonal_in=0, os_scaling=1.0) == 1.0


def test_missing_os_scaling_falls_back_to_height_ratio():
    assert settings.auto_scale_for(1080, diagonal_in=None, os_scaling=None) == 1.0
    assert settings.auto_scale_for(2160, diagonal_in=None, os_scaling=None) == 2.0


def test_scale_is_clamped_to_sane_bounds():
    assert settings.auto_scale_for(4320, diagonal_in=13.0, os_scaling=3.0) <= MAX
    assert settings.auto_scale_for(600, diagonal_in=8.0, os_scaling=0.5) >= MIN


def test_resolve_scale_auto_uses_metrics():
    assert settings.resolve_scale("Auto", 1600, diagonal_in=16.0, os_scaling=1.5) == 1.5


def test_resolve_scale_manual_override_ignores_metrics():
    assert settings.resolve_scale("125%", 1600, diagonal_in=16.0, os_scaling=1.5) == 1.25
    assert settings.resolve_scale("90%", 768, diagonal_in=10.0, os_scaling=1.0) == 0.90


def test_resolve_scale_bad_manual_value_falls_back_to_auto():
    assert settings.resolve_scale("garbage", 1600, diagonal_in=16.0, os_scaling=1.5) == 1.5


# ---------------------------------------------------------------------------
# Viewing distance — the TV/projector case Auto used to get wrong.
# ---------------------------------------------------------------------------
def test_desk_default_is_unchanged_by_the_distance_term():
    """An existing desk install must resolve exactly as it did before viewing
    distance existed: the desk multiplier is 1.0."""
    for height, diag, os_scaling in ((1600, 15.0, 1.5), (1080, 24.0, 1.0),
                                     (2160, 32.0, 1.5), (768, 10.0, 1.0)):
        assert (settings.auto_scale_for(height, diag, os_scaling, settings.DISTANCE_DESK)
                == settings.auto_scale_for(height, diag, os_scaling))


def test_across_the_room_scales_a_tv_up_substantially():
    """A 55" 4K TV at 100% OS scaling resolved to 1.30 — fine two feet away,
    unreadable from the mat."""
    desk = settings.auto_scale_for(2160, 55.0, 1.0, settings.DISTANCE_DESK)
    room = settings.auto_scale_for(2160, 55.0, 1.0, settings.DISTANCE_ROOM)
    assert desk == pytest.approx(1.30, abs=0.05)
    assert room >= 2.4, f"room scale {room} is not enough for a TV across a room"


def test_large_panel_assumes_room_distance_without_a_preference():
    """Nobody sits at a desk in front of 65 inches. Getting this wrong in the
    other direction leaves the app unreadable rather than merely chunky."""
    assert (settings.auto_scale_for(2160, 65.0, 1.0, None)
            == settings.auto_scale_for(2160, 65.0, 1.0, settings.DISTANCE_ROOM))
    # A normal monitor must NOT be swept up by that fallback.
    assert (settings.auto_scale_for(1440, 27.0, 1.0, None)
            == settings.auto_scale_for(1440, 27.0, 1.0, settings.DISTANCE_DESK))


def test_projector_reporting_no_physical_size_still_scales_up_when_told():
    """Projectors commonly report no EDID size, so diagonal_in is None and the
    size multiplier is a neutral 1.0 — the distance preference is the only
    signal left, and it has to be enough on its own."""
    assert settings.auto_scale_for(1080, None, 1.0, settings.DISTANCE_ROOM) >= 1.8


def test_explicit_percentage_ignores_viewing_distance():
    """An explicit percentage is the user stating the answer; nothing should
    second-guess it."""
    for distance in (settings.DISTANCE_DESK, settings.DISTANCE_ROOM, None):
        assert settings.resolve_scale("125%", 2160, 55.0, 1.0, distance) == pytest.approx(1.25)


def test_every_dropdown_option_survives_resolve_scale():
    """Menu options and what resolve_scale accepts drifted apart before: the
    list stopped at 200% while resolve_scale allowed 300%."""
    for option in settings.UI_SCALE_OPTIONS:
        value = settings.resolve_scale(option, 1600, 15.0, 1.5)
        assert 0.5 <= value <= 3.0
        if option != "Auto":
            assert value == pytest.approx(int(option.rstrip("%")) / 100.0)


def test_scale_stays_within_the_clamp_at_the_extremes():
    """The room multiplier must not be able to push past the documented ceiling."""
    worst = settings.auto_scale_for(4320, 120.0, 3.0, settings.DISTANCE_ROOM)
    assert worst <= 3.0
    smallest = settings.auto_scale_for(600, 7.5, 0.5, settings.DISTANCE_DESK)
    assert smallest >= 0.8
