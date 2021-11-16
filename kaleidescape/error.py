"""Custom errors."""
from __future__ import annotations

import asyncio

from . import const

DEFAULT_MESSAGES = {
    asyncio.TimeoutError: "Command timed out",
    ConnectionError: "Connection error",
    BrokenPipeError: "Broken pipe",
    ConnectionAbortedError: "Connection aborted",
    ConnectionRefusedError: "Connection refused",
    ConnectionResetError: "Connection reset",
    OSError: "OS I/O error",
}


def format_error(err: Exception | asyncio.TimeoutError) -> str:
    """Formats error message based on a base error."""
    msg: str | None = str(err)
    if msg == "":
        msg = DEFAULT_MESSAGES.get(type(err))
    return msg if msg else ""


class KaleidescapeError(Exception):
    """Kaleidescape errors."""


class SystemNotFoundError(Exception):
    """Error finding system."""


class MessageError(KaleidescapeError, RuntimeError):
    """Errors from the Kaleidescape Control Protocol."""

    def __init__(self, code: int, message: str = None):
        self.code = code
        self.error = const.RESPONSE_ERROR[code]
        super().__init__(self.error + (f" for command '{message}'" if message else ""))


class MessageParseError(KaleidescapeError, ValueError):
    """Errors parsing Kaleidescape Control Protocol messages."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.error = const.RESPONSE_ERROR[code]
        super().__init__(self.error + (f" for command '{message}'" if message else ""))
