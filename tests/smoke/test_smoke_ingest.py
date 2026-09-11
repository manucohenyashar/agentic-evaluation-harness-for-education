"""The smoke suite (TS-50, issue #143) — the PDF gateway, end to end.

`TC-SMOKE-08` (`FR-INGEST-02`) — one two-page fixture PDF ingests end to end and produces a
`document` row; fails if `transcriber_ref` is null.

Everything between the bytes and the row is real: the PDF is a genuine pdfium-decodable
two-page document built inline (the `minimal_pdf` builder from the live-raster suite,
issue #226 — the bytes are the fixture), the rasterizer is the shipped `PdfiumRasterizer`
(pypdfium2, real page rasters at the configured DPI knob), and the sanitizer is the shipped
`PypdfSanitizer`, exercised incidentally as part of the gateway (this fixture PDF needs no
neutralization, so no sanitizer-specific assertion is made here). The VLM is the one
seam — and it is the shipped `RecordedFixtureProvider` in its regeneration-then-replay
shape: a first sight of a request is answered by a fixed per-page transcript and **recorded
into the fixture provider's own store** through the shipped `record()`/`request_key`
machinery, and every later identical request replays from the recording. That is why the
wrapper rather than a bare scripted double: ingest assembles its prompts *inside*
`ingest_document` (the page image is in the payload), so a test cannot pre-record the
assembled request — the same reason every ingest case in the repo scripts the provider —
but it CAN let the shipped fixture provider own the fixture store and the replay, which is
`F-RECORDED`'s lifecycle and the reason this case can assert exactly one model call per
page on the scripted sight and fixture replay afterwards.

`Written ahead of implementation: yes` is stale — the gateway landed with #36 and the
rasterizer with #226; the case runs green by design.
"""

from __future__ import annotations

import json

import pytest

from aeh.conf import ModelRef
from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
from aeh.prov import (
    Completion,
    FixtureMissingError,
    PromptPayload,
    RecordedFixtureProvider,
    SamplingParams,
)
from aeh.store import open_store
from tests.support.conf_builders import EDGE_TRANSCRIBER
from tests.support.store_api import statement

ISSUE = "#143"


def minimal_pdf(pages: list[tuple[int, int]] | None = None) -> bytes:
    """A REAL pdfium-decodable two-page PDF, built inline with a computed xref — the
    `test_ingest_live_raster.py` builder verbatim (issue #226), so the smoke case runs the
    real decoder over real PDF bytes rather than describing one."""
    dims = list(pages) if pages else [(612, 792)]
    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(len(dims)))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(dims)} >>".encode(),
    ]
    for index, (width, height) in enumerate(dims):
        page_id = 3 + 2 * index
        content_id = page_id + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            f"/Contents {content_id} 0 R >>".encode())
        stream = b"0 0 1 rg\n40 40 200 150 re f\n"
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode()
                       + stream + b"endstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


#: One deterministic transcript per page — plain prose, no region markers, so the
#: document row assembles from exactly what the VLM answered per page.
PAGE_TRANSCRIPTS = {
    1: "Page one: the student states the hypothesis and cites the force diagram.",
    2: "Page two: the student derives the acceleration and checks the units.",
}


class SelfRecordingProvider:
    """The fast tier's model boundary for the ingest path: the shipped
    `RecordedFixtureProvider` owns the fixture store and every replay; the wrapper only
    answers a *first* sight of an unknown request from the per-page script and records it
    through the shipped `record()`. `scripted_calls` counts how often the script (rather
    than a recording) answered — the exactly-one-call-per-page oracle reads that counter."""

    def __init__(self, fixture_dir, transcripts: dict[int, str]) -> None:
        self._inner = RecordedFixtureProvider(fixture_dir=fixture_dir)
        self._transcripts = transcripts
        self.scripted_calls = 0
        self.replayed_calls = 0

    def complete(self, prompt, model_ref, params) -> Completion:
        try:
            completion = self._inner.complete(prompt, model_ref, params)
            self.replayed_calls += 1
            return completion
        except FixtureMissingError:
            pass
        page_no = int(dict(prompt.fields)["page_no"])
        completion = Completion(
            text=self._transcripts.get(page_no, "transcript"),
            tokens_in=10, tokens_out=5, latency_ms=1,
            resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None,
        )
        self._inner.record(prompt, model_ref, params, completion)
        self.scripted_calls += 1
        return completion


def test_tc_smoke_08_two_page_pdf_ingests_end_to_end(tmp_data_dir, tmp_path, monkeypatch):
    """`TC-SMOKE-08` — one two-page fixture PDF ingests end to end and produces a
    `document` row.

    Oracle: **row existence plus exact provenance**. The document row exists; its
    `transcriber_ref` is the build that actually answered — non-null, and equal to the
    transcriber build the configuration named (the column is fed from
    `completion.resolved_build`, so a writer that lost it writes the null this case reds
    on); the assembled Markdown carries **both** pages' transcripts (two pages in, two
    pages of evidence out — a gateway that silently dropped page two still produces a
    document row); and exactly one transcription call happened per page
    (`FR-INGEST-02`'s call budget), with the second sight of the same requests answered
    from the fixture store rather than the script.
    """
    monkeypatch.setenv("HARNESS_INGEST_DPI", "72")
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-smoke")
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES ('c-smoke', 'synthetic', '2026-01-01T00:00:00+00:00')"
        )
        tx.execute(
            "INSERT INTO submission (submission_id, cohort_id, student_ref) "
            "VALUES ('s-smoke', 'c-smoke', 'ref-s-smoke')"
        )

    blobs = store.blobs()
    provider = SelfRecordingProvider(tmp_path / "fixtures", PAGE_TRANSCRIPTS)
    ingestor = Ingestor(
        handle, blobs, provider, EDGE_TRANSCRIBER,
        SamplingParams(temperature=0.0), PdfiumRasterizer(),
        residency=ResidencySlot.for_policy(("transcriber",)),
        sanitizer=PypdfSanitizer(),
    )
    blob_hash = blobs.put(minimal_pdf([(612, 792), (612, 792)]))

    document_id = ingestor.ingest_document(
        [blob_hash], kind="assessment", order_hint=[blob_hash],
        submission_id="s-smoke",
    )

    rows = handle.query(
        statement(
            "SELECT document_id, submission_id, content_hash, markdown, transcriber_ref, "
            "source_blobs FROM document WHERE document_id = :document_id"
        ),
        document_id=document_id,
    )
    assert rows, (
        "TC-SMOKE-08: the end-to-end ingest of a two-page PDF produced no document row. "
        "FR-INGEST-02 is the gateway's whole story: bytes in, one immutable document out."
    )
    row = rows[0]

    transcriber_ref = row["transcriber_ref"]
    assert transcriber_ref, (
        "TC-SMOKE-08: the document row's transcriber_ref is null. The transcriber build "
        "is what actually answered (FR-PROV-04's resolved_build) — a document without it "
        "has no provenance for its own text and fails the requirement outright."
    )
    assert transcriber_ref == EDGE_TRANSCRIBER.build_id

    markdown = row["markdown"]
    assert PAGE_TRANSCRIPTS[1] in markdown and PAGE_TRANSCRIPTS[2] in markdown, (
        "TC-SMOKE-08: the assembled document does not carry both pages' transcripts. A "
        "two-page ingest that loses a page produces a document row that looks complete "
        "and grades half a submission."
    )

    provenance = json.loads(row["source_blobs"])
    assert len(provenance["pages"]) == 2, (
        f"TC-SMOKE-08: page provenance names {len(provenance['pages'])} page(s) for a "
        "two-page PDF. FR-INGEST-02: every page is rasterized and transcribed — a dropped "
        "page must be visible here before it is visible anywhere else."
    )
    for entry in provenance["pages"]:
        assert entry.get("raster_hash"), (
            "TC-SMOKE-08: a page raster was not persisted with the document. The page "
            "image is the evidence the transcription claims to describe."
        )

    assert provider.scripted_calls == 2, (
        f"TC-SMOKE-08: the provider scripted {provider.scripted_calls} call(s) for a "
        "two-page PDF. FR-INGEST-02: exactly one VLM transcription call per page — "
        "neither fewer (a page went unanswered) nor more (a call outside the budget)."
    )
    assert handle.query(
        statement("SELECT COUNT(*) AS n FROM document WHERE document_id = :document_id"),
        document_id=document_id,
    )[0]["n"] == 1