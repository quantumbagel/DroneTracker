"""
Parsing of drone position messages from the Kafka data topic:

    {"drone_id": "uav1", "t": 1729300000.12,
     "position": {"latitude": 35.72, "longitude": -78.69, "altitude": 120.5, "alt_ref": "msl"},
     "velocity": {"north": 3.1, "east": -0.4, "down": 0.0}}

v1 messages, whose velocity is {"x", "y", "z"} on ambiguous axes, are rejected.

drone_id falls back to the Kafka message key, then to "default". t (epoch seconds or milliseconds), alt_ref,
and velocity are optional. Without t, the Kafka record's timestamp stands in for it. An invalid velocity is ignored
(with a warning), rather than costing a valid position.
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
        self.max_clock_skew = cfg["ingest"]["max_clock_skew"]
        self.default_latency = cfg["ingest"]["default_latency"]
        self.ref_alt_msl = cfg["site"]["ref_alt_msl"]
        self._clock_warned = set()
        self._velocity_warned = set()

    def parse(self, key, value, received, sent=None):
        """
        :param sent: the Kafka record timestamp (epoch s), used as the measurement time when the body has no t
        :raises ValueError: if the message is not a valid position report
        """
        try:
            body = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as error:
            raise ValueError(f"not JSON: {error}") from None
        if not isinstance(body, dict) or not isinstance(body.get("position"), dict):
            raise ValueError("missing 'position' object")

        drone_id = body.get("drone_id")
        if drone_id in (None, "") and key:
            drone_id = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else key
        drone_id = str(drone_id) if drone_id not in (None, "") else "default"

        pos = body["position"]
        lat = _finite(pos.get("latitude"), "position.latitude")
        lon = _finite(pos.get("longitude"), "position.longitude")
        alt = _finite(pos.get("altitude"), "position.altitude")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError(f"position out of range: {lat}, {lon}")

        alt_ref = pos.get("alt_ref", body.get("alt_ref", self.default_alt_ref))
        alt_ref = alt_ref.lower() if isinstance(alt_ref, str) else alt_ref
        if alt_ref == "rel":
            if self.ref_alt_msl is None:
                raise ValueError("relative altitude received but site/ref_alt_msl is not configured")
            alt += self.ref_alt_msl
        elif alt_ref != "msl":
            raise ValueError(f"unknown alt_ref {alt_ref!r}")

        velocity = body.get("velocity")
        if isinstance(velocity, dict) and not {"north", "east", "down"} & velocity.keys() \
                and {"x", "y", "z"} & velocity.keys():
            raise ValueError("v1 message (velocity {x, y, z}) is not supported; send velocity {north, east, down}")
        try:
            vel_ned = self._velocity(velocity)
        except ValueError as error:
            vel_ned = None
            if drone_id not in self._velocity_warned:
                self._velocity_warned.add(drone_id)
                log.warning(f"Drone {drone_id}: ignoring invalid velocity ({error}); using its positions only")
        t = body.get("t")
        return Measurement(drone_id, self._measurement_time(drone_id, sent if t is None else t, received), received,
                           lat, lon, alt, vel_ned)

    def _velocity(self, vel):
        if vel is None:
            return None
        if not isinstance(vel, dict):
            raise ValueError("velocity must be an object")
        return tuple(_finite(vel.get(k), f"velocity.{k}") for k in ("north", "east", "down"))

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
