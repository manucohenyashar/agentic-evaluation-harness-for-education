"""The `M-STORE` surface these written-ahead cases call, named once.

TS-08 is written **ahead** of `M-STORE` (issue #14; test plan §8.2), so every name below is a
name the design implies but no code supplies yet. Collecting them here rather than spreading
them across six test files does three things:

1. **States the assumption where a reader will find it.** Design §3.3's Interfaces block
   declares `Store`, `TierHandle` and `BlobStore` and their members; it does **not** declare a
   constructor, a `Statement` factory, a metrics accessor, or the read-only entry point that
   `FR-STORE-13` requires. Those four are inferred, and the PR lists them as findings against
   the design rather than letting a green tick imply the design specified them.
2. **Makes a rename one edit.** If #10 calls it `Store.open()` rather than `open_store()`,
   one function here changes and nine cases keep asserting what they assert.
3. **Keeps `require()` inside the test body.** Every helper resolves its symbol when *called*,
   never at import — a module-level `from aeh.store import ...` produces a collection error,
   which is the failure mode `tests/support/impl.py` exists to prevent.

The invented names are also the `WRITTEN_AHEAD_BLOCKERS` keys, for the reason TS-74 records:
a key on a **protocol member** resolves the moment #10 creates the `Protocol`, firing the gate
two or three stories before the test could possibly run. `store_metrics`, `blob_store_stats`,
`StudentNameInTierDError` and `STATEMENTS` appear in no Interfaces block, so none can exist
before an implementation of the story that owns it does.

**`open_store` is no longer one of them, and #10 is why.** It was a key until #10 landed it and
the gate fired -- correctly -- on four cases that then all failed, because they call
`TierHandle.transaction` (#11) and `Store.blobs()` (#12), which #10 ships as deliberate stubs.
A constructor is the weakest available proxy for "every symbol this file calls exists" precisely
when the constructor's own story stubs its siblings. The lesson is recorded at length in
`tests/support/impl.py`; what it costs here is one line of this docstring.
"""

from __future__ import annotations

from typing import Any

from tests.support.impl import STORE_MODULE, require

# --- the four invented names, one per implementing story -------------------------------------

#: #10 — "Store opens the four lifetime tiers". The constructor design §3.3 never names.
OPEN_STORE = "open_store"

#: #11 — the observability surface design §3.3 describes in prose and `CT-STORE-17` makes
#: contract. One accessor serves `TC-STORE-03`, `TC-STORE-07` and `TC-STORE-24`.
STORE_METRICS = "store_metrics"

#: #12 — content-addressed blob accounting. `TC-STORE-09`'s "one file on disk" oracle is
#: asserted by walking the directory *and* cross-checked against this, so a stats accessor that
#: lies is caught by the independent count rather than believed.
BLOB_STORE_STATS = "blob_store_stats"

#: #13 — `FR-STORE-12` requires Tier D to *reject* a student-name column but names no error.
#: The case asserts an exact exception rather than "something raised", so the name is pinned
#: here and reported as a design gap.
STUDENT_NAME_ERROR = "StudentNameInTierDError"

#: **Unowned** — the declared-statement registry `TC-STORE-15` sweeps, and the one name of the
#: five that belongs to no story. The plan requires that "the registry contains no such
#: statement" and §3.3 types `query`'s argument as `Statement` rather than `str`, but nothing
#: says where the declared set lives. This comment said "#10" until #10 closed without it, which
#: is how the gap surfaced: the case's `require` then named a *closed* issue, sending its reader
#: to a story that could no longer act.
#:
#: Now attributed to **#13** — `FR-STORE-08` ("no search") is #13's, and a declared-statement
#: registry is how a store makes that promise checkable — and keyed there in
#: `WRITTEN_AHEAD_BLOCKERS`. That is a presumption, not a resolution: no issue's acceptance
#: criteria mention `STATEMENTS`, so if #13 closes without it this P0 case sits outside the gate
#: with nothing saying so. Reported in the PR; it needs an owner in the design or the issue
#: graph, and cannot be fixed from a test file.
#:
#: Resolved in `tests/artifact/test_tc_store_15_no_search_surface.py` rather than here, since
#: only that case needs it — listed here so the gap accounting stays in one place.
STATEMENT_REGISTRY = "STATEMENTS"

# --- two invented *signatures*, which are a different kind of gap ----------------------------
#
# The names above are things the design does not mention. These two are places the tests
# **contradict** what it does say, which is worth stating separately rather than burying:
#
# 1. `TierHandle.enqueue_write(self, unit: WriteUnit) -> None` (§3.3). Every case here calls
#    `enqueue_write(statement(...), **params)` instead, because `WriteUnit` is declared nowhere
#    — it appears in that one signature and in no data-model or Interfaces block. A test cannot
#    construct a type the design only names.
# 2. `transaction() -> ContextManager[Tx]` (§3.3). `Tx` is likewise never defined, so the cases
#    assume `tx.execute(stmt, **params)` by analogy with `query`.
#
# Both are reported in the PR against the design rather than resolved here. If #10 lands
# `WriteUnit` and `Tx` with real shapes, the two helpers below are where the tests adapt.
#
# A third assumption, of a different kind: `TC-STORE-03` shares **one** `TierHandle` across nine
# threads. Neither §3.3 nor `FR-STORE-03` says a handle is safe for concurrent `query`, and
# `CT-STORE-04` promises only that "concurrent readers never block the writer" — which implies
# concurrency at the store, not necessarily through a single handle object. If #11 decides a
# handle is per-thread, that case needs one handle per reader and the PR flags it now rather
# than leaving the next reader to discover it from a segfault.


def open_store(data_dir, issue: str = "#10", **kwargs: Any):
    """Open a `Store` rooted at `data_dir`.

    `read_only=True` is `FR-STORE-13`'s entry point — "support opening a Tier P database
    read-only, so an imported package can be inspected before it is trusted". §3.3's
    `package(self, package_id: str) -> TierHandle` has nowhere to say so, which is the gap
    `TC-STORE-16` reports.
    """
    factory = require(STORE_MODULE, OPEN_STORE, issue=issue)
    return factory(data_dir, **kwargs)


def statement(text: str, issue: str = "#10"):
    """A declared `Statement`, the only thing `TierHandle.query` accepts.

    Declared in §3.3's Interfaces block as a type, so it is #10's to supply. Tests build them
    from literals held in module constants — never from an f-string, which is the shape
    `SEC-15`'s walker exists to reject and which these files must not model.
    """
    Statement = require(STORE_MODULE, "Statement", issue=issue)
    return Statement(text)


def store_metrics(store, issue: str = "#11"):
    """The emitted signals as a mapping. See `tests.support.store_vocabulary.STORE_SIGNALS`."""
    accessor = require(STORE_MODULE, STORE_METRICS, issue=issue)
    return accessor(store)


def blob_store_stats(blobs, issue: str = "#12"):
    """Blob-directory accounting: at least `file_count` and `bytes_on_disk`."""
    accessor = require(STORE_MODULE, BLOB_STORE_STATS, issue=issue)
    return accessor(blobs)


def student_name_error(issue: str = "#13"):
    """The exception `FR-STORE-12` requires but does not name."""
    return require(STORE_MODULE, STUDENT_NAME_ERROR, issue=issue)
