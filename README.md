# pykaleidescape

A python library for controlling Kaleidescape devices via the Kaleidescape System Control Protocol.

Note: This library is not operated by, or affiliated with Kaleidescape, Inc.

## Installation

```
pip install pykaleidescape
```

## Usage

Checkout the [examples](examples) directory for more examples.

```python
import asyncio
from kaleidescape import Device


async def main():
    # Use "my-kaleidescape" on Windows
    device = Device("my-kaleidescape.local")
    await device.connect()
    print(f"Power state is currently: {device.power.state}")
    await device.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
```
