"""The SQL statements M-PKG runs, registered in the store's shared registry."""

from __future__ import annotations

from aeh.store import STATEMENTS, Statement

from .schema import _PKG_VERSION_LINEAGE


# --- the owning-module contribution to the store's migration registry ---------------------------
#
# Appended at import: after this module is imported, Tier P's current schema version is 2
# and every store opened afterwards applies the lineage migration. The migration's
# statements are registered in the store's STATEMENTS registry too — the store's rule is
# that every statement it can issue is registered, and the registry is built when store.py
# is imported, so the contribution extends it here.

PKG_STATEMENTS: dict[str, Statement] = {
    f"pkg_version_lineage_{index:02d}": statement
    for index, statement in enumerate(_PKG_VERSION_LINEAGE.statements)
}


PKG_STATEMENTS.update({
    "select_version": Statement(
        "SELECT package_version_id, package_id, revision, locked, parent_version_id "
        "FROM package_version WHERE package_version_id = :v"
    ),
    "insert_first_version": Statement(
        "INSERT INTO package_version (package_version_id, package_id, revision, locked) "
        "VALUES (:v, :p, 1, 0)"
    ),
    "insert_revision": Statement(
        "INSERT INTO package_version (package_version_id, package_id, revision, locked, "
        "parent_version_id) VALUES (:v, :p, :rev, 0, :parent)"
    ),
    "publish": Statement(
        "UPDATE package_version SET locked = 1, published_by = :by, "
        "published_at = datetime('now') WHERE package_version_id = :v"
    ),
    "count_package": Statement(
        "SELECT COUNT(*) AS n FROM package WHERE package_id = :p"
    ),
    "pkg_revision_copy_criterion": Statement(
        # The copy is VERBATIM — every column the M-PKG module defines on the table
        # (#230): a revision that drops criterion fields is mutation by omission, and
        # CT-PKG-02's invariant (a PackageVersionId identifies content permanently)
        # fails with it. The #51-era note stands: a revision copies the read-back
        # payload row too, so a payload asserting an evidence_type cannot sit beside
        # criterion rows whose evidence_type the copy silently NULLed.
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind, "
        "max_points, scoring_model, construct_tag, band_count, answer_key, "
        "evidence_type, band_justification, evaluation_mode, score_method, "
        "component_of) "
        "SELECT :new, criterion_id, question_id, kind, max_points, scoring_model, "
        "construct_tag, band_count, answer_key, evidence_type, band_justification, "
        "evaluation_mode, score_method, component_of FROM criterion "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_band": Statement(
        # The descriptor rides with the set (#230): a band without its descriptor is
        # the judge-facing mapping half-erased.
        "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points, "
        "descriptor) SELECT :new, criterion_id, ordinal, band, points, descriptor "
        "FROM band WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_dependency": Statement(
        "INSERT INTO criterion_dependency (package_version_id, criterion_id, depends_on) "
        "SELECT :new, criterion_id, depends_on FROM criterion_dependency "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_exemplar": Statement(
        "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, band, "
        "provenance, blob_hash) SELECT hex(randomblob(8)), :new, criterion_id, band, "
        "provenance, blob_hash FROM exemplar WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_grade_policy": Statement(
        "INSERT INTO grade_policy (package_version_id, policy, review_window_hours) "
        "SELECT :new, policy, review_window_hours FROM grade_policy "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_mcq_option": Statement(
        "INSERT INTO mcq_option (package_version_id, criterion_id, option_id, label) "
        "SELECT :new, criterion_id, option_id, label FROM mcq_option "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_grade_boundary": Statement(
        "INSERT INTO grade_boundary (package_version_id, grade, scaled_floor) "
        "SELECT :new, grade, scaled_floor FROM grade_boundary "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_question": Statement(
        "INSERT INTO question (package_version_id, question_id, ordinal, prompt_text, "
        "question_type, max_points, reference_solution, confirmed_at) SELECT :new, "
        "question_id, ordinal, prompt_text, question_type, max_points, "
        "reference_solution, confirmed_at FROM question WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_question_option": Statement(
        "INSERT INTO question_option (package_version_id, question_id, option_id, "
        "ordinal, label) SELECT :new, question_id, option_id, ordinal, label "
        "FROM question_option WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_setup_proposal": Statement(
        "INSERT INTO setup_proposal (package_version_id, proposal_id, "
        "assessment_doc_id, payload, template_version, model_ref, attempts, "
        "created_at, confirmed_at) SELECT :new, proposal_id, assessment_doc_id, "
        "payload, template_version, model_ref, attempts, created_at, confirmed_at "
        "FROM setup_proposal WHERE package_version_id = :old"
    ),
    "insert_criterion": Statement(
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind, "
        "max_points, scoring_model, construct_tag, band_count, evidence_type, "
        "evaluation_mode, score_method, component_of) VALUES "
        "(:v, :criterion_id, :question_id, :kind, :max_points, :scoring_model, "
        ":construct_tag, :band_count, :evidence_type, :evaluation_mode, "
        ":score_method, :component_of)"
    ),
    "insert_dependency": Statement(
        "INSERT INTO criterion_dependency (package_version_id, criterion_id, "
        "depends_on) VALUES (:v, :criterion_id, :depends_on)"
    ),
    "insert_band": Statement(
        "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points, "
        "descriptor) VALUES (:v, :criterion_id, :ordinal, :band, :points, :descriptor)"
    ),
    "insert_exemplar": Statement(
        "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, band, "
        "provenance, blob_hash) VALUES (:exemplar_id, :v, :criterion_id, :band, "
        ":provenance, :blob_hash)"
    ),
    "select_criteria": Statement(
        "SELECT criterion_id, question_id, kind, max_points, scoring_model, "
        "construct_tag, band_count, answer_key, evidence_type, band_justification, "
        "evaluation_mode, score_method, component_of FROM criterion "
        "WHERE package_version_id = :v ORDER BY criterion_id"
    ),
    "select_bands": Statement(
        "SELECT criterion_id, ordinal, band, points, descriptor FROM band "
        "WHERE package_version_id = :v ORDER BY criterion_id, ordinal"
    ),
    "select_bands_by_criterion": Statement(
        "SELECT criterion_id, ordinal, band, points, descriptor FROM band "
        "WHERE criterion_id = :criterion_id ORDER BY ordinal"
    ),
    "select_dependencies": Statement(
        "SELECT criterion_id, depends_on FROM criterion_dependency "
        "WHERE package_version_id = :v"
    ),
    "delete_dependencies": Statement(
        "DELETE FROM criterion_dependency WHERE package_version_id = :v"
    ),
    # `agreement IS NOT NULL` since `#373`, for the reason spelled out on
    # `select_all_validations` below: a validation record IS an agreement claim, and
    # `record_validation_baseline` writes a row that makes none. Without it,
    # `validation_for` hands back `{"agreement": None, "n": None}` — a "record" whose
    # figure is absent, which is precisely the reading `NoValidationData` exists to keep
    # unrepresentable (`FR-PKG-09`, distinguishable **in type**).
    #
    # It also restores `store_validation`'s pre-`#373` behaviour exactly rather than
    # changing it: before the baseline there was no such thing as a NULL-agreement row,
    # so this filter can only ever hide a baseline row, and a baseline row is not a
    # validation record whose rewrite `_guard` exists to refuse. On a published version
    # the insert trigger refuses regardless.
    "select_validation": Statement(
        "SELECT criterion_id, population_scope_id, backend_profile, panel_build_ref, "
        "scoring_model, agreement, n, decision_engine_noninferior FROM validation_record "
        "WHERE package_version_id = :v AND agreement IS NOT NULL "
        "AND (:criterion_id IS NULL OR criterion_id = :criterion_id) "
        "AND population_scope_id = :population_scope_id "
        "AND backend_profile = :backend_profile "
        "AND panel_build_ref = :panel_build_ref "
        "AND scoring_model = :scoring_model"
    ),
    # `validation_for`'s read (FR-PKG-23, #454 reopened): the same key, and a row that carries
    # an agreement figure OR a recorded engine verdict. `promote` records the verdict on a row
    # of its own, and FR-PKG-23 says `validation_for` returns it as a field; a baseline-only
    # row (neither) stays out, for the reason the note below gives.
    "select_validation_record": Statement(
        "SELECT criterion_id, population_scope_id, backend_profile, panel_build_ref, "
        "scoring_model, agreement, n, decision_engine_noninferior FROM validation_record "
        "WHERE package_version_id = :v "
        "AND (agreement IS NOT NULL OR decision_engine_noninferior IS NOT NULL) "
        "AND (:criterion_id IS NULL OR criterion_id = :criterion_id) "
        "AND population_scope_id = :population_scope_id "
        "AND backend_profile = :backend_profile "
        "AND panel_build_ref = :panel_build_ref "
        "AND scoring_model = :scoring_model"
    ),
    # `agreement IS NOT NULL` since `#373`: a `ManifestEntry` IS an agreement claim
    # (`FR-PKG-21`), and `manifest()` casts `float(agreement)` / `int(n)` unconditionally.
    # `record_validation_baseline` writes a row that carries a distribution and NO
    # agreement — it makes no such claim — so without this filter the first promoted
    # administration made `manifest()` raise `TypeError` on its own version, and
    # `_weakest_entry` would have invented a weakest criterion for the empty population
    # the baseline is keyed under. A baseline is read through `baseline_for`, never here.
    "select_all_validations": Statement(
        "SELECT criterion_id, population_scope_id, backend_profile, panel_build_ref, "
        "scoring_model, agreement, n FROM validation_record "
        "WHERE package_version_id = :v AND agreement IS NOT NULL"
    ),
    "insert_validation": Statement(
        "INSERT INTO validation_record (validation_record_id, package_version_id, "
        "criterion_id, population_scope_id, backend_profile, panel_build_ref, "
        "scoring_model, agreement, n, recorded_at) VALUES (hex(randomblob(8)), :v, "
        ":criterion_id, :population_scope_id, :backend_profile, :panel_build_ref, "
        ":scoring_model, :agreement, :n, datetime('now'))"
    ),
    # -- the baseline distribution (#373, FR-AGG-08) ---------------------------------------
    # `criterion_id` is matched exactly, with no `IS NULL` wildcard limb — unlike
    # `select_validation`, which has one. A baseline is always ONE criterion's
    # distribution, so a wildcard read has no meaning to return: with several criteria
    # promoted, an unkeyed query matches them all and the reader's `rows[0]` hands back
    # whichever SQLite ordered first. That is an adjacent key answering, the precise
    # failure the six-part key exists to prevent (`CT-PKG-07`, RISK-08).
    "select_validation_baseline": Statement(
        "SELECT expected_mean, expected_sd, expected_histogram FROM validation_record "
        "WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id "
        "AND population_scope_id = :population_scope_id "
        "AND backend_profile = :backend_profile "
        "AND panel_build_ref = :panel_build_ref "
        "AND scoring_model = :scoring_model"
    ),
    "select_version_present": Statement(
        "SELECT package_version_id FROM package_version "
        "WHERE package_version_id = :v"
    ),
    "select_criterion_band_ordinals": Statement(
        "SELECT band, ordinal FROM band "
        "WHERE package_version_id = :v AND criterion_id = :criterion_id "
        "ORDER BY ordinal"
    ),
    "update_validation_baseline": Statement(
        "UPDATE validation_record SET expected_mean = :expected_mean, "
        "expected_sd = :expected_sd, expected_histogram = :expected_histogram "
        "WHERE package_version_id = :v AND criterion_id = :criterion_id "
        "AND population_scope_id = :population_scope_id "
        "AND backend_profile = :backend_profile "
        "AND panel_build_ref = :panel_build_ref "
        "AND scoring_model = :scoring_model"
    ),
    # FR-PKG-23 (#454): the engine non-inferiority verdict on the validation record's row
    # under the six-part key (FR-PKG-08); NULL means not measured.
    "select_validation_noninferiority": Statement(
        "SELECT decision_engine_noninferior FROM validation_record "
        "WHERE package_version_id = :v AND criterion_id = :criterion_id "
        "AND population_scope_id = :population_scope_id "
        "AND backend_profile = :backend_profile "
        "AND panel_build_ref = :panel_build_ref "
        "AND scoring_model = :scoring_model"
    ),
    "update_validation_noninferiority": Statement(
        "UPDATE validation_record SET decision_engine_noninferior = :verdict "
        "WHERE package_version_id = :v AND criterion_id = :criterion_id "
        "AND population_scope_id = :population_scope_id "
        "AND backend_profile = :backend_profile "
        "AND panel_build_ref = :panel_build_ref "
        "AND scoring_model = :scoring_model"
    ),
    "insert_validation_noninferiority": Statement(
        "INSERT INTO validation_record (validation_record_id, package_version_id, "
        "criterion_id, population_scope_id, backend_profile, panel_build_ref, "
        "scoring_model, agreement, n, recorded_at, decision_engine_noninferior) VALUES "
        "(hex(randomblob(8)), :v, :criterion_id, :population_scope_id, :backend_profile, "
        ":panel_build_ref, :scoring_model, NULL, NULL, datetime('now'), :verdict)"
    ),
    "insert_validation_baseline": Statement(
        "INSERT INTO validation_record (validation_record_id, package_version_id, "
        "criterion_id, population_scope_id, backend_profile, panel_build_ref, "
        "scoring_model, agreement, n, recorded_at, expected_mean, expected_sd, "
        "expected_histogram) VALUES (hex(randomblob(8)), :v, :criterion_id, "
        ":population_scope_id, :backend_profile, :panel_build_ref, :scoring_model, "
        "NULL, NULL, datetime('now'), :expected_mean, :expected_sd, "
        ":expected_histogram)"
    ),
    "select_exemplar_provenance": Statement(
        "SELECT DISTINCT provenance FROM exemplar WHERE package_version_id = :v "
        "AND provenance IS NOT NULL"
    ),
    "select_latest_version": Statement(
        "SELECT package_version_id FROM package_version ORDER BY revision DESC LIMIT 1"
    ),
    # -- grade policy, boundaries, answer keys, elicitation history (#30) ----------------
    "select_policy": Statement(
        "SELECT policy, review_window_hours FROM grade_policy "
        "WHERE package_version_id = :v"
    ),
    "insert_policy": Statement(
        "INSERT INTO grade_policy (package_version_id, policy, review_window_hours) "
        "VALUES (:v, :policy, :review_window_hours)"
    ),
    "delete_policy": Statement(
        "DELETE FROM grade_policy WHERE package_version_id = :v"
    ),
    "select_boundaries": Statement(
        "SELECT grade, scaled_floor FROM grade_boundary "
        "WHERE package_version_id = :v ORDER BY scaled_floor"
    ),
    "delete_boundaries": Statement(
        "DELETE FROM grade_boundary WHERE package_version_id = :v"
    ),
    "insert_boundary": Statement(
        "INSERT INTO grade_boundary (package_version_id, grade, scaled_floor) "
        "VALUES (:v, :grade, :scaled_floor)"
    ),
    "select_answer_key_latest": Statement(
        "SELECT c.answer_key AS answer_key FROM criterion c "
        "JOIN package_version pv ON pv.package_version_id = c.package_version_id "
        "WHERE c.criterion_id = :criterion_id "
        "ORDER BY pv.revision DESC LIMIT 1"
    ),
    "update_criterion_answer_key": Statement(
        "UPDATE criterion SET answer_key = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "select_mcq_options": Statement(
        "SELECT option_id, label FROM mcq_option WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id ORDER BY option_id"
    ),
    "delete_mcq_options": Statement(
        "DELETE FROM mcq_option WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "insert_mcq_option": Statement(
        "INSERT INTO mcq_option (package_version_id, criterion_id, option_id, label) "
        "VALUES (:v, :criterion_id, :option_id, :label)"
    ),
    "insert_elicitation": Statement(
        "INSERT INTO elicitation_history (elicitation_id, package_version_id, question, "
        "options_offered, answer_given, resulting_edit, asked_at) "
        "VALUES (:id, :v, :question, :options_offered, :answer_given, "
        ":resulting_edit, datetime('now'))"
    ),
    # -- export gate, provenance, import (#31) --------------------------------------------
    "select_package_flag": Statement(
        "SELECT contains_real_student_text AS flag FROM package WHERE package_id = :p"
    ),
    "refresh_package_flag": Statement(
        "UPDATE package SET contains_real_student_text = "
        "CASE WHEN EXISTS (SELECT 1 FROM exemplar WHERE provenance = 'real_verbatim') "
        "THEN 1 ELSE 0 END WHERE package_id = :p"
    ),
    "select_real_verbatim_exemplars": Statement(
        "SELECT exemplar_id, package_version_id, criterion_id, band FROM exemplar "
        "WHERE provenance = 'real_verbatim' ORDER BY exemplar_id"
    ),
    "select_exemplar_blob_hashes": Statement(
        "SELECT DISTINCT blob_hash FROM exemplar WHERE blob_hash IS NOT NULL"
    ),
    "select_exemplar_by_id": Statement(
        "SELECT exemplar_id FROM exemplar WHERE package_version_id = :v "
        "AND exemplar_id = :exemplar_id"
    ),
    "update_exemplar_provenance": Statement(
        "UPDATE exemplar SET provenance = :value WHERE package_version_id = :v "
        "AND exemplar_id = :exemplar_id"
    ),
    "delete_exemplar": Statement(
        "DELETE FROM exemplar WHERE package_version_id = :v "
        "AND exemplar_id = :exemplar_id"
    ),
    "select_exemplars": Statement(
        "SELECT exemplar_id, criterion_id, band, provenance, blob_hash FROM exemplar "
        "WHERE package_version_id = :v ORDER BY exemplar_id"
    ),
    # -- question inventory and setup proposal (#50) --------------------------------------
    # The package row `create_version` refuses to mint (`_refuse_no_such_package`'s
    # message names M-SETUP as its writer): the initial version's setup flow creates it.
    "insert_package": Statement(
        "INSERT INTO package (package_id, created_at) VALUES (:p, datetime('now'))"
    ),
    "select_latest_draft_version": Statement(
        "SELECT package_version_id FROM package_version WHERE package_id = :p "
        "AND locked = 0 ORDER BY revision DESC LIMIT 1"
    ),
    "select_latest_package_version": Statement(
        "SELECT package_version_id FROM package_version WHERE package_id = :p "
        "ORDER BY revision DESC LIMIT 1"
    ),
    "select_has_version": Statement(
        "SELECT 1 AS one FROM package_version WHERE package_id = :p LIMIT 1"
    ),
    "insert_question": Statement(
        "INSERT INTO question (package_version_id, question_id, ordinal, prompt_text, "
        "question_type, max_points, reference_solution, confirmed_at) VALUES (:v, "
        ":question_id, :ordinal, :prompt_text, :question_type, :max_points, "
        ":reference_solution, :confirmed_at)"
    ),
    "select_questions": Statement(
        "SELECT question_id, ordinal, prompt_text, question_type, max_points, "
        "reference_solution, confirmed_at FROM question "
        "WHERE package_version_id = :v ORDER BY ordinal, question_id"
    ),
    "select_question": Statement(
        "SELECT question_id, ordinal, prompt_text, question_type, max_points, "
        "reference_solution, confirmed_at FROM question "
        "WHERE package_version_id = :v AND question_id = :question_id"
    ),
    "update_question_prompt_text": Statement(
        "UPDATE question SET prompt_text = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "update_question_ordinal": Statement(
        "UPDATE question SET ordinal = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "update_question_max_points": Statement(
        "UPDATE question SET max_points = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "update_question_question_type": Statement(
        "UPDATE question SET question_type = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "update_question_reference_solution": Statement(
        "UPDATE question SET reference_solution = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "insert_question_option": Statement(
        "INSERT INTO question_option (package_version_id, question_id, option_id, "
        "ordinal, label) VALUES (:v, :question_id, :option_id, :ordinal, :label)"
    ),
    "select_version_question_options": Statement(
        "SELECT question_id, option_id, ordinal, label FROM question_option "
        "WHERE package_version_id = :v ORDER BY question_id, ordinal"
    ),
    "select_options_by_question": Statement(
        "SELECT option_id, ordinal, label FROM question_option "
        "WHERE package_version_id = :v AND question_id = :question_id ORDER BY ordinal"
    ),
    "select_proposal": Statement(
        "SELECT proposal_id, assessment_doc_id, payload, template_version, model_ref, "
        "attempts, created_at, confirmed_at FROM setup_proposal "
        "WHERE package_version_id = :v"
    ),
    "insert_proposal": Statement(
        "INSERT INTO setup_proposal (package_version_id, proposal_id, "
        "assessment_doc_id, payload, template_version, model_ref, attempts, created_at) "
        "VALUES (:v, :proposal_id, :assessment_doc_id, :payload, :template_version, "
        ":model_ref, :attempts, datetime('now'))"
    ),
    "update_proposal_payload": Statement(
        "UPDATE setup_proposal SET payload = :payload, attempts = :attempts "
        "WHERE package_version_id = :v"
    ),
    "confirm_proposal": Statement(
        "UPDATE setup_proposal SET confirmed_at = :confirmed_at "
        "WHERE package_version_id = :v"
    ),
    # -- rubric read-back (#51): the provenance row and the columns it fills --------------
    "select_readback": Statement(
        "SELECT rubric_doc_id, assessment_doc_id, payload, template_version, "
        "model_ref, attempts, created_at FROM setup_readback "
        "WHERE package_version_id = :v"
    ),
    "insert_readback": Statement(
        "INSERT INTO setup_readback (package_version_id, rubric_doc_id, "
        "assessment_doc_id, payload, template_version, model_ref, attempts, created_at) "
        "VALUES (:v, :rubric_doc_id, :assessment_doc_id, :payload, :template_version, "
        ":model_ref, :attempts, :created_at)"
    ),
    "insert_readback_criterion": Statement(
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind, "
        "max_points, scoring_model, construct_tag, band_count, evidence_type, "
        "band_justification, evaluation_mode) VALUES "
        "(:v, :criterion_id, :question_id, :kind, "
        ":max_points, :scoring_model, :construct_tag, :band_count, :evidence_type, "
        ":band_justification, :evaluation_mode)"
    ),
    "pkg_revision_copy_setup_readback": Statement(
        "INSERT INTO setup_readback (package_version_id, rubric_doc_id, "
        "assessment_doc_id, payload, template_version, model_ref, attempts, created_at) "
        "SELECT :new, rubric_doc_id, assessment_doc_id, payload, template_version, "
        "model_ref, attempts, created_at FROM setup_readback WHERE package_version_id = :old"
    ),
    # -- #52: the classification and step-provenance writes ------------------------------
    "insert_classification": Statement(
        "INSERT INTO setup_classification (package_version_id, criterion_id, "
        "classification, decomposition_basis, source, recorded_at) VALUES (:v, "
        ":criterion_id, :classification, :decomposition_basis, :source, :recorded_at) "
        "ON CONFLICT (package_version_id, criterion_id) DO UPDATE SET "
        "classification = excluded.classification, "
        "decomposition_basis = excluded.decomposition_basis, "
        "source = excluded.source, recorded_at = excluded.recorded_at"
    ),
    "select_classifications": Statement(
        "SELECT criterion_id, classification, decomposition_basis, source, "
        "recorded_at FROM setup_classification WHERE package_version_id = :v "
        "ORDER BY criterion_id"
    ),
    "select_classification": Statement(
        "SELECT criterion_id, classification, decomposition_basis, source, "
        "recorded_at FROM setup_classification WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "insert_step_record": Statement(
        "INSERT INTO setup_step_record (package_version_id, step_id, status, payload, "
        "recorded_at) VALUES (:v, :step_id, :status, :payload, :recorded_at) "
        "ON CONFLICT (package_version_id, step_id) DO UPDATE SET "
        "status = excluded.status, payload = excluded.payload, "
        "recorded_at = excluded.recorded_at"
    ),
    "select_step_record": Statement(
        "SELECT step_id, status, payload, recorded_at FROM setup_step_record "
        "WHERE package_version_id = :v AND step_id = :step_id"
    ),
    "select_step_records": Statement(
        "SELECT step_id, status, payload, recorded_at FROM setup_step_record "
        "WHERE package_version_id = :v ORDER BY step_id"
    ),
    "pkg_revision_copy_setup_classification": Statement(
        "INSERT INTO setup_classification (package_version_id, criterion_id, "
        "classification, decomposition_basis, source, recorded_at) "
        "SELECT :new, criterion_id, classification, decomposition_basis, source, "
        "recorded_at FROM setup_classification WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_setup_step_record": Statement(
        "INSERT INTO setup_step_record (package_version_id, step_id, status, payload, "
        "recorded_at) SELECT :new, step_id, status, payload, recorded_at "
        "FROM setup_step_record WHERE package_version_id = :old"
    ),
    "pkg_revision_copied_counts": Statement(
        # #230's observability half: the revision result names what was copied, with
        # per-table row counts — one read over the child's copies rather than one per
        # table. The surface list mirrors `_REVISION_COPY_KEYS`; extend both together.
        "SELECT 'criterion' AS surface, COUNT(*) AS n FROM criterion "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'band', COUNT(*) FROM band "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'question', COUNT(*) FROM question "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'question_option', COUNT(*) FROM question_option "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'criterion_dependency', COUNT(*) FROM criterion_dependency "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'exemplar', COUNT(*) FROM exemplar "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'mcq_option', COUNT(*) FROM mcq_option "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'grade_policy', COUNT(*) FROM grade_policy "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'grade_boundary', COUNT(*) FROM grade_boundary "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'setup_proposal', COUNT(*) FROM setup_proposal "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'setup_readback', COUNT(*) FROM setup_readback "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'setup_classification', COUNT(*) FROM setup_classification "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'setup_step_record', COUNT(*) FROM setup_step_record "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'criterion_derivation', COUNT(*) FROM criterion_derivation "
        "WHERE package_version_id = :v"
    ),
    # Per-field UPDATE statements: the SET column cannot be a bound parameter, so each
    # lockable field carries its own literal — the registry stays the one place a
    # statement exists, and the guard selects by field name.
    "update_criterion_max_points": Statement(
        "UPDATE criterion SET max_points = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_criterion_question_type": Statement(
        "UPDATE criterion SET kind = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_criterion_scoring_model": Statement(
        "UPDATE criterion SET scoring_model = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_criterion_construct_tag": Statement(
        "UPDATE criterion SET construct_tag = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_band_label": Statement(
        "UPDATE band SET label = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
    "update_band_ordinal": Statement(
        "UPDATE band SET ordinal = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
    "update_band_descriptor": Statement(
        "UPDATE band SET descriptor = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
    "update_band_points": Statement(
        "UPDATE band SET points = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
})


PKG_STATEMENTS.update({
    "insert_export_gate_outcome": Statement(
        "INSERT INTO export_gate_outcome (package_version_id, outcome, actor, recorded_at) "
        "VALUES (:v, :outcome, :actor, :recorded_at)"
    ),
    "select_export_gate_outcome": Statement(
        "SELECT outcome FROM export_gate_outcome WHERE package_version_id = :v "
        "ORDER BY rowid DESC LIMIT 1"
    ),
})


# #622 (FR-PKG-26): the `general` criterion's derivation provenance. Recording a
# derivation again replaces it AND clears its confirmation: a confirmation is of one
# derived band set, never of whatever set is stored later.
PKG_STATEMENTS.update({
    "upsert_criterion_derivation": Statement(
        "INSERT INTO criterion_derivation (package_version_id, criterion_id, description, "
        "derived_bands, recorded_at, confirmed_by, confirmed_at) VALUES (:v, "
        ":criterion_id, :description, :derived_bands, :recorded_at, NULL, NULL) "
        "ON CONFLICT (package_version_id, criterion_id) DO UPDATE SET "
        "description = excluded.description, derived_bands = excluded.derived_bands, "
        "recorded_at = excluded.recorded_at, confirmed_by = NULL, confirmed_at = NULL"
    ),
    "confirm_criterion_derivation": Statement(
        "UPDATE criterion_derivation SET confirmed_by = :confirmed_by, "
        "confirmed_at = :confirmed_at WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "select_criterion_derivations": Statement(
        "SELECT criterion_id, description, derived_bands, recorded_at, confirmed_by, "
        "confirmed_at FROM criterion_derivation WHERE package_version_id = :v "
        "ORDER BY criterion_id"
    ),
    "pkg_revision_copy_criterion_derivation": Statement(
        "INSERT INTO criterion_derivation (package_version_id, criterion_id, description, "
        "derived_bands, recorded_at, confirmed_by, confirmed_at) SELECT :new, "
        "criterion_id, description, derived_bands, recorded_at, confirmed_by, "
        "confirmed_at FROM criterion_derivation WHERE package_version_id = :old"
    ),
})


STATEMENTS.update(PKG_STATEMENTS)


#: #529 (FR-CONSOLE-24): one administration's validation record, read back.
_SELECT_PROMOTION_RECORD = Statement(
    "SELECT package_version_id, cohort_id, blind_count, n, agreement_kappa, recorded_at "
    "FROM package_validation WHERE package_version_id = :package_version_id "
    "AND cohort_id = :cohort_id"
)
