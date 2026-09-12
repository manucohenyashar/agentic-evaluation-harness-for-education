"""`TC-E2E-03` — the review morning, and the honest residual (§4.2.3, rung 4).

Issue #144 (TS-51), against the **assembled** system: every module in the
journey is the real implementation, driven over one real store - the same
world the other two journeys use, with no doubles at any module boundary and
no egress but the journey's own `RecordedFixtureProvider` (`CT-PROV-10`,
`CT-PROV-15`).

The block form (test plan §6.2, design §4.2.3): the teacher states 30 minutes;
10 are reserved for the blind sample **before** ranking; the queue's header
states honestly what was shown and what stays provisional; a group action
covers its identical members as one decision; the blind sample runs with the
system's output structurally unreachable from the flow; the agreement figure
is computed from blind judged labels only, with n attached; the whole-grade
sample draws from the auto-accepted population; the class finalizes in one
action naming its coverage. **Oracles**: the label rows match the actions
taken with the right `saw_system_output` values, and the agreement figure's n
equals the blind label count and not the total label count.

Drive-shape disclosures, made once here:

* **The overnight run stops before its completing settlement.** Journey 2 pins
  the run-completion finalization road (`CT-GRADE-09`'s automatic-on-completion
  half) and compares the full journey against its committed baseline. The
  review morning's journey pins the OTHER roads the same clause names: this
  world's drive runs every overnight leg, issues the grades while the run is
  still running (they read `provisional` - the window is open), and leaves the
  settlement to the morning: `finalize_batch` is the one action naming its
  coverage, and - in the failure variant, where the teacher does none of it -
  the lapse of the configured review window settles the same grades with no
  teacher action anywhere (`CT-GRADE-09`, HLD `R60`). The window is per-package
  data (`ADR-3`) and a published version is immutable (`FR-PKG-01`), so the
  world's constructor attaches this journey's policy BEFORE the version's
  publication - the journey-3 worlds pass `review_window_hours=48`, and the
  lapse road is real rather than vacuous.
* **The auto-accepted population is engineered, and says so.** `whole_grade_sample`
  draws only from submissions whose every criterion routed `auto`. At the
  design's Assumption thresholds a unanimous three-judge holistic panel carries
  confidence `1.0 x 0.85` (the holistic multiplier) - below the default 0.90
  threshold, so under journey 2's configuration no judged cell ever routes
  auto. Journey 3's walks inject `auto_threshold_holistic=0.85` through the
  world's `agg_config_kwargs` (Q-04: the tests inject the thresholds; the
  assertions are stated against the injection, never against the literals), so
  the unanimous panels the world's judges actually produce route auto and both
  populations exist: items to review, and a system-only population to sample.
  Journey 2's baseline pins the default thresholds.
* **The review queue is the breaker's halt, on purpose.** The same injection
  routes every widened unanimous panel auto, so with escalations widening
  freely the queue would empty and the morning would have nothing to review.
  Journey 3's walks therefore hand the criterion breaker journey-2's variant
  (c) knobs (rate 0.50, window minimum 4): the cells whose widening is halted
  keep the panel's own figure routed `provisional`, state
  `ungradeable_by_panel` (`FR-ORCH-13`, `FR-AGG-11`'s precedence) - the
  population the morning's queue reviews, groups over, and draws its blind
  sample from. The trip is asserted (the world's `breaker_marked` is
  non-empty), not assumed.
* **The agreement pair is the recorded-not-shown protocol.** The blind flow's
  labels are one-sided by construction (`#111`: `system_band` NULL - the flow
  cannot reach a score row, and the honest label says so). The kappa the
  morning reports pairs the blind judgement with the system's actual stored
  output for the same ref, recorded onto the same label id through the shipped
  collection route (`record_label`'s durable upsert - the route the statistics
  cases collect through): recorded, never shown. `saw_system_output` stays 0 -
  the teacher never saw the band - so the label stays admissible
  (`FR-STATS-01`) and the figure's pair is the system's stored band against
  the blind judgement, not a manufactured one (`CT-REVIEW-09` governs the
  flow, and the collection is the system's record, not a teacher view). The
  sitting answers the whole draw - a complete sitting is the ordinary shape
  (`CT-REVIEW-15`'s interrupted half is the contract tier's case) - so the
  blind population is the draw, and the figure's population (no criterion
  filter) is exactly the blind labels. The record's headline kappa follows the
  module's own per-criterion rule (`CT-STATS-06`); the journey asserts the
  record's COUNT of blind labels and that the record advanced, and the
  per-criterion figures ride the record's weakest-entry field.
* **The prior administration in the failure variant is built the same way**: a
  previous term's blind collection, written through the same route, whose
  record carries a real figure - so the carry-forward risk (`RISK-08`) is live
  and the console's refusal to present it as current (`FR-CONSOLE-24`) is
  exercised against a figure that exists, not against an empty record.

Scale disclosure: the plan's block form states its figures at the plan's
declared scale (790 flagged, 40 shown, 210 in the group, 350 finalized). The
journeys run at the variant scale the suite's tiering supports, and the
oracles bind the MECHANISM each figure comes from - the reserve subtracted
before ranking, the header arithmetic, one label per group member, the blind
draw's range, the n the figure attaches - not the plan's illustrative counts.
The full-scale overnight half of this world is journey 2's, against the
committed baseline.

Three-judge base-panel disclosure: the world's judged cells are scored by
three-judge panels, so every routing figure below is a three-judge figure at
the injected threshold; escalations widen to the next odd count the policy
targets, exactly as in journey 2.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tests.support.e2e_world import E2E_COHORT_ID, PKG_ID, SynthWorld
from tests.support.grade_vocabulary import backdate_grades

from aeh.console import render_agreement_block
from aeh.grade import open_grade
from aeh.review import (
    LabelRecord,
    ReviewError,
    ReviewGroup,
    open_review,
    record_label,
)
from aeh.stats import NO_NEW_VALIDATION_EVIDENCE, open_stats

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

ISSUE = "#144"

#: The variant scale - the journeys' reduced execution scale (the same reading
#: journey 2's variants take; see that module's docstring). Sixty: enough
#: submissions that the breaker's windows trip on the cohort's own escalation
#: share (below) while the whole-grade sample's auto population and the queue's
#: signature groups both exist at the injected threshold.
COHORT_N = 60

#: Journey 3's injected holistic auto threshold (Q-04): the unanimous panel's
#: confidence `1.0 x 0.85` routes auto, so the auto-accepted population exists
#: and the queue still holds the split panels. Stated as fixture data.
AUTO_THRESHOLD_HOLISTIC = 0.85
WALK_KWARGS = {"auto_threshold_holistic": AUTO_THRESHOLD_HOLISTIC}

#: The criterion-breaker knobs the walks hand the breaker - journey-2's variant
#: (c) values (rate 0.50; the window minimum pinned below the shipped 20 so the
#: cohort's own first four completions per criterion are the window). The same
#: injection that routes the unanimous widened panels auto would EMPTY the queue
#: if escalations widened freely; the trip is what leaves cells routed
#: provisional (state `ungradeable_by_panel`) for the morning to review.
BREAKER_RATE = "0.50"
BREAKER_MIN_N = "4"

#: The review window the world's package carries (`ADR-3` per-package data) and
#: how far past its edge the failure variant backdates (the disclosed seam).
WINDOW_HOURS = 48
LAPSED_HOURS = 72

#: The morning's stated budget and the blind reserve (`FR-REVIEW-02`'s block
#: numbers, as the service's knobs), and the blind draw at the declared range's
#: top (`FR-REVIEW-12`: 15-25).
BUDGET_MINUTES = 30
BLIND_RESERVE_MINUTES = 10
BLIND_DRAW_N = 25


# --- the drive ------------------------------------------------------------------------------

def _morning_drive(world: SynthWorld, monkeypatch) -> None:
    """The control drive through the overnight legs, WITHOUT the completing
    settlement: the run starts, the deterministic leg runs in topo order, the
    integrity gate passes, the judged legs run, the walk enqueues escalations,
    the widened panels re-aggregate, synthesis runs - and `compute_all` issues
    the grades while the run is still running. The walk's aggregation is the
    injected configuration (see the module docstring's auto-population
    disclosure); the window the roads hang off was attached to the package
    version before its publication, by the world's own constructor."""
    world.build_run()
    world.start_run()
    world.drive_deterministic()
    world.integrity_pass()
    world.drive_extract()
    world.drive_score()
    world.integrity_pass(capture=True)
    walk = dict(
        monkeypatch=monkeypatch, agg_config_kwargs=dict(WALK_KWARGS),
        breaker_rate=BREAKER_RATE, breaker_min_n=BREAKER_MIN_N)
    world.aggregate_walk(**walk)
    world.drive_score(include_escalations=True)
    world.aggregate_walk(**walk)
    world.drive_synthesis()
    open_grade(world.store).compute_all(world.run_id)
    # The queue's population is the breaker's halt - asserted, not assumed: the
    # durable mark on the cells is what the morning's queue reviews, groups
    # over, and draws its blind sample from (the module docstring's disclosure).
    marked = world.handle.query(
        "SELECT COUNT(*) AS n FROM criterion_score WHERE state = 'ungradeable_by_panel'")
    assert marked[0]["n"] > 0, (
        "the criterion breaker never left a marked cell - the queue's population "
        "is the breaker's halt, and an untripped walk routes every widened "
        "unanimous panel auto, with nothing for the morning to review"
    )


def _band_names(world: SynthWorld, criterion_id: str) -> list[str]:
    """The declared band names of one criterion, read from the real package
    (the cache's row shape or the declared value objects, whichever the store
    produces)."""
    rows = world.catalog.bands(criterion_id)
    return [row["band"] if isinstance(row, dict) else row.band for row in rows]


def _store_band(world: SynthWorld, submission_id: str, criterion_id: str) -> str:
    """The system's stored band for one cell - the real aggregated result row.
    `criterion_score`'s key is `(submission_id, criterion_id)`, so the read is
    one row."""
    rows = world.handle.query(
        "SELECT band FROM criterion_score WHERE submission_id = :s "
        "AND criterion_id = :c",
        s=submission_id, c=criterion_id,
    )
    assert rows, f"fixture bug: no stored score for {submission_id}/{criterion_id}"
    return str(rows[0]["band"])


def _grade_states(world: SynthWorld) -> dict[str, int]:
    """The run's current grade rows, counted by state."""
    rows = world.handle.query(
        "SELECT state, COUNT(*) AS n FROM submission_grade "
        "WHERE run_id = :r AND is_current = 1 GROUP BY state",
        r=world.run_id,
    )
    return {row["state"]: row["n"] for row in rows}


def _hours_ago(hours: int) -> str:
    """The disclosed lapse seam's timestamp form (the `_drive.py` precedent)."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _shown_items(queue) -> int:
    """The queue's item count with groups expanded - the residual arithmetic's
    own unit (`build_queue` computes the residual over it)."""
    return sum(
        len(entry.members) if isinstance(entry, ReviewGroup) else 1
        for entry in queue.shown
    )


# --- TC-E2E-03: the happy path --------------------------------------------------------------

def test_tc_e2e_03_review_morning_shows_its_residual_and_collects_its_evidence(
    tmp_data_dir, tmp_path, monkeypatch,
):
    """`TC-E2E-03` happy path, end to end: budget stated, reserve taken before
    ranking, the header honest, the group action one label per member, the
    blind sitting unreachable, the figure from blind judged labels only with n
    attached, the whole-grade sample from the auto population, the class
    finalized in one action naming its coverage - and the record advanced with
    that evidence."""
    world = SynthWorld(tmp_data_dir, tmp_path / "fixtures",
                       n_submissions=COHORT_N, monkeypatch=monkeypatch,
                       review_window_hours=WINDOW_HOURS)
    _morning_drive(world, monkeypatch)

    # The morning opens on provisional grades: the run is still running and the
    # window is open, so the settlement below is the morning's action, not the
    # overnight run's.
    states = _grade_states(world)
    assert states.get("provisional", 0) > 0, (
        f"the grades read {states} - the drive was to issue them provisional "
        "against the journey's windowed policy, leaving the settlement to the "
        "morning's one action (the design §4.2.3 shape)"
    )

    service = open_review(
        world.data_dir,
        run_id=E2E_COHORT_ID,
        actor="teacher",
        catalog=world.catalog,
        review_blind_reserve_minutes=BLIND_RESERVE_MINUTES,
        seed=14403,
    )

    # 30 minutes stated; 10 reserved for the blind sample BEFORE ranking - the
    # build trace's stage order is the contract, and the header's arithmetic is
    # the honesty pair.
    queue = service.build_queue(E2E_COHORT_ID, budget_minutes=BUDGET_MINUTES)
    assert queue.reserved_for_blind_minutes == BLIND_RESERVE_MINUTES, (
        f"the queue reserved {queue.reserved_for_blind_minutes} minutes - the "
        "teacher stated 30 and 10 are the blind sample's, reserved BEFORE the "
        "ranking subtracts them from what the shown set may consume "
        "(FR-REVIEW-02's block form)"
    )
    stage_names = [event.name for event in queue.build_trace]
    assert stage_names.index("reserve_blind_minutes") < stage_names.index(
        "rank_items"), (
        f"the build trace ran {stage_names} - the reserve is subtracted before "
        "anything is ranked (CT-REVIEW-02's stage order), which is what makes "
        "the shown set smaller, not larger"
    )
    assert queue.flagged_total == _shown_items(queue) + queue.residual_provisional, (
        f"the header arithmetic broke: {queue.flagged_total} flagged != "
        f"{_shown_items(queue)} shown + {queue.residual_provisional} residual - "
        "the header states honestly what was shown and what stays provisional"
    )
    assert queue.residual_provisional > 0, (
        "the queue showed everything flagged - the honest residual is the "
        "journey's subject, and a 20-minute spendable budget cannot cover the "
        "world's flagged population"
    )

    # The teacher's per-item decisions on the FIRST group's members: an accept
    # keeps the proposed band; an override names one. A group's members are
    # ReviewItems like any other - the teacher reads the proposed band off the
    # entry and answers it individually - and both decisions write labels that
    # saw the system's output.
    shown_groups = [entry for entry in queue.shown
                    if isinstance(entry, ReviewGroup)]
    assert len(shown_groups) >= 2, (
        f"{len(shown_groups)} signature-identical groups were shown - the "
        "world's identical panels were to form them at the injected threshold, "
        "and both decision legs below would be vacuous"
    )
    group = shown_groups[0]
    members = group.members
    assert len(members) >= 2, (
        "the first group holds fewer than two members - the two individual "
        "decisions below would be vacuous"
    )
    target_bands = _band_names(world, members[1].criterion_id)
    other_band = next(
        band for band in target_bands if band != members[1].proposed_band)
    acted = [
        service.act(members[0], "accept", review_seconds=20),
        service.act(members[1], "override", new_band=other_band,
                    review_seconds=25),
    ]
    assert all(acted), "an action wrote no label"

    # The group action on the SECOND group: one band decision over the whole
    # group, ONE label per member - statistically indistinguishable from N
    # individual actions (CT-REVIEW-13), so the label count the group covers is
    # the member count.
    second = shown_groups[1]
    group_ids = service.act_on_group(
        second, band=second.members[0].proposed_band, review_seconds=60)
    assert len(group_ids) == len(second.members), (
        f"the group action wrote {len(group_ids)} labels for "
        f"{len(second.members)} members - one label per member, or a bulk "
        "decision under-weights itself in every agreement figure"
    )
    assert all(service.label(label_id).via_group for label_id in group_ids), (
        "a group-action label does not record itself as one member of a group "
        "action - the per-member share is session bookkeeping, and losing it "
        "loses CT-REVIEW-13's differential"
    )

    # The blind sample: the draw is in the declared range, and the flow's data
    # boundary is the session type's own (CT-REVIEW-09).
    session = service.blind_sample(E2E_COHORT_ID, n=BLIND_DRAW_N)
    assert 15 <= len(session.items) <= 25
    assert session.readable_tables() == frozenset({"submission", "criterion"})
    # The sitting answers the whole draw - a complete sitting is the ordinary
    # shape (CT-REVIEW-15's interrupted half is the contract tier's case) - so
    # the blind population is the draw itself. The teacher's bands vary across
    # the sitting, each ref named a band of its own criterion, so the judgement
    # side of the figure below carries a real spread.
    bands_by_criterion: dict[str, list[str]] = {}
    answers: dict = {}
    for i, ref in enumerate(session.items):
        bands = bands_by_criterion.setdefault(
            ref.criterion_id, _band_names(world, ref.criterion_id))
        answers[ref] = bands[i % len(bands)]
    blind_ids = service.submit_blind(session.session_id, answers,
                                     review_seconds=90)
    assert len(blind_ids) == len(session.items) >= 15, (
        f"the sitting answered {len(blind_ids)} refs of a "
        f"{len(session.items)}-ref draw - the complete sitting's labels are "
        "the whole draw, and the figure below counts exactly them"
    )

    # The flow half of the label oracle: every blind label was written blind -
    # earned 0, no system band, no score link, no queue action (CT-REVIEW-09
    # step 4, #111) - and every queue label the actions took was written seen.
    labels = service.labels_for(E2E_COHORT_ID)
    by_id = {label.label_id: label for label in labels}
    for label_id in blind_ids:
        label = by_id[label_id]
        assert (label.saw_system_output, label.system_band, label.score_id,
                label.review_queue_action) == (0, None, None, None), (
            f"blind label {label.label_id!r} reads saw={label.saw_system_output}, "
            f"system={label.system_band!r}, score={label.score_id!r}, "
            f"action={label.review_queue_action!r} - the flow cannot reach the "
            "output, and the label says so"
        )
    for label_id in [*acted, *group_ids]:
        label = by_id[label_id]
        assert label.saw_system_output == 1 and label.system_band is not None, (
            f"queue label {label.label_id!r} reads saw={label.saw_system_output} "
            f"system={label.system_band!r} - a queue action happens with the "
            "system's band on the screen, and the label records it"
        )
    blind_rows = [by_id[label_id] for label_id in blind_ids]

    # The agreement pair: the system's stored band for each answered ref is
    # recorded onto the same label through the shipped collection route -
    # recorded, never shown (the module docstring's protocol disclosure).
    for ref, label in zip(session.items, blind_rows):
        collected = replace(label, system_band=_store_band(
            world, ref.submission_id, ref.criterion_id))
        record_label(
            data_dir=world.data_dir, label=collected, cohort_id=E2E_COHORT_ID)

    # The figure: computed from the blind judged labels only, n attached - the
    # issue's oracle is that n equals the blind label count and not the total.
    # No criterion filter: the figure's population is exactly the blind labels
    # the sitting wrote, whatever criteria the draw spanned.
    stats = open_stats(world.data_dir)
    figure = stats.agreement(
        package_version=world.version,
        scope=E2E_COHORT_ID,
        scoring_model="holistic",
    )
    total_labels = len(labels)
    assert figure.n == len(blind_rows), (
        f"the agreement figure's n is {figure.n}, not the blind label count "
        f"{len(blind_rows)} - the population the figure is computed over is "
        "exactly the blind population (FR-STATS-01)"
    )
    assert figure.n != total_labels, (
        f"the agreement figure's n equals the total label count ({total_labels}) "
        "- the seen labels leaked into the validity claim, the contamination "
        "the oracle names"
    )
    assert figure.kappa is not None, (
        f"no kappa over {len(blind_rows)} paired blind judged labels - the "
        "figure the morning reports is computed from the blind population, "
        "with the system's stored band recorded onto the same label"
    )

    # The whole-grade sample draws from the auto-accepted population: every
    # sampled submission's every criterion row routed auto, and the offer is
    # presented as the student would receive it (FR-REVIEW-14).
    sample = service.whole_grade_sample(E2E_COHORT_ID, n=10)
    assert sample, (
        "the whole-grade sample drew nothing - the injected threshold was to "
        "route the unanimous panels auto, so the auto-accepted population "
        "exists for the sample to draw from"
    )
    for grade in sample:
        non_auto = world.handle.query(
            "SELECT COUNT(*) AS n FROM criterion_score WHERE submission_id = :s "
            "AND routing <> 'auto'",
            s=grade.submission_id,
        )[0]["n"]
        assert non_auto == 0, (
            f"the sample drew {grade.submission_id!r}, which holds {non_auto} "
            "non-auto rows - sampling a reviewed submission would measure the "
            "review, not the system (CT-REVIEW-11's membership assertion)"
        )
        assert grade.criterion_bands and grade.points >= 0
        assert grade.rendered_as_student_sees_it, (
            "the whole-grade offer is not marked as the student-facing render - "
            "the sample shows the grade, not the system's internal view "
            "(FR-REVIEW-14)"
        )

    # The class finalizes in ONE action naming its coverage BEFORE it is taken
    # (FR-GRADE-09, CT-GRADE-09's batch limb - asserted on the pre-action
    # summary, not the post-action state).
    grade_service = open_grade(world.store)
    pre = grade_service.coverage(world.run_id)
    pre_counts = dict(pre.grades_by_state)
    assert pre_counts.get("provisional", 0) > 0, (
        f"the pre-action coverage is {pre_counts!r} - the morning's settlement "
        "below would be vacuous"
    )
    record = grade_service.finalize_batch(world.run_id, actor="teacher")
    assert dict(record.coverage) == pre_counts, (
        f"the record echoes {dict(record.coverage)!r}, but the coverage named "
        f"before the action was {pre_counts!r} - the batch names its coverage "
        "before it is taken"
    )
    assert record.finalized == pre_counts["provisional"], (
        f"the batch settled {record.finalized} grades against a provisional "
        f"class of {pre_counts['provisional']} - one action for the whole class"
    )
    assert record.actor == "teacher" and record.settled_at
    after = _grade_states(world)
    assert after.get("final", 0) == (
        pre_counts.get("final", 0) + pre_counts["provisional"]), (
        f"the class reads {after} after the batch - every provisional grade the "
        "coverage named is final"
    )
    assert after.get("incomplete", 0) == pre_counts.get("incomplete", 0), (
        f"the incomplete class reads {after.get('incomplete', 0)} against a "
        f"pre-action {pre_counts.get('incomplete', 0)} - an incomplete grade is "
        "a missing input awaiting an operator, never a batch deliverable"
    )

    # The record advances: the administration's promote claims its labels and
    # counts the blind population with n attached (FR-STATS-10). The headline
    # follows the module's own per-criterion rule (CT-STATS-06): the sitting's
    # blind population is the whole draw - multi-criterion - so no blended
    # headline is computable, and the per-criterion figures ride the record's
    # weakest-entry field instead.
    update = stats.promote(
        cohort_id=E2E_COHORT_ID, package_version=world.version)
    assert update.blind_count == len(blind_rows) and update.n == len(blind_rows), (
        f"the record counted blind {update.blind_count}/n {update.n} against "
        f"{len(blind_rows)} blind labels - the administration's evidence is the "
        "blind population"
    )
    assert update.message != NO_NEW_VALIDATION_EVIDENCE, (
        "the record reports an evidence absence for an administration that "
        "collected its sample"
    )
    assert update.agreement_kappa is None, (
        f"the record carried a blended headline kappa ({update.agreement_kappa!r}) "
        "over a multi-criterion blind population - CT-STATS-04/CT-STATS-06 keep "
        "that claim unrepresentable"
    )
    weakest = dict(update.weakest_per_population)[E2E_COHORT_ID]
    assert weakest["criterion_id"] in world.open_ids, (
        f"the record's weakest entry names {weakest['criterion_id']!r} - the "
        "field rides the per-criterion figures of the population the sitting "
        "actually judged, and the criterion it names is one of the package's "
        "judged criteria (FR-STATS-13)"
    )

    # The console renders the figure chance-corrected, sample-size-adjacent
    # (FR-CONSOLE-10); no absence sentence for an administration that collected.
    rendered = render_agreement_block(
        figure=figure, population=E2E_COHORT_ID, package_version=world.version)
    assert "kappa" in rendered and f"n = {len(blind_rows)}" in rendered, (
        f"the agreement block rendered {rendered!r} - the figure renders with "
        "its n attached"
    )
    assert NO_NEW_VALIDATION_EVIDENCE not in rendered, (
        f"the block rendered the absence sentence over a collected sample: "
        f"{rendered!r}"
    )


# --- TC-E2E-03: the failure variant ---------------------------------------------------------

def test_tc_e2e_03_teacher_does_none_of_it_and_the_absence_is_honest(
    tmp_data_dir, tmp_path, monkeypatch,
):
    """`TC-E2E-03` failure variant, as its own execution: the teacher does none
    of it. Grades finalize anyway - at the lapse of the configured window, with
    no teacher action anywhere (`CT-GRADE-09`, HLD `R60`); the validation
    record does NOT advance (`FR-STATS-11`); and the console reports the
    absence for this administration rather than reusing a prior figure in its
    place (`FR-REVIEW-13`, `FR-CONSOLE-24` - the RISK-08 carry-forward,
    exercised against a prior administration whose record holds a real
    figure)."""
    world = SynthWorld(tmp_data_dir, tmp_path / "fixtures",
                       n_submissions=COHORT_N, monkeypatch=monkeypatch,
                       review_window_hours=WINDOW_HOURS)
    _morning_drive(world, monkeypatch)

    # A prior administration holds a real record - the figure the console must
    # NOT present as current. Its blind collection is the recorded-not-shown
    # protocol through the shipped collection route (module docstring): four
    # blind labels on one criterion, judgement and system band both carried.
    target = world.open_ids[0]
    band_names = _band_names(world, target)
    assert len(band_names) >= 3, (
        "fixture bug: the prior administration's criterion needs three bands "
        "for a non-degenerate pair set"
    )
    prior_ids = []
    for i, (system, teacher) in enumerate([
        (band_names[1], band_names[1]),
        (band_names[1], band_names[2]),
        (band_names[2], band_names[2]),
        (band_names[0], band_names[0]),
    ]):
        prior_ids.append(record_label(
            data_dir=world.data_dir,
            label=LabelRecord(
                label_id=f"tc-e2e-03-prior-{i}",
                label_type="blind",
                saw_system_output=0,
                routing="queued",
                origin="blind_sample",
                evaluation_mode="judged",
                review_seconds=120.0,
                system_band=system,
                teacher_band=teacher,
                actor="teacher",
                timestamp="2026-09-10T06:00:00+00:00",
                score_id=None,
                criterion_id=target,
                review_queue_action=None,
                new_points=None,
            ),
            cohort_id="coh-prior",
        ))
    assert all(prior_ids)
    prior_stats = open_stats(world.data_dir)
    prior_update = prior_stats.promote(
        cohort_id="coh-prior", package_version=world.version)
    assert prior_update.blind_count == len(prior_ids) == prior_update.n
    assert prior_update.agreement_kappa is not None, (
        f"the prior administration's record carries kappa "
        f"{prior_update.agreement_kappa!r} - the carry-forward risk below is "
        "live only against a figure that exists"
    )
    prior_kappa = prior_update.agreement_kappa

    # The current administration: the teacher does none of it. The skip is the
    # administration's honest record of the absence (FR-REVIEW-13), and it is
    # idempotent - skipping twice skips once.
    service = open_review(
        world.data_dir, run_id=E2E_COHORT_ID, actor="teacher", seed=14404)
    report = service.skip_blind_sample(E2E_COHORT_ID)
    assert report.reported is True
    assert report.current_figure is None, (
        f"the skip report presents {report.current_figure!r} as the current "
        "figure - the honest None, whatever an earlier administration produced "
        "(FR-REVIEW-13, RISK-08)"
    )
    assert "no new validation evidence" in report.message
    again = service.skip_blind_sample(E2E_COHORT_ID)
    assert again.reported is True and again.current_figure is None
    with pytest.raises(ReviewError):
        service.blind_sample(E2E_COHORT_ID, n=15)

    # Grades finalize anyway: the window lapses over them, and the settlement
    # pass settles them in place - no teacher action, no batch call, no
    # amendment (the disclosed `backdate_grades` seam is the lapse).
    backdate_grades(world.handle, _hours_ago(LAPSED_HOURS))
    open_grade(world.store).compute_all(world.run_id)
    states = _grade_states(world)
    assert states.get("final", 0) > 0 and "provisional" not in states, (
        f"the grades read {states} after the lapse - finalization happens "
        "anyway at window lapse, with no teacher action (FR-REVIEW-13's "
        "grades-deliver half, CT-GRADE-09, HLD R60)"
    )

    # The validation record does NOT advance: no blind labels were collected,
    # so the record counts none and carries no figure (FR-STATS-11, CT-STATS-05).
    update = open_stats(world.data_dir).promote(
        cohort_id=E2E_COHORT_ID, package_version=world.version)
    assert update.blind_count == 0 and update.n == 0, (
        f"the record counted blind {update.blind_count}/n {update.n} for an "
        "administration that collected nothing"
    )
    assert update.message == NO_NEW_VALIDATION_EVIDENCE, (
        f"the record's message is {update.message!r} - the absence is a "
        "first-class value, not an empty figure (FR-STATS-11)"
    )
    assert update.agreement_kappa is None, (
        f"the record advanced a figure ({update.agreement_kappa!r}) for an "
        "administration with no blind labels - nothing that cannot support a "
        "validity claim reaches one (CT-STATS-05)"
    )

    # The console reports the absence for THIS administration and never a prior
    # figure in its place (FR-CONSOLE-24) - the prior kappa above is what would
    # be carried forward if the block were dishonest.
    rendered = render_agreement_block(
        no_new_evidence=True,
        previous_administration=prior_update,
        population=E2E_COHORT_ID,
    )
    assert NO_NEW_VALIDATION_EVIDENCE in rendered, (
        f"the block rendered {rendered!r} - the absence sentence is the "
        "first-class value the clause names"
    )
    assert "kappa" not in rendered.lower() and str(prior_kappa) not in rendered, (
        f"the block rendered a prior figure ({rendered!r}) - a previous "
        "administration's number in the current administration's position is "
        "the silent carry-forward RISK-08 arrives through"
    )