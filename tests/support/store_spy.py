"""The store spy — a write-audit hook, not a store.

Test plan §4.2 is explicit that the databases are **not doubled**: store-touching cases use
real SQLite in a per-test temp dir, and §4.10 forbids an in-memory stand-in for the
`CT-STORE` contract outright, because a synchronously-committing fake hides every
`CT-STORE-02` violation.

So this is *not* a fake store. It is the write-audit hook the prohibition cases need:
several clauses assert that a module writes **nothing at all**, and the only way to assert
that positively is to hand it something that records. `TC-CONF-C09` is the canonical case —
*"Run a full resolution with the data directory, the blob directory and the database under a
write-audit hook; assert zero writes of any kind"* — and its oracle is "an empty write log".

Shaped after design §3.3's `Store` / `TierHandle` interfaces so a module under test can take
it wherever it takes a real store.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence


@dataclass(frozen=True)
class WriteRecord:
    """One observed write. `in_transaction` matters: `CT-STORE-03` scopes atomicity to a
    single `transaction()` body, so a case checking atomicity needs to see the grouping."""

    tier: str            # "package:<id>" | "cohort:<id>" | "durable" | "blobs"
    operation: str       # "enqueue_write" | "transaction_write" | "blob_put" | "purge_cohort"
    payload: Any
    in_transaction: bool = False


@dataclass
class StoreSpy:
    """Records every write reaching it and never persists anything."""

    writes: list[WriteRecord] = field(default_factory=list)
    queries: list[tuple[str, Any]] = field(default_factory=list)
    # One store, one blob namespace. `CT-STORE-07` promises `get`/`path` resolve any hash
    # `put` returned "for the lifetime of the owning tier" — so it must survive being reached
    # through a second `blobs()` handle, exactly as the real content-addressed directory does.
    _blob_bytes: dict[str, bytes] = field(default_factory=dict, repr=False)

    # -- Store surface (design §3.3) ----------------------------------------------------
    def package(self, package_id: str) -> "TierHandleSpy":
        return TierHandleSpy(self, f"package:{package_id}")

    def cohort(self, cohort_id: str) -> "TierHandleSpy":
        return TierHandleSpy(self, f"cohort:{cohort_id}")

    def durable(self) -> "TierHandleSpy":
        return TierHandleSpy(self, "durable")

    def blobs(self) -> "BlobStoreSpy":
        return BlobStoreSpy(self)

    def purge_cohort(self, cohort_id: str) -> None:
        self.writes.append(
            WriteRecord(tier=f"cohort:{cohort_id}", operation="purge_cohort", payload=cohort_id)
        )

    # -- assertions ---------------------------------------------------------------------
    def assert_no_writes(self) -> None:
        """The whole point of the spy. Used by every 'writes nothing' clause case."""
        if self.writes:
            observed = ", ".join(f"{w.tier}:{w.operation}" for w in self.writes)
            raise AssertionError(
                f"expected zero writes, but {len(self.writes)} were made: {observed}"
            )

    def writes_to(self, tier: str) -> list[WriteRecord]:
        return [w for w in self.writes if w.tier == tier]


@dataclass
class TierHandleSpy:
    """Design §3.3: a `TierHandle` offers `query`, `enqueue_write` and `transaction` — and
    nothing else (`CT-STORE-01`). Kept to exactly those three so a module that reaches for a
    fourth method fails here rather than against the real store."""

    _spy: StoreSpy
    _tier: str
    _in_transaction: bool = False
    _buffer: list[WriteRecord] | None = None

    def query(self, stmt: Any, **params: Any) -> Sequence[Any]:
        self._spy.queries.append((self._tier, (stmt, params)))
        return []

    def enqueue_write(self, unit: Any) -> None:
        record = WriteRecord(
            tier=self._tier,
            operation="transaction_write" if self._in_transaction else "enqueue_write",
            payload=unit,
            in_transaction=self._in_transaction,
        )
        # Inside a transaction the write is held until the body exits cleanly.
        (self._buffer if self._buffer is not None else self._spy.writes).append(record)

    @contextmanager
    def transaction(self) -> Iterator["TierHandleSpy"]:
        """Atomic over the whole body (`CT-STORE-03`) — including the failure half.

        A body that raises leaves **nothing** in the write log. Recording writes from an
        aborted transaction would make "both present or both absent after any crash"
        untestable: a case asserting nothing was committed would pass vacuously against a
        spy that had faithfully recorded the rollback.
        """
        buffered: list[WriteRecord] = []
        nested = TierHandleSpy(self._spy, self._tier, _in_transaction=True, _buffer=buffered)
        yield nested
        # Reached only on a clean exit; an exception propagates and the buffer is dropped.
        self._spy.writes.extend(buffered)


@dataclass
class BlobStoreSpy:
    """Content-addressed like the real one (`CT-STORE-07`: identical bytes, identical hash,
    one copy) so a caller's dedup expectations hold, but nothing touches disk."""

    _spy: StoreSpy

    def put(self, data: bytes) -> str:
        import hashlib

        content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
        # Idempotent: identical bytes store one copy, and re-putting them is not a second
        # write. The real store deduplicates on write (FR-STORE-06), so a spy that counted
        # two would make a dedup assertion fail against a correct implementation.
        if content_hash not in self._spy._blob_bytes:
            self._spy._blob_bytes[content_hash] = data
            self._spy.writes.append(
                WriteRecord(tier="blobs", operation="blob_put", payload=content_hash)
            )
        return content_hash

    def get(self, content_hash: str) -> bytes:
        return self._spy._blob_bytes[content_hash]
