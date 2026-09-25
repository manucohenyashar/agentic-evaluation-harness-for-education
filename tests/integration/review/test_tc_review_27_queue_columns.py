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

import re
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
from aeh.pkg import GradePolicy, PackageCatalog
from aeh.review import _service_from_store
from aeh.store import Statement, open_store
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

#: Written directly rather than through `write_criterion_scores`, which sets only
#: `run_id, submission_id, criterion_id, band, points, routing, state` and leaves `band_spread`
#: and every integrity signal NULL. Over such rows every ranking input resolves to its default,
#: every row scores the same, and `rank_score` is `0.0` for all four — which made the ordering
#: assertion below true of a constant. The rows here vary the inputs FR-REVIEW-18 ranks on.
_INSERT_SCORE = Statement(
    "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, points, "
    "routing, state, band_spread, spans_verified, evidence_present, sufficiency_flag, "
    "ocr_overlap_risk) VALUES (:run_id, :submission_id, :criterion_id, :band, :points, "
    "'provisional', 'provisional_unreviewed', :band_spread, :spans_verified, 1, 0, "
    ":ocr_overlap_risk)"
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
        catalog.set_grade_policy(
            version,
            GradePolicy(combination="weighted_sum", weights=((CRITERION, 2.5),)),
        )
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            for index, (submission, (_ordinal, band, points)) in enumerate(
                zip(SUBMISSIONS, BANDS)
            ):
                # A DISTINCT proposed band per row: `proposed_band` heads
                # `SIGNATURE_COMPONENTS`, so identical bands collapse all four into one
                # `ReviewGroup` and the per-row assertions would have one row to look at.
                # Grouping at scale is TC-REVIEW-08's subject.
                #
                # And a DISTINCT adverse profile, so the four rank differently: without it
                # every rank_score is 0.0 and "non-increasing" is true of a constant.
                tx.execute(
                    _INSERT_SCORE,
                    run_id=run_id, submission_id=submission, criterion_id=CRITERION,
                    band=band, points=points,
                    band_spread=index,
                    spans_verified=0 if index >= 2 else 1,
                    ocr_overlap_risk=1 if index >= 1 else 0,
                )
        yield tmp_data_dir, catalog, run_id
    finally:
        store.close()


def _service(world):
    """A run-scoped service. Not `open_review`, whose `run_id` parameter is really the cohort
    id and which therefore serves whichever run is newest — see TC-REVIEW-25's `_service`,
    which reports the defect in full."""
    tmp_data_dir, catalog, run_id = world
    store = open_store(tmp_data_dir)
    return store, _service_from_store(
        store,
        cohort_ids=[ORCH_COHORT_ID],
        run_id=run_id,
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
    _store, service = _service(queue_world)
    queue = service.build_queue(run_id, BUDGET_MINUTES)

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
    _store, service = _service(queue_world)
    service.build_queue(run_id, BUDGET_MINUTES)

    rows = _queue_rows(tmp_data_dir)
    assert {row["run_id"] for row in rows} == {run_id}, (
        f"queue rows carry run ids {sorted({r['run_id'] for r in rows})}, not {run_id!r}"
    )


def test_tc_review_27_the_ranking_the_build_produced_is_non_increasing(queue_world):
    """The shown order is by descending expected value, and the four rows score differently.

    **The plan asks this of the stored `rank_score` column; it is asserted on the build's own
    figure instead, because the stored column is always `0.0` — a defect this case found.**

    `_record_shown_rows` writes `rank_score=float(_expected_value(member, knobs))`, and
    `member` is a `ReviewItem`. `ReviewItem` carries `expected_value` (computed at itemize time
    from the `_StoredScoreRow`, correctly) but **none of the ranking inputs**: no
    `criterion_weight`, no `panel_spread`, no `adverse_integrity_signals`. `_impact_of`
    multiplies by `criterion_weight`, which `getattr` resolves to `0.0`, so the recomputation
    is zero for every row. Measured on this fixture:

        in-memory expected_value: [0.28704, 0.23148, 0.15741, 0.02778]
        stored rank_score       : [0.0, 0.0, 0.0, 0.0]

    That is exactly the divergence `FR-REVIEW-20` exists to end — the screen reading a figure
    that disagrees with the service that computed it — reappearing inside the column meant to
    close it. The one-line fix is to persist `member.expected_value` rather than recompute from
    an object that has lost the inputs. #383 reports it; writing production code is
    `/fix-issue`'s.

    So this asserts the property the requirement is about, on the figure that carries it, and
    the case above asserts the column is at least written. Both halves are needed: the
    presence check alone passes over a dead column, and this alone says nothing about
    persistence.
    """
    _store, service = _service(queue_world)
    _tmp, _catalog, run_id = queue_world
    queue = service.build_queue(run_id, BUDGET_MINUTES)

    values = [
        float(member.expected_value)
        for entry in queue.shown
        for member in (getattr(entry, "members", None) or (entry,))
    ]

    assert len(values) == ITEMS, f"the build showed {len(values)} items"
    assert len(set(values)) > 1, (
        f"every shown item scored {values[0]}. A constant is what a ranking whose inputs all "
        "resolve to their defaults looks like, and 'non-increasing' is trivially true of it"
    )
    assert values == sorted(values, reverse=True), (
        f"the shown order scores {values}, which is not non-increasing — the queue fills in "
        "rank order, so the order and the figure must agree"
    )


def test_tc_review_27_the_stored_rank_score_does_not_yet_carry_the_ranking(queue_world):
    """The defect above, pinned so the day it is fixed is visible rather than silent.

    This asserts the **current** behaviour — every stored `rank_score` is `0.0` while the
    build's own figures differ — and it is written to go RED when someone persists
    `member.expected_value`. At that point delete this case and move the ordering assertion
    above onto the stored column, which is where the plan wants it.

    Pinned rather than left unwritten because an undocumented zero column is indistinguishable
    from a column nobody has looked at, and this is the third store-scoping-shaped defect in
    this module (see TC-REVIEW-25 on `open_review`).
    """
    tmp_data_dir, _catalog, run_id = queue_world
    _store, service = _service(queue_world)
    queue = service.build_queue(run_id, BUDGET_MINUTES)

    built = {
        str(member.submission_id): float(member.expected_value)
        for entry in queue.shown
        for member in (getattr(entry, "members", None) or (entry,))
    }
    stored = {
        str(row["submission_id"]): float(row["rank_score"] or 0.0)
        for row in _queue_rows(tmp_data_dir)
    }

    assert len(set(built.values())) > 1, "the build did not produce a varying ranking"
    assert set(stored.values()) == {0.0}, (
        f"the stored rank_score column now carries {sorted(set(stored.values()))} rather than "
        "all zeros — the recompute-from-ReviewItem defect this case pins has been fixed. "
        "Delete this case and assert the ordering on the stored column instead (FR-REVIEW-20)"
    )
    assert stored != built


def test_tc_review_27_acting_records_the_action_on_the_items_own_row(queue_world):
    """The acted item carries `action='override'`, `new_band='3'`, `new_points=7.5`,
    `acted_at` — and the items not acted on carry none of them.

    The second half is what makes the first an assertion about *that* row. A writer that
    stamped every row of the build would satisfy the acted item's four columns and lose the
    distinction between "reviewed" and "shown".
    """
    tmp_data_dir, _catalog, run_id = queue_world
    _store, service = _service(queue_world)
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
    """The other two `review_queue` producers name `run_id` **in their INSERT column list**.

    `M-REVIEW` is no longer the table's only writer: `grade.py` enqueues a missing criterion
    and `integ.py` enqueues an integrity route. A row from either without a run id reopens the
    shared-queue hole from a module the review service never touches.

    The column list, not the statement text: `"run_id" in sql` is satisfied by a sub-select's
    `WHERE run_id = …` on a statement that never writes the column, which is exactly the shape
    a half-migrated writer takes. The list between `review_queue (` and the first `)` is what
    the row actually gets.

    **Idempotence is read off the conflict clause rather than driven.** The plan says "each
    enqueues once"; driving M-GRADE's and M-INTEG's enqueue paths twice apiece is those
    modules' own suites' work (`TC-GRADE-01`, `TC-INTEG-16`). What is checkable from here, and
    what makes a second enqueue a no-op, is that each writer carries `OR REPLACE` or
    `OR IGNORE` on a `queue_id` primary key — so the assertion is on that, and #383 notes the
    behavioural half stays with the owning modules.
    """
    from aeh.grade import GRADE_STATEMENTS
    from aeh.integ import INTEG_STATEMENTS

    writers = {
        f"grade:{name}": statement.sql
        for name, statement in GRADE_STATEMENTS.items()
        if "INSERT" in statement.sql.upper() and "review_queue" in statement.sql
    }
    writers.update({
        f"integ:{name}": statement.sql
        for name, statement in INTEG_STATEMENTS.items()
        if "INSERT" in statement.sql.upper() and "review_queue" in statement.sql
    })

    assert len(writers) >= 2, (
        f"expected a review_queue insert in each of grade.py and integ.py, found {writers}. "
        "If the writers moved, this case has to follow them (FR-REVIEW-20)"
    )

    for name, sql in sorted(writers.items()):
        match = re.search(r"review_queue\s*\(([^)]*)\)", sql, re.IGNORECASE)
        assert match, f"{name}: could not read the INSERT column list from {sql!r}"
        columns = {column.strip() for column in match.group(1).split(",")}
        assert "run_id" in columns, (
            f"{name} writes columns {sorted(columns)} — no run_id. A queue row that belongs "
            "to no run is shared by every run over the cohort, and the second build "
            "overwrites the first's decisions"
        )
        assert "queue_id" in columns, f"{name} writes no queue_id: {sorted(columns)}"
        assert re.search(r"INSERT\s+OR\s+(REPLACE|IGNORE)", sql, re.IGNORECASE), (
            f"{name} is a bare INSERT, so a second enqueue of the same queue_id is a "
            "constraint error rather than the no-op 'each enqueues once' requires"
        )
