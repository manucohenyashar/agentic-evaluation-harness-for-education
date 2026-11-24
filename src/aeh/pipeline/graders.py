"""The graders measured after a class run, on every path that drives one (FR-STATS-36,
FR-CALIB-19, #889).

The run-side trigger of the MVVP schedule: a class run's frozen grader configuration is compared
with the one last measured for its test.

- **The MVVP** runs when an FR-STATS-19 dimension (or the decision engine) differs from the
  configuration the version's last MVVP record measured, ran or refused; a version never
  measured is due on every dimension (`aeh.stats.mvvp_due`).
- **The marked examples** are re-graded when a model dimension differs from the configuration
  they were last graded under (M-CALIB's `reference_set_due`).

Why after the drive and not at run start: `aeh run` and the console start a run identically and
must write the same start rows (FR-CONSOLE-42..44, TC-CONSOLE-56). The trigger is a
configuration change, not the start itself, so `measure_graders_after_run` runs once a class run
has been driven to `complete` (the stored status, read back from M-ORCH) — in `aeh run`'s
command and on the console's worker thread, through this one function, so both paths measure
the same graders the same way. The console's `on_run_started` is the same check made on a
server-owned thread for a run it names (`due_measurements` / `perform_measurements`).

A measurement never fails the run that triggered it: anything it raises is logged. A
calibration cohort's own runs (the examples' grading and re-grades, which go through the same
driver) trigger nothing. Nothing here changes an engine or the Jev-final setting (ADR-50,
CT-CONF-14). No SQL (CT-PIPE-05): M-STATS, M-CALIB, M-PKG and M-ORCH own every read and write.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Mapping

LOGGER = logging.getLogger("aeh.pipeline.graders")

#: One measurement per package version at a time, in this process: two runs of one test
#: finishing together, or a run finishing while the console's approval MVVP is under way, must
#: not schedule two MVVPs, or two re-grades, for one change.
_IN_FLIGHT: set[str] = set()
_GUARD = threading.Lock()


@dataclass(frozen=True)
class GradersMeasurement:
    """What one run-side check scheduled: the dimensions that made the MVVP due (empty when it
    was not), the ones that made the examples' re-grade due, and each outcome."""

    package_version_id: str
    mvvp_changes: tuple[str, ...] = ()
    reference_changes: tuple[str, ...] = ()
    mvvp: Any = None
    regrade: Any = None


@dataclass(frozen=True)
class DueMeasurements:
    """The measurements a run's grader configuration makes due for its test."""

    package_version_id: str
    configuration: Mapping[str, Any]
    cost_ceiling: Any = None
    mvvp_changes: tuple[str, ...] = ()
    reference_changes: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.mvvp_changes or self.reference_changes)


def claim_measurement(version: str) -> bool:
    """Claim the version's one measurement slot; False when a measurement holds it."""
    with _GUARD:
        if version in _IN_FLIGHT:
            return False
        _IN_FLIGHT.add(version)
        return True


def release_measurement(version: str) -> None:
    """Release the slot `claim_measurement` took."""
    with _GUARD:
        _IN_FLIGHT.discard(version)


def _calib_reference() -> Any:
    """`aeh.calib.reference_set`, or None when M-CALIB is absent (CT-CALIB-01)."""
    try:
        from aeh.calib import reference_set
    except ImportError:
        return None
    return reference_set


def due_measurements(store: Any, package_version_id: str, configuration: Mapping[str, Any],
                     *, cost_ceiling: Any = None,
                     regrade_examples: bool = True) -> DueMeasurements:
    """What `configuration` (`aeh.stats.grader_configuration`'s shape) makes due for the
    version: the MVVP's changed dimensions and, when `regrade_examples`, the marked examples'.
    Read-only."""
    from aeh.stats import mvvp_due

    if not configuration:
        return DueMeasurements(package_version_id, {}, cost_ceiling)
    mvvp_changes = tuple(mvvp_due(store, package_version_id, configuration))
    reference = _calib_reference() if regrade_examples else None
    reference_changes = (() if reference is None else
                         tuple(reference.reference_set_due(store, package_version_id,
                                                           configuration)))
    return DueMeasurements(package_version_id, dict(configuration), cost_ceiling,
                           mvvp_changes, reference_changes)


def perform_measurements(store: Any, due: DueMeasurements,
                         config: Mapping[str, Any] | None) -> GradersMeasurement:
    """Run what `due` names on `store`: the MVVP (trigger: the changed dimensions) and the
    examples' re-grade under `config`. The caller holds the version's claim. Raises what the
    measurement raises; the callers log it."""
    from aeh.stats import schedule_mvvp

    mvvp = regrade = None
    version = due.package_version_id
    if due.mvvp_changes:
        mvvp = schedule_mvvp(store, package_version_id=version,
                             trigger=",".join(due.mvvp_changes),
                             configuration=due.configuration, cost_ceiling=due.cost_ceiling)
    if due.reference_changes and isinstance(config, Mapping):
        regrade = _calib_reference().regrade_reference_set(
            store, version, config=dict(config), trigger=",".join(due.reference_changes),
            configuration=due.configuration)
    return GradersMeasurement(version, due.mvvp_changes, due.reference_changes,
                              mvvp=mvvp, regrade=regrade)


def measure_graders_after_run(
    store: Any,
    *,
    run_id: str,
    cohort_id: str,
    package_version_id: str,
    run_config: Any,
    config: Mapping[str, Any] | None,
) -> GradersMeasurement | None:
    """FR-STATS-36 / FR-CALIB-19 after a class run was driven: when the run's stored status is
    `complete` and its graders differ from the ones last measured for its test, run the MVVP and
    re-grade the test's marked examples, on the caller's thread and store. `run_config` is the
    run's frozen `RunConfig` (its `to_persisted_dict()` is what the run row's `run_config`
    column holds). Returns what was scheduled, or None when nothing was due (or the check could
    not run). Never raises."""
    from aeh.store import is_calibration_cohort

    if is_calibration_cohort(cohort_id) or not package_version_id:
        return None
    try:
        from aeh.orch import Orchestrator
        from aeh.stats import grader_configuration

        if str(Orchestrator(store).run_handle(run_id).status) != "complete":
            return None
        due = due_measurements(
            store, package_version_id, grader_configuration(run_config.to_persisted_dict()),
            cost_ceiling=getattr(run_config, "cost_ceiling", None),
            regrade_examples=isinstance(config, Mapping))
    except Exception:  # noqa: BLE001 - a measurement never fails its run
        LOGGER.exception("the graders of %s could not be checked", package_version_id)
        return None
    if not due or not claim_measurement(package_version_id):
        return None
    try:
        return perform_measurements(store, due, config)
    except Exception:  # noqa: BLE001 - a measurement never fails its run
        LOGGER.exception("the graders' measurement of %s did not finish", package_version_id)
        return GradersMeasurement(package_version_id, due.mvvp_changes, due.reference_changes)
    finally:
        release_measurement(package_version_id)


__all__ = [
    "DueMeasurements",
    "GradersMeasurement",
    "claim_measurement",
    "due_measurements",
    "measure_graders_after_run",
    "perform_measurements",
    "release_measurement",
]
