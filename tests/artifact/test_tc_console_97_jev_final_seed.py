"""`TC-CONSOLE-97` (seed half) — the Jev-final seed: a reproducible ENG7 cohort store with
§2.4's four cells per student, in one `synthetic` and one `real` cohort.

Traces: TC-CONSOLE-97 (FR-CONSOLE-76, FR-AGG-20; RC-08, RC-18); `console_clarity_test_plan.md`
§2.4, §6 story T1 (#812). The seed is `tests/support/clarity_world.py:seed_jev_final_world`; the
roll-up assertion itself (Q1 2/2, Q2 2/3, Q3 2/3, 6/8 pass) is TC-CONSOLE-97 proper (story
T10), which reads this seed and imports `EXPECTED_ROLLUP` from the same module.

**Oracle.** Determinism: two seeds into two fresh stores are equal row for row over every
table the seed writes. Shape: the cells carry exactly the kinds and points §2.4 and
TC-CONSOLE-97 name, and the per-question sums of the stored points equal the roll-up the
consumers will assert — so a seed that drifted (a band, a line, a cohort's consent class)
fails here, not as a distant console failure.

Rung 0/3: a real store in a tmp directory, the real `build_package` and `create_run`, the
shipped `aggregate` and `write_score` over built verdicts (the disclosed stand-in: no judge
stage). Fast tier.

Markers. The seed cases are green: the seed is this story's deliverable. The one case that
asserts the states FR-AGG-20 gives the seed's cells (the accepted decision `final`, the gate
as its confidence, the not-final reason codes) is `writtenahead` on #806, with its entry in
`WRITTEN_AHEAD_BLOCKERS`.
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.store import open_store
from tests.support.clarity_world import (CELL_KINDS, ENG7_QUESTIONS, ENG7_TOTAL_MAX,
                                         EXPECTED_REASONS, EXPECTED_ROLLUP, JEV_GATE,
                                         JEV_THRESHOLD, SEED_BANDS, STUDENTS,
                                         canonical_snapshot, roster_names, score_rows,
                                         seed_jev_final_world)

CASE = "TC-CONSOLE-97 (seed half)"

#: An evidence checklist is counted once, through its composite (FR-CONSOLE-76).
LINES_OF = {"C1": ("C1a", "C1b"), "C2": ("C2",), "C3": ("C3",)}


@pytest.fixture
def seeded(tmp_path):
    store = open_store(tmp_path / "data")
    try:
        yield store, seed_jev_final_world(store)
    finally:
        store.close()


def test_tc_console_97_seed_builds_identical_stores_on_every_call(tmp_path) -> None:
    snapshots, versions = [], []
    for name in ("first", "second"):
        store = open_store(tmp_path / name)
        try:
            world = seed_jev_final_world(store)
            snapshots.append(canonical_snapshot(store, world))
            # The package version id is the one value that legitimately differs:
            # `build_package` mints it from a fresh proposal id and publish time. Every row
            # the seed writes is compared; the id is compared for shape only.
            versions.append(tuple(
                dataclasses.replace(seed, package_version_id=seed.package_version_id.split("@")[0])
                for seed in (world.synthetic, world.real)))
        finally:
            store.close()
    assert snapshots[0] == snapshots[1], f"{CASE}: two seeds wrote different rows"
    assert versions[0] == versions[1], f"{CASE}: two seeds returned different ids"
    assert all(snapshots[0][c]["criterion_score"] for c in snapshots[0]), (
        f"{CASE}: control — a seed with no scores is trivially identical")


def test_tc_console_97_seed_has_a_synthetic_and_a_real_cohort(seeded) -> None:
    store, world = seeded
    for seed, consent in ((world.synthetic, "synthetic"), (world.real, "real")):
        assert seed.consent_class == consent
        (row,) = store.cohort(seed.cohort_id).query("SELECT consent_class FROM cohort")
        assert row["consent_class"] == consent, f"{CASE}: {seed.cohort_id} is not {consent}"
        assert set(seed.submissions) == set(STUDENTS)
    assert world.synthetic.package_version_id == world.real.package_version_id, (
        f"{CASE}: the two cohorts must administer one ENG7 version")
    assert set(STUDENTS) <= set(roster_names()), (
        f"{CASE}: the seed's students are not the sample-materials names")


@pytest.mark.parametrize("cohort", ["synthetic", "real"])
def test_tc_console_97_seed_cells_are_the_four_kinds(seeded, cohort) -> None:
    """Per student, one cell of each §2.4 kind, at the band and points the table names."""
    store, world = seeded
    seed = getattr(world, cohort)
    rows = score_rows(store, seed)
    assert set(rows) == {(s, c) for s in STUDENTS for c in CELL_KINDS}, (
        f"{CASE}: {cohort} holds cells {sorted(rows)}, not four per student")
    for student in STUDENTS:
        for criterion_id, kind in CELL_KINDS.items():
            row = rows[(student, criterion_id)]
            assert row["band"] == SEED_BANDS[student][criterion_id], (student, criterion_id)
            expected_judges = 3 if kind == "panel_agreeing" else 1
            assert row["judge_count"] == expected_judges, (
                f"{CASE}: {student} {criterion_id} ({kind}) has {row['judge_count']} judges")
        assert rows[(student, "C3")]["state"] == "ungradeable_by_panel", (
            f"{CASE}: C3 is the breaker-tripped criterion")
        assert rows[(student, "C2")]["state"] == "final" and rows[(student, "C2")][
            "band_spread"] == 0, f"{CASE}: C2 is the three-judge agreeing panel"

    cohort_handle = store.cohort(seed.cohort_id)
    prescreens = cohort_handle.query("SELECT * FROM decision_prescreen")
    accepted = [p for p in prescreens if p["criterion_id"] == "C1a"]
    assert len(accepted) == len(STUDENTS) and all(
        p["outcome"] == "accepted" and p["gate_confidence"] == JEV_GATE
        and p["gate_confidence"] > p["threshold"] == JEV_THRESHOLD for p in accepted), (
        f"{CASE}: C1a's accepted decisions are not recorded at gate {JEV_GATE}")
    breakers = cohort_handle.query("SELECT criterion_id, run_id FROM circuit_breaker")
    assert [(b["criterion_id"], b["run_id"]) for b in breakers] == [("C3", seed.run_id)]


@pytest.mark.parametrize("cohort", ["synthetic", "real"])
def test_tc_console_97_seed_points_sum_to_the_expected_rollup(seeded, cohort) -> None:
    """The stored points, summed per question over top-level lines (C1 = C1a + C1b once),
    are TC-CONSOLE-97's roll-up: A 2/2, 2/3, 2/3 = 6 (pass); B 1/2, 1/3, 1/3 = 3."""
    store, world = seeded
    rows = score_rows(store, getattr(world, cohort))
    for student in STUDENTS:
        questions = []
        for qid, (lines, points_max) in ENG7_QUESTIONS.items():
            awarded = sum(rows[(student, part)]["points"]
                          for line in lines for part in LINES_OF[line])
            questions.append((qid, int(awarded), points_max))
        expected_questions, total, grade = EXPECTED_ROLLUP[student]
        assert tuple(questions) == expected_questions, f"{CASE}: {student} {questions}"
        assert sum(q[1] for q in questions) == total
        assert sum(q[2] for q in questions) == ENG7_TOTAL_MAX
        assert grade == ("pass" if total >= 6 else "not yet")


@pytest.mark.writtenahead
@pytest.mark.parametrize("cohort", ["synthetic", "real"])
def test_tc_console_97_seed_cells_route_as_fr_agg_20_says(seeded, cohort) -> None:
    """Written ahead of #806 (FR-AGG-20): the accepted decision is `final` / `auto` with the
    gate as its confidence; every other kind carries its not-final reason code."""
    store, world = seeded
    rows = score_rows(store, getattr(world, cohort))
    for student in STUDENTS:
        jev = rows[(student, "C1a")]
        assert (jev["state"], jev["routing"]) == ("final", "auto"), (
            f"{CASE}: {student}'s accepted decision is {jev['state']}/{jev['routing']}")
        assert jev["confidence"] == pytest.approx(JEV_GATE), (
            f"{CASE}: a Jev-final cell's confidence is its gate value")
        for criterion_id, kind in CELL_KINDS.items():
            assert rows[(student, criterion_id)]["state_reason"] == EXPECTED_REASONS[kind], (
                f"{CASE}: {student} {criterion_id} ({kind}) reason "
                f"{rows[(student, criterion_id)]['state_reason']!r}")
