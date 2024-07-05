"""
A test program to send data to a Kafka server. Just for testing purposes.
"""

import json
import time
import kafka

consumer = kafka.KafkaProducer(bootstrap_servers=['localhost:9092'])
while True:
    lat = float(input("lat: "))
    lon = float(input("lon: "))
    alt = float(input("alt: "))
    delay = float(input("delay: "))
    number_sends = int(input("number_sends: "))
    for i in range(number_sends):
        t = time.time()
        consumer.send("dronetracker-command", b"on")
        consumer.send("dronetracker-data", json.dumps({"position": {"latitude": lat, "longitude": lon,
                                                                    "altitude": alt},
                                                       "velocity": {"x": 0, "y": 0, "z": 0}}).encode("utf-8"))
        delta = delay - (time.time()-t)
        if delta > 0:
            time.sleep(delta)
