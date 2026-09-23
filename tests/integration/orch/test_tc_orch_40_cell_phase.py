"""`TS-85` (issue #379) — `TC-ORCH-40`: `mark_cell_phase` is idempotent per cell and phase, and
refuses a phase outside the declared vocabulary (`FR-ORCH-28`, `CT-ORCH-24`).

| Steps | Expected |
|---|---|
| `mark_cell_phase(tx, R,S,C,'integrity_pre',2)` twice; then `'aggregated',3`; then `'aggregated',5`; then `'bogus',1`; then purge cohort | one row per (cell, phase); the `aggregated` row holds `units_consumed = 5`; `'bogus'` is rejected and surfaces as an error; after purge, zero `cell_phase` rows |

**Why idempotence is the requirement.** `CT-ORCH-24` says `cell_phase` is written only by
`mark_cell_phase`, idempotently (`INSERT OR REPLACE` on the PK). The phase row is what makes
`M-PIPE`'s hooks resume-safe — `FR-ORCH-29` re-offers a cell whose terminal score-unit count
exceeds the recorded `units_consumed` — so a second write that *appended* rather than replaced
would make a recovered run look like it had aggregated twice, and one that *ignored* the later
call would freeze `units_consumed` at the first pass's figure and re-offer the cell forever.
The `3` then `5` sequence is exactly that second failure: the row must end at 5.

**The vocabulary is enforced twice, and this case pins the outer one.** The table carries
`CHECK (phase IN ('integrity_pre','integrity_post','aggregated'))` (`orch.py:667`) and
`mark_cell_phase` pre-checks the same vocabulary before it writes. Defence in depth, and the
pre-check fires first.

**A divergence reported rather than pinned.** The plan's expected column says `'bogus'`
"surfaces as `WorkLedgerError`". The shipped pre-check raises a bare **`ValueError`**. That is a
real inconsistency — `WorkLedgerError` is this module's declared error family, and a caller
catching it would miss this refusal — but which side moves is not a test's call to make, so this
case asserts the behaviour both readings agree on (the write is refused, the message names the
declared vocabulary, and no row is left behind) and #379 reports the type question. Pinning
`ValueError` here would cement the divergence; pinning `WorkLedgerError` would redden the suite
over a one-line decision nobody has taken yet.

**The purge arm is not implemented here.** `store.purge_cohort` refuses a cohort that is not
promoted to Tier D (`PurgePreconditionError`: it gates on `audit_record`, `label` and
`criterion_stats` rows), so "then purge cohort" needs M-STATS/M-REVIEW's `promote` run first.
That is real setup this case does not build, and `TC-STORE-10` already owns the purge sweep
itself. Named in #379's PR rather than approximated — a purge that refused would leave the
`cell_phase` rows in place and the arm would pass for the wrong reason.
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
from aeh.orch import Orchestrator
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "S01"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

#: The declared composition phases (`orch.py:667`'s CHECK, and FR-ORCH-28's vocabulary).
DECLARED_PHASES = ("integrity_pre", "integrity_post", "aggregated")


@pytest.fixture
def cell_world(tmp_data_dir):
    """A real run over a real store — `cell_phase` is a cohort-tier table."""
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        yield store, run_id, Orchestrator(store)
    finally:
        store.close()


def _phases(store: Any, run_id: str) -> dict[str, int]:
    return {
        str(row["phase"]): int(row["units_consumed"])
        for row in store.cohort(ORCH_COHORT_ID).query(
            Statement(
                "SELECT phase, units_consumed FROM cell_phase WHERE run_id = :run_id "
                "AND submission_id = :submission_id AND criterion_id = :criterion_id"
            ),
            run_id=run_id, submission_id=SUBMISSION, criterion_id=CRITERION,
        )
    }


def _row_count(store: Any, run_id: str) -> int:
    return int(
        store.cohort(ORCH_COHORT_ID).query(
            Statement("SELECT COUNT(*) AS n FROM cell_phase WHERE run_id = :run_id"),
            run_id=run_id,
        )[0]["n"]
    )


# --- TC-ORCH-40 ----------------------------------------------------------------------------


def test_tc_orch_40_marking_the_same_phase_twice_leaves_one_row(cell_world):
    """`integrity_pre` twice → one row, not two.

    The PK is `(run_id, submission_id, criterion_id, phase)` and the write is
    `INSERT OR REPLACE`, so a second mark of the same phase replaces rather than appends. A
    duplicate row would make a resumed run look like it ran the gate twice.
    """
    store, run_id, orchestrator = cell_world
    handle = store.cohort(ORCH_COHORT_ID)

    with handle.transaction() as tx:
        orchestrator.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "integrity_pre", 2)
        orchestrator.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "integrity_pre", 2)

    assert _phases(store, run_id) == {"integrity_pre": 2}, (
        f"marking one phase twice produced {_phases(store, run_id)}; CT-ORCH-24 writes it "
        "idempotently, one row per (cell, phase)"
    )
    assert _row_count(store, run_id) == 1


def test_tc_orch_40_a_later_mark_replaces_the_units_consumed(cell_world):
    """`aggregated` at 3 then at 5 → one row holding **5**.

    This is the resume guard. `FR-ORCH-29` re-offers a cell whose terminal score-unit count
    exceeds the recorded `units_consumed`, so a row frozen at the first pass's 3 would re-offer
    the cell on every pass forever — and an implementation that appended instead would report
    two aggregations of one cell.
    """
    store, run_id, orchestrator = cell_world
    handle = store.cohort(ORCH_COHORT_ID)

    with handle.transaction() as tx:
        orchestrator.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "aggregated", 3)
    with handle.transaction() as tx:
        orchestrator.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "aggregated", 5)

    assert _phases(store, run_id) == {"aggregated": 5}, (
        f"the aggregated phase holds {_phases(store, run_id)}; the later mark must replace the "
        "earlier one's units_consumed (FR-ORCH-28), or FR-ORCH-29 re-offers the cell forever"
    )


def test_tc_orch_40_two_phases_of_one_cell_are_separate_rows(cell_world):
    """One row *per phase*, not one per cell: `integrity_pre` and `aggregated` coexist.

    The PK carries `phase`, so a cell that has been gated and then aggregated holds both facts.
    An implementation keyed on the cell alone would lose the first when the second landed.
    """
    store, run_id, orchestrator = cell_world
    handle = store.cohort(ORCH_COHORT_ID)

    with handle.transaction() as tx:
        orchestrator.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "integrity_pre", 2)
        orchestrator.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "aggregated", 5)

    assert _phases(store, run_id) == {"integrity_pre": 2, "aggregated": 5}, (
        f"the cell holds {_phases(store, run_id)}; the two phases are separate facts about one "
        "cell and the PK carries the phase to keep them both"
    )


def test_tc_orch_40_an_undeclared_phase_is_refused_and_writes_nothing(cell_world):
    """`'bogus'` is refused, the message names the declared vocabulary, and no row survives.

    The error *type* is deliberately not asserted: the plan says `WorkLedgerError`, the shipped
    pre-check raises `ValueError`, and #379 reports that rather than a test picking a winner.
    What both readings agree on — refusal, a legible message, and nothing written — is asserted
    in full.
    """
    store, run_id, orchestrator = cell_world
    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        orchestrator.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "integrity_pre", 2)
    before = _phases(store, run_id)

    with pytest.raises(Exception) as caught:
        with handle.transaction() as tx:
            orchestrator.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "bogus", 1)

    message = str(caught.value)
    assert "bogus" in message, (
        f"the refusal does not name the rejected phase: {message!r}"
    )
    assert any(phase in message for phase in DECLARED_PHASES), (
        f"the refusal names no declared phase, so a caller cannot see what was allowed: "
        f"{message!r}. The vocabulary is {DECLARED_PHASES}"
    )
    assert _phases(store, run_id) == before, (
        f"the refused write changed the cell's phases: {before} became "
        f"{_phases(store, run_id)}"
    )
    assert "bogus" not in _phases(store, run_id)
