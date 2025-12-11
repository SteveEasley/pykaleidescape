"""Simple example demonstrating basic volume handling with Kaleidescape.

Connects to a player and:
  1. Waits for a VOLUME_QUERY event coming from a Kaleidescape mobile app
  2. Responds with a VOLUME_CAPABILITIES bitmask set to 31 (all capabilities enabled)
  3. Sends a VOLUME_LEVEL of 20
  4. Sends a MUTE state of False
"""

import asyncio

import logging
import sys

from kaleidescape import Device, const

logging.basicConfig(level=logging.DEBUG)

# Volume Capabilities bitmask to 31
CAPS = (
    const.VOLUME_CAPABILITIES_VOLUME_CONTROL
    | const.VOLUME_CAPABILITIES_MUTE_CONTROL
    | const.VOLUME_CAPABILITIES_VOLUME_FEEDBACK
    | const.VOLUME_CAPABILITIES_MUTE_FEEDBACK
    | const.VOLUME_CAPABILITIES_SET_VOLUME
)


async def main():
    if not len(sys.argv) == 2:
        print(f"Usage: {sys.argv[0]} <ip>")
        sys.exit(1)

    device = Device(sys.argv[1])

    done = asyncio.Event()

    async def _handle(event, params: list[str] = None):
        if event != const.USER_DEFINED_EVENT:
            return

        command = params[0]

        if command == const.USER_DEFINED_EVENT_VOLUME_QUERY:
            print("Received VOLUME_QUERY event, sending volume info then exiting")
            await device.set_volume_capabilities(CAPS)
            await device.set_volume_level(20)
            await device.set_volume_muted(False)
            done.set()

    device.dispatcher.connect(_handle)

    await device.connect()
    await device.refresh()

    print("Waiting for VOLUME_QUERY event... Press Ctrl+C to exit.")

    try:
        await done.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await device.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
