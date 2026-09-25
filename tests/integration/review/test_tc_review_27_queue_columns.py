"""`TS-89` (issue #383) — `TC-REVIEW-27`: the queue row records what the build and the action
decided (`FR-REVIEW-20`).

| Input | Expected |
|---|---|
| `build_queue(R, budget)` showing 4 items | shown items carry `rank_score` (non-increasing with position), `est_seconds` and `shown_at = clock` |
| `act` on item 2 with `override`, new band `3`, 7.5 points | that item carries `action='override'`, `new_band='3'`, `new_points=7.5` and `acted_at` |
| the existing writers in `grade.py` and `integ.py` | each enqueues once, and their rows carry `run_id = R` |

**The divergence these columns end.** `review_queue` shipped as four columns — an item was
flagged, and nothing about the review of it. The console had to re-derive its own header
figures from raw rows and a write-log tally, so the screen's numbers and the service's numbers
were two computations of the same thing and free to disagree. Now the row records what the
service decided, and `FR-CONSOLE-35` reads it back.

**`run_id` is the column that makes the row belong to something.** Without it a queue row
belonged to no run, so two runs over one cohort shared a queue — the second run's build
overwrote the first's decisions and neither could be read back. That is why the grade and integ
writers are checked too: they are the other two producers, and a row written by either without
a run id reopens the same hole from a different module.

**`rank_score` non-increasing is the assertion, not "present".** The column exists so the
screen can show why an item is where it is; a column populated with a constant, or with the
rank recomputed at read time, satisfies presence and tells the teacher nothing. Non-increasing
with position is the property that makes it the ranking's own figure.

**Isolation: rung 2** — a real store, a real package band scale, `open_review` and `act`.
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
from aeh.pkg import PackageCatalog
from aeh.review import open_review
from aeh.store import Statement, open_store
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

CRITERION = "C1"
ITEMS = 4
SUBMISSIONS = tuple(f"S{index:03d}" for index in range(1, ITEMS + 1))

#: The plan's new band and its points. The band is literally named `"3"`.
BANDS = ((0, "1", 2.5), (1, "2", 5.0), (2, "3", 7.5), (3, "4", 10.0))
NEW_BAND = "3"
NEW_POINTS = 7.5

#: Reserve 5 of 10 minutes leaves 300 s, which fits six 45-second items — so all four show.
BUDGET_MINUTES = 10
RESERVE_MINUTES = 5

CRITERIA = (
    {
        "criterion_id": CRITERION,
        "kind": "open",
        "scoring_model": "atomic",
        "band_count": len(BANDS),
    },
)

_QUEUE_ROWS = Statement(
    "SELECT queue_id, run_id, submission_id, criterion_id, rank_score, est_seconds, "
    "shown_at, action, new_band, new_points, acted_at FROM review_queue "
    "ORDER BY rank_score DESC, queue_id"
)


@pytest.fixture
def queue_world(tmp_data_dir):
    """Four queued rows over one run, with a real band scale behind them."""
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, version = seed_run(
            store, submissions=SUBMISSIONS, criteria=CRITERIA,
        )
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        for ordinal, band, points in BANDS:
            catalog.add_band(version, CRITERION, ordinal, band, points)
        write_criterion_scores(
            store.cohort(ORCH_COHORT_ID),
            # A DISTINCT proposed band per row. `proposed_band` is the first of
            # `SIGNATURE_COMPONENTS`, so identical bands collapse all four items into one
            # `ReviewGroup` — the build would then show one entry covering four items and the
            # per-row column assertions below would have one row to look at. Grouping at scale
            # is TC-REVIEW-08's subject, not this case's.
            [
                (submission, CRITERION, band, points, "provisional")
                for submission, (_ordinal, band, points) in zip(SUBMISSIONS, BANDS)
            ],
        )
        yield tmp_data_dir, catalog, run_id
    finally:
        store.close()


def _service(world):
    tmp_data_dir, catalog, _run_id = world
    # Loaded by COHORT, built by RUN — the two identifiers are different and the package
    # resolution needs the run one (see TC-REVIEW-28).
    return open_review(
        tmp_data_dir,
        run_id=ORCH_COHORT_ID,
        catalog=catalog,
        review_blind_reserve_minutes=RESERVE_MINUTES,
    )


def _queue_rows(tmp_data_dir) -> list[dict[str, Any]]:
    store = open_store(tmp_data_dir)
    try:
        return [dict(row) for row in store.cohort(ORCH_COHORT_ID).query(_QUEUE_ROWS)]
    finally:
        store.close()


# --- TC-REVIEW-27 ---------------------------------------------------------------------------


def test_tc_review_27_a_recorded_build_writes_the_build_columns(queue_world):
    """Every shown item's row carries `rank_score`, `est_seconds` and `shown_at`.

    `record=True` is the default and is what makes a build a writer. The three columns are
    asserted together because they are written in one statement — one missing means the
    statement changed, not that one figure was unavailable.
    """
    tmp_data_dir, _catalog, run_id = queue_world
    queue = _service(queue_world).build_queue(run_id, BUDGET_MINUTES)

    assert len(queue.shown) == ITEMS, (
        f"{len(queue.shown)} of {ITEMS} items shown; 5 spendable minutes fit six 45-second "
        "items, so all four belong on the screen"
    )

    rows = _queue_rows(tmp_data_dir)
    assert len(rows) == ITEMS, f"{len(rows)} queue rows written for {ITEMS} shown items"
    for row in rows:
        missing = [
            name for name in ("rank_score", "est_seconds", "shown_at")
            if row[name] is None
        ]
        assert missing == [], (
            f"queue row {row['queue_id']} left {missing} NULL; the screen reads its header "
            "from these rather than re-deriving it (FR-REVIEW-20, FR-CONSOLE-35)"
        )


def test_tc_review_27_every_queue_row_names_its_run(queue_world):
    """`run_id` is populated, and it is the run the build was for.

    Without it a queue row belongs to no run, so two runs over one cohort share a queue and
    the second build overwrites the first's decisions.
    """
    tmp_data_dir, _catalog, run_id = queue_world
    _service(queue_world).build_queue(run_id, BUDGET_MINUTES)

    rows = _queue_rows(tmp_data_dir)
    assert {row["run_id"] for row in rows} == {run_id}, (
        f"queue rows carry run ids {sorted({r['run_id'] for r in rows})}, not {run_id!r}"
    )


def test_tc_review_27_rank_score_does_not_increase_with_position(queue_world):
    """The shown order is by descending `rank_score` — the column is the ranking's own figure.

    A constant, or a value recomputed at read time, satisfies "present" and tells the teacher
    nothing about why an item is where it is.
    """
    tmp_data_dir, _catalog, run_id = queue_world
    queue = _service(queue_world).build_queue(run_id, BUDGET_MINUTES)

    shown_ids = [
        str(getattr(member, "submission_id", ""))
        for entry in queue.shown
        for member in (getattr(entry, "members", None) or (entry,))
    ]
    by_submission = {row["submission_id"]: row for row in _queue_rows(tmp_data_dir)}
    scores = [float(by_submission[sid]["rank_score"]) for sid in shown_ids]

    assert scores == sorted(scores, reverse=True), (
        f"rank_score by shown position is {scores}, which is not non-increasing. The queue "
        "fills in rank order, so the stored figure must agree with the order it produced"
    )


def test_tc_review_27_acting_records_the_action_on_the_items_own_row(queue_world):
    """The acted item carries `action='override'`, `new_band='3'`, `new_points=7.5`,
    `acted_at` — and the items not acted on carry none of them.

    The second half is what makes the first an assertion about *that* row. A writer that
    stamped every row of the build would satisfy the acted item's four columns and lose the
    distinction between "reviewed" and "shown".
    """
    tmp_data_dir, _catalog, run_id = queue_world
    service = _service(queue_world)
    queue = service.build_queue(run_id, BUDGET_MINUTES)

    entry = queue.shown[1]
    members = getattr(entry, "members", None)
    item = members[0] if members else entry
    acted_submission = str(item.submission_id)
    service.act(item, "override", new_band=NEW_BAND)

    rows = {row["submission_id"]: row for row in _queue_rows(tmp_data_dir)}
    acted = rows[acted_submission]

    assert acted["action"] == "override", (
        f"the acted row's action is {acted['action']!r}"
    )
    assert str(acted["new_band"]) == NEW_BAND, (
        f"the acted row's new_band is {acted['new_band']!r}, not {NEW_BAND!r}"
    )
    assert float(acted["new_points"]) == NEW_POINTS, (
        f"the acted row's new_points is {acted['new_points']!r}, not {NEW_POINTS}. The points "
        "are the DERIVED value of the band the teacher chose, never a caller's number "
        "(FR-REVIEW-10)"
    )
    assert acted["acted_at"] is not None, "the acted row records no acted_at"

    untouched = [
        submission for submission, row in rows.items()
        if submission != acted_submission and row["action"] is not None
    ]
    assert untouched == [], (
        f"rows {untouched} were stamped with an action nobody took on them; showing an item "
        "and reviewing it are different facts"
    )


def test_tc_review_27_the_grade_and_integ_writers_name_the_run(queue_world):
    """The other two `review_queue` producers carry `run_id` in their insert.

    `M-REVIEW` is no longer the table's only writer: `grade.py` enqueues a missing criterion
    and `integ.py` enqueues an integrity route. A row from either without a run id reopens
    the shared-queue hole from a module the review service never touches, so the column is
    asserted in their statements rather than only in this module's.
    """
    from aeh.grade import GRADE_STATEMENTS
    from aeh.integ import INTEG_STATEMENTS

    writers = {
        f"grade:{name}": statement
        for name, statement in GRADE_STATEMENTS.items()
        if "INSERT" in statement.sql.upper() and "review_queue" in statement.sql
    }
    writers.update({
        f"integ:{name}": statement
        for name, statement in INTEG_STATEMENTS.items()
        if "INSERT" in statement.sql.upper() and "review_queue" in statement.sql
    })

    assert writers, (
        "neither grade.py nor integ.py declares a review_queue insert; if the writers moved, "
        "this case has to follow them (FR-REVIEW-20)"
    )
    missing = [name for name, statement in writers.items() if "run_id" not in statement.sql]
    assert missing == [], (
        f"these review_queue writers do not name run_id: {missing}. A queue row that belongs "
        "to no run is shared by every run over the cohort"
    )
