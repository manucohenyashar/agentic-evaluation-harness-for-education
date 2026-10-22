"""TC-CONF-44 (#819): the Jev-final knob is frozen at run creation, across pause and resume.

Traces: FR-AGG-20, RC-03. Source: `docs/design/console_clarity_test_plan.md` §3.2 (story T6).

| Case | Asserted |
|---|---|
| TC-CONF-44 | F-DEV-PIPE, decision engine on, base panel of one, every judged cell accepted on its reference band, and the seat judge agrees. The run starts under `HARNESS_JEV_FINAL_ON_ACCEPT=true` and is paused by a decision-engine outage after half of the six judged cells were decided. The environment is then set to `false`, and the resumed drive gets a run config **re-resolved from that environment**. Expected: every accepted-decision cell, before and after the pause, is `final` / `auto` at the gate and was confirmed by the seat judge. The run row's `provider_config` records `jev_final_on_accept: true` and is byte-identical across the episode |

Re-resolving is what makes the case discriminate. If the resume were given the original config,
the case would pass even if the worker or the aggregate hook read the knob from the bound config
or the environment instead of the run row.

**Rung.** Rung 3: the composed pipeline over a real store, with every model answer a recording
keyed on its request (`tests/support/jev_final_pipe.py`).

Markers. `integration`. Written against shipped code (#806), so not `writtenahead`.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

import aeh.pipeline as pipeline
from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import LEASE_SECONDS_ENV, Orchestrator
from aeh.prov import ProviderUnavailableError
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg
from tests.support.jev_final_pipe import ACCEPTED, cells, every_cell, new_world
from tests.support.pipe_world import corpus_refs

pytestmark = pytest.mark.integration

#: Judged cells decided before the outage: half of F-DEV-PIPE's six.
DECIDED_BEFORE_PAUSE = 3


class _DecisionOutage:
    """The world's provider, refusing every `decide` after the first `after` of them."""

    def __init__(self, inner: Any, after: int) -> None:
        self.inner = inner
        self.after = after
        self.decided = 0
        self.refusals = 0

    def decide(self, request: Any, model_ref: Any) -> Any:
        if self.decided >= self.after:
            self.refusals += 1
            raise ProviderUnavailableError("the decision engine is down (TC-CONF-44's pause)")
        self.decided += 1
        return self.inner.decide(request, model_ref)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _provider_config(store: Any, run_id: str) -> str:
    return str(Orchestrator(store).run_handle(run_id).cohort.query(
        "SELECT provider_config FROM run WHERE run_id = :r", r=run_id)[0]["provider_config"])


def test_tc_conf_44_the_knob_is_frozen_across_pause_and_resume(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(LEASE_SECONDS_ENV, "1")
    monkeypatch.setenv("HARNESS_JEV_FINAL_ON_ACCEPT", "true")
    root = tmp_path / "w"
    world = new_world(root, engine=True, panel_size=1, knob=True, agreeing=True,
                      outcomes=every_cell(ACCEPTED), monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    run_id = world.run_id
    assert world.resolved.jev_final_on_accept is True
    frozen = _provider_config(world.store, run_id)
    assert json.loads(frozen)["jev_final_on_accept"] is True

    inner = world.provider
    outage = _DecisionOutage(inner, DECIDED_BEFORE_PAUSE)
    world.provider = outage
    refs = corpus_refs()
    refs["judge_refs"] = world.escalation_judge_refs()
    result = pipeline.run_to_completion(world.store, run_id, provider=outage,
                                        run_config=world.resolved, decision_provider=outage,
                                        **refs)
    assert result.status == "paused", (result.status, result.pause_reason)
    assert outage.decided == DECIDED_BEFORE_PAUSE and outage.refusals >= 1
    world.store.close()

    # The operator changes the environment while the run sits paused, and the resumed drive is
    # handed a config resolved from the CHANGED environment.
    monkeypatch.setenv("HARNESS_JEV_FINAL_ON_ACCEPT", "false")
    world.jev_final_on_accept = False
    changed = resolve_run_config(edge_cfg(panel=world.panel_refs, **world._run_cfg_overrides()),
                                 CohortRef(cohort_id=world.cohort_id, consent_class="synthetic"))
    assert changed.jev_final_on_accept is False, "precondition: the new environment says false"
    time.sleep(1.2)  # every lease held at the pause expires, as RES-20 expires them

    store = open_store(root / "data")
    try:
        pipeline.recover(store)
        if Orchestrator(store).run_handle(run_id).status == "paused":
            Orchestrator(store).resume(run_id)
        resumed = pipeline.run_to_completion(store, run_id, provider=inner, run_config=changed,
                                             decision_provider=inner, **refs)
        assert resumed.status == "complete", (resumed.status, resumed.pause_reason)
        assert _provider_config(store, run_id) == frozen, "the run row's frozen rule moved"
        world.store = store
        world.handle = store.cohort(world.cohort_id)
        judged = cells(world)
    finally:
        store.close()

    from aeh.judge import prescreen_confirmation

    assert len(judged) == 6
    for cell, row in judged.items():
        assert row["prescreen"][0] == "accepted", (cell, row["prescreen"])
        # FR-JUDGE-39 under the frozen rule: the seat judge confirmed every cell, after the
        # pause too. A worker reading the changed config would skip the call and leave no record.
        assert (prescreen_confirmation(row["prescreen"][1]) or ("",))[0] == "confirmed_by", (
            cell, row["prescreen"])
        assert row["engines"] == ["decision"], (cell, row["engines"])
        state, routing, count, confidence = row["score"][2:6]
        assert (state, routing, count) == ("final", "auto", 1), (cell, row["score"])
        assert confidence == pytest.approx(ACCEPTED["gate"])
