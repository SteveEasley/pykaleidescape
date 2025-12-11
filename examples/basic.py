"""Simple example demonstrating basic power control with Kaleidescape."""

import asyncio

import sys
from kaleidescape import const, Device


async def main():
    if not len(sys.argv) == 2:
        print(f"Usage: {sys.argv[0]} <ip>")
        sys.exit(1)

    device = Device(sys.argv[1])

    await device.connect()
    await device.refresh()

    print(f"Power state is currently: {device.power.state}")

    if device.power.state == const.DEVICE_POWER_STATE_STANDBY:
        print("Turning player on...")
        await device.leave_standby()
        await asyncio.sleep(2)
        print(f"Power state is now: {device.power.state}")

    print("Turning player off...")
    await device.enter_standby()
    await asyncio.sleep(2)
    print(f"Power state is now: {device.power.state}")


if __name__ == "__main__":
    asyncio.run(main())
