"""`TC-ORCH-C15` — the random arm is enumerated at `ORCH_RANDOM_ARM_RATE` **independent
of confidence**, is never suppressed by the escalation ceiling — even at ceiling — and
its `origin` separation survives every consumer (§6.11.7).

Three limbs, one per sentence of `CT-ORCH-15`:

1. **Confidence invariance at the enumeration path.** The shipped unit file
   (`tests/unit/orch/test_random_arm.py`) proves the pure draw cannot read a
   confidence; the shipped mechanism file (`tests/integration/orch/
   test_random_arm_enumeration.py`) proves selection is *structurally* blind — the arm
   exists before any confidence does. The limb this case adds is the one a fold into
   the escalation path would survive both of those: confidences land in the ledger
   (real `ScoringWorker` verdicts whose `self_confidence` sweeps the range), a growth
   batch is then enumerated at the SAME rate, and the drawn set must be exactly the
   confidence-free prediction — `random_arm_selection(pair, run_random_arm_seed(run_id),
   rate)` over the pairs. A draw that consulted the ledger's confidences draws the
   growth batch differently; the exact-set differential names it.
2. **Never suppressed, even at ceiling.** The mechanism file drives the rate above the
   default 0.30 budget and asserts pending arm units; this limb drives the budget to
   its floor — 0, where ANY done escalated pair is over — and asserts the arm is not
   merely pending but *dispatchable*: a worker's claim pass leases the `random_arm`
   unit while deferring the pending escalation pair the same pass could otherwise
   have taken (the claim walk consults `admit_escalations` for `origin='escalation'`
   rows only). `escalation_budget_state` shows the same split from the operator side:
   over budget, the escalation pair named provisional, the arm nowhere on that list.
   An arm that folds under budget pressure stops auditing exactly when the routing
   policy is most strained (RISK-07).
3. **Consumers preserve the separation.** `M-AGG` (landed, #91) is driven at rung 3:
   real scoring writes verdicts from a panel whose widened members carry
   `origin='random_arm'`, the consumer reads the ledger and aggregates through the
   shipped module, and then the ORIGINS ARE RELABELLED in the ledger (the adversarial
   act) and the identical read is taken again — an equal `CriterionScore`, and
   `judge_count` 3 in both readings. The relabel's force is structural, and saying
   so precisely: `aeh.agg` exposes only the pure `aggregate(verdicts, criterion,
   signals)`, and the read that feeds it selects no origin column — there is NO
   surface through which the origin could reach the aggregation, and the relabel
   verifies that structurally (the identical read cannot move because the consumer
   input is the verdict figures alone; a future aggregate that DID read origins
   through its caller's query would have to change that query, and the
   `judge_count`-per-reading guards here would catch the drifted read). The other
   two named consumers are not re-asserted here:
   `M-STATS`' origin separability is pinned by
   `tests/contract/stats/test_ct_stats_vocabulary.py` (the origin column the stats
   fixture exposes), and `M-REVIEW`'s limb — the arm spends compute and produces no
   review item — is `tests/contract/review/test_ct_review_admission_and_residual.py::
   test_tc_review_c05_the_random_arm_spends_compute_and_produces_no_review_item`,
   standing behind #109. Duplicating either here would be two suites for one
   requirement.

Relationship to the shipped cases, disclosed: the statistical core (10,000-draw
convergence, ADV-12's engineered population) is the unit file's; up-front enumeration
and above-default-budget non-suppression are the integration file's. Neither drives a
verdict with a confidence, a dispatch claim pass under a tripped budget, or a
consumer — the surfaces this contract case owns.

Isolation: rung 3 — real store, real package, real documents, the real extraction and
scoring workers; the recorded fixture provider is the only double at the model
boundary. The `origin` relabel in limb 3 is a deliberate ledger perturbation (the
`TC-ORCH-C01` precedent of updating `work_unit` rows directly), disclosed as such.
"""

from __future__ import annotations

from typing import Callable

import pytest

from aeh.agg import aggregate as agg_aggregate
from aeh.extract import ExtractionWorker
from aeh.extract import assemble_request, prompt_fields
from aeh.judge import ScoringWorker
from aeh.judge import prompt_fields as judge_prompt_fields
from aeh.orch import (
    STAGE_EXTRACT,
    STAGE_SCORE,
    random_arm_selection,
    run_random_arm_seed,
)
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

_NEEDLE = "The evidence supports the conclusion"

_PANEL_REFS = (EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3)

_WORKER = "w-c15"


def _spans() -> list[dict[str, object]]:
    start = PLAIN_TRANSCRIPT.find(_NEEDLE)
    assert start >= 0, "fixture bug: the span needle is not in the transcript"
    return [{"start": start, "end": start + len(_NEEDLE), "text": _NEEDLE}]


def _declare_bands(store, version, criterion_id="C1"):
    """The criterion's REAL band set through the shipped catalog API (the
    `test_judge_band_forcing.py` seeding pattern): two bands, A and B."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    # Points non-decreasing in ordinal (FR-PKG-06): A is the lower band.
    catalog.add_band(version, criterion_id, 0, "A", 2.0, "adequate")
    catalog.add_band(version, criterion_id, 1, "B", 4.0, "excellent")


def _score_unit_rows(store, run_id, submission_id=None):
    sql = (
        "SELECT work_id, submission_id, criterion_id, judge_id, origin, status "
        "FROM work_unit WHERE run_id = :r AND stage = 'score'"
    )
    if submission_id is not None:
        sql += " AND submission_id = :s"
    return store.cohort(ORCH_COHORT_ID).query(sql, r=run_id, s=submission_id or "")


def _arm_pairs(store, run_id):
    """The (submission, criterion) pairs that carry an arm-origin score unit."""
    return {
        (r["submission_id"], r["criterion_id"])
        for r in store.cohort(ORCH_COHORT_ID).query(
            "SELECT submission_id, criterion_id FROM work_unit "
            "WHERE run_id = :r AND origin = 'random_arm'",
            r=run_id,
        )
    }


def _add_submissions(store, submission_ids) -> None:
    """A growth batch, written in the shipped `submission` shape (`orch_run.py`'s
    disclosed bypass: M-INGEST is not under test, the ledger is)."""
    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        for submission_id in submission_ids:
            tx.execute(
                "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                "VALUES (:s, :c, :r)",
                s=submission_id,
                c=ORCH_COHORT_ID,
                r=f"ref-{submission_id}",
            )


def _drive_extract(orchestrator, store, provider, run_id):
    """Lease and process every extract unit of the run through the real worker."""
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
                span_completion(_spans(), build_id="build-ct-c15"),
            )
            worker.process(unit)


def _score_all(
    orchestrator,
    store,
    provider,
    run_id,
    verdict_for: Callable[[object], tuple[str, float]],
) -> None:
    """Drive every claimable score unit through the real scoring worker.

    `verdict_for(unit)` returns the `(band, self_confidence)` the fixture records for
    that unit's judge reply, or `None` to leave the unit leased-untouched (the drive's
    callers hand plans that name exactly the units they want verdicts for). Each
    verdict's persist marks its unit done, so the edge-local residency gate never
    stalls on a judge's unfinished batch across the loop's lease calls.
    """
    refs_by_build = {ref.build_id: ref for ref in _PANEL_REFS}
    for _ in range(32):
        batch = orchestrator.lease(_WORKER, STAGE_SCORE, 8)
        if not batch:
            break
        for unit in batch:
            entry = verdict_for(unit)
            if entry is None:
                continue
            band_name, confidence = entry
            judge_ref = refs_by_build[unit.judge]
            judge_worker = ScoringWorker(store, provider, judge_ref)
            request = judge_worker.assemble(unit)
            provider.record(
                judge_prompt_fields(request),
                judge_ref,
                sampling_params(),
                verdict_completion(band_name, confidence, build_id="build-ct-c15"),
            )
            result = judge_worker.dispatch(request, judge_ref)
            assert result.band == band_name, (
                "precondition: the judge's reply was not the verdict the fixture "
                "recorded"
            )
            judge_worker.persist(unit, result)


def test_tc_orch_c15_arm_draw_is_invariant_under_ledger_confidence(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """The rate-invariance differential: enumerate at a mid rate over a
    confidence-free ledger, drive real verdicts whose `self_confidence` sweeps the
    range, re-enumerate (a growth batch) at the SAME rate — and the drawn set is
    exactly the confidence-free prediction, for the growth batch and for the base
    pairs alike."""
    from tests.contract.extract._doubles import CountingProvider

    # The arm is what is under test: lift the suite-root conftest's rate-0 pin to a
    # mid rate (the test's setenv lands after the autouse fixture's).
    rate = 0.5
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", str(rate))
    run_id = "run-c15-confidence"

    base = tuple(f"SYN-{i:03d}" for i in range(1, 7))
    growth = tuple(f"SYN-{i:03d}" for i in range(101, 113))
    criteria = (
        {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
         "band_count": 2},
    )

    store = open_store(tmp_data_dir)
    try:
        # A one-arm panel keeps the drive at one base score unit per pair; the widened
        # arms are what an arm draw seats, and only their EXISTENCE is under test here.
        orchestrator, _, version = seed_run(
            store,
            submissions=base,
            criteria=criteria,
            run_id=run_id,
            panel=(EDGE_JUDGE,),
        )
        _declare_bands(store, version)
        # A distinct transcript per submission, so each score request — and therefore
        # each recorded verdict reply — is its own fixture: the sweep below can vary
        # self_confidence per verdict (the reply travels with the request).
        for submission_id in base:
            seed_document(
                store,
                submission_id,
                f"{PLAIN_TRANSCRIPT}\n\nSubmission marker {submission_id}.",
            )
        orchestrator.enumerate_units(run_id)

        pairs = [(s, "C1") for s in base]
        seed = run_random_arm_seed(run_id)
        predicted_base = {
            pair for pair in pairs if random_arm_selection(pair, seed, rate)
        }
        assert predicted_base, (
            "fixture bug: the pinned run id draws no base pair at rate "
            f"{rate} — pick a run id whose seed draws at least one, or the "
            "confidence-invariance differential has no base population"
        )
        assert predicted_base != set(pairs), (
            "fixture bug: every base pair is drawn — a draw that cannot come out "
            "differently cannot show invariance"
        )

        # Confidences sweep the range, written by the REAL scoring path: the ledger
        # now holds exactly the input a confidence-folding draw would consult.
        orchestrator.start(run_id)
        provider = CountingProvider(make_fixture_provider())
        _drive_extract(orchestrator, store, provider, run_id)
        confidence_by_submission = dict(
            zip(sorted(base), (0.01, 0.21, 0.41, 0.61, 0.81, 0.99))
        )

        def _base_confidence(unit):
            origin = store.cohort(ORCH_COHORT_ID).query(
                "SELECT origin FROM work_unit WHERE work_id = :w", w=unit.work_id
            )[0]["origin"]
            if origin != "base":
                return None  # the arm's widened units are not this drive's targets
            return ("B", confidence_by_submission[unit.submission_id])

        _score_all(orchestrator, store, provider, run_id, _base_confidence)
        stored = store.cohort(ORCH_COHORT_ID).query(
            "SELECT v.self_confidence AS c FROM verdict v "
            "JOIN work_unit w ON w.work_id = v.work_id "
            "WHERE w.run_id = :r AND w.origin = 'base'",
            r=run_id,
        )
        sweep = sorted(float(r["c"]) for r in stored)
        assert len(sweep) == len(base) and sweep[0] <= 0.05 and sweep[-1] >= 0.95, (
            f"the ledger holds confidences {sweep} — the sweep must span the range "
            "for the invariance differential below to consult it"
        )

        base_arm_before = _arm_pairs(store, run_id)
        assert base_arm_before == predicted_base, (
            "fixture bug: the ledger's base arm set diverged from the prediction "
            "before the growth batch — the fixture cannot measure a change it did "
            "not make"
        )

        # The growth batch, enumerated at the SAME rate with confidences in the
        # ledger: the draw must still be the confidence-free one.
        _add_submissions(store, growth)
        orchestrator.resume(run_id)

        predicted_growth = {
            (s, "C1") for s in growth if random_arm_selection((s, "C1"), seed, rate)
        }
        assert predicted_growth, (
            "fixture bug: the pinned run id draws no growth pair at rate "
            f"{rate} — the differential would be vacuous"
        )
        growth_arm = {
            pair for pair in _arm_pairs(store, run_id) if pair[0] in growth
        }
        assert growth_arm == predicted_growth, (
            f"the growth batch drew {sorted(growth_arm)} with confidences in the "
            f"ledger, but the confidence-free draw at rate {rate} is "
            f"{sorted(predicted_growth)} — the enumeration's arm selection reached a "
            "confidence (or anything else in the ledger) that CT-ORCH-15 forbids it "
            "to read, and folding the arm into the escalation path is exactly this "
            "delta"
        )
        # The base pairs' draw is unchanged too: the same prediction re-derived over
        # a ledger that now carries confidence, INSERT OR IGNORE'd onto the same rows.
        assert _arm_pairs(store, run_id) & set(pairs) == predicted_base, (
            "re-enumeration moved the base pairs' arm membership after confidences "
            "landed — the draw is not a pure function of (pair, run seed, rate)"
        )
    finally:
        store.close()


def test_tc_orch_c15_the_arm_dispatches_at_a_zero_budget(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """The ceiling limb: `ORCH_ESCALATION_BUDGET=0` with one done escalated pair in
    the ledger (rate 1/3 > 0, strict) — a worker's claim pass leases the `random_arm`
    unit and never leases the pending escalation unit, and the operator surface names
    the escalation pair provisional while the arm stays off that list."""
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    run_id = "run-c15-ceiling"

    base = ("SYN-001", "SYN-003")
    growth = ("SYN-002",)
    criteria = (
        {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
         "band_count": 2},
    )

    store = open_store(tmp_data_dir)
    try:
        orchestrator, _, version = seed_run(
            store, submissions=base, criteria=criteria, run_id=run_id
        )
        _declare_bands(store, version)
        for submission_id in base:  # the growth submission arrives after the escalation
            seed_document(store, submission_id, PLAIN_TRANSCRIPT)
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        provider = make_fixture_provider()
        _drive_extract(orchestrator, store, provider, run_id)

        def _work_ids(submission_id, origin, status):
            return [
                r["work_id"] for r in _score_unit_rows(store, run_id, submission_id)
                if r["origin"] == origin and r["status"] == status
            ]

        # SYN-001: base scored by hand (done, judge named), escalated, and its
        # escalation units DONE — the over-budget premise (processed = 1 pair,
        # escalated = 1 pair, rate 1.0). The completion is by work_id: the claim
        # walk's order is the dispatch order's, not the fixture's.
        (base_work_id,) = [
            r["work_id"] for r in _score_unit_rows(store, run_id, "SYN-001")
            if r["origin"] == "base"
        ]
        orchestrator.complete(base_work_id)
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orchestrator.enqueue_escalation(tx, ("SYN-001", "C1"))
        for work_id in _work_ids("SYN-001", "escalation", "pending"):
            orchestrator.complete(work_id)

        # SYN-003: escalated, its widening units left PENDING — the pair an
        # over-budget dispatch must defer.
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orchestrator.enqueue_escalation(tx, ("SYN-003", "C1"))
        pending_escalation = _work_ids("SYN-003", "escalation", "pending")
        assert pending_escalation, (
            "fixture bug: SYN-003's escalation wrote no pending units — the "
            "deferral below would be vacuous"
        )

        # The growth batch, drawn at rate 1.0: SYN-002's pair enters the random arm.
        monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "1.0")
        _add_submissions(store, growth)
        seed_document(store, growth[0], PLAIN_TRANSCRIPT)
        orchestrator.resume(run_id)
        arm_units = [
            r for r in _score_unit_rows(store, run_id, "SYN-002")
            if r["origin"] == "random_arm"
        ]
        assert arm_units, (
            "fixture bug: the growth pair drew no arm units at rate 1.0 — the "
            "ceiling limb would assert nothing about the arm"
        )
        # The growth pair's extract completes, so its score units (base AND arm) are
        # sweep-2-ready — the gate below must be the ADMISSION gate, not readiness.
        (extract_work_id,) = [
            r["work_id"] for r in store.cohort(ORCH_COHORT_ID).query(
                "SELECT work_id FROM work_unit WHERE run_id = :r "
                "AND submission_id = 'SYN-002' AND stage = 'extract'",
                r=run_id,
            )
        ]
        orchestrator.complete(extract_work_id)

        # The budget's floor: ANY done escalated pair is over it (strict >).
        monkeypatch.setenv("HARNESS_ORCH_ESCALATION_BUDGET", "0")
        state = orchestrator.escalation_budget_state(run_id)
        assert state.over_budget, (
            "the operator surface does not read the run over budget (rate "
            f"{state.escalation_rate} against budget {state.budget}) — the premise "
            "the ceiling limb asserts under does not hold"
        )
        assert "SYN-003/C1" in state.provisional_pairs, (
            f"the pending escalation pair is not on the provisional surface "
            f"({state.provisional_pairs}) — the remainder FR-ORCH-14 marks must be "
            "visible by name, not absorbed into a silent deferral"
        )

        # The dispatch differential: drive the claim pass to exhaustion — the arm is
        # claimed, the escalation is not. The claimed units' origins are read from
        # the ledger (`WorkUnit` carries the judge, not the origin column).
        claimed_work_ids: set[str] = set()
        for _ in range(32):
            batch = orchestrator.lease(_WORKER, STAGE_SCORE, 8)
            if not batch:
                break
            for unit in batch:
                claimed_work_ids.add(unit.work_id)
                orchestrator.complete(unit.work_id)

        def _origin_of(work_id):
            return store.cohort(ORCH_COHORT_ID).query(
                "SELECT origin FROM work_unit WHERE work_id = :w", w=work_id
            )[0]["origin"]

        claimed_origins = [_origin_of(w) for w in claimed_work_ids]
        assert any(origin == "random_arm" for origin in claimed_origins), (
            f"no random_arm unit was claimed while the run stood at a zero budget "
            f"(claimed origins: {claimed_origins}) — the ceiling suppressed the arm, "
            "the exact fold FR-ORCH-11 forbids: the sample stops auditing precisely "
            "when the routing policy is most strained (CT-ORCH-15, RISK-07)"
        )
        assert not any(origin == "escalation" for origin in claimed_origins), (
            f"an over-budget claim pass leased an escalation unit (claimed origins: "
            f"{claimed_origins}) — the budget rations escalation dispatch through "
            "admit_escalations, and a claim that ignores the gate spends past the "
            "budget the operator surface just reported"
        )
        still_pending = _work_ids("SYN-003", "escalation", "pending")
        assert still_pending and not (set(still_pending) & claimed_work_ids), (
            "the pending escalation pair's units were consumed by the drive — the "
            "deferral must leave them pending, the recoverable remainder, never "
            "dropped and never claimed behind the budget's back"
        )
    finally:
        store.close()


def test_tc_orch_c15_agg_preserves_the_origin_separation(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """The M-AGG limb: a panel whose widened members carry `origin='random_arm'` is
    aggregated from the ledger, then the origins are relabelled and the identical
    consumer read is taken again — an equal `CriterionScore`, `judge_count` 3 in both
    readings. The check is structural: the consumer read selects no origin column
    and `aeh.agg` takes no origin input, so the relabel cannot move the result —
    a future aggregate that wanted the origin would have to widen this very read,
    and the per-reading guards below would catch the drift."""
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "1.0")
    run_id = "run-c15-agg-separation"

    store = open_store(tmp_data_dir)
    try:
        orchestrator, _, version = seed_run(
            store,
            submissions=("SYN-001",),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
                 "band_count": 2},
            ),
            run_id=run_id,
        )
        _declare_bands(store, version)
        seed_document(store, "SYN-001", PLAIN_TRANSCRIPT)
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        provider = make_fixture_provider()
        _drive_extract(orchestrator, store, provider, run_id)

        # The panel at rate 1.0: one base unit (the first arm) and two random_arm
        # units — verdicts B, B, A, so disagreement (not unanimity) is what the
        # relabel must be inert to.
        verdict_plan = {
            EDGE_JUDGE.build_id: ("B", 0.9),
            EDGE_JUDGE_2.build_id: ("B", 0.8),
            EDGE_JUDGE_3.build_id: ("A", 0.7),
        }
        rows = _score_unit_rows(store, run_id, "SYN-001")
        by_origin = {
            origin: [r for r in rows if r["origin"] == origin]
            for origin in ("base", "random_arm")
        }
        assert len(by_origin["base"]) == 1 and len(by_origin["random_arm"]) == 2, (
            f"fixture bug: rate 1.0 should seat 1 base + 2 arm units, got "
            f"{ {k: len(v) for k, v in by_origin.items()} }"
        )
        _score_all(orchestrator, store, provider, run_id,
                   lambda unit: verdict_plan[unit.judge])

        origins_before = {
            r["work_id"]: r["origin"] for r in _score_unit_rows(store, run_id)
        }

        # The M-AGG consumer's shape: read the ledger's verdicts for the pair,
        # aggregate through the shipped module. The arm's judge counts.
        criterion = agg_criterion(
            [agg_band("A", 0, 4.0), agg_band("B", 1, 2.0)],
            scoring_model="atomic",
            criterion_id="C1",
        )
        signals = favourable_signals()

        def _read_verdicts():
            return store.cohort(ORCH_COHORT_ID).query(
                "SELECT v.band, v.band_ordinal, v.self_confidence FROM verdict v "
                "JOIN work_unit w ON w.work_id = v.work_id "
                "WHERE w.run_id = :r AND w.submission_id = 'SYN-001' "
                "AND w.criterion_id = 'C1' ORDER BY v.work_id",
                r=run_id,
            )

        def _aggregate():
            ledger_rows = _read_verdicts()
            assert len(ledger_rows) == 3, (
                f"the consumer read {len(ledger_rows)} verdicts for a three-judge "
                "panel — the read is not over the pair's full panel"
            )
            panel = [
                agg_verdict(
                    r["band"], int(r["band_ordinal"]),
                    self_confidence=float(r["self_confidence"]),
                )
                for r in ledger_rows
            ]
            return agg_aggregate(panel, criterion, signals)

        first = _aggregate()
        assert first.judge_count == 3, (
            f"the aggregated panel counts {first.judge_count} judges — the arm "
            "judge's verdict must count (CT-ORCH-15's separation marks which "
            "population a verdict belongs to, never whether it counts)"
        )

        # The adversarial act: relabel the origins — base becomes arm, arm becomes
        # base — then re-run the identical consumer read. The verdicts themselves are
        # untouched: the relabel moves only the population mark.
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute(
                "UPDATE work_unit SET origin = CASE origin "
                "WHEN 'base' THEN 'random_arm' ELSE 'base' END "
                "WHERE run_id = :r AND submission_id = 'SYN-001' "
                "AND criterion_id = 'C1' AND stage = 'score'",
                r=run_id,
            )
        origins_after = {
            r["work_id"]: r["origin"] for r in _score_unit_rows(store, run_id)
        }
        assert origins_after != origins_before and set(origins_after.values()) == {
            "base", "random_arm",
        }, (
            "fixture bug: the relabel was a no-op or emptied a population — the "
            "differential below would assert nothing"
        )

        second = _aggregate()
        assert second.judge_count == 3, (
            f"after relabelling the origins the aggregation counts "
            f"{second.judge_count} judges — the consumer's read depends on "
            "work_unit.origin, which is a population mark, not an aggregation input "
            "(CT-ORCH-15: the consumers preserve the separation, they do not act on "
            "it)"
        )
        assert (
            first.band == second.band
            and first.ordinal == second.ordinal
            and first.points == second.points
            and first.modal_band == second.modal_band
            and first.band_spread == second.band_spread
            and first.judge_count == second.judge_count
            and first.agreement == second.agreement
            and first.agreement_degenerate == second.agreement_degenerate
            and first.histogram == second.histogram
        ), (
            f"relabelling origins changed the criterion score ({first} vs {second}) "
            "— M-AGG's aggregation reads the origin column and counts the random "
            "arm's verdicts differently from the base panel's: the separation "
            "RISK-07 depends on has leaked into the score"
        )
    finally:
        store.close()
