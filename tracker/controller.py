"""Turns an Aim into PTZ commands."""
import logging
import math

from tracker.camera import CameraError
from tracker.geometry import wrap180
from tracker.optics import MAX_SPEED_UNITS, Optics, SpeedMap

log = logging.getLogger("controller")

ZOOM_OUT_DEADBAND = 0.02  # Log-ratio of FOV: start zooming out once the shot is ~2% too tight


def _clamp(value, lo, hi):
    return min(max(value, lo), hi)


class PTZController:
    """
    velocity mode (default): every tick reads the camera's actual position, then commands continuous pan/tilt
    speeds of (target's angular rate) + kp * (pointing error). The rate term keeps the camera moving with the drone
    and the error term removes drift, so it glides instead of jumping min_step degrees at a time. Zoom is driven
    the same way towards the step that gives the required field of view.

    position mode: absolute moves to the predicted position, with the speed chosen to arrive within one tick.
    A fallback for cameras whose continuous moves misbehave.

    Camera pan = azimuth + camera/offset (wrapped), i.e. the offset is the camera pan that looks true north.
    """

    def __init__(self, camera, cfg):
        cam, ctl = cfg["camera"], cfg["control"]
        self.camera = camera
        self.offset = cam["offset"]
        self.tilt_min, self.tilt_max = cam["tilt_limits"]
        self.park_pan, self.park_tilt = cam["park"]["pan"], cam["park"]["tilt"]
        self.park_after = cam["park_after"]
        self.optics = Optics(cam["zoom"])
        self.pan_speed = SpeedMap(cam["speed"]["pan_max"], cam["speed"]["pan_table"])
        self.tilt_speed = SpeedMap(cam["speed"]["tilt_max"], cam["speed"]["tilt_table"])
        self.mode = ctl["mode"]
        self.period = 1 / ctl["hz"]
        self.lookahead = ctl["lookahead"]
        self.kp = ctl["kp"]
        self.deadband = ctl["deadband"]
        self.kz = ctl["kz"]
        self.zoom_deadband = ctl["zoom_deadband"]
        self.min_step = ctl["min_step"]

        self.position = None  # Last PTZPosition read from the camera
        self.error = None  # Last (azimuth, elevation) pointing error, deg
        # Last continuous-move speeds the camera accepted; None when unknown (a move or stop may have failed after
        # the camera acted on it), which forces the next tick to send a command
        self.commanded = (0, 0, 0)
        self.last_absolute = None  # Last (pan, tilt, zoom) sent in position mode
        self.idle_since = None
        self.parked = False
        self.failures = 0

    def camera_pan(self, az):
        return wrap180(az + self.offset)

    def azimuth(self, pan):
        return wrap180(pan - self.offset)

    def track(self, aim, now):
        self.idle_since = None
        self.parked = False
        try:
            if self.mode == "velocity":
                self._track_velocity(aim)
            else:
                self._track_position(aim)
        except CameraError as error:
            self._failed(error)
        else:
            self._recovered()

    def _track_velocity(self, aim):
        pos = self.camera.query_position()
        self.position = pos
        # Compare where the camera will be when this command lands (assuming it holds its current speed) with
        # where the drone will be then; the aim was predicted `lookahead` seconds ahead
        pan_now, tilt_now, _ = self.commanded or (0, 0, 0)
        cam_az = self.azimuth(pos.pan) + self.pan_speed.rate(pan_now) * self.lookahead
        cam_el = pos.tilt + self.tilt_speed.rate(tilt_now) * self.lookahead
        target_el = _clamp(aim.el, self.tilt_min, self.tilt_max)
        err_az = wrap180(aim.az - cam_az)
        err_el = target_el - cam_el
        self.error = (err_az, err_el)

        pan_rate = aim.az_rate + self._correction(err_az)
        tilt_rate = (aim.el_rate if self.tilt_min < aim.el < self.tilt_max else 0.0) + self._correction(err_el)
        if (pos.tilt <= self.tilt_min and tilt_rate < 0) or (pos.tilt >= self.tilt_max and tilt_rate > 0):
            tilt_rate = 0.0

        command = (self.pan_speed.units(pan_rate), self.tilt_speed.units(tilt_rate), self._zoom_speed(aim, pos))
        if command != self.commanded:
            self._send_speeds(command)

    def _zoom_speed(self, aim, pos):
        """
        Continuous zoom speed towards the needed field of view. The error is the log of the FOV ratio, since a
        given step change matters far more at the wide end. Zooming out (a drone may be leaving the frame) reacts
        almost immediately; zooming in waits until the shot is zoom_deadband too wide, so the zoom doesn't hunt.
        """
        needed = min(max(aim.hfov, self.optics.min_hfov), self.optics.max_hfov)
        error = math.log(needed / self.optics.hfov(pos.zoom))  # > 0: too tight, zoom out
        if -math.log1p(self.zoom_deadband) < error < ZOOM_OUT_DEADBAND:
            return 0
        return int(_clamp(round(-self.kz * error), -MAX_SPEED_UNITS, MAX_SPEED_UNITS))

    def _correction(self, error):
        """Proportional correction with a soft deadband: continuous at the edge, so it can't chatter on/off."""
        excess = abs(error) - self.deadband
        return math.copysign(self.kp * excess, error) if excess > 0 else 0.0

    def _track_position(self, aim):
        pan = self.camera_pan(aim.az)
        tilt = _clamp(aim.el, self.tilt_min, self.tilt_max)
        zoom = self.optics.step_for_hfov(aim.hfov)
        rate = self.pan_speed.max_rate
        if self.last_absolute is not None:
            last_pan, last_tilt, last_zoom = self.last_absolute
            d_pan, d_tilt = abs(wrap180(pan - last_pan)), abs(tilt - last_tilt)
            zoom_change = abs(math.log(self.optics.hfov(zoom) / self.optics.hfov(last_zoom)))
            if d_pan < self.min_step and d_tilt < self.min_step and zoom_change < math.log1p(self.zoom_deadband):
                return
            rate = max(d_pan, d_tilt) / self.period
        speed = max(1, self.pan_speed.units(max(rate, abs(aim.az_rate), abs(aim.el_rate))))
        self.camera.absolute_move(pan, tilt, zoom, speed)
        self.last_absolute = (pan, tilt, zoom)

    def _send_speeds(self, speeds):
        self.commanded = None  # Unknown until the camera confirms
        self.camera.continuous_move(*speeds)
        self.commanded = speeds

    def idle(self, now, park_now=False):
        """Called on ticks with nothing to film: stop moving, then park after camera/park_after seconds."""
        if self.idle_since is None:
            self.idle_since = now
            self.last_absolute = None
        try:
            if self.commanded != (0, 0, 0):
                self._send_speeds((0, 0, 0))
            if not self.parked and (park_now or now - self.idle_since >= self.park_after):
                self.park()
        except CameraError as error:
            self._failed(error)
        else:
            self._recovered()

    def park(self):
        """Point at the configured park position (camera/park), zoomed out so new drones are easy to pick up."""
        pan = None if self.park_pan is None else self.camera_pan(self.park_pan)
        log.info(f"Parking camera at pan {pan}, tilt {self.park_tilt}")
        self.camera.absolute_move(pan=pan, tilt=self.park_tilt, zoom=0)
        self.parked = True
        self.last_absolute = None

    def shutdown(self):
        try:
            self._send_speeds((0, 0, 0))
            self.park()
        except CameraError as error:
            log.error(f"Couldn't stop/park the camera on shutdown: {error}")

    def _failed(self, error):
        self.failures += 1
        if self.failures == 1 or self.failures % 50 == 0:
            log.warning(f"Camera command failed ({self.failures} in a row): {error}")
        if self.commanded != (0, 0, 0):
            # Don't leave the camera spinning on a stale command while we can't steer it
            try:
                self._send_speeds((0, 0, 0))
            except CameraError:
                pass

    def _recovered(self):
        if self.failures:
            log.info(f"Camera responding again after {self.failures} failed commands")
            self.failures = 0

    def status(self):
        pos = self.position
        return {"mode": self.mode,
                "position": None if pos is None else {"pan": pos.pan, "tilt": pos.tilt, "zoom": pos.zoom,
                                                      "azimuth": self.azimuth(pos.pan),
                                                      "hfov": self.optics.hfov(pos.zoom)},
                "error": self.error, "speeds": self.commanded, "parked": self.parked, "failures": self.failures}
