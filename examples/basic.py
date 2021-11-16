import asyncio
import logging

from kaleidescape import Kaleidescape

logging.basicConfig(level=logging.DEBUG)

# pylint: disable=all


async def main():
    # Use "my-kaleidescape" on Windows
    kaleidescape = Kaleidescape("my-kaleidescape.local")
    await kaleidescape.connect()
    device = await kaleidescape.get_local_device()
    print(f"Power state is currently: {device.power.state}")
    await kaleidescape.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
