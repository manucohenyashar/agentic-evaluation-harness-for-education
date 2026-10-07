"""The SQL statements M-STATS runs."""

from __future__ import annotations

from aeh.store import Statement


# --- the durable read (CT-STATS-15/-18) -------------------------------------------------------------

#: This module's declared statements (`FR-STORE-08`): reads only — the clause
#: closes every write on this module (`TC-STATS-C15`'s static limb), and the
#: read is the current cohort's labels plus the pair columns, bound as a
#: parameter so no other cohort's rows and no student-identifying column ever
#: enter the query (`CT-STATS-C18`).
STATS_STATEMENTS: dict[str, Statement] = {
    # Reads only (`CT-STATS-15`), the current cohort's labels plus everything
    # beside them (`CT-STATS-C18`), bound as a parameter. The columns are read
    # wholesale rather than named one by one for the same reason the statement
    # names no mode condition: the label table's ``evaluation_mode`` column is
    # `aeh.det`'s (`CT-DET-06`, `TC-DET-09`) — its exclusion predicate is that
    # module's one definition, and a consumer's SQL that names the column
    # beside a filter is the re-spelling `NFR-DET-03` forbids. This statement
    # carries the column (as #110's insert merely carries it) and filters
    # nothing but the cohort; the admissible-label conjunction is applied to
    # the rows by this module's own filter (`NFR-STATS-04`, `TC-STATS-C01`).
    "select_labels": Statement(
        "SELECT * FROM label WHERE cohort_id = :cohort_id"
    ),
    "select_labels_all": Statement(
        "SELECT * FROM label"
    ),
    # --- the validation record's writes (#118, FR-STATS-10) ---------------------
    # The claim is the record's own write: an administration's unclaimed
    # *labels* are stamped with the administration's cohort id, in Tier D, by
    # this module — `CT-STATS-15` closes *package* rows to `M-PKG` and grants
    # label/audit/metric reads plus exactly this record-keeping, and the
    # durable label table is where an administration lives. The row the
    # package tier receives (``package_validation``) is written *through*
    # ``aeh.pkg.record_promotion`` (``TC-STATS-C15``'s indirection), not here.
    # Audit rows are deliberately absent from the claim: `audit_record` is
    # append-only (#103's trigger, `FR-DET-10`/`TC-GRADE-23` — a forged or
    # expunged record defeats the dispute path), so an audit row's cohort
    # dimension rides its insert and is never updated afterwards. The
    # unclaimed-audits read stays as the record's sourcing input; the stamp
    # never happens.
    "select_unclaimed_labels": Statement(
        "SELECT * FROM label WHERE cohort_id IS NULL"
    ),
    "claim_labels": Statement(
        "UPDATE label SET cohort_id = :cohort_id WHERE cohort_id IS NULL"
    ),
    "select_unclaimed_audits": Statement(
        "SELECT run_id, package_version_id, profile_summary, panel_config "
        "FROM audit_record WHERE cohort_id IS NULL"
    ),
    # The per-criterion figures the record carries, one row per
    # criterion-and-administration: the key joins the cohort dimension
    # (#118's migration), so a second administration of the same package is a
    # second record rather than a collision.
    "record_criterion_stats": Statement(
        "INSERT OR REPLACE INTO criterion_stats "
        "(package_version_id, criterion_id, backend_profile, panel_build_ref, "
        "n, cohort_id) VALUES (:package_version_id, :criterion_id, "
        ":backend_profile, :panel_build_ref, :n, :cohort_id)"
    ),
    # The read `criterion_figures` resolves one administration's record
    # through — the same rows `record_criterion_stats` wrote, keyed on the
    # cohort dimension the migration added, so a figure the consumer reads is
    # exactly the figure the record wrote.
    "select_criterion_stats": Statement(
        "SELECT * FROM criterion_stats WHERE cohort_id = :cohort_id"
    ),
    # --- FR-STATS-20: the judge signals' reads -----------------------------------
    # The run's judged cells and their verdict rows (M-JUDGE's columns, #361's two
    # added), plus the durable violation counts `dispatch` records. Reads only
    # (`CT-STATS-15`), and every one names the run.
    "select_run_score_units": Statement(
        "SELECT DISTINCT criterion_id, judge_id FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'score' AND judge_id IS NOT NULL "
        "ORDER BY criterion_id, judge_id"
    ),
    # `#374` (`FR-STATS-21`): the score units a measurement driver may re-score, in the
    # shape the LEASE hands a worker (`orch.select_run_claimable`'s column list). The
    # drivers re-score judgments that have already been MADE, so a lease cannot supply
    # them — it claims pending work — and re-scoring is a read, not a claim.
    #
    # `status = 'done'` is load-bearing, not tidiness. A pending, leased or quarantined
    # score unit was never judged; re-scoring one asks the provider a question nobody
    # asked before, which against a recorded fixture is a missing-recording refusal
    # blaming the prompt, and against a live backend is a real model call whose answer
    # then enters the rate as though it were a re-score. Neither is a measurement.
    #
    # The `student_ref` join is not decoration: `assemble`'s store door fills the view's
    # ref slot from it, so a unit rebuilt without it assembles a DIFFERENT request and
    # misses its recorded reply. The roster join is the same fidelity (#593): the claim
    # select resolves the roster display name, so a lease leaves a NAMED unit, and a
    # rebuild without the name assembles an unpseudonymized transcript where the run
    # sent the ref — the same different-request miss. LEFT join: a ref the roster does
    # not hold, or holds namelessly, rebuilds nameless, exactly as such a lease does.
    #
    # Deliberately NOT filtered by run: `FR-STATS-21`'s signature names a fixture
    # submission set, not a run, and a fixture set judged across two runs is still that
    # judge's evidence. What the absence of a run filter forbids is dividing by the
    # submission count — see the drivers, which divide by each judge's own measured
    # judgments precisely so a second run cannot inflate a rate past 1.0.
    "select_score_units": Statement(
        "SELECT w.work_id, w.run_id, w.stage, w.submission_id, w.criterion_id, "
        "w.judge_id, w.attempts AS attempt, s.student_ref AS student_ref, "
        "r.full_name AS student_name "
        "FROM work_unit w JOIN submission s ON s.submission_id = w.submission_id "
        "LEFT JOIN roster r ON r.cohort_id = s.cohort_id "
        "AND r.student_ref = s.student_ref "
        "WHERE w.stage = 'score' AND w.judge_id IS NOT NULL AND w.status = 'done' "
        "ORDER BY w.work_id"
    ),
    # Jev design delta FR-STATS-26: which engine produced a labelled cell's verdict. A cell
    # with a decision-engine verdict is `decision`; a pre-screened cell answered by the LLM is
    # `llm_fallback`; any other cell is `llm_engine_off`.
    "select_submission_for_ref": Statement(
        "SELECT submission_id FROM submission WHERE student_ref = :student_ref"
    ),
    "select_cell_engine_evidence": Statement(
        "SELECT (SELECT count(*) FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :run_id AND w.submission_id = :submission_id "
        "AND w.criterion_id = :criterion_id AND v.scoring_engine = 'decision') AS decision_n, "
        "(SELECT count(*) FROM decision_prescreen p WHERE p.run_id = :run_id "
        "AND p.submission_id = :submission_id AND p.criterion_id = :criterion_id) AS prescreen_n"
    ),
    "select_run_verdicts": Statement(
        "SELECT w.criterion_id, v.judge_id, v.band, v.uncited, v.evidence_sufficient, "
        "v.latency_ms, v.scoring_engine FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :run_id ORDER BY w.criterion_id, v.judge_id, v.work_id"
    ),
    "select_run_violation_counts": Statement(
        "SELECT criterion_id, judge_id, value FROM run_metrics "
        "WHERE run_id = :run_id AND metric = 'judge_contract_violations'"
    ),
    "select_run_cache_hit_rate": Statement(
        "SELECT value FROM run_metrics WHERE run_id = :run_id AND metric = 'cache_hit_rate'"
    ),
}
