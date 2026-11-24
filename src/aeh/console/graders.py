"""The graders measured, from the console (FR-CONSOLE-88, FR-STATS-36, FR-CALIB-19, #889).

Three pieces, each a thin composition over M-STATS, M-CALIB and the composition root:

- `graders_status` is the System status read's `graders` block: the engine measurements from
  the latest promotion record, whether Jev-final is on, the latest consistency report of the
  marked examples, and the latest scheduled MVVP. Like every read it writes nothing, and with
  no Tier D file it opens none.
- `on_package_approved` schedules the MVVP when a test is published (FR-STATS-36), on a
  server-owned thread with its own store; it never stops the approval.
- `on_run_started` checks a run's frozen grader configuration (the run row's `run_config`)
  against the last measured one and, when it changed, measures on a server-owned thread:
  `aeh.pipeline.graders`' check, made for a run the console names.

The console's `start run` does not call `on_run_started` itself: the start must write exactly
the rows `aeh run` writes (TC-CONSOLE-56), so both paths make the run-side check after the
drive, through `aeh.pipeline.graders.measure_graders_after_run`. The one-measurement-per-version
claim is that module's, shared by all three triggers. Nothing here changes an engine or the
Jev-final setting (ADR-50, CT-CONF-14).
"""

from __future__ import annotations

import json
import logging
import threading
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

# `_IN_FLIGHT` is the composition root's one set of versions under measurement (the same
# object), bound here too because this module's claim lived here first.
from aeh.pipeline.graders import _IN_FLIGHT, claim_measurement, release_measurement  # noqa: F401

LOGGER = logging.getLogger("aeh.console.graders")

#: The run's whole frozen `RunConfig`, as `to_persisted_dict()` wrote it (M-ORCH). The
#: `panel_config` / `provider_config` columns hold M-ORCH's own work-identity shapes, not that
#: dict's keys, so they are not what `grader_configuration` reads.
_RUN_FROZEN_CONFIG_SQL = "SELECT run_config FROM run WHERE run_id = :run_id"


def _calib_reference() -> Any:
    """`aeh.calib.reference_set`, or None when M-CALIB is absent (CT-CALIB-01)."""
    try:
        from aeh.calib import reference_set
    except ImportError:
        return None
    return reference_set


#: FR-AGG-20's setting, read off the console's effective configuration.
JEV_FINAL_SETTING = "HARNESS_JEV_FINAL_ON_ACCEPT"


def jev_final_on(app: Any) -> bool:
    """Whether a confident Jev answer confirmed by one judge is final, as the console's
    effective configuration says (`HARNESS_JEV_FINAL_ON_ACCEPT`, default on): the value the
    resolver freezes for a run (`RunConfig.jev_final_on_accept`), and when the configuration
    does not resolve, the setting itself — only an explicit `false` turns it off."""
    resolved = _resolved(app)
    if resolved is not None:
        return bool(resolved.jev_final_on_accept)
    config = getattr(app, "run_config", None)
    raw = config.get(JEV_FINAL_SETTING) if isinstance(config, Mapping) else None
    return str(raw).strip().lower() not in ("false", "0", "no", "off") if raw is not None else True


def _resolved(app: Any) -> Any:
    """The console's effective configuration resolved as a run resolves it, or None."""
    from aeh.conf import CohortRef, resolve_run_config

    config = getattr(app, "run_config", None)
    if not isinstance(config, Mapping):
        return None
    try:
        return resolve_run_config(config, CohortRef("graders-check", "synthetic"))
    except Exception:  # noqa: BLE001 - an unresolvable configuration has no dimensions
        return None


def graders_status(app: Any, run_row: Any) -> dict[str, Any]:
    """System status's `graders` block (FR-CONSOLE-88): the engine measurements of the latest
    promotion record (of the run's test version when a run is in view), Jev-final on or off,
    the latest consistency report and the latest scheduled MVVP. Stored values only."""
    from aeh.stats import graders_figures, latest_mvvp_record

    from .screen_reads import _grading_point_labels

    store = app._store
    version = None if run_row is None else str(run_row["package_version_id"])
    figures = graders_figures(store, version)
    if version is not None and not figures["criteria"]:
        # The run's version has no record yet: the latest of any version is still evidence
        # about the graders.
        figures = graders_figures(store, None)
    labels: dict[str, str] = {}
    if figures["package_version_id"]:
        from aeh.orch import default_package_id_for

        try:
            labels = _grading_point_labels(app, {
                "package_id": default_package_id_for(figures["package_version_id"]),
                "package_version_id": figures["package_version_id"]})
        except Exception:  # noqa: BLE001 - a figure keeps its id when no label is found
            labels = {}
    # A criterion with no teacher label reads as "a question", never as its id (FR-UI-23).
    criteria = [{**item, "label": labels.get(item["criterion_id"]) or "A question"}
                for item in figures["criteria"]]
    failing = [item["label"] for item in criteria if item["noninferiority"] == "false"]
    reference = _calib_reference()
    mvvp = latest_mvvp_record(store, version) or latest_mvvp_record(store, None)
    return {
        **figures,
        "criteria": criteria,
        "jev_final_on": jev_final_on(app),
        "noninferiority_failing": failing,
        "consistency_report": (None if reference is None
                               else reference.consistency_report(store, version)
                               or reference.consistency_report(store, None)),
        "mvvp": None if mvvp is None else {
            "recorded_at": mvvp["recorded_at"],
            "trigger": mvvp["trigger"],
            "outcome": mvvp["outcome"],
            "refusal": mvvp["detail"].get("refusal"),
            "steps": _served_steps(mvvp["detail"].get("steps")),
        },
    }


def _served_steps(stored: Any) -> dict[str, Any]:
    """The MVVP's steps as System status serves them: each step's own outcome, keyed by its
    number. The record keeps the requirement each step answers to; the screen names a step in
    the teacher's words, so no requirement id is served (FR-UI-23)."""
    if not isinstance(stored, Mapping):
        return {}
    return {str(number): {"outcome": step.get("outcome")}
            for number, step in stored.items() if isinstance(step, Mapping)}


def _on_thread(app: Any, version: str, name: str, work: Any) -> threading.Thread:
    """Run `work(store)` on a server-owned thread with its own store; the version's claim is
    released however the thread ends, the store's open included."""
    from aeh.pipeline.runtime import _open_store

    data_dir = str(app._store.data_dir)

    def run() -> None:
        store = None
        try:
            store = _open_store(data_dir)
            work(store)
        except Exception:  # noqa: BLE001 - a measurement never fails its trigger
            LOGGER.exception("the graders' measurement %s did not finish", name)
        finally:
            release_measurement(version)
            if store is not None:
                store.close()

    thread = threading.Thread(target=run, name=f"aeh-graders-{name}", daemon=True)
    try:
        thread.start()
    except Exception:
        release_measurement(version)
        raise
    return thread


def approval_configuration(app: Any) -> tuple[dict[str, Any], Decimal | None]:
    """The grader configuration the console would run a class under now, and its run cost
    ceiling: the effective configuration resolved as a run resolves it. `({}, None)` when it
    does not resolve (the MVVP then records an unknown configuration)."""
    from aeh.stats import grader_configuration

    resolved = _resolved(app)
    if resolved is None:
        return {}, None
    return grader_configuration(resolved.to_persisted_dict()), resolved.cost_ceiling


def on_package_approved(app: Any, package_version_id: str) -> threading.Thread | None:
    """FR-STATS-36: a published test's MVVP, run once on a server-owned thread. Returns the
    thread, or None when a measurement of this version is already under way."""
    from aeh.stats import PACKAGE_APPROVAL_TRIGGER, schedule_mvvp

    configuration, ceiling = approval_configuration(app)
    if not claim_measurement(package_version_id):
        return None

    def work(store: Any) -> None:
        schedule_mvvp(store, package_version_id=package_version_id,
                      trigger=PACKAGE_APPROVAL_TRIGGER, configuration=configuration,
                      cost_ceiling=ceiling)

    return _on_thread(app, package_version_id, f"approval-{package_version_id}", work)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def run_grader_configuration(store: Any, cohort_id: str,
                             run_id: str) -> tuple[dict[str, Any], Decimal | None]:
    """The grader configuration and run cost ceiling a run was frozen to, from its row's
    `run_config` column; `({}, None)` when the run or its frozen configuration is missing."""
    from aeh.stats import grader_configuration

    rows = list(store.cohort(cohort_id).query(_RUN_FROZEN_CONFIG_SQL, run_id=run_id))
    if not rows:
        return {}, None
    try:
        persisted = json.loads(dict(rows[0]).get("run_config") or "{}")
    except (TypeError, ValueError):
        persisted = {}
    if not isinstance(persisted, dict) or not persisted:
        return {}, None
    provider = persisted.get("provider_config")
    ceiling = _decimal(provider.get("cost_ceiling")) if isinstance(provider, dict) else None
    return grader_configuration(persisted), ceiling


def on_run_started(app: Any, *, run_id: str, cohort_id: str, package_version_id: str,
                   config: Any) -> threading.Thread | None:
    """FR-STATS-36 / FR-CALIB-19 for a run the console names: when its frozen graders differ
    from the ones last measured for its test, run the MVVP (trigger: the changed dimensions)
    and, given the run's `config`, re-grade the test's marked examples, on a server-owned
    thread. Returns the measuring thread, or None when nothing is due or a measurement of the
    version is already under way."""
    from aeh.pipeline.graders import due_measurements, perform_measurements

    configuration, ceiling = run_grader_configuration(app._store, cohort_id, run_id)
    due = due_measurements(app._store, package_version_id, configuration,
                           cost_ceiling=ceiling, regrade_examples=isinstance(config, Mapping))
    if not due or not claim_measurement(package_version_id):
        return None
    run_config = dict(config) if isinstance(config, Mapping) else None
    return _on_thread(app, package_version_id, f"run-{run_id}",
                      lambda store: perform_measurements(store, due, run_config))


__all__ = [
    "approval_configuration",
    "graders_status",
    "jev_final_on",
    "on_package_approved",
    "on_run_started",
    "run_grader_configuration",
]
