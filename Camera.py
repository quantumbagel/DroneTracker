import math
import threading
import time

from geopy.distance import geodesic
from sensecam_control import vapix_control, vapix_config


class NullController:
    """
    A controller class to act as an "imposter" to the main code
    """

    def __init__(self):
        self.fake_value = 0
        return

    def absolute_move(self, *args):
        self.fake_value += 1

        return

    def stop_recording(self, *args):
        print("[fake-stop] stopped recording.")
        self.fake_value += 1
        return True

    def start_recording(self, *args, profile=None):
        print("[fake-start] started recording.")
        self.fake_value += 1
        return 'fake-recording-name', 0


class Camera:
    """
    A class to handle the math for the camera's pan, tilt, and zoom
     as well as actually doing those things in real life.
    """

    def __init__(self,
                 config: dict,
                 lat_long_format='degrees',
                 camera_activate_radius=0,
                 log_level=1,  # 1 is normal, 0 is off, 2 is MAX
                 actually_move=True,
                 disk_name='SD_DISK',
                 profile_name=None):
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
        self.disk_name = disk_name
        self.profile_name = profile_name
        self.record_method = self.config['camera']['activate_method']
        if self.move:
            self.controller = vapix_control.CameraControl(config['login']['ip'],
                                                          config['login']['username'],
                                                          config['login']['password'])
            self.media = vapix_config.CameraConfiguration(config['login']['ip'],
                                                          config['login']['username'],
                                                          config['login']['password'])
        else:
            self.controller = NullController()
            self.media = NullController()
        self.activated = False
        self.log = log_level
        self.current_pan = 0
        self.current_tilt = 0
        self.current_zoom = 0
        self.current_recording_name = ''
        self.deactivating = False

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
        if self.log > 1:
            print("[Camera.update]", 'updated (pan, tilt, horiz_distance, vert_distance, distance, zoom)',
                  self.heading_xz, self.heading_y, self.dist_xz, self.dist_y, self.dist, self.zoom)

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
        if self.config['camera']['is_upside_down']:
            heading_y *= -1
        return heading_xz, heading_y, dist_xz, dist_y

    def calculate_zoom(self):
        """
        A function to calculate the zoom for the camera.
        :return: the absolute distance to the drone, and the necessary zoom value
        """
        dist = math.sqrt(self.dist_xz ** 2 + self.dist_y ** 2)
        max_dimension = max([i for i in [self.config['drone']['x'],
                                         self.config['drone']['y'],
                                         self.config['drone']['z']]])
        zoom = (dist * self.config['scale']['width']) / (self.config['scale']['dist'] * max_dimension)

        zoom = round(((zoom-1) / (self.config['camera']['maximum_zoom']-1)) * 9999)
        zoom *= 1/self.config['camera']['zoom_error']
        return dist, zoom

    def move_camera(self, drone_loc):
        """
        A function to send the command to pan, tilt, and zoom to the camera over whatever protocol we end up using
        :return: none
        """
        self.drone_loc = drone_loc
        self.update()
        if abs(self.dist_xz) < self.camera_activate_radius or self.camera_activate_radius == 0:  # am I in the radius?
            if not self.activated:
                while True:
                    rc_name, out = self.media.start_recording(self.disk_name, profile=self.profile_name)
                    if out == 1:
                        if self.log:
                            print("[Camera.move_camera]", 'failed to start recording!', 'error: ', rc_name)
                        continue
                    self.current_recording_name = rc_name
                    break

                self.activated = True
                if self.log:
                    print("[Camera.move_camera]", "Successfully started recording!", 'id:', self.current_recording_name)
            if (abs(self.current_pan - self.heading_xz)) > self.config['camera']['min_step'] or \
                    (abs(self.current_tilt - self.heading_y)) > self.config['camera']['min_step'] or \
                    (abs(self.current_zoom - self.zoom) > self.config['camera']['min_zoom_step']):
                if self.log > 1:
                    print("[Camera.move_camera]", 'moving to (p, t, z)', self.heading_xz, self.heading_y, self.zoom)
                self.controller.absolute_move(self.heading_xz, self.heading_y, self.zoom)  # this should work
                self.current_pan = self.heading_xz
                self.current_tilt = self.heading_y
                self.current_zoom = self.zoom
            else:
                if self.log > 1:
                    print("[Camera.move_camera]", 'Step is not significant enough to move the camera.')

            # TODO: test the controller and determine the offset
        else:
            if self.activated:
                self.deactivate()
            self.activated = False

    def deactivate(self, delay=0):
        if self.log:
            print("[Camera.deactivate] now starting wait for", delay, 'seconds')
        if delay:
            self.deactivating = True
            worker = threading.Timer(delay,  self._deactivate_function)
            worker.start()
            return worker
        else:
            self._deactivate_function()

    def _deactivate_function(self):
        """
        Force deactivate the camera.
        :return: none
        """
        if self.current_recording_name != '':
            while True:
                if self.log:
                    print("[Camera.deactivate]", 'stopping the recording... (name='+self.current_recording_name+')')
                stopped = self.media.stop_recording(self.current_recording_name)
                if stopped:
                    if self.log:
                        print("[Camera.deactivate]", 'Success!')
                    break
                else:
                    if self.log:
                        print("[Camera.deactivate]", 'failed! retrying...')
            self.current_recording_name = ''
        deactivate_pan = self.config['camera']['deactivate_pos']['pan']
        deactivate_tilt = self.config['camera']['deactivate_pos']['tilt']
        if not deactivate_pan:
            deactivate_pan = self.current_pan
        if not deactivate_tilt:
            deactivate_tilt = self.current_tilt
        if self.log:
            print("[Camera.deactivate]", 'deactivating to (p, t)', deactivate_pan, deactivate_tilt)
        self.controller.absolute_move(deactivate_pan,
                                      deactivate_tilt)
        self.current_pan = deactivate_pan
        self.current_tilt = deactivate_tilt
        self.activated = False
        self.deactivating = False
