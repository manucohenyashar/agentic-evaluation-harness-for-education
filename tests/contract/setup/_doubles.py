"""Shared doubles and harness for the `M-SETUP` contract suite (issue #56, TS-63).

The suite behind `TC-SETUP-C01..C16` (test plan §6.11.6). The Stage A chain — real
store, real `Ingestor`, real `PackageCatalog`, scripted model transport — lives in
`tests/support/setup_harness.py` (built by issue #54 for the FR suite); this file
re-exports it and adds the three instruments the clause cases need and the FR
cases do not:

- `KillHandle` — a pass-through `TierHandle` wrapper that raises `KillError` (a
  `BaseException`, the store's own rollback signal) at a named point of the publish
  transaction: TC-SETUP-C02's randomized mid-publish kills. The wrapper touches
  nothing else, so a killed publish is indistinguishable from a killed process as
  far as the database can tell: an uncommitted transaction that rolls back.
- `AuditHandle` — a pass-through recording wrapper: every statement executed inside
  a transaction and every `query` is logged verbatim. TC-SETUP-C11's write audit
  reads the log; unlike `tests/support/store_spy.StoreSpy` (a non-persisting fake
  for "writes nothing at all" cases) this one lets the real writes through and
  records them.
- `FaultCatalog` — a `PackageCatalog` wrapper that raises a caller-chosen exception
  from one named method and delegates everything else. TC-SETUP-C12 drives the real
  M-PKG error types through the real boundary this way; nothing is stubbed that the
  clause does not name.

Written from an implementation audit that probed the shipped module (`aeh.setup`
landed with #50, b853ecf; the issue body's `Written ahead of implementation: yes`
is stale for the shipped half — those cases run green by design). One place where
a clause's guarantee is not yet enforced on shipped code; a bug in shipped code has
no `writtenahead` target to key on, so it is **disclosed in the case that names it
rather than shipped red**:

- **G1** (`no operation alters a published version`, `CT-SETUP-16`,
  `test_ct_setup_c16_surface.py`): after a finished setup,
  `SetupService.propose_inventory` does not refuse — `ensure_version`
  (`src/aeh/setup.py:588-599`) sees `draft_version() is None`, never consults
  `has_version()`, and mints a **second root version** on the same package
  (`create_version(None)` with no parent link), opening a fresh Stage A. The
  module's own `steps()` report for the same state says the opposite: "setup has
  finished …; a new instrument is a new package or a revision (FR-PKG-02)" — the
  report and the operation disagree, and the operation is the route CT-SETUP-16's
  "no way to attempt it" half exists to close. The published version itself is
  never altered (the lock holds; `TC-PKG-C01` holds the catalog end), so the case
  asserts the surface that does hold and discloses this route.

Also disclosed: the deferrals the test plan names for later modules, listed in the
case files that carry them (`TC-SETUP-C05`/`C10`/`C15` consumer halves — M-ORCH,
M-AGG, M-GRADE, M-CALIB, M-STATS, M-CONSOLE do not exist yet; `TC-SETUP-C11`'s
calibration-paper half — no intake surface accepts one, the #54 TC-SETUP-18
precedent).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from aeh.pkg import PackageCatalog

from tests.support.setup_harness import (  # re-export: the one Stage A chain
    ASSESSMENT_MD,
    INVENTORY_REPLY,
    RUBRIC_MD,
    SETUP_BUILD,
    ScriptedSetupProvider,
    ingest_document,
    make_setup_service,
    stage_chain,
)

__all__ = [
    "ASSESSMENT_MD",
    "AuditHandle",
    "FaultCatalog",
    "INVENTORY_REPLY",
    "KillError",
    "KillHandle",
    "RUBRIC_MD",
    "SETUP_BUILD",
    "ScriptedSetupProvider",
    "db_file_for",
    "ingest_document",
    "make_setup_service",
    "stage_chain",
    "stage_confirmed",
]


# -- TC-SETUP-C02: the randomized mid-publish kill -----------------------------------------

class KillError(BaseException):
    """A process kill, not a test failure.

    `BaseException` deliberately: `aeh.store`'s `transaction()` rolls back on
    `BaseException` rather than `Exception` precisely so an uncontrolled kill —
    `KeyboardInterrupt` mid-transaction — leaves no open transaction behind. An
    `Exception` here would be a *handled* failure, which is not the thing the
    clause asserts against."""


class KillHandle:
    """A `TierHandle` wrapper whose `transaction()` dies at a named point.

    Kill points, in the order a publish transaction reaches them:

    - `"before_begin"` — the kill lands before the store even opens the
      transaction body;
    - `"before_statement"` — the body is open (`BEGIN IMMEDIATE` done), the
      statement has not run;
    - `"after_statement"` — the statement has run, the body has not exited
      (nothing committed);
    - `"after_commit_body"` — the caller's body exited, the context manager has
      not closed the transaction (the commit decision has not been reached).

    Everything else — `query`, `enqueue_write`, the transaction itself when the
    point is not reached — passes through untouched. The handle wraps the REAL
    tier handle (`catalog._handle`), so the database under test is the real
    SQLite file throughout; only the kill is injected.
    """

    def __init__(self, inner, point: str) -> None:
        self._inner = inner
        self._point = point

    def query(self, *args, **kwargs):
        return self._inner.query(*args, **kwargs)

    def enqueue_write(self, *args, **kwargs):
        return self._inner.enqueue_write(*args, **kwargs)

    @contextmanager
    def transaction(self):
        point = self._point
        if point == "before_begin":
            raise KillError("killed before the transaction began")
        with self._inner.transaction() as tx:
            if point == "before_statement":
                raise KillError("killed inside the body, before the statement")

            class _TxProxy:
                def execute(_self, stmt, **params):
                    out = tx.execute(stmt, **params)
                    if point in ("after_statement", "mid_transaction"):
                        raise KillError(f"killed after the statement ran ({point})")
                    return out

            yield _TxProxy()
            if point == "after_commit_body":
                raise KillError("killed after the body, before the commit")


# -- TC-SETUP-C11: the write audit ----------------------------------------------------------

class AuditHandle:
    """A `TierHandle` wrapper that lets every statement through AND records it.

    `writes` logs every statement executed inside a `transaction()` body (the only
    write door the catalog uses); `reads` logs every `query`. The SQL is recorded
    verbatim (the store's `Statement` object normalizes whitespace on `.sql`), so
    a case can assert which TABLES a module's flow touched without re-implementing
    the store.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.writes: list[str] = []
        self.reads: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @contextmanager
    def transaction(self):
        with self._inner.transaction() as tx:
            audit = self

            class _AuditTx:
                def execute(_self, stmt, **params):
                    sql = stmt.sql if hasattr(stmt, "sql") else str(stmt)
                    audit.writes.append(" ".join(sql.split()))
                    return tx.execute(stmt, **params)

            yield _AuditTx()

    def query(self, stmt, **params):
        sql = stmt.sql if hasattr(stmt, "sql") else str(stmt)
        self.reads.append(" ".join(sql.split()))
        return self._inner.query(stmt, **params)


# -- TC-SETUP-C12: the M-PKG fault at the real boundary --------------------------------------

class FaultCatalog:
    """A `PackageCatalog` wrapper that raises `error` from `fault_method`.

    Every other member delegates to the real catalog, so the flow under test runs
    against real storage until the one named call. `SchemaLockViolation` raised
    here is the class `aeh.pkg` itself raises at its own guards — the fault is
    M-PKG's real refusal, injected at the seam M-SETUP owns the calling side of.
    """

    def __init__(self, inner: PackageCatalog, fault_method: str, error: BaseException) -> None:
        self._inner = inner
        self._fault_method = fault_method
        self._error = error
        self.fault_calls = 0

    def __getattr__(self, name):
        # Fires only for names the wrapper itself does not carry — i.e. every
        # catalog member, which either faults or delegates.
        if name == self._fault_method:
            return self._fault
        return getattr(self._inner, name)

    def _fault(self, *args, **kwargs):
        self.fault_calls += 1
        raise self._error


# -- small shared helpers --------------------------------------------------------------------

def stage_confirmed(chain, corrections=()):
    """Propose and confirm the inventory on a fresh chain — blocking gate 1 done."""
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id, corrections)
    return proposal


def db_file_for(data_dir: Path, package_id: str) -> Path:
    """The package tier's SQLite file, for assertions that read STORED DATA alone
    (TC-SETUP-C14's differential reads the rows without importing `aeh.setup`)."""
    hits = sorted(data_dir.rglob(f"{package_id}.pkg.sqlite"))
    if not hits:
        raise AssertionError(f"no package tier file for {package_id!r} under {data_dir}")
    return hits[0]
