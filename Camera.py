import math
from geopy.distance import geodesic
from sensecam_control import vapix_control, vapix_config


class NullController:
    """
    A controller class to act as an "imposter" to the main code
    """

    def __init__(self):
        return

    def absolute_move(self, *args):
        return


class Camera:
    """
    A class to handle the math for the camera's pan, tilt, and zoom
     as well as actually doing those things in real life.
    """

    def __init__(self,
                 config: dict,
                 lat_long_format='degrees',
                 camera_activate_radius=0,
                 log_on=False,
                 actually_move=True):
        """
        Initialize the values and convert to decimal if needed
        :param config: the configuration dictionary
        :param lat_long_format: the format the latitude and longitude are in
        :param camera_activate_radius: the horizontal radius (m) that the drone must be in for the camera to record
        """
        assert lat_long_format in ['degrees', 'decimal']
        if lat_long_format == 'degrees':
            self.lat = self.degrees_to_decimal(config['camera']['lat'])
            self.long = self.degrees_to_decimal(config['camera']['long'])
        else:
            self.lat = float(config['camera']['lat'])
            self.long = float(config['camera']['long'])
        self.config = config
        self.alt = config['camera']['alt']
        self.dist_xz = -1
        self.dist_y = -1
        self.dist = -1
        self.heading_xz = -1
        self.heading_y = -1
        self.zoom = -1
        self.drone_loc = []
        self.camera_activate_radius = camera_activate_radius
        self.move = actually_move
        if self.move:
            self.controller = vapix_control.CameraControl(config['login']['ip'],
                                                          config['login']['username'],
                                                          config['login']['username'])
        else:
            self.controller = NullController()
        self.activated = False
        self.log = log_on
        self.current_pan = 0
        self.current_tilt = 0
        self.current_zoom = 0

    def degrees_to_decimal(self, coord):
        """
        A function to convert a coordinate to decimal (format 35°45'31.2"N or 78°53'59.5"W)
        :param coord: The coordinate (latitude or longitude) to convert to decimal
        :return: the converted coordinate
        """
        coord = coord.replace("°", "-").replace("'", "-").replace('"', "")
        multiplier = 1 if coord[-1] in ['N', 'W'] else -1
        return multiplier * sum(float(x) / 60 ** n for n, x in enumerate(coord[:-1].split('-')))

    def update(self):
        """
        Calculate the zoom and heading directions via Camera.calculate_heading_directions and Camera.calculate_zoom
        :return: none
        """
        self.heading_xz, self.heading_y, self.dist_xz, self.dist_y = self.calculate_heading_directions(
            self.drone_loc[:2])
        self.dist, self.zoom = self.calculate_zoom()
        if self.log:
            print("[Camera.update]", 'updated (pan, tilt, horiz_distance, vert_distance, distance, zoom)',
                  self.heading_xz, self.heading_y, self.dist_xz, self.dist_y, self.dist, self.zoom)

    def calculate_heading_directions_deprecated(self):
        """
        Calculate the heading directions for the camera.
        :return: The heading directions required and the distances vertically and horizontally from the drone
        """
        drone_lat_long = self.drone_loc[:2]
        dist_xz = geodesic(drone_lat_long, [self.lat, self.long]).meters
        # ^ Distance as the crow flies between us and the drone. Uses oblate spheroid for Earth
        dist_y = self.drone_loc[2] - self.alt
        # ^ Difference in altitude
        long_dist = drone_lat_long[1] - self.long
        # ^ The distance in longitude (used for heading_xz)
        # v Some math to determine heading_xz and heading_y
        # (https://www.igismap.com/formula-to-find-bearing-or-heading-angle-between-two-points-latitude-longitude/)
        heading_xz = math.atan2(math.cos(drone_lat_long[0]) * math.sin(long_dist),
                                math.cos(self.lat) * math.sin(drone_lat_long[0]) - math.sin(
                                    self.lat) * math.cos(drone_lat_long[0]) * math.cos(long_dist))
        # v calculate the heading_y
        heading_y = math.atan2(dist_y, dist_xz)

        return heading_xz, heading_y, dist_xz, dist_y

    def calculate_heading_directions(self, drone_lat_long):
        """
        A function to calculate heading.
        :param drone_lat_long: The drone position (lat/long)
        :return: The heading
        """
        pi_c = math.pi / 180
        camera_lat_long = [self.lat, self.long]
        first_lat = camera_lat_long[0] * pi_c
        first_lon = camera_lat_long[1] * pi_c
        second_lat = drone_lat_long[0] * pi_c
        second_lon = drone_lat_long[1] * pi_c
        y = math.sin(second_lon - first_lon) * math.cos(second_lat)
        x = (math.cos(first_lat) * math.sin(second_lat)) - (
                math.sin(first_lat) * math.cos(second_lat) * math.cos(second_lon - first_lon))
        heading_rads = math.atan2(y, x)
        heading_xz = ((heading_rads / pi_c) + 360) % 360
        dist_xz = geodesic(camera_lat_long, drone_lat_long).meters
        dist_y = self.drone_loc[2] - self.alt
        heading_y = math.atan2(dist_y, dist_xz) / pi_c
        return heading_xz, heading_y, dist_xz, dist_y

    def calculate_zoom(self):
        """
        A function to calculate the zoom for the camera.
        :return: the absolute distance to the drone, and the necessary zoom value
        """
        dist = math.sqrt(self.dist_xz ** 2 + self.dist_y ** 2)
        max_dimension = max([i for i in self.config['drone'].values() if 'str' not in str(type(i))])
        zoom = (dist * max_dimension) / (self.config['scale']['dist'] * self.config['scale']['width'])
        return dist, zoom

    def move_camera(self, drone_loc):
        """
        A function to send the command to pan, tilt, and zoom to the camera over whatever protocol we end up using
        :return: none
        """
        self.drone_loc = drone_loc
        self.update()
        if abs(self.dist_xz) < self.camera_activate_radius or self.camera_activate_radius == 0:  # am I in the radius?

            if (abs(self.current_pan - self.heading_xz)) > self.config['camera']['min_step'] or \
                    (abs(self.current_tilt - self.heading_y)) > self.config['camera']['min_step']:
                if self.log:
                    print("[Camera.move_camera]", 'moving to (p, t, z)', self.heading_xz, self.heading_y, self.zoom)
                self.controller.absolute_move(self.heading_xz, self.heading_y, self.zoom)  # this should work
                self.controller.absolute_move(self.heading_xz, self.heading_y, self.zoom)  # this should work
                self.current_pan = self.heading_xz
                self.current_tilt = self.heading_y
                self.current_zoom = self.zoom
            else:
                if self.log:
                    print("[Camera.move_camera]", 'Step is not significant enough to move the camera.')

            self.activated = True
            # TODO: test the controller and determine the offset
        else:
            if self.activated:
                if self.log:
                    print("[Camera.move_camera]", 'deactivating to (p, t, z)', self.heading_xz, self.heading_y,
                          self.zoom)
                self.controller.absolute_move(self.config['camera']['deactivate_pos']['pan'],
                                              self.config['camera']['deactivate_pos']['tilt'])
                self.current_pan = self.heading_xz
                self.current_tilt = self.heading_y
                self.current_zoom = self.zoom
            self.activated = False

    def deactivate(self):
        """
        Force deactivate the camera.
        :return: none
        """
        if self.log:
            print("[Camera.deactivate]", 'deactivating to (p, t, z)', self.heading_xz, self.heading_y, self.zoom)
        self.controller.absolute_move(self.config['camera']['deactivate_pos']['pan'],
                                      self.config['camera']['deactivate_pos']['tilt'])
        self.current_pan = self.heading_xz
        self.current_tilt = self.heading_y
        self.current_zoom = self.zoom
