"""The grading stage's signals and alerts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from aeh.store import Store

from .constants import (
    _GRADE_RUN_STORES,
    GRADE_STATES,
    STATE_FINAL,
    STATE_INCOMPLETE,
    STATE_PROVISIONAL,
    STATUS_COMPLETE,
)
from .refs import _now, _parse_timestamp
from .schema import GRADE_STATEMENTS
from .records import GradeError
from .service import GradingService


# --- the stage's observability surface (CT-GRADE-18, TC-GRADE-24) -----------------------------------
#
# The signal set design §3.14's observability paragraph names, written where every
# other stage's figures ride: the durable `run_metrics` EAV rows `(run_id, metric,
# value)` (the TC-ORCH-35 write contract). `record_grade_signals` derives every
# figure from the current-revision ledger; the one figure the ledger cannot derive —
# the batch finalization road — is recorded by `finalize_batch` itself. The accessors
# are module-level seams (the `class_rollup` precedent): they take a store handle or
# resolve one from the registry the service's run resolutions populate, because a
# read-side signal sweep must not need a grading pass in the room.
#
# The store registry is keyed by run id — every `_run_row` resolution registers — so
# a run graded through the headless constructor leaves its store findable. It holds
# strong references the way `_MIXED_REVISION_COHORTS` does; the same disclosed
# trade (a service's runs are a bounded, small set, and a store that scored a run
# stays open for its reads).


@dataclass(frozen=True)
class GradeAlert:
    """One fired grading alert (TC-GRADE-24): the kind, the run, how many grades it covers, and a
    detail line naming the submissions, so an operator can act on it."""

    kind: str
    run_id: str
    count: int
    detail: str


def _signal_store(run_id: str, store: Store | None) -> Store:
    """The store the signal and alert functions read: the one passed in, else the one the service
    registered for the run, else a refusal explaining what to do."""
    if store is not None:
        return store
    registered = _GRADE_RUN_STORES.get(run_id)
    if registered is None:
        raise GradeError(
            f"no store is registered for run {run_id!r} — pass store= explicitly, "
            "or open the run through open_grade(store), whose run resolutions "
            "register it"
        )
    return registered


def record_grade_signals(
    run_id: str, *, store: Store | None = None
) -> dict[str, float]:
    """Write the grading stage's signals (CT-GRADE-18) to the durable `run_metrics` rows. Writing
    again updates the run's figures in place (insert-or-replace), never duplicates them:

    - **grades by state** — one row per state literal (`grades_by_state_incomplete`
      / `..._provisional` / `..._final`), the `CoverageSummary.grades_by_state`
      shape broken out per state so an incomplete figure is nameable;
    - **`boundary_at_risk` count** — how many current grades sit on a boundary;
    - **coverage distribution** — the five counters summed over the run's current
      grades (the class-level coverage, not one scalar);
    - **finalization path taken** — the settled/awaiting split the ledger CAN
      derive: `finalization_path_settled_at_issuance` (final with
      `finalized_at == computed_at` — settled when issued),
      `finalization_path_settled_after_issuance` (final with a later stamp — the
      automatic roads: run completion or the lapsed window, which settle through
      the same in-place UPDATE and are not distinguishable beyond this without a
      path column — the disclosed boundary of the derivation),
      `finalization_path_awaiting_settlement` (not yet final); the batch road
      writes its own `finalization_path_batch` row at action time;
    - **amendment count** — the amendment entries the run's current revisions
      carry, the revisions' trail counted.

    Returns the emitted figures — the value half of the "exact signal" oracle, and
    the seam-4 surface: a caller reads what the stage reported without re-querying
    the table."""
    resolved = _signal_store(run_id, store)
    return _emit_grade_signals(run_id, resolved)


def _emit_grade_signals(run_id: str, store: Store) -> dict[str, float]:
    """Read the run's current revisions, compute every grading signal, write them in one durable
    transaction, and return what was written."""
    service = GradingService(store)
    run = service._run_row(run_id)
    cohort = store.cohort(run["cohort_id"])
    grades = [
        dict(row)
        for row in cohort.query(
            GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run_id
        )
    ]
    by_state = {state: 0 for state in GRADE_STATES}
    for row in grades:
        by_state[row["state"]] = by_state.get(row["state"], 0) + 1
    coverage_sum = {
        counter: sum(int(row[counter] or 0) for row in grades)
        for counter in (
            "criteria_total",
            "criteria_auto",
            "criteria_reviewed",
            "criteria_provisional",
            "criteria_missing",
        )
    }
    settled_at_issuance = sum(
        1
        for row in grades
        if row["state"] == STATE_FINAL
        and row["finalized_at"] is not None
        and row["finalized_at"] == row["computed_at"]
    )
    settled_total = by_state.get(STATE_FINAL, 0)
    metrics: dict[str, float] = {
        "grades_by_state_incomplete": float(by_state.get(STATE_INCOMPLETE, 0)),
        "grades_by_state_provisional": float(by_state.get(STATE_PROVISIONAL, 0)),
        "grades_by_state_final": float(settled_total),
        "boundary_at_risk_count": float(
            sum(1 for row in grades if int(row["boundary_at_risk"] or 0))
        ),
        "coverage_criteria_total": float(coverage_sum["criteria_total"]),
        "coverage_criteria_auto": float(coverage_sum["criteria_auto"]),
        "coverage_criteria_reviewed": float(coverage_sum["criteria_reviewed"]),
        "coverage_criteria_provisional": float(coverage_sum["criteria_provisional"]),
        "coverage_criteria_missing": float(coverage_sum["criteria_missing"]),
        "finalization_path_settled_at_issuance": float(settled_at_issuance),
        "finalization_path_settled_after_issuance": float(
            settled_total - settled_at_issuance
        ),
        "finalization_path_awaiting_settlement": float(
            len(grades) - settled_total
        ),
        "amendment_count": float(
            sum(
                len(json.loads(row["amendments"] or "[]"))
                for row in grades
            )
        ),
    }
    with store.durable().transaction() as tx:
        for metric, value in sorted(metrics.items()):
            tx.execute(
                GRADE_STATEMENTS["insert_run_metric"],
                run_id=run_id,
                metric=metric,
                value=value,
            )
    return metrics


def evaluate_grade_alerts(
    run_id: str, *, store: Store | None = None
) -> tuple[GradeAlert, ...]:
    """The grading alerts that fire on the run's current ledger (TC-GRADE-24), each checked on its
    own condition:

    - **`incomplete_grades_outstanding`** — current grades still `incomplete` past
      their settlement pressure: the run has completed, or the review window has
      lapsed over them (`FR-GRADE-07`'s operator routing is actionable, not a dead
      end — the rescan is late and the operator hears it);
    - **`provisional_grades_past_window`** — current grades still `provisional` with
      the window lapsed while the run is still running: the settlement pass that
      should have reached them has not (a lapsed window with no recompute since is
      exactly the shape a scheduler gap produces).

    A healthy run — nothing outstanding past its pressure — fires nothing."""
    resolved = _signal_store(run_id, store)
    service = GradingService(resolved)
    run = service._run_row(run_id)
    surface = service._policy_surface(
        resolved.package(run["package_id"]),
        run["package_id"],
        run["package_version_id"],
    )
    window_hours = surface["policy"].review_window_hours
    now = _parse_timestamp(_now()) or datetime.now(timezone.utc)
    cohort = resolved.cohort(run["cohort_id"])
    grades = [
        dict(row)
        for row in cohort.query(
            GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run_id
        )
    ]

    def _past(row: dict[str, Any]) -> bool:
        if run["status"] == STATUS_COMPLETE:
            return True
        if window_hours is None:
            return False
        issued = _parse_timestamp(row["computed_at"])
        return issued is not None and (now - issued) >= timedelta(hours=window_hours)

    alerts: list[GradeAlert] = []
    outstanding = [
        row
        for row in grades
        if row["state"] == STATE_INCOMPLETE and _past(row)
    ]
    if outstanding:
        alerts.append(
            GradeAlert(
                kind="incomplete_grades_outstanding",
                run_id=run_id,
                count=len(outstanding),
                detail="incomplete grades outstanding past settlement ("
                + ", ".join(sorted(row["submission_id"] for row in outstanding))
                + ") — the operator rescan is late (FR-GRADE-07)",
            )
        )
    stale_provisional = [
        row
        for row in grades
        if run["status"] != STATUS_COMPLETE
        and window_hours is not None
        and row["state"] == STATE_PROVISIONAL
        and _past(row)
    ]
    if stale_provisional:
        alerts.append(
            GradeAlert(
                kind="provisional_grades_past_window",
                run_id=run_id,
                count=len(stale_provisional),
                detail="provisional grades past the review window with no "
                "settlement pass since ("
                + ", ".join(sorted(row["submission_id"] for row in stale_provisional))
                + ") — a settlement pass is due",
            )
        )
    return tuple(alerts)
