"""`CT-CONSOLE-10`, `-11` and `-12` — a grade never without its provenance, a statistic never
without its scope, and two queues that never touch.

Test plan §6.11.19, TS-76 (issue #131). All three are about what a **reader** concludes, which is
why all three assert on rendered output rather than on a return value: *"a figure that is correct
in the model and wrong on the page has still broken the contract, because the page is the
interface"*.

* `-10` — package version, rubric version and backend profile on **any** view showing a grade.
  `RISK-12` is a grade that cannot be defended in a dispute, and §6.11.19 names the realistic gap:
  *"provenance present on the main screen and absent on the export preview"*.
* `-11` — three separate renderings, so three tests. Two are positives about a figure; the third
  is a **negative** about a figure that must not be there, and `RISK-08` has no symptom — a
  carried-forward kappa looks better than the honest absence it replaced.
* `-12` — separate routes, separate counts, no reachability, and the blind reservation subtracted
  **before** ranking.

Keyed per rendering rather than per case, because these three cases straddle four stories:
`-10` and `-11`(a) are #123's (`FR-CONSOLE-09`, `-10`), `-11`(b) and `-12`'s ordering half are
#125's (`FR-CONSOLE-24`, `-19`), `-11`(c) is #126's (`FR-CONSOLE-26`, S1 Packages) and `-12`'s
separation half is #123's (`FR-CONSOLE-11`, `-12`). A single key would hold three renderings
outside the gate waiting on a story none of them needs.
"""

from __future__ import annotations

import pytest

from tests.support import broken_console_security_fixtures as fixtures
from tests.support.console_security_vocabulary import (
    FORBIDDEN_QUEUE_ITEM_KINDS,
    NO_NEW_VALIDATION_EVIDENCE,
    NO_VALIDATION_FOR_POPULATION,
    QUARANTINE_STATES,
    agreement_block_problems,
    grade_views_missing_provenance,
    queries_reaching,
)
from tests.support.console_vocabulary import elements, visible_text
from tests.support.impl import CONSOLE_MODULE, require
from tests.support.store_spy import StoreSpy

pytestmark = pytest.mark.contract


# --- CT-CONSOLE-10 — a grade is never displayed without its provenance ---------------------------


@pytest.mark.writtenahead
def test_tc_console_c10_every_route_that_displays_a_grade_displays_its_provenance():
    """`CT-CONSOLE-10` / `FR-CONSOLE-09` — swept over **every** grade-displaying route.

    §6.11.19 names the gap this sweep is for, and it is not the main screen: *"provenance present
    on the main screen and absent on the export preview is the realistic gap"*. That is what makes
    the case exhaustive rather than a single assertion — the screen somebody remembers is the one
    that will have it.

    `FR-CONF-09` is what makes it renderable: `profile_summary()` returns the backend profile
    *"in a form the console renders on any view showing a grade and the audit record stores
    verbatim"*, and `CT-CONF-09` adds that it is credential-free, which is what makes it safe to put
    on every page. So this is a rendering obligation rather than a data-availability problem.

    The rule reads the **value**, not the label: three headings with nothing after them satisfy any
    substring check and defend nothing in a dispute (`RISK-12`).
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    failures: list[str] = []
    grade_views = 0

    for screen, route in app.screens().items():
        html = app.render(route).html
        if not (elements(html, "grade") or elements(html, "band")):
            continue
        grade_views += 1
        missing = grade_views_missing_provenance(html)
        if missing:
            failures.append(f"{screen} ({route}) shows a grade and omits {missing}")

    assert grade_views >= 2, (
        f"only {grade_views} route(s) displayed a grade, so an exhaustive sweep swept almost "
        f"nothing. S9, S12 and S13 all display grades, and the export preview is the one the "
        f"case is about."
    )
    assert not failures, f"{failures}. R66: a grade is never displayed without its provenance."


# --- CT-CONSOLE-11 — three renderings, three tests ------------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c11a_any_agreement_statistic_renders_corrected_scoped_and_unmerged():
    """`FR-CONSOLE-10` — four requirements in one sentence, and each has a way of being lost.

    Chance-corrected (`R8`: on a four-band scale two judges guessing agree a quarter of the time,
    so a raw percentage has a floor no reader corrects for), sample size **adjacent** (a kappa from
    six labels and one from six hundred read identically without it), population- and
    backend-scoped (`R23`, `R51`: a figure from another population is a different measurement
    wearing the same label), and atomic and holistic never merged.

    Swept over every block on every route rather than asserted once, because the fourth requirement
    fails per block: a page can scope its atomic figure correctly and merge the holistic one.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    failures: list[str] = []
    blocks_seen = 0

    for screen, route in app.screens().items():
        for block in elements(app.render(route).html, "agreement"):
            blocks_seen += 1
            problems = agreement_block_problems(visible_text(block))
            if problems:
                failures.append(f"{screen} ({route}): {problems}")

    assert blocks_seen, (
        "no route rendered an agreement block, so this case asserted nothing. S1 and S12 both "
        "carry one, and a console that renders no statistic at all cannot render one wrongly — "
        "which is not the same as satisfying FR-CONSOLE-10."
    )
    assert not failures, f"{failures}"


@pytest.mark.writtenahead
def test_tc_console_c11b_with_no_blind_labels_the_block_says_so_and_carries_no_prior_figure():
    """`FR-CONSOLE-24` — asserted as a **negative**, because `RISK-08` has no symptom.

    §6.11.19: *"the silent carry-forward is RISK-08 and is asserted as a negative"*. The reason is
    in the fixtures — `CARRIED_FORWARD_AGREEMENT_BLOCK` is chance-corrected, scoped, sized and
    unmerged. It passes every well-formedness check in this file. The only thing wrong with it is
    that it is last term's, and no rule can see that from the page.

    So three assertions: the exact copy is present, no figure is in that position, and — the one
    §6.11.19 insists on — **`0.00` is a failure too**. A block rendering `κ = 0.00` because nothing
    was collected has said something false: zero is chance agreement, a real point on the scale,
    and §2.1's error is *"a blank that reads as fine"*.

    Keyed on **#125**: `FR-CONSOLE-24` is invariant 20 and lands with that story.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#125")

    app = build_console(store=StoreSpy(), blind_labels_collected=0)
    block = visible_text(app.render("/runs/{id}/rollup", id="r-1").html)
    lowered = block.lower()

    assert NO_NEW_VALIDATION_EVIDENCE in lowered, (
        f"with no blind labels collected the agreement block reads {block!r}. FR-CONSOLE-24 "
        f"requires this exact sentence, because 'no data' is the paraphrase a reader takes to mean "
        f"'not shown on this page'."
    )
    assert "0.00" not in block and "0.0" not in block, (
        f"a zero figure is rendered in the position reserved for the absence message: {block!r}. "
        f"Zero is chance agreement, not absence — §2.1's error is the blank that reads as fine."
    )
    for statistic in ("kappa", "alpha", "κ", "α"):
        assert statistic not in lowered, (
            f"a {statistic!r} figure appears where FR-CONSOLE-24 requires the absence message. "
            f"That is the prior administration's number in this administration's position, which "
            f"is RISK-08 — and it looks better than the honest rendering, which is why it is a "
            f"risk rather than a bug."
        )


@pytest.mark.writtenahead
def test_tc_console_c11c_a_package_never_administered_here_renders_no_borrowed_figure():
    """`FR-CONSOLE-26` — S1's rule, and HLD §11.5 calls it *"the one most likely to be violated by
    a well-meaning summary card"*.

    A package carries validation data from wherever it has run. A card that shows *"kappa 0.71"*
    for a package never administered to this population has shown a real figure about a different
    cohort, and `R23`'s whole argument is that an instrument's statistics do not transfer.

    Keyed on **#126**, which builds S1 Packages (`FR-CONSOLE-26`). #126 depends only on #122, so it
    is a sibling of #123 and #125 rather than downstream of them — which is exactly why this
    rendering has its own key.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#126")

    app = build_console(store=StoreSpy())
    card = visible_text(
        app.render("/packages", package_version="pkg-3.2.0", population="Grade 11B").html
    )
    lowered = card.lower()

    assert NO_VALIDATION_FOR_POPULATION in lowered, (
        f"S1 renders {card!r} for a package never administered to this population. FR-CONSOLE-26 "
        f"requires that exact sentence."
    )
    for statistic in ("kappa", "κ", "agreement"):
        assert statistic not in lowered, (
            f"S1 shows a {statistic!r} figure beside 'no validation data for this population', so "
            f"the message and the borrowed number are on the card together — which is worse than "
            f"either alone, because the reader resolves the contradiction in favour of the number."
        )


# --- CT-CONSOLE-12 — two queues, and nothing crosses ---------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c12_quarantine_and_the_review_queue_have_separate_routes_and_counts():
    """`FR-CONSOLE-11` / invariant 6, and HLD §11.3 says merging them is *"a design defect"*.

    Not an information-architecture preference: §7.7 routes quarantine triage to the operator
    surface *"because letting rescans consume the teacher-minute budget defeats the budgeting that
    R9 and R12 rest on"*. §11.3 states the consequence exactly — they *"must not share a queue, a
    badge count, or a notification"* — so a shared **count** is a violation even with separate
    routes, and that is the half a route assertion alone would miss.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    review = app.review_queue(run_id="r-1")
    quarantine = app.quarantine(cohort_id="c-1")

    assert review.route != quarantine.route, (
        f"both queues serve from {review.route!r}. §11.3: two entry points with separate "
        f"navigation, because in a small school the same person does both jobs and the alternative "
        f"is 'a 790-item list with three rescans buried in it'."
    )
    assert review.queue.flagged_total != quarantine.queue.flagged_total or not review.queue.shown, (
        f"both queues report {review.queue.flagged_total}, which is the shared badge count §11.3 "
        f"forbids by name — alongside a shared queue and a shared notification"
    )
    assert not (set(review.queue.shown) & set(quarantine.queue.shown)), (
        f"{sorted(set(review.queue.shown) & set(quarantine.queue.shown))} appear in both queues"
    )


@pytest.mark.writtenahead
def test_tc_console_c12_no_quarantine_item_is_reachable_from_the_review_queue():
    """The reachability half, asserted over the queue's **queries** — §6.11.19's own instrument.

    *"A reachability assertion over the queue's queries."* Asserting on what rendered would pass a
    queue that fetches quarantined rows and filters them out in a template, and `FR-INGEST-30` says
    *"no quarantined item shall **ever** appear"* — a filter is not never, it is a line somebody can
    delete without touching the query it protects.

    The helper reports an explicit exclusion as well as a join, deliberately: excluding quarantined
    rows proves the queue joined to a table that carries them.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    queue = app.review_queue(run_id="r-1")

    assert queue.queries, (
        "the review queue issued no queries, so a reachability assertion over them asserts nothing"
    )
    reaches = queries_reaching(queue.queries, QUARANTINE_STATES)
    assert not reaches, (
        f"{reaches}. R64 and §7.7: quarantine is the operator's parallel workstream, and a "
        f"rescan that consumes a teacher-minute has cost a review item that would have changed a "
        f"grade."
    )


@pytest.mark.writtenahead
def test_tc_console_c12_no_deterministic_blind_or_random_arm_item_is_rendered_in_the_queue():
    """`FR-CONSOLE-12` and `-19` — three kinds, and each is kept out for a different reason.

    A **deterministic** criterion has no judgment to review (`R54`, `FR-DET-06`): its score is a
    lookup, so a review item for one is a teacher being asked to second-guess an answer key. A
    **blind** item shown in the queue is no longer blind, which destroys the only unbiased ground
    truth the system has (`R21`). A **random-arm** unit *"spends compute, never teacher minutes"*
    (`FR-REVIEW-07`) — rendering one silently rewrites the experiment that measures whether the
    ranking works at all.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    queue = app.review_queue(run_id="r-1")

    assert queue.queue.shown, "the review queue is empty, so nothing about its contents is asserted"
    offenders = [
        f"{item!r} is {getattr(item, 'kind', '?')}"
        for item in queue.queue.shown
        if getattr(item, "kind", None) in FORBIDDEN_QUEUE_ITEM_KINDS
    ]
    assert not offenders, f"{offenders}"

    reaches = queries_reaching(queue.queries, FORBIDDEN_QUEUE_ITEM_KINDS)
    assert not reaches, (
        f"{reaches}. Rendering is filtered; reachability is structural, and CT-DET-04 says a "
        f"deterministic criterion is never admitted 'on any path'."
    )


@pytest.mark.writtenahead
def test_tc_console_c12_the_blind_reservation_is_subtracted_before_ranking_not_after():
    """`FR-CONSOLE-19` — an **ordering** assertion, and the order is the requirement.

    Subtract-then-rank and rank-then-subtract produce different queues from the same inputs.
    Subtracting after ranking removes the *highest-value* items, because those are the ones the
    reservation lands on first — so the teacher's remaining minutes are spent on items the ranking
    already judged less likely to change a grade. The queue still looks correct: right length, right
    order, and no way to see the difference from the page.

    So the assertion is the console-side view of `CT-REVIEW-02`: the ranked set is drawn from a
    budget the reservation has already come out of.

    Asserted against `M-REVIEW`'s **declared** `ReviewQueue` rather than an invented shape:
    `CT-REVIEW-02` says `reserved_for_blind_minutes` is the field that *"states the
    subtraction"*, so the console reads the number rather than recomputing one.

    Keyed on **#125**, which owns `FR-CONSOLE-19` (invariant 15).
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#125")

    app = build_console(store=StoreSpy())
    view = app.review_queue(run_id="r-1", budget_minutes=40)
    queue = view.queue

    assert queue.reserved_for_blind_minutes > 0, (
        "no blind reservation was made, so 'subtracted before ranking' has nothing to assert. "
        "R21: blind labels are the only unbiased ground truth and cannot be retrofitted onto a "
        "run that did not collect them."
    )
    assert queue.budget_minutes == 40, (
        f"the stated budget renders as {queue.budget_minutes}; the reservation is subtracted from "
        f"it, not applied to the figure the teacher was shown"
    )
    assert len(view.ranked) == len(queue.shown), (
        f"the queue ranked {len(view.ranked)} items and shows {len(queue.shown)}, so something was "
        f"removed after ranking — and what a reservation removes after ranking is the "
        f"highest-value items, which is the measurement crowding out the work"
    )
    assert list(view.ranked) == list(queue.shown), (
        "the rendered order is not the ranked order, so the subtraction happened between them"
    )
    assert fixtures.SENTINEL_STUDENT_NAME not in str(queue.queries), (
        "a queue query carries a student name; ranking is a pure function of stored signals "
        "(NFR-REVIEW-02)"
    )
