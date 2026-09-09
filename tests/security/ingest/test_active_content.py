"""Active content neutralized or refused, and the fail-closed boundary (`M-INGEST` security).

Cases `TC-INGEST-33` and the `SEC-05` / `SEC-07` / `SEC-08` rows of test plan §6.5
(TS-18, issue #47), against the sanitizer the gateway story #42 landed. Rung 2 as the
issue's isolation names it — **the real `PypdfSanitizer`** over the real PDF library,
the corpus generated and digest-verified on demand (`tests.support.corpora.
materialize_adv_pdfs`, the F-ADV-PDF manifest's reproducibility contract), a scripted
rasterizer and provider at the two remaining seams. The wall-clock and page ceilings
carry their small test values through the declared knobs.

One declared reading this suite pins rather than papers over: the F-ADV-PDF
manifest's `expected_outcome: quarantine` is the adversarial-tier world
(`TC-CONFORM-09`, strip disabled), and `FR-INGEST-33`'s default knob is the other
half of the same fork — **strip vs REFUSE, never sanitize-vs-process**: with
`HARNESS_INGEST_STRIP_ACTIVE_CONTENT` at its default, every active construct is
neutralized before rasterization and the sanitized copy — the bytes the rasterizer
is actually handed — carries none of it; with the knob at `false`, the same
construct quarantines as `unreadable` and reaches no model call. Both worlds are
asserted below, per construct, against the sanitized bytes themselves.
"""

from __future__ import annotations

import zlib

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    IngestSanitizeError,
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
COHORT = "c-sec"

#: Construct id → the PDF marker that names it, and the reason a stripped copy must
#: not carry it. The markers are the objects the §4.4 constructs are built from.
CONSTRUCT_MARKERS = {
    "ADV-PDF-01": b"/JavaScript",
    "ADV-PDF-02": b"/OpenAction",
    "ADV-PDF-03": b"/AA",
    "ADV-PDF-04": b"/Launch",
    "ADV-PDF-05": b"/EmbeddedFile",
    "ADV-PDF-06": b"/URI",
    "ADV-PDF-07": b"/GoToR",
    "ADV-PDF-08": b"/SubmitForm",
}
NEUTRALIZED_NAMES = {
    "ADV-PDF-01": "javascript", "ADV-PDF-02": "open_action",
    "ADV-PDF-03": "aa", "ADV-PDF-04": "launch",
    "ADV-PDF-05": "embedded_file", "ADV-PDF-06": "uri",
    "ADV-PDF-07": "goto_r", "ADV-PDF-08": "submit_form",
}


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:dddd", quantization="q4")


class RecordingRasterizer:
    """Records every byte range it is handed — the probe point for 'the sanitized
    copy that rasterization actually reads' (TC-INGEST-33's step 2). `default_pages`
    lets a test script the page count for sources whose parse the real library
    tolerates (the zero-page and cyclic cases route through it)."""

    def __init__(self, plan: dict | None = None,
                 default_pages: list | None = None) -> None:
        self.plan = plan or {}
        self.default_pages = ([(1, b"page-one", 1000, 1400)]
                              if default_pages is None else default_pages)
        self.seen: list[bytes] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.seen.append(bytes(pdf_bytes))
        pages = self.plan.get(bytes(pdf_bytes), self.default_pages)
        return [PageImage(page_no=page_no, png=png, width_px=w, height_px=h)
                for page_no, png, w, h in pages]

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


class _Security:
    """The real sanitizer over one fresh store; the corpus materialized inside the
    store's own data dir."""

    def __init__(self, tmp_data_dir, name: str, sanitizer=None,
                 raster_default: list | None = None) -> None:
        self.root = tmp_data_dir / f"v47-{name}"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                       "created_at) VALUES (:c, 'synthetic', 'x')", c=COHORT)
        self.rasterizer = RecordingRasterizer(default_pages=raster_default)
        self.provider = CountingProvider()
        self.ingestor = Ingestor(self.handle, self.blobs, self.provider,
                                 _model(), SamplingParams(temperature=0.0),
                                 self.rasterizer,
                                 residency=ResidencySlot.for_policy(
                                     ("transcriber",)),
                                 sanitizer=sanitizer or PypdfSanitizer())

    def fixture(self, fixture_id: str) -> tuple[str, bytes]:
        paths = materialize_adv_pdfs(self.root / "adv-pdf", ids=[fixture_id])
        data = paths[fixture_id].read_bytes()
        return self.blobs.put(data), data

    def submission_rows(self):
        return self.handle.query("SELECT ingest_status, quarantined, "
                                 "v0_integrity FROM submission")

    def close(self) -> None:
        self.store.close()


# -- TC-INGEST-33 + SEC-05: every active construct stripped before rasterization -------------------


@pytest.mark.parametrize("fixture_id", sorted(CONSTRUCT_MARKERS))
def test_tc_ingest_33_every_active_construct_is_stripped_before_rasterization(
        tmp_data_dir, fixture_id, monkeypatch):
    """`TC-INGEST-33` / `SEC-05` — one fixture per §4.4 construct, ingested with
    the strip knob pinned at its default: the construct is recorded as
    neutralized, the sanitized copy the rasterizer is ACTUALLY HANDLED carries
    none of the construct's marker (step 2's oracle — asserted on the recorded
    bytes, not on a return value), exactly one model call processes the stripped
    pages, and the contrast holds: the marker is present in the source the
    teacher uploaded."""
    monkeypatch.setenv("HARNESS_INGEST_STRIP_ACTIVE_CONTENT", "true")
    fx = _Security(tmp_data_dir, f"strip-{fixture_id}")
    source, original = fx.fixture(fixture_id)

    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "attack.pdf"})

    marker = CONSTRUCT_MARKERS[fixture_id]
    assert marker in original, (
        f"TC-INGEST-33 ({fixture_id}): the fixture does not carry its own "
        "construct — the corpus changed under the test.")
    neutralized = {name for names in report.detail["neutralized"].values()
                   for name in names}
    assert NEUTRALIZED_NAMES[fixture_id] in neutralized, (
        f"TC-INGEST-33 ({fixture_id}): the construct was not recorded as "
        f"neutralized — got {sorted(neutralized)!r} (FR-INGEST-33).")
    assert fx.rasterizer.seen, (
        f"TC-INGEST-33 ({fixture_id}): the stripped copy was never rasterized.")
    assert marker not in fx.rasterizer.seen[0], (
        f"TC-INGEST-33 ({fixture_id}): the construct's marker survived into the "
        "sanitized copy that rasterization actually reads (FR-INGEST-33).")
    assert fx.provider.calls == 1, (
        f"TC-INGEST-33 ({fixture_id}): the stripped artifact was not processed — "
        f"{fx.provider.calls} calls; the declared reading is strip vs REFUSE, "
        "never sanitize-vs-process.")
    fx.close()


# -- TC-INGEST-33's own fixture gap: several constructs at once, and one hidden in an object stream


def _pdf_with_constructs_in_object_stream() -> bytes:
    """A 1.5-shaped document whose page lives in an ObjStm beside a JavaScript
    action — the plan's object-stream variant: the construct exists only inside
    the compressed object stream, invisible to a walk that does not descend."""
    header = b"3 0 4 0 "
    page_body = b"<< /Type /Page /Parent 2 0 R >>"
    js_body = b"<< /S /JavaScript /JS (app.launchURL('http://attacker')) >>"
    objstm_data = zlib.compress(header + page_body + js_body)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /ObjStm /N 2 /First {len(header)} /Length "
         f"{len(objstm_data)} /Filter /FlateDecode >>\nstream\n").encode()
        + objstm_data + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.5\n")
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


def test_tc_ingest_33_a_construct_hidden_in_an_object_stream_never_survives(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-33`'s object-stream variant — the plan names it a probe: if the
    construct inside a compressed object stream is not neutralized, that is a
    finding. The oracle reads the output, not the bookkeeping: the `/JavaScript`
    marker must be absent from the sanitized copy the rasterizer is handed, and
    the pipeline must process the stripped result. (Mechanism note: the strip
    walk's reach into object streams and the re-serialization that drops them are
    implementation details; what this cell pins is the output the pipeline
    actually reads.)"""
    monkeypatch.setenv("HARNESS_INGEST_STRIP_ACTIVE_CONTENT", "true")
    fx = _Security(tmp_data_dir, "objstm")
    source = fx.blobs.put(_pdf_with_constructs_in_object_stream())
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "objstm.pdf"})
    assert fx.rasterizer.seen, (
        "TC-INGEST-33 (objstm): the document was never rasterized.")
    assert b"/JavaScript" not in fx.rasterizer.seen[0], (
        "TC-INGEST-33: the object-stream-hidden construct survived into the "
        "sanitized copy — a finding, not a test bug (FR-INGEST-33).")
    assert fx.provider.calls == 1
    fx.close()


def test_tc_ingest_33_several_constructs_at_once_are_all_stripped(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-33`'s multi-construct precondition — one PDF carrying several
    constructs at once (JavaScript, URI and OpenAction together): every one is
    recorded as neutralized and none of their markers survives into the sanitized
    copy the rasterizer reads."""
    monkeypatch.setenv("HARNESS_INGEST_STRIP_ACTIVE_CONTENT", "true")
    fx = _Security(tmp_data_dir, "multi")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /JavaScript "
        b"/JS (bad()) >> >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /AA << /O << /S /URI /URI "
        b"(http://attacker) >> >> >>",
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
    source = fx.blobs.put(bytes(out))
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "multi.pdf"})
    neutralized = {name for names in report.detail["neutralized"].values()
                   for name in names}
    assert {"javascript", "open_action", "uri"} <= neutralized, (
        f"TC-INGEST-33: the multi-construct fixture was not fully stripped — "
        f"got {sorted(neutralized)!r} (FR-INGEST-33).")
    handed = fx.rasterizer.seen[0]
    for marker in (b"/JavaScript", b"/OpenAction", b"/URI"):
        assert marker not in handed, (
            f"TC-INGEST-33: the marker {marker!r} survived into the sanitized "
            "copy (FR-INGEST-33).")
    fx.close()


# -- SEC-05/TC-INGEST-33's refusal half + the strip knob -------------------------------------------


def test_sec_05_the_strip_knob_disabled_refuses_instead_of_processing(
        tmp_data_dir, monkeypatch):
    """`SEC-05` / `FR-INGEST-33` — the same construct with
    `HARNESS_INGEST_STRIP_ACTIVE_CONTENT=false`: the artifact **refuses** —
    quarantined as `unreadable`, zero VLM calls, nothing rasterized. The knob
    chooses between stripping and refusing; it never chooses processing."""
    monkeypatch.setenv("HARNESS_INGEST_STRIP_ACTIVE_CONTENT", "false")
    fx = _Security(tmp_data_dir, "strip-off")
    source, _ = fx.fixture("ADV-PDF-01")
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "attack.pdf"})
    assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail"
    assert fx.provider.calls == 0, (
        "SEC-05: with stripping disabled, an active construct reached the "
        "model — the knob must REFUSE, never process.")
    assert fx.rasterizer.seen == []
    assert fx.submission_rows()[0]["quarantined"] == 1
    fx.close()


@pytest.mark.parametrize("fixture_id", ["ADV-PDF-12", "ADV-PDF-14"])
def test_sec_05_anything_unsanitizable_reaches_no_model_call(tmp_data_dir,
                                                             fixture_id):
    """`SEC-05` — the two fixtures the sanitizer cannot read through (really
    RC4-encrypted; truncated mid-object): each quarantines as `unreadable` with
    **zero** VLM calls and zero rasterization — the exact call-count oracle."""
    fx = _Security(tmp_data_dir, f"refuse-{fixture_id}")
    source, _ = fx.fixture(fixture_id)
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "attack.pdf"})
    assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail", (
        f"SEC-05 ({fixture_id}): an unreadable artifact must quarantine at V0.")
    assert fx.provider.calls == 0, (
        f"SEC-05 ({fixture_id}): a refused artifact reached the model — the "
        "exact call-count oracle names zero.")
    assert fx.rasterizer.seen == []
    fx.close()


# -- SEC-07: an exception inside the stripper resolves to quarantine -------------------------------


class _FaultySanitizer(PypdfSanitizer):
    """The real stripper with a fault injected — the issue's step 4, at two points:
    before the parser runs, and after a successful strip (a crash on the way out)."""

    def __init__(self, when: str) -> None:
        super().__init__()
        self._when = when

    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        if self._when == "entry":
            raise RuntimeError("injected: the stripper died on entry")
        result = super().sanitize(pdf_bytes, strip=strip,
                                  max_decompressed_bytes=max_decompressed_bytes,
                                  max_embedded_objects=max_embedded_objects,
                                  deadline=deadline)
        if self._when == "exit":
            raise RuntimeError("injected: the stripper died after stripping")
        return result


@pytest.mark.parametrize("when", ["entry", "exit"])
def test_sec_07_an_exception_inside_the_stripper_resolves_to_quarantine(
        tmp_data_dir, when):
    """`SEC-07` — fail-closed: an exception injected inside the stripper — declared
    or not — resolves to a V0 quarantine, never to processing. NFR-INGEST-08's
    catch is deliberately broad and this pins it from both sides of the work."""
    fx = _Security(tmp_data_dir, f"fault-{when}",
                   sanitizer=_FaultySanitizer(when))
    source, _ = fx.fixture("ADV-PDF-01")
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "attack.pdf"})
    assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail", (
        f"SEC-07 ({when}): a stripper fault must resolve to quarantine, got "
        f"{report.ingest_status!r}.")
    assert fx.provider.calls == 0, (
        f"SEC-07 ({when}): the faulted artifact reached the model.")
    assert fx.submission_rows()[0]["quarantined"] == 1
    fx.close()


# -- SEC-08: the malformed quartet, no hang, no unhandled exception --------------------------------


def _cyclic_zero_page_pdf() -> bytes:
    """A PDF whose object graph is cyclic (catalog ↔ pages) and whose page tree
    resolves to nothing: the sanitizer's seen-set must walk it without hanging,
    and the pipeline must quarantine it as unreadable (zero pages)."""
    return (b"%PDF-1.4\n"
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Parent 1 0 R /Kids [] /Count 1 >> endobj\n"
            b"xref\n0 3\n0000000000 65535 f \n"
            b"trailer << /Size 3 /Root 1 0 R >>\n"
            b"startxref\n0\n%%EOF")


@pytest.mark.parametrize("fixture_id",
                         ["ADV-PDF-12", "ADV-PDF-13", "ADV-PDF-14", "cyclic"],
                         ids=["encrypted", "zero-page", "truncated", "cyclic"])
def test_sec_08_the_malformed_quartet_quarantine_without_hanging(
        tmp_data_dir, fixture_id, monkeypatch):
    """`SEC-08` — encrypted, zero-page, truncated and a cyclic object graph: each
    quarantines as `unreadable`, with no hang (the wall-clock ceiling carries its
    small test value) and no unhandled exception outside the declared taxonomy —
    every outcome is either a successful ingest or a quarantine. The zero-page and
    cyclic sources are ones the real sanitizer tolerates, so the scripted
    rasterizer answers zero pages for them — the pipeline's zero-page resolution
    is what the case then pins."""
    monkeypatch.setenv("HARNESS_INGEST_MAX_FILE_SECONDS", "10")
    fx = _Security(tmp_data_dir, f"malformed-{fixture_id}",
                   raster_default=[])
    if fixture_id == "cyclic":
        source = fx.blobs.put(_cyclic_zero_page_pdf())
    else:
        source, _ = fx.fixture(fixture_id)
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "malformed.pdf"})
    assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail", (
        f"SEC-08 ({fixture_id}): expected a V0 quarantine, got "
        f"{report.ingest_status!r}.")
    assert fx.submission_rows()[0]["quarantined"] == 1
    fx.close()
