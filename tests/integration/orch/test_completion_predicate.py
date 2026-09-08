"""`TC-ORCH-22` — the completion predicate: a run is complete only when it holds **no
pending units and no in-flight unit that could spawn an escalation**. Test plan §5.7;
`FR-ORCH-12`.

Oracle: **state-based** — the predicate is read off the ledger's own state, not off a
counter of completed units: three states are probed on one run (pending work; every unit
claimed and one in flight; every unit done), and the boundary sits between the second and
third. The second state is the discriminating one: a completion predicate that counted
units — "nothing left pending" — would declare the run complete while a scoring judgment
is still in flight, and that judgment is exactly the one whose disagreement can spawn an
escalation (#60's) and add work to the run after its "completion".

**Written ahead of #62** (dispatch isolation, concurrency and `ProgressReport`, which
owns `FR-ORCH-12`). Registered in `WRITTEN_AHEAD_BLOCKERS` keyed on
`aeh.orch:Orchestrator.progress` — design §3.7's Interfaces member that reports run
state; it appears in no earlier story's acceptance criteria, and the predicate lives on
its result.

**Interface this case assumes of #62**, listed so it is reconciled deliberately (the
`record_run_start` precedent):

| Name | Status |
|---|---|
| `Orchestrator.progress(run_id)` | design §3.7 Interfaces — the run-state report |
| the report's completion flag, read here as `.complete` | **assumed here** — `FR-ORCH-12`'s predicate surfaced on the report; if #62 names it differently the rename here is one line |
| `Orchestrator.lease(worker_id, stage, n)` | design §3.7 Interfaces (#58's) — the probe that puts a unit in flight |

**Disclosed stand-ins.** Marking units `done` writes the ledger directly: the complete
surface that does this in production is #58's, and the rows written are exactly the rows
it will write (`work_unit.status`). No production module may write them (`CT-ORCH-17`);
this is test scaffolding standing in for that writer.

**Isolation: rung 2** — real store, real Tier P package, real cohort ledger.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.impl import ORCH_MODULE, require
from tests.support.orch_run import seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#62"

_SUBMISSIONS = ("SYN-001",)
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)


def _set_status(cohort_handle, run_id: str, work_id: str, status: str) -> None:
    with cohort_handle.transaction() as tx:
        tx.execute(
            "UPDATE work_unit SET status = :s WHERE work_id = :w AND run_id = :r",
            s=status,
            w=work_id,
            r=run_id,
        )


def _ids(cohort_handle, run_id: str, stage: str) -> list[str]:
    return [
        row["work_id"]
        for row in cohort_handle.query(
            "SELECT work_id FROM work_unit WHERE run_id = :r AND stage = :s "
            "ORDER BY work_id",
            r=run_id,
            s=stage,
        )
    ]


def test_tc_orch_22_completion_waits_for_in_flight_units_that_could_escalate(
    tmp_data_dir,
):
    """`TC-ORCH-22` — not complete while units are pending; not complete while a scoring
    unit is in flight (it could spawn an escalation) even though nothing is pending;
    complete only when every unit is done."""
    require(ORCH_MODULE, "Orchestrator.progress", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orchestrator.enumerate_units(run_id)
        cohort = store.cohort("c-2026-7B-orch")
        extract_id = _ids(cohort, run_id, "extract")[0]
        score_id = _ids(cohort, run_id, "score")[0]

        # State 1: work is pending. Not complete.
        report = orchestrator.progress(run_id)
        assert not report.complete, (
            "the run reported complete with units still pending — the predicate saw "
            "less than the ledger holds"
        )

        # State 2: the extraction is done and its scoring unit is in flight — nothing is
        # pending any more. A unit that could spawn an escalation (a scoring judgment
        # whose disagreement escalates, #60's) is still open, so the run is not complete.
        _set_status(cohort, run_id, extract_id, "done")
        claimed = orchestrator.lease("worker-a", "score", 10)
        assert [unit.work_id for unit in claimed] == [score_id], (
            "the fixture drifted: the scoring unit must be the one thing left, so the "
            "in-flight state below is exactly the predicate's boundary"
        )
        report = orchestrator.progress(run_id)
        assert not report.complete, (
            "the run reported complete with a scoring unit in flight — 'no pending "
            "units and no in-flight unit that could spawn an escalation' is the "
            "predicate, and a completion that fires here closes the run over a "
            "judgment that can still add work to it"
        )

        # State 3: the last unit is done. Now — and only now — complete.
        _set_status(cohort, run_id, score_id, "done")
        report = orchestrator.progress(run_id)
        assert report.complete, (
            "every unit is done and none is in flight, and the run still does not "
            "report complete — the predicate holds the run open over nothing"
        )
    finally:
        store.close()
