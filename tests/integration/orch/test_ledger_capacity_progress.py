"""`TC-ORCH-33` — the progress half (**written ahead of #62**): progress
latency measured at both the ~23,000-unit and the 40,000-unit scale and
compared, the third operation of the case whose lease and complete halves run
green in `test_ledger_capacity.py` (the `TC-ORCH-29` two-file precedent for an
oracle spanning a shipped and an unshipped surface).

`NFR-ORCH-06`: at least 40,000 ledger units per run **without degradation**.
The plan's oracle: "latency measured at both 23,000 and 40,000 and compared".
The tolerance — per-unit mean at the larger scale within 2x the smaller's — is
the same stated-in-file number the green half uses, generous against SQLite's
logarithmic index growth and self-normalizing (both sizes run in this test, on
this machine, back to back).

**Interface this file assumes of #62** (the `test_failure_visibility.py`
shape):

| Name | Status |
|---|---|
| `Orchestrator.progress(run_id)` | design §3.7 Protocol member #62 ships; the report is the operator surface `TC-ORCH-31` reads |

Isolation: rung 2 — real store, real Tier P package, real cohort ledger; the
driver plays the workers; no doubles, no provider, no network.
"""

from __future__ import annotations

import time

import pytest

from aeh.store import open_store
from tests.support.impl import ORCH_MODULE, require, require_attr
from tests.support.orch_run import seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#62"

#: Handout chunk per lease call — a batch size for the fixture's work pass.
_LEASE_CHUNK = 500

#: The comparative tolerance, shared with the green half of the case.
_DEGRADATION_TOLERANCE = 2.0

_SIZES = (
    (350, 350 * 17 + 350 * 17 * 3 + 350),
    (600, 600 * 17 + 600 * 17 * 3 + 600),
)
assert _SIZES[0][1] >= 23000 and _SIZES[1][1] >= 40000


def _criteria() -> tuple:
    """17 judged open criteria + 1 deterministic MCQ — the uniform panel."""
    return tuple(
        [
            {"criterion_id": f"C{i:02d}", "kind": "open", "scoring_model": "holistic"}
            for i in range(1, 18)
        ]
        + [{"criterion_id": "MCQ", "kind": "mcq", "scoring_model": "deterministic"}]
    )


def _progress_latency(store: object, submissions: tuple, total_units: int) -> float:
    """One run at one size: enumerate, work the ledger to a mixed state, then
    time `progress()` over repeated polls. Returns the per-poll mean seconds.

    The polls run over a ledger with units in EVERY state (done, leased,
    pending) — a progress query timed against a drained ledger measures a
    report of zeros, not the serving path the operator polls mid-run."""
    orch, run_id, _version = seed_run(
        store,
        submissions=submissions,
        criteria=_criteria(),
        panel=None,  # orch_cfg's default: the three-judge edge panel
    )
    report = orch.enumerate_units(run_id)
    assert report.units_enumerated == total_units

    # Extract and deterministic units complete (unlock Sweep 2); a slice of
    # score units stays leased so the polled ledger is mid-run, not drained.
    leased_reserve: list = []
    for stage in ("extract", "deterministic", "score"):
        while True:
            batch = orch.lease("progress-worker", stage, _LEASE_CHUNK)
            if not batch:
                break
            if stage == "score" and len(leased_reserve) < _LEASE_CHUNK:
                leased_reserve.extend(batch[:32])
                batch = batch[32:]
            for unit in batch:
                orch.complete(unit.work_id)

    polls = 10
    t0 = time.perf_counter()
    for _ in range(polls):
        orch.progress(run_id)
    return (time.perf_counter() - t0) / polls


def test_tc_orch_33_progress_latency_at_23k_and_40k_without_degradation(
    tmp_data_dir,
):
    """`TC-ORCH-33` (progress half) — the per-poll mean at the 40,000-unit
    scale within the stated tolerance of the 23,000-unit scale's."""
    require_attr(require(ORCH_MODULE, "Orchestrator", issue=ISSUE), "progress",
                 issue=ISSUE)

    latencies: dict[int, float] = {}
    for subs, total_units in _SIZES:
        # One store per size: a run owns its cohort and ledger rows, and the
        # comparison is between two independent runs, not two passes over one.
        size_dir = tmp_data_dir / f"run-{subs}"
        size_dir.mkdir(parents=True, exist_ok=True)
        store = open_store(size_dir)
        try:
            latencies[total_units] = _progress_latency(
                store, tuple(f"SYN-{i:03d}" for i in range(1, subs + 1)), total_units
            )
        finally:
            store.close()

    small_ms = latencies[_SIZES[0][1]] * 1000.0
    large_ms = latencies[_SIZES[1][1]] * 1000.0
    assert large_ms <= small_ms * _DEGRADATION_TOLERANCE, (
        f"progress latency degraded with scale: {small_ms:.3f} ms/poll at "
        f"{_SIZES[0][1]} units vs {large_ms:.3f} ms/poll at {_SIZES[1][1]} "
        f"units (tolerance {_DEGRADATION_TOLERANCE}x) — the console polls this "
        "path for every progress view (CT-ORCH-17), and a query that slows "
        "superlinearly in the ledger size does not handle 40,000 units"
    )
