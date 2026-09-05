"""`M-STORE` — Persistence Substrate (design §3.3).

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

One sibling remains declared and **raises `NotImplementedError` naming its issue**, rather
than being absent or — much worse — being written as a no-op:

| Surface | Issue | Requirements |
|---|---|---|
| `Store.blobs` | #12 | `FR-STORE-06`, `-11` |

A no-op `transaction()` would have been the worst of the three stubs: `FUZZ-07`'s own
docstring records that review proved that case vacuous by dropping in a bare `yield` and
watching 500/500 examples pass. Raising kept the shape without creating a
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
| Too-new is checked before anything else | `SchemaTooNewError` raised before the first migration and before any row is read | `CT-STORE-11`: "refuses to open, **no partial read**" |
| `SQLITE_BUSY` retry | Internal and **bounded**; exhausting it re-raises SQLite's own error | §3.3 says busy "should not occur" under WAL. No retry loop can promise *never*, and a helper claiming to would be lying about a lock held outside this process |
| `query` refuses a write | The connection is in autocommit, so it would otherwise be a synchronous write channel | `CT-STORE-02` makes writing asynchronous; #11 owns both write paths |
| One file, one mode | A read-only and a writable handle on the same file cannot both be open | `FR-STORE-13` inspects a file whose provenance is in question; two live connections make that inspection meaningless |
| Open-time observability | `Store.opened` — one `TierOpened` per database | `CLAUDE.md` seam 4: a bare success on top of an empty result is the top silent-failure trap |
| Insecure location is a POSIX-mode rule | Resolve the configured dir (`realpath`, which also closes the symlink bypass) and refuse on the first world-writable ancestor (`mode & 0o002`). No-op on Windows, where `os.stat` fabricates `0o777` for every directory and `%TEMP%` is ACL-scoped per user — the precondition "world-writable temporary path" is unconstructible there. The platform and `stat` are injectable so both branches are exercisable from one host | `FR-STORE-09` names world-writable, not merely temporary; pytest's `tmp_path` sits inside `gettempdir()` on every platform, so a blanket temp-dir refusal would red the entire suite |
| Disk-full halts from the last commit, on every write door | `SQLITE_FULL`/`ENOSPC` on any write path — a queue batch, a `transaction()` body or its commit, purge's deletes or its `VACUUM` — rolls the interrupted work back whole (results *and* their paired status transitions), records `DiskFullError`, and halts the process via an injectable hook; the write queue additionally terminally refuses. The stronger reading — post-rollback commit of the batch's `work_unit`-only units — is rejected: with results rolled back it manufactures status-without-result states, breaking the either-both-or-neither invariant `TC-STORE-08` pins. `TC-STORE-13`'s "outstanding ledger status transitions commit" is written against this declared semantics: the ledger stands at its last commit, which is resumable | `FR-STORE-10` halts "rather than continuing with partial writes" and names no door exemption; `CT-STORE-11` says `DiskFullError` is not retryable |
| The Tier D guard parses the INSERT header unanchored | The search for `INSERT [OR …] INTO tbl (cols)` / `REPLACE INTO tbl (cols)` runs anywhere in the statement, tolerates comments and schema-qualified tables, and takes the last identifier as the table. Cost, accepted and stated: a statement whose *string literal* quotes insert-shaped text can be refused when it would have run. A false positive fails loud; a false negative is a name in the tier nothing can purge | `FR-STORE-12` says "any insert"; the CTE form (`WITH x AS (...) INSERT INTO ...`) is ordinary SQL and anchored parsing missed it |
| Purge preconditions are scoped by `cohort_id` | A Tier D gate (`audit_record`, `label`, `criterion_stats`) passes iff the table exists **and** carries a `cohort_id` column **and** holds a row for this cohort. The column name is the contract `M-STATS`/`M-REVIEW` migrations must honor | #10's minimal Tier D columns carry no cohort scope; promotion means cohort-scoped rows were copied in, so absent the column promotion structurally cannot have happened — fail closed (`CT-STORE-10`'s sweep is per-precondition) |
| Purge keeps the file and its `schema_version` | The DELETE sweep skips `schema_version` and the `sqlite_%` internals; wiping `schema_version` would make migration 001 re-run against surviving tables and leave the file permanently unopenable. The file itself remains — `TC-STORE-11`'s oracle scans the emptied file's raw bytes | `FR-STORE-07` deletes Tier C and R *content*; §3.3's data model makes the purge a `VACUUM` on one database |
| Purge does not touch blobs | Blob reclamation at purge time is an **accepted risk** with the rule undeclared (test plan §7.4: "blob shared across cohorts at purge time"), and the blob store is #12's. `PurgeReport.blobs_deleted` is an honest zero | Making the design decision this PR would be deciding what §7.4 reserves for the design |
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
"""

from __future__ import annotations

import errno
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterator, Mapping, Protocol, Sequence

__all__ = [
    "BlobStore",
    "DiskFullError",
    "InsecureLocationError",
    "Migration",
    "PurgePreconditionError",
    "PurgeReport",
    "Row",
    "STATEMENTS",
    "SchemaTooNewError",
    "Statement",
    "Store",
    "StoreError",
    "StudentNameInTierDError",
    "TIER_D_IDENTITY_COLUMN",
    "TIER_MIGRATIONS",
    "Tier",
    "TierHandle",
    "TierOpened",
    "ReadOnlyTierError",
    "StoreLimits",
    "Tx",
    "WriteQueue",
    "WriteQueueClosed",
    "WriteThroughQueryError",
    "WriteUnit",
    "current_schema_version",
    "data_dir_from_environment",
    "is_student_name_column",
    "open_store",
    "store_metrics",
]


# --- configuration ---------------------------------------------------------------------------

#: §3.3: *"no configuration beyond a data directory path"* (`NFR-STORE-03`).
DATA_DIR_ENV = "HARNESS_DATA_DIR"

#: How long SQLite waits for a lock before raising `SQLITE_BUSY`, and how many times this module
#: retries after that. Both are environment-sensitive: WAL plus a single writer should make busy
#: impossible (§3.3), but a slow or networked filesystem makes "should" into "usually", and a
#: constant calibrated for a developer SSD becomes a phantom failure everywhere else.
BUSY_TIMEOUT_MS_ENV = "HARNESS_SQLITE_BUSY_TIMEOUT_MS"
BUSY_RETRIES_ENV = "HARNESS_SQLITE_BUSY_RETRIES"

DEFAULT_BUSY_TIMEOUT_MS = 5_000
DEFAULT_BUSY_RETRIES = 4

#: §3.3 Configuration, with §3.3's own values as the defaults. `FR-STORE-04` calls 100/5000 an
#: Assumption and `FR-STORE-05` calls 1,000 one, which is exactly what makes them knobs rather
#: than literals: the mechanism is fixed, the numbers are calibrated per environment
#: (`CLAUDE.md` seam 3, "production value is the default").
COMMIT_BATCH_ENV = "HARNESS_COMMIT_BATCH"
COMMIT_INTERVAL_MS_ENV = "HARNESS_COMMIT_INTERVAL_MS"
WRITE_QUEUE_DEPTH_ENV = "HARNESS_WRITE_QUEUE_DEPTH"

DEFAULT_COMMIT_BATCH = 100
DEFAULT_COMMIT_INTERVAL_MS = 5_000
DEFAULT_WRITE_QUEUE_DEPTH = 1_000

#: The free-disk alert's other input (§3.3 **Alerts**: "free disk below the projected remaining-run
#: requirement"). `M-ORCH` knows what a run will still write; this module cannot, so the figure is
#: supplied rather than guessed. Zero — the default — means "no projection stated", and an alert
#: with no projection behind it must stay quiet rather than invent a threshold.
PROJECTED_RUN_BYTES_ENV = "HARNESS_PROJECTED_RUN_BYTES"
DEFAULT_PROJECTED_RUN_BYTES = 0

#: How long queue depth must stay at or above the backpressure threshold before the *alert*
#: fires. §3.3 says "queue depth **sustained** above the backpressure threshold", and the word is
#: load-bearing: backpressure at the boundary is normal operation and `CT-STORE-06` tells
#: `M-ORCH` to treat it as a throttle signal, not a fault. An alert that fired on the same edge
#: would page an operator for the system working as designed.
QUEUE_DEPTH_SUSTAIN_MS_ENV = "HARNESS_QUEUE_DEPTH_SUSTAIN_MS"
DEFAULT_QUEUE_DEPTH_SUSTAIN_MS = 5_000

#: How long the writer sleeps between checks when it has nothing due. Bounds how late a
#: time-triggered commit can be, so it is environment-sensitive in the same way the interval is.
WRITER_POLL_MS_ENV = "HARNESS_WRITER_POLL_MS"
DEFAULT_WRITER_POLL_MS = 5

#: The two alerts §3.3 names under **Alerts**, spelled once. `CT-STORE-17` makes their semantics
#: contract, so the names are part of the interface rather than log text.
ALERT_FREE_DISK = "free_disk_below_projection"
ALERT_QUEUE_DEPTH = "queue_depth_sustained"
DECLARED_ALERTS: tuple[str, ...] = (ALERT_FREE_DISK, ALERT_QUEUE_DEPTH)

#: Owner-only, on **each directory this module itself creates** — not on their parents, and not
#: at all on Windows, where `mkdir`'s mode argument and `chmod`'s mode bits are ignored for
#: anything but the read-only attribute. `FR-STORE-09`'s other half — refusing a world-writable
#: location with `InsecureLocationError` — is `_refuse_insecure_location`, called by
#: `open_store` before the first directory is created.
#:
#: An explicit `chmod` after `mkdir` is the part that actually holds on POSIX: `mkdir`'s mode
#: argument is subject to the process umask, so `mode=0o700` can silently create `0o750`. A
#: permission that depends on an umask nobody audited is not `CT-STORE-16`'s owner-only, it is
#: owner-only on a good day.
OWNER_ONLY_DIR = 0o700

#: Owner-only for the **files**: the database files this module creates and the `-wal`/`-shm`
#: siblings SQLite keeps beside them. The WAL holds the same student rows the database does, so
#: a world-readable `-wal` is the same disclosure with a different extension — `0o600` on the
#: database alone would lock the front door and leave the side one unlatched.
OWNER_ONLY_FILE = 0o600

#: The exit code `DiskFullError` halts with (`FR-STORE-10`). Not an environment knob — an
#: operator script matching on an exit code is a deployment concern, and no environment-sensitive
#: calibration is involved. 70 is sysexits' `EX_SOFTWARE`, chosen so a disk-full halt is
#: distinguishable in a shell transcript from a generic crash.
DISK_FULL_EXIT_CODE = 70


def _int_env(name: str, default: int, environ: Mapping[str, str] | None = None) -> int:
    source = os.environ if environ is None else environ
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationProblem(f"{name}={raw!r} is not an integer") from exc
    if value < 0:
        raise ConfigurationProblem(f"{name}={value} must not be negative")
    return value


def data_dir_from_environment(environ: Mapping[str, str] | None = None) -> Path:
    """`HARNESS_DATA_DIR`, or a refusal that names it.

    No default path. A store that silently picked one would put student work somewhere the
    operator did not choose, and Tier C is the largest PII surface in the system (§3.3 security).
    """
    source = os.environ if environ is None else environ
    raw = source.get(DATA_DIR_ENV)
    if raw is None or not raw.strip():
        raise ConfigurationProblem(
            f"{DATA_DIR_ENV} is unset. NFR-STORE-03 requires no configuration beyond a data "
            f"directory path — but it does require that one."
        )
    return Path(raw).expanduser()


# --- errors ----------------------------------------------------------------------------------


class StoreError(Exception):
    """Base for every error this module raises.

    Siblings rather than a hierarchy of causes, for the reason `M-CONF` gives for its own four:
    every `CT-STORE-11` oracle is "exact exception type", and a subclass relationship makes
    `pytest.raises(StoreError)` pass for a defect the case meant to distinguish.
    """


class ConfigurationProblem(StoreError):
    """The data directory or a knob is unusable. Raised before any file is touched."""


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


def _halt_process_on_disk_full(error: BaseException) -> None:
    """The halt `FR-STORE-10` demands: end the process, now, from wherever the writer is.

    `os._exit` rather than `sys.exit`: it does not unwind, does not run `atexit` handlers and
    does not wait for other threads — which is the point. A run that keeps closing handles
    and flushing queues on its way down is a run *continuing with partial writes*, and the
    requirement names that as the thing not to do. SQLite is crash-safe by design; the
    process is not obliged to be graceful about dying. One line reaches stderr first,
    because a halt with no trace is a halt the operator cannot diagnose from the transcript.

    Module-level so a test can monkeypatch exactly one name and capture the error instead of
    ending the interpreter. Never returns in production; if an injected replacement does
    return, the queue's terminal-broken state takes over and every later write raises
    `DiskFullError`.
    """
    print(f"aeh.store: halting on disk full: {error}", file=sys.stderr)
    os._exit(DISK_FULL_EXIT_CODE)  # pragma: no cover - ends the interpreter by design


def _halt_if_disk_full(error: BaseException) -> None:
    """Purge's door of `FR-STORE-10`'s sequence — classify, halt, raise the classified error.

    Purge has no queue state to record, so its door is the classification plus the halt
    hook, and the hook's (test-only) return is answered by raising the `DiskFullError`.
    Returns for anything that is not out-of-space, so the caller re-raises the original
    unchanged. Content a purge deleted before a disk-full failure stays deleted; re-running
    the purge completes its `VACUUM` — the precondition gates still hold and the tables are
    already empty.
    """
    failure = _as_disk_full(error)
    if failure is not None:
        _halt_process_on_disk_full(failure)  # never returns in production
        raise failure


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


# --- the FR-STORE-12 name vocabulary -----------------------------------------------------------
#
# `FR-STORE-12` says Tier D "shall reject any insert containing a column mapped as a
# student-name field", and design §3.3 puts the identity mapping in Tier C alone. The
# requirement names the *concept*, not the spellings, so the guard needs a mapping — and a
# mapping is only as good as its worst omission, since a name-bearing column that no pattern
# matches is precisely the leak `CT-STORE-09` promises callers cannot happen.
#
# **Not a `*_name` rule.** The obvious version — flag any column whose name contains `name` —
# was measured against this module and flagged `criterion_name`, `stat_name`, `scope_name`,
# `run_name`, `metric_name`, `display_name` and nine more. Tier D holds `criterion_stats`,
# `mcq_item_stats` and `run_metrics` (design §3.3), so those are not hypothetical columns: that
# rule reds the build against a *correct* store, and a rule that does that is one the first
# `M-STORE` commit switches off. A switched-off rule catches nothing at all, which is strictly
# worse than the leak it was guarding.
#
# So the rule is **person + name**, not name alone: a column is a student-name column when it
# names a *person* and names their *name*. Two token sets, and the intersection is the finding.
#
# This rule is runtime behaviour as of #13 — the write guard executes it on every Tier D
# insert — so it lives here, and `tests/support/store_vocabulary.py` re-exports it rather than
# carrying a second copy that could drift from the one the store actually enforces.

#: Who the column is about. Absent these, `*_name` is a criterion, a run or a metric.
PERSON_TOKENS: frozenset[str] = frozenset({"student", "pupil", "learner", "candidate", "child"})

#: What about them, in two strengths — and the split is the whole rule.
#:
#: **Strong** tokens mean a name wherever they appear next to a person token. **Weak** ones do
#: not: `first`, `last`, `family`, `display` and the rest are ordinary English that Tier D has
#: every reason to use. Measured against a rule that treated them as strong,
#: `student_first_seen`, `student_last_seen_at`, `student_family_income`,
#: `student_display_order`, `learner_given_consent`, `student_preferred_language` and
#: `pupil_last_updated` were all flagged — longitudinal per-student columns, which is precisely
#: what a permanent pseudonymous tier is *for*. Redding the build against those is the same
#: failure the `*_name` rule had, wearing different clothes.
#:
#: So a weak token counts only when it is **terminal** (`student_first` is as identifying as
#: `student_first_name`) or **immediately followed by a strong token** (`student_first_name`,
#: `student_display_name`).
STRONG_NAME_TOKENS: frozenset[str] = frozenset(
    {
        "name", "names", "fullname", "firstname", "lastname", "surname", "forename",
        "givenname", "familyname", "initials",
    }
)

WEAK_NAME_TOKENS: frozenset[str] = frozenset(
    {"first", "last", "given", "family", "middle", "preferred", "display"}
)

#: Kept as the union for readers and for callers that want the whole vocabulary.
NAME_TOKENS: frozenset[str] = STRONG_NAME_TOKENS | WEAK_NAME_TOKENS

#: The pseudonymous shape `FR-STORE-12` *requires*. A person token with one of these is the
#: sanctioned Tier D column, not a violation — `student_ref` is the whole point of the clause,
#: and a rule that flagged it would flag the correct implementation.
PSEUDONYM_TOKENS: frozenset[str] = frozenset(
    {"ref", "id", "key", "uuid", "hash", "token", "code", "pseudonym", "anon"}
)

#: Spellings that identify a person with no person token attached, so the person+name rule
#: cannot see them. A bare `name` column in a Tier D table is a finding on its own.
BARE_NAME_COLUMNS: frozenset[str] = frozenset(
    {
        "name", "names", "full_name", "fullname", "first_name", "firstname", "last_name",
        "lastname", "surname", "forename", "given_name", "givenname", "family_name",
        "familyname", "middle_name", "preferred_name", "legal_name", "maiden_name",
    }
)

#: The pseudonymous key Tier D is allowed to carry instead (`FR-STORE-12`).
TIER_D_IDENTITY_COLUMN = "student_ref"


def is_student_name_column(column: str) -> bool:
    """Does this column name a student's name?

    `person token AND name token`, with a pseudonym token vetoing the match. See the block
    comment above for why this is not a `*_name` rule.

    Known limit, stated rather than hidden: an unsegmented abbreviation like `sname` or `fname`
    matches nothing here. Catching those needs guessing at abbreviations, and every guess is a
    false positive against some legitimate column. `TC-STORE-12`'s third limb is a sweep over a
    real schema, so the residual risk is a column somebody deliberately obfuscated — which is a
    different threat from the one `FR-STORE-12` describes.
    """
    lowered = column.lower().strip()
    words = re.split(r"[_\s-]+", lowered)
    unique = set(words)

    if lowered in BARE_NAME_COLUMNS:
        return True

    if unique & PERSON_TOKENS:
        # `student_ref`, `pupil_id`, `learner_uuid` — the shape the clause requires. The
        # pseudonym veto protects them, but a *strong name token* outranks it: a hash of a
        # student's name (`student_name_hash`) is a dictionary attack away from the name on
        # the small populations Tier D serves, so person + strong name is refused whatever
        # else the column carries. The veto still governs the weak-token path, which is
        # where the longitudinal columns it exists for live.
        strong = any(word in STRONG_NAME_TOKENS for word in words)
        if not strong and unique & PSEUDONYM_TOKENS:
            return False
        for position, word in enumerate(words):
            if word in STRONG_NAME_TOKENS:
                return True
            if word in WEAK_NAME_TOKENS:
                terminal = position == len(words) - 1
                before_strong = (
                    position + 1 < len(words) and words[position + 1] in STRONG_NAME_TOKENS
                )
                if terminal or before_strong:
                    return True

    # `studentname`, `pupilForename` — a person and a name glued into one token.
    return bool(
        re.search(r"(student|pupil|learner|candidate|child)\w*(name|forename|surname)", lowered)
    )


# --- location and permission hardening (FR-STORE-09, CT-STORE-16) -----------------------------


def _harden_files(path: Path) -> None:
    """`OWNER_ONLY_FILE` on a database file and its `-wal`/`-shm` siblings.

    Called on the writable open path once the file certainly exists (`_open_tier`) and after
    purge's `VACUUM` (which rewrites the file and re-creates the siblings). POSIX-honoured;
    on Windows `os.chmod` maps everything but the read-only attribute, so this is a no-op
    there by the platform's own semantics — stated plainly rather than papered over: on
    Windows the owner-only guarantee comes from the directory ACLs the operator's profile
    creates, not from these bits.
    """
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            os.chmod(candidate, OWNER_ONLY_FILE)


def _harden_dir(path: Path) -> None:
    """`OWNER_ONLY_DIR` on a directory this module just created or manages.

    Applied after `mkdir` because `mkdir`'s mode argument is filtered through the process
    umask — see `OWNER_ONLY_DIR`. Windows: no-op, as `_harden_files` documents.
    """
    os.chmod(path, OWNER_ONLY_DIR)


def _insecure_location_reason(
    path: Path, *, os_name: str | None = None, stat_fn: Callable[[Path], os.stat_result] | None = None
) -> str | None:
    """Why `path` is an insecure location for student data, or `None` if it is not.

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
    """
    platform = os.name if os_name is None else os_name
    stat = os.stat if stat_fn is None else stat_fn
    if platform != "posix":
        return None
    resolved = Path(os.path.realpath(path))
    for candidate in (resolved, *resolved.parents):
        try:
            mode = stat(candidate).st_mode
        except OSError:
            # An ancestor that cannot be stat'ed is not evidence of a world-writable one —
            # and the data directory itself may legitimately not exist yet (`open_store`
            # creates it after this check, which is what keeps the refusal create-nothing).
            continue
        if mode & 0o002:
            return f"{candidate} is world-writable (mode {mode & 0o777:03o})"
    return None


def _refuse_insecure_location(data_dir: Path) -> None:
    """Raise `InsecureLocationError` for a world-writable location, before anything is created."""
    reason = _insecure_location_reason(data_dir)
    if reason is not None:
        raise InsecureLocationError(
            f"{data_dir} is not a safe data directory: {reason}. FR-STORE-09 refuses to put "
            "student work where every other account on the host can reach it — Tier C is the "
            "largest PII surface in the system, and a world-writable location is the one "
            "place the permission control cannot follow it. Nothing was created. Choose a "
            "directory outside the world-writable tree (e.g. under the operator's home)."
        )


# --- the Tier D student-name guard (FR-STORE-12, CT-STORE-09) ----------------------------------


#: The header of an INSERT that names columns: `INSERT [OR …] INTO <tbl> (cols)` and
#: `REPLACE INTO <tbl> (cols)`, where `<tbl>` may be schema-qualified (`main.label`) and the
#: whole header may sit behind a CTE (`WITH x AS (...) INSERT INTO ...`) or comments.
#: Written as one literal, in the declared-statement pattern: the *text* contains SQL
#: keywords, but it is a regular expression, nothing is assembled, and the scanner that
#: flags assembled SQL reads it as one constant — the same discipline every statement in
#: this module follows. In it, the gap between tokens (`(?:\s|--[^\n]*|/\*.*?\*/)*`) is
#: whitespace or a comment — `INSERT INTO /* provenance */ t (cols)` is ordinary SQL and a
#: guard that missed the comment would miss the name — and one identifier is any of its four
#: SQL spellings (double-quoted, backquoted, bracketed, bare).
#:
#: **Unanchored, deliberately.** Anchoring on `INSERT` made `WITH x AS (...) INSERT INTO t
#: (student_name) ...` invisible to the guard — a name lands in the permanent tier with no
#: error, which is the failure a security control may not have. Searching for the header
#: instead buys the CTE case at a stated cost: a statement whose *string literal* quotes
#: insert-shaped text can be refused when it would have run. That trade is chosen on purpose
#: — a false positive fails loud (a write the caller can see and rephrase), a false negative
#: is silent contamination of the one tier nothing can purge — and every caller here is
#: in-process trusted code whose statements are declared literals reviewed in PRs.
_INSERT_COLUMN_LIST = re.compile(
    r"\b(?:INSERT(?:\s|--[^\n]*|/\*.*?\*/)*(?:OR(?:\s|--[^\n]*|/\*.*?\*/)*\w+"
    r"(?:\s|--[^\n]*|/\*.*?\*/)*)?INTO|REPLACE(?:\s|--[^\n]*|/\*.*?\*/)*INTO)"
    r"(?:\s|--[^\n]*|/\*.*?\*/)*"
    r"((?:\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)"
    r"(?:(?:\s|--[^\n]*|/\*.*?\*/)*\.(?:\s|--[^\n]*|/\*.*?\*/)*"
    r"(?:\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*))*)"
    r"(?:\s|--[^\n]*|/\*.*?\*/)*"
    r"\(([^)]*)\)",  # the column list — a missing one means no match at all
    re.IGNORECASE | re.DOTALL,
)


def _reject_tier_d_student_name_insert(declared: Statement) -> None:
    """Raise `StudentNameInTierDError` if `declared` inserts a student-name column into Tier D.

    Runs on the durable tier's two write doors (`enqueue_write` before queueing,
    `Tx.execute` before executing) and nowhere else: the requirement is about *inserts* into
    *Tier D*, and a guard on the other tiers or on reads would be a rule without a threat
    behind it. Parses the column list out of the statement's INSERT header — `INSERT [OR …]
    INTO tbl (cols)`, `REPLACE INTO tbl (cols)` — and applies `is_student_name_column` to
    each named column.

    What the parse tolerates, because each was a silent bypass in an earlier draft: CTE
    prefixes (`WITH x AS (...) INSERT INTO ...` — hence the unanchored search, with its
    string-literal trade recorded above), comments between the header's tokens, and
    schema-qualified tables (`main.label` — the last identifier is the table). What it
    deliberately does not: a statement with **no column list** (`INSERT INTO t DEFAULT
    VALUES`, or a bare `VALUES (...)`) names no column and passes — there is nothing here to
    inspect, and the schema sweep (`TC-STORE-12`'s third limb) is what holds a name-bearing
    *column* out of Tier D in the first place. Nor does the mapping see unsegmented
    abbreviations (`sname`) — `is_student_name_column`'s own stated limit.

    Exactness is the control that makes this a guard rather than a wrapper: only a
    name-mapped column raises. Every other failure — a typo'd column, a CHECK violation, a
    locked database — passes through exactly as SQLite raised it, so a caller can trust
    `StudentNameInTierDError` to mean the one thing it names.
    """
    matched = _INSERT_COLUMN_LIST.search(declared.sql)
    if matched is None:
        return
    # Schema-qualified: `main"."label`, `main.label`, `"main".label` — the table is the last
    # identifier. Split on the dots after unquoting; every segment carries the quotes it had.
    segments = matched.group(1).split(".")
    table = segments[-1].strip().strip("\"'`[]")
    columns = [part.strip().strip("\"'`[]") for part in matched.group(2).split(",")]
    offenders = [column for column in columns if column and is_student_name_column(column)]
    if offenders:
        raise StudentNameInTierDError(
            f"Tier D refused a write naming student-name column(s) "
            f"{', '.join(repr(c) for c in offenders)} on table {table!r}. FR-STORE-12: the "
            f"identity mapping exists only in Tier C; Tier D carries {TIER_D_IDENTITY_COLUMN} "
            f"and is pseudonymized (CT-STORE-09), and it is the one tier purge_cohort does "
            f"not touch — a name here would outlive every retention control in the system."
        )


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


# --- the schema --------------------------------------------------------------------------------
#
# One numbered migration per tier so far. Each is a tuple of `Statement`s applied in order inside
# one transaction, and each creates the tables §3.3's data model names for that tier with a
# **minimal column set**: a primary key, the foreign keys the tier's own structure implies, and
# the columns a merged test already reads.
#
# That is the line between owning files and owning meaning. The owning module adds its columns in
# a later numbered migration (`ALTER TABLE ... ADD COLUMN`, which SQLite does in place) — so
# `M-PKG` decides what a criterion carries and `M-ORCH` decides what a work unit carries, while
# the file layout, the constraints and the version discipline stay here.
#
# Every statement below is a literal. `tests/artifact/test_store_query_surface.py` scans this
# tree for SQL assembled from anything else, and it is green today precisely because nothing here
# builds a statement.

_SCHEMA_VERSION_TABLE = Statement(
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version    INTEGER NOT NULL PRIMARY KEY,
        name       TEXT    NOT NULL,
        applied_at TEXT    NOT NULL
    )
    """
)

#: Tier P — `packages/<package_id>.pkg.sqlite`, permanent, no PII by construction.
_PACKAGE_001: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE package (
            package_id TEXT NOT NULL PRIMARY KEY,
            created_at TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE package_version (
            package_version_id TEXT    NOT NULL PRIMARY KEY,
            package_id         TEXT    NOT NULL REFERENCES package(package_id),
            revision           INTEGER NOT NULL CHECK (revision >= 0),
            locked             INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0, 1))
        )
        """
    ),
    Statement(
        """
        CREATE TABLE criterion (
            criterion_id       TEXT NOT NULL,
            package_version_id TEXT NOT NULL REFERENCES package_version(package_version_id),
            question_id        TEXT NOT NULL,
            kind               TEXT NOT NULL CHECK (kind IN ('open', 'mcq')),
            PRIMARY KEY (package_version_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE band (
            package_version_id TEXT    NOT NULL,
            criterion_id       TEXT    NOT NULL,
            ordinal            INTEGER NOT NULL CHECK (ordinal >= 0),
            band               TEXT    NOT NULL,
            points             REAL    NOT NULL CHECK (points >= 0),
            PRIMARY KEY (package_version_id, criterion_id, ordinal),
            FOREIGN KEY (package_version_id, criterion_id)
                REFERENCES criterion(package_version_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE criterion_dependency (
            package_version_id TEXT NOT NULL,
            criterion_id       TEXT NOT NULL,
            depends_on         TEXT NOT NULL,
            PRIMARY KEY (package_version_id, criterion_id, depends_on),
            FOREIGN KEY (package_version_id, criterion_id)
                REFERENCES criterion(package_version_id, criterion_id),
            CHECK (criterion_id <> depends_on)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE exemplar (
            exemplar_id        TEXT NOT NULL PRIMARY KEY,
            package_version_id TEXT NOT NULL,
            criterion_id       TEXT NOT NULL,
            band               TEXT NOT NULL,
            FOREIGN KEY (package_version_id, criterion_id)
                REFERENCES criterion(package_version_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE grade_policy (
            package_version_id TEXT NOT NULL PRIMARY KEY
                REFERENCES package_version(package_version_id),
            policy             TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE validation_record (
            validation_record_id TEXT NOT NULL PRIMARY KEY,
            package_version_id   TEXT NOT NULL REFERENCES package_version(package_version_id),
            backend_profile      TEXT NOT NULL,
            panel_build_ref      TEXT NOT NULL,
            recorded_at          TEXT NOT NULL
        )
        """
    ),
)

#: Tiers C and R — `cohorts/<cohort_id>.sqlite`, one file, per administration, heavy PII.
#: C first, then R: R's rows reference C's, and SQLite checks a foreign key against a table that
#: must already exist.
_COHORT_001: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE cohort (
            cohort_id     TEXT NOT NULL PRIMARY KEY,
            consent_class TEXT NOT NULL CHECK (consent_class IN ('synthetic', 'consented', 'real')),
            created_at    TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE roster (
            cohort_id   TEXT NOT NULL REFERENCES cohort(cohort_id),
            student_ref TEXT NOT NULL,
            PRIMARY KEY (cohort_id, student_ref)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE submission (
            submission_id TEXT NOT NULL PRIMARY KEY,
            cohort_id     TEXT NOT NULL REFERENCES cohort(cohort_id),
            student_ref   TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE document (
            document_id   TEXT NOT NULL PRIMARY KEY,
            submission_id TEXT NOT NULL REFERENCES submission(submission_id),
            content_hash  TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE document_region (
            region_id    TEXT    NOT NULL PRIMARY KEY,
            document_id  TEXT    NOT NULL REFERENCES document(document_id),
            page_no      INTEGER NOT NULL CHECK (page_no >= 1),
            element_kind TEXT    NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE work_unit (
            work_id       TEXT NOT NULL PRIMARY KEY,
            submission_id TEXT REFERENCES submission(submission_id),
            stage         TEXT NOT NULL,
            status        TEXT NOT NULL
                CHECK (status IN ('pending', 'leased', 'done', 'failed', 'quarantined'))
        )
        """
    ),
    Statement(
        """
        CREATE TABLE evidence (
            evidence_id TEXT NOT NULL PRIMARY KEY,
            work_id     TEXT NOT NULL REFERENCES work_unit(work_id),
            document_id TEXT REFERENCES document(document_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE verdict (
            verdict_id TEXT NOT NULL PRIMARY KEY,
            work_id    TEXT NOT NULL REFERENCES work_unit(work_id),
            judge_id   TEXT NOT NULL,
            band       TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE criterion_score (
            submission_id TEXT NOT NULL REFERENCES submission(submission_id),
            criterion_id  TEXT NOT NULL,
            band          TEXT NOT NULL,
            PRIMARY KEY (submission_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE submission_grade (
            submission_id TEXT    NOT NULL REFERENCES submission(submission_id),
            revision      INTEGER NOT NULL CHECK (revision >= 0),
            PRIMARY KEY (submission_id, revision)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE narrative (
            narrative_id  TEXT NOT NULL PRIMARY KEY,
            submission_id TEXT NOT NULL REFERENCES submission(submission_id),
            criterion_id  TEXT
        )
        """
    ),
    Statement(
        """
        CREATE TABLE review_queue (
            queue_id      TEXT NOT NULL PRIMARY KEY,
            submission_id TEXT NOT NULL REFERENCES submission(submission_id),
            criterion_id  TEXT,
            reason        TEXT NOT NULL
        )
        """
    ),
)

#: Tier D — `durable.sqlite`, permanent, pseudonymized.
#:
#: No column here is a student name and none ever may be: Tier D survives the cohort purge, so a
#: name that reaches it outlives every mechanism built to remove it (`FR-STORE-12`,
#: `CT-STORE-09`). `student_ref` is the only identity column, and `TC-STATS-C18` sweeps this
#: schema for the alternatives.
_DURABLE_001: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE audit_record (
            audit_record_id TEXT NOT NULL PRIMARY KEY,
            run_id          TEXT NOT NULL,
            recorded_at     TEXT NOT NULL,
            profile_summary TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE label (
            label_id     TEXT NOT NULL PRIMARY KEY,
            run_id       TEXT NOT NULL,
            student_ref  TEXT,
            criterion_id TEXT NOT NULL,
            label_type   TEXT NOT NULL,
            band         TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE criterion_stats (
            package_version_id TEXT    NOT NULL,
            criterion_id       TEXT    NOT NULL,
            backend_profile    TEXT    NOT NULL,
            panel_build_ref    TEXT    NOT NULL,
            n                  INTEGER NOT NULL CHECK (n >= 0),
            PRIMARY KEY (package_version_id, criterion_id, backend_profile, panel_build_ref)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE mcq_item_stats (
            package_version_id TEXT    NOT NULL,
            criterion_id       TEXT    NOT NULL,
            option             TEXT    NOT NULL,
            chosen             INTEGER NOT NULL CHECK (chosen >= 0),
            PRIMARY KEY (package_version_id, criterion_id, option)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE mcq_item_summary (
            package_version_id TEXT NOT NULL,
            criterion_id       TEXT NOT NULL,
            PRIMARY KEY (package_version_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE run_metrics (
            run_id     TEXT NOT NULL,
            metric     TEXT NOT NULL,
            value      REAL NOT NULL,
            PRIMARY KEY (run_id, metric)
        )
        """
    ),
)


@dataclass(frozen=True)
class Migration:
    """One numbered, forward-only schema step.

    Forward-only and reversible **only by restoring a copy** (`NFR-STORE-04`). There is no `down`
    field and there will not be one: a reversal that runs against production data is how a
    migration that was wrong becomes two migrations that are wrong.
    """

    version: int
    name: str
    statements: tuple[Statement, ...]


TIER_MIGRATIONS: Mapping[Tier, tuple[Migration, ...]] = {
    Tier.PACKAGE: (Migration(1, "package_tier_initial", _PACKAGE_001),),
    Tier.COHORT: (Migration(1, "cohort_tier_initial", _COHORT_001),),
    Tier.DURABLE: (Migration(1, "durable_tier_initial", _DURABLE_001),),
}


def current_schema_version(tier: Tier) -> int:
    """The schema version this binary implements for `tier`.

    `max`, not `len`: a migration withdrawn before release leaves a gap in the numbering, and a
    count would then claim a version the binary does not implement.
    """
    migrations = TIER_MIGRATIONS[tier]
    return max((m.version for m in migrations), default=0)


# --- purge (FR-STORE-07, CT-STORE-10) -----------------------------------------------------------
#
# `purge_cohort` is irreversible and it is the only operation that deletes student work, so
# everything it executes is declared here, next to the schema it deletes from.
#
# The DELETE list is **bound to `_COHORT_001`**, and any later migration that adds a table to
# the cohort tier must add its DELETE here in the same change: purge refuses a table it does
# not recognize (see `SqliteStore.purge_cohort`) rather than silently leave its bytes behind.
# A silently-skipped table is student text surviving a purge — the failure `CT-STORE-10`
# exists to make impossible, arriving as a green checkmark.
#
# `schema_version` is **deliberately not deleted**. It is this module's own bookkeeping, and
# wiping it makes `_applied_versions` empty on the next open, so migration 001 re-runs its
# CREATE TABLE statements against the surviving tables and the file is permanently
# unopenable — a purge that corrupts what it purged. The `sqlite_%` internals are excluded
# for the same reason: they are the database's bookkeeping, not the cohort's content.

_SCHEMA_VERSION_TABLE_NAME = "schema_version"

_SELECT_COHORT_TABLES = Statement("SELECT name FROM sqlite_master WHERE type = 'table'")
_PRAGMA_DEFER_FOREIGN_KEYS = Statement("PRAGMA defer_foreign_keys = ON")
_VACUUM = Statement("VACUUM")
#: Run after the `VACUUM`, for a reason the main file alone cannot see: `VACUUM` rewrites the
#: database, but the freed pages — with their student text — sit in the `-wal` until a
#: checkpoint reclaims them, and the last-connection-close checkpoint that would normally
#: clear them does not fire while any other connection is open. TRUNCATE zeroes the file;
#: best effort by nature, since a concurrent reader can hold it busy — the rewritten main
#: database is the guarantee, this removes the residual.
_PRAGMA_WAL_CHECKPOINT_TRUNCATE = Statement("PRAGMA wal_checkpoint(TRUNCATE)")

#: Tier D's three promotion gates, in `CT-STORE-10`'s words: audit records, labels, and
#: per-criterion statistics. A gate passes iff the table exists, carries the `cohort_id`
#: scoping column (the convention recorded in the file docstring's decision table), and holds
#: at least one row for the cohort being purged. Fixed literals, one per table, rather than
#: anything assembled: a PRAGMA's table name cannot be a bound parameter, and an assembled
#: statement is exactly what `SEC-15` exists to refuse.
_PURGE_TABLE_INFO: Mapping[str, Statement] = {
    "audit_record": Statement("PRAGMA table_info(audit_record)"),
    "label": Statement("PRAGMA table_info(label)"),
    "criterion_stats": Statement("PRAGMA table_info(criterion_stats)"),
}
_PURGE_PROMOTED_ROWS: Mapping[str, Statement] = {
    "audit_record": Statement("SELECT COUNT(*) FROM audit_record WHERE cohort_id = :cohort_id"),
    "label": Statement("SELECT COUNT(*) FROM label WHERE cohort_id = :cohort_id"),
    "criterion_stats": Statement(
        "SELECT COUNT(*) FROM criterion_stats WHERE cohort_id = :cohort_id"
    ),
}
#: The three gates, named as `CT-STORE-10` names them, so the refusal says which promotion is
#: missing rather than that "a precondition failed".
_PURGE_PRECONDITIONS: tuple[tuple[str, str], ...] = (
    ("audit records", "audit_record"),
    ("labels", "label"),
    ("per-criterion statistics", "criterion_stats"),
)

#: Children before parents. Deferred foreign keys make the order irrelevant to correctness —
#: `PRAGMA defer_foreign_keys` is set before the BEGIN (SQLite makes it a no-op inside a
#: transaction) and checks the constraints at COMMIT, when every table is empty — but a
#: deterministic order keeps the report stable from run to run.
_COHORT_PURGE_ORDER: tuple[str, ...] = (
    "review_queue", "narrative", "submission_grade", "criterion_score", "verdict",
    "evidence", "work_unit", "document_region", "document", "submission", "roster",
    "cohort",
)
_PURGE_DELETES: Mapping[str, Statement] = {
    "review_queue": Statement("DELETE FROM review_queue"),
    "narrative": Statement("DELETE FROM narrative"),
    "submission_grade": Statement("DELETE FROM submission_grade"),
    "criterion_score": Statement("DELETE FROM criterion_score"),
    "verdict": Statement("DELETE FROM verdict"),
    "evidence": Statement("DELETE FROM evidence"),
    "work_unit": Statement("DELETE FROM work_unit"),
    "document_region": Statement("DELETE FROM document_region"),
    "document": Statement("DELETE FROM document"),
    "submission": Statement("DELETE FROM submission"),
    "roster": Statement("DELETE FROM roster"),
    "cohort": Statement("DELETE FROM cohort"),
}


@dataclass(frozen=True)
class PurgeReport:
    """What `purge_cohort` actually did (`CLAUDE.md` seam 4).

    Per-field rather than a boolean, for the reason `IngestReport.gates` is per-gate: purge
    is irreversible, and a bare "purged" sitting on top of an empty report is the top
    silent-failure trap standing on the one operation where silence is unrecoverable.

    `blobs_deleted` is an **honest zero**: blob reclamation at purge time is an accepted risk
    with the rule undeclared (test plan §7.4 — "the design does not say whether
    content-addressed deduplication or per-cohort purge wins"), and the blob store itself is
    #12's. Deleting a shared blob breaks the cohort that still references it; leaving it
    leaves student bytes behind; until the design declares which, purge does not touch the
    blob directory and the report says so rather than implying a sweep happened.
    """

    cohort_id: str
    preconditions_verified: tuple[str, ...]
    tables_cleared: tuple[str, ...]
    rows_deleted_by_table: Mapping[str, int]
    file_bytes_before: int
    file_bytes_after: int
    vacuum_duration_ms: float
    blobs_deleted: int = 0


# --- connections ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TierOpened:
    """What opening one database actually did (`CLAUDE.md` seam 4).

    Per-field rather than a boolean, for the reason `IngestReport.gates` is per-gate: a bare
    "opened successfully" sitting on top of a database with `journal_mode=delete` and foreign keys
    off is the top silent-failure trap, and every field below is one somebody would otherwise
    have to take on trust.
    """

    tier: Tier
    path: Path
    read_only: bool
    schema_version_before: int
    schema_version_after: int
    migrations_applied: tuple[int, ...]
    journal_mode: str
    foreign_keys: bool


_SELECT_APPLIED_VERSIONS = Statement("SELECT version FROM schema_version")
_SELECT_SCHEMA_VERSION_TABLE = Statement(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
)
_INSERT_VERSION = Statement(
    "INSERT INTO schema_version (version, name, applied_at) "
    "VALUES (:version, :name, :applied_at)"
)
_PRAGMA_FOREIGN_KEYS_ON = Statement("PRAGMA foreign_keys = ON")
_PRAGMA_FOREIGN_KEYS = Statement("PRAGMA foreign_keys")
_PRAGMA_JOURNAL_WAL = Statement("PRAGMA journal_mode = WAL")
_PRAGMA_JOURNAL_MODE = Statement("PRAGMA journal_mode")
_BEGIN = Statement("BEGIN IMMEDIATE")
_COMMIT = Statement("COMMIT")
_ROLLBACK = Statement("ROLLBACK")


def _run(connection: sqlite3.Connection, declared: Statement,
         params: Mapping[str, Any] | None = None, *, retries: int = DEFAULT_BUSY_RETRIES
         ) -> sqlite3.Cursor:
    """The module's single execute site (`FR-STORE-08`, `SEC-15`).

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
    """
    attempt = 0
    while True:
        try:
            return connection.execute(declared.sql, dict(params or {}))
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(0.02 * attempt)


def _connect(path: Path, *, read_only: bool, busy_timeout_ms: int,
             retries: int, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open one database and enable foreign keys. **Writes nothing.**

    `foreign_keys` is set on **every** connection, including read-only ones: SQLite defaults it
    off and the setting is per-connection, not per-database, so the CHECK and FOREIGN KEY
    constraints the HLD relies on as guarantees are only guarantees if this line runs every time.
    It is a connection setting and touches no byte of the file.

    **`journal_mode = WAL` is deliberately not set here**, and the ordering is the whole point.
    Setting WAL rewrites bytes 18 and 19 of the file header — so a version check performed *after*
    it has already modified a database the store is about to refuse to open. Review measured
    exactly that: a v99 database came back with a changed mtime and a changed content hash after
    `SchemaTooNewError`, which is what `TC-STORE-05`'s oracle ("the file is unmodified, asserted
    by mtime and content hash") exists to catch, and what `CT-STORE-11`'s "no partial read" means
    in practice. `_open_tier` sets WAL after the check, on the writable path only.
    """
    if read_only:
        # `as_uri()` rather than a hand-built string: it produces the canonical `file:///...`
        # form on both platforms and percent-encodes a path containing a space, which SQLite's
        # URI parser then decodes. A hand-built `"file:" + str(path)` opens the wrong file — or
        # silently creates a new one — the first time a school puts its data under a directory
        # with a space in the name.
        connection = sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=busy_timeout_ms / 1000,
            check_same_thread=check_same_thread,
        )
    else:
        connection = sqlite3.connect(
            path, timeout=busy_timeout_ms / 1000, check_same_thread=check_same_thread
        )
    connection.row_factory = sqlite3.Row
    # Autocommit at the driver level, which as of #11 is what lets this module issue its own
    # BEGIN / COMMIT / ROLLBACK through `_run` rather than having sqlite3 open transactions
    # behind it. Set before any DDL so a migration's BEGIN is the only transaction in play.
    connection.isolation_level = None
    _run(connection, _PRAGMA_FOREIGN_KEYS_ON, retries=retries)
    return connection


def _applied_versions(connection: sqlite3.Connection, retries: int) -> frozenset[int]:
    """Every migration version this database has recorded, as a set.

    A **set**, not `MAX(version)`, and review is what forced the difference. `schema_version`
    carries one row per applied migration, so a database at 1 and 3 — the shape a withdrawn
    migration 2 leaves behind, or a branch merged in the wrong order — reports a maximum of 3.
    Filtering pending work by `version > 3` then skips 2 forever, silently, and the tier opens
    reporting a version whose schema it does not have. Measured: `migration 2 SKIPPED = True`,
    its table absent.

    The set makes "pending" mean what it says: any numbered migration this database has not
    recorded. `NFR-STORE-04`'s migrate-every-prior-version suite is the thing that would have
    caught this, and it cannot exist until there is more than one version — see the PR.
    """
    if not _run(connection, _SELECT_SCHEMA_VERSION_TABLE, retries=retries).fetchall():
        return frozenset()
    rows = _run(connection, _SELECT_APPLIED_VERSIONS, retries=retries).fetchall()
    return frozenset(int(row[0]) for row in rows if row[0] is not None)


def _migrate(connection: sqlite3.Connection, tier: Tier, already: frozenset[int],
             retries: int) -> tuple[int, ...]:
    """Apply every migration this database has not recorded, in version order.

    Pending is "not in `already`" rather than "above the maximum", so a database carrying 1 and 3
    still gets 2 when the binary supplies it. See `_applied_versions`.

    One transaction **per migration** rather than one for all of them: SQLite can roll back DDL,
    so a failure leaves the database at the last *complete* migration rather than at an
    intermediate state no version number describes. That is what makes re-running the open safe,
    and it is why `applied` is returned as the versions that actually landed.
    """
    applied: list[int] = []
    pending = sorted(
        (m for m in TIER_MIGRATIONS[tier] if m.version not in already), key=lambda m: m.version
    )
    for migration in pending:
        _run(connection, _BEGIN, retries=retries)
        try:
            _run(connection, _SCHEMA_VERSION_TABLE, retries=retries)
            for statement in migration.statements:
                _run(connection, statement, retries=retries)
            _run(
                connection,
                _INSERT_VERSION,
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                retries=retries,
            )
            _run(connection, _COMMIT, retries=retries)
        except Exception:
            # The rollback is best-effort and its failure is **swallowed**, deliberately. SQLite
            # rolls a statement-level failure back on its own, so the explicit ROLLBACK then
            # raises "cannot rollback - no transaction is active" — and letting that propagate
            # replaces the real finding (an IntegrityError, or ENOSPC, which is exactly what #13's
            # DiskFullError has to classify) with a message about transaction bookkeeping. Review
            # measured the swap.
            try:
                _run(connection, _ROLLBACK, retries=retries)
            except sqlite3.Error:
                pass
            raise
        applied.append(migration.version)
    return tuple(applied)


def _open_tier(path: Path, tier: Tier, *, read_only: bool, busy_timeout_ms: int,
               retries: int) -> tuple[sqlite3.Connection, TierOpened]:
    """Open, refuse if too new, migrate if behind, and report what happened.

    The order is the requirement. Nothing writes to the file until the version check has passed,
    so `CT-STORE-11`'s *"refuses to open, no partial read"* and `TC-STORE-05`'s *"the file is
    unmodified, asserted by mtime and content hash"* are both properties of the control flow
    rather than of anyone's care.
    """
    if read_only and not path.exists():
        raise ConfigurationProblem(
            f"{path} does not exist, so it cannot be opened read-only. FR-STORE-13 is about "
            f"inspecting an *imported* package before it is trusted."
        )

    path.parent.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)
    # Umask-filtering applies here as much as in open_store, and a lazily-opened tier's
    # parent may be created before any hardening ran on it.
    _harden_dir(path.parent)
    connection = _connect(
        path, read_only=read_only, busy_timeout_ms=busy_timeout_ms, retries=retries
    )

    try:
        already = _applied_versions(connection, retries)
        present = max(already, default=0)
        implemented = current_schema_version(tier)

        # Before anything is read out of a table and before the first migration: `CT-STORE-11`
        # says the store "refuses to open, no partial read", and the only way to mean that is to
        # decide it here.
        if present > implemented:
            raise SchemaTooNewError(
                f"{path} is at schema version {present}; this binary implements {implemented} "
                f"for tier {tier.value!r}. Migrations are forward-only (NFR-STORE-04), so there "
                f"is nothing to run and nothing safe to read — upgrade the binary or restore a "
                f"copy taken at version {implemented} or below."
            )

        if read_only:
            applied: tuple[int, ...] = ()
        else:
            # The first write to the file, and it happens **after** the refusal above.
            # `journal_mode = WAL` rewrites the header, so setting it earlier would modify a
            # database the store was about to refuse — see `_connect`.
            _run(connection, _PRAGMA_JOURNAL_WAL, retries=retries)
            applied = _migrate(connection, tier, already, retries)
            # Owner-only on the file this connection just created or reopened, and on the
            # `-wal`/`-shm` siblings the WAL pragma above created (`FR-STORE-09`). Only ever
            # on the writable path: a read-only inspection must not touch the file it is
            # inspecting, and the too-new refusal above must leave what it refused untouched.
            _harden_files(path)

        after = max(_applied_versions(connection, retries), default=0)
        journal_mode = str(_run(connection, _PRAGMA_JOURNAL_MODE, retries=retries).fetchone()[0])
        foreign_keys = bool(_run(connection, _PRAGMA_FOREIGN_KEYS, retries=retries).fetchone()[0])
    except Exception:
        connection.close()
        raise

    return connection, TierOpened(
        tier=tier,
        path=path,
        read_only=read_only,
        schema_version_before=present,
        schema_version_after=after,
        migrations_applied=applied,
        journal_mode=journal_mode,
        foreign_keys=foreign_keys,
    )


# --- the handles ----------------------------------------------------------------------------------


#: The statement verbs `query` accepts. Everything else is a write and belongs on the queue
#: (`CT-STORE-02`) or inside a transaction (`CT-STORE-03`), both of which are #11's.
READ_VERBS: frozenset[str] = frozenset({"select", "with", "values", "explain", "pragma"})


def _refuse_write(declared: Statement) -> None:
    """Raise unless `declared` starts with a read verb. See `SqliteTierHandle.query`."""
    words = declared.sql.lstrip().lstrip("(").split(None, 1)
    first = words[0].lower() if words else ""
    if first in READ_VERBS:
        return
    raise WriteThroughQueryError(
        f"query() was given a {first.upper() or 'blank'} statement. It reads; writing goes "
        f"through enqueue_write (asynchronous, CT-STORE-02) or transaction() (atomic, "
        f"CT-STORE-03), both of which are issue #11. A synchronous write named query() would "
        f"let callers be written against the opposite of the contract."
    )


@dataclass(frozen=True)
class StoreLimits:
    """The environment-sensitive numbers, resolved once at `open_store`.

    Resolved at construction, not per call, and that is a decision `TC-STORE-24` depends on:
    seam 3 says "production value is the default; the knob exists so a slower test box can
    adjust without a code change", which describes a value read when the process configures
    itself. A store that re-read `os.environ` on every enqueue would be promising live reload,
    which nothing requires and which makes the configured value unobservable.
    """

    commit_batch: int = DEFAULT_COMMIT_BATCH
    commit_interval_ms: int = DEFAULT_COMMIT_INTERVAL_MS
    write_queue_depth: int = DEFAULT_WRITE_QUEUE_DEPTH
    projected_run_bytes: int = DEFAULT_PROJECTED_RUN_BYTES
    queue_depth_sustain_ms: int = DEFAULT_QUEUE_DEPTH_SUSTAIN_MS
    writer_poll_ms: int = DEFAULT_WRITER_POLL_MS
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
    retries: int = DEFAULT_BUSY_RETRIES

    def __post_init__(self) -> None:
        """Refuse a knob whose value is meaningless, rather than hanging on it.

        `_int_env` rejects a negative, which leaves zero -- and zero is not a small value here,
        it is a different program. `commit_batch=0` makes every batch empty, so the writer spins
        forever committing nothing while the queue never shrinks; `write_queue_depth=0` makes
        `enqueue_write` block on its first call, since the depth is reached before anything is
        queued. Both are silent hangs from one mistyped environment variable, and seam 3 exists
        so a slower box can retune these -- retuning is when a typo happens.
        """
        for name, env, value in (
            ("commit_batch", COMMIT_BATCH_ENV, self.commit_batch),
            ("commit_interval_ms", COMMIT_INTERVAL_MS_ENV, self.commit_interval_ms),
            ("write_queue_depth", WRITE_QUEUE_DEPTH_ENV, self.write_queue_depth),
            ("writer_poll_ms", WRITER_POLL_MS_ENV, self.writer_poll_ms),
        ):
            if value <= 0:
                raise ConfigurationProblem(
                    f"{env} is {value}; it must be greater than zero. A {name} of zero does not "
                    "mean 'no limit' — it stalls the write queue with nothing to report."
                )

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> StoreLimits:
        return cls(
            commit_batch=_int_env(COMMIT_BATCH_ENV, DEFAULT_COMMIT_BATCH, environ),
            commit_interval_ms=_int_env(
                COMMIT_INTERVAL_MS_ENV, DEFAULT_COMMIT_INTERVAL_MS, environ),
            write_queue_depth=_int_env(
                WRITE_QUEUE_DEPTH_ENV, DEFAULT_WRITE_QUEUE_DEPTH, environ),
            projected_run_bytes=_int_env(
                PROJECTED_RUN_BYTES_ENV, DEFAULT_PROJECTED_RUN_BYTES, environ),
            queue_depth_sustain_ms=_int_env(
                QUEUE_DEPTH_SUSTAIN_MS_ENV, DEFAULT_QUEUE_DEPTH_SUSTAIN_MS, environ),
            writer_poll_ms=_int_env(WRITER_POLL_MS_ENV, DEFAULT_WRITER_POLL_MS, environ),
            busy_timeout_ms=_int_env(BUSY_TIMEOUT_MS_ENV, DEFAULT_BUSY_TIMEOUT_MS, environ),
            retries=_int_env(BUSY_RETRIES_ENV, DEFAULT_BUSY_RETRIES, environ),
        )


class Tx:
    """The handle a `transaction()` body writes through (`CT-STORE-03`).

    Section 3.3's Interfaces block types `transaction()` as `ContextManager[Tx]` and never
    defines `Tx`, so its one method is this module's. `execute(statement, **params)` mirrors
    `query` deliberately: same declared-`Statement` argument, same keyword parameters, so a
    caller moving a read into a transaction changes the method name and nothing else.

    **No `commit` and no `rollback`.** The context manager owns both -- commit on a clean exit,
    rollback on any exception -- because `CT-STORE-03`'s promise is "atomic and synchronous over
    its whole body", and a body that could commit halfway through would make "both present or
    both absent" a convention rather than a guarantee. `FUZZ-07` is the case that notices:
    review proved its atomicity property vacuous against a `transaction()` that was a bare
    `yield`, and a `Tx` exposing `commit()` is the same hole one level up.
    """

    __slots__ = ("_connection", "_guard", "_retries")

    def __init__(self, connection: sqlite3.Connection, retries: int,
                 guard: Callable[[Statement], None] | None = None) -> None:
        self._connection = connection
        self._retries = retries
        # The tier write guard, if this handle has one (`_reject_tier_d_student_name_insert`
        # on Tier D, `None` elsewhere). Set before the first `execute`, because a guard that
        # only applied from the second statement on would let the first one through.
        self._guard = guard

    def execute(self, statement: Statement, **params: Any) -> Sequence[Row]:
        """Run one declared statement inside the open transaction.

        Reads are allowed as well as writes -- `_refuse_write` guards `query`, not this --
        because a transaction that could not read cannot do the read-modify-write every ledger
        transition is. The rows come back for the same reason `query` returns them.

        The tier write guard runs **before** the statement reaches SQLite: `FR-STORE-12`'s
        rejection is of the insert itself, so a name-bearing statement must fail before it
        writes, not after — and a guard that ran after a successful execute would have
        already landed the row it is refusing.
        """
        declared = statement if isinstance(statement, Statement) else Statement(statement)
        if self._guard is not None:
            self._guard(declared)
        return _run(self._connection, declared, params, retries=self._retries).fetchall()


def _is_disk_full(error: BaseException) -> bool:
    """Is this failure the out-of-space condition `FR-STORE-10` is about?

    Two signatures, because the same condition arrives wearing two faces: SQLite's
    `SQLITE_FULL` (`OperationalError: database or disk is full`) when the *database* layer
    runs out — which on a dedicated data disk is the disk, not the database, since this
    module sets no `max_page_count` — and the OS's `OSError(ENOSPC)` when the filesystem
    itself refuses before SQLite is even reached (a `VACUUM` writing a temp copy can land
    there, as can the WAL). Anything else is not disk-full and must not be classified as
    one: a mis-classified error halts a process that could have kept going, and "halts the
    process" is not an outcome to hand to a loose string match. The message check is
    SQLite's own wording, not a guess at it.
    """
    if isinstance(error, sqlite3.OperationalError):
        return "database or disk is full" in str(error).lower()
    return isinstance(error, OSError) and error.errno == errno.ENOSPC


def _as_disk_full(error: BaseException) -> DiskFullError | None:
    """`DiskFullError` for `error` — chained, with the decision-table wording — or `None`.

    The classification step shared by every door the requirement covers: the write queue's
    batch path, a `transaction()` body, and purge's delete and `VACUUM` steps. The door
    that saw the failure owns the state to record (the queue's failure list and broken
    flag; purge has none) and then runs the halt hook — which is why this helper only
    builds the error and never halts on its own.
    """
    if not _is_disk_full(error):
        return None
    failure = DiskFullError(
        f"the write failed for want of disk space and the process halts (FR-STORE-10): "
        f"{error}. The interrupted work was rolled back whole, so no result row is "
        f"present without its ledger transition, and the ledger stands at its last "
        f"commit, which is resumable (CT-STORE-05's window, not a new loss)."
    )
    failure.__cause__ = error
    return failure


class WriteQueue:
    """The single writer: one queue, one thread, batched commits, backpressure at the depth.

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
    """

    __slots__ = (
        "_broken", "_condition", "_connect_write", "_failures", "_guard", "_halt", "_holder",
        "_last_latency_ms", "_limits", "_over_since", "_pending", "_queue", "_stamps",
        "_stopping", "_thread", "_write_lock",
    )

    def __init__(self, connect_write: Any, limits: StoreLimits, *,
                 guard: Callable[[Statement], None] | None = None,
                 halt: Callable[[BaseException], None] | None = None) -> None:
        self._connect_write = connect_write
        self._limits = limits
        # The tier write guard (Tier D's student-name check) or `None` for a tier without
        # one. Applied at both doors: `enqueue` before queueing, `transaction` via the `Tx`
        # it hands out. See `_reject_tier_d_student_name_insert`.
        self._guard = guard
        # The disk-full halt (`FR-STORE-10`). Module-level default so a test monkeypatches
        # exactly one name; see `DiskFullError`.
        self._halt = _halt_process_on_disk_full if halt is None else halt
        self._queue: deque[WriteUnit] = deque()
        self._stamps: deque[float] = deque()
        self._condition = threading.Condition()
        self._write_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._last_latency_ms = 0.0
        self._over_since: float | None = None
        self._failures: list[BaseException] = []
        # Set once, by the disk-full path: the queue is terminally broken and refuses
        # further writes with the `DiskFullError` that broke it (`CT-STORE-11`: not
        # retryable by the caller). In production the halt hook never returns; this is what
        # an injected (test) hook that does return observes, and what a caller on another
        # thread hits the instant the writer classified the failure.
        self._broken: DiskFullError | None = None
        # Rows enqueued and not yet durable -- queued *or* in flight. One counter rather than
        # two terms; see `depth`.
        self._pending = 0
        # Whether *this* thread is inside a `transaction()` body on this queue. See `enqueue`.
        self._holder = threading.local()

    # -- what the metrics read -----------------------------------------------------------------

    @property
    def depth(self) -> int:
        """Rows enqueued and not yet durable -- queued *or* mid-commit.

        "Not yet durable" rather than "still on the deque", and the difference is what a caller
        waiting for its writes depends on: `CT-STORE-02` makes `enqueue_write` asynchronous and
        nothing else says when the row arrives, so polling this to zero is the only way to wait.
        Counting the deque alone reports zero the instant the last batch is *popped*, while it is
        still inside `COMMIT`, and the caller reads back one commit short. Measured before this
        was a single counter: `TC-STORE-03` landed 225 of 250 rows -- in order, nothing lost,
        the drain simply believing it had finished a batch early.

        **One counter, not two terms added together.** An earlier form was
        `len(self._queue) + self._in_flight`, incremented after the pops; review found the gap
        between the last `popleft` and the `+=` still reads zero for a batch that is in neither
        place. Narrower than a whole `COMMIT`, and not tripped in nine attempts -- but a window
        the docstring claimed was closed. A single `int` read is atomic in CPython and has no
        such gap.

        No lock, deliberately. The merged `_drain` polls this in a tight loop with no sleep, and
        a poll contending with the writer for the writer's own lock on every iteration would be
        the reader blocking the writer, in the one place this module exists to prevent it.
        """
        return self._pending

    @property
    def backpressure_active(self) -> bool:
        """`FR-STORE-05`'s level, at or above the configured depth.

        At, not above. The requirement says "when the pending write queue exceeds a configured
        depth" and `TC-STORE-07` reads that boundary as inclusive -- `N-1` clear, `N` raised. A
        signal that first appeared at `N+1` would let the queue reach the bound
        `NFR-STORE-02`'s durability window is computed from before saying anything.
        """
        return self.depth >= self._limits.write_queue_depth

    @property
    def last_commit_latency_ms(self) -> float:
        return self._last_latency_ms

    @property
    def failures(self) -> tuple[BaseException, ...]:
        return tuple(self._failures)

    def sustained_over_threshold(self) -> bool:
        """Whether backpressure has held long enough to be the *alert* rather than the signal."""
        since = self._over_since
        if since is None:
            return False
        return (time.monotonic() - since) * 1000.0 >= self._limits.queue_depth_sustain_ms

    # -- the caller side -----------------------------------------------------------------------

    def enqueue(self, unit: WriteUnit) -> None:
        """Append, blocking while the queue is at or above the configured depth.

        Blocking is one of the two behaviours `FR-STORE-05` sanctions, and it is the one that
        cannot lie: a caller that is blocked has demonstrably reduced its dispatch rate, whereas
        "slowing" is a promise about a duration nobody can hold. `CT-STORE-06` tells `M-ORCH` to
        read it as a throttle signal rather than a fault, which is why this raises nothing while
        the store is open.

        The writer thread is started **before** the wait, not after. Starting it afterwards
        deadlocks the first caller the moment the depth is reached: nothing would be draining
        the queue it is waiting on.
        """
        if self._broken is not None:
            # CT-STORE-11: DiskFullError is not retryable. A write queued after the halt
            # would either land on a disk that is still full or half-land on one that is not,
            # and both are the process continuing past the failure FR-STORE-10 halts on.
            raise self._broken
        if self._guard is not None:
            # Fail before the writer thread exists for a unit it must never write: the
            # Tier D name guard's rejection is of the insert itself.
            self._guard(unit.statement)
        if getattr(self._holder, "in_transaction", False):
            # F2: this thread is inside a `transaction()` body, so it holds `_write_lock` -- the
            # same lock the drain thread needs to commit anything. Waiting for backpressure to
            # clear would wait for a drain that cannot start, and the process hangs with no
            # timeout and no diagnostic.
            #
            # `CT-STORE-04` is the reason this is a raise rather than a docstring note: "write
            # ordering across different `enqueue_write` calls ... is not guaranteed **except
            # within one `transaction()`**" reads, naturally, as contemplating enqueues inside a
            # transaction body. It cannot mean that here -- an enqueued row is committed by the
            # *writer*, in its own transaction, so it could not be part of the caller's one even
            # if the lock allowed it. Saying so is better than deadlocking at depth 1,000 in an
            # M-ORCH bulk path.
            raise WriteThroughQueryError(
                "enqueue_write was called inside a transaction() body on the same tier. The "
                "queue commits in its own transaction, so the row could not join this one; and "
                "the body holds the write lock the queue's writer needs, so at the configured "
                "depth this call would block forever on a drain that cannot start. Write it "
                "with tx.execute() to be part of this transaction, or enqueue it after the "
                "body exits."
            )
        self._ensure_writer()
        with self._condition:
            while self._pending >= self._limits.write_queue_depth and not self._stopping:
                self._condition.notify_all()
                self._condition.wait(timeout=self._limits.writer_poll_ms / 1000)
            if self._stopping:
                raise WriteQueueClosed(
                    "the store closed while this write was waiting on backpressure; the row was "
                    "not queued and has not been written"
                )
            if self._broken is not None:
                # Re-checked after the wait, not only before: `_disk_full_failure` wakes
                # waiters before halting, so the wake-up that ends this wait can be the
                # disk-full one. Appending past it would hand the caller a normal return
                # from a row the queue will never write.
                raise self._broken
            self._queue.append(unit)
            self._stamps.append(time.monotonic())
            self._pending += 1
            self._note_depth_locked()
            self._condition.notify_all()

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        """Atomic and synchronous over the whole body, within one tier (`CT-STORE-03`).

        `BEGIN IMMEDIATE` rather than a deferred begin: the write lock is already held, so taking
        the database's write lock at the same moment keeps the two in step and means a competing
        process fails at the `BEGIN` -- where `_run`'s bounded `SQLITE_BUSY` retry can see it --
        rather than partway through the body.

        Rollback on **`BaseException`**, not `Exception`. `FUZZ-07` injects its abort as a custom
        exception and a `KeyboardInterrupt` mid-transaction is exactly the "uncontrolled kill"
        `NFR-STORE-02` is about; catching only `Exception` would leave a transaction open on the
        connection for the next caller to inherit.
        """
        if self._broken is not None:
            # CT-STORE-11: the disk-full halt is terminal and not retryable.
            raise self._broken
        if self._stopping:
            # Without this a transaction on a closed store reopens the write connection and
            # commits, so `close()` refuses one write door and holds the other open.
            raise WriteQueueClosed(
                "transaction() was called on a closed store. Reopening the write connection "
                "here would commit to a tier whose handle has already been released."
            )
        with self._write_lock:
            connection = self._connect_write()
            _run(connection, _BEGIN, retries=self._limits.retries)
            self._holder.in_transaction = True
            try:
                yield Tx(connection, self._limits.retries, guard=self._guard)
            except BaseException as error:
                self._holder.in_transaction = False
                try:
                    _run(connection, _ROLLBACK, retries=self._limits.retries)
                except sqlite3.Error:
                    pass  # the transaction is already gone; the caller's exception is the news
                # A body statement can hit the out-of-space condition as surely as a batch
                # can, and `FR-STORE-10` names no door exemption: classify here too, so a
                # disk-full transaction halts instead of surfacing a retryable-looking
                # `OperationalError` from a process that kept going.
                failure = self._disk_full_failure(error)
                if failure is not None:
                    raise failure
                raise
            self._holder.in_transaction = False
            try:
                _run(connection, _COMMIT, retries=self._limits.retries)
            except sqlite3.OperationalError as error:
                # The body wrote; the commit failed. Roll back what could not be made
                # durable, then let the disk-full path decide: classify, halt, or re-raise
                # the original for anything that is not out-of-space.
                try:
                    _run(connection, _ROLLBACK, retries=self._limits.retries)
                except sqlite3.Error:
                    pass
                failure = self._disk_full_failure(error)
                if failure is not None:
                    raise failure
                raise

    def _disk_full_failure(self, error: BaseException) -> DiskFullError | None:
        """Classify `error`; on out-of-space record `DiskFullError`, break the queue, halt.

        The queue door of `FR-STORE-10`'s sequence — shared with `purge_cohort`, whose door
        has no queue state to record and calls `_as_disk_full` plus the halt hook directly.
        The caller has already rolled the interrupted work back **whole** — results and
        their paired ledger transitions together, which is what keeps `CT-STORE-03`'s
        either-both-or-neither invariant true through the failure — so what the ledger
        carries at the halt is its last committed state: no result row without its
        transition, every in-flight unit still pending, and a resume that re-dispatches
        exactly what was lost. That is the bounded loss `CT-STORE-05` names (at most one
        commit window), not a new one.

        The stronger reading of the requirement — committing the batch's `work_unit`-only
        units after the rollback — is rejected deliberately: with the results rolled back,
        committing their status transitions would manufacture status-without-result states,
        and telling the paired from the unpaired would need this module to read parameter
        values, which is schema meaning it does not own. Recorded in the file docstring's
        decision table; `TC-STORE-13` is written against this declared semantics.

        Returns `None` for anything that is not out-of-space, so the caller re-raises the
        original unchanged. Returns the `DiskFullError` only when the halt hook returned —
        which happens only under an injected (test) hook; the production hook ends the
        process and this never returns.
        """
        failure = _as_disk_full(error)
        if failure is None:
            return None
        self._failures.append(failure)
        self._broken = failure
        with self._condition:
            # Wake anything blocked on backpressure: the queue is done, and a caller waiting
            # to enqueue must hit the broken state rather than wait out a drain that will
            # never come.
            self._condition.notify_all()
        self._halt(failure)  # never returns in production; see `DiskFullError`
        return failure

    # -- the writer side -----------------------------------------------------------------------

    def _ensure_writer(self) -> None:
        with self._condition:
            if self._thread is not None or self._stopping:
                return
            thread = threading.Thread(
                target=self._drain_forever, name="aeh-store-writer", daemon=True
            )
            # Started **inside** the lock, and published only once started. Publishing first and
            # starting after left a window in which `close()` read the attribute and called
            # `join()` on a thread that had not begun: `RuntimeError: cannot join thread before
            # it is started`. A shutdown racing a first `enqueue_write` is the ordinary shape of
            # a cancelled run, not an exotic one.
            thread.start()
            self._thread = thread

    def _note_depth_locked(self) -> None:
        """Track how long depth has been at or above the threshold. Call under `_condition`."""
        if self._pending >= self._limits.write_queue_depth:
            if self._over_since is None:
                self._over_since = time.monotonic()
        else:
            self._over_since = None

    def _next_batch(self) -> list[WriteUnit] | None:
        """The next batch to commit, or `None` once the queue is stopped and empty.

        `FR-STORE-04`'s "at most 100 results or 5 seconds, whichever comes first" is two
        conditions on one queue, and both are checked here so one place decides. The age is the
        age of the **oldest** pending row, which is what makes the interval a durability bound:
        `NFR-STORE-02` promises at most one commit window of results is lost, and a window
        measured from the newest row would never close under steady load.
        """
        poll = self._limits.writer_poll_ms / 1000
        with self._condition:
            while True:
                if self._queue:
                    oldest_age_ms = (time.monotonic() - self._stamps[0]) * 1000.0
                    due = (
                        len(self._queue) >= self._limits.commit_batch
                        or oldest_age_ms >= self._limits.commit_interval_ms
                        or self._stopping
                    )
                    if due:
                        take = min(len(self._queue), self._limits.commit_batch)
                        batch = [self._queue.popleft() for _ in range(take)]
                        for _ in range(take):
                            self._stamps.popleft()
                        # `_pending` is untouched here: these rows are still not durable, only
                        # somewhere else. It drops in `_commit`'s `finally`, which is what keeps
                        # `depth` from dipping through the gap between the deque and the COMMIT.
                        self._note_depth_locked()
                        # Wake anyone blocked on backpressure: the depth just dropped.
                        self._condition.notify_all()
                        return batch
                elif self._stopping:
                    return None
                self._condition.wait(timeout=poll)

    def _drain_forever(self) -> None:
        while True:
            if self._broken is not None:
                # The halt hook returned (an injected, test-only hook) or broke the queue
                # from another thread: stop draining. FR-STORE-10's point is that the
                # process never continues with partial writes, and a drain that committed
                # the *next* batch after classifying a disk-full failure would be doing
                # exactly that.
                return
            batch = self._next_batch()
            if batch is None:
                return
            self._commit(batch)

    def _commit(self, batch: list[WriteUnit]) -> None:
        """One batch, one transaction, one latency measurement.

        A failure is **recorded, not swallowed**. The rows are already off the queue, so a writer
        that logged and moved on would let `write_queue_depth` reach zero with the rows gone -- a
        drain reporting success against data that was never written, which is the silent-failure
        trap `CLAUDE.md` seam 4 names. `close()` re-raises the first one and `store_metrics`
        counts them.

        A **disk-full** failure is the one kind that does more than record: the batch was
        rolled back whole in the `with` block below, and `_disk_full_failure` then records
        `DiskFullError`, makes the queue terminally refuse, and halts the process
        (`FR-STORE-10`). In production the halt never returns, so the `finally` bookkeeping
        after it does not run — the depth counter and the latency are left wherever the
        failure found them, which costs a dead process nothing. Under an injected (test)
        hook the bookkeeping completes and the drain loop stops on the broken state.
        """
        started = time.perf_counter()
        try:
            with self._write_lock:
                connection = self._connect_write()
                _run(connection, _BEGIN, retries=self._limits.retries)
                try:
                    for unit in batch:
                        _run(connection, unit.statement, unit.params,
                             retries=self._limits.retries)
                except BaseException:
                    try:
                        _run(connection, _ROLLBACK, retries=self._limits.retries)
                    except sqlite3.Error:
                        pass
                    raise
                _run(connection, _COMMIT, retries=self._limits.retries)
        except BaseException as error:  # noqa: BLE001 -- recorded; see the docstring
            failure = self._disk_full_failure(error)
            if failure is None:
                self._failures.append(error)
        finally:
            # Measured even on failure: a batch that took four seconds to fail is the number an
            # operator needs, and `NFR-STORE-02`'s window is about elapsed time, not success.
            self._last_latency_ms = (time.perf_counter() - started) * 1000.0
            with self._condition:
                self._pending -= len(batch)
                self._note_depth_locked()
                self._condition.notify_all()

    # -- lifecycle ------------------------------------------------------------------------------

    def close(self, *, timeout_s: float = 30.0) -> None:
        """Flush what is queued, stop the thread, then re-raise the first write failure.

        Flush rather than discard: `close()` is the controlled shutdown, and the bounded loss
        `NFR-STORE-02` permits is the loss to an *uncontrolled* kill. Dropping queued rows on a
        clean close would make the two indistinguishable.
        """
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout_s)
        if self._failures:
            raise self._failures[0]


class SqliteTierHandle:
    """One tier's database. `query`, `enqueue_write`, `transaction` — and nothing else.

    The member list is `CT-STORE-01`'s and it is closed on purpose: `FUZZ-07`'s docstring records
    an earlier draft that reached for `handle.has_result()` and `handle.status()`, which would
    have added two members to a protocol the design deliberately shuts. Anything a caller needs
    is a declared statement through `query`.
    """

    __slots__ = (
        "_connection", "_extra_readers", "_limits", "_local", "_opened", "_owner_thread",
        "_path", "_queue", "_read_only", "_retries", "_write_connection",
    )

    def __init__(self, connection: sqlite3.Connection, opened: TierOpened, *,
                 path: Path, limits: StoreLimits | None = None,
                 retries: int | None = None) -> None:
        self._connection = connection
        self._opened = opened
        self._read_only = opened.read_only
        self._path = path
        limits = limits if limits is not None else StoreLimits()
        if retries is not None:
            limits = replace(limits, retries=retries)
        self._limits = limits
        self._retries = limits.retries
        self._write_connection: sqlite3.Connection | None = None
        # One read connection per thread. `CT-STORE-04` promises concurrent readers never block
        # the writer, and sqlite3 refuses a connection used off its creating thread at all --
        # `ProgrammingError`, before SQLite is even reached. Passing `check_same_thread=False` and
        # sharing one connection would silence that check and put every reader behind the GIL and
        # behind each other's cursors, which is "readers block readers" wearing the right answer's
        # clothes. Under WAL a per-thread connection holds no lock the writer needs, which is the
        # property the requirement is actually about.
        self._local = threading.local()
        self._extra_readers: list[sqlite3.Connection] = []
        self._owner_thread = threading.get_ident()
        # No queue on a read-only handle, and no lazy one either. `FR-STORE-13` opens a Tier P
        # database to inspect a package *before* it is trusted, so the write path must be absent
        # rather than merely unused -- a queue that existed and refused later is a queue that
        # could open a connection and move the file's mtime while refusing.
        #
        # The tier write guard exists only on Tier D (`FR-STORE-12`: reject a student-name
        # insert) — the other tiers have no guard, because the requirement is about the one
        # tier that is permanent and pseudonymized, not about SQL in general.
        guard = None if opened.tier is not Tier.DURABLE else _reject_tier_d_student_name_insert
        self._queue: WriteQueue | None = (
            None if self._read_only
            else WriteQueue(self._open_write_connection, limits, guard=guard)
        )

    # -- the read connections ------------------------------------------------------------------

    def _read_connection(self) -> sqlite3.Connection:
        """This thread's read connection, opened on first use.

        The connection `_open_tier` built is this handle's own and stays the one the constructing
        thread uses -- it is the one migrations ran on and the one `TierOpened` describes. Every
        other thread gets its own, recorded in `_extra_readers` so `close()` can reach it: a
        connection nothing closes is, on Windows, a file `purge_cohort` cannot delete.
        """
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            return existing
        connection = _connect(
            self._path, read_only=self._read_only,
            busy_timeout_ms=self._limits.busy_timeout_ms, retries=self._limits.retries,
            # Used by exactly one thread -- the one this branch just created it for -- so the
            # WAL argument above is untouched. The flag is off because `close()` runs on a
            # *different* thread, and with the check on it raised `ProgrammingError` there,
            # aborting the loop and leaving every later reader and the handle's own connection
            # open: precisely the locked file this list exists to prevent.
            check_same_thread=False,
        )
        self._local.connection = connection
        self._extra_readers.append(connection)
        return connection

    # -- the write connection ----------------------------------------------------------------

    def _open_write_connection(self) -> sqlite3.Connection:
        """The second connection, opened on first write and kept for the handle's life.

        **Separate from the read connection, and that is `CT-STORE-04`.** Under WAL a reader
        holds no lock a writer needs, so two connections is what makes "concurrent readers never
        block the writer" a property of the database rather than of a mutex this module happens
        to release often enough.

        `check_same_thread=False` because two threads legitimately use it -- the drain thread for
        batches, the caller's thread for a `transaction()` body -- and `WriteQueue._write_lock`
        is what keeps them from doing so at once. The flag disables sqlite3's own thread check;
        it does not make the connection safe on its own, and the lock is not decoration.

        `journal_mode` is not set here: WAL lives in the file header, `_open_tier` wrote it, and
        this connection inherits it. `foreign_keys` is the opposite -- per connection, never
        persisted -- so `_connect` setting it is exactly what `FR-STORE-14` needs, since this is
        the connection that actually issues every write `CT-STORE-13` promises will fail.
        """
        if self._write_connection is None:
            self._write_connection = _connect(
                self._path, read_only=False, busy_timeout_ms=self._limits.busy_timeout_ms,
                retries=self._limits.retries, check_same_thread=False,
            )
        return self._write_connection

    def _refuse_read_only(self, door: str) -> None:
        if self._read_only:
            raise ReadOnlyTierError(
                f"{door} was called on a read-only handle for {self._path.name}. FR-STORE-13 "
                "opens a Tier P database read-only so an imported package can be inspected "
                "before it is trusted, and a write through that handle would alter the file "
                "whose provenance is the question."
            )

    @property
    def opened(self) -> TierOpened:
        """What opening this database did. Read-only; see `TierOpened`."""
        return self._opened

    def query(self, statement: Statement, **params: Any) -> Sequence[Row]:
        """Run a declared **read** and return its rows.

        **No order is promised** (`CT-STORE-18`): rows come back in whatever order SQLite
        produces, and a caller needing an order states it in the statement. Nothing here sorts,
        because a module that sorted would make every caller's unstated assumption work until the
        day it did not.

        **A write through here is refused**, and that is not tidiness. The connection is in
        autocommit, so before this guard `query(Statement("INSERT ..."))` wrote and committed
        synchronously — review used exactly that to seed every fixture it needed.
        `CT-STORE-02` makes writing *asynchronous*, through `enqueue_write`; a synchronous write
        channel wearing the name `query` is the contract violation that clause exists to prevent.
        Today it is the only write path there is, so every caller written before #11 lands would
        be written against it. `TC-STORE-C01` says the closed member list matters *"because it is
        the door through which every other clause here gets bypassed"* — this is that door, one
        level below the member list.

        The test is the statement's first keyword. Reads are `SELECT`, `WITH`, `VALUES`,
        `EXPLAIN` and `PRAGMA` — `PRAGMA` because schema introspection is how a caller inspects an
        imported package (`FR-STORE-13`) and how `TC-STATS-C18` sweeps Tier D for a name column.
        It is a keyword check and not a parser: it stops a caller reaching for the wrong method,
        which is the only thing that needs stopping, because every caller is in-process trusted
        code and there is no untrusted path into a statement.
        """
        declared = statement if isinstance(statement, Statement) else Statement(statement)
        _refuse_write(declared)
        return _run(self._connection_for_this_thread(), declared, params,
                    retries=self._retries).fetchall()

    def _connection_for_this_thread(self) -> sqlite3.Connection:
        """`_connection` on the thread that opened the handle, a private one on any other.

        Compared by thread identity rather than by trying the connection and catching
        `ProgrammingError`: a probe would be a second `execute()` in this module, and
        `KNOWN_EXECUTE_SITES` in `tests/artifact/test_store_query_surface.py` is an exact set for
        the good reason that every site is somewhere a statement reaches SQLite.
        """
        if threading.get_ident() == self._owner_thread:
            return self._connection
        return self._read_connection()

    def enqueue_write(self, unit: WriteUnit | Statement | str, /, **params: Any) -> None:
        """Queue one write and return. **Asynchronous** (`CT-STORE-02`).

        Returns before the row is durable, and that is the clause design 3.3 calls "the single
        most load-bearing clause in this contract and the easiest to get wrong". A caller that
        must observe its own write reads through `transaction()` or waits for the commit batch;
        nothing here waits on its behalf.

        **Two accepted forms, because the design and the suite disagree.** 3.3's Interfaces block
        types the parameter `WriteUnit`; every merged case calls
        `enqueue_write(statement, **params)`. Both work: a `WriteUnit` is used as given, and a
        statement plus keywords is packed into one. Supporting only the declared form would break
        four merged files including a P0; supporting only the convenience form would drop the
        signature the design states. The gap is reported against the design rather than resolved
        by picking a side.

        Blocks at the configured depth (`FR-STORE-05`) -- see `WriteQueue.enqueue`.

        **The Tier D guard rejects before queueing** (`FR-STORE-12`): an insert naming a
        student-name column raises `StudentNameInTierDError` from this call, synchronously.
        The asynchrony above is about durability, not about accepting writes that must never
        land.
        """
        self._refuse_read_only("enqueue_write")
        if isinstance(unit, WriteUnit):
            if params:
                raise TypeError(
                    "enqueue_write got both a WriteUnit and keyword parameters. The unit already "
                    "carries its params; passing both leaves it ambiguous which wins."
                )
            queued = unit
        else:
            declared = unit if isinstance(unit, Statement) else Statement(unit)
            queued = WriteUnit(statement=declared, params=params)
        assert self._queue is not None  # guaranteed by _refuse_read_only above
        self._queue.enqueue(queued)

    def transaction(self) -> ContextManager[Tx]:
        """Atomic, synchronous, whole-body, within one tier (`CT-STORE-03`).

        Within **one tier handle**. Cross-tier atomicity is deliberately not provided, and a
        caller needing a row in Tier C and a row in Tier D together does not get it from here --
        `CT-STORE-03` says so, and two databases cannot be committed atomically without a
        transaction manager this design rejects along with the server process.
        """
        self._refuse_read_only("transaction")
        assert self._queue is not None  # guaranteed by _refuse_read_only above
        return self._queue.transaction()

    @property
    def metrics(self) -> dict[str, Any]:
        """This tier's share of `CT-STORE-17`'s signals. Aggregated by `store_metrics`."""
        queue = self._queue
        return {
            "write_queue_depth": 0 if queue is None else queue.depth,
            "batch_commit_latency_ms": 0.0 if queue is None else queue.last_commit_latency_ms,
            "backpressure_active": False if queue is None else queue.backpressure_active,
            "queue_depth_sustained": False if queue is None else queue.sustained_over_threshold(),
            "write_failures": 0 if queue is None else len(queue.failures),
            "database_file_bytes": self._path.stat().st_size if self._path.exists() else 0,
        }

    def close(self) -> None:
        """Flush the queue, then close both connections.

        The queue closes **first**: it is still holding rows bound for the write connection, and
        closing that connection out from under a batch mid-flight is how a clean shutdown starts
        losing the writes an uncontrolled kill was supposed to be the only thing that loses.
        """
        if self._queue is not None:
            try:
                self._queue.close()
            finally:
                if self._write_connection is not None:
                    self._write_connection.close()
                    self._write_connection = None
        # Every one of them, even if one raises. A loop that stopped at the first failure would
        # leave the rest open while reporting the problem, which on Windows is a file
        # `purge_cohort` cannot delete -- the failure this list exists to prevent, reached by the
        # cleanup rather than by the absence of one.
        for reader in self._extra_readers:
            try:
                reader.close()
            except sqlite3.Error:
                pass
        self._extra_readers.clear()
        self._connection.close()


# --- the store ---------------------------------------------------------------------------------


class SqliteStore:
    """`Store` over a data directory. One file per package, one per cohort, one shared durable.

    Handles are cached per id, so two calls to `cohort("c-1")` return one handle over one
    connection. That matters more than it looks: `CT-STORE-04` promises readers never observe a
    partially applied transaction, and two connections to one file would make "the writer" a
    matter of which handle a caller happened to hold.
    """

    __slots__ = (
        "_busy_timeout_ms", "_data_dir", "_handles", "_last_vacuum_ms", "_limits", "_opened",
        "_read_only", "_retries",
    )

    def __init__(self, data_dir: Path, *, busy_timeout_ms: int | None = None,
                 retries: int | None = None, limits: StoreLimits | None = None,
                 read_only: bool = False) -> None:
        self._read_only = read_only
        if limits is None:
            limits = StoreLimits()
        if busy_timeout_ms is not None:
            limits = replace(limits, busy_timeout_ms=busy_timeout_ms)
        if retries is not None:
            limits = replace(limits, retries=retries)
        self._limits = limits
        self._data_dir = data_dir
        self._busy_timeout_ms = limits.busy_timeout_ms
        self._retries = limits.retries
        self._handles: dict[tuple[Tier, str, bool], SqliteTierHandle] = {}
        self._opened: list[TierOpened] = []
        # The last `purge_cohort`'s VACUUM duration, honestly 0.0 until one runs — the
        # CT-STORE-17 signal `store_metrics` reports.
        self._last_vacuum_ms = 0.0

    # -- layout, verbatim from §3.3's data model ------------------------------------------------

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def limits(self) -> StoreLimits:
        """The knob values this store was constructed with. See `StoreLimits`."""
        return self._limits

    def package_path(self, package_id: str) -> Path:
        return self._data_dir / "packages" / f"{package_id}.pkg.sqlite"

    def cohort_path(self, cohort_id: str) -> Path:
        return self._data_dir / "cohorts" / f"{cohort_id}.sqlite"

    def durable_path(self) -> Path:
        return self._data_dir / "durable.sqlite"

    @property
    def opened(self) -> tuple[TierOpened, ...]:
        """One record per database this store has opened, in the order it opened them."""
        return tuple(self._opened)

    # -- the three handle kinds ------------------------------------------------------------------

    def _handle(self, tier: Tier, key: str, path: Path, *, read_only: bool) -> SqliteTierHandle:
        cached = self._handles.get((tier, key, read_only))
        if cached is not None:
            return cached
        # One file, one mode. Review measured the alternative: with both cached, two connections
        # were live on one package and the read-only handle observed the writable one's migration
        # — so "inspect an imported package before it is trusted" (`FR-STORE-13`) was inspecting a
        # file this same process had just changed. Refusing is the honest answer: the two modes
        # answer different questions, and holding both at once means neither answer is the one the
        # caller thinks it has.
        conflict = self._handles.get((tier, key, not read_only))
        if conflict is not None:
            raise ConfigurationProblem(
                f"{path} is already open {'read-write' if read_only else 'read-only'} in this "
                f"store. FR-STORE-13's read-only handle exists to inspect a file whose "
                f"provenance is in question, and a writable handle on the same file in the same "
                f"process is what makes that inspection meaningless. Close the store, or inspect "
                f"through the handle you already hold."
            )
        connection, opened = _open_tier(
            path, tier, read_only=read_only, busy_timeout_ms=self._busy_timeout_ms,
            retries=self._retries,
        )
        handle = SqliteTierHandle(connection, opened, path=path, limits=self._limits)
        self._handles[(tier, key, read_only)] = handle
        self._opened.append(opened)
        return handle

    def package(self, package_id: str, *, read_only: bool | None = None) -> SqliteTierHandle:
        """Tier P — one file per package, permanent, no PII by construction.

        `read_only=True` is `FR-STORE-13`: an imported package is inspected *before* it is
        trusted, and inspecting it through a writable handle would let the inspection itself
        migrate a file whose provenance is exactly what is in question.
        """
        return self._handle(
            Tier.PACKAGE, package_id, self.package_path(package_id),
            read_only=self._read_only if read_only is None else read_only,
        )

    def cohort(self, cohort_id: str) -> SqliteTierHandle:
        """Tiers C **and** R — one file, per administration, heavy PII."""
        return self._handle(
            Tier.COHORT, cohort_id, self.cohort_path(cohort_id), read_only=self._read_only
        )

    def durable(self) -> SqliteTierHandle:
        """Tier D — one shared file, permanent, pseudonymized."""
        return self._handle(Tier.DURABLE, "", self.durable_path(), read_only=self._read_only)

    # -- the two surfaces later stories fill in ---------------------------------------------------

    def blobs(self) -> BlobStore:
        """Content-addressed blob directory (`FR-STORE-06`). **#12.**"""
        raise NotImplementedError(
            "Store.blobs is issue #12 (FR-STORE-06: content-addressed on SHA-256, deduplicating "
            "identical content). The directory is created by open_store so #12 adds a store "
            "rather than a layout."
        )

    def purge_cohort(self, cohort_id: str) -> PurgeReport:
        """Delete Tiers C and R and `VACUUM` (`FR-STORE-07`, `CT-STORE-10`).

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
        - Blobs are **not** touched (`PurgeReport.blobs_deleted` is an honest zero): the
          dedup-vs-purge rule is undeclared (test plan §7.4) and the blob store is #12's.
        - On a read-only store this raises `ReadOnlyTierError` — a purge is a write by any
          definition that matters.

        A purge that fails partway (say, `VACUUM` cannot get its temp copy) has already
        committed its deletes; re-running it completes the vacuum — the tables are empty and
        the preconditions still hold.
        """
        if self._read_only:
            raise ReadOnlyTierError(
                f"purge_cohort was called on a read-only store for cohort {cohort_id!r}. A "
                "purge is a write by any definition that matters — it is the one operation "
                "that deletes student work — and FR-STORE-13's read-only entry exists to "
                "inspect without touching."
            )
        missing = self._purge_precondition_failures(cohort_id)
        if missing:
            raise PurgePreconditionError(
                f"cohort {cohort_id!r} is not promoted to Tier D (FR-STORE-07, CT-STORE-10); "
                f"nothing was deleted. Unmet gates: {'; '.join(missing)}. Promotion is "
                f"M-STATS/M-REVIEW's promote; the gates check Tier D's audit_record, label "
                f"and criterion_stats tables, scoped by cohort_id."
            )

        path = self.cohort_path(cohort_id)
        handle = self._handles.pop((Tier.COHORT, cohort_id, False), None)
        if handle is not None:
            handle.close()  # flush queued writes; a failure propagates — nothing deleted

        rows: dict[str, int] = {}
        vacuum_ms = 0.0
        bytes_before = path.stat().st_size if path.exists() else 0
        bytes_after = bytes_before
        tables_cleared: tuple[str, ...] = ()
        if path.exists():
            tables_cleared = tuple(_COHORT_PURGE_ORDER)
            connection = _connect(
                path, read_only=False, busy_timeout_ms=self._busy_timeout_ms,
                retries=self._retries,
            )
            try:
                try:
                    # Before the BEGIN, deliberately: SQLite makes `defer_foreign_keys` a
                    # no-op inside a transaction, and it resets at the end of the next one
                    # — this is exactly the shape it exists for.
                    _run(connection, _PRAGMA_DEFER_FOREIGN_KEYS, retries=self._retries)
                    _run(connection, _BEGIN, retries=self._retries)
                    found = {
                        str(row[0])
                        for row in _run(
                            connection, _SELECT_COHORT_TABLES, retries=self._retries
                        ).fetchall()
                    }
                    unknown = sorted(
                        table for table in found
                        if not table.startswith("sqlite_")
                        and table != _SCHEMA_VERSION_TABLE_NAME
                        and table not in _PURGE_DELETES
                    )
                    if unknown:
                        # Fail closed, before the first DELETE: a table purge cannot name is
                        # student text it would leave behind. See the purge section's comment.
                        raise ConfigurationProblem(
                            f"{path} declares schema object(s) this purge does not "
                            f"recognize: {unknown}. FR-STORE-07 removes Tiers C and R "
                            "*content*, and a name the purge's registry lacks is student "
                            "text it would leave behind — purge refuses rather than "
                            "half-purge. A migration extending the cohort tier must extend "
                            "_PURGE_DELETES in the same change. Nothing was removed."
                        )
                    for table in _COHORT_PURGE_ORDER:
                        cursor = _run(connection, _PURGE_DELETES[table], retries=self._retries)
                        count = cursor.rowcount
                        rows[table] = count if count is not None and count >= 0 else 0
                    _run(connection, _COMMIT, retries=self._retries)
                except BaseException as error:
                    try:
                        _run(connection, _ROLLBACK, retries=self._retries)
                    except sqlite3.Error:
                        pass
                    # Disk-full at a DELETE or the COMMIT: classify and halt here too —
                    # FR-STORE-10 names no door exemption, and a raw OperationalError from
                    # a purge would look retryable to a caller on a disk that cannot
                    # recover until the run stops.
                    _halt_if_disk_full(error)
                    raise
                try:
                    started = time.perf_counter()
                    _run(connection, _VACUUM, retries=self._retries)
                    vacuum_ms = (time.perf_counter() - started) * 1000.0
                    # The vacuum's freed pages — with the student text in them — sit in the
                    # -wal until a checkpoint reclaims them. Truncate it now, while this
                    # connection is open, rather than rely on close() being the last close.
                    _run(connection, _PRAGMA_WAL_CHECKPOINT_TRUNCATE, retries=self._retries)
                except BaseException as error:
                    _halt_if_disk_full(error)
                    raise
            finally:
                connection.close()
                # The dedicated connection recreated the -wal/-shm siblings under the
                # process umask; tighten all three again (no-op on Windows).
                _harden_files(path)
            bytes_after = path.stat().st_size

        self._last_vacuum_ms = vacuum_ms
        return PurgeReport(
            cohort_id=cohort_id,
            preconditions_verified=tuple(name for name, _table in _PURGE_PRECONDITIONS),
            tables_cleared=tables_cleared,
            rows_deleted_by_table=rows,
            file_bytes_before=bytes_before,
            file_bytes_after=bytes_after,
            vacuum_duration_ms=vacuum_ms,
        )

    def _purge_precondition_failures(self, cohort_id: str) -> list[str]:
        """The unmet Tier D promotion gates for `cohort_id`; empty when purge may run.

        A gate (`CT-STORE-10`'s three, in its words) passes iff Tier D holds the table, the
        table carries the `cohort_id` scoping column, and the table holds a row for this
        cohort. Fail-**closed** on all three: a table that does not exist or does not carry
        the column is one promotion structurally cannot have written — #10's minimal Tier D
        columns carry no cohort scope, so the scoping column arrives only when the owning
        module's migration adds it, which is what "promoted" means here. Anything weaker —
        nonempty tables regardless of cohort, say — would let one cohort's promotion unlock
        purging another, and `CT-STORE-10`'s sweep is per-precondition for exactly that
        reason.
        """
        durable = self.durable()
        missing: list[str] = []
        for name, table in _PURGE_PRECONDITIONS:
            columns = {str(row[1]) for row in durable.query(_PURGE_TABLE_INFO[table])}
            if "cohort_id" not in columns:
                missing.append(
                    f"{name} — Tier D's {table!r} does not carry the cohort_id scoping column"
                )
                continue
            count = durable.query(_PURGE_PROMOTED_ROWS[table], cohort_id=cohort_id)[0][0]
            if not count:
                missing.append(f"{name} — no {table} rows for cohort {cohort_id!r} in Tier D")
        return missing

    # -- lifecycle ---------------------------------------------------------------------------------

    def close(self) -> None:
        """Close every handle, then report the first write failure any of them recorded.

        Every handle is closed even if one raises. A store that abandoned the remaining tiers on
        the first bad one would leave open connections behind while reporting the failure, and on
        Windows an open connection is a file nothing else can delete -- which is how `close()`
        starts breaking `purge_cohort` rather than merely reporting a problem.
        """
        first: BaseException | None = None
        for handle in self._handles.values():
            try:
                handle.close()
            except BaseException as error:  # noqa: BLE001 -- re-raised below, after every close
                first = first if first is not None else error
        self._handles.clear()
        if first is not None:
            raise first

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def open_store(data_dir: Path | str | None = None, *, read_only: bool = False,
               environ: Mapping[str, str] | None = None) -> SqliteStore:
    """Open the store rooted at `data_dir`, or at `HARNESS_DATA_DIR` when none is given.

    Positional **and** by keyword, because both forms are already in the suite:
    `open_store(tmp_data_dir)` in `TC-CONF-17` and `FUZZ-07`, `open_store(data_dir=tmp_data_dir)`
    in `TC-STATS-C18`. §3.3's Interfaces block names no constructor at all, so the name and the
    signature are this module's — recorded in the file docstring rather than left to be inferred.

    Nothing is opened here. The three directories are created and the store is returned; each
    database opens on the first call to `package()`, `cohort()` or `durable()`, which is what
    keeps `NFR-STORE-03`'s "no installation step" true — a store constructed against a fresh
    directory has created no `durable.sqlite` a caller never asked for.

    The location is checked **before the first directory is created** (`FR-STORE-09`): a data
    directory that resolves inside a world-writable path raises `InsecureLocationError` and
    creates nothing. The directories are then created and explicitly hardened to
    `OWNER_ONLY_DIR` — `mkdir`'s mode argument is filtered through the umask, so the `chmod`
    is the part that actually holds on POSIX (no-op on Windows; see `_harden_dir`).

    `read_only=True` makes **every** handle this store hands out read-only. `FR-STORE-13` is
    written about Tier P, and `package(id, read_only=True)` remains the narrow form — but the
    situation the requirement describes is inspecting an untrusted import, and a store that
    refused to write the package while happily migrating `durable.sqlite` on the way past would
    have modified the data directory during the very session that was supposed to leave no trace.
    The flag is the whole-store form of the same promise, and `TC-STORE-16` opens it this way.
    """
    root = Path(data_dir).expanduser() if data_dir is not None else data_dir_from_environment(
        environ
    )
    root = root.resolve()
    # The refusal resolves symlinks itself (`realpath`), so a data directory that is a
    # symlink pointing into /tmp is judged by where it lands. Running it before the mkdir
    # loop is what makes "refuses to start, nothing created" a property of the control flow.
    _refuse_insecure_location(root)
    for child in (root, root / "packages", root / "cohorts", root / "blobs"):
        child.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)
        _harden_dir(child)

    return SqliteStore(
        root, limits=StoreLimits.from_environment(environ), read_only=read_only
    )


# --- observability -------------------------------------------------------------------------------


def store_metrics(store: SqliteStore) -> dict[str, Any]:
    """`CT-STORE-17`'s five signals, the two alerts, and the configured values behind them.

    *"Emits write-queue depth, batch commit latency, database file sizes, free disk space, and
    `VACUUM` duration under those names. Free-disk and queue-depth are alert inputs and their
    semantics are contract."* Design 3.3 names them in prose and fixes no spelling, so the
    spelling is here and the gap is reported against the design.

    A **function**, not a `Store` member, and deliberately: `CT-STORE-01` closes `Store` to
    `package`, `cohort`, `durable`, `blobs` and `purge_cohort`, and `TC-STORE-C01` calls that
    closed member list "the door through which every other clause here gets bypassed". Adding a
    sixth method to read metrics would open exactly that door for the most innocuous-looking
    reason there is.

    **`database_file_bytes` is a mapping, not a scalar.** The tiers have different lifetimes --
    Tier D is permanent, C and R are purged together -- so one aggregate number cannot answer
    "which tier is growing", which is the only question the signal exists to answer.

    **`vacuum_duration_ms` is honestly zero until a `VACUUM` runs.** The only one this module
    performs is `purge_cohort`'s, and the store records the last measured duration — so the
    signal is a real measurement of the last purge, not an invention, and zero means "no
    purge has run in this process".
    """
    depth = 0
    latency_ms = 0.0
    failures = 0
    backpressure = False
    sustained = False
    sizes: dict[str, int] = {}

    for (tier, key, _read_only), handle in store._handles.items():  # noqa: SLF001
        share = handle.metrics
        depth += int(share["write_queue_depth"])
        latency_ms = max(latency_ms, float(share["batch_commit_latency_ms"]))
        failures += int(share["write_failures"])
        backpressure = backpressure or bool(share["backpressure_active"])
        sustained = sustained or bool(share["queue_depth_sustained"])
        # Keyed per open tier, so "which tier is growing" is answerable. `TC-STORE-24` reads
        # `durable` and a key beginning `cohort`; the id is carried too, because two cohorts in
        # one run are two files and an aggregate over them answers nothing.
        label = tier.value if not key else f"{tier.value}:{key}"
        sizes[label] = int(share["database_file_bytes"])

    limits = store.limits
    free_bytes = shutil.disk_usage(store.data_dir).free

    firing: list[str] = []
    # A projection of zero means "M-ORCH stated no remaining-run requirement". An alert with no
    # projection behind it stays quiet rather than inventing a threshold -- an always-on alert is
    # worth exactly what an always-off one is worth.
    if limits.projected_run_bytes > 0 and free_bytes < limits.projected_run_bytes:
        firing.append(ALERT_FREE_DISK)
    if sustained:
        firing.append(ALERT_QUEUE_DEPTH)

    return {
        # -- the five CT-STORE-17 signals ------------------------------------------------------
        "write_queue_depth": depth,
        "batch_commit_latency_ms": latency_ms,
        "database_file_bytes": sizes,
        "free_disk_bytes": free_bytes,
        "vacuum_duration_ms": float(store._last_vacuum_ms),  # noqa: SLF001 -- module-internal
        # -- the alerts, declared and firing ---------------------------------------------------
        "alerts_declared": list(DECLARED_ALERTS),
        "alerts_firing": firing,
        # -- FR-STORE-05's level, which M-ORCH throttles on (CT-STORE-06, FR-ORCH-21) ----------
        "backpressure_active": backpressure,
        # -- what the knobs resolved to, so a caller can tell a boundary from a default --------
        "configured_queue_depth": limits.write_queue_depth,
        "configured_commit_batch": limits.commit_batch,
        "configured_commit_interval_ms": limits.commit_interval_ms,
        "configured_projected_run_bytes": limits.projected_run_bytes,
        # -- writes the queue accepted and could not commit. Zero is the only healthy value ----
        "write_failures": failures,
    }


# --- the declared-statement registry (FR-STORE-08) ---------------------------------------------
#
# `STATEMENTS` is where the module's runtime statements live as a set, and it is what makes
# "the store interface offers keyed lookup and declared queries only" checkable rather than
# merely true: `TC-STORE-15`'s second limb sweeps every entry for the SQL shapes that search
# (`LIKE`, `GLOB`, `MATCH`, FTS and vector modules, `REGEXP`), and `CT-STORE-08` is a safety
# property — a search capability added through a new statement is a contract breach this
# registry makes visible in one place.
#
# **Every non-migration statement the module executes is registered here.** A new statement
# added without registering it is a statement the no-search sweep cannot see, which is the
# exact hole the registry exists to close. Migration DDL is the one deliberate exclusion: it
# is versioned data in `TIER_MIGRATIONS` (a CREATE TABLE cannot search), and the schema limb
# of `TC-STORE-15` sweeps the real files for FTS virtual tables anyway.
#
# Every entry today is free of the search shapes; the registry's own first entry rule is that
# it stays that way.

STATEMENTS: Mapping[str, Statement] = {
    # -- schema-version bookkeeping (the migration machinery) ---------------------------------
    "create_schema_version_table": _SCHEMA_VERSION_TABLE,
    "select_applied_versions": _SELECT_APPLIED_VERSIONS,
    "select_schema_version_table": _SELECT_SCHEMA_VERSION_TABLE,
    "insert_version": _INSERT_VERSION,
    # -- connection pragmas and transaction control -------------------------------------------
    "pragma_foreign_keys_on": _PRAGMA_FOREIGN_KEYS_ON,
    "pragma_foreign_keys": _PRAGMA_FOREIGN_KEYS,
    "pragma_journal_wal": _PRAGMA_JOURNAL_WAL,
    "pragma_journal_mode": _PRAGMA_JOURNAL_MODE,
    "pragma_defer_foreign_keys": _PRAGMA_DEFER_FOREIGN_KEYS,
    "begin": _BEGIN,
    "commit": _COMMIT,
    "rollback": _ROLLBACK,
    # -- purge (FR-STORE-07) --------------------------------------------------------------------
    "select_cohort_tables": _SELECT_COHORT_TABLES,
    "vacuum": _VACUUM,
    "wal_checkpoint_truncate": _PRAGMA_WAL_CHECKPOINT_TRUNCATE,
    "table_info_audit_record": _PURGE_TABLE_INFO["audit_record"],
    "table_info_label": _PURGE_TABLE_INFO["label"],
    "table_info_criterion_stats": _PURGE_TABLE_INFO["criterion_stats"],
    "count_promoted_audit_records": _PURGE_PROMOTED_ROWS["audit_record"],
    "count_promoted_labels": _PURGE_PROMOTED_ROWS["label"],
    "count_promoted_criterion_stats": _PURGE_PROMOTED_ROWS["criterion_stats"],
    "purge_delete_review_queue": _PURGE_DELETES["review_queue"],
    "purge_delete_narrative": _PURGE_DELETES["narrative"],
    "purge_delete_submission_grade": _PURGE_DELETES["submission_grade"],
    "purge_delete_criterion_score": _PURGE_DELETES["criterion_score"],
    "purge_delete_verdict": _PURGE_DELETES["verdict"],
    "purge_delete_evidence": _PURGE_DELETES["evidence"],
    "purge_delete_work_unit": _PURGE_DELETES["work_unit"],
    "purge_delete_document_region": _PURGE_DELETES["document_region"],
    "purge_delete_document": _PURGE_DELETES["document"],
    "purge_delete_submission": _PURGE_DELETES["submission"],
    "purge_delete_roster": _PURGE_DELETES["roster"],
    "purge_delete_cohort": _PURGE_DELETES["cohort"],
}
