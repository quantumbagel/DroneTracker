import json
import logging

import pytest

from tests.conftest import make_config
from tracker.messages import MessageParser

NOW = 1_700_000_000.0


def encode(body):
    return json.dumps(body).encode()


def position(alt=100.0, **extra):
    return {"latitude": 35.73, "longitude": -78.69, "altitude": alt, **extra}


@pytest.fixture
def parser(cfg):
    return MessageParser(cfg)


def test_v2_message(parser):
    m = parser.parse(None, encode({"drone_id": "uav7", "t": NOW - 0.2, "position": position(),
                                   "velocity": {"north": 1, "east": 2, "down": 3}}), NOW)
    assert (m.drone_id, m.t, m.alt_msl, m.vel_ned) == ("uav7", NOW - 0.2, 100.0, (1, 2, 3))


def test_drone_id_falls_back_to_key_then_default(parser):
    assert parser.parse(b"uav2", encode({"position": position()}), NOW).drone_id == "uav2"
    assert parser.parse(None, encode({"position": position()}), NOW).drone_id == "default"


@pytest.mark.parametrize("frame, expected", [("ned", (1, 2, 3)), ("enu", (2, 1, -3)), ("v1", (2, 1, 3))])
def test_legacy_velocity_frames(tmp_path, frame, expected):
    parser = MessageParser(make_config(tmp_path, ingest={"legacy_velocity_frame": frame}))
    m = parser.parse(None, encode({"position": position(), "velocity": {"x": 1, "y": 2, "z": 3}}), NOW)
    assert m.vel_ned == expected


def test_millisecond_timestamps(parser):
    assert parser.parse(None, encode({"t": (NOW - 0.5) * 1000, "position": position()}), NOW).t == pytest.approx(NOW - 0.5)


def test_skewed_clock_falls_back_to_receive_time(parser, caplog):
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert parser.parse(None, encode({"t": NOW - 60, "position": position()}), NOW).t == NOW
    assert len([r for r in caplog.records if "off our clock" in r.message]) == 1


def test_default_latency_backdates_untimestamped_messages(tmp_path):
    parser = MessageParser(make_config(tmp_path, ingest={"default_latency": 0.2}))
    assert parser.parse(None, encode({"position": position()}), NOW).t == pytest.approx(NOW - 0.2)


def test_relative_altitude(tmp_path):
    parser = MessageParser(make_config(tmp_path, site={"ref_alt_msl": 70.0}))
    m = parser.parse(None, encode({"position": position(alt=30.0, alt_ref="rel")}), NOW)
    assert m.alt_msl == 100.0


def test_relative_altitude_requires_a_reference(tmp_path):
    parser = MessageParser(make_config(tmp_path, site={"ref_alt_msl": None}))
    with pytest.raises(ValueError, match="ref_alt_msl"):
        parser.parse(None, encode({"position": position(alt_ref="rel")}), NOW)


@pytest.mark.parametrize("value", [b"not json", b"[]", encode({}), encode({"position": {"latitude": 1}}),
                                   encode({"position": position(alt=float("nan"))}),
                                   encode({"position": {"latitude": 95, "longitude": 0, "altitude": 0}}),
                                   encode({"position": position(), "velocity": {"x": "fast"}}),
                                   encode({"position": position(alt_ref="agl")})])
def test_invalid_messages_raise_value_error(parser, value):
    with pytest.raises(ValueError):
        parser.parse(None, value, NOW)
