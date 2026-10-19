"""
Camera clients: a VAPIX HTTP client for AXIS PTZ cameras, and a simulated camera for tests and offline runs.

Both expose the same methods. Every failure raises CameraError; nothing here retries or exits the process.
A VapixCamera holds one HTTP session, so give each thread its own instance.
"""
import math
import threading
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

import requests
from requests.auth import HTTPDigestAuth

from tracker.geometry import wrap180
from tracker.optics import MAX_SPEED_UNITS, MAX_ZOOM_STEP, SpeedMap


class CameraError(RuntimeError):
    pass


@dataclass(frozen=True)
class PTZPosition:
    pan: float  # camera frame, deg
    tilt: float  # deg
    zoom: int  # step, 0-9999


class VapixCamera:
    def __init__(self, ip, username, password, timeout=1.0):
        self.base = f"http://{ip}/axis-cgi"
        self.timeout = timeout
        self.session = requests.Session()
        # A persistent session lets digest auth reuse its nonce, saving a 401 round trip per command
        self.session.auth = HTTPDigestAuth(username, password)

    def _get(self, path, params, timeout=None, stream=False):
        params = {k: v for k, v in params.items() if v is not None}
        try:
            response = self.session.get(self.base + path, params=params, timeout=timeout or self.timeout,
                                        stream=stream)
        except requests.RequestException as error:
            raise CameraError(f"{path}: {error}") from error
        if response.status_code not in (200, 204):
            raise CameraError(f"{path}: HTTP {response.status_code} {response.text[:200].strip()}")
        return response

    def _ptz(self, **params):
        return self._get("/com/ptz.cgi", {"camera": 1, **params})

    def _xml(self, path, params):
        # Recording calls get extra time: retrying a slow-but-successful start would leave a second recording running
        text = self._get(path, params, timeout=self.timeout * 5).text
        try:
            return ElementTree.fromstring(text)
        except ElementTree.ParseError:
            raise CameraError(f"{path}: unexpected response {text[:200]!r}") from None

    def query_position(self):
        text = self._ptz(query="position").text
        values = dict(line.strip().split("=", 1) for line in text.splitlines() if "=" in line)
        try:
            return PTZPosition(float(values["pan"]), float(values["tilt"]), int(float(values["zoom"])))
        except (KeyError, ValueError):
            raise CameraError(f"unexpected position response {text[:200]!r}") from None

    def continuous_move(self, pan, tilt, zoom):
        """Speeds in VAPIX units, -100..100. The camera keeps moving until told otherwise."""
        self._ptz(continuouspantiltmove=f"{int(pan)},{int(tilt)}", continuouszoommove=int(zoom))

    def absolute_move(self, pan=None, tilt=None, zoom=None, speed=None):
        self._ptz(pan=None if pan is None else f"{pan:.2f}", tilt=None if tilt is None else f"{tilt:.2f}",
                  zoom=None if zoom is None else int(zoom), speed=None if speed is None else int(speed))

    def stop(self):
        self.continuous_move(0, 0, 0)

    def start_recording(self, disk, profile=None):
        """:return: the recording id"""
        record = self._xml("/record/record.cgi", {"diskid": disk, "streamprofile": profile}).find("record")
        if record is None or record.get("result") != "OK":
            reason = record.get("errormsg") if record is not None else "no <record> element"
            raise CameraError(f"failed to start recording: {reason}")
        return record.get("recordingid")

    def stop_recording(self, recording_id):
        stop = self._xml("/record/stop.cgi", {"recordingid": recording_id}).find("stop")
        if stop is None or stop.get("result") != "OK":
            reason = stop.get("errormsg") if stop is not None else "no <stop> element"
            raise CameraError(f"failed to stop recording {recording_id}: {reason}")

    def export_recording(self, disk, recording_id, path):
        """Download a finished recording from the camera's disk to `path` as Matroska."""
        response = self._get("/record/export/exportrecording.cgi",
                             {"schemaversion": "1.2", "recordingid": recording_id, "diskid": disk,
                              "exportformat": "matroska"},
                             timeout=(self.timeout * 5, 60), stream=True)
        try:
            with open(path, "wb") as output:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    output.write(chunk)
        except requests.RequestException as error:
            raise CameraError(f"export of {recording_id} interrupted: {error}") from error


class SimCamera:
    """
    A simulated PTZ camera. Commands take effect after `latency` seconds and are integrated over the injected
    clock, using speed maps that can deliberately differ from the controller's to model calibration error.
    """

    def __init__(self, clock, pan_speed, tilt_speed, tilt_limits, latency=0.0, zoom_rate=2500.0,
                 pan=0.0, tilt=0.0, zoom=0):
        self.clock = clock
        self.pan_speed, self.tilt_speed = pan_speed, tilt_speed
        self.tilt_limits = tilt_limits
        self.latency = latency
        self.zoom_rate = zoom_rate  # steps/s at full speed
        self.pan, self.tilt, self.zoom = float(pan), float(tilt), float(zoom)
        self.motion = ("velocity", 0.0, 0.0, 0.0)
        self.pending = []
        self.t = clock()
        self.fail_next = 0  # Make the next N calls raise CameraError, for tests
        self.commands = 0
        self.recording = None
        self.recordings = {}
        self._lock = threading.Lock()
        self._next_id = 1

    def _check_failure(self):
        if self.fail_next:
            self.fail_next -= 1
            raise CameraError("simulated failure")

    def _advance(self):
        now = self.clock()
        while self.pending and self.pending[0][0] <= now:
            t_effect, motion = self.pending.pop(0)
            self._integrate(t_effect)
            self.motion = motion
        self._integrate(now)

    def _integrate(self, t):
        dt = t - self.t
        if dt <= 0:
            return
        self.t = t
        lo, hi = self.tilt_limits
        if self.motion[0] == "velocity":
            _, pan_rate, tilt_rate, zoom_units = self.motion
            self.pan = wrap180(self.pan + pan_rate * dt)
            self.tilt = min(max(self.tilt + tilt_rate * dt, lo), hi)
            self.zoom = min(max(self.zoom + zoom_units / MAX_SPEED_UNITS * self.zoom_rate * dt, 0), MAX_ZOOM_STEP)
        else:
            _, pan, tilt, zoom, rate = self.motion
            if pan is not None:
                error = wrap180(pan - self.pan)
                self.pan = wrap180(self.pan + math.copysign(min(abs(error), rate * dt), error))
            if tilt is not None:
                tilt = min(max(tilt, lo), hi)
                self.tilt += math.copysign(min(abs(tilt - self.tilt), rate * dt), tilt - self.tilt)
            if zoom is not None:
                self.zoom += math.copysign(min(abs(zoom - self.zoom), self.zoom_rate * dt), zoom - self.zoom)

    def _command(self, motion):
        with self._lock:
            self._check_failure()
            self._advance()
            self.commands += 1
            self.pending.append((self.clock() + self.latency, motion))

    def query_position(self):
        with self._lock:
            self._check_failure()
            self._advance()
            return PTZPosition(self.pan, self.tilt, int(round(self.zoom)))

    def continuous_move(self, pan, tilt, zoom):
        self._command(("velocity", self.pan_speed.rate(pan), self.tilt_speed.rate(tilt), float(zoom)))

    def absolute_move(self, pan=None, tilt=None, zoom=None, speed=None):
        rate = self.pan_speed.rate(speed if speed is not None else MAX_SPEED_UNITS)
        self._command(("position", pan, tilt, zoom, rate))

    def stop(self):
        self.continuous_move(0, 0, 0)

    def start_recording(self, disk, profile=None):
        with self._lock:
            self._check_failure()
            recording_id = f"sim-{self._next_id}"
            self._next_id += 1
            self.recording = recording_id
            self.recordings[recording_id] = self.clock()
            return recording_id

    def stop_recording(self, recording_id):
        with self._lock:
            self._check_failure()
            if self.recording != recording_id:
                raise CameraError(f"recording {recording_id} is not running")
            self.recording = None

    def export_recording(self, disk, recording_id, path):
        with self._lock:
            self._check_failure()
            if recording_id not in self.recordings:
                raise CameraError(f"no recording {recording_id}")
        with open(path, "wb") as output:
            output.write(b"simulated recording " + recording_id.encode())


def make_camera_factory(cfg, clock=time.time, sim_camera=None):
    """
    :return: a function returning a new camera client for each caller (each thread needs its own HTTP session)
    """
    cam = cfg["camera"]
    if cam["simulate"]:
        if sim_camera is None:
            sim_camera = SimCamera(clock, SpeedMap(cam["speed"]["pan_max"], cam["speed"]["pan_table"]),
                                   SpeedMap(cam["speed"]["tilt_max"], cam["speed"]["tilt_table"]),
                                   cam["tilt_limits"])
        return lambda: sim_camera
    return lambda: VapixCamera(cam["ip"], cam["username"], cam["password"], cam["request_timeout"])
