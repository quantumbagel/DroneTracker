"""
A test program to send data to a Kafka server and go around in a 360 degree circle.
"""

import json
import time
import kafka
import math

from geopy.distance import geodesic

lat = 35.727481
long = -78.695925
alt = 85.763

def calculate_heading_directions(drone_lat, drone_long, drone_alt, drone_vx, drone_vy, drone_vz, camera_lat, camera_long, camera_alt):
    """
    A function to calculate the heading and distances, while also leading the camera.
    :return: The heading
    """
    pi_c = math.pi / 180  # The deg -> radian conversion factor

    camera_lat_long = [camera_lat, camera_long]

    # Unpack drone_loc
    lat = drone_lat
    long = drone_long
    alt = drone_alt
    vx = drone_vx
    vy = drone_vy
    vz = drone_vz

    # Convert coordinates to arc lengths
    first_lat = camera_lat_long[0] * pi_c
    first_lon = camera_lat_long[1] * pi_c
    second_lat = lat * pi_c
    second_lon = long * pi_c



    # Calculate y and x differential
    y = math.sin(second_lon - first_lon) * math.cos(second_lat)
    x = (math.cos(first_lat) * math.sin(second_lat)) - (
            math.sin(first_lat) * math.cos(second_lat) * math.cos(second_lon - first_lon))

    # Calculate pan
    pre_led_heading_xy = math.atan2(y, x)

    # Calculate xy/z way distances
    pre_led_dist_xy = geodesic(camera_lat_long, [lat, long]).meters
    pre_led_dist_z = alt - camera_alt

    # Calculate tilt
    pre_led_heading_z = math.atan2(pre_led_dist_z, pre_led_dist_xy)

    # Calculate x, y, and z vectors
    x = math.sin(pre_led_heading_xy) * pre_led_dist_xy
    y = math.cos(pre_led_heading_xy) * pre_led_dist_xy
    z = pre_led_dist_z


    lead_time = 0

    # Lead the camera (calculate new relative x, y, and z)
    # We do north/east/up, I guess DroneKit does north/east/down? This can be changed easily
    x += lead_time * vx
    y += lead_time * vy
    z += lead_time * - vz

    # Calculate new heading/distances based on new relative x, y, and z
    heading_xy = math.asin(x / math.sqrt(x ** 2 + y ** 2))
    if pre_led_heading_xy > 0:
        heading_xy = math.pi - heading_xy  # Fix
    dist_xy = math.sqrt(x ** 2 + y ** 2)
    heading_z = math.asin(z / math.sqrt(x ** 2 + y ** 2 + z ** 2))
    dist_z = z

    offset_heading_xy = heading_xy + 1 * pi_c

    if offset_heading_xy > 0:
        offset_heading_xy %= 360 * pi_c
    else:
        offset_heading_xy %= -360 * pi_c

    if offset_heading_xy > 180 * pi_c:  # Fix offset bug positive
        offset_heading_xy = -180 * pi_c + offset_heading_xy
    if offset_heading_xy < -180 * pi_c:  # Fix offset bug negative
        offset_heading_xy = 180 * pi_c - offset_heading_xy
    print(heading_xy / pi_c, offset_heading_xy / pi_c)
    return heading_xy / pi_c, heading_z / pi_c, dist_xy, dist_z


n = 100
r = 0.01
points = [(math.cos(2*math.pi/n*x)*r,math.sin(2*math.pi/n*x)*r) for x in range(0,n+1)]
delay = 0.1

for i in points:
    t = time.time()
    #print(i[0] + lat, i[1] + long, alt)
    calculate_heading_directions(i[0] + lat, i[1] + long, alt, 0, 0, 0, lat, long, alt)
    delta = delay - (time.time()-t)
    if delta > 0:
        time.sleep(delta)


