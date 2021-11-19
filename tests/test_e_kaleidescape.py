"""Tests for kaleidescape module."""

import asyncio

import pytest

from kaleidescape import const, SystemInfo
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
    assert kaleidescape.is_connected is False
    assert kaleidescape.is_reconnecting is False


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

    assert kaleidescape.is_connected is False
    await kaleidescape.connect(discovery_port=10080)
    await asyncio.wait_for(connected_signal.wait(), 0.5)

    assert kaleidescape.is_connected is True
    assert kaleidescape.is_reconnecting is False
    assert kaleidescape.connection.ip_address == "127.0.0.1"
    assert kaleidescape.connection.port == 10001
    assert kaleidescape.connection.timeout == const.DEFAULT_PROTOCOL_TIMEOUT

    assert len(kaleidescape.systems) == 1
    assert "123456789a" in kaleidescape.systems
    system = kaleidescape.systems["123456789a"]
    assert isinstance(system, SystemInfo)
    assert system.system_id == "123456789a"
    assert system.serial_number == "00000000123A"
    assert system.ip_address == "127.0.0.1:10001"
    assert system.kos_version == "10.11.0-22557"
    assert system.friendly_name == "Home Cinema"
    assert system.is_paired is False

    await kaleidescape.disconnect()
    await asyncio.wait_for(disconnected_signal.wait(), 0.5)


@pytest.mark.asyncio
async def test_disconnect(emulator: Emulator):
    """Test disconnecting from hardware."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    assert kaleidescape.is_connected is False
    await kaleidescape.connect(discovery_port=10080)
    assert kaleidescape.is_connected is True
    await kaleidescape.disconnect()
    assert kaleidescape.is_connected is False


@pytest.mark.asyncio
async def test_get_device(emulator: Emulator):
    """Test getting local device after connect."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    await kaleidescape.connect(discovery_port=10080)
    device = await kaleidescape.get_local_device()
    assert isinstance(device, Device)
    assert device.is_local
    assert device.is_connected
    assert len(await kaleidescape.get_devices()) == 1
    await kaleidescape.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device"], indirect=True)
async def test_get_devices(emulator: Emulator):
    """Test getting local devices after connect."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    await kaleidescape.connect(discovery_port=10080)
    devices = await kaleidescape.get_devices()
    assert isinstance(devices, list)
    assert len(await kaleidescape.get_devices()) == 2
    assert devices[0].is_connected and devices[1].is_connected
    await kaleidescape.disconnect()


@pytest.mark.asyncio
async def test_connect_by_system_id(emulator: Emulator):
    """Test connecting with a system id."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    await kaleidescape.discover(port=10080)
    system = next(iter(kaleidescape.systems.values()))
    await kaleidescape.connect(system.system_id, discovery_port=10080)
    device = await kaleidescape.get_local_device()
    assert isinstance(device, Device)
    assert device.is_local
    assert device.is_connected
    assert len(await kaleidescape.get_devices()) == 1
    await kaleidescape.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device"], indirect=True)
async def test_device_added(emulator: Emulator):
    """Test adding a new device works."""
    # Hide 2nd device in emulator. This will prevent the controller from
    # discovering it.
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
    await kaleidescape.connect(discovery_port=10080)

    # Assert there is only one device in the system
    devices = await kaleidescape.get_devices()
    assert len(devices) == 1
    assert devices[0].is_local
    assert devices[0].serial_number == "00000000123A"
    assert devices[0].disabled is False

    # Add new device to emulator, simulating a new device connected to system.
    signal = controller_signal(kaleidescape.dispatcher, const.EVENT_CONTROLLER_UPDATED)
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
        ["01"],
        const.SUCCESS,
        messages.AvailableDevicesBySerialNumber.name,
        ["00000000123A", "00000000123B"],
    )
    await asyncio.wait_for(signal.wait(), 0.5)

    # Assert there are now two devices in the system
    devices = await kaleidescape.get_devices()
    assert len(devices) == 2
    assert devices[0].is_local
    assert devices[0].serial_number == "00000000123A"
    assert devices[1].serial_number == "00000000123B"
    assert (devices[0].disabled and devices[1].disabled) is False

    await kaleidescape.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("emulator", ["multi_device"], indirect=True)
async def test_device_removed_and_readded(emulator: Emulator):
    """Test removing a device works."""
    kaleidescape = Kaleidescape("127.0.0.1", port=10001)
    await kaleidescape.connect(discovery_port=10080)

    # Assert there are two devices in system
    devices = await kaleidescape.get_devices()
    assert len(devices) == 2
    assert (devices[0].disabled and devices[1].disabled) is False

    # Hide the 2nd device from the system
    emulator.change_mock_device_id("#00000000123B", "#00000000123B_")
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
        ["01"],
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
    emulator.change_mock_device_id("#00000000123B_", "#00000000123B")
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
        ["01"],
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

    await kaleidescape.disconnect()
