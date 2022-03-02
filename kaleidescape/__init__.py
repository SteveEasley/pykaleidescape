"""A python client library for controlling Kaleidescape devices via the Kaleidescape
Control Protocol."""

from . import const
from .device import Device
from .error import KaleidescapeError
from .dispatcher import Dispatcher

__version__ = "2022.2.2"
