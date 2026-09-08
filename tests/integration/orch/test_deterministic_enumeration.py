"""`TC-ORCH-10` — a package with three deterministic criteria generates exactly one
`stage = 'deterministic'` unit per (submission, criterion), with a **null** `judge_id`,
and generates **no** extraction and no scoring unit. Test plan §5.7; `FR-ORCH-08`.

Oracle: **exact enumeration** — unit counts and stage/judge columns, not a status.

The design's `evaluation_mode` column does not exist; the catalog's `kind = 'mcq'` is the
carrier the shipped enumeration reads (the interpretation is recorded on #57, and #59 owns
reconciling the two — `CT-SETUP-07` carries the same disclosed bet on the setup side). When
the column lands this case widens to it; it never weakens.

`CT-ORCH-07`'s negative is the same boundary stated from the contract side — a deterministic
criterion leaking into Sweep 2 would be scored by a panel and enter agreement statistics
(RISK-07's mechanism) — so the absence assertions below are the case, not decoration.

**Isolation: rung 2** — real store, real Tier P package, real cohort ledger.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.orch_run import seed_run

pytestmark = pytest.mark.integration

ISSUE = "#63"

_SUBMISSIONS = ("SYN-001", "SYN-002")
_DETERMINISTIC = (
    {"criterion_id": "M1", "kind": "mcq"},
    {"criterion_id": "M2", "kind": "mcq"},
    {"criterion_id": "M3", "kind": "mcq"},
)


def test_tc_orch_10_three_deterministic_criteria_enumerate_exactly_one_unit_each(
    tmp_data_dir,
):
    """`TC-ORCH-10` — exact enumeration: one `deterministic` unit per
    (submission, criterion), null judge, and no extraction or scoring unit anywhere."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_DETERMINISTIC
        )
        report = orchestrator.enumerate_units(run_id)

        cohort = store.cohort("c-2026-7B-orch")
        rows = cohort.query(
            "SELECT work_id, stage, criterion_id, judge_id, status FROM work_unit "
            "WHERE run_id = :r ORDER BY criterion_id, work_id",
            r=run_id,
        )

        # Exact total: every (submission, criterion) pair, exactly one unit, nothing else.
        assert report.units_enumerated == 6, (
            f"2 submissions x 3 deterministic criteria must enumerate exactly 6 units, "
            f"got {report.units_enumerated}"
        )
        assert len(rows) == 6, (
            "the ledger holds a different number of rows than the enumeration computed"
        )
        assert dict(report.by_stage) == {"deterministic": 6}, (
            f"by_stage is {dict(report.by_stage)} — a deterministic criterion produced a "
            "unit in another stage, which is RISK-07's leak: a panel would score it and "
            "it would enter agreement statistics"
        )

        # Shape per row: the right stage, the right criterion, and a NULL judge.
        for row in rows:
            assert row["stage"] == "deterministic", (
                f"unit {row['work_id'][:12]} carried stage {row['stage']!r} for a "
                "deterministic criterion"
            )
            assert row["criterion_id"] in {"M1", "M2", "M3"}
            assert row["judge_id"] is None, (
                f"deterministic unit {row['work_id'][:12]} carries judge "
                f"{row['judge_id']!r} — M-DET never invokes a judge, and a named judge "
                "here is a unit a panel could be dispatched against"
            )
            assert row["status"] == "pending"

        # The negative, swept over the whole ledger: no extraction unit and no scoring
        # unit exists for a deterministic criterion — neither sweep can ever see one.
        stages = {row["stage"] for row in rows}
        assert "extract" not in stages, (
            "a deterministic criterion produced an extraction unit — Sweep 1 is over "
            "judged criteria only"
        )
        assert "score" not in stages, (
            "a deterministic criterion produced a scoring unit — it would be scored by "
            "a panel and enter agreement statistics (CT-ORCH-07, RISK-07)"
        )

        # And each (submission, criterion) pair holds EXACTLY one unit — one per pair,
        # not two rows with the same address under different ids.
        addresses = cohort.query(
            "SELECT submission_id, criterion_id, COUNT(*) AS n FROM work_unit "
            "WHERE run_id = :r GROUP BY submission_id, criterion_id",
            r=run_id,
        )
        assert all(row["n"] == 1 for row in addresses) and len(addresses) == 6, (
            "a (submission, criterion) pair carries more than one unit, or a pair is "
            "missing one — the enumeration is not the exact one-to-one shape"
        )
    finally:
        store.close()
