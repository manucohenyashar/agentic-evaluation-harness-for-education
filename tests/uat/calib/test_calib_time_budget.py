"""`M-CALIB`'s teacher-time budget, rung 4 — `TC-CALIB-17` and `UAT-03` (issue #141).

Test plan §5.17 / §6.3: one teacher, one assessment — a rubric carrying known
ambiguities, and calibration that is a short conversation, not a project
(`NFR-CALIB-01`, `NFR-SYS-07`).

The path is the headless one: `elicit` and `apply_answers` over a real Tier P package —
seven criteria, the shape of a real assessment rubric, each published with two bands, one
ambiguity per criterion so the cap has a real decision to make. The store and the catalog
are real; nothing else stands in for the teacher's session.

Disclosures the plan's wording forces (the `TC-SETUP-21`/`UAT-02` rung-4 file is the
template):

- **The question count is the gate.** `NFR-CALIB-01` / `NFR-SYS-07` bound teacher time
  *structurally*: at most six questions — asserted exactly over seven candidates, so an
  implementation that asks one question per ambiguity fails here; only the cap makes the
  count 6. The asked set is pinned too: the six most-affected ambiguities, not a
  truncation of discovery order.
- **The 15-minute ceiling is reported, not machine-gated** (the `TC-INGEST-47` pattern,
  carried through #55's rung-4 file): the conversation is timed with `time.perf_counter`
  around the whole flow, the measurement is printed and embedded in the assertion
  messages, and the only timing assertion is `elapsed > 0`. The budget belongs to a
  teacher working at human speed — reading two student examples per question, deciding,
  answering; a CI box's wall clock measures the machine, not the teacher, and gating on
  it would make the suite flake on slow hardware rather than catch a wrong interaction
  count.
- **UAT-03's "the teacher agrees each question was about their rubric rather than about
  the model"** is pinned to the observables that exist today and §3.6/§5.17 keep stable:
  each question names a criterion the teacher's rubric actually carries, its text asks
  about that criterion's descriptor (broaden / narrow / keep as is — the rubric's words,
  not the model's), and the two examples shown side by side are the student responses the
  ambiguity was found on, asserted exactly per question. The console's rendering of that
  surface is the console's story, not this case's.
- **Stated bets**: the question surface (`question_id` `q1..qn`, `QUESTION_OPTIONS`, two
  examples, ranked order) and the answer vocabulary (`broaden` / `narrow` / `keep as
  is`). The builders below are the lines that move if a later story changes the package
  shape; the per-case expectations (the count, the side-by-side pair, about-the-rubric
  grounding, the measured-not-gated budget) do not.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from tests.support.calib_vocabulary import EXAMPLES_PER_QUESTION, MAX_QUESTIONS
from tests.support.impl import CALIB_MODULE, require

pytestmark = [pytest.mark.integration]

#: The teacher's rubric: seven criteria, the size a real assessment carries past the cap.
CRITERIA = tuple(f"CRIT-{n}" for n in range(1, 8))

#: The affected counts, one ambiguity per criterion, deliberately NOT in ranked order —
#: a discovery-order ask would otherwise look plausible (the `findings_fixture`
#: discipline, applied to the UAT's own data).
AFFECTED = {"CRIT-1": 13, "CRIT-2": 22, "CRIT-3": 7, "CRIT-4": 19,
            "CRIT-5": 4, "CRIT-6": 16, "CRIT-7": 10}

#: The teacher's answers, keyed by the session's question ids: two of each of the three
#: options, so the applied session walks the full option set.
ANSWERS = {
    "q1": "broaden",
    "q2": "narrow",
    "q3": "keep as is",
    "q4": "broaden",
    "q5": "keep as is",
    "q6": "narrow",
}

_DATA_DIR_PREFIX = "aeh-calib-uat-"
_PACKAGE_ID = "pkg-calib-uat"


def _open_teacher_session():
    """Build the teacher's rubric and open it as the session's working catalog.

    Returns `(store, catalog)` — seven criteria, two bands each, one published version,
    the handle open for the conversation the way a console session holds it. The caller
    owns the store's lifetime (`store.close()` in a `finally`)."""
    # The full migration chain must be imported before the first open (CLAUDE.md):
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.review  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.pkg import PackageCatalog
    from aeh.store import open_store

    data_dir = Path(tempfile.mkdtemp(prefix=_DATA_DIR_PREFIX))
    store = open_store(data_dir)
    handle = store.package(_PACKAGE_ID)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO package (package_id, created_at) "
            "VALUES (:package_id, :created_at)",
            package_id=_PACKAGE_ID, created_at="2026-01-01T00:00:00",
        )
    catalog = PackageCatalog(handle, package_id=_PACKAGE_ID)
    version = catalog.create_version(None)
    for criterion_id in CRITERIA:
        catalog.add_criterion(version, criterion_id, max_points=4.0, band_count=2)
        catalog.add_band(version, criterion_id, 0, "needs work", 0.0,
                         descriptor=f"the response does not yet meet {criterion_id}")
        catalog.add_band(version, criterion_id, 1, "meets it", 4.0,
                         descriptor=f"the response meets {criterion_id}")
    catalog.publish(version, approved_by="teacher")
    return store, catalog


def _findings(calib):
    """The assessment's known ambiguities: one per criterion, counts out of rank order.

    Two student examples per finding — the side-by-side pair the question must show
    (`NFR-CALIB-01`) — and the band the ambiguity lives in, alternating so the session
    addresses both bands a real criterion carries."""
    return tuple(
        calib.Finding(
            criterion_id=criterion_id,
            category="rubric_ambiguity",
            submissions_affected=AFFECTED[criterion_id],
            examples=(
                f"student response A for criterion {criterion_id}",
                f"student response B for criterion {criterion_id}",
            ),
            band_ordinal=(1 if index % 2 == 0 else 0),
        )
        for index, criterion_id in enumerate(CRITERIA)
    )


def _run_conversation(calib, elicit, apply_answers, findings, catalog):
    """The whole conversation the teacher sits through: the questions, the answers.

    Returns `(questions, base, revised)` — the session as asked, the published base it
    ran against, and the version the last edit landed on."""
    base = catalog.latest_version()
    assert base is not None, "the teacher's rubric published no version to calibrate"
    questions = elicit(findings)
    revised = apply_answers(ANSWERS, catalog=catalog)
    assert revised is not None, (
        "the teacher's edit answers produced no version — the conversation never landed"
    )
    return questions, base, revised


def _assert_the_teacher_agrees(questions, findings, catalog, base):
    """UAT-03's sign-off half, pinned to the observables the plan keeps stable.

    Each question was about the teacher's rubric rather than about the model: it names
    a criterion the rubric actually carries, in a text that asks about that criterion's
    descriptor, and it shows exactly the two student responses the ambiguity was found
    on — the material a teacher answers from, never a paraphrase."""
    by_criterion = {f.criterion_id: f for f in findings}
    rubric_criteria = {row["criterion_id"] for row in catalog.criteria(base)}
    for question in questions:
        finding = by_criterion[question.criterion_id]
        assert len(question.examples) == EXAMPLES_PER_QUESTION, (
            f"{question.question_id} carries {len(question.examples)} examples; the "
            "budget is two per question — one is not enough context to answer from, "
            "three is the teacher's evening"
        )
        assert all(
            example is not None and example.strip() for example in question.examples
        ), (
            f"{question.question_id}'s side-by-side pair has an empty slot — a question "
            "padded to two examples is not answerable from two examples"
        )
        assert tuple(question.examples) == finding.examples, (
            f"{question.question_id}'s examples are not the student responses the "
            "ambiguity was found on — the teacher answers from their own students' "
            "work, not from a paraphrase"
        )
        assert question.criterion_id in rubric_criteria, (
            f"{question.question_id} asks about {question.criterion_id!r}, which the "
            "teacher's rubric does not carry — a question about a criterion that is "
            "not theirs is a question about the model, not the rubric"
        )
        assert f"criterion {question.criterion_id}" in question.question, (
            f"{question.question_id}'s text does not name the criterion it is about: "
            f"{question.question!r}. The sign-off criterion — 'each question was about "
            "their rubric rather than about the model' — pins to the question naming "
            "the rubric's own criterion"
        )


def test_tc_calib_17_at_most_six_questions_each_answerable_from_two_examples():
    """`TC-CALIB-17` — the structural gate on the conversation's length and its inputs.

    Seven ambiguities go in; at most six questions come out — and with seven candidates
    the cap is load-bearing, not decorative: an implementation asking one question per
    ambiguity returns seven and fails. Each question is answerable from exactly two
    student examples shown side by side (`NFR-CALIB-01`'s pair — both slots filled, the
    teacher never asked to answer from one example or from a placeholder), and each is
    about the teacher's rubric: it names a criterion the rubric actually carries, in a
    text that asks about that criterion's descriptor. The asked set is the six
    most-affected ambiguities — the cap's decision, made by rank.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")
    apply_answers = require(CALIB_MODULE, "apply_answers", issue="#138")

    store, catalog = _open_teacher_session()
    try:
        findings = _findings(calib)
        questions, base, revised = _run_conversation(
            calib, elicit, apply_answers, findings, catalog
        )

        assert len(questions) == MAX_QUESTIONS, (
            f"the conversation asked {len(questions)} questions for a rubric with seven "
            f"known ambiguities; the budget is at most {MAX_QUESTIONS} — the cap, with "
            "the ranking, decides which ambiguities the teacher never sees"
        )
        _assert_the_teacher_agrees(questions, findings, catalog, base)
        asked = {q.criterion_id for q in questions}
        least_affected = min(AFFECTED, key=AFFECTED.get)
        assert asked == set(CRITERIA) - {least_affected}, (
            f"the cap asked about {sorted(asked)}; the six most-affected ambiguities are "
            f"{sorted(set(CRITERIA) - {least_affected})} — the cap's decision is the "
            "ranking's, not discovery order's"
        )
    finally:
        store.close()


def test_uat_03_the_calibration_conversation_reports_its_time_against_its_ceiling():
    """`UAT-03` — the conversation, timed end to end, against its stated ceiling.

    `time.perf_counter` wraps the whole conversation (the questions being asked and the
    answers being applied — everything the teacher sits through); the measurement is
    printed and embedded in the assertion messages; the only timing assertion is
    `elapsed > 0`, because the 15-minute ceiling is a teacher-time budget and a CI box's
    wall clock measures the machine, not the teacher. The structural gate — at most six
    questions, two examples each — is `TC-CALIB-17`'s assertion above and is re-checked
    here so the budget's number belongs to a conversation of the budgeted shape.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")
    apply_answers = require(CALIB_MODULE, "apply_answers", issue="#138")

    store, catalog = _open_teacher_session()
    try:
        findings = _findings(calib)

        start = time.perf_counter()
        questions, base, revised = _run_conversation(
            calib, elicit, apply_answers, findings, catalog
        )
        elapsed = time.perf_counter() - start
        minutes = elapsed / 60.0

        print(
            f"\n[UAT-03] calibration conversation: {elapsed:.3f}s = {minutes:.3f} min "
            f"(machine wall clock; the 15-minute ceiling is a teacher-time budget, "
            "reported not gated — TC-INGEST-47's pattern)"
        )

        assert elapsed > 0, (
            f"the conversation's measured time was {elapsed}, which is not a measurement"
        )
        assert len(questions) == MAX_QUESTIONS, (
            f"the timed conversation asked {len(questions)} questions; the budget's "
            f"count is at most {MAX_QUESTIONS} (measured: {minutes:.3f} min on this box)"
        )
        _assert_the_teacher_agrees(questions, findings, catalog, base)
    finally:
        store.close()