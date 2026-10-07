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

**Arm (c) is the review-window regrade, under the decided rule (2026-10-07): recovery does
not touch the review window.** Recovery restores persisted state and never mutates it — the
review window after recovery is exactly what it was at crash time. So the regrade applies
`FR-GRADE-10`'s settlement to the window *as it was*: the policy's `review_window_hours`
stays 24, the grades' window anchor (`computed_at`) stays the original issuance, and no new
revision is minted — a settlement in place, never a restarted, extended or re-armed window.
The case fails on each of those mutations. Verified empirically before writing (issue #378's
decided-rule instruction): the landed `recover` satisfies the rule, so the arm is green and
carries no `writtenahead` marker.

**The boundary clause resolves outside recovery's door.** A `complete` run settles through
`FR-GRADE-10`'s first automatic path — run completion — regardless of the window operator
(`_settlement_state` checks `run_complete` before the lapse comparison), so at clock exactly
24 h recovery cannot distinguish strict `>` from `<=`; whichever operator `FR-GRADE-10`
declares is observable only through the direct M-GRADE pass, not through `FR-PIPE-07`.

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
from aeh.grade import open_grade
from aeh.orch import ORCH_LEASE_SECONDS, Orchestrator
from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import Statement, open_store
from tests.support.clock import FrozenClock
from tests.support.grade_vocabulary import grade_rows, write_criterion_scores
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


def _recover_without_a_clock(store: Any) -> Any:
    """Recovery through the real pipeline entry, exactly as a crashed-into operator runs it.

    `recover(store)` with no clock argument: the review window runs on wall time (the grade
    service's clock), so the plain call is the honest one — the (c) arm advances only the wall
    clock and asserts nothing about `finalized_at`, which recovery's own clock stamps.
    """
    return require(PIPE_MODULE, "recover", issue=ISSUE)(store)


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


# --- TC-PIPE-07 (c) ------------------------------------------------------------------------


WINDOW_HOURS = 24
PACKAGE = "pkg-orch"


@pytest.fixture
def complete_run_past_window(tmp_data_dir):
    """A `complete` run holding provisional grades whose `WINDOW_HOURS` window lapsed during
    the downtime — the world of TC-PIPE-07 (c).

    The grades are issued while the run is still open, so they read `provisional` under the
    declared 24-hour window; the run row then flips to `complete` with no settling pass after
    it (the crash: the process recorded completion and died before `compute_all` would have
    settled them), and the clock advances 25 hours. The `FrozenClock` drives the grade service's
    `clock` — a callable returning an ISO timestamp — for issuance and for the wall-time lapse;
    `recover` itself builds its grading pass on the default wall clock, which touches only
    `finalized_at`, a column the oracle deliberately does not assert.
    """
    clock = FrozenClock()
    tick = lambda: clock.now().isoformat()  # noqa: E731 — the service wants a str
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, version = seed_run(
            store, submissions=SUBMISSIONS, criteria=CRITERIA,
        )
        catalog = PackageCatalog(store.package(PACKAGE), package_id=PACKAGE)
        catalog.set_grade_policy(
            version, GradePolicy(combination="weighted_sum", review_window_hours=WINDOW_HOURS)
        )
        cohort = store.cohort(ORCH_COHORT_ID)
        write_criterion_scores(cohort, [(s, "C1", "B2", 7.0, "auto") for s in SUBMISSIONS])
        open_grade(store, clock=tick).compute_all(run_id)
        assert catalog.grade_policy(version).review_window_hours == WINDOW_HOURS, (
            "precondition: the declared 24-hour window did not persist — the grades' "
            "provisional state below would then mean 'no window declared', not 'window open'"
        )
        before = [dict(r) for r in grade_rows(cohort) if r["is_current"]]
        assert before and all(r["state"] == "provisional" for r in before), (
            "precondition: the fixture's grades did not issue provisional under the open "
            f"window: {[(r['submission_id'], r['state']) for r in before]}"
        )
        with cohort.transaction() as tx:
            tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=run_id)
        clock.advance(25 * 3600)
        yield store, run_id, version, before
    finally:
        store.close()


def test_tc_pipe_07_a_complete_run_with_a_lapsed_window_is_regraded_without_touching_the_window(
        complete_run_past_window):
    """Arm (c) — `runs_regraded` contains the run, every grade is `final`, and the review
    window is exactly what it was at crash time (the decided rule, 2026-10-07).

    The plan's oracle is the first two sentences. The rest is the rule the case exists to
    pin: recovery restores persisted state and never mutates it, so the regrade settles the
    *lapsed* window — policy hours unchanged, the grades' window anchor (`computed_at`)
    unchanged, no new revision (a fresh revision would earn a fresh window, `_settlement_state`'s
    fresh-issuance anchor — that is the re-arm this arm refuses). A recovery that restarted,
    extended or re-armed the window fails here even if its report looks right.
    """
    store, run_id, version, before = complete_run_past_window
    cohort = store.cohort(ORCH_COHORT_ID)
    catalog = PackageCatalog(store.package(PACKAGE), package_id=PACKAGE)

    report = _recover_without_a_clock(store)

    assert run_id in report.runs_regraded, (
        f"recover regraded {list(report.runs_regraded)} and not {run_id!r}, whose grades sat "
        "provisional on a complete run past a lapsed 24-hour window (FR-PIPE-07's third step "
        "exists because nothing else wakes up to settle them)"
    )
    after = [dict(r) for r in grade_rows(cohort) if r["is_current"]]
    assert {r["submission_id"] for r in after} == {r["submission_id"] for r in before} and all(
        r["state"] == "final" for r in after
    ), (
        f"the regraded grades read {[(r['submission_id'], r['state']) for r in after]} — every "
        "grade must settle `final` at the lapse of the window (FR-GRADE-10, TC-PIPE-07 (c))"
    )
    assert catalog.grade_policy(version).review_window_hours == WINDOW_HOURS, (
        "recovery altered the review window's policy: grade_policy.review_window_hours left "
        f"{catalog.grade_policy(version).review_window_hours!r}, entered "
        f"{WINDOW_HOURS!r} — recovery does not touch the window (decided rule)"
    )
    anchor_before = {r["submission_id"]: r["computed_at"] for r in before}
    anchor_after = {r["submission_id"]: r["computed_at"] for r in after}
    assert anchor_after == anchor_before, (
        f"recovery re-anchored the window: computed_at {anchor_before} became {anchor_after} — "
        "a recovery that restarts the window at its own clock mints the grades a fresh 24 "
        "hours they never earned (decided rule)"
    )
    revisions_before = {r["submission_id"]: r["revision"] for r in before}
    revisions_after = {r["submission_id"]: r["revision"] for r in after}
    assert revisions_after == revisions_before, (
        f"recovery minted a new grade revision: {revisions_before} became {revisions_after} — "
        "a fresh revision earns a fresh window, so re-arming by re-issuing is the same "
        "mutation under another name (decided rule)"
    )

    again = _recover_without_a_clock(store)
    assert again.runs_regraded == () and not again.runs_resumed and again.leases_reclaimed == 0, (
        f"a second recovery acted again: {again} — recovery restores persisted state once and "
        "a repeat pass must find nothing to do"
    )
    assert [dict(r) for r in grade_rows(cohort) if r["is_current"]] == after, (
        "a second recovery rewrote the grade rows"
    )


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
