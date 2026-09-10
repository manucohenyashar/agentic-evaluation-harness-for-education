"""`TC-JUDGE-24` — the per-(criterion, judge) signal census over a run whose contract
violations are concentrated on one judge (`FR-JUDGE-09`, `FR-JUDGE-04`; issue #83
(TS-31), Observability / 2).

**Disclosed construction**: no shipped per-(criterion, judge) emitter exists in the
landed surface — `run_metrics` is dimensioned by run, not by judge, and M-STATS /
M-CONSOLE are not landed — so the census is built HERE, over the REAL run artifacts a
real emitter would read: the verdict rows (the uncited mark, the sufficiency flag, the
band), the orchestrator's recorded refusals (the contract-violation rate and its strike
counts), and the provider-reported completion figures (`latency_ms`,
`cached_prefix_tokens`). The concentrated-violation ALERT is likewise declared here —
a judge whose violation rate reaches half the batch while every other judge sits at
zero is the concentration signature — and the assertion is exact: each judge's six
signals are hand-counted rates over the batch, and the alert names ONLY the violating
judge. When M-STATS's emitter lands, this file is the pinned contract it must
reproduce. **Pinned axis, disclosed**: the world seeds ONE criterion (`C1`), so the
census's per-(criterion, judge) key collapses to per-judge — every rate is exact over
that axis, but an emitter that aggregated across criteria would be indistinguishable
from a correct one here; the non-degenerate per-criterion pin (marks split between
criteria, a cross-criteria aggregation failing the exact rates) is M-STATS's own case
when it lands.

The run: a three-judge edge-local panel over four submissions. Judges 1 and 3 answer
legally (with varied bands, one uncited verdict and one `evidence_sufficient = false`
verdict between them); judge 2's EVERY reply is permuted — the injected, concentrated
violation. The edge-local residency boundary (one judge model resident at a time,
`FR-ORCH-19`) makes the run's own dispatch order the test's driver: the world's loop
runs judges 1 and 2, the test drives judge 2's fail cycles to quarantine (its refusals
are real, not swallowed), and judge 3's units then lease and judge. Every figure the
census reads came out of that real cycle.

Isolation: rung 2 — real store, real package, real extraction leg, replies through
`RecordedFixtureProvider`. No model, no network.
"""

from __future__ import annotations

from collections import Counter

import pytest

from aeh.orch import STAGE_SCORE
from aeh.store import open_store
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import (
    JUDGE_ISSUE,
    PROMPT_FIELDS,
    sampling_params,
)
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_run import (
    CONTROL_BAND,
    byte_span,
    canonical_document,
    default_pages,
    judge_world,
    permuted_reply,
    reply_text,
    verdict_rows,
    warm_judged_modules,
)

pytestmark = [pytest.mark.integration]

#: The batch: four submissions, three judges — twelve judged units.
SUBMISSIONS = ("s-24a", "s-24b", "s-24c", "s-24d")
J1_BUILD, J2_BUILD, J3_BUILD = (ref.build_id for ref in edge_panel(3))

#: The alternate band judge 1 varies between, beside the control.
ALT_BAND = "emerging"

#: The census worker's id — a distinct worker id per file keeps the lease walk's
#: residency bookkeeping independent of the other suites'.
CENSUS_WORKER_ID = "w-judge-tj24"


def _spans(submission_id: str) -> list[dict]:
    """The submission's own byte offsets over its canonical document."""
    pages = default_pages(submission_id)
    document = canonical_document("\n".join(pages))
    return [byte_span(document, page) for page in pages]


def _reply_for(submission_id: str, judge_build: str):
    """The controlled condition. Judge 1: legal, varied — one uncited verdict (the
    third submission), one `evidence_sufficient = false` verdict (the fourth), varied
    bands, half the batch's completions prefix-cached. Judge 2: the concentrated
    violation — permuted, every unit. Judge 3: legal, uniform control."""
    index = SUBMISSIONS.index(submission_id)
    if judge_build == J2_BUILD:
        return permuted_reply(CONTROL_BAND, 0.5, build_id=J2_BUILD, latency_ms=150)
    if judge_build == J1_BUILD:
        return reply_text(
            CONTROL_BAND if index % 2 == 0 else ALT_BAND,
            0.5 + 0.1 * index,
            build_id=J1_BUILD,
            cited_spans=None if index == 2 else _spans(submission_id),
            evidence_sufficient=index != 3,
            latency_ms=100 + 10 * index,
            cached_prefix_tokens=512 if index < 2 else 0,
        )
    return reply_text(
        CONTROL_BAND,
        0.9,
        build_id=J3_BUILD,
        cited_spans=_spans(submission_id),
        latency_ms=300,
    )


def _world(tmp_data_dir, make_fixture_provider):
    """The world's own loop runs the panel's first two judges: judge 1's units
    complete, judge 2's every dispatch refuses (three strikes each, the unit left
    leased). The test drives the rest through the real cycle."""
    warm_judged_modules()
    store = open_store(tmp_data_dir / "data")
    provider = make_fixture_provider()
    world = judge_world(
        store,
        provider,
        submissions=SUBMISSIONS,
        panel=3,
        reply_for=_reply_for,
        judge_worker_id=CENSUS_WORKER_ID,
    )
    return store, provider, world


class _StrikeCounter:
    """A transport-seam wrapper crediting every `complete` call — the driven cycles'
    strike counts. The fixture recording and lookup still go through the inner
    provider."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def complete(self, payload, model_ref, params):
        self.calls.append(getattr(model_ref, "build_id", str(model_ref)))
        return self._inner.complete(payload, model_ref, params)


def _driven_world(tmp_data_dir, make_fixture_provider):
    """The full run: the world's first pass, then the test drives the REAL cycle —
    judge 2's units are failed and re-dispatched to quarantine (each re-dispatch
    strikes three more times), and judge 3's units then lease, dispatch and persist.
    Returns `(store, provider, world, total_j2_calls)`."""
    store, provider, world = _world(tmp_data_dir, make_fixture_provider)
    JudgmentError = require(JUDGE_MODULE, "JudgmentError", issue=JUDGE_ISSUE)
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue=JUDGE_ISSUE)
    JudgePromptFields = warm_judged_modules()["judge_prompt_fields"]
    orchestrator = world["orchestrator"]
    counter = _StrikeCounter(provider)
    j2_keys = [(submission_id, J2_BUILD) for submission_id in SUBMISSIONS]
    j2_ref = world["judges"][J2_BUILD]

    # Judge 2's leases are live refusals; the first fail requeues each (attempt 1).
    for key in j2_keys:
        unit = world["score_units"][key]
        orchestrator.fail(unit.work_id, world["failures"][key])

    # Two more lease-dispatch-fail cycles: requeue at attempt 2, quarantine at 3.
    for cycle in (2, 3):
        batch = list(orchestrator.lease(CENSUS_WORKER_ID, STAGE_SCORE, 64))
        assert batch and all(unit.judge == J2_BUILD for unit in batch), (
            f"cycle {cycle}: the requeued violating units lease first, got "
            f"{[(u.submission_id, u.judge[:10]) for u in batch]}"
        )
        for unit in batch:
            request = ScoringWorker(store, counter, j2_ref).assemble(unit)
            worker = ScoringWorker(store, counter, j2_ref)
            # pytest.raises, not a recorded except: if a mutant made the permuted
            # reply dispatch, the failure must be THIS test's, not a count mismatch
            # three assertions later (the TC-JUDGE-18 pattern).
            with pytest.raises(JudgmentError) as excinfo:
                worker.dispatch(request, j2_ref)
            orchestrator.fail(unit.work_id, excinfo.value)

    # The residency boundary lifts once judge 2 holds no leased unit: judge 3's
    # units lease, and their replies — never recorded by the world's pass, which
    # never saw these units — are recorded here, exactly as the world records its
    # own, before dispatch.
    batch = list(orchestrator.lease(CENSUS_WORKER_ID, STAGE_SCORE, 64))
    assert batch and all(unit.judge == J3_BUILD for unit in batch), (
        f"judge 3's units lease after the violating judge is quarantined: "
        f"{[(u.submission_id, u.judge[:10]) for u in batch]}"
    )
    j3_ref = world["judges"][J3_BUILD]
    for unit in batch:
        key = (unit.submission_id, J3_BUILD)
        world["score_units"][key] = unit
        request = ScoringWorker(store, provider, j3_ref).assemble(unit)
        world["requests"][key] = request
        completion = _reply_for(unit.submission_id, J3_BUILD)
        world["replies"][key] = completion
        provider.record(JudgePromptFields(request), j3_ref, sampling_params(), completion)
        worker = ScoringWorker(store, provider, j3_ref)
        result = worker.dispatch(request, j3_ref)
        worker.persist(unit, result)
        world["results"][key] = result
        orchestrator.complete(unit.work_id)
    return store, provider, world, counter


def _census(store, world) -> dict:
    """The declared census: per judge, the six signals over the batch, from the real
    artifacts — verdict rows, recorded refusals, provider-reported figures."""
    census = {}
    for judge_build in (J1_BUILD, J2_BUILD, J3_BUILD):
        keys = [(submission_id, judge_build) for submission_id in SUBMISSIONS]
        refused = [key for key in keys if key in world["failures"]]
        rows = []
        for key in keys:
            if key in world["results"]:
                rows.extend(verdict_rows(store, world["score_units"][key].work_id))
        replies = [world["replies"][key] for key in keys]
        census[judge_build] = {
            "judged": len(rows),
            "refused": len(refused),
            "violation_rate": len(refused) / len(SUBMISSIONS),
            "strikes": sum(world["strikes"][key] for key in refused),
            "uncited_rate": (
                sum(row["uncited"] for row in rows) / len(rows) if rows else None
            ),
            "insufficient_rate": (
                sum(1 for row in rows if row["evidence_sufficient"] == 0) / len(rows)
                if rows
                else None
            ),
            "bands": Counter(row["band"] for row in rows),
            "mean_latency_ms": (
                sum(reply.latency_ms for reply in replies) / len(replies)
            ),
            "cached_hit_rate": (
                sum(1 for reply in replies if reply.cached_prefix_tokens > 0)
                / len(replies)
            ),
        }
    return census


def _concentration_alert(census, *, threshold: float = 0.5) -> dict:
    """The declared concentrated-violation rule: a judge whose violation rate reaches
    `threshold` of the batch while every other judge sits at zero is the concentration
    signature; the alert names that judge alone."""
    return {
        judge_build: census[judge_build]["violation_rate"]
        for judge_build in census
        if census[judge_build]["violation_rate"] >= threshold
        and all(
            census[other]["violation_rate"] == 0.0
            for other in census
            if other != judge_build
        )
    }


def test_tc_judge_24_a_the_six_signals_are_exact_per_criterion_and_judge(
    tmp_data_dir, make_fixture_provider
):
    """Each judge's census is the exact rate over the batch: the legal judges carry
    their varied marks (one uncited verdict, one insufficient-verdict, distinct band
    histograms, distinct latency and prefix-cache figures), and the violating judge
    carries NO verdict row at all — its refusals and their strikes are the signal."""
    store, _provider, world, counter = _driven_world(tmp_data_dir, make_fixture_provider)
    census = _census(store, world)

    j1 = census[J1_BUILD]
    assert j1["judged"] == 4 and j1["refused"] == 0
    assert j1["uncited_rate"] == 0.25, f"judge 1's uncited rate: {j1!r}"
    assert j1["insufficient_rate"] == 0.25, f"judge 1's sufficiency flag: {j1!r}"
    assert j1["bands"] == Counter({CONTROL_BAND: 2, ALT_BAND: 2}), (
        f"judge 1's band histogram: {j1!r}"
    )
    assert j1["violation_rate"] == 0.0
    assert j1["mean_latency_ms"] == pytest.approx(115.0), f"judge 1's latency: {j1!r}"
    assert j1["cached_hit_rate"] == 0.5, f"judge 1's prefix-cache rate: {j1!r}"

    j2 = census[J2_BUILD]
    assert j2["judged"] == 0 and j2["refused"] == 4, (
        f"the violating judge persisted nothing: {j2!r}"
    )
    assert j2["violation_rate"] == 1.0
    assert j2["bands"] == Counter(), (
        "a refused unit persists no row — the histogram is honestly empty"
    )
    assert j2["strikes"] == 12, (
        f"the world's first dispatches struck three times per unit: {j2!r}"
    )
    assert j2["mean_latency_ms"] == pytest.approx(150.0)
    assert j2["cached_hit_rate"] == 0.0

    j3 = census[J3_BUILD]
    assert j3["judged"] == 4 and j3["refused"] == 0
    assert j3["uncited_rate"] == 0.0 and j3["insufficient_rate"] == 0.0
    assert j3["bands"] == Counter({CONTROL_BAND: 4})
    assert j3["violation_rate"] == 0.0
    assert j3["mean_latency_ms"] == pytest.approx(300.0)
    assert j3["cached_hit_rate"] == 0.0

    # the driven re-dispatch cycles struck judge 2 exactly three times per attempt:
    # two driven cycles over four units, three calls each.
    assert len([c for c in counter.calls if c == J2_BUILD]) == 24, (
        f"two driven cycles x four units x three strikes: {counter.calls!r}"
    )


def test_tc_judge_24_b_the_concentrated_violation_alert_fires_for_that_judge_only(
    tmp_data_dir, make_fixture_provider
):
    """The alert names judge 2 alone; the same rule over a census whose violations
    are shared stays silent — the concentration, not the violation count, is the
    signature."""
    store, _provider, world, _counter = _driven_world(
        tmp_data_dir, make_fixture_provider
    )
    census = _census(store, world)
    assert _concentration_alert(census) == {J2_BUILD: 1.0}, (
        f"the concentrated-violation alert must name judge 2 alone: "
        f"{_concentration_alert(census)!r}"
    )
    dispersed = {judge: dict(row) for judge, row in census.items()}
    dispersed[J1_BUILD]["violation_rate"] = 0.5
    assert _concentration_alert(dispersed) == {}, (
        "a violation rate the other judges share is not a concentration — the alert "
        "stays silent"
    )