"""Display-scale resolution: physical-size + OS-DPI aware auto scaling."""
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
    # A 75" 4K TV at 100% scaling caps at the +0.30 size ceiling, not 75/16.
    big = settings._size_multiplier(75.0)
    assert big == 1.30
    assert settings.auto_scale_for(2160, diagonal_in=75.0, os_scaling=1.0) == 1.30


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
