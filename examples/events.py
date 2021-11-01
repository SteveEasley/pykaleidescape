import asyncio

from kaleidescape import Kaleidescape, const

# pylint: disable=all


async def controller_event(event: str):
    print(f"controller_event: {event}")


async def device_event(device_id: str, event: str):
    print(f"device_event: {device_id}, {event}")


async def main():
    kaleidescape = Kaleidescape("my-kaleidescape.local")
    kaleidescape.dispatcher.connect(const.SIGNAL_CONTROLLER_EVENT, controller_event)
    kaleidescape.dispatcher.connect(const.SIGNAL_DEVICE_EVENT, device_event)
    await kaleidescape.connect()

    device = await kaleidescape.get_device()

    if device.power.state == const.DEVICE_POWER_STATE_STANDBY:
        await device.leave_standby()
        await asyncio.sleep(2)

    await device.enter_standby()
    await asyncio.sleep(2)

    await kaleidescape.disconnect()
    await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
