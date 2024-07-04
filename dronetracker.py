from ruamel.yaml import YAML
import time
from Drone import Drone
from Camera import Camera
import logging

from Gateway import Gateway

with open("config.yml") as config_file:
    configuration = YAML().load(config_file)
hertz_deactivated = configuration["kafka"]["hz"] == 0
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("kafka").setLevel(logging.WARNING)  # We only want warnings from Kafka





# def print_information(camera):
#     """ A function to print some information about the drone relative to the camera
#         :param camera:  object to obtain things to print from
#     """
#     log = logging.getLogger('print_info')
#
#     log.debug(f"Distance to camera: (m) {camera.dist}")
#     log.debug(f"Horizontal distance to camera: (m) {camera.dist_xz}")
#     log.debug(f"Vertical distance to camera: (m) {camera.dist_y}")
#     log.debug(f"Heading direction to camera: (deg) {camera.heading_xz, camera.heading_y}")


# def load_config():
#     """
#     A function to load config.yaml and identify the latitude/longitude format
#     :return: The coordinate format, in a string, and the configuration, a dictionary
#     """
#     y = YAML()
#     config = y.load(open('config.yml'))
#     config['camera_login']['lat'] = str(config['camera_login']['lat'])
#     config['camera_login']['long'] = str(config['camera_login']['long'])
#     if '°' not in config['camera_login']['lat']:  # decimal format
#         coord_format = 'decimal'
#     else:
#         coord_format = 'degrees'
#     return coord_format, config


def get_drone():
    """
    Wait for the drone to come alive and connect to it. Assumes we are active
    :return: the Drone
    """
    log = logging.getLogger('get_drone')
    log.info('Waiting for drone...')
    while True:
        new_drone = Drone(connection=configuration["kafka"]["ip"], topic=configuration["kafka"]["data_topic"],
                          timeout=configuration["experiment"]["stop_recording_after"])
        if new_drone.consumer is None:  # Drone consumer failed connection, so we will try again
            log.info("Failed to connect to Kafka server! Trying again in 1 second...")
            time.sleep(1)
            continue
        break
    return new_drone


def wait():
    log = logging.getLogger('get_active_tracking')
    log.info("Initializing ")


# def wait_for_record():
#     global d, c
#     while True:
#         should = should_be_recording()
#         if should == -1:  # lost drone connection
#             c.deactivate(delay=0)
#             get_drone(timeout=configuration['drone']['msg_timeout'])
#             continue
#         elif should:
#             return
#
#

active = False
if __name__ == '__main__':
    gateway = Gateway(configuration["kafka"]["ip"], configuration["kafka"]["command_topic"])
    drone = get_drone()
    camera = Camera(configuration,
                    lat_long_format="decimal",
                    actually_move=False)  # Create camera
    while True:
        logging.info("Now waiting for experiment...")
        gateway.wait_for_status("on", hz=configuration["kafka"]["hz"])
        logging.info("Experiment is ready!")
        last_tick_active = False
        while True:
            start = time.time()
            gateway.update()  # Update experiment status
            if gateway.status == "off" and last_tick_active:  # Experiment is over
                logging.error("We have been forcefully disabled by command action!")
                camera.deactivate()  # Deactivate the camera
                break  # Exit loop
            if last_tick_active and not drone.most_recent:  # Drone hasn't received anything
                logging.error("Packet timeout has occurred, deactivating")
                camera.deactivate()  # Deactivate the camera
                break  # Exit loop
            drone.update()  # Update drone position/velocity data

            if drone.most_recent:  # If we are active
                last_tick_active = True
                camera.move_camera([drone.lat, drone.long, drone.alt, drone.vx, drone.vy, drone.vz])
            end = time.time()
            if not hertz_deactivated:
                delta = 1 / configuration["kafka"]["hz"] - (end - start)
                if delta > 0:
                    logging.debug(f"Now sleeping for {delta} seconds because of hertz: {configuration['kafka']['hz']}")
                    time.sleep(delta)
        drone.reset()
