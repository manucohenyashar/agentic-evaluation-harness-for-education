"""Migrations for the document, region, gate and upload tables, and the SQL statements."""

from __future__ import annotations

from aeh.store import Migration, STATEMENTS, Statement, Tier, TIER_MIGRATIONS


# --- the Tier C migration this module contributes -------------------------------------------------
#
# The minimal `document` table (store 001) carried three columns and a NOT NULL
# submission. M-INGEST owns the canonical artifact, so its migration rebuilds the table
# with the canonical-Markdown columns and a NULLABLE submission (a setup artifact —
# assessment, reference, rubric — has no submission; `ingest_document` takes none).
# `transcriber_ref` and `markdown` are NOT NULL: a document without its transcript or
# its transcriber build is unrepresentable (`FR-INGEST-04`). Legacy rows migrated from
# 001 carry the empty string in the new columns — they predate transcription, and a
# CHECK that rejected them would make every pre-existing file unopenable; the data-layer
# guard refuses an empty ref on every row this module writes.

_INGEST_DOCUMENT_COLUMNS = Migration(
    version=2,
    name="ingest_document_core",
    statements=(
        # The children of document come along: document_region (this module's region
        # metadata, #38) and evidence (M-EXTRACT's, whose document_id FK would dangle
        # across the swap). Each is saved, dropped, and restored against the rebuilt
        # table with its original shape.
        Statement(
            """
            CREATE TABLE document_region_saved (
                region_id    TEXT    NOT NULL PRIMARY KEY,
                document_id  TEXT    NOT NULL,
                page_no      INTEGER NOT NULL,
                element_kind TEXT    NOT NULL
            )
            """
        ),
        Statement(
            "INSERT INTO document_region_saved (region_id, document_id, page_no, "
            "element_kind) SELECT region_id, document_id, page_no, element_kind "
            "FROM document_region"
        ),
        Statement(
            """
            CREATE TABLE evidence_saved (
                evidence_id TEXT NOT NULL PRIMARY KEY,
                work_id     TEXT NOT NULL,
                document_id TEXT
            )
            """
        ),
        Statement(
            "INSERT INTO evidence_saved (evidence_id, work_id, document_id) "
            "SELECT evidence_id, work_id, document_id FROM evidence"
        ),
        Statement("DROP TABLE evidence"),
        Statement("DROP TABLE document_region"),
        Statement(
            """
            CREATE TABLE document_new (
                document_id            TEXT    NOT NULL PRIMARY KEY,
                submission_id          TEXT    REFERENCES submission(submission_id),
                content_hash           TEXT    NOT NULL,
                markdown               TEXT    NOT NULL DEFAULT '',
                transcriber_ref        TEXT    NOT NULL DEFAULT '',
                prompt_template_version TEXT   NOT NULL DEFAULT '',
                kind                   TEXT    NOT NULL DEFAULT 'submission'
                    CHECK (kind IN ('assessment', 'reference', 'rubric', 'submission')),
                parent_doc_id          TEXT    REFERENCES document(document_id),
                source_blobs           TEXT,
                pages_with_text_layer  INTEGER,
                text_layer_divergence  REAL,
                created_at             TEXT
            )
            """
        ),
        Statement(
            "INSERT INTO document_new (document_id, submission_id, content_hash) "
            "SELECT document_id, submission_id, content_hash FROM document"
        ),
        Statement("DROP TABLE document"),
        Statement("ALTER TABLE document_new RENAME TO document"),
        Statement(
            """
            CREATE TABLE document_region (
                region_id    TEXT    NOT NULL PRIMARY KEY,
                document_id  TEXT    NOT NULL REFERENCES document(document_id),
                page_no      INTEGER NOT NULL CHECK (page_no >= 1),
                element_kind TEXT    NOT NULL
            )
            """
        ),
        Statement(
            "INSERT INTO document_region (region_id, document_id, page_no, "
            "element_kind) SELECT region_id, document_id, page_no, element_kind "
            "FROM document_region_saved"
        ),
        Statement("DROP TABLE document_region_saved"),
        Statement(
            """
            CREATE TABLE evidence (
                evidence_id TEXT NOT NULL PRIMARY KEY,
                work_id     TEXT NOT NULL REFERENCES work_unit(work_id),
                document_id TEXT REFERENCES document(document_id)
            )
            """
        ),
        Statement(
            "INSERT INTO evidence (evidence_id, work_id, document_id) "
            "SELECT evidence_id, work_id, document_id FROM evidence_saved"
        ),
        Statement("DROP TABLE evidence_saved"),
    ),
)


# The runtime statements only: migration DDL is versioned data in TIER_MIGRATIONS and
# deliberately stays out of the sanctioned runtime registry (the store's documented
# rule) — a DROP TABLE must never be a "declared" runtime statement.
_INGEST_REGION_COLUMNS = Migration(
    version=3,
    name="ingest_region_metadata",
    statements=(
        # FR-INGEST-13: exactly one of three kinds per region.
        Statement(
            "ALTER TABLE document_region ADD COLUMN region_kind TEXT "
            "NOT NULL DEFAULT 'transcribed_text' CHECK (region_kind IN "
            "('transcribed_text', 'described_graphic', 'selection_mark'))"
        ),
        # FR-INGEST-10: the structured description of a non-text region.
        Statement("ALTER TABLE document_region ADD COLUMN description TEXT"),
        # FR-INGEST-12: retractions keep BOTH versions.
        Statement("ALTER TABLE document_region ADD COLUMN retraction TEXT"),
        # FR-INGEST-15: per-region confidence — a document-level value does not
        # satisfy the read path M-INTEG uses.
        Statement("ALTER TABLE document_region ADD COLUMN ocr_conf REAL"),
        # FR-INGEST-16: present / blank / absent — absent and blank are distinct rows.
        Statement(
            "ALTER TABLE document_region ADD COLUMN content_state TEXT "
            "NOT NULL DEFAULT 'present' CHECK (content_state IN "
            "('present', 'blank', 'absent'))"
        ),
        # FR-INGEST-17: selection marks.
        Statement(
            "ALTER TABLE document_region ADD COLUMN selection_state TEXT "
            "CHECK (selection_state IN ('resolved', 'ambiguous', 'multiple_marks'))"
        ),
        Statement("ALTER TABLE document_region ADD COLUMN selection TEXT"),
        # FR-INGEST-13: a described_graphic's crop resolves to a retained image.
        Statement("ALTER TABLE document_region ADD COLUMN crop_ref TEXT"),
        # FR-INGEST-07: page provenance, per region.
        Statement("ALTER TABLE document_region ADD COLUMN source_hash TEXT"),
        Statement("ALTER TABLE document_region ADD COLUMN page_index INTEGER"),
        Statement("ALTER TABLE document_region ADD COLUMN position INTEGER"),
        # FR-INGEST-35: untrusted-content demarcation, per region.
        Statement(
            "ALTER TABLE document_region ADD COLUMN is_untrusted_content INTEGER "
            "NOT NULL DEFAULT 0 CHECK (is_untrusted_content IN (0, 1))"
        ),
        # FR-INGEST-14: the second description from a different model family.
        Statement("ALTER TABLE document_region ADD COLUMN description_secondary TEXT"),
    ),
)


_INGEST_GATE_COLUMNS = Migration(
    version=5,
    name="ingest_gate_columns",
    statements=(
        # FR-INGEST-29: each gate records its own outcome — never one boolean
        # (CT-INGEST-08). V4 fills with #41; the columns exist from the start.
        Statement("ALTER TABLE submission ADD COLUMN v0_integrity TEXT"),
        Statement("ALTER TABLE submission ADD COLUMN v1_pages TEXT"),
        Statement("ALTER TABLE submission ADD COLUMN v2_structure TEXT"),
        Statement("ALTER TABLE submission ADD COLUMN v3_identity TEXT"),
        Statement("ALTER TABLE submission ADD COLUMN v4_match TEXT"),
        Statement(
            "ALTER TABLE submission ADD COLUMN ingest_status TEXT "
            "CHECK (ingest_status IN ('ok', 'low_confidence_ocr', 'unreadable', "
            "'incomplete', 'unmatched_assessment'))"
        ),
        # FR-INGEST-30: quarantine state on the row — the operator surface reads it;
        # the teacher review queue must never contain a quarantined item.
        Statement(
            "ALTER TABLE submission ADD COLUMN quarantined INTEGER "
            "NOT NULL DEFAULT 0 CHECK (quarantined IN (0, 1))"
        ),
    ),
)


_INGEST_V4_MATCH = Migration(
    version=6,
    name="ingest_v4_match",
    statements=(
        # FR-INGEST-27: every V4 signal that fired is recorded ON the submission, so
        # the human deciding sees why — a JSON column next to the gate columns (the
        # signals are an open-shaped record: one entry per signal family, plus the
        # escalation's verdict when the model-assisted path ran).
        Statement("ALTER TABLE submission ADD COLUMN v4_signals TEXT"),
        # FR-INGEST-26: a mismatch may PROPOSE ranked candidates — recorded as a
        # proposal, applied only by a human. The table IS the distinction the plan's
        # oracle asserts: a proposal row here is not an assignment; nothing in this
        # schema or module writes another assessment onto the submission. The
        # resolution columns exist for the human's action (M-CONSOLE); the ingest
        # ladder never writes them.
        Statement(
            """
            CREATE TABLE assessment_match_proposal (
                proposal_id  TEXT NOT NULL PRIMARY KEY,
                submission_id TEXT NOT NULL REFERENCES submission(submission_id),
                v4_match     TEXT NOT NULL CHECK (v4_match IN ('mismatch')),
                candidates   TEXT NOT NULL,
                signals      TEXT NOT NULL,
                proposed_at  TEXT NOT NULL,
                resolved_at  TEXT,
                resolution   TEXT CHECK (resolution IN ('confirmed', 'rejected')
                                         OR resolution IS NULL)
            )
            """
        ),
        # FR-INGEST-28: the cohort circuit breaker — one row per cohort at most, so
        # ONE cohort-level finding is a property of the schema, not of caller
        # discipline: a second INSERT for the same cohort collides on the primary
        # key, which is how "exactly one finding" survives a concurrent ladder.
        Statement(
            """
            CREATE TABLE v4_cohort_breaker (
                cohort_id   TEXT NOT NULL PRIMARY KEY,
                tripped_at  TEXT NOT NULL,
                rate        REAL NOT NULL,
                flagged     INTEGER NOT NULL,
                ingested    INTEGER NOT NULL,
                finding     TEXT NOT NULL
            )
            """
        ),
    ),
)


_INGEST_TOKEN_CLUSTERS = Migration(
    version=4,
    name="ingest_token_clusters",
    statements=(
        # FR-INGEST-20: one cluster per visually-similar unresolved token, presented
        # ONCE for operator resolution; the resolution applies to every occurrence.
        Statement(
            "ALTER TABLE document_region ADD COLUMN content TEXT"
        ),
        Statement(
            """
            CREATE TABLE unresolved_token (
                token       TEXT NOT NULL,
                region_id   TEXT NOT NULL REFERENCES document_region(region_id),
                document_id TEXT NOT NULL REFERENCES document(document_id),
                PRIMARY KEY (token, region_id)
            )
            """
        ),
        Statement(
            """
            CREATE TABLE token_cluster (
                cluster_id  TEXT NOT NULL PRIMARY KEY,
                cohort_id   TEXT NOT NULL,
                token       TEXT NOT NULL,
                resolution  TEXT,
                resolved_at TEXT,
                UNIQUE (cohort_id, token)
            )
            """
        ),
    ),
)


#: Tier C, migration 23 (#355, `FR-INGEST-37`): the selection biconditional, as triggers.
#:
#: `CT-INGEST-05` says a resolved selection mark carries a selection. `FR-INGEST-36` makes the
#: writer honour it; these triggers make the DATABASE refuse the violating row, so no path —
#: this module's, a console's, an operator's hand-written UPDATE, a future writer nobody has
#: reviewed — can store `region_kind='selection_mark' AND selection_state='resolved' AND
#: selection IS NULL`. Defence in depth (`CT-INGEST-21`): the one state M-DET reads as
#: "unanswered" for a question the operator actually fixed is unrepresentable rather than
#: merely unwritten (RISK-50).
#:
#: Both directions, because either door reaches the same state: `BEFORE INSERT` for a row born
#: wrong, `BEFORE UPDATE` for one made wrong. Rows of other kinds are untouched — a
#: `transcribed_text` region has no selection to carry.
_INGEST_SELECTION_BICONDITIONAL: tuple[Statement, ...] = (
    # The rows the defect already wrote come first. A trigger validates the row being written,
    # never the ones already there, so a ledger carrying `resolved` + NULL selection would
    # migrate cleanly and then abort on the NEXT update of that row — including this module's
    # own content replacement, which would make one poisoned legacy row block every other
    # region in its cluster. They are put back to `ambiguous`: the honest state, since nobody
    # knows which option the operator meant, and the state M-DET already reads them as.
    Statement(
        "UPDATE document_region SET selection_state = 'ambiguous' "
        "WHERE region_kind = 'selection_mark' AND selection_state = 'resolved' "
        "AND selection IS NULL"
    ),
    Statement(
        "CREATE TRIGGER document_region_selection_insert_biconditional "
        "BEFORE INSERT ON document_region "
        "WHEN NEW.region_kind = 'selection_mark' AND NEW.selection_state = 'resolved' "
        "AND NEW.selection IS NULL "
        "BEGIN SELECT RAISE(ABORT, 'a resolved selection mark carries a selection "
        "(CT-INGEST-05, FR-INGEST-37): selection_state=resolved with selection NULL is the "
        "state M-DET reads as unanswered'); END"
    ),
    Statement(
        "CREATE TRIGGER document_region_selection_update_biconditional "
        "BEFORE UPDATE ON document_region "
        "WHEN NEW.region_kind = 'selection_mark' AND NEW.selection_state = 'resolved' "
        "AND NEW.selection IS NULL "
        "BEGIN SELECT RAISE(ABORT, 'a resolved selection mark carries a selection "
        "(CT-INGEST-05, FR-INGEST-37): selection_state=resolved with selection NULL is the "
        "state M-DET reads as unanswered'); END"
    ),
)


#: `#373`: which question a region belongs to, as a COLUMN.
#:
#: The fact was already in the parser (`#349` keeps it in memory) and already had a stored
#: home of a sort — `element_kind` is set to the declared `question_id` when there is one
#: (see the parser), so consumers read ownership out of a column that means two things at
#: once. That overloading is what forces the inference this migration removes: a graphic
#: declares no question, so it lands under `element_kind='graphic'`, and the only way to
#: learn that it belongs to Q2 is to look at what came before it in `position` order.
#:
#: Nullable, and no backfill. Regions written before this migration genuinely do not record
#: their owner, and inventing one now — by running that same positional inference once, at
#: migration time — would freeze a guess into the column and make it indistinguishable from
#: a parsed fact. A NULL here means "not recorded", which is the truth about those rows.
_INGEST_REGION_QUESTION_OWNER = (
    Statement("ALTER TABLE document_region ADD COLUMN question_id TEXT"),
)


TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (
        Migration(
            version=23, name="ingest_selection_biconditional",
            statements=_INGEST_SELECTION_BICONDITIONAL,
        ),
        Migration(
            version=27, name="ingest_region_question_owner",
            statements=_INGEST_REGION_QUESTION_OWNER,
        ),
    ), key=lambda m: m.version
))


INGEST_STATEMENTS: dict[str, Statement] = {
    "insert_document": Statement(
        "INSERT INTO document (document_id, submission_id, content_hash, markdown, "
        "transcriber_ref, prompt_template_version, kind, parent_doc_id, source_blobs, "
        "pages_with_text_layer, text_layer_divergence, created_at) VALUES (:document_id, "
        ":submission_id, :content_hash, :markdown, :transcriber_ref, "
        ":prompt_template_version, :kind, :parent_doc_id, :source_blobs, "
        ":pages_with_text_layer, :text_layer_divergence, :created_at)"
    ),
    "select_document": Statement(
        "SELECT document_id, submission_id, content_hash, markdown, transcriber_ref, "
        "prompt_template_version, kind, parent_doc_id, source_blobs, "
        "pages_with_text_layer, text_layer_divergence, created_at FROM document "
        "WHERE document_id = :document_id"
    ),
    "insert_region": Statement(
        "INSERT INTO document_region (region_id, document_id, page_no, element_kind, "
        "region_kind, description, retraction, ocr_conf, content_state, "
        "selection_state, selection, crop_ref, source_hash, page_index, position, "
        "is_untrusted_content, description_secondary, content, question_id) VALUES "
        "(:region_id, "
        ":document_id, :page_no, :element_kind, :region_kind, :description, "
        ":retraction, :ocr_conf, :content_state, :selection_state, :selection, "
        ":crop_ref, :source_hash, :page_index, :position, :is_untrusted_content, "
        ":description_secondary, :content, :question_id)"
    ),
    "select_regions": Statement(
        "SELECT region_id, document_id, page_no, element_kind, region_kind, "
        "description, retraction, ocr_conf, content_state, selection_state, "
        "selection, crop_ref, source_hash, page_index, position, "
        "is_untrusted_content, description_secondary, content, question_id "
        "FROM document_region "
        "WHERE document_id = :document_id ORDER BY position"
    ),
    "select_all_regions": Statement(
        "SELECT document_id, content FROM document_region"
    ),
    "update_region_resolution": Statement(
        "UPDATE document_region SET selection = :resolution, selection_state = "
        "'resolved' WHERE selection_state = 'ambiguous' AND selection = :token"
    ),
    "select_ambiguous_regions": Statement(
        "SELECT document_id, region_id, selection FROM document_region "
        "WHERE selection_state = 'ambiguous' AND selection IS NOT NULL"
    ),
    "insert_cluster": Statement(
        "INSERT INTO token_cluster (cluster_id, cohort_id, token, resolution, "
        "resolved_at) VALUES (:cluster_id, :cohort_id, :token, :resolution, "
        ":resolved_at)"
    ),
    "select_clusters": Statement(
        "SELECT cluster_id, cohort_id, token, resolution, resolved_at "
        "FROM token_cluster WHERE cohort_id = :cohort_id ORDER BY cluster_id"
    ),
    "insert_unresolved_token": Statement(
        "INSERT OR IGNORE INTO unresolved_token (token, region_id, document_id) "
        "VALUES (:token, :region_id, :document_id)"
    ),
    "select_unresolved_documents": Statement(
        "SELECT DISTINCT document_id FROM unresolved_token WHERE token = :token"
    ),
    "select_region_ids_for_token": Statement(
        "SELECT region_id FROM unresolved_token WHERE token = :token"
    ),
    # FR-INGEST-36 splits the old `update_region_content` in two. The single statement set
    # `selection_state = 'resolved'` for EVERY region kind and never wrote `selection`, so an
    # operator resolving an ambiguous tick stored a resolved selection mark with a NULL
    # selection and M-DET scored the question unanswered (RISK-50 — RISK-03 through a new
    # door). Text and graphic regions get their content replaced and nothing else; a selection
    # mark's selection and state are set together, in one statement, or not at all.
    "update_region_text": Statement(
        "UPDATE document_region SET content = REPLACE(content, "
        "'<unresolved>' || :token || '</unresolved>', :resolution) "
        "WHERE region_id = :region_id"
    ),
    "resolve_selection_region": Statement(
        "UPDATE document_region SET content = REPLACE(content, "
        "'<unresolved>' || :token || '</unresolved>', :resolution), "
        "selection = :selection, selection_state = 'resolved' "
        "WHERE region_id = :region_id"
    ),
    # The region's kind and its question (`element_kind` is the question id — M-DET's own
    # reading, `det._selection_reads`), for the per-kind rule.
    "select_regions_by_id": Statement(
        "SELECT region_id, region_kind, element_kind, question_id FROM document_region "
        "WHERE region_id = :region_id"
    ),
    # The declared option ids for one question, read off the package tier when the caller
    # names a catalog that is a bare handle rather than a `PackageCatalog`.
    "select_question_options": Statement(
        "SELECT option_id FROM question_option WHERE package_version_id = :v "
        "AND question_id = :question_id ORDER BY option_id"
    ),
    "delete_unresolved_token": Statement(
        "DELETE FROM unresolved_token WHERE token = :token"
    ),
    "insert_submission": Statement(
        "INSERT INTO submission (submission_id, cohort_id, student_ref) "
        "VALUES (:submission_id, :cohort_id, :student_ref)"
    ),
    "update_submission_gates": Statement(
        "UPDATE submission SET v0_integrity = :v0, v1_pages = :v1, "
        "v2_structure = :v2, v3_identity = :v3, v4_match = :v4, "
        "v4_signals = :v4_signals, "
        "ingest_status = :status, quarantined = :quarantined, "
        "student_ref = :student_ref WHERE submission_id = :submission_id"
    ),
    "select_roster": Statement(
        "SELECT student_ref FROM roster WHERE cohort_id = :cohort_id"
    ),
    # -- V4 (FR-INGEST-25..28) -------------------------------------------------------------------------
    # The scans already read into a document, for the intake command's re-run guard (B4).
    "select_submission_sources": Statement(
        "SELECT submission_id, source_blobs FROM document WHERE kind = 'submission'"
    ),
    # Blocker B4 review: a submission whose read was cut off (Ctrl-C, a killed process) keeps
    # the row `insert_submission` committed and no status (its document may or may not have
    # been written: the gates run after it). Run enumeration admits a NULL status as "not yet
    # judged", so it is parked as quarantined, through `update_submission_gates` (the one
    # writer of `ingest_status`, TC-INGEST-29).
    "select_interrupted_submissions": Statement(
        "SELECT submission_id, student_ref FROM submission WHERE ingest_status IS NULL "
        "ORDER BY submission_id"
    ),
    "select_assessment_documents": Statement(
        "SELECT document_id, parent_doc_id, markdown FROM document "
        "WHERE kind = 'assessment' ORDER BY document_id"
    ),
    "select_v4_rate": Statement(
        "SELECT COUNT(*) AS ingested, "
        "SUM(CASE WHEN v4_match IN ('uncertain', 'mismatch') THEN 1 ELSE 0 END) "
        "AS flagged FROM submission WHERE cohort_id = :cohort_id"
    ),
    "insert_match_proposal": Statement(
        "INSERT INTO assessment_match_proposal (proposal_id, submission_id, "
        "v4_match, candidates, signals, proposed_at) VALUES (:proposal_id, "
        ":submission_id, :v4_match, :candidates, :signals, :proposed_at)"
    ),
    "select_match_proposals": Statement(
        "SELECT proposal_id, submission_id, v4_match, candidates, signals, "
        "proposed_at, resolved_at, resolution FROM assessment_match_proposal "
        "WHERE submission_id = :submission_id"
    ),
    "insert_cohort_breaker": Statement(
        "INSERT OR IGNORE INTO v4_cohort_breaker (cohort_id, tripped_at, rate, "
        "flagged, ingested, finding) VALUES (:cohort_id, :tripped_at, :rate, "
        ":flagged, :ingested, :finding)"
    ),
    "select_cohort_breaker": Statement(
        "SELECT cohort_id, tripped_at, rate, flagged, ingested, finding "
        "FROM v4_cohort_breaker WHERE cohort_id = :cohort_id"
    ),
    "select_document_head": Statement(
        "SELECT document_id, submission_id, content_hash, transcriber_ref, kind, "
        "parent_doc_id, created_at, markdown FROM document "
        "WHERE submission_id = :submission_id "
        "ORDER BY created_at, document_id"
    ),
    # -- the run-level aggregate emitter (#222, F3/G4; CT-INGEST-19/OBS-01) ----------------------------
    # One path each: the emitter reads the cohort's rows through these and
    # no consumer recomputes the counts. Setup artifacts (documents with a
    # NULL submission) are outside every cohort join by construction.
    "select_cohort_gate_rows": Statement(
        "SELECT submission_id, v0_integrity, v1_pages, v2_structure, "
        "v3_identity, v4_match, quarantined FROM submission "
        "WHERE cohort_id = :cohort_id"
    ),
    "select_cohort_documents": Statement(
        "SELECT d.pages_with_text_layer, d.text_layer_divergence FROM document d "
        "JOIN submission s ON d.submission_id = s.submission_id "
        "WHERE s.cohort_id = :cohort_id"
    ),
    "select_cohort_mark_regions": Statement(
        "SELECT r.selection_state FROM document_region r "
        "JOIN document d ON r.document_id = d.document_id "
        "JOIN submission s ON d.submission_id = s.submission_id "
        "WHERE s.cohort_id = :cohort_id AND r.region_kind = 'selection_mark'"
    ),
    "select_document_second_described_regions": Statement(
        "SELECT r.region_id, r.element_kind, r.crop_ref, r.description, "
        "r.description_secondary, d.source_blobs FROM document_region r "
        "JOIN document d ON d.document_id = r.document_id "
        "WHERE r.document_id = :document_id AND r.region_kind = 'described_graphic' "
        "ORDER BY r.position, r.region_id"
    ),
    "select_cohort_second_pass_regions": Statement(
        "SELECT r.description, r.description_secondary FROM document_region r "
        "JOIN document d ON r.document_id = d.document_id "
        "JOIN submission s ON d.submission_id = s.submission_id "
        "WHERE s.cohort_id = :cohort_id AND r.description_secondary IS NOT NULL"
    ),
}


# --- Tier C, migration 32 (#531, `FR-CONSOLE-27`): what an upload delivered ---------------------
#
# The upload handler staged the bytes and recorded nothing, so the page order S2 asks a teacher
# to check before transcription could only be invented. One row per uploaded part: its name (the
# filename tier orders by it), the content address of its first chunk, and when it arrived.
_INGEST_UPLOAD_PART = Migration(
    version=32,
    name="ingest_upload_part",
    statements=(
        Statement(
            """
            CREATE TABLE upload_part (
                cohort_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                blob_ref TEXT NOT NULL,
                received_at TEXT NOT NULL,
                PRIMARY KEY (cohort_id, filename, blob_ref)
            )
            """
        ),
    ),
)


INGEST_STATEMENTS.update({
    "insert_upload_part": Statement(
        "INSERT OR IGNORE INTO upload_part (cohort_id, filename, blob_ref, received_at) "
        "VALUES (:cohort_id, :filename, :blob_ref, :received_at)"
    ),
    "select_upload_parts": Statement(
        "SELECT filename FROM upload_part WHERE cohort_id = :cohort_id ORDER BY rowid"
    ),
})


STATEMENTS.update(INGEST_STATEMENTS)


TIER_MIGRATIONS[Tier.COHORT] = (
    TIER_MIGRATIONS[Tier.COHORT]
    + (_INGEST_DOCUMENT_COLUMNS,)
    + (_INGEST_REGION_COLUMNS,)
    + (_INGEST_TOKEN_CLUSTERS,)
    + (_INGEST_GATE_COLUMNS,)
    + (_INGEST_V4_MATCH,)
    + (_INGEST_UPLOAD_PART,)
)
