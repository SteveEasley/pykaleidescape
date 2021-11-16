"""Controller class for managing the connection and devices in a system."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp
import aiohttp.client_exceptions

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
from .error import KaleidescapeError, SystemNotFoundError

if TYPE_CHECKING:
    from .dispatcher import Signal

_LOGGER = logging.getLogger(__name__)


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
        self._host = host
        self._port = port
        self._timeout = timeout

        self._dispatcher = Dispatcher()
        self._connection = Connection(self._dispatcher)
        self._systems: dict[str, SystemInfo] | None = None
        self._system: SystemInfo | None = None
        self._devices: list[Device] | None = None
        self._deleted_devices: list[Device] = []
        self._devices_loaded: bool = False
        self._signals: list[Signal] = []

    async def connect(
        self,
        system_id: str | None = None,
        *,
        auto_reconnect: bool = False,
        reconnect_delay: float = const.DEFAULT_RECONNECT_DELAY,
        discovery_port: int = const.DEFAULT_DISCOVERY_PORT,
    ) -> None:
        """Connect to local device.

        The system_id is only needed in complex setups with multiple systems on the
        same network. Single systems of one or more devices can omit the param.
        """
        if self.is_connected:
            return

        await self.discover(port=discovery_port)

        assert self._systems is not None
        assert self._system is not None

        if system_id is not None:
            if system_id not in self._systems:
                raise SystemNotFoundError(
                    f"System id not found on network: {system_id}"
                )
            self._system = self._systems[system_id]

        self._signals = [
            self.dispatcher.connect(SIGNAL_CONNECTION_EVENT, self._handle_event)
        ]

        await self._connection.connect(
            self._system.ip_address,
            port=self._port,
            timeout=self._timeout,
            auto_reconnect=auto_reconnect,
            reconnect_delay=reconnect_delay,
        )

        _LOGGER.debug(
            "Connected to system %s with local device %s",
            self._system.system_id,
            self._system.ip_address,
        )

    async def discover(
        self, *, port: int = const.DEFAULT_DISCOVERY_PORT
    ) -> dict[str, SystemInfo]:
        """Discover all systems on local network."""
        self._systems = {}

        ip_address = await Connection.resolve(self._host)
        url = f"http://{ip_address}:{port}/webservices/server_list.dat?version=3"
        timeout = aiohttp.ClientTimeout(total=self._connection.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                err_msg = f"Failed to discover any systems on network via {ip_address}:"
                async with session.get(url) as response:
                    if response.status != 200:
                        raise ConnectionError(f"{err_msg}: code {response.status}")
                    data = await response.text()
            except asyncio.exceptions.TimeoutError as err:
                _LOGGER.error(f"{err_msg}: {err}")
                raise ConnectionError(f"{err_msg}: timeout") from err
            except aiohttp.client_exceptions.ClientConnectorError as err:
                _LOGGER.error(f"{err_msg}: {err}")
                raise ConnectionError(f"{err_msg}: {err}") from err

        servers = [v.strip().splitlines() for v in data.strip("\n\r-").split("---")]

        if len(servers) == 0:
            raise KaleidescapeError("Failed to load discovery data")

        system_id: str | None = None

        for server in servers:
            server = list(filter(None, [v.strip() for v in server]))
            if not isinstance(server, list) or len(server) < 5 or len(server) > 6:
                raise KaleidescapeError("Failed to parse discovery data")

            system = SystemInfo(
                system_id=server[2],
                serial_number=server[0],
                ip_address=server[1],
                is_hds=(server[3].lower() == "hds"),
            )

            if server[1] == ip_address:
                system_id = system.system_id

            if system.is_hds or system.system_id not in self._systems:
                self._systems[system.system_id] = system

        _LOGGER.debug(
            "Discovered %d system%s on network: %s",
            len(self._systems.keys()),
            "" if len(self._systems.keys()) == 1 else "s",
            self._systems.values(),
        )

        assert system_id is not None and system_id in self._systems
        self._system = self._systems[system_id]
        return self._systems

    async def disconnect(self) -> None:
        """Disconnect from hardware."""
        if not self.is_connected:
            return

        await self._connection.disconnect()

        try:
            for signal in self._signals:
                signal.disconnect()
        finally:
            self._signals.clear()

    async def get_local_device(self) -> Device:
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
        if not self.is_connected:
            raise KaleidescapeError("Connect not called yet")

        if self._devices is None:
            self._devices = [Device(self, LOCAL_CPDID, self._system)]
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
                    self._devices.append(
                        Device(self, f"#{serial_number}", self._system)
                    )
                else:
                    device = next(
                        iter(
                            [
                                d
                                for d in self._deleted_devices
                                if d.serial_number == serial_number
                            ]
                        )
                    )
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
    def systems(self) -> dict[str, SystemInfo] | None:
        """Returns map of systems on network."""
        if self._systems is None:
            raise KaleidescapeError("Discovery not called yet")
        return self._systems

    @property
    def dispatcher(self) -> Dispatcher:
        """Returns dispatcher instance."""
        return self._dispatcher

    @property
    def connection(self) -> Connection:
        """Returns connection instance."""
        return self._connection

    @property
    def is_connected(self) -> bool:
        """Returns whether connection is currently connected."""
        return self._connection.state == const.STATE_CONNECTED

    @property
    def is_reconnecting(self) -> bool:
        """Returns whether connection is currently reconnecting."""
        return self._connection.state == const.STATE_RECONNECTING


@dataclass
class SystemInfo:
    """System on network."""

    system_id: str = ""
    serial_number: str = ""
    ip_address: str = ""
    is_hds: bool = False
