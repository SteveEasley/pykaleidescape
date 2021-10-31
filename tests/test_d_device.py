"""Tests for device module."""

import asyncio

import pytest

from kaleidescape import Kaleidescape, const
from kaleidescape import message as messages
from kaleidescape.connection import Connection
from kaleidescape.const import LOCAL_CPDID, SUCCESS
from kaleidescape.device import Device
from kaleidescape.dispatcher import Dispatcher
from kaleidescape.error import KaleidescapeError, MessageError

from . import device_signal
from .emulator import Emulator

# pylint: disable=unused-argument


@pytest.mark.asyncio
async def test_init(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test initialization of device."""
    device = Device(kaleidescape)
    assert isinstance(device.connection, Connection)
    assert isinstance(device.dispatcher, Dispatcher)
    assert device.disabled is False
    assert device.connected is True
    assert device.is_local is True
    assert device.cpdid == ""
    assert device.serial_number == ""

    # Devices can only be initialized with a routable device id, which includes the
    # local cpdid (01), and serial numbers. This is because at startup the controller
    # is not aware of any assigned cpdid's yet.
    with pytest.raises(KaleidescapeError):
        Device(kaleidescape, "02")


@pytest.mark.asyncio
async def test_get_available_devices1(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test get available devices with single device."""
    device = Device(kaleidescape)
    fields = await device.get_available_devices()
    assert fields == [LOCAL_CPDID]


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device"], indirect=True)
async def test_get_available_devices2(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test get available devices with multi devices."""
    device = Device(kaleidescape)
    fields = await device.get_available_devices()
    # Only devices with a cpdid assigned are returned, which in this case is none.
    assert fields == [LOCAL_CPDID]


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device_cpdid"], indirect=True)
async def test_get_available_devices3(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test get available devices with multi devices with cpdid's assigned."""
    device = Device(kaleidescape)
    fields = await device.get_available_devices()
    assert fields == [LOCAL_CPDID, "02", "03"]


@pytest.mark.asyncio
async def test_get_available_serial_numbers1(
    emulator: Emulator, kaleidescape: Kaleidescape
):
    """Test get available devices with single device."""
    device = Device(kaleidescape)
    fields = await device.get_available_serial_numbers()
    assert fields == ["00000000123A"]


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device"], indirect=True)
async def test_get_available_serial_numbers2(
    emulator: Emulator, kaleidescape: Kaleidescape
):
    """Test get available serial numbers with multi devices."""
    device = Device(kaleidescape)
    fields = await device.get_available_serial_numbers()
    # Only devices with a cpdid assigned are returned, which in this case is none.
    assert fields == ["00000000123A", "00000000123B"]


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device_cpdid"], indirect=True)
async def test_get_available_serial_numbers3(
    emulator: Emulator, kaleidescape: Kaleidescape
):
    """Test get available serial numbers with multi devices with cpdid's assigned."""
    device = Device(kaleidescape)
    fields = await device.get_available_serial_numbers()
    assert fields == ["00000000123A", "00000000123B"]


@pytest.mark.asyncio
async def test_refresh_device1(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test refreshing system updates state."""
    device = Device(kaleidescape)
    await device.refresh_device()
    assert device.device_id == "#00000000123A"
    assert device.system.serial_number == "00000000123A"
    assert device.serial_number == "00000000123A"
    assert device.system.cpdid == ""
    assert device.cpdid == ""
    assert device.system.ip_address == "192.168.0.1"
    assert device.system.protocol == 16
    assert device.system.kos == "10.4.2-19218"
    assert device.system.type == "Strato S"
    assert device.system.name == "Theater"
    assert device.capabilities.osd is True
    assert device.capabilities.movies is True
    assert device.capabilities.music is False
    assert device.capabilities.store is True
    assert device.capabilities.movie_zones == 1
    assert device.capabilities.music_zones == 1
    assert device.power.state == const.DEVICE_POWER_STATE_STANDBY
    assert device.power.readiness == const.SYSTEM_READINESS_STATE_IDLE


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device"], indirect=True)
async def test_refresh_device2(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test refreshing system updates state when there are multiple devices."""
    device3a = Device(kaleidescape)
    await device3a.refresh_device()
    assert device3a.device_id == "#00000000123A"
    assert device3a.system.serial_number == "00000000123A"
    assert device3a.serial_number == "00000000123A"
    assert device3a.system.cpdid == ""
    assert device3a.cpdid == ""
    assert device3a.system.ip_address == "192.168.0.1"
    assert device3a.system.protocol == 16
    assert device3a.system.kos == "10.4.2-19218"
    assert device3a.system.type == "Strato S"
    assert device3a.system.name == "Theater"
    assert device3a.capabilities.osd is True
    assert device3a.capabilities.movies is True
    assert device3a.capabilities.music is False
    assert device3a.capabilities.store is True
    assert device3a.capabilities.movie_zones == 1
    assert device3a.capabilities.music_zones == 1
    assert device3a.power.state == const.DEVICE_POWER_STATE_STANDBY
    assert device3a.power.readiness == const.SYSTEM_READINESS_STATE_IDLE

    device3b = Device(kaleidescape, "#00000000123B")
    await device3b.refresh_device()
    assert device3b.device_id == "#00000000123B"
    assert device3b.system.serial_number == "00000000123B"
    assert device3b.serial_number == "00000000123B"
    assert device3b.system.cpdid == ""
    assert device3b.cpdid == ""
    assert device3b.system.ip_address == "192.168.0.2"
    assert device3b.system.protocol == 16
    assert device3b.system.kos == "10.4.2-19218"
    assert device3b.system.type == "Strato S"
    assert device3b.system.name == "Media Room"
    assert device3b.capabilities.osd is True
    assert device3b.capabilities.movies is True
    assert device3b.capabilities.music is False
    assert device3b.capabilities.store is True
    assert device3b.capabilities.movie_zones == 1
    assert device3b.capabilities.music_zones == 1
    assert device3b.power.state == const.DEVICE_POWER_STATE_STANDBY
    assert device3b.power.readiness == const.SYSTEM_READINESS_STATE_IDLE


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device_cpdid"], indirect=True)
async def test_refresh_device3(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test refreshing updates state when there are devices with cpdid's assigned."""
    device02 = Device(kaleidescape)
    await device02.refresh_device()
    assert device02.device_id == "02"
    assert device02.system.serial_number == "00000000123A"
    assert device02.serial_number == "00000000123A"
    assert device02.system.cpdid == "02"
    assert device02.cpdid == "02"
    assert device02.system.ip_address == "192.168.0.1"

    device03 = Device(kaleidescape, "#00000000123B")
    await device03.refresh_device()
    assert device03.device_id == "03"
    assert device03.system.serial_number == "00000000123B"
    assert device03.serial_number == "00000000123B"
    assert device03.system.cpdid == "03"
    assert device03.cpdid == "03"
    assert device03.system.ip_address == "192.168.0.2"


@pytest.mark.asyncio
async def test_refresh_state(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test refreshing state updates state."""
    device = Device(kaleidescape)
    await device.refresh_device()

    assert device.power.state == const.DEVICE_POWER_STATE_STANDBY
    assert device.osd.ui_screen == ""
    assert device.automation.movie_location == ""

    signal = device_signal(
        device.dispatcher, LOCAL_CPDID, messages.DevicePowerState.name
    )

    await emulator.send_event(
        [LOCAL_CPDID], SUCCESS, messages.DevicePowerState.name, ["1"]
    )

    await asyncio.wait_for(signal.wait(), 1)

    assert device.power.state == const.DEVICE_POWER_STATE_ON
    assert device.osd.ui_screen == const.UI_STATE_SCREEN_MOVIE_LIST
    assert device.automation.movie_location == const.MOVIE_LOCATION_CONTENT


@pytest.mark.asyncio
async def test_events1(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test device events with single device."""
    device = Device(kaleidescape)
    # Setup to listen for a SIGNAL_DEVICE_EVENT signal emit
    signal = device_signal(
        device.dispatcher, LOCAL_CPDID, messages.SystemReadinessState.name
    )
    # Produce a signal
    await emulator.send_event(
        [LOCAL_CPDID], SUCCESS, messages.SystemReadinessState.name, ["0"]
    )
    # Assert signal is received
    await asyncio.wait_for(signal.wait(), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device_cpdid"], indirect=True)
async def test_disable(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test calling disable stops commands and events."""
    device1 = Device(kaleidescape)
    device2 = Device(kaleidescape, "#00000000123B")

    await device1.refresh_device()
    await device2.refresh_device()

    # Should not be able to disable the local device
    assert device1.disabled is False
    device1.disable()
    assert device1.disabled is False

    # Disable device2
    assert device2.disabled is False
    device2.disable()
    assert device2.disabled is True

    # Ensure refresh can no longer be called
    with pytest.raises(MessageError) as err:
        await device2.refresh_device()
    assert err.value.code == const.ERROR_DEVICE_UNAVAILABLE
    with pytest.raises(MessageError):
        await device2.refresh_state()
    assert err.value.code == const.ERROR_DEVICE_UNAVAILABLE

    # Ensure signals to device2 have stopped
    signal = device_signal(device1.dispatcher, "03", messages.SystemReadinessState.name)
    await emulator.send_event(
        ["03"], SUCCESS, messages.SystemReadinessState.name, ["0"]
    )
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(signal.wait(), 0.25)


@pytest.mark.asyncio
async def test_commands(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test commands."""
    device = Device(kaleidescape)
    await device.leave_standby()
    await device.play()
    await device.pause()
    await device.stop()
    await device.enter_standby()


@pytest.mark.asyncio
async def test_get_content_details(emulator: Emulator, kaleidescape: Kaleidescape):
    """Test command involving multiline response."""
    device = Device(kaleidescape)
    await device.refresh_device()
    res = await device.get_content_details("26-0.0-S_c446c8e2")
    assert res.field_handle == "26-0.0-S_c446c8e2"
    assert res.field_table == "movies"
    assert res.field_title == "Turtle Odyssey"
