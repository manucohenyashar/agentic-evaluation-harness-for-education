"""`CT-STORE-18` — the non-promise: no query returns rows in an order this module chose.

Case `TC-STORE-C18` (P0), test plan §6.11.3. Issue #17 (TS-60). The plan's automation target
is this file's name.

**The technique is the case: do not assert that order varies — make it vary**, and assert
every reader still behaves correctly. A shim deliberately shuffles every orderless `query`
result, seeded per run; the sanctioned escape (a stated `ORDER BY`) is unaffected; and the
clause's second non-promise — no cross-tier transaction, join, or referential integrity — is
attempted and refused, with the owner (not the store) holding the reference check.

Rung-3 note, recorded: the consumer sweep ("run the full suite of every reading module
against the shuffling store") sweeps consumers that do not exist yet — M-ORCH, M-GRADE,
M-REVIEW, M-STATS. The store-side differential below is the case's live half; the consumer
registry fills as modules land.

`Written ahead of implementation: yes` is stale; green by design.
"""

from __future__ import annotations

import random
import sqlite3

import pytest

import aeh.store as store_module
from aeh.store import store_metrics
from tests.support.store_api import open_store, statement

pytestmark = pytest.mark.contract

ISSUE = "#17"

#: The reading consumers CT-STORE-18 sweeps, rung 3, as they land.
CONSUMERS: tuple[str, ...] = ()


class ShufflingQuery:
    """Patches `SqliteTierHandle.query` at the class level: every orderless result comes
    back shuffled, seeded per run so failures reproduce. The handle uses `__slots__`, so an
    instance-level shim is not possible — the class patch is also what makes the shim hit
    every handle a caller holds, which is what a version bump or VACUUM would do."""

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)
        self._original = store_module.SqliteTierHandle.query

    def install(self) -> None:
        shim = self

        def query(handle, stmt, **params):
            rows = list(self._original(handle, stmt, **params))
            if "order by" not in str(stmt).lower():
                self._random.shuffle(rows)
            return rows

        store_module.SqliteTierHandle.query = query  # type: ignore[method-assign]

    def uninstall(self) -> None:
        store_module.SqliteTierHandle.query = self._original  # type: ignore[method-assign]


def test_tc_store_c18_shuffled_order_changes_no_correct_reader(tmp_data_dir, monkeypatch):
    """The differential: the same reads against the natural store and the shuffling store
    must produce the same *sets* — and a stated `ORDER BY` must survive the shim exactly."""
    for store_kind in ("natural", "shuffling"):
        data_dir = tmp_data_dir / store_kind
        store = open_store(data_dir)
        handle = store.cohort("s-c18")
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO cohort (cohort_id, consent_class, created_at) "
                "VALUES ('s-c18', 'consented', '2026-01-01')", issue=ISSUE))
            tx.execute(statement(
                "INSERT INTO roster (cohort_id, student_ref) VALUES ('s-c18', 'ref-1')",
                issue=ISSUE))
            tx.execute(statement(
                "INSERT INTO roster (cohort_id, student_ref) VALUES ('s-c18', 'ref-2')",
                issue=ISSUE))
            tx.execute(statement(
                "INSERT INTO roster (cohort_id, student_ref) VALUES ('s-c18', 'ref-3')",
                issue=ISSUE))
        shuffler = ShufflingQuery(seed=20260906)
        if store_kind == "shuffling":
            shuffler.install()
            monkeypatch.undo = shuffler.uninstall  # restored even on failure

        # The orderless read: a correct caller reads a SET (or counts), never an order.
        rows = handle.query(statement(
            "SELECT student_ref FROM roster", issue=ISSUE))
        found = {row[0] for row in rows}
        assert found == {"ref-1", "ref-2", "ref-3"}, (
            f"TC-STORE-C18 ({store_kind}): the orderless read lost rows under the shim: "
            f"{found}. The non-promise is about ORDER, not presence — if shuffling changes "
            "membership, the shim is broken, not the reader."
        )
        # The sanctioned escape: a stated ORDER BY is unaffected by the shim.
        ordered = handle.query(statement(
            "SELECT student_ref FROM roster ORDER BY student_ref", issue=ISSUE))
        assert [row[0] for row in ordered] == ["ref-1", "ref-2", "ref-3"], (
            f"TC-STORE-C18 ({store_kind}): a stated ORDER BY did not hold under the shim. "
            "The escape is the clause's whole point — callers needing an order state it, "
            "and it holds."
        )
        if store_kind == "shuffling":
            shuffler.uninstall()
            monkeypatch.undo = lambda: None
        store.close()


def test_tc_store_c18_no_cross_tier_join_or_referential_integrity(tmp_data_dir):
    """The second non-promise: *'no cross-tier transaction, join, or referential integrity —
    a Tier R row referencing a Tier P row is checked by the owning module.'*

    Attempted three ways, each refused or absent: no handle can see another tier's file; a
    cross-file JOIN cannot be expressed; and an orphan Tier R row referencing a removed Tier
    P row raises from the *owning module's* check — here simulated as the caller's own
    lookup returning nothing — while the store accepts the row, because cross-tier
    integrity is not this module's to enforce."""
    store = open_store(tmp_data_dir)
    package = store.package("pkg-c18")
    cohort = store.cohort("s-c18-ref")
    with package.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            "VALUES ('pkg-c18', '2026-01-01')", issue=ISSUE))
    with cohort.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO work_unit (work_id, submission_id, stage, status) "
            "VALUES ('w-refs-pkg', NULL, 'judge', 'pending')", issue=ISSUE))

    # 1. A handle exposes exactly its tier: the package handle sees no cohort tables.
    with pytest.raises(sqlite3.OperationalError):
        package.query(statement(
            "SELECT COUNT(*) FROM work_unit", issue=ISSUE))
    # 2. A cross-file JOIN cannot even be written without ATTACH — which the durable tier's
    #    authorizer refuses, and the other tiers have no second file to name.
    with pytest.raises(sqlite3.OperationalError):
        cohort.query(statement(
            "SELECT COUNT(*) FROM work_unit w, package p", issue=ISSUE))
    # 3. The orphan: a Tier R row naming a Tier P object the package file does not contain.
    #    The store ACCEPTS it — `criterion_id` is TEXT on this side of a file boundary no FK
    #    can cross — and the owner's check is what raises.
    import time

    handle = cohort
    handle.enqueue_write(statement(
        "INSERT INTO verdict (verdict_id, work_id, judge_id, band) "
        "VALUES ('v-orphan', 'w-refs-pkg', 'judge-1', 'b1')", issue=ISSUE))
    deadline = time.monotonic() + 30
    while int(store_metrics(store)["write_queue_depth"]) > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    rows = handle.query(statement(
        "SELECT COUNT(*) FROM verdict WHERE verdict_id = 'v-orphan'", issue=ISSUE))
    assert rows[0][0] == 1, (
        "TC-STORE-C18: the store refused a cross-tier reference. The non-promise is the "
        "point: cross-tier integrity is the owning module's check, and a store that enforced "
        "it would be promising a join it never declared."
    )
    # The owner's check, simulated: the owning module looks up the criterion in Tier P.
    criteria = package.query(statement(
        "SELECT COUNT(*) FROM criterion WHERE criterion_id = 'CRIT-nonexistent'", issue=ISSUE))
    assert criteria[0][0] == 0
    store.close()


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_tc_store_c18_the_consumer_sweep_runs_against_the_shuffling_store(consumer):
    """The rung-3 sweep, parametrized over the consumer registry. Empty today; the scaffold
    exists so the sweep is unmissable when the first reading module lands."""
    pytest.fail(
        f"TC-STORE-C18: consumer {consumer} is registered without a sweep body. Bind the "
        "consumer's full suite against the shuffling store when the module lands — the "
        "differential (shuffled output == natural output) is the oracle."
    )
