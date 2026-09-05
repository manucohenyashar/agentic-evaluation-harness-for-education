"""`CT-REVIEW-04`, `-05`, `-06` — what the queue admits, what it states, and what it writes.

Test plan §6.11.15, `TC-REVIEW-C04`, `-C05` and `-C06`. Three clauses that between them fix the
queue's population, its header and its write set.

`CT-REVIEW-05` is a **reachability** clause, not an absence clause, and the difference decides
what the case is allowed to assert. *"As a reachability property over the queue's actual queries
rather than an observed absence"* — because an observed absence is a statement about one fixture:
build a queue over a population containing no random-arm units and it passes without the module
excluding anything.
"""

from __future__ import annotations

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import CONSOLE_MODULE, REVIEW_MODULE, require, require_attr

pytestmark = pytest.mark.contract


# --- CT-REVIEW-04 — the residual triple, and the obligation to render it -----------------------


@pytest.mark.writtenahead
def test_tc_review_c04_the_queue_states_all_three_figures_and_they_are_arithmetically_consistent():
    """*"Assert `ReviewQueue` states all three of `flagged_total`, `shown` and
    `residual_provisional`, and that they are arithmetically consistent."*

    The arithmetic is what makes the three a triple rather than three numbers. `flagged_total`
    minus what was shown **is** the residual: a queue reporting 812 flagged, 3 shown and 40
    provisional has stated three figures and told the teacher nothing true, and that is the
    likelier defect than a missing field — the residual arrives from a different query and drifts.

    The fixture is deliberately over-subscribed so all three figures are distinct. Over a
    population the budget covers entirely, `flagged_total == len(shown)` and
    `residual_provisional == 0`, and the arithmetic holds for a module that computes none of it.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    population = broken.flagged_population(200)
    queue = build_review(scores=population).build_queue(run_id="run-1", budget_minutes=30)

    missing = [f for f in vocab.RESIDUAL_TRIPLE if getattr(queue, f, None) is None]
    assert missing == [], (
        f"ReviewQueue does not state {missing}. CT-REVIEW-04 names three figures and the "
        "consumer must render all three."
    )

    assert queue.flagged_total == len(population), (
        f"the queue reported {queue.flagged_total} flagged against a population of "
        f"{len(population)} queued rows"
    )
    # Items, not entries. §3.15 types `shown` as `Sequence[ReviewItem | ReviewGroup]`, so a
    # queue presenting 200 items as 16 groups shows 16 entries and covers 200 items — and this
    # clause's arithmetic is about the second number. `len(shown)` would demand a residual of 184
    # from a correct queue with nothing left over.
    covered = vocab.items_shown(queue)
    assert 0 < covered < queue.flagged_total, (
        f"{covered} of {queue.flagged_total} shown — the fixture is not over-subscribed, so the "
        "arithmetic below holds trivially"
    )
    assert queue.residual_provisional == queue.flagged_total - covered, (
        f"{queue.flagged_total} flagged, {covered} covered by what is shown, "
        f"{queue.residual_provisional} residual. The three do not reconcile, so at least one of "
        "them is describing a different population than the teacher is looking at."
    )


@pytest.mark.writtenahead
def test_tc_review_c04_the_console_renders_all_three_figures():
    """The consumer obligation the clause exists for, at rung 3.

    *"Showing only what fits is precisely the dishonesty the clause prevents, and it is a
    rendering failure, so the assertion is over rendered output."* A queue object that states
    three figures beside a screen that shows one satisfies every assertion in the test above,
    and the teacher still believes they have reviewed everything that needed reviewing.

    `unstated_residual` matches on the **numbers**, not the field names: a screen that prints the
    label `residual_provisional` and no figure has rendered nothing, and one that prints "809
    remain provisional" has rendered it whatever the row is called.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    render_review_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")

    # One service behind both. An earlier draft built the queue in memory and rendered the
    # console's own `run-1`, so the comparison was between figures from two unrelated objects —
    # it would mismatch for a correct console, or match by coincidence. Review caught it.
    service = build_review(scores=broken.flagged_population(200))
    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    rendering = render_review_queue(service, run_id="run-1", budget_minutes=30)

    unstated = vocab.unstated_residual(rendering, queue)
    assert unstated == [], (
        f"the queue screen does not state {unstated}. CT-REVIEW-04, R26: a teacher who sees only "
        "what fits on the screen has no way to know what they did not see."
    )


# --- CT-REVIEW-05 — three populations, plus the deterministic criteria -------------------------


@pytest.mark.writtenahead
def test_tc_review_c05_the_queues_admission_query_cannot_reach_the_excluded_populations():
    """*"As a reachability property over the queue's actual queries rather than an observed
    absence."*

    The distinction is the whole case. An absence assertion over a fixture says "these four were
    not in this queue"; a reachability assertion says "no population of any shape puts them
    there". `FR-REVIEW-07`'s three plus `FR-REVIEW-06`'s deterministic criteria are structural
    exclusions, and the design treats them that way — `CT-AGG-06` routes quarantine to `triage`
    rather than `queued` precisely so the queue's own query cannot see it.

    Written against `admission_query()`, invented here and declared in `review_vocabulary`'s
    docstring: §3.15 declares nothing that exposes the query. The absence sweep below is kept as
    the second half rather than the first, because it is the weaker claim.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(40))
    require_attr(service, "admission_query", issue="#109")

    query = service.admission_query(run_id="run-1")

    assert query.routing_values == (vocab.QUEUE_ROUTING,), (
        f"the queue admits routing values {query.routing_values}. CT-AGG-06 makes "
        f"{vocab.QUEUE_ROUTING!r} the teacher's population and {vocab.OPERATOR_ROUTING!r} the "
        "operator's; a query that reads both puts quarantine in front of a teacher."
    )
    assert vocab.RANDOM_ARM_ORIGIN in query.excluded_origins, (
        f"the admission query does not exclude origin {vocab.RANDOM_ARM_ORIGIN!r}. The random "
        "arm is the only unbiased comparison RISK-07 has; an arm that gets reviewed is no longer "
        "independent of the review."
    )
    assert query.evaluation_modes == (vocab.JUDGED_EVALUATION_MODE,), (
        f"the queue admits evaluation modes {query.evaluation_modes}. FR-REVIEW-06 admits no "
        "deterministic criterion on any path (R54) — and CT-DET-06 says the exclusion is "
        "enforced from this column rather than by convention."
    )


@pytest.mark.writtenahead
@pytest.mark.parametrize("population", sorted(vocab.NEVER_RENDERED_POPULATIONS))
def test_tc_review_c05_no_excluded_population_appears_in_a_built_queue(population):
    """The observed-absence half, swept one population at a time.

    Weaker than the reachability assertion above and worth keeping beside it: the query check
    passes a module whose query is right and whose post-filter re-admits, and this one passes a
    module with no query check to make. Parametrized so a failure names the population that
    leaked — a combined test would report "an excluded item appeared" and leave the reader to
    find out which.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    excluded = broken.excluded_population()[population]
    service = build_review(scores=[*broken.flagged_population(20), excluded])
    require_attr(service, "admission_query", issue="#109")

    queue = service.build_queue(run_id="run-1", budget_minutes=600)
    shown = [item.score_id for item in queue.shown]

    assert excluded.score_id not in shown, (
        f"a {population!r} item was rendered in the review queue (FR-REVIEW-06/-07, R64/R54). "
        "The budget was generous enough to show everything admissible, so this is an admission "
        "failure rather than a truncation."
    )


@pytest.mark.writtenahead
def test_tc_review_c05_the_random_arm_spends_compute_and_produces_no_review_item():
    """The clause's own gloss, asserted directly: *"the random arm spends compute, never teacher
    minutes, and produces no review item."*

    Exactly zero, not "few". A run in which the random arm contributes even one review item has
    spent teacher minutes on the arm, and the arm has stopped being a sample of what the system
    does unattended — which takes RISK-07's only unbiased comparison with it.

    Both halves are asserted because they are separable: an arm that produces no review item but
    whose units are counted in `flagged_total` still spends the teacher's attention, on a number
    that overstates what there is to do.
    """
    import dataclasses

    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    arm = [
        dataclasses.replace(row, score_id=f"rand-{i}", origin=vocab.RANDOM_ARM_ORIGIN)
        for i, row in enumerate(broken.flagged_population(15))
    ]
    ordinary = broken.flagged_population(25)
    service = build_review(scores=[*ordinary, *arm])
    require_attr(service, "admission_query", issue="#109")

    queue = service.build_queue(run_id="run-1", budget_minutes=600)
    from_arm = [item.score_id for item in queue.shown if item.score_id.startswith("rand-")]

    assert len(from_arm) == vocab.RANDOM_ARM_REVIEW_ITEMS, (
        f"the random arm produced {len(from_arm)} review items: {from_arm[:5]}. CT-REVIEW-05: it "
        "spends compute, never teacher minutes."
    )
    assert queue.flagged_total == len(ordinary), (
        f"the queue counted {queue.flagged_total} flagged against {len(ordinary)} reviewable "
        "items. The random arm is not work the teacher can do, so counting it inflates the "
        "residual the system reports."
    )


# --- CT-REVIEW-06 — the write set, and the residual that persists ------------------------------


@pytest.mark.writtenahead
def test_tc_review_c06_a_review_action_writes_through_criterion_score_and_never_a_grade():
    """*"Reduce `criteria_provisional` **through `criterion_score`** — asserting the indirection,
    since this module never writes a grade."*

    The indirection is the assertion. A module that decrements a grade row's provisional counter
    directly gets the number right and makes review a grading surface, which is the boundary this
    clause draws — `M-GRADE` owns finalization and `CT-REVIEW-06` keeps review upstream of it.

    Read from a write audit rather than by checking the resulting numbers, because the numbers are
    identical either way. That is what makes this clause need a rung-3 assertion at all.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(20))
    require_attr(service, "write_audit", issue="#109")

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    service.act(queue.shown[0], action="accept", new_band=None, review_seconds=20)

    writes = service.write_audit()
    tables = {write.table for write in writes}

    assert vocab.PROVISIONAL_INDIRECTION_TABLE in tables, (
        f"the action wrote {sorted(tables)} and never touched "
        f"{vocab.PROVISIONAL_INDIRECTION_TABLE!r}. CT-REVIEW-06 reduces the provisional count "
        "through the score row; a count that falls without that write came from somewhere else."
    )
    forbidden = sorted(tables & set(vocab.FORBIDDEN_WRITE_TABLES))
    assert forbidden == [], (
        f"the review action wrote to {forbidden}. This module never writes a grade — that is "
        "M-GRADE's, and review is upstream of it in the strict sense."
    )
    unexpected = sorted(
        tables - set(vocab.PERMITTED_WRITE_TABLES) - {vocab.PROVISIONAL_INDIRECTION_TABLE}
    )
    assert unexpected == [], (
        f"the review action wrote to {unexpected}, which §3.15's Data flow paragraph does not "
        "name. A write nobody declared is a write nobody reasoned about."
    )


@pytest.mark.writtenahead
def test_tc_review_c06_residual_items_are_marked_provisional_unreviewed():
    """`FR-REVIEW-08`, property one of three. The three are separate tests because they fail
    independently and a combined one would name none of them.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(200))
    require_attr(service, "scores", issue="#109")

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    shown = {item.score_id for item in queue.shown}
    residual = [row for row in service.scores(run_id="run-1") if row.score_id not in shown]

    assert residual, "nothing was left over, so this asserts nothing about residual items"
    wrong = sorted({row.state for row in residual} - {vocab.RESIDUAL_STATE})
    assert wrong == [], (
        f"residual items carry states {wrong} rather than {vocab.RESIDUAL_STATE!r}. "
        "FR-REVIEW-08: an item nobody looked at is provisional and unreviewed, and it says so."
    )


@pytest.mark.writtenahead
def test_tc_review_c06_the_residual_persists_across_review_sessions():
    """Property two, and *"the per-sitting clear is the plausible bug"*.

    It is plausible because clearing feels like tidying: the sitting is over, the queue is stale,
    rebuild it fresh. And it would erase the residual the system promised to report — the teacher
    comes back to a queue that has forgotten what it owed them, and `flagged_total` restarts from
    whatever is still routed `queued`.

    Two sittings with an action in between, so the assertion distinguishes "persisted" from
    "nothing changed": the item acted on must leave the residual, and the untouched ones must stay.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(200))
    require_attr(service, "end_session", issue="#109")

    first = service.build_queue(run_id="run-1", budget_minutes=30)
    service.act(first.shown[0], action="accept", new_band=None, review_seconds=20)
    service.end_session(run_id="run-1")

    second = service.build_queue(run_id="run-1", budget_minutes=30)

    # `flagged_total`, not the residual. The residual is `flagged_total - items shown`, and the
    # second sitting frees the reviewed item's `est_seconds` — so a correct greedy fill generally
    # shows a different number of items and the residual moves by more than one. Review found an
    # earlier draft asserting `residual - 1`, which fails correct code. What actually detects the
    # per-sitting clear is the flagged count: it falls by exactly the one item that was reviewed,
    # and a queue that rebuilt from scratch reports the original 200.
    assert second.flagged_total == first.flagged_total - 1, (
        f"flagged_total went from {first.flagged_total} to {second.flagged_total} after one "
        "item was reviewed in the previous sitting. FR-REVIEW-08: the residual persists across "
        "sessions rather than clearing per sitting, and a count that restarts tells the teacher "
        "a new story every time they sit down."
    )
    assert second.residual_provisional == second.flagged_total - vocab.items_shown(second), (
        "the second sitting's residual does not reconcile with what it is showing, so the "
        "carried-forward count and the displayed queue disagree"
    )


@pytest.mark.writtenahead
def test_tc_review_c06_a_residual_item_is_never_silently_finalized_or_backfilled():
    """Property three. The two prohibitions are separate because they arrive from opposite
    motives — finalizing is "the run has to close", backfilling is "the field cannot be empty" —
    and both end with a grade the teacher never saw carrying a value nobody chose.

    Asserted after an explicit run close, which is where finalization pressure actually lands: a
    residual that survives a rebuild and dies at close-out has passed the test above and failed
    the clause.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(200))
    require_attr(service, "close_run", issue="#109")
    require_attr(service, "scores", issue="#109")

    before = service.build_queue(run_id="run-1", budget_minutes=30)
    service.close_run(run_id="run-1")

    rows = {row.score_id: row for row in service.scores(run_id="run-1")}
    shown = {item.score_id for item in before.shown}
    residual = [row for score_id, row in rows.items() if score_id not in shown]
    assert residual, (
        "closing the run left no rows outside what the queue showed, so both assertions below "
        "hold over an empty list. Either the fixture is not over-subscribed or `scores()` stopped "
        "returning the residual at close-out — and the second is the defect this test is for."
    )

    finalized = [row.score_id for row in residual if row.state != vocab.RESIDUAL_STATE]
    assert finalized == [], (
        f"{len(finalized)} residual items were finalized when the run closed: {finalized[:5]}. "
        "FR-REVIEW-08: never silently finalized. A grade nobody reviewed that says it was "
        "reviewed is the one outcome the residual exists to prevent."
    )

    # Asked of the label store, not of the score row. A `criterion_score` row has no
    # `teacher_band` — the teacher's band lives on the `label` (§3.15's Data flow) — so
    # `getattr(row, "teacher_band", None) is None` was true of every row shape and could not fail.
    # Review caught it. A backfill leaves either a label nobody wrote or a resolved state, and
    # both are asked for here.
    labels = {label.score_id for label in service.labels_for(run_id="run-1")}
    backfilled = sorted({row.score_id for row in residual} & labels)
    assert backfilled == [], (
        f"{len(backfilled)} residual items gained a label nobody entered: {backfilled[:5]}. "
        "FR-REVIEW-08: never backfilled with a substitute value."
    )
