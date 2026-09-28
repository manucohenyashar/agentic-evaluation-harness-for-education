"""`TC-JUDGE-C19` and `TC-JUDGE-C20` — the taxonomy safety property and the run-scoped verdict
read (§6.11.3, `CT-JUDGE-19/20`).

| Case | Clause | The violation it catches |
|---|---|---|
| `C19` | a taxonomy error consumes no strike | §8.3's tidy-up: keep the propagation, restore the strike |
| `C20` | `verdicts_for` is scoped to one run and ordered by `work_id` | the run filter dropped, or ordering falling back to rowid |

**C19 is M-EXTRACT's C16 at the other worker**, and it is a separate case for a reason: the two
workers reach the dispatch loop by different paths and a guard added to one is not a guard added
to the other. A judge panel struck by a provider outage quarantines a cell whose verdicts were
never attempted, and `FR-AGG-10` then composes over a panel one verdict short.

**C20's metamorphic arm is the case.** Inserting RB's verdicts **first** and RA's second leaves
the RA result unchanged — which is false for any implementation that dropped the run filter
*and* for any that fell back to rowid order. Insertion order is the one thing a stored read
must not depend on, and it is the one thing a single-run fixture cannot detect: with one run in
the ledger, rowid order and `work_id` order and run-scoped order are all the same sequence.

**Isolation: rung 1 for the taxonomy arms, rung 2 for the verdict read.**
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
from aeh.judge import verdicts_for
from aeh.orch import Orchestrator, StageOutcome
from aeh.prov import BuildChangedError, ProviderUnavailableError, RateLimitedError
from aeh.store import Statement, open_store
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    orch_cfg,
    seed_documents,
    seed_run,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

SUBMISSION = "S01"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

TAXONOMY = (
    ProviderUnavailableError("the endpoint is gone"),
    BuildChangedError("answering as a different build"),
    RateLimitedError("retry-after: 0"),
)

_SCORE_UNITS = Statement(
    "SELECT status, attempts FROM work_unit WHERE run_id = :r AND stage = 'score'"
)
_INSERT_UNIT = Statement(
    "INSERT INTO work_unit (work_id, run_id, submission_id, criterion_id, stage, "
    "judge_id, origin, status, attempts) VALUES (:w, :r, :s, :c, 'score', :j, 'base', "
    "'done', 0)"
)
_INSERT_VERDICT = Statement(
    "INSERT INTO verdict (verdict_id, work_id, judge_id, band, band_ordinal, "
    "cited_spans, evidence_sufficient, uncited) VALUES (:v, :w, :j, :b, :o, NULL, 1, 0)"
)


class _StubProvider:
    def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002 — the seam's shape
        return None

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        raise AssertionError("this suite's executor answers without a model call")


# --- TC-JUDGE-C19 --------------------------------------------------------------------------------


@pytest.mark.parametrize("error", TAXONOMY, ids=lambda e: type(e).__name__)
def test_tc_judge_c19_a_taxonomy_error_consumes_no_strike_on_a_score_unit(
    tmp_data_dir, error
):
    """A provider condition met while scoring charges the score unit nothing.

    The same property as `TC-EXTRACT-C16` at the other worker, and a separate case because the
    two reach the loop by different paths: a guard added to the extraction worker is not a
    guard added to the scoring one. Three strikes quarantine a score unit whose verdict was
    never attempted, and `FR-AGG-10` then composes over a panel one verdict short — which is a
    grade, not an error.
    """
    class _RaisingExecutor:
        def execute(self, unit: Any, governed: Any) -> StageOutcome:  # noqa: ARG002
            raise error

    store = open_store(tmp_data_dir)
    try:
        seeder, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        seed_documents(store, (SUBMISSION,))
        seeder.enumerate_units(run_id)
        cohort = store.cohort(ORCH_COHORT_ID)
        # Finish extraction so the score unit is the one the pass reaches.
        with cohort.transaction() as tx:
            tx.execute(
                Statement(
                    "UPDATE work_unit SET status = 'done' WHERE run_id = :r "
                    "AND stage = 'extract'"
                ),
                r=run_id,
            )
        probe = Orchestrator(
            store, executor=_RaisingExecutor(), provider=_StubProvider()
        )
        probe.start(run_id)
        with cohort.transaction() as tx:
            probe.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "integrity_pre", 1)

        probe.progress(run_id)

        units = [dict(row) for row in cohort.query(_SCORE_UNITS, r=run_id)]
        assert units, "the run enumerated no score unit, so the property is untested"
        for unit in units:
            assert unit["attempts"] == 0, (
                f"a {type(error).__name__} charged {unit['attempts']} attempt(s) to a score "
                "unit. The pause assertion still passes under §8.3's tidy-up; only this one "
                "goes red (RISK-44)"
            )
            assert unit["status"] != "quarantined", (
                f"a {type(error).__name__} quarantined a score unit — the panel loses a "
                "verdict it never attempted, and M-AGG composes over what is left"
            )
    finally:
        store.close()


# --- TC-JUDGE-C20 --------------------------------------------------------------------------------


def _seed_cell(store: Any, run_id: str, judges: tuple[str, ...], prefix: str) -> None:
    """One done score unit and one verdict per judge, for this run's cell."""
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        for index, judge in enumerate(judges):
            work_id = f"{prefix}-{index:02d}"
            tx.execute(
                _INSERT_UNIT, w=work_id, r=run_id, s=SUBMISSION, c=CRITERION, j=judge
            )
            tx.execute(
                _INSERT_VERDICT,
                v=f"v-{work_id}", w=work_id, j=judge,
                b=f"B{index + 1}", o=index + 1,
            )


@pytest.fixture
def two_runs(tmp_data_dir):
    """RA and RB over one cohort, each with its own verdicts for the same cell."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_a, version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        run_b = orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())
        yield store, run_a, run_b
    finally:
        store.close()


def test_tc_judge_c20_the_read_is_scoped_to_its_run(two_runs):
    """RA's read returns RA's verdicts only, and RB's returns RB's.

    Both directions, because "RA's read excludes RB" is also true of a read that returns
    nothing at all.
    """
    store, run_a, run_b = two_runs
    # `a-` sorts before `b-`, so a read that dropped the filter would return RA's first and
    # look plausible.
    _seed_cell(store, run_a, ("judge-a1", "judge-a2"), "a-work")
    _seed_cell(store, run_b, ("judge-b1", "judge-b2", "judge-b3"), "b-work")

    handle = store.cohort(ORCH_COHORT_ID)
    from_a = verdicts_for(handle, run_a, SUBMISSION, CRITERION)
    from_b = verdicts_for(handle, run_b, SUBMISSION, CRITERION)

    assert [v.judge_id for v in from_a] == ["judge-a1", "judge-a2"], (
        f"RA's read returned {[v.judge_id for v in from_a]}. A second run's verdicts for the "
        "same (submission, criterion) must never appear (CT-JUDGE-20)"
    )
    assert [v.judge_id for v in from_b] == ["judge-b1", "judge-b2", "judge-b3"], (
        f"RB's read returned {[v.judge_id for v in from_b]}"
    )


def test_tc_judge_c20_inserting_the_other_runs_verdicts_first_changes_nothing(tmp_data_dir):
    """The metamorphic arm: seed RB **before** RA, and RA's result is identical.

    The case. With one run in the ledger, rowid order and `work_id` order and run-scoped order
    are the same sequence, so a single-run fixture cannot tell them apart. Seeding the other
    run first separates them: an implementation that dropped the filter returns RB's rows,
    and one that fell back to rowid returns RA's in insertion order — which is now different
    from `work_id` order.
    """
    def _read(reverse: bool) -> list[tuple[str, str]]:
        store = open_store(tmp_data_dir / ("reverse" if reverse else "forward"))
        try:
            orchestrator, run_a, version = seed_run(
                store, submissions=(SUBMISSION,), criteria=CRITERIA,
            )
            run_b = orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())
            if reverse:
                _seed_cell(store, run_b, ("judge-b1", "judge-b2"), "b-work")
                _seed_cell(store, run_a, ("judge-a1", "judge-a2"), "a-work")
            else:
                _seed_cell(store, run_a, ("judge-a1", "judge-a2"), "a-work")
                _seed_cell(store, run_b, ("judge-b1", "judge-b2"), "b-work")
            verdicts = verdicts_for(
                store.cohort(ORCH_COHORT_ID), run_a, SUBMISSION, CRITERION
            )
            return [(v.work_id, v.judge_id) for v in verdicts]
        finally:
            store.close()

    forward = _read(reverse=False)
    reverse = _read(reverse=True)

    assert forward == reverse, (
        f"RA's verdicts read {forward} when seeded first and {reverse} when RB was seeded "
        "first. A stored read must not depend on insertion order — that is what rowid "
        "ordering gives you, and it is invisible until a second run exists (CT-JUDGE-20)"
    )
    assert forward == sorted(forward), (
        f"RA's verdicts are not in work_id order: {forward}. The order is the contract, "
        "because M-AGG's panel composition reads the tuple positionally"
    )


def test_tc_judge_c20_a_cell_with_no_verdicts_is_the_empty_tuple(two_runs):
    """A cell nobody judged reads as `()`, never as an error.

    The guard on the scoping assertions: an implementation that raised here would make
    "RA's read excludes RB" untestable for any cell that happened to be empty, and callers
    would have to distinguish "no verdicts" from "no such cell" — which the ledger cannot.
    """
    store, run_a, _run_b = two_runs

    assert verdicts_for(
        store.cohort(ORCH_COHORT_ID), run_a, "S-absent", CRITERION
    ) == ()
