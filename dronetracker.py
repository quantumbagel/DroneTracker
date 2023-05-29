from ruamel.yaml import YAML
import math
import time
from Drone import Drone
from Camera import Camera
import sys

SCROLLING_CONSOLE_LOG = True  # if true, the console log will print indefinitely, if false, it will be overwritten
SLEEP = 0  # time between updates


def print_information(camera):
    """ A function to print some information about the drone relative to the camera
        :param camera: the camera object to obtain things to print from
    """
    if SCROLLING_CONSOLE_LOG:
        print()
    else:
        for _ in range(4):  # delete lines using vt100
            sys.stdout.write('\x1b[1A')
            sys.stdout.write('\x1b[2K')

    print("Distance to camera:", camera.dist)
    print("Horizontal distance to camera:", camera.dist_xz)
    print("Vertical distance to camera:", camera.dist_y)
    print("Heading direction to camera: (deg)", camera.heading_xz * 180 / math.pi, camera.heading_y * 180 / math.pi)


def load_config():
    """
    A function to load config.yaml and identify the latitude/longitude format
    :return: The coordinate format, in a string, and the configuration, a dictionary
    """
    y = YAML()
    config = y.load(open('config.yml'))
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
    c = Camera(configuration, lat_long_format=coordinate_format)  # Create camera
    print('\n\n\n')
    while True:
        c.move_camera(d.get_drone_position())
        print_information(c)
        if SLEEP:
            time.sleep(SLEEP)
