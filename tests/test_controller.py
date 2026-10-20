import pytest

from tests.conftest import make_config
from tracker.camera import CameraError, SimCamera
from tracker.controller import PTZController
from tracker.optics import SpeedMap
from tracker.simulation import FakeClock
from tracker.targeting import Aim


def setup(tmp_path, latency=0.0, pan=0.0, **sections):
    cfg = make_config(tmp_path, **sections)
    clock = FakeClock()
    camera = SimCamera(clock, SpeedMap(60), SpeedMap(60), cfg["camera"]["tilt_limits"], latency=latency, pan=pan)
    return PTZController(camera, cfg), camera, clock


def run(controller, clock, aim_at, seconds, hz=10):
    for _ in range(int(seconds * hz)):
        controller.track(aim_at(clock()), clock())
        clock.advance(1 / hz)


def aim(az, el, az_rate=0.0, el_rate=0.0, hfov=10.0):
    return Aim(("uav1",), az, el, az_rate, el_rate, hfov, 100.0)


def test_velocity_mode_settles_on_a_fixed_target(tmp_path):
    controller, camera, clock = setup(tmp_path, latency=0.1, camera={"offset": 0.0})
    run(controller, clock, lambda t: aim(30, 10), 5)
    position = camera.query_position()
    assert position.pan == pytest.approx(30, abs=0.5)
    assert position.tilt == pytest.approx(10, abs=0.5)
    assert controller.optics.hfov(position.zoom) == pytest.approx(10, rel=0.2)


def test_velocity_mode_follows_a_moving_target(tmp_path):
    controller, camera, clock = setup(tmp_path, latency=0.1, camera={"offset": 0.0})
    start = clock()
    target = lambda t: aim(-20 + 5 * (t - start + 0.2), 5, az_rate=5.0)  # noqa: E731 (aims are 0.2 s ahead)
    run(controller, clock, target, 10)
    assert camera.query_position().pan == pytest.approx(-20 + 5 * (clock() - start), abs=1.0)


def test_negative_offset_wraps_correctly(tmp_path):
    # v1 sent pan = 562.5 for this case
    controller, _, _ = setup(tmp_path, camera={"offset": -32.5})
    assert controller.camera_pan(-170) == pytest.approx(157.5)
    assert controller.azimuth(157.5) == pytest.approx(-170)


def test_tilt_limit_is_respected(tmp_path):
    controller, camera, clock = setup(tmp_path, camera={"offset": 0.0, "tilt_limits": [-90, 45]})
    run(controller, clock, lambda t: aim(0, 80, el_rate=5), 5)
    assert camera.query_position().tilt == pytest.approx(45, abs=0.5)  # Stops within the deadband of the limit
    assert camera.query_position().tilt <= 45
    assert controller.commanded[1] == 0


def test_shot_widens_while_the_target_is_beyond_the_tilt_range(tmp_path):
    controller, camera, clock = setup(tmp_path, camera={"offset": 0.0, "tilt_limits": [-90, 45]})
    assert controller.needed_hfov(aim(0, 40)) == 10.0
    assert controller.needed_hfov(aim(0, 50)) == pytest.approx(10.0 + 2 * 5 * 16 / 9)
    run(controller, clock, lambda t: aim(0, 50), 5)
    position = camera.query_position()
    # Still in the frame height although the camera can't tilt up to it
    assert 50 - position.tilt < controller.optics.hfov(position.zoom) / (16 / 9) / 2


def test_camera_failures_stop_motion_and_recover(tmp_path):
    controller, camera, clock = setup(tmp_path, camera={"offset": 0.0})
    run(controller, clock, lambda t: aim(90, 0), 0.5)
    assert controller.commanded != (0, 0, 0)
    camera.fail_next = 1  # The position query fails; the stop that follows succeeds
    controller.track(aim(90, 0), clock())
    assert controller.failures == 1
    assert controller.commanded == (0, 0, 0)
    camera.query_position()  # Let the stop take effect
    assert camera.motion[1:3] == (0, 0)
    controller.track(aim(90, 0), clock())
    assert controller.failures == 0


def test_move_that_times_out_after_the_camera_acted_is_still_stopped(tmp_path):
    controller, camera, clock = setup(tmp_path, camera={"offset": 0.0, "park": {"pan": None, "tilt": None}})
    real_move = camera.continuous_move

    def accepted_then_timed_out(*speeds):
        real_move(*speeds)
        raise CameraError("read timed out")

    camera.continuous_move = accepted_then_timed_out
    controller.track(aim(90, 0, az_rate=20), clock())  # The camera starts panning, but we never hear back
    camera.continuous_move = real_move
    assert controller.commanded is None
    for _ in range(10):
        controller.idle(clock())
        clock.advance(0.1)
    assert camera.motion[1:3] == (0, 0)


def test_idle_stops_then_parks_keeping_pan(tmp_path):
    # v1 "pan: 0 means no change" actually turned the camera to face north; v2 uses null for "keep"
    controller, camera, clock = setup(tmp_path, pan=0.0, camera={"offset": 0.0, "park": {"pan": None, "tilt": -90},
                                                                 "park_after": 2})
    run(controller, clock, lambda t: aim(40, 0, az_rate=10), 1)
    pan_when_idle = camera.query_position().pan
    for _ in range(50):
        controller.idle(clock())
        clock.advance(0.1)
    position = camera.query_position()
    assert controller.parked
    assert position.tilt == pytest.approx(-90)
    assert position.pan == pytest.approx(pan_when_idle, abs=1.0)
    assert position.zoom == 0


def test_position_mode(tmp_path):
    controller, camera, clock = setup(tmp_path, camera={"offset": 10.0}, control={"mode": "position"})
    run(controller, clock, lambda t: aim(30, 10), 3)
    position = camera.query_position()
    assert (position.pan, position.tilt) == (pytest.approx(40, abs=0.1), pytest.approx(10, abs=0.1))
    assert controller.status()["position"]["azimuth"] == pytest.approx(30, abs=0.1)  # For the session log
    commands = camera.commands
    run(controller, clock, lambda t: aim(30.2, 10), 1)  # Below min_step: no new command
    assert camera.commands == commands
