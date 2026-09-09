"""`TC-ORCH-C04` — the consumer double-run contract (§6.11.7): every consumer of a
leased unit is at-least-once safe — **running it twice over the same unit writes the
stage's rows once** (`CT-ORCH-04`, FR-ORCH-03, ADR-8).

The leasing contract (`CT-ORCH-04`) makes double-execution a *design condition*, not a
defect: an abandoned lease is requeued by the sweeper, so a worker may finish a unit a
reclaimed lease has already handed to another. Each owning stage's answer is the case's
oracle, driven through the stage's real shipped worker (rung 3 — real store, real
package, real documents, the recorded fixture provider the only double):

- `M-EXTRACT` (`aeh.extract.ExtractionWorker.process`): the done-guard — a unit already
  `done` re-reads its evidence instead of re-calling the provider; one evidence row.
- `M-JUDGE` (`aeh.judge.ScoringWorker.persist`): `INSERT OR IGNORE` on
  `verdict_id = work_id` inside the guarded `mark_done` transaction — a second persist
  (even a CONFLICTING band, the strongest form) changes nothing.
- `M-DET` (`aeh.det.DeterministicEvaluator.evaluate`): the upsert — a re-run of the
  same (submission, criterion) is one row.
- `M-SYNTH` (`aeh.synth.synthesize`): the stored narrative absorbs the retried call —
  one L1 row per question, one L2 row, and the provider is not called again.
- The run-level capstone: a full dispatch pass to exhaustion, then another pass after
  the sweep — the transport seam is not called again. No worker double-run is allowed
  to re-dispatch a done unit, which is what "no doubled cost" means at the run level.

Relationship to shipped cases, disclosed: the per-stage at-least-once guarantees are
each asserted by their own contract suites (extraction's `CT-EXTRACT-*` family,
judgment's `FR-JUDGE-11` files, `tests/contract/det/*`, RES-07 in
`tests/resilience/orch/test_escalation_and_synthesis_boundaries.py` for synthesis).
The case's OTHER limb — the leasing mechanics themselves (claim → `leased` with
owner and expiry, heartbeat extension, an expired lease returning to `pending`) — is
`tests/integration/orch/test_leasing.py` (TC-ORCH-05/09), which drives each of those
transitions against the shipped claim pass; this file does not re-assert it.
Those suites drive each stage in isolation, at the stage's own oracle; the C04 limb is
the LEDGER's contract with all of them at once — one vocabulary of states
(`pending/leased/done/quarantined`), one double-run sweep, and the capstone that a
completed run cannot be made to spend again.
"""

from __future__ import annotations

import pytest

from aeh.det import DeterministicEvaluator
from aeh.extract import ExtractionWorker
from aeh.extract import assemble_request, prompt_fields
from aeh.judge import ScoringResult, ScoringWorker
from aeh.judge import prompt_fields as judge_prompt_fields
from aeh.orch import STAGE_EXTRACT, STAGE_SCORE, Orchestrator
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.extract._doubles import CountingProvider
from tests.support.conf_builders import EDGE_JUDGE, edge_panel
from tests.support.extract_vocabulary import (
    extractor_ref,
    sampling_params,
    span_completion,
    verdict_completion,
)
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    PLAIN_TRANSCRIPT,
    orch_cfg,
    seed_document,
    seed_run,
)
from tests.support.synth_vocabulary import (
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.contract]

#: The extractor's recorded reply: one span over the transcript's opening sentence, a
#: valid byte range by construction (the needle is IN the transcript).
_NEEDLE = "The evidence supports the conclusion"


def _spans() -> list[dict[str, object]]:
    start = PLAIN_TRANSCRIPT.find(_NEEDLE)
    assert start >= 0, "fixture bug: the span needle is not in the transcript"
    return [{"start": start, "end": start + len(_NEEDLE), "text": _NEEDLE}]


def _count(store, sql, **params) -> int:
    return store.cohort(ORCH_COHORT_ID).query(sql, **params)[0]["n"]


def _banded_package(store, version, criterion_id):
    """Declare the criterion's REAL band set through the shipped catalog API
    (the `test_judge_band_forcing.py` seeding pattern): two bands, A and B."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    # Points non-decreasing in ordinal (FR-PKG-06): A is the lower band.
    catalog.add_band(version, criterion_id, 0, "A", 2.0, "adequate")
    catalog.add_band(version, criterion_id, 1, "B", 4.0, "excellent")
    return catalog


def test_tc_orch_c04_extract_double_run_single_evidence(
    tmp_data_dir, make_fixture_provider
):
    """`M-EXTRACT` at-least-once: the second `process()` of a done unit reads the
    ledger — one evidence row, and the provider is not called again."""
    provider = CountingProvider(make_fixture_provider())
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store,
            submissions=("SYN-001",),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
            ),
        )
        seed_document(store, "SYN-001", PLAIN_TRANSCRIPT)
        orchestrator.enumerate_units(run_id)
        (unit,) = orchestrator.lease("w-c04-extract", STAGE_EXTRACT, 1)

        model_ref = extractor_ref()
        request = assemble_request(unit, store=store)
        provider.record(
            prompt_fields(request), model_ref, sampling_params(),
            span_completion(_spans(), build_id="build-ct-c04"),
        )
        worker = ExtractionWorker(store, provider, model_ref)
        first = worker.process(unit)
        assert first.spans, "precondition: the first process() extracted nothing"
        evidence = lambda: _count(  # noqa: E731 - the same row set each read
            store,
            "SELECT COUNT(*) AS n FROM evidence e JOIN work_unit w "
            "ON w.work_id = e.work_id WHERE w.run_id = :r",
            r=run_id,
        )
        assert evidence() == 1, "the first extraction wrote something other than one row"
        calls_after_first = provider.count
        assert calls_after_first == 1, (
            "precondition: the first extraction made exactly one model call — the "
            "double-run below is measured against this count"
        )

        second = worker.process(unit)
        assert evidence() == 1, (
            "the second process() of a done unit wrote a second evidence row — the "
            "done-guard (a done unit re-reads its evidence) is not what M-EXTRACT "
            "ships, and at-least-once leasing would double every completed extraction"
        )
        assert provider.count == calls_after_first, (
            "the second process() called the provider again — the done-guard must "
            "absorb the re-entry BEFORE the model boundary, or a reclaimed lease "
            "re-bills every completed unit"
        )
        assert _count(
            store,
            "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r "
            "AND stage = 'extract' AND status = 'done'",
            r=run_id,
        ) == 1
    finally:
        store.close()


def test_tc_orch_c04_judge_double_persist_one_verdict(
    tmp_data_dir, make_fixture_provider
):
    """`M-JUDGE` at-least-once: a second `persist()` — of a CONFLICTING band, the
    strongest form of the double — leaves the first verdict standing, one row."""
    provider = CountingProvider(make_fixture_provider())
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, version = seed_run(
            store,
            submissions=("SYN-001",),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic",
                 "band_count": 2},
            ),
        )
        _banded_package(store, version, "C1")
        seed_document(store, "SYN-001", PLAIN_TRANSCRIPT)
        orchestrator.enumerate_units(run_id)
        # The sweep-2 gate: the criterion's extraction must be done before its score
        # units are claimable (FR-ORCH-07) — run the real extractor once against the
        # recorded seam, so the score lease below is honest dispatch, not a bypass.
        (extract_unit,) = orchestrator.lease("w-c04-judge", STAGE_EXTRACT, 1)
        provider.record(
            prompt_fields(assemble_request(extract_unit, store=store)),
            extractor_ref(),
            sampling_params(),
            span_completion(_spans(), build_id="build-ct-c04"),
        )
        ExtractionWorker(store, provider, extractor_ref()).process(extract_unit)
        (unit,) = orchestrator.lease("w-c04-judge", STAGE_SCORE, 1)

        worker = ScoringWorker(store, provider, EDGE_JUDGE)
        request = worker.assemble(unit)
        provider.record(
            judge_prompt_fields(request), EDGE_JUDGE, sampling_params(),
            verdict_completion("B", 0.9, build_id="build-ct-c04"),
        )
        result = worker.dispatch(request, EDGE_JUDGE)
        assert result.band == "B"
        worker.persist(unit, result)
        verdicts = lambda: store.cohort(ORCH_COHORT_ID).query(  # noqa: E731
            "SELECT band FROM verdict WHERE work_id = :w", w=unit.work_id
        )
        assert len(verdicts()) == 1 and verdicts()[0]["band"] == "B"

        # The double-run: a second completion of the same unit carrying a DIFFERENT
        # band — a naive upsert would flip the stored verdict underneath M-AGG.
        conflict = ScoringResult(
            work_id=unit.work_id,
            judge_id=result.judge_id,
            band="A",
            band_ordinal=0,
            self_confidence=0.95,
            cited_spans=(),
            uncited=True,
            evidence_assessment="the double-run's own assessment",
            evidence_sufficient=False,
            resolved_build="build-ct-c04-late",
            attempts=1,
            notes=None,
        )
        worker.persist(unit, conflict)
        rows = verdicts()
        assert len(rows) == 1, (
            "a second persist of a done unit wrote a second verdict row — INSERT OR "
            "IGNORE on verdict_id is not what M-JUDGE ships, and at-least-once leasing "
            "would double-write every landed verdict"
        )
        assert rows[0]["band"] == "B", (
            f"the second (conflicting) completion REWROTE the stored band to "
            f"{rows[0]['band']!r} — the first worker's verdict must stand (the row "
            "carries the band AND the band's position; a late arrival may not "
            "un-land it)"
        )
    finally:
        store.close()


def test_tc_orch_c04_det_double_evaluation_one_row(tmp_data_dir):
    """`M-DET` at-least-once: two evaluations of the same (submission, criterion) —
    one score row, by the upsert (`FR-DET-02`'s idempotence under redelivery). The
    audit trail appends by design and is deliberately NOT asserted here: `aeh.det`'s
    own disclosure states the design's idempotency constraint names the rederivation
    and the stats writes, not the trail."""
    from tests.support.det_vocabulary import (
        open_det_store,
        seed_det_world,
        seed_selection_answers,
    )

    store = open_det_store(tmp_data_dir)
    try:
        run_id, version, cohort_id = seed_det_world(
            store,
            submissions=("S1",),
            criteria=[{"criterion_id": "M1", "question_id": "Q1", "key": ("B",)}],
        )
        seed_selection_answers(
            store, cohort_id, [{"submission_id": "S1", "selection": "B"}]
        )
        evaluator = DeterministicEvaluator(store)
        evaluator.evaluate(run_id, "S1", "M1")
        rows = lambda: store.cohort(cohort_id).query(  # noqa: E731
            "SELECT band, points, state FROM criterion_score "
            "WHERE submission_id = :s AND criterion_id = :c",
            s="S1", c="M1",
        )
        assert len(rows()) == 1, "precondition: the first evaluation wrote one row"
        band = rows()[0]["band"]

        evaluator.evaluate(run_id, "S1", "M1")
        after = rows()
        assert len(after) == 1, (
            "the second evaluation grew the score table — the upsert (ON CONFLICT DO "
            "UPDATE) is not what M-DET ships, and a requeued deterministic unit would "
            "double-score"
        )
        assert after[0]["band"] == band, (
            "the second evaluation changed the score — a redelivery must re-derive the "
            "same score from the same reads (the evaluation is a pure lookup), and a "
            "moving score means the second write landed different state"
        )
    finally:
        store.close()


def test_tc_orch_c04_synth_double_run_one_row_pair(tmp_data_dir):
    """`M-SYNTH` at-least-once: the retried synthesis is absorbed by the stored
    narrative — one L1 row per question, one L2 row, and the provider is NOT called
    a second time (the call is the cost; the absorb is the guarantee)."""
    from aeh.synth import synthesize

    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store,
            submissions=("SYN-001",),
            criteria=(
                {"criterion_id": "Q1C1", "kind": "open", "scoring_model": "holistic"},
                {"criterion_id": "Q1C2", "kind": "open", "scoring_model": "holistic"},
            ),
        )
        orchestrator.enumerate_units(run_id)
        seed_scored_submission(
            store, run_id, "SYN-001",
            criteria_by_question={"Q1": ("Q1C1", "Q1C2")},
            complete_questions={"Q1"},
        )
        provider = CaptureProvider([
            narrative_completion(
                "Question 1: the response states the hypothesis and cites the worked "
                "steps for this question.",
                ("Q1C1", "Q1C2"),
            ),
            narrative_completion(
                "Overall: the submission works through each question in turn."
            ),
        ])
        synthesize(store, provider, synth_ref(), run_id, submission_id="SYN-001")
        calls_after_first = provider.calls
        assert calls_after_first >= 1, (
            "precondition: the first synthesis made no model call — the fixture cannot "
            "be exercising the retried-call path if the first pass never reached the "
            "boundary"
        )

        synthesize(store, provider, synth_ref(), run_id, submission_id="SYN-001")

        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT level, question_id FROM narrative WHERE run_id = :r "
            "AND submission_id = :s",
            r=run_id, s="SYN-001",
        )
        l1 = [r for r in rows if r["question_id"] == "Q1"]
        l2 = [r for r in rows if r["question_id"] == "__test__"]
        assert len(rows) == 2 and len(l1) == 1 and len(l2) == 1, (
            f"the retried synthesis left {len(rows)} narrative rows ({len(l1)} L1, "
            f"{len(l2)} L2) — the stored narrative does not absorb the retry (ADR-8: "
            "the retried unit conflicts rather than duplicating)"
        )
        assert provider.calls == calls_after_first, (
            "the retried synthesis called the provider again — the absorb must happen "
            "BEFORE the call, or every redelivered synthesis re-bills the model for "
            "work the store already holds"
        )
    finally:
        store.close()


def test_tc_orch_c04_second_full_loop_costs_nothing(tmp_data_dir):
    """The run-level capstone: dispatch to exhaustion, sweep, dispatch again — the
    seam records NOT ONE further call. A done unit re-dispatched by a second pass is
    the doubled cost the at-least-once contract exists to forbid."""
    from aeh.prov import Completion

    class _Seam:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def call(self, request: object) -> Completion:
            self.requests.append(request)
            return Completion(
                text="synthetic band: B",
                tokens_in=3,
                tokens_out=2,
                latency_ms=1,
                resolved_build="build-ct-c04-seam",
                cached_prefix_tokens=0,
                cost=None,
            )

    store = open_store(tmp_data_dir)
    try:
        seam = _Seam()
        orchestrator, run_id, _ = seed_run(
            store,
            submissions=("SYN-001", "SYN-002"),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
                {"criterion_id": "C2", "kind": "mcq"},
            ),
            transport=seam,
        )
        for submission_id in ("SYN-001", "SYN-002"):
            seed_document(store, submission_id, PLAIN_TRANSCRIPT)
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        report = orchestrator.progress(run_id)
        for _ in range(64):
            if report.complete:
                break
            report = orchestrator.progress(run_id)
        assert report.complete, (
            "the fixture's drive never exhausted the run — the second loop below "
            "would be measuring mid-run dispatch, not redelivery"
        )
        calls_at_exhaustion = len(seam.requests)
        assert calls_at_exhaustion >= 4, (
            "precondition: the first loop dispatched too little for the capstone to "
            "mean anything — every extract and score unit must have crossed the seam"
        )

        # The boundary: expire anything a crashed pass might have held, then drive the
        # whole loop again — the second dispatcher's shape.
        orchestrator.sweep_expired_leases()
        for _ in range(8):
            after = orchestrator.progress(run_id)
            assert len(seam.requests) == calls_at_exhaustion, (
                f"a second full dispatch pass made "
                f"{len(seam.requests) - calls_at_exhaustion} further model call(s) — a "
                "completed unit was re-dispatched, which is the doubled cost the "
                "at-least-once contract forbids (FR-ORCH-03: re-running a completed "
                "run is a no-op)"
            )
            if after.complete:
                break
        assert len(seam.requests) == calls_at_exhaustion
    finally:
        store.close()
