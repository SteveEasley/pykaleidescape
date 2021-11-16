"""pytest fixtures"""

import asyncio

import pytest

from kaleidescape.connection import Connection
from kaleidescape.dispatcher import Dispatcher
from kaleidescape.kaleidescape import Kaleidescape
from tests.emulator import Emulator


@pytest.fixture(name="emulator")
def fixture_emulator(event_loop, request):
    """Fixture for creating a device emulator."""
    fixture = request.param if hasattr(request, "param") else "single_device"
    emulator = Emulator(fixture, "127.0.0.1", port=10001)
    event_loop.run_until_complete(emulator.start())
    yield emulator
    event_loop.run_until_complete(emulator.stop())


@pytest.fixture(name="connection")
def fixture_connection(event_loop):
    """Fixture for creating a connection to device."""
    connection = Connection(Dispatcher())
    event_loop.run_until_complete(
        connection.connect("127.0.0.1", port=10001, timeout=1)
    )
    yield connection
    # Ensure work emulator loop can complete tasks
    event_loop.run_until_complete(asyncio.sleep(0.01))
    event_loop.run_until_complete(connection.disconnect())


@pytest.fixture(name="kaleidescape")
def fixture_kaleidescape(event_loop):
    """Fixture for creating a controller."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001, timeout=1)
    event_loop.run_until_complete(kaleidescape.connect(discovery_port=10080))
    yield kaleidescape
    event_loop.run_until_complete(kaleidescape.disconnect())
