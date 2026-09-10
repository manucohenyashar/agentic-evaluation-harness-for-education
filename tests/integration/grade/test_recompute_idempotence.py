"""`TC-GRADE-18` — recomputation with unchanged inputs produces no new revision; the
ledger is idempotent.

Test plan §5.14; `NFR-GRADE-05` / CT-GRADE-11 ("`compute_all` is idempotent:
recomputation with unchanged inputs produces no new revision"); row-count invariant;
P0; rung 2. Three limbs:

1. **The plain pass** — `compute_all` twice over unchanged inputs mints nothing the
   second time: same rows, same revisions, same current flags.
2. **The single-submission entry point** — `compute_one` on an unchanged submission
   writes nothing either; idempotence cannot depend on which entry point recomputes.
3. **The amended submission** (the #101 carry-forward this case owns): an amendment's
   overrides live only on the grade row (`CT-GRADE-14` forbids writing
   `criterion_score`), so a recomputation that ignored them would mint a revision that
   *reverts the teacher's edit* — the pass replays the recorded amendment map before
   comparing content, and an unchanged re-run of an amended submission reproduces the
   AMENDED content and writes nothing. This is the carry-forward TS-39 inherited from
   the #101 review: the replay is what makes an amendment stable under recomputation,
   and the row-count invariant is what proves it.

The oracle is the row count (the plan's), sharpened with the revision set and the
current flags — a pass that rewrote rows in place would keep the count but break the
chain.

**Disclosed stand-ins** (`grade_vocabulary.py`, header): the run-completion UPDATE
(`M-ORCH` is the run row's single writer) and `write_criterion_scores` standing in
for `M-AGG`'s single-writer rows — the same patterns `test_finalization.py` and
`test_recompute_on_correction.py` use.

**Isolation:** rung 2 — real store, real package lineage, real grade ledger.
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

pytestmark = [pytest.mark.integration]

ISSUE = GRADE_BLOCKER

_PACKAGE = "pkg-orch"


def _seed_scored_run(store, submissions):
    """A run with every submission fully scored under a windowless policy."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    criteria = (
        {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
        {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    )
    _orchestrator, run_id, version = seed_run(
        store, submissions=submissions, criteria=criteria
    )
    catalog = PackageCatalog(store.package(_PACKAGE), package_id=_PACKAGE)
    catalog.set_grade_policy(
        version, GradePolicy(combination="weighted_sum")
    )
    cohort = store.cohort(ORCH_COHORT_ID)
    write_criterion_scores(
        cohort,
        [
            (sid, "C1", "B2", 7.0, "auto")
            for sid in submissions
        ]
        + [
            (sid, "C2", "B1", 6.0, "auto")
            for sid in submissions
        ],
    )
    return run_id, cohort


def _ledger_state(cohort):
    """The full current shape of the ledger: row count, the (submission, revision,
    is_current) triples and the current totals — everything a silent rewrite would
    have to match to pass for 'no new revision'."""
    rows = grade_rows(cohort)
    return (
        len(rows),
        sorted(
            (g["submission_id"], g["revision"], g["is_current"], g["total"])
            for g in rows
        ),
    )


def test_tc_grade_18_a_recompute_with_unchanged_inputs_mints_nothing(tmp_data_dir):
    """`TC-GRADE-18` — the plain limb: `compute_all` over unchanged inputs writes
    nothing; the row count, the revision chain and the current flags all stand."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_scored_run(store, ("S-I1", "S-I2"))
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)
        after_first = _ledger_state(cohort)
        assert after_first[0] == 2, (
            f"{after_first[0]} rows after the first pass — one revision per "
            "submission (fixture drift)"
        )

        report = svc.compute_all(run_id)

        assert _ledger_state(cohort) == after_first, (
            "a recomputation pass with unchanged inputs changed the ledger — "
            "NFR-GRADE-05: recomputation with unchanged inputs produces NO new "
            "revision (TC-GRADE-18's row-count invariant)"
        )
        assert report.computed == 2, (
            f"the second pass reports computed={report.computed!r} — every submission "
            "is still recomputed (the work happens; only the WRITE is idempotent)"
        )
    finally:
        store.close()


def test_tc_grade_18_compute_one_is_idempotent_too(tmp_data_dir):
    """`TC-GRADE-18`, single-submission limb: `compute_one` with unchanged inputs
    writes nothing — the per-student entry point is the same idempotent pass, scoped."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_scored_run(store, ("S-I3",))
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)
        after_first = _ledger_state(cohort)

        one = svc.compute_one(run_id, "S-I3")

        assert one.revision == 1, (
            f"compute_one returned revision {one.revision!r} — an unchanged recompute "
            "must not mint a revision (NFR-GRADE-05, TC-GRADE-18)"
        )
        assert _ledger_state(cohort) == after_first, (
            "compute_one with unchanged inputs changed the ledger — the "
            "single-submission entry point is bound by the same idempotence "
            "(TC-GRADE-18)"
        )
        assert one.total == pytest.approx(13.0, abs=1e-9), (
            f"the recomputed total is {one.total!r}, expected 13.0 — idempotence must "
            "not mean skipping the computation (exact value)"
        )
    finally:
        store.close()


def test_tc_grade_18_a_recompute_after_an_amendment_reproduces_the_amendment(
    tmp_data_dir,
):
    """`TC-GRADE-18`'s amended limb (the #101 review's carry-forward): the overrides
    live only on the grade row, so a recomputation replays the recorded amendment map
    before comparing content — an unchanged re-run of an amended submission reproduces
    the AMENDED grade and writes nothing, rather than minting a revert."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_scored_run(store, ("S-I4",))
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)

        revision = svc.amend(
            run_id, "S-I4", {"C1": 3.0}, actor="t-may", reason="mis-banded"
        )
        assert revision.total == pytest.approx(9.0, abs=1e-9), (
            f"the amended total is {revision.total!r}, expected 9.0 — C1 3.0 + C2 6.0 "
            "(fixture drift: the edit did not move the total)"
        )
        after_amendment = _ledger_state(cohort)

        # The limb: a recomputation over unchanged stored scores must keep the
        # amendment — reverting it would be a silent new revision that undoes the
        # teacher's edit.
        svc.compute_all(run_id)
        assert _ledger_state(cohort) == after_amendment, (
            "a recomputation after an amendment changed the ledger — the recorded "
            "amendment map must be replayed before comparing content, so the "
            "amended grade recomputes to itself and writes nothing (NFR-GRADE-05, "
            "FR-GRADE-13 reaching amended revisions; TC-GRADE-18)"
        )
        current = [g for g in grade_rows(cohort) if g["is_current"]][0]
        assert current["total"] == pytest.approx(9.0, abs=1e-9), (
            f"the surviving grade's total is {current['total']!r}, expected 9.0 — "
            "the amendment must still govern the recomputed content"
        )
        assert current["revision"] == 2, (
            "the surviving grade is not the amended revision — the replay must "
            "reproduce the amendment, not revert it"
        )
    finally:
        store.close()