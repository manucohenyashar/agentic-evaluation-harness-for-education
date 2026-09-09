"""`TC-ORCH-24` (`FR-ORCH-21`; integration / rung 2, P1) — the concurrency
ceiling and the backpressure response: in-flight requests never exceed the
ceiling; dispatch reduces when `M-STORE` signals write backpressure and
recovers when it clears (**written ahead of #62's dispatch loop**).

`FR-ORCH-21`: "cap in-flight requests at the configured concurrency ceiling and
reduce dispatch when M-STORE signals write backpressure." `CT-STORE-06` is the
consumer clause: a slow `enqueue_write` is a signal to reduce dispatch, NOT a
fault — a backpressure signal that looks like an error would fail a whole run
under load. `R10` traces this case beside the performance suite: the ceiling is
hypothesis until measured.

The backpressure half drives the REAL shipped signal: the store's write queue
(`HARNESS_WRITE_QUEUE_DEPTH`, `CT-STORE-06`/`TC-STORE-C06`) with its drain held
by the same `_next_batch` technique the store's own C06 case uses, so
`backpressure_active` turns on as a level, and clears when the drain releases.
What the dispatch does under that signal is #62's to ship.

**Interface this file assumes of #62** (the `test_residency_and_concurrency.py`
precedent — the dispatch loop is the unshipped seam; everything else is real):

| Name | Status |
|---|---|
| `Orchestrator.progress(run_id)` | design §3.7 Protocol member #62 ships; drives the dispatch passes |
| the model-call seam is injectable at the Orchestrator | `Orchestrator(store, transport=<seam>)`, kwarg reconciled at landing |
| the seam call is observed in-flight | the seam double counts concurrent entries — the concurrency spy the plan names |
| `report["concurrency"]` | the dispatch report carries the dispatch's current concurrency — the same field `RES-11` (429 back-off) already assumes |
| the ceiling is configurable to 32 | `RunConfig.concurrency_ceiling` derives from the hardware profile (`FR-CONF-06`); the fixture supplies a profile whose ceiling is 32 — the shipped `HardwarePolicy` path, so the plan's "ceiling of 32" input is real, not monkey-patched |

Isolation: rung 2 — real store (its write queue driven to saturation), real
package, real cohort ledger; the model-call seam is the only double. No network.
"""

from __future__ import annotations

import threading
import time

import pytest

from aeh.prov import Completion
from aeh.store import open_store, store_metrics
from tests.support.impl import ORCH_MODULE, require, require_attr
from tests.support.orch_run import ORCH_COHORT_ID, seed_run
from tests.support.store_api import statement

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#62"

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 9))
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
)

#: The plan's input: a concurrency ceiling of 32.
CEILING = 32


def _ceiling_32_config() -> object:
    """A resolved config whose hardware profile carries the plan's ceiling of 32
    (the shipped `FR-CONF-06` path: the ceiling derives from the profile)."""
    from aeh.conf import CohortRef, HardwarePolicy, resolve_run_config
    from tests.support.conf_builders import edge_cfg

    profile = HardwarePolicy(
        residency_policy=("judge", "transcriber"),
        concurrency_ceiling=CEILING,
        quantization_target="q4",
        prefix_token_ceiling=8192,
    )
    return resolve_run_config(
        edge_cfg(
            HARNESS_HARDWARE_PROFILE="capacity-test",
            hardware_profiles={"capacity-test": profile},
            panel=None,
        ),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


class _ConcurrencySpy:
    """The concurrency spy the plan names: counts simultaneous in-flight seam
    calls and records the peak. Every call stalls briefly so overlaps are
    observable."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_flight = 0
        self.peak = 0
        self.calls = 0

    def call(self, req):
        with self._lock:
            self._in_flight += 1
            self.calls += 1
            self.peak = max(self.peak, self._in_flight)
        time.sleep(0.01)
        with self._lock:
            self._in_flight -= 1
        return Completion(
            text="synthetic band: B",
            tokens_in=10,
            tokens_out=5,
            latency_ms=10,
            resolved_build="fixture-build-2026-09-08",
            cached_prefix_tokens=0,
            cost=None,
        )


def _hold_drain_and_saturate(monkeypatch: pytest.MonkeyPatch, store: object) -> threading.Event:
    """Turn the store's real backpressure level ON, the `TC-STORE-C06` way:
    hold `WriteQueue._next_batch` on an Event (deterministic — holding the write
    lock from a side thread races), then park a side thread's enqueues past the
    configured depth so `backpressure_active` engages. Returns the release
    Event; the caller releases it in its own finally."""
    import aeh.store as store_module

    release = threading.Event()
    writer_blocked = threading.Event()
    original_next = store_module.WriteQueue._next_batch

    def held_next(self):
        writer_blocked.set()
        release.wait(timeout=60)
        return original_next(self)

    monkeypatch.setattr(store_module.WriteQueue, "_next_batch", held_next)

    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        tx.execute(statement("CREATE TABLE c66_saturate (n INTEGER)", issue="#66"))
    saturate = statement("INSERT INTO c66_saturate VALUES (:n)", issue="#66")
    saturate_done = threading.Event()

    def enqueue_past_depth():
        for index in range(12):  # well past the configured depth of 5
            handle.enqueue_write(saturate, n=index)
        saturate_done.set()

    threading.Thread(target=enqueue_past_depth, daemon=True).start()
    deadline = time.monotonic() + 30
    while not writer_blocked.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.3)  # the side thread runs into the depth boundary and parks
    return release


def test_tc_orch_24_in_flight_never_exceeds_the_ceiling_and_backpressure_recovers(
    tmp_data_dir, monkeypatch
):
    """`TC-ORCH-24` — three legs, exactly the plan's expected result:

    1. **Ceiling**: driving dispatch at a ceiling of 32, the seam's observed
       peak in-flight count never exceeds 32.
    2. **Reduce**: with the store's write queue saturated (the shipped
       `backpressure_active` level ON, `CT-STORE-06`), the dispatch report's
       concurrency drops below the ceiling — reduction, not a fault.
    3. **Recover**: once the queue drains and the level clears, the concurrency
       returns above its reduced floor — the reduction was a response to the
       signal, not damage.
    """
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    require_attr(Orchestrator, "progress", issue=ISSUE)

    monkeypatch.setenv("HARNESS_WRITE_QUEUE_DEPTH", "5")
    spy = _ConcurrencySpy()
    store = open_store(tmp_data_dir)
    release = None
    try:
        orch, run_id, _version = seed_run(
            store,
            submissions=_SUBMISSIONS,
            criteria=_CRITERIA,
            cfg=_ceiling_32_config(),
        )
        orch.enumerate_units(run_id)

        # Leg 1 — ceiling respected under load.
        for _ in range(8):
            orch.progress(run_id)
        assert spy.calls > 0, (
            "the dispatch made no model calls — the ceiling leg asserted nothing"
        )
        assert spy.peak <= CEILING, (
            f"the dispatch observed {spy.peak} in-flight requests against a "
            f"ceiling of {CEILING} — FR-ORCH-21's cap is exact, and 'rarely "
            "exceeded' is how a provider bill becomes an incident"
        )

        # Legs 2/3 — the real backpressure level on, then off.
        release = _hold_drain_and_saturate(monkeypatch, store)
        deadline = time.monotonic() + 30
        while not store_metrics(store)["backpressure_active"]:
            if time.monotonic() > deadline:
                break
            time.sleep(0.01)
        assert store_metrics(store)["backpressure_active"], (
            "fixture precondition: the store's write queue never signalled "
            "backpressure — CT-STORE-06's level is the signal FR-ORCH-21 "
            "responds to, and without it leg 2 asserts nothing"
        )
        reduced = [orch.progress(run_id)["concurrency"] for _ in range(4)]
        assert any(c < CEILING for c in reduced), (
            f"with backpressure_active ON the dispatch never reduced "
            f"(concurrency over passes: {reduced}) — CT-STORE-06 requires a "
            "slow enqueue_write to be read as a signal to reduce dispatch, "
            "not ignored"
        )

        release.set()
        deadline = time.monotonic() + 30
        while store_metrics(store)["backpressure_active"] and time.monotonic() < deadline:
            time.sleep(0.01)
        recovered = [orch.progress(run_id)["concurrency"] for _ in range(4)]
        assert any(c > min(reduced) for c in recovered), (
            f"after the backpressure cleared the dispatch stayed at its reduced "
            f"level (reduced: {reduced} -> recovered: {recovered}) — the "
            "reduction must recover when the signal clears, or one slow store "
            "permanently throttles the run"
        )
    finally:
        if release is not None:
            release.set()
        store.close()
