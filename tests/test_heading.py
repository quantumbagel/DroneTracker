import math
import unittest
import Camera
import Drone


class TestHeading(unittest.TestCase):
    def test_no_change_lat_long(self):
        d = Drone.Drone(lambda: [20.5, 20.5, 1])
        c = Camera.Camera(lat='20.5', long='20.5', alt=0.0, drone=d, lat_long_format='decimal')
        self.assertEqual(c.calculate_heading_directions(), (0, math.pi/2))

    def test_no_change(self):
        d = Drone.Drone(lambda: [20.5, 20.5, 0])
        c = Camera.Camera(lat='20.5', long='20.5', alt=0.0, drone=d, lat_long_format='decimal')
        self.assertEqual(c.calculate_heading_directions(), (0, 0))


if __name__ == '__main__':
    unittest.main()