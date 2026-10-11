# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Tooling is managed with uv. Dev tool versions in `pyproject.toml` and `.pre-commit-config.yaml` are pinned to match Home Assistant's.

**Setup:**
```bash
uv sync
uv run prek install   # optional: run the hooks on every commit
```

**Lint, format & type-check (all prek hooks: ruff, codespell, zizmor, yamllint, mypy, pylint):**
```bash
uv run prek run --all-files
```

**Run all tests:**
```bash
uv run pytest
```

**Run on another Python version (3.11 is the minimum supported):**
```bash
uv run --python 3.11 pytest
```

**Run a single test:**
```bash
uv run pytest tests/test_d_device.py::test_name
uv run pytest -k "pattern"
```

**Build:**
```bash
uv build
```

## Architecture

pykaleidescape is an async Python client for controlling Kaleidescape media players via the Kaleidescape System Control Protocol (TCP).

### Layered design (bottom to top)

1. **`message.py`** — Protocol layer. `MessageParser` parses/formats raw TCP messages (device ID, sequence number, status, fields, checksum). Each message type is registered in a factory registry.

2. **`connection.py`** — Transport layer. Manages the TCP connection, reconnection with configurable delays, and maps responses back to pending requests via sequence numbers.

3. **`dispatcher.py`** — Event layer. Thin pub/sub dispatcher supporting both sync and async callbacks. Decouples incoming messages from application code.

4. **`device.py`** — Public API. `Device` is the main entry point. It owns five state dataclasses (`System`, `Power`, `OSD`, `Movie`, `Automation`) that are updated reactively as messages arrive. All user-facing commands live here (`play()`, `pause()`, `leave_standby()`, navigation commands, volume helpers, etc.).

5. **`const.py`** / **`error.py`** — Protocol constants and custom exception hierarchy (`KaleidescapeError`, `MessageError`, `MessageParseError`).

Public exports from `kaleidescape/__init__.py`: `Device`, `Dispatcher`, `const`, `KaleidescapeError`.

### Testing

Tests use an in-process `Emulator` (in `tests/emulator.py`) so no physical hardware is needed. All tests are async (`pytest-asyncio`). The `conftest.py` provides `emulator` and `connection` fixtures. Test files are prefixed `test_a` through `test_d` reflecting the layer they cover (message → connection → command → device).
