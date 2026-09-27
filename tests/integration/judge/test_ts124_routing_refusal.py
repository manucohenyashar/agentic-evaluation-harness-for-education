"""TS-124 (#500): TC-PROV-54's M-JUDGE arm (design 1.8, FR-PROV-43). Written ahead of #498.

`RetentionPolicyError` from the routing check is terminal for the run, like FR-PROV-28's gate:
at the worker it propagates from `dispatch`, leaving no `decision_prescreen` row and no verdict,
and making no LLM fallback call. Green on today's worker, which already lets it propagate; the
arm pins that no change turns the routing refusal into a fallback.
"""

from __future__ import annotations

import pytest

from aeh.prov import RetentionPolicyError

pytestmark = pytest.mark.integration


def test_tc_prov_54_m_judge_propagates_the_routing_refusal(tmp_data_dir, make_fixture_provider) -> None:
    """FR-PROV-43: `RetentionPolicyError` is terminal for the run like FR-PROV-28's gate. At the
    worker it propagates from `dispatch`: no `decision_prescreen` row, no verdict, and no LLM
    fallback call for the unit. (The plan's rung-3 arm drives `run_to_completion`; this arm
    asserts the same three facts at the worker, which is where the fallback decision is made.)"""
    from aeh.judge import ScoringWorker
    from tests.integration.judge import test_ts110_decision_dispatch as m
    from tests.support.conf_builders import edge_panel
    from tests.support.orch_run import ORCH_COHORT_ID

    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        llm = m._LLMSpy(provider)
        decider = m._Decider(lambda r: (_ for _ in ()).throw(
            RetentionPolicyError("the response was served by 'OtherHost', outside the pinned order")))
        with pytest.raises(RetentionPolicyError):
            ScoringWorker(store, llm, refs[0], decision_provider=decider,
                          run_config=m._engine_config(tmp_data_dir)).dispatch(request, refs[0])
        assert decider.calls == 1 and llm.calls == []
        cohort = store.cohort(ORCH_COHORT_ID)
        assert cohort.query("SELECT count(*) n FROM decision_prescreen WHERE work_id = :w", w=unit.work_id)[0]["n"] == 0
        assert cohort.query("SELECT count(*) n FROM verdict WHERE work_id = :w", w=unit.work_id)[0]["n"] == 0
    finally:
        store.close()


@pytest.mark.e2e
def test_tc_prov_54_the_run_pauses_naming_the_routing_refusal(tmp_path) -> None:
    """The plan's rung-3 arm (FR-PROV-43, FR-ORCH-30): over F-DEV-PIPE with the engine on, the
    first decision seat's `decide` raises `RetentionPolicyError`. The run stops **paused**,
    naming the error, with no quarantine, no prescreen row for that seat and no LLM fallback
    for it. Green on today's composition, which already pauses on it; the arm pins that no
    change turns a routing refusal into a fallback or a quarantine."""
    from tests.e2e.test_ts117_jev_journeys import _run
    from tests.support import pipe_world

    class _Refusing:
        def __init__(self, inner):
            self._inner = inner
            self.calls = 0

        def decide(self, request, model_ref):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                raise RetentionPolicyError("served by 'OtherHost', outside the pinned provider order")
            return self._inner.decide(request, model_ref)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    world = pipe_world.jev_replay_world(tmp_path / "d")
    try:
        refusing = _Refusing(world.provider)
        outcome = _run(world, decision_provider=refusing)
        assert outcome.status == "paused" and "RetentionPolicyError" in (outcome.pause_reason or "")
        assert world.handle.query("SELECT count(*) n FROM work_unit WHERE status = 'quarantined'")[0]["n"] == 0
        seat = world.resolved.panel[0].build_id
        seat_verdicts = world.handle.query("SELECT count(*) n FROM verdict WHERE judge_id = :j", j=seat)[0]["n"]
        prescreens = world.handle.query("SELECT count(*) n FROM decision_prescreen")[0]["n"]
        assert seat_verdicts == prescreens, "the refused seat got no LLM fallback verdict"
    finally:
        world.store.close()
