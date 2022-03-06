"""Class handling network connection to hardware device."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
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

SEPARATOR = "\n"
SEPARATOR_BYTES = SEPARATOR.encode("latin-1")


class Connection:
    """Class handling network connection to hardware device."""

    def __init__(self, dispatcher: Dispatcher, on_event: Callable = None) -> None:
        """Initializes connection."""
        self._dispatcher = dispatcher
        self._on_event = on_event

        self._ip: str | None = None
        self._port: int | None = None
        self._timeout: float | None = None
        self._state: str = const.STATE_DISCONNECTED
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._response_handler_task: asyncio.Task | None = None
        self._reconnect_delay: float | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_enabled: bool = False
        self._pending_requests: dict[int, Request] = {}

    @property
    def dispatcher(self) -> Dispatcher:
        """Return dispatcher instance."""
        return self._dispatcher

    @property
    def ip(self) -> str | None:
        """Return ip of the server connected to."""
        return self._ip

    @property
    def port(self) -> int | None:
        """Return port of the hardware device to connect to."""
        return self._port

    @property
    def timeout(self) -> float | None:
        """Return connection timeout in seconds."""
        return self._timeout

    @property
    def state(self) -> str:
        """Return state of the connection to the hardware device."""
        return self._state

    async def connect(
        self,
        ip: str,
        port: int,
        timeout: float,
        reconnect: bool = False,
        reconnect_delay: float = const.DEFAULT_RECONNECT_DELAY,
    ) -> None:
        """Connect to the hardware device."""
        if self._state == const.STATE_CONNECTED:
            return

        self._ip = ip
        self._port = port
        self._timeout = timeout

        # Disable auto_reconnect until a good connect
        self._reconnect_enabled = False

        await self._connect()

        self._reconnect_enabled = reconnect
        self._reconnect_delay = reconnect_delay

        _LOGGER.info("Connected to %s", self._ip)

    async def _connect(self) -> None:
        """Connect to server."""
        try:
            connection = asyncio.open_connection(self._ip, self._port)
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
        self._dispatcher.send(const.STATE_CONNECTED)

    async def _response_handler(self) -> None:
        """Main loop receiving responses and events from hardware device."""
        assert self._reader

        while True:
            try:
                result = await self._reader.readuntil()

                response = Response.factory(result.decode("latin-1").strip())
                _LOGGER.debug("Response received '%s'", response.message)

                if response.is_event:
                    # Events are unsolicited notifications about a change in state.
                    if self._on_event:
                        asyncio.create_task(self._on_event(response))
                elif response.device_id == const.LOCAL_CPDID:
                    if response.seq not in self._pending_requests:
                        _LOGGER.error("Response seq not registered '%s'", response)
                    else:
                        request = self._pending_requests[response.seq]
                        request.set(response)
            except (asyncio.IncompleteReadError, OSError) as err:
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

        if self._reconnect_enabled:
            self._state = const.STATE_RECONNECTING
            self._reconnect_task = asyncio.create_task(self._reconnect())
        else:
            self._state = const.STATE_DISCONNECTED

        _LOGGER.error(
            "Disconnected from %s %s('%s')", self._ip, type(err).__name__, err
        )
        self._dispatcher.send(const.STATE_DISCONNECTED)

    async def _reconnect(self):
        """Reconnect to server."""
        try:
            while self._state != const.STATE_CONNECTED:
                try:
                    await self._connect()
                except ConnectionError as err:
                    _LOGGER.warning("Failed reconnect to %s with '%s'", self._ip, err)
                    await self._disconnect()
                    await asyncio.sleep(self._reconnect_delay)
                else:
                    self._reconnect_task = None
                    _LOGGER.info("Reconnected to %s", self._ip)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Unhandled exception %s('%s')", type(err).__name__, err)
            raise

    async def disconnect(self):
        """Disconnect from server."""
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

        _LOGGER.info("Disconnected from %s", self._ip)
        self._dispatcher.send(const.STATE_DISCONNECTED)

    async def _disconnect(self):
        """Disconnect from server."""
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
        """Send request to device"""
        if self._state != const.STATE_CONNECTED:
            err = "Not connected to device"
            _LOGGER.error(err)
            raise KaleidescapeError(err)

        wait = 0.01
        retries = self.timeout * (1/wait)

        while request.seq < 0:
            try:
                # Devices can only handle 10 concurrent requests. Find next available
                # sequence number not in use.
                request.seq = next(
                    (i for i in range(0, 10) if i not in self._pending_requests)
                )
            except StopIteration:
                await asyncio.sleep(wait)
                retries = retries - 1
                if retries == 0:
                    raise ConnectionError
                continue

        self._pending_requests[request.seq] = request

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
        """Clear request from the pending requests list, indicating response has been
        received."""
        if request.seq not in self._pending_requests:
            _LOGGER.error("Request seq not registered '%s'", request)
        else:
            self._pending_requests.pop(request.seq)

    @staticmethod
    async def resolve(host: str, timeout: int = 5) -> str:
        """Resolve hostname to ip address."""

        async def _resolve(use_mdns: bool) -> str:
            resolver = dns.asyncresolver.Resolver()
            resolver.lifetime = timeout
            if use_mdns:
                resolver.nameservers = ["224.0.0.251"]
                resolver.port = 5353
            answer: list[A] = await resolver.resolve(host, rdtype="A")
            if len(answer) == 0:
                raise RuntimeError("Answer expected")
            return answer[0].to_text()

        ip_address = host

        if re.search("^[0-9.]+$", host) is None:
            try:
                # Attempt resolving via mDNS
                ip_address = await _resolve(True)
            except dns.exception.DNSException:
                try:
                    # Attempt resolving via DNS
                    ip_address = await _resolve(False)
                except dns.exception.DNSException as err:
                    raise ConnectionError(f"Failed to resolve host {host}") from err
        else:
            # Normalize IP by removing leading zeros
            ip_address = re.sub(r"\b0+(\d)", r"\1", ip_address)

        if ip_address != host:
            _LOGGER.debug("Resolved %s to %s", host, ip_address)

        return ip_address
