"""Tests for device module."""

import asyncio

import pytest

from kaleidescape import const
from kaleidescape import message as messages
from kaleidescape.connection import Connection
from kaleidescape.const import ERROR_INCOMPATIBLE_VIDEO_CONFIG, LOCAL_CPDID, SUCCESS
from kaleidescape.device import Device
from kaleidescape.dispatcher import Dispatcher

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
async def test_disconnect_during_reconnect(emulator: Emulator):
    """Test Device.disconnect() cancels reconnect in STATE_RECONNECTING."""
    device = Device("127.0.0.1", port=10001, reconnect=True, reconnect_delay=0.5)

    disconnect_signal = create_signal(device.dispatcher, const.STATE_DISCONNECTED)

    await device.connect()
    assert device.is_connected

    # Allow emulator to register the client before stopping
    await asyncio.sleep(0.1)

    # Drop connection to trigger library reconnect
    await emulator.stop()
    await disconnect_signal.wait()
    assert device.connection.state == const.STATE_RECONNECTING

    # Device.disconnect() should work even during STATE_RECONNECTING
    await device.disconnect()
    assert device.connection.state == const.STATE_DISCONNECTED
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
async def test_get_available_serial_numbers(emulator: Emulator):
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

    signal = create_signal(device.dispatcher, messages.DevicePowerState.name)

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
    signal = create_signal(device.dispatcher, messages.SystemReadinessState.name)
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
    await device.status_and_settings()
    await device.intermission_toggle()
    await device.go_movie_list()
    await device.go_movie_collections()
    await device.go_movies()
    await device.go_movie_covers()
    await device.menu_toggle()
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


@pytest.mark.asyncio
async def test_play_status_with_empty_highlighted(emulator: Emulator):
    """Test that a PlayStatus event does not crash when osd.highlighted is empty."""
    device = Device("127.0.0.1", port=10001)
    await device.refresh()

    # Put device into power ON state
    emulator.register_mock_command(
        ("01",),
        messages.GetDevicePowerState.name,
        (SUCCESS, messages.DevicePowerState.name, ["1", "1"]),
    )
    power_signal = create_signal(device.dispatcher, messages.DevicePowerState.name)
    await emulator.send_event(
        [LOCAL_CPDID], SUCCESS, messages.DevicePowerState.name, ["1"]
    )
    await asyncio.wait_for(power_signal.wait(), 1)
    assert device.power.state == const.DEVICE_POWER_STATE_ON

    # Confirm highlighted is empty (default emulator returns "")
    assert device.osd.highlighted == ""

    # Transition play status from NONE to playing with an empty highlighted handle.
    play_signal = create_signal(device.dispatcher, messages.PlayStatus.name)
    await emulator.send_event(
        [LOCAL_CPDID],
        SUCCESS,
        messages.PlayStatus.name,
        ["2", "1", "00", "00000", "00000", "000", "00000", "00000"],
    )
    await asyncio.wait_for(play_signal.wait(), 1)
    assert device.movie.play_status == const.PLAY_STATUS_PLAYING

    await device.disconnect()


@pytest.mark.asyncio
async def test_set_volume_capabilities(emulator: Emulator):
    """Test test_set_volume_capabilities."""
    device = Device("127.0.0.1", port=10001)
    await device.refresh()

    # Should succeed with valid argument
    await device.set_volume_capabilities(15)

    # Invalid argument types
    with pytest.raises(TypeError):
        await device.set_volume_capabilities("50")  # type: ignore[arg-type]

    # Out of range values
    with pytest.raises(ValueError):
        await device.set_volume_capabilities(-1)

    with pytest.raises(ValueError):
        await device.set_volume_capabilities(32)

    await device.disconnect()


@pytest.mark.asyncio
async def test_set_volume_level(emulator: Emulator):
    """Test set_volume_level command and validation."""
    device = Device("127.0.0.1", port=10001)
    await device.refresh()

    # Should succeed with valid argument
    await device.set_volume_level(50)

    # Invalid argument types
    with pytest.raises(TypeError):
        await device.set_volume_level("50")  # type: ignore[arg-type]

    # Out of range values
    with pytest.raises(ValueError):
        await device.set_volume_level(-1)

    with pytest.raises(ValueError):
        await device.set_volume_level(101)

    await device.disconnect()


@pytest.mark.asyncio
async def test_set_volume_muted(emulator: Emulator):
    """Test set_volume_muted command and validation."""
    device = Device("127.0.0.1", port=10001)
    await device.refresh()

    # Should succeed with valid boolean arguments
    await device.set_volume_muted(True)
    await device.set_volume_muted(False)

    # Invalid argument types
    with pytest.raises(TypeError):
        await device.set_volume_muted("true")  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        await device.set_volume_muted(1)  # type: ignore[arg-type]

    await device.disconnect()


@pytest.mark.asyncio
async def test_refresh_after_reconnect(emulator: Emulator):
    """Test device state is refreshed after auto-reconnect."""
    device = Device("127.0.0.1", port=10001, reconnect=True, reconnect_delay=0.5)

    connect_signal = create_signal(device.dispatcher, const.STATE_CONNECTED)
    disconnect_signal = create_signal(device.dispatcher, const.STATE_DISCONNECTED)

    await device.connect()
    await connect_signal.wait()
    assert device.is_connected
    assert device.power.state == const.DEVICE_POWER_STATE_STANDBY

    # Change emulator response so power state differs after reconnect
    emulator.register_mock_command(
        ("01",),
        messages.GetDevicePowerState.name,
        (SUCCESS, messages.DevicePowerState.name, ["1", "1"]),
    )

    # Drop connection
    connect_signal.clear()
    await emulator.stop()
    await disconnect_signal.wait()

    # Reconnect - device state should be refreshed automatically
    await emulator.start()
    await connect_signal.wait()
    assert device.is_connected

    # Give the on_reconnect callback a moment to complete
    await asyncio.sleep(0.1)

    # Power state should reflect the new emulator response
    assert device.power.state == const.DEVICE_POWER_STATE_ON

    await device.disconnect()


@pytest.mark.asyncio
async def test_refresh_partial_failure(emulator: Emulator):
    """Test refresh applies successful results when some queries fail.

    Devices that lack masking calibration or CinemaScope return error 028
    (Incompatible video configuration) for GET_SCREEN_MASK2. Previously
    this caused asyncio.gather to discard all 7 query results. With
    return_exceptions=True, the 6 successful queries should still update
    device state.
    """
    # Register GET_SCREEN_MASK2 to return error 028
    emulator.register_mock_command(
        ("01", "#00000000123A"),
        messages.GetScreenMask2.name,
        (ERROR_INCOMPATIBLE_VIDEO_CONFIG,),
    )

    # Put device in ON state so refresh() runs its queries
    emulator.register_mock_command(
        ("01",),
        messages.GetDevicePowerState.name,
        (SUCCESS, messages.DevicePowerState.name, ["1", "1"]),
    )

    device = Device("127.0.0.1", port=10001)
    await device.connect()

    # Verify device is ON (required for refresh to proceed)
    assert device.power.state == const.DEVICE_POWER_STATE_ON

    # refresh() should succeed despite GET_SCREEN_MASK2 failing
    await device.refresh()

    # Verify successful queries were applied
    assert device.osd.ui_screen == const.UI_STATE_SCREEN_MOVIE_LIST
    assert device.movie.play_status == const.PLAY_STATUS_NONE
    assert device.automation.movie_location == const.MOVIE_LOCATION_CONTENT
    assert device.automation.screen_mask_ratio == const.SCREEN_MASK_ASPECT_RATIO_NONE
    assert device.automation.cinemascape_mode == const.CINEMASCAPE_MODE_NONE

    # Verify failed query left defaults unchanged
    assert device.automation.screen_mask2_top_mask_abs == 0
    assert device.automation.screen_mask2_bottom_mask_abs == 0
    assert device.automation.screen_mask2_top_calibrated == 0
    assert device.automation.screen_mask2_bottom_calibrated == 0

    await device.disconnect()
