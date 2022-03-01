"""Classes for handling messages from the hardware device."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

from . import const
from .const import LOCAL_CPDID
from .error import KaleidescapeError, MessageError, MessageParseError

if TYPE_CHECKING:
    from .connection import Connection

MESSAGE_TYPE_REQUEST = "request"
MESSAGE_TYPE_RESPONSE = "response"
MESSAGE_TYPE_EVENT = "event"

CPDID_FORMAT = re.compile(r"^\d\d$")
DEVICEID_FORMAT = re.compile(r"^(?P<id>\d\d|#[0-9A-F]+|\?\?)(?:\.(?P<zone>\d\d))?/")
SEQ_FORMAT = re.compile(r"^(?:\d|!)/")
STATUS_FORMAT = re.compile(r"^\d\d\d:")
NAME_FORMAT = re.compile(r"^(?:([^:]+):/?|/)")

registry = {}

_LOGGER = logging.getLogger(__name__)


def register(cls):
    """Decorator registering a message response class for factory use."""
    registry[cls.name] = cls
    return cls


class MessageParser:
    """Class for parsing messages from the hardware device."""

    def __init__(self, message: str, *args):
        """Parses string message into its fields."""
        self.message = message

        self.device_id: str = ""
        self.zone: int = 0
        self.seq: int = 0
        self.status: int = 0
        self.name: str = ""
        self.fields: list[str] = []
        self.checksum: int = 0

        is_request: bool = args[0] if len(args) > 0 else False

        pos = self._parse_device_id(0)
        pos = self._parse_seq(pos)
        if not is_request:
            pos = self._parse_status(pos)
        pos = self._parse_name(pos)
        pos = self._parse_fields(pos)
        if not is_request:
            self._parse_checksum(pos)

    def _parse_device_id(self, pos: int) -> int:
        match = re.search(DEVICEID_FORMAT, self.message[pos:])
        if not match:
            raise MessageParseError(const.ERROR_INVALID_DEVICE, self.message)
        self.device_id = match.group("id")
        self.zone = int(match.group("zone")) if match.group("zone") else 0
        return pos + match.end()

    def _parse_seq(self, pos: int) -> int:
        if not re.match(SEQ_FORMAT, self.message[pos:]):
            raise MessageParseError(const.ERROR_INVALID_SEQ_NUMBER, self.message)
        self.seq = int(self.message[pos]) if self.message[pos] != "!" else -1
        return pos + 2

    def _parse_status(self, pos: int) -> int:
        if not re.match(STATUS_FORMAT, self.message[pos:]):
            raise MessageParseError(const.ERROR_UNDETERMINED_ERROR, self.message)
        self.status = int(self.message[pos : pos + 3])
        return pos + 4

    def _parse_name(self, pos: int) -> int:
        match = re.search(NAME_FORMAT, self.message[pos:])
        if not match:
            raise MessageParseError(const.ERROR_INVALID_REQUEST, self.message)
        self.name = self.message[pos : pos + match.end(1)]
        return pos + match.end(1) + 1

    def _parse_fields(self, pos: int) -> int:
        field: str = ""
        escaped: bool = False

        while pos < len(self.message):
            char = self.message[pos]
            if escaped:
                if char == "d":
                    field += chr(int(self.message[pos + 1 : pos + 4]))
                    pos = pos + 3
                elif char == "r":
                    field += "\r"
                elif char == "n":
                    field += "\n"
                elif char == "t":
                    field += "\t"
                elif char == "/":
                    field += "/"
                elif char == "\\":
                    field += "\\"
                elif char == ":":
                    field += ":"
                elif char == "\n":
                    # Protocol bug: newline chars are not coming in encoded
                    field += "\n"
                elif char == "\r":
                    # Same bug as above
                    field += "\r"
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "/":
                break
            elif char == ":":
                self.fields.append(field)
                field = ""
            else:
                field += char

            pos = pos + 1

        if field:
            # Last field not terminated with colon
            raise MessageParseError(const.ERROR_INVALID_PARAMETER, self.message)

        return pos + 1

    def _parse_checksum(self, pos: int):
        if not re.match(r"^\d+$", self.message[pos:]):
            raise MessageParseError(const.ERROR_CHECKSUM_ERROR, self.message)
        self.checksum = int(self.message[pos:])

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"message='{self.message}', "
            f"device_id='{self.device_id}', "
            f"zone={self.zone}, "
            f"seq={self.seq}, "
            f"status={self.status}, "
            f"name='{self.name}', "
            f"fields={self.fields}, "
            f"checksum={self.checksum}"
            ")"
        )


class Message:
    """Abstract class for both request messages (command) and response messages
    (command and event)."""

    name: str = ""
    multiline = False

    def __init__(
        self,
        device_id: str = LOCAL_CPDID,
        zone: int = 0,
        seq: int = 0,
        status: int = 0,
        fields: list[str] | None = None,
    ):
        """Initializes message."""
        self._device_id = device_id
        self._zone = zone
        self._seq = seq
        self._status = status
        self._fields: list[str] = fields if fields is not None else []
        self._message: str = ""
        self._type: str = ""

    @property
    def message(self) -> str:
        """Returns body of the message."""
        return self._message

    @property
    def device_id(self) -> str:
        """The device_id of the message."""
        return self._device_id

    @property
    def zone(self) -> int:
        """Returns zone of the message."""
        return self._zone

    @property
    def seq(self) -> int:
        """Returns sequence of the message."""
        return self._seq

    @seq.setter
    def seq(self, value: int) -> None:
        """Sets sequence number of the message."""
        self._seq = value

    @property
    def status(self) -> int:
        """Returns status of the message."""
        return self._status

    @property
    def type(self) -> str:
        """Returns type of message (request/response)."""
        return self._type

    @property
    def count(self) -> int:
        """Returns how many messages are in message group.

        This is used for responses such as CONTENT_DETAILS which return multiple
        messages in a group.
        """
        raise RuntimeError("This message type does not support the 'count' property")

    def __str__(self) -> str:
        return str(self.message)


class Request(Message):
    """Class representing a command request sent to hardware device."""

    log_invalid_request: bool = True

    def __init__(self, zone: int = 0, fields: list[str] | None = None):
        """Initializes request."""
        super().__init__(
            LOCAL_CPDID, zone, fields=fields if fields is not None else fields
        )

        self.seq = -1
        self._type = MESSAGE_TYPE_REQUEST
        self._responses: list[Response] = []
        self._event = asyncio.Event()

    @property
    def fields(self) -> list[str]:
        """Returns fields in the message."""
        return self._fields

    async def send(self, connection: Connection) -> list[Response]:
        """Sends request to hardware device, returning one or more responses."""
        self._event.clear()
        self._responses.clear()

        response = await connection.send(self)

        if not response.multiline:
            connection.clear(self)

        if response.is_error:
            lvl = logging.ERROR
            if (
                not self.log_invalid_request
                and response.status == const.ERROR_INVALID_REQUEST
            ):
                lvl = logging.DEBUG
            _LOGGER.log(lvl, "Request %s failed with '%s'", repr(self), response.error)
            raise MessageError(response.status, str(self))

        _LOGGER.debug("Request %s received %s", repr(self), repr(response))

        if response.multiline:
            if not response.count:
                _LOGGER.error(
                    "Command %s response had no count '%s'", repr(self), repr(response)
                )
                raise KaleidescapeError("Response count expected")

            async def collector():
                while (len(self._responses) - 1) < response.count:
                    await asyncio.sleep(0)

            try:
                await asyncio.wait_for(collector(), connection.timeout)
            except asyncio.TimeoutError as error:
                err = f"Command {repr(self)} timed out waiting for responses"
                _LOGGER.warning(err)
                raise KaleidescapeError(err) from error

            connection.clear(self)
            return self._responses

        return [response]

    async def wait(self) -> Response:
        """Wait until the event is set."""
        await self._event.wait()
        return self._responses[0]

    def set(self, response: Response) -> None:
        """Complete request."""
        self._responses.append(response)
        self._event.set()

    def __str__(self) -> str:
        if self._message == "":
            seq = "!" if self.seq < 0 else str(self.seq)
            fields = ":".join(self._fields) + ":" if self._fields else ""
            self._message = f"{self._device_id}/{seq}/{self.name}:{fields}"
        return self._message

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"device_id={self.device_id}, "
            f"seq={self.seq}, "
            f"fields={self.fields}"
            ")"
        )


class Response(Message):
    """Class representing a command response or event from hardware device."""

    def __init__(self, parsed: MessageParser):
        """Initializes response."""
        super().__init__(
            parsed.device_id, parsed.zone, parsed.seq, parsed.status, parsed.fields
        )
        self._message = parsed.message
        self._type = MESSAGE_TYPE_EVENT if parsed.seq < 0 else MESSAGE_TYPE_RESPONSE

    @classmethod
    def factory(cls, message: str) -> Response:
        """Returns a new response object for message."""
        parsed = MessageParser(message)
        if parsed.name in registry:
            return registry[parsed.name](parsed)
        return cls(parsed)

    @property
    def is_event(self) -> bool:
        """Returns if response is an event."""
        return self._type == MESSAGE_TYPE_EVENT

    @property
    def is_error(self) -> bool:
        """Returns if response is an error."""
        return bool(self._status)

    @property
    def error(self) -> str:
        """Returns text associated with this message's status."""
        return const.RESPONSE_ERROR[self._status]

    @property
    def fields(self) -> Any:
        """Returns fields in the message."""
        return self._fields

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"device_id={self.device_id}, "
            f"seq={self.seq}, "
            f"status={self.status}, "
            f"fields={self.fields}"
            ")"
        )


@register
class Ack(Response):
    """Class for empty response messages."""

    name = ""


class GetSystemPairingInfo(Request):
    """Class for GET_SYSTEM_PAIRING_INFO messages."""

    log_invalid_request = False
    name = f"GET_{const.SYSTEM_PAIRING_INFO}"


@register
class SystemPairingInfo(Response):
    """Class for SYSTEM_PAIRING_INFO messages."""

    name = const.SYSTEM_PAIRING_INFO

    @property
    def is_paired(self) -> bool:
        """Returns if system is paired."""
        return self._fields[0] != ""

    @property
    def field_paired_system_id(self) -> str:
        """Returns system id of paired peer."""
        return self._fields[1].lower()

    @property
    def field_paired_friendly_name(self) -> str:
        """Returns friendly name of peer."""
        return self._fields[2]

    @property
    def field_paired_peers(self) -> list[tuple[str, str]]:
        """Returns list of peers."""
        if not self.is_paired:
            return []
        res: list[tuple[str, str]] = []
        for i in range(3, len(self._fields), 2):
            encore = f"{(self._fields[i].strip('#'))[-12:]:0>12}"
            premier = f"{(self._fields[i+1].strip('#'))[-12:]:0>12}"
            res.append((encore.upper(), premier.upper()))
        return res


class GetAvailableDevices(Request):
    """Class for GET_AVAILABLE_DEVICES messages."""

    name = f"GET_{const.AVAILABLE_DEVICES}"


@register
class AvailableDevices(Response):
    """Class for AVAILABLE_DEVICES messages."""

    name = const.AVAILABLE_DEVICES

    @property
    def field(self) -> list[str]:
        """Returns list of available devices."""
        return self._fields


class GetAvailableDevicesBySerialNumber(Request):
    """Class for GET_AVAILABLE_DEVICES_BY_SERIAL_NUMBER messages."""

    name = f"GET_{const.AVAILABLE_DEVICES_BY_SERIAL_NUMBER}"


@register
class AvailableDevicesBySerialNumber(Response):
    """Class for AVAILABLE_DEVICES_BY_SERIAL_NUMBER messages."""

    name = const.AVAILABLE_DEVICES_BY_SERIAL_NUMBER

    @property
    def field(self) -> list[str]:
        """Returns list of serial numbers."""
        return [f"{i[-12:]:0>12}" for i in self._fields]


class GetSystemVersion(Request):
    """Class for GET_SYSTEM_VERSION messages."""

    name = f"GET_{const.SYSTEM_VERSION}"


@register
class SystemVersion(Response):
    """Class for SYSTEM_VERSION messages."""

    name = const.SYSTEM_VERSION

    @property
    def field_protocol(self) -> int:
        """Returns protocol."""
        return int(self._fields[0])

    @property
    def field_kos(self) -> str:
        """Returns kos."""
        return self._fields[1]


class GetDeviceInfo(Request):
    """Class for GET_DEVICE_INFO messages."""

    name = f"GET_{const.DEVICE_INFO}"


@register
class DeviceInfo(Response):
    """Class for DEVICE_INFO messages."""

    name = const.DEVICE_INFO

    @property
    def field_serial_number(self) -> str:
        """Returns serial number."""
        return f"{self._fields[1][-12:]:0>12}"

    @property
    def field_cpdid(self) -> str:
        """Returns cpdid."""
        return self._fields[2] if int(self._fields[2]) else ""

    @property
    def field_ip(self) -> str:
        """Returns ip."""
        return re.sub(r"\b0+(\d)", r"\1", self._fields[3])


class GetZoneCapabilities(Request):
    """Class for GET_ZONE_CAPABILITIES messages."""

    name = f"GET_{const.ZONE_CAPABILITIES}"


@register
class ZoneCapabilities(Response):
    """Class for ZONE_CAPABILITIES messages."""

    name = const.ZONE_CAPABILITIES

    @property
    def field_osd(self) -> bool:
        """Returns whether zone has osd."""
        return self._fields[0] == "Y"

    @property
    def field_movies(self) -> bool:
        """Returns whether has movie zones."""
        return self._fields[1] == "Y"

    @property
    def field_music(self) -> bool:
        """Returns whether has music zones."""
        return self._fields[2] == "Y"

    @property
    def field_store(self) -> bool:
        """Returns whether has store."""
        return self._fields[3] == "Y"


class GetNumZones(Request):
    """Class for GET_NUM_ZONES messages."""

    name = f"GET_{const.NUM_ZONES}"


@register
class NumZones(Response):
    """Class for NUM_ZONES messages."""

    name = const.NUM_ZONES

    @property
    def field_movie_zones(self) -> int:
        """Returns movie zones."""
        return int(self._fields[0])

    @property
    def field_music_zones(self) -> int:
        """Returns music zones."""
        return int(self._fields[1])


class GetDeviceTypeName(Request):
    """Class for GET_DEVICE_TYPE_NAME messages."""

    name = f"GET_{const.DEVICE_TYPE_NAME}"


@register
class DeviceTypeName(Response):
    """Class for DEVICE_TYPE_NAME messages."""

    name = const.DEVICE_TYPE_NAME

    @property
    def field(self) -> str:
        """Returns device type name."""
        return self._fields[0]


class GetDevicePowerState(Request):
    """Class for GET_DEVICE_POWER_STATE messages."""

    name = f"GET_{const.DEVICE_POWER_STATE}"


@register
class DevicePowerState(Response):
    """Class for DEVICE_POWER_STATE messages."""

    name = const.DEVICE_POWER_STATE
    index = {
        "power": {
            0: const.DEVICE_POWER_STATE_STANDBY,
            1: const.DEVICE_POWER_STATE_ON,
        },
        "zone": {
            0: const.DEVICE_ZONE_STATE_DISABLED,
            1: const.DEVICE_ZONE_STATE_AVAILABLE,
        },
    }

    @property
    def field_power(self) -> str:
        """Returns power state."""
        return self.index["power"][int(self._fields[0])]

    @property
    def field_zone(self) -> list[str]:
        """Returns zone state."""
        return [self.index["zone"][int(v)] for v in self._fields[1:]]


class GetSystemReadinessState(Request):
    """Class for GET_SYSTEM_READINESS_STATE messages."""

    name = f"GET_{const.SYSTEM_READINESS_STATE}"


@register
class SystemReadinessState(Response):
    """Class for SYSTEM_READINESS_STATE messages."""

    name = const.SYSTEM_READINESS_STATE
    index = {
        0: const.SYSTEM_READINESS_STATE_READY,
        1: const.SYSTEM_READINESS_STATE_BECOMING_READY,
        2: const.SYSTEM_READINESS_STATE_IDLE,
    }

    @property
    def field(self) -> str:
        """Returns readiness state."""
        return self.index[int(self._fields[0])]


class GetPlayStatus(Request):
    """Class for GET_PLAY_STATUS messages."""

    name = f"GET_{const.PLAY_STATUS}"


@register
class PlayStatus(Response):
    """Class for PLAY_STATUS messages."""

    name = const.PLAY_STATUS
    index = {
        0: const.PLAY_STATUS_NONE,
        1: const.PLAY_STATUS_PAUSED,
        2: const.PLAY_STATUS_PLAYING,
        4: const.PLAY_STATUS_FORWARD,
        6: const.PLAY_STATUS_REVERSE,
    }

    @property
    def field_play_status(self) -> str:
        """Return play status."""
        return self.index[int(self._fields[0])]

    @property
    def field_play_speed(self) -> int:
        """Returns play speed."""
        return int(self._fields[1])

    @property
    def field_title_number(self) -> int:
        """Returns title number."""
        return int(self._fields[2])

    @property
    def field_title_length(self) -> int:
        """Returns title length."""
        return int(self._fields[3])

    @property
    def field_title_location(self) -> int:
        """Returns title location."""
        return int(self._fields[4])

    @property
    def field_chapter_number(self) -> int:
        """Returns chapter number."""
        return int(self._fields[5])

    @property
    def field_chapter_length(self) -> int:
        """Returns chapter length."""
        return int(self._fields[6])

    @property
    def field_chapter_location(self) -> int:
        """Returns chapter location."""
        return int(self._fields[7])


class GetFriendlySystemName(Request):
    """Class for GET_FRIENDLY_SYSTEM_NAME messages."""

    name = f"GET_{const.FRIENDLY_SYSTEM_NAME}"


@register
class FriendlySystemName(Response):
    """Class for FRIENDLY_SYSTEM_NAME messages."""

    name = const.FRIENDLY_SYSTEM_NAME

    @property
    def field(self) -> str:
        """Returns friendly system name."""
        return self._fields[0]


class GetFriendlyName(Request):
    """Class for GET_FRIENDLY_NAME messages."""

    name = f"GET_{const.FRIENDLY_NAME}"


@register
class FriendlyName(Response):
    """Class for FRIENDLY_NAME messages."""

    name = const.FRIENDLY_NAME

    @property
    def field(self) -> str:
        """Returns friendly name."""
        return self._fields[0]


class GetUiState(Request):
    """Class for GET_UI_STATE messages."""

    name = f"GET_{const.UI_STATE}"


@register
class UiState(Response):
    """Class for UI_STATE messages."""

    name = const.UI_STATE
    index = {
        const.UI_STATE_SCREEN: {
            0: const.UI_STATE_SCREEN_UNKNOWN,
            1: const.UI_STATE_SCREEN_MOVIE_LIST,
            2: const.UI_STATE_SCREEN_MOVIE_COLLECTIONS,
            3: const.UI_STATE_SCREEN_MOVIE_COVERS,
            4: const.UI_STATE_SCREEN_PARENTAL_CONTROL,
            7: const.UI_STATE_SCREEN_PLAYING_MOVIE,
            8: const.UI_STATE_SCREEN_SYSTEM_STATUS,
            9: const.UI_STATE_SCREEN_MUSIC_LIST,
            10: const.UI_STATE_SCREEN_MUSIC_COVERS,
            11: const.UI_STATE_SCREEN_MUSIC_COLLECTIONS,
            12: const.UI_STATE_SCREEN_MUSIC_NOW_PLAYING,
            14: const.UI_STATE_SCREEN_VAULT_SUMMARY,
            15: const.UI_STATE_SCREEN_SYSTEM_SETTINGS,
            16: const.UI_STATE_SCREEN_MOVIE_STORE,
            17: const.UI_STATE_SCREEN_PAIRED_UNIT_LOBBY,
        },
        const.UI_STATE_POPUP: {
            0: const.UI_STATE_POPUP_NONE,
            1: const.UI_STATE_POPUP_DETAILS,
            2: const.UI_STATE_POPUP_MOVIE_STATUS,
            3: const.UI_STATE_POPUP_MOVIE_NOT_STATUS,
        },
        const.UI_STATE_DIALOG: {
            0: const.UI_STATE_DIALOG_NONE,
            1: const.UI_STATE_DIALOG_MENU,
            2: const.UI_STATE_DIALOG_PASSCODE,
            3: const.UI_STATE_DIALOG_QUESTION,
            4: const.UI_STATE_DIALOG_INFORMATION,
            5: const.UI_STATE_DIALOG_WARNING,
            6: const.UI_STATE_DIALOG_ERROR,
            7: const.UI_STATE_DIALOG_PREPLAY,
            8: const.UI_STATE_DIALOG_WARRANTY,
            9: const.UI_STATE_DIALOG_KEYBOARD,
            10: const.UI_STATE_DIALOG_IP_CONFIG,
        },
        const.UI_STATE_SAVER: {
            0: const.UI_STATE_SAVER_INACTIVE,
            1: const.UI_STATE_SAVER_ACTIVE,
        },
    }

    @property
    def field_screen(self) -> str:
        """Returns screen."""
        return self.index[const.UI_STATE_SCREEN][int(self._fields[0])]

    @property
    def field_popup(self) -> str:
        """Returns popup."""
        return self.index[const.UI_STATE_POPUP][int(self._fields[1])]

    @property
    def field_dialog(self) -> str:
        """Returns dialog."""
        return self.index[const.UI_STATE_DIALOG][int(self._fields[2])]

    @property
    def field_screensaver(self) -> str:
        """Returns screensaver."""
        return self.index[const.UI_STATE_SAVER][int(self._fields[3])]


class GetPlayingTitleName(Request):
    """Class for GET_PLAYING_TITLE_NAME messages."""

    name = f"GET_{const.PLAYING_TITLE_NAME}"


@register
class PlayingTitleName(Response):
    """Class for TITLE_NAME messages."""

    name = const.TITLE_NAME

    @property
    def field(self) -> str:
        """Returns title name."""
        return self._fields[0]


class GetHighlightedSelection(Request):
    """Class for GET_HIGHLIGHTED_SELECTION messages."""

    name = f"GET_{const.HIGHLIGHTED_SELECTION}"


@register
class HighlightedSelection(Response):
    """Class for HIGHLIGHTED_SELECTION messages."""

    name = const.HIGHLIGHTED_SELECTION

    @property
    def field(self) -> str:
        """Returns highlighted selection."""
        return self._fields[0]


class GetContentDetails(Request):
    """Class for GET_CONTENT_DETAILS messages."""

    name = f"GET_{const.CONTENT_DETAILS}"


@register
class ContentDetailsOverview(Response):
    """Class for CONTENT_DETAILS_OVERVIEW messages."""

    name = const.CONTENT_DETAILS_OVERVIEW
    multiline = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.details: dict[str, str] = {}

    @property
    def count(self) -> int:
        """Returns number of content detail rows."""
        return int(self._fields[0])

    @property
    def field_handle(self) -> str:
        """Returns handle."""
        return self._fields[1]

    @property
    def field_table(self) -> str:
        """Returns table."""
        return self._fields[2]

    @property
    def field_title(self) -> str:
        """Returns title."""
        return self.details["Title"] if "Title" in self.details else ""

    @property
    def field_cover_url(self) -> str:
        """Returns cover url."""
        if "Cover_URL" in self.details:
            return self.details["Cover_URL"]
        return ""

    @property
    def field_hires_cover_url(self) -> str:
        """Returns hires cover url."""
        if "HiRes_cover_URL" in self.details:
            return self.details["HiRes_cover_URL"]
        return ""

    @property
    def field_rating(self) -> str:
        """Returns rating."""
        if "Rating" in self.details:
            return self.details["Rating"]
        return ""

    @property
    def field_rating_reason(self) -> str:
        """Returns rating reason."""
        if "Rating_reason" in self.details:
            return self.details["Rating_reason"]
        return ""

    @property
    def field_year(self) -> str:
        """Returns year."""
        if "Year" in self.details:
            return self.details["Year"]
        return ""

    @property
    def field_running_time(self) -> str:
        """Returns running time."""
        if "Running_time" in self.details:
            return self.details["Running_time"]
        return "0"

    @property
    def field_actors(self) -> list[str]:
        """Returns actors."""
        if "Actors" in self.details:
            return re.split("[\n\r]+", self.details["Actors"])
        return []

    @property
    def field_director(self) -> str:
        """Returns director."""
        if "Director" in self.details:
            return self.details["Director"]
        return ""

    @property
    def field_directors(self) -> list[str]:
        """Returns directors."""
        if "Directors" in self.details:
            return re.split("[\n\r]+", self.details["Directors"])
        return []

    @property
    def field_genre(self) -> str:
        """Returns genre."""
        if "Genre" in self.details:
            return self.details["Genre"]
        return ""

    @property
    def field_genres(self) -> list[str]:
        """Returns genres."""
        if "Genres" in self.details:
            return re.split("[\n\r]+", self.details["Genres"])
        return []

    @property
    def field_synopsis(self) -> str:
        """Returns synopsis."""
        if "Synopsis" in self.details:
            return self.details["Synopsis"]
        return ""

    @property
    def field_color_description(self) -> str:
        """Returns color description."""
        if "Color_description" in self.details:
            return self.details["Color_description"]
        return ""

    @property
    def field_country(self) -> str:
        """Returns country."""
        if "Country" in self.details:
            return self.details["Country"]
        return ""

    @property
    def field_aspect_ratio(self) -> str:
        """Returns aspect ratio."""
        if "Aspect_ratio" in self.details:
            return self.details["Aspect_ratio"]
        return ""


@register
class ContentDetails(Response):
    """Class for CONTENT_DETAILS messages."""

    name = const.CONTENT_DETAILS

    @property
    def field(self) -> dict[str, str]:
        """Returns content details."""
        return {self.fields[1]: self.fields[2]}


class GetMovieLocation(Request):
    """Class for GET_MOVIE_LOCATION messages."""

    name = f"GET_{const.MOVIE_LOCATION}"


@register
class MovieLocation(Response):
    """Class for MOVIE_LOCATION messages."""

    name = const.MOVIE_LOCATION
    index = {
        0: const.MOVIE_LOCATION_NONE,
        3: const.MOVIE_LOCATION_CONTENT,
        4: const.MOVIE_LOCATION_INTERMISSION,
        5: const.MOVIE_LOCATION_CREDITS,
        6: const.MOVIE_LOCATION_DISC_MENU,
    }

    @property
    def field(self) -> str:
        """Returns movie location."""
        return self.index[int(self._fields[0])]


class GetMovieMediaType(Request):
    """Class for GET_MOVIE_MEDIA_TYPE messages."""

    name = f"GET_{const.MOVIE_MEDIA_TYPE}"


@register
class MovieMediaType(Response):
    """Class for MOVIE_MEDIA_TYPE messages."""

    name = const.MOVIE_MEDIA_TYPE
    index = {
        0: const.MOVIE_MEDIA_TYPE_NONE,
        1: const.MOVIE_MEDIA_TYPE_DVD,
        2: const.MOVIE_MEDIA_TYPE_STREAM,
        3: const.MOVIE_MEDIA_TYPE_BLURAY,
    }

    @property
    def field(self) -> str:
        """Returns media type."""
        return self.index[int(self._fields[0])]


class GetVideoColor(Request):
    """Class for GET_VIDEO_COLOR messages."""

    name = f"GET_{const.VIDEO_COLOR}"


@register
class VideoColor(Response):
    """Class for VIDEO_COLOR messages."""

    name = const.VIDEO_COLOR
    index = {
        const.VIDEO_COLOR_EOTF: {
            0: const.VIDEO_COLOR_EOTF_UNKNOWN,
            1: const.VIDEO_COLOR_EOTF_SDR,
            2: const.VIDEO_COLOR_EOTF_HDR,
            3: const.VIDEO_COLOR_EOTF_SMTPEST2084,
        },
        const.VIDEO_COLOR_SPACE: {
            0: const.VIDEO_COLOR_SPACE_DEFAULT,
            1: const.VIDEO_COLOR_SPACE_RGB,
            2: const.VIDEO_COLOR_SPACE_BT601,
            3: const.VIDEO_COLOR_SPACE_BT709,
            4: const.VIDEO_COLOR_SPACE_BT2020,
        },
        const.VIDEO_COLOR_DEPTH: {
            0: const.VIDEO_COLOR_DEPTH_UNKNOWN,
            24: const.VIDEO_COLOR_DEPTH_24BIT,
            30: const.VIDEO_COLOR_DEPTH_30BIT,
            36: const.VIDEO_COLOR_DEPTH_36BIT,
        },
        const.VIDEO_COLOR_SAMPLING: {
            0: const.VIDEO_COLOR_SAMPLING_NONE,
            1: const.VIDEO_COLOR_SAMPLING_RGB,
            2: const.VIDEO_COLOR_SAMPLING_YCBCR422,
            3: const.VIDEO_COLOR_SAMPLING_YCBCR444,
            4: const.VIDEO_COLOR_SAMPLING_YCBCR420,
        },
    }

    @property
    def field_eotf(self) -> str:
        """Returns eotf."""
        return self.index[const.VIDEO_COLOR_EOTF][int(self._fields[0])]

    @property
    def field_space(self) -> str:
        """Returns space."""
        return self.index[const.VIDEO_COLOR_SPACE][int(self._fields[1])]

    @property
    def field_depth(self) -> str:
        """Returns depth."""
        return self.index[const.VIDEO_COLOR_DEPTH][int(self._fields[2])]

    @property
    def field_sampling(self) -> str:
        """Returns sampling."""
        return self.index[const.VIDEO_COLOR_SAMPLING][int(self._fields[3])]


class GetVideoMode(Request):
    """Class for GET_VIDEO_MODE messages."""

    name = f"GET_{const.VIDEO_MODE}"


@register
class VideoMode(Response):
    """Class for VIDEO_MODE messages."""

    name = const.VIDEO_MODE
    index = {
        0: const.VIDEO_MODE_NONE,
        1: const.VIDEO_MODE_480I60_4X3,
        2: const.VIDEO_MODE_480I60_16X9,
        3: const.VIDEO_MODE_480P60_4X3,
        4: const.VIDEO_MODE_480P60_16X9,
        5: const.VIDEO_MODE_576I50_4X3,
        6: const.VIDEO_MODE_576I50_16X9,
        7: const.VIDEO_MODE_576P50_4X3,
        8: const.VIDEO_MODE_576P50_16X9,
        9: const.VIDEO_MODE_720P60_NTSC_HD,
        10: const.VIDEO_MODE_720P50_PAL_HD,
        11: const.VIDEO_MODE_1080I60_16X9,
        12: const.VIDEO_MODE_1080I50_16X9,
        13: const.VIDEO_MODE_1080P60_16X9,
        14: const.VIDEO_MODE_1080P50_16X9,
        17: const.VIDEO_MODE_1080P24_16X9,
        19: const.VIDEO_MODE_480I60_64X27,
        20: const.VIDEO_MODE_576I50_64X27,
        21: const.VIDEO_MODE_1080I60_64X27,
        22: const.VIDEO_MODE_1080I50_64X27,
        23: const.VIDEO_MODE_1080P60_64X27,
        24: const.VIDEO_MODE_1080P50_64X27,
        25: const.VIDEO_MODE_1080P23976_64X27,
        26: const.VIDEO_MODE_1080P24_64X27,
        27: const.VIDEO_MODE_3840X2160P23976_16X9,
        28: const.VIDEO_MODE_3840X2160P23976_64X27,
        29: const.VIDEO_MODE_3840X2160P30_16X9,
        30: const.VIDEO_MODE_3840X2160P30_64X27,
        31: const.VIDEO_MODE_3840X2160P60_16X9,
        32: const.VIDEO_MODE_3840X2160P60_64X27,
        33: const.VIDEO_MODE_3840X2160P25_16X9,
        34: const.VIDEO_MODE_3840X2160P25_64X27,
        35: const.VIDEO_MODE_3840X2160P50_16X9,
        36: const.VIDEO_MODE_3840X2160P50_64X27,
        37: const.VIDEO_MODE_3840X2160P24_16X9,
        38: const.VIDEO_MODE_3840X2160P24_64X27,
    }

    @property
    def field(self) -> str:
        """Returns video mode."""
        return self.index[int(self._fields[2])]


class GetScreenMask(Request):
    """Class for GET_SCREEN_MASK messages."""

    name = f"GET_{const.SCREEN_MASK}"


@register
class ScreenMask(Response):
    """Class for SCREEN_MASK messages."""

    name = const.SCREEN_MASK
    index = {
        0: const.SCREEN_MASK_ASPECT_RATIO_NONE,
        1: const.SCREEN_MASK_ASPECT_RATIO_133,
        2: const.SCREEN_MASK_ASPECT_RATIO_166,
        3: const.SCREEN_MASK_ASPECT_RATIO_178,
        4: const.SCREEN_MASK_ASPECT_RATIO_185,
        5: const.SCREEN_MASK_ASPECT_RATIO_235,
    }

    @property
    def field_image_ratio(self) -> str:
        """Returns image ratio."""
        return self.index[int(self._fields[0])]

    @property
    def field_top_trim_rel(self) -> int:
        """Returns top trim rel."""
        return int(self._fields[1])

    @property
    def field_bottom_trim_rel(self) -> int:
        """Returns bottom trim rel."""
        return int(self._fields[2])

    @property
    def field_conservative_ratio(self) -> str:
        """Returns conservative ratio."""
        return self.index[int(self._fields[3])]

    @property
    def field_top_mask_abs(self) -> int:
        """Returns top mask abs."""
        return int(self._fields[4])

    @property
    def field_bottom_mask_abs(self) -> int:
        """Returns bottom mask abs."""
        return int(self._fields[5])


class GetScreenMask2(Request):
    """Class for GET_SCREEN_MASK2 messages."""

    name = f"GET_{const.SCREEN_MASK2}"


@register
class ScreenMask2(Response):
    """Class for SCREEN_MASK2 messages."""

    name = const.SCREEN_MASK2

    @property
    def field_top_mask_abs(self) -> int:
        """Returns top mask abs."""
        return int(self._fields[0])

    @property
    def field_bottom_mask_abs(self) -> int:
        """Returns bottom mask abs."""
        return int(self._fields[1])

    @property
    def field_top_calibrated(self) -> int:
        """Returns top calibrated."""
        return int(self._fields[2])

    @property
    def field_bottom_calibrated(self) -> int:
        """Returns bottom calibrated."""
        return int(self._fields[3])


class GetCinemascapeMode(Request):
    """Class for GET_CINEMASCAPE_MODE messages."""

    name = f"GET_{const.CINEMASCAPE_MODE}"


@register
class CinemascapeMode(Response):
    """Class for CINEMASCAPE_MODE messages."""

    name = const.CINEMASCAPE_MODE
    index = {
        0: const.CINEMASCAPE_MODE_NONE,
        1: const.CINEMASCAPE_MODE_ANAMORPHIC,
        2: const.CINEMASCAPE_MODE_LETTERBOX,
        3: const.CINEMASCAPE_MODE_NATIVE,
    }

    @property
    def field(self) -> str:
        """Returns cinemascape mode."""
        return self.index[int(self._fields[0])]


class GetCinemascapeMask(Request):
    """Class for GET_CINEMASCAPE_MASK messages."""

    name = f"GET_{const.CINEMASCAPE_MASK}"


@register
class CinemascapeMask(Response):
    """Class for CINEMASCAPE_MASK messages."""

    name = const.CINEMASCAPE_MASK

    @property
    def field(self) -> int:
        """Returns cinemascape mask."""
        return int(self._fields[0])


class EnableEvents(Request):
    """Class for ENABLE_EVENTS messages."""

    name = const.ENABLE_EVENTS


class LeaveStandby(Request):
    """Class for LEAVE_STANDBY messages."""

    name = const.LEAVE_STANDBY


class EnterStandby(Request):
    """Class for ENTER_STANDBY messages."""

    name = const.ENTER_STANDBY


class Play(Request):
    """Class for PLAY messages."""

    name = const.PLAY


class Pause(Request):
    """Class for PAUSE messages."""

    name = const.PAUSE


class Stop(Request):
    """Class for STOP messages."""

    name = const.STOP


class Next(Request):
    """Class for NEXT messages."""

    name = const.NEXT


class Previous(Request):
    """Class for PREVIOUS messages."""

    name = const.PREVIOUS


class Replay(Request):
    """Class for REPLAY messages."""

    name = const.REPLAY


class ScanForward(Request):
    """Class for SCAN_FORWARD messages."""

    name = const.SCAN_FORWARD


class ScanReverse(Request):
    """Class for SCAN_REVERSE messages."""

    name = const.SCAN_REVERSE


class Select(Request):
    """Class for SELECT messages."""

    name = const.SELECT


class Up(Request):
    """Class for UP messages."""

    name = const.UP


class Down(Request):
    """Class for DOWN messages."""

    name = const.DOWN


class Left(Request):
    """Class for LEFT messages."""

    name = const.LEFT


class Right(Request):
    """Class for RIGHT messages."""

    name = const.RIGHT


class Cancel(Request):
    """Class for CANCEL messages."""

    name = const.CANCEL


class GoMovieCovers(Request):
    """Class for GO_MOVIE_LIST messages."""

    name = const.GO_MOVIE_COVERS


class MenuToggle(Request):
    """Class for KALEIDESCAPE_MENU_TOGGLE messages."""

    name = const.KALEIDESCAPE_MENU_TOGGLE
