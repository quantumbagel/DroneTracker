import time
from pymavlink import mavutil


class Drone:
    def __init__(self, debug=None, connection='tcp:localhost:5763'):

        self.debug_pos_function = debug
        self.start_time = time.time()
        if debug is None:
            self.vehicle = mavutil.mavlink_connection(connection)
            print("DRONE_INIT:Waiting for heartbeat...")
            self.vehicle.wait_heartbeat()
            self.vehicle.mav.request_data_stream_send(self.vehicle.target_system, self.vehicle.target_component,
                                                      mavutil.mavlink.MAV_DATA_STREAM_ALL, 120, 1)

    def get_drone_position(self):
        if self.debug_pos_function is None:
            self.vehicle.mav.request_data_stream_send(self.vehicle.target_system, self.vehicle.target_component,
                                                      mavutil.mavlink.MAV_DATA_STREAM_ALL, 120, 1)
            msg = self.vehicle.recv_match(type='GLOBAL_POSITION_INT', blocking=True)
            lat = msg.lat * 10**-7
            lon = msg.lon * 10**-7
            alt = msg.alt * 10**-3
            return lat, lon, alt

        else:
            return self.debug_pos_function()
