"""`CT-CALIB-03`, `-04`, `-05`, `-11`, `-12` — what the module discovers, and what it asks.

Test plan §6.11.17, TS-74 (issue #142). Five clauses about the half of `M-CALIB` a teacher
actually meets: what the discovery output claims, how a disagreement is categorized, what an
elicitation question looks like, what is recorded, and how much of the teacher's time it costs.

The thread running through them is that the model's job **never rises above proposing a question**
(`CT-CALIB-05`). Everything here is a guard on that boundary: discovery that claimed accuracy
would make the model an assessor, a disagreement that skipped triage would let the model's own
failures rewrite the rubric, and an elicitation that presented a pre-authored edit would turn the
teacher into an approver. Each is a small drift in the same direction.

All five are red. See `test_ct_calib_vocabulary.py` for what is green and why it is not coverage.
"""

from __future__ import annotations

import pytest

from tests.support.calib_vocabulary import (
    ACCURACY_LANGUAGE,
    EDITABLE_CATEGORY,
    EXAMPLES_PER_QUESTION,
    MAX_QUESTIONS,
    TRIAGE_CATEGORIES,
)
from tests.support.impl import CALIB_MODULE, CONSOLE_MODULE, require

pytestmark = pytest.mark.contract


# --- CT-CALIB-03 — discovery is not a measurement of accuracy -------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c03_the_discovery_report_carries_no_accuracy_figure():
    """`CT-CALIB-03` — discovery output is **ambiguity discovery, never a measurement of accuracy**.

    Asserted over the **type and its fields**, not over a rendering: the clause's claim is that the
    value *cannot* be coerced into an accuracy figure, which is a property of the data structure.
    A report that carried `matched: 41, total: 50` invites the division whether or not anyone
    performs it, and the calibration set is far too small for the result to mean anything.
    `M-STATS` owns the accuracy figures that legitimately exist (`CT-STATS-01`).

    So: no field whose name reads as a rate or a correctness count, and no numeric pair from which
    one falls out. The label half is asserted too — the report says what it is.
    """
    calib = require(CALIB_MODULE, issue="#137")
    discover = require(CALIB_MODULE, "discover", issue="#137")

    report = discover(package_version="pkg-v1", calibration_papers=["s1", "s2", "s3"])

    assert report.kind == "ambiguity_discovery", (
        f"the discovery report is labelled {report.kind!r}; CT-CALIB-03 requires it to be typed "
        "and labelled as ambiguity discovery"
    )

    fields = {name.lower() for name in report.__dataclass_fields__}
    offending = sorted(
        name for name in fields
        if any(term.replace(" ", "_") in name for term in ACCURACY_LANGUAGE)
    )
    assert not offending, (
        f"the discovery report carries accuracy-shaped fields {offending}. The calibration set is "
        "too small for an accuracy claim and M-STATS owns the ones that exist (CT-STATS-01)."
    )
    assert not hasattr(report, "matched") and not hasattr(report, "total"), (
        "the report carries a matched/total pair, from which an accuracy figure falls out whether "
        "or not anyone divides — CT-CALIB-03 says the value cannot be coerced into one"
    )
    assert calib is not None


@pytest.mark.writtenahead
def test_tc_calib_c03_the_console_renders_no_accuracy_language():
    """`CT-CALIB-03`'s **consumer half**, at rung 3 and on its own blocker.

    The clause names the misuse directly: a consumer that renders discovery as *"the model was
    right 82% of the time"* has misused it. That is `M-CONSOLE`'s behaviour, so it lands at #122
    while the type assertion above lands at #137 — keying both on the later would hold the type
    assertion outside the gate for two stories.

    Asserted over the **rendered surface**, because the misuse is language rather than structure: a
    console can compute a percentage from a report that carries none, and the teacher reads the
    percentage, not the report.
    """
    console = require(CONSOLE_MODULE, issue="#122")
    render = require(CONSOLE_MODULE, "render_discovery", issue="#122")

    surface = render(package_version="pkg-v1").lower()

    found = sorted(term for term in ACCURACY_LANGUAGE if term in surface)
    assert not found, (
        f"the rendered discovery surface uses accuracy language {found}. CT-CALIB-03: a consumer "
        "rendering this as 'the model was right 82% of the time' has misused it."
    )
    assert "%" not in surface, "the discovery surface renders a percentage"
    assert console is not None


# --- CT-CALIB-04 — the triage category is required, and only one is editable ----------------------


@pytest.mark.writtenahead
def test_tc_calib_c04_a_disagreement_without_a_triage_category_is_refused():
    """`CT-CALIB-04` — the category is a **required** output field.

    The refusal is the case. An uncategorized disagreement would default into *some* path, and the
    editable path is the dangerous default: the module would fit the rubric to a disagreement
    nobody classified. Asserted as a refusal rather than as "a category is usually present",
    because "usually" is what a default looks like from outside.
    """
    calib = require(CALIB_MODULE, issue="#137")
    triage = require(CALIB_MODULE, "triage", issue="#137")

    with pytest.raises(calib.TriageCategoryRequired):
        triage(calib.Disagreement(criterion_id="c1", category=None))


@pytest.mark.writtenahead
@pytest.mark.parametrize("category", sorted(TRIAGE_CATEGORIES))
def test_tc_calib_c04_only_rubric_ambiguity_can_produce_a_proposed_edit(category):
    """`CT-CALIB-04`'s eligibility rule, one row per category — a **domain sweep**.

    Parametrized over the whole vocabulary, so the assertion is about the closed set rather than
    about the interesting member. Each category has its own required outcome and each failure has
    its own consequence:

    * **`rubric_ambiguity`** — eligible to produce a proposed edit. The only one.
    * **`teacher_inconsistency`** — surfaces **both examples side by side** and is **never fitted
      to** (`FR-CALIB-03`). Fitting here would encode one teacher's noise into the instrument
      permanently, and the instrument outlives the teacher.
    * **`model_failure`** — produces a **pipeline finding** and **no rubric edit** (`FR-CALIB-04`).
      Editing the rubric because the extractor failed changes the assessment to accommodate a bug.
    """
    calib = require(CALIB_MODULE, issue="#137")
    triage = require(CALIB_MODULE, "triage", issue="#137")

    verdict = triage(calib.Disagreement(criterion_id="c1", category=category))

    assert verdict.category == category
    if category == EDITABLE_CATEGORY:
        assert verdict.edit_eligible, f"{category} must be eligible to produce a proposed edit"
    else:
        assert not verdict.edit_eligible, (
            f"{category} produced an edit-eligible verdict. Only {EDITABLE_CATEGORY!r} is "
            "eligible (CT-CALIB-04)."
        )

    if category == "teacher_inconsistency":
        assert len(verdict.examples) == 2, (
            "teacher_inconsistency must surface both examples side by side (FR-CALIB-03) — one "
            "example is an accusation, two are a comparison the teacher can resolve"
        )
        assert not verdict.fitted, "teacher_inconsistency was fitted to"
    if category == "model_failure":
        assert verdict.pipeline_finding, (
            "model_failure must produce a pipeline finding (FR-CALIB-04)"
        )
        assert verdict.proposed_edit is None


# --- CT-CALIB-05 — a question, never a pre-authored edit ------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c05_elicitation_returns_a_question_with_options_and_no_edit():
    """`CT-CALIB-05` — a **question with options**, never a pre-authored rubric edit awaiting
    approval.

    Asserted over the **returned value's shape**, because the difference between the two is exactly
    the difference between the teacher deciding and the teacher clicking *approve*. A pre-authored
    edit shown for approval gets approved; that is what approval interfaces do, and `§10` is about
    keeping the judgement with the person who owns the instrument.

    So: options are present, and **no edit exists before the answer**. The second assertion is the
    load-bearing one — a question carrying a `proposed_edit` field that happens to be populated is
    a pre-authored edit with a question drawn on top.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")

    questions = elicit(calib.findings_fixture(count=3))

    assert questions, "elicitation produced no questions for three findings"
    for question in questions:
        assert question.options, "an elicitation question carries no options"
        assert len(question.options) >= 2, "a question with one option is not a choice"
        assert getattr(question, "proposed_edit", None) is None, (
            "an elicitation question arrived carrying a pre-authored edit. CT-CALIB-05: the "
            "teacher's answer generates the edit; the model's job never rises above proposing "
            "the question."
        )
        assert len(question.examples) == EXAMPLES_PER_QUESTION, (
            f"the question shows {len(question.examples)} examples; NFR-CALIB-01 says two, side "
            "by side"
        )


@pytest.mark.writtenahead
def test_tc_calib_c05_questions_are_capped_and_ranked_by_submissions_affected():
    """`CT-CALIB-05`'s cap and ordering, against a **hand-built fixture with known counts**.

    The cap is `CALIB_MAX_QUESTIONS` (6) — `NFR-CALIB-01`'s teacher-time budget expressed as an
    exact number, so it is asserted exactly rather than as "not too many".

    The ordering is the half that needs a fixture: questions are *"ranked by how many submissions
    the ambiguity affects"* (`FR-CALIB-05`). Asserted against known affected counts, because an
    implementation returning findings in discovery order also produces a plausible-looking list —
    and with the cap applied, the wrong order means the six questions the teacher answers are not
    the six that matter most. The cap and the ranking are one mechanism: either alone is safe,
    together they decide what gets asked.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")

    # Ten findings with distinct, known affected counts, deliberately supplied out of order.
    affected = [3, 41, 7, 19, 2, 55, 11, 28, 1, 34]
    findings = calib.findings_fixture(affected_counts=affected)

    questions = elicit(findings)

    assert len(questions) == MAX_QUESTIONS, (
        f"elicitation returned {len(questions)} questions; CALIB_MAX_QUESTIONS is {MAX_QUESTIONS} "
        "and NFR-CALIB-01's budget is that number, not approximately it"
    )

    returned = [question.submissions_affected for question in questions]
    assert returned == sorted(affected, reverse=True)[:MAX_QUESTIONS], (
        f"questions came back in the order {returned}; ranked by submissions affected they should "
        f"be {sorted(affected, reverse=True)[:MAX_QUESTIONS]}. With a cap of {MAX_QUESTIONS}, the "
        "order decides which ambiguities the teacher never sees."
    )


# --- CT-CALIB-11 — elicitation_history is append-only ---------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c11_elicitation_history_refuses_updates_and_deletes_at_the_store():
    """`CT-CALIB-11` — append-only, asserted **at the store level, not the application level**.

    That distinction is the case. An application that simply never calls update is append-only by
    convention, and a convention is not a guarantee — `FR-PKG-20` and `NFR-PKG-01` both say the
    enforcement belongs in the data layer, so *"violation is a failed write rather than a code
    review finding"*. So the assertion is an attempted update and an attempted delete, each
    refused by the store.

    Rung 2: a real database, because a refusal that only exists in a double proves nothing about
    the schema.
    """
    calib = require(CALIB_MODULE, issue="#138")
    history = calib.elicitation_history_for_test()

    row_id = history.append(question="q1", options=["a", "b"], answer="a", edit="e1")

    with pytest.raises(history.AppendOnlyViolation):
        history.update(row_id, answer="b")
    with pytest.raises(history.AppendOnlyViolation):
        history.delete(row_id)


@pytest.mark.writtenahead
def test_tc_calib_c11_the_history_alone_answers_why_the_rubric_says_this_now():
    """`CT-CALIB-11`'s stated purpose, asserted as a **reconstruction**.

    The clause says what the record is *for*: it answers *"why does the rubric say this now"*. A
    history that recorded answers but not the options offered, or edits but not the question that
    produced them, is append-only and useless — it satisfies the storage claim and fails the
    purpose.

    So the case reconstructs that answer from the history **alone** for a multi-edit fixture: three
    edits, and for each one the question asked, the options offered and the answer given must be
    recoverable without consulting the package, the findings or the module.
    """
    calib = require(CALIB_MODULE, issue="#138")
    history = calib.elicitation_history_for_test()

    asked = [
        ("q1", ["broaden", "narrow"], "broaden", "edit-1"),
        ("q2", ["merge", "split"], "split", "edit-2"),
        ("q3", ["keep", "clarify"], "clarify", "edit-3"),
    ]
    for question, options, answer, edit in asked:
        history.append(question=question, options=options, answer=answer, edit=edit)

    rows = history.all()

    assert len(rows) == len(asked)
    for (question, options, answer, edit), row in zip(asked, rows):
        assert row.question == question
        assert list(row.options) == options, (
            "the options offered were not recorded, so the history cannot say what the teacher "
            "was choosing between — which is most of the answer to 'why does the rubric say this'"
        )
        assert row.answer == answer
        assert row.edit == edit


# --- CT-CALIB-12 — teacher time, and the cost that must be disclosed ------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c12_the_teacher_answers_at_most_six_questions_from_two_examples_each():
    """`CT-CALIB-12` / `NFR-CALIB-01` — teacher time is minutes, as an **interaction count**.

    Two exact numbers rather than a duration, because a duration is unmeasurable in a test and the
    design already expressed the budget as counts: at most six questions, each answerable from two
    student examples shown side by side. The per-question payload is the half that makes the count
    honest — six questions each requiring the teacher to read the whole class is not minutes.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")

    questions = elicit(calib.findings_fixture(count=20))

    assert len(questions) <= MAX_QUESTIONS
    for question in questions:
        assert len(question.examples) == EXAMPLES_PER_QUESTION, (
            f"a question offers {len(question.examples)} examples; NFR-CALIB-01 says two, and a "
            "question needing more is not answerable in the stated budget"
        )


@pytest.mark.writtenahead
def test_tc_calib_c12_the_dual_scoring_cost_is_disclosed_before_the_pass_is_authorized():
    """`CT-CALIB-12`'s cost disclosure — **before** authorization, not after.

    `NFR-CALIB-03`: dual-scoring costs *"one additional full-class scoring pass and shall be
    budgeted as such"*. The clause's word is **budgeted**, and a cost discovered afterwards was
    never budgeted — it was incurred. On `cloud-hosted` that is a second full-class pass against a
    metered provider, which is the operator's money.

    So two assertions: the call count really is one additional full-class pass, and the figure is
    surfaced **before** the operator authorizes it. The ordering is the assertion — a disclosure
    that arrives with the invoice is a receipt.
    """
    calib = require(CALIB_MODULE, issue="#139")
    plan = calib.plan_dual_scoring(cohort_id="c-1", r0="pkg-v1", r1="pkg-v2")

    assert plan.disclosed_before_authorization, (
        "the dual-scoring cost was not surfaced before authorization. NFR-CALIB-03 says it must "
        "be *budgeted*, and a cost discovered afterwards was incurred rather than budgeted."
    )
    assert plan.additional_full_class_passes == 1, (
        f"the plan declares {plan.additional_full_class_passes} additional full-class passes; "
        "NFR-CALIB-03 says one"
    )
    assert plan.estimated_calls == plan.class_size * plan.criteria_count, (
        "the disclosed call count is not one full-class pass, so the figure the operator "
        "authorizes is not the cost they will pay"
    )
