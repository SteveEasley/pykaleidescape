import asyncio

import logging
from kaleidescape import Device, const

# logging.basicConfig(level=logging.DEBUG)
# pylint: disable=all


async def device_event(event: str):
    print(f"event: {event}")


async def main():
    # Use "my-kaleidescape" on Windows
    device = Device("my-kaleidescape.local")

    device.dispatcher.connect(device_event)

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
