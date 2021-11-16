import asyncio

import logging
from kaleidescape import Kaleidescape, const

# pylint: disable=all

# logging.basicConfig(level=logging.DEBUG)


async def main():
    # Use "my-kaleidescape" on Windows
    kaleidescape = Kaleidescape("my-kaleidescape.local")
    await kaleidescape.connect(auto_reconnect=True)
    device = await kaleidescape.get_local_device()
    print(f"Power state is currently: {device.power.state}")

    if device.power.state == const.DEVICE_POWER_STATE_STANDBY:
        await device.leave_standby()
        print(f"Power state is now: {device.power.state}")
        await asyncio.sleep(2)

    await device.enter_standby()
    print(f"Power state is now: {device.power.state}")

    await kaleidescape.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
