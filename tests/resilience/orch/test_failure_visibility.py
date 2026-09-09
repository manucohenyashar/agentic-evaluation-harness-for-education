"""`TC-ORCH-31` (`NFR-ORCH-03`, `NFR-SYS-09`; resilience / rung 3, P0) — a 23,000-unit
run with 300 injected unit failures spread across stages: **the run completes and
delivers; every failure is visible on the operator surface; no failure is silently
absorbed**. Oracle: invariant plus visibility assertion.

**The scale, disclosed.** The plan says "a 23,000-unit run"; the enumerated ledger
here is 350 submissions × 18 criteria (17 judged open, scored by the three-judge
panel, plus 1 mcq scored deterministically — the mcq criterion contributes no
extract unit, the shipped enumerator's own shape):

- extract: 350 × 17 judged = 5,950
- score: 350 × 17 × 3 judges = 17,850
- deterministic: 350 × 1 = 350

…24,150 units — at or above the plan's figure with every one of the three stages
present, which the "spread across stages" premise needs.

**The 300 injected failures, exactly.** 210 units fail once (100 extract, 80 score,
30 deterministic) and then complete on retry; 30 units (20 score, 10 deterministic)
fail persistently and quarantine at the ceiling — 90 further reports — for **exactly
300 failure reports**. The driver's own count is asserted, so the fixture cannot
drift.

**Why no persistent failure lands on extract** (reconciled when #62 landed, the
`record_run_start` precedent): #59's shipped Sweep 2 gate never scores over nothing —
a quarantined extraction is not `done`, so the three score units it feeds stay gated
**forever** (until an operator re-queues the extraction), and a run carrying one can
never complete. A quarantined score or deterministic unit is a leaf: nothing gates on
it, the run delivers. The fail-once extract failures still exercise the
requeue-below-ceiling path on the gated stage — the unit returns to pending with its
attempt kept and completes on retry, and the extraction lands `done`.

**The invariant half.** `sum(attempts)` over the whole ledger equals 300 exactly:
no failure was absorbed without an attempt (the ledger's count is the operator
surface's source), and no phantom attempt appeared (at-least-once duplicates would
break the reconciliation). `mark_done` does not touch `last_error` and
`record_failure` sets it in both arms (the shipped statements, #58), so a failure
that later completed stays visible on its row: 24,120 done units include 210 whose
`last_error` still names what happened to them on the way.

**The visibility half.** The operator surface is `progress`'s report (#62's AC4:
counts by `(stage, criterion, judge)` plus done / in-flight / pending / quarantined
totals): its quarantined total equals the ledger's 30, its totals reconcile to the
ledger's 24,150, it reports the run **complete** (quarantined units are not pending —
NFR-ORCH-03's "fail the unit, never the run" is what lets the run deliver), and —
the non-promise half of AC4 — **no per-student completion figure exists anywhere in
it** (FR-CONSOLE-08: the data must not exist to render).

The grade-reporting half of "delivers" (the artifacts the run feeds) is the grade
stories' to carry (`TC-GRADE-*`); this file's delivery claim is the ledger's: every
non-quarantined unit done, nothing left in flight.

**Interface this file assumes of #62** — landed with #62, and the names shipped
exactly as assumed (the `test_leasing.py` precedent; the design reasoning stays):

| Name | Status |
|---|---|
| `Orchestrator.progress(run_id)` | design §3.7 Protocol member #62 ships; the completion predicate (`TC-ORCH-22`'s symbol) and the AC4 report shape |
| `report["complete"]` | the predicate's observable, as a report field (the existing registry entry keys `progress` for the completion predicate) |
| `report["done"] / ["pending"] / ["in_flight"] / ["quarantined"]` | AC4's totals, flat on the report |
| `report["by_unit"]` | AC4's counts by `(stage, criterion, judge)` — the reconciliation that the surface counts the WHOLE ledger, not a sample |

Isolation: rung 3 — real store, real Tier P package, real cohort ledger, no
doubles; the driver plays the workers (lease / complete / fail are the shipped
worker surface, #58), so no model-call seam is exercised here and none is assumed.
"""

from __future__ import annotations

import pytest

from aeh.orch import WorkError
from aeh.store import open_store
from tests.support.impl import ORCH_MODULE, require, require_attr
from tests.support.orch_run import seed_run

pytestmark = [pytest.mark.integration]

ISSUE = "#62"

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 351))
_CRITERIA = tuple(
    [
        {"criterion_id": f"C{i:02d}", "kind": "open", "scoring_model": "holistic"}
        for i in range(1, 18)
    ]
    + [{"criterion_id": "MCQ", "kind": "mcq", "scoring_model": "deterministic"}]
)

_STAGES = ("extract", "score", "deterministic")

#: Per stage: (units failed once, units failed persistently). The persistent units
#: fail 3 times each (the shipped ceiling), so the total is
#: sum(fail_once + 3 * persistent) = (100 + 0) + (80 + 60) + (30 + 30) = 300.
#: The persistent quota avoids extract — see the docstring's reconciliation note:
#: a quarantined extraction permanently gates its score units (#59's gate), and the
#: run could never complete.
_FAILURE_PLAN = {"extract": (100, 0), "score": (80, 20), "deterministic": (30, 10)}

_TOTAL_UNITS = 350 * 17 + 350 * 17 * 3 + 350 * 1
_PERSISTENT_TOTAL = sum(plan[1] for plan in _FAILURE_PLAN.values())
_INJECTED_FAILURES = sum(plan[0] + 3 * plan[1] for plan in _FAILURE_PLAN.values())


def _spread(ids: list[str], count: int) -> list[str]:
    """`count` ids spread deterministically across the ordered list — even strides,
    so the failures land across the whole stage rather than its head."""
    if count == 0:
        return []
    assert len(ids) >= count, (
        f"the fixture asked to spread {count} failures over {len(ids)} units"
    )
    return [ids[min(len(ids) - 1, i * len(ids) // count)] for i in range(count)]


def test_tc_orch_31_twenty_three_thousand_units_three_hundred_failures_all_visible(
    tmp_data_dir,
):
    """`TC-ORCH-31` — the run completes and delivers; every failure is visible; no
    failure is silently absorbed: the ledger's attempt sum is exactly the injected
    300, the 30 persistent failures are quarantined with their errors, the 210
    single failures completed and still name what happened, and the progress report
    — the operator surface — reconciles to the ledger to the unit."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    require_attr(Orchestrator, "progress", issue=ISSUE)

    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _version = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orch.enumerate_units(run_id)

        # --- designate the failures, spread across stages -----------------------
        fail_once: dict[str, str] = {}
        persistent: dict[str, list[str]] = {}
        chosen: set[str] = set()
        for stage, (n_once, n_persistent) in _FAILURE_PLAN.items():
            ids = [
                row["work_id"]
                for row in store.cohort("c-2026-7B-orch").query(
                    "SELECT work_id FROM work_unit WHERE run_id = :r AND stage = :s "
                    "ORDER BY work_id",
                    r=run_id,
                    s=stage,
                )
            ]
            assert len(ids) >= n_once + n_persistent, (
                f"stage {stage}: the fixture's failure plan exceeds its unit count"
            )
            for work_id in _spread(ids, n_once):
                assert work_id not in chosen, (
                    "the spread designated one unit twice — the 300 would miscount"
                )
                chosen.add(work_id)
                fail_once[work_id] = (
                    f"malformed output on {work_id[:12]}: band outside the declared set"
                )
            remaining = [i for i in ids if i not in chosen]
            for work_id in _spread(remaining, n_persistent):
                assert work_id not in chosen
                chosen.add(work_id)
                persistent[work_id] = [
                    f"persistent malformed output on {work_id[:12]}: retry {n} of 3"
                    for n in (1, 2, 3)
                ]
        assert len(fail_once) == sum(p[0] for p in _FAILURE_PLAN.values())
        assert len(persistent) == _PERSISTENT_TOTAL

        # --- drive the run: workers lease, the injected failures fire -----------
        injected = 0
        while True:
            batch = []
            for stage in _STAGES:
                batch.extend(orch.lease("worker-load", stage, 500))
            if not batch:
                break
            for unit in batch:
                if unit.work_id in persistent:
                    messages = persistent[unit.work_id]
                    orch.fail(unit.work_id, WorkError(message=messages[0]))
                    messages.pop(0)
                    injected += 1
                elif unit.work_id in fail_once:
                    orch.fail(unit.work_id, WorkError(message=fail_once[unit.work_id]))
                    del fail_once[unit.work_id]
                    injected += 1
                else:
                    orch.complete(unit.work_id)
        assert injected == _INJECTED_FAILURES == 300, (
            f"the driver injected {injected} failures, planned {_INJECTED_FAILURES} "
            "— the fixture's own count must be exact or the invariant proves nothing"
        )

        # --- the invariant half: the ledger absorbed nothing silently -----------
        rows = store.cohort("c-2026-7B-orch").query(
            "SELECT work_id, stage, status, attempts, last_error FROM work_unit "
            "WHERE run_id = :r",
            r=run_id,
        )
        assert len(rows) == _TOTAL_UNITS == 24_150, (
            f"the ledger holds {len(rows)} units, planned {_TOTAL_UNITS}"
        )
        assert sum(row["attempts"] for row in rows) == 300, (
            f"the ledger's attempt sum is {sum(r['attempts'] for r in rows)}, not "
            "300 — an attempt lost or invented here IS a failure silently absorbed "
            "or silently invented (NFR-SYS-09's exact premise)"
        )
        quarantined = [row for row in rows if row["status"] == "quarantined"]
        assert len(quarantined) == 30, (
            f"{len(quarantined)} units quarantined, planned 30 — the persistent "
            "failures must land exactly on the ceiling"
        )
        done = [row for row in rows if row["status"] == "done"]
        assert len(done) == _TOTAL_UNITS - 30, (
            f"{len(done)} units done, planned {_TOTAL_UNITS - 30} — the run did "
            "not deliver every non-quarantined unit"
        )
        assert all(row["status"] in ("done", "quarantined") for row in rows), (
            "units left pending or leased after the run ended — the run 'completed' "
            "while work was still open"
        )
        for row in quarantined:
            assert row["attempts"] == 3, (
                f"unit {row['work_id'][:12]} quarantined at "
                f"attempts={row['attempts']} — the ceiling is 3"
            )
            assert row["last_error"] and "persistent malformed output" in row["last_error"], (
                f"quarantined unit {row['work_id'][:12]} does not name its failure "
                "— the operator surface could say THAT it failed, not WHAT"
            )
        for row in done:
            if row["attempts"] == 1:
                assert row["last_error"] and "malformed output" in row["last_error"], (
                    f"unit {row['work_id'][:12]} failed once, completed, and the "
                    "failure left no trace — a failure that completed away is a "
                    "failure the operator surface can never see (NFR-SYS-09)"
                )

        # --- the visibility half: the operator surface reconciles ---------------
        report = orch.progress(run_id)
        assert report["complete"] is True, (
            "the completion predicate did not fire — no pending units and no "
            "in-flight unit that could spawn an escalation, yet the run is not "
            "complete"
        )
        assert report["quarantined"] == 30, (
            f"the operator surface reports {report['quarantined']} quarantined, "
            "the ledger holds 30 — a total that does not reconcile is a failure "
            "half-absorbed between the ledger and the surface"
        )
        assert (
            report["done"] + report["pending"] + report["in_flight"] + report["quarantined"]
            == _TOTAL_UNITS
        ), (
            "the report's status totals do not sum to the ledger's unit count — "
            "some units exist in the ledger but not on the surface, which is the "
            "'no failure is silently absorbed' premise failing at the surface"
        )
        assert sum(report["by_unit"].values()) == _TOTAL_UNITS, (
            "the per-(stage, criterion, judge) counts do not sum to the ledger — "
            "the granularity AC4 requires must cover every unit, not a slice"
        )
        # The non-promise half: no per-student completion figure exists to render.
        surfaces = set(report) | set(report.get("by_unit", {}))
        for key in surfaces:
            text = str(key).lower()
            assert "submission" not in text and "student" not in text, (
                f"the progress report exposes a per-student figure ({key!r}) — "
                "FR-CONSOLE-08: the data must not exist to render"
            )
    finally:
        store.close()
