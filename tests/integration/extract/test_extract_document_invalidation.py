"""`TC-EXTRACT-12` — emitted offsets address the exact `document` version recorded on
the submission, and a superseded document invalidates the evidence through the work-ID
scheme rather than by manual cleanup.
Test plan §5.8; `NFR-EXTRACT-02`, with `CT-INGEST-02/03` as the immutability grounds.

Oracles — **invariant**:
- **Exact version addressing**: the evidence row records the `document_id` it was
  extracted from (the shipped `evidence.document_id` column), and its spans round-trip
  against the bytes THAT row addresses (fetched through `document_id → content_hash →
  blob`) — never against any other version's bytes.
- **No sliding**: after the document is superseded (`CT-INGEST-02`: a correction is a
  NEW immutable row, never a mutation), the old evidence is untouched, still addresses
  the old version, and its offsets do NOT round-trip against the new version's bytes —
  the version binding has teeth, not just a label.
- **Invalidation is addressing, not cleanup**: a fresh run over the superseded
  submission re-extracts against the current document and writes evidence carrying the
  NEW `document_id`, under NEW work-ids (a new run's units are new addresses — the
  work-ID scheme), while the old row remains exactly as it was. Nothing is mutated,
  nothing is deleted, nothing is reconciled by hand.

**Written ahead of #68** (`M-EXTRACT`). Registered in `WRITTEN_AHEAD_BLOCKERS` under
`"#68 extraction suite (TS-26)"` (symbols conjunction; see
`tests/support/extract_vocabulary.py`).

**Interface this case assumes of #68**, listed so it is reconciled deliberately:

| Name | Status |
|---|---|
| `ExtractionWorker(store, provider, model_ref).process(unit)` | **assumed here** — as in the suite's other integration files |
| `assemble_request(unit)`, `prompt_fields(request)` | **assumed / already assumed** — fixture recording needs the render |
| the worker extracts against the submission's CURRENT document and writes its `document_id` onto the evidence row | **assumed here** — the shipped `evidence.document_id` column is the storage contract (`NFR-EXTRACT-02`'s "recorded on the submission"); if #68 names the column differently the read here is one line |

**Disclosed stand-ins.** The supersession is a seeded INSERT of the v2 document row
after v1 — `CT-INGEST-02`'s new-row rule done by hand; how the worker resolves the
submission's current document is #68's to fix, and the assertions read the outcome
(the recorded `document_id` and the round-trips), not the resolution. Seeding bypasses
`M-INGEST` as everywhere in this suite (docstring disclosure). The completion is
`span_completion`'s disclosed stand-in.

**Isolation: rung 2** — real store, real ledger, real blob directory,
`RecordedFixtureProvider` at the only model boundary.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.ingest import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.extract_vocabulary import (
    ASSEMBLE,
    EXTRACT_ISSUE,
    PROMPT_FIELDS,
    RESULT_TYPE,
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package

pytestmark = [pytest.mark.integration]

ISSUE = EXTRACT_ISSUE

_OPEN_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)

_SUBMISSION = "SYN-001"

#: v1 of the canonical artifact: the student cites a rate of 12 kg/h...
_V1_MARKDOWN = (
    UNTRUSTED_OPEN
    + "\n"
    + "The rate is 12 kg per hour.\n"
    + UNTRUSTED_CLOSE
)
#: ...v2 (a re-transcription) says 13. The same byte offsets CANNOT address both.
_V2_MARKDOWN = (
    UNTRUSTED_OPEN
    + "\n"
    + "The rate is 13 kg per hour.\n"
    + UNTRUSTED_CLOSE
)

_SPAN_TEXT_V1 = "The rate is 12 kg per hour."
_SPAN_TEXT_V2 = "The rate is 13 kg per hour."


def _insert_document(store: Any, document_id: str, submission_id: str, markdown: str) -> str:
    """One immutable document row + its blob bytes (the disclosed M-INGEST stand-in).
    Supersession = a second call with a new id, per CT-INGEST-02."""
    content_hash = store.blobs().put(markdown.encode("utf-8"))
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash) "
            "VALUES (:d, :s, :h)",
            d=document_id, s=submission_id, h=content_hash,
        )
    return content_hash


def _resolved() -> Any:
    return resolve_run_config(
        edge_cfg(panel=edge_panel(3)),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


def _extract(store: Any, provider: Any, version: str, *, spans: list[dict[str, Any]],
             document_id: str) -> tuple[Any, Any]:
    """One fresh run + lease + one recorded reply + one worker pass."""
    AssembleRequest, Worker, ExtractionResult = require(
        EXTRACT_MODULE, ASSEMBLE, WORKER, RESULT_TYPE, issue=ISSUE
    )
    PromptFields = require(EXTRACT_MODULE, PROMPT_FIELDS, issue=ISSUE)
    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(ORCH_COHORT_ID, version, _resolved())
    (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)
    request = AssembleRequest(unit, store=store)
    model_ref = extractor_ref()
    provider.record(
        PromptFields(request), model_ref, sampling_params(),
        span_completion(spans, build_id="extractor-build-versions"),
    )
    result = Worker(store, provider, model_ref).process(unit)
    _ = document_id  # the worker's own resolution decides the row's document_id
    return result, run_id


def _evidence_row(store: Any, work_id: str) -> Any:
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT e.evidence_id, e.work_id, e.document_id, e.payload "
        "FROM evidence e WHERE e.work_id = :w",
        w=work_id,
    )
    assert len(rows) == 1, f"expected exactly one evidence row, got {len(rows)}"
    return rows[0]


def _document_bytes(store: Any, document_id: str) -> bytes:
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT content_hash FROM document WHERE document_id = :d", d=document_id
    )
    assert rows, f"fixture bug: document {document_id!r} not found"
    return store.blobs().get(rows[0]["content_hash"])


def _payload_spans(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, memoryview):
        payload = bytes(payload)
    if isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload).decode("utf-8")
    if isinstance(payload, str):
        payload = json.loads(payload)
    spans = payload.get("spans") if isinstance(payload, dict) else payload
    assert isinstance(spans, list), f"unparsable evidence payload: {payload!r}"
    return spans


def _round_trip(document_bytes: bytes, span: Any) -> bool:
    start, end, text = span["start"], span["end"], span["text"]
    if not (0 <= start <= end <= len(document_bytes)):
        return False
    try:
        return document_bytes[start:end].decode("utf-8") == text
    except UnicodeDecodeError:
        return False


def test_tc_extract_12_offsets_address_the_exact_recorded_document_version(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-12` (exact version) — the evidence row records the document it was
    extracted from, and its spans round-trip against THAT version's bytes."""
    require(EXTRACT_MODULE, WORKER, RESULT_TYPE, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, (_SUBMISSION,))
        version = seed_package(store, _OPEN_CRITERIA)
        _insert_document(store, "doc-v1", _SUBMISSION, _V1_MARKDOWN)

        spans = [{"start": _V1_MARKDOWN.encode("utf-8").find(_SPAN_TEXT_V1.encode("utf-8")),
                  "end": _V1_MARKDOWN.encode("utf-8").find(_SPAN_TEXT_V1.encode("utf-8"))
                  + len(_SPAN_TEXT_V1.encode("utf-8")),
                  "text": _SPAN_TEXT_V1}]
        _result, run_id = _extract(
            store, make_fixture_provider(), version,
            spans=spans, document_id="doc-v1",
        )
        units = store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id FROM work_unit WHERE run_id = :r AND stage = :st",
            r=run_id, st=STAGE_EXTRACT,
        )
        assert len(units) == 1, "precondition: one extract unit expected"

        row = _evidence_row(store, units[0]["work_id"])
        # The row addresses a real document version — the one the submission records.
        assert row["document_id"], "evidence row records no document_id"
        document_bytes = _document_bytes(store, row["document_id"])
        for span in _payload_spans(row["payload"]):
            assert _round_trip(document_bytes, span), (
                f"span {span!r} does not round-trip against the document the evidence "
                f"row itself addresses ({row['document_id']!r}) — the offsets do not "
                f"address the exact recorded version"
            )
    finally:
        store.close()


def test_tc_extract_12_supersession_invalidates_by_addressing_not_cleanup(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-12` (supersession) — the old evidence stays addressed to v1 and
    does NOT round-trip against v2's bytes; a fresh run re-extracts under v2 and
    writes NEW evidence under NEW work-ids; nothing is mutated or cleaned by hand."""
    require(EXTRACT_MODULE, WORKER, RESULT_TYPE, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        seed_cohort(store, (_SUBMISSION,))
        version = seed_package(store, _OPEN_CRITERIA)
        _insert_document(store, "doc-v1", _SUBMISSION, _V1_MARKDOWN)

        v1_bytes = _V1_MARKDOWN.encode("utf-8")
        v1_start = v1_bytes.find(_SPAN_TEXT_V1.encode("utf-8"))
        spans_v1 = [{"start": v1_start, "end": v1_start + len(_SPAN_TEXT_V1.encode("utf-8")),
                     "text": _SPAN_TEXT_V1}]
        _result, run_v1 = _extract(
            store, provider, version, spans=spans_v1, document_id="doc-v1",
        )
        old_units = store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id FROM work_unit WHERE run_id = :r AND stage = :st",
            r=run_v1, st=STAGE_EXTRACT,
        )
        old_row_before = _evidence_row(store, old_units[0]["work_id"])

        # The document is superseded: a NEW immutable row for the same submission
        # (CT-INGEST-02), never a mutation of v1.
        _insert_document(store, "doc-v2", _SUBMISSION, _V2_MARKDOWN)
        assert _document_bytes(store, "doc-v1") == v1_bytes, (
            "supersession mutated the old document row"
        )

        # A fresh run re-extracts against the current (v2) document.
        v2_bytes = _V2_MARKDOWN.encode("utf-8")
        v2_start = v2_bytes.find(_SPAN_TEXT_V2.encode("utf-8"))
        spans_v2 = [{"start": v2_start, "end": v2_start + len(_SPAN_TEXT_V2.encode("utf-8")),
                     "text": _SPAN_TEXT_V2}]
        _result, run_v2 = _extract(
            store, provider, version, spans=spans_v2, document_id="doc-v2",
        )

        # The work-ID scheme: the fresh run's units are NEW addresses.
        new_units = store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id FROM work_unit WHERE run_id = :r AND stage = :st",
            r=run_v2, st=STAGE_EXTRACT,
        )
        assert len(new_units) == 1
        assert new_units[0]["work_id"] != old_units[0]["work_id"], (
            "the re-run shares the old unit's work_id — invalidation cannot happen "
            "through the work-ID scheme if the address does not move"
        )

        # The old evidence is untouched and still addresses v1.
        old_row_after = _evidence_row(store, old_units[0]["work_id"])
        assert old_row_after["document_id"] == old_row_before["document_id"] == "doc-v1", (
            "the old evidence row slid onto the new document version"
        )
        assert _round_trip(_document_bytes(store, "doc-v1"),
                           _payload_spans(old_row_after["payload"])[0]), (
            "the old evidence no longer round-trips against its own version"
        )
        # ...and has teeth: v1's offsets do NOT address v2.
        assert not _round_trip(v2_bytes, _payload_spans(old_row_after["payload"])[0]), (
            "the v1 span also round-trips against v2 — the version binding is a label, "
            "not an address (the fixture texts must differ where the span cites)"
        )

        # The new evidence addresses v2 exactly.
        new_row = _evidence_row(store, new_units[0]["work_id"])
        assert new_row["document_id"] == "doc-v2", (
            f"fresh evidence addresses {new_row['document_id']!r}, not the superseded-"
            f"in document doc-v2 — no manual cleanup happened, so the addressing must "
            f"carry the new version"
        )
        assert _round_trip(v2_bytes, _payload_spans(new_row["payload"])[0])
    finally:
        store.close()
