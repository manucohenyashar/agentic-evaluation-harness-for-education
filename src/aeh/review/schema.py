"""Migrations for the label and queue tables, and the SQL statements M-REVIEW runs."""

from __future__ import annotations

import hashlib

from aeh.store import Migration, Statement, Tier, TIER_MIGRATIONS


# --- the label store's durable schema (FR-REVIEW-09, #110) ------------------------------------------
#
# The durable `label` table predates this module (M-STORE's base DDL carries
# label_id/run_id/student_ref/criterion_id/label_type/band, and #87's
# `det_audit_separation_columns` added `evaluation_mode` — deliberately not
# re-added here, its CHECK would fail the ALTER). What it could not carry was a
# *fully-typed* label: `FR-REVIEW-09`'s eight fields, `NFR-REVIEW-03`'s
# attribution pair, the queue action `FR-REVIEW-15`'s parity clause compares,
# and the `cohort_id` scoping column the Tier D promotion gate reads
# (`_PURGE_PROMOTED_ROWS`). This migration is what makes the store able to hold
# one, so an acted review session outlives the process that acted it.

_DURABLE_006 = Migration(
    version=6,
    name="review_label_store_columns",
    statements=(
        # CT-REVIEW-08's admissibility column: 1 = the teacher saw the system's
        # output (an operational signal, excluded from agreement at the
        # consumer per FR-STATS-01), 0 = the blind flow's earned 0 (#111). The
        # default of 1 discloses the honest worst case for pre-existing rows —
        # they count as operational, not as validity evidence they never were.
        Statement("ALTER TABLE label ADD COLUMN saw_system_output INTEGER "
                  "NOT NULL DEFAULT 1"),
        # The routing/origin/mode triple the queue admitted on, recorded so a
        # label can be traced back to the population rule that surfaced it.
        Statement("ALTER TABLE label ADD COLUMN routing TEXT "
                  "NOT NULL DEFAULT 'queued'"),
        Statement("ALTER TABLE label ADD COLUMN origin TEXT "
                  "NOT NULL DEFAULT 'escalation'"),
        # CT-REVIEW-19's Phase 2 calibration input: the seconds the decision
        # actually took, against est_seconds stored on the score row.
        Statement("ALTER TABLE label ADD COLUMN review_seconds REAL "
                  "NOT NULL DEFAULT 0"),
        # The agreement pair itself. `band` above stays NOT NULL — it is the
        # effective band the label stands for; the pair records both sides.
        # system_band is nullable: a blind label carries none (#111).
        Statement("ALTER TABLE label ADD COLUMN system_band TEXT"),
        Statement("ALTER TABLE label ADD COLUMN teacher_band TEXT"),
        # NFR-REVIEW-03's attribution pair. actor carries '' on pre-existing
        # rows (unattributed — a DEFAULT of a name would be the attribution
        # lie CT-REVIEW-07 refuses) rather than pretending an owner.
        Statement("ALTER TABLE label ADD COLUMN actor TEXT NOT NULL DEFAULT ''"),
        Statement("ALTER TABLE label ADD COLUMN timestamp TEXT"),
        # Identity: the score the label is about, the queue action
        # FR-REVIEW-15's parity clause compares, and the derived points.
        Statement("ALTER TABLE label ADD COLUMN score_id TEXT"),
        Statement("ALTER TABLE label ADD COLUMN review_queue_action TEXT"),
        Statement("ALTER TABLE label ADD COLUMN new_points REAL"),
        # The promotion scoping column: `_purge_precondition_failures` refuses a
        # cohort purge while this table lacks it, and a promotion keys labels to
        # the administration they belong to.
        Statement("ALTER TABLE label ADD COLUMN cohort_id TEXT"),
    ),
)


#: This module's declared statements (`FR-STORE-08`): the one write the label
#: store makes to the durable tier, keyword-parameterized. Registered in the
#: module's own registry, the shape every other contributing module uses.
REVIEW_STATEMENTS: dict[str, Statement] = {
    # #518 (CT-REVIEW-07): after a blind sitting is submitted, each blind label records the
    # system's band from the stored score, plus the judgement columns derived from it. The
    # sitting itself never reached the score (CT-REVIEW-09); this runs after it has ended.
    # #518 review: the blind labels of a run that still lack the system band — the ones a
    # failed join left behind — so any later submit or resubmit repairs them.
    "select_unbanded_blind_labels": Statement(
        "SELECT label_id, student_ref, criterion_id, teacher_band FROM label "
        "WHERE run_id = :run_id AND label_type = 'blind' AND system_band IS NULL "
        "ORDER BY label_id"
    ),
    "set_blind_system_band": Statement(
        "UPDATE label SET system_band = :system_band, agreed = :agreed, "
        "band_distance = :band_distance, system_points = :system_points "
        "WHERE label_id = :label_id AND label_type = 'blind' AND system_band IS NULL"
    ),
    # #398 / FR-CONSOLE-02: the reads that make a repeated action write nothing. A browser
    # repeats a post with no replay flag, and a fresh console holds no memory of the first,
    # so the durable label is the only place "this decision was already recorded" lives.
    "select_latest_label_for_score": Statement(
        "SELECT label_id, review_queue_action, teacher_band FROM label "
        "WHERE run_id = :run_id AND score_id = :score_id ORDER BY rowid DESC LIMIT 1"
    ),
    "select_blind_labels_for_run": Statement(
        "SELECT label_id, student_ref, criterion_id FROM label "
        "WHERE run_id = :run_id AND label_type = 'blind' ORDER BY label_id"
    ),
    "insert_label": Statement(
        "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
        "label_type, band, evaluation_mode, saw_system_output, routing, origin, "
        "review_seconds, system_band, teacher_band, actor, timestamp, score_id, "
        "review_queue_action, new_points, cohort_id, "
        "package_version_id, assignment_type, band_distance, system_points, teacher_points, agreed, panel_config, recorded_at, "
        "backend_profile) "
        "VALUES (:label_id, :run_id, :student_ref, :criterion_id, :label_type, "
        ":band, :evaluation_mode, :saw_system_output, :routing, :origin, "
        ":review_seconds, :system_band, :teacher_band, :actor, :timestamp, "
        ":score_id, :review_queue_action, :new_points, :cohort_id, "
        ":package_version_id, :assignment_type, :band_distance, :system_points, :teacher_points, :agreed, :panel_config, :recorded_at, "
        ":backend_profile)"
    ),
    # #111's whole-grade read: the auto-accepted population the sample draws
    # from. The service's own fetch admits only the teacher's routings
    # (`queued`/`provisional`), so the sample reads its population through this
    # declared literal — a `.query`, never a runtime assembly (SEC-15), and
    # never a join to anything the blind flow can reach. In-memory services
    # filter their own rows instead.
    "select_auto_grades": Statement(
        "SELECT submission_id, criterion_id, band FROM criterion_score "
        "WHERE run_id = :run_id AND routing = 'auto' "
        "AND submission_id NOT IN "
        "(SELECT submission_id FROM criterion_score "
        "WHERE run_id = :run_id AND routing <> 'auto')"
    ),
    # #359 (CT-AGG-20): every score read names its run. The store flow names the
    # cohort, not a run, so the score reads resolve the cohort's newest run — the
    # latest non-null `started_at`, then `run_id`, M-DET's own `_newest_run` order —
    # and a second run of the cohort replaces the first run's queue rather than
    # merging into it.
    "select_newest_run": Statement(
        "SELECT run_id FROM run "
        "ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1"
    ),
    "select_run_advisory_scores": Statement(
        "SELECT * FROM criterion_score "
        "WHERE run_id = :run_id AND routing IN ('queued', 'provisional')"
    ),
    #: The run's package linkage (`FR-REVIEW-18`): which package, and which VERSION of
    #: it, this run graded against. The version is what pins the weights, the scoring
    #: models and the boundary table, so a re-ranked older run is ranked by the package
    #: as it stood then rather than as it stands now.
    "select_run_package": Statement(
        "SELECT package_id, package_version_id, panel_config, backend_profile FROM run "
        "WHERE run_id = :run_id"
    ),
    #: Each submission's current total, for boundary proximity. `is_current = 1` because
    #: `submission_grade` is append-only with revisions (`#103`) and the superseded
    #: revision's total would place the submission at a boundary it has already left.
    "select_run_submission_totals": Statement(
        "SELECT submission_id, total FROM submission_grade "
        "WHERE run_id = :run_id AND is_current = 1"
    ),
    # #115's collection route: the same 27 columns `insert_label` carries (19 until
    # #368's `review_label_columns` added eight),
    # written as an upsert so a caller collecting the same label into a second
    # administration's cohort re-keys the row rather than failing on a
    # conflicting id. One statement, keyword-parameterized like its sibling —
    # never assembled at runtime (SEC-15).
    "upsert_label": Statement(
        "INSERT OR REPLACE INTO label (label_id, run_id, student_ref, "
        "criterion_id, label_type, band, evaluation_mode, saw_system_output, "
        "routing, origin, review_seconds, system_band, teacher_band, actor, "
        "timestamp, score_id, review_queue_action, new_points, cohort_id, "
        "package_version_id, assignment_type, band_distance, system_points, teacher_points, agreed, panel_config, recorded_at, "
        "backend_profile) "
        "VALUES (:label_id, :run_id, :student_ref, :criterion_id, :label_type, "
        ":band, :evaluation_mode, :saw_system_output, :routing, :origin, "
        ":review_seconds, :system_band, :teacher_band, :actor, :timestamp, "
        ":score_id, :review_queue_action, :new_points, :cohort_id, "
        ":package_version_id, :assignment_type, :band_distance, :system_points, :teacher_points, :agreed, :panel_config, :recorded_at, "
        ":backend_profile)"
    ),
}


TIER_MIGRATIONS[Tier.DURABLE] = TIER_MIGRATIONS[Tier.DURABLE] + (_DURABLE_006,)


# --- Tier D, migration 10 (#368, `FR-REVIEW-21`): what a label AGREED with ---------------------
#
# `label` records what the teacher chose and what the system had proposed, and nothing
# that says how far apart the two were or which package version they were about. Every
# consumer therefore re-derived the comparison: `FR-STATS-24`'s override history, the
# MVVP step-4 cases and `should_escalate`'s `history` each had to compare two band
# STRINGS and each had to guess the lineage. These eight columns record the comparison
# once, at the moment the label is written, while the criterion's band scale is still in
# hand.
#
# Tier D's standing rule holds (`store.py:1219`): no column here is a student name and
# none ever may be. `system_points`/`teacher_points` are the criterion's points and
# `panel_config` the panel's shape — figures about the SCORING, not about the student.
_DURABLE_010 = Migration(
    version=10,
    name="review_label_columns",
    statements=(
        # Which package version the judgement was about, so a history can be scoped to a
        # lineage instead of pooling every version a criterion has ever had.
        Statement("ALTER TABLE label ADD COLUMN package_version_id TEXT"),
        # The population scope the package declares for this criterion; NULL where it
        # declares none — an undeclared scope is not an assumed one.
        Statement("ALTER TABLE label ADD COLUMN assignment_type TEXT"),
        # |system_ordinal - teacher_ordinal|: how far the teacher moved the band, which a
        # string comparison cannot answer. NULL where the band scale is not in hand.
        Statement("ALTER TABLE label ADD COLUMN band_distance INTEGER"),
        Statement("ALTER TABLE label ADD COLUMN system_points REAL"),
        Statement("ALTER TABLE label ADD COLUMN teacher_points REAL"),
        # The agreement bit itself, recorded rather than re-derived: it is the figure
        # every consumer actually reads, and a derivation in six places is six chances to
        # disagree about what a NULL band means.
        Statement("ALTER TABLE label ADD COLUMN agreed INTEGER CHECK (agreed IN (0, 1))"),
        Statement("ALTER TABLE label ADD COLUMN panel_config TEXT"),
        Statement("ALTER TABLE label ADD COLUMN recorded_at TEXT"),
    ),
)


TIER_MIGRATIONS[Tier.DURABLE] = TIER_MIGRATIONS[Tier.DURABLE] + (_DURABLE_010,)


# --- Tier D, migration 12 (#514, `FR-REVIEW-23`): which backend a label judged --------------------
#
# CT-STATS-04 forbids an agreement figure that pools two backends, and a label that does not
# record its run's backend cannot be split by one. A pre-migration row stays NULL: not
# attributable, so M-STATS excludes it from every backend-scoped figure and names the
# exclusion `backend_not_recorded`. Not a student name (Tier D's standing rule).
_DURABLE_012 = Migration(
    version=12,
    name="review_label_backend_profile",
    statements=(Statement("ALTER TABLE label ADD COLUMN backend_profile TEXT"),),
)


TIER_MIGRATIONS[Tier.DURABLE] = TIER_MIGRATIONS[Tier.DURABLE] + (_DURABLE_012,)


# --- Tier C, migration 26 (#367, `FR-REVIEW-20`): what the queue did, on the queue's own row --
#
# `review_queue` shipped as four columns — `queue_id`, `submission_id`, `criterion_id`,
# `reason` — which say that an item was flagged and nothing about the review of it. HLD §9.6
# declares eight more, in two groups:
#
#   * what BUILDING the queue decided — `run_id` (a queue row belonged to no run, so two runs
#     over one cohort shared a queue), `rank_score`, `est_seconds` and `shown_at`, written for
#     the items `build_queue` actually showed;
#   * what ACTING on it did — `action`, `new_band`, `new_points` and `acted_at`, written by
#     `act`.
#
# Without them the screen had to re-derive its own header figures from raw rows and a
# write-log tally, which is the divergence `FR-CONSOLE-35` exists to end: the queue's numbers
# now come from the service that computed them, and the row records what it decided.
_COHORT_026 = Migration(
    version=26,
    name="review_queue_columns",
    statements=(
        Statement("ALTER TABLE review_queue ADD COLUMN run_id TEXT"),
        Statement("ALTER TABLE review_queue ADD COLUMN rank_score REAL"),
        Statement("ALTER TABLE review_queue ADD COLUMN est_seconds REAL"),
        Statement("ALTER TABLE review_queue ADD COLUMN shown_at TEXT"),
        Statement("ALTER TABLE review_queue ADD COLUMN action TEXT"),
        Statement("ALTER TABLE review_queue ADD COLUMN new_band TEXT"),
        Statement("ALTER TABLE review_queue ADD COLUMN new_points REAL"),
        Statement("ALTER TABLE review_queue ADD COLUMN acted_at TEXT"),
    ),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_COHORT_026,), key=lambda m: m.version
))


REVIEW_QUEUE_STATEMENTS: dict[str, Statement] = {
    # What the BUILD decided, for the items it actually showed. `INSERT OR IGNORE` first so a
    # cell flagged by a route that predates the row still gets one, then the update: the queue
    # row is the record of the build, and a build that showed an item the ledger never queued
    # would otherwise leave no trace of having shown it.
    "ensure_queue_row": Statement(
        "INSERT OR IGNORE INTO review_queue (queue_id, run_id, submission_id, criterion_id, "
        "reason) VALUES (:queue_id, :run_id, :submission_id, :criterion_id, :reason)"
    ),
    "record_shown": Statement(
        "UPDATE review_queue SET run_id = :run_id, rank_score = :rank_score, "
        "est_seconds = :est_seconds, shown_at = :shown_at WHERE queue_id = :queue_id"
    ),
    # What the ACTION did. Written by `act`, so the row says what the teacher decided and
    # when — the queue's own history, rather than a label the queue cannot join to.
    "record_action": Statement(
        "UPDATE review_queue SET action = :action, new_band = :new_band, "
        "new_points = :new_points, acted_at = :acted_at WHERE queue_id = :queue_id"
    ),
}


def _queue_id_for(run_id: str, submission_id: str, criterion_id: str) -> str:
    """The queue row's id for one cell of one run.

    `M-GRADE` mints `q-<hash>` and `M-INTEG` mints `integ-<reason>-...`, so there is no single
    spelling to reuse; this is the review side's own, and it is deterministic so a rebuild
    updates its row rather than adding a second one."""
    # A unit separator, not bare concatenation: ("r1", "s", "c") and ("r", "1s", "c") are
    # different cells and must not share a queue row.
    digest = hashlib.sha256(
        chr(31).join([run_id, submission_id, criterion_id]).encode("utf-8")
    ).hexdigest()
    return f"rq-{digest[:24]}"
