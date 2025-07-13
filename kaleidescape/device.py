"""Classes providing virtualized access to hardware devices."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, cast

from . import const
from . import message as messages
from .connection import EVENT_CONNECTION_MESSAGE, SIGNAL_CONNECTION_EVENT
from .const import LOCAL_CPDID
from .error import KaleidescapeError, MessageError

if TYPE_CHECKING:
    from .connection import Connection
    from .dispatcher import Dispatcher, Signal
    from .kaleidescape import Kaleidescape, SystemInfo
    from .message import Request, Response

    RequestType = TypeVar("RequestType", bound=Request)


class Device:
    """Class representing a hardware device.

    Provides commands for changing the state of the device. Also handles mirroring
    device state by monitoring system events.
    """

    def __init__(
        self, kaleidescape: Kaleidescape, device_id: str = LOCAL_CPDID
    ) -> None:
        """Initializes device."""
        self._connection = kaleidescape.connection
        self._dispatcher = kaleidescape.dispatcher
        self._device_id = device_id

        self.system = System()
        self.power = Power()
        self.osd = OSD()
        self.movie = Movie()
        self.automation = Automation()

        # self._device_id will ALWAYS be the local device id (01) for the the local
        # device, or the #serialnumber for all other devices.
        if device_id == LOCAL_CPDID:
            pass
        elif device_id[0] == "#":
            self.system.serial_number = device_id[1:]
        else:
            raise KaleidescapeError("Invalid device_id: " + device_id)

        self._signal: Signal | None = None
        self._disabled: bool = True
        self.enable()

    @property
    def connection(self) -> Connection:
        """Returns connection instance."""
        return self._connection

    @property
    def dispatcher(self) -> Dispatcher:
        """Returns dispatcher instance."""
        return self._dispatcher

    @property
    def disabled(self) -> bool:
        """Returns disabled state for the device."""
        return self._disabled

    @property
    def is_local(self) -> bool:
        """Returns if this device is the local one.

        The local device is the device being directly communicated with over the TCP/IP
        network. Hardware devices that are not the local device are communicated with
        via command routing through this device.
        """
        return self._device_id == LOCAL_CPDID

    @property
    def device_id(self) -> str:
        """Returns logical controller device identifier."""
        return self._device_id

    @property
    def cpdid(self) -> str:
        """Returns hardware assigned device cpdid.

        Default is None unless the user has assigned one in the Kaleidescape
        configuration.
        """
        return self.system.cpdid

    @property
    def serial_number(self) -> str:
        """Returns hardware device's serial number."""
        return self.system.serial_number

    @property
    def is_connected(self) -> bool:
        """Returns current state of the connection."""
        return (
            self._connection.state == const.STATE_CONNECTED and self._disabled is False
        )

    @property
    def is_server_only(self) -> bool:
        """Returns if device has no movie zone (Terra, 1U, 3U, etc)."""
        return self.system.movie_zones == 0

    @property
    def is_movie_player(self) -> bool:
        """Returns if device has a movie zone."""
        return self.system.movie_zones > 0

    @property
    def is_music_player(self) -> bool:
        """Returns if device has a music zone."""
        return self.system.music_zones - self.system.movie_zones > 0

    def has_device_id(self, device_id: str) -> bool:
        """Returns if this device has device_id."""
        return device_id in list(
            filter(None, [self._device_id, f"#{self.serial_number}", self.cpdid])
        )

    def enable(self) -> None:
        """Enables device, allowing it to send commands and receive events."""
        if not self._disabled:
            return
        self._disabled = False
        self._signal = self._dispatcher.connect(
            SIGNAL_CONNECTION_EVENT, self._handle_event
        )

    def disable(self) -> None:
        """Disables device, preventing it from sending commands and receiving events.

        Devices are marked as disabled by the controller.
        """
        if self._disabled or self.is_local:
            return
        self._disabled = True
        self.close()
        self.power.state = const.DEVICE_POWER_STATE_STANDBY
        self.power.readiness = const.SYSTEM_READINESS_STATE_IDLE

    def close(self) -> None:
        """Closes device resources."""
        if self._signal:
            self._signal.disconnect()
            self._signal = None

    async def get_system_pairing_info(self) -> messages.SystemPairingInfo:
        """Returns a list the serial numbers in the system."""
        res = await self._send(messages.GetSystemPairingInfo)
        return cast(messages.SystemPairingInfo, res)

    async def get_friendly_system_name(self) -> str:
        """Returns friendly system name."""
        res = await self._send(messages.GetFriendlySystemName)
        return cast(messages.FriendlySystemName, res).field

    async def get_available_serial_numbers(self) -> list[str]:
        """Returns a list the serial numbers in the system."""
        res = await self._send(messages.GetAvailableDevicesBySerialNumber)
        return (cast(messages.AvailableDevicesBySerialNumber, res)).field

    async def get_available_devices(self) -> list[str]:
        """Returns a list of cpdid's in the system that have cpdid's assigned."""
        res = await self._send(messages.GetAvailableDevices)
        return (cast(messages.AvailableDevices, res)).field

    async def enable_events(self, device_id: str) -> None:
        """Sends enable events command for device with id."""
        assert device_id != LOCAL_CPDID
        await self._send(messages.EnableEvents, 0, [device_id])

    async def leave_standby(self) -> None:
        """Sends leave standby command."""
        await self._send(messages.LeaveStandby)

    async def enter_standby(self) -> None:
        """Sends enter standby command."""
        await self._send(messages.EnterStandby)

    async def play(self) -> None:
        """Sends play command."""
        await self._send(messages.Play)

    async def pause(self) -> None:
        """Sends pause command."""
        await self._send(messages.Pause)

    async def stop(self) -> None:
        """Sends stop command."""
        await self._send(messages.Stop)

    async def enableVolumeControl(self) -> None:
        """Sends enable volume controls command."""
        await self._send(messages.VolumeCapabilities)

    async def refresh_device(self) -> None:
        """Syncs device state."""
        if self.disabled:
            raise MessageError(const.ERROR_DEVICE_UNAVAILABLE)

        result = iter(
            await asyncio.gather(
                self._get_device_info(),
                self._get_system_version(),
                self._get_device_type_name(),
                self._get_num_zones(),
                self._get_device_power_state(),
                self._get_system_readiness_state(),
            )
        )

        self._update_device_info(next(result))
        self._update_system_version(next(result))
        self._update_device_type_name(next(result))
        self._update_num_zones(next(result))
        self._update_device_power_state(next(result))
        self._update_system_readiness_state(next(result))

        if self.is_movie_player:
            # Server only devices don't support this call
            self._update_friendly_name(await self._get_friendly_name())

    async def refresh_state(self) -> None:
        """Syncs device state."""
        if self.disabled:
            raise MessageError(const.ERROR_DEVICE_UNAVAILABLE)

        if self.is_server_only or self.power.state != const.DEVICE_POWER_STATE_ON:
            return

        result = iter(
            await asyncio.gather(
                self._get_ui_state(),
                self._get_highlighted_selection(),
                self._get_play_status(),
                self._get_movie_location(),
                self._get_screen_mask(),
                self._get_screen_mask2(),
                self._get_cinemascape_mode(),
            )
        )

        self._update_ui_state(next(result))
        self._update_highlighted_selection(next(result))
        self._update_play_status(next(result))
        self._update_movie_location(next(result))
        self._update_screen_mask(next(result))
        self._update_screen_mask2(next(result))
        self._update_cinemascape_mode(next(result))

        if self.movie.play_status != const.PLAY_STATUS_NONE:
            res1 = await self.get_content_details(self.osd.highlighted)
            self._update_content_details(cast(messages.ContentDetailsOverview, res1))

        if self.automation.cinemascape_mode != const.CINEMASCAPE_MODE_NONE:
            res2 = await self._get_cinemascape_mask()
            self._update_cinemascape_mask(cast(messages.CinemascapeMask, res2))

    async def _get_device_info(self) -> messages.DeviceInfo:
        """Returns device info."""
        res = await self._send(messages.GetDeviceInfo)
        return cast(messages.DeviceInfo, res)

    def _update_device_info(self, res: messages.DeviceInfo) -> None:
        self.system.serial_number = res.field_serial_number
        self.system.cpdid = res.field_cpdid
        self.system.ip_address = res.field_ip

    async def _get_system_version(self) -> messages.SystemVersion:
        """Returns system version."""
        res = await self._send(messages.GetSystemVersion)
        return cast(messages.SystemVersion, res)

    def _update_system_version(self, res: messages.SystemVersion) -> None:
        self.system.protocol = res.field_protocol
        self.system.kos_version = res.field_kos

    async def _get_num_zones(self) -> messages.NumZones:
        """Returns number of zones."""
        res = await self._send(messages.GetNumZones)
        return cast(messages.NumZones, res)

    def _update_num_zones(self, res: messages.NumZones) -> None:
        self.system.movie_zones = res.field_movie_zones
        self.system.music_zones = res.field_music_zones

    async def _get_device_type_name(self) -> messages.DeviceTypeName:
        """Returns device type name."""
        res = await self._send(messages.GetDeviceTypeName)
        return cast(messages.DeviceTypeName, res)

    def _update_device_type_name(self, res: messages.DeviceTypeName) -> None:
        self.system.type = res.field

    async def _get_device_power_state(self) -> messages.DevicePowerState:
        """Returns power state."""
        res = await self._send(messages.GetDevicePowerState)
        return cast(messages.DevicePowerState, res)

    def _update_device_power_state(self, res: messages.DevicePowerState) -> None:
        self.power.state = res.field_power
        self.power.zone = res.field_zone

    async def _get_system_readiness_state(self) -> messages.SystemReadinessState:
        """Returns readiness state."""
        res = await self._send(messages.GetSystemReadinessState)
        return cast(messages.SystemReadinessState, res)

    def _update_system_readiness_state(
        self, res: messages.SystemReadinessState
    ) -> None:
        self.power.readiness = res.field

    async def _get_friendly_name(self) -> messages.FriendlyName:
        """Returns friendly name."""
        res = await self._send(messages.GetFriendlyName)
        return cast(messages.FriendlyName, res)

    def _update_friendly_name(self, res: messages.FriendlyName) -> None:
        self.system.friendly_name = res.field

    async def _get_ui_state(self) -> messages.UiState:
        """Returns ui state."""
        res = await self._send(messages.GetUiState)
        return cast(messages.UiState, res)

    def _update_ui_state(self, res: messages.UiState) -> None:
        self.osd.ui_screen = res.field_screen
        self.osd.ui_popup = res.field_popup
        self.osd.ui_dialog = res.field_dialog
        self.osd.ui_screensaver = res.field_screensaver

    async def _get_playing_title_name(self) -> messages.PlayingTitleName:
        """Returns playing title name."""
        res = await self._send(messages.GetPlayingTitleName)
        return cast(messages.PlayingTitleName, res)

    def _update_playing_title_name(self, res: messages.PlayingTitleName) -> None:
        self.osd.title_name = res.field

    async def _get_highlighted_selection(self) -> messages.HighlightedSelection:
        """Returns highlighted selection."""
        res = await self._send(messages.GetHighlightedSelection)
        return cast(messages.HighlightedSelection, res)

    def _update_highlighted_selection(self, res: messages.HighlightedSelection) -> None:
        self.osd.highlighted = res.field

    async def _get_play_status(self) -> messages.PlayStatus:
        """Returns play status."""
        res = await self._send(messages.GetPlayStatus)
        return cast(messages.PlayStatus, res)

    def _update_play_status(self, res: messages.PlayStatus) -> None:
        self.movie.play_status = res.field_play_status
        self.movie.play_speed = res.field_play_speed
        self.movie.title_number = res.field_title_number
        self.movie.title_length = res.field_title_length
        self.movie.title_location = res.field_title_location
        self.movie.chapter_number = res.field_chapter_number
        self.movie.chapter_length = res.field_chapter_length
        self.movie.chapter_location = res.field_chapter_location

    async def get_content_details(
        self, handle: str, passcode: str = None
    ) -> messages.ContentDetailsOverview:
        """Returns content details for the currently selected title."""
        responses: list[Response] = await self._send_multi(
            messages.GetContentDetails, 0, [handle, passcode if passcode else ""]
        )
        overview = cast(messages.ContentDetailsOverview, responses[0])
        for response in responses[1:]:
            overview.details.update(cast(messages.ContentDetails, response).field)
        return overview

    def _update_content_details(
        self, res: messages.ContentDetailsOverview = None
    ) -> None:
        self.movie.handle = res.field_handle if res else ""
        self.movie.title = res.field_title if res else ""
        self.movie.cover = res.field_cover_url if res else ""
        self.movie.cover_hires = res.field_hires_cover_url if res else ""
        self.movie.rating = res.field_rating if res else ""
        self.movie.rating_reason = res.field_rating_reason if res else ""
        self.movie.year = res.field_year if res else ""
        self.movie.runtime = res.field_running_time if res else "0"
        self.movie.actors = res.field_actors if res else []
        self.movie.director = res.field_director if res else ""
        self.movie.directors = res.field_directors if res else []
        self.movie.genre = res.field_genre if res else ""
        self.movie.genres = res.field_genres if res else []
        self.movie.synopsis = res.field_synopsis if res else ""
        self.movie.color = res.field_color_description if res else ""
        self.movie.country = res.field_country if res else ""
        self.movie.aspect_ratio = res.field_aspect_ratio if res else ""

    async def _get_movie_location(self) -> messages.GetMovieLocation:
        """Returns movie location."""
        res = await self._send(messages.GetMovieLocation)
        return cast(messages.GetMovieLocation, res)

    def _update_movie_location(self, res: messages.MovieLocation) -> None:
        self.automation.movie_location = res.field

    async def _get_movie_media_type(self) -> messages.MovieMediaType:
        """Returns movie media type."""
        res = await self._send(messages.GetMovieMediaType)
        return cast(messages.MovieMediaType, res)

    def _update_movie_media_type(self, res: messages.MovieMediaType) -> None:
        self.movie.media_type = res.field

    async def _get_video_color(self) -> messages.VideoColor:
        """Returns video color."""
        res = await self._send(messages.GetVideoColor)
        return cast(messages.VideoColor, res)

    def _update_video_color(self, res: messages.VideoColor) -> None:
        self.automation.video_color_eotf = res.field_eotf
        self.automation.video_color_space = res.field_space
        self.automation.video_color_depth = res.field_depth
        self.automation.video_color_sampling = res.field_sampling

    async def _get_video_mode(self) -> messages.VideoMode:
        """Returns video mode."""
        res = await self._send(messages.GetVideoMode)
        return cast(messages.VideoMode, res)

    def _update_video_mode(self, res: messages.VideoMode) -> None:
        self.automation.video_mode = res.field

    async def _get_screen_mask(self) -> messages.ScreenMask:
        """Returns screen mask."""
        res = await self._send(messages.GetScreenMask)
        return cast(messages.ScreenMask, res)

    def _update_screen_mask(self, res: messages.ScreenMask) -> None:
        self.automation.screen_mask_ratio = res.field_image_ratio
        self.automation.screen_mask_top_trim_rel = res.field_top_trim_rel
        self.automation.screen_mask_bottom_trim_rel = res.field_bottom_trim_rel
        self.automation.screen_mask_conservative_ratio = res.field_conservative_ratio
        self.automation.screen_mask_top_mask_abs = res.field_top_mask_abs
        self.automation.screen_mask_bottom_mask_abs = res.field_bottom_mask_abs

    async def _get_screen_mask2(self) -> messages.ScreenMask2:
        """Returns screen mask2."""
        res = await self._send(messages.GetScreenMask2)
        return cast(messages.ScreenMask2, res)

    def _update_screen_mask2(self, res: messages.ScreenMask2) -> None:
        self.automation.screen_mask2_top_mask_abs = res.field_top_mask_abs
        self.automation.screen_mask2_bottom_mask_abs = res.field_bottom_mask_abs
        self.automation.screen_mask2_top_calibrated = res.field_top_calibrated
        self.automation.screen_mask2_bottom_calibrated = res.field_bottom_calibrated

    async def _get_cinemascape_mode(self) -> messages.CinemascapeMode:
        """Returns cinemascape mode."""
        res = await self._send(messages.GetCinemascapeMode)
        return cast(messages.CinemascapeMode, res)

    def _update_cinemascape_mode(self, res: messages.CinemascapeMode) -> None:
        self.automation.cinemascape_mode = res.field

    async def _get_cinemascape_mask(self) -> messages.CinemascapeMask:
        """Returns cinemascape mask."""
        res = await self._send(messages.GetCinemascapeMask)
        return cast(messages.CinemascapeMask, res)

    def _update_cinemascape_mask(self, res: messages.CinemascapeMask) -> None:
        self.automation.cinemascape_mask = res.field

    async def _send(
        self, request: type[RequestType], zone: int = 0, fields: list[str] | None = None
    ) -> Response:
        """Sends request to hardware device, returning a single response."""
        res = await self._send_multi(request, zone, fields)
        assert len(res) == 1
        return res[0]

    async def _send_multi(
        self, request: type[RequestType], zone: int = 0, fields: list[str] | None = None
    ) -> list[Response]:
        """Sends request to hardware device, returning one or more responses."""
        req = request(self.device_id, zone, fields)
        return await req.send(self._connection)

    async def _handle_event(self, event: str, *args) -> None:
        """Handles events sent by the hardware device."""
        if self.disabled:
            return

        # Ignore connect and disconnect messages, those are handled by the controller.
        if event != EVENT_CONNECTION_MESSAGE:
            return

        response: Response = args[0]

        # Ignore events not addressed to this device
        if self.has_device_id(response.device_id) is False:
            return

        # System
        if isinstance(response, messages.DevicePowerState):
            self._update_device_power_state(response)
            await self.refresh_state()
        elif isinstance(response, messages.SystemReadinessState):
            self._update_system_readiness_state(response)
        elif isinstance(response, messages.FriendlyName):
            self._update_friendly_name(response)

        # OSD
        elif isinstance(response, messages.UiState):
            self._update_ui_state(response)
        elif isinstance(response, messages.PlayingTitleName):
            self._update_playing_title_name(response)
        elif isinstance(response, messages.HighlightedSelection):
            self._update_highlighted_selection(response)

        # Movie
        elif isinstance(response, messages.PlayStatus):
            old_mode = self.movie.play_status
            self._update_play_status(response)
            if (
                self.power.state == const.DEVICE_POWER_STATE_ON
                and self.movie.play_status != const.PLAY_STATUS_NONE
            ):
                if old_mode == const.PLAY_STATUS_NONE or old_mode is None:
                    res = await self.get_content_details(self.osd.highlighted)
                    self._update_content_details(
                        cast(messages.ContentDetailsOverview, res)
                    )
            elif self.movie.title:
                self._update_content_details()
        elif isinstance(response, messages.MovieMediaType):
            self._update_movie_media_type(response)

        # Automation
        elif isinstance(response, messages.MovieLocation):
            self._update_movie_location(response)
        elif isinstance(response, messages.VideoColor):
            self._update_video_color(response)
        elif isinstance(response, messages.VideoMode):
            self._update_video_mode(response)
        elif isinstance(response, messages.ScreenMask):
            self._update_screen_mask(response)
        elif isinstance(response, messages.ScreenMask2):
            self._update_screen_mask2(response)
        elif isinstance(response, messages.CinemascapeMode):
            self._update_cinemascape_mode(response)
        elif isinstance(response, messages.CinemascapeMask):
            self._update_cinemascape_mask(response)

        # User-defined events
        elif isinstance(response, messages.UserDefinedEvent):
            # User-defined event - dispatch with event type for better monitoring
            self._dispatcher.send(
                const.SIGNAL_DEVICE_EVENT, response.device_id, f"{response.name}:{response.event_type}"
            )
            return
        else:
            # Handle unregistered events - dispatch with raw data
            self._dispatcher.send(
                const.SIGNAL_DEVICE_EVENT, response.device_id, response.name, response
            )
            return

        self._dispatcher.send(
            const.SIGNAL_DEVICE_EVENT, response.device_id, response.name
        )


@dataclass
class System:
    """System related properties."""

    ip_address: str = ""
    serial_number: str = ""
    cpdid: str = ""
    type: str = ""
    protocol: int = 0
    kos_version: str = ""
    friendly_name: str = ""
    movie_zones: int = 0
    music_zones: int = 0


@dataclass
class Power:
    """Power related state."""

    state: str = ""
    readiness: str = ""
    zone: list[str] | None = None


@dataclass
class OSD:
    """On Screen Display related state."""

    ui_screen: str = const.UI_STATE_SCREEN_UNKNOWN
    ui_popup: str = const.UI_STATE_POPUP_NONE
    ui_dialog: str = const.UI_STATE_DIALOG_NONE
    ui_screensaver: str = const.UI_STATE_SAVER_INACTIVE
    title_name: str = ""
    highlighted: str = ""


@dataclass
class Movie:
    """Movie media related state."""

    handle: str = ""
    title: str = ""
    cover: str = ""
    cover_hires: str = ""
    rating: str = ""
    rating_reason: str = ""
    year: str = ""
    runtime: str = ""
    actors: list[str] | None = None
    director: str = ""
    directors: list[str] | None = None
    genre: str = ""
    genres: list[str] | None = None
    synopsis: str = ""
    color: str = ""
    country: str = ""
    aspect_ratio: str = ""
    media_type: str = const.MOVIE_MEDIA_TYPE_NONE
    play_status: str = const.PLAY_STATUS_NONE
    play_speed: int = 0
    title_number: int = 0
    title_length: int = 0
    title_location: int = 0
    chapter_number: int = 0
    chapter_length: int = 0
    chapter_location: int = 0


@dataclass
class Automation:
    """Automation related state."""

    movie_location: str = const.MOVIE_LOCATION_NONE
    cinemascape_mask: int = 0
    cinemascape_mode: str = const.CINEMASCAPE_MODE_NONE
    video_mode: str = const.VIDEO_MODE_NONE
    video_color_eotf: str = const.VIDEO_COLOR_EOTF_UNKNOWN
    video_color_space: str = const.VIDEO_COLOR_SPACE_DEFAULT
    video_color_depth: str = const.VIDEO_COLOR_DEPTH_UNKNOWN
    video_color_sampling: str = const.VIDEO_COLOR_SAMPLING_NONE
    screen_mask_ratio: str = const.SCREEN_MASK_ASPECT_RATIO_NONE
    screen_mask_top_trim_rel: int = 0
    screen_mask_bottom_trim_rel: int = 0
    screen_mask_conservative_ratio: str = ""
    screen_mask_top_mask_abs: int = 0
    screen_mask_bottom_mask_abs: int = 0
    screen_mask2_top_mask_abs: int = 0
    screen_mask2_bottom_mask_abs: int = 0
    screen_mask2_top_calibrated: int = 0
    screen_mask2_bottom_calibrated: int = 0
