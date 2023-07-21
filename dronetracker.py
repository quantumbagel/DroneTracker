from ruamel.yaml import YAML
import time
from Drone import Drone
from Camera import Camera


def dprint(function, level, *args):
    if level <= configuration['debug']:
        print("[" + function + "]", *args)


def print_information(camera):
    """ A function to print some information about the drone relative to the camera
        :param camera:  object to obtain things to print from
    """
    dprint("print_info", 2, "Distance to camera: (m)", camera.dist)
    dprint("print_info", 2, "Horizontal distance to camera: (m)", camera.dist_xz)
    dprint("print_info", 2, "Vertical distance to camera: (m)", camera.dist_y)
    dprint("print_info", 2, "Heading direction to camera: (deg)", camera.heading_xz, camera.heading_y)


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


def get_drone(connection_address='tcp:localhost:5762', timeout=1):
    """
    Wait for the drone to come alive and connect to it.
    :return: the Drone
    """
    att = 1
    dprint('get_drone', 1, 'Waiting for drone...')
    while True:
        try:
            drone_obj = Drone(connection=connection_address, timeout=timeout)  # Load drone
            break
        except ConnectionRefusedError:
            dprint("get_drone", 1, "Failed on attempt " + str(att))
            att += 1
    dprint('get_drone', 1, 'Got connection to drone!')
    return drone_obj


def wait_for_record():
    global d, c
    while True:
        should = should_be_recording()
        if should == -1:  # lost drone connection
            c.deactivate()
            d = get_drone(connection_address=configuration['drone']['address'],
                          timeout=configuration['drone']['msg_timeout'])
            continue
        elif should:
            return


def should_be_recording():
    mode = configuration['camera']['activate_method']
    if mode == 'armed':
        msg = d.recv_message('HEARTBEAT')
        if msg is None:
            return -1
        dprint('should_be_recording', 2, 'Checking if the drone is armed...')
        dprint('should_be_recording', 2, d.is_armed())
        return d.is_armed()
    if mode == 'file':
        dprint('should_be_recording', 2, 'Checking the file for a 1...')
        try:
            msg = d.recv_message('HEARTBEAT')
            if msg is None:
                return -1
            with open('record') as record_file:
                lines = record_file.readlines()
                if len(lines):
                    if lines[0].startswith('1'):
                        return True

                return False
        except FileNotFoundError:
            dprint('should_be_recording', 2, 'The file "record" does not exist!')
            return False
    if mode.startswith('relative-height'):
        height = int(mode.replace('relative-height', ''))
        dprint('should_be_recording', 2, 'Checking height >', height)
        msg = d.recv_message('GLOBAL_POSITION_INT')
        if msg is not None:
            dprint('should_be_recording', 2, 'Height is', msg.relative_alt / 1000, msg.alt / 1000)
            return msg.relative_alt / 1000 > height
        else:
            dprint('should_be_recording', 2, 'Failed to get message!')
            return -1
    else:
        dprint('should_be_recording', 2, "Invalid mode: ", mode)
        return False


if __name__ == '__main__':
    coordinate_format, configuration = load_config()  # Load configuration
    d = get_drone(connection_address=configuration['drone']['address'], timeout=configuration['drone']['msg_timeout'])
    c = Camera(configuration,
               lat_long_format=coordinate_format,
               camera_activate_radius=configuration['camera']['radius_activate'],
               actually_move=True,
               log_level=configuration['debug'])  # Create camera

    while True:
        s = should_be_recording()
        if s == -1:
            c.deactivate()
            d = get_drone()
        if not s:
            dprint('main', 1, 'I should not be recording. Deactivating the camera...')
            c.deactivate()
            dprint('main', 1, 'Now waiting for recording...')
            wait_for_record()
            dprint('main', 1, 'done')
        lat, long, alt = d.get_drone_position()
        if lat == -1 and long == alt == 0:
            dprint('main', 1, "Lost drone connection!")
            c.deactivate()
            del d
            d = get_drone()
            wait_for_record()
            continue
        else:
            c.move_camera([lat, long, alt])
        print_information(c)
        if configuration['camera']['wait']:
            time.sleep(configuration['camera']['wait'])
