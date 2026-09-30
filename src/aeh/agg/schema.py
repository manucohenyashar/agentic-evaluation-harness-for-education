"""Migrations for the score columns and the SQL statements M-AGG runs."""

from __future__ import annotations

from typing import Any

from aeh.store import (
    Migration,
    MigrationError,
    MigrationPrecondition,
    Statement,
    Tier,
    TIER_MIGRATIONS,
)


# --- the writer: the score row in the caller's transaction (FR-AGG-15, #360) ----------------------
#
# `aggregate` stays pure (`CT-AGG-01`); persisting its result is this one declared
# upsert, run in the transaction the caller opened (`CT-AGG-19`) so a score and
# whatever the caller writes beside it — the escalation it enqueues — land or
# vanish together. Keyed on the run-scoped key (#359), so a second write of the
# same (run, submission, criterion) updates the one row.

AGG_STATEMENTS: dict[str, Statement] = {
    "upsert_criterion_score": Statement(
        "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
        "modal_band, band_spread, points, judge_count, agreement, confidence, "
        "confidence_base, spans_verified, evidence_present, sufficiency_flag, "
        "ocr_overlap_risk, described_evidence, extractor_disagreement, caps_fired, "
        "routing, state, state_reason) VALUES (:run_id, :submission_id, :criterion_id, "
        ":band, :modal_band, :band_spread, :points, :judge_count, :agreement, :confidence, "
        ":confidence_base, :spans_verified, :evidence_present, :sufficiency_flag, "
        ":ocr_overlap_risk, :described_evidence, :extractor_disagreement, :caps_fired, "
        ":routing, :state, :state_reason) "
        "ON CONFLICT (run_id, submission_id, criterion_id) DO UPDATE SET "
        "band = excluded.band, modal_band = excluded.modal_band, "
        "band_spread = excluded.band_spread, points = excluded.points, "
        "judge_count = excluded.judge_count, agreement = excluded.agreement, "
        "confidence = excluded.confidence, confidence_base = excluded.confidence_base, "
        "spans_verified = excluded.spans_verified, "
        "evidence_present = excluded.evidence_present, "
        "sufficiency_flag = excluded.sufficiency_flag, "
        "ocr_overlap_risk = excluded.ocr_overlap_risk, "
        "described_evidence = excluded.described_evidence, "
        "extractor_disagreement = excluded.extractor_disagreement, "
        "caps_fired = excluded.caps_fired, routing = excluded.routing, "
        "state = excluded.state, state_reason = excluded.state_reason"
    ),
}


#: FR-AGG-17's reads: one run's stored score rows and its score work units. Nothing else —
#: the signals are re-derivable from the database by anyone, which is what makes a figure in a
#: report answerable months later.
AGG_SIGNAL_STATEMENTS: dict[str, Statement] = {
    "select_run_scores": Statement(
        "SELECT criterion_id, band, band_spread, agreement, routing, caps_fired "
        "FROM criterion_score WHERE run_id = :run_id "
        "ORDER BY criterion_id, submission_id"
    ),
    # Panels, not units: one widening writes TWO units (1→3, 3→5), so counting rows would
    # report twice the share of panels widened and could exceed 1.0. The shipped precedent is
    # M-ORCH's own `select_escalated_results` — COUNT(DISTINCT submission_id).
    "select_run_escalated_panels": Statement(
        "SELECT criterion_id, COUNT(DISTINCT submission_id) AS n FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'score' AND origin = 'escalation' "
        "GROUP BY criterion_id"
    ),
    "select_run_judged_panels": Statement(
        "SELECT criterion_id, COUNT(DISTINCT submission_id) AS n FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'score' GROUP BY criterion_id"
    ),
}


AGG_STATEMENTS.update(AGG_SIGNAL_STATEMENTS)


#: #517 (CT-REVIEW-06, FR-AGG-07): the teacher's decision reaches the score row. `reviewed` is
#: the routing value M-AGG never assigns to its own aggregations; it records that a reviewer
#: acted, with the band and points the reviewer settled on. Declared here because this module
#: is the only writer of `criterion_score` (CT-AGG-18); M-REVIEW calls `record_review`.
AGG_STATEMENTS.update({
    "record_review": Statement(
        # Points: the package's figure for the settled band when the caller has one; the row's
        # own points when the band is unchanged (an accept keeps what the package scored);
        # NULL when the band moved and no package figure is in hand (unknown, never a
        # default-scale number).
        "UPDATE criterion_score SET points = CASE WHEN :points IS NOT NULL THEN :points "
        "WHEN band = :band THEN points ELSE NULL END, band = :band, routing = 'reviewed', "
        "state = 'final' WHERE run_id = :run_id AND submission_id = :submission_id "
        "AND criterion_id = :criterion_id"
    ),
})


#
# M-AGG owns this migration because it owns the columns' meaning: the four
# integrity inputs ride the score row so the figure is reconstructible from
# stored data alone (`NFR-AGG-04`), and `confidence_base` carries what the caps
# consumed (the post-multiplier, pre-cap base) so the replay is exact rather
# than approximate. Every column is nullable: `NULL` = not recorded, which is
# how the migration leaves every pre-existing row, and the re-derivation reads
# `NULL` fail-closed — the same polarity the live signals carry. The stored
# booleans are constrained to 0/1-or-NULL (three-valued, like the signals
# themselves: `NULL` is neither favourable nor zero) — a real 0/1 with `NULL`
# allowed, not a fake third value.
#
# `state` and `routing` already exist (det migration v9's CHECK admits every
# value this module's paths write — `final`, `queued` and, since #93,
# `provisional` on routing and `provisional_unreviewed`/`ungradeable_by_panel`
# on state);
# only the six columns #92 introduces are added here.

_AGG_CONFIDENCE_COLUMNS = Migration(
    version=16,
    name="agg_confidence_columns",
    statements=(
        Statement("ALTER TABLE criterion_score ADD COLUMN confidence REAL"),
        Statement("ALTER TABLE criterion_score ADD COLUMN confidence_base REAL"),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN spans_verified "
            "INTEGER CHECK (spans_verified IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN evidence_present "
            "INTEGER CHECK (evidence_present IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN sufficiency_flag "
            "INTEGER CHECK (sufficiency_flag IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN ocr_overlap_risk "
            "INTEGER CHECK (ocr_overlap_risk IN (0, 1))"
        ),
    ),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_AGG_CONFIDENCE_COLUMNS,), key=lambda m: m.version
))


# --- Tier C, migration 30 (#524, `FR-PIPE-18`): why a row carries its state ---------------------
#
# An `ungradeable_by_panel` row can come from the criterion breaker or from an even panel whose
# replacement arm was refused; the reviewer must be able to tell which. NULL on every other row.
_AGG_STATE_REASON = Migration(
    version=30,
    name="agg_criterion_score_state_reason",
    statements=(Statement("ALTER TABLE criterion_score ADD COLUMN state_reason TEXT"),),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_AGG_STATE_REASON,), key=lambda m: m.version
))


# --- #359: run-scoped criterion_score (FR-AGG-16, CT-AGG-20) ---------------------------------
#
# A second run of a cohort must never overwrite the first run's scores, so the score row is keyed
# by the run: `(run_id, submission_id, criterion_id)`. SQLite cannot change a primary key in
# place, so the table is rebuilt — the grade v18 precedent (`_GRADE_SUBMISSION_GRADE_KEY`):
# create `criterion_score_new`, copy, drop, rename — inside the one migration transaction, so a
# failure at any statement leaves the old table whole (`RES-21`).
#
# The surviving columns keep their declaration order and the new ones follow them — the grade
# v18 precedent — so a positional reader of the table's leading columns (F-SCHEMA's fixture
# builder) reads the same columns at every version; the key's order is the PRIMARY KEY clause's.
#
# `run_id` carries **no default**: the backfill names the run explicitly, and a writer that
# forgets the run fails the NOT NULL rather than landing under a placeholder. It is not a foreign
# key either — the cohort ledger's other run-scoped tables (`submission_grade`) do not declare
# one, and the ledger's run rows are not the only producers of score rows under test.
#
# The backfill attributes existing rows to the cohort's only run. With rows present and any other
# run count — two or more (ambiguous) or zero (no run to name) — the guard refuses with
# `MigrationError` before a statement runs; with no rows there is nothing to attribute and the
# rebuild proceeds whatever the run count. Migrated rows were single-verdict-band rows, so
# `modal_band = band` and `band_spread = 0`. The three FR-AGG-15 columns #360's `write_score`
# fills (`described_evidence`, `extractor_disagreement`, `caps_fired`) arrive NULL: not measured.

def _refuse_unattributable_scores(rows: list[Any]) -> None:
    """Refuse the rebuild when existing score rows cannot be attributed to exactly one run."""
    present, runs = int(rows[0][0]), int(rows[0][1])
    if present and runs != 1:
        raise MigrationError(f"criterion_score rows cannot be attributed to a run: {runs} runs")


_AGG_RUN_SCOPED_SCORE = Migration(
    version=20,
    name="agg_run_scoped_score",
    statements=(
        MigrationPrecondition(
            "SELECT EXISTS (SELECT 1 FROM criterion_score) AS present, "
            "(SELECT COUNT(*) FROM run) AS runs",
            check=_refuse_unattributable_scores,
        ),
        Statement(
            """
            CREATE TABLE criterion_score_new (
                submission_id          TEXT    NOT NULL REFERENCES submission(submission_id),
                criterion_id           TEXT    NOT NULL,
                band                   TEXT    NOT NULL,
                points                 REAL,
                judge_count            INTEGER NOT NULL DEFAULT 0
                    CHECK (judge_count = 0 OR judge_count % 2 = 1),
                agreement              REAL,
                state                  TEXT    NOT NULL DEFAULT 'final'
                    CHECK (state IN ('final', 'provisional_unreviewed', 'ungradeable_by_panel',
                                     'unresolved_selection')),
                routing                TEXT    NOT NULL DEFAULT 'auto'
                    CHECK (routing IN ('auto', 'queued', 'reviewed', 'provisional', 'triage')),
                confidence             REAL,
                confidence_base        REAL,
                spans_verified         INTEGER CHECK (spans_verified IN (0, 1)),
                evidence_present       INTEGER CHECK (evidence_present IN (0, 1)),
                sufficiency_flag       INTEGER CHECK (sufficiency_flag IN (0, 1)),
                ocr_overlap_risk       INTEGER CHECK (ocr_overlap_risk IN (0, 1)),
                run_id                 TEXT    NOT NULL,
                modal_band             TEXT,
                band_spread            INTEGER NOT NULL DEFAULT 0,
                described_evidence     INTEGER,
                extractor_disagreement INTEGER,
                caps_fired             TEXT,
                PRIMARY KEY (run_id, submission_id, criterion_id)
            )
            """
        ),
        Statement(
            "INSERT INTO criterion_score_new (run_id, submission_id, criterion_id, band, "
            "modal_band, band_spread, points, judge_count, agreement, state, routing, "
            "confidence, confidence_base, spans_verified, evidence_present, sufficiency_flag, "
            "ocr_overlap_risk) SELECT (SELECT run_id FROM run), submission_id, criterion_id, "
            "band, band, 0, points, judge_count, agreement, state, routing, confidence, "
            "confidence_base, spans_verified, evidence_present, sufficiency_flag, "
            "ocr_overlap_risk FROM criterion_score"
        ),
        Statement("DROP TABLE criterion_score"),
        Statement("ALTER TABLE criterion_score_new RENAME TO criterion_score"),
    ),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_AGG_RUN_SCOPED_SCORE,), key=lambda m: m.version
))
