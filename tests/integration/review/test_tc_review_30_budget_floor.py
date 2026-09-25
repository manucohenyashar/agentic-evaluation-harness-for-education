"""`TS-89` (issue #383) — `TC-REVIEW-30`: the blind reserve, the floor of one, and the
ordering invariant (`FR-REVIEW-02`, `NFR-REVIEW-05` as amended by D-1).

Reserve 5 minutes; an identical flagged population of 20 items at 45 s each.

| Budget | Reserve | Ranked minutes | Shown | Residual |
|---|---|---|---|---|
| 60 | 5 | 55 | **all 20** (73 would fit, only 20 exist) | 0 |
| 5 | 5 | 0 | **1** (the floor) | 19 |
| 4 | 4 (the min) | 0 | 1 | 19 |
| 0.5 | 0.5 | 0 | 1 | 19 |

Plus: the ranking **order** of the shown prefix is identical at every budget, and the header
states the subtraction.

**The floor of one is what keeps a degraded queue honest.** With the reserve equal to or
larger than the budget there is nothing left to rank, and the arithmetically correct answer is
to show nothing. D-1 shows one item instead — the top-ranked one — and states the other 19 in
the residual. A queue that showed nothing would be indistinguishable from a run with no
flagged work at all, and the teacher would close a screen that had silently given up.

**The reserve is `min(reserve, budget)`, which is why budget 4 reserves 4 and not 5.** A
reserve larger than the budget would make `budget - reserve` negative; clamping it at the
budget is what keeps the subtraction the header states arithmetically true.

**The ordering invariant is the assertion that catches a plausible wrong fix.** An
implementation that met the floor by showing "whatever happens to be cheapest" would satisfy
every count in the table and quietly reorder the queue — the teacher's one remaining minute
would go to the least valuable item rather than the most. `NFR-REVIEW-05` says the fill never
reorders, so the first shown item is the same at every budget.

**Grouping is deliberately kept out of the way.** `_group_identical` collapses rows with
identical signatures into one entry, and a group counts its members. The fixture gives each
row a distinct band so no group forms and the counts are about the budget rather than about
grouping — which is `TC-REVIEW-08`'s subject.

**Isolation: rung 2** — a real store, a real run, `open_review` over the stored rows.
"""

from __future__ import annotations

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.review import REVIEW_EST_SECONDS_ATOMIC, open_review
from aeh.store import open_store
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

#: The plan's reserve for this case, passed explicitly — the module's own default is 10.
RESERVE_MINUTES = 5

#: The plan's population: 20 items, each an atomic criterion at 45 s.
ITEMS = 20
EST_SECONDS = REVIEW_EST_SECONDS_ATOMIC  # 45.0

CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)
SUBMISSIONS = tuple(f"S{index:03d}" for index in range(1, ITEMS + 1))


@pytest.fixture
def budget_world(tmp_data_dir):
    """20 queued rows over one run, each with a distinct band so no signature group forms."""
    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=SUBMISSIONS, criteria=CRITERIA)
        write_criterion_scores(
            store.cohort(ORCH_COHORT_ID),
            [
                (submission, "C1", f"B{index:03d}", 6.0, "provisional")
                for index, submission in enumerate(SUBMISSIONS, start=1)
            ],
        )
    finally:
        store.close()

    def _service():
        return open_review(
            tmp_data_dir,
            run_id=ORCH_COHORT_ID,
            review_blind_reserve_minutes=RESERVE_MINUTES,
        )

    return _service


def _queue(service_factory, budget):
    return service_factory().build_queue(ORCH_COHORT_ID, budget, record=False)


def _shown_items(queue) -> int:
    total = 0
    for entry in queue.shown:
        members = getattr(entry, "members", None)
        total += len(members) if members is not None else 1
    return total


# --- TC-REVIEW-30 ---------------------------------------------------------------------------


def test_tc_review_30_the_population_is_the_one_the_table_describes(budget_world):
    """The fixture's own precondition: 20 flagged items at 45 s each, ungrouped.

    Asserted first because every row of the table is arithmetic over these two numbers. A
    fixture that produced 19 items, or grouped them into one entry, would make the whole
    sweep pass or fail for reasons that have nothing to do with the budget.
    """
    queue = _queue(budget_world, 60)

    assert queue.flagged_total == ITEMS, (
        f"the run holds {queue.flagged_total} flagged rows, not {ITEMS}"
    )
    assert len(queue.shown) == _shown_items(queue) == ITEMS, (
        f"{len(queue.shown)} entries cover {_shown_items(queue)} items; the bands are "
        "distinct so no signature group should form (grouping is TC-REVIEW-08's subject)"
    )
    assert {entry.est_seconds for entry in queue.shown} == {EST_SECONDS}, (
        f"the items are estimated at {sorted({e.est_seconds for e in queue.shown})}s, not "
        f"{EST_SECONDS}s — an atomic criterion's declared figure"
    )


def test_tc_review_30_a_generous_budget_shows_every_item_with_no_residual(budget_world):
    """Budget 60 → reserve 5, 55 ranked minutes, all 20 shown, residual 0.

    55 minutes fits 73 items at 45 s; only 20 exist. The queue shows what there is rather than
    what would fit, and the residual is 0 rather than a negative number.
    """
    queue = _queue(budget_world, 60)

    assert queue.reserved_for_blind_minutes == RESERVE_MINUTES
    assert _shown_items(queue) == ITEMS, (
        f"{_shown_items(queue)} of {ITEMS} items shown against 55 spendable minutes, which "
        "fits 73"
    )
    assert queue.residual_provisional == 0, (
        f"residual is {queue.residual_provisional}; every flagged item was shown"
    )


@pytest.mark.parametrize("budget,expected_reserve", ((5, 5), (4, 4), (0.5, 0.5)))
def test_tc_review_30_a_budget_at_or_below_the_reserve_still_shows_one_item(
    budget_world, budget, expected_reserve
):
    """Budgets 5, 4 and 0.5 → nothing left to rank, and the floor shows exactly one.

    All three rows of the table in one parametrization, because they differ only in which of
    `budget` and `reserve` the `min` picks. The residual states the other 19 — that is what
    makes the degradation honest rather than silent.
    """
    queue = _queue(budget_world, budget)

    assert queue.reserved_for_blind_minutes == expected_reserve, (
        f"budget {budget} reserved {queue.reserved_for_blind_minutes}, not "
        f"{expected_reserve}; the reserve is min(reserve, budget) so the subtraction the "
        "header states stays arithmetically true"
    )
    assert _shown_items(queue) == 1, (
        f"budget {budget} showed {_shown_items(queue)} items. With no spendable minutes the "
        "arithmetic says zero and D-1 says one: a queue that showed nothing is "
        "indistinguishable from a run with no flagged work, and the teacher closes a screen "
        "that silently gave up"
    )
    assert queue.residual_provisional == ITEMS - 1, (
        f"residual is {queue.residual_provisional}, not {ITEMS - 1}; the floor is honest only "
        "because the items it could not show are stated"
    )


def test_tc_review_30_the_shown_prefix_is_in_the_same_order_at_every_budget(budget_world):
    """The ordering invariant — the first shown item is the same at 60, 5, 4 and 0.5.

    The assertion that catches the plausible wrong fix. An implementation meeting the floor by
    showing the *cheapest* remaining item, or by re-ranking once the budget ran out, satisfies
    every count above and spends the teacher's last minute on the least valuable item in the
    queue. `NFR-REVIEW-05`: the fill takes what fits in rank order and never reorders.
    """
    firsts = {}
    for budget in (60, 5, 4, 0.5):
        queue = _queue(budget_world, budget)
        entry = queue.shown[0]
        members = getattr(entry, "members", None)
        firsts[budget] = (
            members[0].score_id if members else getattr(entry, "score_id", None)
        )

    assert len(set(firsts.values())) == 1, (
        f"the top shown item differs by budget: {firsts}. The fill takes a prefix of the "
        "ranking, so shrinking the budget may show fewer items but never different ones"
    )

    generous = [
        getattr(entry, "score_id", None) for entry in _queue(budget_world, 60).shown
    ]
    assert generous[0] == next(iter(firsts.values())), (
        "the floor's single item is not the generous budget's first — the prefix property "
        "does not hold"
    )


def test_tc_review_30_the_header_states_the_subtraction(budget_world):
    """The build trace names the reserve and what is left, so the arithmetic is auditable.

    `CT-REVIEW-02` makes stage order contractual: the reserve is subtracted **before** anything
    is ranked, and the trace says so. A queue that showed one item with no explanation reads as
    a bug; one that says "5 of 5 minutes reserved, 0s spendable" reads as a policy.
    """
    queue = _queue(budget_world, 5)

    events = {event.name: event.detail for event in queue.build_trace}
    assert "reserve_blind_minutes" in events, (
        f"the build trace has no reserve stage: {sorted(events)}"
    )
    detail = events["reserve_blind_minutes"]
    assert "5" in detail and ("0s" in detail or "0 " in detail), (
        f"the reserve stage does not state the subtraction: {detail!r}"
    )

    stages = [event.name for event in queue.build_trace]
    assert stages.index("reserve_blind_minutes") < stages.index("rank_items"), (
        f"the reserve is subtracted after ranking: {stages}. CT-REVIEW-02 makes the order "
        "contractual — ranking a budget the blind sample will later eat produces a queue "
        "whose header was never true"
    )
