"""The home hub's live state read (`GET /api/v1/hub`, FR-UI-02, #634).

The hub shows three facts about the system — the package version in force, the last run's
status and the decision engine in use — read live from the store when the screen loads and on
`CONSOLE_POLL_INTERVAL_MS` afterwards. The read is pure over what the console already holds:
it queries only cohort files that exist (the `StoreReadsMixin` no-create rule), writes nothing,
and answers even when the store is empty (a fresh install shows a hub with no run yet).
"""

from __future__ import annotations

from typing import Any

from aeh.conf.decision_engine import decision_engine_setting

from .settings import CONSOLE_POLL_INTERVAL_MS


def engine_in_use(cfg: Any) -> str:
    """The engine the hub names: `jev` or `off`, the closed pair the SPA renders.

    Read from the effective configuration through the same helper the resolver uses
    (FR-CONF-29), so the console and a started run cannot disagree about an unset
    `HARNESS_DECISION_ENGINE`. Anything the setting holds besides `jev` is the engine being
    off, not a value to echo.
    """
    config = cfg if isinstance(cfg, dict) else {}
    profile = str(config.get("HARNESS_PROFILE") or "edge-local")
    return "jev" if decision_engine_setting(config, profile) == "jev" else "off"


def hub_payload(console: Any) -> dict[str, Any]:
    """The hub's state for the run the console serves, as the SPA's `fetch` returns it.

    `run_id` is the one `serve_console` was started with; a console started without one (or
    whose run is not in any cohort file yet) answers `None`s for the run's fields and the hub
    renders its cards without a run line, never an error. The engine and the poll interval
    always answer: they are configuration, not run state.
    """
    app = console.app
    run_id = getattr(console, "run_id", None)
    row = None
    if run_id:
        try:
            row = app._run_row(str(run_id))
        except Exception:  # noqa: BLE001 — a store mid-write is an empty hub, not a 500
            row = None
    return {
        "run_id": run_id,
        "package_version_id": None if row is None else row.get("package_version_id"),
        "run_status": None if row is None else row.get("status"),
        "engine": engine_in_use(getattr(app, "run_config", None)),
        "poll_interval_ms": CONSOLE_POLL_INTERVAL_MS,
    }
