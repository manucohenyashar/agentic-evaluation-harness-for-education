"""The untrusted-content marker discriminates: submissions are fenced, setup is not.

Cases `TC-INGEST-35` and `-36` of test plan §5.5 (TS-18, issue #47), against the
demarcation pass #42 landed (`FR-INGEST-35`). Rung 2 — the real `PypdfSanitizer`,
real store and blob dir; the transcript is scripted, so the test knows exactly
which tokens are submission-origin and can assert where each of them landed in the
stored artifact.

The oracle is the plan's artifact form: not "a marker exists" but "the marker
covers the FULL byte range of submission-origin content" — every transcript token
must appear inside a region block whose opening marker carries
`is_untrusted_content=1`, and on no unmarked line — while a `reference` and a
`rubric` carry no untrusted marking at all, because the delimited block must be
allowed to contain the answer key (`TC-INGEST-36`: the marker discriminates rather
than blanket-applying).
"""

from __future__ import annotations

import re

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

pytestmark = pytest.mark.integration

ISSUE = "#47"
COHORT = "c-demarc"


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:ffff", quantization="q4")


def _minimal_pdf(token: bytes) -> bytes:
    """A one-page, well-formed PDF whose visible text is `token` — enough for the
    real sanitizer to pass through and the scripted rasterizer to render."""
    page = (b"<< /Type /Page /Parent 2 0 R /Contents 3 0 R /Resources"
            b" << /Font << /F0 4 0 R >> >> >>")
    content = (f"BT /F0 12 Tf 72 720 Td ({token.decode('ascii')}) Tj ET"
               .encode())
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        page,
        (f"<< /Length {len(content)} >>\nstream\n".encode() + content +
         b"\nendstream"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
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


class ScriptedRasterizer:
    def __init__(self) -> None:
        self.seen: list[bytes] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.seen.append(bytes(pdf_bytes))
        return [PageImage(page_no=1, png=b"page-one", width_px=100,
                          height_px=140)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class ScriptedProvider:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.calls = 0

    def complete(self, prompt, model_ref, params) -> Completion:
        self.calls += 1
        return Completion(text=self.transcript, tokens_in=1, tokens_out=1,
                          latency_ms=1, resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class _Demarc:
    def __init__(self, tmp_data_dir, name: str, transcript: str) -> None:
        self.root = tmp_data_dir / f"v47d-{name}"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                       "created_at) VALUES (:c, 'synthetic', 'x')", c=COHORT)
            tx.execute("INSERT INTO roster (cohort_id, student_ref) "
                       "VALUES (:c, 'amara-o')", c=COHORT)
        self.rasterizer = ScriptedRasterizer()
        self.provider = ScriptedProvider(transcript)
        self.ingestor = Ingestor(self.handle, self.blobs, self.provider,
                                 _model(), SamplingParams(temperature=0.0),
                                 self.rasterizer,
                                 residency=ResidencySlot.for_policy(
                                     ("transcriber",)),
                                 sanitizer=PypdfSanitizer())

    def put_source(self, token: bytes) -> str:
        return self.blobs.put(_minimal_pdf(token))

    def close(self) -> None:
        self.store.close()


TRANSCRIPT = (
    "preamblesecret page furniture\n"
    "Student: amara-o\n"
    "<!-- region: kind=transcribed_text question_id=Q1 state=present -->\n"
    "the water cycle answer tokenalphasub\n<!-- /region -->\n"
    "<!-- region: kind=transcribed_text question_id=Q2 state=blank -->\n"
    "<!-- /region -->\n"
    "<!-- region: kind=selection_mark question_id=Q3 selection_state=resolved "
    "selection=B -->\nthe mark as seen\n<!-- /region -->")
#: One distinctive token per region's body PLUS one for the outside-protocol
#: preamble — where each lands in the stored artifact is what the byte-range
#: oracle reads, and the preamble token is what catches a demarcation that wraps
#: the regions but leaves the header text bare (the FULL byte range, FR-INGEST-35).
SUBMISSION_TOKENS = ("tokenalphasub", "the mark as seen", "preamblesecret")


def _unmarked_lines(markdown: str) -> list[str]:
    """The markdown's lines that sit OUTSIDE any region block."""
    lines: list[str] = []
    inside = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("<!-- region:"):
            inside = True
            continue
        if stripped.startswith("<!-- /region -->"):
            inside = False
            continue
        if not inside:
            lines.append(line)
    return lines


def _marked_regions(markdown: str) -> list[tuple[str, list[str]]]:
    """(opening marker, body lines) for each region block, in order."""
    regions: list[tuple[str, list[str]]] = []
    open_marker: str | None = None
    body: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("<!-- region:"):
            open_marker, body = stripped, []
        elif stripped.startswith("<!-- /region -->"):
            if open_marker is not None:
                regions.append((open_marker, body))
            open_marker, body = None, []
        elif open_marker is not None:
            body.append(line)
    return regions


# -- TC-INGEST-35: the marker covers the full byte range of submission content -----


def test_tc_ingest_35_the_untrusted_marker_covers_the_full_byte_range(
        tmp_data_dir):
    """`TC-INGEST-35` — an ingested submission: every region row carries
    `is_untrusted_content=1`, and the byte-range oracle — each submission-origin
    token appears inside a block whose opening marker carries the untrusted flag,
    and on NO unmarked line. There is no form in the stored artifact a downstream
    template could mistake for harness instructions."""
    fx = _Demarc(tmp_data_dir, "submission", TRANSCRIPT)
    source = fx.put_source(b"answer sheet scan")
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "scan-01.md"})
    assert report.ingest_status == "ok", (
        "TC-INGEST-35: the benign submission must ingest cleanly for the "
        f"demarcation assertion to be about marking, not about failure "
        f"(got {report.ingest_status!r}).")

    rows = fx.handle.query(
        "SELECT region_kind, is_untrusted_content FROM document_region "
        "WHERE document_id = :d", d=report.document_id)
    assert rows, "TC-INGEST-35: the transcript's regions were not stored."
    assert all(row["is_untrusted_content"] == 1 for row in rows), (
        "TC-INGEST-35: a submission-origin region is not marked untrusted — got "
        f"{[(r['region_kind'], r['is_untrusted_content']) for r in rows]!r} "
        "(FR-INGEST-35).")

    markdown = fx.handle.query("SELECT markdown FROM document "
                               "WHERE document_id = :d",
                               d=report.document_id)[0]["markdown"]
    regions = _marked_regions(markdown)
    marked_bodies = "\n".join("\n".join(body) for _, body in regions)
    for token in SUBMISSION_TOKENS:
        assert token in marked_bodies, (
            f"TC-INGEST-35: the submission-origin token {token!r} does not "
            "appear inside any region block — the marker does not cover it.")
    unmarked = "\n".join(_unmarked_lines(markdown))
    for token in SUBMISSION_TOKENS:
        assert token not in unmarked, (
            f"TC-INGEST-35: the submission-origin token {token!r} appears on an "
            "UNMARKED line of the stored artifact — a downstream template could "
            "not distinguish it from harness instructions (FR-INGEST-35).")
    for marker, _ in regions:
        assert "is_untrusted_content=1" in marker, (
            f"TC-INGEST-35: a region block's opening marker lacks the untrusted "
            f"flag: {marker!r}.")
    fx.close()


# -- TC-INGEST-36: the marker discriminates — setup artifacts are not marked -------


@pytest.mark.parametrize("kind", ["reference", "rubric"])
def test_tc_ingest_36_setup_artifacts_are_not_marked_untrusted(
        tmp_data_dir, kind):
    """`TC-INGEST-36` — a `reference` and a `rubric` artifact: no region carries
    the untrusted mark and no block in the stored artifact is flagged — the
    marker discriminates rather than blanket-applying, otherwise the delimited
    block could not contain the answer key."""
    setup_transcript = (
        "Assessment: Physics Midterm\n"
        "<!-- region: kind=transcribed_text question_id=Q1 -->\n"
        "the answer key text tokenkeyref\n<!-- /region -->")
    fx = _Demarc(tmp_data_dir, f"setup-{kind}", setup_transcript)
    source = fx.put_source(b"answer key scan")
    document_id = fx.ingestor.ingest_document(
        [source], kind=kind, filenames={source: f"{kind}.pdf"})

    rows = fx.handle.query(
        "SELECT is_untrusted_content FROM document_region "
        "WHERE document_id = :d", d=document_id)
    assert rows, "TC-INGEST-36: the setup artifact's regions were not stored."
    assert all(row["is_untrusted_content"] == 0 for row in rows), (
        f"TC-INGEST-36 ({kind}): a setup artifact's region is marked untrusted — "
        "the marker must discriminate, not blanket-apply (FR-INGEST-35).")

    markdown = fx.handle.query("SELECT markdown FROM document "
                               "WHERE document_id = :d", d=document_id)[0]["markdown"]
    assert "is_untrusted_content=1" not in markdown, (
        f"TC-INGEST-36 ({kind}): the stored artifact carries an untrusted block — "
        "the answer key could not live inside one (FR-INGEST-35).")
    assert "tokenkeyref" in markdown, (
        f"TC-INGEST-36 ({kind}): the setup artifact's content did not survive "
        "into the stored artifact.")
    for marker, body in _marked_regions(markdown):
        if "tokenkeyref" in "\n".join(body):
            assert "is_untrusted_content=1" not in marker, (
                f"TC-INGEST-36 ({kind}): the answer key's block is flagged — "
                "the marker must discriminate (FR-INGEST-35).")
    fx.close()
