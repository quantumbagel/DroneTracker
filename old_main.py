import math
import sys

from geopy.distance import geodesic
import time
import requests
start_time = time.time()  # for get_drone_lat_long_alt() 


def get_drone_lat_long_alt():
    """
    A function to simulate *realistically* the movement of the drone
    :return: A tuple containing (lat, long, alt)
    """
    return 35.7512755 + 0.001 * (time.time() - start_time), \
        -78.9 + 0.0001 * (time.time() - start_time), \
        200 + 10 * (time.time() - start_time)


DRONE = (24, 16, 20)  # 24 x, 16 y, 20 z - the dimensions of the drone (in)
my_loc = (35.7512729, -78.9019773, 200)  # My (camera) location
my_lat_long = my_loc[:2]  # My latitude and longitude
LAST_DRONE_LOC = ()  # The last packet
LAST_DRONE_PACKET_TIME = time.time()  # When the last packet was sent
PACKET_SLEEP = 1  # Time sleeping between checks


def calculate_camera_rotation(log=False):
    global LAST_DRONE_LOC, LAST_DRONE_PACKET_TIME  # don't like using global
    drone_loc = get_drone_lat_long_alt()
    if LAST_DRONE_LOC == drone_loc:  # Drone hasn't updated the location yet, just return
        if log:
            print("WARN: no packet in ", time.time() - LAST_DRONE_PACKET_TIME)
        return 0, 0
    else:
        LAST_DRONE_LOC = drone_loc
        LAST_DRONE_PACKET_TIME = time.time()
        if log:
            print("INFO: received packet:", drone_loc)
    drone_lat_long = drone_loc[:2]
    dist_xz = geodesic(drone_lat_long, my_lat_long).feet
    # Distance as the crow flies between us and the drone. Uses oblate spheroid for Earth
    dist_y = drone_loc[2] - my_loc[2]
    # Difference in altitudes
    if log:
        print("My x/z distance from drone from geopy.distance.geodesic: (feet)", dist_xz)
        print("My y distance from drone: (ft)", dist_y)
        print("My distance from drone: (ft)", math.sqrt(dist_y ** 2 + dist_xz ** 2))
    long_dist = drone_lat_long[1] - my_lat_long[1]
    # v Some math to determine heading
    # (https://www.igismap.com/formula-to-find-bearing-or-heading-angle-between-two-points-latitude-longitude/)
    heading_xz = math.atan2(math.cos(drone_lat_long[0]) * math.sin(long_dist),
                            math.cos(my_lat_long[0]) * math.sin(drone_lat_long[0]) - math.sin(
                                my_lat_long[0]) * math.cos(drone_lat_long[0]) * math.cos(long_dist))
    heading_y = math.atan2(dist_y, dist_xz)
    if log:
        print("My x/z heading (towards drone) (deg)", heading_xz * (180 / math.pi))
        print("My y heading (towards drone) (deg)", heading_y * (180 / math.pi))
    return heading_xz, heading_y


# RETRIES = 0
# DRONE_IP = 'http://192.168.2.197:8080'
# if __name__ == '__main__':
#     print("Establishing connection with camera...", end='')
#     json = {}
#     for i in range(RETRIES):
#         try:
#             about = requests.get(DRONE_IP+"/about", timeout=5)
#             json = about.json()
#             break
#         except requests.exceptions.ConnectTimeout:
#             print("failed\nRetrying...", end='')
#             continue
#     if len(json.keys()):
#         print("success")
#     else:
#         print("failed")
#         print("Failed to establish connection within", RETRIES, 'retries. Quitting.')
#         if RETRIES == 0:
#             print("continuing actually")
#             json = {"FirmwareVersion": "BirdDog Firmware version", "Format": "CAM 1", "HostName": "birddog-device",
#                     "IPAddress": "192.168.100.100", "NetworkConfigMethod": "dhcp", "NetworkMask": "255.255.255.0",
#                     "SerialNumber": "0123456789", "Status": "active"}
#         else:
#             sys.exit(0)
#     print("\nAbout Camera:")
#     for key in json:
#         print(key+':', json[key])
#


import camera

c = camera.D100()
c.init()

while True:
    pan, tilt = calculate_camera_rotation(log=True)
    c.relative_position()