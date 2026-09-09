"""`TC-ORCH-35` (`FR-ORCH-18`, `FR-ORCH-13`, `OBS-03`, `CT-ORCH-20`;
observability / rung 2, P1) — `run_metrics` carries the full signal set: total
and escalated units, quarantined units, wall clock, tokens, `cache_hit_rate`,
peak concurrency, retries, rate-limit counters, estimated and actual cost,
resolved builds, and model swap count and duration — each present, and each
matches a hand-counted expectation where the fixture can count it
(**written ahead of the run-metrics write, #66**).

`CT-ORCH-20` makes these names contract: `M-STATS` and the acceptance gate read
them. Six of them are pinned verbatim by `FR-PROV-12` — `transport_retries`,
`rate_limited_calls`, `rate_limit_wait_s`, `tokens_in`, `tokens_out`,
`cache_hit_rate` — and are asserted by exact name. The rest are asserted
name-agnostically per concept (the `TC-ORCH-23` precedent: a metric whose
concept is present but whose exact string is the writer's to land fails neither
the case nor the truth).

The fixture drives every condition OBS-03 names: quarantines (the shipped
fail ladder), an escalation (the §3.7 member #60 ships), and a tripped breaker
(FR-ORCH-13's criterion breaker — the run's own escalation policy; the
breaker's tripped state is reachable through the escalation surface at
landing, reconciled there).

**Interface this file assumes** (reconciled deliberately):

| Name | Status |
|---|---|
| `Orchestrator.record_run_metrics` | **invented-and-reserved name** — the design's Protocol has no metrics member; #65 reserved it for TS-25 and this file claims it (see the `WRITTEN_AHEAD_BLOCKERS` entry). Whether dispatch flushes metrics through it internally or the test calls it explicitly reconciles at landing; the file requires the symbol and reads the ledger's `run_metrics` rows |
| `Orchestrator.progress(run_id)` | #62's dispatch driver, as `TC-ORCH-31`'s file assumes |
| the model-call seam is injectable | `Orchestrator(store, transport=<seam>)`, kwarg reconciled at landing; the seam returns the real `Completion` with known token counts, so the token totals are hand-countable |
| `Orchestrator.enqueue_escalation(run_id, submission_id=..., criterion_id=...)` | #60's member, the same shape `RES-06`/`RES-08`'s file assumes |
| run_metrics reads | shipped: the EAV rows `(run_id, metric, value)`, read through the durable tier |

Isolation: rung 2 — real store, real package, real cohort ledger; the
model-call seam is the only double. No network.
"""

from __future__ import annotations

import pytest

from aeh.orch import WorkError
from aeh.prov import Completion
from aeh.store import open_store
from tests.support.impl import ORCH_MODULE, require, require_attr
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#62"

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 7))
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
)

#: FR-PROV-12 pins these names verbatim: the provider's counters persist into
#: run_metrics under exactly these names (CT-ORCH-20 makes the names contract).
PROV12_METRIC_NAMES = (
    "transport_retries",
    "rate_limited_calls",
    "rate_limit_wait_s",
    "tokens_in",
    "tokens_out",
    "cache_hit_rate",
)

#: Every CT-ORCH-20 concept, as (concept label, name tokens that satisfy it).
#: A concept with NO matching metric name fails presence; the countable ones
#: are value-checked against hand counts below.
CONCEPTS = (
    ("total units", ("total",)),
    ("escalated units", ("escalat",)),
    ("quarantined units", ("quarantin",)),
    ("wall clock", ("wall", "clock", "duration_s", "elapsed")),
    ("tokens", ("tokens_in", "tokens_out")),
    ("cache_hit_rate", ("cache_hit_rate",)),
    ("peak concurrency", ("peak",)),
    ("retries", ("retr",)),
    ("rate-limit counters", ("rate_limited", "rate_limit")),
    ("estimated cost", ("estimated",)),
    ("actual cost", ("actual",)),
    ("resolved builds", ("build",)),
    ("model swap count and duration", ("swap",)),
)


def _metrics(store: object, run_id: str) -> dict:
    rows = store.durable().query(
        "SELECT metric, value FROM run_metrics WHERE run_id = :r", r=run_id
    )
    return {row["metric"]: row["value"] for row in rows}


class _CountingSeam:
    """Every call succeeds with KNOWN token counts, so `tokens_in`/`tokens_out`
    are hand-countable, and the resolved build is known, so the resolved-builds
    concept is value-checkable."""

    def __init__(self) -> None:
        self.calls = 0

    def call(self, req):
        self.calls += 1
        return Completion(
            text="synthetic band: B",
            tokens_in=10,
            tokens_out=5,
            latency_ms=1,
            resolved_build="fixture-build-2026-09-08",
            cached_prefix_tokens=0,
            cost=None,
        )


def test_tc_orch_35_run_metrics_carries_every_ct_orch_20_signal(tmp_data_dir):
    """`TC-ORCH-35` — a run with a quarantine, an escalation and a tripped
    breaker persists `run_metrics` in full: every CT-ORCH-20 concept present
    (by exact name where FR-PROV-12 pins it), and the hand-countable values
    match the fixture's ledger."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    require_attr(Orchestrator, "progress", issue=ISSUE)
    require_attr(Orchestrator, "record_run_metrics", issue="#66")
    require_attr(Orchestrator, "enqueue_escalation", issue="#60")

    seam = _CountingSeam()
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _version = seed_run(
            store,
            submissions=_SUBMISSIONS,
            criteria=_CRITERIA,
            panel=None,  # orch_cfg's default: the three-judge edge panel
        )
        orch.enumerate_units(run_id)

        # Extract and deterministic units: complete them all (unlock Sweep 2).
        for stage in ("extract", "deterministic"):
            while True:
                batch = orch.lease("metrics-worker", stage, 64)
                if not batch:
                    break
                for unit in batch:
                    orch.complete(unit.work_id)

        # Score units: complete all but one, which rides the shipped three-fail
        # ladder into `quarantined` (FR-ORCH-18) — the run continues.
        quarantined = 0
        while True:
            batch = orch.lease("metrics-worker", "score", 64)
            if not batch:
                break
            for unit in batch:
                if unit.submission_id == "SYN-006" and quarantined == 0:
                    for _ in range(3):
                        orch.fail(
                            unit.work_id,
                            WorkError(message="injected: the metrics quarantine leg"),
                        )
                    quarantined = 1
                else:
                    orch.complete(unit.work_id)

        # The escalation leg: one escalated re-check through the §3.7 member
        # (#60), against a completed unit's (submission, criterion).
        orch.enqueue_escalation(
            run_id, submission_id="SYN-001", criterion_id="C1"
        )
        # The breaker leg (FR-ORCH-13): the criterion breaker's tripped state is
        # the run's own escalation policy; reconciled at landing — the escalation
        # above is the surface the breaker state rides.

        # Drive the dispatch so the metrics persist through the write (#66).
        for _ in range(4):
            orch.progress(run_id)

        metrics = _metrics(store, run_id)
        assert metrics, (
            "run_metrics holds no rows for the run — CT-ORCH-20 makes the "
            "write contract and M-STATS reads it; an empty metrics table is "
            "the silent-failure shape (a bare status with nothing beside it)"
        )

        # Presence, exact names first (FR-PROV-12's verbatim six).
        missing_exact = [n for n in PROV12_METRIC_NAMES if n not in metrics]
        assert not missing_exact, (
            f"run_metrics is missing FR-PROV-12's pinned counter(s) "
            f"{missing_exact} — the provider's counters persist under these "
            "exact names (CT-PROV-11, CT-ORCH-20); present: "
            f"{sorted(metrics)}"
        )
        # Presence, per concept (name-agnostic; exact strings reconcile).
        for label, tokens in CONCEPTS:
            if label == "tokens" or label == "cache_hit_rate" or label == "rate-limit counters":
                continue  # already asserted by exact name above
            assert any(
                any(token in name for token in tokens) for name in metrics
            ), (
                f"run_metrics carries no {label} signal — CT-ORCH-20 lists it "
                f"in full; present: {sorted(metrics)}"
            )
        swap_names = [n for n in metrics if "swap" in n]
        assert any("duration" in n for n in swap_names), (
            f"run_metrics records a swap count but no swap duration beside it: "
            f"{sorted(metrics)} — CT-ORCH-20 names 'model swap count and "
            "duration' together"
        )

        # Hand-counted values, where the fixture can count them.
        assert metrics["tokens_in"] == 10 * seam.calls, (
            f"run_metrics tokens_in={metrics['tokens_in']}, the seam served "
            f"{seam.calls} calls at 10 tokens each — OBS-03: each field matches "
            "a hand-counted expectation, and a token total that drifts breaks "
            "the cost model built on it"
        )
        assert metrics["tokens_out"] == 5 * seam.calls, (
            f"run_metrics tokens_out={metrics['tokens_out']}, the seam served "
            f"{seam.calls} calls at 5 tokens each"
        )
        assert metrics["rate_limited_calls"] == 0, (
            f"run_metrics counts {metrics['rate_limited_calls']} rate-limited "
            "calls against a seam that never raised one — a counter that "
            "increments without cause is an alert that fires without cause"
        )
        assert 0 <= metrics["cache_hit_rate"] <= 1, (
            f"cache_hit_rate={metrics['cache_hit_rate']} is not a rate — the "
            "acceptance gate reads it as one"
        )
        assert any(
            "fixture-build-2026-09-08" in str(value) for value in metrics.values()
        ), (
            f"no metric records the resolved build the seam served — "
            "FR-PROV-04: the *resolved* build metadata aggregates into "
            "run_metrics.resolved_builds"
        )
    finally:
        store.close()
