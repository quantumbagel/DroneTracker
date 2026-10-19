import logging

import numpy as np
import pytest

from tests.conftest import make_config, measurement_at
from tracker.geometry import LocalFrame
from tracker.tracks import TrackManager

T0 = 1_700_000_000.0
AIRBORNE = (0, 200, 40)
GROUND = (0, 200, -9)  # The fixture's lens is 9 m above ref_alt_msl


def manager(tmp_path, **sections):
    cfg = make_config(tmp_path, **sections)
    cam = cfg["camera"]
    frame = LocalFrame(cam["lat"], cam["lon"], cam["alt"])
    return TrackManager(cfg, frame), frame


def feed(tracks, frame, pos, start, end, mode="auto", hz=5, drone_id="uav1", vel=(0, 0, 0)):
    """Report a drone at pos (moving at ENU vel) from start to end, updating the manager every message."""
    events = []
    for i in range(int((end - start) * hz)):
        t = start + i / hz
        enu = np.array(pos, float) + np.array(vel, float) * (t - T0)
        tracks.ingest(measurement_at(frame, enu, t, drone_id, vel_ned=(vel[1], vel[0], -vel[2])))
        events += tracks.update(t, mode)
    return events


def test_airborne_drone_activates_after_delay(tmp_path):
    tracks, frame = manager(tmp_path)
    feed(tracks, frame, AIRBORNE, T0, T0 + 1.5)
    assert not tracks.get("uav1").active
    events = feed(tracks, frame, AIRBORNE, T0 + 1.5, T0 + 3)
    assert tracks.get("uav1").active
    assert {"type": "track_active", "drone_id": "uav1"} in events


def test_drone_on_the_ground_is_ignored_in_auto_but_tracked_in_on(tmp_path):
    tracks, frame = manager(tmp_path)
    feed(tracks, frame, GROUND, T0, T0 + 5)
    assert not tracks.get("uav1").active
    assert tracks.eligibility(tracks.get("uav1"), T0 + 5, "auto") == (False, "on the ground")
    feed(tracks, frame, GROUND, T0 + 5, T0 + 10, mode="on")
    assert tracks.get("uav1").active


def test_brief_dropout_keeps_tracking_but_long_one_stops(tmp_path):
    tracks, frame = manager(tmp_path)
    feed(tracks, frame, AIRBORNE, T0, T0 + 5)
    assert tracks.update(T0 + 8, "auto") == []  # Stale for 3 s: ineligible, but within deactivate_after
    assert tracks.get("uav1").active
    feed(tracks, frame, AIRBORNE, T0 + 8, T0 + 9)
    assert tracks.update(T0 + 12, "auto") == []
    events = tracks.update(T0 + 17.5, "auto")
    assert events == [{"type": "track_inactive", "drone_id": "uav1", "reason": "no recent data"}]


def test_off_deactivates_immediately(tmp_path):
    tracks, frame = manager(tmp_path)
    feed(tracks, frame, AIRBORNE, T0, T0 + 5)
    assert tracks.update(T0 + 5, "off")[0]["type"] == "track_inactive"


def test_tracks_are_forgotten(tmp_path):
    tracks, frame = manager(tmp_path)
    feed(tracks, frame, AIRBORNE, T0, T0 + 1)
    tracks.update(T0 + 100, "auto")
    assert tracks.get("uav1") is None


@pytest.mark.parametrize("sections, pos, reason", [
    ({"auto": {"max_range": 100}}, (0, 200, 40), "out of range"),
    ({"auto": {"min_elevation": 20}}, (0, 200, 40), "below minimum elevation"),
    ({"auto": {"sector": [90, 270]}}, (0, 200, 40), "outside visible sector"),
    ({"auto": {"sector": [270, 90]}}, (0, -200, 40), "outside visible sector"),
])
def test_auto_gates(tmp_path, sections, pos, reason):
    tracks, frame = manager(tmp_path, **sections)
    feed(tracks, frame, pos, T0, T0 + 5)
    assert tracks.eligibility(tracks.get("uav1"), T0 + 5, "auto") == (False, reason)


def test_sector_wrapping_through_north(tmp_path):
    tracks, frame = manager(tmp_path, auto={"sector": [270, 90]})
    feed(tracks, frame, (50, 200, 40), T0, T0 + 5)
    assert tracks.get("uav1").active


def test_out_of_order_messages_are_dropped(tmp_path):
    tracks, frame = manager(tmp_path)
    tracks.ingest(measurement_at(frame, (0, 100, 40), T0 + 1))
    tracks.ingest(measurement_at(frame, (0, 900, 40), T0 + 0.5))
    assert tracks.get("uav1").filter.position == pytest.approx([0, 100, 40], abs=0.01)


def test_position_jump_restarts_filter(tmp_path):
    tracks, frame = manager(tmp_path)
    feed(tracks, frame, AIRBORNE, T0, T0 + 2)
    tracks.ingest(measurement_at(frame, (500, 500, 40), T0 + 2.2))
    assert tracks.get("uav1").filter.position == pytest.approx([500, 500, 40], abs=0.01)


def test_swapped_velocity_axes_are_detected(tmp_path, caplog):
    tracks, frame = manager(tmp_path)
    with caplog.at_level(logging.WARNING):
        for i in range(60):  # Flying east at 10 m/s but reporting the velocity as if north
            t = T0 + i * 0.2
            tracks.ingest(measurement_at(frame, (10 * i * 0.2, 200, 40), t, vel_ned=(10, 0, 0)))
    assert not tracks.get("uav1").use_velocity
    assert "axes look swapped" in caplog.text


def test_correct_velocities_are_kept(tmp_path):
    tracks, frame = manager(tmp_path)
    feed(tracks, frame, AIRBORNE, T0, T0 + 12, vel=(10, 0, 2))
    assert tracks.get("uav1").use_velocity
