"""
Measure how fast the camera actually pans and tilts at each VAPIX speed setting, and print tables to paste into
config.yml (camera/speed/pan_table and tilt_table). Velocity-mode tracking leans on these numbers.

The camera WILL move: it pans back and forth around its current position and tilts across its tilt range.
Before running, turn off "proportional speed" (zoom-dependent speed) in the camera's PTZ settings if it has it,
since that scales continuous-move speeds by the zoom level.

    python utils/calibrate_speed.py
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.camera import VapixCamera  # noqa: E402
from tracker.config import load_config  # noqa: E402
from tracker.geometry import wrap180  # noqa: E402

SPEEDS = [1, 2, 3, 5, 8, 12, 20, 30, 45, 60, 80, 100]


def measure(camera, axis, units, seconds, direction):
    """:return: measured deg/s while moving at `units` along axis ("pan" or "tilt")"""
    move = (units * direction, 0) if axis == "pan" else (0, units * direction)
    camera.continuous_move(*move, 0)
    time.sleep(0.3)  # Let it get up to speed
    start, t0 = camera.query_position(), time.time()
    time.sleep(seconds)
    end, t1 = camera.query_position(), time.time()
    camera.stop()
    moved = wrap180(end.pan - start.pan) if axis == "pan" else end.tilt - start.tilt
    return abs(moved) / (t1 - t0)


def monotonic(rows, axis):
    """
    Drop measurements that aren't faster than the one before (the camera not moving at all at the lowest speeds,
    or measurement noise), since camera/speed tables must increase.
    """
    kept = []
    for units, rate in rows:
        if rate > (kept[-1][1] if kept else 0.0):
            kept.append([units, rate])
        else:
            print(f"Leaving {axis} speed {units} ({rate} deg/s) out of the table: not faster than the speed below it")
    return kept


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "..", "config.yml"))
    parser.add_argument("--max-sweep", type=float, default=40.0, help="degrees to move in each measurement")
    args = parser.parse_args()
    cam = load_config(args.config)["camera"]
    camera = VapixCamera(cam["ip"], cam["username"], cam["password"], timeout=3.0)
    tilt_lo, tilt_hi = cam["tilt_limits"]

    tables = {}
    for axis in ("pan", "tilt"):
        camera.absolute_move(tilt=-30, zoom=0)
        time.sleep(3)
        rows, direction, estimate = [], 1, None
        for units in SPEEDS:
            # Size each run so the camera sweeps about max_sweep degrees, within 0.3-20 s
            seconds = 5.0 if estimate is None else min(max(args.max_sweep / (estimate * units), 0.3), 20.0)
            if axis == "tilt":  # Start at one end of the tilt range and sweep towards the other
                camera.absolute_move(tilt=tilt_lo + 5 if direction > 0 else tilt_hi - 5)
                time.sleep(3)
            rate = measure(camera, axis, units, seconds, direction)
            estimate = rate / units if rate > 0 else None
            rows.append([units, round(rate, 3)])
            print(f"{axis} speed {units:3}: {rate:7.3f} deg/s")
            direction = -direction
        tables[axis] = monotonic(rows, axis)

    print("\nPaste into config.yml under camera/speed:")
    for axis in ("pan", "tilt"):
        print(f"    {axis}_table: {tables[axis]}")


if __name__ == "__main__":
    main()
