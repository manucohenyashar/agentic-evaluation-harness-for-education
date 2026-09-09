"""`TC-EXTRACT-14` — extraction payloads and stored evidence are Tier R student PII
and are purged with it.
Test plan §5.8; `NFR-EXTRACT-04`, `CT-EXTRACT-13`: extraction payloads carry **verbatim
student work** — the strictest tier — so the working store after a run must come out of
a purge with none of it.

Oracle — **post-purge absence**, against real bytes:
- before the purge, the student's verbatim sentence is provably present in BOTH places
  the module puts it (the `evidence` payload and the document blob) — the absence
  assertions would otherwise be vacuous;
- after `purge_cohort`, the `evidence` table is EMPTY (the payload lives in the row —
  a side table or out-of-row blob store for payloads is the design point this case
  exists to catch, and the shipped purge refuses a store it cannot fully sweep), and
  NO file under the blob directory contains the student's sentence — the
  `TC-STORE-11`/`SEC-13` reclaim-by-evidence idiom, read against extraction's bytes.

**Written ahead of #68** (`M-EXTRACT`). Registered in `WRITTEN_AHEAD_BLOCKERS` under
`"#68 extraction suite (TS-26)"` (symbols conjunction; see
`tests/support/extract_vocabulary.py`).

**Interface this case assumes of #68**: `ExtractionWorker(store, provider,
model_ref).process(unit)` and `assemble_request`/`prompt_fields` — as everywhere in
the suite; the storage contract under test is the SHIPPED one (`evidence` in
`_COHORT_PURGE_ORDER`, payloads in-row).

**Disclosed stand-ins.** Seeding bypasses `M-INGEST` as everywhere in this suite; the
completion is `span_completion`'s disclosed stand-in. The purge machinery itself is
shipped (`M-STORE`, #55/#225) and NOT under test here — it is the instrument, the same
role the fixture provider plays in the other cases; if this test fails on the purge
half, the failure names a store regression, not an extract one.

**Isolation: rung 2** — real store, real Tier R rows, real blob directory on disk;
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

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = EXTRACT_ISSUE

_OPEN_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)

#: The PII sentinel: verbatim student work, unique enough that "no file contains it"
#: is a byte-level statement, not a word-overlap one.
_SENTENCE = "My burner calibration read zxq-pii-7q4 degrees at noon."

_MARKDOWN = (
    UNTRUSTED_OPEN
    + "\n"
    + _SENTENCE
    + "\n"
    + UNTRUSTED_CLOSE
)


def _seed_document(store: Any, submission_id: str, markdown: str) -> None:
    content_hash = store.blobs().put(markdown.encode("utf-8"))
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash) "
            "VALUES (:d, :s, :h)",
            d=f"doc-{submission_id}-1", s=submission_id, h=content_hash,
        )


def _blob_dir_texts(tmp_data_dir: Any) -> list[str]:
    """Every blob file's bytes, decoded lossily — what "no blob contains the sentence"
    is read against (the TC-STORE-11 idiom)."""
    texts = []
    for blob_file in sorted((tmp_data_dir / "blobs").rglob("*")):
        if blob_file.is_file():
            texts.append(blob_file.read_bytes().decode("utf-8", errors="replace"))
    return texts


def _extract(store: Any, provider: Any, version: str) -> str:
    """One run, one lease, one recorded reply, one worker pass; returns the unit's
    work_id."""
    AssembleRequest, Worker, ExtractionResult = require(
        EXTRACT_MODULE, ASSEMBLE, WORKER, RESULT_TYPE, issue=ISSUE
    )
    PromptFields = require(EXTRACT_MODULE, PROMPT_FIELDS, issue=ISSUE)
    resolved = resolve_run_config(
        edge_cfg(panel=edge_panel(3)),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )
    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(ORCH_COHORT_ID, version, resolved)
    (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)
    request = AssembleRequest(unit, store=store)
    model_ref = extractor_ref()
    # Calibration (disclosed in the PR): the span addresses the sentence by BYTE
    # offset in the canonical artifact, like every other file's `_byte_span` — the
    # sentence does not start at offset 0 (the fence tag is there first), and the
    # parse derives `text` from the bytes the offsets address, so a canned span whose
    # offsets cannot round-trip is refused, not persisted.
    sentence_start = _MARKDOWN.encode("utf-8").find(_SENTENCE.encode("utf-8"))
    assert sentence_start > 0, "fixture bug: the sentence is not in the document"
    provider.record(
        PromptFields(request), model_ref, sampling_params(),
        span_completion(
            [{
                "start": sentence_start,
                "end": sentence_start + len(_SENTENCE.encode("utf-8")),
                "text": _SENTENCE,
            }],
            build_id="extractor-build-pii",
        ),
    )
    Worker(store, provider, model_ref).process(unit)
    return unit.work_id


def test_tc_extract_14_extraction_payloads_are_purged_with_the_tier_r_rows(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-14` — after the purge, no evidence row and no blob carries the
    student's verbatim work."""
    require(EXTRACT_MODULE, WORKER, RESULT_TYPE, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("SYN-001",))
        version = seed_package(store, _OPEN_CRITERIA)
        _seed_document(store, "SYN-001", _MARKDOWN)
        work_id = _extract(store, make_fixture_provider(), version)

        # Precondition (non-vacuity): the sentence is in BOTH stores, verbatim.
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT payload FROM evidence WHERE work_id = :w", w=work_id
        )
        assert rows, "precondition: the extraction wrote no evidence row"
        payload = rows[0]["payload"]
        payload_text = (
            bytes(payload).decode("utf-8") if isinstance(payload, memoryview)
            else payload.decode("utf-8") if isinstance(payload, (bytes, bytearray))
            else payload if isinstance(payload, str)
            else json.dumps(payload)
        )
        assert _SENTENCE in payload_text, (
            "precondition: the evidence payload does not carry the student's verbatim "
            "work — the purge-absence below would be vacuous"
        )
        assert any(_SENTENCE in text for text in _blob_dir_texts(tmp_data_dir)), (
            "precondition: the document blob does not hold the student's work"
        )

        # The purge (shipped M-STORE instrument).
        store.purge_cohort(ORCH_COHORT_ID)

        # Post-purge absence, byte-level.
        remaining = store.cohort(ORCH_COHORT_ID).query("SELECT COUNT(*) AS n FROM evidence")
        assert remaining[0]["n"] == 0, (
            "evidence rows survived the purge — extraction payloads are Tier R "
            "student PII and are purged WITH the tier"
        )
        assert not any(_SENTENCE in text for text in _blob_dir_texts(tmp_data_dir)), (
            "the student's verbatim work is still in the blob directory after the "
            "purge"
        )
    finally:
        store.close()
