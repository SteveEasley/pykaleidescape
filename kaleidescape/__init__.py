"""A python client library for controlling Kaleidescape devices via the Kaleidescape
Control Protocol."""

__version__ = "1.1.7"

from . import const
from .device import Device
from .dispatcher import Dispatcher
from .error import KaleidescapeError

__all__ = ["Device", "Dispatcher", "KaleidescapeError", "const"]
