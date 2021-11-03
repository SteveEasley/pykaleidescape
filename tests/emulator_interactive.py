"""Interactive Kaleidescape Control Protocol emulator used for integration testing."""

from __future__ import annotations

import asyncio
import getopt
import json
import logging
import os.path
import signal
import sys

import aioconsole

from kaleidescape import const, error, message
from kaleidescape.connection import SEPARATOR
from kaleidescape.const import LOCAL_CPDID, SUCCESS
from kaleidescape.message import MessageParser

_LOGGER = logging.getLogger(__name__)

# pylint: disable=missing-function-docstring, invalid-name, no-self-use, line-too-long
# fmt: off


# Returns the inverse of map
def xo(val: dict[int, str]) -> dict[str, int]:
    return {v: k for k, v in val.items()}


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
        seq: int,
        status: int,
        name: str = None,
        fields: list[str] = None,
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

    def __init__(self, source_device_ids: list[str], status: int, name: str, fields: list = None) -> None:
        super().__init__(None, -1, status, name, fields)
        self.source_device_ids = source_device_ids


class Client:
    """Class representing a connection to Emulator."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._subscribed_device_ids = [LOCAL_CPDID]

    def subscribe(self, device_id):
        if device_id not in self._subscribed_device_ids:
            self._subscribed_device_ids.append(device_id)

    def unsubscribe(self, device_id):
        if device_id in self._subscribed_device_ids:
            self._subscribed_device_ids.remove(device_id)

    async def disconnect(self):
        self._reader.feed_eof()
        self._writer.close()

    async def _write(self, payload: str):
        data = (payload + SEPARATOR).encode("latin-1")
        self._writer.write(data)
        await self._writer.drain()

    async def send(self, msg: str | Response | Event):
        if isinstance(msg, Event):
            for device_id in self._subscribed_device_ids:
                if device_id in msg.source_device_ids:
                    msg.device_id = device_id
                    await self._write(str(msg))
                    _LOGGER.debug("> %s", str(msg))
        elif isinstance(msg, Response):
            await self._write(str(msg))
            _LOGGER.debug("> %s", str(msg))
        else:
            await self._write(msg)
            _LOGGER.debug("> %s", msg)


class State:
    """Class representing the state of a Device."""

    def __init__(self, device: Device, state: dict) -> None:
        self._device = device
        self._cpdid = state["cpdid"]
        self._serial_number = state["serial_number"]
        self._ip_address = state["ip_address"]
        self._movie_zones = state["movie_zones"]
        self._music_zones = state["music_zones"]
        self._type_name = state["type_name"]
        self._protocol_version = state["protocol_version"]
        self._kos_version = state["kos_version"]
        self._friendly_name = state["friendly_name"]
        self._cinemascape_mode = state["cinemascape_mode"]
        self._power_state = (
            state["_power_state"]
            if "_power_state" in state
            else xo(message.DevicePowerState.index["power"])["standby"]
        )
        self._readiness_state = (
            state["_readiness_state"]
            if "_readiness_state" in state
            else xo(message.SystemReadinessState.index)["idle"]
        )
        self._highlighted_selection = state["_highlighted_selection"] if "_highlighted_selection" in state else ""
        self._movie_media_type = (
            state["_movie_media_type"] if "_movie_media_type" in state else xo(message.MovieMediaType.index)["none"]
        )
        self._movie_title_name = state["_movie_title_name"] if "_movie_title_name" in state else ""
        self._movie_location = (
            state["_movie_location"] if "_movie_location" in state else xo(message.MovieLocation.index)["none"]
        )

        self.movies: dict[str, dict] = {}

        self._ui_state = (
            state["_ui_state"]
            if "_ui_state" in state
            else {
                "screen": xo(message.UiState.index["screen"])["unknown"],
                "popup": xo(message.UiState.index["popup"])["none"],
                "dialog": xo(message.UiState.index["dialog"])["none"],
                "saver": xo(message.UiState.index["saver"])["inactive"],
            }
        )

        self._movie_play_status = (
            state["_movie_play_status"]
            if "_movie_play_status" in state
            else {
                "mode": xo(message.PlayStatus.index)["none"],
                "speed": 0,
                "title_num": 0,
                "title_length": 0,
                "title_loc": 0,
                "chap_num": 0,
                "chap_length": 0,
                "chap_loc": 0,
            }
        )

        self.video_mode = state["_video_mode"] if "_video_mode" in state else xo(message.VideoMode.index)["none"]

        self._video_color = (
            state["_video_color"]
            if "_video_color" in state
            else {
                "eotf": xo(message.VideoColor.index["eotf"])["sdr"],
                "space": xo(message.VideoColor.index["space"])["default"],
                "depth": xo(message.VideoColor.index["depth"])["unknown"],
                "sampling": xo(message.VideoColor.index["sampling"])["none"],
            }
        )

        self._screen_mask = (
            state["_screen_mask"]
            if "_screen_mask" in state
            else {
                "image_ratio": xo(message.ScreenMask.index)["1.78"],
                "top_trim_rel": 0,
                "bottom_trim_rel": 0,
                "conservative_ratio": 0,
                "top_mask_abs": 0,
                "bottom_mask_abs": 0,
            }
        )

        self._screen_mask2 = (
            state["_screen_mask2"]
            if "_screen_mask2" in state
            else {
                "top_mask_abs": 0,
                "bottom_mask_abs": 0,
                "top_calibrated": 0,
                "bottom_calibrated": 0,
            }
        )

    async def _send_event(self, *msg):
        await self._device.send_event(*msg)

    def _create_work(self, *tasks):
        async def work():
            for task in tasks:
                await task

        asyncio.create_task(work())

    @property
    def cpdid(self) -> str:
        return self._cpdid

    @cpdid.setter
    def cpdid(self, value: str):
        assert isinstance(value, str)
        assert value != "01"
        self._cpdid = value

    def get_assigned_cpdid(self) -> str:
        return self.cpdid

    async def set_assigned_cpdid(self, value: str):
        self.cpdid = value
        await self.send_available_devices()

    @property
    def serial_number(self) -> str:
        return self._serial_number

    @serial_number.setter
    def serial_number(self, value: str):
        assert value and value[0] != "#"
        self._serial_number = f"{value:0>12}"

    def get_serial_number(self) -> str:
        return self.serial_number

    async def set_serial_number(self, value: str):
        self.serial_number = value
        await self.send_available_devices_by_serial_number()

    @property
    def ip_address(self) -> str:
        return self._ip_address

    @ip_address.setter
    def ip_address(self, value: str):
        assert value
        self._ip_address = str(value)

    def get_device_info(self):
        return [
            "99",
            self.serial_number,
            self.cpdid if self.cpdid else "00",
            self.ip_address,
        ]

    @property
    def movie_zones(self) -> int:
        return self._movie_zones

    @movie_zones.setter
    def movie_zones(self, value: int):
        assert int(value) in range(0, 2)
        self._movie_zones = int(value)

    @property
    def music_zones(self) -> int:
        return self._music_zones

    @music_zones.setter
    def music_zones(self, value: int):
        assert int(value) in range(0, 5)
        self._music_zones = int(value)

    def get_num_zones(self):
        return [self.movie_zones, self.music_zones]

    @property
    def type_name(self) -> str:
        return self._type_name

    @type_name.setter
    def type_name(self, value: str):
        assert value
        self._type_name = str(value)

    def get_device_type_name(self):
        return self.type_name

    @property
    def protocol_version(self) -> int:
        return self._protocol_version

    @protocol_version.setter
    def protocol_version(self, value: int):
        assert value
        self._protocol_version = int(value)

    @property
    def kos_version(self) -> str:
        return self._kos_version

    @kos_version.setter
    def kos_version(self, value: str):
        assert value
        self._kos_version = str(value)

    def get_system_version(self):
        return [self.protocol_version, self.kos_version]

    @property
    def friendly_name(self) -> str:
        return self._friendly_name

    @friendly_name.setter
    def friendly_name(self, value: str):
        assert value
        self._friendly_name = str(value)

    def get_friendly_name(self) -> str:
        return self.friendly_name

    async def set_friendly_name(self, value: str):
        self.friendly_name = value
        msg = await self._device.GET_FRIENDLY_NAME(self.get_friendly_name())
        await self._send_event(*msg)

    @property
    def cinemascape_mode(self) -> int:
        return self._cinemascape_mode

    @cinemascape_mode.setter
    def cinemascape_mode(self, value: int):
        assert int(value) in range(0, 4)
        self._cinemascape_mode = int(value)

    def get_cinemascape_mode(self) -> int:
        return self.cinemascape_mode

    async def set_cinemascape_mode(self, value: int):
        self.cinemascape_mode = value
        msg = await self._device.GET_CINEMASCAPE_MODE(self.get_cinemascape_mode())
        await self._send_event(*msg)

    @property
    def power_state(self) -> int:
        return self._power_state

    @power_state.setter
    def power_state(self, value: int):
        assert int(value) in range(0, 2)
        self._power_state = int(value)

    def get_device_power_state(self) -> int:
        return self.power_state

    async def set_power_state(self, value: int):
        self.power_state = value
        msg = await self._device.GET_DEVICE_POWER_STATE(self.get_device_power_state())
        await self._send_event(*msg)

    @property
    def readiness_state(self) -> int:
        return self._readiness_state

    @readiness_state.setter
    def readiness_state(self, value: int):
        assert int(value) in range(0, 3)
        self._readiness_state = int(value)

    def get_system_readiness_state(self) -> int:
        return self.readiness_state

    async def set_readiness_state(self, value: int):
        self.readiness_state = value
        msg = await self._device.GET_SYSTEM_READINESS_STATE(self.get_system_readiness_state())
        await self._send_event(*msg)

    @property
    def highlighted_selection(self) -> str:
        return self._highlighted_selection

    @highlighted_selection.setter
    def highlighted_selection(self, value: str):
        self._highlighted_selection = str(value) if value else ""

    def get_highlighted_selection(self, privileged: bool = False):
        if not privileged and self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)
        return self.highlighted_selection

    async def set_highlighted_selection(self, value: str):
        self.highlighted_selection = value
        msg = await self._device.GET_HIGHLIGHTED_SELECTION(self.get_highlighted_selection(True))
        await self._send_event(*msg)

    @property
    def movie_media_type(self) -> int:
        return self._movie_media_type

    @movie_media_type.setter
    def movie_media_type(self, value: int):
        assert int(value) in range(0, 4)
        self._movie_media_type = int(value)

    def get_movie_media_type(self, privileged: bool = False) -> int:
        if not privileged and self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)
        return self.movie_media_type

    async def set_movie_media_type(self, value: int):
        self.movie_media_type = value
        msg = await self._device.GET_MOVIE_MEDIA_TYPE(self.get_movie_media_type(True))
        await self._send_event(*msg)

    @property
    def movie_location(self) -> int:
        return self._movie_location

    @movie_location.setter
    def movie_location(self, value: int):
        assert int(value) in range(0, 7)
        self._movie_location = int(value)

    def get_movie_location(self, privileged: bool = False) -> int:
        if not privileged and self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)
        return self.movie_location

    async def set_movie_location(self, value: int):
        self.movie_location = value
        msg = await self._device.GET_MOVIE_LOCATION(self.get_movie_location(True))
        await self._send_event(*msg)

    @property
    def movie_title_name(self) -> str:
        return self._movie_title_name

    @movie_title_name.setter
    def movie_title_name(self, value: str):
        self._movie_title_name = str(value) if value else ""

    def get_movie_title_name(self, privileged: bool = False) -> list[str]:
        if not privileged and self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)
        return [self.movie_title_name]

    async def set_movie_title_name(self, value: str):
        self.movie_title_name = value
        msg = await self._device.GET_PLAYING_TITLE_NAME(self.get_movie_title_name(True))
        await self._send_event(*msg)

    @property
    def video_mode(self) -> int:
        return self._video_mode

    @video_mode.setter
    def video_mode(self, value: int):
        assert int(value) in range(0, 39)
        self._video_mode = int(value)

    def get_video_mode(self) -> list[int]:
        return [0, 0, self.video_mode]

    async def set_video_mode(self, value: int):
        self.video_mode = value
        msg = await self._device.GET_VIDEO_MODE(self.get_video_mode())
        await self._send_event(*msg)

    @property
    def video_color(self) -> dict[str, int]:
        return self._video_color

    @video_color.setter
    def video_color(self, value: dict[str, int]):
        assert value["eotf"] in range(0, 4)
        assert value["space"] in range(0, 5)
        assert value["depth"] in [0, 24, 30, 36]
        assert value["sampling"] in range(0, 5)
        self._video_color = value

    def get_video_color(self) -> list[int]:
        return list(self.video_color.values())

    async def set_video_color(self, value: dict[str, int]):
        self.video_color.update(value)
        msg = await self._device.GET_VIDEO_COLOR(self.get_video_color())
        await self._send_event(*msg)

    @property
    def screen_mask(self) -> dict[str, str | int]:
        return self._screen_mask

    @screen_mask.setter
    def screen_mask(self, value: dict[str, str | int]):
        assert value["image_ratio"] in range(0, 6)
        assert isinstance(value["top_trim_rel"], int)
        assert isinstance(value["bottom_trim_rel"], int)
        assert isinstance(value["conservative_ratio"], int)
        assert isinstance(value["top_mask_abs"], int)
        assert isinstance(value["bottom_mask_abs"], int)
        self._screen_mask = value

    def get_screen_mask(self) -> list[int]:
        return list(self.screen_mask.values())

    async def set_screen_mask(self, value: dict[str, str | int]):
        self.screen_mask.update(value)
        msg = await self._device.GET_SCREEN_MASK(self.get_screen_mask())
        await self._send_event(*msg)

    @property
    def screen_mask2(self) -> dict[str, int]:
        return self._screen_mask2

    @screen_mask2.setter
    def screen_mask2(self, value: dict[str, int]):
        assert isinstance(value["top_mask_abs"], int)
        assert isinstance(value["bottom_mask_abs"], int)
        assert isinstance(value["top_calibrated"], int)
        assert isinstance(value["bottom_calibrated"], int)
        self._screen_mask2 = value

    def get_screen_mask2(self) -> list[int]:
        return list(self.screen_mask2.values())

    async def set_screen_mask2(self, value: dict[str, int]):
        self.screen_mask2.update(value)
        msg = await self._device.GET_SCREEN_MASK2(self.get_screen_mask2())
        await self._send_event(*msg)

    @property
    def ui_state(self) -> dict[str, int]:
        return self._ui_state

    @ui_state.setter
    def ui_state(self, value: dict[str, int]):
        self._ui_state = value

    def get_ui_state(self, privileged: bool = False) -> list[int]:
        if not privileged and self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)
        return list(self.ui_state.values())

    async def set_ui_state(self, value: dict[str, int]):
        self.ui_state.update(value)
        msg = await self._device.GET_UI_STATE(self.get_ui_state(True))
        await self._send_event(*msg)

    @property
    def movie_play_status(self) -> dict[str, int]:
        return self._movie_play_status

    @movie_play_status.setter
    def movie_play_status(self, value: dict[str, int]):
        self._movie_play_status = value

    def get_movie_play_status(self, privileged: bool = False) -> list[int]:
        if not privileged and self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)
        return list(self.movie_play_status.values())

    async def set_movie_play_status(self, value: dict[str, int]):
        self.movie_play_status.update(value)
        msg = await self._device.GET_PLAY_STATUS(self.get_movie_play_status(True))
        await self._send_event(*msg)

    def _assert_in_standby(self):
        assert self.power_state == xo(message.DevicePowerState.index["power"])["standby"]
        assert self.movie_play_status["mode"] == xo(message.PlayStatus.index)["none"]
        assert self.movie_title_name == ""
        assert self.movie_media_type == xo(message.MovieMediaType.index)["none"]
        assert self.movie_location == xo(message.MovieLocation.index)["none"]
        assert self.video_mode == xo(message.VideoMode.index)["none"]
        assert self.video_color["eotf"] == xo(message.VideoColor.index["eotf"])["sdr"]
        assert self.video_color["space"] == xo(message.VideoColor.index["space"])["default"]
        assert self.video_color["depth"] == xo(message.VideoColor.index["depth"])["unknown"]
        assert self.video_color["sampling"] == xo(message.VideoColor.index["sampling"])["none"]
        assert self.ui_state["screen"] == xo(message.UiState.index["screen"])["unknown"]
        assert self.ui_state["popup"] == xo(message.UiState.index["popup"])["none"]
        assert self.ui_state["dialog"] == xo(message.UiState.index["dialog"])["none"]
        assert self.ui_state["saver"] == xo(message.UiState.index["saver"])["inactive"]

    async def _async_assert_in_standby(self):
        self._assert_in_standby()

    def _assert_movie_playing(self):
        assert self.power_state == xo(message.DevicePowerState.index["power"])["on"]
        assert self.readiness_state == xo(message.SystemReadinessState.index)["ready"]
        assert self.movie_play_status["mode"] in [
            xo(message.PlayStatus.index)["playing"],
            xo(message.PlayStatus.index)["forward"],
            xo(message.PlayStatus.index)["reverse"],
        ]
        assert self.movie_title_name != ""
        assert self.movie_media_type == xo(message.MovieMediaType.index)["stream"]
        assert self.movie_location == xo(message.MovieLocation.index)["content"]
        assert self.video_mode != xo(message.VideoMode.index)["none"]
        assert self.video_color["eotf"] != xo(message.VideoColor.index["eotf"])["unknown"]
        assert self.video_color["space"] != xo(message.VideoColor.index["space"])["default"]
        assert self.video_color["depth"] != xo(message.VideoColor.index["depth"])["unknown"]
        assert self.video_color["sampling"] != xo(message.VideoColor.index["sampling"])["none"]
        assert self.highlighted_selection != ""
        assert self.ui_state["screen"] == xo(message.UiState.index["screen"])["playing_movie"]
        assert self.ui_state["popup"] == xo(message.UiState.index["popup"])["none"]
        assert self.ui_state["dialog"] == xo(message.UiState.index["dialog"])["none"]
        assert self.ui_state["saver"] == xo(message.UiState.index["saver"])["inactive"]

    async def _async_assert_movie_playing(self):
        self._assert_movie_playing()

    def _assert_showing_menu(self):
        assert self.power_state == xo(message.DevicePowerState.index["power"])["on"]
        assert self.readiness_state == xo(message.SystemReadinessState.index)["ready"]
        assert self.movie_play_status["mode"] == xo(message.PlayStatus.index)["none"]
        assert self.movie_title_name == ""
        assert self.movie_media_type == xo(message.MovieMediaType.index)["none"]
        assert self.movie_location == xo(message.MovieLocation.index)["none"]
        assert self.video_mode != xo(message.VideoMode.index)["none"]
        assert self.video_color["eotf"] == xo(message.VideoColor.index["eotf"])["sdr"]
        assert self.video_color["space"] == xo(message.VideoColor.index["space"])["default"]
        assert self.video_color["depth"] == xo(message.VideoColor.index["depth"])["24bit"]
        assert self.video_color["sampling"] == xo(message.VideoColor.index["sampling"])["ycbcr444"]
        assert self.ui_state["screen"] == xo(message.UiState.index["screen"])["movie_covers"]
        assert self.ui_state["popup"] == xo(message.UiState.index["popup"])["none"]
        assert self.ui_state["dialog"] == xo(message.UiState.index["dialog"])["none"]
        assert self.ui_state["saver"] == xo(message.UiState.index["saver"])["inactive"]

    async def _async_assert_showing_menu(self):
        self._assert_showing_menu()

    async def send_available_devices(self):
        msg = await self._device.GET_AVAILABLE_DEVICES()
        await self._send_event(*msg)

    async def send_available_devices_by_serial_number(self):
        msg = await self._device.GET_AVAILABLE_DEVICES_BY_SERIAL_NUMBER()
        await self._send_event(*msg)

    async def sleep(self, delay: float):
        await asyncio.sleep(delay)

    def load_movies(self, movies: list[dict[str, str]]):
        self.movies.clear()
        for movie in movies:
            self.movies[movie["Content_handle"]] = movie

    def _get_movie(self, handle):
        if handle not in self.movies:
            raise error.MessageError(const.ERROR_INVALID_CONTENT_HANDLE)
        return self.movies[handle]

    async def leave_standby(self):
        if self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            self._create_work(
                self.set_power_state(xo(message.DevicePowerState.index["power"])["on"]),
                self.set_readiness_state(xo(message.SystemReadinessState.index)["becoming_ready"]),
                self.set_ui_state({"screen": xo(message.UiState.index["screen"])["movie_covers"]}),
                self.set_video_mode(xo(message.VideoMode.index)["3840x2160p60_16:9"]),
                self.set_video_color(
                    {
                        "eotf": xo(message.VideoColor.index["eotf"])["sdr"],
                        "space": xo(message.VideoColor.index["space"])["default"],
                        "depth": xo(message.VideoColor.index["depth"])["24bit"],
                        "sampling": xo(message.VideoColor.index["sampling"])["ycbcr444"],
                    }
                ),
                self.set_screen_mask(
                    {
                        "image_ratio": xo(message.ScreenMask.index)["1.78"],
                        "top_trim_rel": 0,
                        "bottom_trim_rel": 0,
                        "conservative_ratio": 0,
                        "top_mask_abs": 0,
                        "bottom_mask_abs": 0,
                    }
                ),
                self.set_screen_mask2(
                    {
                        "top_mask_abs": 0,
                        "bottom_mask_abs": 0,
                        "top_calibrated": 0,
                        "bottom_calibrated": 0,
                    }
                ),
                self.sleep(0.01),
                self.set_readiness_state(xo(message.SystemReadinessState.index)["ready"]),
                self._async_assert_showing_menu(),
            )

    async def enter_standby(self):
        if self.power_state == xo(message.DevicePowerState.index["power"])["on"]:
            self._create_work(
                self.set_power_state(xo(message.DevicePowerState.index["power"])["standby"]),
                self.set_readiness_state(xo(message.SystemReadinessState.index)["idle"]),
                self.sleep(0),
                self.set_video_mode(xo(message.VideoMode.index)["none"]),
                self.set_video_color(
                    {
                        "eotf": xo(message.VideoColor.index["eotf"])["sdr"],
                        "space": xo(message.VideoColor.index["space"])["default"],
                        "depth": xo(message.VideoColor.index["depth"])["unknown"],
                        "sampling": xo(message.VideoColor.index["sampling"])["none"],
                    }
                ),
                self.set_highlighted_selection(""),
                self.set_ui_state(
                    {
                        "screen": xo(message.UiState.index["screen"])["unknown"],
                        "popup": xo(message.UiState.index["popup"])["none"],
                        "dialog": xo(message.UiState.index["dialog"])["none"],
                        "saver": xo(message.UiState.index["saver"])["inactive"],
                    }
                ),
                self.sleep(0.25),  # Sleep to ensure playing media sees ui_state change
                self._async_assert_in_standby(),
            )

    async def play(self, handle: str = None):
        if self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)

        if self.movie_play_status["mode"] == xo(message.PlayStatus.index)["playing"]:
            self._assert_movie_playing()
            return
        if self.movie_play_status["mode"] == xo(message.PlayStatus.index)["paused"]:
            await self.unpause()
            return
        if self.movie_play_status["mode"] == xo(message.PlayStatus.index)["none"]:
            self._assert_showing_menu()

        if not handle:
            handle = self.get_highlighted_selection()
            if not handle:
                await self.set_highlighted_selection(list(self.movies.keys())[0])
                handle = self.get_highlighted_selection()

        movie = self._get_movie(handle)

        self._create_work(
            self.set_ui_state({"screen": xo(message.UiState.index["screen"])["playing_movie"]}),
            self.set_movie_media_type(movie["_media_type"]),
            self.set_movie_title_name(movie["Title"]),
            self.set_movie_location(xo(message.MovieLocation.index)["content"]),
            self.sleep(0),
            self.set_video_mode(movie["_video_mode"]),
            self.set_video_color(movie["_video_color"].copy()),
            self._play_movie(handle),
        )

    async def pause(self):
        if self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)

        is_playing = [
            xo(message.PlayStatus.index)["playing"],
            xo(message.PlayStatus.index)["forward"],
            xo(message.PlayStatus.index)["reverse"],
        ]

        if self.movie_play_status["mode"] not in is_playing:
            self._assert_showing_menu()
            return

        self._assert_movie_playing()

        self._create_work(self.set_movie_play_status({"mode": xo(message.PlayStatus.index)["paused"]}))

    async def unpause(self):
        if self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)

        if self.movie_play_status["mode"] != xo(message.PlayStatus.index)["paused"]:
            self._assert_showing_menu()
            return

        self._create_work(self.set_movie_play_status({"mode": xo(message.PlayStatus.index)["playing"]}))

    async def stop(self):
        if self.power_state == xo(message.DevicePowerState.index["power"])["standby"]:
            raise error.MessageError(const.ERROR_DEVICE_IN_STANDBY)

        if self.movie_play_status["mode"] == xo(message.PlayStatus.index)["none"]:
            self._assert_showing_menu()
            return

        self._create_work(self.set_ui_state({"screen": xo(message.UiState.index["screen"])["movie_covers"]}))

    async def _play_movie(self, handle: str):
        movie = self._get_movie(handle)
        status = self.movie_play_status

        await self.sleep(0.5)

        await self.set_movie_play_status(
            {
                "mode": xo(message.PlayStatus.index)["playing"],
                "speed": 0,
                "title_num": 1,
                "title_length": int(movie["Running_time"]),
                "title_loc": 0,
            }
        )

        await self.set_screen_mask(movie["_screen_mask"].copy())
        await self.set_screen_mask2(movie["_screen_mask2"].copy())

        self._assert_movie_playing()

        is_playing = [
            xo(message.PlayStatus.index)["playing"],
            xo(message.PlayStatus.index)["forward"],
            xo(message.PlayStatus.index)["reverse"],
        ]

        while (
            status["title_loc"] < status["title_length"]
            and self.ui_state["screen"] == xo(message.UiState.index["screen"])["playing_movie"]
        ):
            if status["mode"] in is_playing:
                if (
                    status["title_loc"] >= movie["_time_credits"]
                    and self.movie_location != xo(message.MovieLocation.index)["credits"]
                ):
                    await self.set_movie_location(xo(message.MovieLocation.index)["credits"])
                status["title_loc"] = status["title_loc"] + 1 + (status["speed"] * 1)
                await self.sleep(1)
            elif status["mode"] == xo(message.PlayStatus.index)["paused"]:
                await self.sleep(0)

        if self.ui_state["screen"] != xo(message.UiState.index["screen"])["movie_covers"]:
            await self.set_ui_state({"screen": xo(message.UiState.index["screen"])["movie_covers"]})

        await self.set_movie_media_type(xo(message.MovieMediaType.index)["none"])
        await self.set_movie_title_name("")
        await self.set_movie_play_status({"mode": xo(message.PlayStatus.index)["paused"]})
        await self.set_movie_location(xo(message.MovieLocation.index)["none"])
        await self.set_movie_play_status(
            {
                "mode": xo(message.PlayStatus.index)["none"],
                "speed": 0,
                "title_num": 0,
                "title_length": 0,
                "title_loc": 0,
                "chap_num": 0,
                "chap_length": 0,
                "chap_loc": 0,
            }
        )
        await self.set_video_mode(xo(message.VideoMode.index)["3840x2160p60_16:9"])
        await self.set_video_color(
            {
                "eotf": xo(message.VideoColor.index["eotf"])["sdr"],
                "space": xo(message.VideoColor.index["space"])["default"],
                "depth": xo(message.VideoColor.index["depth"])["24bit"],
                "sampling": xo(message.VideoColor.index["sampling"])["ycbcr444"],
            }
        )
        self._assert_showing_menu()

    def get_content_details(self, handle: str) -> tuple:
        movie = self._get_movie(handle)
        details = [[k, v] for k, v in movie.items() if k[0] != "_"]
        return len(details), details

    def refresh_available_devices(self):
        self._create_work(
            self.send_available_devices(),
            self.send_available_devices_by_serial_number(),
        )


class Device:
    """Class representing a Kaleidescape device."""

    def __init__(self, emu: Emulator) -> None:
        self.emulator = emu
        self.state: State | None = None
        self._enabled = True
        self._connected = True

    @property
    def is_local(self) -> bool:
        return self.emulator.local_device == self

    @property
    def normalized_serial_number(self) -> str:
        return self.emulator.normalize_serial_number(self.state.serial_number)

    @property
    def cpdid(self) -> str:
        return self.state.cpdid

    @property
    def serial_number(self) -> str:
        return self.state.serial_number

    @property
    def device_ids(self) -> list[str]:
        local_cpdid = LOCAL_CPDID if self.is_local else None
        return list(filter(None, [local_cpdid, self.cpdid, self.normalized_serial_number]))

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        if not self.is_local:
            self._enabled = value

    @property
    def connected(self) -> bool:
        return self._connected

    @connected.setter
    def connected(self, value: bool):
        if not self.is_local:
            self._connected = value

    async def send_event(self, status: int, name: str, fields: list = None):
        await self.emulator.send_event(self.device_ids, status, name, fields)

    # pylint: disable=unused-argument

    async def ENABLE_EVENTS(self, request: Request, client: Client):
        if len(request.fields) != 1:
            raise error.MessageError(const.ERROR_INVALID_NUMBER_PARAMETERS, request.message)
        device, device_id = self.emulator.get_matching_device(request.fields[0])
        if not device:
            raise error.MessageError(const.ERROR_INVALID_DEVICE, request.message)
        client.subscribe(device_id)
        return SUCCESS

    async def DISABLE_EVENTS(self, request: Request, client: Client):
        if len(request.fields) != 1:
            raise error.MessageError(const.ERROR_INVALID_NUMBER_PARAMETERS, request.message)
        device, device_id = self.emulator.get_matching_device(request.fields[0])
        if not device:
            raise error.MessageError(const.ERROR_INVALID_DEVICE, request.message)
        client.unsubscribe(device_id)
        return SUCCESS

    # noinspection PyUnusedLocal
    async def LEAVE_STANDBY(self, *args, **kwargs):
        await self.state.leave_standby()
        return SUCCESS

    # noinspection PyUnusedLocal
    async def ENTER_STANDBY(self, *args, **kwargs):
        await self.state.enter_standby()
        return SUCCESS

    # noinspection PyUnusedLocal
    async def PLAY(self, *args, **kwargs):
        await self.state.play()
        return SUCCESS

    # noinspection PyUnusedLocal
    async def PAUSE(self, *args, **kwargs):
        await self.state.pause()
        return SUCCESS

    # noinspection PyUnusedLocal
    async def PAUSE_ON(self, *args, **kwargs):
        await self.state.pause()
        return SUCCESS

    # noinspection PyUnusedLocal
    async def PAUSE_OFF(self, *args, **kwargs):
        await self.state.unpause()
        return SUCCESS

    # noinspection PyUnusedLocal
    async def STOP(self, *args, **kwargs):
        await self.state.stop()
        return SUCCESS

    # noinspection PyUnusedLocal
    async def GET_AVAILABLE_DEVICES(self, *args, **kwargs):
        fields = [LOCAL_CPDID] if self.is_local else []
        fields = fields + [d.cpdid for d in self.emulator.devices if d.cpdid]
        return SUCCESS, "AVAILABLE_DEVICES", fields

    # noinspection PyUnusedLocal
    async def GET_AVAILABLE_DEVICES_BY_SERIAL_NUMBER(self, *args, **kwargs):
        fields = [d.serial_number for d in self.emulator.devices]
        return SUCCESS, "AVAILABLE_DEVICES_BY_SERIAL_NUMBER", fields

    # noinspection PyUnusedLocal
    async def GET_SYSTEM_VERSION(self, *args, **kwargs):
        fields = self.state.get_system_version()
        return SUCCESS, "SYSTEM_VERSION", fields

    # noinspection PyUnusedLocal
    async def GET_DEVICE_INFO(self, *args, **kwargs):
        fields = self.state.get_device_info()
        return SUCCESS, "DEVICE_INFO", fields

    # noinspection PyUnusedLocal
    async def GET_ZONE_CAPABILITIES(self, *args, **kwargs):
        fields = self.state.get_num_zones()
        return (
            SUCCESS,
            "ZONE_CAPABILITIES",
            ["Y", "Y", "N", "Y"],
        )

    # noinspection PyUnusedLocal
    async def GET_NUM_ZONES(self, *args, **kwargs):
        fields = self.state.get_num_zones()
        return (
            SUCCESS,
            "NUM_ZONES",
            [
                f"{fields[0]:02}",
                f"{fields[1]:02}",
            ],
        )

    # noinspection PyUnusedLocal
    async def GET_DEVICE_TYPE_NAME(self, *args, **kwargs):
        fields = self.state.get_device_type_name()
        return SUCCESS, "DEVICE_TYPE_NAME", [fields]

    # noinspection PyUnusedLocal
    async def GET_FRIENDLY_NAME(self, *args, **kwargs):
        field = args[0] if len(args) > 0 else self.state.get_friendly_name()
        return SUCCESS, "FRIENDLY_NAME", [field]

    # noinspection PyUnusedLocal
    async def GET_DEVICE_POWER_STATE(self, *args, **kwargs):
        field = args[0] if len(args) > 0 else self.state.get_device_power_state()
        return SUCCESS, "DEVICE_POWER_STATE", [field, "1"]

    # noinspection PyUnusedLocal
    async def GET_SYSTEM_READINESS_STATE(self, *args, **kwargs):
        field = args[0] if len(args) > 0 else self.state.get_system_readiness_state()
        return SUCCESS, "SYSTEM_READINESS_STATE", [field]

    # noinspection PyUnusedLocal
    async def GET_PLAY_STATUS(self, *args, **kwargs):
        fields = args[0] if len(args) > 0 else self.state.get_movie_play_status()
        return (
            SUCCESS,
            "PLAY_STATUS",
            [
                str(fields[0]),
                str(fields[1]),
                f"{fields[2]:02}",
                f"{fields[3]:05}",
                f"{fields[4]:05}",
                f"{fields[5]:02}",
                f"{fields[6]:05}",
                f"{fields[7]:05}",
            ],
        )

    # noinspection PyUnusedLocal
    async def GET_PLAYING_TITLE_NAME(self, *args, **kwargs):
        field = args[0] if len(args) > 0 else self.state.get_movie_title_name()
        return SUCCESS, "TITLE_NAME", field

    # noinspection PyUnusedLocal
    async def GET_HIGHLIGHTED_SELECTION(self, *args, **kwargs):
        field = args[0] if len(args) > 0 else self.state.get_highlighted_selection()
        return SUCCESS, "HIGHLIGHTED_SELECTION", [field]

    # noinspection PyUnusedLocal
    async def GET_MOVIE_LOCATION(self, *args, **kwargs):
        field = args[0] if len(args) > 0 else self.state.get_movie_location()
        field = f"{field:02}"
        return SUCCESS, "MOVIE_LOCATION", [field]

    # noinspection PyUnusedLocal
    async def GET_MOVIE_MEDIA_TYPE(self, *args, **kwargs):
        field = args[0] if len(args) > 0 else self.state.get_movie_media_type()
        field = f"{field:02}"
        return SUCCESS, "MOVIE_MEDIA_TYPE", [field]

    # noinspection PyUnusedLocal
    async def GET_CONTENT_DETAILS(self, request: Request, **kwargs):
        if len(request.fields) != 2:
            raise error.MessageError(const.ERROR_INVALID_NUMBER_PARAMETERS, request.message)
        handle = request.fields[0]
        count, content = self.state.get_content_details(handle)
        fields = [(SUCCESS, "CONTENT_DETAILS_OVERVIEW", [count, handle, "movies"])]
        return fields + [(SUCCESS, "CONTENT_DETAILS", [i + 1] + c) for i, c in enumerate(content)]

    # noinspection PyUnusedLocal
    async def GET_UI_STATE(self, *args, **kwargs):
        fields = args[0] if len(args) > 0 else self.state.get_ui_state()
        return (
            SUCCESS,
            "UI_STATE",
            [
                f"{fields[0]:02}",
                f"{fields[1]:02}",
                f"{fields[2]:02}",
                str(fields[3]),
            ],
        )

    # noinspection PyUnusedLocal
    async def GET_VIDEO_COLOR(self, *args, **kwargs):
        fields = args[0] if len(args) > 0 else self.state.get_video_color()
        return (
            SUCCESS,
            "VIDEO_COLOR",
            [
                f"{fields[0]:02}",
                f"{fields[1]:02}",
                f"{fields[2]:02}",
                f"{fields[3]:02}",
            ],
        )

    # noinspection PyUnusedLocal
    async def GET_VIDEO_MODE(self, *args, **kwargs):
        fields = args[0] if len(args) > 0 else self.state.get_video_mode()
        return (
            SUCCESS,
            "VIDEO_MODE",
            [
                f"{fields[0]:02}",
                f"{fields[1]:02}",
                f"{fields[2]:02}",
            ],
        )

    # noinspection PyUnusedLocal
    async def GET_SCREEN_MASK(self, *args, **kwargs):
        fields = args[0] if len(args) > 0 else self.state.get_screen_mask()
        return (
            SUCCESS,
            "SCREEN_MASK",
            [
                f"{fields[0]:02}",
                f"{fields[1]:{'04' if fields[1] < 0 else '03'}}",
                f"{fields[2]:{'04' if fields[2] < 0 else '03'}}",
                f"{fields[3]:02}",
                f"{fields[4]:{'05' if fields[4] < 0 else '04'}}",
                f"{fields[5]:{'05' if fields[5] < 0 else '04'}}",
            ],
        )

    # noinspection PyUnusedLocal
    async def GET_SCREEN_MASK2(self, *args, **kwargs):
        fields = args[0] if len(args) > 0 else self.state.get_screen_mask2()
        return (
            SUCCESS,
            "SCREEN_MASK2",
            [
                f"{fields[0]:{'05' if fields[0] < 0 else '04'}}",
                f"{fields[1]:{'05' if fields[1] < 0 else '04'}}",
                f"{fields[2]:{'06' if fields[2] < 0 else '05'}}",
                f"{fields[3]:{'06' if fields[3] < 0 else '05'}}",
            ],
        )

    # noinspection PyUnusedLocal
    async def GET_CINEMASCAPE_MODE(self, *args, **kwargs):
        field = args[0] if len(args) > 0 else self.state.get_cinemascape_mode()
        return SUCCESS, "CINEMASCAPE_MODE", [field]


class Emulator:
    """Class for emulating a Kaleidescape system."""

    def __init__(self, fixture: str, host: str, port: int = const.DEFAULT_CONNECT_PORT):
        """Initialize the emulator."""
        self._host = host
        self._port = port
        self._devices: list[Device] = []
        self._clients: list[Client] = []
        self._server: asyncio.base_events.Server | None = None
        self._mock_commands: dict[str, tuple[int, str, list]] = {}

        if not os.path.isfile(fixture):
            if os.path.isfile(f"tests/fixtures/{fixture}.json"):
                fixture = f"tests/fixtures/{fixture}.json"

        device = Device(self)

        with open(fixture, encoding="utf8") as file:
            fixture = json.load(file)

        device.state = State(device, fixture["devices"]["members"][0])

        with open("tests/fixtures/movies.json", encoding="utf8") as file:
            device.state.load_movies(json.load(file))

        self._devices.append(device)

        for state in fixture["devices"]["members"][1:]:
            d = Device(self)
            d.state = State(d, state)
            d.state.movies = device.state.movies
            self._devices.append(d)

    async def start(self):
        """Starts the emulator."""
        if self._server:
            raise Exception("Already started")
        self._server = await asyncio.start_server(self._connection_handler, self._host, self._port)
        _LOGGER.debug("Started")

    async def stop(self):
        """Stops the emulator."""
        if self._server is None:
            return
        for client in self._clients:
            await client.disconnect()
        self._clients.clear()
        self._devices.clear()
        self._server.close()
        await self._server.wait_closed()
        # Ensure sleep in self::_connection_handler() finishes
        await asyncio.sleep(0.01)
        self._server = None
        _LOGGER.debug("Stopped")

    @property
    def devices(self) -> list[Device]:
        """Returns all devices in system."""
        return [d for d in self._devices if d.enabled]

    @property
    def local_device(self) -> Device:
        """Returns the local device."""
        return self._devices[0]

    def register_mock_command(self, name: str, msg: tuple[int, str, list] | tuple[int, str]):
        """Adds a new simulated command to server. Overrides built in commands."""
        self._mock_commands[name] = msg

    async def _connection_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Main service loop for handling client connections."""
        client = Client(reader, writer)
        if self.local_device.cpdid:
            client.unsubscribe(LOCAL_CPDID)
            client.subscribe(self.local_device.cpdid)
        self._clients.append(client)
        _LOGGER.debug("Client connected")

        while True:
            request = None
            try:
                result = await reader.readuntil()
                result = result.decode("latin-1").strip()
                if not result:
                    continue

                _LOGGER.debug("< %s", result)

                request = Request(result)

                device, device_id = self.get_matching_device(request.device_id)
                if not device:
                    raise error.MessageError(const.ERROR_INVALID_DEVICE, request.message)
                request.device_id = device_id

                # Simulated case of child device disconnected
                if not device.connected:
                    raise error.MessageError(const.ERROR_DEVICE_UNAVAILABLE, request.message)

                if request.name in self._mock_commands:
                    msgs = self._mock_commands[request.name]
                elif hasattr(device, request.name):
                    msgs = await getattr(device, request.name)(request=request, client=client)
                else:
                    raise error.MessageError(const.ERROR_INVALID_REQUEST, request.message)

                if isinstance(msgs, int):
                    msgs = [(msgs,)]
                elif isinstance(msgs, tuple):
                    msgs = [msgs]
                for msg in msgs:
                    await client.send(Response(request.device_id, request.seq, *msg))

                await asyncio.sleep(0.001)

            except asyncio.IncompleteReadError:
                # Occurs when the reader is being stopped
                break
            except (error.MessageError, error.MessageParseError) as e:
                device_id = request.device_id if request else "??"
                seq = request.seq if request else "?"
                response = Response(device_id, seq, e.code, e.error)
                await client.send(response)

        try:
            self._clients.remove(client)
            _LOGGER.debug("Client disconnected")
        except ValueError:
            pass

    def get_matching_device(self, device_id: str, disabled=False) -> tuple[Device, str]:
        device_id = self.normalize_device_id(device_id)
        for device in self.devices if not disabled else self._devices:
            for did in device.device_ids:
                if did == device_id:
                    return device, did
        return None, None

    def normalize_device_id(self, device_id) -> str:
        """Returns device_id.

        If the device has a cpdid assigned, that is returned.
        Otherwise serialize number is returned in normalized format."""
        if device_id[0] == "#":
            return self.normalize_serial_number(device_id)
        return device_id

    def normalize_serial_number(self, serial_number: str) -> str:
        """Returns serial number formatted in the pound prefixed, 12 digit format."""
        return f"#{serial_number.lstrip('#0'):0>12}"

    async def send_event(self, device_ids: list[str], status: int, name: str, fields: list = None):
        """Sends an event message to device_ids."""
        event = Event(device_ids, status, name, fields)
        for client in self._clients:
            await client.send(event)

    def disable_device(self, device_id: str) -> None:
        """Simulates device being removed from system."""
        device, device_id = self.get_matching_device(device_id, True)
        if not device:
            raise error.MessageError(const.ERROR_INVALID_DEVICE, device_id)
        device.enabled = False
        self.local_device.state.refresh_available_devices()

    def reenable_device(self, device_id: str) -> None:
        """Simulates device being re-added to system."""
        device, device_id = self.get_matching_device(device_id, True)
        if not device:
            raise error.MessageError(const.ERROR_INVALID_DEVICE, device_id)
        device.enabled = True
        self.local_device.state.refresh_available_devices()

    def disconnect_device(self, device_id: str) -> None:
        """Simulates device becoming unavailable, but still in device list."""
        device, device_id = self.get_matching_device(device_id, True)
        if not device:
            raise error.MessageError(const.ERROR_INVALID_DEVICE, device_id)
        device.connected = False

    def reconnect_device(self, device_id: str) -> None:
        """Simulates device becoming available again."""
        device, device_id = self.get_matching_device(device_id, True)
        if not device:
            raise error.MessageError(const.ERROR_INVALID_DEVICE, device_id)
        device.connected = True

    def change_cpdid(self, device_id: str, cpdid: str):
        """Simulates a device having its cpdid changed."""
        device, device_id = self.get_matching_device(device_id, True)
        if not device:
            raise error.MessageError(const.ERROR_INVALID_DEVICE, device_id)
        device.state.cpdid = cpdid
        self.local_device.state.refresh_available_devices()


class Shell:
    """Shell for interacting with command line invoked emulator."""

    def __init__(self, emulator: Emulator):
        """Initialize shell."""
        self._emulator = emulator
        self._running = True

    async def start(self):
        print(f"Listening on port {const.DEFAULT_CONNECT_PORT}")
        print("Type `help` for commands.")
        while self._running:
            cmd = await aioconsole.ainput("> ")
            args = cmd.strip().split(" ")
            cmd = args[0]
            if cmd:
                try:
                    await getattr(self, f"do_{cmd}")(*args[1:])
                except Exception as err:  # pylint: disable=broad-except
                    print(err)

    async def do_disable_device(self, *args):
        """disable_device {device_id}"""
        self._emulator.disable_device(*args)
        print("done")

    async def do_reenable_device(self, *args):
        """reenable_device {device_id}"""
        self._emulator.reenable_device(*args)
        print("done")

    async def do_disconnect_device(self, *args):
        """disconnect_device {device_id}"""
        self._emulator.disconnect_device(*args)
        print("done")

    async def do_reconnect_device(self, *args):
        """reconnect_device {device_id}"""
        self._emulator.reconnect_device(*args)
        print("done")

    async def do_change_cpdid(self, *args):
        """change_cpdid {device_id} {cpdid}"""
        self._emulator.change_cpdid(*args)
        print("done")

    async def do_help(self):
        """help"""
        print(self.do_disable_device.__doc__)
        print(self.do_reenable_device.__doc__)
        print(self.do_disconnect_device.__doc__)
        print(self.do_reconnect_device.__doc__)
        print(self.do_change_cpdid.__doc__)
        print(self.do_help.__doc__)


def main(argv):
    fixture = None

    def usage():
        print("Usage: python -m tests.emulator -h -f <filename>")
        print("    -h Help")
        print("    -f Fixture filename (from tests/fixtures)")

    try:
        opts, _ = getopt.getopt(argv, "hf:")
    except getopt.GetoptError:
        usage()
        sys.exit(2)
    for opt, arg in opts:
        if opt == "-h":
            usage()
            sys.exit()
        elif opt in "-f":
            fixture = arg

    if not os.path.isfile(fixture):
        print("Error: fixture not found")
        sys.exit()

    loop = asyncio.get_event_loop()

    async def stop():
        loop.stop()

    def shutdown():
        for task in asyncio.all_tasks():
            task.cancel()
        asyncio.create_task(stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    logging.basicConfig(level=logging.DEBUG)

    emulator = Emulator(fixture, "127.0.0.1")
    shell = Shell(emulator)

    loop.run_until_complete(emulator.start())
    asyncio.ensure_future(shell.start(), loop=loop)
    loop.run_forever()
    loop.run_until_complete(emulator.stop())
    loop.close()


if __name__ == "__main__":
    main(sys.argv[1:])
