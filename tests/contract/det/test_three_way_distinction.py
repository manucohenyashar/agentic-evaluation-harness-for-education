"""`CT-DET-03` — the three-way distinction (`TC-DET-C03`), the safety property.

Case of test plan §6.11.11, in the plan's BLOCK FORM (the automatable path the
plan itself names: `tests/contract/det/test_three_way_distinction.py`); issue
#90 (TS-68). Guards RISK-03; `FR-DET-03/04`, HLD `R13`. Consumers: `M-AGG`,
`M-GRADE`, `M-CONSOLE`.

The clause: the three-way distinction is contract and must not be collapsed by
any consumer — `blank` → scored `incorrect`, a legitimate zero; `absent`,
`ambiguous`, `multiple_marks` → `state = 'unresolved_selection'` routed to
`triage`, **never** scored incorrect; `resolved` → key comparison. A scanning
failure is never allowed to look like a wrong answer.

**Adversarial construction** (`CollapseDistinctionMutant` in `_doubles`): map
`ambiguous` to the darkest mark, and `absent` to `incorrect` "because an
unanswered question is worth zero anyway". The case asserts the mutant
agrees with the real module on EVERY resolved-selection cell — the inputs the
`FR-DET-*` cases pin, so every functional case stays green under it — and
differs on EVERY unresolved cell, where it empties the triage queue and marks
the weakest scans down. That differential IS the clause: a refactor that
passes the FR suite and fails this case is RISK-03 in its most concrete form.

**Disclosed rung deviation (step 2's consumer sweep)**: the block form's step 2
sweeps `M-AGG`, `M-GRADE` and `M-CONSOLE` at rung 3. None of the three modules
is shipped yet (only conf/pkg/setup/store/ingest/orch/det/prov exist), so the
sweep is asserted at the data level the consumers will actually read — the
`criterion_score` row shapes are disjoint by column, so a consumer reading the
data cannot conflate blank with unresolved — and the live-module sweep lands
with the modules themselves (same disclosure the TS-33 integration track
recorded for its queue case).
"""

from __future__ import annotations

import pytest

from aeh.det import DeterministicEvaluator
from tests.contract.det._doubles import (
    ISSUE,
    SINGLE_KEY,
    UNRESOLVED_CELLS,
    CollapseDistinctionMutant,
    evaluate_cell,
    resolved_cells,
    SITUATION_TABLE,
)
from tests.support.det_vocabulary import (
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.contract


# --- step 1: the exhaustive mapping, exact values -----------------------------------------------


def test_tc_det_c03_step1_exhaustive_mapping_exact_values():
    """Step 1 — every `selection_state` maps to its exact outcome: blank is
    scored `incorrect` (a legitimate zero), absent/ambiguous/multiple_marks
    are `unresolved_selection` routed to `triage` and NEVER scored incorrect,
    resolved goes to the key comparison. Asserted per field, off the same
    transcription the byte-reproducibility case enumerates."""
    blank = next(c for c in SITUATION_TABLE if c.cell == "6")
    outcome = evaluate_cell(blank)
    assert outcome.band == "incorrect" and outcome.state == "final"
    assert outcome.routing == "auto" and outcome.credit == 0.0
    assert outcome.reason == "blank_legitimate_zero"

    for name in UNRESOLVED_CELLS:
        cell = next(c for c in SITUATION_TABLE if c.cell == name)
        outcome = evaluate_cell(cell)
        assert outcome.state == "unresolved_selection", (
            f"TC-DET-C03 cell {name}: state {outcome.state!r} — an unreadable "
            "mark left the triage vocabulary."
        )
        assert outcome.routing == "triage", (
            f"TC-DET-C03 cell {name}: routed {outcome.routing!r}, not to the "
            "operator."
        )
        assert outcome.band != "incorrect", (
            f"TC-DET-C03 cell {name}: an unreadable mark was scored incorrect."
        )
        assert outcome.band == "unresolved" and outcome.credit == 0.0
        assert outcome.selection_read is None, (
            f"TC-DET-C03 cell {name}: an unresolved read carries a selection — "
            "the mark was mapped to an option."
        )


def test_tc_det_c03_step1_resolved_goes_to_the_key():
    """Step 1 (the third arm) — a resolved selection is compared to the key:
    match is `correct`, miss is `incorrect`, and nothing in between."""
    hit = evaluate_cell(next(c for c in SITUATION_TABLE if c.cell == "1"))
    miss = evaluate_cell(next(c for c in SITUATION_TABLE if c.cell == "2"))
    assert (hit.band, hit.state, hit.routing, hit.credit) == (
        "correct", "final", "auto", 1.0)
    assert (miss.band, miss.state, miss.routing, miss.credit) == (
        "incorrect", "final", "auto", 0.0)


# --- step 3: the negative, asserted on ABSENCE in the store -------------------------------------


def test_tc_det_c03_step3_no_zero_or_incorrect_value_exists_for_unresolved(
        tmp_data_dir):
    """Step 3 — for every unresolved state, NO `criterion_score` with a zero
    or incorrect value exists. Asserted on absence in the store: the rows the
    cohort pass wrote for ambiguous / multiple_marks / absent submissions are
    queried directly, and none of them carries `band = 'incorrect'`, a points
    value, or a final state — the scanner fault is not a zero the student
    earned, and it is not hiding in a column."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S-correct", "S-ambiguous", "S-multi", "S-absent",
                         "S-blank"),
            criteria=[{"criterion_id": "M1", "question_id": "Q1",
                       "key": SINGLE_KEY}],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S-correct", "selection": "B"},
                {"submission_id": "S-ambiguous", "content_state": "present",
                 "selection_state": "ambiguous"},
                # Boundary (step 4): TWO selection marks for the question —
                # det's input vocabulary carries no darkness, so the scan that
                # invites "clearly they meant this one" arrives exactly as
                # multiple marks. One mark being far darker than the other is
                # invisible here BY CONTRACT — the mutant below is what needs
                # that information.
                {"submission_id": "S-multi", "regions": [
                    {"content_state": "present", "selection_state": None},
                    {"content_state": "present", "selection_state": None},
                ]},
                {"submission_id": "S-absent", "omit_document": True},
                {"submission_id": "S-blank", "content_state": "blank"},
            ],
        )
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert report.criteria == 1 and report.evaluations == 5

        cohort = store.cohort(cohort_id)
        rows = {
            row["submission_id"]: dict(row)
            for row in cohort.query(
                "SELECT submission_id, band, points, state, routing FROM "
                "criterion_score WHERE criterion_id = 'M1'"
            )
        }
        assert set(rows) == {
            "S-correct", "S-ambiguous", "S-multi", "S-absent", "S-blank",
        }, f"TC-DET-C03: a submission is missing its score row: {sorted(rows)}"

        # The legitimate zero: blank is a scored incorrect row — counted in
        # blank_count, never in unresolved_count.
        blank = rows["S-blank"]
        assert (blank["band"], blank["state"], blank["routing"]) == (
            "incorrect", "final", "auto")
        assert blank["points"] == 0.0

        # The unresolved states: the row EXISTS (FR-DET-03 names its state)
        # but carries no score value at all — asserted as absence.
        for name in ("S-ambiguous", "S-multi", "S-absent"):
            row = rows[name]
            assert row["state"] == "unresolved_selection" and \
                row["routing"] == "triage", (
                f"TC-DET-C03 {name}: {(row['state'], row['routing'])} — the "
                "distinction left the triage vocabulary."
            )
            assert row["band"] != "incorrect", (
                f"TC-DET-C03 {name}: an unreadable mark was scored incorrect."
            )
            assert row["points"] is None, (
                f"TC-DET-C03 {name}: points {row['points']!r} — a zero VALUE "
                "exists for a state that was never scored (CT-DET-03)."
            )
        # And the sweep-level absence: no row for any unresolved submission
        # anywhere in the score table carries a zero or an incorrect value.
        leaks = cohort.query(
            "SELECT submission_id FROM criterion_score WHERE criterion_id = "
            "'M1' AND submission_id IN ('S-ambiguous', 'S-multi', 'S-absent') "
            "AND (band = 'incorrect' OR points IS NOT NULL OR state = 'final')"
        )
        assert list(leaks) == [], (
            f"TC-DET-C03: unresolved submissions scored anyway: "
            f"{[dict(r) for r in leaks]}."
        )
    finally:
        store.close()


# --- the adversarial construction ---------------------------------------------------------------


def test_tc_det_c03_adversarial_mutant_green_on_resolved_red_on_unresolved():
    """The adversarial construction — `CollapseDistinctionMutant` (ambiguous →
    darkest mark, absent → incorrect) agrees with the real module on EVERY
    resolved-selection cell, so every `FR-DET-*` case stays green under it,
    and differs on EVERY unresolved cell, where the rollup gets cleaner, the
    triage queue empties, and the weakest scans are marked down. This case is
    what turns red under that refactor while the functional suite stays
    green — the discriminator the safety property demands."""
    mutant = CollapseDistinctionMutant(darkest="B")

    # GREEN half: on resolved inputs the mutant is indistinguishable.
    for cell in resolved_cells():
        real = evaluate_cell(cell)
        theirs = mutant.evaluate(
            content_state=cell.content_state,
            selection_state=cell.selection_state,
            selection=cell.selection,
            key=cell.key,
            multi_select=cell.multi_select,
            partial_credit=cell.partial_credit,
            option_set=cell.option_set,
        )
        assert (theirs.band, theirs.credit) == (real.band, real.credit), (
            f"TC-DET-C03: the mutant differs on resolved cell {cell.cell} — "
            "the construction is too weak; it must pass every FR-DET case."
        )

    # RED half: on every unresolved input the mutant scores a band.
    for name in UNRESOLVED_CELLS:
        cell = next(c for c in SITUATION_TABLE if c.cell == name)
        real = evaluate_cell(cell)
        theirs = mutant.evaluate(
            content_state=cell.content_state,
            selection_state=cell.selection_state,
            selection=cell.selection,
            key=cell.key,
        )
        assert real.state == "unresolved_selection" and \
            real.routing == "triage"
        assert theirs.state == "final" and theirs.routing == "auto", (
            f"TC-DET-C03: the mutant does not resolve cell {name} — it must "
            "empty the triage queue for the differential to bite."
        )
        # The two directions of the collapse: an ambiguous mark becomes the
        # student's answer (darkest = B = the key here), and absent becomes a
        # zero the student "earned".
        assert theirs.band in ("correct", "incorrect") and \
            real.band == "unresolved", (
                f"TC-DET-C03 cell {name}: the mutant did not produce a "
                "scoring outcome — the collapse did not happen."
            )


def test_tc_det_c03_adversarial_mutant_empties_the_triage_queue(tmp_data_dir):
    """The adversarial construction at the store level — over the SAME seeded
    world as step 3, the mutant's outcomes would empty the triage queue
    (zero unresolved rows) and fill the incorrect band: the rollup reads
    cleaner while students with faint pencils or poor scans are marked down.
    The real pass's triage rows are what stands between the cohort and that
    reading."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S-ambiguous", "S-multi", "S-absent"),
            criteria=[{"criterion_id": "M1", "question_id": "Q1",
                       "key": SINGLE_KEY}],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S-ambiguous", "content_state": "present",
                 "selection_state": "ambiguous"},
                {"submission_id": "S-multi", "regions": [
                    {"content_state": "present", "selection_state": None},
                    {"content_state": "present", "selection_state": None},
                ]},
                {"submission_id": "S-absent", "omit_document": True},
            ],
        )
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert report.unresolved == 3 and report.incorrect == 0, (
            "TC-DET-C03: the real pass did not route all three scans to "
            "triage — the differential has nothing to protect."
        )

        # Under the mutant, the same three scans score: the triage queue
        # empties, the incorrect band fills. Reconstruct each read the way the
        # cohort pass resolved it and run the mutant on it.
        from aeh.det import SelectionRead

        mutant = CollapseDistinctionMutant(darkest="B")
        reads = (
            SelectionRead("present", "ambiguous", None),
            SelectionRead("present", "multiple_marks", None),
            SelectionRead("absent", None, None),
        )
        mutant_bands = [
            mutant.evaluate(
                content_state=r.content_state,
                selection_state=r.selection_state,
                selection=r.selection,
                key=SINGLE_KEY,
            ).band
            for r in reads
        ]
        assert mutant_bands == ["correct", "correct", "incorrect"], (
            f"TC-DET-C03: the mutant produced {mutant_bands} — it must score "
            "every scan the contract refuses to score (the darkest mark here "
            "IS the key, so the unreadable marks read as correct — the "
            "cleaner-looking and worse failure)."
        )
    finally:
        store.close()


# --- step 2: the consumer sweep, at the data the consumers read (disclosed) ---------------------


def test_tc_det_c03_step2_the_row_shapes_cannot_be_collapsed(tmp_data_dir):
    """Step 2 (disclosed rung) — the distinction cannot be collapsed by any
    consumer. `M-AGG`, `M-GRADE` and `M-CONSOLE` are not shipped yet (the
    disclosure in the module docstring), so the sweep asserts the DATA they
    will read: the blank row and the unresolved row are disjoint by column —
    different band, different state, different routing, and points that exist
    for exactly one of them — so no consumer reading the data alone can treat
    a scanning failure as a wrong answer. A consumer that collapses them has
    to write code that erases one of these column differences; the columns
    are the contract's memory."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S-blank", "S-ambiguous"),
            criteria=[{"criterion_id": "M1", "question_id": "Q1",
                       "key": SINGLE_KEY}],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S-blank", "content_state": "blank"},
                {"submission_id": "S-ambiguous", "content_state": "present",
                 "selection_state": "ambiguous"},
            ],
        )
        DeterministicEvaluator(store).evaluate_cohort(run_id)
        rows = {
            row["submission_id"]: dict(row)
            for row in store.cohort(cohort_id).query(
                "SELECT submission_id, band, points, state, routing FROM "
                "criterion_score WHERE criterion_id = 'M1'"
            )
        }
        blank, unresolved = rows["S-blank"], rows["S-ambiguous"]
        # Every column that carries the distinction is DIFFERENT between the
        # two rows — there is no column on which a consumer can read them as
        # the same event.
        assert blank["band"] != unresolved["band"]
        assert blank["state"] != unresolved["state"]
        assert blank["routing"] != unresolved["routing"]
        assert blank["points"] is not None and unresolved["points"] is None
        # And neither shape impersonates the other's consumer obligation:
        # the blank never asks for an operator, the unresolved never asks
        # for a grade.
        assert blank["routing"] != "triage"
        assert unresolved["routing"] == "triage"
        assert unresolved["points"] is None
    finally:
        store.close()
