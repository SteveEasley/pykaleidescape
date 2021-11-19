"""Controller class for managing the connection and devices in a system."""

from __future__ import annotations

import asyncio
import logging
import re
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
from .error import KaleidescapeError, MessageError, SystemNotFoundError

if TYPE_CHECKING:
    from .dispatcher import Signal

_LOGGER = logging.getLogger(__name__)


class Kaleidescape:
    """Controller for managing the connection and devices."""

    def __init__(
        self,
        host: str,
        *,
        port: int = const.DEFAULT_PROTOCOL_PORT,
        timeout: float = const.DEFAULT_PROTOCOL_TIMEOUT,
    ) -> None:
        """Initialize the controller."""
        self._host = host
        self._port = port
        self._timeout = timeout

        self._dispatcher = Dispatcher()
        self._connection = Connection(self._dispatcher)
        self._systems: dict[str, SystemInfo] | None = None
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

        default_system_id = await self.discover(port=discovery_port)

        if system_id is None:
            system_id = default_system_id

        assert self._systems is not None

        if system_id not in self._systems:
            raise SystemNotFoundError(
                f"System id ({system_id}) not found in discovered systems on network"
            )

        system = self._systems[system_id]

        self._signals = [
            self.dispatcher.connect(SIGNAL_CONNECTION_EVENT, self._handle_event)
        ]

        (server_ip, server_port) = system.connect_address

        await self._connection.connect(
            server_ip,
            port=server_port,
            timeout=self._timeout,
            auto_reconnect=auto_reconnect,
            reconnect_delay=reconnect_delay,
        )

        _LOGGER.debug(
            "Connected to system %s via server %s",
            system.system_id,
            system.ip_address,
        )

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

        if self._devices is not None:
            for device in self._devices:
                device.close()

        self._devices = None
        self._systems = None
        self._devices_loaded = False
        self._deleted_devices.clear()

    async def discover(self, *, port: int = const.DEFAULT_DISCOVERY_PORT) -> str:
        """Discover all system on local network.

        Returns the system id of the system matching the host used to connect to.
        """
        self._systems = {}

        ip_address = await Connection.resolve(self._host)
        discovery_address = f"{ip_address}"
        if port != const.DEFAULT_DISCOVERY_PORT:
            discovery_address = discovery_address + f":{port}"
        protocol_address = f"{ip_address}"
        if self._port != const.DEFAULT_PROTOCOL_PORT:
            protocol_address = protocol_address + f":{self._port}"

        # Get list of server data for all servers on network.
        url = f"http://{discovery_address}/webservices/server_list.dat?version=3"
        timeout = aiohttp.ClientTimeout(total=self._connection.timeout)
        err_msg = f"Failed to discover any systems on network via {ip_address}:"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
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

        servers = [
            s.lstrip().splitlines() for s in data.strip().strip("-").split("---")
        ]

        if len(servers) == 0:
            raise KaleidescapeError("Failed to load discovery data")

        default_system_id: str | None = None

        for server in servers:
            server = list(map(str.strip, server))

            # Parse newline delimited server info lines.
            if not isinstance(server, list) or len(server) < 5 or len(server) > 6:
                raise KaleidescapeError("Unrecognized format for discovery data")

            system_id = f"{int(server[2]):x}"
            serial_number = f"{server[0][-12:]:0>12}".upper()
            address = re.sub(r"\b0+(\d)", r"\1", server[1])

            if len(server) == 6:
                is_primary = server[3].lower() == "hds"
                kos_version = server[4]
            else:
                is_primary = system_id not in self._systems
                kos_version = server[3]

            if not is_primary:
                continue

            system = SystemInfo(
                system_id=system_id,
                serial_number=serial_number,
                ip_address=address,
                kos_version=kos_version,
            )

            self._systems[system.system_id] = system

            if system.ip_address == protocol_address:
                default_system_id = system.system_id

        assert len(self._systems) > 0
        if default_system_id is None:
            err_msg = f"Discovery failed to find a server matching address"
            raise ConnectionError(f"{err_msg} {protocol_address}")
        assert default_system_id is not None
        assert default_system_id in self._systems

        # Populate systems with friendly name and pairing info
        for system in self._systems.values():
            # Establish protocol connection to device
            (server_ip, server_port) = system.connect_address
            await self._connection.connect(
                server_ip, port=server_port, timeout=self._timeout
            )

            device = Device(self, LOCAL_CPDID)
            system.friendly_name = await device.get_friendly_system_name()

            try:
                # Determine if this system is Co-Star paired with another system.
                pairing = await device.get_system_pairing_info()
                if pairing is not False and pairing.is_paired:
                    system.is_paired = True
                    system.paired_system_id = pairing.field_paired_system_id
                    system.paired_friendly_name = pairing.field_paired_friendly_name
                    system.paired_peers = pairing.field_paired_peers
            except MessageError as err:
                if err.code == const.ERROR_INVALID_REQUEST:
                    # Must be a Premier system
                    pass
                else:
                    raise err
            finally:
                device.close()

            await self._connection.disconnect()

        _LOGGER.debug(
            "Discovered %d system%s on network: %s",
            len(self._systems.keys()),
            "" if len(self._systems.keys()) == 1 else "s",
            self._systems.values(),
        )

        return default_system_id

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
        if self._systems is None or self._devices is None:
            return

        local_device = self._devices[0]
        assert local_device.is_local
        if local_device.serial_number == "":
            await local_device.refresh_device()

        # Latest is the most recent list of known serial numbers is the system.
        if latest_serial_numbers is None:
            latest_serial_numbers = await local_device.get_available_serial_numbers()

        # List of known serial numbers to be compared to the latest list.
        serial_numbers = [d.serial_number for d in self._devices]

        # List of serial numbers no longer in system.
        deleted_serial_numbers = [d.serial_number for d in self._deleted_devices]

        # List of serial numbers that are Co-Star paired.
        peered_serial_numbers: list[str] = []
        for system in self._systems.values():
            if system.is_paired:
                assert system.paired_peers is not None
                peered_serial_numbers = peered_serial_numbers + [
                    p[1] for p in system.paired_peers
                ]

        # Disable and remove orphaned devices.
        for device in list(self._devices):
            assert device.serial_number
            if device.serial_number not in latest_serial_numbers:
                assert not device.is_local
                device.disable()
                self._devices.remove(device)
                self._deleted_devices.append(device)

        # Add new devices
        for serial_number in latest_serial_numbers:
            if serial_number not in serial_numbers:
                if serial_number not in deleted_serial_numbers:
                    assert serial_number != local_device.serial_number
                    if serial_number not in peered_serial_numbers:
                        self._devices.append(Device(self, f"#{serial_number}"))
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
        await asyncio.gather(*(d.refresh_device() for d in devices[1:]))
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
    kos_version: str = ""
    friendly_name: str = ""
    is_paired: bool = False
    paired_system_id: str | None = None
    paired_friendly_name: str | None = None
    paired_peers: list[tuple[str, str]] | None = None

    @property
    def connect_address(self) -> tuple[str, int]:
        """Returns ip, port tuple."""
        addr = self.ip_address.split(":")
        if len(addr) == 1:
            return addr[0], const.DEFAULT_PROTOCOL_PORT
        else:
            return addr[0], int(addr[1])

    def __repr__(self) -> str:
        res = (
            f"SystemInfo("
            f"system_id={self.system_id}, "
            f"serial_number={self.serial_number}, "
            f"ip_address={self.ip_address}, "
            f"kos_version={self.kos_version}, "
            f"friendly_name='{self.friendly_name}', "
            f"is_paired={self.is_paired}"
        )

        if self.is_paired:
            res = res + (
                f", paired_system_id={self.paired_system_id}, "
                f"paired_friendly_name='{self.paired_friendly_name}', "
                f"paired_peers={self.paired_peers}"
            )

        return res + ")"
