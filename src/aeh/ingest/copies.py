"""A class's read papers, copied into another cohort file to be scored again (FR-CALIB-18).

The first class graded with a test whose clarified rubric R1 is pending is graded and delivered
under R0 as normal; a second scoring pass under R1 runs beside it. That pass must write nothing
into the class's own file: the class's reads show the file's newest run, so a second run there
would put R1's marks on the student pages. It runs in a calibration cohort instead (the reserved
id prefix keeps every class reader out of it, CT-CALIB-18), over the same papers.

The papers are not read again: re-reading would spend a second transcription and could read a
page differently, and then the two passes would not be scoring the same answers. What this
module copies is what intake wrote — each paper, its documents and their regions (plus the
unresolved tokens that keep a region's integrity signal) — with every id kept, so a paper's
score under R1 joins its score under R0 by submission id. The cohort row and its class list
belong to M-ORCH and are created by the caller before the copy.

Only the declared statements below run, keyword-parameterized (FR-STORE-08).
"""

from __future__ import annotations

from typing import Any

from aeh.store import Statement

from .errors import IngestError

#: Every statement the copy runs: reads against the class's file, inserts into the target's.
#: Spelled out in full (SEC-15): each column is named, so a column added later is a visible gap
#: in this list rather than a silent one.
COPY_STATEMENTS: dict[str, Statement] = {
    "select_submissions": Statement(
        "SELECT submission_id, student_ref, v0_integrity, v1_pages, v2_structure, "
        "v3_identity, v4_match, ingest_status, quarantined, v4_signals FROM submission "
        "WHERE cohort_id = :cohort_id ORDER BY submission_id"
    ),
    "select_documents": Statement(
        "SELECT document_id, submission_id, content_hash, markdown, transcriber_ref, "
        "prompt_template_version, kind, parent_doc_id, source_blobs, "
        "pages_with_text_layer, text_layer_divergence, created_at FROM document ORDER BY "
        "document_id"
    ),
    "select_regions": Statement(
        "SELECT region_id, document_id, page_no, element_kind, region_kind, description, "
        "retraction, ocr_conf, content_state, selection_state, selection, crop_ref, "
        "source_hash, page_index, position, is_untrusted_content, description_secondary, "
        "content, question_id FROM document_region ORDER BY region_id"
    ),
    "select_unresolved_tokens": Statement(
        "SELECT token, region_id, document_id FROM unresolved_token ORDER BY document_id, "
        "region_id, token"
    ),
    "select_target_submission_count": Statement(
        "SELECT COUNT(*) AS n FROM submission"
    ),
    "insert_submission": Statement(
        "INSERT INTO submission (cohort_id, submission_id, student_ref, v0_integrity, "
        "v1_pages, v2_structure, v3_identity, v4_match, ingest_status, quarantined, "
        "v4_signals) VALUES (:cohort_id, :submission_id, :student_ref, :v0_integrity, "
        ":v1_pages, :v2_structure, :v3_identity, :v4_match, :ingest_status, :quarantined, "
        ":v4_signals)"
    ),
    "insert_document": Statement(
        "INSERT INTO document (document_id, submission_id, content_hash, markdown, "
        "transcriber_ref, prompt_template_version, kind, parent_doc_id, source_blobs, "
        "pages_with_text_layer, text_layer_divergence, created_at) VALUES (:document_id, "
        ":submission_id, :content_hash, :markdown, :transcriber_ref, "
        ":prompt_template_version, :kind, :parent_doc_id, :source_blobs, "
        ":pages_with_text_layer, :text_layer_divergence, :created_at)"
    ),
    "insert_region": Statement(
        "INSERT INTO document_region (region_id, document_id, page_no, element_kind, "
        "region_kind, description, retraction, ocr_conf, content_state, selection_state, "
        "selection, crop_ref, source_hash, page_index, position, is_untrusted_content, "
        "description_secondary, content, question_id) VALUES (:region_id, :document_id, "
        ":page_no, :element_kind, :region_kind, :description, :retraction, :ocr_conf, "
        ":content_state, :selection_state, :selection, :crop_ref, :source_hash, "
        ":page_index, :position, :is_untrusted_content, :description_secondary, :content, "
        ":question_id)"
    ),
    "insert_unresolved_token": Statement(
        "INSERT INTO unresolved_token (token, region_id, document_id) VALUES (:token, "
        ":region_id, :document_id)"
    ),
}


def _parents_first(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The documents ordered so each one's parent is inserted before it."""
    placed: set[str] = set()
    known = {str(doc["document_id"]) for doc in documents}
    ordered: list[dict[str, Any]] = []
    pending = list(documents)
    while pending:
        rest = [doc for doc in pending
                if doc["parent_doc_id"] and str(doc["parent_doc_id"]) in known
                and str(doc["parent_doc_id"]) not in placed]
        ready = [doc for doc in pending if doc not in rest]
        if not ready:
            raise IngestError("the class's documents name each other as parents in a cycle; "
                              "nothing was copied")
        for doc in ready:
            ordered.append(doc)
            placed.add(str(doc["document_id"]))
        pending = rest
    return ordered


def copy_read_papers(source: Any, target: Any, *, source_cohort_id: str,
                     target_cohort_id: str) -> int:
    """Copy the class's read papers from `source` (its cohort file) into `target`, a cohort
    file whose cohort row and class list already exist and which holds no paper yet. Returns
    the number of papers copied. One transaction on the target: a refused or failed copy
    leaves it without any paper."""
    if target.query(COPY_STATEMENTS["select_target_submission_count"])[0]["n"]:
        raise IngestError(f"cohort {target_cohort_id!r} already holds papers; a copy is made "
                          "once, into an empty cohort")
    submissions = [dict(row) for row in source.query(
        COPY_STATEMENTS["select_submissions"], cohort_id=source_cohort_id)]
    documents = _parents_first([dict(row) for row in source.query(
        COPY_STATEMENTS["select_documents"])])
    regions = [dict(row) for row in source.query(COPY_STATEMENTS["select_regions"])]
    tokens = [dict(row) for row in source.query(COPY_STATEMENTS["select_unresolved_tokens"])]
    with target.transaction() as tx:
        for row in submissions:
            tx.execute(COPY_STATEMENTS["insert_submission"], cohort_id=target_cohort_id, **row)
        for row in documents:
            tx.execute(COPY_STATEMENTS["insert_document"], **row)
        for row in regions:
            tx.execute(COPY_STATEMENTS["insert_region"], **row)
        for row in tokens:
            tx.execute(COPY_STATEMENTS["insert_unresolved_token"], **row)
    return len(submissions)


__all__ = ["COPY_STATEMENTS", "copy_read_papers"]
