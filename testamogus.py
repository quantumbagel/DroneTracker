import math
from ruamel.yaml import YAML
config = YAML().load(open("config.yml"))

dist_xz = 30
dist_y = 0


dist = math.sqrt(dist_xz ** 2 + dist_y ** 2)
# Determine the maximum relative "size" of the drone relative to the camera
max_dimension = 1
zoom = (dist * config['scale']['width']) / (config['scale']['dist'] * max_dimension)  # Zoom is linear
# zoom = round(((zoom - 1) / (config['camera']['maximum_zoom'] - 1)) * 9999)  # Ensure zoom cap
zoom *= 1 / 5  # Account for the "fudge factor"
print(zoom)