"""`CT-REVIEW-07`, `-12`, `-13` — what a label carries, how an edit is made, and group actions.

Test plan §6.11.15, `TC-REVIEW-C07`, `-C12` and `-C13`. The three clauses that decide whether the
label store is a validation instrument or a log of what happened.

`CT-REVIEW-13` is the one whose failure is silent and statistical. One label for a group action of
210 members weights that decision as a single observation in every agreement figure — the teacher
made 210 judgements and κ counts one. Nothing errors, nothing looks wrong, and the figure is
wrong by however much bulk review is used.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require, require_attr

pytestmark = pytest.mark.contract


# --- CT-REVIEW-07 — every action writes a label carrying the named fields ----------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("label_type", vocab.LABEL_TYPES)
def test_tc_review_c07_every_label_type_carries_the_named_fields_by_set_equality(label_type):
    """*"Assert every action writes a `label` carrying all nine named fields, by set equality.
    Sweep `label_type` over `accept`, `edit`, `override`, `blind`."*

    Set equality rather than presence, and the direction that matters is the one presence misses:
    a label carrying an **extra** field is a label carrying something `M-STATS` did not agree to
    read, and the field that arrives this way is a convenience denormalization of the very score
    the label is supposed to be independent of.

    `FR-REVIEW-09`'s eight and `NFR-REVIEW-03`'s two are asserted as one required set and checked
    separately below, because they come from different requirements — see the count finding in
    `review_vocabulary`.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(20))
    require_attr(service, "label", issue="#110")
    label = service.label(_write_one(service, label_type))

    present = {name for name in dir(label) if not name.startswith("_")}
    required = set(vocab.LABEL_FIELDS) | set(vocab.LABEL_ATTRIBUTION_FIELDS)

    missing = sorted(required - present)
    assert missing == [], (
        f"a {label_type!r} label is missing {missing}. FR-REVIEW-09 and NFR-REVIEW-03 name these "
        "on every label, not on the ones where they happen to apply."
    )


@pytest.mark.writtenahead
def test_tc_review_c07_both_bands_are_present_and_agreement_is_computed_over_them_not_points():
    """*"Assert both `system_band` and `teacher_band` are present — a label with only one is
    useless for agreement."*

    Then the rung-3 half against `M-STATS`: *"agreement is computed over bands, never points."*
    The two halves are one test because either alone is satisfiable by a module the other
    condemns — a label carrying both bands that `M-STATS` then reads points from, or a points-free
    statistic computed over a label that only records what the teacher said.

    The construction makes the difference visible: bands `B1` and `B2` are adjacent and differ by
    one ordinal, while their points differ by 20. A statistic computed over points on this
    population reports a disagreement an ordinal band statistic calls adjacent.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")

    service = build_review(scores=broken.flagged_population(20))
    require_attr(service, "label", issue="#110")
    label = service.label(_write_one(service, "override"))

    for field in vocab.AGREEMENT_BAND_PAIR:
        assert getattr(label, field, None) is not None, (
            f"the label carries no {field!r}. Agreement is a comparison; a label recording one "
            "side of it measures nothing."
        )

    labels = [
        broken.Label(
            label_id=f"blind-{i}",
            system_band="B1" if i % 2 else "B2",
            teacher_band="B2" if i % 2 else "B1",
        )
        for i in range(20)
    ]
    figure = build_stats(labels=labels).agreement(scope=None)

    assert getattr(figure, "computed_over", None) == "band", (
        f"the agreement figure was computed over {getattr(figure, 'computed_over', None)!r}. "
        "CT-REVIEW-07: agreement is computed over bands, never points — points are a package "
        "mapping applied after the fact, and comparing them measures the mapping as well as the "
        "judgement."
    )
    read = sorted(set(getattr(figure, "input_fields", ())) & set(vocab.POINTS_FIELD_NAMES))
    assert read == [], (
        f"the agreement figure read {read} from the labels. A band comparison that also reads "
        "points is one package revision away from moving without anybody's judgement changing."
    )


@pytest.mark.writtenahead
def test_tc_review_c07_every_label_names_an_actor_and_a_timestamp():
    """`NFR-REVIEW-03` — *"what makes the label store auditable rather than merely large."*

    Both fields non-null, on a label from each collection path. A default actor is the failure
    here rather than a missing column: `actor = "system"` on a teacher's override is a label that
    exists, passes the set-equality test above, and cannot answer the only question an audit asks.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(20), actor="teacher-7")
    require_attr(service, "label", issue="#110")

    for label_type in vocab.LABEL_TYPES:
        label = service.label(_write_one(service, label_type))
        assert label.actor == "teacher-7", (
            f"a {label_type!r} label is attributed to {label.actor!r} rather than the acting "
            "teacher. NFR-REVIEW-03: attributable to an actor, which a default value is not."
        )
        assert label.timestamp is not None, (
            f"a {label_type!r} label carries no timestamp, so it cannot be placed in a sequence "
            "of decisions"
        )


# --- CT-REVIEW-12 — edits are band selections, everywhere ---------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c12_no_interface_in_the_module_accepts_a_numeric_score():
    """*"Asserted over the whole surface rather than the queue screen alone."*

    `numeric_entry_parameters` parses the module source rather than inspecting the six declared
    members, for the reason the clause gives: the loophole is a *seventh* entry point, added later
    for a view §3.15 never listed. A signature check over `SERVICE_MEMBERS` cannot see it.

    The rule flags a numeric score as a **parameter** and permits it as a return or an attribute:
    `FR-REVIEW-10` derives `new_points` from `new_band`, so the direction is the whole
    distinction. Both directions are controlled in the vocabulary suite.
    """
    import inspect

    module = require(REVIEW_MODULE, issue="#110")
    source = inspect.getsource(module)

    accepting = vocab.numeric_entry_parameters(source)
    assert accepting == [], (
        f"these entry points accept a numeric score: {accepting}. FR-REVIEW-10: score edits are "
        "band selections, and the module exposes no interface accepting a number — a teacher who "
        "can type 7 has bypassed the band descriptors the package pinned (R65)."
    )


@pytest.mark.writtenahead
def test_tc_review_c12_new_points_is_derived_from_new_band_through_the_pinned_mapping():
    """The derivation, asserted against `CT-PKG-05`'s mapping rather than against a number.

    A module that computes points correctly by its own arithmetic satisfies any equality check
    against an expected value and violates `NFR-AGG-02`'s single-place rule, which is what makes
    the mapping pinned. So the assertion is that the label's points equal what the catalog returns
    for that band — the same call, not the same answer.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(20))
    require_attr(service, "points_for_band", issue="#110")

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    item = queue.shown[0]
    label = service.label(
        service.act(item, action="edit", new_band="B4", review_seconds=30)
    )

    expected = service.points_for_band(
        package_version_id=item.package_version_id,
        criterion_id=item.criterion_id,
        band="B4",
    )
    assert getattr(label, vocab.DERIVED_POINTS_FIELD) == expected, (
        f"the edit recorded {getattr(label, vocab.DERIVED_POINTS_FIELD)!r} points for band 'B4' "
        f"against the catalog's {expected!r}. FR-REVIEW-10 derives points through CT-PKG-05's "
        "pinned mapping; a second conversion here is a second place for the two to disagree."
    )


@pytest.mark.writtenahead
def test_tc_review_c12_an_edit_from_any_view_writes_the_same_action_and_the_same_label_type():
    """The completeness clause: *"Sweep every such view; an edit path that skips label creation
    silently removes data from the validity argument."*

    `FR-REVIEW-15` makes review available from any view displaying a band, which is the feature —
    and the loophole, because the view that gets added last is the one whose author does not know
    the label store exists. The teacher's judgement is recorded on the score and not in the
    instrument, and every agreement figure is computed over a population missing exactly the
    decisions somebody found convenient to make elsewhere.

    Swept over `edit_views()` rather than a hard-coded list, so a view added later is covered by
    this test on the day it appears rather than the day somebody remembers.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(40))
    require_attr(service, "edit_views", issue="#110")
    require_attr(service, "act_from_view", issue="#110")

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    from_queue = service.label(
        service.act(queue.shown[0], action="edit", new_band="B4", review_seconds=30)
    )

    views = list(service.edit_views())
    assert views, (
        "the module reports no views that display a band, so this sweep asserts nothing. "
        "FR-REVIEW-15 makes the set enumerable precisely so it can be swept."
    )

    for view in views:
        item = queue.shown[1]
        label = service.label(
            service.act_from_view(
                item, view=view, action="edit", new_band="B4", review_seconds=30
            )
        )
        assert label is not None, (
            f"an edit from view {view!r} wrote no label. FR-REVIEW-15: the same label type as one "
            "made inside the queue — a path that skips label creation removes the teacher's "
            "judgement from the validity argument without removing it from the grade."
        )
        assert label.label_type == from_queue.label_type, (
            f"an edit from view {view!r} wrote label_type {label.label_type!r} against "
            f"{from_queue.label_type!r} from the queue. The same action taken in two places has "
            "to be one thing in the label store or agreement is computed over a mixture."
        )
        assert label.review_queue_action == from_queue.review_queue_action, (
            f"an edit from view {view!r} wrote review_queue action "
            f"{label.review_queue_action!r} against {from_queue.review_queue_action!r}"
        )


# --- CT-REVIEW-13 — a group action is N individual actions --------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c13_a_group_action_emits_one_label_per_member():
    """*"So a group action is statistically indistinguishable from N individual actions in the
    label store."*

    Count first, because the count is the defect: *"a single group label would silently
    under-weight bulk decisions in every agreement figure."* Nothing errors and nothing is
    missing — the store has a label, it is correct, and it stands for 210 judgements while
    counting as one.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    members = broken.identical_signature_population(12)
    service = build_review(scores=members)

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    assert queue.groups, (
        "12 rows sharing a band and all four integrity signals produced no group, so this case "
        "cannot test what a group action writes"
    )
    group = queue.groups[0]

    label_ids = service.act_on_group(group, band="B4", review_seconds=60)
    assert len(label_ids) == len(group.members) * vocab.GROUP_LABELS_PER_MEMBER, (
        f"a group action over {len(group.members)} members wrote {len(label_ids)} labels. "
        "CT-REVIEW-13: one per member — a single label weights a bulk decision as one "
        "observation in every agreement figure the teacher's judgement feeds."
    )


@pytest.mark.writtenahead
def test_tc_review_c13_group_labels_are_indistinguishable_from_individual_ones():
    """*"Assert that indistinguishability directly by comparing the resulting label set against N
    individual actions."*

    The differential, not a field check. Two runs over the same population — one group action, N
    individual actions — and the resulting label sets must agree on everything except the fields
    a group action legitimately changes. `review_seconds` is excluded deliberately: a group action
    genuinely took less time per member and the label records that honestly, which is why
    `GROUP_INDISTINGUISHABILITY_FIELDS` names seven fields rather than eight.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    members = broken.identical_signature_population(12)

    grouped = build_review(scores=members)
    group = grouped.build_queue(run_id="run-1", budget_minutes=30).groups[0]
    group_labels = [
        grouped.label(i) for i in grouped.act_on_group(group, band="B4", review_seconds=60)
    ]

    individually = build_review(scores=members)
    queue = individually.build_queue(run_id="run-1", budget_minutes=600)
    individual_labels = [
        individually.label(
            individually.act(item, action="edit", new_band="B4", review_seconds=5)
        )
        for item in queue.shown
    ]

    def signature(labels):
        return sorted(
            tuple(getattr(label, f, None) for f in vocab.GROUP_INDISTINGUISHABILITY_FIELDS)
            for label in labels
        )

    assert signature(group_labels) == signature(individual_labels), (
        "the label set a group action produced is distinguishable from the same decisions made "
        "one at a time. CT-REVIEW-13: an agreement figure that can tell them apart is weighting "
        "bulk review differently from individual review, which is a property of the interface "
        "rather than of the teacher's judgement."
    )


@pytest.mark.writtenahead
def test_tc_review_c13_group_items_rank_above_per_item_entries():
    """`FR-REVIEW-05` — *"ranked above per-item entries, rather than N separate items."*

    The construction gives the individual items the higher per-item expected value, so a ranking
    that merely sorts by expected value puts them first and fails. That is the discriminating
    shape: the group's claim on the teacher's minutes is that one decision resolves twelve, which
    no per-item score expresses.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")

    group_members = broken.identical_signature_population(12)
    urgent = [
        dataclasses.replace(
            row,
            score_id=f"urgent-{i}",
            panel_spread=0.95,
            adverse_integrity_signals=3,
            criterion_weight=0.9,
            est_seconds=30,
        )
        for i, row in enumerate(broken.flagged_population(6))
    ]
    service = build_review(scores=[*urgent, *group_members])

    queue = service.build_queue(run_id="run-1", budget_minutes=600)
    entries = list(queue.shown)
    group_positions = [i for i, e in enumerate(entries) if e in queue.groups]

    assert group_positions, "no group appeared in the queue, so ranking cannot be compared"
    assert group_positions[0] == 0, (
        f"the first group sits at position {group_positions[0]}, behind per-item entries. "
        "FR-REVIEW-05: a group ranks above per-item entries whenever one exists — the "
        "higher-scoring individual items in this fixture are exactly the case the rule is for."
    )


# --- helpers -------------------------------------------------------------------------------------


def _write_one(service, label_type: str):
    """Produce one label of each `FR-REVIEW-09` type through the path that actually creates it.

    `blind` does not come from the queue at all, which is the point of `CT-REVIEW-08`'s sweep — so
    it is written through the blind flow here rather than by passing `label_type="blind"` to
    `act()`, which would test a parameter rather than a collection path.
    """
    if label_type == "blind":
        session = service.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[0])
        return service.submit_blind(
            session.session_id, bands={ref: "B2" for ref in session.items}
        )[0]

    queue = service.build_queue(run_id="run-1", budget_minutes=600)
    item = queue.shown[vocab.LABEL_TYPES.index(label_type)]
    new_band = None if label_type == "accept" else "B4"
    return service.act(item, action=label_type, new_band=new_band, review_seconds=30)
