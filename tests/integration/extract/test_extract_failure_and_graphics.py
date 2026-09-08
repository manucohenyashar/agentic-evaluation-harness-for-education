"""`TC-EXTRACT-08` — a unit failing three times quarantines and writes NO empty
`evidence` row — and `TC-EXTRACT-09` — described-graphic regions are citable and a span
originating in one is marked.
Test plan §5.8; `FR-EXTRACT-08`, `FR-EXTRACT-09`.

Oracles:
- **TC-EXTRACT-08 — exact value plus row-absence**: the failure injected is the
  `M-PROV`-named one (a malformed reply: "parse failures retry and then surface" — the
  row that makes the three-strike quarantine well-defined). The provider boundary
  raises the shipped `MalformedResponseError` on every call; the worker must strike
  EXACTLY three times (not two, not four), leave the unit `quarantined`, and write
  ZERO evidence rows — an empty row is indistinguishable downstream from a student who
  wrote nothing, so absence is the assertion, not null-checking a written row.
- **TC-EXTRACT-09 — exact value**: the canonical document carries a real
  `described_graphic` region (the shipped `M-INGEST` header shape) next to a
  transcribed one; the reply's span into the graphic region is marked
  `region_kind="described_graphic"` and the span into the student's words
  `"transcribed_text"`, so `M-INTEG` and `M-JUDGE` can tell a student's words from a
  model's account of a picture. Citability is the byte round-trip: the graphic-region
  span addresses the canonical bytes exactly like any other span. The persisted
  evidence payload carries the same marking — the row is what `M-JUDGE` reads.

**Written ahead of #68** (`M-EXTRACT`). Registered in `WRITTEN_AHEAD_BLOCKERS` under
`"#68 extraction suite (TS-26)"` (symbols conjunction; see
`tests/support/extract_vocabulary.py`).

**Interface this case assumes of #68**, listed so it is reconciled deliberately:

| Name | Status |
|---|---|
| `ExtractionWorker(store, provider, model_ref).process(unit)` | **assumed here** — as in the spans file |
| `assemble_request(unit) -> ExtractionRequest`, `prompt_fields(request) -> PromptPayload` | **assumed / already assumed** — fixture recording needs the render |
| region parsing: a span the worker emits from a `described_graphic` region carries `region_kind="described_graphic"` | **assumed here** — the §3.8 span gains the `region_kind` marker (`FR-EXTRACT-09`); `REGION_KINDS` itself is shipped (`aeh.ingest`, #41) |
| retry semantics: every `ProviderError` from the boundary counts as one strike | **assumed here** — the taxonomy is shipped (`aeh.prov`, #55); if #68 discriminates further, this stub narrows to the parse case it already raises |

**Disclosed stand-ins.** The failing provider is a hand stub — the shipped
`RecordedFixtureProvider` records successes, and a stub counts the strikes the oracle
reads. The canonical document in TC-EXTRACT-09 composes the shipped region headers by
hand; the production composition is `M-INGEST`'s, and only the header shapes the
extractor must parse are load-bearing here. The reply format is `span_completion`'s
disclosed stand-in, with `region_kind` on the spans the same way.

**Isolation: rung 2** — real store, real ledger, real blob directory; the provider
boundary is the only fake (`RecordedFixtureProvider` where the reply succeeds, a
counting stub where it must fail).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.ingest import REGION_KINDS, UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.prov import MalformedResponseError
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

#: The canonical artifact of a submission whose answer is a labelled diagram: the
#: student's words in a transcribed region, the transcriber's account of the picture in
#: a described_graphic one — the shipped header shapes (`aeh.ingest`, #38/#41).
_GRAPHIC_HEADER = "<!-- region: kind=described_graphic element_kind=free_body_diagram -->"
_DIAGRAM_MARKDOWN = (
    UNTRUSTED_OPEN
    + "\n"
    + "<!-- region: kind=transcribed_text is_untrusted_content=1 -->\n"
    + "The crate sits on a 30 degree incline.\n"
    + "<!-- /region -->\n"
    + _GRAPHIC_HEADER + "\n"
    + "Labelled arrows: weight W down, normal N, friction f up the slope.\n"
    + "<!-- /region -->\n"
    + UNTRUSTED_CLOSE
)

_TRANSCRIBED_SPAN_TEXT = "The crate sits on a 30 degree incline."
_GRAPHIC_SPAN_TEXT = "weight W down, normal N, friction f up the slope."


class _FailingProvider:
    """A provider boundary whose every call raises the shipped parse-failure error —
    the failure M-PROV's Requires row names ("parse failures retry and then surface").
    Counts the strikes, which is the oracle's exact-value half."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls += 1
        raise MalformedResponseError(
            "extraction reply is not parseable span output (fixture: strike)"
        )


def _seed_document(store: Any, submission_id: str, markdown: str) -> None:
    """Seed the canonical artifact: markdown bytes into the blob store, a `document`
    row pointing at the hash (the disclosed M-INGEST stand-in)."""
    content_hash = store.blobs().put(markdown.encode("utf-8"))
    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash) "
            "VALUES (:d, :s, :h)",
            d=f"doc-{submission_id}-1", s=submission_id, h=content_hash,
        )


def _seed_world(store: Any, markdown: str) -> str:
    seed_cohort(store, ("SYN-001",))
    version = seed_package(store, _OPEN_CRITERIA)
    _seed_document(store, "SYN-001", markdown)
    return version


def _resolved() -> Any:
    return resolve_run_config(
        edge_cfg(panel=edge_panel(3)),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


def _byte_span(markdown: str, needle: str, region_kind: str) -> dict[str, Any]:
    md_bytes = markdown.encode("utf-8")
    start = md_bytes.find(needle.encode("utf-8"))
    assert start >= 0, f"fixture bug: {needle!r} not in the document"
    return {
        "start": start,
        "end": start + len(needle.encode("utf-8")),
        "text": needle,
        "region_kind": region_kind,
    }


def _evidence_count(store: Any, work_id: str | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM evidence"
    params: dict[str, Any] = {}
    if work_id is not None:
        sql += " WHERE work_id = :w"
        params["w"] = work_id
    return store.cohort(ORCH_COHORT_ID).query(sql, **params)[0]["n"]


def _unit_status(store: Any, work_id: str) -> str:
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT status FROM work_unit WHERE work_id = :w", w=work_id
    )
    assert rows, f"work_unit {work_id} vanished from the ledger"
    return rows[0]["status"]


def test_tc_extract_08_three_failures_quarantine_and_write_no_evidence_row(
    tmp_data_dir,
):
    """`TC-EXTRACT-08` — three malformed replies: exactly three strikes, the unit
    quarantines, and NO evidence row is written (an empty row would be
    indistinguishable from a student who wrote nothing)."""
    require(EXTRACT_MODULE, WORKER, RESULT_TYPE, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        version = _seed_world(store, _DIAGRAM_MARKDOWN)
        orchestrator = Orchestrator(store)
        run_id = orchestrator.create_run(ORCH_COHORT_ID, version, _resolved())
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)

        provider = _FailingProvider()
        model_ref = extractor_ref()
        Worker(store, provider, model_ref).process(unit)

        # The exact value: three strikes — not two, not four.
        assert provider.calls == 3, (
            f"the unit must strike exactly three times, saw {provider.calls} calls"
        )
        # The unit is quarantined, and the worker surfaces the outcome rather than
        # crashing the lease.
        assert _unit_status(store, unit.work_id) == "quarantined", (
            "a thrice-failing unit must quarantine"
        )
        # Row-absence: nothing for this unit, and nothing anywhere in the cohort's
        # evidence table.
        assert _evidence_count(store, unit.work_id) == 0, (
            "an evidence row was written for a quarantined unit — an empty row is "
            "indistinguishable downstream from a student who wrote nothing"
        )
        assert _evidence_count(store) == 0, (
            "the failed extraction left evidence rows behind"
        )
    finally:
        store.close()


def test_tc_extract_09_described_graphic_spans_are_citable_and_marked(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-09` — the span into the described-graphic region is marked
    `described_graphic`, the span into the student's words `transcribed_text`, both
    round-trip against the canonical bytes, and the persisted payload carries the
    marking `M-JUDGE` will read."""
    AssembleRequest, Worker, ExtractionResult = require(
        EXTRACT_MODULE, ASSEMBLE, WORKER, RESULT_TYPE, issue=ISSUE
    )
    PromptFields = require(EXTRACT_MODULE, PROMPT_FIELDS, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        # Precondition: the canonical artifact really carries the graphic region the
        # reply will cite.
        assert _GRAPHIC_HEADER in _DIAGRAM_MARKDOWN
        assert "described_graphic" in REGION_KINDS

        version = _seed_world(store, _DIAGRAM_MARKDOWN)
        spans = [
            _byte_span(_DIAGRAM_MARKDOWN, _TRANSCRIBED_SPAN_TEXT, "transcribed_text"),
            _byte_span(_DIAGRAM_MARKDOWN, _GRAPHIC_SPAN_TEXT, "described_graphic"),
        ]
        orchestrator = Orchestrator(store)
        run_id = orchestrator.create_run(ORCH_COHORT_ID, version, _resolved())
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)

        request = AssembleRequest(unit)
        model_ref = extractor_ref()
        provider = make_fixture_provider()
        provider.record(
            PromptFields(request), model_ref, sampling_params(),
            span_completion(spans, build_id="extractor-build-graphics"),
        )
        result = Worker(store, provider, model_ref).process(unit)

        emitted = list(result.spans)
        kinds = {
            _span_text_key(span): _span_region_kind(span) for span in emitted
        }
        assert kinds.get(_TRANSCRIBED_SPAN_TEXT) == "transcribed_text", (
            f"a span from the student's words is not marked transcribed_text: {kinds}"
        )
        assert kinds.get(_GRAPHIC_SPAN_TEXT) == "described_graphic", (
            f"a span from the described-graphic region is not marked "
            f"described_graphic: {kinds} — M-INTEG/M-JUDGE cannot tell a student's "
            f"words from a model's account of a picture"
        )
        assert set(kinds.values()) <= set(REGION_KINDS), (
            f"region_kind values outside the shipped vocabulary: {kinds}"
        )

        # Citability: byte round-trip for BOTH spans, the graphic one included.
        md_bytes = _DIAGRAM_MARKDOWN.encode("utf-8")
        for span in emitted:
            start = _span_field(span, "start")
            end = _span_field(span, "end")
            assert md_bytes[start:end].decode("utf-8") == _span_field(span, "text")

        # The persisted payload carries the same marking — the row is what M-JUDGE reads.
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT payload FROM evidence WHERE work_id = :w", w=unit.work_id
        )
        assert len(rows) == 1, f"expected one evidence row, got {len(rows)}"
        payload = rows[0]["payload"]
        payload_text = (
            payload.decode("utf-8") if isinstance(payload, (bytes, bytearray))
            else bytes(payload).decode("utf-8") if isinstance(payload, memoryview)
            else str(payload)
        )
        assert json.dumps("described_graphic")[1:-1] in payload_text, (
            "the persisted evidence payload lost the described_graphic marking"
        )
    finally:
        store.close()


def _span_text_key(span: Any) -> str:
    return _span_field(span, "text")


def _span_region_kind(span: Any) -> Any:
    kind = _span_field(span, "region_kind")
    assert kind is not None, f"span carries no region_kind marker: {span!r}"
    return kind


def _span_field(span: Any, name: str) -> Any:
    value = getattr(span, name, None)
    if value is None and isinstance(span, dict):
        value = span.get(name)
    assert value is not None, f"span missing {name!r}: {span!r}"
    return value
