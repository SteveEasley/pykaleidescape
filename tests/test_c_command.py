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
from .emulator import Emulator, NoResponse

# pylint: disable=unused-argument


@pytest.mark.asyncio
async def test_command_succeeds(connection: Connection):
    """Test command succeeds."""
    req = messages.GetAvailableDevices()
    res = cast(messages.AvailableDevices, (await req.send(connection))[0])
    assert res.field == [LOCAL_CPDID]


@pytest.mark.asyncio
async def test_command_fails(emulator: Emulator, connection: Connection):
    """Test an error status in the response raises MessageError with that code."""
    emulator.register_mock_command(
        ("01",),
        messages.GetAvailableDevices.name,
        (const.ERROR_DEVICE_UNAVAILABLE, messages.AvailableDevices.name),
    )
    with pytest.raises(MessageError) as err:
        await messages.GetAvailableDevices().send(connection)
    assert err.value.code == const.ERROR_DEVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_command_timeout(emulator: Emulator):
    """Test a command that gets no response within the timeout raises."""
    connection = Connection(Dispatcher())
    await connection.connect("127.0.0.1", port=emulator.port, timeout=0.1)

    with pytest.raises(KaleidescapeError) as err:
        await NoResponse().send(connection)
    assert isinstance(err.value.__cause__, TimeoutError)

    await connection.disconnect()


@pytest.mark.asyncio
async def test_timeouts_release_sequence_numbers(emulator: Emulator):
    """Test timed out requests free their seq, since only 10 can be in flight."""
    connection = Connection(Dispatcher())
    await connection.connect("127.0.0.1", port=emulator.port, timeout=0.1)

    results = await asyncio.gather(
        *[NoResponse().send(connection) for _ in range(10)], return_exceptions=True
    )
    assert all(isinstance(r, KaleidescapeError) for r in results)

    res = cast(
        messages.AvailableDevices,
        (await messages.GetAvailableDevices().send(connection))[0],
    )
    assert res.field == [LOCAL_CPDID]

    await connection.disconnect()


@pytest.mark.asyncio
async def test_timed_out_sequence_number_reused_last(emulator: Emulator):
    """Test sequence numbers rotate, so a timed out one is the last to be reused."""
    connection = Connection(Dispatcher())
    await connection.connect("127.0.0.1", port=emulator.port, timeout=0.1)

    with pytest.raises(KaleidescapeError):
        await NoResponse().send(connection)
    assert emulator.requests_named(NoResponse.name)[0].seq == 0

    seqs = [
        (await messages.GetAvailableDevices().send(connection))[0].seq
        for _ in range(10)
    ]
    assert seqs == [1, 2, 3, 4, 5, 6, 7, 8, 9, 0]

    await connection.disconnect()


@pytest.mark.asyncio
async def test_commands_fail_when_disconnected(emulator: Emulator):
    """Test calling commands fail when disconnected."""
    connection = Connection(Dispatcher())
    await connection.connect("127.0.0.1", port=emulator.port, timeout=1)
    await connection.disconnect()
    assert connection.state == const.STATE_DISCONNECTED
    with pytest.raises(KaleidescapeError) as err:
        await messages.GetAvailableDevices().send(connection)
    assert str(err.value) == "Not connected to device"


@pytest.mark.asyncio
async def test_command_fails_while_reconnecting(emulator: Emulator):
    """Test commands fail fast while reconnecting, then work once reconnected."""
    dispatcher = Dispatcher()
    connection = Connection(dispatcher)
    connect_signal = create_signal(dispatcher, STATE_CONNECTED)
    disconnect_signal = create_signal(dispatcher, STATE_DISCONNECTED)

    await connection.connect(
        "127.0.0.1", port=emulator.port, timeout=1, reconnect=True, reconnect_delay=0.1
    )
    await emulator.wait_for_client()
    await emulator.stop()
    await disconnect_signal.wait()
    assert connection.state == const.STATE_RECONNECTING

    with pytest.raises(KaleidescapeError) as err:
        await messages.GetAvailableDevices().send(connection)
    assert str(err.value) == "Not connected to device"

    await emulator.start()
    await connect_signal.wait()
    res = cast(
        messages.AvailableDevices,
        (await messages.GetAvailableDevices().send(connection))[0],
    )
    assert res.field == [LOCAL_CPDID]

    await connection.disconnect()


@pytest.mark.asyncio
async def test_get_available_devices_by_serial_number(connection: Connection):
    """Test command."""
    req = messages.GetAvailableDevicesBySerialNumber()
    res = cast(messages.AvailableDevicesBySerialNumber, (await req.send(connection))[0])
    assert res.field == ["00000000123A"]


@pytest.mark.asyncio
async def test_get_device_info(connection: Connection):
    """Test command with single device."""
    req = messages.GetDeviceInfo()
    res = cast(messages.DeviceInfo, (await req.send(connection))[0])
    assert res.field_serial_number == "00000000123A"
    assert res.field_cpdid == ""
    assert res.field_ip == "127.0.0.1"


@pytest.mark.asyncio
async def test_concurrency(connection: Connection):
    """Test requests beyond the 10 sequence numbers wait for one to free up."""
    requests = [messages.GetAvailableDevices() for _ in range(12)]

    responses = await asyncio.gather(*[r.send(connection) for r in requests])

    assert all(
        cast(messages.AvailableDevices, r[0]).field == [LOCAL_CPDID] for r in responses
    )
    seqs = sorted(r[0].seq for r in responses)
    assert seqs == [0, 0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9]
