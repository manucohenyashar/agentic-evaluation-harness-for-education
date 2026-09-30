"""Migrations, the SQL statements M-INTEG runs, and the names of its rate metrics."""

from __future__ import annotations

from aeh.store import Migration, Statement, Tier, TIER_MIGRATIONS


# --- the schema step (the per-criterion dimension the rates are emitted under) -------------------

#: Tier D, migration 5: `run_metrics` rebuilt with the submission and criterion
#: dimensions. SQLite cannot add primary-key columns in place, so the rebuild
#: is the create-copy-drop-rename march — the same shape #97's narrative rekey
#: used. The three legacy columns lead **in their original order** on purpose:
#: the migration golden seeds fixture rows positionally by the table's leading
#: columns at every schema version, and one row shape that fits both the old
#: and the new table is what keeps that fixture honest across the rebuild.
#: The dimension columns are `NOT NULL DEFAULT ''` so a writer that omits them
#: (M-ORCH's three-column rate flush, the table's pre-#73 shape) still lands on
#: the declared primary key — with nullable dimensions, SQLite treats NULLs as
#: distinct in a non-INTEGER key, and M-ORCH's `INSERT OR REPLACE` would never
#: conflict with itself: every `progress()` flush would stack a fresh row per
#: metric instead of replacing it. The empty-string cell is the aggregate
#: dimension: the legacy row the golden seeds and every M-ORCH flush live
#: there, deduped by the key; the gate's full-cell upserts carry real
#: dimensions and REPLACE their own cell. The declared primary key is what
#: makes a re-emitted rate REPLACE the cell's earlier value instead of
#: stacking a second row.
_INTEG_DURABLE_005: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE run_metrics_dimensioned (
            run_id        TEXT NOT NULL,
            metric        TEXT NOT NULL,
            value         REAL NOT NULL,
            submission_id TEXT NOT NULL DEFAULT '',
            criterion_id  TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (run_id, metric, submission_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        INSERT INTO run_metrics_dimensioned (run_id, metric, value)
        SELECT run_id, metric, value FROM run_metrics
        """
    ),
    Statement("DROP TABLE run_metrics"),
    Statement("ALTER TABLE run_metrics_dimensioned RENAME TO run_metrics"),
)


TIER_MIGRATIONS[Tier.DURABLE] = TIER_MIGRATIONS[Tier.DURABLE] + (
    Migration(version=5, name="integ_rate_dimensions", statements=_INTEG_DURABLE_005),
)


# --- the declared statements (FR-STORE-08: one literal each, keyword parameters) ------------------

#: Tier C, migration 25 (#363, `FR-INTEG-10`/`FR-INTEG-12`): the reads the gate makes on
#: every cell, and the column its idempotence record lives in.
#:
#: `read_document` filters `document` by `submission_id` and no migration had ever indexed that
#: column, so every `verify` scanned the table; the gate runs per cell, so the scan is per cell.
#: The index carries `document_id` as its second column because the read orders by it — the
#: seek and the order come from one structure rather than a scan plus a sort.
#:
#: `verdict.work_id` is the one that governs how the module SCALES. `count_verdicts` asks
#: "has this cell been scored yet" on every `verify`, through `work_id IN (SELECT …)`, and with
#: no index on the child column that is a scan of the whole `verdict` table per cell — so the
#: gate's per-call cost grows with the cohort, which is exactly what PERF-06 measured when it
#: was written (15.1 ms per verify at 350 submissions against 3.1 ms at 8, and the note it
#: prints names this scan first). `read_panel_sufficiency`'s join reads it too.
#:
#: `document_region.document_id` is an unindexed foreign-key child column, and
#: `StoreExtractionView.regions` reads it once per cell, so without the second index the view
#: this story publishes would add a full scan of `document_region` per cell to a module held to
#: 1% of run wall clock (`NFR-INTEG-01`). `position` rides along because the read orders by it.
#:
#: `panel_state` is `FR-INTEG-10`'s idempotence record. The requirement's words put it in
#: `cell_phase.units_consumed`, but that column is `INTEGER NOT NULL` and `ready_cells` parses
#: EVERY phase's value with `int()` — a panel state is a join of `work_id`s, so storing it
#: there made a shipped reader raise on the gate's own row. It gets its own TEXT column and
#: `units_consumed` keeps the meaning `FR-ORCH-28` gives it. Disclosed on the issue.
#:
#: `count_units` and `max_retry_attempts` are already served by `idx_wu_cell` (#362), which is
#: why this migration indexes `document` and `document_region` rather than `work_unit`.
_INTEG_READ_INDEXES: tuple[Statement, ...] = (
    Statement(
        "CREATE INDEX idx_document_submission ON document (submission_id, document_id)"
    ),
    Statement(
        "CREATE INDEX idx_document_region_doc ON document_region (document_id, position)"
    ),
    Statement("CREATE INDEX idx_verdict_work ON verdict (work_id)"),
    Statement("ALTER TABLE cell_phase ADD COLUMN panel_state TEXT"),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (
        Migration(version=25, name="integ_gate_reads_and_panel_state",
                  statements=_INTEG_READ_INDEXES),
    ), key=lambda m: m.version
))


INTEG_STATEMENTS: dict[str, Statement] = {
    # --- #363 (FR-INTEG-09): `StoreExtractionView`'s five reads ------------------------------
    "read_cell_evidence": Statement(
        "SELECT e.payload FROM evidence e JOIN work_unit w ON w.work_id = e.work_id "
        "WHERE w.submission_id = :submission_id AND w.criterion_id = :criterion_id "
        "AND w.stage = 'extract' ORDER BY e.work_id"
    ),
    "read_cell_evidence_in_run": Statement(
        "SELECT e.payload FROM evidence e JOIN work_unit w ON w.work_id = e.work_id "
        "WHERE w.run_id = :run_id AND w.submission_id = :submission_id "
        "AND w.criterion_id = :criterion_id AND w.stage = 'extract' ORDER BY e.work_id"
    ),
    "read_document_for_regions": Statement(
        "SELECT document_id, markdown FROM document WHERE submission_id = :submission_id "
        "ORDER BY document_id LIMIT 1"
    ),
    "read_document_regions": Statement(
        "SELECT region_id, document_id, element_kind, region_kind, description, "
        "retraction, content, ocr_conf, content_state, selection_state, selection, "
        "crop_ref, "
        "position FROM document_region WHERE document_id = :document_id ORDER BY position"
    ),
    "read_panel_sufficiency": Statement(
        "SELECT v.evidence_sufficient FROM verdict v "
        "JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.submission_id = :submission_id AND w.criterion_id = :criterion_id "
        "AND w.stage = 'score' ORDER BY v.work_id"
    ),
    "read_panel_sufficiency_in_run": Statement(
        "SELECT v.evidence_sufficient FROM verdict v "
        "JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :run_id AND w.submission_id = :submission_id "
        "AND w.criterion_id = :criterion_id AND w.stage = 'score' ORDER BY v.work_id"
    ),
    # --- #363 (FR-INTEG-10): the idempotence key, and the phase it lives in -------------------
    "read_cell_panel_state": Statement(
        "SELECT work_id FROM work_unit WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND criterion_id = :criterion_id "
        "AND stage IN ('extract', 'score') AND status IN ('done', 'quarantined') "
        "ORDER BY work_id"
    ),
    "read_integrity_post": Statement(
        "SELECT panel_state FROM cell_phase WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND criterion_id = :criterion_id "
        "AND phase = 'integrity_post'"
    ),
    "write_integrity_post": Statement(
        "INSERT INTO cell_phase (run_id, submission_id, criterion_id, phase, "
        "units_consumed, panel_state, recorded_at) VALUES (:run_id, :submission_id, "
        ":criterion_id, 'integrity_post', :units_consumed, :panel_state, :recorded_at) "
        "ON CONFLICT (run_id, submission_id, criterion_id, phase) DO UPDATE SET "
        "units_consumed = excluded.units_consumed, "
        "panel_state = excluded.panel_state, recorded_at = excluded.recorded_at"
    ),
    "database_list": Statement("PRAGMA database_list"),
    "read_document": Statement(
        "SELECT document_id, markdown, content_hash FROM document "
        "WHERE submission_id = :submission_id ORDER BY document_id LIMIT 1"
    ),
    "count_units": Statement(
        "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :run_id AND "
        "submission_id = :submission_id AND criterion_id = :criterion_id"
    ),
    "count_verdicts": Statement(
        "SELECT COUNT(*) AS n FROM verdict WHERE work_id IN (SELECT work_id FROM "
        "work_unit WHERE run_id = :run_id AND submission_id = :submission_id AND "
        "criterion_id = :criterion_id)"
    ),
    "max_retry_attempts": Statement(
        "SELECT MAX(attempts) AS n FROM work_unit WHERE run_id = :run_id AND "
        "submission_id = :submission_id AND criterion_id = :criterion_id AND "
        "stage = 'extract' AND status IN ('pending', 'leased')"
    ),
    # The gate's own ledger entry for the cell — the routing request's ride. On a
    # failure route it is filed pending and the bump grows it with the criterion's
    # enumerated units; on the released path it is filed done, so a verified
    # criterion leaves no live extraction request behind.
    "insert_unit": Statement(
        "INSERT OR IGNORE INTO work_unit (work_id, run_id, submission_id, criterion_id, "
        "stage, status, attempts, origin) VALUES (:work_id, :run_id, :submission_id, "
        ":criterion_id, :stage, :status, :attempts, 'base')"
    ),
    # The retry: every PENDING OR LEASED extract unit for the cell moves in
    # lockstep — enumerated and gate-owned alike — and a unit at the ceiling
    # quarantines instead of retrying forever (FR-EXTRACT-08's ladder). Done and
    # quarantined units are outside the clause, so a completed unit survives a
    # failed verification untouched and the ladder stops at the quarantine.
    "bump_retries": Statement(
        "UPDATE work_unit SET status = CASE WHEN attempts + 1 >= :max_attempts THEN "
        "'quarantined' ELSE 'pending' END, attempts = attempts + 1 WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND criterion_id = :criterion_id AND "
        "stage = 'extract' AND status IN ('pending', 'leased')"
    ),
    "mark_extract_done": Statement(
        "UPDATE work_unit SET status = 'done' WHERE run_id = :run_id AND "
        "submission_id = :submission_id AND criterion_id = :criterion_id AND "
        "stage = 'extract' AND status IN ('pending', 'leased')"
    ),
    "enqueue_review": Statement(
        "INSERT OR IGNORE INTO review_queue (queue_id, run_id, submission_id, "
        "criterion_id, reason) VALUES (:queue_id, :run_id, :submission_id, "
        ":criterion_id, :reason)"
    ),
    # The described-evidence review unit: its id carries the crop reference, so the
    # teacher-review surface can resolve the image in one action (FR-INTEG-05).
    "insert_review_unit": Statement(
        "INSERT OR IGNORE INTO work_unit (work_id, run_id, submission_id, criterion_id, "
        "stage, status, attempts, origin) VALUES (:work_id, :run_id, :submission_id, "
        ":criterion_id, 'review', 'pending', 0, 'base')"
    ),
    # The repeat-insufficiency escalation: a widened panel the ledger expresses as
    # score units nobody has answered yet — a human queue and a verdict are mutually
    # exclusive outcomes of the same signal, and this module writes no verdict.
    "insert_escalation_unit": Statement(
        "INSERT OR IGNORE INTO work_unit (work_id, run_id, submission_id, criterion_id, "
        "stage, status, attempts, origin) VALUES (:work_id, :run_id, :submission_id, "
        ":criterion_id, 'score', 'pending', 0, 'escalation')"
    ),
    # The per-cell rate write, latest value wins; the alert rides the same dimensioned
    # surface so a fired alert names the cell it accuses.
    #
    # `#432`: no longer issued — `upsert_six_metrics` below writes all six rates in one
    # statement. Kept declared rather than deleted because it is the single-row form of the
    # same write, and `upsert_alert` is byte-identical to it: the pair documents that the
    # alert and a rate are the same row shape on the same dimensioned surface, which is why
    # a fired alert can name its cell at all. A future single-rate write belongs here rather
    # than as a seventh tuple in the batched statement.
    "upsert_metric": Statement(
        "INSERT OR REPLACE INTO run_metrics (run_id, metric, value, submission_id, "
        "criterion_id) VALUES (:run_id, :metric, :value, :submission_id, :criterion_id)"
    ),
    # `#432`: the six per-cell rates in ONE statement. `_emit_metrics` issued six
    # `upsert_metric` executes per verify and they were the single largest block of the
    # gate's cost (0.694 s of 2.127 s over 456 calls). The rows are the same rows: same
    # table, same columns, same REPLACE semantics, same six metric names in the same order
    # — this is a change to how the writes are ISSUED, not to what is written
    # (`CT-INTEG-04` pins the set).
    #
    # Six fixed tuples rather than an assembled VALUES list: `SEC-15`/`FR-STORE-08` forbids
    # building SQL at runtime, so the arity is declared here and the parameters are keyword
    # ones. A seventh signal is a new statement and a contract bump, which is the same
    # property `INTEG_RATE_METRICS`' positional zip already gives.
    "upsert_six_metrics": Statement(
        "INSERT OR REPLACE INTO run_metrics (run_id, metric, value, submission_id, "
        "criterion_id) VALUES "
        "(:run_id, :metric_0, :value_0, :submission_id, :criterion_id), "
        "(:run_id, :metric_1, :value_1, :submission_id, :criterion_id), "
        "(:run_id, :metric_2, :value_2, :submission_id, :criterion_id), "
        "(:run_id, :metric_3, :value_3, :submission_id, :criterion_id), "
        "(:run_id, :metric_4, :value_4, :submission_id, :criterion_id), "
        "(:run_id, :metric_5, :value_5, :submission_id, :criterion_id)"
    ),
    "upsert_alert": Statement(
        "INSERT OR REPLACE INTO run_metrics (run_id, metric, value, submission_id, "
        "criterion_id) VALUES (:run_id, :metric, :value, :submission_id, :criterion_id)"
    ),
}


#: The six per-criterion rates, in the design's declared order (§3.9):
#: span verification failure, empty evidence, low-confidence overlap, described
#: evidence, sufficiency flag, extractor disagreement. Position 0 is the rate
#: the alert sits on.
INTEG_RATE_METRICS = (
    "integ-span-verification-failure-rate",
    "integ-empty-evidence-rate",
    "integ-ocr-overlap-rate",
    "integ-described-evidence-rate",
    "integ-sufficiency-flag-rate",
    "integ-extractor-disagreement-rate",
)


#: The alert CT-INTEG-14 declares: a span-verification failure rate above a low
#: threshold means the extractor is hallucinating spans — a model or prompt
#: problem, not a data problem. A string OUTSIDE the six rates (it sits ON one).
ALERT_SPAN_VERIFICATION_FAILURES = "integ-span-verification-failure-alert"
