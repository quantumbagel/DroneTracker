from ruamel.yaml import YAML
import time
from Drone import Drone
from Camera import Camera


def dprint(function, *args):
    if configuration['debug']:
        print("[" + function + "]", *args)


def print_information(camera):
    """ A function to print some information about the drone relative to the camera
        :param camera: the camera object to obtain things to print from
    """
    dprint("print_info", "Distance to camera: (m)", camera.dist)
    dprint("print_info", "Horizontal distance to camera: (m)", camera.dist_xz)
    dprint("print_info", "Vertical distance to camera: (m)", camera.dist_y)
    dprint("print_info", "Heading direction to camera: (deg)", camera.heading_xz, camera.heading_y)


def load_config():
    """
    A function to load config.yaml and identify the latitude/longitude format
    :return: The coordinate format, in a string, and the configuration, a dictionary
    """
    y = YAML()
    config = y.load(open('config.yml'))
    config['camera']['lat'] = str(config['camera']['lat'])
    config['camera']['long'] = str(config['camera']['long'])
    if '°' not in config['camera']['lat']:  # decimal format
        coord_format = 'decimal'
    else:
        coord_format = 'degrees'
    return coord_format, config


def get_drone(connection_address='tcp:localhost:5762'):
    """
    Wait for the drone to come alive and connect to it.
    :return: the Drone
    """
    att = 1
    while True:
        try:
            drone_obj = Drone(connection=connection_address)  # Load drone
            break
        except ConnectionRefusedError:
            dprint("get_drone", "Failed on attempt " + str(att))
            att += 1
    return drone_obj


if __name__ == '__main__':
    coordinate_format, configuration = load_config()  # Load configuration
    dprint('main', 'Waiting for drone...')
    d = get_drone(connection_address=configuration['drone']['address'])
    dprint('main', 'Got connection to drone!')
    dprint('main', 'Waiting for drone to arm...')
    d.wait_for_armed()
    dprint('main', 'Drone has armed! Now tracking!')
    c = Camera(configuration,
               lat_long_format=coordinate_format,
               camera_activate_radius=configuration['camera']['radius_activate'],
               actually_move=False,
               log_on=configuration['debug'])  # Create camera

    while True:
        if not d.is_armed():
            dprint('main', 'Drone is no longer armed. Waiting for drone to arm...')
            c.deactivate()
            d.wait_for_armed()
        lat, long, alt = d.get_drone_position()
        if lat == -1 and long == alt == 0:
            dprint('main', "Lost drone connection!")
            c.deactivate()
            dprint('main', 'Waiting for drone...')
            del d
            d = get_drone()
            dprint('main', 'Got connection to drone!')
            dprint('main', 'Waiting for drone to arm...')
            d.wait_for_armed()
            dprint('main', 'Drone has armed! Now tracking!')
            continue
        else:
            c.move_camera([lat, long, alt])
        print_information(c)
        if configuration['camera']['wait']:
            time.sleep(configuration['camera']['wait'])
