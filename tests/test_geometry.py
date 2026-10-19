import math

import numpy as np
import pytest

from tracker.geometry import angular_size, pointing, wrap180, wrap360


@pytest.mark.parametrize("angle, expected", [(0, 0), (180, -180), (-180, -180), (190, -170), (-190, 170),
                                             (540, -180), (359, -1), (-32.5 - 170, 157.5)])
def test_wrap180(angle, expected):
    assert wrap180(angle) == pytest.approx(expected)


def test_wrap360():
    assert wrap360(-10) == pytest.approx(350)


def test_enu_matches_known_distances(frame):
    north = frame.to_enu(frame.lat + 0.001, frame.lon, frame.alt)
    east = frame.to_enu(frame.lat, frame.lon + 0.001, frame.alt)
    assert north == pytest.approx([0, 110.95, 0], abs=0.3)
    assert east == pytest.approx([90.37, 0, 0], abs=0.3)


def test_enu_round_trip(frame):
    for enu in ([0, 0, 0], [1500.0, -800.0, 120.0], [-3.2, 4.5, -9.0]):
        assert frame.to_enu(*frame.to_geodetic(enu)) == pytest.approx(enu, abs=1e-3)


@pytest.mark.parametrize("pos, az", [((0, 100, 0), 0), ((100, 0, 0), 90), ((0, -100, 0), -180), ((-100, 0, 0), -90),
                                     ((100, 100, 0), 45), ((-100, -100, 0), -135)])
def test_azimuth_in_every_quadrant(pos, az):
    assert pointing(pos).az == pytest.approx(az)


def test_v1_quadrant_bug_regression():
    # v1 computed 76.1° for a target east-south-east of the camera after the velocity lead; the truth is 104°
    assert pointing((20, -5, 0)).az == pytest.approx(math.degrees(math.atan2(20, -5)))


def test_elevation_and_range():
    view = pointing((0, 100, 100))
    assert view.el == pytest.approx(45)
    assert view.range == pytest.approx(math.sqrt(2) * 100)


def test_directly_overhead_does_not_divide_by_zero():
    view = pointing((0, 0, 50), (5, 0, 0))
    assert view.el == pytest.approx(90)
    assert view.az_rate == 0


def test_rates_match_finite_differences():
    rng = np.random.default_rng(3)
    for _ in range(50):
        pos = rng.uniform(-500, 500, 3)
        vel = rng.uniform(-20, 20, 3)
        h = 1e-4
        now, later = pointing(pos, vel), pointing(pos + vel * h)
        assert now.az_rate == pytest.approx(wrap180(later.az - now.az) / h, rel=1e-3, abs=1e-4)
        assert now.el_rate == pytest.approx((later.el - now.el) / h, rel=1e-3, abs=1e-4)


def test_angular_size():
    assert angular_size(1, 100) == pytest.approx(0.573, abs=1e-3)
