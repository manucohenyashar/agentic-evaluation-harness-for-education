"""Active-content construct variants the #47 suite disclosed as missing (#237, TS-18 corpus).

Cases `TC-INGEST-33` / `TC-INGEST-34` (FR-INGEST-33), three construct classes no existing
fixture carried:

- **A deliberately-unremovable construct.** A `/Launch` action dictionary hung under a key the
  strip pass does not prune (not `/A`, `/AA`, `/OpenAction`, `/JS`, `/XFA` or `/EF`), so the
  measurement walk detects it, the strip leaves it, and the VERIFY re-parse finds it again. This
  is the sanitizer's survival branch (`PypdfSanitizer.sanitize`: "a surviving construct reads as
  `unremovable` rather than as success"), which only the strip-disabled refusal reached before.
- **An incremental-update variant.** A clean document followed by an incremental update section
  whose new catalog revision carries an `/OpenAction` JavaScript action.
- **An XFA variant.** An `/AcroForm` whose `/XFA` stream carries an XDP packet with a script.

Rung 2 as #47: the real `PypdfSanitizer` over the real PDF library, a real store, a recording
rasterizer and a counting provider at the two remaining seams, no network. The strip knob's two
worlds are asserted as #47 reads them: strip active (the default) → neutralized or, for the
survivor, refused; strip disabled → refused.

**Why these fixtures are built here and not in `F-ADV-PDF`.** The corpus manifest is pinned to
test plan §4.4's fourteen constructs (`harness.corpora.adv_pdf.SECTION_4_4_CONSTRUCTS`, asserted
by `test_tc_conform_09_adversarial_corpora.py`). Adding variants there changes the plan's corpus
definition, which is `/create-test-plan`'s. The fixtures follow the #47 suite's own precedent for
variants (the object-stream and multi-construct PDFs are built in-test), and are deterministic.
"""

from __future__ import annotations

import pytest

from aeh.conf import ModelRef
from aeh.ingest import Ingestor, PageImage, PypdfSanitizer, ResidencySlot
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store

pytestmark = pytest.mark.integration

COHORT = "c-sec-237"
STRIP_ENV = "HARNESS_INGEST_STRIP_ACTIVE_CONTENT"


# -- the fixtures ----------------------------------------------------------------------------------


def _body(objects: dict[int, bytes], start: int) -> tuple[bytes, dict[int, int]]:
    out = bytearray()
    offsets = {}
    for number, body in objects.items():
        offsets[number] = start + len(out)
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    return bytes(out), offsets


def _xref(offsets: dict[int, int]) -> bytes:
    out = bytearray(b"xref\n")
    for number in sorted(offsets):
        out += f"{number} 1\n{offsets[number]:010d} 00000 n \n".encode()
    return bytes(out)


def _pdf(objects: dict[int, bytes]) -> bytes:
    """A single-revision PDF 1.4 with a classic xref (object 0 included)."""
    head = b"%PDF-1.4\n"
    body, offsets = _body(objects, len(head))
    xref_at = len(head) + len(body)
    size = max(objects) + 1
    xref = f"xref\n0 {size}\n0000000000 65535 f \n".encode() + b"".join(
        f"{offsets[n]:010d} 00000 n \n".encode() for n in range(1, size))
    trailer = (f"trailer << /Size {size} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n").encode()
    return head + body + xref + trailer


PAGES = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
PAGE = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"


def survivor_pdf() -> bytes:
    """`/Launch` under `/PieceInfo` (a private-data dictionary the strip pass does not
    prune): detected by the walk, left by the strip, re-detected by the verify pass."""
    page = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/PieceInfo << /Vendor << /S /Launch /F (calc.exe) >> >> >>")
    return _pdf({1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: PAGES, 3: page})


def removable_launch_pdf() -> bytes:
    """The same `/Launch` action where the strip pass does reach it (a page `/AA` open
    action): the contrast that tells "stripped clean" from "survived"."""
    page = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/AA << /O << /S /Launch /F (calc.exe) >> >> >>")
    return _pdf({1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: PAGES, 3: page})


def incremental_update_pdf() -> bytes:
    """A clean revision, then an incremental update whose catalog revision adds an
    `/OpenAction` JavaScript action. The construct exists only after the first %%EOF."""
    base = _pdf({1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: PAGES, 3: PAGE})
    first_xref = int(base.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
    update_objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R >>",
        4: b"<< /S /JavaScript /JS (app.alert('update')) >>",
    }
    body, offsets = _body(update_objects, len(base))
    xref_at = len(base) + len(body)
    trailer = (f"trailer << /Size 5 /Root 1 0 R /Prev {first_xref} >>\n"
               f"startxref\n{xref_at}\n%%EOF\n").encode()
    return base + body + _xref(offsets) + trailer


XDP = (b"<xdp:xdp xmlns:xdp='http://ns.adobe.com/xdp/'><template><subform>"
       b"<event activity='initialize'><script contentType='application/x-javascript'>"
       b"xfa.host.gotoURL('http://attacker')</script></event></subform></template></xdp:xdp>")


def xfa_pdf() -> bytes:
    """An `/AcroForm` whose `/XFA` stream carries an XDP packet with an initialize script."""
    return _pdf({
        1: b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [] /XFA 4 0 R >> >>",
        2: PAGES,
        3: PAGE,
        4: f"<< /Length {len(XDP)} >>\nstream\n".encode() + XDP + b"\nendstream",
    })


# -- the harness (the #47 suite's shape) ------------------------------------------------------------


class RecordingRasterizer:
    def __init__(self) -> None:
        self.seen: list[bytes] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.seen.append(bytes(pdf_bytes))
        return [PageImage(page_no=1, png=b"page-one", width_px=1000, height_px=1400)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt, model_ref, params) -> Completion:
        self.calls += 1
        return Completion(text="plain page", tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None)


class _Gateway:
    def __init__(self, tmp_data_dir, name: str) -> None:
        self.store = open_store(tmp_data_dir / f"v237-{name}")
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, created_at) "
                       "VALUES (:c, 'synthetic', 'x')", c=COHORT)
        self.rasterizer = RecordingRasterizer()
        self.provider = CountingProvider()
        self.ingestor = Ingestor(
            self.handle, self.blobs, self.provider,
            ModelRef(role="transcriber", provider="local", build_id="vlm@sha256:dddd",
                     quantization="q4"),
            SamplingParams(temperature=0.0), self.rasterizer,
            residency=ResidencySlot.for_policy(("transcriber",)), sanitizer=PypdfSanitizer())

    def ingest(self, data: bytes, name: str):
        source = self.blobs.put(data)
        return self.ingestor.ingest_submission([source], cohort_id=COHORT, package_version="v0",
                                               filenames={source: name})

    def close(self) -> None:
        self.store.close()


def _sanitize(data: bytes, *, strip: bool):
    return PypdfSanitizer().sanitize(data, strip=strip, max_decompressed_bytes=None,
                                     max_embedded_objects=None, deadline=None)


def _neutralized(report) -> set[str]:
    return {name for names in report.detail["neutralized"].values() for name in names}


# -- the deliberately-unremovable construct: the verify pass's SURVIVAL branch -----------------------


def test_tc_ingest_33_a_construct_the_strip_cannot_reach_is_re_detected_by_the_verify_pass(
        monkeypatch):
    """The survivor, at the sanitizer: the strip pass RAN, a verify walk re-parsed its
    output and found `launch` still there, so the result is `unremovable` with nothing
    `neutralized`, and the bytes returned are the untouched original (no half-stripped
    copy). The removable twin, same action reached through `/AA`, is stripped clean —
    the contrast this branch needs, which the strip-disabled refusal cannot give."""
    calls = {"walk": 0, "strip": 0}
    real_walk, real_strip = PypdfSanitizer._walk, PypdfSanitizer._strip

    def walk(self, *args, **kwargs):
        calls["walk"] += 1
        return real_walk(self, *args, **kwargs)

    def strip(self, *args, **kwargs):
        calls["strip"] += 1
        return real_strip(self, *args, **kwargs)

    monkeypatch.setattr(PypdfSanitizer, "_walk", walk)
    monkeypatch.setattr(PypdfSanitizer, "_strip", strip)

    data = survivor_pdf()
    result = _sanitize(data, strip=True)
    assert (result.unremovable, result.neutralized) == (("launch",), ()), result
    assert calls == {"walk": 2, "strip": 1}, (
        f"TC-INGEST-33: the survivor must be found by the VERIFY walk after a strip ran, "
        f"got {calls} — a refusal before the strip is the strip-disabled branch")
    assert result.pdf_bytes == data, "the survivor's refusal must return the original bytes"

    calls.update(walk=0, strip=0)
    twin = _sanitize(removable_launch_pdf(), strip=True)
    assert (twin.unremovable, twin.neutralized) == ((), ("aa", "launch")), twin
    assert calls == {"walk": 2, "strip": 1}
    assert b"/Launch" not in twin.pdf_bytes


def test_tc_ingest_33_the_unremovable_construct_quarantines_with_zero_model_calls(
        tmp_data_dir, monkeypatch):
    """The survivor, through the gateway with the strip knob at its default: quarantined
    `unreadable` at V0, the finding names the survivor, nothing is rasterized and no model
    is called — the strip-active world refusing, not processing."""
    monkeypatch.setenv(STRIP_ENV, "true")
    fx = _Gateway(tmp_data_dir, "survivor")
    try:
        report = fx.ingest(survivor_pdf(), "survivor.pdf")
        assert (report.ingest_status, report.gates["v0"]) == ("unreadable", "fail")
        assert fx.rasterizer.seen == [] and fx.provider.calls == 0
        findings = " ".join(str(finding) for finding in report.detail["findings"])
        assert "cannot be removed" in findings and "launch" in findings, findings
        assert _neutralized(report) == set(), (
            "TC-INGEST-33: a construct that survived must not be recorded as neutralized")
    finally:
        fx.close()


# -- the incremental-update and XFA variants: both worlds --------------------------------------------


VARIANTS = {
    "incremental-update": (incremental_update_pdf, {"open_action", "javascript"},
                           (b"/OpenAction", b"/JavaScript", b"app.alert")),
    "xfa": (xfa_pdf, {"xfa"}, (b"/XFA", b"gotoURL")),
}


def test_the_variant_fixtures_carry_their_constructs_where_declared():
    """Fixture guard: the incremental update's construct lives only after the first
    %%EOF (in the update section), and the XFA packet carries its script."""
    data = incremental_update_pdf()
    first_eof = data.index(b"%%EOF")
    assert data.count(b"%%EOF") == 2 and data.index(b"/OpenAction") > first_eof
    assert b"/Prev" in data[first_eof:]
    assert b"gotoURL" in xfa_pdf() and b"/XFA" in xfa_pdf()


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_tc_ingest_33_the_variant_is_stripped_before_rasterization(tmp_data_dir, monkeypatch,
                                                                   variant):
    """Strip active: the construct is recorded as neutralized, the sanitized copy the
    rasterizer is actually handed carries none of its markers, and exactly one model call
    processes the stripped page."""
    monkeypatch.setenv(STRIP_ENV, "true")
    build, names, markers = VARIANTS[variant]
    data = build()
    for marker in markers:
        assert marker in data, f"fixture: {variant} lost its marker {marker!r}"
    fx = _Gateway(tmp_data_dir, f"strip-{variant}")
    try:
        report = fx.ingest(data, f"{variant}.pdf")
        assert names <= _neutralized(report), (
            f"TC-INGEST-33 ({variant}): expected {sorted(names)} neutralized, "
            f"got {sorted(_neutralized(report))}")
        assert fx.rasterizer.seen, f"{variant}: the stripped copy was not rasterized"
        for handed in fx.rasterizer.seen:
            assert handed != data, f"{variant}: the unsanitized source reached the rasterizer"
            for marker in markers:
                assert marker not in handed, (
                    f"TC-INGEST-33 ({variant}): {marker!r} survived into a sanitized copy "
                    "the rasterizer read")
        assert fx.provider.calls == 1
    finally:
        fx.close()


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_tc_ingest_33_the_variant_refuses_with_the_strip_knob_disabled(tmp_data_dir, monkeypatch,
                                                                       variant):
    """Strip disabled: the same variant refuses — quarantined `unreadable`, nothing
    rasterized, zero model calls — and the sanitizer names the construct as unremovable."""
    monkeypatch.setenv(STRIP_ENV, "false")
    build, names, _markers = VARIANTS[variant]
    assert names <= set(_sanitize(build(), strip=False).unremovable)
    fx = _Gateway(tmp_data_dir, f"refuse-{variant}")
    try:
        report = fx.ingest(build(), f"{variant}.pdf")
        assert (report.ingest_status, report.gates["v0"]) == ("unreadable", "fail")
        assert fx.rasterizer.seen == [] and fx.provider.calls == 0
    finally:
        fx.close()
