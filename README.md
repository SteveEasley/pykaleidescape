# pykaleidescape

[![Test](https://github.com/SteveEasley/pykaleidescape/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/SteveEasley/pykaleidescape/actions/workflows/ci.yml)

Async Python client for controlling Kaleidescape devices via the Kaleidescape System Control Protocol.

> Note: This library is not operated by, or affiliated with, Kaleidescape, Inc.

## Features

- Async API built on `asyncio`
- High-level `Device` abstraction for connecting to a Kaleidescape player
- Mirrors device state into convenient dataclasses (`system`, `power`, `osd`, `movie`, `automation`)
- Event-driven integration via a lightweight `Dispatcher`
- Automation integration using user-defined events

## Installation

```bash
pip install pykaleidescape
```

## Quickstart

This minimal example connects to a Kaleidescape player and prints its power state.
See the [Examples](#examples) section for more complete usage patterns.

```python
import asyncio
import logging

from kaleidescape import const, Device

logging.basicConfig(level=logging.DEBUG)

async def main() -> None:
    device = Device("<ipaddress>")

    # Open the connection and perform initial state sync
    await device.connect()
    await device.refresh()

    print(f"Power state is currently: {device.power.state}")


if __name__ == "__main__":
    asyncio.run(main())
```

All library calls that talk to the device are async and must be awaited inside an event loop.

## Examples

The `examples/` directory contains small, runnable scripts that demonstrate typical usage patterns.

- `examples/basic.py` – connect to a player, refresh state, and control power.
- `examples/events.py` – register an event listener with `device.dispatcher` and react to incoming events.
- `examples/volume.py` – implement external volume control by responding to Kaleidescape user-defined events.

## API overview

Most users will interact with the `Device` class and constants from `kaleidescape.const`.

```python
from kaleidescape import Device, const
```

### Device lifecycle

A `Device` represents a single Kaleidescape player and manages the underlying TCP connection.

- `Device(host, *, port=..., timeout=..., reconnect=True, reconnect_delay=...)`
  - Create a new client instance for the given `host`.
- `await device.connect()`
  - Resolve the host, open a TCP connection, and start the reader task.
- `await device.refresh()`
  - Perform an initial or on-demand state sync (system, power, UI, movie, automation).
- `await device.disconnect()`
  - Close the connection and stop reconnect behavior.
- `device.is_connected`
  - Boolean indicating whether the underlying connection is currently open.

### State dataclasses

After `connect()` and `refresh()`, the `Device` exposes several state objects that are kept up to date by incoming events:

- `device.system`
  - System-level information such as serial number, IP, CPDID, model, friendly name, number of zones, firmware/protocol versions.
- `device.power`
  - Power and readiness state, using constants from `kaleidescape.const` such as `DEVICE_POWER_STATE_ON` and `DEVICE_POWER_STATE_STANDBY`.
- `device.osd`
  - On-screen display state, including the current UI screen and highlighted item when available.
- `device.movie`
  - Movie playback state such as play status, current location, and content handle (when applicable).
- `device.automation`
  - Automation-centric fields (movie location, Cinemascape mode, mask information, etc.).

### Common commands

All commands are async methods on `Device` and must be awaited.

**Power**

- `await device.leave_standby()` – bring the player out of standby.
- `await device.enter_standby()` – put the player into standby.

**Transport** (availability may depend on the connected device)

- `await device.play()`
- `await device.pause()`
- `await device.stop()`
- `await device.next()`
- `await device.previous()`
- `await device.replay()`
- `await device.scan_forward()`
- `await device.scan_reverse()`

**Navigation & UI**

- `await device.select()`
- `await device.up()` / `await device.down()`
- `await device.left()` / `await device.right()`
- `await device.cancel()`
- `await device.go_movie_covers()`
- `await device.menu_toggle()`

**System info & content**

- `await device.get_system_pairing_info()` – retrieve pairing-related information.
- `await device.get_friendly_system_name()` – get the configured friendly name.
- `await device.get_available_devices()` – query other devices visible to this system.
- `await device.get_available_serial_numbers()` – query serial numbers of available devices.
- `await device.get_content_details(handle)` – fetch rich metadata for a specific content handle.

**Volume integration**

The library supports integration with an external volume / AVR by responding to Kaleidescape user-defined events.

- `await device.set_volume_capabilities(bitmask)` – advertise supported volume capabilities (see `kaleidescape.const` for bit flags).
- `await device.set_volume_level(level)` – report the current volume level.
- `await device.set_volume_muted(is_muted)` – report the current mute state.

See `examples/volume.py` for a complete flow.

### Events and dispatcher

The library is event-driven: incoming protocol messages are parsed into response objects and dispatched to subscribers.

- `device.dispatcher` is a `Dispatcher` instance.
- Register a callback with:

  ```python
  async def handle_event(event: str, *args) -> None:
      print("Event received:", event, args)

  device.dispatcher.connect(handle_event)
  ```

- Callbacks may be async or sync callables.
- Events include power changes, system readiness updates, UI state changes, user-defined events (for volume integration), and more.

## Async usage

pykaleidescape is built on `asyncio`.

- Use `asyncio.run(main())` for simple scripts.
- In larger applications (e.g., Home Assistant), reuse the application event loop rather than creating new ones.
- Do not call async methods like `connect()`, `refresh()`, or command methods from synchronous code without running them in the event loop.
- For long-running integrations:
  - Create a single `Device` per player.
  - Connect once, call `refresh()` on startup, and keep the connection alive.
  - Use the `dispatcher` to react to state changes instead of polling.

The underlying `Connection` supports automatic reconnect when enabled (see the `Device` constructor arguments), so transient network issues can often be handled transparently.

## Development and testing

This repository includes a full test suite and an in-process emulator for the Kaleidescape System Control Protocol.

### Project layout

- `kaleidescape/`
  - Library code: `device.py`, `connection.py`, `message.py`, `dispatcher.py`, `const.py`, `error.py`.
- `examples/`
  - Runnable examples demonstrating common usage patterns.
- `tests/`
  - `test_a_message.py` – message parsing/formatting.
  - `test_b_connection.py` – connection lifecycle & reconnect behavior.
  - `test_c_command.py` – command behavior.
  - `test_d_device.py` – `Device` behavior and state updates.
  - `emulator.py` – protocol emulator used by the tests.

### Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Running tests

Use `pytest` to run the test suite:

```bash
pytest
```

The tests automatically start the in-process emulator; no physical Kaleidescape hardware is required.

If you have `tox` installed, you can also run the full test matrix defined in `tox.ini`:

```bash
tox
```

### Linting, type checking, and formatting

This project uses `ruff` (for linting and formatting) and `mypy`.

```bash
ruff check kaleidescape tests
ruff format kaleidescape tests
mypy kaleidescape
```

When contributing changes, please keep tests passing and the linters clean.

## Limitations and notes

- This project is not affiliated with or endorsed by Kaleidescape, Inc.
- Behavior depends on the firmware and capabilities of your Kaleidescape system; some commands may only apply to movie players and not server-only devices.
- Network connectivity, DNS resolution, and firewall rules must allow outbound TCP connections to the Kaleidescape System Control Protocol port on your player.

## License

This project is licensed under the terms specified in the `LICENSE` file included in this repository.
