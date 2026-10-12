"""The read queries the screens run, declared once."""

from __future__ import annotations


# --- the control surface (HLD §11.8) -------------------------------------------------------------------

#: The run's queue rows as `FR-REVIEW-20` records them: the build's own `rank_score`,
#: `est_seconds` and `shown_at`, and the action columns `act` writes. Ordered by the rank the
#: build computed, so the screen lists items in the order the service ranked them rather than
#: re-deriving one. Scoped by `run_id`, the column migration 26 adds: before it, two runs over
#: one cohort shared a queue.
_SELECT_RUN_QUEUE = (
    "SELECT queue_id, submission_id, criterion_id, reason, rank_score, est_seconds, "
    "shown_at, action, new_band, new_points, acted_at FROM review_queue "
    "WHERE run_id = :run_id ORDER BY rank_score DESC, queue_id"
)


#: `FR-CONSOLE-19`'s ordering notes for the queue's query log. Constants rather than
#: f-strings: SEC-15's walker reads an f-string carrying ordering vocabulary as assembled
#: SQL, and `CT-CONSOLE-12` reads these very words out of the log to assert that the
#: reservation was taken before anything was ordered. Neither is negotiable, so the words
#: are declared once and only counts are interpolated around them.
_QUEUE_RANK_NOTE = " ranked, order by expected_value desc, holistic first"


_QUEUE_AUDIT_ORDER_NOTE = " queued rows from the write audit, order by write order"


# --- the console's read-only SQL -----------------------------------------------------------------------
#
# Reads go through the tier handles at the same seam `M-GRADE`, `M-DET` and `M-INGEST` use.
# The gate and breaker statements mirror the cohort-tier shapes `M-INGEST` declares
# (INGEST_STATEMENTS) so the ladder reads what the writer wrote.

#: S1's read, against the table that exists (`validation_record`, package tier — the
#: six-part key `FR-PKG-08` fixes, read here population-scoped). The table this module
#: once guessed (`package_validation`) has no migration, so the positive half of
#: `FR-CONSOLE-26` was dead code: a genuinely stored record rendered as an absence.
#: The scoring-model column is deliberately not projected: the ladder reports, per
#: gate, who validated under which backend and how well — the model itself is the
#: package's classification fact (`CT-AGG-09`), and a consumer that cannot read the
#: attribute cannot branch on it (`aeh.console` is outside the sanctioned readers).
_SELECT_VALIDATION = (
    "SELECT criterion_id, backend_profile, agreement, n "
    "FROM validation_record "
    "WHERE package_version_id = :package_version_id "
    "AND population_scope_id = :population"
)


#: The same table, version-scoped without a population — the provenance gate's read
#: (`validation_record()`), which reports every population a record exists for.
_SELECT_VALIDATION_VERSION = (
    "SELECT population_scope_id, agreement, n FROM validation_record "
    "WHERE package_version_id = :package_version_id"
)


_SELECT_GATE_ROWS = (
    "SELECT submission_id, v0_integrity, v1_pages, v2_structure, v3_identity, v4_match, "
    "quarantined FROM submission WHERE cohort_id = :cohort_id"
)


_SELECT_COHORT_BREAKER = (
    "SELECT cohort_id, tripped_at, rate, flagged, ingested, finding "
    "FROM v4_cohort_breaker WHERE cohort_id = :cohort_id"
)


#: A submission's score rows as the student page and `render_scores` show them. Neither
#: route names a run, so the read is scoped to each cohort ledger's newest run (latest
#: non-null `started_at`, then `run_id` — M-DET's `_newest_run` order): every score read
#: names its run (#359, CT-AGG-20), and a second run's rows replace the first run's on the
#: page rather than rendering beside them.
_SELECT_SCORES = (
    "SELECT criterion_id, band, judge_count, agreement, state, routing, "
    "points FROM criterion_score WHERE run_id = "
    "(SELECT run_id FROM run "
    "ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1) "
    "AND submission_id = :submission_id "
    "ORDER BY criterion_id"
)


_SELECT_GRADES = (
    "SELECT submission_id, revision, state, total, policy_version, grade, "
    "criteria_total, criteria_auto, criteria_reviewed, criteria_provisional, "
    "criteria_missing, boundary_at_risk, score_low, score_high "
    "FROM submission_grade WHERE run_id = :run_id ORDER BY submission_id"
)


#: The export's rows (#398): the CURRENT revision of each grade, with the delivery stamp
#: the provisional flag is read from. `submission_grade` is a cohort-tier table, so this is
#: read across the cohort files, never from Tier D.
_SELECT_EXPORT_GRADES = (
    "SELECT submission_id, revision, state, total, policy_version, finalized_at "
    "FROM submission_grade WHERE run_id = :run_id AND is_current = 1 "
    "ORDER BY submission_id"
)


#: One revision of one grade, off the append-only submission_grade history (`FR-GRADE-09`):
#: the superseded revision stays readable after an amendment writes the next one.
_SELECT_GRADE_REVISION = (
    "SELECT submission_id, revision, finalized_at, state, total, policy_version "
    "FROM submission_grade WHERE submission_id = :submission_id AND revision = :revision "
    "ORDER BY submission_id"
)


#: `FR-CONSOLE-39`: the revision the teacher is looking at — the ledger's own `is_current`
#: flag, never `MAX(revision)` and never revision 1.
#:
#: ADR-9's partial unique index is `(run_id, submission_id) WHERE is_current = 1`, so
#: "current" is current *per run*: a submission graded under two runs of one cohort has TWO
#: current rows, and a bare `is_current = 1` would hand back whichever the file listed first.
#: This route names no run — `grade_revision(submission_ref=...)` is the teacher's read of a
#: submission — so it scopes to the ledger's newest run, the same subselect and the same
#: reasoning as `_SELECT_SCORES` above (#359): a second run's grade replaces the first's on
#: the page rather than shadowing it by row order.
_SELECT_CURRENT_GRADE_REVISION = (
    "SELECT submission_id, revision, finalized_at, state, total, policy_version "
    "FROM submission_grade WHERE submission_id = :submission_id AND is_current = 1 "
    "AND run_id = (SELECT run_id FROM run "
    "ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1) "
    "ORDER BY submission_id"
)


_SELECT_NARRATIVE = (
    "SELECT question_id, text, score_claim_flag FROM narrative "
    "WHERE submission_id = :submission_id ORDER BY question_id"
)


#: S8's park list, declared rather than assembled (`FR-STORE-08`, SEC-15). The park is
#: the FLAG (`submission.quarantined`, 0/1 — the schema's own parking state), not a
#: status IN-list: `ingest_status` is the diagnosis beside the flag, and an IN-list over
#: a guessed status vocabulary matched no real row (the CHECK domain admits only
#: `('ok', 'low_confidence_ocr', 'unreadable', 'incomplete', 'unmatched_assessment')`).
#: `points` rides its own line of the score statement the same way every other reader of
#: `criterion_score` spells it — `TC-PKG-C05` reserves the band-to-points *mapping* to
#: `aeh.pkg`, and the stored value a consumer reads back is that mapping already applied.
_SELECT_QUARANTINE = (
    "SELECT submission_id, ingest_status FROM submission "
    "WHERE quarantined = 1 ORDER BY submission_id"
)


#: FR-CONSOLE-29 (#530): the stored crops M-INGEST kept for a parked submission's regions
#: (a described region, an unreadable mark where one was cropped), as content hashes.
_SELECT_SUBMISSION_CROPS = (
    "SELECT r.crop_ref AS crop_ref, r.region_kind AS region_kind FROM document_region r "
    "JOIN document d ON d.document_id = r.document_id "
    "WHERE d.submission_id = :submission_id AND r.crop_ref IS NOT NULL "
    # The CURRENT document only: a revision supersedes its parent, whose regions stay in the
    # ledger for the record but are not what the operator is looking at (#530 review).
    "AND d.document_id NOT IN (SELECT parent_doc_id FROM document "
    "WHERE parent_doc_id IS NOT NULL) ORDER BY r.region_id"
)


#: The crop route's allow-list: a content address is served only when some region's stored
#: crop names it, so `/blobs/<ref>` is never a read of an arbitrary stored file (#530 review).
_SELECT_CROP_REF_KNOWN = (
    "SELECT COUNT(*) AS n FROM document_region WHERE crop_ref = :crop_ref"
)


_SELECT_COHORT_QUARANTINE = (
    "SELECT submission_id, ingest_status FROM submission "
    "WHERE cohort_id = :cohort_id AND quarantined = 1"
)


_INSERT_RUN_CONTROL = (
    "INSERT INTO run_control (control_id, run_id, action, reason, requested_at) "
    "VALUES (:control_id, :run_id, :action, :reason, :requested_at)"
)


#: S8's close-as-unresolvable: the operator's resolution, not an automatic one — the
#: console writes the diagnosis the schema's CHECK domain admits (`incomplete`) and
#: clears the park flag, and the grade consequence (criteria MISSING, grade INCOMPLETE,
#: never zero) is M-GRADE's landed missing-criteria rule computing over a submission
#: whose criteria were never scored (`FR-GRADE-03`'s NULL-grade rule; `FR-GRADE-07/08`).
_UPDATE_QUARANTINE_RESOLUTION = (
    "UPDATE submission SET ingest_status = :status, quarantined = 0 "
    "WHERE submission_id = :submission_id"
)


_SELECT_SUBMISSION_EXISTS = (
    "SELECT submission_id FROM submission WHERE submission_id = :submission_id"
)


#: Whose paper a quarantined submission is: V3's outcome and the student it matched. A release
#: (`matched`) is refused unless V3 passed, because the paper would be graded under `unknown`.
_SELECT_SUBMISSION_IDENTITY = (
    "SELECT v3_identity, student_ref FROM submission WHERE submission_id = :submission_id"
)


# --- the SPA read surface (FR-CONSOLE-47…52, FR-CONSOLE-60, #755) ---------------------------------------
#
# The redesign SPA's reads read the same rows the server-rendered screens read, through the
# same tier handles. Every statement is a declared constant (`FR-STORE-08`, SEC-15) and
# every parameter is bound, never interpolated.

#: Every run row, across the cohort files: the context read's run entities and the jobs
#: read's run-mirrored job records. `cost_spend` is the ledger's own accrual figure —
#: a zero is a measured zero, never a fabricated one (`CT-PROV-03`).
_SELECT_RUNS_ALL = (
    "SELECT run_id, cohort_id, package_id, package_version_id, status, "
    "started_at, completed_at, cost_spend, pause_reason FROM run ORDER BY run_id"
)


#: One run's work units in completion order: the logs read's stage records. `done_ticks`
#: is the monotonic completion order (`FR-ORCH-13`); units without ticks (never completed)
#: sort last by id — a read is not promised row order (`TierHandle.query`), so the ORDER BY
#: here is the display order the SPA renders, not a dependency.
_SELECT_RUN_WORK_UNITS = (
    "SELECT work_id, submission_id, stage, criterion_id, judge_id, status, attempts, "
    "last_error, done_ticks FROM work_unit WHERE run_id = :run_id "
    "ORDER BY CASE WHEN done_ticks IS NULL THEN 1 ELSE 0 END, done_ticks, work_id"
)


#: One run's second-opinion requests and breaker latches: the issues read's escalation
#: and breaker records, in the order they were requested.
_SELECT_RUN_ESCALATIONS = (
    "SELECT request_id, submission_id, criterion_id, admitted, requested_at, detail "
    "FROM escalation_request WHERE run_id = :run_id ORDER BY requested_at, request_id"
)


_SELECT_RUN_BREAKERS = (
    "SELECT breaker_id, criterion_id, kind, tripped_at, detail "
    "FROM circuit_breaker WHERE run_id = :run_id ORDER BY tripped_at, breaker_id"
)


#: The parked papers, across the cohort files: the quarantine flag's rows with the
#: diagnosis and the identity evidence beside each (`_SELECT_QUARANTINE`'s scope, plus the
#: columns the parked read needs to say who the paper matched, or why it could not).
_SELECT_PARKED_PAPERS = (
    "SELECT submission_id, cohort_id, ingest_status, v3_identity, student_ref "
    "FROM submission WHERE quarantined = 1 ORDER BY submission_id"
)


#: A ledger's population counts, roster first (`FR-CONSOLE-44`'s safe form: the roster is
#: the class list; submissions are the papers that arrived) plus its run count — the three
#: numbers the context read derives a ledger's kind and state from.
_SELECT_LEDGER_POPULATION = (
    "SELECT (SELECT COUNT(*) FROM roster) AS roster_n, "
    "(SELECT COUNT(*) FROM submission) AS papers_n, "
    "(SELECT COUNT(*) FROM run) AS runs_n"
)


#: The versions of one package, with the published flag: the context read's package
#: entities and their wizard state.
_SELECT_PACKAGE_VERSIONS = (
    "SELECT package_version_id, locked FROM package_version ORDER BY package_version_id"
)


#: The runs a package version graded, and how many students it has already reached
#: (FR-CONSOLE-49's impact read): the current grades of every run over that version.
_SELECT_VERSION_RUNS = (
    "SELECT run_id, cohort_id, status, started_at FROM run "
    "WHERE package_version_id = :package_version_id ORDER BY run_id"
)


_SELECT_VERSION_REACHED_STUDENTS = (
    "SELECT COUNT(DISTINCT g.submission_id) AS n FROM submission_grade g "
    "JOIN run r ON r.run_id = g.run_id "
    "WHERE r.package_version_id = :package_version_id AND g.is_current = 1"
)


#: The run's current grades still short of `final`: what separates the reviewing stage
#: from the exporting one in the context read's stage derivation.
_SELECT_RUN_UNFINALIZED = (
    "SELECT COUNT(*) AS n FROM submission_grade "
    "WHERE run_id = :run_id AND is_current = 1 AND state != 'final'"
)


#: The run's papers holding a current grade: the jobs read's per-job `items graded`
#: figure (FR-CONSOLE-52), read from the ledger that holds the run.
_SELECT_RUN_GRADED_STUDENTS = (
    "SELECT COUNT(DISTINCT submission_id) AS n FROM submission_grade "
    "WHERE run_id = :run_id AND is_current = 1"
)
