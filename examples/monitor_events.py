"""
Connect to a Kaleidescape device and stream its events until interrupted.

Usage:
    python -m examples.monitor_events <hostname-or-ip>

Defaults to ``my-kaleidescape.local`` if no host is provided. Press Ctrl+C to
stop. Pass ``--volume-events`` to request user-defined volume events in
addition to the standard system events.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import datetime

from kaleidescape import Device


async def main(host: str, enable_volume: bool) -> None:
    """Connect to the device, attach an event listener, and run until stopped."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    device = Device(host)

    async def log_event(event: str) -> None:
        print(f"{datetime.now().isoformat(timespec='seconds')}  {event}")

    # Dispatcher pushes every incoming event through this callback
    device.dispatcher.connect(log_event)

    stop_event = asyncio.Event()

    def request_stop() -> None:
        if not stop_event.is_set():
            print("\nStopping event monitor ...")
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            # add_signal_handler may not be available on some platforms (e.g. Windows)
            pass

    try:
        await device.connect()
        await device.refresh()

        if enable_volume:
            await device.enable_volume_events()

        print(
            "Connected. Listening for events from "
            f"{host!r}. Press Ctrl+C to stop."
        )
        await stop_event.wait()
    finally:
        await device.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Monitor events emitted by a Kaleidescape device."
    )
    parser.add_argument(
        "host",
        nargs="?",
        default="my-kaleidescape.local",
        help="Hostname or IP of the device (default: my-kaleidescape.local)",
    )
    parser.add_argument(
        "--volume-events",
        action="store_true",
        help="Request volume/user-defined events in addition to system events.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(args.host, args.volume_events))
    except KeyboardInterrupt:
        # In case the signal handler is unavailable, fall back to graceful exit
        pass
