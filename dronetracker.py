import json
import math
import time
from Drone import Drone
from Camera import Camera
import sys

NICE_LOG = False


def delete_last_line(lines=1):
    for _ in range(lines):
        sys.stdout.write('\x1b[1A')
        sys.stdout.write('\x1b[2K')


def load_config():
    config = json.load(open('config.json'))
    camera_lat_long = config['camera']['lat/long'].split(' ')
    camera_lat = camera_lat_long[0]
    camera_long = camera_lat_long[1]
    camera_alt = float(config['camera']['alt'])

    if '°' not in camera_lat:  # decimal format
        coord_format = 'decimal'
        print("Recognized decimal format in config!")
    else:
        coord_format = 'degrees'
        print("Recognized degree format in config!")
    return camera_lat, camera_long, camera_alt, coord_format, config


if __name__ == '__main__':
    start_time = time.time()
    camera_latitude, camera_longitude, camera_altitude, coordinate_format, configuration = load_config()

    def bad_drone_sim():
        c_time = time.time()
        return [36.75677777777778 - 0.001 * (start_time-c_time),  # same as from config file.
                78.89816666666667 + 0.001 * (start_time-c_time),
                camera_altitude + 0.1 * (start_time-c_time)]

    d = Drone(debug=None)
    c = Camera(camera_latitude, camera_longitude, camera_altitude, d, configuration, lat_long_format=coordinate_format)
    first_loop = True
    while True:
        drone_loc = d.get_drone_position()
        c.update(drone_loc)
        c.move_camera()
        if not first_loop and NICE_LOG:
            delete_last_line(4)
        first_loop = False
        if not NICE_LOG:
            print()
        print("Distance to camera:", c.dist)
        print("Horizontal distance to camera:", c.dist_xz)
        print("Vertical distance to camera:", c.dist_y)
        print("Heading direction to camera: (deg)", c.heading_xz * 180/math.pi, c.heading_y * 180/math.pi)
        time.sleep(1)
