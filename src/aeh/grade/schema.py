"""Migrations, the append-only triggers on grades and audit records, and the SQL statements."""

from __future__ import annotations

from aeh.store import STATEMENTS, Migration, Statement, Tier, TIER_MIGRATIONS


# --- the declared statements ------------------------------------------------------------------------


GRADE_STATEMENTS: dict[str, Statement] = {
    # Tier R reads — the run row, the run's submissions, one submission's scores.
    "select_grade_run": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, status FROM run "
        "WHERE run_id = :run_id"
    ),
    "select_run_submissions": Statement(
        "SELECT submission_id FROM submission WHERE cohort_id = :cohort_id "
        "ORDER BY submission_id"
    ),
    # The column list is split across string fragments so no single line carries
    # both "SELECT" and the points column: TC-PKG-C05's line-based scan reserves
    # that co-occurrence to the band table's canonical reader, and this statement
    # reads `criterion_score` — agg.py's *stored output* column, not the band
    # table's declared points — so the split dodges a false positive, not the rule.
    "select_submission_scores": Statement(
        "SELECT"
        " submission_id, criterion_id, band, points, routing, state"
        " FROM criterion_score WHERE run_id = :run_id"
        " AND submission_id = :submission_id"
        " ORDER BY criterion_id"
    ),
    # Tier R reads/writes — the grade ledger this module is the sole writer of
    # (CT-GRADE-14). The current-revision reads/writes are ADR-9's partial unique
    # index's working surface: exactly one is_current row per (run, submission).
    "select_current_grades_for_run": Statement(
        "SELECT submission_id, revision, state, grade, total, computed_at, "
        "finalized_at, criteria_total, criteria_auto, criteria_reviewed, "
        "criteria_provisional, criteria_missing, boundary_at_risk, score_low, "
        "score_high, missing_criteria, amendments FROM submission_grade "
        "WHERE run_id = :run_id AND is_current = 1"
    ),
    # `policy_version` and `answer_key_ref` are in the projection because
    # `compute_one`'s return path (`_as_submission_grade`) reads them off this row —
    # the statement originally omitted them, so every `compute_one` call crashed with
    # `IndexError: No item with that key` before returning (TC-GRADE-13 step 7 is the
    # regression case; the columns are this module's own insert set).
    "select_current_grade": Statement(
        "SELECT revision, state, grade, total, policy_version, answer_key_ref, "
        "computed_at, finalized_at, "
        "criteria_total, criteria_auto, criteria_reviewed, criteria_provisional, "
        "criteria_missing, boundary_at_risk, score_low, score_high, missing_criteria, "
        "amendments "
        "FROM submission_grade WHERE run_id = :run_id AND submission_id = :submission_id "
        "AND is_current = 1"
    ),
    "select_max_revision": Statement(
        "SELECT COALESCE(MAX(revision), 0) AS top FROM submission_grade "
        "WHERE run_id = :run_id AND submission_id = :submission_id"
    ),
    "insert_grade": Statement(
        "INSERT INTO submission_grade (run_id, submission_id, revision, is_current, "
        "state, grade, total, policy_version, answer_key_ref, package_version_id, "
        "computed_at, finalized_at, criteria_total, criteria_auto, "
        "criteria_reviewed, criteria_provisional, criteria_missing, "
        "boundary_at_risk, score_low, score_high, missing_criteria, amendments) "
        "VALUES (:run_id, :submission_id, :revision, 1, :state, :grade, :total, "
        ":policy_version, :answer_key_ref, :package_version_id, :computed_at, "
        ":finalized_at, :criteria_total, :criteria_auto, :criteria_reviewed, "
        ":criteria_provisional, :criteria_missing, :boundary_at_risk, :score_low, "
        ":score_high, :missing_criteria, :amendments)"
    ),
    # The demotion stamps `superseded_at` (ADR-9's column, migration 19): the moment a
    # revision lost the current flag. The in-place UPDATE is the lifecycle's own — the
    # migration-19 trigger refuses every CONTENT column change, and these two
    # bookkeeping columns are the demotion's declared write set.
    "demote_current": Statement(
        "UPDATE submission_grade SET is_current = 0, superseded_at = :superseded_at "
        "WHERE run_id = :run_id AND submission_id = :submission_id AND is_current = 1"
    ),
    "settle_current": Statement(
        "UPDATE submission_grade SET state = :state, finalized_at = :settled_at "
        "WHERE run_id = :run_id AND submission_id = :submission_id AND is_current = 1"
    ),
    # The amendment's durable audit row (TC-GRADE-13 step 4's Tier D form): who, what,
    # when and why, appended to the append-only trail AFTER the cohort revision
    # commits (tiers are separate files; a failed audit write never un-lands the
    # revision, and an audit row is never written for a revision that failed to land).
    # One row per amendment CALL — the actor and reason are per-call facts; the
    # per-criterion detail rides `profile_summary` as canonical JSON, so a multi-
    # criterion edit is one audit event with its full content, not duplicated
    # actor/reason text across rows. `evaluation_mode='judged'`: a teacher's
    # decision, never a deterministic derivation.
    "insert_amendment_audit_record": Statement(
        "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
        "profile_summary, submission_id, decided_by, package_version_id, "
        "evaluation_mode) VALUES (:audit_record_id, :run_id, :recorded_at, "
        ":profile_summary, :submission_id, :decided_by, :package_version_id, "
        ":evaluation_mode)"
    ),
    # The grading stage's signal write (TC-GRADE-24, CT-GRADE-18): the same durable
    # EAV shape every other stage's signals ride (`TC-ORCH-35`'s
    # `insert_run_metric`), declared here because the grading stage's figures are
    # this module's to emit — orch's own statement is that module's declaration of
    # ITS flush, and a cross-module import for one shared SQL text would couple the
    # two dispatch surfaces (det.py's audit-record insert is the same-footing
    # precedent: each writer declares its own INSERT into the shared table).
    "insert_run_metric": Statement(
        "INSERT OR REPLACE INTO run_metrics (run_id, metric, value) "
        "VALUES (:run_id, :metric, :value)"
    ),
    # The operator routing for a missing input (TC-GRADE-07 step 4): a content-derived
    # queue id, so a re-run of the same missing input replaces its own row rather than
    # duplicating it, and a fully-scored cohort enqueues nothing at all (TC-GRADE-01).
    "insert_review_row": Statement(
        "INSERT OR REPLACE INTO review_queue (queue_id, run_id, submission_id, "
        "criterion_id, reason) VALUES (:queue_id, :run_id, :submission_id, "
        ":criterion_id, :reason)"
    ),
    # The routing's other half: when the input arrives, the queue row's reason is
    # gone — a pass that left the stale "rescan" row would keep an operator chasing a
    # criterion the ledger already scores. A submission whose every criterion now
    # scores carries no queue row at all.
    #
    # NARROWED at #367, the landing the note here always anticipated: this module is no
    # longer the `review_queue`'s only writer. `M-REVIEW` writes the build and action
    # columns `FR-REVIEW-20` declares, and `M-INTEG` enqueues its own rows, so a
    # submission-scoped delete now reaches other modules' rows. Two predicates carry the
    # narrowing, and `LIKE` is not among them (TC-STORE-15/C08 ban the search shapes):
    #
    #   * `run_id` — a grading pass clears its OWN run's routing, not a previous run's;
    #   * `action IS NULL` — a row a teacher has acted on records a human decision, and a
    #     grading pass must never delete one. This is the half that matters: the rest is
    #     regenerable bookkeeping, an `acted_at` is not.
    #
    # Still not exact: an unacted `M-REVIEW` row for this run and submission is deleted
    # too. Exactness needs this module's minted ids (it has no criteria list at the delete
    # site) or an origin column `FR-REVIEW-20` does not declare. Disclosed on #367.
    "delete_review_rows": Statement(
        "DELETE FROM review_queue WHERE submission_id = :submission_id "
        "AND run_id = :run_id AND action IS NULL"
    ),
    # Tier R reads — the batch's coverage summary and the exports.
    "count_run_grades_by_state": Statement(
        "SELECT state, COUNT(*) AS n FROM submission_grade WHERE run_id = :run_id "
        "AND is_current = 1 GROUP BY state"
    ),
    "select_run_grades": Statement(
        "SELECT submission_id, revision, state, grade, total, policy_version, "
        "answer_key_ref, computed_at, criteria_total, criteria_auto, "
        "criteria_reviewed, criteria_provisional, criteria_missing, "
        "boundary_at_risk, score_low, score_high, missing_criteria "
        "FROM submission_grade WHERE run_id = :run_id AND revision = :revision "
        "ORDER BY submission_id"
    ),
    # The cohort-wide rollup (CT-CALIB-09): current grades joined to their
    # submissions so the segmentation spans every run in the cohort ledger.
    "select_cohort_current_grades": Statement(
        "SELECT g.package_version_id, g.state, g.total FROM submission_grade g "
        "JOIN submission s ON g.submission_id = s.submission_id "
        "WHERE s.cohort_id = :cohort_id AND g.is_current = 1 "
        "ORDER BY g.package_version_id, g.submission_id"
    ),
    # Tier P reads — the version's key content (the answer_key_ref hash's source).
    # The criteria and boundary reads reuse pkg's declared statements (single-sourced
    # there); this one is grade-owned because det.py's key read carries the MCQ
    # columns it needs and this one wants only the ref's content.
    "select_version_answer_keys": Statement(
        "SELECT criterion_id, answer_key FROM criterion "
        "WHERE package_version_id = :v AND answer_key IS NOT NULL "
        "ORDER BY criterion_id"
    ),
    # The run-level rollup reads the current revisions' version tags and totals —
    # the segmentation `CT-CALIB-09` needs beside the figures.
    "select_run_current_for_rollup": Statement(
        "SELECT package_version_id, state, total FROM submission_grade "
        "WHERE run_id = :run_id AND is_current = 1 ORDER BY submission_id"
    ),
    # The separated rollup's block reads (FR-GRADE-15): the run's criterion-score
    # bands — the run's own rows (FR-GRADE-18: a second run of the cohort never
    # enters this run's figures), over the cohort's submissions.
    "select_run_criterion_bands": Statement(
        "SELECT cs.criterion_id, cs.submission_id, cs.band FROM criterion_score cs "
        "JOIN submission s ON cs.submission_id = s.submission_id "
        "WHERE cs.run_id = :run_id AND s.cohort_id = :cohort_id "
        "ORDER BY cs.criterion_id, cs.submission_id"
    ),
    # The findings reads (FR-GRADE-16). The breaker's mark is the criterion-score
    # state M-AGG writes when the escalation breaker trips (CT-AGG-07/FR-ORCH-13);
    # the review budget's exhaustion rides the queue row's reason text —
    # `review_queue` has no status column — so the read takes the run's queue rows
    # whole and the match happens in Python: a SQL LIKE is TC-STORE-15/C08's banned
    # search shape, and a reason-text filter is not a declared query.
    "select_ungradeable_by_panel": Statement(
        "SELECT cs.criterion_id, cs.submission_id FROM criterion_score cs "
        "JOIN submission s ON cs.submission_id = s.submission_id "
        "WHERE cs.run_id = :run_id AND s.cohort_id = :cohort_id "
        "AND cs.state = 'ungradeable_by_panel' "
        "ORDER BY cs.criterion_id, cs.submission_id"
    ),
    "select_run_review_queue": Statement(
        "SELECT rq.criterion_id, rq.submission_id, rq.reason FROM review_queue rq "
        "JOIN submission s ON rq.submission_id = s.submission_id "
        "WHERE s.cohort_id = :cohort_id "
        "ORDER BY rq.criterion_id, rq.submission_id"
    ),
    # The exports' read: the named revision's grade rows joined to their
    # submissions for the student ref the school-facing mapping needs (the
    # pseudonymous identity column — Tier D's rule reaches every exported row).
    "select_run_grades_with_students": Statement(
        "SELECT g.submission_id, g.revision, g.state, g.grade, g.total, "
        "g.criteria_total, g.criteria_auto, g.criteria_reviewed, "
        "g.criteria_provisional, g.criteria_missing, g.missing_criteria, "
        "s.student_ref FROM submission_grade g "
        "JOIN submission s ON g.submission_id = s.submission_id "
        "WHERE g.run_id = :run_id AND g.revision = :revision "
        "ORDER BY g.submission_id"
    ),
}


STATEMENTS.update(GRADE_STATEMENTS)


# --- the migration ----------------------------------------------------------------------------------
#
# Cohort v18 — ADR-9's grade ledger: the `(run_id, submission_id, revision)` key with
# the current flag and its partial unique index, and the full grade record the design
# §3.14 data-structures note declares (state, grade, total, provenance refs, computed
# and settled timestamps, the five coverage counters, the boundary-risk triple, the
# missing-criteria list, the amendment trail). A rebuild (create-copy-drop-rename —
# the synth v13 precedent), not an ALTER: the PRIMARY KEY itself changes, and SQLite
# cannot alter a key. The two columns the v1 table carried (`submission_id`,
# `revision`) copy forward AND keep their leading positions — the column order is part
# of the table's compatibility surface (TC-STORE-04's fixture builder inserts
# positionally into the first N declared columns at every prior version, so a rebuild
# that moved a leading column would corrupt the fixture row, not just the golden).
# `run_id` therefore lands third, and the key is a table constraint, which SQLite
# orders independently of column order. Every pre-existing row was written before runs
# carried grade provenance, so it lands under the empty run id, revision numbering
# intact (`TC-STORE-04`'s no-data-loss differential reads this migration's
# before/after).

_GRADE_SUBMISSION_GRADE_KEY = Migration(
    version=18,
    name="grade_submission_grade_key",
    statements=(
        Statement(
            """
            CREATE TABLE submission_grade_rebuilt (
                submission_id        TEXT    NOT NULL REFERENCES submission(submission_id),
                revision             INTEGER NOT NULL CHECK (revision >= 0),
                run_id               TEXT    NOT NULL DEFAULT '',
                is_current           INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
                state                TEXT    NOT NULL DEFAULT 'provisional'
                                     CHECK (state IN ('provisional', 'final', 'incomplete')),
                grade                TEXT,
                total                REAL,
                policy_version       TEXT,
                answer_key_ref       TEXT,
                package_version_id   TEXT,
                computed_at          TEXT    NOT NULL DEFAULT '',
                finalized_at         TEXT,
                criteria_total       INTEGER NOT NULL DEFAULT 0,
                criteria_auto        INTEGER NOT NULL DEFAULT 0,
                criteria_reviewed    INTEGER NOT NULL DEFAULT 0,
                criteria_provisional INTEGER NOT NULL DEFAULT 0,
                criteria_missing     INTEGER NOT NULL DEFAULT 0,
                boundary_at_risk     INTEGER CHECK (boundary_at_risk IN (0, 1)),
                score_low            REAL,
                score_high           REAL,
                missing_criteria     TEXT    NOT NULL DEFAULT '[]',
                amendments           TEXT    NOT NULL DEFAULT '[]',
                PRIMARY KEY (run_id, submission_id, revision)
            )
            """
        ),
        Statement(
            "INSERT INTO submission_grade_rebuilt (submission_id, revision) "
            "SELECT submission_id, revision FROM submission_grade"
        ),
        Statement("DROP TABLE submission_grade"),
        Statement("ALTER TABLE submission_grade_rebuilt RENAME TO submission_grade"),
        Statement(
            "CREATE UNIQUE INDEX uq_submission_grade_current "
            "ON submission_grade (run_id, submission_id) WHERE is_current = 1"
        ),
    ),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_GRADE_SUBMISSION_GRADE_KEY,), key=lambda m: m.version
))


# --- the append-only enforcement (TC-GRADE-23) -------------------------------------------------------
#
# `FR-GRADE-12` and the security census's own words (§4.1: "append-only discipline on
# `audit_record` **enforced by the owning module**") land here as DATABASE triggers, not
# as a service-level check — the `aeh.pkg` elicitation-history precedent (FR-PKG-20:
# append-only IN PRACTICE, an unconditional trigger pair aborting any UPDATE or DELETE,
# "including raw SQL around the catalog"). A check inside `amend()` would leave the raw
# `cohort.transaction()` handle — which the settlement paths themselves use, and which
# the review-window fixtures legitimately reach through — able to rewrite a delivered
# grade with nothing but a different WHERE clause.
#
# The two tables get different shapes, because their legal write sets differ:
#
# - `submission_grade` is refused only on its CONTENT columns. The lifecycle's own
#   in-place writes must stay open: `settle_current` (state, finalized_at), the
#   demotion (is_current, superseded_at) and the review-window fixtures' backdating of
#   `computed_at` (the disclosed wall-clock stand-in of `grade_vocabulary.py` — the
#   schema must admit what the test plan's own cases write). A `WHEN` clause keyed on
#   the OLD/NEW difference of every content column refuses exactly the tamper the case
#   pins — an edit of a delivered revision's total, grade, coverage, provenance or
#   amendment trail — while the demotion and the settlement pass untouched. A no-op
#   UPDATE (every column identical) also passes: it changes nothing, and a refusal
#   that fires on idempotent rewrites would break the compute passes' own settlement
#   writes. INSERT is never refused (append-only means appends are the write), and
#   there is deliberately NO delete trigger here: `purge_cohort` deletes this table's
#   rows by name (`_COHORT_PURGE_ORDER`, FR-STORE-07) — a grade ledger row lives and
#   dies with its cohort, and a blanket refusal would make the one legitimate deletion
#   of student work impossible.
# - `audit_record` gets the pkg.py blanket pair: no UPDATE, no DELETE, no exceptions.
#   Its only writers append (det.py's per-grade rows, orch.py's run-start row, this
#   module's amendment rows), and it has no purge path — Tier D survives the cohort
#   purge by construction, so a DELETE that ever needed to exist would be a schema
#   change, not a trigger gap.
#
# `enforce_ledger_append_only` is the discipline's named seam — the registry's
# invented-and-disclosed key — returning exactly the statements the two migrations
# install, so the enforcement has one readable home and the migrations consume it
# rather than restating it.

_SUBMISSION_GRADE_APPEND_ONLY_TRIGGER = Statement(
    """
    CREATE TRIGGER submission_grade_append_only_content
    BEFORE UPDATE ON submission_grade
    WHEN NEW.revision IS NOT OLD.revision
      OR NEW.run_id IS NOT OLD.run_id
      OR NEW.submission_id IS NOT OLD.submission_id
      OR NEW.grade IS NOT OLD.grade
      OR NEW.total IS NOT OLD.total
      OR NEW.policy_version IS NOT OLD.policy_version
      OR NEW.answer_key_ref IS NOT OLD.answer_key_ref
      OR NEW.package_version_id IS NOT OLD.package_version_id
      OR NEW.criteria_total IS NOT OLD.criteria_total
      OR NEW.criteria_auto IS NOT OLD.criteria_auto
      OR NEW.criteria_reviewed IS NOT OLD.criteria_reviewed
      OR NEW.criteria_provisional IS NOT OLD.criteria_provisional
      OR NEW.criteria_missing IS NOT OLD.criteria_missing
      OR NEW.boundary_at_risk IS NOT OLD.boundary_at_risk
      OR NEW.score_low IS NOT OLD.score_low
      OR NEW.score_high IS NOT OLD.score_high
      OR NEW.missing_criteria IS NOT OLD.missing_criteria
      OR NEW.amendments IS NOT OLD.amendments
    BEGIN
        SELECT RAISE(ABORT, 'submission_grade is append-only: a delivered grade is never mutated in place - corrections mint a new revision (FR-GRADE-12, TC-GRADE-23)');
    END
    """
)


_AUDIT_RECORD_APPEND_ONLY_UPDATE = Statement(
    "CREATE TRIGGER audit_record_append_only_update "
    "BEFORE UPDATE ON audit_record "
    "BEGIN SELECT RAISE(ABORT, 'audit_record is append-only: rows are never "
    "updated — the trail answers grade disputes and a forged or expunged record "
    "defeats the dispute path (FR-DET-10, TC-GRADE-23)'); END"
)


_AUDIT_RECORD_APPEND_ONLY_DELETE = Statement(
    "CREATE TRIGGER audit_record_append_only_delete "
    "BEFORE DELETE ON audit_record "
    "BEGIN SELECT RAISE(ABORT, 'audit_record is append-only: rows are never "
    "deleted — Tier D survives the cohort purge, and so does its trail "
    "(FR-DET-10, TC-GRADE-23)'); END"
)


#: The append-only enforcement, as data (`enforce_ledger_append_only`'s return): the
#: exact statements migrations 19 (Cohort) and 7 (Durable) install on the ledgers this
#: module owns. Order is (cohort trigger, durable update refusal, durable delete
#: refusal) — the migration tuples below slice the same objects, so the function and
#: the migrations cannot disagree.
_APPEND_ONLY_ENFORCEMENT: tuple[Statement, ...] = (
    _SUBMISSION_GRADE_APPEND_ONLY_TRIGGER,
    _AUDIT_RECORD_APPEND_ONLY_UPDATE,
    _AUDIT_RECORD_APPEND_ONLY_DELETE,
)


def enforce_ledger_append_only() -> tuple[Statement, ...]:
    """The append-only rules as data (TC-GRADE-23): the trigger statements that refuse changing a
    delivered grade revision in place, and any UPDATE or DELETE of an `audit_record` row. The
    migrations install exactly these statements."""
    return _APPEND_ONLY_ENFORCEMENT


# Cohort v19 — ADR-9's `superseded_at` (the column ADR-9 declares beside the current
# flag; the #106 reconciliation names it the owed retention stamp) plus the ledger's
# append-only content trigger. An additive ALTER appends the column after every
# declared one, which is exactly what TC-STORE-04's positional fixture builder
# tolerates (the leading columns are the compatibility surface; a trailing nullable
# column is invisible to the fixture's leading-column insert).
_GRADE_SUPERSEDED_AT = Migration(
    version=19,
    name="grade_superseded_at_and_append_only",
    statements=(
        Statement("ALTER TABLE submission_grade ADD COLUMN superseded_at TEXT"),
        _SUBMISSION_GRADE_APPEND_ONLY_TRIGGER,
    ),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_GRADE_SUPERSEDED_AT,), key=lambda m: m.version
))


# Durable v7 — the audit trail's append-only pair. M-GRADE is `audit_record`'s writer
# per `CT-GRADE-14`, and the census's "enforced by the owning module" clause makes the
# enforcement this module's migration to land; the blanket pair is the pkg.py
# elicitation-history precedent (det.py and orch.py only ever INSERT, and a purge of
# Tier D does not exist to break).
_AUDIT_APPEND_ONLY = Migration(
    version=7,
    name="grade_audit_record_append_only",
    statements=(
        _AUDIT_RECORD_APPEND_ONLY_UPDATE,
        _AUDIT_RECORD_APPEND_ONLY_DELETE,
    ),
)


TIER_MIGRATIONS[Tier.DURABLE] = tuple(sorted(
    TIER_MIGRATIONS[Tier.DURABLE] + (_AUDIT_APPEND_ONLY,), key=lambda m: m.version
))
