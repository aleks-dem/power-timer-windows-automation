from __future__ import annotations

import sys
import argparse

from ui.app import PowerTimerApp
from util.single_instance import (
    acquire_single_instance,
    release_single_instance,
    signal_show_event,
    SINGLE_INSTANCE_NAME,
    SHOW_EVENT_NAME,
)


def main() -> int:
    if sys.platform != "win32":
        print("Windows-only.")
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Reserved (not used in this build).")
    args = parser.parse_args()

    mutex = acquire_single_instance(SINGLE_INSTANCE_NAME)
    if not mutex:
        signal_show_event(SHOW_EVENT_NAME)
        return 1

    app = PowerTimerApp()
    try:
        app.run()
    finally:
        release_single_instance(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
