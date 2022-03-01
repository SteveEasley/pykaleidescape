"""Unit tests."""

from __future__ import annotations

import asyncio
import logging

from kaleidescape.dispatcher import Dispatcher

_LOGGER = logging.getLogger(__name__)


def create_signal(dispatcher: Dispatcher, target_event: str) -> asyncio.Event:
    """Returns an asyncio event that is triggered when event is emitted."""
    trigger = asyncio.Event()

    async def handler(event):
        if event == target_event:
            trigger.set()

    dispatcher.connect(handler)

    return trigger

