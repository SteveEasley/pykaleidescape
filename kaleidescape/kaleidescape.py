"""Controller class for managing the connection and devices in a system."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from . import const
from . import message as messages
from .connection import (
    EVENT_CONNECTION_CONNECTED,
    EVENT_CONNECTION_DISCONNECTED,
    EVENT_CONNECTION_MESSAGE,
    SIGNAL_CONNECTION_EVENT,
    Connection,
)
from .const import LOCAL_CPDID
from .device import Device
from .dispatcher import Dispatcher
from .error import KaleidescapeError

if TYPE_CHECKING:
    from .dispatcher import Signal


class Kaleidescape:
    """Controller for managing the connection and devices."""

    def __init__(
        self,
        host: str,
        *,
        port: int = const.DEFAULT_CONNECT_PORT,
        timeout: float = const.DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        """Initialize the controller."""
        self._dispatcher = Dispatcher()
        self._connection = Connection(
            self._dispatcher, host, port=port, timeout=timeout
        )
        self._devices: list[Device] | None = None
        self._deleted_devices: list[Device] = []
        self._devices_loaded: bool = False
        self._signals: list[Signal] = []

    async def connect(
        self,
        auto_reconnect: bool = False,
        reconnect_delay: float = const.DEFAULT_RECONNECT_DELAY,
    ) -> None:
        """Connect to hardware."""
        if self.connected:
            return

        self._signals = [
            self.dispatcher.connect(SIGNAL_CONNECTION_EVENT, self._handle_event)
        ]

        await self._connection.connect(
            auto_reconnect=auto_reconnect, reconnect_delay=reconnect_delay
        )

    async def disconnect(self) -> None:
        """Disconnect from hardware."""
        if not self.connected:
            return

        await self._connection.disconnect()

        try:
            for signal in self._signals:
                signal.disconnect()
        finally:
            self._signals.clear()

    async def get_device(self) -> Device:
        """Returns locally connected device."""
        if self._devices is None:
            await self.get_devices()

        if not self._devices:
            raise KaleidescapeError("No devices found")

        return self._devices[0]

    async def load_devices(self) -> None:
        """Loads devices in system."""
        await self.get_devices()

    async def get_devices(self) -> list[Device]:
        """Returns a list of all devices in system."""
        if self._devices is None:
            self._devices = [Device(self, LOCAL_CPDID)]
            await self._refresh_devices()
            self._devices_loaded = True

        if not self._devices:
            raise KaleidescapeError("No devices found")

        return self._devices

    async def _handle_event(self, event: str, *args) -> None:
        """Handles updates to the system."""
        if event == EVENT_CONNECTION_CONNECTED:
            # Skip refresh until initial load of devices is complete. Preventing any
            # race conditions.
            if self._devices_loaded:
                await self._refresh_devices()
            self._dispatcher.send(
                const.SIGNAL_CONTROLLER_EVENT, const.EVENT_CONTROLLER_CONNECTED
            )

        elif event == EVENT_CONNECTION_DISCONNECTED:
            self._dispatcher.send(
                const.SIGNAL_CONTROLLER_EVENT, const.EVENT_CONTROLLER_DISCONNECTED
            )

        elif event == EVENT_CONNECTION_MESSAGE:
            response: messages.Response = args[0]

            if response.name == const.AVAILABLE_DEVICES_BY_SERIAL_NUMBER:
                await self._refresh_devices(response.fields)
                self._dispatcher.send(
                    const.SIGNAL_CONTROLLER_EVENT, const.EVENT_CONTROLLER_UPDATED
                )

    async def _refresh_devices(self, latest_serial_numbers: list[str] = None) -> None:
        """Refreshes device list and the state of each."""
        if self._devices is None:
            return

        local_device = self._devices[0]
        assert local_device.is_local
        if local_device.serial_number == "":
            await local_device.refresh_device()

        # Latest is the most recent list of known serial numbers is the system.
        if latest_serial_numbers is None:
            latest_serial_numbers = await local_device.get_available_serial_numbers()

        # List of stale serial numbers to be compared to latest list.
        serial_numbers = [d.serial_number for d in self._devices]
        deleted_serial_numbers = [d.serial_number for d in self._deleted_devices]

        # Disable and remove orphaned devices.
        for device in list(self._devices):
            assert device.serial_number
            if device.serial_number not in latest_serial_numbers:
                assert not device.is_local
                device.disable()
                self._devices.remove(device)
                self._deleted_devices.append(device)

        # Add new devices. On startup this is where other devices in a multi-device
        # system are added.
        for serial_number in latest_serial_numbers:
            if serial_number not in serial_numbers:
                if serial_number not in deleted_serial_numbers:
                    assert serial_number != local_device.serial_number
                    self._devices.append(Device(self, f"#{serial_number}"))
                else:
                    device = next(iter(
                        [
                            d
                            for d in self._deleted_devices
                            if d.serial_number == serial_number
                        ]
                    ))
                    assert device
                    self._deleted_devices.remove(device)
                    self._devices.append(device)
                    device.enable()

        # Refresh entire system state
        devices = [d for d in self._devices if not d.disabled]
        await asyncio.gather(*(d.refresh_device() for d in devices))
        await asyncio.gather(*(d.refresh_state() for d in devices))
        await asyncio.gather(
            *(local_device.enable_events(d.device_id) for d in devices[1:])
        )

    @property
    def dispatcher(self) -> Dispatcher:
        """Returns dispatcher instance."""
        return self._dispatcher

    @property
    def connection(self) -> Connection:
        """Returns connection instance."""
        return self._connection

    @property
    def connected(self) -> bool:
        """Returns whether connection is currently connected."""
        return self._connection.state == const.STATE_CONNECTED

    @property
    def reconnecting(self) -> bool:
        """Returns whether connection is currently reconnecting."""
        return self._connection.state == const.STATE_RECONNECTING
