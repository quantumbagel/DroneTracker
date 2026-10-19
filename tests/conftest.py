import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.config import build_config  # noqa: E402
from tracker.geometry import LocalFrame  # noqa: E402
from tracker.messages import Measurement  # noqa: E402

CAMERA = {"lat": 35.727481, "lon": -78.695925, "alt": 85.763}


def make_config(tmp_path, **sections):
    """A valid simulated-camera config; keyword arguments override whole option paths, e.g. auto={"min_height": 0}."""
    raw = {"camera": {"simulate": True, **CAMERA}, "site": {"ref_alt_msl": CAMERA["alt"] - 9},
           "recording": {"dir": str(tmp_path / "recordings")}}
    for section, values in sections.items():
        raw.setdefault(section, {}).update(values)
    return build_config(raw)


@pytest.fixture
def cfg(tmp_path):
    return make_config(tmp_path)


@pytest.fixture
def frame():
    return LocalFrame(CAMERA["lat"], CAMERA["lon"], CAMERA["alt"])


def measurement_at(frame, enu, t, drone_id="uav1", vel_ned=None, received=None):
    lat, lon, alt = frame.to_geodetic(enu)
    return Measurement(drone_id, t, t if received is None else received, lat, lon, alt, vel_ned)
