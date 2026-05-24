from __future__ import annotations

import argparse
import time

from .scheduler import RoomBrain


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the object-ecology room-brain loop.")
    parser.add_argument("--root", default=None, help="Project root. Defaults to this checkout.")
    parser.add_argument("--once", action="store_true", help="Poll health once and exit.")
    args = parser.parse_args()

    brain = RoomBrain(args.root)
    interval = float(brain.configs["room"]["timing"].get("poll_interval_seconds", 2.0))

    while True:
        responses = brain.poll_health()
        for response in responses:
            print(response)
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
