"""`TS-24`'s residency and concurrency cases — `TC-ORCH-23`, `RES-11`, `RES-13` —
**landed with #62** (dispatch isolation, residency batching, concurrency,
progress granularity) and #66 (run-metrics persistence); this file shipped
red-by-design ahead of them and unmarked when they landed.

The three cases share one seam: the dispatch loop #62 ships. `TC-ORCH-23` is
residency — an `edge-local` profile that permits one resident model must finish a
model's ENTIRE batch (across all questions, criteria and submissions) before the
next loads, and record the swap count and duration (`FR-ORCH-19`). `RES-11` is a
sustained HTTP 429 — "expected, not an error: honour `Retry-After`, back off, reduce
concurrency" (§9.13), oracle **no unit failed; concurrency reduced;
`rate_limited_calls` incremented**. `RES-13` is OOM during a model swap — "reduce
concurrency, retry, then drop to a smaller panel and record it in `panel_config`"
(§9.11), oracle **the reduced panel is recorded, so a later validation record cannot
claim the full panel**.

**Interface this file assumes of #62/#66** — shipped exactly as assumed (the
`test_sweep_admission_and_ordering.py` precedent; the design reasoning stays):

| Name | Status |
|---|---|
| `Orchestrator.progress(run_id)` | design §3.7 Protocol member #62 ships; drives one dispatch pass and returns the report (AC4: counts by `(stage, criterion, judge)` plus totals — the four-seams rule's stage-level detail) |
| `report["concurrency"]` | the dispatch report carries the dispatch's current concurrency — the observable "dispatch respects concurrency / reduces" needs (four-seams rule #4); shipped as a mapping, exactly as assumed |
| the dispatch's model-call seam is injectable at the Orchestrator | the four-seams rule requires a deterministic transport for every external dependency the moment it is added, so #62's dispatch binds one injectably; shipped as `Orchestrator(store, transport=<call seam>)`, kwarg name exactly as assumed |
| the call seam's shape | `call(unit) -> Completion` for a successful model call, or a raise of the REAL taxonomy error (`RateLimitedError`, `MemoryError`) — `Completion` is shipped (#19), so the double returns the real type and only the *seam* is assumed |
| `Orchestrator.record_run_metrics` | the **invented name** shipped as-is — the design's Protocol has no metrics member; the KEY is the write `CT-ORCH-20` makes contract (M-ORCH is sole `run_metrics` writer, `CT-PROV-11` has it persisting the provider's counters) and the owning story is #66 |
| run_metrics reads | shipped: the EAV table `(run_id, metric, value)` (store.py `_DURABLE_001`), read through `store.durable().query(...)` |
| judges stand in for models | each panel judge names its own model, so model identity is the unit's `judge`; the panel used here has three distinct models |

Isolation: rung 2/3 — real store, real Tier P package, real cohort ledger; the
model-call seam is the only double (§4.2 forbids an in-memory stand-in for the store
contract outright). `RES-11`/`RES-13`'s failures are **injected, not induced** — the
plan's declared control for exactly these two ("real disk-full and real OOM:
injected, not induced; not reproducible in CI").
"""

from __future__ import annotations

import json

import pytest

from aeh.prov import Completion, RateLimitedError
from aeh.store import open_store
from tests.support.impl import ORCH_MODULE, require, require_attr
from tests.support.orch_run import (
    EDGE_PANEL_3,
    ORCH_COHORT_ID,
    orch_cfg,
    seed_cohort,
    seed_package,
)

pytestmark = [pytest.mark.integration]

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 6))
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
)


def _canned_completion() -> Completion:
    """One successful model answer — the real shipped type, cost=None because
    nothing on `edge-local` was billed (`Completion`'s own documented case)."""
    return Completion(
        text="synthetic band: B",
        tokens_in=10,
        tokens_out=5,
        latency_ms=1,
        resolved_build="fixture-build-2026-09-08",
        cached_prefix_tokens=0,
        cost=None,
    )


class _SucceedingCallSeam:
    """Every call succeeds — the control seam `TC-ORCH-23`'s residency sequence
    needs (batches must be able to COMPLETE for the unload to be observable)."""

    def __init__(self) -> None:
        self.calls = 0

    def call(self, unit):
        self.calls += 1
        return _canned_completion()


class _Always429CallSeam:
    """A sustained HTTP 429 — every call raises the real classification
    (`RateLimitedError`, #19), and the counter is `CT-PROV-11`'s shape: in-memory,
    read by `M-ORCH`, persisted to `run_metrics`."""

    def __init__(self) -> None:
        self.rate_limited_calls = 0

    def call(self, unit):
        self.rate_limited_calls += 1
        raise RateLimitedError(
            f"sustained HTTP 429 (call {self.rate_limited_calls}), Retry-After: 2"
        )


class _OomAtSwapCallSeam:
    """OOM at the swap point — the first call of any model that is not the resident
    one raises `MemoryError` (the weights are half-loaded and the box is out of
    memory); the resident model's own calls succeed, so the OOM is specifically a
    swap OOM, not a general outage. After #62's remedy drops the panel, the
    surviving judge's calls continue to succeed."""

    def __init__(self) -> None:
        self.resident: str | None = None
        self.oom_calls = 0

    def call(self, unit):
        model = unit.judge
        if self.resident is None:
            self.resident = model
        if model != self.resident:
            self.oom_calls += 1
            raise MemoryError(
                f"OOM while loading weights during the swap to {model!r} "
                f"(offending call {self.oom_calls})"
            )
        return _canned_completion()


def _seeded_run(store, transport):
    """The fixture chain with the call seam bound — the seam #62 must ship (see the
    module table). Returns `(orchestrator, run_id)`."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue="#62")
    seed_cohort(store, _SUBMISSIONS)
    version = seed_package(store, _CRITERIA)
    resolved = orch_cfg("edge-local", panel=EDGE_PANEL_3)
    orch = Orchestrator(store, transport=transport)
    run_id = orch.create_run(ORCH_COHORT_ID, version, resolved)
    orch.enumerate_units(run_id)
    return orch, run_id


def _metrics(store, run_id: str) -> dict[str, float]:
    rows = store.durable().query(
        "SELECT metric, value FROM run_metrics WHERE run_id = :r", r=run_id
    )
    return {row["metric"]: row["value"] for row in rows}


def test_tc_orch_23_residency_finishes_one_models_batch_before_the_next_loads(
    tmp_data_dir,
):
    """`TC-ORCH-23` (`FR-ORCH-19`, integration / rung 3, P1) — an `edge-local` profile
    whose residency policy permits one resident model: a model's entire batch across
    all questions, criteria and submissions completes before the next model loads.

    Oracle: the **sequence assertion** (every handout batch is single-model, and a
    model that has been unloaded never comes back — the handout order is a
    concatenation of per-model runs, no interleaving and no thrashing) **plus exact
    metrics** (the recorded swap count equals the observed model transitions, and a
    swap duration is recorded beside it — `CT-ORCH-20` names both as contract)."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue="#62")
    require_attr(Orchestrator, "progress", issue="#62")
    require_attr(Orchestrator, "record_run_metrics", issue="#66")

    store = open_store(tmp_data_dir)
    try:
        orch, run_id = _seeded_run(store, _SucceedingCallSeam())

        # Drive dispatch to exhaustion through the worker surface, recording the
        # handout order. Residency is the DISPATCHER's policy: it decides what a
        # lease may return, so the lease sequence is the observable.
        handout: list[str] = []
        while True:
            orch.progress(run_id)
            batch = orch.lease("worker-a", "score", 100)
            if not batch:
                break
            models = sorted({unit.judge for unit in batch})
            assert len(models) == 1, (
                f"one lease handed out {models} — with one resident model "
                "permitted, a batch that mixes models unloads and reloads weights "
                "mid-batch, which is exactly the thrashing FR-ORCH-19 exists to "
                "prevent on an edge-local box"
            )
            handout.extend(models)
            for unit in batch:
                orch.complete(unit.work_id)

        assert handout, "the fixture dispatched no score units"
        # Contiguity: once a model's run ends, no later handout returns to it.
        seen: list[str] = []
        for model in handout:
            if not seen or seen[-1] != model:
                assert model not in seen, (
                    f"model {model!r} was loaded, unloaded, and loaded AGAIN — the "
                    f"handout order {handout} interleaves models, and every "
                    "re-load is a weights swap an edge-local box pays for twice"
                )
                seen.append(model)
        assert len(seen) == 3, (
            f"the fixture dispatched {len(seen)} models, expected the panel's 3 — "
            "the swap-count oracle needs every model loaded at least once"
        )

        # Exact metrics: the swap count equals the observed transitions and a
        # swap duration is recorded beside it. Metric NAMES are contract per
        # CT-ORCH-20 but their exact strings are #66's to land, so the scan is
        # name-agnostic over the swap-shaped metrics (disclosed).
        metrics = _metrics(store, run_id)
        swap_metrics = {name: value for name, value in metrics.items() if "swap" in name}
        assert any(value == len(seen) - 1 for value in swap_metrics.values()), (
            f"run_metrics {metrics} does not record the observed swap count "
            f"({len(seen) - 1} transitions over {seen}) — the swap metrics are "
            "CT-ORCH-20's contract, and a swap that goes unrecorded cannot be "
            "costed or alerted on"
        )
        assert any("duration" in name for name in swap_metrics), (
            f"run_metrics records no swap duration beside the count: {metrics} — "
            "CT-ORCH-20 names 'model swap count and duration' together"
        )
    finally:
        store.close()


def test_res_11_sustained_rate_limiting_fails_no_unit_and_reduces_concurrency(
    tmp_data_dir,
):
    """`RES-11` (`FR-PROV-07`, resilience, P1) — sustained HTTP 429: expected, not an
    error. Oracle, all three parts: **no unit failed** (no unit leaves
    pending/leased, no attempt consumed, no error written — a rate limit is the
    provider's condition, not the unit's, and §9.11 says so in exactly those
    words); **concurrency reduced** (the dispatch report's concurrency shrinks while
    the 429s persist — monotone non-increasing with at least one strict reduction,
    §9.13's back-off); **`rate_limited_calls` incremented** (the provider's counter
    read and persisted into `run_metrics` — `CT-PROV-11`). The `Retry-After`
    honouring half is the provider's own case (`TC-PROV-11`) and is not re-asserted
    here."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue="#62")
    require_attr(Orchestrator, "progress", issue="#62")
    require_attr(Orchestrator, "record_run_metrics", issue="#66")

    transport = _Always429CallSeam()
    store = open_store(tmp_data_dir)
    try:
        orch, run_id = _seeded_run(store, transport)

        # Drive several dispatch passes into the sustained 429. progress() must
        # NOT raise: "expected, not an error" means the dispatch loop absorbs the
        # classification and reports, not that the caller learns to expect an
        # exception.
        concurrencies = []
        for _ in range(4):
            report = orch.progress(run_id)
            concurrencies.append(report["concurrency"])
        assert transport.rate_limited_calls >= 4, (
            "the seam made fewer calls than the passes drove — the sustained 429 "
            "never reached the dispatch loop"
        )

        # (1) No unit failed: every unit is still pending or leased, no attempt
        # consumed, no error written — the ledger cannot tell a 429 happened.
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT status, attempts, last_error FROM work_unit WHERE run_id = :r",
            r=run_id,
        )
        assert rows, "the fixture enumerated no units"
        for row in rows:
            assert row["status"] in ("pending", "leased"), (
                f"a unit under sustained 429 is '{row['status']}' — rate limiting "
                "is 'expected, not an error' (§9.11); requeueing, quarantining or "
                "failing units for it converts a provider condition into lost work"
            )
            assert row["attempts"] == 0, (
                f"a rate-limited call consumed an attempt ({row['attempts']}) — "
                "sustained 429s would then quarantine the whole cohort at the "
                "ceiling, which is the exact failure RES-11 forbids"
            )
            assert row["last_error"] is None, (
                "a rate-limited call wrote a unit-level error — the taxonomy is "
                "for unit failures and a 429 is not one"
            )

        # (2) Concurrency reduced: non-increasing across the passes, strictly down
        # at least once — the back-off must be observable, not just declared.
        assert all(
            later <= earlier
            for earlier, later in zip(concurrencies, concurrencies[1:])
        ), f"concurrency rose under sustained 429s: {concurrencies} (§9.13)"
        assert concurrencies[-1] < concurrencies[0], (
            f"concurrency never reduced under sustained 429s: {concurrencies} — "
            "the dispatch kept pressing a provider that answers 429"
        )

        # (3) rate_limited_calls incremented: the provider's in-memory counter is
        # persisted into run_metrics (CT-PROV-11 — M-ORCH reads and persists).
        metrics = _metrics(store, run_id)
        persisted = [
            value for name, value in metrics.items() if "rate_limited" in name
        ]
        assert persisted and persisted[0] >= 1, (
            f"run_metrics {metrics} carries no incremented rate_limited_calls — "
            "the counter CT-PROV-11 has M-ORCH persist never made it to the "
            "record an operator would alert on"
        )
    finally:
        store.close()


def test_res_13_oom_during_swap_reduces_concurrency_and_records_the_smaller_panel(
    tmp_data_dir,
):
    """`RES-13` (`FR-ORCH-19`, resilience, P1) — out-of-memory during a model swap:
    reduce concurrency, retry, then drop to a smaller panel and **record it in
    `panel_config`** (§9.11). Oracle: the reduced panel is recorded, so a later
    validation record cannot claim the full panel.

    The reduction is a **drop, not a substitution**: the recorded panel is a subset
    of the frozen one — a panel that swapped a judge for a different model would be
    CT-PROV-08's forbidden substitution wearing an OOM's clothes. No unit carries
    the OOM as its own failure either: the OOM is the BOX's condition, and §9.11's
    remedy is concurrency and panel shape, not the failure taxonomy."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue="#62")
    require_attr(Orchestrator, "progress", issue="#62")

    transport = _OomAtSwapCallSeam()
    store = open_store(tmp_data_dir)
    try:
        orch, run_id = _seeded_run(store, transport)
        before = store.cohort(ORCH_COHORT_ID).query(
            "SELECT panel_config FROM run WHERE run_id = :r", r=run_id
        )[0]["panel_config"]
        before_judges = _judges_of(before)

        # Drive dispatch into the swap: the resident model's calls succeed until
        # its batch ends, the next model's first call OOMs, and the remedy runs.
        concurrencies = []
        for _ in range(4):
            report = orch.progress(run_id)
            concurrencies.append(report["concurrency"])
        assert transport.oom_calls >= 1, (
            "the seam never OOM'd at a swap — the fixture did not reach the "
            "condition this case exists for"
        )

        # The run row now records the SMALLER panel — the oracle's exact words.
        after = store.cohort(ORCH_COHORT_ID).query(
            "SELECT panel_config FROM run WHERE run_id = :r", r=run_id
        )[0]["panel_config"]
        after_judges = _judges_of(after)
        assert len(after_judges) < len(before_judges), (
            f"panel_config was not reduced after the OOM ({before_judges} -> "
            f"{after_judges}) — a later validation record would claim the full "
            "panel the box could not hold (§9.11: record it in panel_config)"
        )
        assert set(after_judges) < set(before_judges), (
            f"the reduced panel {after_judges} is not a subset of the frozen panel "
            f"{before_judges} — an OOM drops judges, it never substitutes them "
            "(CT-PROV-08: no silent substitution, terminal or not)"
        )

        # Concurrency reduced and the run still dispatching (retry): the OOM is
        # absorbed into the dispatch report, not raised into the caller.
        assert all(
            later <= earlier
            for earlier, later in zip(concurrencies, concurrencies[1:])
        ), f"concurrency rose across the OOM remedy: {concurrencies} (§9.11)"
        assert concurrencies[-1] < concurrencies[0], (
            f"concurrency never reduced after the OOM: {concurrencies} — §9.11's "
            "remedy begins with 'reduce concurrency', and the retry rides on it"
        )

        # And no unit carried the OOM as its own failure.
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT status, last_error FROM work_unit WHERE run_id = :r", r=run_id
        )
        for row in rows:
            assert row["status"] != "quarantined" and row["last_error"] is None, (
                f"a unit recorded the OOM as its own failure ({row['status']}, "
                f"{row['last_error']!r}) — the box's condition is §9.11's "
                "concurrency remedy, not the unit taxonomy's"
            )
    finally:
        store.close()


def _judges_of(panel_config: str) -> list[str]:
    """The judge identities in a run row's `panel_config` snapshot — the same JSON
    `create_run` freezes. Parsed permissively over its judge/model-bearing entries,
    because the snapshot's exact shape is `create_run`'s (#57, shipped) while the
    REDUCED shape is #62's to land; what the oracle needs is a comparable identity
    list before and after."""
    parsed = json.loads(panel_config)
    judges: list[str] = []
    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict):
                        identity = entry.get("judge_id") or entry.get("model")
                        if identity:
                            judges.append(str(identity))
                    elif isinstance(entry, str):
                        judges.append(entry)
    assert judges, f"panel_config parsed to no judges: {panel_config[:200]}"
    return judges
