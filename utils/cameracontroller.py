"""
Drive the camera from the keyboard, to check connectivity and the camera/offset calibration.
WASD pans/tilts, up/down arrows zoom, p prints the position (with the azimuth it corresponds to), v toggles recording.
The `keyboard` package needs root on Linux and accessibility permissions on macOS.
"""
import os
import sys
import time

import keyboard

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.camera import CameraError, VapixCamera  # noqa: E402
from tracker.config import load_config  # noqa: E402
from tracker.geometry import wrap180  # noqa: E402

cfg = load_config(os.path.join(os.path.dirname(__file__), "..", "config.yml"))
cam = cfg["camera"]
camera = VapixCamera(cam["ip"], cam["username"], cam["password"])
print(f"Connected; camera at {camera.query_position()}")

recording = None
last = None
while True:
    up_down = int(keyboard.is_pressed("w")) - int(keyboard.is_pressed("s"))
    left_right = int(keyboard.is_pressed("d")) - int(keyboard.is_pressed("a"))
    zoom = int(keyboard.is_pressed("up")) - int(keyboard.is_pressed("down"))
    command = (left_right * 50, up_down * 50, zoom * 100)
    try:
        if command != last:
            camera.continuous_move(*command)
            last = command
        if keyboard.is_pressed("p"):
            position = camera.query_position()
            print(f"pan {position.pan:.2f}  tilt {position.tilt:.2f}  zoom {position.zoom}  "
                  f"(azimuth {wrap180(position.pan - cam['offset']):.2f})")
            time.sleep(0.3)
        if keyboard.is_pressed("v"):
            if recording is None:
                recording = camera.start_recording(cam["disk"])
                print(f"Recording {recording}")
            else:
                camera.stop_recording(recording)
                print(f"Stopped {recording}")
                recording = None
            time.sleep(0.5)
    except CameraError as error:
        print(f"Camera error: {error}")
    time.sleep(0.05)
