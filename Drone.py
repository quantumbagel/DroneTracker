import time
from pymavlink import mavutil


class Drone:
    """
    A class to represent the drone and handle the connection and location of it
    """
    def __init__(self, debug=None, connection='tcp:localhost:5762'):
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
        if debug is None:
            self.vehicle = mavutil.mavlink_connection(connection)
            print("DRONE_INIT:Waiting for heartbeat...")
            self.vehicle.wait_heartbeat()
            print("DONE")
            self.vehicle.mav.request_data_stream_send(self.vehicle.target_system, self.vehicle.target_component,
                                                      mavutil.mavlink.MAV_DATA_STREAM_ALL, 120, 1)
            self.get_drone_position()


    def update_drone_position(self):
        """
        Get the position of the drone and save it to the class
        :return: nothing
        """
        if self.debug_pos_function is None:
            self.vehicle.mav.request_data_stream_send(self.vehicle.target_system, self.vehicle.target_component,
                                                      mavutil.mavlink.MAV_DATA_STREAM_ALL, 120, 1)  # Update the data
            msg = self.vehicle.recv_match(type='GLOBAL_POSITION_INT', blocking=True)  # Get the position message that
            # was most recently sent
            self.lat = msg.lat * 10**-7  # Convert latitude, longitude, and altitude to the correct order of magnitude.
            self.long = msg.lon * 10**-7
            self.alt = msg.alt * 10**-3
        else:
            self.lat, self.long, self.alt = self.debug_pos_function()  # Call the debug function

    def get_drone_position(self):
        """
        Update and return the drone's location
        :return: latitude, longitude, altitude
        """
        self.update_drone_position()
        return self.lat, self.long, self.alt

    def wait_for_armed(self):
        """
        A function to wait for the drone to arm
        :return: none
        """
        return self.vehicle.motors_armed_wait()

    def is_armed(self):
        """
        A function to check if the drone is currently armed
        :return: none
        """
        return self.vehicle.motors_armed()
