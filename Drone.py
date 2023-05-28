import time


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
