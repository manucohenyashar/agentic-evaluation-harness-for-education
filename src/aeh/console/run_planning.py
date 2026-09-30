"""Building a console over a store, and planning a run or a retry."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .records import RunPlan
from .app import ConsoleApp


def build_console(
    store: Any = None,
    *,
    provider: Any = None,
    cohort_size: int | None = None,
    student_name: str | None = None,
    blind_labels_collected: int | None = None,
    bind_address: str | None = None,
) -> ConsoleApp:
    """Create a `ConsoleApp` over the given store, or over none (every screen then shows its empty
    state). The `provider` argument is accepted but never used, because the console never calls a
    model."""
    return ConsoleApp(
        store=store,
        provider=provider,
        cohort_size=cohort_size,
        student_name=student_name,
        blind_labels_collected=blind_labels_collected,
        bind_address=bind_address,
    )


# --- run planning -----------------------------------------------------------------------------------------


def _persisted_shape(config: Any) -> str:
    """The configuration as a canonical string for hashing: `to_persisted_dict()` for a resolved
    config, or the dict itself."""
    if hasattr(config, "to_persisted_dict"):
        config = config.to_persisted_dict()
    if isinstance(config, dict):
        return json.dumps(config, sort_keys=True, default=str)
    return str(config)


def _profile_of(config: Any) -> str:
    raw = None
    if hasattr(config, "to_persisted_dict"):
        raw = config.to_persisted_dict().get("HARNESS_PROFILE")
    if raw is None and isinstance(config, dict):
        raw = config.get("HARNESS_PROFILE")
    return str(raw or "edge-local")


def start_run(config: Any) -> RunPlan:
    """Plan a run. The run id comes from the saved configuration, so the same config gives the same
    run and a different config gives a different one (FR-CONF-04). Planning writes nothing; the
    orchestrator creates the run row."""
    digest = hashlib.sha256(_persisted_shape(config).encode("utf-8")).hexdigest()[:12]
    return RunPlan(run_id=f"run-{digest}", backend_profile=_profile_of(config))


def retry_run(run_id: str, *, backend_profile: str) -> RunPlan:
    """Plan a retry of `run_id` with a different backend profile. The retry gets a new id: it is a
    new run, never the same rows picked up again (FR-CONF-04)."""
    digest = hashlib.sha256(f"{run_id}\n{backend_profile}".encode("utf-8")).hexdigest()[:12]
    return RunPlan(run_id=f"run-{digest}", backend_profile=backend_profile, retry_of=run_id)
