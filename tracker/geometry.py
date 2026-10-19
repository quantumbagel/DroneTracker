"""
Coordinate conversion and pointing geometry.

Positions are handled in a local East/North/Up frame (metres) centred on the camera lens. That keeps the pointing
math planar: azimuth is atan2(east, north) and elevation is atan2(up, horizontal range), with no quadrant fix-ups.
Angles are in degrees unless a name says otherwise.
"""
import math
from dataclasses import dataclass

import numpy as np

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)


def wrap180(angle):
    """Wrap an angle to [-180, 180)."""
    return (angle + 180.0) % 360.0 - 180.0


def wrap360(angle):
    """Wrap an angle to [0, 360)."""
    return angle % 360.0


def geodetic_to_ecef(lat, lon, alt):
    lat_r, lon_r = math.radians(lat), math.radians(lon)
    sin_lat = math.sin(lat_r)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)
    return np.array([(n + alt) * math.cos(lat_r) * math.cos(lon_r),
                     (n + alt) * math.cos(lat_r) * math.sin(lon_r),
                     (n * (1 - WGS84_E2) + alt) * sin_lat])


def ecef_to_geodetic(x, y, z):
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - WGS84_E2))
    alt = 0.0
    for _ in range(6):  # Converges to sub-millimetre in a few iterations away from the poles
        n = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(lat) ** 2)
        alt = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - WGS84_E2 * n / (n + alt)))
    return math.degrees(lat), math.degrees(lon), alt


class LocalFrame:
    """An East/North/Up frame (metres) with its origin at the camera lens."""

    def __init__(self, lat, lon, alt):
        self.lat, self.lon, self.alt = lat, lon, alt
        self._origin = geodetic_to_ecef(lat, lon, alt)
        lat_r, lon_r = math.radians(lat), math.radians(lon)
        sl, cl, so, co = math.sin(lat_r), math.cos(lat_r), math.sin(lon_r), math.cos(lon_r)
        self._rot = np.array([[-so, co, 0.0],
                              [-sl * co, -sl * so, cl],
                              [cl * co, cl * so, sl]])

    def to_enu(self, lat, lon, alt):
        return self._rot @ (geodetic_to_ecef(lat, lon, alt) - self._origin)

    def to_geodetic(self, enu):
        return ecef_to_geodetic(*(self._rot.T @ np.asarray(enu, dtype=float) + self._origin))


@dataclass(frozen=True)
class Pointing:
    az: float  # clockwise from true north, [-180, 180)
    el: float  # above the horizontal
    az_rate: float  # deg/s
    el_rate: float  # deg/s
    range: float  # slant range, metres


def pointing(pos, vel=(0.0, 0.0, 0.0), min_horizontal=1.0):
    """
    Where to point to see an ENU position, and how fast that direction is changing given an ENU velocity.
    :param min_horizontal: below this horizontal range (m) the target is treated as overhead and the azimuth rate
     is reported as 0, since azimuth is undefined directly above the camera
    """
    e, n, u = (float(v) for v in pos)
    ve, vn, vu = (float(v) for v in vel)
    r2 = e * e + n * n
    r = math.sqrt(r2)
    slant2 = r2 + u * u
    az = wrap180(math.degrees(math.atan2(e, n)))
    el = math.degrees(math.atan2(u, r))
    az_rate = math.degrees((n * ve - e * vn) / r2) if r >= min_horizontal else 0.0
    r_dot = (e * ve + n * vn) / r if r > 0 else 0.0
    el_rate = math.degrees((r * vu - u * r_dot) / slant2) if slant2 > 0 else 0.0
    return Pointing(az, el, az_rate, el_rate, math.sqrt(slant2))


def angular_size(size, distance):
    """The angle (deg) subtended by an object `size` metres across at `distance` metres."""
    return math.degrees(2 * math.atan2(size / 2, max(distance, 1e-6)))
