"""A python client library for controlling Kaleidescape devices via the Kaleidescape
Control Protocol."""

from . import const
from .device import Device
from .dispatcher import Dispatcher
from .kaleidescape import Kaleidescape

__version__ = "2021.11.0"
