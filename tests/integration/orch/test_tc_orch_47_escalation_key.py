"""`TS-85` (issue #379) — `TC-ORCH-47`: the escalation key names its run (`FR-ORCH-34`,
`CT-ORCH-26`).

| Arm | Key | Expected |
|---|---|---|
| a | `(RA, S1, C1)` | units enqueued for RA only |
| b | `(S1, C1)`, one open run RA | units enqueued for RA, and a deprecation is recorded (warning) |
| c | `(S1, C1)`, open runs RA **and** RB | `WorkLedgerError`, and the caller's transaction rolls back with zero escalation units |

**What the run-scoped key prevents** (`CT-ORCH-C26`): escalations for `(RA,S1,C1)` and
`(RB,S1,C1)` must coexist as distinct units. Drop `run_id` from the key and RB's escalation is
swallowed as a duplicate of RA's — two cohorts marked by one panel widening, and the second
run's widened panel silently never exists. That coexistence is asserted here as its own case,
because arm (a) alone does not reach it.

**Arm (b)'s "a deprecation is recorded (warning)" is NOT implemented, and this is reported
rather than asserted away.** The shipped `enqueue_escalation` documents the two-element form
as deprecated in its docstring and raises `WorkLedgerError` when the form is ambiguous, but it
emits no `DeprecationWarning` and writes no deprecation row — `src/aeh/orch.py` contains no
`warnings.warn` at all. So the arm asserts the half that *is* shipped (the form resolves to
the single open run and enqueues there), and #379 reports the missing signal. Asserting
`pytest.warns(DeprecationWarning)` would put a permanently red test in a suite whose
implementing issues are all closed; asserting nothing would let the plan claim coverage that
does not exist.

**Arm (c)'s rollback is asserted over the caller's transaction, not just the raise.** The
requirement is `CT-ORCH-08`'s atomicity read across the boundary: the widened units are
written into the transaction the CALLER opened. A refusal that left rows behind after the
caller's `with` block unwound would satisfy `pytest.raises` and still corrupt the ledger.

**Isolation: rung 2** — real store, real Tier P package, real cohort ledger.
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
from aeh.orch import Orchestrator, WorkLedgerError
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "S1"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

_ESCALATION_UNITS = Statement(
    "SELECT run_id, COUNT(*) AS n FROM work_unit WHERE origin = 'escalation' "
    "AND submission_id = :submission_id AND criterion_id = :criterion_id "
    "GROUP BY run_id ORDER BY run_id"
)


@pytest.fixture
def two_runs(tmp_data_dir):
    """RA and RB, both open over one cohort, each holding the pair's score panel."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_a, version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        orchestrator.enumerate_units(run_a)
        run_b = orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())
        orchestrator.enumerate_units(run_b)
        yield store, orchestrator, run_a, run_b
    finally:
        store.close()


def _escalations(store: Any) -> dict[str, int]:
    """Escalation-origin unit counts for the pair, per run."""
    return {
        str(row["run_id"]): int(row["n"])
        for row in store.cohort(ORCH_COHORT_ID).query(
            _ESCALATION_UNITS, submission_id=SUBMISSION, criterion_id=CRITERION,
        )
    }


# --- TC-ORCH-47 -----------------------------------------------------------------------------


def test_tc_orch_47_arm_a_the_three_element_key_widens_only_its_own_run(two_runs):
    """Arm (a) — `(RA, S1, C1)` enqueues for RA and leaves RB untouched.

    RB exists, holds the same `(submission, criterion)` pair, and is open. That is what makes
    "only RA" an assertion rather than a tautology.
    """
    store, orchestrator, run_a, run_b = two_runs

    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        reports = orchestrator.enqueue_escalation(tx, (run_a, SUBMISSION, CRITERION))

    assert len(reports) == 1, (
        f"the run-scoped key returned {len(reports)} report(s); it widens ONE run's panel"
    )
    counts = _escalations(store)
    assert counts.get(run_a, 0) > 0, (
        f"no escalation unit was written for RA: {counts}. The key names the run whose panel "
        "widens"
    )
    assert run_b not in counts, (
        f"RB's panel was widened by an escalation keyed to RA: {counts}. FR-ORCH-34 scopes "
        "the escalation to the run its key names"
    )


def test_tc_orch_47_arm_b_the_deprecated_pair_key_resolves_a_single_open_run(tmp_data_dir):
    """Arm (b) — `(S1, C1)` with exactly one open run resolves to it and enqueues there.

    The deprecation *signal* is not asserted: the shipped module emits none (see the file
    docstring). What is asserted is that the compatibility path still works, which is the
    reason the form is deprecated rather than removed.
    """
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_a, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        orchestrator.enumerate_units(run_a)

        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            reports = orchestrator.enqueue_escalation(tx, (SUBMISSION, CRITERION))

        assert len(reports) == 1
        counts = _escalations(store)
        assert counts.get(run_a, 0) > 0, (
            f"the deprecated pair key resolved to no run: {counts}. With exactly one open run "
            "holding the pair, the form must still resolve (FR-ORCH-34's compatibility clause)"
        )
    finally:
        store.close()


def test_tc_orch_47_arm_c_an_ambiguous_pair_key_is_refused(two_runs):
    """Arm (c) — two open runs hold the pair: `WorkLedgerError`, naming both runs.

    Resolving to "whichever run sorted first" would widen a panel in a run the caller was not
    thinking about, and nothing downstream could tell that had happened.
    """
    store, orchestrator, run_a, run_b = two_runs

    with pytest.raises(WorkLedgerError) as caught:
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orchestrator.enqueue_escalation(tx, (SUBMISSION, CRITERION))

    message = str(caught.value)
    assert run_a in message and run_b in message, (
        f"the refusal does not name the runs that made the key ambiguous: {message!r}"
    )
    assert "run_id" in message, (
        f"the refusal does not tell the caller which key to use instead: {message!r}"
    )


def test_tc_orch_47_arm_c_the_callers_transaction_rolls_back_with_zero_units(two_runs):
    """Arm (c)'s second half — after the refusal, the ledger holds no escalation unit.

    `CT-ORCH-08` puts the widened units inside the caller's transaction. A refusal that had
    already written some of them, or that left a partial panel behind when the caller's block
    unwound, would be exactly the partial write the atomicity clause forbids.
    """
    store, orchestrator, _run_a, _run_b = two_runs
    assert _escalations(store) == {}, "the fixture must start with no escalation units"

    with pytest.raises(WorkLedgerError):
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orchestrator.enqueue_escalation(tx, (SUBMISSION, CRITERION))

    assert _escalations(store) == {}, (
        f"the refused enqueue left escalation units behind: {_escalations(store)}"
    )


def test_tc_orch_47_ct_orch_c26_two_runs_escalations_coexist_as_distinct_units(two_runs):
    """`CT-ORCH-C26` — `(RA,S1,C1)` and `(RB,S1,C1)` both widen, as separate units.

    The case that breaks if `run_id` leaves the work-id key: RB's escalation would be
    swallowed as a duplicate of RA's — `INSERT OR IGNORE` on an identical id — and RB's panel
    would silently never widen. Arm (a) cannot see this, because it only ever escalates one
    run; the counts have to be taken after *both*.
    """
    store, orchestrator, run_a, run_b = two_runs

    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        orchestrator.enqueue_escalation(tx, (run_a, SUBMISSION, CRITERION))
    after_a = _escalations(store)

    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        orchestrator.enqueue_escalation(tx, (run_b, SUBMISSION, CRITERION))
    after_both = _escalations(store)

    assert after_a.get(run_b, 0) == 0, "RB had units before it was escalated"
    assert after_both.get(run_a, 0) == after_a.get(run_a, 0), (
        f"escalating RB changed RA's unit count: {after_a} became {after_both}"
    )
    assert after_both.get(run_b, 0) > 0, (
        f"RB's escalation wrote no unit: {after_both}. Its units carry the same "
        "(submission, criterion, judge) as RA's, so a work id that omitted run_id would make "
        "them collide and INSERT OR IGNORE would drop them (CT-ORCH-C26)"
    )


def test_tc_orch_47_a_key_no_run_holds_a_panel_for_is_refused_before_any_write(two_runs):
    """A key naming a run that holds no panel for the pair raises before anything is written.

    The guard that keeps the arms above honest: without it, an `enqueue_escalation` that
    quietly created the panel it was asked to widen would satisfy arm (a) by inventing units
    rather than widening existing ones.
    """
    from aeh.orch import EscalationPlanError

    store, orchestrator, run_a, _run_b = two_runs

    with pytest.raises(EscalationPlanError) as caught:
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orchestrator.enqueue_escalation(tx, (run_a, SUBMISSION, "C-absent"))

    assert "C-absent" in str(caught.value)
    assert _escalations(store) == {}
