"""PERF-13 (NFR-CONSOLE-08; TS-99 #393): the console's "start run" answers in under 1 s for a
350-submission run, every one of 20 single requests.

The store holds a real 350-submission cohort seeded and scored through the shipped modules
(`seed_scored_run`, TC-CONSOLE-33's world). Each request goes through the console's own door
(`perform("start run", run_id=...)`), which resolves the configuration and returns while the run
is driven on a server-owned thread. Disclosed: the 20 runs are created PENDING through M-ORCH first
and the door starts each by id; the door refuses to create a second run beside a cohort's existing
one for the same version, so 20 fresh creations would need 20 cohorts of 350. The response time
is `perf_counter` around the door call alone. The worker's model calls are refused (the drive is
not what is measured), and each worker is joined after its timing so the 20 requests are
independent.

Marked `slow`: twenty runs over a 350-submission cohort take minutes on E1.
"""

from __future__ import annotations

import time

import pytest

import aeh.pipeline as pipeline
from aeh.console import build_console
from aeh.prov import ProviderUnavailableError
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg
from tests.support.console_vocabulary import REFERENCE_COHORT_SIZE
from tests.support.console_world import seed_scored_run

pytestmark = [pytest.mark.integration, pytest.mark.slow]

BUDGET_SECONDS = 1.0
REQUESTS = 20


def test_perf_13_start_run_answers_within_a_second_for_350_submissions(tmp_data_dir, monkeypatch):
    class Down:
        def complete(self, *args, **kwargs):
            raise ProviderUnavailableError("the drive is not what PERF-13 measures")

    monkeypatch.setattr(pipeline, "_provider_for", lambda config: Down())
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, submissions=REFERENCE_COHORT_SIZE, with_open_criteria=True)
        from aeh.conf import resolve_run_config
        from aeh.orch import Orchestrator

        orch = Orchestrator(store)
        config = resolve_run_config(edge_cfg(), orch.cohort_ref(world.cohort_id))
        pending = [orch.create_run(world.cohort_id, world.package_version_id, config)
                   for _ in range(REQUESTS)]
        app = build_console(store=store)
        timings: list[float] = []
        started: list[str] = []
        for run_id in pending:
            t0 = time.perf_counter()
            outcome = app.perform("start run", run_id=run_id, config=edge_cfg())
            timings.append(time.perf_counter() - t0)
            assert outcome.dispatched, outcome.detail
            started.append(run_id)
            thread = app._run_threads[run_id]
            thread.join(timeout=300)
            assert not thread.is_alive(), f"the worker for {run_id} never stopped"
    finally:
        store.close()
    assert len(set(started)) == REQUESTS, f"fixture: {len(set(started))} distinct runs for {REQUESTS} requests"
    slow = [round(t, 3) for t in timings if t >= BUDGET_SECONDS]
    assert not slow, f"start run answered in >= {BUDGET_SECONDS} s on {len(slow)} of {REQUESTS}: {slow}"
