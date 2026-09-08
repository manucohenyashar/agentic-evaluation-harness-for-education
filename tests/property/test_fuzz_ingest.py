"""The ingestion path under generated malformation, and assembly's invariants.

Cases `TC-INGEST-37` and the `FUZZ-01` / `FUZZ-02` rows of test plan §6.7 (TS-18,
issue #47). `FUZZ-01` draws structure-aware malformations of REAL PDFs — the
F-ADV-PDF corpus's malformed trio plus a benign baseline, truncated, byte-flipped
and xref-corrupted at drawn offsets — and asserts the plan's invariant, not a
crash count: every outcome is either a successful ingest or a quarantine, no
exception outside the declared taxonomy ever escapes, and the wall-clock ceiling
(small test value) bounds any example. `FUZZ-02` draws page sequences — variable
lengths, mixed content, mixed unicode, and a drawn presentation order — over real
one-page PDFs, and asserts the three assembly invariants: every stored region's
content addresses inside `document.markdown`, `content_state` is always one of the
three declared values, and assembly is identical when the same pages arrive in a
different order with an order source to settle it. (The duplicate and gap
dimensions of the plan's generator row are the V1 gate's named-positions territory
— `TC-INGEST-24` pins them — and "mixed orientations" has no observable at a
scripted raster; what this property owns is the three invariants above.)

The pipeline is the real one — real sanitizer, real store, real blob dir — with the
rasterizer and provider scripted, which is exactly where the plan puts the fuzz
boundary: the malformation lives in the bytes, the model and the raster are
deterministic.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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

pytestmark = pytest.mark.property

ISSUE = "#47"
COHORT = "c-fuzz"

CONTENT_STATES = ("present", "blank", "absent")

#: §6.7's *Examples per run* column for `FUZZ-01`: *"200 in CI"*. `deadline=None`
#: because the default profile carries hypothesis's 200 ms per-example deadline,
#: and one example here runs the real sanitizer over a real store — the declared
#: wall-clock ceiling inside the ingest (2 s, the small test value) is the hang
#: guard the case actually names.
FUZZ_EXAMPLES = 200


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:7777", quantization="q4")


class ScriptedRasterizer:
    def __init__(self, pages: int = 1) -> None:
        self.pages = pages
        self.seen: list[bytes] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.seen.append(bytes(pdf_bytes))
        return [PageImage(page_no=index + 1, png=f"p{index}".encode(),
                          width_px=20, height_px=20)
                for index in range(self.pages)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class KeyedProvider:
    def __init__(self, texts: dict) -> None:
        self.texts = texts
        self.calls: list[tuple[str, int]] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        key = (fields["source_blob_hash"], int(fields["page_no"]))
        self.calls.append(key)
        return Completion(text=self.texts.get(key, "plain page"),
                          tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class _Fuzz:
    """One store and ingestor per example — cheap enough for the profile. The
    root is unique per construction: hypothesis reuses the test's `tmp_path`
    across examples, and each example's cohort must be its own."""

    _made = 0

    def __init__(self, tmp_path) -> None:
        _Fuzz._made += 1
        self.root = tmp_path / f"fuzz-{_Fuzz._made}"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                       "created_at) VALUES (:c, 'synthetic', 'x')", c=COHORT)
            tx.execute("INSERT INTO roster (cohort_id, student_ref) "
                       "VALUES (:c, 'amara-o')", c=COHORT)
        self.rasterizer = ScriptedRasterizer()
        self.provider = KeyedProvider({})
        self.ingestor = Ingestor(self.handle, self.blobs, self.provider,
                                 _model(), SamplingParams(temperature=0.0),
                                 self.rasterizer,
                                 residency=ResidencySlot.for_policy(
                                     ("transcriber",)),
                                 sanitizer=PypdfSanitizer())

    def close(self) -> None:
        self.store.close()


_BASES: dict[str, bytes] = {}


def _base_pdf(name: str) -> bytes:
    """The malformation bases, built once per session: the corpus's truncated and
    zero-page constructs plus a minimal benign document."""
    if not _BASES:
        import tempfile
        from pathlib import Path

        paths = materialize_adv_pdfs(
            Path(tempfile.mkdtemp(prefix="fuzz-bases-")),
            ids=["ADV-PDF-13", "ADV-PDF-14"])
        _BASES["zero-page"] = paths["ADV-PDF-13"].read_bytes()
        _BASES["truncated"] = paths["ADV-PDF-14"].read_bytes()
        _BASES["benign"] = _BENIGN
    return _BASES[name]


_BENIGN = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R >> endobj\n"
    b"4 0 obj << /Length 0 >>\nstream\n\nendstream\nendobj\n"
    b"xref\n0 5\n0000000000 65535 f \n"
    b"trailer << /Size 5 /Root 1 0 R >>\n"
    b"startxref\n0\n%%EOF")

BASE_NAMES = ("benign", "zero-page", "truncated")


# -- TC-INGEST-37 / FUZZ-01: the malformation invariant --------------------------------------------


@st.composite
def _malformed(draw) -> bytes:
    base = _base_pdf(draw(st.sampled_from(BASE_NAMES)))
    kind = draw(st.sampled_from(["truncate", "flip", "corrupt-xref",
                                 "junk-prefix", "duplicate-trailer"]))
    if kind == "truncate":
        cut = draw(st.integers(min_value=0, max_value=max(len(base) - 1, 0)))
        return base[:cut]
    if kind == "flip":
        position = draw(st.integers(min_value=0, max_value=len(base) - 1))
        mutated = bytearray(base)
        mutated[position] ^= 1 << draw(st.integers(min_value=0, max_value=7))
        return bytes(mutated)
    if kind == "corrupt-xref":
        mutated = bytearray(base)
        start = mutated.find(b"startxref")
        if start <= 0:
            return base[: draw(st.integers(min_value=1, max_value=len(base)))]
        position = draw(st.integers(min_value=start,
                                    max_value=len(mutated) - 1))
        mutated[position] = draw(st.sampled_from(b"0123456789ABCDEF"))
        return bytes(mutated)
    if kind == "junk-prefix":
        junk = bytes(draw(st.binary(min_size=0, max_size=64)))
        return junk + base
    payload = base + base[-64:]
    return payload


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(data=_malformed())
def test_fuzz_01_every_malformation_resolves_to_ingest_or_quarantine(
        tmp_path, data, monkeypatch):
    """`TC-INGEST-37` / `FUZZ-01` — over generated malformations of real PDFs: no
    exception outside the declared taxonomy ever escapes `ingest_submission`; the
    outcome is a successful ingest or a quarantine (never partial content); no
    example hangs past the wall-clock ceiling (2 s, the small test value)."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_FILE_SECONDS", "2")
    fx = _Fuzz(tmp_path)
    try:
        source = fx.blobs.put(data)
        # No try: an exception here IS the finding — anything outside the
        # declared taxonomy escaping the ladder fails this property. The ladder
        # itself resolves every refusal to a quarantine report.
        report = fx.ingestor.ingest_submission(
            [source], cohort_id=COHORT, package_version="v0",
            filenames={source: "fuzz.pdf"})
        assert report.ingest_status in (
            "ok", "low_confidence_ocr", "unreadable", "incomplete",
            "unmatched_assessment"), (
            f"FUZZ-01: ingest_status {report.ingest_status!r} is outside the "
            "declared vocabulary.")
        # CT-INGEST-11's rule, as the property's own arithmetic: admissible iff
        # `quarantined = 0` — the two admitted statuses (`ok` and, #221, the
        # confidence floor's `low_confidence_ocr`) are exactly the unquarantined
        # ones; the three quarantine statuses never present partial content as
        # processed.
        admissible = report.ingest_status in ("ok", "low_confidence_ocr")
        row = fx.handle.query(
            "SELECT quarantined FROM submission")[0]
        assert (row["quarantined"] == 0) == admissible, (
            f"FUZZ-01: status {report.ingest_status!r} with quarantined="
            f"{row['quarantined']} breaks CT-INGEST-11's biconditional — "
            "admissibility and the quarantine flag disagree.")
    finally:
        fx.close()


# -- FUZZ-02: assembly's invariants over generated page sequences ----------------------------------


def _one_page_pdf(token: bytes) -> bytes:
    """A one-page, well-formed PDF with `token` as its visible text — the real
    blob the sanitizer must pass for the assembly invariants to run at all."""
    content = f"BT 12 Tf 72 720 Td ({token.decode('ascii')}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
        (f"<< /Length {len(content)} >>\nstream\n".encode() + content +
         b"\nendstream"),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF").encode()
    return bytes(out)


@st.composite
def _page_sequence(draw) -> tuple[list[str], list[int]]:
    """Page transcripts carrying ONE order source per sequence (printed page
    numbers, or fiducial markers — a sequence that mixes the two has no uniform
    source and falls through to the filename tier) plus a DRAWN presentation
    order."""
    count = draw(st.integers(min_value=1, max_value=5))
    words = st.sampled_from(["alpha", "beta", "gamma", "delta", "Water",
                             "cycle", "forces", "balance", "κύκλος", " forces"])
    numbered = draw(st.booleans())
    pages = []
    for number in range(1, count + 1):
        words_on_page = " ".join(draw(st.lists(words, min_size=2, max_size=6)))
        pages.append(
            f"Page {number} of {count}. {words_on_page}" if numbered
            else f"[fiducial:page-{number}] {words_on_page}")
    order = list(draw(st.permutations(list(range(count)))))
    return pages, order


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(sequence=_page_sequence())
def test_fuzz_02_regions_address_inside_the_markdown_and_reordering_is_stable(
        tmp_path, sequence, monkeypatch):
    """`FUZZ-02` — over generated page sequences on real one-page PDFs: every
    stored region's content addresses inside `document.markdown`; `content_state`
    is always one of the three declared values; region positions are the dense
    sequence; and the same pages presented in a different order assemble to an
    identical artifact when an order source (the printed page numbers or the
    fiducial markers) settles the sequence."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_FILE_SECONDS", "2")
    pages, order = sequence
    fx = _Fuzz(tmp_path)
    try:
        blobs = [fx.blobs.put(_one_page_pdf(f"sheet-{index}".encode()))
                 for index in range(len(pages))]
        for index, text in enumerate(pages):
            fx.provider.texts[(blobs[index], 1)] = text

        presented = [blobs[i] for i in order]
        report = fx.ingestor.ingest_submission(
            presented, cohort_id=COHORT, package_version="v0",
            filenames={blob: f"scan-{position:02d}.md"
                      for position, blob in enumerate(presented)})
        assert report.document_id, (
            "FUZZ-02: the drawn sequence's real PDFs must ingest — the assembly "
            "invariants below are about the stored artifact, and a quarantine "
            "here would make them vacuous.")

        rows = fx.handle.query(
            "SELECT position, content_state, content FROM document_region "
            "WHERE document_id = :d ORDER BY position",
            d=report.document_id)
        markdown = fx.handle.query(
            "SELECT markdown FROM document WHERE document_id = :d",
            d=report.document_id)[0]["markdown"]
        positions = [row["position"] for row in rows]
        assert positions == list(range(len(rows))), (
            "FUZZ-02: region positions are not the dense 0-based sequence.")
        for row in rows:
            assert row["content_state"] in CONTENT_STATES, (
                f"FUZZ-02: content_state {row['content_state']!r} is outside "
                "the declared vocabulary.")
            if row["content"]:
                assert row["content"] in markdown, (
                    "FUZZ-02: a region's content does not address inside "
                    "document.markdown — the span coordinate system would "
                    "point outside the artifact.")

        # The same pages, a different presentation order: an identical
        # artifact, because the order source settles the sequence.
        fx2 = _Fuzz(tmp_path)
        try:
            other_blobs = [fx2.blobs.put(_one_page_pdf(f"sheet-{index}".encode()))
                           for index in range(len(pages))]
            for index, text in enumerate(pages):
                fx2.provider.texts[(other_blobs[index], 1)] = text
            mirrored = list(reversed(other_blobs))
            report2 = fx2.ingestor.ingest_submission(
                mirrored, cohort_id=COHORT, package_version="v0",
                filenames={blob: f"scan-{position:02d}.md"
                           for position, blob in enumerate(mirrored)})
            assert report2.document_id, (
                "FUZZ-02: the mirrored presentation must ingest as its twin did.")
            markdown2 = fx2.handle.query(
                "SELECT markdown FROM document WHERE document_id = :d",
                d=report2.document_id)[0]["markdown"]
            assert markdown2 == markdown, (
                "FUZZ-02: the same pages in a different presentation "
                "order assembled to a different artifact — the order "
                "source did not settle the sequence.")
        finally:
            fx2.close()
    finally:
        fx.close()
