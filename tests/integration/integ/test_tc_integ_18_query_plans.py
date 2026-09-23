"""`TS-86` (issue #380) — `TC-INTEG-18`: the gate's hot reads are index-backed
(`FR-INTEG-12`, `NFR-INTEG-01`, gap-fix test plan §5 / §6).

| Case | Input | Expected |
|---|---|---|
| `TC-INTEG-18` | `EXPLAIN QUERY PLAN` for `INTEG_STATEMENTS["read_document"]`, `count_units` and `max_retry_attempts` after migrations | plans name `idx_document_submission`, `idx_wu_cell` and `idx_wu_cell`; none shows `SCAN work_unit` or `SCAN document` |

**Why a query plan is the oracle.** `NFR-INTEG-01` budgets the gate at under 1% of run time, and
`PERF-06` was red at 2.25% on the branch that prompted this delta. A wall-clock assertion alone
would tell you the gate got slower without saying why, and would move with the machine. The plan
text is the *mechanism*: a full scan of `work_unit` is the thing that makes the gate quadratic in
the cohort, and it is visible here on one submission, long before it is visible on a timer.

**The requirement is the absence of a scan; the index names are the pin.** The two assertions do
different jobs. "No `SCAN work_unit` / `SCAN document`" is what `FR-INTEG-12` actually demands and
it holds whatever the planner chooses. The per-statement index name is a regression pin: it makes
a silent change of access path visible in review rather than as a slow afternoon six months on.

**A divergence from the plan, reported rather than smoothed over.** The plan expects
`max_retry_attempts` to use `idx_wu_cell`. SQLite chooses **`idx_wu_pairs`**, whose columns
`(run_id, status, stage, submission_id, criterion_id)` are strictly more selective for that
statement's `WHERE` than `idx_wu_cell`'s `(run_id, submission_id, criterion_id)`. The shipped
behaviour is *better* than the plan's expectation, not worse, and both satisfy `FR-INTEG-12`. So
this case pins what ships and #380 reports the expectation for correction — pinning the plan's
name would redden the suite over a planner choice that is an improvement.

**The plans are read on a seeded store**, not an empty one: SQLite's planner is free to choose
differently when a table has no rows, and a plan measured on an empty database is not the plan
production runs.
"""

from __future__ import annotations

import re
import sqlite3
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
from aeh.integ import INTEG_STATEMENTS
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

#: The three statements `FR-INTEG-12` names, with the index each must ride.
#:
#: `max_retry_attempts` carries the divergence described in the module docstring: the plan
#: expects `idx_wu_cell`, SQLite chooses the more selective `idx_wu_pairs`. Both are index
#: searches, so `FR-INTEG-12` holds either way; the value here is what ships.
EXPECTED_INDEX = {
    "read_document": "idx_document_submission",
    "count_units": "idx_wu_cell",
    "max_retry_attempts": "idx_wu_pairs",
}

#: The plan's own expectation, kept beside the shipped one so the divergence is legible in the
#: source rather than only in a PR nobody re-reads.
PLAN_EXPECTED_INDEX = {**EXPECTED_INDEX, "max_retry_attempts": "idx_wu_cell"}

#: The access paths `FR-INTEG-12` forbids outright.
FORBIDDEN = ("SCAN work_unit", "SCAN document")

#: Representative bindings for the declared statements' named parameters. Values that
#: exist in the seeded store, so the planner sees the query production issues.
_PARAM_VALUES = {
    "submission_id": "S01",
    "criterion_id": "C1",
    "status": "pending",
    "stage": "extract",
}


def _plan(connection: sqlite3.Connection, sql: str) -> list[str]:
    """`EXPLAIN QUERY PLAN` rows for a declared statement, with its parameters BOUND.

    Real bindings rather than a NULL substitution. Both were measured against the same mutant
    (`read_document` moved onto an unindexed column) and **both caught it**, so this is a
    robustness choice, not a fix for a demonstrated hole: `WHERE col = NULL` is a shape SQLite
    is free to plan differently from `WHERE col = ?`, and the plan worth asserting is the one
    production issues. Recorded precisely because the tempting version of this note — "the NULL
    draft let a mutant through" — is not what happened.
    """
    names = sorted(set(re.findall(r":(\w+)", sql)))
    params = {name: _PARAM_VALUES.get(name, "x") for name in names}
    return [row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + sql, params)]


@pytest.fixture
def cohort_connection(tmp_data_dir):
    """A migrated, seeded cohort file, opened read-only for planning.

    Seeded rather than empty: the planner may choose a different path on a table with no rows,
    and a plan measured on an empty database is not the one production runs.
    """
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _version = seed_run(
            store,
            submissions=("S01", "S02"),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
                {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
            ),
        )
        orchestrator.enumerate_units(run_id)
    finally:
        store.close()

    connection = sqlite3.connect(tmp_data_dir / "cohorts" / f"{ORCH_COHORT_ID}.sqlite")
    try:
        yield connection
    finally:
        connection.close()


# --- TC-INTEG-18 ---------------------------------------------------------------------------


@pytest.mark.parametrize("statement", sorted(EXPECTED_INDEX))
def test_tc_integ_18_the_gate_hot_reads_never_scan(statement, cohort_connection):
    """`FR-INTEG-12`'s actual requirement: no full scan of `work_unit` or `document`.

    This is the assertion that holds whatever the planner decides, and it is the one that
    matters: a scan of `work_unit` makes the gate quadratic in the cohort, which is how
    `PERF-06` reached 2.25% against a 1% budget.
    """
    plan = _plan(cohort_connection, INTEG_STATEMENTS[statement].sql)
    offending = [row for row in plan for bad in FORBIDDEN if bad in row]
    assert offending == [], (
        f"INTEG_STATEMENTS[{statement!r}] scans a table FR-INTEG-12 forbids scanning: "
        f"{offending}. Full plan: {plan}"
    )
    assert plan and any("USING" in row and "INDEX" in row for row in plan), (
        f"INTEG_STATEMENTS[{statement!r}] rides no index at all: {plan}"
    )


@pytest.mark.parametrize("statement", sorted(EXPECTED_INDEX))
def test_tc_integ_18_each_hot_read_rides_its_pinned_index(statement, cohort_connection):
    """The regression pin: each statement's access path, named.

    Separate from the no-scan case on purpose. A changed index is not necessarily a defect —
    it may be an improvement, as `max_retry_attempts` is — but it should be *seen*, and a
    combined assertion would report "the gate is slow" when the real news is "the access path
    moved".
    """
    plan = _plan(cohort_connection, INTEG_STATEMENTS[statement].sql)
    expected = EXPECTED_INDEX[statement]
    assert any(expected in row for row in plan), (
        f"INTEG_STATEMENTS[{statement!r}] no longer rides {expected!r}: {plan}. If the new path "
        f"is deliberate, move the pin in the same change — the plan's own expectation for this "
        f"statement is {PLAN_EXPECTED_INDEX[statement]!r}"
    )


def test_tc_integ_18_the_indexes_fr_integ_12_names_exist(cohort_connection):
    """The indexes themselves exist after migration.

    Without this the two cases above could both pass on a database where the planner happened
    to find another route, and the migration that was supposed to create these indexes could
    have quietly done nothing.
    """
    present = {
        row[0] for row in cohort_connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing = sorted(set(EXPECTED_INDEX.values()) - present)
    assert missing == [], (
        f"FR-INTEG-12's indexes are absent after migration: {missing}. Present: {sorted(present)}"
    )
