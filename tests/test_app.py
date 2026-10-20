import json
import os

import numpy as np
import pytest

from tests.conftest import make_config
from tracker.app import App
from tracker.camera import CameraError, make_camera_factory
from tracker.geometry import LocalFrame
from tracker.simulation import FakeClock


def build(tmp_path, **sections):
    cfg = make_config(tmp_path, **sections)
    clock = FakeClock()
    events = []
    send = lambda key, value: events.append(json.loads(value)) if key == b"event" else None  # noqa: E731
    app = App(cfg, make_camera_factory(cfg, clock), send=send, clock=clock, recorder_sleep=lambda _: None)
    cam = cfg["camera"]
    return app, clock, events, LocalFrame(cam["lat"], cam["lon"], cam["alt"])


def fly(app, clock, frame, seconds, enu=(100, 200, 40), drone_id="uav1", hz=10):
    """Report a drone hovering at enu, stepping the app every tick."""
    lat, lon, alt = frame.to_geodetic(np.array(enu, float))
    for _ in range(int(seconds * hz)):
        now = clock()
        body = {"drone_id": drone_id, "t": now, "position": {"latitude": lat, "longitude": lon, "altitude": alt}}
        app.on_data(None, json.dumps(body).encode(), now)
        app.step(now)
        clock.advance(1 / hz)


def idle(app, clock, seconds, hz=10):
    for _ in range(int(seconds * hz)):
        app.step(clock())
        clock.advance(1 / hz)


def types(events):
    return [e["type"] for e in events]


def test_full_session_lifecycle(tmp_path):
    app, clock, events, frame = build(tmp_path)
    fly(app, clock, frame, 5)
    assert app.targets == ("uav1",)
    assert app.session is not None
    session = app.session.name
    idle(app, clock, 20)  # Data stops: deactivate after 1.5 + 5 s, then the session ends 10 s later
    app.recorder.wait_idle()
    idle(app, clock, 0.1)
    assert app.session is None
    for expected in ("track_active", "targets", "session_started", "recording_started", "track_inactive",
                     "session_ended", "recording_stopped", "recording_exported"):
        assert expected in types(events)
    directory = app.cfg["recording"]["dir"]
    assert sorted(os.listdir(directory)) == [f"{session}.jsonl", f"{session}.mkv"]
    with open(os.path.join(directory, f"{session}.jsonl")) as log:
        lines = [json.loads(line) for line in log]
    assert "recording_exported" in types(lines)  # Arrives after the session ended, but still lands in its log
    states = [line for line in lines if line["type"] == "state"]
    assert states and states[-1]["tracks"]["uav1"]["lat"] == pytest.approx(frame.to_geodetic([100, 200, 40])[0])
    app.shutdown()


def test_off_ends_the_session_immediately(tmp_path):
    app, clock, events, frame = build(tmp_path)
    fly(app, clock, frame, 5)
    app.on_command(b"track_camera", b"off")
    fly(app, clock, frame, 0.2)
    assert app.session is None and app.targets == ()
    assert app.controller.parked  # Immediately, not after park_after
    fly(app, clock, frame, 5)
    assert app.session is None  # Still off, even with fresh data
    app.shutdown()


def test_manual_selection_films_a_drone_auto_would_skip(tmp_path):
    app, clock, events, frame = build(tmp_path)
    fly(app, clock, frame, 3, enu=(0, 100, -9))  # On the ground
    assert app.targets == ()
    app.on_command(b"select", b"uav1")
    fly(app, clock, frame, 0.2, enu=(0, 100, -9))
    assert app.targets == ("uav1",)
    app.shutdown()


def test_two_drones_are_framed_together(tmp_path):
    app, clock, events, frame = build(tmp_path)
    for _ in range(40):
        fly(app, clock, frame, 0.1, enu=(0, 300, 40), drone_id="a")
        fly(app, clock, frame, 0.1, enu=(30, 300, 45), drone_id="b")
    assert set(app.targets) == {"a", "b"}
    assert -1 < app.aim.az < 6
    app.shutdown()


def test_full_disk_does_not_stop_camera_control(tmp_path):
    app, clock, events, frame = build(tmp_path)
    fly(app, clock, frame, 4)
    assert app.session is not None
    directory = app.cfg["recording"]["dir"]
    os.chmod(directory, 0o500)  # Session log writes now fail, as on a full disk
    try:
        for name in os.listdir(directory):
            os.chmod(os.path.join(directory, name), 0o400)
        commands = app.controller.camera.commands
        fly(app, clock, frame, 2, enu=(-200, 100, 40))  # The drone moves: the camera must follow
        assert app.controller.camera.commands > commands
        app.on_command(b"track_camera", b"off")
        idle(app, clock, 0.2)
        assert app.controller.parked and app.session is None
    finally:
        os.chmod(directory, 0o700)
        for name in os.listdir(directory):
            os.chmod(os.path.join(directory, name), 0o600)
    app.shutdown()


def test_bad_messages_do_not_crash(tmp_path):
    app, clock, events, frame = build(tmp_path)
    for value in (b"garbage", b"{}", b'{"position": {"latitude": null}}', None):
        app.on_data(None, value, clock())
    app.step(clock())
    assert app.bad_messages == 4
    app.shutdown()


def test_recording_failure_is_reported_not_fatal(tmp_path):
    app, clock, events, frame = build(tmp_path)
    camera = app.controller.camera
    original = camera.start_recording
    camera.start_recording = lambda *args, **kwargs: (_ for _ in ()).throw(CameraError("disk full"))
    fly(app, clock, frame, 4)
    app.recorder.wait_idle()
    fly(app, clock, frame, 0.2)
    assert "recording_failed" in types(events)
    assert app.targets == ("uav1",)  # Still tracking
    camera.start_recording = original
    app.shutdown()


def test_unexpected_recorder_error_does_not_end_recording_for_good(tmp_path):
    app, clock, events, frame = build(tmp_path)
    camera = app.controller.camera
    original = camera.start_recording
    camera.start_recording = lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("surprise"))
    fly(app, clock, frame, 4)
    app.recorder.wait_idle()
    camera.start_recording = original
    idle(app, clock, 20)  # That session ends; the next one must still record
    fly(app, clock, frame, 4)
    app.recorder.wait_idle()
    fly(app, clock, frame, 0.2)
    assert types(events).count("session_started") == 2
    assert "recording_failed" in types(events) and "recording_started" in types(events)
    app.shutdown()


def test_backlog_of_untimestamped_messages_uses_kafka_timestamps(tmp_path):
    """A stalled tick delivers several messages without t at once; their Kafka timestamps keep the velocity right."""
    app, clock, _, frame = build(tmp_path)
    start = clock()
    for i in range(60):  # 5 Hz at 20 m/s; the first 50 arrive promptly, the last 10 all at once after a 2 s stall
        sent = start + i * 0.2
        lat, lon, alt = frame.to_geodetic(np.array([20.0 * i * 0.2, 200, 40]))
        value = json.dumps({"position": {"latitude": lat, "longitude": lon, "altitude": alt}}).encode()
        app.on_data(b"uav1", value, max(sent, start + 59 * 0.2) if i >= 50 else sent, sent)
    assert app.tracks.get("uav1").filter.velocity[0] == pytest.approx(20, abs=1)
