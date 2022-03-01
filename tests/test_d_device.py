"""Tests for device module."""

import asyncio

import pytest

from kaleidescape import const
from kaleidescape import message as messages
from kaleidescape.connection import Connection
from kaleidescape.const import LOCAL_CPDID, SUCCESS
from kaleidescape.device import Device
from kaleidescape.dispatcher import Dispatcher
from kaleidescape.error import KaleidescapeError, MessageError

from . import create_signal
from .emulator import Emulator

# pylint: disable=unused-argument


@pytest.mark.asyncio
async def test_init(emulator: Emulator):
    """Test initialization of device."""
    device = Device("127.0.0.1", port=10001)
    assert isinstance(device.connection, Connection)
    assert isinstance(device.dispatcher, Dispatcher)
    assert device.host == "127.0.0.1"
    assert device.port == 10001
    assert device.is_connected is False
    assert device.serial_number == ""


@pytest.mark.asyncio
async def test_connect(emulator: Emulator):
    """Test initialization of device."""
    device = Device("127.0.0.1", port=10001)
    await device.connect()
    assert device.is_connected

    await device.disconnect()
    assert not device.is_connected


@pytest.mark.asyncio
async def test_get_available_devices(emulator: Emulator):
    """Test get available devices."""
    device = Device("127.0.0.1", port=10001)
    await device.connect()
    fields = await device.get_available_devices()
    assert fields == [LOCAL_CPDID]
    await device.disconnect()


@pytest.mark.asyncio
async def test_get_available_serial_numbers(
    emulator: Emulator
):
    """Test get available devices."""
    device = Device("127.0.0.1", port=10001)
    await device.connect()
    fields = await device.get_available_serial_numbers()
    assert fields == ["00000000123A"]
    await device.disconnect()


@pytest.mark.asyncio
async def test_refresh(emulator: Emulator):
    """Test refreshing system updates state."""
    device = Device("127.0.0.1", port=10001)
    await device.refresh()
    assert device.system.serial_number == "00000000123A"
    assert device.serial_number == "00000000123A"
    assert device.system.cpdid == ""
    assert device.system.ip_address == "127.0.0.1"
    assert device.system.protocol == 16
    assert device.system.kos_version == "10.4.2-19218"
    assert device.system.type == "Strato S"
    assert device.system.friendly_name == "Theater"
    assert device.system.movie_zones == 1
    assert device.system.music_zones == 1
    assert device.power.state == const.DEVICE_POWER_STATE_STANDBY
    assert device.power.readiness == const.SYSTEM_READINESS_STATE_IDLE
    assert device.is_server_only is False
    assert device.is_movie_player is True
    await device.disconnect()


@pytest.mark.asyncio
async def test_refresh_state(emulator: Emulator):
    """Test refreshing state updates state."""
    device = Device("127.0.0.1", port=10001)
    await device.refresh()

    assert device.power.state == const.DEVICE_POWER_STATE_STANDBY
    assert device.osd.ui_screen == const.UI_STATE_SCREEN_UNKNOWN
    assert device.automation.movie_location == const.MOVIE_LOCATION_NONE

    signal = create_signal(
        device.dispatcher, messages.DevicePowerState.name
    )

    emulator.register_mock_command(
        ("01",),
        messages.GetDevicePowerState.name,
        (SUCCESS, messages.DevicePowerState.name, ["1", "1"]),
    )

    await emulator.send_event(
        [LOCAL_CPDID], SUCCESS, messages.DevicePowerState.name, ["1"]
    )

    await asyncio.wait_for(signal.wait(), 1)

    assert device.power.state == const.DEVICE_POWER_STATE_ON
    assert device.osd.ui_screen == const.UI_STATE_SCREEN_MOVIE_LIST
    assert device.automation.movie_location == const.MOVIE_LOCATION_CONTENT

    await device.disconnect()


@pytest.mark.asyncio
async def test_events(emulator: Emulator):
    """Test device events."""
    device = Device("127.0.0.1", port=10001)
    await device.connect()
    # Setup to listen for signal emit
    signal = create_signal(
        device.dispatcher, messages.SystemReadinessState.name
    )
    # Produce a signal
    await emulator.send_event(
        [LOCAL_CPDID], SUCCESS, messages.SystemReadinessState.name, ["0"]
    )
    # Assert signal is received
    await asyncio.wait_for(signal.wait(), 1)

    await device.disconnect()


@pytest.mark.asyncio
async def test_commands(emulator: Emulator):
    """Test commands."""
    device = Device("127.0.0.1", port=10001)
    await device.connect()
    await device.leave_standby()
    await device.play()
    await device.pause()
    await device.stop()
    await device.enter_standby()

    await device.disconnect()


@pytest.mark.asyncio
async def test_get_content_details(emulator: Emulator):
    """Test command involving multiline response."""
    device = Device("127.0.0.1", port=10001)
    await device.refresh()
    res = await device.get_content_details("26-0.0-S_c446c8e2")
    assert res.field_handle == "26-0.0-S_c446c8e2"
    assert res.field_table == "movies"
    assert res.field_title == "Turtle Odyssey"

    await device.disconnect()
