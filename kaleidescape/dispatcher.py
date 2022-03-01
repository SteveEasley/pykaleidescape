"""Classes for dispatching events"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)


class Signal:
    """Container for a named target function that receives events"""

    def __init__(self, dispatcher: Dispatcher, target: Callable):
        """Initialize signal."""
        self.dispatcher = dispatcher
        self.target = target

    def disconnect(self) -> None:
        """Removes signal from the dispatcher."""
        self.dispatcher.disconnect(self)


class Dispatcher:
    """Handle event dispatching."""

    def __init__(self):
        """Initialize dispatcher."""
        self._signals: list[Signal] = []
        self._loop = asyncio.get_event_loop()
        self._disconnects = []

    def connect(self, target: Callable) -> Signal:
        """Return a new signal that runs the target function."""
        signal = Signal(self, target)
        self._signals.append(signal)
        return signal

    def send(self, *args: Any) -> None:
        """Call named signal's target function with args."""
        for signal in self._signals:
            self._call_target(signal.target, *args)
        if len(self._signals) > 0:
            _LOGGER.debug(
                "Dispatched signal to %s listener%s with %s",
                len(self._signals),
                "s" if len(self._signals) > 1 else "",
                args,
            )

    def disconnect(self, signal: Signal):
        """Removes signal."""
        try:
            self._signals.remove(signal)
        except ValueError:
            pass

    def disconnect_all(self) -> None:
        """Disconnect all signals."""
        self._signals.clear()

    def _call_target(self, target: Callable, *args) -> Awaitable:
        check_target = target
        while isinstance(check_target, functools.partial):
            check_target = check_target.func
        if asyncio.iscoroutinefunction(check_target):
            return self._loop.create_task(target(*args))
        return self._loop.run_in_executor(None, target, *args)
