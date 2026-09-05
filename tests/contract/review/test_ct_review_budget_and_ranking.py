"""`CT-REVIEW-01`, `-02`, `-03`, `-16`, `-19` — the budget, what fills it, and in what order.

Test plan §6.11.15, `TC-REVIEW-C01`, `-C02`, `-C03`, `-C16` and `-C19`. Five clauses about one
scarce resource: a teacher's stated minutes.

`CT-REVIEW-02` is the quiet one. The test plan flags it as *"the quiet one to watch"* and the
reason is worth restating: reserving the blind sample's minutes **after** ranking produces a full
queue and zero blind items on any over-subscribed run, nothing looks wrong on the screen, and the
system's only unbiased validity instrument silently stops collecting. RISK-13 arrives without
anybody choosing it. So `TC-REVIEW-C02` is written as an **event-order** assertion rather than an
arithmetic one — `reserved_for_blind_minutes` having the right value is satisfiable by a module
that computes it last.
"""

from __future__ import annotations

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import CONSOLE_MODULE, REVIEW_MODULE, require, require_attr

pytestmark = pytest.mark.contract


# --- CT-REVIEW-01 — sized by minutes, degrading honestly ---------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c01_queue_size_tracks_the_minute_budget_and_not_a_proportion():
    """*"Holding the flagged population constant and varying only the budget, then confirming the
    queue size tracks minutes rather than a proportion."*

    The differential is what discriminates. A queue sized at "the top 10%" also grows when the
    budget grows if somebody wires the percentage to the budget, so the assertion is not "more
    minutes, more items" — it is that the item count moves with **minutes** while the flagged
    population is fixed, and that doubling the budget does not double a *proportion* of a
    population that never changed.

    The second assertion is the one a percentage implementation fails: with the population held
    at 40 items, a proportional queue shows a count that is a fixed fraction of 40 regardless of
    minutes, so the three budgets would produce the same count.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    population = broken.flagged_population(40)
    service = build_review(scores=population)

    # Every budget here clears REVIEW_BLIND_RESERVE_MINUTES (10) with room to spare, so the
    # counts compared below are all counts of a queue that actually got built. See
    # `test_tc_review_c01_a_five_minute_budget_…` for the case where they do not.
    sizes = {
        minutes: len(service.build_queue(run_id="run-1", budget_minutes=minutes).shown)
        for minutes in (20, 40, 80)
    }

    assert len(set(sizes.values())) > 1, (
        f"the queue showed {sizes} — the same count at every budget over a fixed population of "
        "40. FR-REVIEW-01: the queue is sized by the teacher's minutes, so it cannot be a "
        "proportion of the flagged set."
    )
    assert sizes[20] < sizes[40] < sizes[80], (
        f"queue sizes {sizes} are not monotone in the budget. More stated minutes cannot buy "
        "fewer items."
    )


@pytest.mark.writtenahead
def test_tc_review_c01_a_five_minute_budget_shows_fewer_items_with_the_same_ranking_rule():
    """`NFR-REVIEW-05`'s honest degradation, and the half that is easy to get wrong.

    *"At 5 minutes assert fewer items and a larger stated residual, with the same ranking rule —
    a queue that switches heuristics under pressure is optimizing the appearance of coverage."*

    Three assertions, and the third is the clause's actual subject. Fewer items and a larger
    residual are arithmetic; the **ranking rule** staying the same is the property that stops a
    module from switching to "cheapest first" when minutes are short, which would fill the screen
    with quick wins and look like better coverage than it is.

    Asserted as a prefix relation rather than by reading `ranking_rule`: if the rule is unchanged,
    the short queue's items are the long queue's first items **in order**. A module that reorders
    under pressure fails this even if it reports the same rule name.

    **The plan's 5 minutes collides with §3.15's 10-minute blind reserve**, and the collision is
    asserted rather than dodged. `NFR-REVIEW-05` names 5 minutes; `REVIEW_BLIND_RESERVE_MINUTES`
    is 10, subtracted *before* ranking (`FR-REVIEW-02`), which leaves a 5-minute budget with
    nothing to spend. The design says what happens at neither. So the first assertion below
    requires a non-empty queue and says why: an implementation that returns zero items here
    satisfies "fewer items and a larger residual" **vacuously**, and this case would then pass
    while asserting nothing about the ranking rule — which is the half the clause is about.
    Reported as a finding on the PR.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(60))

    generous = service.build_queue(run_id="run-1", budget_minutes=30)
    squeezed = service.build_queue(
        run_id="run-1", budget_minutes=vocab.DEGRADED_BUDGET_MINUTES
    )

    assert len(squeezed.shown) > 0, (
        f"a {vocab.DEGRADED_BUDGET_MINUTES}-minute budget produced an empty queue. "
        f"REVIEW_BLIND_RESERVE_MINUTES is "
        f"{vocab.CONFIG_DEFAULTS['REVIEW_BLIND_RESERVE_MINUTES']} and FR-REVIEW-02 subtracts it "
        "first, so a budget below the reserve has nothing left — but NFR-REVIEW-05 still "
        "promises honest degradation at 5 minutes. The design settles neither; whichever way "
        "this is resolved, an empty queue makes the ranking-rule assertion below vacuous."
    )
    assert len(squeezed.shown) < len(generous.shown), (
        f"a {vocab.DEGRADED_BUDGET_MINUTES}-minute budget showed {len(squeezed.shown)} items "
        f"against {len(generous.shown)} at 30 minutes"
    )
    assert squeezed.residual_provisional > generous.residual_provisional, (
        "the squeezed queue did not state a larger residual. NFR-REVIEW-05: it degrades by "
        "showing less and saying so, never by quietly redefining what counts as covered."
    )

    short_ids = [item.score_id for item in squeezed.shown]
    long_ids = [item.score_id for item in generous.shown]
    assert short_ids == long_ids[: len(short_ids)], (
        f"the 5-minute queue is {short_ids}, which is not a prefix of the 30-minute queue "
        f"{long_ids[: len(short_ids) + 2]}…. The ranking rule changed under pressure — a queue "
        "that switches heuristics when minutes are short is optimizing the appearance of "
        "coverage (R12)."
    )


# --- CT-REVIEW-02 — the subtraction happens first ----------------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c02_blind_minutes_are_subtracted_before_any_ranking_occurs():
    """The **event-order** assertion, because *"the clause says the ordering is the contract"*.

    A trace, not arithmetic. `reserved_for_blind_minutes` carrying the right number is satisfiable
    by a module that ranks the whole flagged set against the full budget and then subtracts on the
    way out — which is exactly the defect, and it produces an identical header.

    So the assertion reads the build trace and requires the reservation event to precede the
    ranking event. This is the only form that discriminates; every value-based check on this
    clause passes the broken implementation.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.oversubscribed_population())

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    require_attr(queue, "build_trace", issue="#111")
    trace = [event.name for event in queue.build_trace]

    assert "reserve_blind_minutes" in trace, (
        f"the build trace {trace} records no reservation event. FR-REVIEW-02 makes the "
        "subtraction a step, and a step that is not in the trace cannot be shown to have "
        "happened first."
    )
    assert "rank_items" in trace, f"the build trace {trace} records no ranking event"
    assert trace.index("reserve_blind_minutes") < trace.index("rank_items"), (
        f"the build ranked before reserving: {trace}. FR-REVIEW-02 makes the ordering the "
        "contract — reserving afterwards lets a full queue crowd out the validation sample, "
        "which is the whole measurement."
    )


@pytest.mark.writtenahead
def test_tc_review_c02_the_blind_sample_survives_a_run_with_far_more_items_than_budget():
    """The discriminating fixture: *"a run with far more flagged items than budget, where
    reserve-after-ranking would produce a full queue and zero blind items."*

    800 flagged items against 30 minutes. The header assertion and the survival assertion are both
    here because they fail differently: a module that reserves last reports
    `reserved_for_blind_minutes = 10` and still hands back zero blind items, so the number alone
    would pass it.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.oversubscribed_population())
    require_attr(service, "blind_sample", issue="#111")

    budget = vocab.CONFIG_DEFAULTS["REVIEW_DEFAULT_BUDGET_MINUTES"]
    reserve = vocab.CONFIG_DEFAULTS["REVIEW_BLIND_RESERVE_MINUTES"]
    queue = service.build_queue(run_id="run-1", budget_minutes=budget)

    assert queue.reserved_for_blind_minutes == reserve, (
        f"the queue reserved {queue.reserved_for_blind_minutes} minutes for the blind sample "
        f"against REVIEW_BLIND_RESERVE_MINUTES = {reserve}. FR-REVIEW-02: the header states the "
        "subtraction."
    )

    # `blind_sample` draws independently of the queue, so its item count is the same under either
    # ordering and asserting it proves nothing — review caught that. What a reserve-after-ranking
    # implementation actually does is *spend* the reserved minutes on queue items: it ranks
    # against the full 30, fills, and reports a reservation it already gave away. So the
    # assertion is that the minutes are still there.
    available_seconds = (budget - reserve) * 60
    spent = sum(item.est_seconds for item in queue.shown)
    assert spent <= available_seconds, (
        f"the queue filled {spent}s against the {available_seconds}s left after reserving "
        f"{reserve} minutes for the blind sample. On an over-subscribed run this is exactly what "
        "reserving *after* ranking looks like: a full queue, a header that still says "
        f"{reserve}, and no minutes left for the measurement. Nothing on the screen looks wrong."
    )


# --- CT-REVIEW-03 — expected value, and what may not drive it ----------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("signal", vocab.ERROR_PROBABILITY_SIGNALS)
def test_tc_review_c03_ranking_responds_to_each_error_probability_signal_alone(signal):
    """*"By varying each alone and asserting the order responds."*

    Parametrized so a failure names the signal the ranking ignores. A combined test would report
    "ranking did not respond" for a module reading three of the four, and the fourth is the one
    that matters — `historical_override_rate` is the signal a first implementation is likeliest to
    leave for later, and it is the one that carries the criterion's actual track record.

    The construction holds every other field of the row identical and moves one, so a ranking that
    happens to correlate the signal with something else cannot pass by accident.
    """
    import dataclasses

    build_review = require(REVIEW_MODULE, "build_review", issue="#108")

    baseline = broken.ScoreRow(score_id="probe", **{signal: _low(signal)})
    raised = dataclasses.replace(baseline, score_id="probe", **{signal: _high(signal)})
    others = broken.flagged_population(20)

    low_rank = _rank_of(build_review, others, baseline)
    high_rank = _rank_of(build_review, others, raised)

    assert high_rank < low_rank, (
        f"raising {signal} from {_low(signal)!r} to {_high(signal)!r} moved the item from rank "
        f"{low_rank} to {high_rank} — it did not rise. FR-REVIEW-03 names four inputs to "
        f"P(score wrong) and this is one of them; a ranking that ignores it is ranking on the "
        "other three."
    )


@pytest.mark.writtenahead
def test_tc_review_c03_the_order_does_not_move_when_only_self_confidence_changes():
    """The prohibition: *"hold the observables fixed, sweep self-confidence, assert the order is
    unchanged."*

    `FR-REVIEW-03` says P(error) combines four observable signals, *"not self-reported confidence
    alone"*, and `CT-JUDGE-07` says the same from the other side. The sweep is the only form that
    catches the plausible defect, which is not "ranking uses self-confidence instead" but "ranking
    uses it as a tiebreaker nobody documented" — and a tiebreaker moves the order.
    """
    import dataclasses

    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    population = broken.flagged_population(24)

    orders = []
    for confidence in (0.1, 0.5, 0.9):
        swept = [
            dataclasses.replace(row, self_confidence=confidence) for row in population
        ]
        queue = build_review(scores=swept).build_queue(run_id="run-1", budget_minutes=30)
        orders.append([item.score_id for item in queue.shown])

    assert orders[0] == orders[1] == orders[2], (
        "the queue order moved when only self_confidence changed. FR-REVIEW-03: P(score wrong) "
        "combines panel spread, integrity signals, transcription overlap and override history — "
        "not self-reported confidence, which is the judge grading its own certainty (R22)."
    )


@pytest.mark.writtenahead
def test_tc_review_c03_rebuilding_with_unchanged_data_yields_an_identical_order():
    """`NFR-REVIEW-02` — *"a queue that reshuffles between sittings cannot be reasoned about or
    tested."*

    Three builds rather than two. Two builds catch a ranking seeded from the clock; three catch
    one seeded from a counter that happens to produce the same order on the second call, which is
    the shape a cached-then-invalidated implementation takes.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(40))

    orders = [
        [item.score_id for item in
         service.build_queue(run_id="run-1", budget_minutes=30).shown]
        for _ in range(3)
    ]

    assert orders[0] == orders[1] == orders[2], (
        "rebuilding the queue with unchanged data produced different orders. NFR-REVIEW-02 makes "
        "ranking a pure function of stored signals, because a teacher who leaves and comes back "
        "must find the same queue."
    )


@pytest.mark.writtenahead
def test_tc_review_c03_the_ranking_score_is_expected_value_per_estimated_second():
    """The formula itself: `(P(score wrong) × impact) / est_seconds`.

    The three sensitivity tests above establish that ranking responds to the right inputs; none of
    them establishes the **shape**. A ranking that adds `est_seconds` as a penalty term instead of
    dividing by it passes every one of them and mis-orders exactly where the clause cares: two
    items of equal expected value and different cost.

    So the construction is two rows with identical P and impact and a 4× difference in
    `est_seconds`, which under the stated formula puts the cheap one first by a factor of four —
    and under any additive alternative puts them adjacent.
    """
    import dataclasses

    build_review = require(REVIEW_MODULE, "build_review", issue="#108")

    cheap = broken.ScoreRow(score_id="cheap", est_seconds=30)
    dear = dataclasses.replace(cheap, score_id="dear", est_seconds=120)
    service = build_review(scores=[cheap, dear])

    scores = service.rank_queue_items(run_id="run-1")
    by_id = {entry.score_id: entry.expected_value for entry in scores}

    assert by_id["dear"] > 0, (
        f"every expected value is {by_id['dear']!r}, so the ratio below is 0 == approx(0) and "
        "passes for a ranker that scores nothing"
    )
    assert by_id["cheap"] == pytest.approx(by_id["dear"] * 4, rel=0.01), (
        f"equal-value items costing 30s and 120s scored {by_id['cheap']} and {by_id['dear']}. "
        "FR-REVIEW-03 divides expected value by estimated seconds, so a 4× cost difference is a "
        "4× score difference — an additive cost penalty gets the order right and the arithmetic "
        "wrong, and mis-orders as soon as the two terms are close."
    )


# --- CT-REVIEW-16 — the build is fast, and it is not billed to the teacher ---------------------


@pytest.mark.writtenahead
@pytest.mark.slow
def test_tc_review_c16_the_queue_builds_within_two_seconds_at_the_stated_load():
    """`NFR-REVIEW-01`'s threshold at `NFR-REVIEW-01`'s load: 350 students, ~800 flagged items.

    The clause states its own reason and this case preserves it: the queue is opened at the start
    of a fixed time budget, so *"every second spent building is a second not spent reviewing"*.

    Marked `slow` as well as `writtenahead` — it constructs the full stated load, and §4.6 keeps
    load cases out of the fast tier.
    """
    import time

    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(
        scores=broken.flagged_population(vocab.PERF_FLAGGED_ITEMS, criteria=8)
    )

    started = time.perf_counter()
    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    elapsed = time.perf_counter() - started

    assert queue.flagged_total == vocab.PERF_FLAGGED_ITEMS, (
        f"the fixture presented {queue.flagged_total} flagged items rather than "
        f"{vocab.PERF_FLAGGED_ITEMS}, so this is not the stated load"
    )
    assert elapsed < vocab.QUEUE_BUILD_SECONDS, (
        f"the queue took {elapsed:.2f}s to build at {vocab.PERF_STUDENTS} students and "
        f"{vocab.PERF_FLAGGED_ITEMS} flagged items, against NFR-REVIEW-01's "
        f"{vocab.QUEUE_BUILD_SECONDS}s."
    )


@pytest.mark.writtenahead
def test_tc_review_c16_build_time_is_excluded_from_the_teachers_minute_budget():
    """*"Assert build time is excluded from the teacher's minute budget rather than silently
    consuming it."*

    The half of the clause a timing test does not cover, and the one with a real failure mode: a
    queue that bills its own build to the budget hands the teacher fewer minutes than they asked
    for and reports the number they asked for. Two seconds is small; a slow run is not, and this
    is the accounting that decides which one the teacher pays for.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(
        scores=broken.flagged_population(vocab.PERF_FLAGGED_ITEMS, criteria=8)
    )

    budget = 30
    queue = service.build_queue(run_id="run-1", budget_minutes=budget)

    assert queue.budget_minutes == budget, (
        f"the queue reports a budget of {queue.budget_minutes} against the {budget} the teacher "
        "stated"
    )
    assert isinstance(getattr(queue, "build_seconds", None), (int, float)), (
        "the queue does not report its own build time, so CT-REVIEW-16's accounting cannot be "
        "checked from stored data. (An earlier draft wrote this as "
        "`getattr(queue, 'build_seconds', 0) >= 0`, which is true of every implementation "
        "including the one with no such field — review caught it.)"
    )

    available_seconds = (queue.budget_minutes - queue.reserved_for_blind_minutes) * 60
    shown_seconds = sum(item.est_seconds for item in queue.shown)

    assert shown_seconds <= available_seconds, (
        f"the queue filled {shown_seconds}s against {available_seconds}s available after the "
        "blind reservation, so it is spending minutes the teacher did not offer"
    )
    # The direction that detects billing. A queue that charged its own build to the budget
    # under-fills, and reports the full number it was given — so the header check above cannot
    # see it. `est_seconds` is at most 190 in this fixture, so a queue that stopped more than one
    # item short of the pool left time on the table that something else consumed.
    largest = max(item.est_seconds for item in queue.shown)
    assert shown_seconds > available_seconds - largest - int(queue.build_seconds), (
        f"the queue filled only {shown_seconds}s of {available_seconds}s and reported a build "
        f"time of {queue.build_seconds}s. CT-REVIEW-16: every second spent building is a second "
        "not spent reviewing, and it is not the teacher who should pay for it."
    )


# --- CT-REVIEW-19 — the non-promise about est_seconds ------------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c19_the_queue_still_degrades_honestly_when_est_seconds_is_badly_wrong():
    """*"Run with `est_seconds` deliberately wrong by a large factor and assert the queue still
    functions and degrades honestly — ranking still reproducible, residual still stated
    correctly."*

    A non-promise case, so the assertion is that nothing *else* breaks. `FR-REVIEW-16` is Phase 2:
    the estimate is uncalibrated today, and a queue whose reproducibility or residual arithmetic
    depended on the estimate being roughly right would be making a promise the design withholds.
    """
    import dataclasses

    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    population = broken.flagged_population(40)
    distorted = [
        dataclasses.replace(row, est_seconds=row.est_seconds * vocab.EST_SECONDS_DISTORTION_FACTOR)
        for row in population
    ]
    service = build_review(scores=distorted)

    first = service.build_queue(run_id="run-1", budget_minutes=30)
    second = service.build_queue(run_id="run-1", budget_minutes=30)

    assert [i.score_id for i in first.shown] == [i.score_id for i in second.shown], (
        f"ranking stopped being reproducible once est_seconds was {vocab.EST_SECONDS_DISTORTION_FACTOR}× "
        "wrong. NFR-REVIEW-02 is a property of the stored signals, not of the estimate's accuracy."
    )
    assert first.flagged_total == len(distorted), (
        f"the queue reported {first.flagged_total} flagged against {len(distorted)} — the "
        "residual arithmetic moved with the estimate"
    )
    assert first.residual_provisional == first.flagged_total - vocab.items_shown(first), (
        "the stated residual no longer accounts for every flagged item that was not shown"
    )


@pytest.mark.writtenahead
def test_tc_review_c19_the_console_does_not_present_the_budget_as_a_guarantee_of_elapsed_time():
    """The consumer obligation, over rendered language: *"a consumer must not present the budget
    as a guarantee of elapsed time."*

    Keyed on `M-CONSOLE` (#124) rather than `M-REVIEW`, because the language is the console's.
    `budget_guarantee_language` is controlled in both directions in the vocabulary suite: it stays
    silent on *"30 minutes, estimated"* and fires on *"this will take 20 minutes"*.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    render_review_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")

    # Rendered from a real queue, so the caption under test exists. A sweep over an empty page
    # finds no forbidden language and passes for any console.
    service = build_review(scores=broken.flagged_population(200))
    rendering = render_review_queue(service, run_id="run-1", budget_minutes=30)
    assert str(service.build_queue(run_id="run-1", budget_minutes=30).budget_minutes) in rendering, (
        "the rendering does not state the budget, so there is no budget language here to sweep"
    )
    promises = vocab.budget_guarantee_language(rendering)

    assert promises == [], (
        f"the queue screen says {promises}. CT-REVIEW-19: `est_seconds` is uncalibrated at "
        "Phase 1, so the budget is a plan, not a guarantee of elapsed time."
    )


@pytest.mark.writtenahead
def test_tc_review_c19_both_calibration_inputs_are_stored_so_phase_2_has_a_path():
    """*"Assert the Phase 2 path exists: calibration against observed `review_seconds` is possible
    from stored data, since `CT-REVIEW-18` records both."*

    The half that makes this a non-promise rather than a limitation. A clause saying "uncalibrated
    at Phase 1" is only honest if Phase 2 is reachable without a migration, and that means both
    sides of the comparison have to be in the store today.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(12))
    require_attr(service, "label", issue="#110")
    require_attr(service, "observability_counters", issue="#110")

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    item = queue.shown[0]
    label_id = service.act(item, action="accept", new_band=None, review_seconds=95)
    label = service.label(label_id)

    assert label.review_seconds == 95, (
        "the observed review time was not stored on the label, so there is nothing to calibrate "
        "the estimate against"
    )
    assert item.est_seconds is not None, (
        "the item carries no est_seconds, so the estimate side of the comparison is missing"
    )
    counters = service.observability_counters(run_id="run-1")
    missing = [name for name in vocab.CALIBRATION_INPUTS
               if not any(name in counter for counter in counters)]
    assert missing == [], (
        f"the observability surface records neither side of {missing}. CT-REVIEW-19's Phase 2 "
        "path runs through CT-REVIEW-18's stored pair; without both, calibration needs a "
        "migration rather than a query."
    )


# --- helpers -----------------------------------------------------------------------------------


def _low(signal: str) -> float | int:
    """The quiet end of each `FR-REVIEW-03` signal, in that signal's own units."""
    return {
        "panel_spread": 0.0,
        "adverse_integrity_signals": 0,
        "transcription_overlap": 0.0,
        "historical_override_rate": 0.0,
    }[signal]


def _high(signal: str) -> float | int:
    """The loud end. Large enough that a ranking reading the signal at all must move the item."""
    return {
        "panel_spread": 0.9,
        "adverse_integrity_signals": 3,
        "transcription_overlap": 0.9,
        "historical_override_rate": 0.9,
    }[signal]


def _rank_of(build_review, population, probe) -> int:
    """Where `probe` lands in a queue built over `population` plus itself.

    The queue is built with a budget generous enough to show everything, so the probe's rank is
    always defined — a probe that fell outside a truncated queue would make the comparison read
    "did not move" when it moved further than the test could see.
    """
    queue = build_review(scores=[*population, probe]).build_queue(
        run_id="run-1", budget_minutes=600
    )
    ids = [item.score_id for item in queue.shown]
    assert probe.score_id in ids, (
        f"the probe {probe.score_id!r} was not shown in a 600-minute queue over "
        f"{len(population) + 1} items, so its rank cannot be compared"
    )
    return ids.index(probe.score_id)
