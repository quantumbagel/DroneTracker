import time
from pymavlink import mavutil


class Drone:
    """
    A class to represent the drone and handle the connection and location of it
    """

    def __init__(self, debug=None, log_level=1, connection='tcp:localhost:5762', timeout=1):
        """
        Initialize and connect to the drone.
        :param debug: a function to replace the drone for testing. Can be None to turn this off
        :param connection: where to connect
        """
        self.debug_pos_function = debug
        self.start_time = time.time()
        self.lat = None
        self.long = None
        self.alt = None
        self.log_level = log_level
        self.timeout = timeout
        if debug is None:
            self.vehicle = mavutil.mavlink_connection(connection, retries=1)  # be very impatient
            self.get_drone_position()

    def update_drone_position(self):
        """
        Get the position of the drone and save it to the class
        :return: nothing
        """
        if self.debug_pos_function is None:
            self.vehicle.mav.request_data_stream_send(self.vehicle.target_system, self.vehicle.target_component,
                                                      mavutil.mavlink.MAV_DATA_STREAM_ALL, 120, 1)  # Update the data
            try:
                # Get the position message
                msg = self.vehicle.recv_match(type='GLOBAL_POSITION_INT', blocking=True, timeout=self.timeout)
                if msg is None:
                    print('[Drone] GLOBAL_POSITION request timed out! Drone is disconnected!')
                    return 1
            except ConnectionResetError:
                return 1
            self.lat = msg.lat * 10 ** -7
            self.long = msg.lon * 10 ** -7
            self.alt = msg.alt * 10 ** -3
        else:
            self.lat, self.long, self.alt = self.debug_pos_function()  # Call the debug function
        return 0

    def recv_message(self, msg_type):
        try:
            msg = self.vehicle.wait_heartbeat(timeout=self.timeout)
            if msg is None:
                print('[Drone] HEARTBEAT request timed out! Drone is disconnected!')
                return None
        except ConnectionResetError:
            print('[Drone] HEARTBEAT request timed out! Drone is disconnected!')

        try:
            msg = self.vehicle.recv_match(type=msg_type, blocking=True,
                                          timeout=self.timeout)  # Get the position message
            if msg is None:
                print('[Drone] '+msg_type+' request timed out! Drone is disconnected!')
                return None
        except ConnectionResetError:
            print('[Drone] ' + msg_type + ' request timed out! Drone is disconnected!')
            return None
        return msg

    def get_drone_position(self):
        """
        Update and return the drone's location
        :return: latitude, longitude, altitude
        """
        exit_code = self.update_drone_position()
        if exit_code:
            return -1, 0, 0
        return self.lat, self.long, self.alt

    def wait_for_armed(self):
        """
        A function to wait for the drone to arm
        :return: 1 if drone disconnects, 0 if successful
        """
        run = 1
        while True:
            m = self.vehicle.wait_heartbeat(timeout=self.timeout)
            if self.log_level:
                print("[Drone.wait_for_armed] waiting for the drone to arm... on cycle", run)
            if m is None:
                return 1
            if self.vehicle.motors_armed():
                break
            run += 1
        return 0

    def is_armed(self):
        """
        A function to check if the drone is currently armed
        :return: none
        """
        return self.vehicle.motors_armed()
