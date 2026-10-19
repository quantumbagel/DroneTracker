"""Choosing which drone(s) the camera should look at, and how wide the shot must be to hold them."""
import math
from dataclasses import dataclass

import numpy as np

from tracker.geometry import angular_size, pointing, wrap180

GROUP_HYSTERESIS = 1.15  # A drone already in the shot stays until the shot needs 15% more than max_group_hfov


@dataclass(frozen=True)
class TargetView:
    """One drone as seen from the camera at a given time."""
    drone_id: str
    az: float
    el: float
    az_rate: float
    el_rate: float
    range: float
    size: float  # angular size of the drone, deg
    uncertainty: float  # angular position uncertainty (1 sigma), deg
    activated_at: float


@dataclass(frozen=True)
class Aim:
    """Where the camera should point and how wide the shot should be."""
    drone_ids: tuple
    az: float
    el: float
    az_rate: float
    el_rate: float
    hfov: float  # required horizontal field of view, deg
    range: float  # to the nearest target, m


def view_track(track, t, drone_size):
    pos, vel, cov = track.state_at(t)
    view = pointing(pos, vel)
    sigma = math.sqrt(max(np.trace(cov[:3, :3]) / 3, 0.0))
    return TargetView(track.id, view.az, view.el, view.az_rate, view.el_rate, view.range,
                      angular_size(drone_size, view.range), math.degrees(math.atan2(sigma, max(view.range, 1.0))),
                      track.activated_at or 0.0)


def frame(views, framing):
    """Compute an Aim that holds every view in shot."""
    k = framing["uncertainty_k"]
    margin = 2 * k * max(v.uncertainty for v in views)
    if len(views) == 1:
        v = views[0]
        return Aim((v.drone_id,), v.az, v.el, v.az_rate, v.el_rate,
                   max(v.size / framing["target_fraction"] + margin, framing["min_hfov"]), v.range)

    # Azimuths relative to the first view, so the spread is computed correctly across the ±180° seam
    base = views[0].az
    rel = [wrap180(v.az - base) for v in views]
    az_lo = min(r - v.size / 2 for r, v in zip(rel, views))
    az_hi = max(r + v.size / 2 for r, v in zip(rel, views))
    el_lo = min(v.el - v.size / 2 for v in views)
    el_hi = max(v.el + v.size / 2 for v in views)
    el_center = (el_lo + el_hi) / 2
    # Azimuth differences shrink in the image as the camera looks up
    width = (az_hi - az_lo) * math.cos(math.radians(min(abs(el_center), 89.0)))
    height = el_hi - el_lo
    spread = max(width, height * framing["aspect"]) / framing["group_fill"]
    # Never tighter than the largest drone would get on its own
    hfov = max(max(spread, max(v.size for v in views) / framing["target_fraction"]) + margin, framing["min_hfov"])
    return Aim(tuple(v.drone_id for v in views), wrap180(base + (az_lo + az_hi) / 2), el_center,
               sum(v.az_rate for v in views) / len(views), sum(v.el_rate for v in views) / len(views),
               hfov, min(v.range for v in views))


class TargetSelector:
    """
    Picks the drone(s) to film, in this order:
    1. a drone manually selected over Kafka, if it's being tracked;
    2. otherwise a primary drone: the best ranked in framing/priority, then the earliest activated, but the current
       primary is kept unless a strictly higher-priority drone appears (so the camera doesn't flip-flop);
    3. other drones are added to the shot, by rank, while they all fit within framing/max_group_hfov.
    """

    def __init__(self, framing):
        self.framing = framing
        self.priority = list(framing["priority"])
        self.manual = None
        self.current = ()

    def rank(self, view):
        tier = self.priority.index(view.drone_id) if view.drone_id in self.priority else len(self.priority)
        return tier, view.activated_at, view.drone_id

    def select(self, views):
        """
        :param views: {drone_id: TargetView} of the drones that may be filmed
        :return: tuple of drone ids to frame, primary first
        """
        if self.manual is not None and self.manual in views:
            self.current = (self.manual,)
            return self.current
        if not views:
            self.current = ()
            return self.current

        ranked = sorted(views.values(), key=self.rank)
        primary = ranked[0]
        if self.current and self.current[0] in views:
            incumbent = views[self.current[0]]
            if self.rank(incumbent)[0] <= self.rank(primary)[0]:
                primary = incumbent

        chosen = [primary]
        if self.framing["group"]:
            for view in ranked:
                if view is primary:
                    continue
                limit = self.framing["max_group_hfov"] * (GROUP_HYSTERESIS if view.drone_id in self.current else 1.0)
                if frame(chosen + [view], self.framing).hfov <= limit:
                    chosen.append(view)
        self.current = tuple(v.drone_id for v in chosen)
        return self.current
