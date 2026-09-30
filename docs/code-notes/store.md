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
