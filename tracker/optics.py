"""Calibration tables: zoom step <-> field of view, and VAPIX speed units <-> angular rate."""
import math

import numpy as np

MAX_ZOOM_STEP = 9999
MAX_SPEED_UNITS = 100


def _pairs(table, name):
    try:
        pairs = sorted((float(a), float(b)) for a, b in table)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a list of [x, y] pairs") from None
    if len(pairs) < 2:
        raise ValueError(f"{name} needs at least two entries")
    xs, ys = (np.array(v) for v in zip(*pairs))
    if np.any(np.diff(xs) <= 0):
        raise ValueError(f"{name} has duplicate entries")
    return xs, ys


class Optics:
    """
    Maps the camera's zoom steps (0-9999) to horizontal field of view.
    Built from a measured table when one is configured, otherwise from the wide-end FOV and maximum optical zoom,
    assuming magnification grows linearly with the step (true for many AXIS PTZs, but worth measuring).
    """

    def __init__(self, zoom_cfg):
        if zoom_cfg.get("table"):
            steps, hfovs = _pairs(zoom_cfg["table"], "camera/zoom/table")
        else:
            wide, max_zoom = float(zoom_cfg["wide_hfov"]), float(zoom_cfg["max_zoom"])
            steps = np.linspace(0, MAX_ZOOM_STEP, 41)
            magnification = 1 + (max_zoom - 1) * steps / MAX_ZOOM_STEP
            hfovs = np.degrees(2 * np.arctan(math.tan(math.radians(wide) / 2) / magnification))
        if np.any(np.diff(hfovs) >= 0):
            raise ValueError("field of view must shrink as the zoom step grows")
        self._steps = steps
        self._hfovs = hfovs

    @property
    def max_hfov(self):
        return float(self._hfovs[0])

    @property
    def min_hfov(self):
        return float(self._hfovs[-1])

    def hfov(self, step):
        return float(np.interp(step, self._steps, self._hfovs))

    def step_for_hfov(self, hfov):
        """The zoom step giving (at least) the requested field of view, clamped to the lens' range."""
        hfov = min(max(hfov, self.min_hfov), self.max_hfov)
        # np.interp needs increasing x, so interpolate over the reversed (increasing-FOV) table
        return int(round(float(np.interp(hfov, self._hfovs[::-1], self._steps[::-1]))))


class SpeedMap:
    """
    Maps an angular rate (deg/s) to VAPIX continuous-move speed units (-100..100) and back.
    Uses a measured [[units, deg_per_s], ...] table when given (see utils/calibrate_speed.py), else a linear map.
    """

    def __init__(self, max_rate, table=None, name="speed table"):
        if table:
            units, rates = _pairs(table, name)
            if units[0] != 0:
                units, rates = np.insert(units, 0, 0.0), np.insert(rates, 0, 0.0)
            if np.any(np.diff(rates) <= 0):
                raise ValueError(f"{name}: rates must increase with speed units")
        else:
            units, rates = np.array([0.0, MAX_SPEED_UNITS]), np.array([0.0, float(max_rate)])
        self._units = units
        self._rates = rates

    @property
    def max_rate(self):
        return float(self._rates[-1])

    def units(self, rate):
        magnitude = float(np.interp(abs(rate), self._rates, self._units))
        return int(math.copysign(min(round(magnitude), MAX_SPEED_UNITS), rate))

    def rate(self, units):
        return math.copysign(float(np.interp(abs(units), self._units, self._rates)), units)
