"""`TS-85` (issue #379) — `TC-ORCH-41`: `ready_cells`' decision table (`FR-ORCH-29`).

The plan's eight rows, one test each, over one run holding one cell per row plus a second
run for row 8:

| Row | Extract units | Score units | Phases | `ready_cells(R,'integrity_pre')` | `ready_cells(R,'aggregate')` |
|---|---|---|---|---|---|
| 1 | 2 done | none | none | contains cell | empty |
| 2 | 1 done, 1 pending | none | none | empty | empty |
| 3 | 2 done | 3 done | `integrity_pre` | empty | contains cell |
| 4 | 2 done | 2 done, 1 leased | `integrity_pre` | empty | empty |
| 5 | 2 done | 3 done | `integrity_pre`, `aggregated(3)` | empty | empty |
| 6 | 2 done | 5 done | `integrity_pre`, `aggregated(3)` | empty | contains cell |
| 7 | 2 quarantined | none | none | contains cell | empty |
| 8 | row 3, but for run RB | — | — | RA query excludes RB's cell | RA query excludes RB's cell |

**What each row is actually discriminating**, because "contains cell" alone would be met by
several wrong implementations:

* **Rows 1 and 2** separate *terminal* from *enumerated*. An implementation that offered a
  cell as soon as any extract unit finished passes row 1 and fails row 2 — and row 2 is the
  one that matters, because the integrity gate reads the whole extraction.
* **Row 7** is row 1 with `quarantined` in place of `done`. A gate that waited for `done`
  would wait for a unit that will never produce evidence, and the cell would hang forever.
  This row is why `ready_cells` says *terminal*, not *complete*.
* **Rows 3, 5 and 6** are the count comparison, and 6 is the load-bearing one: `units_consumed`
  is recorded as a **number** rather than a flag precisely so a panel widened from three
  verdicts to five re-offers the cell. An `aggregated` flag passes rows 3 and 5 and fails 6.
* **Row 4** pins that a leased unit is not terminal. `leased` means a worker holds it; treating
  it as finished would aggregate over a panel that is still one verdict short.
* **Row 8** is the run scoping. Two runs over the same cohort hold cells with identical
  `(submission_id, criterion_id)` keys, and a query that grouped on the cell alone would
  return RB's work to RA's composition layer.

**Disclosed stand-in: the ledger rows are written directly.** A cell needs two extract units
and, by turns, three and five score units; enumeration produces exactly one of each per cell
(`by_stage={'extract': 1, 'score': 1}` per submission), and the widening to 3 and 5 is
`enqueue_escalation`'s — which brings the panel ladder, the criterion breaker and the
escalation budget with it, none of which `ready_cells` reads. The rows written here are the
rows those writers write (`work_unit`'s own columns, `cell_phase` through the shipped
`mark_cell_phase`), and the real escalation write path is `TC-ORCH-47`'s subject. No
production module may write these rows (`CT-ORCH-17`'s single-writership clause); this file is
test scaffolding standing in for that writer, the same disclosure
`tests/integration/orch/test_completion_predicate.py` carries.

**Isolation: rung 2** — real store, real Tier P package, real cohort ledger.
"""

from __future__ import annotations

from typing import Any, Sequence

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
from aeh.orch import CellKey, Orchestrator
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_run

pytestmark = pytest.mark.integration

CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

#: One submission per decision-table row, so the rows are independent cells of one run and a
#: single fixture covers the table. Row 8's cell is `ROW3`'s key under a second run.
ROWS = ("R1", "R2", "R3", "R4", "R5", "R6", "R7")

_INSERT_UNIT = Statement(
    "INSERT INTO work_unit (work_id, run_id, submission_id, criterion_id, stage, "
    "judge_id, origin, status, attempts) "
    "VALUES (:work_id, :run_id, :submission_id, :criterion_id, :stage, :judge_id, "
    "'base', :status, 0)"
)

_DELETE_UNITS = Statement("DELETE FROM work_unit WHERE run_id = :run_id")


def _write_units(
    store: Any, run_id: str, submission_id: str, stage: str, statuses: Sequence[str]
) -> None:
    """Give one cell exactly `statuses` units at `stage` — the row's precondition, verbatim."""
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        for index, status in enumerate(statuses):
            tx.execute(
                _INSERT_UNIT,
                work_id=f"w-{run_id[-8:]}-{submission_id}-{stage}-{index}",
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=CRITERION,
                stage=stage,
                judge_id=f"judge-{index}" if stage == "score" else None,
                status=status,
            )


def _mark(
    store: Any, orchestrator: Any, run_id: str, submission_id: str,
    phase: str, units_consumed: int,
) -> None:
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        orchestrator.mark_cell_phase(
            tx, run_id, submission_id, CRITERION, phase, units_consumed
        )


@pytest.fixture
def table_world(tmp_data_dir):
    """Run RA holding the seven single-run rows, and run RB holding row 8's cell.

    Enumeration's own units are cleared first: every row states its cell's units exactly, and
    leaving the enumerated pair in place would silently add a pending unit to each one — which
    would make rows 1 and 7 fail for a reason the table never named.
    """
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_a, version = seed_run(
            store, submissions=(*ROWS, "R8"), criteria=CRITERIA,
        )
        orchestrator.enumerate_units(run_a)
        run_b = orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())
        orchestrator.enumerate_units(run_b)
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute(_DELETE_UNITS, run_id=run_a)
            tx.execute(_DELETE_UNITS, run_id=run_b)
        yield store, orchestrator, run_a, run_b
    finally:
        store.close()


def _ready(orchestrator: Any, run_id: str, hook: str) -> tuple[CellKey, ...]:
    return orchestrator.ready_cells(run_id, hook)


# --- TC-ORCH-41, one test per decision-table row --------------------------------------------


def test_tc_orch_41_row_1_all_extraction_terminal_offers_the_integrity_gate(table_world):
    """Row 1 — 2 extract done, no score units, no phases: `integrity_pre` contains the cell.

    `aggregate` is empty for the reason the arithmetic gives and not by luck: the cell has
    **zero** score units, and a cell with no panel has nothing to aggregate. An implementation
    that read "terminal >= consumed" without first requiring `total` to be non-zero would offer
    every un-panelled cell to M-AGG on the first pass.
    """
    store, orchestrator, run_a, _run_b = table_world
    _write_units(store, run_a, "R1", "extract", ("done", "done"))

    assert CellKey("R1", CRITERION) in _ready(orchestrator, run_a, "integrity_pre"), (
        "a cell whose every extract unit is terminal and which carries no integrity_pre phase "
        "is exactly the integrity gate's moment (FR-ORCH-29)"
    )
    assert CellKey("R1", CRITERION) not in _ready(orchestrator, run_a, "aggregate"), (
        "the cell has no score units at all; offering it to the aggregate hook would ask "
        "M-AGG to compose a panel that does not exist"
    )


def test_tc_orch_41_row_2_one_pending_extract_unit_withholds_the_cell(table_world):
    """Row 2 — 1 done, 1 pending: **both** hooks empty.

    The discriminating row. "Some extraction finished" is not the gate's precondition; the
    gate reads the cell's whole extraction, so one outstanding unit withholds it. An
    implementation offering the cell on the first `done` passes row 1 and fails here.
    """
    store, orchestrator, run_a, _run_b = table_world
    _write_units(store, run_a, "R2", "extract", ("done", "pending"))

    assert CellKey("R2", CRITERION) not in _ready(orchestrator, run_a, "integrity_pre"), (
        "one extract unit is still pending; the integrity gate reads a COMPLETE extraction "
        "(FR-ORCH-29) and a partial read would judge the student on half their answer"
    )
    assert CellKey("R2", CRITERION) not in _ready(orchestrator, run_a, "aggregate")


def test_tc_orch_41_row_3_a_gated_cell_with_all_scores_terminal_is_ready_to_aggregate(
    table_world,
):
    """Row 3 — 2 extract done, 3 score done, `integrity_pre` recorded: `aggregate` contains it.

    And `integrity_pre` no longer does: the phase row is the record that the gate has already
    run, so re-offering the cell would run the gate twice on one extraction.
    """
    store, orchestrator, run_a, _run_b = table_world
    _write_units(store, run_a, "R3", "extract", ("done", "done"))
    _write_units(store, run_a, "R3", "score", ("done", "done", "done"))
    _mark(store, orchestrator, run_a, "R3", "integrity_pre", 2)

    assert CellKey("R3", CRITERION) not in _ready(orchestrator, run_a, "integrity_pre"), (
        "the cell carries an integrity_pre phase; re-offering it would run the gate a second "
        "time over the same extraction"
    )
    assert CellKey("R3", CRITERION) in _ready(orchestrator, run_a, "aggregate"), (
        "every score unit is terminal and the cell has never aggregated — FR-ORCH-29's "
        "aggregate hook"
    )


def test_tc_orch_41_row_4_a_leased_score_unit_is_not_terminal(table_world):
    """Row 4 — 2 score done, 1 **leased**: `aggregate` empty.

    `leased` means a worker holds the unit and its verdict is still coming. Counting it as
    finished would hand M-AGG a two-verdict panel when the run intends three — and a
    two-verdict panel is the one shape `FR-ORCH-10` forbids adjudicating.
    """
    store, orchestrator, run_a, _run_b = table_world
    _write_units(store, run_a, "R4", "extract", ("done", "done"))
    _write_units(store, run_a, "R4", "score", ("done", "done", "leased"))
    _mark(store, orchestrator, run_a, "R4", "integrity_pre", 2)

    assert CellKey("R4", CRITERION) not in _ready(orchestrator, run_a, "aggregate"), (
        "one score unit is leased, not terminal; aggregating now would compose over a panel "
        "one verdict short of the one the run enumerated"
    )
    assert CellKey("R4", CRITERION) not in _ready(orchestrator, run_a, "integrity_pre")


def test_tc_orch_41_row_5_an_aggregated_cell_with_no_new_verdicts_is_not_re_offered(
    table_world,
):
    """Row 5 — 3 score done and `aggregated(3)`: `aggregate` empty.

    Terminal equals consumed, so nothing has landed since the last composition. Without the
    comparison the cell would be re-offered on every dispatch pass for the life of the run.
    """
    store, orchestrator, run_a, _run_b = table_world
    _write_units(store, run_a, "R5", "extract", ("done", "done"))
    _write_units(store, run_a, "R5", "score", ("done", "done", "done"))
    _mark(store, orchestrator, run_a, "R5", "integrity_pre", 2)
    _mark(store, orchestrator, run_a, "R5", "aggregated", 3)

    assert CellKey("R5", CRITERION) not in _ready(orchestrator, run_a, "aggregate"), (
        "three verdicts are terminal and three were consumed; re-offering the cell would "
        "re-aggregate identical inputs on every pass"
    )


def test_tc_orch_41_row_6_a_widened_panel_re_offers_the_cell(table_world):
    """Row 6 — 5 score done against `aggregated(3)`: `aggregate` contains the cell again.

    The row the count exists for. `units_consumed` is a **number**, not a flag, so an
    escalation that widened a three-arm panel to five re-offers the cell with the two new
    verdicts in it. Rows 3 and 5 both pass against a boolean `aggregated` flag; this one does
    not, and a run whose escalations never recomposed would report the pre-escalation score.
    """
    store, orchestrator, run_a, _run_b = table_world
    _write_units(store, run_a, "R6", "extract", ("done", "done"))
    _write_units(
        store, run_a, "R6", "score", ("done", "done", "done", "done", "done")
    )
    _mark(store, orchestrator, run_a, "R6", "integrity_pre", 2)
    _mark(store, orchestrator, run_a, "R6", "aggregated", 3)

    assert CellKey("R6", CRITERION) in _ready(orchestrator, run_a, "aggregate"), (
        "five score units are terminal and only three were consumed; the widened panel is "
        "exactly the case FR-ORCH-29 re-offers, and a flag-shaped `aggregated` would drop it"
    )


def test_tc_orch_41_row_7_a_quarantined_extraction_still_opens_the_gate(table_world):
    """Row 7 — 2 extract **quarantined**: `integrity_pre` contains the cell.

    Row 1 with the other terminal status. A quarantined unit will never produce evidence, so a
    gate that waited for `done` would wait forever and the cell would never reach a grade — the
    silent-stall failure, which no status field reports because nothing is wrong.
    """
    store, orchestrator, run_a, _run_b = table_world
    _write_units(store, run_a, "R7", "extract", ("quarantined", "quarantined"))

    assert CellKey("R7", CRITERION) in _ready(orchestrator, run_a, "integrity_pre"), (
        "terminal means done OR quarantined (FR-ORCH-29): a cell whose extraction quarantined "
        "must still reach the gate, or it waits on evidence that is never coming"
    )


def test_tc_orch_41_row_8_one_runs_query_never_returns_another_runs_cell(table_world):
    """Row 8 — RB holds row 3's cell; RA's queries exclude it, and RB's own return it.

    Two runs over one cohort hold cells with identical `(submission_id, criterion_id)` keys.
    The positive half is what makes this a scoping assertion rather than an emptiness one: RB
    really does hold a ready cell, and RA simply cannot see it.
    """
    store, orchestrator, run_a, run_b = table_world
    _write_units(store, run_b, "R8", "extract", ("done", "done"))
    _write_units(store, run_b, "R8", "score", ("done", "done", "done"))
    _mark(store, orchestrator, run_b, "R8", "integrity_pre", 2)

    assert _ready(orchestrator, run_a, "integrity_pre") == (), (
        "RA holds no units at all in this arm, yet its integrity_pre query returned cells — "
        "the query is not scoped to the run (FR-ORCH-34's scoping rule, read across hooks)"
    )
    assert _ready(orchestrator, run_a, "aggregate") == ()
    assert CellKey("R8", CRITERION) in _ready(orchestrator, run_b, "aggregate"), (
        "RB's own cell must be ready — without this the scoping assertion above would pass "
        "against an implementation that returned nothing for anybody"
    )


def test_tc_orch_41_an_undeclared_hook_is_refused(table_world):
    """A hook outside `READY_HOOKS` is refused by name rather than quietly returning nothing.

    Not a plan row; it is the guard that keeps every emptiness assertion above honest. A typo'd
    hook that returned `()` would make rows 2, 4 and 5 pass for the wrong reason.
    """
    _store, orchestrator, run_a, _run_b = table_world

    with pytest.raises(ValueError) as caught:
        orchestrator.ready_cells(run_a, "integrity_mid")

    assert "integrity_mid" in str(caught.value)
    assert "integrity_pre" in str(caught.value), (
        f"the refusal names no declared hook: {caught.value!r}"
    )
