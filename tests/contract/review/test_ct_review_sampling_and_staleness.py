"""`CT-REVIEW-10`, `-11`, `-15` — the two samples, what skipping costs, and the two error paths.

Test plan §6.11.15, `TC-REVIEW-C10`, `-C11` and `-C15`.

`CT-REVIEW-10` is the clause that keeps a missing measurement missing. Its failure mode is the
most comfortable one available: an administration skips the blind sample, and the screen shows
last term's κ because a figure is better than a blank. Every number is real, every number is
stale, and RISK-08 has arrived through the back door — so the case's discriminating fixture is an
administration that skips **while a previous figure exists**, which is the only construction under
which the defect is visible.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require, require_attr

pytestmark = pytest.mark.contract


# --- CT-REVIEW-10 — skipping has exactly one consequence ----------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c10_skipping_the_blind_sample_leaves_grades_delivered_and_finalized():
    """The *"exactly one"* half, asserted as everything-else-normal.

    *"Assert skipping the blind sample has exactly one consequence — no new validation evidence
    for that administration — by asserting everything else is unaffected: grades deliver and
    finalize normally."*

    Written this way round because the tempting implementation is the opposite: treat a skipped
    sample as a blocking condition, refuse to finalize, and make the teacher do the validation
    work before they can hand back marks. That is a *defensible* product decision and it is not
    what `FR-REVIEW-13` says — the sample is the system's instrument, not the student's gate.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(40))
    require_attr(service, "skip_blind_sample", issue="#111")

    service.skip_blind_sample(run_id="run-1")
    outcome = service.close_run(run_id="run-1")

    for expectation in vocab.UNAFFECTED_BY_SKIP:
        assert getattr(outcome, expectation) is True, (
            f"skipping the blind sample left {expectation} false. FR-REVIEW-13: skipping has "
            "exactly one consequence, and it is about the system's evidence, not the student's "
            "marks."
        )


@pytest.mark.writtenahead
def test_tc_review_c10_the_absence_is_reported_rather_than_papered_over():
    """The honesty half, and the discriminating negative.

    *"The discriminating case is an administration that skips the sample while a previous
    administration's figure exists; assert the earlier figure is not presented as current."*

    Two administrations, the first with labels and the second skipped. A module that carries the
    first figure forward reports a real number computed from real labels, which is what makes the
    defect survive review: nothing is fabricated, the number is simply about a different
    administration than the one the reader is looking at.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")

    earlier = build_stats(
        labels=[
            broken.Label(label_id=f"prev-{i}", system_band="B2",
                         teacher_band="B2" if i % 3 else "B3")
            for i in range(20)
        ],
        administration_id="admin-1",
    )
    assert earlier.agreement(scope=None).kappa is not None, (
        "the earlier administration produced no figure, so there is nothing that could be "
        "carried forward and this case asserts nothing"
    )

    blind_sample_skipped = require(REVIEW_MODULE, "blind_sample_skipped", issue="#111")
    service = build_review(scores=broken.flagged_population(40), administration_id="admin-2")
    require_attr(service, "skip_blind_sample", issue="#111")
    service.skip_blind_sample(run_id="run-2")

    report = blind_sample_skipped(service, run_id="run-2")
    assert report.reported is True, (
        "the skipped sample was not reported. FR-REVIEW-13: the system reports the absence — a "
        "blank where a figure belongs is the finding, not a gap to fill."
    )
    assert vocab.SKIP_CONSEQUENCE in report.message, (
        f"the report says {report.message!r}, which does not state "
        f"{vocab.SKIP_CONSEQUENCE!r}"
    )
    assert report.current_figure is None, (
        f"the skipped administration presents {report.current_figure!r} as its current figure. "
        "That number is last administration's, computed from last administration's labels, and "
        "presenting it here is RISK-08 arriving through the back door (R60)."
    )


# --- CT-REVIEW-11 — the two samples and their populations ---------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c11_the_blind_sample_draws_inside_its_range_over_judged_criteria_only():
    """`FR-REVIEW-12`'s two halves.

    The **range** and the **default** are asserted separately and the distinction is not
    pedantic: §3.15's Interfaces block defaults `blind_sample(n: int = 15)` and `REVIEW_BLIND_N`
    is 15, so a test that only calls the default and checks `15 <= n <= 25` has asserted the
    default, not the range. The sweep below asks for both ends and the middle.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#111")
    low, high = vocab.BLIND_SAMPLE_RANGE

    deterministic = [
        dataclasses.replace(
            row,
            score_id=f"det-{i}",
            evaluation_mode=vocab.DETERMINISTIC_EVALUATION_MODE,
        )
        for i, row in enumerate(broken.flagged_population(20))
    ]
    service = build_review(scores=[*broken.flagged_population(60), *deterministic])
    require_attr(service, "blind_sample", issue="#111")

    for n in (low, (low + high) // 2, high):
        session = service.blind_sample(run_id="run-1", n=n)
        assert len(session.items) == n, (
            f"blind_sample(n={n}) drew {len(session.items)} submissions. FR-REVIEW-12 accepts "
            f"{low}–{high}; a module that ignores n and always draws its default is not sampling "
            "to the teacher's request."
        )
        modes = {item.evaluation_mode for item in session.items}
        assert modes == {vocab.JUDGED_EVALUATION_MODE}, (
            f"the blind sample covered evaluation modes {sorted(modes)}. FR-REVIEW-12: judged "
            "criteria only — a deterministic criterion has no panel judgement to validate, so a "
            "blind label on one measures the scanner (R53)."
        )


@pytest.mark.writtenahead
def test_tc_review_c11_the_blind_sample_refuses_a_draw_outside_its_stated_range():
    """The other side of the range, which the acceptance test above cannot see.

    A module that accepts any `n` satisfies every assertion about 15, 20 and 25 and will happily
    draw 3 when a teacher in a hurry asks for 3 — and a κ over three labels is a number with no
    business being reported. `FR-REVIEW-12` states the range as the contract, so both ends refuse.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(60))
    require_attr(service, "blind_sample", issue="#111")
    low, high = vocab.BLIND_SAMPLE_RANGE

    for n in (low - 1, high + 1):
        with pytest.raises(ValueError) as caught:
            service.blind_sample(run_id="run-1", n=n)
        assert str(n) in str(caught.value) or "range" in str(caught.value).lower(), (
            f"blind_sample(n={n}) refused without saying what the range is, so the caller cannot "
            f"correct it: {caught.value!r}"
        )


@pytest.mark.writtenahead
def test_tc_review_c11_the_whole_grade_sample_draws_from_the_auto_accepted_population_only():
    """*"The auto-accepted restriction is the clause's stated point, so it gets its own
    assertion."*

    And the reason is worth restating: *"sampling reviewed grades would measure the review, not
    the system."* A whole-grade sample drawn from grades a teacher has already corrected shows the
    teacher their own work and reports it as evidence about the system.

    The fixture makes both populations available and the assertion is membership, not count — a
    module that draws 12 from a mixed pool passes every range check and fails this.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#111")

    auto = [
        dataclasses.replace(row, score_id=f"auto-{i}", routing="auto")
        for i, row in enumerate(broken.flagged_population(30))
    ]
    reviewed = [
        dataclasses.replace(row, score_id=f"rev-{i}", routing="reviewed")
        for i, row in enumerate(broken.flagged_population(30))
    ]
    service = build_review(scores=[*auto, *reviewed])
    require_attr(service, "whole_grade_sample", issue="#111")

    low, high = vocab.WHOLE_GRADE_SAMPLE_RANGE
    sample = service.whole_grade_sample(run_id="run-1", n=vocab.CONFIG_DEFAULTS["REVIEW_WHOLE_GRADE_N"])

    assert low <= len(sample) <= high, (
        f"the whole-grade sample drew {len(sample)} grades against FR-REVIEW-14's {low}–{high}"
    )
    from_reviewed = [g.submission_id for g in sample if g.submission_id.startswith("rev-")]
    assert from_reviewed == [], (
        f"the whole-grade sample included reviewed grades: {from_reviewed[:5]}. FR-REVIEW-14 "
        "draws from the auto-accepted population — sampling reviewed grades measures the review, "
        "not the system."
    )
    assert all(g.rendered_as_student_sees_it for g in sample), (
        "the sample is not shown as the student would receive it, so it is not the thing "
        "FR-REVIEW-14 asks the teacher to look at"
    )


@pytest.mark.writtenahead
def test_tc_review_c11_the_draw_is_uniform_over_the_eligible_set_rather_than_first_n():
    """*"Assert randomness is genuine (seeded, uniform over the eligible set) rather than
    first-N."*

    First-N is the plausible implementation and it is invisible to every other assertion in this
    file: the count is right, the population is right, and the sample is the same twenty
    submissions every administration — so the validation evidence accumulates about one corner of
    the cohort and says nothing about the rest.

    Two assertions. Distinct seeds must give distinct draws (a module ignoring the seed fails),
    and the union over many draws must cover the eligible set (a module drawing the first N
    passes the first assertion if it shuffles the tail, and fails this).
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#111")
    population = broken.flagged_population(120, criteria=1)
    eligible = {row.submission_id for row in population}

    require_attr(build_review(scores=population, seed=0), "blind_sample", issue="#111")

    draws = []
    for seed in range(vocab.RANDOMNESS_TRIALS):
        service = build_review(scores=population, seed=seed)
        session = service.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[0])
        draws.append(frozenset(item.submission_id for item in session.items))

    assert len(set(draws)) > 1, (
        f"{vocab.RANDOMNESS_TRIALS} seeds produced one draw. The sample is not random, so every "
        "administration validates the same submissions and the evidence never widens."
    )

    covered = set().union(*draws)
    assert covered == eligible, (
        f"{len(covered)} of {len(eligible)} eligible submissions were ever drawn across "
        f"{vocab.RANDOMNESS_TRIALS} seeds. FR-REVIEW-12 draws at random over the eligible set; a "
        "draw that can never reach part of the cohort is a biased instrument reporting an "
        "unbiased number."
    )


# --- CT-REVIEW-15 — the stale action, and the interrupted session --------------------------------


@pytest.mark.writtenahead
def test_tc_review_c15_an_action_on_a_stale_item_is_rejected_with_a_refresh():
    """*"Construct the race directly: open the item, escalate underneath it, then act."*

    The race is the case. A staleness check written against a version the caller passes in is
    correct and untested until something actually changes between the read and the write, and the
    escalation path is what does that in production — `M-ORCH` supersedes the score while the
    teacher is reading it.

    Two assertions, and the second is the one that protects the data: the action is refused
    **and** the old row is untouched. A module that raises after applying the write has told the
    teacher it failed and recorded that it succeeded.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(20))
    require_attr(service, "escalate", issue="#108")
    require_attr(service, "scores", issue="#109")

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    item = queue.shown[0]

    superseded = service.escalate(item.score_id)
    assert superseded.score_id != item.score_id or superseded.version != item.version, (
        "the escalation did not supersede the row the teacher is holding, so there is no race here"
    )

    with pytest.raises(Exception) as caught:
        service.act(item, action="override", new_band="B1", review_seconds=30)

    assert "refresh" in str(caught.value).lower() or "stale" in str(caught.value).lower(), (
        f"the stale action was refused with {caught.value!r}, which does not tell the teacher to "
        "refresh. CT-REVIEW-15 rejects *with a refresh* — a bare error leaves them retrying the "
        "same dead row."
    )
    rows = {row.score_id: row for row in service.scores(run_id="run-1")}
    assert getattr(rows[item.score_id], "teacher_band", None) is None, (
        "the rejected action was applied to the old row anyway. CT-REVIEW-15: never applied to "
        "the old row — a band written against a superseded score is a judgement about text the "
        "teacher was not shown."
    )


@pytest.mark.writtenahead
def test_tc_review_c15_an_interrupted_blind_session_keeps_the_criteria_actually_answered():
    """The second half, *"which protects data rather than rejecting it"*.

    *"A blind session interrupted mid-way records only the criteria actually answered, and those
    labels are valid."* Both halves matter and they pull opposite ways: discarding the partial
    session wastes the scarcest data the system collects, and keeping the unanswered criteria as
    labels invents judgements nobody made.

    So the assertion is an exact set — the answered criteria, no more and no fewer — plus
    admissibility, since a partial blind label that `M-STATS` will not accept is the same as no
    label at all.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(60))
    require_attr(service, "blind_sample", issue="#111")
    require_attr(service, "label", issue="#110")

    session = service.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[0])
    answered = list(session.items)[:6]

    label_ids = service.submit_blind(
        session.session_id,
        bands={ref: "B2" for ref in answered},
        interrupted=True,
    )
    labels = [service.label(i) for i in label_ids]

    assert len(labels) == len(answered), (
        f"an interrupted session recorded {len(labels)} labels for {len(answered)} answered "
        "criteria. CT-REVIEW-15 records only what was answered — more means a band nobody chose, "
        "fewer means the scarcest data the system collects was thrown away."
    )
    assert {label.criterion_id for label in labels} == {ref.criterion_id for ref in answered}, (
        "the labels recorded do not correspond to the criteria actually answered"
    )
    for label in labels:
        assert label.label_type == "blind", (
            f"a label from an interrupted blind session carries type {label.label_type!r}, so "
            "M-STATS's admissibility filter would not count it"
        )
        assert getattr(label, vocab.ADMISSIBILITY_COLUMN) == 0, (
            "a label from an interrupted blind session records that the system's output was "
            "visible. CT-REVIEW-15: those labels are valid — the interruption changes how many "
            "there are, not what they are."
        )
