"""`CT-REVIEW-08` — `saw_system_output` separates a validity claim from an operational signal.

Test plan §6.11.15, `TC-REVIEW-C08`, block form. A §4.7 **safety property**: the field the entire
validity argument rests on, and the one whose corruption has no symptom.

The four steps the block form names are four assertions here, kept separate on purpose. Step 1
(populated everywhere, no null) and step 2 (the right value on *every* collection path) live in
this module; steps 3 and 4 are the enforcement, which the clause locates at the consumer —
`M-STATS` filters **from this column**, not from a naming convention or a table split — so they
are asserted against `M-STATS` at rung 3.

The adversarial construction is the reason the case is worth its length. Setting
`saw_system_output = 0` for queue actions where the teacher **overrode** the system is a change
somebody makes for a *good* reason — an override does show independent judgment — and it turns
every `FR-REVIEW-*` case green while κ rises and the validity claim strengthens. HLD §0.8's
thesis is that every available bias makes the numbers look better; this is that thesis in one
field.
"""

from __future__ import annotations

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require, require_attr

pytestmark = pytest.mark.contract


# --- step 1: populated on every label, with no default and no null ---------------------------


@pytest.mark.writtenahead
def test_tc_review_c08_saw_system_output_is_populated_on_every_label_with_no_null():
    """*"A null here is indistinguishable from a 0 at query time and would admit contaminated
    labels silently."*

    The assertion is `is not None` **and** membership in `{0, 1}`, not truthiness. A label whose
    `saw_system_output` is `None` is falsy, so a filter written as `if not label.saw_system_output`
    admits it — which is precisely the "indistinguishable from a 0" the block form warns about,
    and a truthiness assertion here would reproduce the bug rather than catch it.

    Swept over every `label_type` in `FR-REVIEW-09`'s domain, because the failure is one path
    defaulting wrongly rather than the field being absent everywhere.
    """
    record_label, labels_for = require(
        REVIEW_MODULE, "record_label", "labels_for", issue="#110"
    )

    for label_type in vocab.LABEL_TYPES:
        record_label(
            run_id="run-1",
            score_id=f"score-{label_type}",
            label_type=label_type,
            teacher_band="B2",
            review_seconds=30,
        )

    written = list(labels_for(run_id="run-1"))
    assert len(written) == len(vocab.LABEL_TYPES), (
        f"{len(written)} labels for {len(vocab.LABEL_TYPES)} actions, so the sweep below is not "
        "covering every collection path"
    )

    for label in written:
        value = getattr(label, vocab.ADMISSIBILITY_COLUMN, None)
        assert value is not None, (
            f"a {label.label_type!r} label carries {vocab.ADMISSIBILITY_COLUMN} = None. "
            "CT-REVIEW-08: a null is indistinguishable from a 0 at query time, so it admits a "
            "contaminated label into an agreement statistic silently."
        )
        assert value in (0, 1), (
            f"a {label.label_type!r} label carries {vocab.ADMISSIBILITY_COLUMN} = {value!r}, "
            "which is neither 0 nor 1 — the column M-STATS filters on has to be a decidable flag"
        )


# --- step 2: the right value on every collection path ----------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c08_every_collection_path_writes_the_correct_saw_system_output_value():
    """The sweep the block form asks for: *"every path that can create a label"*, four of them.

    Queue actions set it to 1; blind-flow actions set it to 0; edits from other views
    (`CT-REVIEW-12`) set it to 1; a group action is N queue actions (`CT-REVIEW-13`) and carries
    the queue value. The values come from `SAW_SYSTEM_OUTPUT_BY_PATH` so a path added later has
    somewhere to be declared, and a failure names the path rather than the field.

    Asserting the paths **together** matters more than asserting any one of them: three correct
    paths and one wrong one is the shape this defect actually takes, and a per-path test that
    somebody forgets to extend leaves the new path unchecked.
    """
    service = require(REVIEW_MODULE, "build_review", issue="#108")(
        scores=broken.flagged_population(12)
    )
    require_attr(service, "act_from_view", issue="#110")

    produced: dict[str, object] = {}  # collection path -> the LabelId it returned

    item = service.build_queue(run_id="run-1", budget_minutes=30).shown[0]
    produced["queue_action"] = service.act(
        item, action="accept", new_band=None, review_seconds=20
    )

    # The blind flow answers **its own** items. Submitting the queue item here would ask the
    # session to record a band for a criterion it never drew, which a correct `submit_blind`
    # refuses (CT-REVIEW-15 records only what was answered) — so the path that matters most to
    # this sweep would fail for a reason that has nothing to do with `saw_system_output`.
    session = service.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[0])
    blind_ref = list(session.items)[0]
    produced["blind_flow"] = service.submit_blind(
        session.session_id, bands={blind_ref: "B2"}
    )[0]

    # A different item: `item` was accepted above, and re-actioning a resolved item is a
    # different case (CT-REVIEW-15) that would fail here for the wrong reason.
    produced["other_view_edit"] = service.act_from_view(
        service.build_queue(run_id="run-1", budget_minutes=30).shown[1],
        view="submission_detail",
        action="edit",
        new_band="B4",
        review_seconds=15,
    )

    group = service.build_queue(run_id="run-1", budget_minutes=30).groups[0]
    produced["group_action"] = service.act_on_group(group, band="B2", review_seconds=40)[0]

    labels = {path: service.label(label_id) for path, label_id in produced.items()}

    wrong = {
        path: getattr(label, vocab.ADMISSIBILITY_COLUMN, None)
        for path, label in labels.items()
        if getattr(label, vocab.ADMISSIBILITY_COLUMN, None)
        != vocab.SAW_SYSTEM_OUTPUT_BY_PATH[path]
    }
    assert wrong == {}, (
        f"these collection paths wrote the wrong {vocab.ADMISSIBILITY_COLUMN}: {wrong}, against "
        f"the required {vocab.SAW_SYSTEM_OUTPUT_BY_PATH}. CT-REVIEW-08: one path defaulting "
        "wrongly is how a contaminated label reaches an agreement statistic."
    )


@pytest.mark.writtenahead
def test_tc_review_c08_an_override_from_the_queue_still_records_that_the_system_was_visible():
    """The block form's **adversarial construction**, asserted directly.

    *"Set `saw_system_output = 0` for queue actions where the teacher **overrode** the system, on
    the reasoning that an override shows independent judgment."* The reasoning is not stupid,
    which is why the construction is the one worth pinning: κ rises, the validity claim
    strengthens, and the figure is now built on labels anchored by the very output they are
    supposed to validate.

    This is a separate test from the sweep above because the sweep records an `accept` from the
    queue, and an implementation could special-case `override` while passing it. The construction
    names `override` specifically, so the case does too.
    """
    service = require(REVIEW_MODULE, "build_review", issue="#108")(
        scores=broken.flagged_population(12)
    )
    require_attr(service, "label", issue="#110")

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    item = queue.shown[0]
    label_id = service.act(
        item,
        action=vocab.ADVERSARIAL_OVERRIDE_LABEL_TYPE,
        new_band="B1",
        review_seconds=60,
    )
    label = service.label(label_id)

    assert label.label_type == vocab.ADVERSARIAL_OVERRIDE_LABEL_TYPE, (
        "the fixture did not produce an override label, so the construction is not being tested"
    )
    assert getattr(label, vocab.ADMISSIBILITY_COLUMN) == 1, (
        "an override made from the queue recorded saw_system_output = 0. The teacher disagreed "
        "with the system's band while looking at it — that is an operational signal, not "
        "independent judgment, and CT-REVIEW-08 is the field that keeps the two apart."
    )


# --- steps 3 and 4: the enforcement lives at the consumer ------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c08_m_stats_excludes_an_operational_label_from_agreement_and_says_how_many():
    """Steps 3 and 4, at rung 3 — the enforcement is `M-STATS`'s and the clause says so.

    Step 3 inserts a label with `saw_system_output = 1` into the population an agreement statistic
    reads and asserts it is **excluded**. Step 4 is the half that keeps the exclusion from being
    silently lossy: `M-STATS` reports the count excluded, so a run whose labels are *all*
    operational reports **no validity evidence** rather than a figure computed on fewer labels
    than the reader assumes.

    Step 4's fixture is the discriminating one. A module that filters correctly and then computes
    κ over the two survivors passes step 3 and fails here, and that is the failure the reader of
    the number would never see.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")

    admissible = [
        broken.Label(label_id=f"blind-{i}", label_type="blind", saw_system_output=0,
                     system_band=f"B{(i % 3) + 1}", teacher_band=f"B{(i % 4) + 1}")
        for i in range(20)
    ]
    operational = broken.Label(
        label_id="op-1", label_type="override", saw_system_output=1,
        system_band="B1", teacher_band="B4",
    )

    stats = build_stats(labels=admissible + [operational])
    figure = stats.agreement(scope=None)

    assert figure.n == len(admissible), (
        f"the agreement figure was computed over {figure.n} labels against "
        f"{len(admissible)} admissible ones. CT-REVIEW-08: a label with "
        "saw_system_output = 1 is not admissible, and FR-STATS-01 enforces that from this "
        "column rather than from a naming convention."
    )

    all_operational = build_stats(
        labels=[
            broken.Label(label_id=f"op-{i}", label_type="override", saw_system_output=1)
            for i in range(20)
        ]
    )
    empty = all_operational.agreement(scope=None)

    assert getattr(empty, "kappa", None) is None, (
        "a run whose labels are all operational produced an agreement coefficient. Every label "
        "was anchored by the system's own output, so there is no validity evidence here to "
        "report — CT-REVIEW-08 step 4."
    )
    assert getattr(empty, "excluded_count", None) == 20, (
        "the exclusion is silent: M-STATS dropped 20 operational labels without reporting how "
        "many. A reader then sees a figure computed on fewer labels than they assume, which is "
        "the lossiness step 4 exists to prevent."
    )
