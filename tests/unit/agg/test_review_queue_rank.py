"""`TC-AGG-07` — the review-queue rank limb: holistic ranks higher at equal expected value.

Test plan §5.12 (row form), issue #95 (TS-36). Traces to `FR-AGG-06`. Its own file
because its blocker is not `aeh.agg`: at equal expected value the ordering is the
review queue's to produce, and the queue is `M-REVIEW`'s (`aeh.review:
rank_queue_items`, #108 — the name the `#108 stats` consumer entry already pins). The
ceiling limb of the same case lives in `test_routing_and_escalation.py`.

**Declared reading of FR-AGG-06**: the holistic criterion's *distinction* comes from
the package (CT-AGG-09 — no consumer special-cases at run time), and what the queue
must honour is the tie-break: two items at the same expected value, differing only in
`scoring_model`, order holistic-first. A consumer that ignores `scoring_model` in its
tie-break fails here.

**Assumed interface of #108** (the `#108 review` entry's ranking tests drive the same
surface): `rank_queue_items(items) -> sequence`, ordered best-first; each item carries
`.expected_value` and `.scoring_model`. Reconciles at #108's landing.

Isolation: rung 0 — a pure ranking function over stand-in items; the socket guard is
autouse.
"""

from __future__ import annotations

from tests.support.impl import REVIEW_MODULE, require


def test_tc_agg_07_holistic_ranks_higher_than_atomic_at_equal_expected_value():
    """`TC-AGG-07` rank limb (`FR-AGG-06`, unit / rung 0, exact comparison, P0) — two
    review-queue items at the SAME expected value, differing only in scoring model:
    the holistic item ranks higher (earlier)."""
    rank_queue_items = require(REVIEW_MODULE, "rank_queue_items", issue="#108")

    atomic_item = SimpleNamespaceItem(expected_value=0.75, scoring_model="atomic")
    holistic_item = SimpleNamespaceItem(expected_value=0.75, scoring_model="holistic")

    order = list(rank_queue_items([atomic_item, holistic_item]))
    assert order[0] is holistic_item, (
        f"at equal expected value the queue ordered {[i.scoring_model for i in order]} "
        "— the holistic criterion must rank higher than the atomic one (FR-AGG-06: "
        "'shall rank higher in the review queue at equal expected value')"
    )


def test_tc_agg_07_expected_value_still_dominates_the_rank():
    """`TC-AGG-07` rank limb, negative control (`FR-AGG-06`, unit / rung 0, P0) — the
    tie-break is a tie-break: an atomic item with strictly higher expected value ranks
    above a holistic one. Without this limb, a queue that sorts holistic-first would
    satisfy the other test while breaking the ranking's reason to exist."""
    rank_queue_items = require(REVIEW_MODULE, "rank_queue_items", issue="#108")

    atomic_item = SimpleNamespaceItem(expected_value=0.90, scoring_model="atomic")
    holistic_item = SimpleNamespaceItem(expected_value=0.50, scoring_model="holistic")

    order = list(rank_queue_items([holistic_item, atomic_item]))
    assert order[0] is atomic_item, (
        f"expected value {atomic_item.expected_value} ranked below "
        f"{holistic_item.expected_value} — the scoring-model tie-break applies at "
        "equal expected value only (FR-AGG-06; the queue ranks by expected value)"
    )


class SimpleNamespaceItem:
    """A review-queue item stand-in: the two fields the ranking reads."""

    def __init__(self, expected_value: float, scoring_model: str):
        self.expected_value = expected_value
        self.scoring_model = scoring_model
