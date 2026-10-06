"""`TC-GRADE-C22` — `CT-GRADE-22`: composition follows the declared method, and the method is
blind everywhere else (#625, TS-146).

`CT-GRADE-22` (behaviour; consumers `M-REVIEW`, `M-STATS`, `M-CONSOLE`): *"Awarded points per
criterion follow the declared method (FR-PKG-25); a `general` criterion grades exactly as a
`bands` criterion; an `evidence_sum` criterion's points are the sum of its aspects'. The method
is never an input to confidence, routing or escalation."* Plan §5.5: *"As TC-GRADE-27 run as
the provider's clause suite, plus: a `general` criterion's grade path is byte-identical to its
`bands` twin's (same rows written)."* **Breaks if** the method reaches confidence, routing or
escalation.

The clause's three sentences, one case each, over `tests/support/composition_world.py`'s drive
(hand-set `StoredVerdict` panels → real `aggregate` → real `write_score` → real
`GradingService.compute_all`):

1. **byte-identical grade path** — `F-RUBRIC-METHODS` and its twin with `C-general` declared
   `bands`, scored from the same verdicts: every `criterion_score`, `submission_grade` and
   `review_queue` row the two runs write is identical once run ids and clock stamps are
   stripped. A method that reached any figure on any row breaks it;
2. **composite = sum of aspects** — one submission whose composite figure (1 + 2 = 3 of 4)
   differs from its present-aspect count and its maximum, read from the grade row (complete,
   total counted once) and from FR-GRADE-22's presented line;
3. **method-blind confidence, routing and escalation** — the sweep over band patterns × signal
   sets × citation × escalation contexts, for every aspect against its standalone twin and for
   `general` against its `bands` twin, the criterion value built by `M-PIPE`'s own builder (so
   the stored `score_method` / `component_of` columns ride into `aggregate` exactly as they do
   in production). The sweep must show varied outputs, or "equal" would be vacuous.

**Written ahead of #626** (the builder needs #622 first). Markers keyed to #626.

Isolation: rung 2 — real store, real published package, real aggregation and grading.
"""

from __future__ import annotations

import json

import pytest

from aeh.store import open_store
from tests.support.composition_world import (
    ASPECTS,
    BANDS,
    COMPOSITE,
    COMPOSITE_MAX,
    FOUR_BAND_PATTERNS,
    GENERAL,
    TWO_BAND_PATTERNS,
    aspects_standalone,
    composite_line,
    current_grade,
    general_as_bands,
    grade,
    grade_rows,
    method_blind_sweep,
    queue_rows,
    rubric_methods,
    score_rows,
    score_submissions,
    seed_rubric_run,
)

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

SUBMISSION = "s-c22"
A1, A2, A3 = ASPECTS

#: A split panel on the general line (median 2, spread 2) and a single-judge aspect, so the
#: rows carry non-trivial confidence, routing and state for the byte comparison to bite on.
PANELS = {SUBMISSION: {BANDS: (1, 2, 2), GENERAL: (1, 2, 3), A1: (1, 1, 1), A2: (0, 1, 1),
                       A3: (0,)}}
MCQ_CORRECT = {SUBMISSION: True}
#: Hand arithmetic: a1 present (1) + a2 median present (2) + a3 absent (0).
COMPOSITE_AWARDED = 3.0


@pytest.fixture
def worlds(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    opened = []

    def make(name, shape):
        world = seed_rubric_run(open_store(tmp_data_dir / name), shape, (SUBMISSION,))
        score_submissions(world, PANELS, MCQ_CORRECT)
        grade(world)
        opened.append(world)
        return world

    yield make
    for world in opened:
        world.store.close()


def test_tc_grade_c22_a_general_criterion_writes_exactly_its_bands_twins_rows(worlds):
    general = worlds("general", rubric_methods())
    twin = worlds("twin", general_as_bands())
    assert score_rows(general), "precondition: the grade path wrote score rows"
    assert score_rows(general) == score_rows(twin), (
        "CT-GRADE-22: a general criterion's criterion_score rows differ from its bands twin's")
    assert grade_rows(general) and grade_rows(general) == grade_rows(twin), (
        "CT-GRADE-22: a general criterion's grade differs from its bands twin's")
    assert queue_rows(general) == queue_rows(twin), (
        "CT-GRADE-22: the general method changed what the grade pass routed to review")


def test_tc_grade_c22_an_evidence_sum_criterion_is_the_sum_of_its_aspects(worlds):
    world = worlds("composite", rubric_methods())
    row = current_grade(world, SUBMISSION)
    assert COMPOSITE not in json.loads(row["missing_criteria"] or "[]"), (
        "the composite was graded as a missing input rather than as its aspects' sum")
    line = composite_line(world, SUBMISSION)
    assert float(line.awarded) == pytest.approx(COMPOSITE_AWARDED), (
        f"composite awarded {line.awarded}, hand-computed {COMPOSITE_AWARDED} (1 + 2 + 0)")
    assert float(line.max_points) == pytest.approx(COMPOSITE_MAX)


@pytest.mark.parametrize("pair", [*[("aspect", a) for a in ASPECTS], ("general", GENERAL)],
                         ids=lambda pair: pair[1])
def test_tc_grade_c22_the_method_is_never_an_input_to_confidence_routing_or_escalation(
    worlds, pair
):
    kind, criterion_id = pair
    if kind == "aspect":
        a, b = worlds("m", rubric_methods()), worlds("s", aspects_standalone())
        patterns = TWO_BAND_PATTERNS
    else:
        a, b = worlds("m", rubric_methods()), worlds("s", general_as_bands())
        patterns = FOUR_BAND_PATTERNS
    sweep = method_blind_sweep(a, criterion_id, b, criterion_id, patterns)
    assert not sweep.mismatches, (
        f"CT-GRADE-22 broken for {criterion_id} in {len(sweep.mismatches)} of {sweep.cases} "
        "cases:\n  " + "\n  ".join(sweep.mismatches[:10]))
    assert (len(sweep.confidences) >= 3 and len(sweep.states) >= 2
            and {"auto", "queued", "provisional"} <= sweep.routings
            and sweep.escalations == {True, False}), (
        "precondition: the sweep must move confidence, routing and state, or equality is "
        f"vacuous: {sorted(sweep.confidences, key=str)}, {sorted(sweep.routings)}, "
        f"{sorted(sweep.states)}")
