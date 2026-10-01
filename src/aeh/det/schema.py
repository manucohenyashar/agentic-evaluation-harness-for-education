"""Migrations for M-DET's columns and tables, and the SQL statements it runs."""

from __future__ import annotations

from aeh.store import STATEMENTS, Migration, Statement, Tier, TIER_MIGRATIONS

from .constants import DETERMINISTIC_EXCLUSION


# --- migrations ------------------------------------------------------------------------------------
# Appended to the registry at import, in the pattern pkg/ingest/orch set. Versions
# claimed: package 10, cohort 9, durable 3 and 4 — renumber on rebase if a sibling took
# one (#52's pkg_setup_classification took package 9, #58's orch_leasing took cohort 8).

_DET_SELECTION_POLICY = Migration(
    version=10,
    name="det_selection_policy_columns",
    statements=(
        # FR-DET-05: the partial-credit policy is DECLARED in the package or it
        # does not exist. multi_select marks a criterion keyed to several
        # options; a NULL partial_credit on such a criterion is refused at
        # scoring time, never defaulted (TC-DET-03 cell 11).
        Statement(
            "ALTER TABLE criterion ADD COLUMN multi_select INTEGER NOT NULL "
            "DEFAULT 0 CHECK (multi_select IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE criterion ADD COLUMN partial_credit TEXT "
            "CHECK (partial_credit IS NULL OR partial_credit IN "
            "('all_or_nothing', 'per_option'))"
        ),
    ),
)


_DET_SCORE_STATE = Migration(
    version=9,
    name="det_score_state_columns",
    statements=(
        # FR-DET-02/03/04: the deterministic score row's shape. judge_count is
        # 0 and agreement NULL by construction; the CHECK is the HLD §9.6
        # constraint (0 or odd), so an even panel is a failed write the day
        # M-AGG starts writing these rows too. state and routing carry the
        # three-way distinction: 'unresolved_selection' routed to 'triage' is
        # expressible, and nothing in this module's vocabulary admits 'queued'.
        Statement("ALTER TABLE criterion_score ADD COLUMN points REAL"),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN judge_count INTEGER "
            "NOT NULL DEFAULT 0 CHECK (judge_count = 0 OR judge_count % 2 = 1)"
        ),
        Statement("ALTER TABLE criterion_score ADD COLUMN agreement REAL"),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN state TEXT NOT NULL "
            "DEFAULT 'final' CHECK (state IN ('final', 'provisional_unreviewed', "
            "'ungradeable_by_panel', 'unresolved_selection'))"
        ),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN routing TEXT NOT NULL "
            "DEFAULT 'auto' CHECK (routing IN ('auto', 'queued', 'reviewed', "
            "'provisional', 'triage'))"
        ),
    ),
)


_DET_ITEM_STATISTICS = Migration(
    version=3,
    name="det_item_statistic_columns",
    statements=(
        # FR-DET-07 / CT-DET-08: blank count and unresolved count are SEPARATE
        # figures with SEPARATE columns, so a later merge into one "not
        # answered" figure is a schema change, not an accident. is_key is
        # denormalized so the rollup needs no join (HLD §9.7).
        Statement(
            "ALTER TABLE mcq_item_stats ADD COLUMN is_key INTEGER NOT NULL "
            "DEFAULT 0 CHECK (is_key IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE mcq_item_summary ADD COLUMN n INTEGER NOT NULL DEFAULT 0"
        ),
        Statement(
            "ALTER TABLE mcq_item_summary ADD COLUMN correct_rate REAL "
            "NOT NULL DEFAULT 0.0"
        ),
        Statement(
            "ALTER TABLE mcq_item_summary ADD COLUMN blank_count INTEGER "
            "NOT NULL DEFAULT 0"
        ),
        Statement(
            "ALTER TABLE mcq_item_summary ADD COLUMN unresolved_count INTEGER "
            "NOT NULL DEFAULT 0"
        ),
    ),
)


_DET_AUDIT_SEPARATION = Migration(
    version=4,
    name="det_audit_separation_columns",
    statements=(
        # FR-DET-10 / CT-DET-09: the deterministic grade's audit record, at the
        # HLD §9.7 column set. The per-grade columns (submission/criterion/
        # points/decided_by/version) are NULL on orch's run-level rows, which
        # predate this migration and carry only the profile summary; the
        # vocabulary columns default to 'judged' because every pre-existing row
        # is a judged artifact, and det writes 'deterministic' explicitly. The
        # NOT NULL + DEFAULT form is what an additive SQLite column on a
        # populated table can carry — see `docs/code-notes/det.md`'s interpretations.
        Statement("ALTER TABLE audit_record ADD COLUMN submission_id TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN criterion_id TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN final_points REAL"),
        Statement("ALTER TABLE audit_record ADD COLUMN decided_by TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN package_version_id TEXT"),
        Statement(
            "ALTER TABLE audit_record ADD COLUMN evaluation_mode TEXT "
            "NOT NULL DEFAULT 'judged' CHECK (evaluation_mode IN "
            "('judged', 'deterministic'))"
        ),
        Statement("ALTER TABLE audit_record ADD COLUMN panel_config TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN prompt_template_v TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN answer_key_ref TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN selection_read TEXT"),
        # FR-DET-09 / CT-DET-06: the separation column itself. The exclusion it
        # enforces is DETERMINISTIC_EXCLUSION above — one predicate, every
        # statistics consumer (NFR-DET-03).
        Statement(
            "ALTER TABLE label ADD COLUMN evaluation_mode TEXT "
            "NOT NULL DEFAULT 'judged' CHECK (evaluation_mode IN "
            "('judged', 'deterministic'))"
        ),
    ),
)


DET_STATEMENTS: dict[str, Statement] = {
    "select_det_run": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id FROM run "
        "WHERE run_id = :run_id"
    ),
    "select_cohort_submissions": Statement(
        "SELECT submission_id FROM submission WHERE cohort_id = :cohort_id "
        "ORDER BY submission_id"
    ),
    "select_criterion": Statement(
        "SELECT criterion_id, question_id, kind, answer_key, multi_select, "
        "partial_credit, evaluation_mode FROM criterion "
        "WHERE package_version_id = :v AND criterion_id = :criterion_id"
    ),
    "select_mcq_criteria": Statement(
        "SELECT criterion_id, question_id, kind, answer_key, multi_select, "
        "partial_credit, evaluation_mode FROM criterion "
        "WHERE package_version_id = :v "
        "AND evaluation_mode = 'deterministic' ORDER BY criterion_id"
    ),
    "select_options": Statement(
        "SELECT option_id FROM mcq_option WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id ORDER BY option_id"
    ),
    # M-INGEST's head-document query shape: page replacements append newer
    # documents, so the head is the last row.
    "select_det_document_head": Statement(
        "SELECT document_id, submission_id, content_hash, parent_doc_id, "
        "created_at FROM document WHERE submission_id = :submission_id "
        "ORDER BY created_at, document_id"
    ),
    "select_det_regions": Statement(
        "SELECT region_id, document_id, element_kind, region_kind, retraction, "
        "content_state, selection_state, selection FROM document_region "
        "WHERE document_id = :document_id ORDER BY position"
    ),
    "upsert_det_criterion_score": Statement(
        "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
        "modal_band, band_spread, points, judge_count, agreement, state, routing) "
        "VALUES (:run_id, :submission_id, :criterion_id, :band, :band, 0, :points, "
        ":judge_count, :agreement, :state, :routing) "
        "ON CONFLICT (run_id, submission_id, criterion_id) DO UPDATE SET "
        "band = excluded.band, modal_band = excluded.modal_band, band_spread = 0, "
        "points = excluded.points, "
        "judge_count = excluded.judge_count, agreement = excluded.agreement, "
        "state = excluded.state, routing = excluded.routing"
    ),
    "delete_item_stats": Statement(
        "DELETE FROM mcq_item_stats WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "insert_item_stat": Statement(
        "INSERT INTO mcq_item_stats (package_version_id, criterion_id, option, "
        "chosen, is_key) VALUES (:v, :criterion_id, :option, :chosen, :is_key)"
    ),
    "delete_item_summary": Statement(
        "DELETE FROM mcq_item_summary WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "insert_item_summary": Statement(
        "INSERT INTO mcq_item_summary (package_version_id, criterion_id, n, "
        "correct_rate, blank_count, unresolved_count) VALUES (:v, "
        ":criterion_id, :n, :correct_rate, :blank_count, :unresolved_count)"
    ),
    # --- #87: rederivation, the audit record, the shared filter, the read API ---
    "select_cohort_runs": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, started_at "
        "FROM run WHERE cohort_id = :cohort_id ORDER BY run_id"
    ),
    "select_criterion_scores": Statement(
        # criterion_score.points is the STORED SCORE, not the band-to-points
        # mapping (whose only reader is pkg's points_for_band, CT-PKG-C05) —
        # the alias keeps that net unambiguous about which column this reads.
        "SELECT submission_id, band,"
        " points AS prev_points, state, routing FROM criterion_score"
        " WHERE run_id = :run_id AND criterion_id = :criterion_id"
        " ORDER BY submission_id"
    ),
    "upsert_rederived_score": Statement(
        # The same shape as upsert_criterion_score: a re-derivation is an
        # evaluation under the corrected key, and a re-run of the same
        # (submission, criterion) lands on the same row.
        "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
        "modal_band, band_spread, points, judge_count, agreement, state, routing) "
        "VALUES (:run_id, :submission_id, :criterion_id, :band, :band, 0, :points, "
        ":judge_count, :agreement, :state, :routing) "
        "ON CONFLICT (run_id, submission_id, criterion_id) DO UPDATE SET "
        "band = excluded.band, modal_band = excluded.modal_band, band_spread = 0, "
        "points = excluded.points, "
        "judge_count = excluded.judge_count, agreement = excluded.agreement, "
        "state = excluded.state, routing = excluded.routing"
    ),
    "insert_det_audit_record": Statement(
        "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
        "profile_summary, submission_id, criterion_id, final_points, decided_by, "
        "package_version_id, evaluation_mode, panel_config, prompt_template_v, "
        "answer_key_ref, selection_read) VALUES (:audit_record_id, :run_id, "
        ":recorded_at, :profile_summary, :submission_id, :criterion_id, "
        ":final_points, :decided_by, :package_version_id, :evaluation_mode, "
        ":panel_config, :prompt_template_v, :answer_key_ref, :selection_read)"
    ),
    # NFR-DET-03's canonical composition: the agreement-figure query. The
    # exclusion half is DETERMINISTIC_EXCLUSION above — the ONE definition — and
    # the blind half is NFR-STATS-04's, recorded here so the whole conjunction
    # has a readable home. Consumers use this statement or compose the constant;
    # neither is re-spelled at a call site.
    "select_agreement_labels": Statement(
        "SELECT label_id, run_id, student_ref, criterion_id, label_type, band, "
        "evaluation_mode FROM label WHERE label_type = 'blind' AND "
        "label.evaluation_mode <> 'deterministic' ORDER BY label_id"
    ),
    "select_item_stats_for_version": Statement(
        "SELECT criterion_id, option, chosen, is_key FROM mcq_item_stats "
        "WHERE package_version_id = :v ORDER BY criterion_id, option"
    ),
    "select_item_summary_for_version": Statement(
        "SELECT criterion_id, n, correct_rate, blank_count, unresolved_count "
        "FROM mcq_item_summary WHERE package_version_id = :v ORDER BY criterion_id"
    ),
}


STATEMENTS.update(DET_STATEMENTS)


# SEC-15 refuses assembled SQL, so the composition is not an f-string: the statement
# above spells the filter as a pure literal, and this assert is what ties it to the
# ONE definition — a drift in either is a failed import, not a silent second filter.
assert DETERMINISTIC_EXCLUSION in DET_STATEMENTS["select_agreement_labels"], (
    "select_agreement_labels must carry DETERMINISTIC_EXCLUSION verbatim: the "
    "deterministic-exclusion filter is defined once (NFR-DET-03), and the "
    "literal-only statement (the SEC-15 rule) is bound to that constant here."
)


TIER_MIGRATIONS[Tier.PACKAGE] = TIER_MIGRATIONS[Tier.PACKAGE] + (_DET_SELECTION_POLICY,)


# Sorted merge, not a bare append (#60): the registry's version order is a contract
# (TC-STORE-06's monotonicity walk), and another owning module's import may already
# have registered a higher cohort version than this one claims — import order across
# a pytest session cannot be controlled, so the merge keeps the history honest.
TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_DET_SCORE_STATE,), key=lambda m: m.version
))


TIER_MIGRATIONS[Tier.DURABLE] = TIER_MIGRATIONS[Tier.DURABLE] + (
    _DET_ITEM_STATISTICS,
    _DET_AUDIT_SEPARATION,
)
