import asyncio

import logging
from kaleidescape import const, Device

# pylint: disable=all

logging.basicConfig(level=logging.DEBUG)


async def main():
    # Use "my-kaleidescape" on Windows
    device = Device("my-kaleidescape.local")
    await device.connect()
    await device.refresh()

    print(f"Power state is currently: {device.power.state}")

    if device.power.state == const.DEVICE_POWER_STATE_STANDBY:
        await device.leave_standby()
        print(f"Power state is now: {device.power.state}")
        await asyncio.sleep(2)

    await device.enter_standby()
    print(f"Power state is now: {device.power.state}")


if __name__ == "__main__":
    asyncio.run(main())
