"""`TS-85` (issue #379) — `TC-ORCH-43`: the failure taxonomy pauses the run instead of
striking the unit (`FR-ORCH-30`, `CT-ORCH-28`, RISK-44).

| Arm | Provider raises | Expected |
|---|---|---|
| a | `ProviderUnavailableError` | `progress()` **returns**; `run.status='paused'`; the cause names the class; the unit is `pending` with `attempts` unchanged (0); no further unit leased in that pass |
| b | `BuildChangedError` | as (a) |
| c | `RateLimitedError(retry_after=0)` ×2 then success | no pause; the unit completes with `attempts = 0`; `rate_limited_calls = 2` |

**The defect this guards is a 20-minute outage at 02:00.** RISK-44: three strikes get counted
against every in-flight unit, hundreds of valid units quarantine, and the morning shows a
cohort full of "could not be scored" rather than a paused run an operator can resume. The
`attempts` assertion is therefore not a detail — it is the whole case. A provider outage is
the *provider's* condition, never the unit's, so nothing may be charged to the unit.

**`attempts` is the assertion that survives the plausible tidy-up.** §8.3 names it: someone
"simplifies" the worker to `except ProviderError as e: self._strike(unit, e); raise`, which
keeps the pause and restores the strike. The pause assertion still passes. Only `attempts`
goes red.

**`progress()` returning rather than raising is the other half.** `CT-ORCH-28` says the
exception must not propagate: a caller that meets a raise cannot read the report that tells it
the run paused, and `M-PIPE`'s loop would treat it as a composition fault and exit non-zero on
a condition that is simply worth waiting out.

**Isolation: rung 2**, executor bound — real store, real ledger, the model boundary a scripted
stub (F-TAXONOMY's shape: call *n* raises the taxonomy error from a list).
"""

from __future__ import annotations

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
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.orch import Orchestrator, StageOutcome
from aeh.prov import BuildChangedError, ProviderUnavailableError, RateLimitedError
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_documents, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "S01"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

_UNITS = Statement(
    "SELECT work_id, status, attempts FROM work_unit WHERE run_id = :run_id "
    "AND stage = 'extract' ORDER BY work_id"
)
_RUN = Statement("SELECT status, pause_reason FROM run WHERE run_id = :run_id")
_METRIC = Statement(
    "SELECT value FROM run_metrics WHERE run_id = :run_id AND metric = :metric"
)


class ScriptedExecutor:
    """F-TAXONOMY as a `StageExecutor`: call *n* raises the scripted error, or completes.

    The taxonomy is raised from the executor rather than from deep inside a shipped worker
    because `FR-ORCH-30`'s contract is stated at the seam — "let `RateLimitedError`,
    `MemoryError`, `ProviderUnavailableError` and `BuildChangedError` propagate; the loop
    classifies each one" (`StageExecutor`'s own docstring). Raising here is raising exactly
    where the loop promises to catch, so the case pins the classification rather than one
    worker's re-raise behaviour.
    """

    def __init__(self, script: list[BaseException | None]) -> None:
        self._script = list(script)
        self.calls = 0

    def execute(self, unit: Any, governed: Any) -> StageOutcome:  # noqa: ARG002
        index, self.calls = self.calls, self.calls + 1
        error = self._script[index] if index < len(self._script) else None
        if error is not None:
            raise error
        return StageOutcome(completed=True, detail="scripted success")


class StubProvider:
    def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002 — the seam's shape
        return None

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        raise AssertionError("the scripted executor answers without reaching the provider")


def _world(tmp_data_dir, script: list[BaseException | None]):
    store = open_store(tmp_data_dir)
    seeder, run_id, _version = seed_run(
        store, submissions=(SUBMISSION,), criteria=CRITERIA,
    )
    seed_documents(store, (SUBMISSION,))
    seeder.enumerate_units(run_id)
    executor = ScriptedExecutor(script)
    probe = Orchestrator(store, executor=executor, provider=StubProvider())
    probe.start(run_id)
    return store, probe, executor, run_id


def _extract_units(store: Any, run_id: str) -> list[dict[str, Any]]:
    return [
        {"work_id": row["work_id"], "status": row["status"], "attempts": row["attempts"]}
        for row in store.cohort(ORCH_COHORT_ID).query(_UNITS, run_id=run_id)
    ]


def _run_row(store: Any, run_id: str) -> dict[str, Any]:
    row = store.cohort(ORCH_COHORT_ID).query(_RUN, run_id=run_id)[0]
    return {"status": row["status"], "pause_reason": row["pause_reason"]}


def _metric(store: Any, run_id: str, name: str) -> float | None:
    rows = store.durable().query(_METRIC, run_id=run_id, metric=name)
    return float(rows[0]["value"]) if rows else None


def _assert_outage_arm(store: Any, probe: Any, run_id: str, class_name: str) -> None:
    """The four assertions arms (a) and (b) share, stated once."""
    report = probe.progress(run_id)
    assert report is not None, (
        "progress() returned None; CT-ORCH-28 requires it to RETURN a report rather than "
        "raise, so the caller can read that the run paused"
    )

    run = _run_row(store, run_id)
    assert run["status"] == "paused", (
        f"the run is {run['status']!r} after a provider outage; FR-ORCH-30 pauses the run "
        "because every other unit is about to meet the same condition"
    )
    assert class_name in str(run["pause_reason"] or ""), (
        f"the pause cause {run['pause_reason']!r} does not name {class_name}; an operator "
        "reading it in the morning cannot tell an outage from a cost stop (RISK-44's "
        "'quarantines are visible, their cause is not')"
    )

    units = _extract_units(store, run_id)
    assert units, "the run enumerated no extract unit, so the arm proves nothing"
    for unit in units:
        assert unit["status"] == "pending", (
            f"unit {unit['work_id'][:12]} is {unit['status']!r}; a unit the provider never "
            "answered must return to pending, not stay leased until its lease expires"
        )
        assert unit["attempts"] == 0, (
            f"unit {unit['work_id'][:12]} was charged {unit['attempts']} attempt(s) for the "
            "PROVIDER's outage. Three of those quarantine a perfectly good unit, and a "
            "20-minute outage does it to every unit in flight (RISK-44)"
        )


# --- TC-ORCH-43 -----------------------------------------------------------------------------


def test_tc_orch_43_arm_a_a_provider_outage_pauses_the_run_and_charges_no_attempt(
    tmp_data_dir,
):
    """Arm (a) — `ProviderUnavailableError`."""
    store, probe, _executor, run_id = _world(
        tmp_data_dir, [ProviderUnavailableError("the endpoint is gone")]
    )
    try:
        _assert_outage_arm(store, probe, run_id, "ProviderUnavailable")
    finally:
        store.close()


def test_tc_orch_43_arm_b_a_changed_build_pauses_the_run_and_charges_no_attempt(
    tmp_data_dir,
):
    """Arm (b) — `BuildChangedError`. The same shape: the model answering is not the model the
    run froze, which is the provider's condition and not the unit's."""
    store, probe, _executor, run_id = _world(
        tmp_data_dir, [BuildChangedError("the endpoint answers as a different build")]
    )
    try:
        _assert_outage_arm(store, probe, run_id, "BuildChanged")
    finally:
        store.close()


def test_tc_orch_43_arm_a_no_further_unit_is_leased_in_the_pausing_pass(tmp_data_dir):
    """Arm (a)'s last clause — the pass stops rather than burning the batch against an outage.

    Two units, and the first call raises. A loop that carried on would spend the second unit
    against an endpoint that is already known to be gone; at cohort scale that is the whole
    run's work thrown at a dead provider before anyone notices.
    """
    store = open_store(tmp_data_dir)
    try:
        submissions = ("S01", "S02")
        seeder, run_id, _version = seed_run(
            store, submissions=submissions, criteria=CRITERIA,
        )
        seed_documents(store, submissions)
        seeder.enumerate_units(run_id)
        executor = ScriptedExecutor([ProviderUnavailableError("gone")])
        probe = Orchestrator(store, executor=executor, provider=StubProvider())
        probe.start(run_id)

        probe.progress(run_id)
        after_first = executor.calls

        probe.progress(run_id)
        assert executor.calls == after_first, (
            f"a paused run dispatched {executor.calls - after_first} more unit(s) on the next "
            "pass; a pause that does not stop dispatch is not a pause"
        )
        assert _run_row(store, run_id)["status"] == "paused"
        for unit in _extract_units(store, run_id):
            assert unit["attempts"] == 0, (
                f"unit {unit['work_id'][:12]} carries {unit['attempts']} attempt(s); no unit "
                "in the pausing pass may be charged for the outage"
            )
    finally:
        store.close()


def test_tc_orch_43_arm_c_rate_limits_requeue_without_pausing_or_charging_an_attempt(
    tmp_data_dir,
):
    """Arm (c) — two `RateLimitedError(retry_after=0)` then success.

    A rate limit is an expected condition rather than an outage: the run does **not** pause,
    the unit requeues, and it completes on the pass that succeeds — still at `attempts = 0`,
    because the provider's throttle is not the unit's failure either. `rate_limited_calls`
    counts exactly two, which is what tells an operator the throttling happened at all.
    """
    store, probe, executor, run_id = _world(
        tmp_data_dir,
        [
            RateLimitedError("retry-after: 0"),
            RateLimitedError("retry-after: 0"),
            None,
        ],
    )
    try:
        for _pass in range(3):
            probe.progress(run_id)

        run = _run_row(store, run_id)
        assert run["status"] != "paused", (
            f"the run is {run['status']!r}; a rate limit is the provider asking for patience, "
            "not an outage, and pausing on one would stop every throttled run"
        )
        units = _extract_units(store, run_id)
        assert [unit["status"] for unit in units] == ["done"], (
            f"the unit ended {[u['status'] for u in units]}; it must complete on the pass "
            "that succeeds"
        )
        assert units[0]["attempts"] == 0, (
            f"the unit was charged {units[0]['attempts']} attempt(s) for the provider's "
            "throttle; §9.11 says a rate limit consumes no attempt and records no unit error"
        )
        assert executor.calls == 3, (
            f"the executor was called {executor.calls} times; the script is two refusals and "
            "one success, so anything else means the requeue did not re-offer the unit"
        )
        assert _metric(store, run_id, "rate_limited_calls") == 2.0, (
            f"rate_limited_calls reads "
            f"{_metric(store, run_id, 'rate_limited_calls')!r}, not 2 — the throttling is "
            "invisible to the operator (FR-PROV-07, RES-11)"
        )
    finally:
        store.close()
