"""`RES-20` (issue #393, TS-99) — a provider outage of ten SIMULATED minutes, striking mid-run
on F-DEV-PIPE: the run pauses within the pass that saw the error, quarantines nothing, and
`resume` drives to `complete` against the SAME frozen provider.

Gap-fix test plan §6.8 (resilience, rung 2), tracing `CT-PIPE-04`, `CT-ORCH-28` and
`FR-ORCH-16`. The boundary `TC-E2E-02` variant (b) holds is the same shape over the journey's
hand-rolled drive; this case holds it over the composed pipeline, where the outage lands inside
`run_to_completion`'s pass loop and the absorbed-future discipline (`FR-ORCH-30`) is what must
turn it into a pause rather than a traceback, a quarantine or a silent skip.

The wrapper refuses while the frozen clock sits inside a ten-minute window, so the recovery is
real: the test advances the SAME clock past the window only after the pause is asserted —
`resume` succeeds against the same provider object because the outage ENDED, never because the
run was re-bound to a healthier one. `provider_config` and `panel_config` are compared byte for
byte across the whole episode (the TC-E2E-02 (b) oracle): a pause is a stop, never a rewrite of
what the run froze.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import pytest

import aeh.pipeline as pipeline
from aeh.orch import LEASE_SECONDS_ENV, Orchestrator
from aeh.prov import ProviderUnavailableError
from aeh.store import open_store
from tests.support import pipe_world
from tests.support.clock import FrozenClock

pytestmark = pytest.mark.integration

#: The outage's length in simulated wall time (`FrozenClock` moves only when told).
OUTAGE_MINUTES = 10

#: Successful provider completions served before the refusal. Each extraction unit makes two
#: (primary and second-family), so four calls is two finished units — mid-Sweep 2: extraction
#: had completed work when the outage bit, and the run was nowhere near done.
AFTER_N_CALLS = 4


class _OutageAfter:
    """The composed run's provider: delegates the first `after` completions, then refuses while
    the frozen clock sits inside the outage window; every other attribute delegates untouched."""

    def __init__(self, inner: Any, clock: FrozenClock, outage_end: Any, after: int) -> None:
        self._inner = inner
        self._clock = clock
        self._outage_end = outage_end
        self._after = after
        self.served = 0
        self.refusals = 0

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        if self.served >= self._after and self._clock.now() < self._outage_end:
            self.refusals += 1
            raise ProviderUnavailableError(
                f"RES-20 simulated outage ({OUTAGE_MINUTES} simulated minutes)"
            )
        self.served += 1
        return self._inner.complete(prompt, model_ref, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _run_row(store: Any, run_id: str) -> dict[str, Any]:
    handle = store.cohort(pipe_world.PIPE_COHORT_ID)
    return dict(handle.query(
        "SELECT status, pause_reason, provider_config, panel_config FROM run "
        "WHERE run_id = :r", r=run_id)[0])


def _counts(store: Any, run_id: str) -> dict[tuple[str, str], int]:
    handle = store.cohort(pipe_world.PIPE_COHORT_ID)
    rows = handle.query(
        "SELECT status, COUNT(*) AS n FROM work_unit WHERE run_id = :r "
        "GROUP BY status", r=run_id)
    return {str(r["status"]): int(r["n"]) for r in rows}


def _extract_done(store: Any, run_id: str) -> int:
    """Extract-stage units the outage's pass had already completed when it paused."""
    handle = store.cohort(pipe_world.PIPE_COHORT_ID)
    return int(handle.query(
        "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r AND stage = 'extract' "
        "AND status = 'done'", r=run_id)[0]["n"])


def test_res_20_provider_outage_pauses_then_resumes_to_complete(tmp_path, monkeypatch):
    monkeypatch.setenv(LEASE_SECONDS_ENV, "1")
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    root = tmp_path / "w"
    clock = FrozenClock()
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    run_id = world.run_id
    frozen = _run_row(world.store, run_id)

    # The SAME provider object stays bound for the whole episode: the outage, the pause and
    # the resumed drive all go through this one wrapper (FR-ORCH-16's same-provider clause
    # has an object identity behind it, not just a config equality).
    outage = _OutageAfter(world.provider, clock, clock.now() + timedelta(minutes=OUTAGE_MINUTES),
                          AFTER_N_CALLS)
    world.provider = outage
    result = pipe_world.drive_composed(world)
    world.store.close()

    # CT-ORCH-28: the run paused, naming the sensed cause — never completed past the error.
    assert result.status == "paused", f"RES-20: the outage did not pause the run ({result.status})"
    assert outage.refusals >= 1, "fixture: the outage never refused a completion"
    assert result.pause_reason and "ProviderUnavailable" in result.pause_reason, (
        f"RES-20: the pause reason does not name the sensed cause: {result.pause_reason!r}"
    )

    # Every lease held at the pause is now expired, the way TC-PIPE-11 expires them, so
    # `recover`'s sweep reclaims the batch the driver was holding mid-strike.
    time.sleep(1.2)

    store = open_store(root)
    try:
        counts = _counts(store, run_id)
        extract_done = _extract_done(store, run_id)
        assert extract_done >= 1, (
            f"RES-20: the outage bit before extraction had completed work "
            f"(not mid-Sweep 2): {counts}"
        )
        done = counts.get("done", 0)
        total = sum(counts.values())
        assert done < total, (
            f"RES-20: nothing was left undone at the pause - the outage did not interrupt a "
            f"mid-flight run: {counts}"
        )
        quarantined = counts.get("quarantined", 0)
        assert quarantined == 0, (
            f"RES-20: the outage quarantined {quarantined} units - an unavailable provider is "
            "a pause, never a quarantine"
        )

        # FR-ORCH-16: the frozen backend snapshot survives the pause untouched.
        paused_row = _run_row(store, run_id)
        assert paused_row["status"] == "paused"
        assert paused_row["provider_config"] == frozen["provider_config"], (
            "RES-20: the pause moved the run's frozen provider_config - a pause is a stop, "
            "never a re-bind (FR-ORCH-16)"
        )
        assert paused_row["panel_config"] == frozen["panel_config"]

        # The ten simulated minutes pass while the run sits paused; then the operator's resume.
        clock.advance(OUTAGE_MINUTES * 60)
        pipeline.recover(store)
        if _run_row(store, run_id)["status"] == "paused":
            Orchestrator(store).resume(run_id)
        assert _run_row(store, run_id)["status"] == "running", (
            "RES-20: the resume did not effect the paused -> running edge (FR-ORCH-16)"
        )

        resumed = pipeline.run_to_completion(
            store, run_id, provider=outage, run_config=world.resolved,
            **pipe_world.corpus_refs(),
        )
        assert resumed.status == "complete", (
            f"RES-20: the resumed run did not complete: {resumed.status} / {resumed.pause_reason}"
        )
        assert outage.served > AFTER_N_CALLS, (
            "RES-20: the resumed drive made no provider call - it did not run against the "
            "SAME provider object"
        )

        counts = _counts(store, run_id)
        assert set(counts) == {"done"}, (
            f"RES-20: the completed run left units undone or quarantined: {counts}"
        )
        final_row = _run_row(store, run_id)
        assert final_row["provider_config"] == frozen["provider_config"], (
            "RES-20: the completed run's provider_config differs from the pre-outage freeze"
        )
        assert final_row["panel_config"] == frozen["panel_config"]
    finally:
        store.close()