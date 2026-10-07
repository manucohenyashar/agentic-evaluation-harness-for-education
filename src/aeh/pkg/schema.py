"""The Tier P and durable-tier migrations M-PKG contributes to the store."""

from __future__ import annotations

from aeh.store import Migration, Statement, Tier, TIER_MIGRATIONS


# --- the Tier P migration this module contributes (design §3.3's decision table) ---------------
#
# `M-STORE` owns the migration *mechanism*; the owning module contributes the migrations.
# #26's migration adds the lineage columns the schema's minimal 001 set did not carry and
# installs the immutability triggers — the database half of `NFR-PKG-01`.

_PKG_SCHEMA_LOCK_COLUMNS = Migration(
    version=3,
    name="pkg_schema_lock_columns",
    statements=(
        Statement("ALTER TABLE criterion ADD COLUMN max_points REAL"),
        Statement("ALTER TABLE criterion ADD COLUMN band_count INTEGER"),
        Statement("ALTER TABLE criterion ADD COLUMN scoring_model TEXT"),
        Statement("ALTER TABLE criterion ADD COLUMN construct_tag TEXT"),
        Statement("ALTER TABLE band ADD COLUMN descriptor TEXT"),
        Statement("ALTER TABLE exemplar ADD COLUMN provenance TEXT"),
    ),
)


_PKG_VALIDATION_KEYS = Migration(
    version=4,
    name="pkg_validation_keys",
    statements=(
        Statement("ALTER TABLE validation_record ADD COLUMN criterion_id TEXT"),
        Statement(
            "ALTER TABLE validation_record ADD COLUMN population_scope_id TEXT"),
        Statement("ALTER TABLE validation_record ADD COLUMN scoring_model TEXT"),
        Statement("ALTER TABLE validation_record ADD COLUMN agreement REAL"),
        Statement("ALTER TABLE validation_record ADD COLUMN n INTEGER"),
        Statement(
            "CREATE UNIQUE INDEX validation_record_key ON validation_record "
            "(package_version_id, criterion_id, population_scope_id, backend_profile, "
            "panel_build_ref, scoring_model)"
        ),
    ),
)


_PKG_GRADE_POLICY_AND_KEYS = Migration(
    version=5,
    name="pkg_grade_policy_and_keys",
    statements=(
        # FR-PKG-17: the key is a column on criterion — one canonical representation.
        Statement("ALTER TABLE criterion ADD COLUMN answer_key TEXT"),
        # ADR-1: the options table carries NO correctness column — not is_correct, not
        # correct_option, nothing. The key lives once, on criterion.answer_key; a second
        # representation is how a corrected key leaves two disagreeing sources behind.
        Statement(
            """
            CREATE TABLE mcq_option (
                package_version_id TEXT NOT NULL,
                criterion_id       TEXT NOT NULL,
                option_id          TEXT NOT NULL,
                label              TEXT NOT NULL,
                PRIMARY KEY (package_version_id, criterion_id, option_id),
                FOREIGN KEY (package_version_id, criterion_id)
                    REFERENCES criterion(package_version_id, criterion_id)
            )
            """
        ),
        # FR-PKG-16: the boundary table is the single canonical representation of the
        # grade resolution rule. Floors are INCLUSIVE — boundary_for resolves the grade
        # with the greatest floor <= the scaled score.
        Statement(
            """
            CREATE TABLE grade_boundary (
                package_version_id TEXT NOT NULL REFERENCES package_version(package_version_id),
                grade              TEXT NOT NULL,
                scaled_floor       REAL NOT NULL,
                PRIMARY KEY (package_version_id, grade)
            )
            """
        ),
        # ADR-3: the review window is a column, not a policy-JSON field.
        Statement("ALTER TABLE grade_policy ADD COLUMN review_window_hours INTEGER"),
        # FR-PKG-20 / FR-CALIB-14: the calibration audit trail — every question asked,
        # options offered, answer given, resulting edit. It is the record that answers
        # "why does the rubric say this now", which is why it is append-only below.
        Statement(
            """
            CREATE TABLE elicitation_history (
                elicitation_id     TEXT NOT NULL PRIMARY KEY,
                package_version_id TEXT NOT NULL REFERENCES package_version(package_version_id),
                question           TEXT NOT NULL,
                options_offered    TEXT NOT NULL,
                answer_given       TEXT NOT NULL,
                resulting_edit     TEXT NOT NULL DEFAULT '',
                asked_at           TEXT NOT NULL
            )
            """
        ),
        # FR-PKG-20: append-only IN PRACTICE, not by convention — an unconditional
        # trigger pair aborts any UPDATE or DELETE, including raw SQL around the catalog.
        Statement(
            "CREATE TRIGGER elicitation_history_append_only_update "
            "BEFORE UPDATE ON elicitation_history "
            "BEGIN SELECT RAISE(ABORT, 'elicitation_history is append-only: rows are "
            "never updated (FR-PKG-20)'); END"
        ),
        Statement(
            "CREATE TRIGGER elicitation_history_append_only_delete "
            "BEFORE DELETE ON elicitation_history "
            "BEGIN SELECT RAISE(ABORT, 'elicitation_history is append-only: rows are "
            "never deleted (FR-PKG-20)'); END"
        ),
        # The 002 pattern, carried to the new content tables: a published version's
        # options and boundaries are immutable — plus the DELETE refusal 002's tables
        # predate. grade_policy gets one too: this diff introduces its first DELETE
        # statement (set_grade_policy's draft rewrite), so the backstop moves with it.
        # elicitation_history is deliberately NOT here: appends are always allowed (the
        # trail records conversations about the rubric as published).
        Statement(
            "CREATE TRIGGER grade_policy_delete_refused BEFORE DELETE ON grade_policy "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade policy "
            "removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER mcq_option_immutable BEFORE UPDATE ON mcq_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: mcq_option "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER mcq_option_insert_locked BEFORE INSERT ON mcq_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: mcq_option "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER mcq_option_delete_refused BEFORE DELETE ON mcq_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: mcq_option "
            "removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_boundary_immutable BEFORE UPDATE ON grade_boundary "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade_boundary "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_boundary_insert_locked BEFORE INSERT ON grade_boundary "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade_boundary "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_boundary_delete_refused BEFORE DELETE ON grade_boundary "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade_boundary "
            "removed from a published version'); END"
        ),
    ),
)


_PKG_EXPORT_GATE = Migration(
    version=6,
    name="pkg_export_gate",
    statements=(
        # ADR-4: the flag is DERIVED from exemplar presence — the catalog recomputes it
        # on every exemplar write, so flag and rows cannot disagree. A stored column,
        # because the export gate (FR-PKG-11) and the console read one value.
        Statement(
            "ALTER TABLE package ADD COLUMN contains_real_student_text INTEGER NOT NULL "
            "DEFAULT 0 CHECK (contains_real_student_text IN (0, 1))"
        ),
        # CT-STORE-07: exemplar material lives in the content-addressed blob store; the
        # reference is the hash itself (verified on get, no FK — blobs are content-
        # addressed across the whole installation). Nullable: a text-only exemplar.
        Statement("ALTER TABLE exemplar ADD COLUMN blob_hash TEXT"),
    ),
)


_PKG_VERSION_LINEAGE = Migration(
    version=2,
    name="pkg_version_lineage",
    statements=(
        Statement(
            "ALTER TABLE package_version ADD COLUMN parent_version_id "
            "REFERENCES package_version(package_version_id)"
        ),
        Statement("ALTER TABLE package_version ADD COLUMN published_by TEXT"),
        Statement("ALTER TABLE package_version ADD COLUMN published_at TEXT"),
        # The immutability backstops: UPDATE triggers on every guarded table, plus
        # INSERT triggers on the child tables (adding a row to a published version's
        # content is the §6.2 edit-in-place FR-PKG-04 refuses). Both fire only when the
        # referenced version is locked, so a revision's copies into its own unlocked
        # version pass.
        Statement(
            "CREATE TRIGGER package_version_immutable BEFORE UPDATE ON package_version "
            "WHEN OLD.locked = 1 "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: create a "
            "revision instead'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_immutable BEFORE UPDATE ON criterion "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: criterion "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER band_immutable BEFORE UPDATE ON band "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: band references "
            "a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_dependency_immutable BEFORE UPDATE ON "
            "criterion_dependency "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: dependency "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER exemplar_immutable BEFORE UPDATE ON exemplar "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: exemplar "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_policy_immutable BEFORE UPDATE ON grade_policy "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade policy "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER validation_record_immutable BEFORE UPDATE ON "
            "validation_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: validation "
            "record references a published version'); END"
        ),
        # INSERT triggers on the child tables: ADDING a sub-criterion (or band, exemplar,
        # policy, dependency) to a published version is the §6.2 edit-in-place
        # FR-PKG-04 refuses — the new rows would silently change what the published
        # version contains. They fire only when the referenced version is locked, so a
        # revision's copies into its own unlocked version pass.
        Statement(
            "CREATE TRIGGER criterion_insert_locked BEFORE INSERT ON criterion "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: criterion added "
            "to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER band_insert_locked BEFORE INSERT ON band "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: band added to a "
            "published version'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_dependency_insert_locked BEFORE INSERT ON "
            "criterion_dependency "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: dependency "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER exemplar_insert_locked BEFORE INSERT ON exemplar "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: exemplar added "
            "to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_policy_insert_locked BEFORE INSERT ON grade_policy "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade policy "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER validation_record_insert_locked BEFORE INSERT ON "
            "validation_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: validation "
            "record added to a published version'); END"
        ),
    ),
)


# The question inventory (HLD §9.5's `question` and per-question option tables) and the
# setup-proposal record #50 stages. Ownership: M-PKG is Tier P's sole writer (`CT-PKG-12`,
# §3.4's "questions and MCQ options"); M-SETUP reaches these rows only through the catalog
# methods below. Rows are written ONCE, at `confirm_inventory` — the teacher's assertion
# about content — and the confirmation lock engages there (FR-SETUP-02), deliberately
# earlier than publication. The tables are empty until that confirmation.
#
# Two locks, in trigger form (NFR-PKG-01: at the data layer, so a caller that routes
# around the catalog hits the database's own refusal):
#   * published immunity — the 002 pattern, carried to all three tables: a published
#     version's rows refuse UPDATE, INSERT and DELETE.
#   * the confirmation lock — a CONFIRMED question row refuses edits of its content
#     columns (prompt, ordinal, points, type) and its removal, while
#     `reference_solution` stays writable (the rubric read-back, #51, fills it on a
#     confirmed version); an option of a confirmed question refuses UPDATE and DELETE.
#     The option table's INSERT path is deliberately NOT confirmation-locked: the
#     revision copy's vehicle is an INSERT into the child version, whose copied
#     questions are born confirmed — a trigger there would break FR-PKG-02's copy.
#     The catalog's `write_confirmed_inventory` (which refuses an already-confirmed
#     proposal) is the only sanctioned writer, and a raw-SQL option INSERT can only
#     ADD to a confirmed inventory, never unconfirm it: `publish`'s gate reads
#     `setup_proposal.confirmed_at` plus the question rows, so the hole fails closed.
#
# Named divergence from the HLD §9.5 DDL: the per-question option table is
# `question_option`, because migration 005 took `mcq_option` for the criterion-scoped
# table (#31) and two tables of one name cannot share a schema. ADR-1's shape is kept:
# NO correctness column — the key lives on `criterion.answer_key` (FR-PKG-17), and
# option correctness is not declared at setup time at all.
_PKG_QUESTION_INVENTORY = Migration(
    version=7,
    name="pkg_question_inventory",
    statements=(
        # `confirmed_at` is NOT NULL on purpose: a question row exists ONLY because the
        # inventory was confirmed, and the schema should say so — the same taste as the
        # §6.2 lock itself (a constraint, not a convention).
        Statement(
            """
            CREATE TABLE question (
                package_version_id TEXT    NOT NULL REFERENCES package_version(package_version_id),
                question_id        TEXT    NOT NULL,
                ordinal            INTEGER NOT NULL CHECK (ordinal >= 0),
                prompt_text        TEXT    NOT NULL,
                question_type      TEXT    NOT NULL CHECK (question_type IN ('open', 'mcq', 'mixed')),
                max_points         REAL    NOT NULL DEFAULT 0.0 CHECK (max_points >= 0),
                reference_solution TEXT,
                confirmed_at       TEXT    NOT NULL,
                PRIMARY KEY (package_version_id, question_id)
            )
            """
        ),
        Statement(
            """
            CREATE TABLE question_option (
                package_version_id TEXT    NOT NULL,
                question_id        TEXT    NOT NULL,
                option_id          TEXT    NOT NULL,
                ordinal            INTEGER NOT NULL CHECK (ordinal >= 0),
                label              TEXT    NOT NULL,
                PRIMARY KEY (package_version_id, question_id, option_id),
                FOREIGN KEY (package_version_id, question_id)
                    REFERENCES question(package_version_id, question_id)
            )
            """
        ),
        # One proposal per version (the PK): `propose_inventory` runs once per version
        # (CT-SETUP-16); re-requests after an unparseable model reply UPDATE the same
        # row (payload + attempts), and confirmation stamps `confirmed_at`. The payload
        # is the proposal JSON as proposed — the provenance of what the teacher saw.
        Statement(
            """
            CREATE TABLE setup_proposal (
                package_version_id TEXT    NOT NULL PRIMARY KEY
                    REFERENCES package_version(package_version_id),
                proposal_id        TEXT    NOT NULL,
                assessment_doc_id  TEXT    NOT NULL,
                payload            TEXT    NOT NULL,
                template_version   TEXT    NOT NULL,
                model_ref          TEXT    NOT NULL,
                attempts           INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
                created_at         TEXT    NOT NULL,
                confirmed_at       TEXT
            )
            """
        ),
        # -- published immunity (the 002 pattern) --
        Statement(
            "CREATE TRIGGER question_immutable BEFORE UPDATE ON question "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_insert_locked BEFORE INSERT ON question "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question added "
            "to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_delete_refused BEFORE DELETE ON question "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question "
            "removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_immutable BEFORE UPDATE ON question_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question_option "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_insert_locked BEFORE INSERT ON "
            "question_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question_option "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_delete_refused BEFORE DELETE ON "
            "question_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question_option "
            "removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_proposal_immutable BEFORE UPDATE ON setup_proposal "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_proposal "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_proposal_insert_locked BEFORE INSERT ON "
            "setup_proposal "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_proposal "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_proposal_delete_refused BEFORE DELETE ON "
            "setup_proposal "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_proposal "
            "removed from a published version'); END"
        ),
        # -- the confirmation lock (FR-SETUP-02): engages at confirm_inventory, before
        # -- publication. One trigger per content column, so the refusal names the field.
        Statement(
            "CREATE TRIGGER question_confirmed_prompt_text BEFORE UPDATE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "AND OLD.prompt_text IS NOT NEW.prompt_text "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): prompt_text is the teacher-confirmed content'); END"
        ),
        Statement(
            "CREATE TRIGGER question_confirmed_ordinal BEFORE UPDATE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "AND OLD.ordinal IS NOT NEW.ordinal "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): ordinal is the teacher-confirmed order'); END"
        ),
        Statement(
            "CREATE TRIGGER question_confirmed_max_points BEFORE UPDATE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "AND OLD.max_points IS NOT NEW.max_points "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): max_points is the teacher-confirmed content'); END"
        ),
        Statement(
            "CREATE TRIGGER question_confirmed_question_type BEFORE UPDATE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "AND OLD.question_type IS NOT NEW.question_type "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): question_type is the teacher-confirmed content — HLD §7.8 "
            "names the open/mcq conversion a redefinition'); END"
        ),
        Statement(
            "CREATE TRIGGER question_confirmed_delete_refused BEFORE DELETE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): a confirmed question is not removed — corrections happen "
            "before confirmation'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_confirmed BEFORE UPDATE ON question_option "
            "WHEN EXISTS (SELECT 1 FROM question q WHERE q.package_version_id "
            "= OLD.package_version_id AND q.question_id = OLD.question_id "
            "AND q.confirmed_at IS NOT NULL) "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): an option of a confirmed question is not editable'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_confirmed_delete_refused BEFORE DELETE ON "
            "question_option "
            "WHEN EXISTS (SELECT 1 FROM question q WHERE q.package_version_id "
            "= OLD.package_version_id AND q.question_id = OLD.question_id "
            "AND q.confirmed_at IS NOT NULL) "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): an option of a confirmed question is not removed'); END"
        ),
    ),
)


# The rubric read-back (§3.6, #51): the provenance row for the one read-back per version
# (CT-SETUP-16, the proposal row's twin) and the two criterion columns the read back fills.
#
# `evidence_type` (FR-SETUP-09) declares what kind of textual evidence satisfies the
# criterion — M-INTEG routes on it (FR-INTEG-03: empty evidence is routed, never
# auto-scored). The design pins no closed vocabulary for it (M-EXTRACT's interface example
# names `textual_span`), so the column is TEXT without a CHECK: a CHECK would invent the
# vocabulary the design withholds.
#
# `band_justification` (FR-SETUP-04) records WHY a criterion carries more than the default
# two bands — partial credit genuinely part of the construct — so the wider band set is
# auditable rather than arbitrary. Written only through `write_readback`, which refuses a
# band_count above two without one.
#
# Neither column joins SCHEMA_LOCK_FIELDS: the §6.2 list enumerates the HLD's named fields
# (13, unchanged), and a published version's criterion rows already refuse EVERY UPDATE
# through the migration-002 triggers — a new column is locked by the same backstop, not by
# a second list.
#
# The read-back row is written ONCE, after the criteria it produced are written, in the
# same transaction; a draft re-runs nothing (resume returns the stored row, CT-SETUP-03).
# Published immunity is the 002 pattern carried to the new table. No confirmation lock:
# criteria are not question rows — they are mutable until the version publishes.
_PKG_SETUP_READBACK = Migration(
    version=8,
    name="pkg_setup_readback",
    statements=(
        Statement(
            "ALTER TABLE criterion ADD COLUMN evidence_type TEXT"
        ),
        Statement(
            "ALTER TABLE criterion ADD COLUMN band_justification TEXT"
        ),
        Statement(
            """
            CREATE TABLE setup_readback (
                package_version_id TEXT    NOT NULL PRIMARY KEY
                    REFERENCES package_version(package_version_id),
                rubric_doc_id      TEXT    NOT NULL,
                assessment_doc_id  TEXT    NOT NULL,
                payload            TEXT    NOT NULL,
                template_version   TEXT    NOT NULL,
                model_ref          TEXT    NOT NULL,
                attempts           INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
                created_at         TEXT    NOT NULL
            )
            """
        ),
        # -- published immunity (the 002 pattern) --
        Statement(
            "CREATE TRIGGER setup_readback_immutable BEFORE UPDATE ON setup_readback "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_readback "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_readback_insert_locked BEFORE INSERT ON "
            "setup_readback "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_readback "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_readback_delete_refused BEFORE DELETE ON "
            "setup_readback "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_readback "
            "removed from a published version'); END"
        ),
    ),
)


_PKG_SETUP_CLASSIFICATION = Migration(
    # #52: the decomposability verdicts and the setup steps' provenance rows. Two
    # tables, because they answer two different audit questions:
    #
    # `setup_classification` — one row per (version, criterion): the classification
    # the §5.3 table produced (`source='default'`, the module's own decision) and the
    # one the teacher confirmed over it (`source='teacher'`, upserted by
    # `confirm_classifications`). HLD R62's distinction: M-CALIB and M-STATS must be
    # able to tell a teacher's judgment from a system default, so a skipped
    # confirmation leaves the default row standing rather than nothing at all.
    # `decomposition_basis` is FR-SETUP-06's record of WHICH question decided —
    # an audit field, not a scoring input (the scoring input is the criterion's
    # `scoring_model`, which the read back writes from the same table).
    #
    # `setup_step_record` — one row per (version, step_id): how each non-blocking
    # setup step was completed (`FR-SETUP-14`: a default taken is recorded, never
    # indistinguishable from an explicit choice). #53's grade-policy and prefix-budget
    # steps write the same table; the row exists so a skip-only run still leaves
    # stored provenance naming the step.
    version=9,
    name="pkg_setup_classification",
    statements=(
        Statement(
            """
            CREATE TABLE setup_classification (
                package_version_id TEXT    NOT NULL,
                criterion_id       TEXT    NOT NULL,
                classification     TEXT    NOT NULL,
                decomposition_basis TEXT,
                source             TEXT    NOT NULL
                    CHECK (source IN ('default', 'teacher')),
                recorded_at        TEXT    NOT NULL,
                PRIMARY KEY (package_version_id, criterion_id),
                FOREIGN KEY (package_version_id)
                    REFERENCES package_version(package_version_id)
            )
            """
        ),
        Statement(
            """
            CREATE TABLE setup_step_record (
                package_version_id TEXT    NOT NULL,
                step_id            TEXT    NOT NULL,
                status             TEXT    NOT NULL,
                payload            TEXT    NOT NULL,
                recorded_at        TEXT    NOT NULL,
                PRIMARY KEY (package_version_id, step_id),
                FOREIGN KEY (package_version_id)
                    REFERENCES package_version(package_version_id)
            )
            """
        ),
        # -- published immunity (the 002/8 pattern): a published version's setup
        #    provenance is part of the record a defended grade leans on --
        Statement(
            "CREATE TRIGGER setup_classification_immutable BEFORE UPDATE ON "
            "setup_classification "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_classification references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_classification_insert_locked BEFORE INSERT ON "
            "setup_classification "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_classification added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_classification_delete_refused BEFORE DELETE ON "
            "setup_classification "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_classification removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_step_record_immutable BEFORE UPDATE ON "
            "setup_step_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_step_record references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_step_record_insert_locked BEFORE INSERT ON "
            "setup_step_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_step_record added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_step_record_delete_refused BEFORE DELETE ON "
            "setup_step_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_step_record removed from a published version'); END"
        ),
    ),
)


# --- Package migration 11 (#369, `FR-PKG-22`): how a criterion is evaluated ------------------
#
# `kind` says what SHAPE a criterion is; it has been doing double duty as a statement about
# how the criterion is EVALUATED, through the equivalence "`kind='mcq'` IS
# `evaluation_mode='deterministic'`" that several modules wrote into their docstrings. The
# two are not the same claim. A multiple-choice question whose options a panel must weigh is
# `kind='mcq'` and judged; the equivalence makes that package unrepresentable, and every
# consumer that tested `kind = 'mcq'` was deciding evaluation from shape.
#
# So the mode becomes a column the package DECLARES (`CT-PKG-19`), and the equivalence
# becomes the backfill: `deterministic` exactly where `kind='mcq'` today, which is what the
# equivalence asserted and is therefore lossless for every package that exists. The default
# is `judged` — the mode that runs the full pipeline. A wrong `judged` costs judge calls; a
# wrong `deterministic` silently skips the panel, so the default fails toward doing the work.
_PKG_CRITERION_EVALUATION_MODE = Migration(
    version=11,
    name="pkg_criterion_evaluation_mode",
    statements=(
        Statement(
            "ALTER TABLE criterion ADD COLUMN evaluation_mode TEXT NOT NULL "
            "DEFAULT 'judged' "
            "CHECK (evaluation_mode IN ('judged', 'deterministic'))"
        ),
        # The backfill, second and deliberately so: the ALTER gives every existing row
        # `judged`, and this restores the reading the old predicate had. Running it the
        # other way round would leave every mcq criterion judged for the width of one
        # migration — and a migration is not a window anyone gets to observe, but the
        # order is still the one that is correct on its own.
        Statement(
            "UPDATE criterion SET evaluation_mode = 'deterministic' WHERE kind = 'mcq'"
        ),
    ),
)


#: `#373`: the baseline distribution a promoted administration leaves behind, so
#: `should_escalate`'s distributional-anomaly input (`FR-AGG-08`) has something to compare
#: against and the drift check (`FR-STATS-09`) has a prior. Three columns, all NULLABLE and
#: all defaulting to NULL — a version nobody has promoted has NO baseline, and that is a
#: different fact from a baseline of zero. `should_escalate` reads the absence as "no data"
#: and skips the rule; a zero would read as a real distribution with no spread and suppress
#: the rule while looking like it ran.
_PKG_VALIDATION_BASELINE = Migration(
    version=12,
    name="pkg_validation_baseline",
    statements=(
        Statement("ALTER TABLE validation_record ADD COLUMN expected_mean REAL"),
        Statement("ALTER TABLE validation_record ADD COLUMN expected_sd REAL"),
        Statement("ALTER TABLE validation_record ADD COLUMN expected_histogram TEXT"),
    ),
)


# --- Tier P, migration 13 (#528, `FR-CONSOLE-23`): the export gate's outcome, recorded ---------
#
# A provenance gate whose result is not recorded is indistinguishable from one that was skipped
# (R71). The outcome lives beside the package it gated, append-only (the latest row is the
# current outcome), never in Tier D's `audit_record`, which M-STATS' promote sources.
_PKG_EXPORT_GATE_OUTCOME = Migration(
    version=13,
    name="pkg_export_gate_outcome",
    statements=(
        Statement(
            """
            CREATE TABLE export_gate_outcome (
                package_version_id TEXT NOT NULL REFERENCES package_version(package_version_id),
                outcome TEXT NOT NULL,
                actor TEXT,
                recorded_at TEXT NOT NULL
            )
            """
        ),
    ),
)


# --- Tier P, migration 14 (#454, `FR-PKG-23`): the engine non-inferiority verdict ---------------
#
# NFR-STATS-06's verdict needs a column of its own: the record's JSON columns are keyed
# documents consumers parse, and reusing one would break their readers. NULL = not measured
# (an engine-off run writes nothing), distinct from 'insufficient_data' (measured, too few).
_PKG_DECISION_ENGINE_NONINFERIOR = Migration(
    version=14,
    name="pkg_decision_engine_noninferior",
    statements=(
        Statement(
            "ALTER TABLE validation_record ADD COLUMN decision_engine_noninferior TEXT "
            "CHECK (decision_engine_noninferior IN ('true', 'false', 'insufficient_data'))"
        ),
    ),
)


# --- Tier P, migration 15 (#622, `FR-PKG-24`/`FR-PKG-26`, ADR-39): the rubric method --------
#
# Every new method is composition over the existing banded criterion, so the schema gains
# only what the composition needs: the method itself (closed, CHECKed, `bands` by default
# so every pre-15 criterion reads as what it always was) and the aspect-to-composite link.
# The `general` type's provenance — the teacher's prose and the band set derived from it,
# plus the confirmation that makes it publishable — gets its own table, under the same
# published-immunity triggers as every other row of a version (the §6.2 lock carried to
# the new data, as the design states it).
_PKG_CRITERION_SCORE_METHOD = Migration(
    version=15,
    name="pkg_criterion_score_method",
    statements=(
        Statement(
            "ALTER TABLE criterion ADD COLUMN score_method TEXT NOT NULL DEFAULT 'bands' "
            "CHECK (score_method IN ('bands', 'evidence_sum', 'general'))"
        ),
        Statement("ALTER TABLE criterion ADD COLUMN component_of TEXT NULL"),
        Statement(
            """
            CREATE TABLE criterion_derivation (
                package_version_id TEXT NOT NULL,
                criterion_id       TEXT NOT NULL,
                description        TEXT NOT NULL CHECK (length(trim(description)) > 0),
                derived_bands      TEXT NOT NULL,
                recorded_at        TEXT NOT NULL,
                confirmed_by       TEXT,
                confirmed_at       TEXT,
                CHECK ((confirmed_by IS NULL) = (confirmed_at IS NULL)),
                PRIMARY KEY (package_version_id, criterion_id),
                FOREIGN KEY (package_version_id, criterion_id)
                    REFERENCES criterion(package_version_id, criterion_id)
            )
            """
        ),
        Statement(
            "CREATE TRIGGER criterion_derivation_immutable BEFORE UPDATE ON "
            "criterion_derivation "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "criterion_derivation references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_derivation_insert_locked BEFORE INSERT ON "
            "criterion_derivation "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "criterion_derivation added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_derivation_delete_refused BEFORE DELETE ON "
            "criterion_derivation "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "criterion_derivation removed from a published version'); END"
        ),
    ),
)


# --- Tier P, migration 16 (#525, FR-PIPE-15): the published baseline exception ------------------
#
# The escalation baseline (`pkg_validation_baseline`'s three columns) is evidence ABOUT a
# package version, and every version a run grades against is published — so with the 002
# triggers standing as they were, no baseline could ever reach a run and the
# distributional-anomaly limb (`FR-PIPE-15`, RISK-96) never fired in production. Decision
# (a) of 2026-10-07 (#525): the baseline is the ONE kind of record allowed onto a published
# version, under append-only semantics — evidence may be ADDED (a new row, or a row whose
# three figure columns are still NULL), never altered. Every other write keeps refusing,
# including a rewrite of recorded figures and any agreement or verdict write.
#
# Both triggers keep their names (TC-PKG-27 matches the trigger set by name) and their
# FR-PKG-04 abort message; the exception rides the WHEN clause. A plain ALTER TABLE cannot
# replace a trigger, so the pair is dropped and recreated — forward-only like every
# migration here.
_PKG_PUBLISHED_BASELINE_EVIDENCE = Migration(
    version=16,
    name="pkg_published_baseline_evidence",
    statements=(
        Statement("DROP TRIGGER IF EXISTS validation_record_immutable"),
        Statement(
            "CREATE TRIGGER validation_record_immutable BEFORE UPDATE ON validation_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            # The sanctioned exception: filling a row's three baseline figures that are
            # still NULL, with every other column pinned by `IS` (NULL-safe) — anything
            # else, above all a rewrite of recorded figures, aborts.
            "AND NOT (OLD.expected_mean IS NULL AND OLD.expected_sd IS NULL "
            "AND OLD.expected_histogram IS NULL "
            "AND NEW.expected_mean IS NOT NULL AND NEW.expected_sd IS NOT NULL "
            "AND NEW.expected_histogram IS NOT NULL "
            "AND OLD.validation_record_id IS NEW.validation_record_id "
            "AND OLD.package_version_id IS NEW.package_version_id "
            "AND OLD.criterion_id IS NEW.criterion_id "
            "AND OLD.population_scope_id IS NEW.population_scope_id "
            "AND OLD.backend_profile IS NEW.backend_profile "
            "AND OLD.panel_build_ref IS NEW.panel_build_ref "
            "AND OLD.scoring_model IS NEW.scoring_model "
            "AND OLD.agreement IS NEW.agreement "
            "AND OLD.n IS NEW.n "
            "AND OLD.recorded_at IS NEW.recorded_at "
            "AND OLD.decision_engine_noninferior IS NEW.decision_engine_noninferior) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: validation "
            "record references a published version'); END"
        ),
        Statement("DROP TRIGGER IF EXISTS validation_record_insert_locked"),
        Statement(
            "CREATE TRIGGER validation_record_insert_locked BEFORE INSERT ON "
            "validation_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            # The sanctioned exception: a NEW row that is a baseline row and nothing else
            # — figures recorded, no agreement claim and no engine verdict riding along.
            "AND NOT (NEW.expected_mean IS NOT NULL AND NEW.expected_sd IS NOT NULL "
            "AND NEW.agreement IS NULL "
            "AND NEW.decision_engine_noninferior IS NULL) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: validation "
            "record added to a published version'); END"
        ),
    ),
)


TIER_MIGRATIONS[Tier.PACKAGE] = (
    TIER_MIGRATIONS[Tier.PACKAGE]
    + (_PKG_VERSION_LINEAGE,)
    + (_PKG_SCHEMA_LOCK_COLUMNS,)
    + (_PKG_VALIDATION_KEYS,)
    + (_PKG_GRADE_POLICY_AND_KEYS,)
    + (_PKG_EXPORT_GATE,)
    + (_PKG_QUESTION_INVENTORY,)
    + (_PKG_SETUP_READBACK,)
    + (_PKG_SETUP_CLASSIFICATION,)
    + (_PKG_CRITERION_EVALUATION_MODE,)
    + (_PKG_VALIDATION_BASELINE,)
    + (_PKG_EXPORT_GATE_OUTCOME,)
    + (_PKG_DECISION_ENGINE_NONINFERIOR,)
    + (_PKG_CRITERION_SCORE_METHOD,)
    + (_PKG_PUBLISHED_BASELINE_EVIDENCE,)
)


# Durable v8 — #118's promotion record. M-PKG is the seam `aeh.stats.promote` stores its
# per-administration figures through (the ProxyReport payload travels with them), so the
# schema the figures land in is this module's migration to land, by the same ownership
# rule that put `audit_record`'s append-only pair in `aeh.grade` (#103): the census's
# "enforced by the owning module" clause reads as *declared and written by the owner*.
# Three steps, one version:
#
# `package_validation` — one row per (package_version_id, cohort_id): the administration's
# promotion record. Figures and ids only (`TC-SYNTH-C10` scans every Tier D cell for
# narrative prose; this table must stay prose-free). `agreement_kappa` is **nullable** on
# purpose — an administration with no blind labels has no agreement figure, and the
# #111/#125 precedent says absence is reported as a first-class value, never as a zero and
# never as an earlier figure. The absence is the NULL plus the message that names it.
# `weakest_per_population` and `surface_proxy_flags` are JSON documents (criterion ids and
# flag names — figure-shaped, not prose), the latter carrying #117's `ProxyReport`
# payload seam through to the durable tier.
#
# `audit_record.cohort_id` — the promotion gate's first precondition (CT-STORE-10's
# "audit records" gate) needs the column to exist and to be written by a real promotion;
# the store's own purge preconditions were written against these ALTERs when the columns
# were simulated by tests. An additive nullable column is invisible to v7's append-only
# triggers and to the positional fixture builders (the leading-column insert).
#
# `criterion_stats.cohort_id` — rebuilt, not ALTERed: the administration dimension joins
# the key, because two administrations of the same package/criterion/profile/panel are
# separate records by #118's semantics, and the original PK would collide on the second.
# The rebuild follows `aeh.integ`'s v5 precedent — legacy columns lead in their original
# order, the new dim is NOT NULL DEFAULT '' so pre-#118 rows (there are none today: no
# writer of the table has ever shipped) keep their shape, and the copy step preserves any.
_PKG_DURABLE_008 = Migration(
    version=8,
    name="pkg_validation_record",
    statements=(
        Statement("ALTER TABLE audit_record ADD COLUMN cohort_id TEXT"),
        Statement(
            """
            CREATE TABLE criterion_stats_v8 (
                package_version_id TEXT    NOT NULL,
                criterion_id       TEXT    NOT NULL,
                backend_profile    TEXT    NOT NULL,
                panel_build_ref    TEXT    NOT NULL,
                n                  INTEGER NOT NULL CHECK (n >= 0),
                cohort_id          TEXT    NOT NULL DEFAULT '',
                PRIMARY KEY (package_version_id, criterion_id, backend_profile,
                             panel_build_ref, cohort_id)
            )
            """
        ),
        Statement(
            """
            INSERT INTO criterion_stats_v8
                (package_version_id, criterion_id, backend_profile, panel_build_ref,
                 n, cohort_id)
            SELECT package_version_id, criterion_id, backend_profile, panel_build_ref,
                   n, '' FROM criterion_stats
            """
        ),
        Statement("DROP TABLE criterion_stats"),
        Statement("ALTER TABLE criterion_stats_v8 RENAME TO criterion_stats"),
        Statement(
            """
            CREATE TABLE package_validation (
                package_version_id     TEXT    NOT NULL,
                cohort_id              TEXT    NOT NULL,
                recorded_at            TEXT    NOT NULL,
                cohorts_used           INTEGER NOT NULL CHECK (cohorts_used >= 0),
                operational_count      INTEGER NOT NULL CHECK (operational_count >= 0),
                blind_count            INTEGER NOT NULL CHECK (blind_count >= 0),
                n                      INTEGER NOT NULL CHECK (n >= 0),
                agreement_kappa        REAL,
                weakest_per_population TEXT    NOT NULL,
                surface_proxy_flags    TEXT    NOT NULL,
                message                TEXT    NOT NULL DEFAULT '',
                PRIMARY KEY (package_version_id, cohort_id)
            )
            """
        ),
    ),
)


TIER_MIGRATIONS[Tier.DURABLE] = tuple(sorted(
    TIER_MIGRATIONS[Tier.DURABLE] + (_PKG_DURABLE_008,), key=lambda m: m.version
))
