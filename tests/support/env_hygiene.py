"""Process-environment hygiene for test-support worlds (`TC-REG-10`, TS-126, #537).

The knobs are read at call time (CLAUDE.md seam 3), so a world that drives a run has to
set them in the process environment. When a caller passes `monkeypatch`, pytest restores
them. When it does not, the world used to write `os.environ` directly and never restore
it, so every later test in the process inherited `HARNESS_INGEST_DPI=72`,
`HARNESS_INGEST_V4_SEMANTIC_FLOOR=0.0` and the corpus escalation budget. That produced
ten order-dependent reds and the gate's `test_ct_ingest_v4_halting` flakes (design 1.9
§5.2).

`set_world_env` records the value it overwrites the first time a name is set, and
`restore_world_env` puts every recorded value back. `tests/conftest.py` calls the latter
after every test, so a world built without `monkeypatch` lives exactly as long as its test.
"""

from __future__ import annotations

import os
from typing import Any

#: name -> the value it held before a world first set it (`None`: it was unset).
_SAVED: dict[str, str | None] = {}


def set_world_env(name: str, value: str, monkeypatch: Any = None) -> None:
    """Set one knob for the current test: through `monkeypatch` when given, else directly,
    remembering the previous value so `restore_world_env` can undo it."""
    if monkeypatch is not None:
        monkeypatch.setenv(name, value)
        return
    _SAVED.setdefault(name, os.environ.get(name))
    os.environ[name] = value


def restore_world_env() -> list[str]:
    """Undo every `set_world_env` made without `monkeypatch`. Returns the names restored."""
    restored = sorted(_SAVED)
    for name, previous in _SAVED.items():
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous
    _SAVED.clear()
    return restored


def take_world_env_names() -> list[str]:
    """The names worlds set without monkeypatch since the last call, clearing the registry.
    The suite root resets each to its value at the start of the test (TC-REG-10)."""
    names = sorted(_SAVED)
    _SAVED.clear()
    return names


def harness_env_snapshot() -> dict[str, str]:
    """Every `HARNESS_*` variable currently set."""
    return {key: value for key, value in os.environ.items() if key.startswith("HARNESS_")}
