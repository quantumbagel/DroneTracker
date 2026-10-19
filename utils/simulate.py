"""
Fly simulated drones against the full tracker and a simulated camera, offline (no Kafka, no camera), and report
how well the camera kept them in frame. Useful for tuning control/ and framing/ settings before a field test.

    python utils/simulate.py                      # every scenario, with ../config.yml
    python utils/simulate.py pair --trace out.csv # one scenario, with a per-tick CSV
"""
import argparse
import csv
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.config import load_config  # noqa: E402
from tracker.simulation import SCENARIOS, run_simulation  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenarios", nargs="*", metavar="scenario",
                        help=f"any of: {', '.join(SCENARIOS)} (default: all)")
    parser.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "..", "config.yml"))
    parser.add_argument("--msg-hz", type=float, default=5.0, help="position reports per second per drone")
    parser.add_argument("--noise", type=float, default=1.5, help="GPS noise, metres (1 sigma)")
    parser.add_argument("--msg-latency", type=float, default=0.15, help="mean message transit time, s")
    parser.add_argument("--camera-latency", type=float, default=0.1, help="camera command latency, s")
    parser.add_argument("--speed-error", type=float, default=0.85,
                        help="real camera speed / configured speed (models calibration error)")
    parser.add_argument("--format", choices=("v2", "v1"), default="v2", help="message format to send")
    parser.add_argument("--trace", help="write per-tick samples to this CSV (only with one scenario)")
    args = parser.parse_args()
    unknown = set(args.scenarios) - set(SCENARIOS)
    if unknown:
        parser.error(f"unknown scenario(s) {', '.join(sorted(unknown))}; choose from {', '.join(SCENARIOS)}")
    if args.trace and len(args.scenarios) != 1:
        parser.error("--trace needs exactly one scenario")
    logging.basicConfig(level=logging.WARNING)

    cfg = load_config(args.config)
    for name in args.scenarios or SCENARIOS:
        result = run_simulation(cfg, name, msg_hz=args.msg_hz, noise=args.noise, msg_latency=args.msg_latency,
                                camera_latency=args.camera_latency, speed_error=args.speed_error, fmt=args.format,
                                trace=bool(args.trace))
        print(f"{name:9} in frame {result['in_frame_pct']:5.1f}% over {result['tracked_seconds']:5.1f}s | "
              f"error rms {result['rms_error_deg']}° max {result['max_error_deg']}° | "
              f"pan accel rms {result['rms_pan_accel']}°/s² | {result['camera_commands']} commands")
        if args.trace:
            with open(args.trace, "w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(result["trace"][0]))
                writer.writeheader()
                writer.writerows(result["trace"])
            print(f"Wrote {len(result['trace'])} samples to {args.trace}")


if __name__ == "__main__":
    main()
