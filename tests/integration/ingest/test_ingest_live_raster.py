"""The LIVE raster surface (`TC-INGEST-49`, the regression for issue #226).

F9 (disclosed on TC-INGEST-45's live half, found by PRs #204 + #211):
`ingest_document` calls `self._rasterizer.crop(...)` for every
`described_graphic` region, but `PdfiumRasterizer` implemented only
`rasterize`/`text_layer` — no shipped class defined `crop` (probe:
`grep "def crop" src/` found nothing), so the live path raised
`AttributeError` the moment a described_graphic ingest ran. The scripted
double carried the method, which is why the fast tier stayed green. F1/G7:
the full-page rasters were transcribed and then discarded — only crops were
written — while `FR-STORE-06` names page rasters among the blobs the store
keeps. F10: `pypdfium2` was not declared anywhere a fresh clone installs.

This suite runs the described_graphic path end-to-end through the REAL
`PdfiumRasterizer` (pypdfium2, lazy-imported; the sanitizer stays a pass-through
double — the real sanitizer is rung 2's corpus suite). The crop bytes and the
persisted page rasters assertable in the blob store come out of pypdfium2, not
out of any double.

Design interpretations recorded here (the design is silent on both):

- **Crop geometry.** A box is `(x, y, w, h)` in the RASTER PIXEL SPACE of the
  requested DPI — the form the ingest path already speaks, since its no-box
  default passes the full-page pixel rect of the raster it just made
  (`(0, 0, image.width_px, image.height_px)`).
- **Out-of-bounds refusal.** A crop reaching outside the page (or a degenerate
  or negative box) is REFUSED, never clamped: a clamped crop would silently
  resolve a `described_graphic`'s `crop_ref` to an image other than the one
  the description described, which is exactly the mismatch `FR-INGEST-13`'s
  "resolving" forbids. The operator sees the refusal instead.
- **Page-raster retention.** Page rasters persist in the same content-addressed
  blob store as crops (`FR-STORE-06`'s storage form: the blob under its
  SHA-256, only the hash in the database — recorded per page in
  `document.source_blobs`' provenance), retained under the crop precedent:
  kept until the cohort's Tier C purge (`NFR-INGEST-04`, PII). The
  environment-sensitive bound is `HARNESS_INGEST_RETAIN_PAGE_RASTERS`
  (production default on; a capacity-constrained box can turn full-page
  retention off while crops keep flowing, since `FR-INGEST-13`'s retained
  crop is the requirement and the full-page raster is the provenance extra).
"""

from __future__ import annotations

import json
import struct

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    IngestError,
    Ingestor,
    PageReplacement,
    PdfiumRasterizer,
    PdfSanitizer,
    SanitizeResult,
)
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#226"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def minimal_pdf(pages: list[tuple[int, int]] | None = None) -> bytes:
    """A REAL pdfium-decodable PDF, built inline with a computed xref (no
    fixture file, no writer library: the bytes are the fixture). Each page is
    a `(width_pt, height_pt)` MediaBox with a blue rectangle; the default is
    one 612x792pt page. Varying the page sizes is what lets a case tell
    "cropped the page the region sits on" from "cropped page 1"."""
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


def png_dimensions(data: bytes) -> tuple[int, int]:
    """The (width, height) a PNG's IHDR declares — the structural assert for a
    crop's geometry, readable without an imaging library."""
    assert data[:8] == PNG_SIGNATURE, "the crop is not a PNG."
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:cccc", quantization="q4")


class ThroughSanitizer(PdfSanitizer):
    """The pass-through sanitizer double: no constructs, the bytes through.
    The sanitizer is not this suite's subject — the REAL rasterizer is — and
    the gateway refuses a gateway built without a `PdfSanitizer`, so the double
    subclasses it exactly as the fast tier always has."""

    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 deadline=None, **kwargs):
        return SanitizeResult(pdf_bytes=bytes(pdf_bytes))


class PerPageTranscriptProvider:
    """One deterministic `Completion` per call, the transcript chosen per page
    number; every call recorded."""

    def __init__(self, texts: dict[int, str], default: str) -> None:
        self.texts = texts
        self.default = default
        self.calls: list[int] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        page_no = dict(prompt.fields)["page_no"]
        self.calls.append(page_no)
        text = self.texts.get(int(page_no), self.default)
        return Completion(
            text=text, tokens_in=10, tokens_out=5, latency_ms=1,
            resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None,
        )


GRAPHIC_TRANSCRIPT = (
    "<!-- region: kind=described_graphic element_kind=graph_or_plot "
    "conf=0.9 crop=40,40,200,150 -->\n"
    "a line graph plotting attendance across the term\n"
    "<!-- /region -->\n"
)

#: A described_graphic with NO crop box: the crop is the whole page the
#: region sits on.
GRAPHIC_NO_BOX = (
    "<!-- region: kind=described_graphic element_kind=graph_or_plot "
    "conf=0.8 -->\n"
    "the whole page is one figure with its caption\n"
    "<!-- /region -->\n"
)


# -- TC-INGEST-49: the live crop contract ------------------------------------------------


def test_tc_ingest_49_live_crop_serves_the_doubles_contract():
    """`crop(pdf_bytes, page_no, box, dpi)` — the signature every test double
    implements — returns the PNG bytes of the box carved from the page raster
    at that DPI: full-page box yields the full page's dimensions, a sub-box
    yields the box's own."""
    rasterizer = PdfiumRasterizer()
    pdf = minimal_pdf()
    pages = rasterizer.rasterize(pdf, 72)
    assert [(p.width_px, p.height_px) for p in pages] == [(612, 792)]

    whole = rasterizer.crop(pdf, 1, (0, 0, 612, 792), 72)
    assert png_dimensions(whole) == (612, 792)

    part = rasterizer.crop(pdf, 1, (40, 40, 200, 150), 72)
    assert png_dimensions(part) == (200, 150)


def test_tc_ingest_49_live_crop_refuses_out_of_bounds_never_clamps():
    """A crop outside the page is REFUSED (`IngestError`), not clamped — the
    recorded interpretation (a clamped crop would resolve `crop_ref` to an
    image the description did not describe). Negative origins, degenerate
    boxes, non-4-tuples and a page past the end refuse the same way."""
    rasterizer = PdfiumRasterizer()
    pdf = minimal_pdf()
    refusals = [
        ((0, 0, 613, 792), "past the right edge"),
        ((0, 0, 612, 793), "past the bottom edge"),
        ((-1, 0, 100, 100), "negative origin"),
        ((0, -1, 100, 100), "negative origin"),
        ((0, 0, 0, 100), "degenerate width"),
        ((0, 0, 100, 0), "degenerate height"),
        ("40,40,200,150", "a string, not a box"),
        ((40, 40, 200), "three numbers, not a box"),
        ((True, False, True, True), "booleans, not integers"),
    ]
    for box, why in refusals:
        try:
            rasterizer.crop(pdf, 1, box, 72)
        except IngestError as error:
            assert "out of bounds" in str(error) or "refus" in str(error), (
                f"TC-INGEST-49: the refusal for {why} names its reason: {error}."
            )
        else:
            pytest.fail(
                f"TC-INGEST-49: box {box!r} ({why}) was served, not refused — "
                "an out-of-bounds crop must never be silently clamped."
            )
    with pytest.raises(IngestError):
        rasterizer.crop(pdf, 2, (0, 0, 10, 10), 72)  # the PDF has one page
    with pytest.raises(IngestError):
        rasterizer.crop(pdf, 0, (0, 0, 10, 10), 72)  # page numbers are 1-based


def test_tc_ingest_49_described_graphic_ingests_end_to_end_through_the_live_rasterizer(
        tmp_data_dir, monkeypatch):
    """The evaluation strategy the issue names: a described_graphic ingest
    through the REAL rasterizer — the AttributeError went red here before the
    fix — with the region's `crop_ref` AND the full-page rasters assertable in
    the blob store afterwards. Runs at 72 DPI through the declared knob."""
    monkeypatch.setenv("HARNESS_INGEST_DPI", "72")
    store = open_store(tmp_data_dir)
    blobs = store.blobs()
    ingestor = Ingestor(
        store.cohort("c-live"), blobs,
        PerPageTranscriptProvider({}, GRAPHIC_TRANSCRIPT),
        _model(), SamplingParams(temperature=0.0), PdfiumRasterizer(),
        sanitizer=ThroughSanitizer())
    pdf = minimal_pdf()
    blob_hash = blobs.put(pdf)

    document_id = ingestor.ingest_document(
        [blob_hash], kind="assessment", order_hint=[blob_hash])

    documents = store.cohort("c-live").query(
        statement("SELECT * FROM document WHERE document_id = :d"), d=document_id)
    assert documents, "the live ingest produced no document row."
    provenance = json.loads(documents[0]["source_blobs"])
    regions = store.cohort("c-live").query(
        statement("SELECT * FROM document_region WHERE document_id = :d"), d=document_id)
    graphics = [r for r in regions if r["region_kind"] == "described_graphic"]
    assert len(graphics) == 1, "the described_graphic region did not survive."
    crop_ref = graphics[0]["crop_ref"]
    assert crop_ref, "FR-INGEST-13: the described_graphic carries no crop_ref."
    crop_bytes = blobs.get(crop_ref)
    assert png_dimensions(crop_bytes) == (200, 150), (
        "TC-INGEST-49: crop_ref does not resolve to the boxed crop at the "
        "requested DPI."
    )
    # F1/G7: the full-page rasters persist alongside the crops (FR-STORE-06's
    # storage form), their content hashes recorded in the provenance.
    assert provenance["pages"], "the document recorded no page provenance."
    for entry in provenance["pages"]:
        raster_hash = entry.get("raster_hash")
        assert raster_hash, (
            "TC-INGEST-49: a page raster was not persisted — F1/G7's discard "
            "is still live."
        )
        assert png_dimensions(blobs.get(raster_hash)) == (612, 792), (
            "TC-INGEST-49: the persisted page raster is not the page's raster "
            "at the pinned DPI."
        )


def test_tc_ingest_49_retention_knob_off_skips_rasters_keeps_crops(
        tmp_data_dir, monkeypatch):
    """`HARNESS_INGEST_RETAIN_PAGE_RASTERS=0` — the env knob (seam 3), read at
    call time — bounds the new storage surface: full-page rasters are skipped
    (provenance records the skip honestly) while `FR-INGEST-13`'s retained
    crop still flows."""
    monkeypatch.setenv("HARNESS_INGEST_DPI", "72")
    monkeypatch.setenv("HARNESS_INGEST_RETAIN_PAGE_RASTERS", "0")
    store = open_store(tmp_data_dir)
    blobs = store.blobs()
    ingestor = Ingestor(
        store.cohort("c-live"), blobs,
        PerPageTranscriptProvider({}, GRAPHIC_TRANSCRIPT),
        _model(), SamplingParams(temperature=0.0), PdfiumRasterizer(),
        sanitizer=ThroughSanitizer())
    blob_hash = blobs.put(minimal_pdf())

    document_id = ingestor.ingest_document(
        [blob_hash], kind="assessment", order_hint=[blob_hash])

    documents = store.cohort("c-live").query(
        statement("SELECT * FROM document WHERE document_id = :d"), d=document_id)
    provenance = json.loads(documents[0]["source_blobs"])
    for entry in provenance["pages"]:
        assert entry.get("raster_hash") is None, (
            "TC-INGEST-49: the retention knob was off, yet a page raster was "
            "persisted."
        )
    regions = store.cohort("c-live").query(
        statement("SELECT * FROM document_region WHERE document_id = :d"), d=document_id)
    graphics = [r for r in regions if r["region_kind"] == "described_graphic"]
    assert graphics and graphics[0]["crop_ref"], (
        "TC-INGEST-49: with page-raster retention off, FR-INGEST-13's crop "
        "retention must still hold."
    )
    assert png_dimensions(blobs.get(graphics[0]["crop_ref"])) == (200, 150)


def test_tc_ingest_49_boxless_described_graphic_crops_the_page_it_sits_on(
        tmp_data_dir, monkeypatch):
    """A region with no `crop=` box crops the WHOLE page the region sits on —
    and on a multi-page source that is that page's OWN rect, not page 1's
    (review finding, #226): page 1 is letter-height, page 2 is half-height,
    and the page-2 region's crop must come out half-height. The scripted
    doubles' box-blind crop could never tell the two apart."""
    monkeypatch.setenv("HARNESS_INGEST_DPI", "72")
    store = open_store(tmp_data_dir)
    blobs = store.blobs()
    ingestor = Ingestor(
        store.cohort("c-live"), blobs,
        PerPageTranscriptProvider(
            {1: "plain text, no figure on the first page"}, GRAPHIC_NO_BOX),
        _model(), SamplingParams(temperature=0.0), PdfiumRasterizer(),
        sanitizer=ThroughSanitizer())
    pdf = minimal_pdf(pages=[(612, 792), (612, 396)])
    blob_hash = blobs.put(pdf)

    document_id = ingestor.ingest_document(
        [blob_hash], kind="assessment", order_hint=[blob_hash])

    regions = store.cohort("c-live").query(
        statement("SELECT * FROM document_region WHERE document_id = :d"),
        d=document_id)
    graphics = [r for r in regions if r["region_kind"] == "described_graphic"]
    assert len(graphics) == 1, "expected the page-2 described_graphic region."
    assert graphics[0]["page_index"] == 2, (
        "the graphic region should sit on page 2."
    )
    assert png_dimensions(blobs.get(graphics[0]["crop_ref"])) == (612, 396), (
        "TC-INGEST-49: the boxless crop is not the region's own page — the "
        "no-box default used the wrong page's rect."
    )


def test_tc_ingest_49_revision_crops_live_through_the_real_rasterizer(
        tmp_data_dir, monkeypatch):
    """The revision path's crop stage runs LIVE too: a rescan transcribed as a
    boxless described_graphic crops the whole rescan page — the page the model
    actually saw — and the revision lands its own document row. The original
    page is letter-height, the rescan half-height; the revision's crop must be
    half-height (review finding, #226: the zero-rect default is gone)."""
    monkeypatch.setenv("HARNESS_INGEST_DPI", "72")
    store = open_store(tmp_data_dir)
    blobs = store.blobs()
    ingestor = Ingestor(
        store.cohort("c-live"), blobs,
        PerPageTranscriptProvider({}, GRAPHIC_NO_BOX),
        _model(), SamplingParams(temperature=0.0), PdfiumRasterizer(),
        sanitizer=ThroughSanitizer())
    original_hash = blobs.put(minimal_pdf())
    rescan_hash = blobs.put(minimal_pdf(pages=[(612, 396)]))

    document_id = ingestor.ingest_document(
        [original_hash], kind="assessment", order_hint=[original_hash])
    new_id = ingestor.revise_document(
        document_id, [PageReplacement(blob_hash=rescan_hash, page_no=1)])

    assert new_id != document_id, "a revision returns a new document id."
    regions = store.cohort("c-live").query(
        statement("SELECT * FROM document_region WHERE document_id = :d"),
        d=new_id)
    graphics = [r for r in regions if r["region_kind"] == "described_graphic"]
    assert len(graphics) == 1, "the revision's described_graphic did not land."
    crop_ref = graphics[0]["crop_ref"]
    assert crop_ref, "FR-INGEST-13: the revision's graphic carries no crop_ref."
    assert png_dimensions(blobs.get(crop_ref)) == (612, 396), (
        "TC-INGEST-49: the revision's boxless crop is not the rescan page's "
        "rect — the crop stage did not use the page it transcribed."
    )
