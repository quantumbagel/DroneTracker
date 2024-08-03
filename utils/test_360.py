"""
A test program to send data to a Kafka server and go around in a 360 degree circle.
"""

import json
import time
import kafka
import math
lat = 35.727481
long = -78.695925
alt = 85.763
consumer = kafka.KafkaProducer(bootstrap_servers=['192.168.60.202:9092'])
consumer.send("dronetracker-command", key=b"track_camera", value=b"on")

n = 100
r = 0.01
points = [(math.cos(2*math.pi/n*x)*r,math.sin(2*math.pi/n*x)*r) for x in range(0,n+1)]
delay = 0.1

for i in points:
    t = time.time()
    consumer.send("dronetracker-data", json.dumps({"position": {"latitude": i[0] + lat,
                                                                "longitude": i[1] + long,
                                                                "altitude": alt},
                                                   "velocity": {"x": 0, "y": 0, "z": 0}}).encode("utf-8"))
    delta = delay - (time.time()-t)
    if delta > 0:
        time.sleep(delta)
consumer.send("dronetracker-command", key=b"track_camera", value=b"off")
