"""Tests for command module."""
from __future__ import annotations

import asyncio
from typing import cast

import pytest

from kaleidescape import const
from kaleidescape import message as messages
from kaleidescape.connection import Connection

from kaleidescape.const import LOCAL_CPDID, STATE_CONNECTED, STATE_DISCONNECTED
from kaleidescape.dispatcher import Dispatcher
from kaleidescape.error import KaleidescapeError, MessageError

from . import create_signal
from .emulator import Emulator

# pylint: disable=unused-argument


@pytest.mark.asyncio
async def test_command_succeeds(emulator: Emulator, connection: Connection):
    """Test command succeeds."""
    req = messages.GetAvailableDevices()
    res = cast(messages.AvailableDevices, (await req.send(connection))[0])
    assert res.field == [LOCAL_CPDID]


@pytest.mark.asyncio
async def test_command_fails(emulator: Emulator, connection: Connection):
    """Test command fails."""
    emulator.register_mock_command(
        ("01",),
        messages.GetAvailableDevices.name,
        (const.ERROR_DEVICE_UNAVAILABLE, messages.AvailableDevices.name),
    )
    with pytest.raises(MessageError) as err:
        req = messages.GetAvailableDevices()
        await req.send(connection)
    assert const.RESPONSE_ERROR[const.ERROR_DEVICE_UNAVAILABLE] in str(err.value)


@pytest.mark.asyncio
async def test_commands_fail_when_disconnected(emulator: Emulator):
    """Test calling commands fail when disconnected."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher)
    await connection.connect("127.0.0.1", port=10001, timeout=1)
    await connection.disconnect()
    assert connection.state == const.STATE_DISCONNECTED
    with pytest.raises(KaleidescapeError) as err:
        req = messages.GetAvailableDevices()
        await req.send(connection)
    assert str(err.value) == "Not connected to device"


@pytest.mark.asyncio
async def test_reconnect_during_command(emulator: Emulator):
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
    assert connection.state == const.STATE_CONNECTED
    connect_signal.clear()

    # Break connection
    await emulator.stop()
    await emulator.start()

    # Assert command with orphaned connection times out
    with pytest.raises(KaleidescapeError) as err:
        req = messages.GetAvailableDevices()
        await req.send(connection)
    assert "Not connected to device" in str(err.value)

    # Wait for reconnect
    await disconnect_signal.wait()
    await connect_signal.wait()

    # Assert reconnected
    assert connection.state == const.STATE_CONNECTED

    await connection.disconnect()


@pytest.mark.asyncio
async def test_get_available_devices(emulator: Emulator, connection: Connection):
    """Test command."""
    req = messages.GetAvailableDevices()
    res = cast(messages.AvailableDevices, (await req.send(connection))[0])
    assert res.field == [LOCAL_CPDID]


@pytest.mark.asyncio
async def test_get_available_devices_by_serial_number(
    emulator: Emulator, connection: Connection
):
    """Test command."""
    req = messages.GetAvailableDevicesBySerialNumber()
    res = cast(messages.AvailableDevicesBySerialNumber, (await req.send(connection))[0])
    assert res.field == ["00000000123A"]


@pytest.mark.asyncio
async def test_get_device_info(emulator: Emulator, connection: Connection):
    """Test command with single device."""
    req = messages.GetDeviceInfo()
    res = cast(messages.DeviceInfo, (await req.send(connection))[0])
    assert res.field_serial_number == "00000000123A"
    assert res.field_cpdid == ""
    assert res.field_ip == "127.0.0.1"


@pytest.mark.asyncio
async def test_concurrency(emulator: Emulator, connection: Connection):
    """Test command concurrency handling."""
    requests: list[messages.GetAvailableDevices] = []
    for _ in range(0, 12):
        requests.append(messages.GetAvailableDevices())

    responses = await asyncio.gather(*[r.send(connection) for r in requests])

    assert len([r[0].seq for r in responses if r[0].seq == 0]) == 2
    assert len([r[0].seq for r in responses if r[0].seq == 1]) == 2
    assert len([r[0].seq for r in responses if r[0].seq == 2]) == 1
    assert len([r[0].seq for r in responses if r[0].seq == 9]) == 1

    await connection.disconnect()
