"""Tests for connection module."""

import asyncio
from unittest.mock import patch

import pytest

from kaleidescape.connection import Connection
from kaleidescape.const import STATE_CONNECTED, STATE_DISCONNECTED, STATE_RECONNECTING
from kaleidescape.dispatcher import Dispatcher
from kaleidescape.message import Response

from . import create_signal
from .emulator import Emulator

# pylint: disable=unused-argument


@pytest.mark.asyncio
async def test_init():
    """Test init sets properties."""
    connection = Connection(Dispatcher())
    assert isinstance(connection.dispatcher, Dispatcher)
    await connection.disconnect()


@pytest.mark.asyncio
async def test_connect_fails():
    """Test connect fails when host not available."""
    connection = Connection(Dispatcher())
    with pytest.raises(ConnectionError) as err:
        await connection.connect("127.0.0.1", port=10001, timeout=1)
    assert isinstance(err.value, ConnectionRefusedError)

    # Also fails for initial connection even with reconnect.
    with pytest.raises(ConnectionError) as err:
        await connection.connect("127.0.0.1", port=10001, timeout=1, reconnect=True)
    assert isinstance(err.value, ConnectionRefusedError)


@pytest.mark.asyncio
async def test_connect_timeout():
    """Test connect timeout when host not available."""
    connection = Connection(Dispatcher())
    with pytest.raises(ConnectionError):
        await connection.connect("0.0.0.1", port=10001, timeout=1)

    # Also fails for initial connection even with reconnect.
    with pytest.raises(ConnectionError):
        await connection.connect("0.0.0.1", port=10001, timeout=1, reconnect=True)


@pytest.mark.asyncio
async def test_connect_succeeds(emulator: Emulator):
    """Test connect updates state without emitting signal."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher)
    assert connection.state == STATE_DISCONNECTED
    await connection.connect("127.0.0.1", port=10001, timeout=1)
    assert connection.ip == "127.0.0.1"
    assert connection.port == 10001
    assert connection.timeout == 1
    assert connection.state == STATE_CONNECTED
    await connection.disconnect()


@pytest.mark.asyncio
async def test_manual_disconnect(emulator: Emulator, connection: Connection):
    """Test disconnect updates state and emits signal."""
    signal = create_signal(connection.dispatcher, STATE_DISCONNECTED)
    await connection.disconnect()
    await signal.wait()
    assert connection.state == STATE_DISCONNECTED
    # await emulator.stop()


@pytest.mark.asyncio
async def test_event_disconnect(emulator: Emulator, connection: Connection):
    """Test connection error during event results in disconnected."""
    assert connection.state == STATE_CONNECTED
    signal = create_signal(connection.dispatcher, STATE_DISCONNECTED)
    await emulator.stop()
    await signal.wait()
    assert connection.state == STATE_DISCONNECTED


@pytest.mark.asyncio
async def test_reconnect_during_event(emulator: Emulator):
    """Test reconnect while waiting for events/responses."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher)

    connect_signal = create_signal(dispatcher, STATE_CONNECTED)
    disconnect_signal = create_signal(dispatcher, STATE_DISCONNECTED)

    # Initial connect - no STATE_CONNECTED signal expected
    await connection.connect(
        "127.0.0.1", port=10001, timeout=1, reconnect=True, reconnect_delay=1
    )
    assert connection.state == STATE_CONNECTED

    # Allow emulator to register the client before stopping
    await asyncio.sleep(0.1)

    # Assert transitions to reconnecting and emits disconnect signal
    await emulator.stop()
    await disconnect_signal.wait()
    assert connection.state == STATE_RECONNECTING

    # Assert reconnects once server is back up and emits connected signal
    await emulator.start()
    await connect_signal.wait()
    assert connection.state == STATE_CONNECTED

    await connection.disconnect()


@pytest.mark.asyncio
async def test_reconnect_cancelled(emulator):
    """Test reconnect is canceled by calling disconnect."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher)

    disconnect_signal = create_signal(dispatcher, STATE_DISCONNECTED)

    # Initial connect - no STATE_CONNECTED signal expected
    await connection.connect(
        "127.0.0.1", port=10001, timeout=1, reconnect=True, reconnect_delay=0.5
    )
    assert connection.state == STATE_CONNECTED

    # Allow emulator to register the client before stopping
    await asyncio.sleep(0.1)

    # Assert transitions to reconnecting and emits disconnect signal
    await emulator.stop()
    await disconnect_signal.wait()
    assert connection.state == STATE_RECONNECTING

    await connection.disconnect()
    assert connection.state == STATE_DISCONNECTED


@pytest.mark.asyncio
async def test_unhandled_exception_triggers_reconnect(emulator: Emulator):
    """Test that unhandled exceptions in _response_handler trigger reconnect."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher)

    connect_signal = create_signal(dispatcher, STATE_CONNECTED)
    disconnect_signal = create_signal(dispatcher, STATE_DISCONNECTED)

    await connection.connect(
        "127.0.0.1", port=10001, timeout=1, reconnect=True, reconnect_delay=0.5
    )
    assert connection.state == STATE_CONNECTED

    # Allow emulator to register the client
    await asyncio.sleep(0)

    # Patch Response.factory to raise an unexpected exception, simulating an
    # unhandled error in the response handler loop.
    with patch.object(Response, "factory", side_effect=RuntimeError("simulated")):
        await emulator.send_event(["01"], 0, "DEVICE_POWER_STATE", ["0"])
        await asyncio.wait_for(disconnect_signal.wait(), timeout=2)

    # Handler should have exited and triggered reconnect
    assert connection.state == STATE_RECONNECTING

    # Reconnect should succeed and emit STATE_CONNECTED
    await connect_signal.wait()
    assert connection.state == STATE_CONNECTED

    await connection.disconnect()


@pytest.mark.asyncio
async def test_connect_does_not_dispatch_connected(emulator: Emulator):
    """Test that initial connect does not dispatch STATE_CONNECTED signal."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher)
    signal_received = False

    async def on_signal(event, *args):
        nonlocal signal_received
        if event == STATE_CONNECTED:
            signal_received = True

    dispatcher.connect(on_signal)

    await connection.connect("127.0.0.1", port=10001, timeout=1)
    assert connection.state == STATE_CONNECTED

    # Give any pending tasks a chance to run
    await asyncio.sleep(0.05)

    assert not signal_received, "STATE_CONNECTED should not be dispatched during initial connect"

    await connection.disconnect()
