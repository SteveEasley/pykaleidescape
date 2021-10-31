"""Tests for connection module."""

import asyncio
from unittest.mock import patch

import pytest

from kaleidescape import const
from kaleidescape.connection import (
    EVENT_CONNECTION_CONNECTED,
    EVENT_CONNECTION_DISCONNECTED,
    Connection,
)
from kaleidescape.dispatcher import Dispatcher

from . import connection_signal
from .emulator import Emulator

# pylint: disable=unused-argument


def test_init():
    """Test init sets properties."""
    connection = Connection(Dispatcher(), "127.0.0.1")
    assert isinstance(connection.dispatcher, Dispatcher)
    assert connection.host == "127.0.0.1"
    assert connection.port == const.DEFAULT_CONNECT_PORT
    assert connection.timeout == const.DEFAULT_CONNECT_TIMEOUT
    assert connection.state == const.STATE_DISCONNECTED

    connection = Connection(Dispatcher(), "127.0.0.1", port=10001, timeout=1)
    assert isinstance(connection.dispatcher, Dispatcher)
    assert connection.host == "127.0.0.1"
    assert connection.port == 10001
    assert connection.timeout == 1
    assert connection.state == const.STATE_DISCONNECTED


@pytest.mark.asyncio
async def test_connect_fails():
    """Test connect fails when host not available."""
    connection = Connection(Dispatcher(), "127.0.0.1", port=10001, timeout=1)
    with pytest.raises(ConnectionError) as err:
        await connection.connect()
    assert isinstance(err.value, ConnectionRefusedError)

    # Also fails for initial connection even with reconnect.
    with pytest.raises(ConnectionError) as err:
        await connection.connect(auto_reconnect=True)
    assert isinstance(err.value, ConnectionRefusedError)


@pytest.mark.asyncio
async def test_connect_timeout():
    """Test connect fails when host not available."""
    connection = Connection(Dispatcher(), "www.google.com", timeout=1)
    with pytest.raises(ConnectionError) as err:
        await connection.connect()
    assert isinstance(err.value.__cause__, asyncio.TimeoutError)

    # Also fails for initial connection even with reconnect.
    with pytest.raises(ConnectionError) as err:
        await connection.connect(auto_reconnect=True)
    assert isinstance(err.value.__cause__, asyncio.TimeoutError)


@pytest.mark.asyncio
async def test_connect_succeeds(emulator: Emulator):
    """Test connect updates state and emits signal."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher, "127.0.0.1", port=10001, timeout=1)
    assert connection.state == const.STATE_DISCONNECTED
    signal = connection_signal(dispatcher, EVENT_CONNECTION_CONNECTED)
    await connection.connect()
    await signal.wait()
    assert connection.state == const.STATE_CONNECTED


@pytest.mark.asyncio
async def test_manual_disconnect(emulator: Emulator, connection: Connection):
    """Test disconnect updates state and emits signal."""
    signal = connection_signal(connection.dispatcher, EVENT_CONNECTION_DISCONNECTED)
    await connection.disconnect()
    await signal.wait()
    assert connection.state == const.STATE_DISCONNECTED


@pytest.mark.asyncio
async def test_event_disconnect(emulator: Emulator, connection: Connection):
    """Test connection error during event results in disconnected."""
    signal = connection_signal(connection.dispatcher, EVENT_CONNECTION_DISCONNECTED)
    await emulator.stop()
    await signal.wait()
    assert connection.state == const.STATE_DISCONNECTED


@pytest.mark.asyncio
async def test_connect_resolve_fails(emulator: Emulator):
    """Test connect fails when host name resolution fails."""
    with patch("socket.gethostbyname") as mock:
        mock.side_effect = OSError
        with pytest.raises(ConnectionError) as err:
            connection = Connection(Dispatcher(), "google.com", timeout=1)
            await connection.connect()
        assert isinstance(err.value, ConnectionError)
        assert str(err.value) == "Failed to resolve host google.com"


@pytest.mark.asyncio
async def test_connect_resolve_succeeds(emulator: Emulator):
    """Test connect fails when host name resolution succeeds."""
    with patch("socket.gethostbyname") as mock:
        mock.return_value = "127.0.0.1"
        dispatcher = Dispatcher()
        connection = Connection(dispatcher, "google.com", port=10001, timeout=1)
        signal = connection_signal(dispatcher, EVENT_CONNECTION_CONNECTED)
        await connection.connect()
        await signal.wait()
        assert connection.state == const.STATE_CONNECTED


@pytest.mark.asyncio
async def test_reconnect_during_event(emulator: Emulator):
    """Test reconnect while waiting for events/responses."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher, "127.0.0.1", port=10001, timeout=1)

    connect_signal = connection_signal(dispatcher, EVENT_CONNECTION_CONNECTED)
    disconnect_signal = connection_signal(dispatcher, EVENT_CONNECTION_DISCONNECTED)

    # Assert connection
    await connection.connect(auto_reconnect=True, reconnect_delay=1)
    await connect_signal.wait()
    assert connection.state == const.STATE_CONNECTED
    connect_signal.clear()

    # Assert transitions to reconnecting and emits disconnect signal
    await emulator.stop()
    await disconnect_signal.wait()
    assert connection.state == const.STATE_RECONNECTING

    # Assert reconnects once server is back up and emits connected signal
    await emulator.start()
    await connect_signal.wait()
    assert connection.state == const.STATE_CONNECTED

    await connection.disconnect()


@pytest.mark.asyncio
async def test_reconnect_cancelled(emulator):
    """Test reconnect is canceled by calling disconnect."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher, "127.0.0.1", port=10001)

    connect_signal = connection_signal(dispatcher, EVENT_CONNECTION_CONNECTED)
    disconnect_signal = connection_signal(dispatcher, EVENT_CONNECTION_DISCONNECTED)

    # Assert open and fires connected
    await connection.connect(auto_reconnect=True, reconnect_delay=0.5)
    await connect_signal.wait()
    assert connection.state == const.STATE_CONNECTED

    # Assert transitions to reconnecting and emits disconnect signal
    await emulator.stop()
    await disconnect_signal.wait()
    assert connection.state == const.STATE_RECONNECTING

    await connection.disconnect()
    assert connection.state == const.STATE_DISCONNECTED
