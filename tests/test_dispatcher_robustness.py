"""Callback failure and task lifetime regression tests."""

import asyncio
import logging

import pytest

from kaleidescape.dispatcher import Dispatcher


@pytest.mark.asyncio
async def test_callback_errors_are_logged_and_tasks_retained(caplog):
    """Both synchronous and asynchronous callback failures are reported."""
    dispatcher = Dispatcher()
    started = asyncio.Event()
    release = asyncio.Event()

    async def async_callback():
        started.set()
        await release.wait()
        raise ValueError("async failure")

    def sync_callback():
        raise ValueError("sync failure")

    dispatcher.connect(async_callback)
    dispatcher.connect(sync_callback)
    with caplog.at_level(logging.ERROR):
        dispatcher.send()
        await started.wait()
        assert len(dispatcher._tasks) == 1  # pylint: disable=protected-access
        release.set()
        await asyncio.gather(*dispatcher._tasks)  # pylint: disable=protected-access
    assert "sync failure" in caplog.text
    assert "async failure" in caplog.text
    assert "Traceback" in caplog.text
