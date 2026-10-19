"""
Send a command to a running DroneTracker over Kafka and print what comes back on the output topic.

    python utils/command.py status
    python utils/command.py track_camera auto
    python utils/command.py select uav2
    python utils/command.py list_recordings
    python utils/command.py --watch          # just print events and replies until Ctrl-C
"""
import argparse
import os
import sys
import time

import kafka

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.config import load_config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", help="track_camera, select, priority, status, list_recordings, ...")
    parser.add_argument("value", nargs="*", help="the command's argument(s)")
    parser.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "..", "config.yml"))
    parser.add_argument("--watch", action="store_true", help="keep printing output until interrupted")
    parser.add_argument("--wait", type=float, default=3.0, help="seconds to wait for a reply")
    args = parser.parse_args()
    if not args.command and not args.watch:
        parser.error("give a command, or --watch")

    cfg = load_config(args.config)["kafka"]
    consumer = kafka.KafkaConsumer(cfg["output_topic"], bootstrap_servers=cfg["servers"], auto_offset_reset="latest")
    consumer.poll(timeout_ms=1000)  # Join the topic before sending, so the reply isn't missed
    if args.command:
        producer = kafka.KafkaProducer(bootstrap_servers=cfg["servers"])
        producer.send(cfg["command_topic"], key=args.command.encode(), value=" ".join(args.value).encode())
        producer.flush()

    deadline = time.time() + args.wait
    try:
        while args.watch or time.time() < deadline:
            for records in consumer.poll(timeout_ms=200).values():
                for record in records:
                    key = record.key.decode(errors="replace") if record.key else ""
                    print(f"{key}: {record.value.decode(errors='replace')}")
                    if key == args.command and not args.watch:
                        return
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
