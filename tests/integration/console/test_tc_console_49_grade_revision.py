"""`TS-90` (issue #384) — `TC-CONSOLE-49`: `grade_revision` reads the ledger's own
`is_current` flag, never `MAX(revision)` (`FR-CONSOLE-39`, GAP-20, ADR-9).

| Input | Expected |
|---|---|
| S1 in run R with revision 1 (`is_current = 0`) and revision 2 (`is_current = 1`) | `revision=None` → revision 2 |
| a variant that flips `is_current` onto revision 1 | `revision=None` → **revision 1** — this is what catches a `MAX(revision)` implementation |
| `revision=1` | revision 1's row |
| a second run RB with its own current revision | not returned for R |

**Why the flag and not the maximum.** The two agree in the ordinary case — an amendment writes
the next revision and marks it current — which is exactly why the ordinary case cannot test
this. They disagree when an amendment is itself superseded, or when a ledger's current row is
an earlier revision, and then a `MAX(revision)` read renders a grade **nobody holds**: not the
delivered one, not the corrected one, a third thing. ADR-9's partial unique index
`(run_id, submission_id) WHERE is_current = 1` is the ledger's own answer to "which one
counts", so the read asks it.

**The flipped variant is therefore the case**, and it is built by direct fixture write rather
than through `amend`: `amend` always makes the highest revision current, so it cannot produce
the state that separates the two readings. The write is disclosed here and is the state ADR-9's
index permits — exactly one current row per `(run, submission)`, on whichever revision.

**A finding, reported rather than asserted around.** `_SELECT_CURRENT_GRADE_REVISION` scopes to
`(SELECT run_id FROM run ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1)` — the
newest run, with a **uuid tiebreak** when neither run has started. `_SELECT_GRADE_REVISION` (the
explicit-revision path) carries **no run filter at all**. So "a second run RB is not returned
for R" is not something the console can currently guarantee: which run answers depends on a
string comparison between two run ids. The two-run case below measures that directly and says
so. #384 reports it; it is the same shape as `open_review`'s run scoping (#383).

**Isolation: rung 2** — a real store, real `submission_grade` rows, and the real console read.
"""

from __future__ import annotations

from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.console import build_console
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "S001"
CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)

_INSERT_GRADE = Statement(
    "INSERT INTO submission_grade (run_id, submission_id, revision, total, state, "
    "policy_version, finalized_at, is_current) VALUES (:run_id, :submission_id, "
    ":revision, :total, 'final', 'v1', :finalized_at, :is_current)"
)
_FLIP = Statement(
    "UPDATE submission_grade SET is_current = :flag WHERE run_id = :run_id "
    "AND submission_id = :submission_id AND revision = :revision"
)


def _seed(store: Any, run_id: str, rows) -> None:
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        for revision, total, is_current in rows:
            tx.execute(
                _INSERT_GRADE,
                run_id=run_id, submission_id=SUBMISSION, revision=revision,
                total=total, finalized_at=f"2026-09-0{revision}T00:00:00+00:00",
                is_current=is_current,
            )


@pytest.fixture
def grade_world(tmp_data_dir):
    """Run R with revision 1 superseded and revision 2 current."""
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        _seed(store, run_id, ((1, 61.0, 0), (2, 72.0, 1)))
        yield store, tmp_data_dir, run_id
    finally:
        store.close()


def _console(tmp_data_dir):
    store = open_store(tmp_data_dir)
    return store, build_console(store=store)


def _revision_of(tmp_data_dir, revision):
    store, console = _console(tmp_data_dir)
    try:
        return console.grade_revision(submission_ref=SUBMISSION, revision=revision)
    finally:
        store.close()


# --- TC-CONSOLE-49 ---------------------------------------------------------------------------


def test_tc_console_49_the_current_revision_is_the_flagged_one(grade_world):
    """`revision=None` → revision 2, the row flagged `is_current = 1`.

    The ordinary case, where the flag and the maximum agree. It is here as the control: the
    flipped variant below is the one that tells them apart, and it would pass vacuously if the
    ordinary read did not work.
    """
    _store, tmp_data_dir, _run_id = grade_world

    record = _revision_of(tmp_data_dir, None)

    assert record is not None, "no current revision was found for a submission that has two"
    assert record.revision == 2, (
        f"the current revision reads {record.revision}, not 2"
    )


def test_tc_console_49_an_explicit_revision_reads_that_row(grade_world):
    """`revision=1` → revision 1's row, superseded and still readable.

    The superseded revision staying readable after an amendment is what separates *superseding*
    a delivered grade from *mutating* it — the differential the append-only history exists for.
    """
    _store, tmp_data_dir, _run_id = grade_world

    record = _revision_of(tmp_data_dir, 1)

    assert record is not None, "the superseded revision is not readable"
    assert record.revision == 1, f"the read returned revision {record.revision}, not 1"


def test_tc_console_49_a_current_flag_on_an_earlier_revision_wins_over_the_maximum(
    grade_world,
):
    """The flipped variant — `is_current` on revision 1, revision 2 superseded: `None` → **1**.

    The case, and the only one that separates the flag from `MAX(revision)`. A maximum-based
    read returns revision 2 here: a grade the ledger says nobody holds — not the delivered one
    and not the current one, a third thing the teacher never saw.

    Built by direct write because `amend` cannot produce this state: it always makes the
    highest revision current. ADR-9's partial unique index permits it — exactly one current row
    per `(run, submission)`, on whichever revision — so this is a legal ledger, not a corrupt
    one.
    """
    store, tmp_data_dir, run_id = grade_world
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        tx.execute(_FLIP, flag=0, run_id=run_id, submission_id=SUBMISSION, revision=2)
        tx.execute(_FLIP, flag=1, run_id=run_id, submission_id=SUBMISSION, revision=1)

    record = _revision_of(tmp_data_dir, None)

    assert record is not None, "no current revision was found after the flag moved"
    assert record.revision == 1, (
        f"the current revision reads {record.revision}, not 1. The ledger flags revision 1 as "
        "current; a MAX(revision) read renders revision 2, which is a grade nobody holds "
        "(FR-CONSOLE-39, ADR-9)"
    )


def test_tc_console_49_the_current_read_is_scoped_to_one_run(tmp_data_dir):
    """Two runs, each with its own current revision — and the read does not pool them.

    **This measures a real limitation rather than asserting the plan's wording.**
    `_SELECT_CURRENT_GRADE_REVISION` scopes to the newest run by
    `COALESCE(started_at, '') DESC, run_id DESC`; with two unstarted runs that is a uuid
    comparison. So the read returns exactly one run's row — which is the half that matters,
    because pooling would return two grades for one submission — but *which* run is not
    something the caller can choose. #384 reports it.
    """
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_a, version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        from aeh.orch import Orchestrator
        from tests.support.orch_run import orch_cfg

        run_b = Orchestrator(store).create_run(ORCH_COHORT_ID, version, orch_cfg())
        _seed(store, run_a, ((1, 61.0, 1),))
        _seed(store, run_b, ((1, 88.0, 1),))
    finally:
        store.close()

    record = _revision_of(tmp_data_dir, None)

    assert record is not None, "two runs each with a current grade returned nothing"
    total = record.bands[1] if record.bands else None
    assert total in (61.0, 88.0), (
        f"the read returned a total of {total!r}, which is neither run's — the two runs' rows "
        "were combined"
    )
    assert run_a != run_b


def test_tc_console_49_an_unknown_submission_reads_as_absent(grade_world):
    """A submission with no grade returns `None` rather than someone else's row.

    The guard that keeps every case above honest: a read that ignored `submission_id` would
    return the first row in the table for any argument, and each assertion above happens to
    name the only submission there is.
    """
    _store, tmp_data_dir, _run_id = grade_world
    store, console = _console(tmp_data_dir)
    try:
        assert console.grade_revision(submission_ref="S-absent") is None, (
            "a submission with no grade returned a record"
        )
    finally:
        store.close()


def test_tc_console_49_a_revision_that_does_not_exist_reads_as_absent(grade_world):
    """`revision=99` → `None`, not the nearest row.

    An explicit revision is a request for that revision. Answering with a different one would
    show a teacher a grade under a revision number it does not have.
    """
    _store, tmp_data_dir, _run_id = grade_world

    assert _revision_of(tmp_data_dir, 99) is None, (
        "a revision the ledger does not hold returned a record"
    )
