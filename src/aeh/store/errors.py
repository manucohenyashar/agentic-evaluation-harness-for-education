"""The errors M-STORE raises."""

from __future__ import annotations


# --- errors ----------------------------------------------------------------------------------


class StoreError(Exception):
    """Base for every error this module raises.

    Siblings rather than a hierarchy of causes, for the reason `M-CONF` gives for its own four:
    every `CT-STORE-11` oracle is "exact exception type", and a subclass relationship makes
    `pytest.raises(StoreError)` pass for a defect the case meant to distinguish.
    """


class ConfigurationProblem(StoreError):
    """The data directory or a knob is unusable. Raised before any file is touched."""


class IncompleteMigrationChainError(StoreError):
    """The process opened a tier before every module that contributes its migrations was imported.

    The chains in `TIER_MIGRATIONS` are **concatenated at import time** by the modules that own
    the schema they add — Tier P: `aeh.pkg` and `aeh.det`; Cohort: `aeh.ingest`, `aeh.det`,
`aeh.orch`, `aeh.extract`, `aeh.judge`, `aeh.synth`, `aeh.agg` and `aeh.grade`; Tier D:
    `aeh.det` and `aeh.integ` (#375's `calib_dual_scored_roster` is declared in THIS module,
    for the reason its own block gives) — so the chain an open sees is only as long
    as the list of contributing modules the process has imported so far. A file opened on the
    short chain
    builds at the base schema, and the columns the missing migrations would have added surface
    **later, far from the open**, as `sqlite3.OperationalError: no such column:
    parent_version_id` — #46's probe, disclosed in PR #208 and found suite-wide by #94, whose
    seeds chose between the two worlds. #234's guard (`COMPLETE_SCHEMA_VERSIONS`, checked by
    `_open_tier` before the tier file's parent directory is made and before any connection is
    opened — `open_store`'s layout skeleton is made regardless) turns that distant phantom into
    a refusal **at the open site, naming the cause**. The fix on the
caller's side is one line — `import aeh.agg, aeh.det, aeh.extract, aeh.grade,
    aeh.ingest, aeh.integ, aeh.judge, aeh.orch, aeh.pkg, aeh.synth,
    aeh.review`
    registers every tier's complete chain (`import aeh.pkg` alone is *not* enough: it does not
    import `aeh.det`, and Tier P's chain is short by one migration without it; `aeh.extract`
    pulls `aeh.ingest` and `aeh.orch` in transitively but is itself needed for Cohort's tail —
    11 of its 18 migrations — `aeh.orch` for #61's `orch_run_lifecycle`, `aeh.synth` for
    #97's `synth_narrative_key`, `aeh.judge` for #78's `judge_verdict_columns` and
    #80's `judge_verdict_response_columns` — `aeh.orch` again for #62's
    `orch_report_indexes`, `aeh.agg` for #92's `agg_confidence_columns`, and
    `aeh.grade` for the last, #101's `grade_submission_grade_key`, Cohort 18;
    `aeh.review` owns Durable's tail, #110's `review_label_store_columns`, after
    `aeh.integ`'s #73 `integ_rate_dimensions`).

    Import order has two failure modes, and #269's `_VersionOrderedRegistry` already fixed the
    one it could fix at the root: a tier's chain arriving **out of version order** when an early
    import appends a late migration first. Sorting each tier's tuple at write time makes the
    order a contract instead of an accident of collection. What sorting cannot repair is a
    module that was **never imported** — it contributes no migrations at all, so the chain is
    short no matter how it is ordered, and this guard is the refusal for that world.

    Sibling of `SchemaTooNewError`, not its subclass: the too-new refusal says the *file* is
    ahead of the binary; this one says the *process* is behind its own binary. `CT-STORE-11`'s
    exact-type oracles distinguish them, and a subclass relationship would let one pass for the
    other exactly when a reader is diagnosing which of the two went wrong.
    """


class MigrationError(StoreError):
    """A migration refused to run because the file's data cannot be carried forward unambiguously.

    Raised by a migration's `guard` inside the migration's own transaction, so the refusal rolls
    back with everything else and the file stays at the last complete version — byte-identical
    tables, no interim table, no version stamp (`FR-AGG-16`'s ambiguous-attribution refusal,
    `TC-AGG-22` (b)). A sibling, not a subclass of `SchemaTooNewError`: the file is not ahead of
    the binary, its *contents* are what the step cannot attribute.
    """


class SchemaTooNewError(StoreError):
    """The database was written by a newer binary (`FR-STORE-02`, `CT-STORE-11`).

    Raised **before** any migration runs and before any row is read, so "no partial read" is a
    property of the control flow rather than a promise. A store that degraded to reading what it
    recognized would hand a caller a partial view of a package it does not understand.
    """


class InsecureLocationError(StoreError):
    """The data directory resolves inside a world-writable path (`FR-STORE-09`).

    Raised by `open_store` **before the first directory is created**, so a refused start
    creates nothing. The rule is POSIX: the resolved directory — `realpath`, which closes the
    symlink bypass a naive prefix check misses — must have no world-writable ancestor. See
    `_insecure_location_reason` for why Windows is a documented no-op rather than a weaker
    version of the same check.
    """


class WriteThroughQueryError(StoreError):
    """A write was passed to `query`, which reads (`CT-STORE-02`). See `SqliteTierHandle.query`."""


class PurgePreconditionError(StoreError):
    """`purge_cohort` before promotion to Tier D (`FR-STORE-07`, `CT-STORE-10`).

    Raised by `SqliteStore.purge_cohort` with every unmet gate named, and **nothing is
    deleted** — the check runs before the purge touches the cohort file, and the refusal
    leaves every byte where it was. Not retryable by the caller in the sense that matters:
    the missing promotion is `M-STATS`/`M-REVIEW`'s `promote`, not something a retry of
    `purge_cohort` can produce.
    """


class DiskFullError(StoreError):
    """A write failed for want of disk space; the process halts (`FR-STORE-10`, `CT-STORE-11`).

    Raised from **every** write door — a queue batch, a `transaction()` body or its commit,
    purge's deletes or its `VACUUM` — with the SQLite or OS error chained as its cause,
    after the interrupted work has been rolled back whole: results and their paired ledger
    transitions together, so the either-both-or-neither invariant `CT-STORE-03` promises
    survives the halt. The ledger stands at its last commit, which is resumable.

    Halting is the process-level effect and it goes through one indirection, the module
    function `_halt_process_on_disk_full` (default `os._exit(DISK_FULL_EXIT_CODE)`). A test
    injects the disk-full condition and monkeypatches that one function to capture the
    error instead of ending the interpreter; after the hook returns — which in production it
    never does — the write queue is terminally broken and every later `enqueue_write` or
    `transaction()` raises this error. Not retryable by the caller (`CT-STORE-11`).
    """


class StudentNameInTierDError(StoreError):
    """An insert into Tier D carried a column mapped as a student-name field
    (`FR-STORE-12`, `CT-STORE-09`).

    Raised by the write guard on the durable tier's two write doors — `enqueue_write` before
    the row is queued, `Tx.execute` before the statement runs — with the offending column
    name(s) and the target table in the message, because an operator who cannot see which
    column was rejected cannot fix the caller. The mapping the guard applies is
    `is_student_name_column`; the pseudonymous key `student_ref` is the sanctioned shape and
    is never rejected.

    Deliberately **not** raised for anything else: a typo'd column, a locked database, a
    CHECK violation — every other error passes through exactly as SQLite raised it. A guard
    that wrapped every Tier D error would report every schema mistake as a privacy incident
    while catching no actual name, and would be indistinguishable from no guard at all in
    the one case that matters.
    """


class ReadOnlyTierError(StoreError):
    """A write was attempted on a handle opened read-only (`FR-STORE-13`).

    **The class name carries the refusal.** `TC-STORE-16` matches its evidence against the
    exception's type name *as well as* its message, because a store-level guard is more likely to
    say "writes are not permitted on an imported package" than to use the word "readonly" — and
    requiring the wording alone would red a correct store. `ReadOnlyTierError` satisfies the type
    half whatever the message says, which is why the name is not `ImportedPackageWriteError`.

    Raised **before** anything opens a write connection. That ordering is the requirement, not
    tidiness: `FR-STORE-13` exists so an imported package can be inspected *before* it is
    trusted, and a refusal that had already created a `-wal` file beside the database would move
    the mtime and the digest of the very file whose provenance is in question.
    """


class WriteQueueClosed(StoreError):
    """The store closed while a write was queued or blocked on backpressure."""


class CrossTierTransactionError(StoreError):
    """A `transaction()` body attempted to open a second tier's transaction on the same
    thread (`CT-STORE-03`).

    CT-STORE-03 provides atomicity **within one tier handle** and says so: "Cross-tier
    atomicity is **not** provided." The dangerous outcome is not the missing guarantee — it
    is the caller who nests a second tier's `transaction()` inside a first's and believes
    both sides committed together, because without this refusal the nested transaction
    commits independently and the outer one commits on its own schedule. The refusal makes
    the attempt loud instead of silently split. Not retryable: the fix is in the caller's
    shape, not in the timing.
    """


class InvalidContentHashError(StoreError):
    """A `content_hash` that `put` could not have returned (`FR-STORE-06`, `SEC-09`).

    Raised **before the filesystem is touched**, which is the requirement rather than the
    implementation detail it looks like. Test plan `TC-STORE-22` fixes the rule: *"`get()` and
    `path()` reject any argument that is not 64 lowercase hex characters, before touching the
    filesystem"*. `SEC-09` is why -- it attacks `path()` with `../`, an absolute path, a wrong
    length and mixed case, and a check performed after building the path has already asked the
    operating system to resolve whatever the attacker wrote.

    Design §3.3 names no error for this. The name is this module's and is reported as a gap.
    """


# --- the declared-statement registry (FR-STORE-08) ---------------------------------------------
#
# `STATEMENTS` is where the module's runtime statements live as a set, and it is what makes
# "the store interface offers keyed lookup and declared queries only" checkable rather than
# merely true: `TC-STORE-15`'s second limb sweeps every entry for the SQL shapes that search
# (`LIKE`, `GLOB`, `MATCH`, FTS and vector modules, `REGEXP`), and `CT-STORE-08` is a safety
# property — a search capability added through a new statement is a contract breach this
# registry makes visible in one place.
#
# **Every statement the module can issue is registered here**, migration DDL included (see
# the entry block below for why). A new statement added without registering it is a statement
# the no-search sweep cannot see, which is the exact hole the registry exists to close.
#
# Every entry today is free of the search shapes; the registry's own first entry rule is that
# it stays that way.

class StatementConflictError(ValueError):
    """A statement name registered a second time with different SQL (FR-STORE-16, CT-STORE-19).

    Raised at import by the module whose registration conflicts, naming both modules. The
    registry is left exactly as it was: a name has one SQL text whatever the import order."""
