"""Migrations for M-JUDGE's tables and the SQL statements it runs."""

from __future__ import annotations

from aeh.store import Migration, Statement, Tier, TIER_MIGRATIONS


# --- the schema step -----------------------------------------------------------------------------

#: Tier C, migration 14: the two columns a verdict row carries beyond the shipped
#: four (`FR-JUDGE-11`/`FR-JUDGE-13`: the band's position in the DECLARED set, and the
#: judge's own confidence — persisted, never alone routing). Column-adding, like every
#: migration here: forward-only, no edit to an earlier step. `verdict_id` stays the
#: work unit's id, so a re-judged arm is an `INSERT OR IGNORE` that lands nowhere —
#: at-least-once leasing cannot produce a second verdict. (Numbered 14, not 12: the
#: merge with #61's `orch_run_lifecycle` took 12 first and #97's `synth_narrative_key`
#: took 13 — the number is first-come, the schema is additive either way.)
_JUDGE_VERDICT_COLUMNS: tuple[Statement, ...] = (
    Statement("ALTER TABLE verdict ADD COLUMN band_ordinal INTEGER"),
    Statement("ALTER TABLE verdict ADD COLUMN self_confidence REAL"),
)


TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (
    Migration(
        version=14, name="judge_verdict_columns",
        statements=_JUDGE_VERDICT_COLUMNS,
    ),
)


#: Tier C, migration 17: the response-contract columns #80 adds to the verdict row
#: (`CT-JUDGE-06`): the reply's cited-span inventory (a JSON array of the span documents
#: the reply cited, `NULL` when the reply cited nothing — a null is `FR-JUDGE-12`'s
#: uncited verdict, persisted and MARKED, never discarded), the reply's sufficiency
#: answer, and the uncited mark itself. Every column is nullable because the migration
#: is additive: a pre-existing row (a migration-001-era verdict, or any writer that did
#: not know the mark) carries `NULL`, and the consumers' reading is fail-open toward
#: *cited* — M-AGG's rule is "the mark is the signal" (`_verdict_cited`), so an
#: unmarked row is read as cited, exactly as the shipped reading demands; a row THIS
#: module writes always carries the mark. The booleans are 0/1-or-`NULL` (three-valued,
#: the `agg_confidence_columns` pattern). **No points column exists and none is added**
#: (`FR-JUDGE-11`: a verdict carries a band and the band's ordinal — the points scale is
#: the package tier's, and a single judge's verdict never carries a number of points).
#: (Numbered 17, the next free Cohort number after #92's `agg_confidence_columns` took
#: 16 — the merge-order convention the chain has followed since 12.)
_JUDGE_VERDICT_RESPONSE_COLUMNS: tuple[Statement, ...] = (
    Statement("ALTER TABLE verdict ADD COLUMN cited_spans TEXT"),
    Statement(
        "ALTER TABLE verdict ADD COLUMN evidence_sufficient "
        "INTEGER CHECK (evidence_sufficient IN (0, 1))"
    ),
    Statement(
        "ALTER TABLE verdict ADD COLUMN uncited INTEGER CHECK (uncited IN (0, 1))"
    ),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (
        Migration(
            version=17, name="judge_verdict_response_columns",
            statements=_JUDGE_VERDICT_RESPONSE_COLUMNS,
        ),
    ), key=lambda m: m.version
))


#: Tier C, migration 22 (#361, `FR-JUDGE-20`): the reply's `evidence_assessment` inventory and
#: the successful call's `latency_ms` on the verdict row — inputs `judge_signals` reads
#: (`FR-STATS-20`). Nullable and additive: `NULL` assessment is "none given", never `''`.
_JUDGE_VERDICT_ASSESSMENT: tuple[Statement, ...] = (
    Statement("ALTER TABLE verdict ADD COLUMN evidence_assessment TEXT"),
    Statement("ALTER TABLE verdict ADD COLUMN latency_ms INTEGER"),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (
        Migration(
            version=22, name="judge_verdict_assessment",
            statements=_JUDGE_VERDICT_ASSESSMENT,
        ),
    ), key=lambda m: m.version
))


#: Tier D, migration 9 (#361, `FR-JUDGE-21`): `run_metrics` gains a `judge_id` dimension so
#: `judge_contract_violations` can be counted per (criterion, judge). A key column cannot be
#: added in place, so the table is rebuilt — integ's Durable 5 march. `judge_id` is appended
#: after the existing columns (the F-SCHEMA fixture seeds leading columns positionally) and is
#: `NOT NULL DEFAULT ''` for the reason Durable 5 gives its dimensions: every writer that omits
#: it lands on the aggregate cell and still conflicts with itself on the key.
_JUDGE_RUN_METRICS_JUDGE_DIMENSION: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE run_metrics_judged (
            run_id        TEXT NOT NULL,
            metric        TEXT NOT NULL,
            value         REAL NOT NULL,
            submission_id TEXT NOT NULL DEFAULT '',
            criterion_id  TEXT NOT NULL DEFAULT '',
            judge_id      TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (run_id, metric, submission_id, criterion_id, judge_id)
        )
        """
    ),
    Statement(
        "INSERT INTO run_metrics_judged (run_id, metric, value, submission_id, criterion_id) "
        "SELECT run_id, metric, value, submission_id, criterion_id FROM run_metrics"
    ),
    Statement("DROP TABLE run_metrics"),
    Statement("ALTER TABLE run_metrics_judged RENAME TO run_metrics"),
)


TIER_MIGRATIONS[Tier.DURABLE] = tuple(sorted(
    TIER_MIGRATIONS[Tier.DURABLE] + (
        Migration(
            version=9, name="judge_run_metrics_judge_dimension",
            statements=_JUDGE_RUN_METRICS_JUDGE_DIMENSION,
        ),
    ), key=lambda m: m.version
))


#: Tier C, migration 28 (Jev design delta FR-JUDGE-34): one pre-screen row per decision-seat unit.
#: Written before the verdict (or the LLM fallback), keyed on the work id, so a redelivered unit
#: reuses it and never samples the decision engine twice (FR-JUDGE-33). No points column.
_JUDGE_DECISION_PRESCREEN: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE decision_prescreen (
            work_id            TEXT PRIMARY KEY,
            run_id             TEXT NOT NULL,
            submission_id      TEXT NOT NULL,
            criterion_id       TEXT NOT NULL,
            engine_build       TEXT NOT NULL,
            outcome            TEXT NOT NULL CHECK (outcome IN
                                   ('accepted', 'below_gate', 'ineligible', 'rejected', 'malformed')),
            reason             TEXT,
            gate_confidence    REAL,
            band_confidence    REAL,
            sufficiency_p      REAL,
            argmax_band        TEXT,
            band_probabilities TEXT,
            band_score         REAL,
            cite_probabilities TEXT,
            threshold          REAL NOT NULL,
            tokens_in          INTEGER,
            latency_ms         INTEGER,
            cost               TEXT
        )
        """
    ),
    Statement("CREATE INDEX idx_prescreen_run ON decision_prescreen (run_id, criterion_id)"),
)


#: Tier C, migration 29 (FR-JUDGE-35): verdict provenance. NULL on a pre-delta row reads `llm`.
_JUDGE_VERDICT_ENGINE: tuple[Statement, ...] = (
    Statement(
        "ALTER TABLE verdict ADD COLUMN scoring_engine TEXT "
        "CHECK (scoring_engine IN ('llm', 'decision'))"
    ),
    Statement("ALTER TABLE verdict ADD COLUMN engine_build TEXT"),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (
        Migration(version=28, name="judge_decision_prescreen", statements=_JUDGE_DECISION_PRESCREEN),
        Migration(version=29, name="judge_verdict_engine", statements=_JUDGE_VERDICT_ENGINE),
    ), key=lambda m: m.version
))


# --- the runtime statements (declared, never assembled — FR-STORE-08, SEC-15) --------------------
#
# Write ownership (CT-JUDGE-12): this dict holds the module's ENTIRE write surface —
# one `INSERT OR IGNORE` into `verdict`, keyed on the work id. No statement here
# touches `criterion_score`, `evidence`, `narrative` or any package row; the work-unit
# `done` transition is the orchestrator's own statement, driven inside the same
# transaction (the `M-EXTRACT` shape) so a verdict and its completed arm commit or
# abort together.

JUDGE_STATEMENTS: dict[str, Statement] = {
    "select_work_unit": Statement(
        "SELECT work_id, run_id, submission_id, criterion_id, stage, status, "
        "attempts, last_error FROM work_unit WHERE work_id = :work_id"
    ),
    "select_judge_run": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status, started_at, "
        "completed_at FROM run WHERE run_id = :run_id"
    ),
    "select_judge_run_evidence": Statement(
        "SELECT e.evidence_id, e.payload "
        "FROM evidence e JOIN work_unit w ON w.work_id = e.work_id "
        "WHERE w.run_id = :run_id AND w.submission_id = :submission_id "
        "AND w.criterion_id = :criterion_id AND w.stage = :stage "
        "ORDER BY e.work_id"
    ),
    "insert_verdict": Statement(
        "INSERT OR IGNORE INTO verdict (verdict_id, work_id, judge_id, band, "
        "band_ordinal, self_confidence, cited_spans, evidence_sufficient, uncited, "
        "evidence_assessment, latency_ms, scoring_engine, engine_build) "
        "VALUES (:verdict_id, :work_id, :judge_id, :band, :band_ordinal, "
        ":self_confidence, :cited_spans, :evidence_sufficient, :uncited, "
        ":evidence_assessment, :latency_ms, :scoring_engine, :engine_build)"
    ),
    # FR-JUDGE-33/34: the decision-seat pre-screen, read before any engine call and written
    # once (INSERT OR IGNORE on the work id) before the verdict or the LLM fallback.
    "select_prescreen": Statement(
        "SELECT work_id, outcome, reason, engine_build, band_confidence, sufficiency_p, "
        "band_probabilities, band_score, cite_probabilities, latency_ms, tokens_in "
        "FROM decision_prescreen WHERE work_id = :work_id"
    ),
    "insert_prescreen": Statement(
        "INSERT OR IGNORE INTO decision_prescreen (work_id, run_id, submission_id, "
        "criterion_id, engine_build, outcome, reason, gate_confidence, band_confidence, "
        "sufficiency_p, argmax_band, band_probabilities, band_score, cite_probabilities, "
        "threshold, tokens_in, latency_ms, cost) VALUES (:work_id, :run_id, :submission_id, "
        ":criterion_id, :engine_build, :outcome, :reason, :gate_confidence, :band_confidence, "
        ":sufficiency_p, :argmax_band, :band_probabilities, :band_score, :cite_probabilities, "
        ":threshold, :tokens_in, :latency_ms, :cost)"
    ),
    # FR-JUDGE-36: one run's pre-screen rows, for `decision_engine_metrics`.
    "select_run_prescreens": Statement(
        "SELECT criterion_id, outcome, reason, gate_confidence, latency_ms "
        "FROM decision_prescreen WHERE run_id = :run_id ORDER BY work_id"
    ),
    # FR-JUDGE-18 / CT-JUDGE-20: one run's verdicts for one cell, in work_id order.
    "select_cell_verdicts": Statement(
        "SELECT v.work_id, v.judge_id, v.band, v.band_ordinal, v.cited_spans, "
        "v.evidence_sufficient, v.uncited, v.scoring_engine FROM verdict v "
        "JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :run_id AND w.submission_id = :submission_id "
        "AND w.criterion_id = :criterion_id ORDER BY v.work_id"
    ),
    # FR-CONFORM-18: one run's pre-screen rows with their band columns, for the live
    # acceptance's per-criterion band agreement. `select_run_prescreens` deliberately omits
    # these columns (M-STATS needs only the outcome mix); the acceptance needs the engine's
    # band per cell next to the LLM panel's, so it reads its own statement rather than widening
    # one consumer's SELECT for another's sake.
    "select_run_prescreen_bands": Statement(
        "SELECT work_id, submission_id, criterion_id, outcome, argmax_band, "
        "band_probabilities FROM decision_prescreen WHERE run_id = :run_id ORDER BY work_id"
    ),
    # FR-CONFORM-18: one run's LLM-panel band ordinals, per cell, for the same comparison.
    # `scoring_engine = 'llm'` excludes the decision engine's own verdict rows — the panel is
    # the operand the engine's band is compared against.
    "select_run_llm_band_ordinals": Statement(
        "SELECT w.submission_id, w.criterion_id, v.band_ordinal FROM verdict v "
        "JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :run_id AND v.scoring_engine = 'llm' "
        "AND v.band_ordinal IS NOT NULL ORDER BY v.work_id"
    ),
    # FR-JUDGE-21: dispatch's strike path counts contract violations per (criterion, judge)
    # on the durable run_metrics row, accumulating across the run's units.
    "add_contract_violations": Statement(
        "INSERT INTO run_metrics (run_id, metric, value, submission_id, criterion_id, "
        "judge_id) VALUES (:run_id, 'judge_contract_violations', :n, '', :criterion_id, "
        ":judge_id) ON CONFLICT (run_id, metric, submission_id, criterion_id, judge_id) "
        "DO UPDATE SET value = value + excluded.value"
    ),
}
