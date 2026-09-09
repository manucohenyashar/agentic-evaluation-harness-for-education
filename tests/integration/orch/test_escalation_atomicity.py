"""`TC-ORCH-11` — the escalation enqueue is **part of the caller's transaction**
(`CT-ORCH-08`); **landed at #60** (unmarked there).

The design's form (detailed-design §3.7, CT-ORCH-08) is `enqueue_escalation(tx,
criterion_score_key, judges)`: the orchestrator writes its escalation into a transaction
the **caller** opened and the caller will commit or abort. The reason this shape is the
requirement (not a convenience): a run's score unit for a criterion and the escalation
that widens that criterion's panel are one logical step — *both present or both absent
after any crash* is CT-STORE-03's atomicity clause read across the boundary. An
implementation that commits its own units inside the caller's rolled-back transaction
has built exactly the partial write the clause forbids: the panel widened with no
adjudication to show for it, or an adjudication recorded against a panel that never
existed.

**Interface this file assumes of #60** (declared for reconciliation — CT-ORCH-08 pins the
shape but not the column semantics):

| Name | Status |
|---|---|
| `Orchestrator.enqueue_escalation(tx, criterion_score_key, judges)` | **landed at #60 in this shape** — design CT-ORCH-08's declared signature: the caller's transaction object first, the key second, the judges third (the **added** judges, or None to derive them from the panel). `criterion_score_key` names the escalation's target the way the `criterion_score` table does — `(submission_id, criterion_id)`. `judges` are the judges being **added** (the plan's 1→3 escalation adds two, never re-writes the seated one — TC-ORCH-20's odd-panel rule). |
| escalation units are `work_unit` rows, `stage = 'score'`, one per added judge, `status = 'pending'` | the shipped enumeration's own shape for a panel-judged criterion (TC-ORCH-10 asserts it for the deterministic case); an escalation is the same kind of unit arriving late, so it carries the same shape. |
| escalation adds panel **members**, not a `criterion_score` row | `criterion_score` is the adjudicated result (aggregation's write, TC-ORCH-21's boundary); an enqueue is a plan, not a verdict. |

Judge identity is read off the ledger rows, not off the `ModelRef`s: a `ModelRef` carries
role/provider/build_id/quantization but no explicit id field, so the test takes the seated
judge's id from the base unit's `judge_id` column and asserts the added units differ from
it and from each other — two judges that resolved to one ledger id would silently narrow
the panel the escalation paid for.

Each limb runs in **its own store** (`tmp_data_dir` subdirectories): the escalation key is
run-agnostic — `(submission_id, criterion_id)` matches units in every run over the cohort —
so sharing one store across limbs would make the added units' run ambiguous, and the test
would be asserting its own fixture. One store per limb makes every count exact.

Isolation: rung 2 — real store, real Tier P package, real cohort ledger, no doubles; the
crashes are a raised exception through the caller's `transaction()` body, the seam
CT-STORE-03 scopes atomicity to.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.conf_builders import EDGE_JUDGE_2, EDGE_JUDGE_3
from tests.support.impl import ORCH_MODULE, require, require_attr
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

_SUBMISSIONS = ("SYN-001",)
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)
_ADDED_JUDGES = (EDGE_JUDGE_2, EDGE_JUDGE_3)  # the 1 -> 3 escalation adds two


class _Crash(Exception):
    """The crash the rollback limbs inject mid-transaction."""


def _score_units(cohort, run_id: str) -> list[dict]:
    """The run's score units, stable order."""
    return cohort.query(
        "SELECT work_id, judge_id, status FROM work_unit "
        "WHERE run_id = :r AND stage = 'score' ORDER BY work_id",
        r=run_id,
    )


def _verdict_present(cohort, verdict_id: str) -> bool:
    return bool(
        cohort.query(
            "SELECT 1 FROM verdict WHERE verdict_id = :v", v=verdict_id
        )
    )


def _seed_limb(tmp_data_dir, name: str):
    """One fresh store, one run enumerated at the single-judge default panel."""
    store = open_store(tmp_data_dir / name)
    orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
    orch.enumerate_units(run_id)
    cohort = store.cohort(ORCH_COHORT_ID)
    return store, orch, cohort, run_id


def test_tc_orch_11_enqueue_escalation_commits_and_rolls_back_with_the_callers_transaction(
    tmp_data_dir,
):
    """`TC-ORCH-11` (`CT-ORCH-08`, `CT-STORE-03` across the boundary, integration /
    rung 2, atomicity, P0) — three limbs over the caller's transaction:

    1. **commit**: the caller's verdict and the escalation land together — the verdict
       survives and the panel widens 1 → 3;
    2. **crash before the enqueue**: the verdict is gone and the panel never widened —
       a caller's own write must not survive a transaction whose body raised;
    3. **crash after the enqueue**: *neither* survives — the escalation written into
       the caller's transaction dies with it, and does not outlive the sibling write
       it was enqueued alongside.
    """
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue="#58")
    require_attr(Orchestrator, "enqueue_escalation", issue="#60")

    # --- limb 1: commit — verdict in, panel widened, in one transaction -------------------
    store, orch, cohort, run_id = _seed_limb(tmp_data_dir, "commit")
    try:
        base = _score_units(cohort, run_id)
        assert len(base) == 1, (
            f"the single-judge panel enumerated {len(base)} score units — the fixture "
            "must start from the 1 in the 1 -> 3 escalation"
        )
        seated_judge = base[0]["judge_id"]

        with cohort.transaction() as tx:
            tx.execute(
                "INSERT INTO verdict (verdict_id, work_id, judge_id, band) "
                "VALUES (:v, :w, :j, :b)",
                v="v-commit",
                w=base[0]["work_id"],
                j=seated_judge,
                b="B",
            )
            orch.enqueue_escalation(tx, ("SYN-001", "C1"), _ADDED_JUDGES)

        assert _verdict_present(cohort, "v-commit"), (
            "the caller's verdict did not survive its own committed transaction — the "
            "escalation enqueue broke the transaction it was handed"
        )
        widened = _score_units(cohort, run_id)
        assert len(widened) == 3, (
            f"after the committed escalation the run holds {len(widened)} score units, "
            "expected 3 — a 1 -> 3 escalation adds two panel members"
        )
        added = [row for row in widened if row["work_id"] != base[0]["work_id"]]
        assert len(added) == 2, (
            "the escalation did not preserve the seated unit — widening a panel must "
            "add members, not rewrite the judge already seated"
        )
        added_judges = {row["judge_id"] for row in added}
        assert seated_judge not in added_judges and len(added_judges) == 2, (
            f"the added panel members carry judges {added_judges!r} against the seated "
            f"{seated_judge!r} — two judges that resolve to one ledger id narrow the "
            "panel the escalation paid for"
        )
        assert all(row["status"] == "pending" for row in added), (
            "an escalated unit did not enter the queue as 'pending' — a widened panel "
            "whose new members are not dispatchable is a plan the run can never execute"
        )
    finally:
        store.close()

    # --- limb 2: crash before the enqueue — the caller's write dies with the tx -----------
    store, orch, cohort, run_id = _seed_limb(tmp_data_dir, "crash-before")
    try:
        base = _score_units(cohort, run_id)
        with pytest.raises(_Crash):
            with cohort.transaction() as tx:
                tx.execute(
                    "INSERT INTO verdict (verdict_id, work_id, judge_id, band) "
                    "VALUES (:v, :w, :j, :b)",
                    v="v-crash-before",
                    w=base[0]["work_id"],
                    j=base[0]["judge_id"],
                    b="B",
                )
                raise _Crash()
        assert not _verdict_present(cohort, "v-crash-before"), (
            "a verdict written before a mid-transaction crash survived — limb 2 is the "
            "store's own atomicity control: without it, limb 3's both-absent could be "
            "read as the enqueue having swallowed the caller's write"
        )
        assert len(_score_units(cohort, run_id)) == 1
    finally:
        store.close()

    # --- limb 3: crash after the enqueue — BOTH die, the atomicity core --------------------
    store, orch, cohort, run_id = _seed_limb(tmp_data_dir, "crash-after")
    try:
        base = _score_units(cohort, run_id)
        with pytest.raises(_Crash):
            with cohort.transaction() as tx:
                tx.execute(
                    "INSERT INTO verdict (verdict_id, work_id, judge_id, band) "
                    "VALUES (:v, :w, :j, :b)",
                    v="v-crash-after",
                    w=base[0]["work_id"],
                    j=base[0]["judge_id"],
                    b="B",
                )
                orch.enqueue_escalation(tx, ("SYN-001", "C1"), _ADDED_JUDGES)
                raise _Crash()
        assert not _verdict_present(cohort, "v-crash-after"), (
            "the caller's verdict was destroyed by the escalation's rollback — "
            "enqueue_escalation participates in the caller's transaction, it must not "
            "own it (CT-ORCH-08)"
        )
        survived = _score_units(cohort, run_id)
        assert len(survived) == 1, (
            f"after the crash the run holds {len(survived)} score units, expected the "
            "original 1 — an escalation that outlives the transaction it was enqueued "
            "into is a partial write: a panel widened with no adjudication to show for "
            "it, the split CT-STORE-03 forbids"
        )
        assert survived[0]["work_id"] == base[0]["work_id"]
    finally:
        store.close()
