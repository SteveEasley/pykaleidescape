"""Simple example demonstrating basic event handling with Kaleidescape.

Connects to a player and:
  1. Registers an event listener that prints all events to the console
  2. Sends a power on then power off command
  3. Disconnects
"""

import asyncio

import logging
import sys

from kaleidescape import Device, const

logging.basicConfig(level=logging.DEBUG)


async def main():
    if not len(sys.argv) == 2:
        print(f"Usage: {sys.argv[0]} <ip>")
        sys.exit(1)

    device = Device(sys.argv[1])

    async def _handle_event(event: str, params: list[str] = None):
        print(f">>> Event Received: {event} {params}")

    device.dispatcher.connect(_handle_event)

    await device.connect()
    await device.refresh()

    if device.power.state == const.DEVICE_POWER_STATE_STANDBY:
        await device.leave_standby()
        await asyncio.sleep(2)

    await device.enter_standby()
    await asyncio.sleep(2)

    await device.disconnect()
    await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
