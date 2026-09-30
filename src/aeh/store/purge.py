"""Purging a cohort file once its results are promoted: order, blob references, the report."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import ConfigurationProblem
from .interfaces import Statement
from .connection import _run


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


_SELECT_COHORT_TRIGGERS_VIEWS = Statement(
    "SELECT name, type, sql FROM sqlite_master WHERE type IN ('trigger', 'view')"
)


#: The one trigger shape a purge can coexist with: a `BEFORE UPDATE` trigger whose whole
#: body is a single `SELECT RAISE(ABORT|FAIL, ...)` (a `WHEN` clause allowed in front).
#: Its event is UPDATE, so it never fires on the sweep's own DELETEs, and a RAISE-only
#: body cannot write a row — it can only refuse one. Everything else (any AFTER/DELETE/
#: AFTER trigger, a BEFORE DELETE trigger, any trigger with a write in its body, anything
#: unparseable) fails
#: closed: the purge cannot verify a shape it does not recognize. #103's append-only
#: enforcement is a cohort-tier trigger of exactly this shape (`submission_grade`'s
#: content lock); the audit trio in Tier D never meets this guard — the purge sweeps
#: Tier C, not Tier D.
def _is_pure_refusal_trigger(sql: str | None) -> bool:
    if not sql:
        return False
    flat = re.sub(r"\s+", " ", sql).strip().lower()
    header = re.match(
        r"create trigger (?:if not exists )?\S+ "
        r"(before|after|instead of) (update(?: of .+?)?|insert|delete) on ",
        flat,
    )
    if header is None or header.group(1) != "before":
        return False
    if not header.group(2).startswith(("update", "insert")):
        return False
    body = flat[header.end():]
    begin = body.find("begin")
    end = body.rfind("end")
    if begin == -1 or end == -1 or end < begin:
        return False
    body = body[begin + len("begin"):end]
    # Strip the quoted message literals before scanning for write verbs — a refusal
    # message may name the words it refuses.
    body = re.sub(r"'(?:[^']|'')*'", "''", body)
    if re.fullmatch(r" ?select raise\((abort|fail),.*; ?", body, flags=re.S) is None:
        return False
    return re.search(r"\b(insert|update|delete|replace|drop|create|attach)\b", body) is None


_PRAGMA_DEFER_FOREIGN_KEYS = Statement("PRAGMA defer_foreign_keys = ON")


#: Table-valued pragma form (#225): the FK-graph introspection purge does runs with the
#: table name as a **bound parameter**, so no identifier is ever interpolated into SQL.
_SELECT_FOREIGN_KEY_PARENTS = Statement(
    'SELECT "table" AS parent_table FROM pragma_foreign_key_list(:table)'
)


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
#: deterministic order keeps the report stable from run to run. What the order **is** load-bearing
#: for is completeness: the sweep iterates this tuple, so a name missing here is a table the
#: sweep never touches — #39's token tables sat in `_PURGE_DELETES` but out of this tuple and
#: every token-carrying cohort's purge aborted at COMMIT with a raw `IntegrityError` (#225).
_COHORT_PURGE_ORDER: tuple[str, ...] = (
    "review_queue", "narrative", "submission_grade", "criterion_score", "verdict",
    # #448 (FR-JUDGE-34): the decision-seat pre-screen rows, run state keyed on the work id.
    "decision_prescreen",
    "evidence", "work_unit", "escalation_request", "circuit_breaker", "run_control",
    # #362's per-cell composition phases: swept before `run`, like every other run-scoped
    # table, so the FK graph is walked child-first.
    "cell_phase",
    "run",
    "assessment_match_proposal", "v4_cohort_breaker",
    "unresolved_token", "token_cluster", "document_region", "document", "submission",
    # #531 (FR-CONSOLE-27): what an upload delivered — file names and blob addresses of a
    # cohort's scans, purged with the cohort.
    "upload_part",
    "roster", "cohort",
)


_PURGE_DELETES: Mapping[str, Statement] = {
    "review_queue": Statement("DELETE FROM review_queue"),
    "narrative": Statement("DELETE FROM narrative"),
    "submission_grade": Statement("DELETE FROM submission_grade"),
    "criterion_score": Statement("DELETE FROM criterion_score"),
    # #362 (FR-ORCH-28): the composition phases of the run's cells. Purged with the cohort
    # like every other run-scoped row — a phase outliving the work it describes would tell a
    # restarted pipeline to skip a cell whose evidence is gone.
    "cell_phase": Statement("DELETE FROM cell_phase"),
    "verdict": Statement("DELETE FROM verdict"),
    # #448 (FR-JUDGE-34): the decision-seat pre-screen rows — engine answers about a
    # student's work (probabilities, cited-span labels) — die with the cohort like the verdicts.
    "decision_prescreen": Statement("DELETE FROM decision_prescreen"),
    "evidence": Statement("DELETE FROM evidence"),
    "work_unit": Statement("DELETE FROM work_unit"),
    # #60's escalation bookkeeping: the queue's request rows and the breaker latch
    # reference the run (and name submissions and criteria) and are run state — they
    # die with the cohort like the run they hang from; a name the registry lacks
    # would leave the escalation's audit trail behind (FR-STORE-07).
    "escalation_request": Statement("DELETE FROM escalation_request"),
    "circuit_breaker": Statement("DELETE FROM circuit_breaker"),
    # #61's control-row queue: pause/resume requests name the run they hang from and
    # are run state — they die with the cohort like the run they address, before the
    # run row their FK points at (children before parents); a name the registry lacks
    # would leave the operator's control history behind (FR-STORE-07).
    "run_control": Statement("DELETE FROM run_control"),
    # #57's ledger tables: the run registry is run state (it names the cohort, the package
    # version and the frozen configuration) and dies with the cohort like every other Tier
    # C/R row — a name the registry lacks would leave a run's provenance behind.
    "run": Statement("DELETE FROM run"),
    "document_region": Statement("DELETE FROM document_region"),
    "document": Statement("DELETE FROM document"),
    "submission": Statement("DELETE FROM submission"),
    "roster": Statement("DELETE FROM roster"),
    # #39's cohort-tier tables: unresolved-token occurrences and their clusters are
    # cohort content (they reference documents) and are purged with the cohort — a
    # name the registry lacks would be student text left behind (FR-STORE-07).
    "unresolved_token": Statement("DELETE FROM unresolved_token"),
    "token_cluster": Statement("DELETE FROM token_cluster"),
    # #41's cohort-tier tables: the mismatch proposals carry the submission's signal
    # snapshots (student text among them) and the breaker row is the cohort's own
    # finding — both purge with the cohort, proposals before the submissions their
    # FK points at.
    "assessment_match_proposal": Statement("DELETE FROM assessment_match_proposal"),
    "v4_cohort_breaker": Statement("DELETE FROM v4_cohort_breaker"),
    # #531: the upload record names the cohort's scan files and their blobs.
    "upload_part": Statement("DELETE FROM upload_part"),
    "cohort": Statement("DELETE FROM cohort"),
}


#: A name in `_PURGE_DELETES` but not in `_COHORT_PURGE_ORDER` is a table the registry can
#: name yet the sweep never visits — exactly the rot #225 fixed, where #39's token tables
#: were added to the deletes and not to the order and the FK check at COMMIT aborted the
#: purge. Checked at import so the next migration cannot land the same rot silently; the
#: at-purge-time walk (`_assert_purge_order_matches_fk_graph`) is the live-graph half.
_UNORDERED_PURGE_TABLES: frozenset[str] = (
    frozenset(_PURGE_DELETES) - frozenset(_COHORT_PURGE_ORDER)
)


if _UNORDERED_PURGE_TABLES:
    raise ConfigurationProblem(
        f"_PURGE_DELETES names entries _COHORT_PURGE_ORDER lacks: "
        f"{sorted(_UNORDERED_PURGE_TABLES)}. The sweep iterates the order tuple, so an "
        f"entry missing there is a name the sweep never visits — its rows survive and "
        f"the deferred FK check aborts at COMMIT. Extend _COHORT_PURGE_ORDER in the "
        f"same change (children before parents)."
    )


#: One declared row-scan per swept name (#225): the reclamation phase reads blob references
#: out of the cohort's rows, and `SELECT *` means a migration adding or renaming a
#: hash-bearing column needs no edit here — the scan follows the table. A name missing from
#: this registry would be a swept name whose references the reclamation never reads, which
#: is the import-time guard right below.
_PURGE_BLOB_HASH_SCANS: Mapping[str, Statement] = {
    "review_queue": Statement("SELECT * FROM review_queue"),
    "narrative": Statement("SELECT * FROM narrative"),
    "submission_grade": Statement("SELECT * FROM submission_grade"),
    "criterion_score": Statement("SELECT * FROM criterion_score"),
    "verdict": Statement("SELECT * FROM verdict"),
    # #448: no blob references (probabilities, labels, a build id), registered so a column a
    # later migration adds is read by the same walk without an edit here.
    "decision_prescreen": Statement("SELECT * FROM decision_prescreen"),
    "evidence": Statement("SELECT * FROM evidence"),
    "work_unit": Statement("SELECT * FROM work_unit"),
    # #60's escalation bookkeeping: neither table carries blob references (request
    # and breaker rows name ids, values and policy detail, never student bytes), but
    # the scan registry covers every swept name so a column a future migration adds
    # is read by the same walk without an edit here.
    "escalation_request": Statement("SELECT * FROM escalation_request"),
    # #362's `cell_phase`: ids, a phase name and a count — no blob reference and no student
    # bytes. Registered anyway, because the scan registry covers every swept name so a column
    # a later migration adds is read by the same walk without an edit here.
    "cell_phase": Statement("SELECT * FROM cell_phase"),
    "circuit_breaker": Statement("SELECT * FROM circuit_breaker"),
    # #61's control-row queue: no blob references (reason strings name conditions,
    # never student bytes), but the scan registry covers every swept name so a
    # column a future migration adds is read by the same walk without an edit here.
    "run_control": Statement("SELECT * FROM run_control"),
    "run": Statement("SELECT * FROM run"),
    "assessment_match_proposal": Statement("SELECT * FROM assessment_match_proposal"),
    "v4_cohort_breaker": Statement("SELECT * FROM v4_cohort_breaker"),
    # #531: `blob_ref` is a content address, so the blob sweep reads it.
    "upload_part": Statement("SELECT * FROM upload_part"),
    "unresolved_token": Statement("SELECT * FROM unresolved_token"),
    "token_cluster": Statement("SELECT * FROM token_cluster"),
    "document_region": Statement("SELECT * FROM document_region"),
    "document": Statement("SELECT * FROM document"),
    "submission": Statement("SELECT * FROM submission"),
    "roster": Statement("SELECT * FROM roster"),
    "cohort": Statement("SELECT * FROM cohort"),
}


#: A swept name without a row-scan is a reference the reclamation misses — student bytes
#: left behind while the report claims a purge. Import-time, so the next migration cannot
#: land the gap silently (the same doctrine as `_UNORDERED_PURGE_TABLES` above).
_UNSCANNED_PURGE_TABLES: frozenset[str] = (
    frozenset(_PURGE_DELETES) - frozenset(_PURGE_BLOB_HASH_SCANS)
)


if _UNSCANNED_PURGE_TABLES:
    raise ConfigurationProblem(
        f"_PURGE_BLOB_HASH_SCANS does not cover every name _PURGE_DELETES clears: "
        f"{sorted(_UNSCANNED_PURGE_TABLES)}. The reclamation reads blob references by "
        f"scanning each swept name's rows, so an entry missing there is a reference "
        f"purge misses — student bytes left behind. Extend the registry in the same "
        f"change."
    )


#: Any 64-hex run bounded by non-hex characters — `BLOB_HASH_PATTERN` unanchored, with
#: boundaries so a longer hex run (a SHA-512, a concatenation) yields no phantom sub-match.
#: This is what `ContentAddressedBlobStore.put` returns and therefore the shape every blob
#: reference takes, wherever a migration puts it.
_BLOB_HASH_RUN = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


#: The dump-walking variant (#225): case-insensitive, because an arbitrary-schema file's
#: hash-carrying column may be BLOB-typed and dumps as uppercase hex — and missing a real
#: reference is the unsafe direction. Binary values that happen to carry 64 hex-like bytes
#: only make purge KEEP a blob, which is the safe mistake.
_BLOB_HASH_RUN_ANYCASE = re.compile(
    r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])"
)


def _assert_purge_order_matches_fk_graph(
    connection: sqlite3.Connection, found: set[str], path: Path, *, retries: int,
) -> None:
    """Check the deletion order against the cohort file's actual foreign-key graph.

    Walks `pragma foreign_key_list` for every table the file actually carries and checks
    the result against `_COHORT_PURGE_ORDER`: every found table is IN the tuple (a name
    missing there is a table the sweep never visits — the rot that aborted every
    token-carrying cohort's purge), and every foreign key among the found tables points
    child-before-parent. Deferred FKs make the direction cosmetic for correctness — COMMIT
    sees every table empty either way — but an order that contradicts the live graph is
    the shape a half-extended registry wears, and it is refused here, before the first
    DELETE, rather than discovered as a raw `IntegrityError` at COMMIT with the sweep
    half-run. A migration adding a cohort-scoped table without the order entry fails here
    with the edge named, instead of silently rotting the purge.
    """
    order_index = {name: index for index, name in enumerate(_COHORT_PURGE_ORDER)}
    violations: list[str] = []
    for table in sorted(found):
        if table.startswith("sqlite_") or table == _SCHEMA_VERSION_TABLE_NAME:
            continue  # internals and the per-tier version marker the sweep keeps by design
        if table not in order_index:
            violations.append(
                f"{table}: in the file but not in _COHORT_PURGE_ORDER — the sweep would "
                f"never visit it"
            )
            continue
        parents = _run(connection, _SELECT_FOREIGN_KEY_PARENTS,
                       params={"table": table}, retries=retries).fetchall()
        for row in parents:
            parent = str(row[0])
            if parent == table or parent not in found:
                continue  # self-reference, or a parent absent from this (older) file
            if parent in order_index and order_index[table] >= order_index[parent]:
                violations.append(
                    f"{table} references {parent}: child at position "
                    f"{order_index[table]}, parent at {order_index[parent]}"
                )
    if violations:
        raise ConfigurationProblem(
            f"{path} has a foreign-key graph _COHORT_PURGE_ORDER does not match: "
            f"{violations}. The purge sweep iterates the order tuple, so a missing name "
            f"is a table the sweep never clears and a contradicted edge is a registry "
            f"half-extended. A migration extending the cohort tier extends "
            f"_COHORT_PURGE_ORDER in the same change. Nothing was removed."
        )


def _collect_blob_hash_references(
    connection: sqlite3.Connection, tables: set[str], *, retries: int,
) -> set[str]:
    """Every hash-like value in the given tables' rows, using the declared scans.

    The blob store is content-addressed and deliberately keyless: no cohort table carries
    a foreign key to it, so "which blobs does this file reference" cannot be derived from
    the FK graph. It is derived from the data instead — any `_BLOB_HASH_RUN` match in any
    value of any row of any swept name, through `_PURGE_BLOB_HASH_SCANS`' declared `SELECT
    *` per name. That covers a bare hash column (`document.content_hash`), a JSON list of
    them (`document.source_blobs`) and a crop ref alike, and because the scans select
    every column, a migration adding a hash-bearing column is picked up with no registry
    edit. A value that only looks like a hash costs one filesystem miss in the caller's
    reclamation loop and nothing more.
    """
    hashes: set[str] = set()
    for table in sorted(tables):
        cursor = _run(connection, _PURGE_BLOB_HASH_SCANS[table], retries=retries)
        for row in cursor:  # streamed row by row: a purge must not materialize the file
            for value in row:
                if isinstance(value, bytes):
                    # A BLOB-typed column returns bytes; a hash stored there is a real
                    # reference the text branch would miss — the unsafe direction. The
                    # dump walk made the same choice through its case-insensitive form.
                    value = value.decode("ascii", "ignore")
                if isinstance(value, str):
                    hashes.update(_BLOB_HASH_RUN.findall(value))
    return hashes


def _collect_blob_hash_references_from_dump(connection: sqlite3.Connection) -> set[str]:
    """Hash-like values in a database of any schema, found by walking its SQL dump.

    Package files and Tier D carry their owning modules' schemas — `M-STORE` owns no
    schema meaning, so there are no declared row-scans to reuse for them, and assembling
    SQL against names read from their catalogs is exactly what `FR-STORE-08`'s scanner
    exists to refuse. `iterdump` is stdlib SQLite's own traversal of the file it is
    handed: this module writes no statement at all. Mistakes land conservative — a
    BLOB-typed reference dumps as uppercase hex, which `_BLOB_HASH_RUN_ANYCASE` still
    sees, and a binary value that happens to carry 64 hex-like bytes only ever makes
    purge KEEP a blob it might have deleted, never the reverse.
    """
    hashes: set[str] = set()
    for line in connection.iterdump():
        hashes.update(_BLOB_HASH_RUN_ANYCASE.findall(line))
    return hashes


@dataclass(frozen=True)
class PurgeReport:
    """What `purge_cohort` actually did.

    Per-field rather than a boolean, for the reason `IngestReport.gates` is per-gate: purge
    is irreversible, and a bare "purged" sitting on top of an empty report is the top
    silent-failure trap standing on the one operation where silence is unrecoverable.

    `blobs_deleted` is a real count since #225: the blob files purge actually unlinked —
    the cohort's hash-shaped references minus those another database in the data directory
    still holds. Zero is an honest number, not a policy: it means the cohort referenced no
    blobs, or every hash it referenced survives in another file's rows. A purge whose
    blob phase is interrupted after the commit leaves the surviving blobs orphaned and
    says so through the error it raises — the report never implies a sweep that did not
    happen.
    """

    cohort_id: str
    preconditions_verified: tuple[str, ...]
    tables_cleared: tuple[str, ...]
    rows_deleted_by_table: Mapping[str, int]
    file_bytes_before: int
    file_bytes_after: int
    vacuum_duration_ms: float
    blobs_deleted: int = 0
