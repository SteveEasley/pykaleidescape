"""Class handling network connection to hardware device."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

import dns.asyncresolver
import dns.exception

from . import const
from .error import KaleidescapeError, MessageParseError, format_error
from .message import Response

if TYPE_CHECKING:
    import dns.resolver
    from dns.rdtypes.IN.A import A

    from .dispatcher import Dispatcher
    from .message import Request

_LOGGER = logging.getLogger(__name__)

SIGNAL_CONNECTION_EVENT = "connection"
EVENT_CONNECTION_MESSAGE = "message"
EVENT_CONNECTION_CONNECTED = "connection_connected"
EVENT_CONNECTION_DISCONNECTED = "connection_disconnected"
SEPARATOR = "\n"
SEPARATOR_BYTES = SEPARATOR.encode("latin-1")


class Connection:
    """Class handling network connection to hardware device."""

    def __init__(
        self, dispatcher: Dispatcher, host: str, port: int = None, timeout: float = None
    ) -> None:
        """Initializes connection."""
        self._dispatcher = dispatcher
        self._host = host
        self._port = port if port else const.DEFAULT_CONNECT_PORT
        self._timeout = timeout if timeout else const.DEFAULT_CONNECT_TIMEOUT

        self._state: str = const.STATE_DISCONNECTED
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._response_handler_task: asyncio.Task | None = None
        self._reconnect_delay: float | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._auto_reconnect: bool = False
        self._pending_requests: dict[str, dict[int, Request]] = {}

    @property
    def dispatcher(self) -> Dispatcher:
        """Returns dispatcher instance."""
        return self._dispatcher

    @property
    def host(self) -> str:
        """Returns host of the hardware device to connect to."""
        return self._host

    @property
    def port(self) -> int:
        """Returns port of the hardware device to connect to."""
        return self._port

    @property
    def timeout(self) -> float:
        """Returns connection timeout in seconds."""
        return self._timeout

    @property
    def state(self) -> str:
        """Returns state of the connection to the hardware device."""
        return self._state

    async def connect(
        self,
        auto_reconnect: bool = False,
        reconnect_delay: float = const.DEFAULT_RECONNECT_DELAY,
    ) -> None:
        """Connects to the hardware device."""
        if self._state == const.STATE_CONNECTED:
            return

        if re.search("^[0-9.]+$", self._host) is None:
            host = self._host
            try:
                # Attempt resolving via mDNS
                self._host = await self._resolve(host, True)
            except dns.exception.DNSException:
                try:
                    # Attempt resolving via DNS
                    self._host = await self._resolve(host)
                except dns.exception.DNSException:
                    raise ConnectionError(f"Failed to resolve host {self._host}")

            _LOGGER.debug("Resolved %s to %s", host, self._host)

        # Disable auto_reconnect until a good initial connect
        self._auto_reconnect = False

        await self._connect()

        self._auto_reconnect = auto_reconnect
        self._reconnect_delay = reconnect_delay

        _LOGGER.info("Connected to %s", self._host)

    async def _resolve(self, host: str, use_mdns: bool = False) -> str:
        """Resolve hostname to IP using mDNS."""
        resolver = dns.asyncresolver.Resolver()
        if use_mdns:
            resolver.nameservers = ["224.0.0.251"]
            resolver.port = 5353
        resolver.lifetime = min(self._timeout, 5.0)
        answer: list[A] = await resolver.resolve(host, rdtype="A")
        if len(answer) == 0:
            raise RuntimeError("Answer expected")
        return answer[0].to_text()

    async def _connect(self) -> None:
        """Connect to host device."""
        try:
            connection = asyncio.open_connection(self._host, self._port)
            self._reader, self._writer = await asyncio.wait_for(
                connection, self._timeout
            )
        except ConnectionError:
            # Don't allow subclasses of ConnectionError to be cast as OSErrors below
            raise
        except (OSError, asyncio.TimeoutError) as err:
            # Generalize connection errors
            raise ConnectionError(format_error(err)) from err

        self._response_handler_task = asyncio.create_task(self._response_handler())

        self._state = const.STATE_CONNECTED
        self._dispatcher.send(SIGNAL_CONNECTION_EVENT, EVENT_CONNECTION_CONNECTED)

    async def _response_handler(self) -> None:
        """Main loop receiving responses and events from hardware device."""
        assert self._reader

        while True:
            try:
                result = await self._reader.readuntil()

                response = Response.factory(result.decode("latin-1").strip())
                _LOGGER.debug("Response received '%s'", response.message)

                device_id = response.device_id

                if response.is_event:
                    # Events are unsolicited notifications about a change in state.
                    # Send message to all devices.
                    self._dispatcher.send(
                        SIGNAL_CONNECTION_EVENT, EVENT_CONNECTION_MESSAGE, response
                    )
                else:
                    # Messages are a response to a pending request.
                    if device_id not in self._pending_requests:
                        _LOGGER.warning("Response device not registered '%s'", response)
                    elif response.seq not in self._pending_requests[device_id]:
                        _LOGGER.warning("Response seq not registered '%s'", response)
                    else:
                        request = self._pending_requests[device_id][response.seq]
                        request.set(response)
            except (asyncio.IncompleteReadError, ConnectionError, OSError) as err:
                asyncio.create_task(self._handle_connection_error(err))
                return
            except MessageParseError as err:
                _LOGGER.exception(err)
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception(
                    "Unhandled exception %s('%s')", type(err).__name__, err
                )

    async def _handle_connection_error(self, err: Exception):
        """Handle connection failures and schedule reconnect."""
        if self._reconnect_task:
            return

        await self._disconnect()

        if self._auto_reconnect:
            self._state = const.STATE_RECONNECTING
            self._reconnect_task = asyncio.create_task(self._reconnect())
        else:
            self._state = const.STATE_DISCONNECTED

        _LOGGER.debug(
            "Disconnected from %s %s('%s')", self._host, type(err).__name__, err
        )
        self._dispatcher.send(SIGNAL_CONNECTION_EVENT, EVENT_CONNECTION_DISCONNECTED)

    async def _reconnect(self):
        """Reconnect to host device."""
        try:
            while self._state != const.STATE_CONNECTED:
                try:
                    await self._connect()
                except ConnectionError as err:
                    _LOGGER.debug("Failed reconnect to %s with '%s'", self._host, err)
                    await self._disconnect()
                    await asyncio.sleep(self._reconnect_delay)
                else:
                    self._reconnect_task = None
                    _LOGGER.info("Reconnected to %s", self._host)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Unhandled exception %s('%s')", type(err).__name__, err)
            raise

    async def disconnect(self):
        """Disconnect from host device."""
        if self._state == const.STATE_DISCONNECTED:
            return

        # Cancel pending reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except:  # pylint: disable=bare-except
                # Ensure completes
                pass
            self._reconnect_task = None

        await self._disconnect()
        self._state = const.STATE_DISCONNECTED

        _LOGGER.info("Disconnected from %s", self._host)
        self._dispatcher.send(SIGNAL_CONNECTION_EVENT, EVENT_CONNECTION_DISCONNECTED)

    async def _disconnect(self):
        """Disconnect from host device."""
        if self._response_handler_task:
            self._response_handler_task.cancel()
            try:
                await self._response_handler_task
            except:  # pylint: disable=bare-except
                # Ensure completes
                pass
            self._response_handler_task = None

        if self._writer:
            self._writer.close()
            self._writer = None

        self._reader = None
        self._pending_requests.clear()

    async def send(self, request: Request) -> Response:
        """Sends request to host device."""
        if self._state != const.STATE_CONNECTED:
            err = "Not connected to device"
            _LOGGER.error(err)
            raise KaleidescapeError(err)

        if request.device_id not in self._pending_requests:
            self._pending_requests[request.device_id] = {}

        while request.seq < 0:
            try:
                # Devices can only handle 10 concurrent requests. Find next available
                # sequence number not in use.
                request.seq = next(
                    (
                        i
                        for i in range(0, 10)
                        if i not in self._pending_requests[request.device_id]
                    )
                )
            except StopIteration:
                await asyncio.sleep(0.01)
                continue

        self._pending_requests[request.device_id][request.seq] = request

        try:
            assert self._writer
            writer = self._writer
            writer.write(str(request).encode("latin-1") + SEPARATOR_BYTES)
            await writer.drain()
            _LOGGER.debug("Request sent '%s'", request)
            response = await asyncio.wait_for(request.wait(), self._timeout)
        except (OSError, ConnectionError, asyncio.TimeoutError) as err:
            msg = f"Request '{request}' failed with '{format_error(err)}'"
            _LOGGER.warning(msg)
            raise KaleidescapeError(msg) from err

        return response

    def clear(self, request: Request):
        """Clears request from the pending requests list, indicating response has been
        received."""
        if request.device_id not in self._pending_requests:
            _LOGGER.error("Request device_id not registered '%s'", request)
        elif request.seq not in self._pending_requests[request.device_id]:
            _LOGGER.error("Request seq not registered '%s'", request)
        else:
            self._pending_requests[request.device_id].pop(request.seq)
