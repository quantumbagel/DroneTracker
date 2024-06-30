import kafka
from ruamel.yaml import YAML
import time
from Drone import Drone
from Camera import Camera
import logging


configuration = YAML().load(open("config.yml"))


def print_information(camera):
    """ A function to print some information about the drone relative to the camera
        :param camera:  object to obtain things to print from
    """
    log = logging.getLogger('print_info')
    
    log.debug(f"Distance to camera: (m) {camera.dist}")
    log.debug(f"Horizontal distance to camera: (m) {camera.dist_xz}")
    log.debug(f"Vertical distance to camera: (m) {camera.dist_y}")
    log.debug(f"Heading direction to camera: (deg) {camera.heading_xz, camera.heading_y}")


def load_config():
    """
    A function to load config.yaml and identify the latitude/longitude format
    :return: The coordinate format, in a string, and the configuration, a dictionary
    """
    y = YAML()
    config = y.load(open('config.yml'))
    config['camera_login']['lat'] = str(config['camera_login']['lat'])
    config['camera_login']['long'] = str(config['camera_login']['long'])
    if '°' not in config['camera_login']['lat']:  # decimal format
        coord_format = 'decimal'
    else:
        coord_format = 'degrees'
    return coord_format, config


def get_drone():
    """
    Wait for the drone to come alive and connect to it. Assumes we are active
    :return: the Drone
    """
    log = logging.getLogger('get_drone')
    log.info('Waiting for drone...')
    while True:
        drone = Drone(connection=configuration["kafka"]["ip"])
        if drone.consumer is None:  # Drone consumer failed connection, so we will try again
            log.info("Failed to connect to Kafka server! Trying again in 1 second...")
            time.sleep(1)
            continue
        break
    return drone




def wait_for_record():
    global d, c
    while True:
        should = should_be_recording()
        if should == -1:  # lost drone connection
            c.deactivate(delay=0)
            get_drone(timeout=configuration['drone']['msg_timeout'])
            continue
        elif should:
            return


def should_be_recording():
    log = logging.getLogger('should_be_recording')
    mode = configuration['camera_login']['activate_method']
    if mode == 'armed':
        msg = d.recv_message('HEARTBEAT')
        if msg is None:
            return -1
        log.debug('Checking if the drone is armed...')
        log.debug(d.is_armed())
        return d.is_armed()
    if mode == 'file':
        log.debug('Checking the file for a 1...')
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
            log.debug('The file "record" does not exist!')
            return False
    if mode.startswith('relative-height'):
        height = int(mode.replace('relative-height', ''))
        log.debug('Checking height >', height)
        msg = d.recv_message('GLOBAL_POSITION_INT')
        if msg is not None:
            log.debug('Height is', msg.relative_alt / 1000, msg.alt / 1000)
            return msg.relative_alt / 1000 > height
        else:
            log.debug('Failed to get message!')
            return -1
    else:
        log.debug("Invalid mode: ", mode)
        return False


# if __name__ == '__main__':
#     d = None
#     coordinate_format, configuration = load_config()  # Load configuration
#     get_drone(timeout=configuration['drone']['msg_timeout'])
#     c = Camera(configuration,
#                lat_long_format=coordinate_format,
#                camera_activate_radius=configuration['camera']['radius_activate'],
#                actually_move=True,
#                log_level=configuration['logs'])  # Create camera
#     current_deactivate_worker = None
#     log = logging.getLogger('main')
#     while True:
#         # s = should_be_recording()
#         # if s == -1:
#         #     c.deactivate(configuration['camera_login']['delay'])
#         #     get_drone()
#         # if not s:
#         #     log.info('I should not be recording. Deactivating the camera...')
#         #     if c.activated:
#         #         current_deactivate_worker = c.deactivate(configuration['camera_login']['delay'])
#         #     else:
#         #         c.deactivate(delay=0)
#         #     log.info('Now waiting for recording...')
#         #     get_drone()
#         #     if current_deactivate_worker is not None and current_deactivate_worker.is_alive():
#         #         # We have reconnected before expiration
#         #         current_deactivate_worker.cancel()
#         #         current_deactivate_worker = None
#         #         log.info('Detected alive deactivate worker! Continuing to record!')
#         #     else:
#         #         current_deactivate_worker = None
#         #     log.info('done')
#         pos = d.get_drone_position()
#
#         if pos == -1:
#             log.info("Lost drone connection!")
#             current_deactivate_worker = c.deactivate(configuration['camera']['delay'])
#             del d
#             get_drone()
#             if current_deactivate_worker is not None and current_deactivate_worker.is_alive():
#                 # We have reconnected before expiration
#                 current_deactivate_worker.cancel()
#                 current_deactivate_worker = None
#                 log.info('Detected alive deactivate worker! Continuing to record!')
#             else:
#                 current_deactivate_worker = None
#             continue
#         else:
#             c.move_camera(pos)
#         print_information(c)
#         if configuration['camera']['wait']:
#             time.sleep(configuration['camera']['wait'])



active = False
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    log = logging.getLogger('Drone')
    log.warning("oh yeah")
    drone = get_drone()

    c = Camera(configuration,
                   lat_long_format="decimal",
                   camera_activate_radius=configuration['camera']['radius_activate'],
                   actually_move=False)  # Create camera
    while True:
        position_data = drone.get_drone_position()
        if position_data[0] is not None:
            c.move_camera(position_data[0:3])
        #print(position_data)



