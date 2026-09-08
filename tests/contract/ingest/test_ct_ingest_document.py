"""`CT-INGEST-02` / `CT-INGEST-03` — document immutability and span durability
(`TC-INGEST-C02`, `TC-INGEST-C03`).

Cases of test plan §6.11.5; issue #49 (TS-62). Green by design — #36..#42 landed
the module.

`CT-INGEST-02`: a document is immutable — `document.markdown` is written once
with its `content_hash` and its `transcriber_ref` is never null; a correction
(`revise_document`) emits a NEW row with `parent_doc_id` set, never a rewrite.
The static half reads the declared registry: no statement whose target is
`document` is an UPDATE or a DELETE. The behavioural half runs a correction and
holds the original byte-stable across it.

`CT-INGEST-03`: the spans consumers compute are byte offsets into
`document.markdown`, and the markdown they point into is durable — stored
verbatim, byte-stable across reopen, hashed over UTF-8 bytes. The producer half
pins the artifact the offsets point into; the consumer half (a span whose stored
work-ID no longer matches the document it is resolved against is detected, not
silently applied) needs the extract/integration seam, which does not exist yet
(`work_unit` carries no `document_id` column — G5 in `_doubles`' docstring), so
it is deferred with disclosure, keyed on M-EXTRACT #68..#71 / M-INTEG #73..#76.
The byte-offset-vs-char-offset DISCRIMINATOR is equally deferred: shipped code
has no span writer at all — a region's `position` is an assembled-sequence
ordinal (`aeh/ingest.py:1855`), not a byte offset — so the multi-byte fixture
below asserts the UTF-8≠UTF-16 property the future resolution must disagree
under, but no stored value is ever resolved AS an offset; that half lands with
M-EXTRACT.

Discriminator: `CT-INGEST-02`'s registry sweep and the byte-stability assertions
go red if the clause breaks (an UPDATE slips into the registry, a correction
mutates the original row, the stored markdown is re-encoded) while every FR-*
case stays green — the FR cases assert what a fresh ingest *produces*, not that
what was produced is never rewritten.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from aeh.ingest import IngestError, PageReplacement
from aeh.store import open_store
from tests.contract.ingest._doubles import (
    ISSUE,
    Contract,
    answer_text,
    statement_texts,
    student_answer,
    written_tables,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract


# -- TC-INGEST-C02: the document row is written once, and corrections are new rows --------------------


def test_tc_ingest_c02_the_registry_has_no_rewrite_of_document():
    """`TC-INGEST-C02` (static half) — no declared statement's target is
    `document` under UPDATE or DELETE: the only writes to the document row are
    the registry's INSERTs. The sweep reads the declared literals, not a
    database, so a new write cannot pass unnoticed (the pkg/store suites' same
    discipline)."""
    pattern = re.compile(r"\b(?:UPDATE|DELETE\s+FROM)\s+document\b",
                         re.IGNORECASE)
    offenders = {name: sql for name, sql in statement_texts().items()
                 if pattern.search(sql)}
    assert not offenders, (
        f"TC-INGEST-C02: declared statements rewrite the document row: {offenders}. "
        "A document is written once; a correction is a new row (CT-INGEST-02)."
    )
    # The guard is only meaningful if the registry actually writes documents.
    assert "document" in written_tables(), (
        "TC-INGEST-C02: the registry no longer writes `document` — the sweep is "
        "vacuous, which is a broken walker, not a passing clause."
    )


def test_tc_ingest_c02_the_stored_row_carries_hash_ref_and_markdown_together(
        tmp_data_dir):
    """`TC-INGEST-C02` (behavioural half) — a fresh ingest stores, together on
    one row: `content_hash` = sha256 over the markdown's UTF-8 bytes,
    `transcriber_ref` = the build that actually answered (never empty), and the
    markdown itself."""
    fx = Contract(tmp_data_dir, "c02-row")
    fx.add_roster("alice")
    source = fx.put(b"c02 pdf")
    fx.script(source, {1: student_answer("alice", answer_text("Q1", "4/2 = 2"))})
    document_id = fx.ingestor.ingest_document([source], kind="submission",
                                              filenames={source: "a.pdf"})
    row = fx.documents("document_id = :d", d=document_id)[0]
    assert row["content_hash"] == hashlib.sha256(
        row["markdown"].encode("utf-8")).hexdigest(), (
        "TC-INGEST-C02: content_hash is not sha256 over the stored markdown's "
        "bytes — the identity consumers verify against has no anchor."
    )
    assert row["transcriber_ref"] == fx.model.build_id and row["transcriber_ref"], (
        f"TC-INGEST-C02: transcriber_ref {row['transcriber_ref']!r} is not the "
        "answering build — a document without its transcriber build is "
        "unrepresentable (the clause's never-null guarantee)."
    )
    assert row["markdown"].strip() and "4/2 = 2" in row["markdown"], (
        "TC-INGEST-C02: the stored markdown lost the transcript."
    )
    assert row["kind"] == "submission"
    fx.close()


def test_tc_ingest_c02_a_correction_mints_a_new_row_and_the_original_is_byte_stable(
        tmp_data_dir):
    """`TC-INGEST-C02` (correction half) — `revise_document` returns a DIFFERENT
    id whose row carries `parent_doc_id` and a new hash, and the original row —
    every column — is byte-identical before and after the correction."""
    fx = Contract(tmp_data_dir, "c02-revise")
    fx.add_roster("alice")
    source = fx.put(b"c02 revise pdf")
    fx.script(source, {1: student_answer("alice", answer_text("Q1", "part one"))})
    original_id = fx.ingestor.ingest_document([source], kind="submission",
                                              filenames={source: "a.pdf"})
    before = fx.documents("document_id = :d", d=original_id)[0]

    rescan = fx.put(b"c02 rescan pdf")
    fx.script(rescan, {1: "corrected page"})
    revised_id = fx.ingestor.revise_document(
        original_id, [PageReplacement(blob_hash=rescan, page_no=1)])

    after = fx.documents("document_id = :d", d=original_id)[0]
    assert revised_id != original_id, (
        "TC-INGEST-C02: the correction returned the same id — it rewrote instead "
        "of minting a new row."
    )
    revised = fx.documents("document_id = :d", d=revised_id)[0]
    assert revised["parent_doc_id"] == original_id, (
        f"TC-INGEST-C02: the revised row's parent_doc_id is "
        f"{revised['parent_doc_id']!r}, not the original."
    )
    assert dict(before) == dict(after), (
        "TC-INGEST-C02: the original document row changed across the correction "
        f"(before {dict(before)} vs after {dict(after)})."
    )
    assert revised["content_hash"] != before["content_hash"], (
        "TC-INGEST-C02: the correction produced the same content_hash — the "
        "replacement page did not reach the markdown."
    )
    assert revised["transcriber_ref"] == fx.model.build_id, (
        "TC-INGEST-C02: the revised row carries no transcriber build."
    )
    fx.close()


def test_tc_ingest_c02_a_correction_names_a_missing_document_only_by_refusal(
        tmp_data_dir):
    """`TC-INGEST-C02` (edge) — revising a document id that does not exist is a
    refusal, not a silent new row."""
    fx = Contract(tmp_data_dir, "c02-missing")
    rescan = fx.put(b"rescan")
    with pytest.raises(IngestError, match="does not exist"):
        fx.ingestor.revise_document("doc-nonexistent",
                                    [PageReplacement(blob_hash=rescan,
                                                     page_no=1)])
    assert fx.documents() == [], (
        "TC-INGEST-C02: a refused correction left a document row behind."
    )
    fx.close()


# -- TC-INGEST-C03: the markdown the spans point into is durable and byte-exact -----------------------


def test_tc_ingest_c03_markdown_round_trips_byte_exact_across_reopen(tmp_data_dir):
    """`TC-INGEST-C03` (producer half) — a transcript whose content is
    multi-byte (the byte-vs-char offset hazard, the clause's named one) is
    stored VERBATIM: the same bytes are read back through a fresh handle on the
    same data dir, the hash stays sha256-over-bytes, and no region row's
    position can drift because the artifact never moved. The consumer half (a
    stale work-ID is *detected*) is deferred with the extract/integration seam —
    G5 in `_doubles`' docstring."""
    fx = Contract(tmp_data_dir, "c03-bytes")
    fx.add_roster("aja")
    # The multi-byte hazard: CJK before and combining marks inside the answer,
    # so char offsets and byte offsets disagree everywhere.
    body = ("解答：да — " + "caf" + chr(0x65) + chr(0x301) + " proof " + chr(0x1f914))
    source = fx.put(b"c03 pdf")
    fx.script(source, {1: student_answer("aja", answer_text("Q1", body))})
    document_id = fx.ingestor.ingest_document([source], kind="submission",
                                              filenames={source: "a.pdf"})
    row = fx.documents("document_id = :d", d=document_id)[0]
    markdown = row["markdown"]

    assert markdown.encode("utf-8") != markdown.encode("utf-16-le"), (
        "TC-INGEST-C03: the fixture does not carry the multi-byte hazard it "
        "exists for — the corpus changed under the test."
    )
    assert row["content_hash"] == hashlib.sha256(
        markdown.encode("utf-8")).hexdigest(), (
        "TC-INGEST-C03: the hash is not over the markdown's UTF-8 bytes — a "
        "consumer computing byte offsets against it cannot anchor a span."
    )

    # Durable: a FRESH store on the same data dir reads the same bytes.
    fx.store.close()
    reopened_store = open_store(fx.root)
    reopened_handle = reopened_store.cohort("c-ingest-ct")
    reopened_row = reopened_handle.query(statement(
        "SELECT document_id, submission_id, content_hash, markdown, "
        "transcriber_ref, prompt_template_version, kind, parent_doc_id, "
        "source_blobs, pages_with_text_layer, text_layer_divergence, "
        "created_at FROM document WHERE document_id = :d", issue=ISSUE),
        d=document_id)[0]
    assert reopened_row["markdown"] == markdown, (
        "TC-INGEST-C03: the markdown moved across reopen — byte offsets "
        "computed before the reopen now point elsewhere (the clause's "
        "durability half)."
    )
    assert reopened_row["content_hash"] == row["content_hash"], (
        "TC-INGEST-C03: the hash changed across reopen with unchanged bytes — "
        "the anchor is unstable."
    )
    # And every region the page produced is accounted for inside that artifact.
    regions = reopened_handle.query(statement(
        "SELECT * FROM document_region WHERE document_id = :d", issue=ISSUE),
        d=document_id)
    assert regions, "TC-INGEST-C03: the document carries no regions at all."
    assert all(isinstance(r["position"], int) for r in regions), (
        "TC-INGEST-C03: a region's position is not an integer ordinal — the "
        "ordering spans resolve against is gone."
    )
    reopened_store.close()
