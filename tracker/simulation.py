"""
Synthetic drone flights, and an end-to-end simulation of the tracker against a simulated camera (no Kafka, no
hardware). Used by the tests, utils/simulate.py, and utils/fake_drones.py.
Flight paths are in the camera's ENU frame (metres, relative to the lens).
"""
import copy
import json
import math
import random
import tempfile

import numpy as np

from tracker.app import App
from tracker.camera import SimCamera
from tracker.geometry import LocalFrame, pointing, wrap180
from tracker.optics import Optics, SpeedMap


class FakeClock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class Orbit:
    def __init__(self, center, radius, up, speed, phase=0.0):
        self.center, self.radius, self.up, self.speed, self.phase = center, radius, up, speed, phase

    def position(self, t):
        angle = self.phase + self.speed / self.radius * t
        return np.array([self.center[0] + self.radius * math.sin(angle),
                         self.center[1] + self.radius * math.cos(angle), self.up])


class Line:
    """Flies back and forth along a polyline at constant speed."""

    def __init__(self, waypoints, speed):
        self.points = [np.array(p, dtype=float) for p in waypoints]
        self.lengths = [float(np.linalg.norm(b - a)) for a, b in zip(self.points, self.points[1:])]
        self.speed = speed

    def position(self, t):
        total = sum(self.lengths)
        s = (self.speed * t) % (2 * total)
        if s > total:
            s = 2 * total - s
        for a, b, length in zip(self.points, self.points[1:], self.lengths):
            if s <= length:
                return a + (b - a) * (s / length)
            s -= length
        return self.points[-1].copy()


class Takeoff:
    """Sits on the ground, climbs vertically, then flies `path`."""

    def __init__(self, path, ground_up, wait, climb_rate=3.0):
        self.path, self.ground_up, self.wait, self.climb_rate = path, ground_up, wait, climb_rate
        self.start = path.position(0.0)
        self.climb_time = (self.start[2] - ground_up) / climb_rate

    def position(self, t):
        if t < self.wait:
            return np.array([self.start[0], self.start[1], self.ground_up])
        if t < self.wait + self.climb_time:
            return np.array([self.start[0], self.start[1], self.ground_up + self.climb_rate * (t - self.wait)])
        return self.path.position(t - self.wait - self.climb_time)


class SimDrone:
    def __init__(self, drone_id, path, start=0.0, end=None):
        self.id, self.path, self.start, self.end = drone_id, path, start, end

    def flying(self, t):
        return t >= self.start and (self.end is None or t <= self.end)

    def state(self, t):
        """:return: ENU position and velocity at scenario time t"""
        h = 0.01
        t = t - self.start
        return self.path.position(t), (self.path.position(t + h) - self.path.position(t - h)) / (2 * h)


CAMERA_HEIGHT = 9.0  # Lens height above the ground in the scenarios, m


def scenario(name):
    """:return: (drones, duration in seconds)"""
    ground = -CAMERA_HEIGHT
    if name == "orbit":
        return [SimDrone("uav1", Orbit((0, 300), 150, 40, 12))], 90
    if name == "flyby":
        return [SimDrone("uav1", Line([(-600, 40, 30), (600, 40, 30)], 25))], 60
    if name == "overhead":
        return [SimDrone("uav1", Line([(-300, 5, 25), (300, 5, 25)], 15))], 50
    if name == "pair":
        return [SimDrone("uav1", Orbit((50, 200), 120, 45, 10)),
                SimDrone("uav2", Line([(-500, 350, 60), (500, 150, 60)], 20), start=10)], 120
    if name == "takeoff":
        return [SimDrone("uav1", Takeoff(Orbit((100, 100), 80, 50, 10), ground, wait=15))], 70
    raise ValueError(f"unknown scenario {name!r} (choose from {', '.join(SCENARIOS)})")


SCENARIOS = ("orbit", "flyby", "overhead", "pair", "takeoff")


def make_message(drone, t_rel, timestamp, frame, rng, noise=0.0):
    """A Kafka data message for `drone` at scenario time t_rel. :return: (key, value) bytes"""
    pos, vel = drone.state(t_rel)
    pos = pos + np.array([rng.gauss(0, noise), rng.gauss(0, noise), rng.gauss(0, noise)])
    lat, lon, alt = frame.to_geodetic(pos)
    body = {"drone_id": drone.id, "t": timestamp,
            "position": {"latitude": lat, "longitude": lon, "altitude": alt, "alt_ref": "msl"},
            "velocity": {"north": vel[1], "east": vel[0], "down": -vel[2]}}
    return drone.id.encode("utf-8"), json.dumps(body).encode("utf-8")


def simulation_config(cfg):
    """A copy of cfg set up for simulation: simulated camera, auto mode, scratch recording directory."""
    cfg = copy.deepcopy(cfg)
    cfg["camera"]["simulate"] = True
    cfg["auto"]["startup_mode"] = "auto"
    cfg["site"]["ref_alt_msl"] = cfg["camera"]["alt"] - CAMERA_HEIGHT
    cfg["recording"]["dir"] = tempfile.mkdtemp(prefix="dronetracker-sim-")
    return cfg


def run_simulation(cfg, name, msg_hz=5.0, noise=1.5, msg_latency=0.15, camera_latency=0.1, speed_error=0.85,
                   seed=1, settle=3.0, trace=False):
    """
    Fly a scenario against the full tracker with a simulated camera.
    :param speed_error: how fast the simulated camera really moves relative to the configured speed calibration
    :param settle: seconds after a target change before pointing error is counted
    :param trace: also return per-tick samples under "trace"
    :return: metrics dict
    """
    cfg = simulation_config(cfg)
    drones, duration = scenario(name)
    rng = random.Random(seed)
    clock = FakeClock()
    cam = cfg["camera"]

    def true_speed(max_rate, table):
        return SpeedMap(max_rate * speed_error, [[u, r * speed_error] for u, r in table] if table else None)

    sim_camera = SimCamera(clock, true_speed(cam["speed"]["pan_max"], cam["speed"]["pan_table"]),
                           true_speed(cam["speed"]["tilt_max"], cam["speed"]["tilt_table"]), cam["tilt_limits"],
                           latency=camera_latency)
    events = []

    def send(key, value):
        if key == b"event":
            events.append(json.loads(value))

    app = App(cfg, lambda: sim_camera, send=send, clock=clock, recorder_sleep=lambda _: None)
    frame = LocalFrame(cam["lat"], cam["lon"], cam["alt"])
    optics = Optics(cam["zoom"])
    aspect = cfg["framing"]["aspect"]
    dt = 1 / cfg["control"]["hz"]
    start = clock()
    in_flight = []  # (deliver_at, key, value, Kafka record timestamp)
    next_message = {d.id: 0.0 for d in drones}
    errors, in_frame, rates, target_since, last_targets = [], [], [], None, ()
    last_pan = None
    samples = []

    for _ in range(int(duration / dt)):
        now = clock()
        t_rel = now - start
        for drone in drones:
            if drone.flying(t_rel) and t_rel >= next_message[drone.id]:
                next_message[drone.id] = t_rel + 1 / msg_hz
                key, value = make_message(drone, t_rel, now, frame, rng, noise)
                in_flight.append((now + msg_latency * (0.5 + rng.random()), key, value, now))
        for message in [m for m in in_flight if m[0] <= now]:
            in_flight.remove(message)
            app.on_data(message[1], message[2], now, message[3])

        app.step(now)

        position = sim_camera.query_position()
        if last_pan is not None:
            rates.append(wrap180(position.pan - last_pan) / dt)
        last_pan = position.pan
        if app.targets != last_targets:
            target_since, last_targets = now, app.targets
        if app.targets and now - target_since >= settle:
            hfov = optics.hfov(position.zoom)
            cam_az = app.controller.azimuth(position.pan)
            visible = True
            for i, drone_id in enumerate(app.targets):
                drone = next(d for d in drones if d.id == drone_id)
                truth = pointing(drone.state(t_rel)[0])
                err_x = wrap180(truth.az - cam_az) * math.cos(math.radians(truth.el))
                err_y = truth.el - position.tilt
                if i == 0:
                    errors.append(math.hypot(err_x, err_y))
                visible &= abs(err_x) < hfov / 2 and abs(err_y) < hfov / aspect / 2
            in_frame.append(visible)
            if trace:
                samples.append({"t": round(t_rel, 1), "targets": list(app.targets), "visible": visible,
                                "error": round(errors[-1], 2), "hfov": round(hfov, 1),
                                "needed_hfov": round(app.aim.hfov, 1)})
        clock.advance(dt)

    app.shutdown()
    accelerations = np.diff(rates) / dt if len(rates) > 1 else np.zeros(1)
    return {"scenario": name,
            "tracked_seconds": round(len(in_frame) * dt, 1),
            "in_frame_pct": round(100 * sum(in_frame) / len(in_frame), 1) if in_frame else 0.0,
            "rms_error_deg": round(float(np.sqrt(np.mean(np.square(errors)))), 2) if errors else None,
            "max_error_deg": round(float(np.max(errors)), 2) if errors else None,
            "rms_pan_accel": round(float(np.sqrt(np.mean(np.square(accelerations)))), 1),
            "camera_commands": sim_camera.commands,
            "events": events,
            "recordings_dir": cfg["recording"]["dir"],
            **({"trace": samples} if trace else {})}
