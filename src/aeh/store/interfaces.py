"""The store's public shapes: `Statement`, `Tier`, `TierHandle`, `BlobStore` and `Store`."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ContextManager, Mapping, Protocol, Sequence


#: The tiers holding an open `transaction()` on this thread, as a per-tier **depth** — not a
#: set. Same-tier nesting is legal at the bookkeeping level (two cohort handles are two
#: files), and a set's difference operation would lose the outer tier when an inner
#: same-tier transaction exits, disarming the cross-tier guard for the rest of the outer
#: body. A counter keeps the outer tier visible until its own transaction closes. (Found by
#: TC-STORE-C03's own review: hold cohort A, open cohort B, close B, open durable — the set
#: version split silently. Same-tier nesting on SQLite itself still fails on its own terms.)
_OPEN_TX_TIERS = threading.local()


# --- the declared-statement type ---------------------------------------------------------------


class Statement(str):
    """A SQL statement the caller declared, rather than assembled.

    A `str` subclass, and deliberately so: a module-level SQL literal **is** a declared
    statement, which is the pattern every caller already uses (`FUZZ-07`'s `LEDGER_ROW`,
    `TC-STATS-C18`'s `sqlite_master` read), and a type that rejected those would force every
    caller to wrap a literal in a constructor for no gain in safety.

    What the type buys is the thing `FR-STORE-08` is actually about. `TierHandle.query` is
    annotated `Statement`, so `SEC-15`'s reflective probe can tell this interface from
    `query(sql: str)` — and inside this module the value that reaches `execute()` is
    `declared.sql`, an attribute of a declared statement, which is the shape
    `tests/support/sql_scan.py` sanctions. There is no path by which text assembled *in this
    module* reaches SQLite.

    It is **not** a defence against a caller writing bad SQL, and nothing here pretends
    otherwise: every caller is in-process trusted code and there is no untrusted input path into
    a statement. `CT-STORE-08`'s guarantee is the absence of a *search surface* — no similarity,
    no embeddings, no free text over student work — not the rejection of SQL.
    """

    __slots__ = ()

    @property
    def sql(self) -> str:
        """The statement text. Passing this, rather than the parameter, is the point."""
        return str(self)


#: What `query` hands back. `sqlite3.Row` supports both `row[0]` and `row["column"]`, which is
#: what the merged suites already assume — `TC-STATS-C18` indexes positionally and `FUZZ-07`
#: reads `row["status"]`.
Row = sqlite3.Row


@dataclass(frozen=True)
class WriteUnit:
    """One row bound for the single-writer queue (`FR-STORE-03`).

    Declared so `TierHandle.enqueue_write`'s signature matches §3.3's Interfaces block from the
    first commit. #11 owns what happens to it.
    """

    statement: Statement
    params: Mapping[str, Any] = field(default_factory=dict)


# --- the protocols §3.3 declares ----------------------------------------------------------------


class TierHandle(Protocol):
    """`query`, `enqueue_write`, `transaction` — and nothing else (`CT-STORE-01`)."""

    def query(self, statement: Statement, **params: Any) -> Sequence[Row]: ...

    def enqueue_write(self, unit: WriteUnit) -> None: ...

    def transaction(self) -> ContextManager[Any]: ...


class BlobStore(Protocol):
    """Content-addressed on SHA-256 (`CT-STORE-07`). Implemented by #12."""

    def put(self, data: bytes) -> str: ...

    def get(self, content_hash: str) -> bytes: ...

    def path(self, content_hash: str) -> Path: ...


class Store(Protocol):
    """Exactly three handle kinds, plus `blobs()` and `purge_cohort()` (`CT-STORE-01`)."""

    def package(self, package_id: str) -> TierHandle: ...

    def cohort(self, cohort_id: str) -> TierHandle: ...

    def durable(self) -> TierHandle: ...

    def blobs(self) -> BlobStore: ...

    def purge_cohort(self, cohort_id: str) -> Any: ...


# --- tiers -------------------------------------------------------------------------------------


class Tier(str, Enum):
    """The three physical databases, named as §3.3's data model names them.

    Three rather than four: **C and R share one file**, deliberately, because they are created
    and purged together and one file keeps `purge_cohort` a `VACUUM` on one database rather than
    a two-file consistency problem (§3.3). `FR-STORE-01` counts four *tiers*; this counts files.
    """

    PACKAGE = "package"
    COHORT = "cohort"
    DURABLE = "durable"
