"""`TC-ORCH-33` (`NFR-ORCH-06`, `PERF-09`; performance / rung 2, P2) — the ledger
handles 40,000 units in one run **without degradation**: latency measured at both
the ~23,000-unit and the 40,000-unit scale and compared, over the orchestrator's
operations.

**Which operations live in this file.** The case names three — lease, complete
and progress. Lease and complete are shipped (#58) and are measured here, green.
The progress half needs `Orchestrator.progress` (#62, unshipped) and lives in
`test_ledger_capacity_progress.py` (writtenahead, same fixture, same tolerance),
the `TC-ORCH-29` two-file precedent for a case whose oracle spans a shipped and
an unshipped surface. When #62 lands, the two files together carry the case.

Fixture: the uniform-panel run at two sizes — 350 submissions (24,150 units,
the `TC-ORCH-30`/`TC-ORCH-31` shape) and 600 submissions (41,400 units, at and
above NFR-ORCH-06's 40,000 floor).

Oracle, in the plan's words "handled without degradation ... and compared":

- **Capacity** (the absolute half): at the 40,000-unit size, every unit
  enumerates, leases and completes — a unit that cannot hand out or retire at
  scale is the degradation NFR-ORCH-06 exists to forbid.
- **No degradation** (the comparative half): per-unit mean lease wall time and
  per-unit mean complete wall time at 41,400 stay within 2x their 24,150-unit
  counterparts. The tolerance is stated here because the plan names no number;
  2x is generous against SQLite's logarithmic index growth, which is the only
  growth a correct implementation should show. The ratio is self-normalizing —
  both sizes run on the same machine in the same test, so load moves both
  sides, not the comparison.
- **Footprint** (`PERF-09`'s second measure): the 40,000-unit run's on-disk
  size stays under the 500 MB the plan pins — handling the scale by ballooning
  is not handling it.

Enumeration wall time is `TC-ORCH-30`'s measured quantity (the per-(run, stage)
order cache) and is not re-asserted here.

Isolation: rung 2 — real store, real Tier P package, real cohort ledger; no
doubles, no provider, no network.
"""

from __future__ import annotations

import time

import pytest

from aeh.store import open_store
from tests.support.orch_run import seed_run

pytestmark = [pytest.mark.integration]

#: Handout chunk per lease call — a batch size for the scheduling pass.
_LEASE_CHUNK = 500

#: The comparative tolerance: per-unit mean latency at the 40,000-unit scale may
#: exceed the 23,000-unit scale's by at most this factor ("without degradation").
_DEGRADATION_TOLERANCE = 2.0

_SIZES = (
    # (submissions, units) — units = subs * 17 extract + subs * 17 * 3 score + subs det
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


def _drain(orch: object, stage: str, sink: list) -> float:
    """Lease `stage` to exhaustion, timing ONLY the lease calls (seconds)."""
    elapsed = 0.0
    while True:
        t0 = time.perf_counter()
        batch = orch.lease("capacity-worker", stage, _LEASE_CHUNK)
        elapsed += time.perf_counter() - t0
        if not batch:
            return elapsed
        sink.extend(batch)


def _run_size(store: object, submissions: tuple, total_units: int) -> tuple[float, float, int]:
    """One run at one size: enumerate, then lease+complete every unit.

    Returns `(lease_seconds, complete_seconds, units)` — the lease and complete
    wall times cover ONLY those calls (seeding and enumeration are excluded:
    `PERF-09` compares the ledger's serving operations, not its loading).
    """
    orch, run_id, _version = seed_run(
        store,
        submissions=submissions,
        criteria=_criteria(),
        panel=None,  # orch_cfg's default: the three-judge edge panel
    )
    report = orch.enumerate_units(run_id)
    assert report.units_enumerated == total_units

    lease_s = 0.0
    complete_s = 0.0
    units = 0
    for stage in ("extract", "deterministic", "score"):
        while True:
            t0 = time.perf_counter()
            batch = orch.lease("capacity-worker", stage, _LEASE_CHUNK)
            lease_s += time.perf_counter() - t0
            if not batch:
                break
            t0 = time.perf_counter()
            for unit in batch:
                orch.complete(unit.work_id)
            complete_s += time.perf_counter() - t0
            units += len(batch)
    return lease_s, complete_s, units


def test_tc_orch_33_lease_and_complete_at_23k_and_40k_without_degradation(
    tmp_data_dir,
):
    """`TC-ORCH-33` (lease + complete half) — both scales fully served, and the
    per-unit means at the larger scale within the stated tolerance."""
    timings: dict[int, tuple[float, float, int]] = {}
    for subs, total_units in _SIZES:
        # One store per size: a run owns its cohort and ledger rows, and the
        # comparison is between two independent runs, not two passes over one.
        size_dir = tmp_data_dir / f"run-{subs}"
        size_dir.mkdir(parents=True, exist_ok=True)
        store = open_store(size_dir)
        try:
            timings[total_units] = _run_size(
                store, tuple(f"SYN-{i:03d}" for i in range(1, subs + 1)), total_units
            )
        finally:
            store.close()

    (small_lease, small_complete, small_units) = timings[_SIZES[0][1]]
    (large_lease, large_complete, large_units) = timings[_SIZES[1][1]]

    # Capacity: both scales fully served. The small run's count is the
    # comparison's denominator — a short small run inflates the small
    # per-unit mean and silently relaxes the 2x tolerance.
    assert small_units == _SIZES[0][1], (
        f"{small_units} of {_SIZES[0][1]} units served at the 23,000-unit "
        "scale — the baseline half of the comparison must be a fully served "
        "run, or the tolerance compares against a degraded reference"
    )
    # Capacity: every unit at the 40,000 scale was leased and retired.
    assert large_units == _SIZES[1][1], (
        f"{large_units} of {_SIZES[1][1]} units served at the 40,000-unit scale — "
        "NFR-ORCH-06's floor is 40,000 ledger units per run, and units that "
        "cannot hand out or retire at scale are the failure it forbids"
    )

    # PERF-09's second measure: footprint stays under 500 MB at the
    # 40,000-unit scale — a ledger that serves 40k units only by ballooning
    # on disk fails the clause the plan wrote beside the latency one.
    large_dir = tmp_data_dir / f"run-{_SIZES[1][0]}"
    footprint_mb = (
        sum(path.stat().st_size for path in large_dir.rglob("*") if path.is_file())
        / (1024 * 1024)
    )
    assert footprint_mb < 500, (
        f"the 41,400-unit run left {footprint_mb:.1f} MB on disk under "
        f"{large_dir} — PERF-09's footprint ceiling is 500 MB, and a ledger "
        "that handles the scale only by ballooning does not handle it"
    )

    small_ms = small_lease / small_units * 1000.0
    large_ms = large_lease / large_units * 1000.0
    assert large_ms <= small_ms * _DEGRADATION_TOLERANCE, (
        f"lease latency degraded with scale: {small_ms:.3f} ms/unit at "
        f"{small_units} units vs {large_ms:.3f} ms/unit at {large_units} units "
        f"(tolerance {_DEGRADATION_TOLERANCE}x) — a serving path that slows "
        "superlinearly in the ledger size does not handle 40,000 units"
    )

    small_ms = small_complete / small_units * 1000.0
    large_ms = large_complete / large_units * 1000.0
    assert large_ms <= small_ms * _DEGRADATION_TOLERANCE, (
        f"complete latency degraded with scale: {small_ms:.3f} ms/unit at "
        f"{small_units} units vs {large_ms:.3f} ms/unit at {large_units} units "
        f"(tolerance {_DEGRADATION_TOLERANCE}x) — retirement is a serving "
        "operation the operator feels on every unit"
    )
