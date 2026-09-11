"""`TC-REVIEW-04` — ranking is a pure function of stored signals, and reproducible.

Test plan §5.15, `TC-REVIEW-04` (row form): *"Generated item sets, ranked twice. Ranking is a
pure function of stored signals and reproducible: rebuilding with unchanged data yields the same
order, including a declared deterministic tie-break. Oracle: Invariant."* Traces to
`NFR-REVIEW-02`. P0, rung 0 — no store, no console; the ranking read through
`ReviewService.rank_queue_items` (`FR-REVIEW-03`: the ranking separable from the budget) and
through the queue's own `shown` order.

What the property asserts, per generated set:

* **Reproducible** — two independent services over the same rows, and a second build on the
  same service, produce the identical order (the queue's grouping can collapse rows into
  `ReviewGroup` entries, so `shown` is compared entry-for-entry through a canonical key).
* **Pure** — the same seven declared inputs with a different `self_confidence` and different
  submission ids give the identical ranked order. `self_confidence` is stored but forbidden to
  drive ranking (`FR-REVIEW-03`); the submission id is no ranking input at all. The seed
  differs too: sampling is random, ranking is not.

The deterministic tie-break gets its own permutation property: over rows whose every ranking
input is identical, the ranked output is the input order itself — for *every* permutation, not
a sampled one, because a stable sort's tie behaviour is exactly "input order at full ties" and
the plan asks for the declared tie-break to be part of the reproducibility, not an accident.
The holistic-above-atomic class limb of the same sort key is TC-AGG-07's case
(`tests/unit/agg/test_review_queue_rank.py`); the `ScoreRow` fixture carries no `scoring_model`
column, so this suite pins the tie-break limb that reaches it.

Generation is coarse-quantized on purpose: floats at 32-bit precision essentially never tie, and
a property whose ties never occur asserts the easy 99% of the rule and misses the tie-break
entirely. Every quantized value is exactly representable at width 32.

**Fixed seed set**: the hypothesis profile is `derandomize=True` (conftest §4.6) — every run
replays the same example set.
"""

from __future__ import annotations

import dataclasses

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.support import broken_review_fixtures as broken
from tests.support.impl import REVIEW_MODULE, require

pytestmark = pytest.mark.property

FUZZ_EXAMPLES = 1000

CRITERIA_POOL = ("C-01", "C-02", "C-03")
BAND_POOL = ("B1", "B2", "B3", "B4")

# Coarse so ties occur: five spread levels x four signal counts x three overlap x three
# override x three weights x three deltas x three estimates x two flag tuples — a tie space
# dense enough that equal-EV collisions happen at the generated scale.
_SPREADS = (0.0, 0.25, 0.5, 0.75, 1.0)
_SIGNALS = (0, 1, 2, 3)
_OVERLAPS = (0.0, 0.5, 1.0)
_OVERRIDES = (0.0, 0.5, None, 1.0)
_WEIGHTS = (0.1, 0.4, 0.9)
_DELTAS = (0.0, 10.0, 20.0)
_ESTS = (30, 60, 120)
_FLAG_TUPLES = (
    (True, True, True, False),
    (False, True, False, True),
)
_CONFIDENCES = (0.3, 0.9)  # stored, declared-irrelevant: purity's differing field


def _row(row_id: int, spread, signals, overlap, override, weight, delta, est,
         criterion, band, flags, confidence):
    spans, evidence, sufficiency, ocr = flags
    return broken.ScoreRow(
        score_id=row_id,
        criterion_id=criterion,
        submission_id=f"sub-{row_id}",
        proposed_band=band,
        panel_spread=spread,
        adverse_integrity_signals=signals,
        transcription_overlap=overlap,
        historical_override_rate=override,
        criterion_weight=weight,
        grade_boundary_delta=delta,
        est_seconds=est,
        self_confidence=confidence,
        spans_verified=spans,
        evidence_present=evidence,
        sufficiency_flag=sufficiency,
        ocr_overlap_risk=ocr,
    )


_rows = st.lists(
    st.tuples(
        st.sampled_from(_SPREADS),
        st.integers(min_value=0, max_value=3),
        st.sampled_from(_OVERLAPS),
        st.sampled_from(_OVERRIDES),
        st.sampled_from(_WEIGHTS),
        st.sampled_from(_DELTAS),
        st.sampled_from(_ESTS),
        st.sampled_from(CRITERIA_POOL),
        st.sampled_from(BAND_POOL),
        st.sampled_from(_FLAG_TUPLES),
        st.sampled_from(_CONFIDENCES),
    ),
    min_size=2,
    max_size=8,
)


def _population(rows):
    return [
        _row(f"prop-{position}", *values)
        for position, values in enumerate(rows)
    ]


def _entries(queue):
    """A canonical, hashable form of a queue's shown entries — items and groups alike.

    A group has no `score_id` of its own; its identity is its members' ids and its aggregated
    value. Two builds whose only difference is an internal object identity must compare equal,
    so the key is built entirely from ids and figures.
    """
    form = []
    for entry in queue.shown:
        if hasattr(entry, "score_id"):
            form.append(("item", entry.score_id, round(entry.expected_value, 9)))
        else:
            form.append((
                "group",
                tuple(sorted(member.score_id for member in entry.members)),
                round(entry.expected_value, 9),
            ))
    return tuple(form)


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(rows=_rows)
def test_tc_review_04_ranking_is_reproducible_over_generated_item_sets(rows):
    """Rebuilding with unchanged data yields the same order — two services, and two builds.

    The comparison is over the full ranking (`rank_queue_items` — no budget truncation, so the
    order is the rule's own output) and over the queue's `shown` sequence, where the exact
    signature rule may group the generated rows: coarse flags and a three-criterion pool make
    shared signatures common, and the group form must reproduce as well as the item form.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    population = _population(rows)

    first = build_review(scores=population)
    second = build_review(scores=population)

    ranked_first = tuple(
        (item.score_id, round(item.expected_value, 9))
        for item in first.rank_queue_items(run_id="run-1")
    )
    ranked_second = tuple(
        (item.score_id, round(item.expected_value, 9))
        for item in second.rank_queue_items(run_id="run-1")
    )
    assert ranked_first == ranked_second, (
        "two services over identical rows ranked differently. NFR-REVIEW-02: ranking is a pure "
        "function of stored signals — a rebuild that reorders is a ranking that reads something "
        "outside the signals, and every agreement figure built on it is unstable."
    )
    assert len(ranked_first) == len(population), (
        "rank_queue_items did not return every admitted row, so reproducibility is being "
        "compared over a subset"
    )
    assert ranked_first[0][1] >= ranked_first[-1][1], (
        "the ranking is not best-first in expected value"
    )

    queue_first = _entries(first.build_queue(run_id="run-1", budget_minutes=30))
    queue_second = _entries(second.build_queue(run_id="run-1", budget_minutes=30))
    assert queue_first == queue_second, (
        "the queue's shown sequence did not reproduce over identical data. NFR-REVIEW-02 covers "
        "the queue, not only the ranking function — groups collapsing differently between two "
        "builds is the same defect at the surface the teacher sees."
    )


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(rows=_rows)
def test_tc_review_04_ranking_reads_only_the_declared_signals(rows):
    """The purity limb: forbidden and irrelevant fields do not move the order.

    Two populations identical on every declared ranking input, differing in `self_confidence`
    (stored, forbidden to drive ranking) and submission ids (not ranking inputs at all). The
    ranked id sequence must be identical — and so must the EV figures, since a ranking that
    reproduces the order while shifting the values behind it is not a pure function either.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    population = _population(rows)

    honest = build_review(scores=population)
    # The score_ids stay fixed: a different id would make the compared sequences differ by
    # name alone. What varies is exactly what the ranking must ignore.
    lured = build_review(
        scores=[
            dataclasses.replace(
                row,
                submission_id=f"lured-sub-{i}",
                self_confidence=0.1 if row.self_confidence >= 0.5 else 0.95,
            )
            for i, row in enumerate(population)
        ]
    )

    honest_ids = tuple(item.score_id for item in honest.rank_queue_items(run_id="run-1"))
    lured_ids = tuple(item.score_id for item in lured.rank_queue_items(run_id="run-1"))
    assert lured_ids == honest_ids, (
        "changing self_confidence moved the ranked order. FR-REVIEW-03: P(error) combines panel "
        "spread, integrity signals, transcription overlap and override history — not "
        "self-reported confidence, which is the teacher's guess rather than a stored signal."
    )

    honest_values = tuple(
        round(item.expected_value, 9) for item in honest.rank_queue_items(run_id="run-1")
    )
    lured_values = tuple(
        round(item.expected_value, 9) for item in lured.rank_queue_items(run_id="run-1")
    )
    assert lured_values == honest_values, (
        "the ranked order reproduced but the expected values behind it moved. NFR-REVIEW-02: a "
        "pure function's output is the value, not merely its relative position."
    )


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(permutation=st.permutations(range(6)))
def test_tc_review_04_full_ties_rank_in_input_order_for_every_permutation(permutation):
    """The declared deterministic tie-break, asserted exhaustively over input orders.

    Six rows whose every ranking input is identical (and whose distinct criteria keep the
    grouping signature from collapsing them) have one expected value between them, so the
    ranking carries no information that could distinguish them — the plan's tie-break clause is
    the sort's stability, and stability means the output order is the input order, whatever the
    input order is. A sort that breaks ties by anything undeclared (score id, dictionary
    insertion order, points) reorders at least one permutation of this set.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")

    tie_value = dict(
        panel_spread=0.2,
        adverse_integrity_signals=0,
        transcription_overlap=0.0,
        historical_override_rate=0.1,
        criterion_weight=0.2,
        grade_boundary_delta=0.0,
        est_seconds=60,
    )
    population = [
        broken.ScoreRow(
            score_id=f"tie-{position}",
            criterion_id=f"C-{position + 1:02d}",
            submission_id=f"tie-sub-{position}",
            **tie_value,
        )
        for position in permutation
    ]
    service = build_review(scores=population)

    ranked = [item.score_id for item in service.rank_queue_items(run_id="run-1")]
    expected = [f"tie-{position}" for position in permutation]
    assert ranked == expected, (
        f"identical-value rows ranked {ranked} against input order {expected}. The declared "
        "tie-break is input order at full ties — stable sort — and a tie-break by anything "
        "undeclared makes the order a function of something no stored signal states."
    )