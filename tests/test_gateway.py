import json
import socket
import threading
import time

import pytest

from tests.conftest import make_config
from tracker.app import App
from tracker.camera import make_camera_factory
from tracker.simulation import FakeClock


class Outbox(list):
    def __call__(self, key, value):
        self.append((key.decode(), value.decode()))

    def replies(self, key):
        return [v for k, v in self if k == key]


@pytest.fixture
def app(tmp_path):
    cfg = make_config(tmp_path)
    outbox = Outbox()
    clock = FakeClock()
    application = App(cfg, make_camera_factory(cfg, clock), send=outbox, clock=clock, recorder_sleep=lambda _: None)
    application.outbox = outbox
    yield application
    application.shutdown()


def test_track_camera_modes(app):
    for mode in ("off", "on", "auto"):
        app.on_command(b"track_camera", mode.encode())
        assert app.mode == mode  # v1 compared bytes to str here, so "off" never took effect
    app.on_command(b"track_camera", b"sideways")
    assert app.mode == "auto"
    assert app.outbox.replies("track_camera") == ["success"] * 3 + ["failure"]


def test_select_and_priority(app):
    app.on_command(b"select", b"ghost")
    app.on_command(b"select", b"none")
    app.on_command(b"priority", b"uav2, uav1")
    assert app.outbox.replies("select") == ["failure", "success"]
    assert app.selector.priority == ["uav2", "uav1"]


def test_status(app):
    app.on_command(b"status", b"")
    status = json.loads(app.outbox.replies("status")[0])
    assert status["mode"] == "auto" and status["tracks"] == {}


def test_unknown_command(app):
    app.on_command(b"self_destruct", b"now")
    assert app.outbox.replies("error") == ["unknown command 'self_destruct'"]


def test_list_recordings_only_lists_finished_files(app):
    directory = app.cfg["recording"]["dir"]
    for name in ("b.mkv", "a.jsonl", "c.mkv.part", "notes.txt"):
        open(f"{directory}/{name}", "w").close()
    app.on_command(b"list_recordings", b"")
    assert app.outbox.replies("list_recordings") == ["a.jsonl\nb.mkv"]


@pytest.mark.parametrize("request_text", ["", "0", "x 127.0.0.1", "5 127.0.0.1", "../config.yml 127.0.0.1",
                                          "0 127.0.0.1;rm${IFS}-rf${IFS}/", "0 127.0.0.1 99999", "0 $(reboot)",
                                          "² 127.0.0.1", "0 127.0.0.1 ²"])
def test_bad_download_requests_fail_safely(app, request_text):
    open(f"{app.cfg['recording']['dir']}/a.mkv", "w").close()
    app.on_command(b"download_recording", request_text.encode())
    assert app.outbox.replies("download_recording") == [f"failure {request_text.split()[0] if request_text else ''}"]


def test_download_streams_the_file(app):
    payload = b"video bytes " * 10000
    with open(f"{app.cfg['recording']['dir']}/a.mkv", "wb") as f:
        f.write(payload)
    server = socket.create_server(("127.0.0.1", 0))
    received = bytearray()

    def receive():
        connection, _ = server.accept()
        with connection:
            while chunk := connection.recv(65536):
                received.extend(chunk)

    receiver = threading.Thread(target=receive)
    receiver.start()
    app.on_command(b"download_recording", f"0 127.0.0.1 {server.getsockname()[1]}".encode())
    receiver.join(5)
    server.close()
    assert bytes(received) == payload
    for _ in range(50):
        if app.outbox.replies("download_recording"):
            break
        time.sleep(0.02)
    assert app.outbox.replies("download_recording") == ["success 0"]
