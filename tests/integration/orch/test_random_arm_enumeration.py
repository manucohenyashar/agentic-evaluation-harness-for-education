"""`TC-ORCH-12`'s mechanism half — the random arm at the enumeration surface, written
ahead of #60. The statistical core (10k-draw convergence, strata independence, ADV-12's
engineered population) lives in `tests/unit/orch/test_random_arm.py`; this file holds the
two mechanism clauses the plan states with it and a rung-0 file cannot observe:

1. **The arm is enumerated up front** (`FR-ORCH-11`, `CT-ORCH-15`): `origin =
   'random_arm'` units exist immediately after `enumerate_units`, before any scoring has
   produced a confidence — which makes confidence-independence *structural*: selection
   could not have read a confidence that did not exist yet. That is the mechanism behind
   the statistical independence the unit file asserts over draws.
2. **The escalation ceiling does not suppress the arm** (`FR-ORCH-11`): with the run's
   escalation rate driven above `ORCH_ESCALATION_BUDGET` (0.30), growth still samples the
   arm — new submissions re-enumerated via `resume()` still carry `origin =
   'random_arm'` units. An arm that folds under budget pressure stops auditing exactly
   when the routing policy is under the most strain.

**Surfaces and carriers.**

| Thing | Status |
|---|---|
| `work_unit.origin`, `CHECK (origin IN ('base','escalation','random_arm'))` | **shipped** — orch's own cohort migration (`_ORCH_COHORT_007`); CT-ORCH-15's separability carrier needs no assumption, only the value. |
| the arm's selection inside `enumerate_units` | #60's: enumeration reads `ORCH_RANDOM_ARM_RATE` and samples; its pure core is the unit file's `random_arm_selection`. This file asserts the ledger outcome, not the sampler's internals. |
| `Orchestrator.enqueue_escalation(tx, criterion_score_key, judges)` | assumed per CT-ORCH-08 — the same declared form `test_escalation_atomicity.py` uses (the caller's transaction, the key `(submission_id, criterion_id)`, the **added** judges). |
| the escalation rate's denominator | declared reading: escalations against the run's score units at the time — here 35 escalations over 100 single-judge base units = 35%, above the 0.30 budget. If #60 ships a different denominator, the overrun premise below is the line that reconciles. |
| the growth batch's `INSERT INTO submission` rows | the `orch_run.py` bypass, disclosed: `M-INGEST` is not under test, the ledger is, and the rows are the shipped writer's exact shape. |

≥1 assertions are made against the suite's fixed world, not against luck: the expected
arm share of a 100-submission batch is ~7 units (p=0.07), so a working sampler under any
sane seed leaves many; an outcome of 0 from #60's shipped seed is a visible
reconciliation, not a flake, because nothing here is re-randomized between runs.

Isolation: rung 2 — real store, real Tier P package, real cohort ledger, no doubles.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.conf_builders import EDGE_JUDGE_2, EDGE_JUDGE_3
from tests.support.impl import ORCH_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

_BASE = tuple(f"SYN-{i:03d}" for i in range(1, 101))  # 100 base submissions
_GROWTH = tuple(f"SYN-{i:03d}" for i in range(101, 201))  # 100 more, added mid-run
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)
_ADDED_JUDGES = (EDGE_JUDGE_2, EDGE_JUDGE_3)  # the 1 -> 3 escalation adds two
_ESCALATIONS = 35  # 35 / 100 base units = 35% > the 0.30 budget


def _arm_units(cohort, run_id: str) -> list[dict]:
    return cohort.query(
        "SELECT work_id, submission_id, stage, status FROM work_unit "
        "WHERE run_id = :r AND origin = 'random_arm' ORDER BY work_id",
        r=run_id,
    )


def _add_growth_submissions(store) -> None:
    """The growth batch, written in the shipped `submission` shape (`orch_run.py`'s
    disclosed bypass: M-INGEST is not under test, the ledger is)."""
    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        for submission_id in _GROWTH:
            tx.execute(
                "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                "VALUES (:s, :c, :r)",
                s=submission_id,
                c=ORCH_COHORT_ID,
                r=f"ref-{submission_id}",
            )


def test_tc_orch_12_the_arm_is_enumerated_up_front_before_any_confidence_exists(
    tmp_data_dir,
):
    """`TC-ORCH-12` mechanism half 1 (`FR-ORCH-11`, `CT-ORCH-15`, integration / rung 2,
    P0) — `origin = 'random_arm'` units exist immediately after enumeration, with no
    verdict or score row anywhere in the store: selection is structurally independent of
    confidence, because at enumeration time there is none to read."""
    require(ORCH_MODULE, "ORCH_RANDOM_ARM_RATE", issue="#60")

    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(store, submissions=_BASE, criteria=_CRITERIA)
        orch.enumerate_units(run_id)
        cohort = store.cohort(ORCH_COHORT_ID)

        arm = _arm_units(cohort, run_id)
        assert len(arm) >= 1, (
            "enumeration produced no random-arm units — the arm is not sampled up "
            "front, so the blind and random-arm labels would have nothing to compare "
            "and FR-ORCH-11's audit population is empty"
        )

        # The arm is score-shaped and dispatchable: a second pass over judged
        # criteria, entering the queue like any other unit.
        assert all(row["stage"] == "score" for row in arm), (
            "a random-arm unit did not carry stage 'score' — the arm is a scoring "
            "pass, and a unit in any other stage would enter a sweep it was never "
            "meant for"
        )
        assert all(row["status"] == "pending" for row in arm), (
            "a random-arm unit did not enter the queue as 'pending' — an arm unit "
            "that is not dispatchable spends the budget without ever producing a "
            "label"
        )

        # Nothing has been scored: no verdict anywhere in the store. The arm exists
        # in a ledger that holds no confidence yet — the structural half of
        # "independent of confidence".
        verdicts = cohort.query("SELECT 1 FROM verdict LIMIT 1")
        scores = cohort.query("SELECT 1 FROM criterion_score LIMIT 1")
        assert not verdicts and not scores, (
            "the ledger holds a verdict or criterion_score before any unit was "
            "leased — the fixture's no-confidence-yet premise is broken, and the "
            "structural independence claim with it"
        )

        # Separability (CT-ORCH-15): the same run holds both origins, and the two
        # populations are disjoint by the column the design named — no unit is both
        # a base unit and an arm unit.
        base = cohort.query(
            "SELECT COUNT(*) AS n FROM work_unit "
            "WHERE run_id = :r AND origin = 'base' AND stage = 'score'",
            r=run_id,
        )[0]["n"]
        assert base >= 1, (
            "the run holds no base score units — the fixture's premise is broken"
        )
        assert base + len(arm) == cohort.query(
            "SELECT COUNT(*) AS n FROM work_unit "
            "WHERE run_id = :r AND stage = 'score'",
            r=run_id,
        )[0]["n"], (
            "score units exist with an origin outside {'base', 'random_arm'} — "
            "origin is what keeps the arm statistically separable (CT-ORCH-15), and "
            "a third population would enter neither label set cleanly"
        )
    finally:
        store.close()


def test_tc_orch_12_the_escalation_ceiling_does_not_suppress_the_arm(tmp_data_dir):
    """`TC-ORCH-12` mechanism half 2 (`FR-ORCH-11`, integration / rung 2, P0) — with 35
    of the 100 base criteria escalated (35%, above the 0.30 budget), a growth batch of
    100 new submissions re-enumerated via `resume()` still samples the arm: the ceiling
    rations escalations, never the arm."""
    rate, budget, _enqueue = require(
        ORCH_MODULE,
        "ORCH_RANDOM_ARM_RATE",
        "ORCH_ESCALATION_BUDGET",
        "Orchestrator.enqueue_escalation",
        issue="#60",
    )

    # The overrun premise, checked against the shipped constants: if the budget is
    # ever retuned past 35%, the fixture must grow with it — and this line is where
    # that shows.
    assert _ESCALATIONS / len(_BASE) > budget, (
        f"the fixture escalates {_ESCALATIONS}/{len(_BASE)} = "
        f"{_ESCALATIONS / len(_BASE):.0%} against ORCH_ESCALATION_BUDGET = {budget!r} "
        "— the premise 'above budget' does not hold; grow _ESCALATIONS"
    )

    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(store, submissions=_BASE, criteria=_CRITERIA)
        orch.enumerate_units(run_id)
        cohort = store.cohort(ORCH_COHORT_ID)

        # Drive the run above the escalation budget: 35 criteria escalated 1 -> 3,
        # one transaction, the atomicity file's declared form.
        with cohort.transaction() as tx:
            for submission_id in _BASE[:_ESCALATIONS]:
                orch.enqueue_escalation(
                    tx, (submission_id, "C1"), _ADDED_JUDGES
                )

        escalated = cohort.query(
            "SELECT COUNT(*) AS n FROM work_unit "
            "WHERE run_id = :r AND origin = 'escalation'",
            r=run_id,
        )[0]["n"]
        assert escalated == _ESCALATIONS * len(_ADDED_JUDGES), (
            f"the ledger holds {escalated} escalation units, expected "
            f"{_ESCALATIONS * len(_ADDED_JUDGES)} — each 1 -> 3 escalation adds two "
            "panel members, and a shorter ladder undercuts the overrun premise"
        )

        # The growth batch arrives while the run is over budget.
        _add_growth_submissions(store)
        orch.resume(run_id)

        new_arm = [
            row for row in _arm_units(cohort, run_id)
            if row["submission_id"] in _GROWTH
        ]
        assert len(new_arm) >= 1, (
            f"a {len(_GROWTH)}-submission growth batch re-enumerated at "
            f"ORCH_RANDOM_ARM_RATE = {rate!r} sampled no arm units while the run "
            "stood above the escalation budget — the ceiling suppressed the arm "
            "(FR-ORCH-11's forbidden fold), so the routing policy's most strained "
            "period is exactly the one nothing audits"
        )
        assert all(row["stage"] == "score" and row["status"] == "pending" for row in new_arm), (
            "a growth-batch arm unit is not a pending score unit — the arm must keep "
            "its shape under budget pressure, not degrade into a different kind of row"
        )
    finally:
        store.close()
