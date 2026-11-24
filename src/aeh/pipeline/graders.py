"""The graders measured after a class run, on every path that drives one (FR-STATS-36, #889).

`measure_graders_after_run` is the run-side trigger of the MVVP schedule: once a class run is
stored `complete`, its frozen grader configuration is compared with the one the version's last
MVVP record measured, ran or refused. A changed FR-STATS-19 dimension (or a decision engine
swapped in or out) runs the MVVP, the trigger naming the changes; a version never measured is
due on every dimension (`aeh.stats.mvvp_due`); an unchanged configuration runs nothing.

Why after the drive and not at run start: `aeh run` and the console start a run identically and
must write the same start rows (FR-CONSOLE-42..44, TC-CONSOLE-56). The trigger is a
configuration change, not the start itself, so the check runs once the run has been driven —
in `aeh run`'s command and on the console's worker thread — through this one function, so both
paths measure the same graders the same way.

The marked examples' re-grade (FR-CALIB-19) belongs to M-CALIB, which sits above the driver
(CT-CALIB-01: M-PIPE imports nothing from it). A caller that offers the examples step passes it
in as `after`: the console's worker does; `aeh run` has no examples step.

A measurement never fails the run that triggered it: anything it raises is logged. A
calibration cohort's own runs (the examples' grading and re-grades, which go through the same
driver) trigger nothing. Nothing here changes an engine or the Jev-final setting (ADR-50,
CT-CONF-14). No SQL (CT-PIPE-05): M-STATS, M-PKG and M-ORCH own every read and write.
"""

from __future__ import annotations

import logging
import threading
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

LOGGER = logging.getLogger("aeh.pipeline.graders")

#: The versions under measurement in this process. One measurement per package version at a
#: time: two runs of one test finishing together, or a run finishing while the console's
#: approval MVVP is under way, must not schedule two MVVPs, or two re-grades, for one change.
MEASUREMENTS_IN_FLIGHT: set[str] = set()
_GUARD = threading.Lock()

#: What a caller passes as `after`: `(store, package_version_id, configuration)`, run on the
#: same thread and store, inside the version's claim.
AfterMeasurement = Callable[[Any, str, Mapping[str, Any]], Any]


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def claim_measurement(version: str) -> bool:
    """Claim the version's one measurement slot; False when a measurement holds it."""
    with _GUARD:
        if version in MEASUREMENTS_IN_FLIGHT:
            return False
        MEASUREMENTS_IN_FLIGHT.add(version)
        return True


def release_measurement(version: str) -> None:
    """Release the slot `claim_measurement` took."""
    with _GUARD:
        MEASUREMENTS_IN_FLIGHT.discard(version)


def measure_graders_after_run(
    store: Any,
    *,
    run_id: str,
    cohort_id: str,
    package_version_id: str,
    after: AfterMeasurement | None = None,
) -> Any:
    """FR-STATS-36 after a class run was driven: when the run is stored `complete` and its
    graders differ from the ones the version's last MVVP measured, run the MVVP on the caller's
    thread and store, then `after` (the examples' re-grade check, when the caller offers one).
    The graders compared are the ones the run FROZE — its row's `run_config`, as M-ORCH's
    `run_handle` hands it over — never the configuration this process resolved today (a
    continued or resumed run is measured as it ran). Returns the `ScheduledMvvp`, or None when
    no MVVP ran. Never raises."""
    from aeh.store import is_calibration_cohort

    if is_calibration_cohort(cohort_id) or not package_version_id:
        return None
    try:
        from aeh.orch import Orchestrator
        from aeh.stats import grader_configuration, mvvp_due

        handle = Orchestrator(store).run_handle(run_id)
        persisted = handle.persisted_config
        if str(handle.status) != "complete" or not isinstance(persisted, Mapping):
            return None
        configuration = grader_configuration(persisted)
        provider = persisted.get("provider_config")
        ceiling = _decimal(provider.get("cost_ceiling")) if isinstance(provider, Mapping) else None
        changes = tuple(mvvp_due(store, package_version_id, configuration))
    except Exception:  # noqa: BLE001 - a measurement never fails its run
        LOGGER.exception("the graders of %s could not be checked", package_version_id)
        return None
    if not changes and after is None:
        return None
    if not claim_measurement(package_version_id):
        return None
    scheduled = None
    try:
        if changes:
            from aeh.stats import schedule_mvvp

            scheduled = schedule_mvvp(
                store, package_version_id=package_version_id, trigger=",".join(changes),
                configuration=configuration, cost_ceiling=ceiling)
        if after is not None:
            after(store, package_version_id, configuration)
    except Exception:  # noqa: BLE001 - a measurement never fails its run
        LOGGER.exception("the graders' measurement of %s did not finish", package_version_id)
    finally:
        release_measurement(package_version_id)
    return scheduled


__all__ = [
    "AfterMeasurement",
    "MEASUREMENTS_IN_FLIGHT",
    "claim_measurement",
    "measure_graders_after_run",
    "release_measurement",
]
