"""Unit tests."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from kaleidescape import const
from kaleidescape.connection import SIGNAL_CONNECTION_EVENT
from kaleidescape.dispatcher import Dispatcher

_LOGGER = logging.getLogger(__name__)


def signal(dispatcher: Dispatcher, sig: str, target: Callable) -> asyncio.Event:
    """Returns an asyncio event that is triggered when event is emitted."""
    trigger = asyncio.Event()

    async def handler(*args):
        if target(*args):
            trigger.set()

    dispatcher.connect(sig, handler)

    return trigger


def controller_signal(dispatcher: Dispatcher, event: str) -> asyncio.Event:
    """Returns an asyncio event that is triggered when controller event is emitted."""
    return signal(
        dispatcher,
        const.SIGNAL_CONTROLLER_EVENT,
        lambda e: e == event,
    )


def device_signal(dispatcher: Dispatcher, device_id: str, event: str) -> asyncio.Event:
    """Returns an asyncio event that is triggered when device event is emitted."""
    return signal(
        dispatcher,
        const.SIGNAL_DEVICE_EVENT,
        lambda d, e: d == device_id and e == event,
    )


def connection_signal(dispatcher: Dispatcher, event: str) -> asyncio.Event:
    """Returns an asyncio event that is triggered when connection event is emitted."""
    return signal(
        dispatcher,
        SIGNAL_CONNECTION_EVENT,
        lambda e, *a: e == event,
    )
