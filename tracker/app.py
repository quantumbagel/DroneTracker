"""Wires tracks, targeting, camera control, recording, and commands together. Call step() at control/hz."""
import json
import logging
import os
import queue
import time

from tracker.controller import PTZController
from tracker.gateway import Gateway
from tracker.geometry import LocalFrame
from tracker.messages import MessageParser
from tracker.recorder import Recorder
from tracker.targeting import TargetSelector, frame, view_track
from tracker.tracks import TrackManager

log = logging.getLogger("app")


def append_log(path, record):
    """
    Append one JSON line to a session log. Logging must never stop the camera being steered, so failures
    (e.g. a full disk) are logged and swallowed.
    :return: whether it was written
    """
    try:
        with open(path, "a") as log_file:
            log_file.write(json.dumps(record) + "\n")
        return True
    except OSError as error:
        log.error(f"Couldn't write session log {path}: {error}")
        return False


class Session:
    """
    One continuous stretch of filming. Its log (<name>.jsonl next to the recordings) has periodic state lines and
    every event, so the footage can be matched to which drone was in shot and where it was.
    """

    def __init__(self, name, started, path):
        self.name = name
        self.started = started
        self.last_log = float("-inf")
        self.path = path
        self.failed = False

    def write(self, record):
        if not self.failed:  # After one failure, stop trying (and logging the error) for this session
            self.failed = not append_log(self.path, record)


class App:
    def __init__(self, cfg, camera_factory, send=None, clock=time.time, recorder_sleep=time.sleep):
        """
        :param camera_factory: returns a camera client; called once per thread that talks to the camera
        :param send: function(key: bytes, value: bytes) publishing to the Kafka output topic
        :param clock: epoch-seconds clock (replaceable for simulation)
        """
        self.cfg = cfg
        self.clock = clock
        self.send = send if send is not None else (lambda key, value: None)
        cam = cfg["camera"]
        self.frame = LocalFrame(cam["lat"], cam["lon"], cam["alt"])
        self.parser = MessageParser(cfg)
        self.tracks = TrackManager(cfg, self.frame)
        self.selector = TargetSelector(cfg["framing"])
        self.controller = PTZController(camera_factory(), cfg)
        os.makedirs(cfg["recording"]["dir"], exist_ok=True)
        self.recorder = Recorder(camera_factory, cfg, sleep=recorder_sleep) if cfg["recording"]["enabled"] else None
        self.gateway = Gateway(self, cfg, self.send)
        self.mode = cfg["auto"]["startup_mode"]
        self.targets = ()
        self.aim = None
        self.session = None
        self.last_busy = None
        self.bad_messages = 0
        log.info(f"Starting in mode '{self.mode}'")

    # --- Inputs ---

    def on_data(self, key, value, received, sent=None):
        """:param sent: the Kafka record timestamp (epoch s), if any"""
        try:
            measurement = self.parser.parse(key, value, received, sent)
        except ValueError as error:
            self.bad_messages += 1
            if self.bad_messages == 1 or self.bad_messages % 100 == 0:
                log.warning(f"Ignoring invalid data message ({self.bad_messages} so far): {error}")
            return
        self.tracks.ingest(measurement)

    def on_command(self, key, value):
        self.gateway.handle(key, value)

    # --- Commands ---

    def set_mode(self, mode):
        if mode != self.mode:
            log.info(f"Mode {self.mode} -> {mode}")
            self.mode = mode
            self.emit({"type": "mode", "mode": mode})

    def select(self, drone_id):
        """Manually choose the drone to film (None returns to automatic selection)."""
        if drone_id is not None and self.tracks.get(drone_id) is None:
            log.warning(f"Can't select unknown drone {drone_id}")
            return False
        self.selector.manual = drone_id
        self.emit({"type": "selected", "drone_id": drone_id})
        return True

    def set_priority(self, drone_ids):
        self.selector.priority = list(drone_ids)
        self.emit({"type": "priority", "priority": list(drone_ids)})

    def emit(self, event):
        """Publish an event on the output topic and record it in its session's log."""
        event = {"t": round(self.clock(), 3), **event}
        self.send(b"event", json.dumps(event).encode("utf-8"))
        session = event.get("session")
        if self.session and session in (None, self.session.name):
            self.session.write(event)
        elif session:  # E.g. an export finishing after its session ended
            append_log(os.path.join(self.cfg["recording"]["dir"], f"{session}.jsonl"), event)

    # --- Main loop ---

    def step(self, now):
        for event in self.tracks.update(now, self.mode):
            self.emit(event)
        self._drain_recorder_events()

        t = now + self.cfg["control"]["lookahead"]
        size = self.cfg["framing"]["drone_size"]
        views = {}
        if self.mode != "off":
            views = {track.id: view_track(track, t, size) for track in self.tracks.active()}
            manual = self.tracks.get(self.selector.manual) if self.selector.manual else None
            # A manually selected drone is filmed whenever we have fresh data for it, even if auto rules exclude it
            if manual and manual.id not in views and self.tracks.eligibility(manual, now, "on")[0]:
                views[manual.id] = view_track(manual, t, size)
        targets = self.selector.select(views)

        if targets != self.targets:
            log.info(f"Filming {', '.join(targets) if targets else 'nothing'}")
            self.emit({"type": "targets", "drone_ids": list(targets)})
            self.targets = targets
        if targets:
            self.aim = frame([views[i] for i in targets], self.cfg["framing"])
            self.controller.track(self.aim, now)
        else:
            self.aim = None
            self.controller.idle(now, park_now=self.mode == "off")
        self._update_session(now, busy=bool(targets))

    def _update_session(self, now, busy):
        rec = self.cfg["recording"]
        if busy:
            self.last_busy = now
            if self.session is None:
                self._start_session(now)
        elif self.session and (self.mode == "off" or now - self.last_busy >= rec["stop_after"]):
            self._end_session(now)
        if self.session and now - self.session.last_log >= rec["log_interval"]:
            self.session.last_log = now
            self.session.write(self._snapshot(now))

    def _start_session(self, now):
        directory = self.cfg["recording"]["dir"]
        base = time.strftime("session-%Y%m%d-%H%M%S", time.gmtime(now))
        name, n = base, 1
        while os.path.exists(os.path.join(directory, name + ".jsonl")):
            n += 1
            name = f"{base}-{n}"
        self.session = Session(name, now, os.path.join(directory, name + ".jsonl"))
        log.info(f"Session {name} started")
        self.emit({"type": "session_started", "session": name})
        if self.recorder:
            self.recorder.start(name)

    def _end_session(self, now):
        if self.recorder:
            self.recorder.stop()
        log.info(f"Session {self.session.name} ended")
        self.emit({"type": "session_ended", "session": self.session.name,
                   "duration": round(now - self.session.started, 1)})
        self.session = None

    def _drain_recorder_events(self):
        if self.recorder is None:
            return
        while True:
            try:
                self.emit(self.recorder.events.get_nowait())
            except queue.Empty:
                return

    def _track_state(self, track, now):
        pos, vel, _ = track.state_at(now)
        lat, lon, alt = self.frame.to_geodetic(pos)
        return {"lat": round(lat, 7), "lon": round(lon, 7), "alt_msl": round(alt, 2),
                "vel_enu": [round(float(v), 2) for v in vel], "active": track.active,
                "age": round(track.age(now), 2)}

    def _snapshot(self, now):
        aim = self.aim
        return {"t": round(now, 3), "type": "state", "mode": self.mode, "targets": list(self.targets),
                "aim": None if aim is None else {"az": round(aim.az, 3), "el": round(aim.el, 3),
                                                 "hfov": round(aim.hfov, 2)},
                "camera": self.controller.status(),
                "tracks": {track.id: self._track_state(track, now) for track in self.tracks.tracks.values()}}

    def status(self):
        now = self.clock()
        return {"mode": self.mode, "targets": list(self.targets), "selected": self.selector.manual,
                "priority": self.selector.priority, "session": self.session.name if self.session else None,
                "recording_id": self.recorder.recording_id if self.recorder else None,
                "camera": self.controller.status(),
                "tracks": {track.id: self._track_state(track, now) for track in self.tracks.tracks.values()}}

    def stop_camera(self):
        """Best-effort stop, for when a tick failed part-way and the camera may still be moving."""
        self.controller.idle(self.clock())

    def shutdown(self):
        self.controller.shutdown()  # Camera first: nothing below may leave it moving
        if self.session:
            self._end_session(self.clock())
        if self.recorder:
            self.recorder.close()
            self._drain_recorder_events()
