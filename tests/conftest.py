"""pytest fixtures"""

import pytest_asyncio

from kaleidescape.connection import Connection
from kaleidescape.device import Device
from kaleidescape.dispatcher import Dispatcher
from tests.emulator import Emulator


@pytest_asyncio.fixture(name="emulator")
async def fixture_emulator():
    """Fixture for creating a device emulator."""
    emulator = Emulator("127.0.0.1")
    await emulator.start()
    yield emulator
    await emulator.stop()


@pytest_asyncio.fixture(name="connection")
async def fixture_connection(emulator: Emulator):
    """Fixture for creating a connection to the emulator."""
    connection = Connection(Dispatcher())
    await connection.connect("127.0.0.1", port=emulator.port, timeout=1)
    yield connection
    await connection.disconnect()


@pytest_asyncio.fixture(name="device")
async def fixture_device(emulator: Emulator):
    """Fixture for a device pointed at the emulator, left unconnected so tests can
    register mock commands first."""
    device = Device("127.0.0.1", port=emulator.port)
    yield device
    await device.disconnect()
