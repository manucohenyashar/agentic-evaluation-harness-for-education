"""`TC-AGG-C05` — the confidence inversion: integrity caps, never weighted penalties.

Test plan §6.11.12's block case — the design's *"single most important test in this
module"* (CT-AGG-05, ADR-10, RISK-01), a §4.7 safety property. The shipped sibling
`tests/unit/agg/test_confidence_inversion.py` (`TC-AGG-06`, #92) carries steps 1, 2's
sweep, 4 and the exact distinctive injected caps: the single named assertion, the
64-cell cap sweep with a nominal-metric / penalty-term negative control, the
fail-closed `None` cells, and the recorded-inputs assertion.

This file carries what no sibling runs:

- **the case's named adversarial construction** (the Oracle/Adversarial block): a
  weighted-combination implementation *defined here in the test* — the cap read as a
  prior whose force is scaled by panel unanimity ("dissent already discounts the
  figure, so the cap need not bind twice"), a reasonable-sounding weighting — shown
  to **pass the step-1 exact-value check** (its three-unanimous-adverse figure lands
  exactly at the cap, routing `queued`) while **failing the step-2 cap invariant** on
  a well-chosen cell. That pair is the discriminating proof the case table demands:
  it is why the sweep is the real case and the single assertion is not — the
  construction passes the one and fails the other, exactly as the table says ("a
  weighted implementation passes step 1 for a well-chosen weight and fails this
  sweep").
- **step 3 at the limit**: perfect agreement, maximal self-confidence, every judge
  citing — with `spans_verified = false` — still capped, never `auto`.
- **the rung-3 consequence**: the same inversion through a real store — a real
  judged panel (the `_drive` run's verdict rows, read back from the ledger),
  aggregated with the adverse signal a hallucinated span produces, inserted into
  `criterion_score`, read back `queued`. The hallucinated span never becomes a final
  auto-accepted grade even at the storage boundary the consumers read.
- **the rung-4 consequence** (`writtenahead`): the hallucinated span with a unanimous
  panel reaches `M-REVIEW`'s review queue rather than the student's transcript —
  blocked on `aeh.review:build_review` (#108), registered in
  `WRITTEN_AHEAD_BLOCKERS` under `"#96 c05 the inversion's rung-4 consequence
  (M-REVIEW)"`.

A name disclosure: the issue's automatable path is
`tests/contract/agg/test_confidence_inversion.py`; the shipped sibling already holds
`tests/unit/agg/test_confidence_inversion.py` (TC-AGG-06), and two files with one
basename collide at collection under the repo's prepend import mode. The contract file
carries the suite's `test_ct_agg_*` convention instead, same case ID.

Isolation: rung 0 for the policy, rung 2-3 for the store consequence; the socket
guard is autouse.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from aeh.store import open_store
from tests.contract.agg._drive import (
    criterion_bands,
    drive_scored_run,
    stored_verdicts,
)
from tests.support.agg_vocabulary import (
    DESIGN_CAPS,
    FAVOURABLE,
    agg_config,
    band,
    criterion,
    panel,
    signals,
    verdict,
)
from tests.support.impl import AGG_MODULE, REVIEW_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))
_SPLIT = panel(("B0", 0), ("B1", 1), ("B1", 1), ("B1", 1), ("B2", 2))  # α = 0.52

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C05"
_CRITERION = "C1"

_INSERT = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing, confidence, confidence_base, "
    "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
    "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, "
    ":routing, :confidence, :confidence_base, :spans_verified, "
    ":evidence_present, :sufficiency_flag, :ocr_overlap_risk)"
)


def _caps(config, name):
    """The cap table in force for `name` — the injected one when a config rides."""
    if config is not None and getattr(config, "caps", None):
        return config.caps[name]
    return DESIGN_CAPS[name]


def _weighted_combination(aggregate):
    """The adversarial construction the case names, in code.

    §3.12's computation is `min(base, every adverse cap)` — a cap is a hard
    ceiling. The construction instead reads each cap as a PRIOR whose force is
    scaled by the panel's dissent — "dissent already discounts the figure, so the
    cap need not bind twice; restore the discount's share of the prior":
    `confidence = min(base, cap) + (1 − α) · (1 − cap)`. On the step-1 cell (three
    unanimous, spans adverse, α = 1) the weight is 0 and it produces exactly the
    capped figure 0.25 — the single assertion passes. On a well-chosen cell of the
    step-2 sweep — the split panel, α = 0.52, whose capped figure is the same 0.25 —
    it restores 0.48 · 0.75 ≈ 0.36 and lands at ≈ 0.61, above the cap, which the
    invariant `confidence ≤ cap` forbids. That is the weighted-penalty defect
    CT-AGG-05 exists to forbid, wearing a reasonable face.
    """
    def weighted(verdicts, crit, sig, *, config=None):
        score = aggregate(verdicts, crit, sig, config=config)
        alpha = score.agreement if score.agreement is not None else 1.0
        confidence = score.confidence if score.confidence is not None else 1.0
        for name, favourable in FAVOURABLE.items():
            value = getattr(sig, name, None)
            if value is not None and value is favourable:
                continue
            cap = _caps(config, name)
            # The reasonable-sounding part: consensus-graded enforcement.
            confidence = min(confidence, cap) + (1.0 - alpha) * (1.0 - cap)
        return replace(score, confidence=min(confidence, 1.0))
    return weighted


def test_tc_agg_c05_the_single_named_assertion():
    """`TC-AGG-C05` step 1 (`CT-AGG-05`, `FR-AGG-05`, unit / rung 0, exact value,
    P0) — three unanimous verdicts with `spans_verified = false`: confidence at or
    below the cap, routing `queued`, never `auto`. The design's single assertion,
    executed here so the contract case carries it (the release-gate REG-CT-AGG-05
    reads the sibling's identical assertion too)."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#92")

    score = aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(spans_verified=False),
                      config=agg_config())

    cap = agg_config().caps["spans_verified"]
    assert score.confidence is not None and score.confidence <= cap, (
        f"three unanimous verdicts with a failed span check scored "
        f"{score.confidence!r} — at or below the {cap!r} cap (ADR-10: unanimity "
        "cannot outrun a failed span check)"
    )
    assert score.routing == "queued", (
        f"the unanimous adverse result routed {score.routing!r} — a capped result "
        "is routed to the teacher, never auto-accepted (CT-AGG-05)"
    )


def test_tc_agg_c05_the_adversarial_weighted_construction_fails_the_cap_invariant():
    """`TC-AGG-C05` step 2's construction (`CT-AGG-05`, ADR-10, unit / rung 0,
    adversarial discriminating pair, P0) — the weighted combination defined above
    PASSES the step-1 exact-value check (its unanimous-adverse figure is exactly the
    capped one) and FAILS the cap invariant on the split panel: proof that the
    property sweep is the discriminating oracle and the single assertion is not.
    The clause lives because this construction is *reasonable-sounding*."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#92")

    weighted = _weighted_combination(aggregate)

    # Step 1 against the weighted combination: the unanimous-adverse cell.
    unanimous = weighted(_UNANIMOUS_TOP, _FOUR_BAND, signals(spans_verified=False),
                         config=agg_config())
    cap = agg_config().caps["spans_verified"]
    passes_step_1 = unanimous.confidence <= cap and unanimous.routing == "queued"

    # Step 2's invariant, on a cell the construction was built to break: the split
    # panel's base sits above the cap only through unanimity's weight; the weighted
    # form restores part of the cap and lands above it.
    split = weighted(_SPLIT, _FOUR_BAND, signals(spans_verified=False),
                     config=agg_config())

    assert passes_step_1, (
        "fixture bug: the weighted construction does not pass the step-1 "
        "exact-value check, so the discriminating pair below proves nothing"
    )
    assert split.confidence > cap, (
        "fixture bug: the weighted construction stayed under the cap on the split "
        "cell — it does not model the weighted-combination defect and cannot "
        "discriminate"
    )
    # The real policy fails NEITHER: the shipped min cannot be clawed back.
    real = aggregate(_SPLIT, _FOUR_BAND, signals(spans_verified=False),
                     config=agg_config())
    assert real.confidence <= cap, (
        f"the shipped policy scored {real.confidence!r} above the adverse cap — "
        "the inversion (ADR-10) does not hold"
    )


def test_tc_agg_c05_unanimity_at_the_limit_still_routes():
    """`TC-AGG-C05` step 3 (`CT-AGG-05`, unit / rung 0, invariant at the limit,
    P0) — perfect agreement, maximal self-confidence, every judge citing — with
    `spans_verified = false`: still capped, never `auto`. The limit cell of the
    step-2 invariant."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#92")

    score = aggregate(
        [verdict("B3", 3), verdict("B3", 3), verdict("B3", 3)],
        _FOUR_BAND, signals(spans_verified=False), config=agg_config(),
    )

    assert score.confidence <= agg_config().caps["spans_verified"], (
        f"a maximally-consensual panel scored {score.confidence!r} — the cap holds "
        "at the limit (ADR-10)"
    )
    assert score.routing != "auto", (
        f"the limit cell routed {score.routing!r} — the most convincing panel the "
        "system can produce, with one failed span check, is still the teacher's "
        "(CT-AGG-05's single assertion at its extreme)"
    )


def test_tc_agg_c05_a_missing_signal_is_treated_as_adverse():
    """`TC-AGG-C05` step 4 (`CT-AGG-05` × `CT-INTEG-03`, unit / rung 0, P0) — a
    missing integrity signal is treated as adverse, not as unknown-therefore-fine:
    the consuming half of the fail-closed guarantee."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#92")

    score = aggregate(_UNANIMOUS_TOP, _FOUR_BAND,
                      signals(spans_verified=None), config=agg_config())

    assert score.confidence <= agg_config().caps["spans_verified"], (
        f"a not-measured span check scored {score.confidence!r} — fail-closed: "
        "`None` is adverse, never unknown-therefore-fine (CT-AGG-05 step 4)"
    )
    assert score.routing != "auto", (
        f"the not-measured cell routed {score.routing!r} — an unmeasured signal "
        "must not buy an auto-accept"
    )


def test_tc_agg_c05_the_inversion_through_a_real_store_stays_queued(
    tmp_data_dir, make_fixture_provider
):
    """`TC-AGG-C05` rung 3 (`CT-AGG-05`, contract / rung 2-3, P0) — the inversion
    through a real judged panel: the drive's verdict rows read back from the
    ledger, aggregated with the adverse signal a hallucinated span produces,
    inserted into a real `criterion_score` row and read back `queued`. The
    storage boundary the consumers read carries the routing, not a repaired one."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#92")

    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        # A `holistic` criterion: the shipped enumeration's base depth for it is
        # 3 (`FR-SETUP-08`), so the drive judges a real three-judge panel.
        _, run_id, _ = drive_scored_run(
            store, provider, submissions=(_SUBMISSION,),
            criterion_specs=[{"criterion_id": _CRITERION, "kind": "open",
                              "scoring_model": "holistic", "band_count": 2}],
        )
        rows = stored_verdicts(store, run_id, _SUBMISSION, _CRITERION)
        assert len(rows) == 3, (
            "precondition: the drive did not judge a three-judge panel, so the "
            "unanimity claim below would be vacuous"
        )
        crit = criterion(criterion_bands(store, _CRITERION),
                         criterion_id=_CRITERION, scoring_model="holistic")

        # The signals M-INTEG would report for a hallucinated span: the span check
        # fails (the span's bytes do not match the transcript), everything else
        # favourable — supplied at this seam because the drive's fixture span is the
        # recorded one; the adverse polarity is what the clause names, whatever
        # measured it.
        score = aggregate(rows, crit, signals(spans_verified=False),
                          config=agg_config())
        assert score.confidence <= agg_config().caps["spans_verified"], (
            f"a real unanimous panel with a failed span check scored "
            f"{score.confidence!r} — the inversion holds on real stored verdicts "
            "(CT-AGG-05)"
        )
        assert score.routing == "queued", (
            f"the real panel routed {score.routing!r} — the hallucinated span's "
            "unanimous verdict reaches the review queue, never the student's "
            "transcript as final (CT-AGG-05's consequence)"
        )

        cohort = store.cohort(_COHORT)
        with cohort.transaction() as tx:
            tx.execute(
                _INSERT,
                sid=_SUBMISSION, cid=_CRITERION, band=score.band, points=score.points,
                judge_count=score.judge_count, agreement=score.agreement,
                state=score.state, routing=score.routing, confidence=score.confidence,
                confidence_base=score.confidence_base,
                spans_verified=score.spans_verified,
                evidence_present=score.evidence_present,
                sufficiency_flag=score.sufficiency_flag,
                ocr_overlap_risk=score.ocr_overlap_risk,
            )
        stored = cohort.query(
            "SELECT routing, state, confidence FROM criterion_score "
            "WHERE submission_id = :s AND criterion_id = :c",
            s=_SUBMISSION, c=_CRITERION,
        )
        assert stored[0]["routing"] == "queued", (
            "the stored row lost the queued routing — the review queue (which reads "
            "the stored rows) would never see the hallucinated panel"
        )
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_agg_c05_a_hallucinated_span_with_a_unanimous_panel_reaches_the_review_queue(
    tmp_data_dir, make_fixture_provider
):
    """`TC-AGG-C05` step 5, rung 4 (`CT-AGG-05`, contract / rung 4, writtenahead
    on `aeh.review:build_review`, #108) — the consequence end to end: a
    hallucinated span with a unanimous panel reaches the REVIEW QUEUE rather than
    the student's transcript. The aggregate half is executable above at rung 3;
    this limb drives the consumer the clause names — M-REVIEW's queue holds the
    item, keyed by the (submission, criterion) pair the score row records."""
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    aggregate = require(AGG_MODULE, "aggregate", issue="#92")

    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        # A `holistic` criterion: the shipped enumeration's base depth for it is
        # 3 (`FR-SETUP-08`), so the drive judges a real three-judge panel.
        _, run_id, _ = drive_scored_run(
            store, provider, submissions=(_SUBMISSION,),
            criterion_specs=[{"criterion_id": _CRITERION, "kind": "open",
                              "scoring_model": "holistic", "band_count": 2}],
        )
        rows = stored_verdicts(store, run_id, _SUBMISSION, _CRITERION)
        crit = criterion(criterion_bands(store, _CRITERION),
                         criterion_id=_CRITERION, scoring_model="holistic")
        score = aggregate(rows, crit, signals(spans_verified=False),
                          config=agg_config())
        assert score.routing == "queued", (
            "the unanimous adverse panel did not route to the teacher's queue"
        )

        review = build_review(store)
        queue = review.queue()
        pairs = set()
        for item in queue:
            if isinstance(item, dict):
                pairs.add((item.get("submission_id"), item.get("criterion_id")))
            else:
                pairs.add((getattr(item, "submission_id", None),
                           getattr(item, "criterion_id", None)))
        assert (_SUBMISSION, _CRITERION) in pairs, (
            f"the hallucinated span's unanimous panel is absent from the review "
            f"queue {queue!r} — the inversion's consequence failed end to end"
        )
    finally:
        store.close()
