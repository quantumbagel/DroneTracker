import json
from ruamel.yaml import YAML
import math
import time
from Drone import Drone
from Camera import Camera
import sys

NICE_LOG = True  # whether script should delete past lines from terminal to clean up
SLEEP = 0  # time between updates


def print_information(fl, camera):
    """ A function to print some information about the drone relative to the camera
        :param fl: whether it is the first loop (to stop the program from deleting lines it hasn't printed)
        :param camera: the camera object to obtain things to print from
        :return the new first loop state
    """
    if not fl and NICE_LOG:
        delete_last_line(4)
    fl = False
    if not NICE_LOG:
        print()
    print("Distance to camera:", camera.dist)
    print("Horizontal distance to camera:", camera.dist_xz)
    print("Vertical distance to camera:", camera.dist_y)
    print("Heading direction to camera: (deg)", camera.heading_xz * 180 / math.pi, camera.heading_y * 180 / math.pi)
    return fl


def delete_last_line(lines=1):
    """
    A function to delete lines from the terminal
    :param lines: The amount of lines to delete
    """
    for _ in range(lines):
        sys.stdout.write('\x1b[1A')
        sys.stdout.write('\x1b[2K')


def load_config():
    """
    A function to load config.yaml and identify the latitude/longitude format
    :return: The coordinate format, in a string, and the configuration, a dictionary
    """
    y = YAML()
    config = y.load(open('config.yml'))
    print(config)
    config['camera']['lat'] = str(config['camera']['lat'])
    config['camera']['ong'] = str(config['camera']['long'])
    if '°' not in config['camera']['lat']:  # decimal format
        coord_format = 'decimal'
        print("Recognized decimal format in config!")
    else:
        coord_format = 'degrees'
        print("Recognized degree format in config!")
    return coord_format, config


if __name__ == '__main__':
    coordinate_format, configuration = load_config()  # Load configuration
    d = Drone(connection="tcp:localhost:5762")  # Load drone
    c = Camera(d, configuration, lat_long_format=coordinate_format)  # Create camera
    first_loop = True
    while True:
        d.get_drone_position()
        c.update()
        c.move_camera()
        first_loop = print_information(first_loop, c)
        if SLEEP:
            time.sleep(SLEEP)
