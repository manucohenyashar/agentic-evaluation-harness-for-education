"""`TC-ORCH-C21` — the two non-promises: no ordering promise inside a Sweep 2 batch,
and no promise of when a unit runs (§6.11.7).

`CT-ORCH-21`'s technique: make the unpromised thing vary and assert the consumers
still behave. The dispatch order's fixed key (`FR-ORCH-07`, CT-ORCH-05's four
promised levels) orders scoring **judge → question → criterion, the submissions
parallel beneath** — so the submission order inside one `(judge, question, criterion)`
batch is precisely what is NOT promised (`_dispatch_order` itself records it: within
a group the submission order is `work_id`'s, explicitly unpromised), and the moment
a unit runs is unpromised too. Both are varied here, and the consumers — M-JUDGE's
scoring workers landing verdicts, M-AGG's aggregate over the ledger — must not move:

1. **Intra-batch shuffles.** The score units are leased batch by batch in the
   dispatch's own handout order — a batch is one `(judge, question, criterion)`
   group's handout, the residency gate holding the batch's judge until its units
   finish — and each batch is processed in a seeded permutation that re-orders
   ONLY its submissions. Across many shuffle seeds the per-unit verdicts and the
   per-pair `CriterionScore` are identical to the unshuffled world's. A consumer
   that keyed on intra-batch position — an aggregation that averaged in submission
   order, a verdict write that assumed the batch's first unit grades first — fails
   here.
2. **Randomized run timing.** The second non-promise, separately: units run when the
   ledger says, not when a clock promises. The delayed world dispatches every unit
   in the handout order and lands each batch's persists in a seeded-random
   completion order — the ledger's `done_ticks` sequence, which is the only "when"
   the consumer can observe — and the aggregate is identical to the in-order
   world's. No wall-clock ordering assumption, no implicit "later units see earlier
   results" beyond the dependency graph CT-ORCH-05 does promise. (The residency
   gate confines the deferral to one batch at a time — the shipped gate's own
   constraint — and within it the completion order is fully seeded-random. The
   delay is realized as completion-order randomization, not sleeps: the consumer's
   only timing input is the ledger's completion order, and a sleep would produce
   the same state slower.)
3. **The promised levels still hold** — under every shuffle: the dispatch handout
   and the shuffled processing sequence both project to the key
   (judge panel position, criterion) non-decreasing, and the shuffle is proven to
   actually permute submissions. A shuffle that "passed" by also re-ordering the
   promised levels would be breaking CT-ORCH-05 to satisfy CT-ORCH-21; these
   assertions close that door.

The verdict plan is fixed per (judge, submission) — deliberately disagreeing
panels, so each pair's aggregate is a real median over a real spread and not one
constant row the differential could match by accident.

Isolation: rung 2 for the orchestrator (real store, real package, real documents,
the real claim walk whose handout order is the promised-levels observable), rung 3
per consumer — the real scoring workers over the recorded fixture provider, and
M-AGG's pure `aggregate` read from the ledger.
"""

from __future__ import annotations

import random

import pytest

from aeh.agg import aggregate as agg_aggregate
from aeh.extract import ExtractionWorker
from aeh.extract import assemble_request, prompt_fields
from aeh.judge import ScoringWorker
from aeh.judge import prompt_fields as judge_prompt_fields
from aeh.orch import STAGE_EXTRACT, STAGE_SCORE, Orchestrator
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.agg_vocabulary import band as agg_band
from tests.support.agg_vocabulary import criterion as agg_criterion
from tests.support.agg_vocabulary import favourable_signals, verdict as agg_verdict
from tests.support.conf_builders import EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3
from tests.support.extract_vocabulary import (
    extractor_ref,
    sampling_params,
    span_completion,
    verdict_completion,
)
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    PLAIN_TRANSCRIPT,
    seed_document,
    seed_run,
)

pytestmark = [pytest.mark.contract]

_RUN_ID = "run-c21-nonpromise"

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003", "SYN-004")

#: One judged criterion, holistic — a real three-judge base panel per submission,
#: so each `(judge, question, criterion)` batch spans the cohort and the intra-batch
#: submission order is a real dimension, not a single row.
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic",
     "band_count": 4},
)

#: The declared band set: four bands, points non-decreasing in ordinal
#: (FR-PKG-06) — a non-degenerate scale, so the agreement figure is real.
_BANDS = (("A", 0, 2.0), ("B", 1, 3.0), ("C", 2, 4.0), ("D", 3, 5.0))

_PANEL_REFS = (EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3)

_WORKER = "w-c21"

_NEEDLE = "The evidence supports the conclusion"

#: The shuffle seeds. Each seeds one world's intra-batch permutation; the worlds
#: share the cohort, the package and the verdict plan — only the unpromised order
#: varies.
_SHUFFLE_SEEDS = (11, 20260101, 7, 404, 99, 12345)


def _spans() -> list[dict[str, object]]:
    start = PLAIN_TRANSCRIPT.find(_NEEDLE)
    assert start >= 0, "fixture bug: the span needle is not in the transcript"
    return [{"start": start, "end": start + len(_NEEDLE), "text": _NEEDLE}]


def _verdict_for(unit) -> tuple[str, float]:
    """The fixed verdict content for one unit: keyed by (judge, submission), so the
    processing order can never change what a unit's judge says — only whether the
    consumers stay indifferent to when it lands."""
    judge_index = next(
        (i for i, ref in enumerate(_PANEL_REFS) if ref.build_id == unit.judge), None
    )
    assert judge_index is not None, (
        f"fixture bug: unit's judge {unit.judge!r} is not a panel arm"
    )
    submission_index = _SUBMISSIONS.index(unit.submission_id)
    band = _BANDS[(judge_index + submission_index) % len(_BANDS)]
    confidence = 0.70 + 0.05 * judge_index + 0.01 * submission_index
    return band[0], round(confidence, 2)


def _declare_bands(store, version) -> None:
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    for ordinal, (name, ord_, points) in enumerate(_BANDS):
        catalog.add_band(version, "C1", ord_, name, points, f"band {name}")


def _drive_extract(orchestrator, store, provider, run_id) -> None:
    worker_ref = extractor_ref()
    worker = ExtractionWorker(store, provider, worker_ref)
    while True:
        batch = orchestrator.lease(_WORKER, STAGE_EXTRACT, 8)
        if not batch:
            break
        for unit in batch:
            request = assemble_request(unit, store=store)
            provider.record(
                prompt_fields(request),
                worker_ref,
                sampling_params(),
                span_completion(_spans(), build_id="build-ct-c21"),
            )
            worker.process(unit)


def _score_in_batches(store, orchestrator, provider, *, seed=None,
                      result_sink=None, batch_flush=None):
    """Lease and process every score unit, one batch at a time.

    The claim walk hands out in `_dispatch_order`'s order — the promised key
    (judge panel position, question, criterion) with the submissions parallel
    beneath — and the handout is single-`(judge, question, criterion)` per batch
    (the residency gate holds the batch's judge until its units finish), so each
    leased batch IS one group's handout in the dispatch's own order.

    `seed` permutes the SUBMISSIONS inside each leased batch and nothing else; the
    processed sequence's group order stays the dispatch's. `result_sink` defers a
    unit's persist (the timing leg's delay) and `batch_flush` lands the deferred
    results at each batch's end — the gate holds the batch's judge until its units
    finish, so the deferral cannot span batches and the flush is where the
    completion order is chosen. Returns `(handout, processed)` — the dispatch's
    order, and the order the units were actually processed in.
    """
    rng = random.Random(seed) if seed is not None else None
    handout: list = []
    processed: list = []
    for _ in range(32):
        batch = orchestrator.lease(_WORKER, STAGE_SCORE, 8)
        if not batch:
            break
        handout.extend(batch)
        order = list(range(len(batch)))
        if rng is not None:
            rng.shuffle(order)
        for i in order:
            unit = batch[i]
            processed.append(unit)
            _process_and_persist(store, provider, unit, result_sink=result_sink)
        if batch_flush is not None:
            batch_flush()
    return handout, processed


def _grouped(units):
    """The units grouped by `(judge, criterion)` — first-appearance order, which is
    the dispatch handout's group order (the promised levels, held)."""
    grouped: dict[tuple, list] = {}
    for unit in units:
        grouped.setdefault((unit.judge, unit.criterion_id), []).append(unit)
    return grouped


def _panel_positions() -> dict[str, int]:
    return {ref.build_id: i for i, ref in enumerate(_PANEL_REFS)}


def _level_projection(units) -> list[tuple[int, str]]:
    """The promised key's projection: (judge panel position, criterion) — the
    levels CT-ORCH-05 fixes; the submission dimension is deliberately absent."""
    positions = _panel_positions()
    return [(positions[u.judge], u.criterion_id) for u in units]


def _process_and_persist(store, provider, unit, *, result_sink=None) -> None:
    """Assemble, record the unit's judge reply, dispatch through the real worker —
    persist immediately, or hand the result to `result_sink` for a delayed land."""
    judge_ref = next(ref for ref in _PANEL_REFS if ref.build_id == unit.judge)
    judge_worker = ScoringWorker(store, provider, judge_ref)
    request = judge_worker.assemble(unit)
    band_name, confidence = _verdict_for(unit)
    provider.record(
        judge_prompt_fields(request),
        judge_ref,
        sampling_params(),
        verdict_completion(band_name, confidence, build_id="build-ct-c21"),
    )
    result = judge_worker.dispatch(request, judge_ref)
    assert result.band == band_name, (
        "precondition: the judge's reply was not the verdict the fixture recorded"
    )
    if result_sink is None:
        judge_worker.persist(unit, result)
    else:
        result_sink(unit, result)


def _read_panel_scores(store, run_id) -> dict[str, tuple]:
    """M-AGG's consumer read: the ledger's verdicts per (submission, criterion),
    aggregated through the shipped module — no ORDER BY, so the read order is the
    ledger's own insertion order, which the shuffle and delay legs vary."""
    criterion = agg_criterion(
        [agg_band(name, ord_, points) for name, ord_, points in _BANDS],
        scoring_model="holistic",
        criterion_id="C1",
    )
    signals = favourable_signals()
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT w.submission_id, v.band, v.band_ordinal, v.self_confidence "
        "FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :r AND w.criterion_id = 'C1'",
        r=run_id,
    )
    panels: dict[str, list] = {}
    for row in rows:
        panels.setdefault(row["submission_id"], []).append(row)
    scores: dict[str, object] = {}
    for submission_id, panel_rows in panels.items():
        verdicts = [
            agg_verdict(
                r["band"], int(r["band_ordinal"]),
                self_confidence=float(r["self_confidence"]),
            )
            for r in panel_rows
        ]
        scores[submission_id] = agg_aggregate(verdicts, criterion, signals)
    return scores


def _read_verdicts(store, run_id) -> dict[tuple, tuple]:
    """The landed verdicts keyed by the unit's semantic identity —
    (judge, submission, criterion): the per-unit content the shuffle must not move.
    (`work_id` is a content hash that differs per store, so it can't key a
    cross-world differential; the (judge, submission) pair is what the verdict plan
    fixes, and each judge grades each submission once on C1.)"""
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT w.judge_id, w.submission_id, w.criterion_id, "
        "v.band, v.band_ordinal, v.self_confidence "
        "FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :r AND w.criterion_id = 'C1' ORDER BY v.work_id",
        r=run_id,
    )
    return {
        (r["judge_id"], r["submission_id"], r["criterion_id"]): (
            r["band"], int(r["band_ordinal"]), float(r["self_confidence"])
        )
        for r in rows
    }


def _score_projection(scores) -> dict[str, tuple]:
    return {
        submission_id: (
            score.criterion_id, score.band, score.ordinal, score.points,
            score.modal_band, score.band_spread, score.judge_count,
            score.agreement, score.agreement_degenerate, score.histogram,
        )
        for submission_id, score in scores.items()
    }


def _world(tmp_data_dir, seed_tag: str, provider_factory):
    """One fresh world: cohort, package, documents, extraction all done."""
    store = open_store(tmp_data_dir / seed_tag)
    orchestrator, run_id, version = seed_run(
        store, submissions=_SUBMISSIONS, criteria=_CRITERIA, run_id=_RUN_ID,
    )
    _declare_bands(store, version)
    for submission_id in _SUBMISSIONS:
        seed_document(store, submission_id)
    orchestrator.enumerate_units(run_id)
    orchestrator.start(run_id)
    provider = provider_factory()
    _drive_extract(orchestrator, store, provider, run_id)
    return store, orchestrator, provider, run_id


def test_tc_orch_c21_consumer_output_is_invariant_across_intra_batch_shuffles(
    tmp_data_dir, make_fixture_provider
):
    """Step 1-3: across many seeded shuffles of the submission order inside each
    `(judge, criterion)` batch — promised levels held — the verdicts and the
    aggregated `criterion_score` figures are identical to the unshuffled world's."""
    reference_scores = None
    reference_verdicts = None

    for seed in (None, *_SHUFFLE_SEEDS):
        store, orchestrator, provider, run_id = _world(
            tmp_data_dir, "identity" if seed is None else f"shuffle-{seed}",
            make_fixture_provider,
        )
        try:
            handout, processed = _score_in_batches(
                store, orchestrator, provider, seed=seed
            )
            assert len(handout) == len(_SUBMISSIONS) * len(_PANEL_REFS), (
                f"world {seed}: the drive leased {len(handout)} score units, "
                f"expected {len(_SUBMISSIONS) * len(_PANEL_REFS)} — a partial panel "
                "would let the differential pass on rows that were never scored"
            )

            # The promised levels hold in the DISPATCH's own handout, whatever the
            # submissions beneath: (judge panel position, criterion) non-decreasing.
            projection = _level_projection(handout)
            assert projection == sorted(projection), (
                f"world {seed}: the dispatch handout's (judge, criterion) sequence "
                f"{projection} is not in the promised key order — the orchestrator "
                "broke CT-ORCH-05's levels, which this case holds fixed"
            )

            # Step 1: process in the seeded-shuffled order (or the handout's own,
            # seed None — the identity world), promised levels still held.
            processed_projection = _level_projection(processed)
            assert processed_projection == sorted(processed_projection), (
                f"seed {seed}: the shuffled processing sequence left the promised "
                "(judge, criterion) levels — the shuffle must vary ONLY the "
                "submission dimension inside each batch (step 3's door, closed)"
            )
            if seed is not None:
                shuffled_groups = {
                    key: [u.submission_id for u in units]
                    for key, units in _grouped(processed).items()
                }
                identity_groups = {
                    key: [u.submission_id for u in units]
                    for key, units in _grouped(handout).items()
                }
                assert shuffled_groups != identity_groups, (
                    f"seed {seed}: the shuffle permuted nothing — every group kept "
                    "the identity order, so the differential below would assert "
                    "nothing about intra-batch order"
                )

            verdicts = _read_verdicts(store, run_id)
            scores = _read_panel_scores(store, run_id)
            assert len(scores) == len(_SUBMISSIONS), (
                f"world {seed}: {len(scores)} pairs aggregated from "
                f"{len(_SUBMISSIONS)} submissions — the consumer read is not over "
                "the cohort's full panel set"
            )
            if reference_verdicts is None:
                reference_verdicts, reference_scores = verdicts, scores
            else:
                assert verdicts == reference_verdicts, (
                    f"seed {seed}: the landed verdicts differ from the unshuffled "
                    "world's — M-JUDGE's verdict write carries an intra-batch "
                    "position (CT-ORCH-21: none is promised, so none may matter)"
                )
                assert scores == reference_scores, (
                    f"seed {seed}: the aggregated criterion scores differ from the "
                    "unshuffled world's — M-AGG consumed the submission order the "
                    "orchestrator never promised (CT-ORCH-21)"
                )
        finally:
            store.close()


def test_tc_orch_c21_consumer_output_is_invariant_under_randomized_run_timing(
    tmp_data_dir, make_fixture_provider
):
    """Step 4, separately: the orchestrator promises that a unit runs or quarantines
    visibly, never WHEN. A world whose units complete in a seeded-random order (the
    persists land shuffled — the ledger's done_ticks sequence randomized) aggregates
    to the identical verdicts and criterion scores as the in-order world."""
    store, orchestrator, provider, run_id = _world(
        tmp_data_dir, "in-order", make_fixture_provider
    )
    try:
        handout, _ = _score_in_batches(store, orchestrator, provider)
        assert len(handout) == len(_SUBMISSIONS) * len(_PANEL_REFS
        ), (
            "precondition: the in-order reference leased an incomplete panel — the "
            "differential below would compare against a broken reference"
        )
        in_order_scores = _read_panel_scores(store, run_id)
        in_order_verdicts = _read_verdicts(store, run_id)
    finally:
        store.close()

    for seed in (5, 606, 7007):
        store, orchestrator, provider, run_id = _world(
            tmp_data_dir, f"delay-{seed}", make_fixture_provider
        )
        try:
            # Dispatch in the handout order, defer every persist, land each batch's
            # deferred results in a seeded-random completion order: the "when a unit
            # runs" dimension, varied. The residency gate forces the flush at each
            # batch's end — the gate holds the batch's judge until its units finish —
            # so the randomization is per batch; across the run's batches the
            # completion sequence is still nothing like the handout's.
            pending: list[tuple] = []
            rng = random.Random(seed)

            def sink(unit, result):
                pending.append((unit, result))

            def flush():
                rng.shuffle(pending)
                for unit, result in pending:
                    worker = ScoringWorker(
                        store, provider,
                        next(
                            ref for ref in _PANEL_REFS
                            if ref.build_id == unit.judge
                        ),
                    )
                    worker.persist(unit, result)
                pending.clear()

            handout, _ = _score_in_batches(
                store, orchestrator, provider, result_sink=sink, batch_flush=flush,
            )
            assert len(handout) == len(_SUBMISSIONS) * len(_PANEL_REFS), (
                f"seed {seed}: the delayed drive leased {len(handout)} score units, "
                f"expected {len(_SUBMISSIONS) * len(_PANEL_REFS)} — the differential "
                "below would compare against a broken world"
            )

            completion_order = [
                r["work_id"]
                for r in store.cohort(ORCH_COHORT_ID).query(
                    "SELECT work_id FROM work_unit WHERE run_id = :r "
                    "AND stage = 'score' ORDER BY done_ticks ASC",
                    r=run_id,
                )
            ]
            assert completion_order != [
                u.work_id for u in handout
            ], (
                f"seed {seed}: the delayed land completed in the handout order — the "
                "timing non-promise was never varied and the differential below "
                "would assert nothing"
            )
            assert _read_verdicts(store, run_id) == in_order_verdicts, (
                f"seed {seed}: the verdicts moved with the completion order — a "
                "consumer assumed 'later units see earlier results' the dependency "
                "graph never promised"
            )
            delayed = _read_panel_scores(store, run_id)
            assert _score_projection(delayed) == _score_projection(in_order_scores), (
                f"seed {seed}: the aggregated criterion scores differ under the "
                "randomized completion order — M-AGG carries a timing dependency "
                "(CT-ORCH-21: no wall-clock ordering assumption)"
            )
        finally:
            store.close()
