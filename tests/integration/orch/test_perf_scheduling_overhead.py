"""`TC-ORCH-30` (`NFR-ORCH-01`, `PERF-03`; performance / rung 2, P1) — scheduling
overhead at the design's scale: 23,000 units enumerated and scheduled, under
5 ms per unit, "so the orchestrator is never the bottleneck against a ~1.7 hour
batched run" (detailed-design.md, M-ORCH NFR table; `CT-ORCH-18`).

`PERF-03` pins the measured quantity: **enumeration and scheduling only, provider
stubbed** — no model call is involved at any point (there is no transport to
stub: this test plays the workers over the shipped lease/complete surface, #58).
The fixture is the design's uniform-panel 350-student run — 350 submissions x
17 judged criteria x panel depth 3, plus the deterministic criterion — 24,150
units, the same fixture shape `TC-ORCH-31`'s resilience case stands on, at and
above the ~23,100-unit uniform-panel 350-student run `NFR-ORCH-06` names.

What counts as "scheduling" here, stated because it is load-bearing:

- `enumerate_units` — the pass that computes and inserts the ledger rows;
- `lease` — the handout pass, which resolves `FR-ORCH-07`'s dispatch order (the
  per-(run, stage) order cache #59 shipped is exactly what NFR-ORCH-01's budget
  protects: without it, order resolution re-runs per claim). The drain
  therefore ends in a chunk-1 tail: only a single-unit claim pays the
  per-claim cost, and a batch handout would hide exactly the cache's loss.

Completing the extract units is the *dependency gate* Sweep 2 needs
(`FR-ORCH-06`) — a bookkeeping step between scheduling passes, deliberately
**excluded** from the measured numerator: `PERF-03` measures enumeration and
scheduling, not ledger writes.

Threshold: the plan's 5 ms/unit, never weakened. #59's landing measured
1.57 ms/unit at 3,000 units; this case holds the budget at the design's full
23,000-unit scale — the cache makes order resolution O(1) per unit, so the
per-unit cost must not grow with the run.

Isolation: rung 2 — real store, real Tier P package, real cohort ledger; no
doubles, no provider, no network (the socket guard is active).
"""

from __future__ import annotations

import time

import pytest

from aeh.store import open_store
from tests.support.orch_run import seed_run

pytestmark = [pytest.mark.integration]

#: The uniform-panel 350-student run the NFR numbers are written against:
#: 17 judged open criteria + 1 deterministic MCQ criterion, panel depth 3.
_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 351))
_CRITERIA = tuple(
    [
        {"criterion_id": f"C{i:02d}", "kind": "open", "scoring_model": "holistic"}
        for i in range(1, 18)
    ]
    + [{"criterion_id": "MCQ", "kind": "mcq", "scoring_model": "deterministic"}]
)

_TOTAL_UNITS = 350 * 17 + 350 * 17 * 3 + 350 * 1
assert _TOTAL_UNITS >= 23000

#: `NFR-ORCH-01` / `PERF-03`: scheduling overhead under 5 ms per unit at 23,000 units.
BUDGET_MS_PER_UNIT = 5.0

#: Handout chunk per lease call. Not the concurrency ceiling — a batch size for the
#: scheduling pass; the *per-unit* cost is the measured quantity.
_LEASE_CHUNK = 500

#: The drain's final score units are claimed ONE PER CALL: a chunk-500 handout
#: amortizes order resolution across the batch, so only a chunk-1 claim pays
#: the per-claim cost the order cache exists to remove (#59 measured
#: 5.3 ms/unit without it — over budget exactly here).
_TAIL_CLAIMS = 50


def _drain(orch: object, stage: str, sink: list) -> float:
    """Lease `stage` to exhaustion, timing ONLY the lease calls.

    Returns the total lease wall time in seconds; the handed-out units land in
    `sink`. An empty handout ends the stage — the shipped lease surface returns
    nothing once the stage is exhausted (the `TC-ORCH-05` claim semantics).
    """
    elapsed = 0.0
    while True:
        t0 = time.perf_counter()
        batch = orch.lease("perf-worker", stage, _LEASE_CHUNK)
        elapsed += time.perf_counter() - t0
        if not batch:
            return elapsed
        sink.extend(batch)


def test_tc_orch_30_scheduling_overhead_under_5ms_per_unit_at_23k(tmp_data_dir):
    """`TC-ORCH-30` — 24,150 units enumerated and scheduled; the combined
    enumeration + lease wall time stays under 5 ms per unit.

    The oracle is the metric threshold (`PERF-03`), asserted against the exact
    enumerated count the fixture owes — a smaller fixture would measure nothing
    about the design's scale, and a miscounted one would divide by the wrong n.
    """
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(
        store,
        submissions=_SUBMISSIONS,
        criteria=_CRITERIA,
        panel=None,  # orch_cfg's default: the three-judge edge panel
    )
    try:
        t0 = time.perf_counter()
        report = orch.enumerate_units(run_id)
        enumerate_s = time.perf_counter() - t0

        assert report.units_enumerated == _TOTAL_UNITS, (
            f"the fixture enumerated {report.units_enumerated} units, expected "
            f"{_TOTAL_UNITS} — PERF-03's input is the design's uniform-panel "
            "350-student run, and a different n measures a different budget"
        )
        assert report.units_inserted == _TOTAL_UNITS, (
            f"enumeration inserted {report.units_inserted} of "
            f"{report.units_enumerated} computed units — scheduling a fresh run "
            "must land every unit in the ledger"
        )

        # Sweep 1: extract units schedule (and gate Sweep 2 — completes untimed).
        extract: list = []
        lease_s = _drain(orch, "extract", extract)
        assert len(extract) == 350 * 17, (
            f"extract handout {len(extract)} != 350*17 — a judged criterion owes "
            "one extraction unit per submission (FR-ORCH-05)"
        )
        for unit in extract:
            orch.complete(unit.work_id)

        # Deterministic units: no extraction, no judge (FR-ORCH-08).
        deterministic: list = []
        lease_s += _drain(orch, "deterministic", deterministic)
        assert len(deterministic) == 350

        # Sweep 2: score units, unlocked once every extraction is done. All
        # but the reserved tail go out in batch handouts, timed per call. Each
        # handout is completed before the next lease (untimed, like the extract
        # completes): since #62 the residency policy (`FR-ORCH-19`) holds an
        # edge-local score handout to ONE judge's batch — the box holds one
        # model resident, a handout never mixes models — so the handouts arrive
        # judge by judge, and a claimant that left its handout in flight would
        # stall at the boundary with the resident's batch in flight. Completing
        # as it goes is what lets the handouts cover all three judges; the
        # measured quantity (enumerate + lease) is untouched.
        score: list = []
        score_total = 350 * 17 * 3
        chunked_target = score_total - _TAIL_CLAIMS
        while len(score) < chunked_target:
            t0 = time.perf_counter()
            batch = orch.lease(
                "perf-worker",
                "score",
                min(_LEASE_CHUNK, chunked_target - len(score)),
            )
            lease_s += time.perf_counter() - t0
            assert batch, (
                f"score handout ended at {len(score)} of {chunked_target} — "
                "the panel's base depth is 3, so every (submission, "
                "criterion) owes three score units"
            )
            score.extend(batch)
            for unit in batch:
                orch.complete(unit.work_id)

        # The tail: the last _TAIL_CLAIMS units, one claim per call — the
        # per-claim measurement the batch handout cannot provide.
        tail_s = 0.0
        tail_units = 0
        while True:
            t0 = time.perf_counter()
            batch = orch.lease("perf-worker", "score", 1)
            tail_s += time.perf_counter() - t0
            if not batch:
                break
            score.extend(batch)
            tail_units += 1
        assert len(score) == score_total, (
            f"score handout {len(score)} != {score_total} — the panel's base "
            "depth is 3, so every (submission, criterion) owes three score units"
        )
        assert tail_units == _TAIL_CLAIMS, (
            f"the chunk-1 tail claimed {tail_units} of {_TAIL_CLAIMS} units — "
            "the reserved tail is the per-claim measurement, and a different "
            "count measures something else"
        )
        lease_s += tail_s

        scheduled = len(extract) + len(deterministic) + len(score)
        assert scheduled == _TOTAL_UNITS, (
            f"scheduled {scheduled} units, enumerated {report.units_enumerated} — "
            "units that never hand out are scheduling failures the budget cannot see"
        )

        per_unit_ms = (enumerate_s + lease_s) / scheduled * 1000.0
        assert per_unit_ms < BUDGET_MS_PER_UNIT, (
            f"scheduling overhead {per_unit_ms:.3f} ms/unit over {scheduled} units "
            f"(enumerate {enumerate_s:.2f}s + lease {lease_s:.2f}s) exceeds "
            f"NFR-ORCH-01's {BUDGET_MS_PER_UNIT} ms/unit budget — at 23,000 units "
            "the orchestrator, not the model, would be the bottleneck"
        )

        # The tail's own teeth, same unweakened budget: the per-claim cost a
        # batch handout amortizes away is exactly what the order cache removes.
        tail_ms = tail_s / tail_units * 1000.0
        assert tail_ms < BUDGET_MS_PER_UNIT, (
            f"a chunk-1 claim costs {tail_ms:.3f} ms against the "
            f"{BUDGET_MS_PER_UNIT} ms/unit budget (mean over the "
            f"{_TAIL_CLAIMS}-claim tail) — the per-(run, stage) order cache "
            "makes order resolution O(1) per claim (#59 measured 5.3 ms/unit "
            "without it), and a batch-only handout would hide this regression"
        )
    finally:
        store.close()
