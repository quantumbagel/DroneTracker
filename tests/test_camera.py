"""VapixCamera against canned HTTP responses."""
import pytest
import requests

from tracker.camera import CameraError, PTZPosition, VapixCamera


class FakeResponse:
    def __init__(self, text="", status=200, chunks=()):
        self.text, self.status_code, self.chunks = text, status, chunks

    def iter_content(self, chunk_size):
        yield from self.chunks


@pytest.fixture
def camera(monkeypatch):
    cam = VapixCamera("10.0.0.5", "user", "pass")
    cam.calls = []
    cam.responses = []

    def get(url, params=None, timeout=None, stream=False):
        cam.calls.append((url, params, timeout))
        response = cam.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(cam.session, "get", get)
    return cam


def test_query_position(camera):
    camera.responses.append(FakeResponse("pan=-12.5\ntilt=3.25\nzoom=4200\niris=1\nautofocus=on\n"))
    assert camera.query_position() == PTZPosition(-12.5, 3.25, 4200)
    url, params, timeout = camera.calls[0]
    assert url == "http://10.0.0.5/axis-cgi/com/ptz.cgi" and params == {"camera": 1, "query": "position"}
    assert timeout == 1.0


def test_continuous_move_parameters(camera):
    camera.responses.append(FakeResponse(status=204))
    camera.continuous_move(12, -3, 0)
    assert camera.calls[0][1] == {"camera": 1, "continuouspantiltmove": "12,-3", "continuouszoommove": 0}


def test_absolute_move_leaves_out_unset_axes(camera):
    camera.responses.append(FakeResponse())
    camera.absolute_move(tilt=-90, zoom=0)
    assert camera.calls[0][1] == {"camera": 1, "tilt": "-90.00", "zoom": 0}


def test_wrong_password_raises_instead_of_exiting(camera):
    # sensecam_control called sys.exit(1) on a 401
    camera.responses.append(FakeResponse("Unauthorized", status=401))
    with pytest.raises(CameraError, match="401"):
        camera.query_position()


def test_timeout_raises_camera_error(camera):
    camera.responses.append(requests.Timeout("read timed out"))
    with pytest.raises(CameraError, match="timed out"):
        camera.stop()


def test_garbage_position_response(camera):
    camera.responses.append(FakeResponse("<html>oops</html>"))
    with pytest.raises(CameraError):
        camera.query_position()


def test_recording_round_trip(camera, tmp_path):
    camera.responses += [FakeResponse('<root><record result="OK" recordingid="20240804_abc"/></root>'),
                         FakeResponse('<root><stop result="OK"/></root>'),
                         FakeResponse(chunks=[b"abc", b"def"])]
    assert camera.start_recording("SD_DISK") == "20240804_abc"
    assert "streamprofile" not in camera.calls[0][1]
    camera.stop_recording("20240804_abc")
    camera.export_recording("SD_DISK", "20240804_abc", tmp_path / "out.mkv")
    assert (tmp_path / "out.mkv").read_bytes() == b"abcdef"


def test_recording_errors(camera):
    camera.responses += [FakeResponse('<root><record result="ERROR" errormsg="No disk"/></root>'),
                         FakeResponse("not xml")]
    with pytest.raises(CameraError, match="No disk"):
        camera.start_recording("SD_DISK")
    with pytest.raises(CameraError, match="unexpected response"):
        camera.stop_recording("x")
