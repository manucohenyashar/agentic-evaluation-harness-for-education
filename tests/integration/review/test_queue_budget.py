"""`TC-REVIEW-01` — the blind reservation is subtracted before ranking, and the residual is stated.

Test plan §5.15 (full-block form), issue #112 (TS-40). Traces to `FR-REVIEW-01`, `FR-REVIEW-02`,
`FR-REVIEW-04`, `NFR-REVIEW-05`. The plan pins this file's path, the load (a run with 790 flagged
items and `REVIEW_BLIND_RESERVE_MINUTES = 10`) and the budgets swept (5, 10, 30, 120).

The C-clause suite (`tests/contract/review/test_ct_review_budget_and_ranking.py`) already holds the
clause-level limbs at the fast tier: `CT-REVIEW-C01`'s budget monotonicity and 5-minute
same-ranking rule, `CT-REVIEW-C02`'s event-order trace assertion and reserve survival, `CT-REVIEW-C04`'s
residual triple. This file implements the **case** at its pinned shape, which none of those carry:

* the pinned 790-item load, with a fixture built so *"drawn from a 20-minute budget"* and
  *"not truncated from a 30-minute ranking"* are two **different** sets — the discriminator the
  computation-order sentence asks for;
* the budget sweep at the plan's own four budgets, with the sum invariant and the same-rule
  invariant asserted at every one of them;
* the variant — a budget smaller than the blind reservation itself — asserted, as the plan
  demands, rather than left to whatever the implementation does;
* the API enumeration: the queue is never sized by a percentage or a bare confidence threshold.

**Disclosed isolation split.** The plan marks the case rung 2. The store carries none of
`FR-REVIEW-03`'s seven ranking inputs (the module's own disclosed reading since #301), so the
signal-controlled discriminator runs at rung 0 over rows that carry the inputs, and the rung-2
limb below asserts the header, the sweep and the residual arithmetic over a real store — the
budget mechanics, which are what this case is about, do not depend on the ranking being
informed. Budgets 5 and 10 both leave zero spendable seconds (5 < 10 caps the reserve at 5;
10 − 10 = 0), so the sweep's monotonicity assertions run over the budgets whose spendable
windows actually differ.

**Isolation:** rung 0 for the discriminator limbs (pure in-memory rows, no egress); rung 2 for
`test_tc_review_01_..._store_backed` (real store, real cohort ledger, no model).
"""

from __future__ import annotations

import inspect

import pytest

from aeh.store import open_store
from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.impl import CONSOLE_MODULE, REVIEW_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

#: §5.15's fixture figure: 790 flagged items against `REVIEW_BLIND_RESERVE_MINUTES = 10`.
PINNED_FLAGGED_ITEMS = 790
PINNED_RESERVE_MINUTES = vocab.CONFIG_DEFAULTS["REVIEW_BLIND_RESERVE_MINUTES"]
SWEEP_BUDGETS = (5, 10, 30, 120)

#: The expensive sentinel's estimate, chosen so it fits a 30-minute ranking's full window
#: (30 × 60 = 1800s) but **not** the post-reservation one ((30 − 10) × 60 = 1200s). That
#: single fact is what makes "drawn from 20 minutes" and "truncated from 30" provably
#: different sets — see `test_tc_review_01_..._not_truncated`.
EXPENSIVE_EST_SECONDS = 1300


def _pinned_load() -> list[broken.ScoreRow]:
    """The plan's 790 flagged items, built so the ranking order is known by construction.

    One expensive item whose signals are all maxed — P(error) 4.0, impact 1.0 — against 789
    cheap items whose signals are all near-floor. Under `FR-REVIEW-03`'s equal weights the
    expensive item's expected value (4.0 / 1300 ≈ 0.0031) tops every cheap item's
    (0.02 / 30 ≈ 0.0007), so it heads the ranked order despite costing 43× as much to review:
    exactly the item a fill that truncates a 30-minute ranking would show and a 20-minute
    budget cannot afford.

    The 789 cheap rows share their ranking inputs but not their `CT-REVIEW-20` signature —
    band and integrity flags are a bijection from the row's index within its criterion, the
    same construction `flagged_population` uses — so nothing groups and the budget arithmetic
    below is about the case's subject, not about grouping.
    """
    expensive = broken.ScoreRow(
        score_id="score-expensive",
        criterion_id="C-99",
        submission_id="sub-expensive",
        proposed_band="B7",
        panel_spread=1.0,
        adverse_integrity_signals=3,
        transcription_overlap=1.0,
        historical_override_rate=1.0,
        criterion_weight=1.0,
        grade_boundary_delta=0.0,
        est_seconds=EXPENSIVE_EST_SECONDS,
    )
    cheap = [
        broken.ScoreRow(
            score_id=f"score-{i}",
            criterion_id=f"C-{(i % 13) + 1:02d}",
            submission_id=f"sub-{i}",
            proposed_band=f"B{(i // 13 % 4) + 1}",
            panel_spread=0.02,
            adverse_integrity_signals=0,
            transcription_overlap=0.0,
            historical_override_rate=0.0,
            criterion_weight=1.0,
            grade_boundary_delta=0.0,
            est_seconds=30,
            spans_verified=bool((i // 52) & 1),
            evidence_present=bool((i // 52) & 2),
            sufficiency_flag=bool((i // 52) & 4),
            ocr_overlap_risk=bool((i // 52) & 8),
        )
        for i in range(PINNED_FLAGGED_ITEMS - 1)
    ]
    return [expensive, *cheap]


def _walk(entries, available_seconds: float) -> list:
    """The declared fill rule, transcribed independently of the module (`NFR-REVIEW-05`'s
    recorded reading): walk the entries in rank order, take every one that fits, pass over
    one that does not, never reorder — and over a non-empty population never show nothing,
    falling back to the single top entry when nothing fits.

    Transcribed rather than called so the assertion is against the rule the design states,
    not against the module's own helper — the two agreeing is the finding.
    """
    shown: list = []
    spent = 0.0
    for entry in entries:
        if spent + entry.est_seconds <= available_seconds:
            shown.append(entry)
            spent += entry.est_seconds
    if not shown and entries:
        shown.append(entries[0])
    return shown


def _spendable(minutes: int, reserve: int) -> int:
    return max(minutes - reserve, 0) * 60


# --- steps 1-3: computation order, the header, and the three figures ---------------------------


def test_tc_review_01_the_ranked_set_is_drawn_from_the_20_remaining_minutes_not_truncated():
    """Step 1, at the plan's fixture: *"'asserted on the computation order, by checking that
    the ranked set is drawn from a 20-minute budget and not truncated from a 30-minute
    ranking.'"*

    The event-order trace assertion that pins the *ordering* is `CT-REVIEW-C02`'s; this test
    pins the **arithmetic** the ordering produces, which needs the two candidate sets to
    differ — which the fixture arranges:

    The expensive item heads the ranking (its expected value per second is the population's
    highest) but cannot fit the 1200s left after the reservation. A queue drawn from the
    20-minute budget skips it and fills 40 cheap items; a queue that ranked against the full
    30 minutes and then cut would show it — either dropping the cheap tail (and over-spending
    the post-reservation budget) or dropping the expensive item (and leaving cheap items the
    20-minute walk *does* show unfilled). The shown set below matches the first shape
    exactly, which is the assertion that the reserve was subtracted **before** ranking.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=_pinned_load())
    queue = service.build_queue(run_id="run-1", budget_minutes=30)

    ranked = service.rank_queue_items(run_id="run-1")
    assert ranked[0].score_id == "score-expensive", (
        "the fixture's expensive item does not head the ranked order, so the truncation "
        "discriminator below asserts nothing — the fixture is broken, not the queue"
    )

    expected = _walk(ranked, _spendable(30, queue.reserved_for_blind_minutes))
    shown_ids = [entry.score_id for entry in queue.shown]
    assert shown_ids == [entry.score_id for entry in expected], (
        f"the 30-minute queue showed {len(shown_ids)} entries that do not match the greedy "
        "fill of its own ranked order within the "
        f"{_spendable(30, queue.reserved_for_blind_minutes)}s left after reserving "
        f"{queue.reserved_for_blind_minutes} minutes. FR-REVIEW-02: the blind reservation is "
        "subtracted before any ranking occurs, so what is shown is what fits the "
        "*post-reservation* budget — not a 30-minute ranking cut down after the fact."
    )
    assert "score-expensive" not in shown_ids, (
        "the queue showed the 1300s item inside a 20-minute budget. FR-REVIEW-02: a ranked set "
        "truncated from a 30-minute ranking shows exactly this item — ranked first on expected "
        "value, taken by the 30-minute fill, too expensive for the minutes that remain."
    )
    spent = sum(entry.est_seconds for entry in queue.shown)
    assert spent <= _spendable(30, PINNED_RESERVE_MINUTES), (
        f"the queue filled {spent}s against the "
        f"{_spendable(30, PINNED_RESERVE_MINUTES)}s left after reserving "
        f"{PINNED_RESERVE_MINUTES} minutes — the reserved minutes were spent on queue items"
    )
    # The two candidate sets really do differ under this fixture, so the equality above is a
    # discriminator and not a coincidence of arithmetic: the 30-minute fill contains the
    # expensive item, the shown set does not.
    thirty_minute_fill = _walk(ranked, _spendable(30, 0))
    assert "score-expensive" in [entry.score_id for entry in thirty_minute_fill], (
        "the 30-minute fill of the ranked order does not contain the expensive item, so "
        "'drawn from 20 minutes' and 'truncated from 30' coincide and this case can no longer "
        "tell them apart"
    )


def test_tc_review_01_the_header_states_the_subtraction_and_all_three_figures():
    """Steps 2-3 at the pinned load: the header carries the reservation, and the three
    figures — flagged, shown, left provisional — reconcile.

    The consumer half is asserted on the rendered page: the residual figures by the
    vocabulary's number-matching rule (`unstated_residual`, `CT-REVIEW-C04`'s rule at this
    case's load) and the subtraction by the reservation figures themselves, which the page's
    build-trace section carries — a header that said "10 minutes reserved" while ranking
    against 30 would satisfy a word-matching rule and fail the arithmetic.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    render_review_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")
    service = build_review(scores=_pinned_load())

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    assert queue.budget_minutes == 30 and queue.reserved_for_blind_minutes == 10, (
        f"the header reports budget {queue.budget_minutes} and reserve "
        f"{queue.reserved_for_blind_minutes}. FR-REVIEW-02: the header states the subtraction — "
        "the reserve figure beside the budget it was taken from."
    )
    assert queue.flagged_total == PINNED_FLAGGED_ITEMS, (
        f"the queue reported {queue.flagged_total} flagged against the plan's "
        f"{PINNED_FLAGGED_ITEMS}-item fixture"
    )
    covered = vocab.items_shown(queue)
    assert 0 < covered < queue.flagged_total, (
        "the fixture is over-subscribed — a queue that shows everything or nothing asserts "
        "no residual arithmetic"
    )
    assert queue.residual_provisional == queue.flagged_total - covered, (
        f"{queue.flagged_total} flagged, {covered} covered, {queue.residual_provisional} "
        "residual — the three figures do not reconcile. FR-REVIEW-04: what is flagged minus "
        "what is shown IS the residual; three numbers that do not sum tell the teacher nothing."
    )

    rendering = render_review_queue(service, run_id="run-1", budget_minutes=30)
    assert vocab.unstated_residual(rendering, queue) == [], (
        f"the rendered queue does not state {vocab.unstated_residual(rendering, queue)}. "
        "FR-REVIEW-04, at this case's pinned load: all three figures are rendered or the "
        "clause is broken."
    )
    stated = f"{PINNED_RESERVE_MINUTES} of 30 minutes reserved"
    assert stated in rendering.html, (
        f"the rendered queue never states the reservation ({stated!r} absent). FR-REVIEW-02: "
        "the header states the subtraction — a teacher looking at a 30-minute budget is owed "
        "the fact that 10 of those minutes were never theirs to spend."
    )


# --- step 4: the sweep — same rule, fewer items, larger residual --------------------------------


def test_tc_review_01_at_every_budget_the_same_rule_shows_fewer_and_states_more():
    """Step 4, at the plan's budgets: *"Rebuild at 5, 10, 30 and 120 minutes ... at every
    budget the same ranking rule with fewer items and a larger stated residual — never a
    different rule (`NFR-REVIEW-05`)."*

    The same-rule invariant is asserted against the ranked order itself, not against the
    queues: each budget's shown set must be the greedy fill of the **one** ranked order at
    that budget's spendable seconds. A queue that switched heuristics under pressure would
    fill a differently-ordered list and fail the walk equality even with the counts right.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=_pinned_load())
    ranked = service.rank_queue_items(run_id="run-1")
    ranked_ids = [entry.score_id for entry in ranked]

    observed: dict[int, tuple[int, int, int]] = {}
    for minutes in SWEEP_BUDGETS:
        queue = service.build_queue(run_id="run-1", budget_minutes=minutes)
        reserve = min(PINNED_RESERVE_MINUTES, minutes)
        assert [entry.score_id for entry in service.rank_queue_items(run_id="run-1")] == (
            ranked_ids
        ), f"the ranked order itself moved between the {minutes}-minute builds"

        expected = _walk(ranked, _spendable(minutes, reserve))
        assert [entry.score_id for entry in queue.shown] == [
            entry.score_id for entry in expected
        ], (
            f"at {minutes} minutes the queue showed a set that is not the fill of the ranked "
            "order at that budget's spendable seconds. NFR-REVIEW-05: every budget applies the "
            "same ranking rule and shows less — a queue that reorders under pressure is "
            "optimizing the appearance of coverage (R12)."
        )
        assert queue.reserved_for_blind_minutes == reserve, (
            f"at {minutes} minutes the header reserved {queue.reserved_for_blind_minutes} "
            f"minutes. FR-REVIEW-02 states the reserve as min(10, budget) at every budget, and "
            "the header states it however small the budget is."
        )
        assert queue.residual_provisional == queue.flagged_total - vocab.items_shown(queue), (
            f"at {minutes} minutes the three figures do not reconcile: {queue.flagged_total} "
            f"flagged, {vocab.items_shown(queue)} shown, {queue.residual_provisional} residual."
        )
        observed[minutes] = (
            len(queue.shown), queue.residual_provisional, vocab.items_shown(queue),
        )

    covered = {minutes: figures[2] for minutes, figures in observed.items()}
    residuals = {minutes: figures[1] for minutes, figures in observed.items()}
    assert covered[5] <= covered[10] <= covered[30] <= covered[120], (
        f"items shown across the sweep are not monotone in the budget: {covered}. More stated "
        "minutes cannot buy fewer items."
    )
    assert residuals[5] >= residuals[10] >= residuals[30] >= residuals[120], (
        f"the stated residual is not monotone in the budget: {residuals}. NFR-REVIEW-05: it "
        "degrades by showing less and saying so — a larger budget owes a smaller residual."
    )
    assert covered[30] > covered[10] and covered[120] > covered[30], (
        f"the sweep produced the same coverage at larger budgets: {covered}. A queue sized by "
        "a proportion of the flagged set shows the same count at 30 and at 120 minutes."
    )


def test_tc_review_01_a_budget_smaller_than_the_reservation_degrades_to_the_top_entry():
    """The variant, asserted as the plan demands: *"a budget smaller than the blind
    reservation itself — the declared behaviour must be asserted, not left to the
    implementation."*

    The declared reading, recorded since #301 and kept unchanged by #111: the reserve is
    `min(REVIEW_BLIND_RESERVE_MINUTES, budget)` and the queue never shows nothing over a
    non-empty admitted population — the floor of one. At 5 minutes the reserve takes the
    whole budget, the ranking has nothing to spend, and the queue shows the single top entry
    while stating a residual of 789: the degradation the design wants is *visible*, not
    silent.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=_pinned_load())

    queue = service.build_queue(run_id="run-1", budget_minutes=vocab.DEGRADED_BUDGET_MINUTES)
    ranked = service.rank_queue_items(run_id="run-1")

    assert queue.reserved_for_blind_minutes == vocab.DEGRADED_BUDGET_MINUTES, (
        f"at a {vocab.DEGRADED_BUDGET_MINUTES}-minute budget the header reserved "
        f"{queue.reserved_for_blind_minutes} minutes. The reserve is min(10, budget): a "
        "reservation larger than the budget it is subtracted from is not a reservation, it is "
        "a fiction."
    )
    assert [entry.score_id for entry in queue.shown] == [ranked[0].score_id], (
        "a budget below the reserve did not degrade to the single top entry. The queue never "
        "shows nothing over a non-empty population (the recorded floor-of-one reading) — "
        "an empty queue would make the residual below vacuously 790 while showing nothing."
    )
    assert queue.residual_provisional == queue.flagged_total - vocab.items_shown(queue), (
        "the floor-of-one queue's figures do not reconcile"
    )
    assert queue.residual_provisional == PINNED_FLAGGED_ITEMS - 1, (
        f"the residual states {queue.residual_provisional} against "
        f"{PINNED_FLAGGED_ITEMS} flagged and one item shown. NFR-REVIEW-05's 5-minute "
        "degradation is a large, honestly stated residual — not a quiet redefinition of "
        "coverage."
    )


# --- step 5: the API enumeration ----------------------------------------------------------------


def test_tc_review_01_no_api_parameter_sizes_the_queue_by_a_share_or_a_threshold():
    """Step 5: *"Assert the queue is never sized by a fixed percentage or a bare confidence
    threshold — enumerate the API and confirm no such parameter exists."*

    Enumerated rather than sampled, for the reason the clause gives: the loophole is a
    parameter added later — `top_n=` beside `budget_minutes=` — which no behaviour test
    would reach until somebody called it. The sweep covers `build_queue`'s signature, the
    queue's own fields, and every public callable the service exposes.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(20))
    queue = service.build_queue(run_id="run-1", budget_minutes=30)

    forbidden = (*vocab.PERCENTAGE_SIZING_NAMES, "threshold", "confidence")
    sized_by = sorted(
        f"{owner}:{name}"
        for owner, names in (
            ("build_queue", list(inspect.signature(service.build_queue).parameters)),
            ("ReviewQueue", list(type(queue).__dataclass_fields__)),
            (
                "ReviewService",
                [
                    name
                    for name in dir(service)
                    if not name.startswith("_") and callable(getattr(service, name))
                ],
            ),
        )
        for name in names
        if any(rule in name.lower() for rule in forbidden)
    )
    assert sized_by == [], (
        f"the queue-sizing API carries {sized_by}. FR-REVIEW-01: the queue is sized by a minute "
        f"budget and never by {vocab.FORBIDDEN_SIZING_RULES} — a percentage survives every "
        "budget change and a bare threshold hides the ranking entirely."
    )


# --- the rung-2 limb ----------------------------------------------------------------------------


def test_tc_review_01_the_store_backed_queue_carries_the_same_header_and_sweep(tmp_data_dir):
    """The plan's rung-2 isolation limb, over a real store: the same header, the same sum
    invariant, the same sweep.

    **Disclosed at the load:** the store's `criterion_score` carries none of `FR-REVIEW-03`'s
    seven inputs, so every admitted row scores expected value 0.0 and the ranking is the
    store's row order — the module's own disclosed reading, recorded at #301 and kept here.
    That does not blunt the case: the reservation, the header, the fill and the residual are
    arithmetic over the ranked order whatever informs it, and the sweep asserts them at the
    plan's four budgets over the real store path the production queue reads.
    """
    open_review = require(REVIEW_MODULE, "open_review", issue="#111")

    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store,
            submissions=tuple(f"S{i:03d}" for i in range(1, PINNED_FLAGGED_ITEMS + 1)),
            criteria=({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},),
        )
        cohort = store.cohort(ORCH_COHORT_ID)
        # The stand-in seeds `provisional` rather than `queued` — the disclosed mapping
        # (`ROUTING_TO_STATE`) derives `provisional_unreviewed` from it, and both routings
        # are the review queue's admitted population (`_ADVISORY_ROUTINGS`). Bands are
        # distinct per row so the exact-signature grouping rule forms no group here: this
        # case's subject is the budget arithmetic, and grouping at scale is TC-REVIEW-08's
        # own case.
        write_criterion_scores(
            cohort,
            [
                (f"S{i:03d}", "C1", f"B{i:03d}", 6.0, "provisional")
                for i in range(1, PINNED_FLAGGED_ITEMS + 1)
            ],
        )
        service = open_review(tmp_data_dir, run_id=ORCH_COHORT_ID)
    finally:
        store.close()

    try:
        ranked = service.rank_queue_items(run_id=ORCH_COHORT_ID)
        assert len(ranked) == PINNED_FLAGGED_ITEMS, (
            f"the store-backed service ranked {len(ranked)} rows against a cohort of "
            f"{PINNED_FLAGGED_ITEMS} queued scores — the rung-2 read missed rows"
        )

        covered: dict[int, int] = {}
        residuals: dict[int, int] = {}
        for minutes in SWEEP_BUDGETS:
            queue = service.build_queue(run_id=ORCH_COHORT_ID, budget_minutes=minutes)
            reserve = min(PINNED_RESERVE_MINUTES, minutes)
            assert queue.reserved_for_blind_minutes == reserve, (
                f"the store-backed queue reserved {queue.reserved_for_blind_minutes} minutes "
                f"at a {minutes}-minute budget"
            )
            expected = _walk(ranked, _spendable(minutes, reserve))
            assert [entry.score_id for entry in queue.shown] == [
                entry.score_id for entry in expected
            ], (
                f"at {minutes} minutes the store-backed queue is not the fill of its ranked "
                "order — the rung-2 build diverges from the declared fill rule"
            )
            assert queue.residual_provisional == queue.flagged_total - vocab.items_shown(queue), (
                f"at {minutes} minutes the store-backed queue's three figures do not reconcile"
            )
            covered[minutes] = vocab.items_shown(queue)
            residuals[minutes] = queue.residual_provisional

        assert covered[5] <= covered[10] <= covered[30] <= covered[120], (
            f"the store-backed sweep is not monotone in the budget: {covered}"
        )
        assert residuals[5] >= residuals[10] >= residuals[30] >= residuals[120], (
            f"the store-backed residual is not monotone in the budget: {residuals}"
        )
        assert covered[30] > covered[10] and covered[120] > covered[30], (
            f"the store-backed sweep produced the same coverage at larger budgets: {covered}"
        )
    finally:
        service.close()