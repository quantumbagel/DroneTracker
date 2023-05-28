import math

from geopy.distance import geodesic

from Drone import Drone


def degrees_to_decimal(coord):
    coord = coord.replace("°", "-").replace("'", "-").replace('"', "")
    multiplier = 1 if coord[-1] in ['N', 'W'] else -1
    return multiplier * sum(float(x) / 60 ** n for n, x in enumerate(coord[:-1].split('-')))


class Camera:
    def __init__(self, lat: str, long: str, alt: float, drone: Drone, config: dict, lat_long_format='degrees'):
        assert lat_long_format in ['degrees', 'decimal']
        if lat_long_format == 'degrees':
            self.lat = degrees_to_decimal(lat)
            self.long = degrees_to_decimal(long)
        else:
            self.lat = float(lat)
            self.long = float(long)
        self.config = config
        self.alt = alt
        self.drone = drone
        self.dist_xz = -1
        self.dist_y = -1
        self.dist = -1
        self.heading_xz = -1
        self.heading_y = -1
        self.zoom = -1
        self.drone_loc = []

    def update(self, drone_loc: list):
        self.drone_loc = drone_loc
        self.heading_xz, self.heading_y, self.dist_xz, self.dist_y = self.calculate_heading_directions()
        self.dist, self.zoom = self.calculate_zoom()

    def calculate_heading_directions(self):
        drone_lat_long = self.drone_loc[:2]
        dist_xz = geodesic(drone_lat_long, [self.lat, self.long]).feet
        # Distance as the crow flies between us and the drone. Uses oblate spheroid for Earth
        dist_y = self.drone_loc[2] - self.alt
        # Difference in altitude
        long_dist = drone_lat_long[1] - self.long
        # v Some math to determine heading
        # (https://www.igismap.com/formula-to-find-bearing-or-heading-angle-between-two-points-latitude-longitude/)
        heading_xz = math.atan2(math.cos(drone_lat_long[0]) * math.sin(long_dist),
                                math.cos(self.lat) * math.sin(drone_lat_long[0]) - math.sin(
                                    self.lat) * math.cos(drone_lat_long[0]) * math.cos(long_dist))
        heading_y = math.atan2(dist_y, dist_xz)

        return heading_xz, heading_y, dist_xz, dist_y

    def calculate_zoom(self):
        dist = math.sqrt(self.dist_xz ** 2 + self.dist_y ** 2)
        max_dimension = max([i for i in self.config['drone'].values()])
        zoom = (dist * max_dimension) / (self.config['scale']['dist'] * self.config['scale']['width'])
        return dist, zoom

    def move_camera(self):
        pass
