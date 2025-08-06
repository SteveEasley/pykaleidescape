"""pytest fixtures"""

import asyncio

import pytest_asyncio

from kaleidescape.connection import Connection
from kaleidescape.dispatcher import Dispatcher
from tests.emulator import Emulator


@pytest_asyncio.fixture(name="emulator")
async def fixture_emulator():
    """Fixture for creating a device emulator."""
    emulator = Emulator("127.0.0.1", port=10001)
    await emulator.start()
    yield emulator
    await emulator.stop()


@pytest_asyncio.fixture(name="connection")
async def fixture_connection():
    """Fixture for creating a connection to device."""
    connection = Connection(Dispatcher())
    await connection.connect("127.0.0.1", port=10001, timeout=1)
    yield connection
    await asyncio.sleep(0.01)
    await connection.disconnect()
