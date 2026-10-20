"""
Publish simulated drone positions to Kafka in real time, for testing a running DroneTracker end to end.

    python utils/fake_drones.py pair                     # two drones
    python utils/fake_drones.py --hover 35.7276 -78.6957 120 --seconds 30
"""
import argparse
import json
import os
import random
import sys
import time

import kafka

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.config import load_config  # noqa: E402
from tracker.geometry import LocalFrame  # noqa: E402
from tracker.simulation import SCENARIOS, make_message, scenario  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", nargs="?", default="orbit", choices=SCENARIOS)
    parser.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "..", "config.yml"))
    parser.add_argument("--hz", type=float, default=5.0, help="messages per second per drone")
    parser.add_argument("--noise", type=float, default=1.0, help="GPS noise, metres")
    parser.add_argument("--hover", nargs=3, type=float, metavar=("LAT", "LON", "ALT_MSL"),
                        help="instead of a scenario, report one stationary drone here")
    parser.add_argument("--seconds", type=float, help="stop after this long (default: the scenario's length)")
    parser.add_argument("--mode", choices=("on", "auto"), help="also send track_camera <mode> first")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cam = cfg["camera"]
    frame = LocalFrame(cam["lat"], cam["lon"], cam["alt"])
    producer = kafka.KafkaProducer(bootstrap_servers=cfg["kafka"]["servers"])
    if args.mode:
        producer.send(cfg["kafka"]["command_topic"], key=b"track_camera", value=args.mode.encode())

    if args.hover:
        lat, lon, alt = args.hover
        drones, duration = None, args.seconds or 60
    else:
        drones, duration = scenario(args.scenario)
        duration = args.seconds or duration
    rng = random.Random()
    start = time.time()
    sent = 0
    while (now := time.time()) - start < duration:
        if drones is None:
            body = {"drone_id": "hover", "t": now, "position": {"latitude": lat, "longitude": lon, "altitude": alt}}
            producer.send(cfg["kafka"]["data_topic"], key=b"hover", value=json.dumps(body).encode())
            sent += 1
        else:
            for drone in drones:
                if drone.flying(now - start):
                    key, value = make_message(drone, now - start, now, frame, rng, args.noise)
                    producer.send(cfg["kafka"]["data_topic"], key=key, value=value)
                    sent += 1
        print(f"\r{now - start:6.1f}s  {sent} messages sent", end="", flush=True)
        time.sleep(max(0.0, 1 / args.hz - (time.time() - now)))
    producer.flush()
    print()


if __name__ == "__main__":
    main()
