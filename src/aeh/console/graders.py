"""The graders measured, from the console (FR-CONSOLE-88, FR-STATS-36, FR-CALIB-19, #889).

Three pieces, each a thin composition over M-STATS and M-CALIB:

- `graders_status` is the System status read's `graders` block: the engine measurements from
  the latest promotion record, whether Jev-final is on, the latest consistency report of the
  marked examples, and the latest scheduled MVVP.
- `on_package_approved` schedules the MVVP when a test is published (FR-STATS-36).
- `on_run_started` checks a started run's frozen grader configuration against the last
  measured one: a changed FR-STATS-19 dimension (or a decision engine swapped in or out) runs
  the MVVP, and a changed model dimension re-grades the test's marked examples (FR-CALIB-19).
  Unchanged runs nothing.

Both triggers work on a server-owned thread with their own store, and neither can stop the
approval or the run that triggered it: a measurement that fails is logged. Nothing here changes
an engine or the Jev-final setting (ADR-50, CT-CONF-14).
"""

from __future__ import annotations

import json
import logging
import threading
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

LOGGER = logging.getLogger("aeh.console.graders")

#: One measurement per package version at a time: two runs started together must not schedule
#: two MVVPs, or two re-grades, for one change.
_IN_FLIGHT: set[str] = set()
_GUARD = threading.Lock()

_RUN_FROZEN_CONFIG_SQL = "SELECT panel_config, provider_config FROM run WHERE run_id = :run_id"


def _calib_reference() -> Any:
    """`aeh.calib.reference_set`, or None when M-CALIB is absent (CT-CALIB-01)."""
    try:
        from aeh.calib import reference_set
    except ImportError:
        return None
    return reference_set


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def jev_final_on(app: Any) -> bool:
    """Whether a confident Jev answer confirmed by one judge is final, as the console's
    effective configuration says (`HARNESS_JEV_FINAL_ON_ACCEPT`, default on)."""
    from aeh.conf.sources import JEV_FINAL_ON_ACCEPT_KEY, parse_jev_final_on_accept

    config = getattr(app, "run_config", None)
    config = config if isinstance(config, Mapping) else {}
    try:
        return parse_jev_final_on_accept(config.get(JEV_FINAL_ON_ACCEPT_KEY))
    except Exception:  # noqa: BLE001 - an unreadable value is refused at run start; default
        return True


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
    criteria = [{**item, "label": labels.get(item["criterion_id"], item["criterion_id"])}
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
            "steps": mvvp["detail"].get("steps") or {},
        },
    }


def _claim(version: str) -> bool:
    with _GUARD:
        if version in _IN_FLIGHT:
            return False
        _IN_FLIGHT.add(version)
        return True


def _release(version: str) -> None:
    with _GUARD:
        _IN_FLIGHT.discard(version)


def _on_thread(app: Any, name: str, work: Any) -> threading.Thread:
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
            if store is not None:
                store.close()

    thread = threading.Thread(target=run, name=f"aeh-graders-{name}", daemon=True)
    thread.start()
    return thread


def approval_configuration(app: Any) -> tuple[dict[str, Any], Decimal | None]:
    """The grader configuration the console would run a class under now, and its run cost
    ceiling: the effective configuration resolved as a run resolves it. `({}, None)` when it
    does not resolve (the MVVP then records an unknown configuration)."""
    from aeh.conf import CohortRef, resolve_run_config
    from aeh.stats import grader_configuration

    config = getattr(app, "run_config", None)
    if not isinstance(config, Mapping):
        return {}, None
    try:
        resolved = resolve_run_config(config, CohortRef("graders-check", "synthetic"))
    except Exception:  # noqa: BLE001 - an unresolvable configuration has no dimensions
        return {}, None
    return grader_configuration(resolved.to_persisted_dict()), resolved.cost_ceiling


def on_package_approved(app: Any, package_version_id: str) -> threading.Thread | None:
    """FR-STATS-36: a published test's MVVP, run once on a server-owned thread. Returns the
    thread, or None when a measurement of this version is already under way."""
    from aeh.stats import PACKAGE_APPROVAL_TRIGGER, schedule_mvvp

    if not _claim(package_version_id):
        return None
    configuration, ceiling = approval_configuration(app)

    def work(store: Any) -> None:
        try:
            schedule_mvvp(store, package_version_id=package_version_id,
                          trigger=PACKAGE_APPROVAL_TRIGGER, configuration=configuration,
                          cost_ceiling=ceiling)
        finally:
            _release(package_version_id)

    return _on_thread(app, f"approval-{package_version_id}", work)


def run_grader_configuration(store: Any, cohort_id: str,
                             run_id: str) -> tuple[dict[str, Any], Decimal | None]:
    """The grader configuration and run cost ceiling a started run was frozen to."""
    from aeh.stats import grader_configuration

    rows = list(store.cohort(cohort_id).query(_RUN_FROZEN_CONFIG_SQL, run_id=run_id))
    if not rows:
        return {}, None
    row = dict(rows[0])
    try:
        provider = json.loads(row.get("provider_config") or "{}")
    except (TypeError, ValueError):
        provider = {}
    ceiling = _decimal(provider.get("cost_ceiling")) if isinstance(provider, dict) else None
    return grader_configuration(row), ceiling


def on_run_started(app: Any, *, run_id: str, cohort_id: str, package_version_id: str,
                   config: Any) -> threading.Thread | None:
    """FR-STATS-36 / FR-CALIB-19: when the started run's graders differ from the ones last
    measured for its test, run the MVVP (trigger: the changed dimensions) and re-grade the
    test's marked examples; with no change, nothing runs. Returns the measuring thread, or
    None when nothing is due."""
    from aeh.stats import mvvp_due, schedule_mvvp

    store = app._store
    configuration, ceiling = run_grader_configuration(store, cohort_id, run_id)
    if not configuration:
        return None
    mvvp_changes = mvvp_due(store, package_version_id, configuration)
    reference = _calib_reference()
    reference_changes = (() if reference is None else
                         reference.reference_set_due(store, package_version_id, configuration))
    if not mvvp_changes and not reference_changes:
        return None
    if not _claim(package_version_id):
        return None

    def work(worker_store: Any) -> None:
        try:
            if mvvp_changes:
                schedule_mvvp(worker_store, package_version_id=package_version_id,
                              trigger=",".join(mvvp_changes), configuration=configuration,
                              cost_ceiling=ceiling)
            if reference_changes and isinstance(config, Mapping):
                reference.regrade_reference_set(
                    worker_store, package_version_id, config=dict(config),
                    trigger=",".join(reference_changes), configuration=configuration)
        finally:
            _release(package_version_id)

    return _on_thread(app, f"run-{run_id}", work)


__all__ = [
    "approval_configuration",
    "graders_status",
    "jev_final_on",
    "on_package_approved",
    "on_run_started",
    "run_grader_configuration",
]
