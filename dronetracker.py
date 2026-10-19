"""DroneTracker entry point: python dronetracker.py [--config config.yml]"""
import argparse
import logging
import signal
import sys
import threading
import time

from tracker.config import ConfigError, load_config


def main(argv=None):
    parser = argparse.ArgumentParser(description="Point an AXIS PTZ camera at drones reported over Kafka.")
    parser.add_argument("--config", default="config.yml", help="path to the config file (default: config.yml)")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except (OSError, ConfigError) as error:
        print(f"Config error: {error}", file=sys.stderr)
        return 2

    level = getattr(logging, cfg["logs"].upper())
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("kafka").setLevel(max(level, logging.WARNING))
    logging.getLogger("urllib3").setLevel(max(level, logging.INFO))
    log = logging.getLogger("dronetracker")

    # Imported after logging is configured, so no module can claim the root logger first
    from tracker.app import App
    from tracker.bus import KafkaBus
    from tracker.camera import make_camera_factory

    stop = threading.Event()

    def request_stop(signum, _):
        stop.set()
        signal.signal(signum, signal.SIG_DFL)  # A second signal kills a slow shutdown

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_stop)

    bus = KafkaBus(cfg["kafka"])
    if not bus.connect(stop):
        return 0
    app = App(cfg, make_camera_factory(cfg), send=bus.send)
    data_topic, command_topic = cfg["kafka"]["data_topic"], cfg["kafka"]["command_topic"]
    period = 1 / cfg["control"]["hz"]
    errors = 0
    try:
        while not stop.is_set():
            started = time.monotonic()
            try:
                for topic, key, value in bus.poll():
                    try:
                        if topic == data_topic:
                            app.on_data(key, value, time.time())
                        elif topic == command_topic:
                            app.on_command(key, value)
                    except Exception:  # One bad message mustn't cost the rest of the batch
                        log.exception(f"Error handling {topic} message {key!r}")
                app.step(time.time())
                errors = 0
            except Exception:  # One bad tick shouldn't take down tracking; log it, make the camera safe, carry on
                errors += 1
                if errors == 1 or errors % 600 == 0:
                    log.exception(f"Error in tracking loop ({errors} ticks in a row)")
                app.stop_camera()
            elapsed = time.monotonic() - started
            if elapsed > period:
                log.debug(f"Tick took {elapsed * 1000:.0f} ms, over the {period * 1000:.0f} ms budget")
            stop.wait(max(0.0, period - elapsed))
    finally:
        log.info("Shutting down")
        app.shutdown()
        bus.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
