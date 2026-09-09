"""`TC-GRADE-07`'s rung-2 half — the persisted grade goes `incomplete` when — and only
when — an input is missing, names that input, and routes the operator to rescan it;
judgment uncertainty never produces it.

Test plan §5.14's `TC-GRADE-07` block form; `FR-GRADE-07`, `FR-GRADE-08`; RISK-03 and
RISK-11 (both Critical). The case's isolation column splits it: the rung-0 halves (the
coverage record's exactness, the no-substitution computation, and the artifact
assertion refusing a substitution path) live in `tests/unit/grade/test_no_imputation.py`;
this file pins the **persisted** consequences on a real store:

1. a submission with one missing criterion (its extraction quarantined — no
   `criterion_score` row at all) computes to a grade in state `incomplete` whose record
   names the missing input (`C3` here), never a smaller grade pretending to be whole;
2. the missing input is **routed**: the review queue carries a row for the missing
   criterion whose reason directs the operator to rescan it — `incomplete` is actionable,
   not a dead end (`CT-GRADE-13`'s operator flow);
3. the differential (`CT-GRADE-08`): a purely-provisional submission — every input
   scored, none missing — is **never** `incomplete`. `incomplete` is caused exclusively
   by ingestion failure, never by judgment uncertainty.

**Fixture disclosure.** The block form's precondition is a 15-criterion submission
(11 auto / 2 reviewed / 1 provisional / 1 missing); this file runs it as a
three-criterion miniature (2 present, 1 missing) because the state, naming and routing
limbs it owns do not scale with the criterion count. The 15-criterion coverage fixture
the block form fixes is pinned at its full shape in `test_no_imputation.py` (steps 1-2
and step 6 over exactly 15 / 11 / 2 / 1 / 1), which is where the reduction is paid back.

**Written ahead of #101** (`M-GRADE`), reached through `open_grade(store)`
(`grade_vocabulary.py`). Assumed of the grade row: `.state` carrying `incomplete`, and
the missing-input names on the record (which column names them is #101's to land — the
vocabulary header's `missing-input names` row); assumed of the routing: a
`review_queue` row whose `reason` is free text (the shipped migration-001 shape) — the
pinned reading is that the reason names the action (`rescan`), disclosed as an
interpretation the design leaves implicit, reconciled at #101.

**Disclosed stand-ins** (`grade_vocabulary.py`, header): `write_criterion_scores` is
the `M-AGG` stand-in — writing the rows the production writer alone may write, and
writing *fewer* of them is exactly how this fixture manufactures an ingestion failure.

**Isolation:** rung 2 — real store, real Tier P package, real cohort ledger.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.grade_vocabulary import GRADE_BLOCKER, grade_rows, write_criterion_scores
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = GRADE_BLOCKER

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C3", "kind": "open", "scoring_model": "atomic"},
)


def _seed_run(store, submissions):
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    _orchestrator, run_id, _version = seed_run(
        store, submissions=submissions, criteria=_CRITERIA
    )
    return run_id, store.cohort(ORCH_COHORT_ID)


def _missing_input_names(row):
    """The grade record's missing-input names, however #101 lands the column set: the
    vocabulary header's `missing-input names` row collects the candidates."""
    for name in ("missing_criteria", "criteria_missing_ids", "missing_inputs"):
        value = row.get(name)
        if value:
            return value
    return None


def test_tc_grade_07_a_missing_input_makes_the_grade_incomplete_and_names_it(
    tmp_data_dir,
):
    """`TC-GRADE-07` rung 2, step 3 — one quarantined criterion: the persisted grade is
    `incomplete` and its record names the missing input. A grade that stayed silent
    about *which* input is missing would make the operator's next step a guess."""
    run_id, cohort = _seed_run(store := open_store(tmp_data_dir), ("S-I1",))
    try:
        # C3 is missing on purpose: no row at all — its extraction was quarantined.
        write_criterion_scores(
            cohort,
            [("S-I1", "C1", "B2", 7.0, "auto"),
             ("S-I1", "C2", "B1", 6.0, "reviewed")],
        )

        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        open_grade(store).compute_all(run_id)

        grades = grade_rows(cohort)
        assert len(grades) == 1, (
            "a submission with a missing input got no grade row at all — the state "
            "model computes it as `incomplete`, it does not skip it (TC-GRADE-07)"
        )
        row = grades[0]
        assert row["state"] == "incomplete", (
            f"the grade over a missing input reads {row['state']!r} — it must be "
            "`incomplete`, the one state that is not a deliverable grade (design "
            "§3.14's state model; FR-GRADE-07)"
        )
        named = _missing_input_names(row)
        assert named is not None and "C3" in str(named), (
            f"the incomplete grade's record ({named!r}) does not name the missing "
            "input C3 — an incomplete grade must say what it is missing (TC-GRADE-07 "
            "step 3, RISK-03)"
        )
    finally:
        store.close()


def test_tc_grade_07_a_missing_input_is_routed_to_the_operator_for_rescan(
    tmp_data_dir,
):
    """`TC-GRADE-07` rung 2, step 4 — the missing input is routed: a review-queue row
    for the missing criterion, with a reason that directs the operator to rescan.

    `incomplete` is actionable, not a dead end: the queue is the operator's work list,
    and a row that does not say *what to do* (rescan the extraction) or *for whom*
    (the missing criterion) does not route anyone."""
    run_id, cohort = _seed_run(store := open_store(tmp_data_dir), ("S-I2",))
    try:
        write_criterion_scores(
            cohort,
            [("S-I2", "C1", "B2", 7.0, "auto"),
             ("S-I2", "C2", "B1", 6.0, "auto")],
        )  # C3 missing: no row.

        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        open_grade(store).compute_all(run_id)

        queue = [
            dict(r) for r in cohort.query(
                "SELECT * FROM review_queue ORDER BY criterion_id"
            )
        ]
        routed = [q for q in queue if q["criterion_id"] == "C3"]
        assert routed, (
            f"the review queue holds {[q['criterion_id'] for q in queue]} after a "
            "grade went incomplete over C3 — the missing input must be routed to the "
            "operator (TC-GRADE-07 step 4, CT-GRADE-13's operator flow)"
        )
        reasons = " | ".join(str(q["reason"]) for q in routed)
        assert "rescan" in reasons.lower(), (
            f"the routing reason(s) {reasons!r} do not direct the operator to rescan "
            "— the pinned reading of the routing clause (design leaves the reason "
            "wording implicit; disclosed in this module's docstring, reconciles at "
            "#101)"
        )
    finally:
        store.close()


def test_tc_grade_07_a_purely_provisional_submission_is_never_incomplete(
    tmp_data_dir,
):
    """`TC-GRADE-07` rung 2, the differential (`CT-GRADE-08`) — every input scored and
    provisional: the grade is **not** `incomplete`. Judgment uncertainty is never
    absence; only ingestion failure produces `incomplete`."""
    run_id, cohort = _seed_run(store := open_store(tmp_data_dir), ("S-I3",))
    try:
        write_criterion_scores(
            cohort,
            [("S-I3", "C1", "B1", 4.0, "provisional"),
             ("S-I3", "C2", "B1", 3.5, "provisional"),
             ("S-I3", "C3", "B1", 4.5, "provisional")],
        )

        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        open_grade(store).compute_all(run_id)

        grades = grade_rows(cohort)
        assert len(grades) == 1, (
            "a purely-provisional submission got no grade — judgment uncertainty "
            "withholds nothing (CT-GRADE-08)"
        )
        row = grades[0]
        assert row["state"] != "incomplete", (
            f"a purely-provisional submission was marked {row['state']!r} — "
            "`incomplete` is caused exclusively by ingestion failure, never by "
            "judgment uncertainty (CT-GRADE-08); it reads `provisional`"
        )
        assert row["state"] == "provisional", (
            f"the purely-provisional grade reads {row['state']!r}, expected "
            "`provisional` — uncertainty is visible on the grade, not laundered "
            "(TC-GRADE-07's differential, CT-GRADE-08)"
        )
        assert row["criteria_missing"] == 0, (
            "the purely-provisional grade's coverage claims a missing criterion — "
            "provisional is scored, not missing (FR-GRADE-06 vs FR-GRADE-07)"
        )
    finally:
        store.close()
