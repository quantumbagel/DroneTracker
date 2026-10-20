import os

import pytest

from tests.conftest import CAMERA
from tracker.config import ConfigError, build_config, load_config, parse_coordinate

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def minimal(**camera):
    return {"camera": {"simulate": True, **CAMERA, **camera}}


@pytest.mark.parametrize("value, kind, expected", [
    (35.727481, "lat", 35.727481),
    ("-78.695925", "lon", -78.695925),
    ("35°43'38.9\"N", "lat", 35 + 43 / 60 + 38.9 / 3600),
    ("78 41'45.3\"W", "lon", -(78 + 41 / 60 + 45.3 / 3600)),  # Degree sign lost in a paste
    ("33°51'31.0\"S", "lat", -(33 + 51 / 60 + 31 / 3600)),
])
def test_parse_coordinate(value, kind, expected):
    assert parse_coordinate(value, kind) == pytest.approx(expected)


@pytest.mark.parametrize("value, kind", [("35°43'38.9\"E", "lat"), ("north", "lat"), (95, "lat"), (None, "lon")])
def test_bad_coordinates(value, kind):
    with pytest.raises(ConfigError):
        parse_coordinate(value, kind)


def test_repository_config_loads():
    cfg = load_config(os.path.join(REPO, "config.yml"))
    assert cfg["camera"]["ip"] == "192.168.60.101"
    assert cfg["kafka"]["servers"] == ["192.168.60.202:9092"]


def test_defaults_fill_in():
    cfg = build_config(minimal())
    assert cfg["control"]["hz"] == 10
    assert cfg["auto"]["startup_mode"] == "auto"


def test_unknown_option_is_rejected():
    with pytest.raises(ConfigError, match="unknown option 'camera/lead'"):
        build_config(minimal(lead=0))


def test_camera_ip_required_for_real_camera():
    with pytest.raises(ConfigError, match="camera/ip"):
        build_config(minimal(simulate=False))


def test_bare_kafka_host_gets_default_port():
    cfg = build_config({**minimal(), "kafka": {"servers": "10.0.0.1"}})
    assert cfg["kafka"]["servers"] == ["10.0.0.1:9092"]


def test_password_from_environment(monkeypatch):
    monkeypatch.setenv("DRONETRACKER_CAMERA_PASSWORD", "hunter2")
    assert build_config(minimal())["camera"]["password"] == "hunter2"


@pytest.mark.parametrize("raw, message", [
    ({"control": {"mode": "warp"}}, "control/mode"),
    ({"framing": {"target_fraction": 2}}, "framing/target_fraction"),
    ({"camera": {**CAMERA, "simulate": True, "tilt_limits": [45, -90]}}, "tilt_limits"),
    ({"camera": {**CAMERA, "simulate": True, "zoom": {"table": [[0, 1], [10, 2]]}}}, "field of view"),
    ({"ingest": {"default_alt_ref": "rel"}}, "ref_alt_msl"),
    ({"logs": "verbose"}, "logs"),
])
def test_validation_errors(raw, message):
    with pytest.raises(ConfigError, match=message):
        build_config({**minimal(), **raw})


def test_full_circle_sector_means_no_sector():
    assert build_config({**minimal(), "auto": {"sector": [0, 360]}})["auto"]["sector"] is None
    assert build_config({**minimal(), "auto": {"sector": [300, 60]}})["auto"]["sector"] == [300, 60]
