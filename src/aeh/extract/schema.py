"""Migrations for the evidence table and the SQL statements M-EXTRACT runs."""

from __future__ import annotations

from aeh.store import Migration, Statement, Tier, TIER_MIGRATIONS


# --- the schema step -----------------------------------------------------------------------------

#: Tier C, migration 10: the two columns extraction puts on the shipped `evidence`
#: row. `payload` holds the persisted span set (Tier R student PII — `NFR-EXTRACT-04`
#: purges it WITH the tier, which the shipped purge already does by owning the whole
#: row), `resolved_build` the build that actually answered (`FR-PROV-04`,
#: `FR-EXTRACT-05`). Column-adding, like every migration here: forward-only, no edit
#: to an earlier step.
_EXTRACT_EVIDENCE_COLUMNS: tuple[Statement, ...] = (
    Statement("ALTER TABLE evidence ADD COLUMN payload BLOB"),
    Statement("ALTER TABLE evidence ADD COLUMN resolved_build TEXT"),
)


TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (
    Migration(
        version=11, name="extract_evidence_columns",
        statements=_EXTRACT_EVIDENCE_COLUMNS,
    ),
)


#: Tier C, migration 21 (#361, `FR-EXTRACT-13`): the evidence row's `latency_ms`, the wall time
#: of the SUCCESSFUL provider attempt — the provider's own `Completion.latency_ms` for the call
#: whose spans were persisted, so a failed attempt before it is never counted. Nullable: a row
#: from before the column carries `NULL`, "not recorded".
_EXTRACT_LATENCY: tuple[Statement, ...] = (
    Statement("ALTER TABLE evidence ADD COLUMN latency_ms INTEGER"),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (
        Migration(version=21, name="extract_latency", statements=_EXTRACT_LATENCY),
    ), key=lambda m: m.version
))


# --- the runtime statements (declared, never assembled — FR-STORE-08, SEC-15) --------------------

EXTRACT_STATEMENTS: dict[str, Statement] = {
    # #516 (CT-PKG-01/06): the package version the unit's run pinned, so the request's
    # criterion is read from THAT version, never a later draft.
    "select_unit_run_version": Statement(
        "SELECT r.package_id, r.package_version_id FROM work_unit w "
        "JOIN run r ON r.run_id = w.run_id WHERE w.work_id = :work_id"
    ),
    "select_work_unit": Statement(
        "SELECT work_id, run_id, submission_id, criterion_id, stage, status, "
        "attempts, last_error FROM work_unit WHERE work_id = :work_id"
    ),
    "select_evidence": Statement(
        "SELECT evidence_id, work_id, document_id, payload, resolved_build "
        "FROM evidence WHERE work_id = :work_id"
    ),
    # FR-EXTRACT-12: one run's stored evidence, per criterion — the emitter's whole input
    # (the payload the worker wrote and #361's latency column), joined to the ledger for the
    # criterion and the run filter.
    "select_run_evidence": Statement(
        "SELECT w.criterion_id, e.payload, e.latency_ms FROM evidence e "
        "JOIN work_unit w ON w.work_id = e.work_id "
        "WHERE w.run_id = :run_id AND w.stage = 'extract' "
        "ORDER BY w.criterion_id, e.work_id"
    ),
    "insert_evidence": Statement(
        "INSERT OR REPLACE INTO evidence (evidence_id, work_id, document_id, "
        "payload, resolved_build, latency_ms) VALUES (:evidence_id, :work_id, "
        ":document_id, :payload, :resolved_build, :latency_ms)"
    ),
}
