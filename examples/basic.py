import asyncio
import logging

from kaleidescape import Kaleidescape

logging.basicConfig(level=logging.DEBUG)


async def main():
    kaleidescape = Kaleidescape('my-kaleidescape.local')  # or "my-kaleidescape" on Windows
    await kaleidescape.connect(auto_reconnect=True)
    device = await kaleidescape.get_device()
    print(f"Power state is currently: {device.power.state}")
    await kaleidescape.disconnect()

if __name__ == "__main__":
    asyncio.run(main())