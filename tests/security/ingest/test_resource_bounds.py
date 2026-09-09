"""Resource ceilings quarantine before allocation (`M-INGEST` security).

Case `TC-INGEST-34` and the `SEC-06` row of test plan §6.5 (TS-18, issue #47),
against the ceilings #42 landed. Rung 2 — the real `PypdfSanitizer`, real blob
store, scripted rasterizer/provider; every ceiling carries its test value through
the declared `HARNESS_INGEST_*` knob, and the boundary cells are the plan's:
ceiling-minus-one and at-ceiling accepted, ceiling-plus-one quarantined.

The memory watermark is the oracle that separates 'we checked the size after
decompressing' from 'we refused before allocating': the decompression bomb expands
to 64 MiB, the byte ceiling is set to 1 MiB, and Python-level peak allocation
during the ingest — `tracemalloc`, the watermark the plan names — must stay a
stated few multiples of the CEILING, not of the expansion. An implementation that
absorbed the bomb first would peak at sixty-four times the bound this asserts.
"""

from __future__ import annotations

import tracemalloc
import zlib

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    Ingestor,
    PageImage,
    PypdfSanitizer,
    ResidencySlot,
)
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store
from tests.support.corpora import materialize_adv_pdfs

pytestmark = pytest.mark.integration

ISSUE = "#47"
COHORT = "c-bounds"

BOMB_DECOMPRESSED = 67108864  # ADV-PDF-09's declared expansion, from the manifest


@pytest.fixture(autouse=True)
def _below_floor_rasters_are_legal(monkeypatch):
    """These cells isolate the DECLARED-dimension ceilings, so the scripted 20x20
    post-raster pages stay deliberately tiny — below the resolution floor's
    default. The floor knob (#227) is pinned low for this module, which is what
    the seam-3 knob exists for: the subject here is the ceiling, not the floor."""
    monkeypatch.setenv("HARNESS_INGEST_RESOLUTION_FLOOR", "10")


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:eeee", quantization="q4")


class ScriptedRasterizer:
    def __init__(self) -> None:
        self.seen: list[bytes] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.seen.append(bytes(pdf_bytes))
        # 20x20 px: small enough that the post-raster belt-and-braces never fires
        # for these tests' knob values — the DECLARED-dimension ceiling is what
        # the pixel cells isolate.
        return [PageImage(page_no=1, png=b"page", width_px=20, height_px=20)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt, model_ref, params) -> Completion:
        self.calls += 1
        return Completion(text="plain page", tokens_in=1, tokens_out=1,
                          latency_ms=1, resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


# -- the crafted-PDF builders ----------------------------------------------------------------------


def _assemble(objects: list[bytes]) -> bytes:
    """Lay out `objects` (1-based) as a classic PDF with a correct xref table."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF").encode()
    return bytes(out)


def _pdf_with_pages(pages: int) -> bytes:
    kids = " ".join(f"{3 + index} 0 R" for index in range(pages))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
    ]
    objects += [b"<< /Type /Page /Parent 2 0 R >>" for _ in range(pages)]
    return _assemble(objects)


def _pdf_with_flate_stream(decompressed: int) -> bytes:
    """One page whose content stream is a Flate stream expanding to exactly
    `decompressed` bytes — the byte ceiling's boundary fixture."""
    payload = zlib.compress(b"A" * decompressed)
    body = (f"<< /Length {len(payload)} /Filter /FlateDecode >>\nstream\n"
            .encode() + payload + b"\nendstream")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
        body,
    ]
    return _assemble(objects)


def _pdf_with_declared_image(width: int, height: int) -> bytes:
    """One page carrying an image XObject that DECLARES `width`x`height` pixels
    over a few bytes of data — the allocation the pixel ceiling must refuse."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im0 4 0 R >>"
        b" >> /Contents 5 0 R >>",
        (f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
         f"/BitsPerComponent 8 /ColorSpace /DeviceGray /Length 4 >>\nstream\n"
         ).encode() + b"\x00\x00\x00\x00" + b"\nendstream",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    return _assemble(objects)


def _pdf_with_objects(count: int) -> bytes:
    """A catalog, a page tree, and `count - 3` filler objects REFERENCED from the
    page — the strip walk counts what it reaches from the root, so the fillers
    must be reachable for the embedded-object ceiling's count to include them."""
    fillers = list(range(4, count + 1))
    annots = " ".join(f"{index} 0 R" for index in fillers)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /Annots [{annots}] >>".encode(),
    ]
    objects += [f"<< /Filler {index} >>".encode() for index in fillers]
    return _assemble(objects)


class _Bounds:
    """One fresh store with the real sanitizer; a fixture or crafted source put
    into the blob dir."""

    def __init__(self, tmp_data_dir, name: str) -> None:
        self.root = tmp_data_dir / f"v47b-{name}"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                       "created_at) VALUES (:c, 'synthetic', 'x')", c=COHORT)
        self.rasterizer = ScriptedRasterizer()
        self.provider = CountingProvider()
        self.ingestor = Ingestor(self.handle, self.blobs, self.provider,
                                 _model(), SamplingParams(temperature=0.0),
                                 self.rasterizer,
                                 residency=ResidencySlot.for_policy(
                                     ("transcriber",)),
                                 sanitizer=PypdfSanitizer())

    def put_fixture(self, fixture_id: str) -> str:
        paths = materialize_adv_pdfs(self.root / "adv-pdf", ids=[fixture_id])
        return self.blobs.put(paths[fixture_id].read_bytes())

    def close(self) -> None:
        self.store.close()


def _quarantined(fx: _Bounds, source: str) -> None:
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "bounded.pdf"})
    assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail", (
        f"ISSUE {ISSUE}: an over-ceiling artifact must quarantine as `unreadable`, "
        f"got {report.ingest_status!r}.")
    return report


# -- the page ceiling ------------------------------------------------------------------------------


@pytest.mark.parametrize(("pages", "ceiling", "accepted"),
                         [(4, 5, True), (5, 5, True), (6, 5, False),
                          (200, 200, True), (201, 200, False)],
                         ids=["under", "at", "over", "default-at", "default-over"])
def test_tc_ingest_34_the_page_ceiling_boundary(tmp_data_dir, pages, ceiling,
                                                accepted, monkeypatch):
    """`TC-INGEST-34` — the page ceiling at its boundary: ceiling-minus-one and the
    exact ceiling accepted, ceiling-plus-one quarantined. The last two cells pin
    the DECLARED default (200) on a real 200/201-page document."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_PAGES_PER_DOC", str(ceiling))
    fx = _Bounds(tmp_data_dir, f"pages-{pages}x{ceiling}")
    source = fx.blobs.put(_pdf_with_pages(pages))
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "pages.pdf"})
    if accepted:
        assert report.gates["v0"] == "pass", (
            f"TC-INGEST-34: {pages} pages under a ceiling of {ceiling} must be "
            "accepted — at-ceiling is not over-ceiling.")
    else:
        _quarantined(fx, source)
        assert fx.provider.calls == 0, (
            "TC-INGEST-34: the over-ceiling artifact was rasterized or read by "
            "the model — the ceiling must refuse before allocation.")
    fx.close()


# -- the decompressed-byte ceiling, and the bomb's memory watermark --------------------------------


@pytest.mark.parametrize(("decompressed", "ceiling", "accepted"),
                         [(4096, 4097, True), (4096, 4096, True),
                          (4096, 4095, False)],
                         ids=["under", "at", "over"])
def test_tc_ingest_34_the_decompressed_byte_ceiling_boundary(
        tmp_data_dir, decompressed, ceiling, accepted, monkeypatch):
    """`TC-INGEST-34` — the byte ceiling measured on a real Flate stream: a stream
    that expands to exactly the ceiling is accepted; one byte over is refused. The
    chunked measurement that stops absorbing at the ceiling is what keeps this
    from being a memory test in disguise."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_DECOMPRESSED_BYTES", str(ceiling))
    fx = _Bounds(tmp_data_dir, f"flate-{decompressed}x{ceiling}")
    source = fx.blobs.put(_pdf_with_flate_stream(decompressed))
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "flate.pdf"})
    if accepted:
        assert report.gates["v0"] == "pass", (
            f"TC-INGEST-34: a {decompressed}-byte expansion under a ceiling of "
            f"{ceiling} must be accepted.")
    else:
        _quarantined(fx, source)
    fx.close()


def test_tc_ingest_34_the_bomb_quarantines_before_full_decompression(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-34` — the corpus's decompression bomb (65 KB expanding to
    64 MiB) under a 1 MiB ceiling: quarantined, **zero** model calls, and the
    memory watermark stays a few multiples of the CEILING — the oracle that
    separates 'refused before allocating' from 'measured after decompressing'.
    The sanitizer's lazy pypdf import is warmed BEFORE the watermark opens, so
    the measured window contains only the ingest's own allocations."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_DECOMPRESSED_BYTES", str(1024 * 1024))
    fx = _Bounds(tmp_data_dir, "bomb")
    source = fx.put_fixture("ADV-PDF-09")
    PypdfSanitizer().sanitize(_pdf_with_pages(1), strip=True,
                              max_decompressed_bytes=None,
                              max_embedded_objects=None, deadline=None)

    tracemalloc.start()
    try:
        report = fx.ingestor.ingest_submission(
            [source], cohort_id=COHORT, package_version="v0",
            filenames={source: "bomb.pdf"})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail"
    assert fx.provider.calls == 0, (
        "TC-INGEST-34: the bomb reached the model.")
    assert peak < 8 * 1024 * 1024, (
        f"TC-INGEST-34: peak allocation during the bomb ingest was {peak} bytes — "
        "the ceiling is 1 MiB and the expansion is 64 MiB. A peak anywhere near "
        "the expansion means the file was decompressed before it was refused "
        "(NFR-INGEST-08's bounded-memory form).")
    fx.close()


def test_tc_ingest_34_the_bomb_at_its_exact_expansion_is_accepted(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-34` — the at-ceiling form on the real fixture: the bomb expands
    to exactly 64 MiB (the manifest's declared figure), so a ceiling of exactly
    that accepts it — the boundary's other side, on the real artifact."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_DECOMPRESSED_BYTES",
                       str(BOMB_DECOMPRESSED))
    fx = _Bounds(tmp_data_dir, "bomb-at")
    source = fx.put_fixture("ADV-PDF-09")
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "bomb.pdf"})
    assert report.gates["v0"] == "pass", (
        "TC-INGEST-34: a 64 MiB expansion at an exact 64 MiB ceiling is the "
        "at-ceiling cell — accepted, not refused.")
    fx.close()


# -- the pixel ceiling -----------------------------------------------------------------------------


@pytest.mark.parametrize(("pixels", "ceiling", "accepted"),
                         [(3600, 3600, True), (3600, 3599, False),
                          (3600000000, None, False)],
                         ids=["at", "over", "corpus-giant-vs-default"])
def test_tc_ingest_34_the_pixel_ceiling_boundary(tmp_data_dir, pixels, ceiling,
                                                 accepted, monkeypatch):
    """`TC-INGEST-34` — the pixel ceiling on the DECLARED dimensions (the fixture
    carries a 60×60 image over a few bytes): at-ceiling accepted, over-ceiling
    refused, and the corpus's giant image (60000×60000, about 10 TB of
    allocation-by-declaration) refused by the declared default of 64 M."""
    if ceiling is not None:
        monkeypatch.setenv("HARNESS_INGEST_MAX_IMAGE_PIXELS", str(ceiling))
    fx = _Bounds(tmp_data_dir, f"pixels-{pixels}x{ceiling}")
    width = height = 60
    assert width * height == pixels or pixels == 3600000000
    if pixels == 3600000000:
        source = fx.put_fixture("ADV-PDF-11")
        filename = "giant.pdf"
    else:
        source = fx.blobs.put(_pdf_with_declared_image(width, height))
        filename = "pixels.pdf"
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: filename})
    if accepted:
        assert report.gates["v0"] == "pass"
    else:
        _quarantined(fx, source)
        assert fx.provider.calls == 0
    fx.close()


# -- the embedded-object ceiling -------------------------------------------------------------------


@pytest.mark.parametrize(("objects", "ceiling", "accepted"),
                         [(12, 13, True), (12, 12, True), (12, 11, False)],
                         ids=["under", "at", "over"])
def test_tc_ingest_34_the_embedded_object_ceiling_boundary(
        tmp_data_dir, objects, ceiling, accepted, monkeypatch):
    """`TC-INGEST-34` — the embedded-object ceiling over the walk's seen set: a
    well-formed document of `objects` top-level objects against a knob of
    ceiling-minus-one, exactly the count, and one under."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_EMBEDDED_OBJECTS", str(ceiling))
    fx = _Bounds(tmp_data_dir, f"objects-{objects}x{ceiling}")
    source = fx.blobs.put(_pdf_with_objects(objects))
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "objects.pdf"})
    if accepted:
        assert report.gates["v0"] == "pass", (
            f"TC-INGEST-34: {objects} objects under a ceiling of {ceiling} must "
            "be accepted.")
    else:
        _quarantined(fx, source)
    fx.close()


# -- the wall-clock ceiling ------------------------------------------------------------------------


class _AdvancingClock:
    """A fake `time` whose `monotonic` advances past any deadline on its Nth
    reading — the injected clock §4.6 asks for instead of a sleep."""

    def __init__(self, jump_on: int, jump_by: float = 3600.0) -> None:
        self._readings = 0
        self._jump_on = jump_on
        self._jump_by = jump_by
        self._now = 1000.0

    def monotonic(self) -> float:
        self._readings += 1
        if self._readings >= self._jump_on:
            self._now += self._jump_by
        return self._now


def test_tc_ingest_34_the_wall_clock_ceiling_cuts_the_ingest(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-34` — the wall-clock ceiling: with the injected clock jumping
    past the deadline at the sanitizer's next boundary read, the artifact is cut
    with a quarantine whose finding NAMES the wall clock — the observable must
    depend on the ceiling, not on some other bound that would refuse the fixture
    anyway. The clock is the seam; no test sleeps."""
    import aeh.ingest as ingest_module

    monkeypatch.setenv("HARNESS_INGEST_MAX_FILE_SECONDS", "5")
    fx = _Bounds(tmp_data_dir, "clock")
    source = fx.blobs.put(_pdf_with_pages(1))  # nothing else refuses this
    monkeypatch.setattr(ingest_module, "time", _AdvancingClock(jump_on=2))
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "slow.pdf"})
    assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail", (
        f"TC-INGEST-34: the wall-clock cut must quarantine, got "
        f"{report.ingest_status!r}.")
    joined = "\n".join(str(f["finding"]) for f in report.detail["findings"])
    assert "wall_clock" in joined, (
        f"TC-INGEST-34: the cut must be the clock's own finding, got: "
        f"{joined[:200]!r} — a fixture another ceiling refuses does not exercise "
        "the wall clock.")
    assert fx.provider.calls == 0, (
        "TC-INGEST-34: the cut artifact reached the model.")
    fx.close()


def test_tc_ingest_34_the_page_count_bomb_is_refused_at_the_declared_default(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-34` / `SEC-06` — the corpus's wholly well-formed 100k-page
    document against the DECLARED page ceiling of 200, read from its default (the
    pages knob is unset; the embedded-object ceiling is raised out of the way so
    the page bound is provably what fires): refused before anything is allocated
    for it, with zero model calls, and the finding names the page ceiling."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_EMBEDDED_OBJECTS", "200000")
    fx = _Bounds(tmp_data_dir, "page-bomb")
    source = fx.put_fixture("ADV-PDF-10")
    report = _quarantined(fx, source)
    joined = "\n".join(str(f["finding"]) for f in report.detail["findings"])
    assert "pages" in joined, (
        f"TC-INGEST-34: the refusal must name the page ceiling, got: "
        f"{joined[:200]!r}.")
    assert fx.provider.calls == 0, (
        "TC-INGEST-34: the 100k-page bomb reached the model.")
    fx.close()


# -- TC-INGEST-34's variants ------------------------------------------------------------------------


def test_tc_ingest_34_a_lying_page_count_cannot_dodge_the_ceiling(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-34`'s declared-count variant — a file whose /Count disagrees
    with its actual page tree, in the dangerous direction: declare ONE page,
    carry five. The ceiling reads the actual tree (three-page knob), so the lie
    is refused before anything is rasterized — and the mirror cell shows the
    upward lie (declare 200000, carry two) does not trip the ceiling either: the
    enforced count is the actual one, never the declaration."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_PAGES_PER_DOC", "3")
    fx = _Bounds(tmp_data_dir, "lie-down")
    kids = " ".join(f"{3 + index} 0 R" for index in range(5))
    liar = _assemble(
        [b"<< /Type /Catalog /Pages 2 0 R >>",
         f"<< /Type /Pages /Kids [{kids}] /Count 1 >>".encode()]
        + [b"<< /Type /Page /Parent 2 0 R >>" for _ in range(5)])
    source = fx.blobs.put(liar)
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "liar.pdf"})
    assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail", (
        "TC-INGEST-34: a downward page-count lie must not dodge the ceiling — "
        f"got {report.ingest_status!r}.")
    assert fx.rasterizer.seen == [] and fx.provider.calls == 0, (
        "TC-INGEST-34: the lying document was rasterized before refusal.")
    fx.close()

    fx2 = _Bounds(tmp_data_dir / "up", "lie-up")
    source2 = fx2.blobs.put(_pdf_with_pages(2).replace(b"/Count 2", b"/Count 200000"))
    report2 = fx2.ingestor.ingest_submission(
        [source2], cohort_id=COHORT, package_version="v0",
        filenames={source2: "liar-up.pdf"})
    assert report2.gates["v0"] == "pass", (
        "TC-INGEST-34: an upward page-count lie must not trip the ceiling — the "
        "enforced count is the actual page tree.")
    fx2.close()


def test_tc_ingest_34_a_nested_bomb_is_bounded_by_the_outer_ceiling(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-34`'s nested-compression variant — a Flate stream whose
    decompressed bytes carry another Flate stream that would expand to 64 MiB IF
    anything recursively decompressed it. The shipped design does not: the outer
    payload (~60 KB decompressed) sits under the 4 MiB ceiling, the ingest
    succeeds, and the memory watermark stays bounded — while a design that grew
    recursive decompression would absorb the inner 64 MiB and blow the same
    watermark this cell holds. That is the regression this variant exists to
    surface, and the sizes are chosen so it would."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_DECOMPRESSED_BYTES",
                       str(4 * 1024 * 1024))
    fx = _Bounds(tmp_data_dir, "nested")
    inner = zlib.compress(b"B" * BOMB_DECOMPRESSED)  # 64 MiB, ~60 KB compressed
    outer_payload = b"inner stream follows\n" + inner
    outer = zlib.compress(outer_payload)
    body = (f"<< /Length {len(outer)} /Filter /FlateDecode >>\nstream\n"
            .encode() + outer + b"\nendstream")
    source = fx.blobs.put(_assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
        body,
    ]))
    tracemalloc.start()
    try:
        report = fx.ingestor.ingest_submission(
            [source], cohort_id=COHORT, package_version="v0",
            filenames={source: "nested.pdf"})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert report.gates["v0"] == "pass", (
        f"TC-INGEST-34: the nested document's outer payload sits under the "
        f"ceiling and must ingest — got {report.ingest_status!r}.")
    assert peak < 16 * 1024 * 1024, (
        f"TC-INGEST-34: the nested stream's peak allocation was {peak} — the "
        "outer ceiling must bound the work, and the inner 64 MiB must never be "
        "decompressed (a recursive design blows this watermark).")
    fx.close()
