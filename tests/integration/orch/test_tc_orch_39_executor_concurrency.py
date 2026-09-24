"""`TS-85` (issue #379) — `TC-ORCH-39`: the concurrency ceiling governs the **production**
executor, not only the test transport (`FR-ORCH-27`, `FR-ORCH-21`).

| Precondition | Oracle |
|---|---|
| ceiling 4, 40 units, `ProductionStageExecutor` over a fixture provider with a 5 ms barrier per call | peak in-flight `GovernedProvider.complete` calls ≤ 4 **and reaches** 4; `peak_concurrency` metric = 4 |

**Why this case exists at all, given `TC-ORCH-24` already asserts a ceiling.** §4.9's
substitution register is explicit: the base governor suites (`TC-ORCH-24`, `TC-ORCH-33`,
`TC-ORCH-35`) dispatch through `TransportStageExecutor`, which has no worker behind it —
"governor suites using it prove counting and ceilings, never payload-before-done". They would
stay green if the production executor escaped the pool entirely, because they never run it.
This is the companion case that puts the real door under the same ceiling.

**Both halves of the oracle are load-bearing, and the second is the one that catches the
common defect.** "≤ 4" alone passes trivially against a dispatch that ran everything
one-at-a-time — which is exactly what a pool accidentally constructed with `max_workers=1`,
or an executor that serialised on a lock inside the worker, would produce. "Reaches 4" is what
makes the ceiling a ceiling rather than an upper bound nobody approaches. Little's law is why
the barrier is in the provider rather than the test body: the in-flight peak a pool can be
*observed* to reach is bounded by `call_duration / submission_interval`, so a call that
returned instantly would be observed at a peak of 1 however wide the pool was.

**Extract units, not the plan's score units — a deliberate, reported divergence.** A score
unit reaching the production door needs its cell's `integrity_pre` phase recorded first
(`FR-ORCH-30`, `TC-ORCH-42` arm A) and its extraction evidence persisted, so 40 score units
means first driving 40 extractions and 40 integrity hooks — a composed run, which is
`TC-PIPE-01`'s subject, not this one. What this case is about is whether the governor's
ceiling reaches the production executor's pool, and the pool is stage-agnostic: it is
`_run_model_batch`'s single `ThreadPoolExecutor`, shared by both stages. Forty extract units
exercise it identically and keep the case at the level the requirement lives at. #379 reports
the substitution rather than burying it.

**Isolation: rung 3** — real store, real package, real `ExtractionWorker` behind the seam,
with the model boundary a fixture provider (`CT-PROV-10`: the only egress point).
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pipeline  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.orch import Orchestrator
from aeh.pipeline import ProductionStageExecutor
from aeh.store import Statement, open_store
from aeh.conf import CohortRef, resolve_run_config
from tests.support.conf_builders import EDGE_PANEL_3, edge_cfg
from tests.support.extract_vocabulary import span_completion
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    PLAIN_TRANSCRIPT,
    seed_documents,
    seed_run,
)

pytestmark = pytest.mark.integration

#: `FR-ORCH-21`'s ceiling for this case, and the figure both halves of the oracle name.
CEILING = 4

#: Forty units, as the plan specifies — ten times the ceiling, so the pool is asked to refill
#: many times over and a peak of 4 cannot be an artefact of one lucky burst.
UNIT_COUNT = 40

#: The per-call barrier. Long enough that every worker in a batch is still inside `complete`
#: when the next is submitted (see Little's law, above); short enough that forty calls at a
#: width of four cost about 50 ms of wall time.
BARRIER_MS = 5.0

#: One token out per answer, so `tokens_out` counts governed calls exactly.
TOKENS_PER_CALL = 1

CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)
SUBMISSIONS = tuple(f"S{index:03d}" for index in range(UNIT_COUNT))

_COUNT_METRIC = Statement(
    "SELECT value FROM run_metrics WHERE run_id = :run_id AND metric = :metric"
)


class BarrierProvider:
    """A fixture provider that holds each call for `BARRIER_MS` and records its own peak.

    The peak recorded here is the **provider-side** figure — how many calls were inside
    `complete` at once. `GovernedProvider` wraps this object, so the two must agree; asserting
    on both is what separates "the governor counted correctly" from "the pool was actually
    that wide".
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0
        self.calls = 0

    def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002 — the seam's shape
        return None

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        with self._lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            self.calls += 1
        try:
            time.sleep(BARRIER_MS / 1000.0)
        finally:
            with self._lock:
                self.in_flight -= 1
        build = getattr(model_ref, "build_id", None) or "fixture-build"
        answer = span_completion(
            [{"start": 0, "end": 5, "text": PLAIN_TRANSCRIPT[:5]}], build_id=build
        )
        # One token out per call, so the run's `tokens_out` metric IS its count of governed
        # calls — the equality the second case reads. `span_completion` reports zero, which
        # would make that assertion 0 == 0 whatever the wrapper did.
        return replace(answer, tokens_out=TOKENS_PER_CALL)


@pytest.fixture
def ceilinged_run(tmp_data_dir):
    """Forty pending extract units on a run whose concurrency ceiling is `CEILING`."""
    store = open_store(tmp_data_dir)
    try:
        # The ceiling is the run's FROZEN one (`_concurrency_ceiling` reads it back out of
        # `provider_config`), so it is set in the config the run is created with — there is no
        # constructor knob, and setting one mid-run would be a width the operator never
        # approved (`FR-CONF-07`).
        config = resolve_run_config(
            edge_cfg(panel=EDGE_PANEL_3, HARNESS_CONCURRENCY=str(CEILING)),
            CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
        )
        assert config.concurrency_ceiling == CEILING, (
            f"the fixture resolved a ceiling of {config.concurrency_ceiling}, not {CEILING}; "
            "the hardware policy clamped it and the case would assert against the wrong figure"
        )
        seeder, run_id, _version = seed_run(
            store, submissions=SUBMISSIONS, criteria=CRITERIA, cfg=config,
        )
        seed_documents(store, SUBMISSIONS)
        seeder.enumerate_units(run_id)
        provider = BarrierProvider()
        executor = ProductionStageExecutor(store, provider, config)
        orchestrator = Orchestrator(store, executor=executor, provider=provider)
        executor.orchestrator = orchestrator
        orchestrator.start(run_id)
        yield store, orchestrator, provider, run_id
    finally:
        store.close()


def _metric(store: Any, run_id: str, name: str) -> float | None:
    """One `run_metrics` value, read through the **durable** tier the rows live in."""
    rows = store.durable().query(_COUNT_METRIC, run_id=run_id, metric=name)
    return float(rows[0]["value"]) if rows else None


# --- TC-ORCH-39 -----------------------------------------------------------------------------


def test_tc_orch_39_the_production_executor_runs_inside_the_concurrency_ceiling(
    ceilinged_run,
):
    """Peak in-flight calls ≤ 4 and reaches 4, and `peak_concurrency` agrees.

    One assertion would not do. The upper bound alone is satisfied by a serial dispatch; the
    lower bound alone is satisfied by an unbounded one; and the metric alone is satisfied by a
    counter that was never connected to the pool. The three together say the ceiling governs
    the production executor's pool and the run's own report of it is true.
    """
    store, orchestrator, provider, run_id = ceilinged_run

    passes = 0
    while provider.calls < UNIT_COUNT and passes < 40:
        orchestrator.progress(run_id)
        passes += 1

    assert provider.calls >= UNIT_COUNT, (
        f"only {provider.calls} of {UNIT_COUNT} units reached the provider in {passes} "
        "passes; the case cannot speak about a ceiling it never approached"
    )
    assert provider.peak <= CEILING, (
        f"{provider.peak} calls were in flight at once against a ceiling of {CEILING} — "
        "FR-ORCH-21's ceiling does not reach the production executor's pool"
    )
    assert provider.peak == CEILING, (
        f"the peak reached only {provider.peak} of {CEILING}: the dispatch never used the "
        "width it was given, so the '≤ ceiling' assertion above is passing over a serial run "
        "and would pass against max_workers=1"
    )

    reported = _metric(store, run_id, "peak_concurrency")
    assert reported == float(CEILING), (
        f"run_metrics reports peak_concurrency={reported!r}; the pool was observed at "
        f"{provider.peak}. The operator's figure and the run's behaviour must be the same "
        "number (FR-ORCH-21, CT-PROV-11)"
    )


def test_tc_orch_39_every_unit_crossed_the_governed_wrapper(ceilinged_run):
    """The provider's own call count equals the run's counted calls — no unit went round.

    §8.3's adversarial construction for `FR-ORCH-27` is an executor that calls the raw
    provider "to save a hop". Here the raw provider is the same object, so the call reaches
    it either way and the ceiling above still passes — what changes is whether the run
    *counted* it. This equality is the half that goes red.
    """
    store, orchestrator, provider, run_id = ceilinged_run

    # The counters are per RUN, not per pass (`_dispatch_state`: "kept per run — not per pass —
    # so the counters a report reads are the run's own cumulative truth"), and each flush
    # REPLACEs the metric row. So the figure on the table after the last pass is the run's
    # running total, and it is comparable against the provider's own cumulative count.
    passes = 0
    while provider.calls < UNIT_COUNT and passes < 40:
        orchestrator.progress(run_id)
        passes += 1

    assert provider.calls >= UNIT_COUNT, "the run never reached the provider often enough"
    counted = _metric(store, run_id, "tokens_out")
    assert counted == float(provider.calls * TOKENS_PER_CALL), (
        f"the provider answered {provider.calls} call(s) and the run counted {counted} "
        f"token(s) out at {TOKENS_PER_CALL} per call. A call that reached the provider "
        "without crossing GovernedProvider spends money the run does not count "
        "(CT-PROV-11) — §8.3's 'save a hop' construction"
    )
