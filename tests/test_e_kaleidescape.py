"""Tests for kaleidescape module."""

import asyncio

import pytest

from kaleidescape import const
from kaleidescape import message as messages
from kaleidescape.connection import Connection
from kaleidescape.device import Device
from kaleidescape.dispatcher import Dispatcher
from kaleidescape.kaleidescape import Kaleidescape

from . import controller_signal
from .emulator import Emulator

# pylint: disable=unused-argument, protected-access


def test_init():
    """Test initialization of controller."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    assert isinstance(kaleidescape.dispatcher, Dispatcher)
    assert isinstance(kaleidescape.connection, Connection)
    assert kaleidescape.connected is False
    assert kaleidescape.reconnecting is False
    assert kaleidescape.connection.host == "127.0.0.1"
    assert kaleidescape.connection.port == 10001


@pytest.mark.asyncio
async def test_connect(emulator: Emulator):
    """Test connecting to hardware."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    connected_signal = controller_signal(
        kaleidescape.dispatcher, const.EVENT_CONTROLLER_CONNECTED
    )
    disconnected_signal = controller_signal(
        kaleidescape.dispatcher, const.EVENT_CONTROLLER_DISCONNECTED
    )

    assert kaleidescape.connected is False
    await kaleidescape.connect()
    await asyncio.wait_for(connected_signal.wait(), 0.5)
    assert kaleidescape.connected is True
    assert kaleidescape.reconnecting is False
    assert kaleidescape.connection.timeout == const.DEFAULT_CONNECT_TIMEOUT
    assert kaleidescape.connection._reconnect_delay == const.DEFAULT_RECONNECT_DELAY
    assert kaleidescape.connection._auto_reconnect is False
    await kaleidescape.disconnect()
    await asyncio.wait_for(disconnected_signal.wait(), 0.5)

    kaleidescape = Kaleidescape(
        "127.0.0.1", port=10001, timeout=const.DEFAULT_CONNECT_TIMEOUT + 1
    )
    connected_signal = controller_signal(
        kaleidescape.dispatcher, const.EVENT_CONTROLLER_CONNECTED
    )
    disconnected_signal = controller_signal(
        kaleidescape.dispatcher, const.EVENT_CONTROLLER_DISCONNECTED
    )

    assert kaleidescape.connected is False
    await kaleidescape.connect(
        auto_reconnect=True, reconnect_delay=const.DEFAULT_RECONNECT_DELAY + 1
    )
    await asyncio.wait_for(connected_signal.wait(), 0.5)
    assert kaleidescape.connected is True
    assert kaleidescape.reconnecting is False
    assert kaleidescape.connection._timeout == const.DEFAULT_CONNECT_TIMEOUT + 1
    assert kaleidescape.connection._reconnect_delay == const.DEFAULT_RECONNECT_DELAY + 1
    assert kaleidescape.connection._auto_reconnect is True
    await kaleidescape.disconnect()
    await asyncio.wait_for(disconnected_signal.wait(), 0.5)


@pytest.mark.asyncio
async def test_disconnect(emulator: Emulator):
    """Test disconnecting from hardware."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    assert kaleidescape.connected is False
    await kaleidescape.connect()
    assert kaleidescape.connected is True
    await kaleidescape.disconnect()
    assert kaleidescape.connected is False


@pytest.mark.asyncio
async def test_get_device(emulator: Emulator):
    """Test getting local device after connect."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    await kaleidescape.connect()
    device = await kaleidescape.get_device()
    assert isinstance(device, Device)
    assert device.is_local
    assert device.connected
    assert len(await kaleidescape.get_devices()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device_cpdid"], indirect=True)
async def test_get_devices(emulator: Emulator):
    """Test getting local devices after connect."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    await kaleidescape.connect()
    devices = await kaleidescape.get_devices()
    assert isinstance(devices, list)
    assert len(await kaleidescape.get_devices()) == 2
    assert devices[0].connected and devices[1].connected


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device_cpdid"], indirect=True)
async def test_device_added(emulator: Emulator):
    """Test adding a new device works."""
    # Hide 2nd device in emulator. This will prevent the controller from
    # discovering it.
    emulator.register_mock_command(
        ("01", "02", "#00000000123A"),
        messages.GetAvailableDevices.name,
        (const.SUCCESS, messages.AvailableDevices.name, ["01", "02"]),
    )
    emulator.register_mock_command(
        ("01", "02", "#00000000123A"),
        messages.GetAvailableDevicesBySerialNumber.name,
        (
            const.SUCCESS,
            messages.AvailableDevicesBySerialNumber.name,
            ["#00000000123A"],
        ),
    )

    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    await kaleidescape.connect()

    # Assert there is only one device in the system
    devices = await kaleidescape.get_devices()
    assert len(devices) == 1
    assert devices[0].cpdid == "02"
    assert devices[0].disabled is False

    # Add new device to emulator, simulating a new device connected to system.
    signal = controller_signal(kaleidescape.dispatcher, const.EVENT_CONTROLLER_UPDATED)
    emulator.register_mock_command(
        ("01", "02", "#00000000123A"),
        messages.GetAvailableDevices.name,
        (const.SUCCESS, messages.AvailableDevices.name, ["01", "02", "03"]),
    )
    emulator.register_mock_command(
        ("01", "02", "#00000000123A"),
        messages.GetAvailableDevicesBySerialNumber.name,
        (
            const.SUCCESS,
            messages.AvailableDevicesBySerialNumber.name,
            ["#00000000123A", "00000000123B"],
        ),
    )
    await emulator.send_event(
        ["02"],
        const.SUCCESS,
        messages.AvailableDevicesBySerialNumber.name,
        ["00000000123A", "00000000123B"],
    )
    await asyncio.wait_for(signal.wait(), 0.5)

    # Assert there are now two devices in the system
    devices = await kaleidescape.get_devices()
    assert len(devices) == 2
    assert devices[0].cpdid == "02" and devices[1].cpdid == "03"
    assert (devices[0].disabled and devices[1].disabled) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device_cpdid"], indirect=True)
async def test_device_removed_and_readded(emulator: Emulator):
    """Test removing a device works."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    await kaleidescape.connect()

    # Assert there are two devices in system
    devices = await kaleidescape.get_devices()
    assert len(devices) == 2
    assert (devices[0].disabled and devices[1].disabled) is False

    # Hide the 2nd device from the system
    emulator.change_mock_device_id("03", "03_")
    emulator.change_mock_device_id("#00000000123B", "#00000000123B_")
    emulator.register_mock_command(
        ("01", "02", "#00000000123A"),
        messages.GetAvailableDevices.name,
        (const.SUCCESS, messages.AvailableDevices.name, ["01", "02"]),
    )
    emulator.register_mock_command(
        ("01", "02", "#00000000123A"),
        messages.GetAvailableDevicesBySerialNumber.name,
        (
            const.SUCCESS,
            messages.AvailableDevicesBySerialNumber.name,
            ["#00000000123A"],
        ),
    )
    await emulator.send_event(
        ["02"],
        const.SUCCESS,
        messages.AvailableDevicesBySerialNumber.name,
        ["00000000123A"],
    )
    signal = controller_signal(kaleidescape.dispatcher, const.EVENT_CONTROLLER_UPDATED)
    await asyncio.wait_for(signal.wait(), 0.5)
    signal.clear()

    # Assert there is now only one enabled device in the system
    devices = await kaleidescape.get_devices()
    assert len(devices) == 1
    assert devices[0].serial_number == "00000000123A"
    assert devices[0].disabled is False
    assert len(kaleidescape._deleted_devices) == 1

    #
    # Re-add 2nd device to system
    #
    emulator.change_mock_device_id("03_", "03")
    emulator.change_mock_device_id("#00000000123B_", "#00000000123B")
    emulator.register_mock_command(
        ("01", "02", "#00000000123A"),
        messages.GetAvailableDevices.name,
        (const.SUCCESS, messages.AvailableDevices.name, ["01", "02", "03"]),
    )
    emulator.register_mock_command(
        ("01", "02", "#00000000123A"),
        messages.GetAvailableDevicesBySerialNumber.name,
        (
            const.SUCCESS,
            messages.AvailableDevicesBySerialNumber.name,
            ["#00000000123A", "#00000000123B"],
        ),
    )
    await emulator.send_event(
        ["02"],
        const.SUCCESS,
        messages.AvailableDevicesBySerialNumber.name,
        ["00000000123A", "00000000123B"],
    )
    signal = controller_signal(kaleidescape.dispatcher, const.EVENT_CONTROLLER_UPDATED)
    await asyncio.wait_for(signal.wait(), 0.5)
    assert len(devices) == 2
    assert devices[1].serial_number == "00000000123B"
    assert devices[0].disabled is False and devices[1].disabled is False
    assert len(kaleidescape._deleted_devices) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device_cpdid"], indirect=True)
async def test_device_cpdid_changed(emulator: Emulator):
    """Test changing a cpdid works."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    await kaleidescape.connect()

    # Assert there are two devices in system
    devices = await kaleidescape.get_devices()
    assert len(devices) == 2
    assert devices[0].cpdid == "02" and devices[1].cpdid == "03"

    # Change cpdid of 2nd device from 03 to 04
    emulator.change_mock_device_id("03", "04")
    emulator.register_mock_command(
        ("01", "02", "#00000000123A"),
        messages.GetAvailableDevices.name,
        (const.SUCCESS, messages.AvailableDevices.name, ["01", "02", "04"]),
    )
    emulator.register_mock_command(
        ("04", "#00000000123B"),
        messages.GetDeviceInfo.name,
        (
            const.SUCCESS,
            messages.DeviceInfo.name,
            ["", "00000000123B", "04", "192.168.0.2"],
        ),
    )

    # Sending AvailableDevicesBySerialNumber not AvailableDevices event since
    # controller only listens for these. Kaleidescape devices always send both when
    # a cpdid is changed.
    await emulator.send_event(
        ["02"],
        const.SUCCESS,
        messages.AvailableDevicesBySerialNumber.name,
        ["00000000123A", "00000000123B"],
    )
    signal = controller_signal(kaleidescape.dispatcher, const.EVENT_CONTROLLER_UPDATED)
    await asyncio.wait_for(signal.wait(), 0.5)

    # Assert cpdids updated
    devices = await kaleidescape.get_devices()
    assert len(devices) == 2
    assert devices[0].cpdid == "02" and devices[1].cpdid == "04"
