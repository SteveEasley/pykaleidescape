"""A python client library for controlling Kaleidescape devices via the Kaleidescape
Control Protocol."""

from . import const
from ._version import __version__
from .device import Device
from .dispatcher import Dispatcher
from .error import KaleidescapeError, RequestNotSentError, RequestOutcomeUnknownError

__all__ = [
    "Device",
    "Dispatcher",
    "KaleidescapeError",
    "RequestNotSentError",
    "RequestOutcomeUnknownError",
    "__version__",
    "const",
]
