"""`TC-JUDGE-18` — a malformed reply is struck to the budget and the unit is
quarantined, with no verdict ever written (`FR-JUDGE-14`, `NFR-JUDGE-05`; issue #83
(TS-31)).

A reply whose fields arrive out of the pinned order is refused EVERY time it is
retried: inside one dispatch the strike loop spends all three attempts on it (three
provider calls, three refusals), surfaces `JudgmentError`, and the orchestrator's fail
cycle — driven here through the REAL boundary, lease → assemble → dispatch → fail —
requeues the unit twice and quarantines it at the attempt ceiling, `last_error`
retained. Nothing was ever accepted, so nothing was persisted: the verdict rows for
the work unit are zero at every point in the cycle.

Isolation: rung 2 — real store, real package, real extraction leg, replies through
`RecordedFixtureProvider` (recorded once, replayed on every strike). No model, no
network.
"""

from __future__ import annotations

import pytest

from aeh.orch import STAGE_SCORE
from aeh.store import open_store
from tests.support.conf_builders import EDGE_JUDGE
from tests.support.extract_vocabulary import JUDGE_ISSUE
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_run import (
    CONTROL_BAND,
    CONTROL_CONFIDENCE,
    judge_world,
    permuted_reply,
    verdict_rows,
    warm_judged_modules,
    work_unit_row,
)

pytestmark = [pytest.mark.integration]

#: The one submission, judged by the one judge — its reply is the malformed
#: condition, and nothing else varies.
SUBMISSION = "s-18"
JUDGE_BUILD = EDGE_JUDGE.build_id
JUDGE_WORKER_ID = "w-judge-tj18"


def _world(tmp_data_dir, make_fixture_provider):
    warm_judged_modules()
    store = open_store(tmp_data_dir / "data")
    provider = make_fixture_provider()
    world = judge_world(
        store,
        provider,
        submissions=(SUBMISSION,),
        panel=1,
        reply_for=lambda _submission_id, _judge_build: permuted_reply(
            CONTROL_BAND,
            CONTROL_CONFIDENCE,
            build_id=JUDGE_BUILD,
        ),
    )
    return store, provider, world


class _StrikeCounter:
    """A transport-seam wrapper crediting every `complete` call — the re-dispatch
    cycles' strike counts, read cumulatively. The fixture recording and lookup still
    go through the inner provider."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def complete(self, payload, model_ref, params):
        self.calls.append(getattr(model_ref, "build_id", str(model_ref)))
        return self._inner.complete(payload, model_ref, params)


# --- the strike: three attempts, one refusal, nothing persisted --------------------------------------


def test_tc_judge_18_a_a_malformed_reply_is_struck_three_times_and_refused(
    tmp_data_dir, make_fixture_provider
):
    """The world's first dispatch strikes three times — three provider calls for one
    unit — and refuses with `JudgmentError` naming the attempt budget; no verdict row
    exists."""
    store, _provider, world = _world(tmp_data_dir, make_fixture_provider)
    JudgmentError = require(JUDGE_MODULE, "JudgmentError", issue=JUDGE_ISSUE)
    key = (SUBMISSION, JUDGE_BUILD)
    assert world["strikes"][key] == 3, (
        f"one dispatch strikes three times (the attempt budget), got "
        f"{world['strikes'][key]} provider calls"
    )
    error = world["failures"][key]
    assert isinstance(error, JudgmentError), (
        f"the refusal surfaces as JudgmentError, got {error!r}"
    )
    assert "3 attempt" in str(error), (
        f"the refusal names the budget it struck out on: {error}"
    )
    unit = world["score_units"][key]
    assert verdict_rows(store, unit.work_id) == [], (
        "a refused unit has written no verdict row"
    )


def test_tc_judge_18_b_the_fail_cycles_requeue_then_quarantine_with_no_verdict(
    tmp_data_dir, make_fixture_provider
):
    """The REAL orchestration cycle around a refusing unit: each fail requeues the
    unit pending below the attempt ceiling, each re-lease re-dispatches it (three
    more provider strikes), and the third fail quarantines it with `last_error`
    retained — the verdict table still empty after every cycle."""
    store, provider, world = _world(tmp_data_dir, make_fixture_provider)
    JudgmentError = require(JUDGE_MODULE, "JudgmentError", issue=JUDGE_ISSUE)
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue=JUDGE_ISSUE)
    orchestrator = world["orchestrator"]
    key = (SUBMISSION, JUDGE_BUILD)
    unit = world["score_units"][key]

    # The world's dispatch was the first strike set; its refusal drives fail #1.
    orchestrator.fail(unit.work_id, world["failures"][key])
    counter = _StrikeCounter(provider)

    for cycle, expected_total in ((2, 3), (3, 6)):
        batch = list(orchestrator.lease(JUDGE_WORKER_ID, STAGE_SCORE, 8))
        assert len(batch) == 1, (
            f"cycle {cycle}: the requeued unit is leased exactly once, got {len(batch)}"
        )
        unit = batch[0]
        request = ScoringWorker(store, counter, EDGE_JUDGE).assemble(unit)
        worker = ScoringWorker(store, counter, EDGE_JUDGE)
        with pytest.raises(JudgmentError) as excinfo:
            worker.dispatch(request, EDGE_JUDGE)
        assert "3 attempt" in str(excinfo.value)
        assert len(counter.calls) == expected_total, (
            f"cycle {cycle}: every re-dispatch strikes three times again "
            f"(cumulative {len(counter.calls)}, expected {expected_total})"
        )
        assert verdict_rows(store, unit.work_id) == [], (
            f"cycle {cycle}: no verdict row exists for a refused unit"
        )
        orchestrator.fail(unit.work_id, excinfo.value)

    row = work_unit_row(store, unit.work_id)
    assert row["status"] == "quarantined", (
        f"the third fail quarantines the unit: {dict(row)!r}"
    )
    assert row["attempts"] == 3, (
        f"the attempt ceiling is three: {dict(row)!r}"
    )
    assert row["last_error"] and "3 attempt" in str(row["last_error"]), (
        f"the quarantine retains the refusal: {row['last_error']!r}"
    )
    assert verdict_rows(store, unit.work_id) == [], (
        "quarantine never writes a verdict (NFR-JUDGE-05: no fallback verdict exists)"
    )