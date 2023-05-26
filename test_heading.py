import math
import unittest
import main


class TestHeading(unittest.TestCase):
    def test_no_change_lat_long(self):
        d = main.Drone(lambda: [20.5, 20.5, 1])
        c = main.Camera(lat='20.5', long='20.5', alt=0.0, drone=d, lat_long_format='decimal')
        self.assertEqual(c.calculate_heading_directions(), (0, math.pi/2))

    def test_no_change(self):
        d = main.Drone(lambda: [20.5, 20.5, 0])
        c = main.Camera(lat='20.5', long='20.5', alt=0.0, drone=d, lat_long_format='decimal')
        self.assertEqual(c.calculate_heading_directions(), (0, 0))

    def test_split(self):
        s = 'hello world'
        self.assertEqual(s.split(), ['hello', 'world'])
        # check that s.split fails when the separator is not a string
        with self.assertRaises(TypeError):
            s.split(2)


if __name__ == '__main__':
    unittest.main()