"""Simple Kaleidescape Control Protocol emulator used for unit testing."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from kaleidescape import const, error
from kaleidescape import message as messages
from kaleidescape.connection import SEPARATOR
from kaleidescape.const import SUCCESS
from kaleidescape.message import MessageParser

_LOGGER = logging.getLogger(__name__)


# pylint: disable=missing-function-docstring, invalid-name, line-too-long
# fmt: off

SIMPLE_COMMANDS: tuple[type[messages.Request], ...] = (
    messages.LeaveStandby,
    messages.EnterStandby,
    messages.Play,
    messages.Pause,
    messages.Stop,
    messages.Next,
    messages.Previous,
    messages.Replay,
    messages.ScanForward,
    messages.ScanReverse,
    messages.Select,
    messages.Up,
    messages.Down,
    messages.Left,
    messages.Right,
    messages.Cancel,
    messages.StatusAndSettings,
    messages.IntermissionToggle,
    messages.GoMovieList,
    messages.GoMovieCollections,
    messages.GoMovies,
    messages.GoMovieCovers,
    messages.MenuToggle,
)


class NoResponse(messages.Request):
    """Test-only command the emulator accepts but never answers."""

    name = "_NO_RESPONSE"


class Request:
    """Class representing a request sent to Emulator from Client."""

    def __init__(self, msg: str) -> None:
        parsed = MessageParser(msg, True)
        self.message = msg
        self.device_id: str = parsed.device_id
        self.seq: int = parsed.seq
        self.name: str = parsed.name
        self.fields: list[str] = parsed.fields
        self.checksum: int = parsed.checksum


class Response:
    """Class representing a response sent from Emulator to Client."""

    def __init__(
        self,
        device_id: str | None,
        seq: int = 0,
        status: int = 0,
        name: str | None = None,
        fields: list[str] | None = None,
    ):
        self.device_id = device_id
        self.seq = seq
        self.status = status
        self.name = name
        self.fields = fields
        self.checksum: int = 1

    def __str__(self) -> str:
        msg = [f"{self.status:03}"]
        if self.name:
            msg.append(self.name)
        if self.fields:
            fields = [self._encode(str(f)) for f in self.fields]
            msg = msg + fields
        seq = "!" if self.seq < 0 else str(self.seq)
        return f"{self.device_id}/{seq}/{':'.join(msg)}:/1"

    def _encode(self, field: str) -> str:
        field = field.replace("\\", "\\\\")
        field = field.replace("/", r"\/")
        field = field.replace("\n", "\\\n")  # The escaped newline emulated the bug found in actual devices
        field = field.replace("\r", "\\\r")
        field = field.replace("\t", r"\t")
        field = field.replace(":", r"\:")
        for i in range(192, 255):
            field = field.replace(chr(i), "\\d{i:03}")
        return field


class Event(Response):
    """Class for responses that are broadcast to multiple Devices."""

    def __init__(self, source_device_ids: list[str], status: int, name: str, fields: list[str] | None = None) -> None:
        super().__init__(None, -1, status, name, fields)
        self.source_device_ids = source_device_ids


class Client:
    """Class representing a connection to Emulator."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self._writer = writer

    async def disconnect(self):
        self._writer.close()
        with contextlib.suppress(OSError):
            await self._writer.wait_closed()

    async def _write(self, payload: str):
        data = (payload + SEPARATOR).encode("latin-1")
        self._writer.write(data)
        await self._writer.drain()

    async def send(self, msg: str | Response | Event):
        if isinstance(msg, Event):
            for device_id in msg.source_device_ids:
                msg.device_id = device_id
                await self._write(str(msg))
                _LOGGER.debug("> %s", str(msg))
        elif isinstance(msg, Response):
            await self._write(str(msg))
            _LOGGER.debug("> %s", str(msg))
        else:
            await self._write(msg)
            _LOGGER.debug("> %s", msg)


class Emulator:
    """Class for emulating a Kaleidescape system."""

    def __init__(self, host: str, port: int = 0):
        """Initialize the emulator. Port 0 binds a free port on first start."""
        self._host = host
        self._port = port
        self._clients: list[Client] = []
        self._client_tasks: set[asyncio.Task] = set()
        self._server: asyncio.Server | None = None
        self._mock_commands: dict[str, dict] = {}
        self.received_requests: list[Request] = []
        self._client_connected = asyncio.Event()

        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetAvailableDevicesBySerialNumber.name,
            (SUCCESS, messages.AvailableDevicesBySerialNumber.name, ["00000000123A"])
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetAvailableDevices.name,
            (SUCCESS, messages.AvailableDevices.name, ["01"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetDeviceInfo.name,
            (SUCCESS, messages.DeviceInfo.name, ["", "00000000123A", "00", "127.0.0.1"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetSystemVersion.name,
            (SUCCESS, messages.SystemVersion.name, ["16", "10.4.2-19218"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetNumZones.name,
            (SUCCESS, messages.NumZones.name, ["01", "01"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetDeviceTypeName.name,
            (SUCCESS, messages.DeviceTypeName.name, ["Strato S"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetFriendlyName.name,
            (SUCCESS, messages.FriendlyName.name, ["Theater"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetDevicePowerState.name,
            (SUCCESS, messages.DevicePowerState.name, ["0", "0"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetSystemReadinessState.name,
            (SUCCESS, messages.SystemReadinessState.name, ["2"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetContentDetails.name,
            [
                (SUCCESS, messages.ContentDetailsOverview.name, ["2", "26-0.0-S_c446c8e2", "movies"]),
                (SUCCESS, messages.ContentDetails.name, ["1", "Content_handle", "26-0.0-S_c446c8e2"]),
                (SUCCESS, messages.ContentDetails.name, ["2", "Title", "Turtle Odyssey"]),
            ]
        )

        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetFriendlySystemName.name,
            (SUCCESS, messages.FriendlySystemName.name, ["Home Cinema"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetZoneCapabilities.name,
            (SUCCESS, messages.ZoneCapabilities.name, ["Y", "Y", "N", "Y"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetUiState.name,
            (SUCCESS, messages.UiState.name, ["01", "00", "00", "0"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetHighlightedSelection.name,
            (SUCCESS, messages.HighlightedSelection.name, [""]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetPlayStatus.name,
            (SUCCESS, messages.PlayStatus.name, ["0", "1", "00", "00000", "00000", "000", "00000", "00000"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetMovieLocation.name,
            (SUCCESS, messages.MovieLocation.name, ["03"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetVideoColor.name,
            (SUCCESS, messages.VideoColor.name, ["00", "00", "24", "00"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetVideoMode.name,
            (SUCCESS, messages.VideoMode.name, ["00", "00", "00"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetScreenMask.name,
            (SUCCESS, messages.ScreenMask.name, ["00", "000", "000", "05", "0000", "0000"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetScreenMask2.name,
            (SUCCESS, messages.ScreenMask2.name, ["00", "00", "00000", "00000"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetCinemascapeMode.name,
            (SUCCESS, messages.CinemascapeMode.name, ["0"]),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.GetCinemascapeMask.name,
            (SUCCESS, messages.CinemascapeMask.name, ["000"]),
        )

        self.register_mock_command(
            ("01", "#00000000123A"),
            messages.EnableEvents.name,
            (SUCCESS,),
        )
        for command in SIMPLE_COMMANDS:
            self.register_mock_command(
                ("01", "#00000000123A"),
                command.name,
                (SUCCESS,),
            )
        self.register_mock_command(
            ("01",),
            messages.SendEvent.name,
            (SUCCESS,),
        )
        self.register_mock_command(
            ("01",),
            messages.SendToSyslog.name,
            (SUCCESS,),
        )
        self.register_mock_command(
            ("01", "#00000000123A"),
            NoResponse.name,
            [],
        )

    @property
    def port(self) -> int:
        """Returns the port the emulator listens on."""
        return self._port

    async def start(self):
        """Starts the emulator, on the same port when restarted."""
        if self._server:
            raise RuntimeError("Already started")
        self._client_connected.clear()
        self._server = await asyncio.start_server(
            self._accept, self._host, self._port
        )
        self._port = self._server.sockets[0].getsockname()[1]
        _LOGGER.debug("Started on port %s", self._port)

    async def stop(self):
        """Stops the emulator and closes every client connection."""
        if self._server is None:
            return
        server = self._server
        self._server = None
        server.close()
        # Closed here, not by the client tasks: a task cancelled before its first
        # step never runs its cleanup.
        for client in list(self._clients):
            await client.disconnect()
        self._clients.clear()
        tasks = list(self._client_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await server.wait_closed()
        self._client_connected.clear()
        _LOGGER.debug("Stopped")

    def register_mock_command(
            self,
            device_ids: tuple[str, ...],
            name: str,
            msg: tuple | list
    ):
        """Adds a new simulated command to server. Overrides built in commands."""
        for device_id in device_ids:
            self._mock_commands.setdefault(device_id, {})
            self._mock_commands[device_id][name] = msg

    async def wait_for_client(self) -> None:
        """Waits until a client connection has been accepted.

        stop() only closes accepted clients, so a test that stops the emulator
        right after connecting must wait for the accept to be handled first.
        """
        await self._client_connected.wait()

    def requests_named(self, name: str) -> list[Request]:
        """Returns the received requests with the given message name."""
        return [r for r in self.received_requests if r.name == name]

    def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Registers a new client connection synchronously, so stop() always sees it."""
        if self._server is None:
            # Accepted by the socket before stop() closed the server.
            writer.close()
            return
        client = Client(reader, writer)
        self._clients.append(client)
        task = asyncio.create_task(self._serve(client))
        self._client_tasks.add(task)
        task.add_done_callback(self._client_tasks.discard)
        self._client_connected.set()
        _LOGGER.debug("Client connected")

    async def _serve(self, client: Client):
        """Main service loop for a client connection."""
        try:
            await self._serve_requests(client)
        finally:
            with contextlib.suppress(ValueError):
                self._clients.remove(client)
            await client.disconnect()
            _LOGGER.debug("Client disconnected")

    async def _serve_requests(self, client: Client):
        while True:
            request = None
            try:
                data = await client.reader.readuntil()
                result = data.decode("latin-1").strip()
                if not result:
                    continue

                _LOGGER.debug("< %s", result)

                request = Request(result)
                self.received_requests.append(request)

                if request.device_id in self._mock_commands:
                    if request.name in self._mock_commands[request.device_id]:
                        msgs = self._mock_commands[request.device_id][request.name]
                    else:
                        raise error.MessageError(const.ERROR_INVALID_REQUEST, request.message)
                else:
                    raise error.MessageError(const.ERROR_INVALID_DEVICE, request.message)

                if isinstance(msgs, int):
                    msgs = [(msgs,)]
                elif isinstance(msgs, tuple):
                    msgs = [msgs]

                for msg in msgs:
                    await client.send(Response(request.device_id, request.seq, *msg))

                await asyncio.sleep(0.001)

            except (asyncio.IncompleteReadError, ConnectionError):
                break
            except (error.MessageError, error.MessageParseError) as e:
                device_id = request.device_id if request else "??"
                seq = request.seq if request else -1
                response = Response(device_id, seq, e.code, e.error)
                await client.send(response)

    async def send_event(self, device_ids: list[str], status: int, name: str, fields: list[str] | None = None):
        """Sends an event message to device_ids."""
        event = Event(device_ids, status, name, fields)
        for client in self._clients:
            await client.send(event)
