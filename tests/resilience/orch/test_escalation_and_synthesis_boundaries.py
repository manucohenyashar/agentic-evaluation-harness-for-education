"""`TS-24`'s escalation and synthesis boundary cases — `RES-06`, `RES-08` (issue #60:
escalations, panels and breakers, **landed** — unmarked at that landing) and `RES-07`
(issue #97, `M-SYNTH`, still written ahead).

- `RES-06` (`FR-ORCH-09`, resilience, P0): `SIGKILL` after a verdict is written but
  before its escalation units are leased — the escalation was written in the same
  transaction as the verdict (§9.10), so it survives; oracle **the escalation units
  exist after resume**.
- `RES-08` (`FR-ORCH-26`, `FR-AGG-12`, resilience, P0): a judge call failing
  permanently, leaving two verdicts — retry for the third; then discard the second
  and fall back to single-judge provisional; **never adjudicate between two** (§9.11);
  oracle **exact final state; no two-judge aggregation anywhere**.
- `RES-07` (`FR-ORCH-02`, resilience, P0): `SIGKILL` during synthesis — resume; a
  retried synthesis unit conflicts rather than duplicating (ADR-8); oracle **no
  duplicate `narrative` rows**.

**What "kill" means here, disclosed** (the `test_resume.py` precedent): the process
boundary is a store close + reopen over the same data directory — the exact state an
uncontrolled kill leaves behind — and the new process constructs a fresh
`Orchestrator` over the reopened store.

**Interface #60 landed** (reconciled deliberately, with one alignment disclosed):

| Name | Landed shape |
|---|---|
| `Orchestrator.enqueue_escalation(tx, criterion_score_key, judges=None)` | the design §3.7 member in `CT-ORCH-08`'s declared form: the caller's transaction first, the `(submission_id, criterion_id)` tuple second — `run_id`-agnostic (the key resolves its runs from the ledger) and landing inside the transaction the caller holds (here the test's, standing in for `M-AGG`'s verdict transaction) |
| escalation units at the enqueue | inserted by the enqueue itself, `origin='escalation'` (`FR-ORCH-09`: units in the same transaction as the result that triggered them). **Alignment disclosed:** the case originally snapshotted the base panel's three score units *after* the enqueue — with the landed, design-conformant semantics the widened units are already there, so the snapshot moved to *before* the enqueue. The oracle is untouched: escalation units exist past the boundary, are not duplicated by the resume, and dispatch |
| escalation units' ledger shape | score units for the same (submission, criterion) BEYOND the panel's original three, claimable after resume — asserted name-agnostically over counts and claimability; the landed units carry `origin='escalation'` and `judge_id`s the panel never enumerated |
| the random arm | off under test: the suite-root conftest pins `HARNESS_ORCH_RANDOM_ARM_RATE=0` (`tests/conftest.py`), so the base panel is exactly the three units these counts read |
| the verdict itself | `M-AGG`'s artifact, not shipped — the test enters at `enqueue_escalation`, the seam §9.10 requires to share the verdict's transaction; the aggregation half of `RES-08` (single-judge provisional fallback) is `TC-AGG-12`'s case and is not re-asserted here |
| `aeh.synth` with a `synthesize` entry point | **invented**: the design declares no `M-SYNTH` Protocol (grep of detailed-design.md for a Protocol block returns nothing — the console-suite precedent for an invented-and-disclosed key); the KEY is `RES-07`'s property, the name reconciles at #97's landing |
| `narrative` rows | the plan's own oracle names the table ("No duplicate `narrative` rows"); read through the store handle `M-SYNTH` registers, assumed the cohort handle |
| synthesis idempotence | ADR-8's conflict-on-duplicate: a retried synthesis for the same identity absorbs into the existing row rather than writing a second |

Isolation: rung 3 — real store, real Tier P package, real cohort ledger, no doubles
(§4.2); the model-call seam is not exercised (the driver plays the worker, #58's
shipped surface), so no transport is assumed here.
"""

from __future__ import annotations

import pytest

from aeh.orch import WorkError
from aeh.store import open_store
from tests.support.impl import ORCH_MODULE, SYNTH_MODULE, require, require_attr
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 6))
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)


def _score_rows(store, run_id: str, submission_id: str, criterion_id: str) -> list[dict]:
    # `last_error` rides along for RES-08's exact-final-state read (the quarantine's
    # retained error) — the helper predated that case's first actual run.
    return store.cohort("c-2026-7B-orch").query(
        "SELECT work_id, status, attempts, last_error FROM work_unit "
        "WHERE run_id = :r AND submission_id = :s AND criterion_id = :c AND stage = 'score'",
        r=run_id,
        s=submission_id,
        c=criterion_id,
    )


def test_res_06_escalation_survives_the_kill_and_dispatches_after_resume(
    tmp_data_dir,
):
    """`RES-06` (`FR-ORCH-09`, resilience, P0) — kill after the verdict's escalation
    is enqueued, before its units are leased: the escalation survives the boundary
    (§9.10 — same transaction as the verdict), and after `resume()` the escalation
    units EXIST and are dispatchable — not committed-then-forgotten, and not
    re-created by the resume (one escalation, not two)."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue="#58")
    require_attr(Orchestrator, "enqueue_escalation", issue="#60")

    data_dir = tmp_data_dir / "res06"
    store = open_store(data_dir)
    orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
    orch.enumerate_units(run_id)

    # Drive every extraction unit so scoring is dispatchable, and land one verdict:
    # its unit completes, and the escalation is enqueued — the dispatch loop's move
    # when a verdict lands outside its band (the verdict row itself is M-AGG's).
    for stage in ("extract", "deterministic"):
        while True:
            batch = orch.lease("worker-a", stage, 100)
            if not batch:
                break
            for unit in batch:
                orch.complete(unit.work_id)
    victim = orch.lease("worker-a", "score", 1)[0]
    orch.complete(victim.work_id)
    # The base panel, snapshotted BEFORE the enqueue — the landed semantics insert
    # the escalation units in the enqueue's own transaction (FR-ORCH-09), so after
    # the call the pair's score units number five, not three. (The original
    # written-ahead draft snapshotted after the call; see the module docstring's
    # disclosed alignment.) The random arm is pinned off by the suite-root conftest,
    # so exactly the panel's three units are here.
    before = _score_rows(store, run_id, victim.submission_id, victim.criterion_id)
    assert len(before) == 3, (
        f"the panel enumerated {len(before)} score units, expected the panel's 3"
    )
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        orch.enqueue_escalation(tx, (victim.submission_id, victim.criterion_id))

    # --- the kill: process boundary = close + reopen; a fresh orchestrator ---
    store.close()
    store = open_store(data_dir)
    try:
        restarted = Orchestrator(store)

        # The escalation survived: score units for the escalated criterion BEYOND
        # the panel's original three are in the ledger after the boundary.
        after_kill = _score_rows(store, run_id, victim.submission_id, victim.criterion_id)
        assert len(after_kill) > 3, (
            f"{len(after_kill)} score units after the kill — the escalation did "
            "not survive the boundary, though §9.10 wrote it in the verdict's own "
            "transaction; a killed escalation is a student's band decided by a "
            "panel that was never widened"
        )

        # resume() with no arguments — and the escalation units exist after it,
        # dispatchable, and NOT duplicated by the resume.
        restarted.resume()
        after_resume = _score_rows(store, run_id, victim.submission_id, victim.criterion_id)
        assert len(after_resume) == len(after_kill), (
            f"resume() grew the escalation units from {len(after_kill)} to "
            f"{len(after_resume)} — a resume that re-enqueues an escalation "
            "double-runs the widened panel (RISK-09's duplicated-work half)"
        )
        escalated_ids = {row["work_id"] for row in after_resume} - {
            row["work_id"] for row in before
        }
        assert escalated_ids, "the escalation units are indistinguishable from the base panel"
        won = restarted.lease("worker-b", "score", 100)
        assert any(unit.work_id in escalated_ids for unit in won), (
            "the escalation units exist but are not dispatchable — an escalation "
            "that never leases is a verdict that never gets its third judge"
        )
    finally:
        store.close()


def test_res_08_two_verdicts_never_adjudicate_the_third_is_never_faked(tmp_data_dir):
    """`RES-08` (`FR-ORCH-26`, `FR-AGG-12`, resilience, P0) — a judge call failing
    permanently, leaving two verdicts: the third judge is retried (the attempt
    ceiling), then quarantines — and NOTHING papered over the hole: no unit was
    failed into a two-judge state, no replacement unit was enqueued to re-run the
    judge silently, and the exact final state is two done, one quarantined with its
    error. The aggregation-side fallback (discard the second, single-judge
    provisional) is `TC-AGG-12`'s case against `M-AGG`; what the LEDGER owes this
    case is a state that makes that fallback possible and adjudication impossible —
    there is no third verdict to hide behind."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue="#58")
    require_attr(Orchestrator, "enqueue_escalation", issue="#60")

    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        orch.enumerate_units(run_id)
        for stage in ("extract", "deterministic"):
            while True:
                batch = orch.lease("worker-a", stage, 100)
                if not batch:
                    break
                for unit in batch:
                    orch.complete(unit.work_id)

        # One (submission, criterion) trio: two judges deliver, the third fails
        # permanently. Lease the trio once and disposition it directly — every
        # leased unit is accounted for, and `fail` wins over a live lease (the
        # shipped semantics), so the permanently failing judge is reported in
        # place without re-leasing.
        won = orch.lease("worker-a", "score", 100)
        assert won, "the fixture leased no score units"
        first = won[0]
        trio = [
            unit
            for unit in won
            if unit.submission_id == first.submission_id
            and unit.criterion_id == first.criterion_id
        ]
        assert len(trio) == 3, "the fixture did not isolate one panel trio"
        others = [unit for unit in trio if unit.work_id != first.work_id]
        assert len(others) == 2, "the fixture's trio overlaps the victim"
        # Land the two verdicts.
        for unit in others:
            orch.complete(unit.work_id)
        # The third judge fails permanently: 3 reports, the ceiling.
        for _ in range(3):
            orch.fail(
                first.work_id,
                WorkError(message=f"judge call failed permanently on {first.work_id[:12]}"),
            )

        # Exact final state, per row: the two verdicts stand done, the third is
        # quarantined at the ceiling with its error — never re-queued into a
        # two-judge shadow state, never quietly marked done, never replaced by a
        # re-run the ledger does not show.
        rows = {row["work_id"]: row for row in _score_rows(store, run_id, first.submission_id, first.criterion_id)}
        assert len(rows) == 3, (
            f"{len(rows)} score units for the trio — a permanent failure must not "
            "spawn replacement units; the retry is the ATTEMPT ceiling, not a "
            "re-enqueue (the escalated re-run is an explicit enqueue_escalation, "
            "which this case did not make)"
        )
        assert (
            rows[others[0].work_id]["status"] == "done"
            and rows[others[1].work_id]["status"] == "done"
        ), (
            "a delivered verdict was disturbed by its sibling's permanent failure — "
            "the two verdicts the fallback needs must stand"
        )
        assert rows[first.work_id]["status"] == "quarantined", (
            f"the permanently failing judge is '{rows[first.work_id]['status']}' — "
            "§9.11: retry to the ceiling, then quarantine; never adjudicate "
            "between two verdicts by pretending the third exists"
        )
        assert rows[first.work_id]["attempts"] == 3 and rows[first.work_id]["last_error"], (
            "the quarantined third judge lost its attempt count or its error — "
            "the exact final state the plan's oracle names"
        )

        # And the store holds no aggregation artifact a two-judge decision could
        # hide in: at this surface the ledger is the only place a verdict lives,
        # and it shows 2 + 1 — the fallback's honest input.
        others_done = [rows[unit.work_id]["status"] for unit in others]
        assert others_done == ["done", "done"] and rows[first.work_id]["status"] == (
            "quarantined"
        ), "the trio's final state moved after the assertions above"
    finally:
        store.close()


@pytest.mark.writtenahead
def test_res_07_retried_synthesis_conflicts_rather_than_duplicating(tmp_data_dir):
    """`RES-07` (`FR-ORCH-02`, resilience, P0) — `SIGKILL` during synthesis: resume;
    the retried synthesis unit conflicts rather than duplicating (ADR-8); oracle **no
    duplicate `narrative` rows**."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue="#58")
    synthesize = require(SYNTH_MODULE, "synthesize", issue="#97")

    data_dir = tmp_data_dir / "res07"
    store = open_store(data_dir)
    orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
    orch.enumerate_units(run_id)
    submission_id = _SUBMISSIONS[0]

    # Synthesis begins: the narrative for the submission is written...
    synthesize(run_id, submission_id=submission_id)

    # --- the kill: process boundary = close + reopen ---
    store.close()
    store = open_store(data_dir)
    try:
        restarted = Orchestrator(store)

        # ...and the retried synthesis unit CONFLICTS rather than duplicating
        # (ADR-8): the same identity synthesized again absorbs into the existing
        # row — whether by refusal, no-op, or an explicit conflict the caller
        # sees, it must not write a second narrative.
        restarted.resume()
        synthesize(run_id, submission_id=submission_id)

        narratives = store.cohort("c-2026-7B-orch").query(
            "SELECT * FROM narrative WHERE run_id = :r AND submission_id = :s",
            r=run_id,
            s=submission_id,
        )
        assert len(narratives) == 1, (
            f"{len(narratives)} narrative rows for one submission after a retried "
            "synthesis — the duplicate is ADR-8's named failure: two narratives "
            "for one student is a coin flip over which one ships"
        )
    finally:
        store.close()
