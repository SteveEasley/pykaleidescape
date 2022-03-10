"""A python client library for controlling Kaleidescape devices via the Kaleidescape
Control Protocol."""

from . import const
from .device import Device
from .dispatcher import Dispatcher
from .error import KaleidescapeError

__version__ = "1.0.1"
