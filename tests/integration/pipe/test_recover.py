"""`TS-84` (issue #378) — `TC-PIPE-07`: what `recover` reclaims, resumes and regrades
(`FR-PIPE-07`, gap-fix test plan §5 / §6).

| Arm | Precondition | Expected |
|---|---|---|
| (a) | a leased unit whose lease expired at `T0+10 min`, clock at `T0+11 min` | `leases_reclaimed = 1` and the unit is `pending` |
| (b) | a `running` run with pending units after a simulated crash | `runs_resumed` contains the run |
| (c) | a `complete` run, `review_window_hours = 24`, grades provisional, clock advanced 25 h | `runs_regraded` contains the run and every grade is `final` |
| (d) | a clean store | all three report fields empty or zero, and no row changes |

**`FR-PIPE-07`**: `recover(store)` calls `Orchestrator.sweep_expired_leases()`, then
`Orchestrator.resume()`, then `GradingService.compute_all` for every `complete` run whose
grades are not all final, and returns a `RecoveryReport`.

**Arm (d) is the one that stops the others passing for the wrong reason.** A `recover` that
reclaimed and resumed unconditionally satisfies (a) and (b) and is badly wrong — it would
resume runs an operator deliberately paused. So (d) asserts the *absence* of action on a clean
store, and it compares row counts before and after rather than trusting the report about itself.

**Arm (c) is NOT implemented here, and that is deliberate.** It needs a package whose grade
policy declares `review_window_hours = 24` and a run graded to `provisional`, and the grade
policy surface is one I have not verified against the code. Writing assertions against a surface
I have only read about in the plan is exactly the defect that sank #377's first suite, so the
arm is named here and in #378's PR rather than guessed at. `FR-PIPE-07`'s regrade clause is
therefore **not covered** by this file, and the RTM should not claim it is.

**The lease clock is the store's monotonic counter, not wall time.** `sweep_expired_leases`
compares `ticks >= lease_expires_ticks` (`orch.py:4363`), so the expiry is produced by advancing
an injected `FrozenClock` past `ORCH_LEASE_SECONDS` on an `Orchestrator(store, clock=...)` — the
idiom `TC-ORCH-05` already uses (`tests/integration/orch/test_leasing.py:122`). A wall-clock
`FrozenClock` alone would not expire anything, which is why `recover`'s own `clock=` argument is
about the review window rather than about leases.

**Written ahead of implementation: yes** — `aeh.pipeline` is #365's. Every body probes it first
with `require(...)`. The *setup* uses only verified surfaces and is exercised independently of
the probe (see #378's PR).
"""

from __future__ import annotations

from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.orch import ORCH_LEASE_SECONDS, Orchestrator
from aeh.store import Statement, open_store
from tests.support.clock import FrozenClock
from tests.support.impl import PIPE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

ISSUE = "#365"

SUBMISSIONS = ("S01", "S02")
CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)

#: The cohort tables a recovery could disturb. Arm (d) compares all of them.
WATCHED_TABLES = ("work_unit", "run", "criterion_score", "submission_grade")


def _units_by_status(store: Any, run_id: str) -> dict[str, int]:
    rows = store.cohort(ORCH_COHORT_ID).query(
        Statement("SELECT status, COUNT(*) AS n FROM work_unit WHERE run_id = :run_id "
                  "GROUP BY status"),
        run_id=run_id,
    )
    return {str(row["status"]): int(row["n"]) for row in rows}


def _row_counts(store: Any) -> dict[str, int]:
    handle = store.cohort(ORCH_COHORT_ID)
    return {
        table: int(handle.query(Statement(f"SELECT COUNT(*) AS n FROM {table}"))[0]["n"])  # noqa: S608
        for table in WATCHED_TABLES
    }


def _run_status(store: Any, run_id: str) -> str:
    rows = store.cohort(ORCH_COHORT_ID).query(
        Statement("SELECT status FROM run WHERE run_id = :run_id"), run_id=run_id,
    )
    return str(rows[0]["status"])


@pytest.fixture
def abandoned_lease(tmp_data_dir):
    """A run with one expired lease: the injury a SIGKILLed worker leaves.

    The expiry is produced the way `TC-ORCH-05` produces it — an injected `FrozenClock` advanced
    past `ORCH_LEASE_SECONDS` on the orchestrator that took the lease — because the sweeper
    compares the store's monotonic counter, not wall time.
    """
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store, submissions=SUBMISSIONS, criteria=CRITERIA,
        )
        clock = FrozenClock()
        orchestrator = Orchestrator(store, clock=clock)
        orchestrator.start(run_id)
        leased = orchestrator.lease("worker-dead", "extract", 1)
        assert len(leased) == 1, (
            f"the fixture leased {len(leased)} units, not 1 — arm (a) counts exactly one "
            "reclaimed lease"
        )
        clock.advance(ORCH_LEASE_SECONDS)
        yield store, run_id, leased[0]
    finally:
        store.close()


# --- TC-PIPE-07 (a) ------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_07_an_expired_lease_is_reclaimed_and_the_unit_is_pending(abandoned_lease):
    """Arm (a) — `leases_reclaimed = 1`, and the unit is back to `pending`.

    Both halves: the report's figure, and the ledger it claims to describe. A `recover` that
    counted a reclaim it did not perform passes the first and fails the second.
    """
    recover = require(PIPE_MODULE, "recover", issue=ISSUE)
    store, run_id, unit = abandoned_lease
    assert _units_by_status(store, run_id).get("leased") == 1, (
        "precondition: the fixture's unit is not leased"
    )

    report = recover(store)

    assert report.leases_reclaimed == 1, (
        f"recover reports leases_reclaimed={report.leases_reclaimed!r}; one lease expired "
        f"{ORCH_LEASE_SECONDS}s ago (FR-PIPE-07 sweeps before it resumes)"
    )
    assert _units_by_status(store, run_id).get("leased", 0) == 0, (
        f"unit {unit.work_id[:12]} is still leased after recovery: "
        f"{_units_by_status(store, run_id)}. A lease nobody reclaims stalls the run forever"
    )
    assert _units_by_status(store, run_id).get("pending", 0) >= 1, (
        "the reclaimed unit did not return to pending, so nothing can claim it again"
    )


# --- TC-PIPE-07 (b) ------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_07_a_running_run_with_pending_units_is_resumed(abandoned_lease):
    """Arm (b) — `runs_resumed` contains the run.

    The same world as (a): a `running` run with work left is exactly what a crash leaves behind,
    and `FR-PIPE-07` resumes it after sweeping.
    """
    recover = require(PIPE_MODULE, "recover", issue=ISSUE)
    store, run_id, _unit = abandoned_lease
    assert _run_status(store, run_id) == "running", (
        f"precondition: the run is {_run_status(store, run_id)!r}, not running"
    )

    report = recover(store)

    assert run_id in report.runs_resumed, (
        f"recover resumed {list(report.runs_resumed)} and not {run_id!r}, which is running with "
        "pending units — the run a crashed process leaves behind"
    )


# --- TC-PIPE-07 (d) ------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_07_a_clean_store_is_left_alone(tmp_data_dir):
    """Arm (d) — nothing reclaimed, nothing resumed, nothing regraded, and no row changed.

    This arm is what stops (a) and (b) passing for a `recover` that acts unconditionally — one
    that reclaimed and resumed whatever it found would satisfy both and would also resume runs
    an operator deliberately paused. The oracle is the row counts, not the report's own account
    of itself.
    """
    recover = require(PIPE_MODULE, "recover", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store, submissions=SUBMISSIONS, criteria=CRITERIA,
        )
        before_counts = _row_counts(store)
        before_status = _run_status(store, run_id)
        before_units = _units_by_status(store, run_id)

        report = recover(store)

        assert report.leases_reclaimed == 0, (
            f"recover reclaimed {report.leases_reclaimed} leases on a store with none"
        )
        assert not report.runs_resumed, (
            f"recover resumed {list(report.runs_resumed)} on a store whose run was never "
            "started — a recovery that resumes unconditionally restarts work an operator stopped"
        )
        assert not report.runs_regraded, (
            f"recover regraded {list(report.runs_regraded)} on a store with no complete run"
        )
        assert _row_counts(store) == before_counts, (
            f"recovery changed row counts on a clean store: {before_counts} became "
            f"{_row_counts(store)}"
        )
        assert _run_status(store, run_id) == before_status
        assert _units_by_status(store, run_id) == before_units
    finally:
        store.close()
