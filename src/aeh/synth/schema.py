"""The `narrative` table's migration and the SQL statements M-SYNTH runs."""

from __future__ import annotations

from aeh.store import Migration, Statement, Tier, TIER_MIGRATIONS


# --- the schema step (FR-SYNTH-07, ADR-8) ---------------------------------------------------------

#: Tier C, migration 13: the `narrative` table rebuilt onto the ADR-8 key. SQLite cannot
#: add primary-key columns in place, so the rebuild is the create-copy-drop-rename
#: march — and the copy is the data-loss half the golden pins (`TC-STORE-04`): every
#: legacy row survives, its three legacy columns verbatim and its new key columns
#: defaulted (`criterion_id` becomes the legacy row's `question_id` — the identity it
#: actually carried). The declared `PRIMARY KEY (run_id, submission_id, level,
#: question_id)` with `question_id NOT NULL` is what makes a retried synthesis unit
#: conflict rather than duplicate — SQLite permits NULLs in the columns of a
#: non-INTEGER primary key, which is exactly the hole the NOT NULL closes.
#:
#: The legacy columns lead the declaration **in their original order** on purpose: the
#: migration golden's fixture rows are seeded positionally by the table's leading
#: columns at every schema version, and one fixture row shape that fits both the old
#: and the new table is what keeps that fixture honest across the rebuild.
#:
#: Known limitation, disclosed: a pre-13 ledger holding TWO narratives for one
#: `(submission_id, criterion_id)` under different `narrative_id`s — the duplicates
#: the old narrative_id-only key permitted — cannot copy cleanly onto the new key
#: (both would map to the same `('' , submission, 'l1_question', criterion_id)` row),
#: so the migration fails loudly at the open and rolls back rather than silently
#: dropping either row. No shipped ledger carries such a pair; if one ever does, the
#: remediation is a documented pre-dedup step in the same change, not a quiet
#: `INSERT OR IGNORE`.
_SYNTH_NARRATIVE_KEY: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE narrative_rekeyed (
            narrative_id     TEXT NOT NULL,
            submission_id    TEXT NOT NULL REFERENCES submission(submission_id),
            criterion_id     TEXT,
            run_id           TEXT NOT NULL DEFAULT '',
            level            TEXT NOT NULL DEFAULT 'l1_question'
                             CHECK (level IN ('l1_question', 'l2_test')),
            question_id      TEXT NOT NULL DEFAULT '',
            text             TEXT NOT NULL DEFAULT '',
            citations        TEXT NOT NULL DEFAULT '[]',
            score_claim_flag INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (run_id, submission_id, level, question_id)
        )
        """
    ),
    Statement(
        """
        INSERT INTO narrative_rekeyed (narrative_id, submission_id, criterion_id,
                                       run_id, level, question_id, text, citations,
                                       score_claim_flag)
        SELECT narrative_id, submission_id, criterion_id, '', 'l1_question',
               COALESCE(criterion_id, ''), '', '[]', 0
        FROM narrative
        """
    ),
    Statement("DROP TABLE narrative"),
    Statement("ALTER TABLE narrative_rekeyed RENAME TO narrative"),
)


TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (
    Migration(version=13, name="synth_narrative_key", statements=_SYNTH_NARRATIVE_KEY),
)


# --- the runtime statements (declared, never assembled — FR-STORE-08, SEC-15) ---------------------

SYNTH_STATEMENTS: dict[str, Statement] = {
    "select_synth_score_units": Statement(
        "SELECT work_id, criterion_id, status FROM work_unit "
        "WHERE run_id = :run_id AND submission_id = :submission_id AND stage = 'score'"
    ),
    "select_verdicts": Statement(
        "SELECT verdict_id, work_id, judge_id, band FROM verdict WHERE work_id = :work_id"
    ),
    "select_synth_evidence": Statement(
        "SELECT evidence_id, work_id, document_id, payload FROM evidence "
        "WHERE work_id = :work_id"
    ),
    "select_synth_document": Statement(
        "SELECT d.document_id, d.submission_id, d.markdown, s.student_ref "
        "FROM document d LEFT JOIN submission s ON s.submission_id = d.submission_id "
        "WHERE d.document_id = :document_id"
    ),
    # FR-PIPE-17 / #523: an MC-only paper's template narrative is built from its scored
    # deterministic results, so the worker reads the run's `criterion_score` rows — the
    # same rows M-DET's pass-through wrote (FR-AGG-10). Filtered per question in Python;
    # the statement stays one declared text (FR-STORE-08).
    "select_mc_scores": Statement(
        "SELECT criterion_id, band,"
        " points AS mc_points FROM criterion_score"
        " WHERE run_id = :run_id AND submission_id = :submission_id"
    ),
    "select_narratives": Statement(
        "SELECT narrative_id, run_id, submission_id, level, question_id, text, "
        "citations, score_claim_flag FROM narrative "
        "WHERE run_id = :run_id AND submission_id = :submission_id"
    ),
    "insert_narrative": Statement(
        "INSERT INTO narrative (narrative_id, run_id, submission_id, level, "
        "question_id, text, citations, score_claim_flag) VALUES (:narrative_id, "
        ":run_id, :submission_id, :level, :question_id, :text, :citations, "
        ":score_claim_flag)"
    ),
}
