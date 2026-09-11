"""`TC-CALIB-03` — teacher inconsistency is surfaced side by side and never fitted to.

Test plan §5.17, `TC-CALIB-03` (FR-CALIB-03, Integration / rung 2).

The contract suite carries the pair's shape (`TC-CALIB-C04`: a `teacher_inconsistency` verdict
carries exactly two examples) — but asserted over a **hand-built** disagreement whose examples
nobody derived from a discovery run. What no green test carried before this file is the
material arriving from discovery itself: the teacher graded the same criterion differently on
two samples, and those repeat labels — not the disagreement with the panel — are what triage
shows the teacher side by side:

* the verdict's examples are **exactly** the teacher's own differing labels, `((paper, band),
  (paper, band))`, straight from a real `discover()` run — not invented fixtures, and not the
  panel's bands;
* `fitted` reads False and an edit attachment is refused (`EditNotEligible`) — the fitting
  prohibition, at the constructor;
* the pair's shape is enforced at the value (`SideBySideRequired`) — one example is an
  accusation, two are a comparison;
* the non-editable categories produce no elicitation questions — the side-by-side material and
  the pipeline finding never become a question the teacher answers to fit the rubric.

All transports are the injected seams (recorded bands); nothing here touches the socket guard.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.support.impl import CALIB_MODULE, require


def _categorized_as_teacher_inconsistency(calib, report):
    """The fixture's single disagreement, carrying the triage category the triage conversation
    assigned it.

    Discovery emits disagreements uncategorized (`category=None` — categorizing is triage's
    judgement, TC-CALIB-02), and `triage()` refuses one that arrives still blank. The category
    is assigned here with `dataclasses.replace`, which is exactly the hand-off the pipeline
    describes: discovery identifies, the conversation categorizes, `triage()` records."""
    (disagreement,) = report.disagreements
    return dataclasses.replace(disagreement, category="teacher_inconsistency")


def _discovery_fixture(calib):
    """A real discovery run whose single disagreement carries the teacher's own differing
    repeat labels.

    Two papers, two criteria, model bands recorded under R₀. The teacher read c1 differently
    across the two samples ('3' on p1, '2' on p2) — repeat labels on the same criterion — and
    disagrees with the panel on p1/c1. c2 agrees everywhere, so the run identifies exactly one
    disagreement and its examples are the teacher's own c1 labels.
    """
    return calib.discover(
        package_version="pkg-v1-r0",
        calibration_papers=["p1", "p2"],
        teacher_bands={
            "p1": {"c1": "3", "c2": "2"},
            "p2": {"c1": "2", "c2": "2"},
        },
        model_bands={
            "p1": {"c1": "2", "c2": "2"},
            "p2": {"c1": "2", "c2": "2"},
        },
    )


# --- the pair, from a real discovery run ----------------------------------------------------------


def test_tc_calib_03_the_verdicts_examples_are_the_teachers_own_differing_labels():
    """The side-by-side pair arrives from discovery's repeat labels, exactly.

    The teacher's labels for c1 differ across p1 and p2 — ('3', then '2') — and those two, in
    the order the papers were graded, are the pair. The fixture fails unless the examples are
    *both* the teacher's: the panel's band ('2') on p1/c1 is deliberately absent from them,
    because the comparison the teacher is shown is their own two readings, not a debate with
    the model.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "discover", "triage", issue="#140")

    report = _discovery_fixture(calib)
    identified = [
        (d.criterion_id, d.sample_id, d.teacher_band, d.model_band)
        for d in report.disagreements
    ]
    assert identified == [("c1", "p1", "3", "2")], (
        f"the fixture's single disagreement is p1/c1 (teacher '3' against the panel's '2'); "
        f"discovery identified {identified}"
    )

    (disagreement,) = report.disagreements
    assert disagreement.examples == (("p1", "3"), ("p2", "2")), (
        f"the disagreement's examples are {disagreement.examples!r}; the teacher's own "
        "differing c1 labels are (('p1', '3'), ('p2', '2')) — the material FR-CALIB-03 "
        "surfaces side by side, attached by the discovery run and not by this test"
    )

    verdict = calib.triage(_categorized_as_teacher_inconsistency(calib, report))
    assert verdict.category == "teacher_inconsistency"
    assert verdict.examples == (("p1", "3"), ("p2", "2")), (
        f"triage surfaced {verdict.examples!r} side by side; the exact pair from the "
        "teacher's repeat labels is what the teacher must see to resolve the "
        "inconsistency (FR-CALIB-03)"
    )
    assert verdict.fitted is False, "teacher_inconsistency was fitted to"
    assert verdict.edit_eligible is False, (
        "teacher_inconsistency produced an edit-eligible verdict — only rubric_ambiguity is "
        "eligible (CT-CALIB-04), and fitting to the teacher's own inconsistency is the "
        "instrument encoding one teacher's noise permanently"
    )


def test_tc_calib_03_an_edit_on_the_side_by_side_verdict_is_refused():
    """`EditNotEligible` — the verdict that exists cannot carry an edit, structurally.

    The prohibition is asserted at the constructor with the pair the discovery run produced,
    and again through the eligibility sweep's shape: `proposed_edit=None` is the only lawful
    value on this category. A verdict that carried the edit would be `fitted` true — the
    property exists to turn that future relaxation into a failing assertion.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "triage", "TriageVerdict", "EditNotEligible", issue="#140")

    report = _discovery_fixture(calib)
    verdict = calib.triage(_categorized_as_teacher_inconsistency(calib, report))

    with pytest.raises(calib.EditNotEligible):
        calib.TriageVerdict(
            criterion_id=verdict.criterion_id,
            category="teacher_inconsistency",
            examples=verdict.examples,
            proposed_edit="descriptor: 'clear' -> 'well structured'",
        )


def test_tc_calib_03_one_example_is_not_a_pair_the_constructor_refuses_it():
    """`SideBySideRequired` — one example is an accusation, two are a comparison.

    `triage()` normalizes the material to the pair (padding the unfilled slot with None so the
    surface is visible as incomplete rather than pretending to be complete); the value's own
    constructor refuses any other count. Asserted directly, because that is the structural
    half: a verdict that exists with one example shows the teacher an accusation and calls it
    a comparison.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "triage", "TriageVerdict", "SideBySideRequired", issue="#140")

    for shape in (
        (("p1", "3"),),                       # one example: an accusation
        (("p1", "3"), ("p2", "2"), ("p3", "4")),  # three: not the pair's shape
        (),                                   # none at all
    ):
        with pytest.raises(calib.SideBySideRequired):
            calib.TriageVerdict(
                criterion_id="c1", category="teacher_inconsistency", examples=shape
            )

    # The pair triage() itself produces is lawful and complete: the fixture's discovery run
    # collected two labels, so both slots are filled.
    report = _discovery_fixture(calib)
    verdict = calib.triage(_categorized_as_teacher_inconsistency(calib, report))
    assert len(verdict.examples) == 2
    assert all(example is not None for example in verdict.examples), (
        "the pair arrived with an unfilled slot; the fixture's discovery run collected two "
        "labels, so the pad path is not what produced this verdict — if you are seeing this, "
        "the fixture or the padding moved and the pair is no longer the teacher's two labels"
    )


def test_tc_calib_03_the_non_editable_categories_elicit_no_questions():
    """Findings from `teacher_inconsistency` and `model_failure` produce zero questions.

    `elicit()` turns edit-eligible findings into questions; these two categories are not
    eligible, and the assertion is that nothing about them reaches the teacher as a question —
    the side-by-side material is shown at triage, and the pipeline finding routes a failure to
    a stage, but neither is an ambiguity the rubric can be edited around. A question generated
    from either would be the fit FR-CALIB-03 forbids, arriving through elicitation's door
    instead.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "elicit", "Finding", issue="#140")

    questions = calib.elicit(
        [
            calib.Finding(
                criterion_id="c1",
                category="teacher_inconsistency",
                submissions_affected=9,
                examples=("p1", "p2"),
            ),
            calib.Finding(
                criterion_id="c2",
                category="model_failure",
                submissions_affected=4,
            ),
        ]
    )

    assert questions == (), (
        f"elicit() asked {len(questions)} question(s) from non-editable findings — the "
        "side-by-side material and the pipeline finding are triage surfaces, not rubric "
        "edit input, and a question generated from either is the fit FR-CALIB-03 forbids"
    )