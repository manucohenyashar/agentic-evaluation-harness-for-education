"""`TC-EXTRACT-01`, `TC-EXTRACT-02`, `TC-EXTRACT-05` — spans are byte offsets into the
canonical Markdown, the `evidence` row is one per (run, submission, criterion) with no
judge dimension, and every row carries the extractor's **resolved** build identity.
Test plan §5.8; `FR-EXTRACT-01`, `FR-EXTRACT-02`, `FR-EXTRACT-05`.

Oracles:
- **TC-EXTRACT-01 — round-trip invariant**: `markdown[start:end]` decoded equals `text`
  for every span, where `markdown` is the submission's canonical artifact as bytes. The
  document is built so ASCII, 2-byte (é), 3-byte (中) and 4-byte (emoji) characters all
  sit inside cited material — a module that emits character offsets, or that re-slices
  the transcript by character index anywhere between the model reply and the persisted
  span, fails the round trip on the first multi-byte span.
- **TC-EXTRACT-02 — schema assertion plus differential**: exactly one `evidence` row for
  the (run, submission, criterion) triple although the panel has three judges; no judge
  column exists on `evidence` at all; and the evidence **payload bytes** are identical
  across two runs over the same submission that differ only in panel depth — a payload
  that leaked judge or panel context would differ, and that is the differential, not a
  non-null check. **Disclosed substitution**: the plan's literal differential compares
  the evidence bytes each judge's scoring REQUEST carried — `M-JUDGE` (#78) is not
  landed, so that comparison is not rung-feasible here; the panel-depth pair is what
  is. It is deliberately stricter than the plan: any run-level metadata inside the
  payload (a `work_id` echo, a timestamp) fails the cross-run byte-identity, which pins
  the payload to the span set and nothing else.
- **TC-EXTRACT-05 — exact value**: the row's build identity equals the
  `resolved_build` the provider reported on the completion (`FR-PROV-04`: the build that
  actually answered, never the one requested).

**Written ahead of #68** (`M-EXTRACT`); the marker and its `WRITTEN_AHEAD_BLOCKERS`
entry (`"#68 extraction suite (TS-26)"`, a conjunction over the module names this
suite resolves, built from `tests/support/extract_vocabulary.py` — design §3.8 pins
no Python names, so every one is an invented-and-used-together name, the
`record_run_start` precedent) left when #68 landed `aeh.extract`.

**Interface this case assumes of #68**, listed so it is reconciled deliberately:

| Name | Status |
|---|---|
| `ExtractionWorker(store, provider, model_ref).process(unit) -> ExtractionResult` | **assumed here** — the driver; §3.8 names no Python surface |
| `assemble_request(unit) -> ExtractionRequest` | **assumed here** — the pure assembly; `submission.transcript` carries the canonical Markdown per the §3.8 Interfaces JSON |
| `prompt_fields(request) -> PromptPayload` | **already assumed by the repo** — the `"#68 review"` registry entry resolves it; the fixture recording needs the same render (`CT-PROV-05` makes field order contract) |
| the `evidence` row's build column, read here as `resolved_build` | **assumed here** — `FR-EXTRACT-05`/`CT-EXTRACT-05` put the identity "on every evidence row"; if #68 names the column differently the rename here is one line |
| the `evidence` row's payload column, read here as `payload` | **assumed here** — where the persisted span set lives, and the span set is ALL it lives with (no run-level metadata: TC-EXTRACT-02's cross-panel byte-identity pins this); `evidence_id`/`work_id`/`document_id` are the shipped migration-001 columns |

**Disclosed stand-ins.** Seeding writes the `document` row and its blob bytes directly —
the production writer is `M-INGEST` (landed, but driven by files and rasterized pages
this case does not exercise). The rows written are exactly the shipped DDL's
(`document(document_id, submission_id, content_hash)` + the blob the hash names), and
the markdown is wrapped in `M-INGEST`'s real untrusted-content delimiters, so the
canonical artifact the worker reads is real-shaped. The completion recorded into
`RecordedFixtureProvider` is built by `span_completion` — the assumed reply format,
one place in the vocabulary file.

**Isolation: rung 2** — real store, real Tier P package, real cohort ledger, real
blob directory, `RecordedFixtureProvider` as the only model boundary.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aeh.conf import resolve_run_config
from aeh.conf import CohortRef
from aeh.ingest import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.store import open_store
from tests.support.conf_builders import EDGE_JUDGE, edge_panel, edge_cfg
from tests.support.extract_vocabulary import (
    ASSEMBLE,
    EXTRACT_ISSUE,
    PROMPT_FIELDS,
    REQUEST_TYPE,
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

_JUDGED = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)

#: The multi-byte ladder of TC-EXTRACT-01: each UTF-8 encoding width sits inside the
#: cited material, so the first multi-byte span decides the coordinate system.
_UTF8_MARKDOWN = (
    UNTRUSTED_OPEN
    + "\n"
    + "The rate is 12 kg per hour.\n"            # ASCII
    + "Café temperature élevée.\n"                # é — 2 bytes
    + "中心 temperature noted.\n"                 # 中 — 3 bytes
    + "Alarm raised: \U0001F6A8 on the log.\n"    # emoji — 4 bytes
    + UNTRUSTED_CLOSE
)

_DOC = "doc-syn001-1"


def _seed_document(store: Any, submission_id: str, markdown: str) -> str:
    """Seed the canonical artifact: markdown bytes into the blob store, a `document`
    row pointing at the hash. The production writer is `M-INGEST`; this is the
    disclosed stand-in recorded in this file's docstring."""
    md_bytes = markdown.encode("utf-8")
    content_hash = store.blobs().put(md_bytes)
    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash) "
            "VALUES (:d, :s, :h)",
            d=_DOC,
            s=submission_id,
            h=content_hash,
        )
    return content_hash


def _byte_span(markdown: str, needle: str) -> dict[str, Any]:
    """A canned span over `needle`, located by BYTE offset — what the test records into
    the fixture. The module under test must keep the coordinate system intact; the
    round-trip assertion in TC-EXTRACT-01 is what decides that."""
    md_bytes = markdown.encode("utf-8")
    start = md_bytes.find(needle.encode("utf-8"))
    assert start >= 0, f"fixture bug: {needle!r} not in the document"
    return {"start": start, "end": start + len(needle.encode("utf-8")), "text": needle}


def _seed_world(store: Any, markdown: str) -> str:
    """Cohort + package + canonical document, once; runs are created over them."""
    seed_cohort(store, ("SYN-001",))
    version = seed_package(store, _JUDGED)
    _seed_document(store, "SYN-001", markdown)
    return version


def _resolved(panel: tuple) -> Any:
    return resolve_run_config(
        edge_cfg(panel=panel),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


def _extract_once(
    store: Any,
    provider: Any,
    version: str,
    *,
    panel: tuple,
    spans: list[dict[str, Any]],
    build_id: str,
):
    """Create a run over the seeded world, lease its extract unit, record the reply
    for the exact request the worker will make, and drive the worker once.
    Returns `(request, result, run_id)`."""
    AssembleRequest, Worker, ExtractionResult = require(
        EXTRACT_MODULE, ASSEMBLE, WORKER, RESULT_TYPE, issue=ISSUE
    )
    PromptFields = require(EXTRACT_MODULE, PROMPT_FIELDS, issue=ISSUE)

    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(ORCH_COHORT_ID, version, _resolved(panel))
    (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)

    request = AssembleRequest(unit, store=store)
    model_ref = extractor_ref()
    provider.record(
        PromptFields(request), model_ref, sampling_params(),
        span_completion(spans, build_id=build_id),
    )
    result = Worker(store, provider, model_ref).process(unit)
    return request, result, run_id


def _evidence_rows(store: Any, run_id: str) -> list[Any]:
    """The evidence row(s) for the run's (submission, criterion) extract unit, with the
    unit's judge column and the row's payload and build identity."""
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT e.evidence_id, e.work_id, e.payload, e.resolved_build, w.judge_id "
        "FROM evidence e JOIN work_unit w ON w.work_id = e.work_id "
        "WHERE w.run_id = :r AND w.submission_id = :s AND w.criterion_id = :c "
        "AND w.stage = :st",
        r=run_id,
        s="SYN-001",
        c="C1",
        st=STAGE_EXTRACT,
    )


def _as_bytes(payload: Any) -> bytes:
    if payload is None:
        raise AssertionError("evidence payload is NULL — the row was written empty")
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, memoryview):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def test_tc_extract_01_spans_are_byte_offsets_that_round_trip_over_utf8(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-01` — every span carries `start`, `end`, `text`; offsets are BYTE
    offsets into `document.markdown`; slicing the canonical bytes and decoding equals
    `text` for every span."""
    require(EXTRACT_MODULE, ASSEMBLE, WORKER, RESULT_TYPE, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        spans = [
            _byte_span(_UTF8_MARKDOWN, "The rate is 12 kg per hour."),
            _byte_span(_UTF8_MARKDOWN, "Café temperature élevée."),
            _byte_span(_UTF8_MARKDOWN, "中心 temperature noted."),
            _byte_span(_UTF8_MARKDOWN, "\U0001F6A8 on the log"),
        ]
        version = _seed_world(store, _UTF8_MARKDOWN)
        request, result, _run_id = _extract_once(
            store, make_fixture_provider(), version,
            panel=edge_panel(3), spans=spans, build_id="extractor-build-1",
        )

        markdown = request.submission.transcript
        assert isinstance(markdown, str)
        md_bytes = markdown.encode("utf-8")
        # The request carries exactly the canonical artifact the submission records.
        assert md_bytes.decode("utf-8") == _UTF8_MARKDOWN

        emitted = list(result.spans)
        assert len(emitted) == len(spans)
        for span, expected in zip(emitted, spans, strict=True):
            start = getattr(span, "start", None)
            end = getattr(span, "end", None)
            text = getattr(span, "text", None)
            if start is None and isinstance(span, dict):
                start, end, text = span["start"], span["end"], span["text"]
            assert None not in (start, end, text), f"span missing a field: {span!r}"
            assert (start, end, text) == (
                expected["start"], expected["end"], expected["text"]
            )
            # THE round trip: byte offsets, decoded — not character offsets.
            assert md_bytes[start:end].decode("utf-8") == text, (
                f"span {start}:{end} does not round-trip to {text!r}"
            )
    finally:
        store.close()


def test_tc_extract_02_one_evidence_row_no_judge_dimension_identical_bytes_across_panels(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-02` — three judges scoring the same (submission, criterion) read ONE
    `evidence` row; the row carries no judge dimension; and the payload bytes are
    identical to a second run whose panel is one judge deep."""
    require(EXTRACT_MODULE, WORKER, RESULT_TYPE, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        spans = [_byte_span(_UTF8_MARKDOWN, "The rate is 12 kg per hour.")]
        version = _seed_world(store, _UTF8_MARKDOWN)

        panel3, panel1 = edge_panel(3), edge_panel(1)
        _request_a, _result_a, run_a = _extract_once(
            store, provider, version, panel=panel3, spans=spans,
            build_id="extractor-build-2",
        )
        _request_b, _result_b, run_b = _extract_once(
            store, provider, version, panel=panel1, spans=spans,
            build_id="extractor-build-2",
        )

        # The 3-judge run really enumerates three score arms — the differential is
        # against real panel depth, not a vacuous one-judge stand-in.
        arms = store.cohort(ORCH_COHORT_ID).query(
            "SELECT judge_id FROM work_unit WHERE run_id = :r AND stage = 'score' "
            "AND submission_id = :s AND criterion_id = :c ORDER BY judge_id",
            r=run_a, s="SYN-001", c="C1",
        )
        assert len(arms) == 3, (
            f"precondition: expected 3 score units for the panel, got {len(arms)}"
        )

        rows_a = _evidence_rows(store, run_a)
        assert len(rows_a) == 1, (
            f"evidence must be one row per (run, submission, criterion), got "
            f"{len(rows_a)} — a row per judge is the keying CT-EXTRACT-03 forbids"
        )
        assert rows_a[0]["judge_id"] is None
        # No judge column exists on the evidence table under any name.
        columns = [
            row["name"]
            for row in store.cohort(ORCH_COHORT_ID).query("PRAGMA table_info(evidence)")
        ]
        assert not [c for c in columns if "judge" in c.lower()], (
            f"evidence carries a judge dimension: {columns}"
        )
        payload_a = _as_bytes(rows_a[0]["payload"])

        rows_b = _evidence_rows(store, run_b)
        assert len(rows_b) == 1
        payload_b = _as_bytes(rows_b[0]["payload"])
        assert payload_a == payload_b, (
            "evidence bytes differ between a 3-judge and a 1-judge run over the same "
            "submission — the payload leaked panel context, which is what the "
            "differential exists to catch"
        )
    finally:
        store.close()


def test_tc_extract_05_evidence_row_carries_the_providers_resolved_build(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-05` — the extractor's RESOLVED build identity is on the evidence row
    and equals what the provider reported, not what was requested."""
    require(EXTRACT_MODULE, WORKER, RESULT_TYPE, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        answered_build = "extractor-build-actually-answered"
        spans = [_byte_span(_UTF8_MARKDOWN, "The rate is 12 kg per hour.")]
        version = _seed_world(store, _UTF8_MARKDOWN)
        _request, result, run_id = _extract_once(
            store, make_fixture_provider(), version,
            panel=edge_panel(3), spans=spans, build_id=answered_build,
        )

        # The result reports the resolved build (`Completion.resolved_build` is
        # "what actually answered", FR-PROV-04) — never a request-time identity.
        assert getattr(result, "resolved_build", None) == answered_build

        # ...and the PERSISTED row carries the same identity.
        rows = _evidence_rows(store, run_id)
        assert len(rows) == 1
        assert rows[0]["resolved_build"] == answered_build, (
            f"evidence build identity {rows[0]['resolved_build']!r} != the provider's "
            f"resolved build {answered_build!r}"
        )
    finally:
        store.close()
