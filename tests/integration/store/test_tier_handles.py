"""The four tier handles: WAL, foreign keys, and the read-only import path.

Cases `TC-STORE-01` (`FR-STORE-01`, P0), `TC-STORE-02` (`FR-STORE-14`, P0) and `TC-STORE-16`
(`FR-STORE-13`, P2), test plan §5.3. Issue #14 (TS-08); opened by issue #10, but blocked on
**#11** — all three cases write through `TierHandle.transaction`, which #10 ships as a stub.

Rung 2 throughout — real SQLite files in a real directory. §4.10 is explicit that consumers
test against a real temporary store rather than a double: "an in-memory fake that commits
synchronously would hide every `CT-STORE-02` violation". The same reasoning applies here.
`journal_mode` and `foreign_keys` are properties of a real connection to a real file, and a
double reports whatever it was written to report.

**Written ahead of implementation** (issue field; test plan §8.2). `aeh.store` exists since
#10, so these no longer red with `NotImplementedYet` from `require()` — they red with the
`NotImplementedError` #10 deliberately put in `TierHandle.transaction`, naming #11. They carry
`writtenahead` and are registered in `WRITTEN_AHEAD_BLOCKERS` under `#11 store_metrics`.

Every oracle here reads through an **independent** `sqlite3` connection to the file rather than
through the module under test — except where the requirement is explicitly about the connection
the module hands out (`TC-STORE-02`: `foreign_keys` is per-connection and not persisted, so an
outside connection cannot see it and asking the module is the only probe that means anything).
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from tests.support.impl import require_attr
from tests.support.store_api import open_store, statement
from tests.support.store_vocabulary import journal_mode, table_names

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#10"

#: Design §3.3's data model, verbatim. The file mapping *is* the requirement — "P (per package
#: file), C and R (per cohort file), D (one shared file)" — so it is asserted as exact paths
#: rather than by asking the store where it put things.
PACKAGE_FILE = "packages/{package_id}.pkg.sqlite"
COHORT_FILE = "cohorts/{cohort_id}.sqlite"
DURABLE_FILE = "durable.sqlite"

#: One Tier C table and one Tier R table, from design §3.3's tier table. C and R "share one file
#: deliberately: they are created and purged together, and a single file keeps the purge a
#: `VACUUM` on one database rather than a two-file consistency problem." That sharing is only
#: observable as *both of these appearing in the same file*, which is what `TC-STORE-01`
#: asserts — a two-file implementation satisfies every other clause in the case.
TIER_C_TABLE = "submission"
TIER_R_TABLE = "work_unit"

#: `FR-STORE-14`'s foreign-key fixture. Declared as literals, never assembled — `SEC-15`.
_PARENT_DDL = "CREATE TABLE fk_parent (id INTEGER PRIMARY KEY)"
_CHILD_DDL = (
    "CREATE TABLE fk_child ("
    "  id INTEGER PRIMARY KEY,"
    "  parent_id INTEGER NOT NULL REFERENCES fk_parent(id)"
    ")"
)
_VIOLATING_INSERT = "INSERT INTO fk_child (id, parent_id) VALUES (1, 999)"
_FOREIGN_KEYS_PRAGMA = "PRAGMA foreign_keys"

_META_DDL = "CREATE TABLE package_meta (k TEXT PRIMARY KEY, v TEXT)"
_META_SEED = "INSERT INTO package_meta (k, v) VALUES ('name', 'imported')"
_META_READ = "SELECT k, v FROM package_meta"
_META_WRITE = "INSERT INTO package_meta (k, v) VALUES ('x', 'y')"
_META_DELETE = "DELETE FROM package_meta"


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: Exception types that mean *the test harness broke*, never *the store refused*. Catching a
#: bare `Exception` and calling it a refusal is how a read-only assertion passes against a store
#: that raised `AttributeError` because its read-only path never built a write queue.
HARNESS_FAILURE_TYPES = (
    AssertionError, AttributeError, TypeError, NameError, ImportError, SyntaxError,
)

#: What a genuine read-only refusal says — matched against the exception's **type name as well
#: as its message**. SQLite's own wording is "attempt to write a readonly database"; a
#: store-level guard is more likely to be a `ReadOnlyTierError` whose message never uses the
#: word. Either is a refusal; an `AttributeError` on a `None` is not.
READ_ONLY_MARKERS = (
    "readonly", "read-only", "read only", "not writable", "immutable", "notwritable",
)


def _close(store) -> None:
    """Close a store, requiring the method to exist.

    Deliberately **not** a `getattr(..., None)` no-op. Design §3.3 declares no lifecycle method
    on `Store` — it has `package`, `cohort`, `durable`, `blobs` and `purge_cohort` and nothing
    that releases a file handle — so an implementation may well ship without one. But
    `TC-STORE-02` is *about* the second connection and `TC-STORE-16` needs the file closed
    before it reopens read-only, and a silent no-op turns both into tests of one connection that
    still report green. `require_attr` states the gap as a failure instead, which is what puts it
    in front of whoever implements #10.
    """
    require_attr(store, "close", issue=ISSUE)()


def test_tc_store_01_four_tiers_open_as_wal_files_in_the_layout_the_design_fixes(tmp_data_dir):
    """`TC-STORE-01` — *"Four tier handles open; P is per package, C and R share one file, D is
    one shared file; every connection reports `journal_mode` of `wal`."*

    Oracle: **exact value via `PRAGMA`**, plus exact file paths.

    Four separate claims, and the case fails if any one is wrong:

    1. Each tier's file appears at the path design §3.3 fixes. A store that puts every package
       in one shared file still opens four handles and still reports `wal`.
    2. Two packages get two files; two calls for one package get one file. "Per package" is a
       *cardinality* claim, and one file for all packages passes every pragma check there is.
    3. Tier C and Tier R tables live in the **same** file. This is the clause with no other
       witness in the suite: nothing else can tell a shared C+R file from two files, and the
       whole purge design rests on it.
    4. `journal_mode` is exactly `wal` on every one of them, read from the file itself.
    """
    store = open_store(tmp_data_dir, issue=ISSUE)

    package_a = store.package("PKG-A")
    package_b = store.package("PKG-B")
    cohort = store.cohort("COH-1")
    durable = store.durable()

    assert package_a is not None and package_b is not None
    assert cohort is not None and durable is not None

    path_a = tmp_data_dir / PACKAGE_FILE.format(package_id="PKG-A")
    path_b = tmp_data_dir / PACKAGE_FILE.format(package_id="PKG-B")
    cohort_path = tmp_data_dir / COHORT_FILE.format(cohort_id="COH-1")
    durable_path = tmp_data_dir / DURABLE_FILE

    tiers = (
        ("Tier P (PKG-A)", path_a),
        ("Tier P (PKG-B)", path_b),
        ("Tiers C+R (COH-1)", cohort_path),
        ("Tier D", durable_path),
    )

    for label, path in tiers:
        assert path.exists(), (
            f"TC-STORE-01: {label} is not at {path.relative_to(tmp_data_dir)}. Design §3.3 "
            "fixes the tier layout, and every module's retention posture is stated in terms of "
            "which file holds what."
        )

    # (2) per-package cardinality, in both directions.
    assert path_a != path_b, (
        "TC-STORE-01: two packages resolved to one file. Tier P is per package and permanent "
        "(design §3.3); one shared package file makes an imported package's blast radius the "
        "whole catalogue."
    )
    assert store.package("PKG-A") is not None
    package_files = sorted(p.name for p in (tmp_data_dir / "packages").glob("*.sqlite"))
    assert package_files == ["PKG-A.pkg.sqlite", "PKG-B.pkg.sqlite"], (
        "TC-STORE-01: reopening PKG-A created another file. `package(id)` must resolve to the "
        f"same database, not a new one. Found {package_files}."
    )

    # (3) the shared C+R file — the clause nothing else in the suite witnesses.
    #
    # The two tables are created here rather than assumed to exist. Design §3.3 says M-STORE
    # "does not own any schema meaning — table semantics belong to the module that owns the
    # tier", so whether #10's migrations create `submission` and `work_unit` is genuinely
    # ambiguous and #10's acceptance criteria never say. The claim under test is about **file
    # topology**, not about who runs the DDL: a Tier C table and a Tier R table, written through
    # the one `cohort()` handle, must land in the one file.
    with cohort.transaction() as tx:
        tx.execute(statement(f"CREATE TABLE {TIER_C_TABLE} (id INTEGER PRIMARY KEY)", issue=ISSUE))
        tx.execute(statement(f"CREATE TABLE {TIER_R_TABLE} (id INTEGER PRIMARY KEY)", issue=ISSUE))

    cohort_tables = table_names(cohort_path)
    assert cohort_tables, (
        f"TC-STORE-01: {cohort_path.name} reports no tables at all, so the assertion below "
        "would pass against an empty file. The two CREATE TABLEs above committed through a "
        "transaction and must be visible to an independent reader."
    )
    assert {TIER_C_TABLE, TIER_R_TABLE} <= cohort_tables, (
        f"TC-STORE-01: Tier C ({TIER_C_TABLE}) and Tier R ({TIER_R_TABLE}) are not both in "
        f"{cohort_path.name}. Design §3.3: they share one file deliberately, so that "
        "`purge_cohort` is a VACUUM on one database rather than a two-file consistency "
        f"problem. Found: {sorted(cohort_tables)}"
    )
    # The assertion above is close to tautological on its own — both tables were written through
    # the one `cohort()` handle, so of course they landed together. The load-bearing half is the
    # *file count*: one cohort must produce exactly one database. A store that split R into
    # `cohorts/COH-1.r.sqlite` would pass everything above and make purge the two-file
    # consistency problem design §3.3 chose this layout to avoid.
    cohort_files = sorted(p.name for p in (tmp_data_dir / "cohorts").glob("*.sqlite"))
    assert cohort_files == ["COH-1.sqlite"], (
        f"TC-STORE-01: one cohort produced {cohort_files}. Tiers C and R share a single file; "
        "any second file here is the split the design rejects."
    )

    # (4) WAL, exactly, on every tier file.
    for label, path in tiers:
        mode = journal_mode(path)
        assert mode == "wal", (
            f"TC-STORE-01: {label} reports journal_mode={mode!r}, not 'wal'. FR-STORE-01 "
            "requires WAL on every tier, and NFR-STORE-02's recovery bound and CT-STORE-04's "
            "'readers never block the writer' both depend on it."
        )


def test_tc_store_02_foreign_keys_are_on_for_every_connection_including_after_reconnect(
    tmp_data_dir,
):
    """`TC-STORE-02` — *"`PRAGMA foreign_keys` is 1 on each; an FK-violating insert then
    fails."*

    Oracle: **exact value plus exact failure**, and both halves are load-bearing.

    `foreign_keys` defaults to **off** in SQLite and is per-connection, never persisted in the
    file. So a store that sets it on the first connection and forgets on the next passes any
    single-connection probe. `FR-STORE-14` exists so that "the CHECK and FOREIGN KEY
    constraints the HLD relies on as guarantees are actually enforced", and `CT-STORE-13`
    promises callers "a violating write fails rather than being caught by review". A guarantee
    that holds on connection one and not connection two is not a guarantee.

    Hence the plan's *"including one created after a reconnect"*: the store is closed and
    reopened, and both assertions run again against the fresh connection.

    The two halves are separate because they fail separately. A store can report `1` from a
    cached value while the connection actually issuing the write has it off — the pragma
    assertion alone would pass. And an insert can fail for `NOT NULL` or a type error while
    `foreign_keys` is off — the behavioural assertion alone would pass. So the second half
    asserts the *reason*, not just the failure.
    """
    # The handle objects themselves, kept alive for the whole case. An earlier draft compared
    # `id()` values, which is correct here only because the first handle happens to still be
    # referenced when the second is allocated — a property no reader should have to verify.
    seen_handles: list[object] = []
    for attempt, phase in enumerate(("first open", "after reconnect")):
        store = open_store(tmp_data_dir, issue=ISSUE)
        handle = store.package("PKG-FK")
        seen_handles.append(handle)

        if attempt == 0:
            with handle.transaction() as tx:
                tx.execute(statement(_PARENT_DDL, issue=ISSUE))
                tx.execute(statement(_CHILD_DDL, issue=ISSUE))

        rows = list(handle.query(statement(_FOREIGN_KEYS_PRAGMA, issue=ISSUE)))
        value = rows[0][0]
        assert int(value) == 1, (
            f"TC-STORE-02 ({phase}): PRAGMA foreign_keys is {value!r}, not 1. SQLite defaults "
            "it OFF per connection, so every FK in the DDL is decoration until this is set on "
            "every connection the module hands out (FR-STORE-14, CT-STORE-13)."
        )

        with pytest.raises(sqlite3.IntegrityError) as raised:
            with handle.transaction() as tx:
                tx.execute(statement(_VIOLATING_INSERT, issue=ISSUE))
        assert "foreign key" in str(raised.value).lower(), (
            f"TC-STORE-02 ({phase}): the violating insert failed, but not for the FK. Got "
            f"{raised.value!r}. A NOT NULL or type failure here passes a weaker assertion while "
            "foreign_keys stays off, which is the defect this case exists to catch."
        )

        _close(store)

    # The plan's "including one created after a reconnect" is only tested if a reconnect
    # actually happened. A store that memoizes per data directory and sets `foreign_keys` once
    # at construction — forgetting it on every connection opened later — would hand back the
    # same handle twice, and both loop iterations would probe the one connection that happens to
    # be correct. That is the precise defect this case exists to catch, so it is asserted.
    assert seen_handles[0] is not seen_handles[1], (
        "TC-STORE-02: reopening the store returned the same TierHandle object, so the second "
        "iteration probed the first connection and 'after reconnect' asserted nothing. "
        "FR-STORE-14 is about *every* connection the module hands out."
    )
    # Object identity is a proxy, not the thing itself: a fresh handle wrapping a memoized
    # connection still passes. The behavioural half above — the pragma read and the FK-violating
    # insert, both re-run on the second handle — is what actually probes the connection, and
    # this assertion only guarantees there was a second handle to probe.


def test_tc_store_16_an_imported_tier_p_opens_read_only_and_is_not_touched(tmp_data_dir):
    """`TC-STORE-16` — *"Reads succeed; every write path raises; the file's mtime is unchanged
    after the session."*

    Oracle: **exact exception plus file assertion**.

    `FR-STORE-13` exists for one situation: an imported package is inspected *before it is
    trusted*. So the assertion is not merely that writes fail — it is that the session leaves no
    trace. A store that opens the file read-write, lets a write reach the WAL and then rolls
    back has satisfied "writes raise" and modified the file on disk.

    Both the mtime the plan names **and** a content digest are asserted. mtime alone is weak:
    filesystem timestamp granularity is coarse enough that a write and a check inside one test
    can share a stamp. The digest is what actually says the bytes did not move.

    *Every* write path, not one. `CT-STORE-01`: a `TierHandle` offers `query`, `enqueue_write`
    and `transaction`, and nothing else. A store that guards one write door and not the other is
    the realistic partial implementation, so both are swept.
    """
    seeded = open_store(tmp_data_dir, issue=ISSUE)
    writable = seeded.package("PKG-IMPORT")
    with writable.transaction() as tx:
        tx.execute(statement(_META_DDL, issue=ISSUE))
        tx.execute(statement(_META_SEED, issue=ISSUE))
    _close(seeded)

    path = tmp_data_dir / PACKAGE_FILE.format(package_id="PKG-IMPORT")
    before_mtime = path.stat().st_mtime_ns
    before_digest = _digest(path)

    store = open_store(tmp_data_dir, issue=ISSUE, read_only=True)
    handle = store.package("PKG-IMPORT")

    rows = list(handle.query(statement(_META_READ, issue=ISSUE)))
    assert rows, (
        "TC-STORE-16: a read-only Tier P returned nothing. FR-STORE-13 exists so an imported "
        "package can be *inspected* before it is trusted; a handle that cannot read is not the "
        "feature."
    )

    for door, attempt in (
        ("enqueue_write", lambda: handle.enqueue_write(statement(_META_WRITE, issue=ISSUE))),
        ("transaction", lambda: _write_in_transaction(handle)),
    ):
        with pytest.raises(Exception) as raised:
            attempt()
        assert not isinstance(raised.value, HARNESS_FAILURE_TYPES), (
            f"TC-STORE-16: {door} raised {type(raised.value).__name__}, which means the harness "
            f"broke rather than the store refusing: {raised.value!r}. A read-only path that "
            "never builds a write queue raises AttributeError on a None, writes nothing, and "
            "leaves mtime and digest intact — so a bare `pytest.raises(Exception)` passes it."
        )
        # The exception's *type name* counts as well as its message. SQLite says "attempt to
        # write a readonly database"; a store-level guard would more likely raise
        # `ReadOnlyTierError("writes are not permitted on an imported package")`, whose message
        # says nothing matching. Requiring the wording alone would red that correct store.
        evidence = f"{type(raised.value).__name__} {raised.value}".lower()
        assert any(marker in evidence for marker in READ_ONLY_MARKERS), (
            f"TC-STORE-16: {door} raised {type(raised.value).__name__}({raised.value!r}), and "
            "neither its type nor its message says the tier is read-only. The plan's oracle is "
            f"an *exact* exception; one of {READ_ONLY_MARKERS} must appear so the refusal is "
            "distinguishable from an unrelated failure that happened to leave the file alone."
        )

    _close(store)

    assert _digest(path) == before_digest, (
        "TC-STORE-16: the Tier P file's contents changed during a read-only session. This is "
        "the assertion mtime cannot make on its own — a write that reached the WAL and rolled "
        "back still moved these bytes."
    )
    assert path.stat().st_mtime_ns == before_mtime, (
        "TC-STORE-16: the Tier P file's mtime moved during a read-only session. An imported "
        "package must be inspectable without being altered (FR-STORE-13)."
    )


def _write_in_transaction(handle) -> None:
    with handle.transaction() as tx:
        tx.execute(statement(_META_DELETE, issue=ISSUE))
