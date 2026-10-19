import numpy as np
import pytest

from tracker.kalman import ConstantVelocityFilter


def make_filter(t=0.0, pos=(0, 0, 0), vel=None):
    return ConstantVelocityFilter(t, np.array(pos, float), None if vel is None else np.array(vel, float),
                                  accel_noise=3.0, pos_sigma=2.0, vel_sigma=0.5)


def test_learns_velocity_from_noisy_positions():
    rng = np.random.default_rng(0)
    true_vel = np.array([12.0, -5.0, 1.0])
    kf = make_filter()
    for i in range(1, 60):  # 12 s at 5 Hz
        t = i * 0.2
        kf.update(t, true_vel * t + rng.normal(0, 2.0, 3))
    assert kf.velocity == pytest.approx(true_vel, abs=1.0)
    predicted, _, _ = kf.state_at(kf.t + 1.0)
    assert predicted == pytest.approx(true_vel * (kf.t + 1.0), abs=3.0)


def test_velocity_measurements_converge_immediately():
    kf = make_filter(vel=(10, 0, 0))
    kf.update(0.2, np.array([2.0, 0, 0]), np.array([10.0, 0, 0]))
    assert kf.velocity == pytest.approx([10, 0, 0], abs=0.2)


def test_state_at_does_not_modify_the_filter():
    kf = make_filter(vel=(1, 2, 3))
    before = (kf.x.copy(), kf.p.copy(), kf.t)
    pos, vel, cov = kf.state_at(5.0)
    assert pos == pytest.approx([5, 10, 15])
    assert np.trace(cov) > np.trace(before[1])
    assert (kf.x == before[0]).all() and (kf.p == before[1]).all() and kf.t == before[2]


def test_covariance_stays_symmetric():
    kf = make_filter()
    for i in range(1, 100):
        kf.update(i * 0.1, np.array([i, 0.0, 0.0]), np.array([10.0, 0, 0]))
    assert kf.p == pytest.approx(kf.p.T)
    assert np.all(np.linalg.eigvalsh(kf.p) > 0)
