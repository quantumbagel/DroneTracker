import json
import math
import time

from geopy.distance import geodesic


def degrees_to_decimal(coord):
    coord = coord.replace("°", "-").replace("'", "-").replace('"', "")
    multiplier = 1 if coord[-1] in ['N', 'W'] else -1
    return multiplier * sum(float(x) / 60 ** n for n, x in enumerate(coord[:-1].split('-')))


class Drone:
    def __init__(self, debug=None):
        self.debug_pos_function = debug
        self.start_time = time.time()
        self.serial_channel = 'COM1'  # placeholder

    def get_drone_position(self):
        if self.debug_pos_function is None:
            # TODO: do retrieval stuff
            print("Would retrieve data, but NOT IMPLEMENTED (errors will likely follow this)")
        else:
            return self.debug_pos_function()


class Camera:
    def __init__(self, lat: str, long: str, alt: float, drone: Drone, lat_long_format='degrees'):
        assert lat_long_format in ['degrees', 'decimal']
        if lat_long_format == 'degrees':
            self.lat = degrees_to_decimal(lat)
            self.long = degrees_to_decimal(long)
        else:
            self.lat = float(lat)
            self.long = float(long)
        self.alt = alt
        self.drone = drone

    def calculate_heading_directions(self):
        drone_loc = self.drone.get_drone_position()
        drone_lat_long = drone_loc[:2]
        dist_xz = geodesic(drone_lat_long, [self.lat, self.long]).feet
        # Distance as the crow flies between us and the drone. Uses oblate spheroid for Earth
        dist_y = drone_loc[2] - self.alt
        # Difference in altitude
        long_dist = drone_lat_long[1] - self.long
        # v Some math to determine heading
        # (https://www.igismap.com/formula-to-find-bearing-or-heading-angle-between-two-points-latitude-longitude/)
        heading_xz = math.atan2(math.cos(drone_lat_long[0]) * math.sin(long_dist),
                                math.cos(self.lat) * math.sin(drone_lat_long[0]) - math.sin(
                                    self.lat) * math.cos(drone_lat_long[0]) * math.cos(long_dist))
        heading_y = math.atan2(dist_y, dist_xz)

        return heading_xz, heading_y, dist_xz, dist_y

if __name__ == '__main__':
    print("Loading configuration file...")
    config = json.load(open('config.json'))
    print("done.")
    camera_lat_long = config['camera']['lat/long'].split(' ')
    camera_lat = camera_lat_long[0]
    camera_long = camera_lat_long[1]
    camera_alt = float(config['camera']['alt'])
    d = Drone()
    if '°' not in camera_lat:  # decimal format
        coord_format = 'decimal'
        print("Recognized decimal format in config!")
    else:
        coord_format = 'degrees'
        print("Recognized degree format in config!")
    c = Camera(camera_lat, camera_long, camera_alt, d, lat_long_format=coord_format)
    heading_xz, heading_y, dist_xz, dist_y = c.calculate_heading_directions()
    deg_heading_xz = heading_xz * (180/math.pi)
    deg_heading_y = heading_y * (180/math.pi)
    print("X/Z:", deg_heading_xz, "\nY:  ", deg_heading_y)
    print("Calculating zoom...")
    dist = math.sqrt(dist_xz**2 + dist_y**2)
    print("I am ", dist, "feet away from the drone.")
    max_dimension = max([i for i in config['drone'].values()])
    print("Drone's biggest dimension", max_dimension)
    zoom = (dist * max_dimension) / (config['scale']['dist'] * config['scale']['width'])
    print("Scaling (zoom) factor", zoom)