"""`TC-GRADE-C03` — the non-repudiation case: recomputation is exact, from storage alone (§6.11.14).

`CT-GRADE-03` (behaviour): "A grade is recomputable **exactly** from its stored
criterion scores, `policy_version`, and key version (`NFR-GRADE-02`, `FR-GRADE-02`).
This is the non-repudiation guarantee: a dispute three years later is answerable by
recomputation, not by memory."

The oracle, in the plan's order: recompose the grade from the submission's OWN stored
`criterion_score` rows plus the version-pinned policy and boundary table — the same
composition the service runs — and require byte equality with the delivered row.
Then delete the run's working state (the raw judging artifacts and derived rows:
`work_unit`, `verdict`, `evidence`, `review_queue`) and recompose again. A
recomputation that depends on anything not stored — a verdict still in the ledger, a
work unit, a queue row, an in-memory cache — fails here, which is the failure that
turns a dispute three years later into "we cannot say" (RISK-12).

The recomposition reads the policy and boundaries through the shipped
`PackageCatalog` pinned to the run's package version — the version pin (`CT-PKG-09`)
is what makes the recomposition exact, so the case exercises the pin, not a
reimplementation of it.

Isolation: rung 3 — real store, real Tier P package, real service; the socket guard
is autouse. The `criterion_score` rows are the vocabulary's disclosed `M-AGG`
stand-in; the `work_unit`/`verdict` stand-ins are disclosed seeding of the
`M-ORCH`/`M-JUDGE` ledgers (rows the production writers write), written to give the
deletion something real to delete.
"""

from __future__ import annotations

import json
import pytest

from aeh.grade import (
    apply_policy,
    boundary_risk,
    coverage_for,
    resolve_grade,
)
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.grade._drive import (
    current_grades,
    criterion_rows,
    graded_run,
    set_boundaries,
    set_policy,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.grade_vocabulary import score

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

#: The boundary table installed on the run's version — the shipped CUTS shape, so
#: the recomposed grade resolves.
_CUTS = (("D", 40.0), ("C", 55.0), ("B", 70.0), ("A", 85.0))

_ROWS = (
    ("S-DONE", "C1", "B2", 7.0, "auto"),
    ("S-DONE", "C2", "B3", 38.0, "auto"),
    ("S-PART", "C1", "B2", 7.0, "auto"),
    # S-PART's C2 never scored — the missing input whose operator routing is part
    # of the derived working state the deletion removes.
)


def _working_state_counts(cohort) -> dict[str, int]:
    return {
        table: cohort.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
        for table in ("work_unit", "verdict", "evidence", "review_queue")
    }


def _recompose_submission(store, cohort, version, submission_id, criteria_ids):
    """The recomposition the clause names: stored criterion rows + the version's
    policy and boundaries -> the grade. Read through the shipped seams only."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    policy = catalog.grade_policy(version)
    boundaries = [
        (row["grade"], float(row["scaled_floor"]))
        for row in store.package("pkg-orch").query(
            "SELECT grade, scaled_floor FROM grade_boundary "
            "WHERE package_version_id = :v ORDER BY scaled_floor",
            v=version,
        )
    ]
    stored = []
    for row in criterion_rows(cohort, submission_id):
        if row["points"] is None or row["routing"] == "triage":
            continue
        stored.append(
            score(row["criterion_id"], row["points"], routing=row["routing"],
                  band=row["band"])
        )
    coverage = coverage_for(stored, criteria_ids)
    computation = apply_policy(stored, policy)
    total = computation.total
    grade = resolve_grade(total, boundaries) if total is not None else None
    return {
        "total": total,
        "grade": grade,
        "coverage": coverage,
        "missing": tuple(
            cid for cid in criteria_ids
            if cid not in {s.criterion_id for s in stored}
        ),
    }


def test_tc_grade_c03_recomputation_is_byte_exact_and_survives_working_state_deletion(
    tmp_data_dir,
):
    """`TC-GRADE-C03` (`CT-GRADE-03`, rung 3) — recompose from the stored rows, then
    delete the run's working state and recompose again: byte equality, because
    everything the recomputation reads is stored (`FR-GRADE-02`, `NFR-GRADE-02`).
    The working state is real before the deletion — the seeded `M-ORCH`/`M-JUDGE`
    ledgers and the operator queue the missing-input routing wrote — so a
    recomputation that quietly consulted any of them fails the byte comparison
    rather than passing an empty-deletion formality."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-DONE", "S-PART"),
            criteria=_CRITERIA,
            rows=_ROWS,
            compute=False,
        )
        version = world.version
        from aeh.pkg import GradePolicy, ScaleRule
        from tests.contract.grade._drive import set_policy

        set_policy(store, version, GradePolicy(
            weights=(("C1", 2.0), ("C2", 1.0)), scale=ScaleRule(factor=2.0),
        ))
        set_boundaries(store, version, _CUTS)

        cohort = world.cohort
        package_handle = store.package("pkg-orch")
        criteria_ids = [
            row["criterion_id"]
            for row in package_handle.query(
                "SELECT criterion_id FROM criterion WHERE package_version_id = :v "
                "ORDER BY criterion_id",
                v=version,
            )
        ]
        assert sorted(criteria_ids) == ["C1", "C2"], (
            f"fixture bug: the version's criteria are {criteria_ids!r}"
        )

        # Seed the working state the deletion will remove — the M-ORCH work ledger
        # and M-JUDGE verdict rows, in the shipped minimal shapes (disclosed
        # stand-ins; the base four columns, later migrations' all nullable/defaulted).
        # It EXISTS BEFORE the first grading pass, so the pass runs over a world
        # whose working state is populated — exactly the world a recomputation that
        # quietly consulted it would betray.
        with cohort.transaction() as tx:
            for work_id, sid in (("w-1", "S-DONE"), ("w-2", "S-DONE"), ("w-3", "S-PART")):
                tx.execute(
                    "INSERT INTO work_unit (work_id, submission_id, stage, status, run_id) "
                    "VALUES (:w, :s, 'judge', 'done', :r)",
                    w=work_id, s=sid, r=world.run_id,
                )
            for verdict_id, work_id in (("v-1", "w-1"), ("v-2", "w-2"), ("v-3", "w-3")):
                tx.execute(
                    "INSERT INTO verdict (verdict_id, work_id, judge_id, band) "
                    "VALUES (:v, :w, 'j-1', 'B2')",
                    v=verdict_id, w=work_id,
                )
        before_counts = _working_state_counts(cohort)
        assert before_counts["work_unit"] >= 3 and before_counts["verdict"] >= 3, (
            f"fixture bug: the working state is {before_counts!r} — the deletion must "
            "remove something real"
        )

        # The first grading pass, over the populated world.
        world.service.compute_all(world.run_id)
        assert _working_state_counts(cohort)["review_queue"] >= 1, (
            "fixture bug: the missing-input routing wrote no operator item — the "
            "derived working state the deletion must also survive is empty"
        )

        # The stored grades, with the provenance a three-years-later dispute resolves
        # through: the policy version and the answer key ref are on every row.
        stored = {row["submission_id"]: row for row in current_grades(cohort, world.run_id)}
        for row in stored.values():
            assert row["policy_version"] and row["answer_key_ref"], (
                f"a grade row is missing its provenance ({row['policy_version']!r}, "
                f"{row['answer_key_ref']!r}) — the recomputation must know WHICH "
                "policy and key version to replay (CT-GRADE-03, FR-GRADE-02)"
            )

        # Recomposition 1, from storage alone.
        first = {
            sid: _recompose_submission(store, cohort, version, sid, criteria_ids)
            for sid in ("S-DONE", "S-PART")
        }
        for sid, recomputed in first.items():
            row = stored[sid]
            assert recomputed["total"] == row["total"], (
                f"{sid}: recomposed total {recomputed['total']!r} != stored "
                f"{row['total']!r} — the grade is not recomputable from its stored "
                "criterion scores and version-pinned policy (CT-GRADE-03: "
                "non-repudiation; a dispute three years later would be unanswerable)"
            )
            assert recomputed["grade"] == row["grade"], (
                f"{sid}: recomposed grade {recomputed['grade']!r} != stored "
                f"{row['grade']!r} — the resolution is not exact from storage"
            )
            assert recomputed["missing"] == tuple(
                json.loads(row["missing_criteria"])
            ), (
                f"{sid}: recomposed missing {recomputed['missing']!r} != stored — the "
                "coverage is not exact from storage"
            )

        # Delete the run's working state — the raw judging artifacts and the
        # derived operator routing. The stored criterion scores, the grade rows and
        # the version-pinned package are the recomputation's only inputs.
        with cohort.transaction() as tx:
            for table in ("verdict", "evidence", "review_queue", "work_unit"):
                tx.execute(f"DELETE FROM {table}")
        after_counts = _working_state_counts(cohort)
        assert all(n == 0 for n in after_counts.values()), (
            f"fixture bug: the working state survived the deletion {after_counts!r}"
        )

        # Recomposition 2, over the deletion: byte equality with the first.
        second = {
            sid: _recompose_submission(store, cohort, version, sid, criteria_ids)
            for sid in ("S-DONE", "S-PART")
        }
        assert second == first, (
            f"recomputation changed after deleting the working state: {second!r} vs "
            f"{first!r} — the recomputation depends on something not stored, which "
            "is the failure that turns a dispute into 'we cannot say' (CT-GRADE-03, "
            "RISK-12)"
        )
        # And the service itself agrees: a fresh grading pass over the deleted world
        # reproduces the stored rows exactly — no new revision, byte-identical.
        world.service.compute_all(world.run_id)
        still = {row["submission_id"]: row for row in current_grades(cohort, world.run_id)}
        for sid, row in stored.items():
            fresh = still[sid]
            compared = (
                fresh["revision"], fresh["state"], fresh["grade"], fresh["total"],
                fresh["policy_version"], fresh["answer_key_ref"],
                fresh["computed_at"],
                fresh["criteria_total"], fresh["criteria_auto"],
                fresh["criteria_reviewed"], fresh["criteria_provisional"],
                fresh["criteria_missing"], fresh["missing_criteria"],
            )
            original = (
                row["revision"], row["state"], row["grade"], row["total"],
                row["policy_version"], row["answer_key_ref"], row["computed_at"],
                row["criteria_total"], row["criteria_auto"], row["criteria_reviewed"],
                row["criteria_provisional"], row["criteria_missing"],
                row["missing_criteria"],
            )
            assert compared == original, (
                f"{sid}: the service's recomputation over the deleted world differs "
                f"from the stored grade ({compared!r} vs {original!r}) — a field "
                "recomputed from the working state is not stored-state-derived "
                "(CT-GRADE-03's byte-equality clause)"
            )
    finally:
        store.close()
