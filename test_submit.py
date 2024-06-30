import json
import random
import time

import kafka

consumer = kafka.KafkaProducer(bootstrap_servers=['localhost:9092'])
i = 0
alt = 400
lat = 35.751253
long = -78.902028
persec = 1
while True:
    t = time.time()
    newalt = random.random() + alt
    newlat = random.random()/1000000 + lat
    newlong = random.random()/1000000 + long

    consumer.send("dronetracker-data", json.dumps({"position": {"latitude": newlat, "longitude": newlong,
                                                                "altitude": newalt},
                                                   "velocity": {"x": 2, "y": 3, "z": 4}}).encode("utf-8"))
    i += 1
    delta = 1/persec - (time.time()-t)
    if delta > 0:
        print(f"action {newalt, newlat, newlong} completed in {time.time()-t}, sleeping for {delta}"
              f" seconds to survive rate limit of {persec}/sec ({1/persec})")
        time.sleep(delta)
