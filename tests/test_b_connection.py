"""Tests for connection module."""
import asyncio
from unittest.mock import MagicMock, patch

import dns.exception
import pytest
from dns.rdtypes.IN.A import A

from kaleidescape.const import STATE_CONNECTED, STATE_DISCONNECTED, STATE_RECONNECTING
from kaleidescape.connection import Connection
from kaleidescape.dispatcher import Dispatcher

from . import create_signal
from .emulator import Emulator

# pylint: disable=unused-argument


def test_init():
    """Test init sets properties."""
    connection = Connection(Dispatcher())
    assert isinstance(connection.dispatcher, Dispatcher)


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
    """Test connect fails when host not available."""
    connection = Connection(Dispatcher())
    with pytest.raises(ConnectionError):
        await connection.connect("0.0.0.1", port=10001, timeout=1)

    # Also fails for initial connection even with reconnect.
    with pytest.raises(ConnectionError):
        await connection.connect("0.0.0.1", port=10001, timeout=1, reconnect=True)


@pytest.mark.asyncio
async def test_connect_succeeds(emulator: Emulator):
    """Test connect updates state and emits signal."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher)
    assert connection.state == STATE_DISCONNECTED
    signal = create_signal(dispatcher, STATE_CONNECTED)
    await connection.connect("127.0.0.1", port=10001, timeout=1)
    await signal.wait()
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


@pytest.mark.asyncio
async def test_event_disconnect(emulator: Emulator, connection: Connection):
    """Test connection error during event results in disconnected."""
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

    # Assert connection
    await connection.connect(
        "127.0.0.1", port=10001, timeout=1, reconnect=True, reconnect_delay=1
    )
    await connect_signal.wait()
    assert connection.state == STATE_CONNECTED
    connect_signal.clear()

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

    connect_signal = create_signal(dispatcher, STATE_CONNECTED)
    disconnect_signal = create_signal(dispatcher, STATE_DISCONNECTED)

    # Assert open and fires connected
    await connection.connect(
        "127.0.0.1", port=10001, timeout=1, reconnect=True, reconnect_delay=0.5
    )
    await connect_signal.wait()
    assert connection.state == STATE_CONNECTED

    # Assert transitions to reconnecting and emits disconnect signal
    await emulator.stop()
    await disconnect_signal.wait()
    assert connection.state == STATE_RECONNECTING

    await connection.disconnect()
    assert connection.state == STATE_DISCONNECTED


@pytest.mark.asyncio
async def test_resolve_succeeds(emulator: Emulator):
    """Test resolve when host name resolution succeeds."""
    with patch("dns.asyncresolver.Resolver.resolve") as mock:
        mock.return_value = [MagicMock(spec=A)]
        mock.return_value[0].to_text.side_effect = [
            "127.0.0.1",  # 1st call: mDSN succeeds
            dns.exception.DNSException,  # 2nd call: mDSN fails
            "127.0.0.1"  # 2nd call: DSN succeeds
        ]
        # First call simulates mDNS lookup
        assert await Connection.resolve("my-kaleidescape") == "127.0.0.1"
        # Second call simulates DNS lookup
        assert await Connection.resolve("some-kaleidescape") == "127.0.0.1"


@pytest.mark.asyncio
async def test_resolve_fails(emulator: Emulator):
    """Test resolve when host name resolution fails."""
    with patch("dns.asyncresolver.Resolver.resolve") as mock:
        mock.return_value = [MagicMock(spec=A)]
        mock.return_value[0].to_text.side_effect = dns.exception.DNSException
        with pytest.raises(ConnectionError) as err:
            assert await Connection.resolve("my-kaleidescape") == "127.0.0.1"
        assert isinstance(err.value, ConnectionError)
        assert str(err.value) == "Failed to resolve host my-kaleidescape"
