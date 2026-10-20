"""Per-drone tracks: filtering, freshness, and the auto-activation rules that decide which drones to film."""
import logging

import numpy as np

from tracker.geometry import pointing, wrap360
from tracker.kalman import ConstantVelocityFilter

log = logging.getLogger("tracks")


class Track:
    def __init__(self, drone_id, t, received, enu, vel_enu, tracking_cfg):
        self.id = drone_id
        self.cfg = tracking_cfg
        self.filter = self._new_filter(t, enu, vel_enu)
        self.first_seen = received
        self.last_received = received
        self.updates = 1
        self.active = False
        self.activated_at = None
        self.eligible_since = None
        self.ineligible_since = None

    def _new_filter(self, t, enu, vel_enu):
        return ConstantVelocityFilter(t, enu, vel_enu, accel_noise=self.cfg["accel_noise"],
                                      pos_sigma=self.cfg["pos_sigma"], vel_sigma=self.cfg["vel_sigma"])

    def state_at(self, t):
        """
        Predicted (position, velocity, covariance), extrapolating at most tracking/max_extrapolation seconds.
        Past that the prediction holds still, so its velocity is zero: otherwise the camera would keep panning at the
        drone's last angular rate while aiming at a fixed point, and settle off it.
        """
        limit = self.filter.t + self.cfg["max_extrapolation"]
        pos, vel, cov = self.filter.state_at(min(t, limit))
        return (pos, vel, cov) if t <= limit else (pos, np.zeros(3), cov)

    def age(self, now):
        return now - self.last_received


class TrackManager:
    def __init__(self, cfg, frame):
        self.cfg = cfg
        self.tracking = cfg["tracking"]
        self.auto = cfg["auto"]
        self.frame = frame
        ref = cfg["site"]["ref_alt_msl"]
        # ENU "up" is relative to the lens; this converts it to height above the site reference
        self.height_offset = cfg["camera"]["alt"] - (ref if ref is not None else cfg["camera"]["alt"])
        self.tracks = {}

    def get(self, drone_id):
        return self.tracks.get(drone_id)

    def active(self):
        return [t for t in self.tracks.values() if t.active]

    def ingest(self, m):
        enu = self.frame.to_enu(m.lat, m.lon, m.alt_msl)
        vel_enu = None if m.vel_ned is None else np.array([m.vel_ned[1], m.vel_ned[0], -m.vel_ned[2]])
        track = self.tracks.get(m.drone_id)
        if track is None:
            track = Track(m.drone_id, m.t, m.received, enu, vel_enu, self.tracking)
            self.tracks[m.drone_id] = track
            log.info(f"New drone {m.drone_id} at {self._describe(enu)}")
            return track
        if m.t <= track.filter.t:
            log.debug(f"Drone {m.drone_id}: dropping out-of-order or duplicate message")
            return track

        predicted = track.filter.state_at(m.t)[0]
        jump = float(np.linalg.norm(predicted - enu))
        if jump > self.tracking["gate"]:
            log.warning(f"Drone {m.drone_id}: position jumped {jump:.0f} m from prediction; restarting its filter")
            track.filter = track._new_filter(m.t, enu, vel_enu)
        else:
            track.filter.update(m.t, enu, vel_enu)
        track.last_received = m.received
        track.updates += 1
        return track

    def update(self, now, mode):
        """
        Re-evaluate which tracks are active and forget long-dead ones.
        A track becomes active after being eligible for auto/activate_after seconds, and inactive after being
        ineligible for auto/deactivate_after seconds, so brief dropouts don't stop the recording.
        :return: a list of event dicts describing changes
        """
        events = []
        for track in list(self.tracks.values()):
            if track.age(now) > self.tracking["forget_after"]:
                del self.tracks[track.id]
                log.info(f"Forgetting drone {track.id}")
                if track.active:
                    events.append({"type": "track_inactive", "drone_id": track.id, "reason": "forgotten"})
                continue
            eligible, reason = self.eligibility(track, now, mode)
            if eligible:
                track.ineligible_since = None
                if track.eligible_since is None:
                    track.eligible_since = now
                if not track.active and now - track.eligible_since >= self.auto["activate_after"]:
                    track.active = True
                    track.activated_at = now
                    events.append({"type": "track_active", "drone_id": track.id})
            else:
                track.eligible_since = None
                if track.ineligible_since is None:
                    track.ineligible_since = now
                if track.active and (mode == "off" or now - track.ineligible_since >= self.auto["deactivate_after"]):
                    track.active = False
                    events.append({"type": "track_inactive", "drone_id": track.id, "reason": reason})
        return events

    def eligibility(self, track, now, mode):
        """:return: (eligible, reason it isn't)"""
        if mode == "off":
            return False, "tracking off"
        if track.age(now) > self.tracking["stale_after"]:
            return False, "no recent data"
        if mode == "on":
            return True, None
        pos, _, _ = track.state_at(now)
        view = pointing(pos)
        a = self.auto
        if a["min_height"] is not None and pos[2] + self.height_offset < a["min_height"]:
            return False, "on the ground"
        if a["max_range"] is not None and view.range > a["max_range"]:
            return False, "out of range"
        if a["min_elevation"] is not None and view.el < a["min_elevation"]:
            return False, "below minimum elevation"
        if a["sector"] is not None:
            start, end = a["sector"]
            if wrap360(view.az - start) > wrap360(end - start):
                return False, "outside visible sector"
        return True, None

    def _describe(self, enu):
        view = pointing(enu)
        return (f"az {view.az:.1f}°, el {view.el:.1f}°, range {view.range:.0f} m, "
                f"height {enu[2] + self.height_offset:.1f} m")
