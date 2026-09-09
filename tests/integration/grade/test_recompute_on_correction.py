"""`TC-GRADE-12` — an answer-key correction, then a grade-policy version change: the
affected grades recompute, and every revision records which policy version and which
answer key produced it.

Test plan §5.14; `FR-GRADE-13`. The recomputation story is built on `M-PKG`'s own
correction doctrine (aeh/pkg.py, `FR-PKG-18`): a key CORRECTION is a **new version** —
`create_version(parent)` copies the parent's content, the correction lands in the child,
and the grade "pins by `answer_key_ref`" the exact key that produced it. The same
lineage carries the policy change: `grade_policy` rows are copied to the child version
by the revision copy, and `set_grade_policy` overwrites the child's copy — so each
correction is a fresh package version the run is re-pinned to, and the versions are
what the grade row's provenance columns resolve against.

The oracle is **exact**: the corrected submission gains a revision whose
`answer_key_ref` differs from revision 1's (the key changed) while `policy_version`
stays (the policy did not); the policy change then produces a revision whose
`policy_version` differs while the key stays; and revision 1 is still present,
retained (ADR-9's retention guarantee). Unaffected submissions gain no revision —
"affected grades recomputed" cuts both ways.

**Written ahead of #101** (`M-GRADE`), reached through `open_grade(store)`
(`grade_vocabulary.py`). The grade row's provenance columns (`policy_version`,
`answer_key_ref`) are assumed columns — see the vocabulary header for their standing.

**Disclosed stand-ins** (`grade_vocabulary.py`, header): the run-row re-baseline UPDATE
(`UPDATE run SET package_version_id`) — the run row is `M-ORCH`'s alone to write, and
the correction flow's re-pointing of the run to the corrected version is what this
stands in for; and the corrected `criterion_score` rows — `M-AGG` is that table's
single writer, and an answer-key correction in production changes the deterministic
scores `M-DET` derives from the key, which arrive here as rewritten rows for the
affected submission only.

**Isolation:** rung 2 — real store, real `M-PKG` lineage, real cohort ledger.
"""

from __future__ import annotations

import pytest

from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.grade_vocabulary import (
    GRADE_BLOCKER,
    grade_rows,
    write_criterion_scores,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = GRADE_BLOCKER

_PACKAGE = "pkg-orch"
_SUBMISSIONS = ("S-K1", "S-K2")   # S-K1 is affected by the correction; S-K2 is not


def _seed_keyed_run(store):
    """A run over an MCQ criterion (the kind an answer key grades) and an open one."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    criteria = (
        {"criterion_id": "C1", "kind": "mcq", "scoring_model": "atomic",
         "max_points": 10.0},
        {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    )
    _orchestrator, run_id, version = seed_run(
        store, submissions=_SUBMISSIONS, criteria=criteria
    )
    catalog = PackageCatalog(store.package(_PACKAGE), package_id=_PACKAGE)
    catalog.set_answer_key(version, "C1", ["B"])   # the key the run first graded under
    cohort = store.cohort(ORCH_COHORT_ID)
    write_criterion_scores(
        cohort,
        [("S-K1", "C1", "B1", 8.0, "auto"), ("S-K1", "C2", "B1", 6.0, "auto"),
         ("S-K2", "C1", "B1", 7.0, "auto"), ("S-K2", "C2", "B1", 5.0, "auto")],
    )
    return run_id, version, catalog, cohort


def _rebaseline_run(cohort, run_id, version):
    """The disclosed stand-in for the correction flow's run re-pointing."""
    with cohort.transaction() as tx:
        tx.execute(
            "UPDATE run SET package_version_id = :v WHERE run_id = :r",
            v=version, r=run_id,
        )


def _current(grades, submission_id):
    return [g for g in grades if g["submission_id"] == submission_id
            and g["is_current"]]


def _revisions(grades, submission_id):
    return sorted(g["revision"] for g in grades if g["submission_id"] == submission_id)


def test_tc_grade_12_key_correction_then_policy_change_recompute_with_provenance(
    tmp_data_dir,
):
    """`TC-GRADE-12` — the answer-key correction recomputes the affected grade under
    the new key; the policy change recomputes it again under the new policy; each
    revision records which policy version and which key version produced it; revision 1
    is retained; the unaffected submission gains no revision."""
    store = open_store(tmp_data_dir)
    try:
        run_id, v1, catalog, cohort = _seed_keyed_run(store)
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)

        first = grade_rows(cohort)
        assert len(_current(first, "S-K1")) == 1, "fixture drift: no revision 1"
        baseline = _current(first, "S-K1")[0]
        baseline_policy = baseline["policy_version"]
        baseline_key = baseline["answer_key_ref"]

        # --- correction 1: the answer key (FR-PKG-18's flow — a new version) --------
        v2 = catalog.create_version(v1)
        catalog.set_answer_key(v2, "C1", ["D"])          # the corrected key
        _rebaseline_run(cohort, run_id, v2)
        # The key change moves the affected submission's deterministic score; the
        # unaffected submission's rows are untouched (M-AGG stand-in, header).
        write_criterion_scores(
            cohort, [("S-K1", "C1", "B1", 4.0, "auto")],
        )
        svc.compute_all(run_id)

        after_key = grade_rows(cohort)
        second = _current(after_key, "S-K1")
        assert _revisions(after_key, "S-K1") == [1, 2], (
            f"the affected submission's revisions are {_revisions(after_key, 'S-K1')} "
            "after the key correction — the grade must recompute as revision 2 "
            "(TC-GRADE-12, FR-GRADE-13)"
        )
        assert second[0]["answer_key_ref"] != baseline_key, (
            "revision 2 pins the same answer key as revision 1 — each revision must "
            "record which key version produced it (TC-GRADE-12, `answer_key_ref`)"
        )
        assert second[0]["policy_version"] == baseline_policy, (
            "revision 2 changed the policy version although only the key changed — "
            "the provenance columns must say which change produced the revision"
        )
        assert _revisions(after_key, "S-K2") == [1], (
            "the unaffected submission gained a revision — only affected grades "
            "recompute (TC-GRADE-12's 'affected' qualifier)"
        )
        # Revision 1 retained (ADR-9).
        assert len([g for g in after_key if g["submission_id"] == "S-K1"]) == 2, (
            "revision 1 is gone after the recompute — prior revisions are retained "
            "(ADR-9, FR-GRADE-13's audit trail)"
        )
        retained = [g for g in after_key
                    if g["submission_id"] == "S-K1" and g["revision"] == 1][0]
        assert not retained["is_current"], (
            "revision 1 still reads current after revision 2 exists — exactly one "
            "current revision per submission (ADR-9's partial unique index)"
        )

        # --- correction 2: the grade policy (the same lineage flow) -----------------
        v3 = catalog.create_version(v2)
        catalog.set_grade_policy(
            v3, GradePolicy(combination="weighted_sum",
                            weights=(("C1", 2.0), ("C2", 1.0)))
        )
        _rebaseline_run(cohort, run_id, v3)
        svc.compute_all(run_id)

        after_policy = grade_rows(cohort)
        third = _current(after_policy, "S-K1")
        assert _revisions(after_policy, "S-K1") == [1, 2, 3], (
            f"the affected submission's revisions are "
            f"{_revisions(after_policy, 'S-K1')} after the policy change — the grade "
            "must recompute again as revision 3 (TC-GRADE-12)"
        )
        assert third[0]["policy_version"] != baseline_policy, (
            "revision 3 pins the same policy version as revision 1 — each revision "
            "must record which policy version produced it (TC-GRADE-12)"
        )
        assert third[0]["answer_key_ref"] == second[0]["answer_key_ref"], (
            "revision 3 changed the answer key although only the policy changed — "
            "the provenance columns must say which change produced the revision"
        )
        assert third[0]["total"] == pytest.approx(14.0, abs=1e-9), (
            f"revision 3's total is {third[0]['total']!r}, expected 14.0 — the new "
            "policy weights C1 x 2.0 (4.0) + C2 x 1.0 (6.0), and the recomputation "
            "must apply it (exact value, TC-GRADE-12)"
        )
    finally:
        store.close()
