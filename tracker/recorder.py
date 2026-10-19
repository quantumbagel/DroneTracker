"""Camera recording on background threads, so slow or failing recording calls never stall tracking."""
import glob
import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

from tracker.camera import CameraError

log = logging.getLogger("recorder")


class Recorder:
    """
    Starts and stops edge recordings on the camera's disk from a worker thread, then exports each finished recording
    to recording/dir on a separate thread. Exports are written to a .part file and renamed when complete, so
    list_recordings never offers a half-written file. Progress is reported as event dicts on `self.events`.
    """
    ATTEMPTS = 5

    def __init__(self, camera_factory, cfg, sleep=time.sleep):
        self.disk = cfg["camera"]["disk"]
        self.profile = cfg["camera"]["stream_profile"]
        self.directory = cfg["recording"]["dir"]
        self.camera_factory = camera_factory
        self.sleep = sleep
        self.events = queue.Queue()
        self.recording_id = None
        self.session = None
        self._jobs = queue.Queue()
        self._camera = camera_factory()
        self._exports = ThreadPoolExecutor(max_workers=1, thread_name_prefix="export")
        self._pending_exports = set()
        self._pending_lock = threading.Lock()
        self._export_camera = threading.local()
        for partial in glob.glob(os.path.join(self.directory, "*.part")):
            log.warning(f"Removing {partial}, left by an interrupted export (the recording is still on the camera)")
            os.remove(partial)
        self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._thread.start()

    def start(self, session):
        self._jobs.put(("start", session))

    def stop(self):
        self._jobs.put(("stop", None))

    def close(self, timeout=90.0):
        """Stop any recording, then wait (up to `timeout` seconds in all) for pending exports to finish."""
        deadline = time.monotonic() + timeout
        self._jobs.put(("stop", None))
        self._jobs.put(("close", None))
        self._thread.join(timeout)
        with self._pending_lock:
            pending = list(self._pending_exports)
        _, unfinished = wait(pending, timeout=max(0.0, deadline - time.monotonic()))
        if unfinished:
            log.warning(f"Shutting down with {len(unfinished)} export(s) unfinished; the recordings are still on "
                        f"the camera's {self.disk}")
        self._exports.shutdown(wait=False, cancel_futures=True)

    def wait_idle(self, timeout=5.0):
        """Block until queued start/stop jobs and exports are done (for tests and simulations)."""
        done = threading.Event()
        self._jobs.put(("notify", done))
        done.wait(timeout)
        self._exports.submit(lambda: None).result(timeout)

    def _run(self):
        while True:
            job, argument = self._jobs.get()
            if job == "close":
                return
            if job == "notify":
                argument.set()
            elif job == "start":
                self._start(argument)
            elif job == "stop":
                self._stop()

    def _retry(self, action, description):
        for attempt in range(self.ATTEMPTS):
            try:
                return action(), None
            except (CameraError, OSError) as error:
                log.warning(f"{description} failed (attempt {attempt + 1}/{self.ATTEMPTS}): {error}")
                last_error = error
                if attempt + 1 < self.ATTEMPTS:
                    self.sleep(min(2 ** attempt, 10))
        return None, last_error

    def _start(self, session):
        if self.recording_id is not None:
            self._stop()
        recording_id, error = self._retry(lambda: self._camera.start_recording(self.disk, self.profile),
                                          "Starting recording")
        if error:
            self.events.put({"type": "recording_failed", "session": session, "error": str(error)})
            return
        self.recording_id, self.session = recording_id, session
        log.info(f"Recording {recording_id} started for {session}")
        self.events.put({"type": "recording_started", "session": session, "recording_id": recording_id})

    def _stop(self):
        if self.recording_id is None:
            return
        recording_id, session = self.recording_id, self.session
        _, error = self._retry(lambda: self._camera.stop_recording(recording_id), f"Stopping recording {recording_id}")
        self.recording_id = self.session = None
        if error:
            self.events.put({"type": "recording_failed", "session": session, "recording_id": recording_id,
                             "error": f"couldn't stop recording; it may still be running on the camera: {error}"})
            return
        log.info(f"Recording {recording_id} stopped; exporting")
        self.events.put({"type": "recording_stopped", "session": session, "recording_id": recording_id})
        future = self._exports.submit(self._export, session, recording_id)
        with self._pending_lock:
            self._pending_exports.add(future)
        future.add_done_callback(self._export_done)

    def _export_done(self, future):
        with self._pending_lock:
            self._pending_exports.discard(future)

    def _export(self, session, recording_id):
        if not hasattr(self._export_camera, "camera"):
            self._export_camera.camera = self.camera_factory()
        camera = self._export_camera.camera
        path = os.path.join(self.directory, f"{session}.mkv")
        partial = path + ".part"
        os.makedirs(self.directory, exist_ok=True)
        _, error = self._retry(lambda: camera.export_recording(self.disk, recording_id, partial),
                               f"Exporting recording {recording_id}")
        if error is None:
            try:
                os.replace(partial, path)
            except OSError as os_error:
                error = os_error
        if error:
            if os.path.exists(partial):
                os.remove(partial)
            log.error(f"Export of {recording_id} failed; it is still on the camera's {self.disk}: {error}")
            self.events.put({"type": "export_failed", "session": session, "recording_id": recording_id,
                             "error": str(error)})
            return
        log.info(f"Exported recording {recording_id} to {path}")
        self.events.put({"type": "recording_exported", "session": session, "recording_id": recording_id,
                         "file": os.path.basename(path)})
