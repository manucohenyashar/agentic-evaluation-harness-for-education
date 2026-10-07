"""`TC-GRADE-27` — awarded points follow each criterion's declared method (`FR-PKG-25`,
`FR-GRADE-22`; #625, TS-146).

Operator-requirements test plan §5.5: *"F-RUBRIC-METHODS scored: hand-set aspect verdicts and
band verdicts. (a) Composite points. (b) A `general` criterion vs its `bands` twin with
identical verdicts. (c) The whole run twice. (d) Confidence, routing and escalation figures for
composite vs standalone cells."* Oracles: (a) the sum of the aspects' awarded points, max the
sum of aspect maxima — hand-computed; (b) identical awarded points; (c) identical grades;
(d) a composite cell's escalation and confidence behaviour equals a standalone cell's at the
same band pattern.

The drive (`tests/support/composition_world.py`): every cell is scored from a hand-set
`StoredVerdict` panel through the real `aggregate` (criterion value built by `M-PIPE`'s own
builder over the real published package), stored by the real `write_score`, and graded by the
real `GradingService.compute_all`. No model is called.

The hand arithmetic (`F-RUBRIC-METHODS`: MCQ 1 pt; `C-bands` and `C-general` four bands worth
0/1/2/3; the composite's aspects two bands each, worth 1, 2 and 1 when present):

| Submission | MCQ | C-bands | C-general | a1 a2 a3 | composite | total |
|---|---|---|---|---|---|---|
| S1 | correct 1 | ordinal 2 → 2 | ordinal 3 → 3 | present present absent | 1+2 = **3** / 4 | **9** |
| S2 | wrong 0 | ordinal 1 → 1 | ordinal 0 → 0 | absent present absent | 2 = **2** / 4 | **3** |
| S3 | correct 1 | ordinal 3 → 3 | ordinal 2 → 2 | absent absent absent | **0** / 4 | **6** |

S1 and S2 are chosen so the composite's sum differs from its count of present aspects (S1:
sum 3, count 2; S2: sum 2, count 1) and from its maximum — a count, a max, or an average would
each give a different figure.

**Written ahead of #626** (the builder needs #622's `score_method` first): red until both land;
markers keyed to #626.

Isolation: rung 2 — real store, real published package, real aggregation, real grading.
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
    rescan_rows_for,
    rubric_methods,
    score_rows,
    score_submissions,
    seed_rubric_run,
    method_blind_sweep,
)

pytestmark = [pytest.mark.integration]

S1, S2, S3 = "s-27-1", "s-27-2", "s-27-3"
SUBMISSIONS = (S1, S2, S3)
A1, A2, A3 = ASPECTS


def _unanimous(ordinal: int) -> tuple[int, int, int]:
    return (ordinal, ordinal, ordinal)


#: The hand-set panels — unanimous three-judge panels, so each cell's band is the table's.
PANELS = {
    S1: {BANDS: _unanimous(2), GENERAL: _unanimous(3),
         A1: _unanimous(1), A2: _unanimous(1), A3: _unanimous(0)},
    S2: {BANDS: _unanimous(1), GENERAL: _unanimous(0),
         A1: _unanimous(0), A2: _unanimous(1), A3: _unanimous(0)},
    S3: {BANDS: _unanimous(3), GENERAL: _unanimous(2),
         A1: _unanimous(0), A2: _unanimous(0), A3: _unanimous(0)},
}
MCQ_CORRECT = {S1: True, S2: False, S3: True}

#: The hand-computed figures (the table in the module docstring).
COMPOSITE_AWARDED = {S1: 3.0, S2: 2.0, S3: 0.0}
GENERAL_AWARDED = {S1: 3.0, S2: 0.0, S3: 2.0}
TOTAL = {S1: 9.0, S2: 3.0, S3: 6.0}


def _graded_world(path, shape):
    store = open_store(path)
    world = seed_rubric_run(store, shape, SUBMISSIONS)
    score_submissions(world, PANELS, MCQ_CORRECT)
    grade(world)
    return world


@pytest.fixture
def graded(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    worlds = []

    def make(name, shape=None):
        world = _graded_world(tmp_data_dir / name, shape or rubric_methods())
        worlds.append(world)
        return world

    yield make
    for world in worlds:
        world.store.close()


def _points(world, submission_id, criterion_id):
    rows = world.cohort.query(
        "SELECT points FROM criterion_score WHERE run_id = :r AND submission_id = :s "
        "AND criterion_id = :c", r=world.run_id, s=submission_id, c=criterion_id)
    return [float(r["points"]) for r in rows]


# --- (a) composite points: the sum of the aspects', max the sum of the aspect maxima -----------


def test_tc_grade_27_a_the_composite_is_graded_as_the_sum_of_its_aspects(graded):
    """Every submission's grade is complete — the composite is not an input waiting on a score
    row of its own — and the total counts each aspect's points exactly once."""
    world = graded("a")
    for submission_id in SUBMISSIONS:
        row = current_grade(world, submission_id)
        missing = json.loads(row["missing_criteria"] or "[]")
        assert COMPOSITE not in missing and row["criteria_missing"] == 0, (
            f"{submission_id}: the composite was counted as a missing input "
            f"(missing={missing}, criteria_missing={row['criteria_missing']}) — its points "
            "are its aspects' sum (FR-PKG-25), never a score row of its own to wait for")
        assert row["state"] != "incomplete", (
            f"{submission_id}: every line was scored, yet the grade is {row['state']!r}")
        assert row["total"] == pytest.approx(TOTAL[submission_id]), (
            f"{submission_id}: total {row['total']} != hand-computed {TOTAL[submission_id]} — "
            "each aspect's points count once, inside the composite, never twice")
    assert rescan_rows_for(world, COMPOSITE) == [], (
        "the grade pass routed the composite to rescan as a missing input")
    for aspect in ASPECTS:
        assert all(len(_points(world, s, aspect)) == 1 for s in SUBMISSIONS), (
            f"FR-GRADE-22: aspect {aspect} keeps its own score row beneath the composite")


def test_tc_grade_27_a_the_composite_line_reads_sum_awarded_over_sum_of_maxima(graded):
    """FR-GRADE-22's one presented line: awarded = the sum of the aspects' awarded points,
    max = the sum of the aspect maxima (1 + 2 + 1 = 4), hand-computed per submission."""
    world = graded("a-line")
    for submission_id in SUBMISSIONS:
        line = composite_line(world, submission_id)
        assert float(line.awarded) == pytest.approx(COMPOSITE_AWARDED[submission_id]), (
            f"{submission_id}: composite awarded {line.awarded} != hand-computed "
            f"{COMPOSITE_AWARDED[submission_id]}")
        assert float(line.max_points) == pytest.approx(COMPOSITE_MAX), (
            f"{submission_id}: composite max {line.max_points} != the sum of aspect maxima "
            f"{COMPOSITE_MAX}")
        assert set(line.aspects) == set(ASPECTS), (
            f"the composite line names its aspects beneath it: {line.aspects!r}")


# --- (b) general vs its bands twin ------------------------------------------------------------


def test_tc_grade_27_b_a_general_criterion_awards_what_its_bands_twin_awards(graded):
    """Identical verdicts → identical awarded points, and the figure is the hand-computed one."""
    general = graded("b-general")
    twin = graded("b-bands", general_as_bands())
    for submission_id in SUBMISSIONS:
        assert _points(general, submission_id, GENERAL) == [GENERAL_AWARDED[submission_id]], (
            f"{submission_id}: the general criterion awarded "
            f"{_points(general, submission_id, GENERAL)}, hand-computed "
            f"{GENERAL_AWARDED[submission_id]}")
        assert (_points(general, submission_id, GENERAL)
                == _points(twin, submission_id, GENERAL)), (
            f"{submission_id}: a general criterion graded differently from its bands twin")
        assert (current_grade(general, submission_id)["total"]
                == current_grade(twin, submission_id)["total"])


# --- (c) determinism ---------------------------------------------------------------------------


def test_tc_grade_27_c_the_whole_run_twice_grades_identically(graded):
    """Two fresh stores, identical score rows → identical grades, whatever each line's method."""
    first = graded("c-1")
    second = graded("c-2")
    assert score_rows(first) == score_rows(second), "precondition: identical score rows"
    assert grade_rows(first) and grade_rows(first) == grade_rows(second), (
        "two runs over identical score rows produced different grades (FR-PKG-25: the "
        "computation is deterministic from score rows and the declared structure)")
    # And a recompute over the same store writes nothing new.
    before = grade_rows(first)
    grade(first)
    assert grade_rows(first) == before, "a re-grade of an unchanged run minted new rows"


# --- (d) the method is never an input to confidence, routing or escalation --------------------


@pytest.mark.parametrize("aspect", ASPECTS)
def test_tc_grade_27_d_a_composite_cell_behaves_as_a_standalone_cell(graded, aspect):
    """Each aspect vs the same criterion declared standalone `bands` (no composite): identical
    `CriterionScore` and identical escalation decision at every band pattern, signal set,
    citation state and escalation context."""
    composite = graded("d-comp")
    standalone = graded("d-alone", aspects_standalone())
    sweep = method_blind_sweep(composite, aspect, standalone, aspect, TWO_BAND_PATTERNS)
    assert not sweep.mismatches, (
        f"{len(sweep.mismatches)} of {sweep.cases} cases: the composite's method reached "
        "confidence, routing or escalation:\n  " + "\n  ".join(sweep.mismatches[:10]))
    assert (len(sweep.confidences) >= 3 and len(sweep.states) >= 2
            and {"auto", "queued", "provisional"} <= sweep.routings
            and sweep.escalations == {True, False}), (
        "precondition: the sweep's patterns must move confidence and routing, or 'equal' "
        f"is vacuous (confidences={sorted(sweep.confidences, key=str)}, "
        f"routings={sorted(sweep.routings)})")


def test_tc_grade_27_d_a_general_cell_behaves_as_its_bands_twin(graded):
    """The same sweep for `general` vs its `bands` twin over a four-band set."""
    general = graded("d-general")
    twin = graded("d-bands", general_as_bands())
    sweep = method_blind_sweep(general, GENERAL, twin, GENERAL, FOUR_BAND_PATTERNS)
    assert not sweep.mismatches, (
        f"{len(sweep.mismatches)} of {sweep.cases} cases: the general method reached "
        "confidence, routing or escalation:\n  " + "\n  ".join(sweep.mismatches[:10]))
    assert (len(sweep.confidences) >= 3 and len(sweep.states) >= 2
            and {"auto", "queued", "provisional"} <= sweep.routings
            and sweep.escalations == {True, False}), (
        "precondition: the sweep's patterns must move confidence and routing")
