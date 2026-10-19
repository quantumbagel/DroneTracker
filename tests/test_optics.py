import math

import pytest

from tracker.optics import Optics, SpeedMap

DEFAULT_ZOOM = {"wide_hfov": 63.1, "max_zoom": 31.0, "table": None}


def test_default_optics_span_the_lens():
    optics = Optics(DEFAULT_ZOOM)
    assert optics.hfov(0) == pytest.approx(63.1)
    # 31x magnification divides tan(hfov/2), not the angle itself
    assert optics.min_hfov == pytest.approx(math.degrees(2 * math.atan(math.tan(math.radians(63.1 / 2)) / 31)))


def test_step_for_hfov_round_trip():
    optics = Optics(DEFAULT_ZOOM)
    for step in (0, 500, 3000, 9999):
        assert optics.step_for_hfov(optics.hfov(step)) == pytest.approx(step, abs=2)


def test_zoom_is_always_in_range():
    # v1 sent 26998 steps for a drone 400 m away and negative steps up close
    optics = Optics(DEFAULT_ZOOM)
    assert optics.step_for_hfov(0.01) == 9999
    assert optics.step_for_hfov(170) == 0


def test_measured_zoom_table():
    optics = Optics({**DEFAULT_ZOOM, "table": [[9999, 2.0], [0, 60.0], [5000, 10.0]]})
    assert optics.hfov(2500) == pytest.approx(35.0)
    assert optics.step_for_hfov(10.0) == 5000


@pytest.mark.parametrize("table", [[[0, 10], [100, 20]], [[0, 10]], [[0, 10], [0, 5]], "nope"])
def test_bad_zoom_tables(table):
    with pytest.raises(ValueError):
        Optics({**DEFAULT_ZOOM, "table": table})


def test_linear_speed_map():
    speed = SpeedMap(60)
    assert speed.units(30) == 50
    assert speed.units(-30) == -50
    assert speed.units(1000) == 100
    assert speed.units(0.2) == 0
    assert speed.rate(-50) == pytest.approx(-30)


def test_measured_speed_table():
    speed = SpeedMap(60, [[100, 120.0], [10, 1.0], [50, 20.0]])
    assert speed.units(0.5) == 5  # (0, 0) is implied
    assert speed.units(10.5) == 30
    assert speed.max_rate == 120


def test_bad_speed_table():
    with pytest.raises(ValueError):
        SpeedMap(60, [[10, 5.0], [20, 4.0]])
