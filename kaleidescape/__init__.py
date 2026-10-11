"""A python client library for controlling Kaleidescape devices via the Kaleidescape
Control Protocol."""

from . import const
from ._version import __version__
from .device import Device
from .dispatcher import Dispatcher
from .error import KaleidescapeError

__all__ = ["Device", "Dispatcher", "KaleidescapeError", "__version__", "const"]
