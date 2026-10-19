"""
Parsing of drone position messages from the Kafka data topic.

v2 message (preferred):
    {"drone_id": "uav1", "t": 1729300000.12,
     "position": {"latitude": 35.72, "longitude": -78.69, "altitude": 120.5, "alt_ref": "msl"},
     "velocity": {"north": 3.1, "east": -0.4, "down": 0.0}}

v1 message (still accepted):
    {"position": {"latitude": ..., "longitude": ..., "altitude": ...}, "velocity": {"x": ..., "y": ..., "z": ...}}
    The v1 velocity axes are ambiguous, so they are interpreted per ingest/legacy_velocity_frame.

drone_id falls back to the Kafka message key, then to "default". t (epoch seconds or milliseconds), alt_ref,
and velocity are optional.
"""
import json
import logging
import math
from dataclasses import dataclass

log = logging.getLogger("messages")

MAX_TRANSIT = 5.0  # s; a timestamp older than this (beyond clock skew) is treated as a clock problem


@dataclass(frozen=True)
class Measurement:
    drone_id: str
    t: float  # when the position was measured (epoch s, on this machine's clock)
    received: float  # when we received it (epoch s)
    lat: float
    lon: float
    alt_msl: float
    vel_ned: tuple | None  # (north, east, down) m/s


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


class MessageParser:
    def __init__(self, cfg):
        self.default_alt_ref = cfg["ingest"]["default_alt_ref"]
        self.legacy_frame = cfg["ingest"]["legacy_velocity_frame"]
        self.max_clock_skew = cfg["ingest"]["max_clock_skew"]
        self.default_latency = cfg["ingest"]["default_latency"]
        self.ref_alt_msl = cfg["site"]["ref_alt_msl"]
        self._clock_warned = set()

    def parse(self, key, value, received):
        """
        :raises ValueError: if the message is not a valid position report
        """
        try:
            body = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as error:
            raise ValueError(f"not JSON: {error}") from None
        if not isinstance(body, dict) or not isinstance(body.get("position"), dict):
            raise ValueError("missing 'position' object")

        drone_id = body.get("drone_id")
        if drone_id is None and key:
            drone_id = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else key
        drone_id = str(drone_id) if drone_id not in (None, "") else "default"

        pos = body["position"]
        lat = _finite(pos.get("latitude"), "position.latitude")
        lon = _finite(pos.get("longitude"), "position.longitude")
        alt = _finite(pos.get("altitude"), "position.altitude")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError(f"position out of range: {lat}, {lon}")

        alt_ref = pos.get("alt_ref", body.get("alt_ref", self.default_alt_ref))
        if alt_ref == "rel":
            if self.ref_alt_msl is None:
                raise ValueError("relative altitude received but site/ref_alt_msl is not configured")
            alt += self.ref_alt_msl
        elif alt_ref != "msl":
            raise ValueError(f"unknown alt_ref {alt_ref!r}")

        return Measurement(drone_id, self._measurement_time(drone_id, body.get("t"), received), received,
                           lat, lon, alt, self._velocity(body.get("velocity")))

    def _velocity(self, vel):
        if vel is None:
            return None
        if not isinstance(vel, dict):
            raise ValueError("velocity must be an object")
        if "north" in vel or "east" in vel or "down" in vel:
            return tuple(_finite(vel.get(k), f"velocity.{k}") for k in ("north", "east", "down"))
        x, y, z = (_finite(vel.get(k), f"velocity.{k}") for k in ("x", "y", "z"))
        if self.legacy_frame == "ned":
            return x, y, z
        if self.legacy_frame == "enu":
            return y, x, -z
        return y, x, z  # "v1": what v1 DroneTracker assumed (x east, y north, z down)

    def _measurement_time(self, drone_id, t, received):
        """
        Use the sender's timestamp when it agrees with our clock (allowing for skew plus up to MAX_TRANSIT seconds
        in transit); otherwise fall back to the receive time less ingest/default_latency.
        """
        fallback = received - self.default_latency
        if t is None:
            return fallback
        t = _finite(t, "t")
        if t > 1e11:  # Milliseconds
            t /= 1000
        age = received - t
        if -self.max_clock_skew <= age <= self.max_clock_skew + MAX_TRANSIT:
            return min(t, received)
        if drone_id not in self._clock_warned:
            self._clock_warned.add(drone_id)
            log.warning(f"Drone {drone_id}: message timestamp is {age:+.1f}s off our clock; using receive time "
                        f"instead. Check NTP on the sender and on this machine.")
        return fallback
