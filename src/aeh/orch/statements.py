"""The SQL statements M-ORCH runs."""

from __future__ import annotations

from aeh.store import Statement


ORCH_STATEMENTS: dict[str, Statement] = {
    "insert_run": Statement(
        "INSERT INTO run (run_id, cohort_id, package_version_id, package_id, "
        "panel_config, backend_profile, provider_config, prompt_template_v, status, "
        "run_config) "
        "VALUES (:run_id, :cohort_id, :package_version_id, :package_id, :panel_config, "
        ":backend_profile, :provider_config, :prompt_template_v, 'pending', :run_config)"
    ),
    # The run-row read carries the lifecycle columns #61 added (`cost_estimate`,
    # `cost_spend`, `pause_reason`) beside the frozen backend snapshot — the ceiling is
    # enforced from the row's OWN figures, never from current configuration.
    "select_run": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status, started_at, "
        "completed_at, cost_estimate, cost_spend, pause_reason "
        "FROM run WHERE run_id = :run_id"
    ),
    # The runs resume() may drive: everything not yet finished. Ordered by run_id so two
    # enumerations of the same state walk the same rows in the same order (NFR-ORCH-05).
    "select_open_runs": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status, started_at, "
        "completed_at, cost_estimate, cost_spend, pause_reason "
        "FROM run WHERE status IN ('pending', 'running', 'paused') "
        "ORDER BY run_id"
    ),
    # The same columns with no status filter: `recover` (FR-PIPE-07) has to find runs that are
    # COMPLETE but whose grades are not all final, and those are exactly the runs
    # `select_open_runs` excludes. Filtering in Python rather than in SQL keeps one statement
    # for every status a caller might ask about.
    # The cohort's declared consent class (`ADR-5`). `M-PIPE` needs it to build the `CohortRef`
    # `resolve_run_config` gates on: `CohortRef` defaults to `'real'` and that default is
    # fail-closed by design, so a caller that does not read the stored value refuses every
    # synthetic cohort against a remote backend (`FR-CONF-08`).
    # Rewrite ONLY the recorded reason on a run that is already paused. `pause()` deliberately
    # changes nothing in that case — an operator double-pausing must not manufacture a state
    # flip — but a run refused for a NEW cause needs the new cause on the row, or the operator
    # surface explains the stop with a reason that is no longer why.
    "update_pause_reason": Statement(
        "UPDATE run SET pause_reason = :pause_reason "
        "WHERE run_id = :run_id AND status = 'paused'"
    ),
    # One unit's ledger status. A stage door may terminalise its own unit — `M-EXTRACT`'s
    # worker quarantines at the strike ceiling and RETURNS rather than raising — and the
    # composition layer has to know that before it reports the unit completed, because
    # `complete()` refuses a unit a worker already quarantined.
    "select_unit_status": Statement(
        "SELECT status FROM work_unit WHERE work_id = :work_id"
    ),
    "select_cohort_row": Statement(
        "SELECT cohort_id, consent_class FROM cohort WHERE cohort_id = :cohort_id"
    ),
    # -- creating a cohort and its roster (live-test blocker B3, `cohorts.py`) ------------------------
    "select_cohort_ids": Statement("SELECT cohort_id FROM cohort ORDER BY cohort_id"),
    "select_cohort_created": Statement(
        "SELECT consent_class, created_at FROM cohort WHERE cohort_id = :cohort_id"
    ),
    "insert_cohort": Statement(
        "INSERT INTO cohort (cohort_id, consent_class, created_at) "
        "VALUES (:cohort_id, :consent_class, :created_at)"
    ),
    "insert_roster_entry": Statement(
        "INSERT INTO roster (cohort_id, student_ref, full_name) "
        "VALUES (:cohort_id, :student_ref, :full_name)"
    ),
    "select_roster_refs": Statement(
        "SELECT student_ref FROM roster WHERE cohort_id = :cohort_id ORDER BY student_ref"
    ),
    "select_all_runs": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status, started_at, "
        "completed_at, cost_estimate, cost_spend, pause_reason "
        "FROM run ORDER BY run_id"
    ),
    "select_run_work_ids": Statement(
        "SELECT work_id FROM work_unit WHERE run_id = :run_id"
    ),
    # FR-ORCH-42 (#523): every submission the run enumerated, in enumeration order (first
    # unit written), whatever its criteria's evaluation modes: a deterministic-only
    # submission has only `deterministic` units and is still listed.
    "select_run_enumerated_submissions": Statement(
        "SELECT submission_id FROM work_unit WHERE run_id = :run_id "
        "GROUP BY submission_id ORDER BY MIN(rowid)"
    ),
    "select_submissions": Statement(
        "SELECT submission_id, student_ref, ingest_status, v3_identity FROM submission "
        "WHERE cohort_id = :cohort_id ORDER BY submission_id"
    ),
    "select_run_counts": Statement(
        "SELECT stage, status, COUNT(*) AS n FROM work_unit WHERE run_id = :run_id "
        "GROUP BY stage, status"
    ),
    "insert_work_unit": Statement(
        "INSERT OR IGNORE INTO work_unit "
        "(work_id, submission_id, stage, status, run_id, criterion_id, judge_id, "
        "origin, attempts) "
        "VALUES (:work_id, :submission_id, :stage, 'pending', :run_id, :criterion_id, "
        ":judge_id, :origin, 0)"
    ),
    # Read inside the same transaction as each `insert_work_unit`: the ledger's own
    # count of what that write did, since `OR IGNORE` reports neither an ignored
    # duplicate nor a refused row.
    "select_changes": Statement("SELECT changes() AS n"),
    "insert_audit_record": Statement(
        "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, profile_summary) "
        "VALUES (:audit_record_id, :run_id, :recorded_at, :profile_summary)"
    ),
    # -- leasing (FR-ORCH-04) ------------------------------------------------------------------
    # Claim candidates: pending units of one stage **of one run** (a paused run schedules
    # nothing — CT-ORCH-12 — and #59's claim pass walks open runs individually, because
    # the dispatch order is a function of the run's own package). Ordered by work_id as
    # the base order — the stage's sweep key is applied over these rows in Python, where
    # the run's catalog lives; work_id is the deterministic tie-break beneath every key.
    # Unbounded per read, on purpose: the sweep order must choose from ALL pending
    # candidates of the run, and a SQL LIMIT applied before the Python order would
    # truncate by work_id and silently mis-order the sweep. What keeps the fine-grained
    # drain off the quadratic (NFR-ORCH-01) is not a LIMIT here but `_claim_pass`'s
    # order cache: the sorted result is derived once and drained front to back, so a
    # one-at-a-time poll late in a large run serves its head instead of re-reading and
    # re-sorting the whole pending set.
    # The roster join (#593, NFR-PROV-08): the claimed row carries the student's roster
    # display name beside the ref, so the boundary (`M-JUDGE`'s assembler) HAS a name to
    # replace. LEFT join on the roster's own key — a ref the roster does not hold, or
    # holds namelessly (a pre-migration row), yields NULL, and the assembler passes the
    # request through unchanged. A ref-only or nameless roster is the pre-#620 shape and
    # must keep assembling today's bytes.
    "select_run_claimable": Statement(
        "SELECT w.work_id, w.run_id, w.stage, w.submission_id, w.criterion_id, "
        "w.judge_id, w.origin, w.attempts AS attempt, s.student_ref AS student_ref, "
        "r.full_name AS student_name "
        "FROM work_unit w "
        "JOIN submission s ON s.submission_id = w.submission_id "
        "LEFT JOIN roster r ON r.cohort_id = s.cohort_id "
        "AND r.student_ref = s.student_ref "
        "WHERE w.run_id = :run_id AND w.status = 'pending' AND w.stage = :stage "
        "ORDER BY w.work_id"
    ),
    # The Sweep 2 gate's read (`FR-ORCH-06`): the extraction units of the run that are
    # not done — pending, leased, or quarantined. A score unit is claimable only when
    # neither its own criterion's extraction nor any dependency's is in this set. One
    # indexed query per run per claim pass; the set it returns is what the gate diffs.
    "select_not_done_extracts": Statement(
        "SELECT criterion_id, submission_id FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'extract' AND status != 'done'"
    ),
    "select_work_unit_row": Statement(
        "SELECT * FROM work_unit WHERE work_id = :work_id"
    ),
    # --- #362 (FR-ORCH-28/29/30): the per-cell composition phases -----------------------------
    "upsert_cell_phase": Statement(
        "INSERT INTO cell_phase (run_id, submission_id, criterion_id, phase, "
        "units_consumed, recorded_at) VALUES (:run_id, :submission_id, :criterion_id, "
        ":phase, :units_consumed, :recorded_at) "
        "ON CONFLICT (run_id, submission_id, criterion_id, phase) DO UPDATE SET "
        "units_consumed = excluded.units_consumed, recorded_at = excluded.recorded_at"
    ),
    "select_cell_phases": Statement(
        "SELECT submission_id, criterion_id, phase, units_consumed FROM cell_phase "
        "WHERE run_id = :run_id"
    ),
    # One row per (cell, stage) with its terminal and total unit counts — `ready_cells`'
    # whole input beside the phases. Terminal is `done` or `quarantined`: a quarantined unit
    # will not produce more evidence, so a cell waiting on it would wait forever.
    "select_cell_unit_counts": Statement(
        "SELECT submission_id, criterion_id, stage, "
        "SUM(CASE WHEN status IN ('done', 'quarantined') THEN 1 ELSE 0 END) AS terminal, "
        "SUM(CASE WHEN status = 'quarantined' THEN 1 ELSE 0 END) AS quarantined, "
        "COUNT(*) AS total FROM work_unit WHERE run_id = :run_id "
        "GROUP BY submission_id, criterion_id, stage"
    ),
    # --- #597 (NFR-PIPE-02): the readiness decision runs IN SQL -------------------------------
    #
    # The Python-side scan (`_ready_cells_in` before #597) read every count row and every
    # phase row of the run into dicts on every pass, and a pass's hook then touched only the
    # few cells the run's concurrency cap allows. At 40 submissions that is a 13.9 ms read
    # twice per pass over a 9.3 ms/unit composition budget. The GROUP BY + HAVING forms here
    # decide readiness where the rows live: the same index range is walked in C, and only the
    # ready cells — a handful per pass — are materialized. `ready_cells`' exact semantics
    # (FR-ORCH-29): every unit of the cell's stage terminal, and either no phase row yet
    # (`integrity_pre`) or more terminal units than the `aggregated` phase consumed
    # (`aggregate` — the count comparison that re-aggregates a widened panel).
    #
    # Two literals rather than one parameterized shape because the two hooks' phase arms
    # genuinely differ: `integrity_pre` is ready only while the phase is ABSENT, `aggregate`
    # is ready when absent or outgrown. Assembling that difference at run time is exactly what
    # SEC-15/FR-STORE-08 refuses.
    "select_ready_integrity_pre": Statement(
        "SELECT w.submission_id AS submission_id, w.criterion_id AS criterion_id, "
        "SUM(CASE WHEN w.status IN ('done', 'quarantined') THEN 1 ELSE 0 END) AS terminal, "
        "SUM(CASE WHEN w.status = 'quarantined' THEN 1 ELSE 0 END) AS quarantined, "
        "COUNT(*) AS total "
        "FROM work_unit w LEFT JOIN cell_phase p "
        "ON p.run_id = w.run_id AND p.submission_id = w.submission_id "
        "AND p.criterion_id = w.criterion_id AND p.phase = 'integrity_pre' "
        "WHERE w.run_id = :run_id AND w.stage = 'extract' "
        "GROUP BY w.submission_id, w.criterion_id "
        "HAVING SUM(CASE WHEN w.status IN ('done', 'quarantined') THEN 1 ELSE 0 END) "
        "= COUNT(*) AND p.units_consumed IS NULL "
        "ORDER BY w.submission_id, w.criterion_id"
    ),
    "select_ready_aggregate": Statement(
        "SELECT w.submission_id AS submission_id, w.criterion_id AS criterion_id, "
        "SUM(CASE WHEN w.status IN ('done', 'quarantined') THEN 1 ELSE 0 END) AS terminal, "
        "SUM(CASE WHEN w.status = 'quarantined' THEN 1 ELSE 0 END) AS quarantined, "
        "COUNT(*) AS total "
        "FROM work_unit w LEFT JOIN cell_phase p "
        "ON p.run_id = w.run_id AND p.submission_id = w.submission_id "
        "AND p.criterion_id = w.criterion_id AND p.phase = 'aggregated' "
        "WHERE w.run_id = :run_id AND w.stage = 'score' "
        "GROUP BY w.submission_id, w.criterion_id "
        "HAVING SUM(CASE WHEN w.status IN ('done', 'quarantined') THEN 1 ELSE 0 END) "
        "= COUNT(*) AND (p.units_consumed IS NULL OR "
        "SUM(CASE WHEN w.status IN ('done', 'quarantined') THEN 1 ELSE 0 END) "
        "> p.units_consumed) "
        "ORDER BY w.submission_id, w.criterion_id"
    ),
    # The provenance join (#223, FR-INGEST-01): unit -> submission -> document, LEFT-joined
    # so a broken hop reads as NULL here and is refused by `provenance()`, never imputed.
    # One row per document of the submission, oldest first; the head is the last row, the
    # same ordering `M-INGEST`'s `select_document_head` defines.
    "select_unit_provenance": Statement(
        "SELECT w.work_id, w.run_id, w.stage, w.submission_id, "
        "s.submission_id AS joined_submission_id, d.document_id, d.content_hash "
        "FROM work_unit w "
        "LEFT JOIN submission s ON s.submission_id = w.submission_id "
        "LEFT JOIN document d ON d.submission_id = s.submission_id "
        "WHERE w.work_id = :work_id "
        "ORDER BY d.created_at, d.document_id"
    ),
    # The document a unit's text was actually READ from, once extraction has run: the
    # evidence rows it wrote carry the document_id of the head at that moment.
    "select_unit_evidence_documents": Statement(
        "SELECT DISTINCT document_id FROM evidence "
        "WHERE work_id = :work_id AND document_id IS NOT NULL ORDER BY document_id"
    ),
    # The one-row existence probe behind lease()'s enumerate-on-empty gate: a run whose
    # ledger holds *any* row was enumerated (or partially so, which is a crash
    # `resume()` repairs) — re-enumerating it on every drained poll would make the
    # hot claim path a full enumeration pass (NFR-ORCH-01).
    "select_any_work_unit": Statement(
        "SELECT work_id FROM work_unit WHERE run_id = :run_id LIMIT 1"
    ),
    "select_leased_units": Statement(
        "SELECT w.work_id, w.run_id, w.lease_expires_ticks FROM work_unit w "
        "JOIN run r ON r.run_id = w.run_id "
        "WHERE w.status = 'leased' AND r.status IN ('pending', 'running') "
        "ORDER BY w.work_id"
    ),
    # The claim: pending → leased, guarded on `status = 'pending'` so two claimers
    # cannot both win. `changes()` read in the same transaction says whether THIS write
    # won — the lease-clock expiry was persisted before the attempt, so a lost guard is
    # a no-op here and a slightly-raised counter there (see lease()'s docstring).
    "mark_leased": Statement(
        "UPDATE work_unit SET status = 'leased', lease_owner = :owner, "
        "lease_expires_ticks = :expires_ticks, lease_expires_at = :expires_at "
        "WHERE work_id = :work_id AND status = 'pending'"
    ),
    # The heartbeat: extends a live lease's expiry only. `:owner IS NULL OR` makes the
    # owner check optional — a caller naming its worker_id cannot extend a lease another
    # worker holds, and an unnamed heartbeat is still guarded on `leased`. The guard
    # makes a lost lease a zero-row write, which the caller detects via `changes()`.
    "extend_lease": Statement(
        "UPDATE work_unit SET lease_expires_ticks = :expires_ticks, "
        "lease_expires_at = :expires_at "
        "WHERE work_id = :work_id AND status = 'leased' "
        "AND (:owner IS NULL OR lease_owner = :owner)"
    ),
    # The sweeper's requeue: expired lease → pending, lease columns cleared. Attempts
    # survive the round-trip: the unit's failure history is not the lease's.
    "requeue_expired": Statement(
        "UPDATE work_unit SET status = 'pending', lease_owner = NULL, "
        "lease_expires_ticks = NULL, lease_expires_at = NULL "
        "WHERE work_id = :work_id AND status = 'leased'"
    ),
    "mark_done": Statement(
        "UPDATE work_unit SET status = 'done', lease_owner = NULL, "
        "lease_expires_ticks = NULL, lease_expires_at = NULL, "
        "done_ticks = :done_ticks "
        "WHERE work_id = :work_id AND status IN ('leased', 'pending')"
    ),
    # The failure taxonomy: requeue with the attempt counted, or quarantine at the
    # ceiling — last_error retained in both arms, lease columns cleared. The count and
    # the status arm are computed **inside the statement** (`attempts + 1`; every SET
    # expression sees the pre-update row), so two failure reports cannot both read the
    # same count and write the same increment — one attempt can never be lost, and
    # quarantine lands on the report that actually reaches the ceiling.
    "record_failure": Statement(
        "UPDATE work_unit SET "
        "status = CASE WHEN attempts + 1 >= :max_attempts THEN 'quarantined' "
        "ELSE 'pending' END, "
        "attempts = attempts + 1, "
        "last_error = :last_error, lease_owner = NULL, "
        "lease_expires_ticks = NULL, lease_expires_at = NULL "
        "WHERE work_id = :work_id AND status IN ('leased', 'pending')"
    ),
    # -- escalation, the random arm and the breakers (FR-ORCH-09/10/11/13/14) ------------------
    # The criterion's judges for one (submission, criterion): every score unit's judge,
    # whatever its origin — the base panel, the random arm's widening and a prior
    # escalation rung are all the panel the criterion now has. Ordered by work_id so the
    # prior-judge list is deterministic (the plan's derivation reads it).
    "select_pair_score_judges": Statement(
        "SELECT judge_id FROM work_unit "
        "WHERE run_id = :run_id AND submission_id = :submission_id "
        "AND criterion_id = :criterion_id AND stage = 'score' ORDER BY work_id"
    ),
    # The criterion breaker's window (`FR-ORCH-13`): the submissions whose judged
    # scoring for one criterion completed EARLIEST, by the monotonic completion ticks.
    # Rows without ticks are order-unknown and excluded — the window is the first N
    # the ledger can honestly order. MIN(), not bare completion, because a submission's
    # panel completes unit by unit; its processing moment is its FIRST verdict.
    "select_criterion_window": Statement(
        "SELECT submission_id, MIN(done_ticks) AS first_done FROM work_unit "
        "WHERE run_id = :run_id AND criterion_id = :criterion_id "
        "AND stage = 'score' AND judge_id IS NOT NULL AND status = 'done' "
        "AND done_ticks IS NOT NULL "
        "GROUP BY submission_id ORDER BY first_done ASC, submission_id ASC LIMIT :n"
    ),
    # The escalation pairs of one criterion: distinct submissions with at least one
    # escalation-origin unit. The breaker intersects this with its window.
    "select_criterion_escalated": Statement(
        "SELECT DISTINCT submission_id FROM work_unit "
        "WHERE run_id = :run_id AND criterion_id = :criterion_id "
        "AND origin = 'escalation'"
    ),
    # One pair's escalation count — the idempotence probe: an enqueue for a pair that
    # already carries escalation-origin units is a no-op, whatever path widened it.
    "select_pair_escalated": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND submission_id = :submission_id "
        "AND criterion_id = :criterion_id AND origin = 'escalation'"
    ),
    # The run-wide budget's OBSERVED rate (`FR-ORCH-14`): distinct (submission,
    # criterion) pairs whose judged scoring has completed, and pairs whose escalation
    # has completed. Both sides are done-based because the rate is an observation —
    # an escalation whose panel is still running has produced no outcome to count,
    # and counting plans instead of outcomes would defer the very units the budget
    # exists to carry (a run's first escalated pair would read as a 100% rate). Both
    # are indexed aggregates over the run's score units, never a side-file counter
    # (the ledger is the only bookkeeping, FR-ORCH-02). `idx_wu_pairs` (the report
    # indexes' migration) carries the processed side: its (status, stage) range
    # precedes the (submission_id, criterion_id) pair, so the DISTINCT streams in
    # index order instead of temp-sorting every done score unit per poll.
    "select_processed_results": Statement(
        "SELECT COUNT(*) AS n FROM (SELECT DISTINCT submission_id, criterion_id "
        "FROM work_unit WHERE run_id = :run_id AND stage = 'score' "
        "AND judge_id IS NOT NULL AND status = 'done')"
    ),
    "select_escalated_results": Statement(
        "SELECT COUNT(*) AS n FROM (SELECT DISTINCT submission_id, criterion_id "
        "FROM work_unit WHERE run_id = :run_id AND origin = 'escalation' "
        "AND status = 'done')"
    ),
    # The escalation record (`FR-ORCH-14`). A request is content-addressed (see the
    # migration note) and INSERT OR IGNORE'd, so a retried enqueue cannot record a
    # rung twice; the row carries the caller's expected value, which is the ranking
    # key the dispatch-time admission consumes. The enqueue flips `admitted` once its
    # units are written — the flag records "this request's units are in the ledger",
    # not a budget decision: the budget rations DISPATCH (`admit_escalations` at the
    # claim pass), because the atomicity clause (`CT-ORCH-08`) has the enqueue write
    # the plan into the verdict's transaction whatever the budget is doing.
    "insert_escalation_request": Statement(
        "INSERT OR IGNORE INTO escalation_request "
        "(request_id, run_id, submission_id, criterion_id, expected_value, "
        "admitted, requested_at, detail) "
        "VALUES (:request_id, :run_id, :submission_id, :criterion_id, "
        ":expected_value, 0, :requested_at, :detail)"
    ),
    "select_queue_depth": Statement(
        "SELECT COUNT(*) AS n FROM escalation_request "
        "WHERE run_id = :run_id AND admitted = 0"
    ),
    # The dispatch gate's read (`FR-ORCH-14`): the run's pending escalation pairs with
    # their request's expected value (0.0 when the request row is absent — the arm
    # never writes one and a lost row must not rank above a valued one). This is the
    # candidate list `admit_escalations` evaluates at claim time; the provisional
    # half is the remainder `FR-ORCH-14` marks.
    "select_pending_escalation_pairs": Statement(
        "SELECT w.submission_id, w.criterion_id, "
        "COALESCE(q.expected_value, 0.0) AS expected_value "
        "FROM work_unit w "
        "LEFT JOIN escalation_request q "
        "ON q.run_id = w.run_id AND q.submission_id = w.submission_id "
        "AND q.criterion_id = w.criterion_id "
        "WHERE w.run_id = :run_id AND w.origin = 'escalation' "
        "AND w.status = 'pending' "
        "GROUP BY w.submission_id, w.criterion_id, q.expected_value"
    ),
    # The deprecated two-element key's resolution (FR-ORCH-34, CT-ORCH-26): the runs
    # whose ledger holds the pair's score panel, open runs flagged. Exactly one
    # candidate resolves; two or more are ambiguous and refused — a key that names no
    # run must not widen every run's panel.
    "select_pair_runs": Statement(
        "SELECT DISTINCT w.run_id, "
        "r.status IN ('pending', 'running', 'paused') AS is_open "
        "FROM work_unit w JOIN run r ON r.run_id = w.run_id "
        "WHERE w.submission_id = :submission_id AND w.criterion_id = :criterion_id "
        "AND w.stage = 'score' ORDER BY w.run_id"
    ),
    # The three-element key's check: the named run's ledger holds the pair's panel.
    "select_run_pair_panel": Statement(
        "SELECT 1 FROM work_unit WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND criterion_id = :criterion_id "
        "AND stage = 'score' LIMIT 1"
    ),
    # FR-ORCH-43 (#524): the pair's quarantined score units — how many arms quarantine
    # has cost the panel — and whether a content-addressed request row already exists.
    "select_pair_quarantined_score_units": Statement(
        "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND criterion_id = :criterion_id "
        "AND stage = 'score' AND status = 'quarantined'"
    ),
    "select_request_exists": Statement(
        "SELECT COUNT(*) AS n FROM escalation_request WHERE request_id = :request_id"
    ),
    "admit_request": Statement(
        "UPDATE escalation_request SET admitted = 1, admitted_at = :admitted_at, "
        "detail = :detail WHERE request_id = :request_id AND admitted = 0"
    ),
    # The breaker latch (`FR-ORCH-13`): content-addressed, INSERT OR IGNORE — a
    # criterion trips once; a second trip evaluation cannot rewrite the first event.
    "insert_breaker": Statement(
        "INSERT OR IGNORE INTO circuit_breaker "
        "(breaker_id, run_id, criterion_id, kind, tripped_at, detail) "
        "VALUES (:breaker_id, :run_id, :criterion_id, 'criterion_escalation', "
        ":tripped_at, :detail)"
    ),
    "select_breaker": Statement(
        "SELECT breaker_id, criterion_id, kind, tripped_at, detail "
        "FROM circuit_breaker WHERE run_id = :run_id AND criterion_id = :criterion_id "
        "AND kind = 'criterion_escalation'"
    ),
    "select_run_breakers": Statement(
        "SELECT criterion_id, kind, tripped_at, detail FROM circuit_breaker "
        "WHERE run_id = :run_id ORDER BY criterion_id ASC, kind ASC"
    ),
    # -- the run lifecycle and the cost ceiling (FR-ORCH-15/16/17/25, #61) -----------------------
    # start()'s edge: pending → running, stamping started_at. The guard makes every
    # undeclared edge a zero-row write the caller detects via changes() — the machine
    # never moves along an edge FR-ORCH-25 does not declare.
    "transition_run_started": Statement(
        "UPDATE run SET status = 'running', started_at = :started_at, "
        "pause_reason = NULL, completed_at = NULL "
        "WHERE run_id = :run_id AND status = 'pending'"
    ),
    # The lifecycle's guarded transition, shared by pause/resume/complete: the
    # from_status guard IS the transition matrix's enforcement — a request from a
    # state the machine does not declare the edge from writes nothing.
    "transition_run_status": Statement(
        "UPDATE run SET status = :to_status, pause_reason = :pause_reason, "
        "completed_at = :completed_at "
        "WHERE run_id = :run_id AND status = :from_status"
    ),
    # The orchestrator's own sensed pauses (cost ceiling reached mid-dispatch): from
    # either dispatchable state, never from a terminal one. The reason text is the
    # alert — the pause names its spend and what remains (FR-ORCH-15).
    "pause_run_sensed": Statement(
        "UPDATE run SET status = 'paused', pause_reason = :pause_reason, "
        "completed_at = NULL "
        "WHERE run_id = :run_id AND status IN ('running', 'pending')"
    ),
    "accrue_run_spend": Statement(
        "UPDATE run SET cost_spend = :cost_spend WHERE run_id = :run_id"
    ),
    "set_run_estimate": Statement(
        "UPDATE run SET cost_estimate = :cost_estimate WHERE run_id = :run_id"
    ),
    "count_run_pending": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND status = 'pending'"
    ),
    # The completion probe's read (FR-ORCH-12): a run completes when nothing is
    # pending and nothing is in flight. Quarantined units hold the run open only
    # through the scoring they gated (their score units stay pending).
    "select_run_open_units": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND status IN ('pending', 'leased')"
    ),
    # The estimate's units: everything the run may still dispatch, one row per unit
    # with the seam's keys (the same shape the claim select hands over).
    "select_run_units_for_estimate": Statement(
        "SELECT w.work_id, w.run_id, w.stage, w.submission_id, w.criterion_id, "
        "w.judge_id, w.origin, w.attempts AS attempt, s.student_ref AS student_ref "
        "FROM work_unit w "
        "JOIN submission s ON s.submission_id = w.submission_id "
        "WHERE w.run_id = :run_id AND w.status IN ('pending', 'leased') "
        "ORDER BY w.work_id"
    ),
    # -- the control rows (CT-ORCH-13) ------------------------------------------------------------
    # A control action WRITES a row; the orchestrator EFFECTS it when it reads one —
    # the request is never the effect. A row written while no orchestrator is reading
    # queues (applied_at NULL) and is honoured at the next read: start, resume, or a
    # claim pass of a run that is actively dispatching.
    "insert_run_control": Statement(
        "INSERT INTO run_control "
        "(control_id, run_id, action, reason, requested_at) "
        "VALUES (:control_id, :run_id, :action, :reason, :requested_at)"
    ),
    "select_unapplied_control": Statement(
        "SELECT control_id, action, reason, requested_at FROM run_control "
        "WHERE run_id = :run_id AND applied_at IS NULL "
        "ORDER BY requested_at ASC, control_id ASC"
    ),
    #: `FR-ORCH-33`: the APPLIED controls, in the order they took effect. The wall clock
    #: subtracts paused intervals, and an interval is a pause that actually happened —
    #: `applied_at`, not `requested_at`: a pause requested and superseded before it ever
    #: applied never stopped the clock, and subtracting it would under-report the work.
    "select_applied_control": Statement(
        "SELECT control_id, action, applied_at FROM run_control "
        "WHERE run_id = :run_id AND applied_at IS NOT NULL "
        "ORDER BY applied_at ASC, control_id ASC"
    ),
    "mark_control_applied": Statement(
        "UPDATE run_control SET applied_at = :applied_at "
        "WHERE control_id = :control_id AND applied_at IS NULL"
    ),
    # A later resume supersedes the pause requests queued before it (latest control
    # intent wins): superseded pause rows are marked applied so the next start does
    # not pause a run the operator already resumed.
    "mark_pauses_applied": Statement(
        "UPDATE run_control SET applied_at = :applied_at "
        "WHERE run_id = :run_id AND action = 'pause' AND applied_at IS NULL"
    ),
    # The same supersede, bounded by request time: a resume supersedes only the
    # pauses queued BEFORE it — a pause requested after the resume is a later
    # intent, and marking it applied here would drop a request that was never
    # effected (it would be honoured at its own pass otherwise).
    "mark_pauses_applied_before": Statement(
        "UPDATE run_control SET applied_at = :applied_at "
        "WHERE run_id = :run_id AND action = 'pause' AND applied_at IS NULL "
        "AND requested_at < :requested_at"
    ),
    # -- progress, dispatch and run metrics (#62/#66) -------------------------------------------
    # The report's status totals: one GROUP BY over the run's rows. The ledger is the
    # only bookkeeping (FR-ORCH-02), so the report counts rows — never side-file
    # counters, which is what makes it right on a ledger that is growing underneath the
    # poll (CT-ORCH-09).
    "select_run_status_counts": Statement(
        "SELECT status, COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id GROUP BY status"
    ),
    # The report's (stage, criterion, judge) counts — FR-ORCH-23's granularity. One row
    # per distinct triple over ALL the run's units (judge NULL for extract and
    # deterministic units), so the counts sum to the ledger exactly (TC-ORCH-31).
    # The report's criterion axis rides the same aggregate: the distinct criteria the
    # run's ledger holds are exactly the criterion members of these groups, so one
    # pass feeds both and no second ledger scan is spent on the same set.
    "select_run_by_unit": Statement(
        "SELECT stage, criterion_id, judge_id, COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id GROUP BY stage, criterion_id, judge_id"
    ),
    # The first open unit, for the report's position fields (stage first with open
    # work, then its criterion and judge positions). The pick is the schedule
    # order `idx_wu_sched` already keeps — (status, stage, criterion_id), in-flight
    # first — not `work_id` order: an ordered probe down that index reads a
    # handful of entries where an `ORDER BY work_id` scan read the ledger's head
    # on every poll (the 40k-scaling degradation NFR-ORCH-06 exists to prevent).
    # No case pins WHICH open unit is pointed at — the position fields are coarse
    # operator pointers, and this reading is the one the index serves.
    "select_run_first_open": Statement(
        "SELECT stage, criterion_id, judge_id FROM work_unit "
        "WHERE run_id = :run_id AND status IN ('pending', 'leased') "
        "ORDER BY status, stage, criterion_id LIMIT 1"
    ),
    # The residency boundary's check (FR-ORCH-19): whether the resident judge still
    # holds score work **in flight** — its batch, the units already handed out for it.
    # A swap fires only when the answer is no: unloading a model whose judgments are
    # still running is the thrash the residency policy exists to prevent. Pending
    # units do not count — gated or budget-deferred work is not dispatchable (it may
    # never become ready without an operator), so it is no batch's tail; when it does
    # become ready the model reloads to serve it.
    "select_judge_leased_units": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'score' AND judge_id = :judge_id "
        "AND status = 'leased'"
    ),
    # The score units in flight: the completion predicate's second clause
    # (FR-ORCH-12) — a scoring judgment in flight can still disagree with its panel
    # and spawn an escalation.
    "select_run_leased_score": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'score' AND status = 'leased'"
    ),
    # The run's escalation-origin units (any status) — the escalated-units metric's
    # numerator is the ledger's own rows (FR-ORCH-02).
    "select_run_escalation_units": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND origin = 'escalation'"
    ),
    # The run-metrics write (CT-ORCH-20 makes the names contract): one EAV row per
    # metric, REPLACE so a re-flush updates in place. M-ORCH is the sole writer
    # (CT-STORE-03's single-writership: the orchestrator owns what the run did).
    #: `FR-ORCH-32`: the cache hit rates OTHER runs recorded — this run's baseline. Its
    #: own row is excluded, or the current figure would be part of the mean it is being
    #: compared against and a collapse would partly hide itself.
    "select_prior_cache_hit_rates": Statement(
        "SELECT value FROM run_metrics WHERE metric = 'cache_hit_rate' "
        "AND run_id <> :run_id ORDER BY run_id"
    ),
    #: `FR-ORCH-33`: this run's already-recorded metrics, so a flush can EXTEND a set
    #: rather than replace it with whatever this process happened to observe. Tier D.
    "select_run_metric_values": Statement(
        "SELECT metric, value FROM run_metrics WHERE run_id = :run_id ORDER BY metric"
    ),
    "insert_run_metric": Statement(
        "INSERT OR REPLACE INTO run_metrics (run_id, metric, value) "
        "VALUES (:run_id, :metric, :value)"
    ),
    # The OOM remedy's panel record (RES-13): the reduced panel is written to the run
    # row as a strict subset — a later validation record cannot claim the full panel
    # the box could not hold.
    "record_reduced_panel": Statement(
        "UPDATE run SET panel_config = :panel_config WHERE run_id = :run_id"
    ),
}
