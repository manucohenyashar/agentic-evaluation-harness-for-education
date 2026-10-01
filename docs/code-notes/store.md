# `aeh.store`: design notes

These notes were the docstring of `src/aeh/store.py` before it was split into the `aeh/store/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-STORE` — Persistence Substrate (design §3.3).

Owns the physical stores: four SQLite databases by lifetime tier, the schema discipline that
lets Tiers P and D outlive software versions, and — from the stories that follow — the
single-writer commit queue, the content-addressed blob directory, and purge.

It owns **no schema meaning**. Table semantics belong to the module that owns the tier (`M-PKG`
for Tier P, `M-ORCH` for the ledger, `M-STATS` for Tier D's figures). What lives here is files,
connections, transactions, migrations, and the absence of a retrieval API.

Scope of this file today
------------------------
Issues **#10**, **#11** and **#13**: the tier handles, WAL and migrations (`FR-STORE-01`,
`-02`, `-13`, `-14`), the single-writer queue with batch commits and backpressure
(`FR-STORE-03`, `-04`, `-05`), and the safety half — no search surface (`FR-STORE-08`,
enforced structurally by `CT-STORE-01`'s closed member list and the `STATEMENTS` registry),
owner-only permissions and the insecure-location refusal (`FR-STORE-09`), the disk-full halt
(`FR-STORE-10`), purge with its Tier D precondition (`FR-STORE-07`), and Tier D's
student-name guard (`FR-STORE-12`).

No sibling remains a stub: the tier handles, the queue, the blob store, purge, the
permission and disk-full doctrine and the name guard are all implemented — the last
`NotImplementedError`-naming-its-issue stub was `Store.blobs`, which #12 landed. The stub
discipline itself is worth keeping on the record: `FUZZ-07`'s own docstring records that
review proved a no-op `transaction()` vacuous by dropping in a bare `yield` and watching
500/500 examples pass, so the three stories that preceded their implementations raised
`NotImplementedError` naming their issue instead — keeping the shape without creating a
green-by-blindness path.

Decisions this file fixes, that the design underdetermines
----------------------------------------------------------
Recorded here rather than in a commit message, because `TS-08`/`TS-09`/`TS-10` (#14, #15, #16)
and `TS-60` (#17) are written against whatever this module ships, and a signature they have to
guess is a suite that asserts the wrong thing.

| Decision | Choice | Forced by |
|---|---|---|
| Entry point | `open_store(data_dir)`, positional **and** by keyword | §3.3's Interfaces block names no constructor; three merged tests already call it both ways |
| `Statement` | A `str` subclass carrying `.sql` | `SEC-15` requires `query`'s first parameter to be annotated `Statement` and not `str`; merged tests pass module-level SQL literals, which *are* declared statements |
| What reaches `execute()` | `declared.sql`, never the parameter | `tests/support/sql_scan.py` flags a parameter reaching an execute call and explicitly sanctions attribute access on a declared-statement table. One execute site in the module, registered in `KNOWN_EXECUTE_SITES` |
| Migration 001 creates the tier's tables | Yes — the table *names* from §3.3's data model, with a minimal column set | `TC-STATS-C18` asserts Tier D has tables and would be vacuous over an empty database; `FR-STORE-14` needs a real FK to enforce |
| Later columns | `ALTER TABLE ADD COLUMN` in a later numbered migration, contributed by the owning module | §3.3: this module owns migrations, not table semantics |
| `result` table | **Not** created here | It is not in §3.3's data model; `FUZZ-07` reads it and is keyed on #11, which is the story that builds the write path |
| Schema version is per tier | One `schema_version` table per database; the **set** of applied versions is what pending work is measured against | `FR-STORE-02` says "per tier"; Tier P files are handed between schools and version independently of Tier D |
| Read-only Tier P | `package(id, read_only=True)` over a `file:...?mode=ro` URI | `FR-STORE-13`; a read-only handle never migrates, because migrating is a write |
| Too-new is checked before anything else reaches the file | The chain-completeness refusal (`IncompleteMigrationChainError`, #234) comes first — a process whose chain is short cannot judge any file — then `SchemaTooNewError`, both before the first migration and before any row is read | `CT-STORE-11`: "refuses to open, **no partial read**" |
| `SQLITE_BUSY` retry | Internal and **bounded**; exhausting it re-raises SQLite's own error | §3.3 says busy "should not occur" under WAL. No retry loop can promise *never*, and a helper claiming to would be lying about a lock held outside this process |
| `query` refuses a write | The connection is in autocommit, so it would otherwise be a synchronous write channel | `CT-STORE-02` makes writing asynchronous; #11 owns both write paths |
| One file, one mode | A read-only and a writable handle on the same file cannot both be open | `FR-STORE-13` inspects a file whose provenance is in question; two live connections make that inspection meaningless |
| Open-time observability | `Store.opened` — one `TierOpened` per database | `CLAUDE.md` seam 4: a bare success on top of an empty result is the top silent-failure trap |
| Insecure location is a POSIX-mode rule | Resolve the configured dir (`realpath`, which also closes the symlink bypass) and refuse on the first world-writable ancestor (`mode & 0o002`). No-op on Windows, where `os.stat` fabricates `0o777` for every directory and `%TEMP%` is ACL-scoped per user — the precondition "world-writable temporary path" is unconstructible there. The platform and `stat` are injectable so both branches are exercisable from one host | `FR-STORE-09` names world-writable, not merely temporary; pytest's `tmp_path` sits inside `gettempdir()` on every platform, so a blanket temp-dir refusal would red the entire suite |
| Disk-full halts from the last commit, on every write door | `SQLITE_FULL`/`ENOSPC` on any write path — a queue batch, a `transaction()` body or its commit, purge's deletes or its `VACUUM` — rolls the interrupted work back whole (results *and* their paired status transitions), records `DiskFullError`, and halts the process via an injectable hook; the write queue additionally terminally refuses. The stronger reading — post-rollback commit of the batch's `work_unit`-only units — is rejected: with results rolled back it manufactures status-without-result states, breaking the either-both-or-neither invariant `TC-STORE-08` pins. `TC-STORE-13`'s "outstanding ledger status transitions commit" is written against this declared semantics: the ledger stands at its last commit, which is resumable | `FR-STORE-10` halts "rather than continuing with partial writes" and names no door exemption; `CT-STORE-11` says `DiskFullError` is not retryable |
| The Tier D guard parses the INSERT header unanchored | The search for `INSERT [OR …] INTO tbl (cols)` / `REPLACE INTO tbl (cols)` runs anywhere in the statement, tolerates comments and schema-qualified tables, and takes the last identifier as the table. Cost, accepted and stated: a statement whose *string literal* quotes insert-shaped text can be refused when it would have run. A false positive fails loud; a false negative is a name in the tier nothing can purge | `FR-STORE-12` says "any insert"; the CTE form (`WITH x AS (...) INSERT INTO ...`) is ordinary SQL and anchored parsing missed it |
| Tier D write connections refuse schema DDL | `set_authorizer` denies CREATE/ALTER/DROP of tables, indexes, triggers and views, plus `ATTACH`/`DETACH`, on the durable tier's write connections. The header guard reads statements; without this, a `CREATE TABLE` through a guarded `transaction()` body — followed by a no-column-list `INSERT ... SELECT` the guard cannot parse — was a verified end-to-end bypass. Migrations are unaffected: they run on the open connection, not the write connection | Schema belongs to migrations (`NFR-STORE-04`); the guard's own guarantee ("a false negative is a name in the tier nothing can purge") requires the DDL half closed, not documented |
| Destructive operations validate their identifier | `purge_cohort` refuses a `cohort_id` that cannot safely become a filename component — the same principle `TC-STORE-22` fixes for the blob accessors, applied where the blast radius is irreversible. Keyed lookups pass ids as bound parameters and need no rule | Review verified the traversal: `purge_cohort('../other')` and an absolute path both escaped the data directory |
| Purge preconditions are scoped by `cohort_id` | A Tier D gate (`audit_record`, `label`, `criterion_stats`) passes iff the table exists **and** carries a `cohort_id` column **and** holds a row for this cohort. The column name is the contract `M-STATS`/`M-REVIEW` migrations must honor | #10's minimal Tier D columns carry no cohort scope; promotion means cohort-scoped rows were copied in, so absent the column promotion structurally cannot have happened — fail closed (`CT-STORE-10`'s sweep is per-precondition) |
| Purge keeps the file and its `schema_version` | The DELETE sweep skips `schema_version` and the `sqlite_%` internals; wiping `schema_version` would make migration 001 re-run against surviving tables and leave the file permanently unopenable. The file itself remains — `TC-STORE-11`'s oracle scans the emptied file's raw bytes | `FR-STORE-07` deletes Tier C and R *content*; §3.3's data model makes the purge a `VACUUM` on one database |
| Purge reclaims the cohort's blobs by evidence, not a refcount | After the commit, purge scans every other database in the data directory for the cohort's hash-shaped values and unlinks only hashes nothing surviving references (#225; §7.4's dedup-vs-purge tension resolves in favor of the surviving reference). The blob store has no refcount table, and a schema-derived one would have to be maintained by every writer forever; a value scan is self-validating and picks up new hash-bearing columns with no registry edit | `FR-STORE-07` as #225 states it: purge deletes Tier C and R *content*, and student bytes in blobs are content |
| `STATEMENTS` is the registry of runtime statements | Every non-migration statement literal the module executes, keyed by name. Migration DDL is excluded — it is versioned data in `TIER_MIGRATIONS`, and the schema limb of `TC-STORE-15` sweeps real files | `FR-STORE-08`'s "declared queries" is only checkable if the declared set has a home; `TC-STORE-15` limb 2 sweeps this registry, and `tests/support/store_api.py` attributes it to #13 |

Configuration
-------------
§3.3 names `HARNESS_DATA_DIR`, `HARNESS_COMMIT_BATCH`, `HARNESS_COMMIT_INTERVAL_MS` and
`HARNESS_WRITE_QUEUE_DEPTH`. All four are read here as of #11, plus knobs for the
environment-sensitive constants this module introduces on its own account — `CLAUDE.md` seam 3:
the production value is the default, the knob exists so a slower box need not edit code.

These are **not** `M-CONF`'s six `HARNESS_*` keys. That tuple is the run-configuration snapshot
and `TC-CONF-C11` sweeps it; these are this module's own and are read here, once, in
`_int_env`/`data_dir_from_environment`.

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.store`. Each section is named after the file and the function or class it describes.

### connection.py: _run

One site, so `KNOWN_EXECUTE_SITES` in `tests/artifact/test_store_query_surface.py` stays a
list a reviewer can actually read, and so the `SQLITE_BUSY` retry below cannot be forgotten
at some other call.

What is passed is `declared.sql` — an attribute of a declared statement, which is the shape
`tests/support/sql_scan.py` sanctions — never the parameter itself. Passing the parameter
would mean "whatever the caller passed reaches SQLite unchecked", and the scanner is right
that that is a different interface from the one §3.3 declares.

`SQLITE_BUSY` is retried here rather than at any call site (`CT-STORE-11`). Under WAL with one
writer it should not occur at all, and "should not" is why the retry is bounded: a lock held
by something outside this process is not a condition an unbounded retry improves.

So it is **bounded, not never** — exhausting the retries re-raises SQLite's own error rather
than a new one, and the caller sees `OperationalError` exactly as it would have without the
retry. §3.3 says busy "should not occur"; a helper that promised it could not would be
promising something no retry loop can deliver.

`lock_waits` (the `#118` export-seam figure) is counted through the thread-local sink
`_LOCK_WAIT_SINK`, not through this signature: a test that patches `_run` with a
same-shape wrapper (TC-STORE-13's does, verbatim) must keep working, and a new keyword
would break every one of them. A handle-owned window (`SqliteTierHandle.query`,
`WriteQueue._commit`, `WriteQueue.transaction`) installs its counter dict for the
statements it runs; every SQLITE_BUSY retry slept through inside the window increments
it, and the count surfaces in `SqliteTierHandle._metrics` → `store_metrics` →
`PipelineOutcome.lock_waits`. Open-time sites (migration, the pragmas) run outside any
window and are deliberately outside the count: the figure is about a *run's* waits,
not the file's construction.

### disk_full.py: _as_disk_full

Two signatures, because the same condition arrives wearing two faces: SQLite's
`SQLITE_FULL` (`OperationalError: database or disk is full`) when the *database* layer
runs out — which on a dedicated data disk is the disk, not the database, since this
module sets no `max_page_count` — and the OS's `OSError(ENOSPC)` when the filesystem
itself refuses before SQLite is even reached (a `VACUUM` writing a temp copy can land
there, as can the WAL). Anything else is not disk-full and must not be classified as
one: a mis-classified error halts a process that could have kept going, and "halts the
process" is not an outcome to hand to a loose string match. The message check is
SQLite's own wording, not a guess at it.

`include_os_errors=False` is the **transaction body's** setting, and it is not a
technicality: a `transaction()` body runs arbitrary caller code, so a raw
`OSError(ENOSPC)` raised there can be the caller's *own* file export failing on an
unrelated path. Classifying that as the store's disk-full would halt the run for
somebody else's I/O. The body door therefore classifies only the store's own
`sqlite3` errors; the batch, commit and purge doors — whose failures are always this
module's I/O — keep `OSError(ENOSPC)` in scope.

Declared residual faces: out-of-space that surfaces as `SQLITE_CANTOPEN` ("unable to
open database file") or a generic `disk I/O error` is **not** classified, because
neither message is unique to exhaustion — the same codes fire for a wrong path or
permissions, and a mis-classified halt is exactly the loose string match this helper
refuses to be.

The returned error carries the decision-table wording and the original chained as its
cause. The door that saw the failure owns the state to record (the queue's failure
list and broken flag; purge has none) and then runs the halt hook — which is why this
helper only builds the error and never halts on its own.

### errors.py: IncompleteMigrationChainError

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

### security.py: _insecure_location_reason

The rule `FR-STORE-09` states and `CT-STORE-16` makes contract: refuse a data directory
that **resolves inside a world-writable temporary path**. Mechanically:

- **Resolve first.** `os.path.realpath` follows the whole symlink chain, so a data
  directory that is a symlink pointing into `/tmp` is judged by where it *lands* — the
  bypass a naive prefix check on the configured path misses, and the exact case
  `TC-STORE-C16` names.
- **Walk the ancestors.** The first directory from the resolved path up to the root whose
  POSIX mode is world-writable (`mode & 0o002`) is the reason — `/tmp` at `1777` is the
  canonical hit, and any world-writable ancestor is the same disclosure: files created
  beneath it are reachable by every other account on the host. A directory that is only
  group-writable is **not** refused; `TC-STORE-10`'s expected result names world-writable
  and temp, and a check that refused group-write would red the correct case.
- **POSIX only.** On Windows the check returns `None` by design, not by omission: `os.stat`
  fabricates `0o777` for every directory there, so a bit test would refuse *every* data
  directory, and `%TEMP%` is ACL-scoped to the user, so the requirement's precondition —
  a world-writable temporary path — is unconstructible. Known residual limits, stated
  rather than hidden: an UNC share is writable across machines by nature, and a FAT/exFAT
  volume has no ACLs at all; neither is detectable through `os.stat` and neither is
  refused here. `NFR-STORE-05`'s platform-encryption placement is the compensating
  deployment control.

`os_name` and `stat_fn` are injectable so both branches are exercisable from one host —
this repository's suite runs on Windows only, and a refusal path nothing can run is a
refusal path nobody can trust. `TC-STORE-10` drives them directly.

### sqlite_store.py: SqliteStore.purge_cohort

Irreversible, and the only operation in this module that deletes student work.

The precondition is checked **against Tier D, before anything is deleted**:
`audit_record`, `label` and `criterion_stats` must each exist, carry the `cohort_id`
scoping column, and hold at least one row for this cohort. Any unmet gate raises
`PurgePreconditionError` naming every missing promotion, and the cohort file is left
byte-for-byte as it was. Inspecting Tier D opens it: on a store whose Tier D never
existed this creates the empty, migrated file and then refuses — nothing of the
cohort's is touched either way.

What purge deletes is the **content** of Tiers C and R — every row of every table in
the cohort file — inside one transaction with foreign keys deferred to the commit,
followed by a `VACUUM` and a truncate checkpoint. The vacuum is why a sentinel
embedded in a submission is gone from the file's raw bytes afterward: a `DELETE`
alone leaves text recoverable in freed pages, which is the reason the requirement
names `VACUUM` — and the checkpoint is why it is gone from the `-wal` too, where the
freed pages would otherwise sit until the last connection closed. The file itself
remains, empty and migrated — and `schema_version` survives with it, because wiping
it would make the next open re-run migration 001 against the surviving tables and
leave the file permanently unopenable.

Around the caller:

- The cached cohort handle is **closed and evicted first**. Its queued writes are
  flushed (a flush failure aborts the purge before anything is deleted — rows that
  could not commit would otherwise land in the emptied file), Windows file locks are
  released, and no queued write can repopulate the tables after the delete. A handle
  a caller still holds past this point fails with a raw `sqlite3.ProgrammingError` —
  declared here rather than discovered there.
- Blobs **are** reclaimed (#225): the cohort's hash-shaped references are read
  inside the transaction, and after the commit every hash no other database in
  the data directory still holds is unlinked from the content-addressed store —
  a blob shared with a surviving cohort keeps resolving (test plan §7.4's
  dedup-vs-purge tension resolves in favor of the survivor), and a blob
  referenced by nothing loses its student bytes. The count is
  `PurgeReport.blobs_deleted`.
- On a read-only store this raises `ReadOnlyTierError` — a purge is a write by any
  definition that matters.

A purge that fails partway (say, `VACUUM` cannot get its temp copy) has already
committed its deletes; re-running it completes the vacuum — the tables are empty and
the preconditions still hold. One asymmetry #225 makes explicit: if the **blob**
phase fails after the commit, re-running cannot finish it — the rows that named the
cohort's hashes are gone, so the error names the hash it stopped on and the
leftover blob is unreferenced orphan. The scan-before-any-unlink discipline keeps
that window as small as a post-commit phase can be.

### student_names.py: _reject_tier_d_student_name_insert

Runs on the durable tier's two write doors (`enqueue_write` before queueing,
`Tx.execute` before executing) and nowhere else: the requirement is about *inserts* into
*Tier D*, and a guard on the other tiers or on reads would be a rule without a threat
behind it. Parses the column list out of the statement's INSERT header — `INSERT [OR …]
INTO tbl (cols)`, `REPLACE INTO tbl (cols)` — and applies `is_student_name_column` to
each named column.

What the parse tolerates, because each was a silent bypass in an earlier draft: CTE
prefixes (`WITH x AS (...) INSERT INTO ...` — hence the unanchored search, with its
string-literal trade recorded above), comments between the header's tokens and inside
the column list, and schema-qualified tables (`main.label` — the last identifier is the
table). What it deliberately does not: a statement with **no column list** (`INSERT
INTO t DEFAULT VALUES`, `INSERT INTO t SELECT ...`, or a bare `VALUES (...)`) names no
column and passes the header parse — the rest of that defense is structural, not
textual: the schema authorizer (`_refuse_tier_d_schema`) refuses to let a name-bearing
column be *created* through a Tier D write connection, so the tables a no-column-list
insert can reach are exactly those the migrations shipped, which the sweep
(`TC-STORE-12`'s third limb) holds clean at test time. Nor does the mapping see
unsegmented abbreviations (`sname`) — `is_student_name_column`'s own stated limit.

Exactness is the control that makes this a guard rather than a wrapper: only a
name-mapped column raises. Every other failure — a typo'd column, a CHECK violation, a
locked database — passes through exactly as SQLite raised it, so a caller can trust
`StudentNameInTierDError` to mean the one thing it names.

### write_queue.py: WriteQueue

`FR-STORE-03` ("serialize all writes through a single writer thread fed by an in-process
queue; concurrent readers shall not block the writer"), `FR-STORE-04` (batch at 100 rows or
5 seconds, whichever comes first) and `FR-STORE-05` (backpressure above a configured depth)
are one mechanism, so they are one class.

**Why a second connection rather than a shared mutex.** The reader connection stays exactly
where #10 left it and this queue opens its own. Under WAL that is what makes `CT-STORE-04`
("concurrent readers never block the writer") true *at the database level* -- a reader holds
no lock the writer needs. A single connection guarded by a lock would satisfy `TC-STORE-03`,
whose docstring says so plainly ("what this case does not catch: a per-operation shared
mutex"), and would fail `NFR-STORE-01` under real load. The contract is the promise; the
test is only what happens to be checkable.

**What "single writer" means once `transaction()` exists.** Section 3.3 hands the caller a
context manager, so a transaction body necessarily runs on the caller's thread -- it cannot
be marshalled to the writer thread without marshalling arbitrary user code. So the
serialization point is the write *connection*, guarded by `_write_lock`: the drain thread
takes it per batch, `transaction()` takes it for its whole body, and at most one write
transaction is ever open on the tier. One writer, in the sense the requirement is about --
never two writes interleaved, never a partially applied transaction observable -- and the
sense in which the design's own interface makes "one thread executes every statement"
unachievable is recorded here rather than quietly redefined.

**Ordering.** A `deque`, popped from the left, committed in slices. Single-caller FIFO holds
end to end, which is what `TC-STORE-03` asserts and `CT-STORE-04` promises; ordering
*across* callers is explicitly not promised and nothing here manufactures it.
