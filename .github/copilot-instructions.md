# Copilot Instructions for `pykaleidescape`

This document is for AI coding assistants working in this repository. It explains the architecture, coding patterns,
and how to safely extend the library.

---

## 1. Project Overview & Main Entry Points

`pykaleidescape` is an async Python client for controlling Kaleidescape devices via the Kaleidescape System Control
Protocol.

Key modules:

- `kaleidescape/__init__.py`
  - Public API exports:
    - `Device` – high-level interface users work with.
    - `Dispatcher` – event dispatcher used to receive protocol events.
    - `KaleidescapeError` – base error type.
    - `const` – constants namespace (imported via package-level import).
- `kaleidescape/device.py`
  - Core high-level API.
  - Manages a `Connection`, a `Dispatcher`, and several state dataclasses:
    - `System`, `Power`, `OSD`, `Movie`, `Automation`.
  - Exposes async methods such as `connect`, `disconnect`, `refresh`, `leave_standby`, `play`, `set_volume_level`, etc.
- `kaleidescape/connection.py`
  - Low-level TCP connection handling, DNS resolution, reconnect logic.
- `kaleidescape/dispatcher.py`
  - Simple signal/slot-style dispatcher for events (`Dispatcher`, `Signal`).
- `kaleidescape/message.py`
  - Parsing/formatting of protocol messages.
  - Defines `Request`/`Response` classes and many typed subclasses registered via `@register`.
- `kaleidescape/const.py`
  - Protocol constants: message names, error codes, enums, and volume capability bits.
- `kaleidescape/error.py`
  - Error types and helper `format_error`.

Usage references:

- `examples/basic.py` – minimal connection and power state example.
- `examples/events.py` – event subscription via `device.dispatcher.connect`.
- `examples/volume.py` – volume integration using user-defined events.

Tests (canonical behavior specs):

- `tests/test_a_message.py` – message parsing/formatting.
- `tests/test_b_connection.py` – connection lifecycle & reconnect behavior.
- `tests/test_c_command.py` – command behavior.
- `tests/test_d_device.py` – `Device`-level behavior and state updates.
- `tests/emulator.py` – emulator for the Kaleidescape protocol used in tests.

End users should primarily interact with `Device` and constants from `kaleidescape.const`.

---

## 2. Architecture & Async Patterns

High-level architecture:

- **Device (`kaleidescape/device.py`)**
  - Owned by end users.
  - Holds:
    - `self._dispatcher: Dispatcher`
    - `self._connection: Connection`
    - State dataclasses: `system`, `power`, `osd`, `movie`, `automation`.
  - Responsibilities:
    - Manage connection lifecycle (`connect`, `disconnect`).
    - Perform initial and periodic state sync via async `_get_*` / `_update_*` methods.
    - Expose high-level async commands that wrap protocol messages.
    - React to events from `Connection` in `_handle_event`, updating state and re-dispatching via `Dispatcher`.

- **Connection (`kaleidescape/connection.py`)**
  - Async TCP client using `asyncio.open_connection`.
  - Resolves hostnames to IPs via `Connection.resolve` (using `aiodns`).
  - Manages:
    - Internal reader task (`_response_handler`) that receives protocol lines and turns them into `Response` objects.
    - A `dispatcher` that emits connection-state signals (e.g., `STATE_CONNECTED`, `STATE_DISCONNECTED`).
    - Reconnect behavior when `reconnect=True`.
    - Request/response correlation via `_pending_requests` and `Request.wait()`.

- **Dispatcher (`kaleidescape/dispatcher.py`)**
  - Lightweight event dispatcher used by `Device` and `Connection`.
  - `Dispatcher.connect(target)` returns a `Signal` that can later be `disconnect()`ed.
  - `send(*args)` calls each subscriber; supports async and sync callables.

- **Messages & Parsing (`kaleidescape/message.py`)**
  - `MessageParser` parses raw protocol strings into fields: device ID, zone, seq, status, name, fields, checksum.
  - `Request` constructs outgoing commands; `Response` represents responses/events.
  - Concrete `Request`/`Response` subclasses provide typed properties like `field_power`, `field_play_status`, `field_screen`, etc.
  - `Response.factory(message: str)` chooses the appropriate subclass from a `registry` populated by the `@register` decorator.

- **Constants (`kaleidescape/const.py`)**
  - Defines tokens for commands, events, statuses, and enums.
  - Message names (e.g., `DEVICE_POWER_STATE`, `PLAY_STATUS`), error codes, and mappings from protocol numeric codes to string labels.

### Async Guidelines

- All network I/O is async and based on `asyncio`.
- New user-facing commands on `Device` should be `async def` and use `await self._send(...)` or `await self._send_multi(...)`.
- Do not introduce blocking operations (e.g., `time.sleep`, synchronous network calls). Use `await asyncio.sleep(...)` if needed.
- Preserve the existing pattern of:
  - `_get_*` methods to send a single request and return a parsed `Response` subclass.
  - `_update_*` methods to mutate a state dataclass from a `Response` instance.

---

## 3. Adding New Protocol Features

When the Kaleidescape protocol gains a new command/event or you need to expose an existing one, follow this pattern:

1. **Add/Update Constants** (`kaleidescape/const.py`)

   - If the protocol defines a new message name, event, or enum value, add a new `UPPER_SNAKE_CASE` constant where similar values live.
   - For example, to add a new message `NEW_FEATURE`, define:
     - `NEW_FEATURE = "NEW_FEATURE"`
   - If there are new enums or error codes, extend the appropriate mappings (`RESPONSE_ERROR`, etc.).

2. **Define Request/Response Types** (`kaleidescape/message.py`)

   - Add a new `Request` subclass for the command:

     ```python
     class GetNewFeature(Request):
         """Class for GET_NEW_FEATURE messages."""

         name = f"GET_{const.NEW_FEATURE}"
     ```

   - Add a `Response` subclass for the corresponding response and register it:

     ```python
     @register
     class NewFeature(Response):
         """Class for NEW_FEATURE messages."""

         name = const.NEW_FEATURE

         @property
         def field_something(self) -> str:
             return self._fields[0]
     ```

   - Follow existing naming and docstring patterns; expose properties that interpret `_fields` into useful Python types (e.g., `int(self._fields[0])`).

3. **Expose on Device** (`kaleidescape/device.py`)

   - For simple commands that don't track state:

     ```python
     async def do_new_feature(self) -> None:
         """Send NEW_FEATURE command."""
         await self._send(messages.GetNewFeature)
     ```

   - For commands that return data:

     ```python
     async def get_new_feature(self) -> messages.NewFeature:
         """Return NEW_FEATURE state."""
         res = await self._send(messages.GetNewFeature)
         return cast(messages.NewFeature, res)
     ```

   - For stateful values that should live in one of the `System`, `Power`, `OSD`, `Movie`, or `Automation` dataclasses:
     - Add `_get_new_feature` and `_update_new_feature` methods mirroring existing `_get_*` / `_update_*` examples.
     - Call `_get_new_feature` in `connect()` and/or `refresh()` as appropriate, and use `_update_new_feature` to mutate the relevant dataclass.
     - Update `_handle_event` to respond to new event types by calling `_update_new_feature` and dispatching via `self._dispatcher.send(...)` (usually automatic via `Dispatcher`).

4. **Events & Dispatcher Integration**

   - Most new response types automatically go through `_handle_event` if they are emitted by the protocol as events.
   - To surface new events to user callbacks, ensure `_handle_event` updates internal state and then allows `self._dispatcher.send(response.name, response.fields)` to be called.
   - Users subscribe with:

     ```python
     signal = device.dispatcher.connect(callback)
     # callback(event_name, *args)
     ```

5. **Keep Parsing/Encoding in `message.py`**

   - Do not embed protocol parsing logic in `Device` or `Connection`.
   - All field parsing and mapping from raw strings to typed values should live in the relevant `Response` subclass.
   - `Device` should only use typed properties (e.g., `field_power`, `field_screen`).

---

## 4. Testing Strategy

This repo uses `pytest` with asyncio support.

Relevant configuration:

- `pyproject.toml`:
  - `asyncio_default_fixture_loop_scope = "function"`.
  - `testpaths = "tests"`.
- Tests rely on an in-process emulator (`tests/emulator.py`) instead of real hardware.

Guidelines:

1. **Where to Put Tests**

   - Message parsing/formatting: `tests/test_a_message.py`.
   - Connection-level behavior: `tests/test_b_connection.py`.
   - Command behavior (requests/responses): `tests/test_c_command.py`.
   - High-level `Device` behavior and state: `tests/test_d_device.py`.

2. **Patterns for New Tests**

   - For new `Request`/`Response` types:
     - Add unit tests that:
       - Construct raw protocol strings.
       - Use `Response.factory(...)` to parse them.
       - Assert the parsed properties (e.g., `field_power`, `field`, `is_error`, etc.).
     - Optionally test stringification of new `Request` types.

   - For new `Device` methods:
     - Reuse the emulator fixtures (`emulator`, `connection`, `device`) from `tests/conftest.py`.
     - Write async tests (`@pytest.mark.asyncio`) that:
       - Connect the device.
       - Trigger the new method.
       - Assert resulting state on `device.system`, `device.power`, `device.osd`, `device.movie`, or `device.automation`.

3. **Running Tests**

   - In this repo, the default test command is:

     ```bash
     pytest
     ```

   - After any non-trivial change, run the test suite and ensure it passes.

---

## 5. Python Version, Typing & Style

From project metadata (`setup.cfg`, `pyproject.toml`):

- Python: target modern versions (includes `Programming Language :: Python :: 3.13`). Code uses `from __future__ import annotations`.
- Linting: `ruff` is used, with `lint.extend-select = ["I"]` (import sorting).
- Type checking: `mypy` is configured with `disable_error_code = "annotation-unchecked"` but type hints are widely used.

### Style Expectations

- Use modern type hints:
  - Prefer `list[str]`, `dict[str, str]` etc., not `List[str]`, `Dict[str, str]`.
  - Maintain type annotations for all public functions and methods.
- Imports:
  - Keep imports sorted and grouped in a `ruff`/isort-compatible way.
- Docstrings:
  - Short, single-line descriptions like existing functions (e.g., `"""Return device info."""`).
- Naming:
  - `CamelCase` for classes and message types (e.g., `GetSystemVersion`, `DevicePowerState`).
  - `lower_snake_case` for variables and methods (e.g., `get_system_pairing_info`).
  - `UPPER_SNAKE_CASE` for constants and protocol tokens (e.g., `DEVICE_POWER_STATE_ON`).
- Async:
  - Minimize mutable shared state across tasks; follow existing patterns.
  - Use `asyncio.create_task` sparingly and where the existing code does so (e.g., handling events, reconnect logic).

---

## 6. Good Commit-Sized Changes for Assistants

When making changes, prefer small, focused diffs that align with existing patterns.

Examples of good, self-contained changes:

1. **Add a Single New Command**

- Touch points:
  - Add constants in `kaleidescape/const.py`.
  - Add one `Request` + one `Response` subclass in `kaleidescape/message.py`.
  - Add one or two new async methods on `Device` in `kaleidescape/device.py`.
  - Add 1–3 tests in the appropriate `tests/test_*.py` file.

2. **Extend State Tracking for an Existing Command**

- Touch points:
  - Update a `Response` subclass to expose additional `field_*` properties.
  - Update the corresponding `_update_*` method in `Device` to persist those fields into the appropriate dataclass.
  - Add or extend unit tests to cover the new fields.

3. **Small Improvements & Fixes**

- Add missing type hints to helper functions.
- Clarify or add short docstrings consistent with the existing style.
- Factor out a small private helper to reduce duplication in `device.py` or `message.py` (without altering public behavior).

Examples of changes that are too large for a single commit and should be split:

- Cross-cutting refactors affecting multiple core modules (`device.py`, `connection.py`, `message.py`, `dispatcher.py`).
- Behavior changes to connection lifecycle, reconnect logic, or event handling without matching tests.
- Repository-wide formatting-only changes.

---

## 7. Usage Hints for Assistants

- New user-facing features should be designed around the `Device` API.
  - Avoid exposing `Connection`/`Dispatcher` directly unless strictly necessary.
- When in doubt, copy the most similar existing pattern:
  - For new commands: mirror `get_system_pairing_info`, `leave_standby`, `get_available_devices`, etc.
  - For new event/state handling: mirror patterns in `_handle_event`.
- Maintain backward compatibility:
  - Do not remove or rename public methods or constants without updating tests and (ideally) `README.md`/`examples/`.
- For new user-facing features, consider adding or updating an example under `examples/` to demonstrate best practices.

