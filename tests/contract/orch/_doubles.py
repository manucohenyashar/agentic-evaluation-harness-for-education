"""Shared instruments for the `M-ORCH` contract suite (issue #67, TS-64).

The suite behind `TC-ORCH-C01..C21` (test plan §6.11.7). The run-shaped world —
real store, real Tier P package, real cohort ledger, resolved `RunConfig` — is
`tests/support/orch_run.py`'s (built by #63); this file adds the three
instruments the clause cases need and the FR cases do not:

- `LedgerAuditHandle` — a pass-through `TierHandle` wrapper that lets every
  statement through AND records it with the **module that issued it** (the first
  non-`aeh.store`, non-tests frame above the store). `CT-ORCH-17`'s write audit
  reads the log; unlike `tests/support/store_spy.StoreSpy` (a non-persisting
  fake for "writes nothing at all" cases) this one lets the real writes through.
  Shaped after `tests/contract/setup/_doubles.AuditHandle` (the TC-SETUP-C11
  precedent), with the caller attribution the sole-writership clause needs.
- `KillCohortHandle` — the same wrapper shape raising `KillError` (a
  `BaseException`, the store's own rollback signal) when a statement matching a
  marker executes for the nth time: `TC-ORCH-C19`'s mid-commit kills. The
  `KillHandle` precedent (`tests/contract/setup/_doubles.py`) is the pattern; a
  killed transaction is indistinguishable from a killed process as far as the
  database can tell — an uncommitted transaction that rolls back.
- `install_audit` / `install_kill` — the two installers. The store caches one
  handle per tier in `store._handles` (`SqliteStore._handles`), so the wrapper
  replaces the cached entry: every `store.cohort(...)` / `store.durable()`
  accessor the orchestrator resolves hands back the wrapper. Touching the
  store's private cache is test scaffolding, disclosed here once; no production
  module may do this.

Isolation note: every wrapper delegates to the REAL SQLite handle. Nothing here
stands in for the store (§4.2 forbids it) — the writes land, the queries
answer, and only the observation (or the kill) is injected.
"""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class KillError(BaseException):
    """A process kill, not a test failure.

    `BaseException` deliberately, for the reason `tests/contract/setup/_doubles.py`
    spells out: `aeh.store`'s `transaction()` rolls back on `BaseException` rather
    than `Exception` precisely so an uncontrolled kill — a `SIGKILL` mid-transaction
    — leaves no open transaction behind. An `Exception` here would be a *handled*
    failure, which is not the thing the checkpoint kills assert against.
    """


def _caller_module() -> str:
    """The module executing the current statement, by frame walk.

    The frames between the caller and the store's `execute` are the store's own
    (`aeh/store.py`) and this wrapper's; both are skipped. A frame under `src/aeh`
    names the production module (`aeh.orch`, `aeh.judge`, ...); a frame under
    `tests/` names the test scaffolding, which seeds disclosedly — recorded as
    `tests:<file>` so a case can exclude it without pretending it did not happen.
    """
    depth = 2
    try:
        frame = sys._getframe(depth)
    except ValueError:
        return "<unknown>"
    while frame is not None:
        path = frame.f_code.co_filename.replace("\\", "/")
        if "/aeh/store" in path or "/_doubles.py" in path:
            frame = frame.f_back
            continue
        match = re.search(r"/aeh/([a-z_]+)\.py", path)
        if match:
            return f"aeh.{match.group(1)}"
        match = re.search(r"/tests/([A-Za-z0-9_/]+)\.py", path)
        if match:
            return f"tests:{match.group(1).split('/')[-1]}"
        frame = frame.f_back
    return "<unknown>"


_WRITE_PREFIXES = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "CREATE",
    "ALTER",
    "DROP",
    "REPLACE",
)


def _sql_text(stmt: Any) -> str:
    sql = stmt.sql if hasattr(stmt, "sql") else str(stmt)
    return " ".join(sql.split())


def _table_of(sql: str) -> str | None:
    """The table a write statement names — the audit's first grouping key."""
    match = re.match(
        r"(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO|"
        r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|ALTER\s+TABLE|DROP\s+TABLE)"
        r"\s+[\"'`]?([A-Za-z_][A-Za-z0-9_]*)",
        sql,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


class WriteRecord:
    """One observed write: which module's frame executed it, against which table,
    with the normalized SQL and the read it reports (`changes()` is the ledger's
    own account of what the write did)."""

    __slots__ = ("module", "table", "sql")

    def __init__(self, module: str, sql: str) -> None:
        self.module = module
        self.sql = sql
        self.table = _table_of(sql)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic aid
        return f"<write {self.module} -> {self.table}: {self.sql[:60]}>"


class LedgerAuditHandle:
    """A `TierHandle` wrapper: every statement through, every write recorded.

    `writes` logs every statement executed inside a `transaction()` body with the
    executing module's name (the frame walk above — the store is the conduit, not
    the writer); `reads` logs every `query` the same way. The SQL is normalized
    verbatim (`Statement.sql`), so a case can group by table without re-implementing
    the store.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.writes: list[WriteRecord] = []
        self.reads: list[tuple[str, str]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with self._inner.transaction() as tx:
            audit = self

            class _AuditTx:
                def execute(_self, stmt: Any, **params: Any) -> Any:
                    sql = _sql_text(stmt)
                    upper = sql.upper()
                    if any(upper.startswith(p) for p in _WRITE_PREFIXES):
                        audit.writes.append(WriteRecord(_caller_module(), sql))
                    return tx.execute(stmt, **params)

            yield _AuditTx()

    def query(self, stmt: Any, **params: Any) -> Any:
        self.reads.append((_caller_module(), _sql_text(stmt)))
        return self._inner.query(stmt, **params)


class KillCohortHandle:
    """A `TierHandle` wrapper whose `transaction()` dies when a named statement
    executes for the nth time.

    The kill point is `(sql_marker, occurrence)` — the transaction body dies
    (with `KillError`, so the store rolls back everything the body wrote) after
    the occurrence-th execute of a statement whose SQL contains `sql_marker`.
    Everything else — `query`, `enqueue_write`, transactions that never reach
    the marker — passes through untouched, so a flow driven under the handle is
    the real flow until the one named statement lands.
    """

    def __init__(self, inner: Any, marker: str, occurrence: int = 1) -> None:
        self._inner = inner
        self._marker = marker
        self._occurrence = occurrence
        self.seen = 0
        self.killed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        point = self
        with self._inner.transaction() as tx:

            class _KillTx:
                def __init__(_self) -> None:
                    _self._fired = False

                def execute(_self, stmt: Any, **params: Any) -> Any:
                    out = tx.execute(stmt, **params)
                    sql = _sql_text(stmt)
                    if (
                        not _self._fired
                        and point._marker in sql
                    ):
                        point.seen += 1
                        if point.seen >= point._occurrence:
                            point.killed = True
                            _self._fired = True
                            raise KillError(
                                f"process killed after {sql[:60]!r} ran "
                                "(uncommitted — the store's rollback is the kill)"
                            )
                    return out

            yield _KillTx()

    def query(self, stmt: Any, **params: Any) -> Any:
        return self._inner.query(stmt, **params)


def _swap_cached_handle(store: Any, tier: Any, key: str, wrapper: Any) -> None:
    """Put `wrapper` where the store's cached handle for `(tier, key)` sits.

    The store caches one handle per (tier, key, mode) in `SqliteStore._handles`, and
    every `store.cohort(...)` / `store.durable()` resolution returns the cached one —
    so the wrapper takes the cached entry's place and every later accessor call (the
    orchestrator's, the workers', the sweeper's) resolves to it. The store is slotted
    and its accessors are class attributes, so the cache — not the accessor — is the
    seam. Touching `_handles` is test scaffolding, disclosed in this module's
    docstring; no production module may do this.
    """
    cache_key = (tier, key, store._read_only)
    if store._handles.get(cache_key) is None:
        raise AssertionError(
            f"no cached handle for ({tier}, {key!r}) — open the tier before "
            "installing; the wrapper wraps the REAL handle and has nothing to "
            "wrap otherwise"
        )
    store._handles[cache_key] = wrapper


def install_audit(store: Any, cohort_id: str) -> tuple[LedgerAuditHandle, LedgerAuditHandle]:
    """Audit the cohort and durable tiers of one store.

    Returns `(cohort_audit, durable_audit)`. The package tier is untouched: the
    clause's sole-writership surface is the run ledger (`run`, `work_unit`,
    `run_metrics`), and wrapping a tier the flow under test never reads would
    only widen the log without narrowing the oracle.
    """
    from aeh.store import Tier

    cohort_audit = LedgerAuditHandle(store.cohort(cohort_id))
    durable_audit = LedgerAuditHandle(store.durable())
    _swap_cached_handle(store, Tier.COHORT, cohort_id, cohort_audit)
    _swap_cached_handle(store, Tier.DURABLE, "", durable_audit)
    return cohort_audit, durable_audit


def install_kill(
    store: Any, cohort_id: str, marker: str, occurrence: int = 1
) -> KillCohortHandle:
    """Install the kill on one store's cohort tier at the named statement."""
    from aeh.store import Tier

    handle = KillCohortHandle(store.cohort(cohort_id), marker, occurrence)
    _swap_cached_handle(store, Tier.COHORT, cohort_id, handle)
    return handle


def unit_projection(store: Any, cohort_id: str, run_id: str) -> dict[tuple, str]:
    """The run's unit identities projected to status — the differential's shape
    (`tests/resilience/orch/test_resume.py`'s `_snapshot`, re-declared here so
    the contract file carries its own disclosed projection).

    The projection is the enumeration's own unit identity; the uniqueness
    invariant is `len(rows) == len(projection)` at the call site.
    """
    rows = store.cohort(cohort_id).query(
        "SELECT submission_id, stage, criterion_id, judge_id, origin, status "
        "FROM work_unit WHERE run_id = :r",
        r=run_id,
    )
    projection = {
        (r["submission_id"], r["stage"], r["criterion_id"], r["judge_id"], r["origin"]): r[
            "status"
        ]
        for r in rows
    }
    assert len(projection) == len(rows), (
        f"{len(rows) - len(projection)} result rows share a unit identity — the "
        "uniqueness invariant on work_id is violated"
    )
    return projection


def table_row_counts(store: Any, cohort_id: str) -> dict[str, int]:
    """Row counts for every table in the cohort ledger — the double-click and
    re-run invariants' 'no new rows in ANY table' half."""
    names = [
        row["name"]
        for row in store.cohort(cohort_id).query(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        name: store.cohort(cohort_id).query(f"SELECT COUNT(*) AS n FROM {name}")[0]["n"]
        for name in sorted(names)
    }


__all__ = [
    "KillCohortHandle",
    "KillError",
    "LedgerAuditHandle",
    "WriteRecord",
    "install_audit",
    "install_kill",
    "table_row_counts",
    "unit_projection",
]
