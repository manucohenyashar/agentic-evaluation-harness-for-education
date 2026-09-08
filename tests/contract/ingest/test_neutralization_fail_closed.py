"""`CT-INGEST-13` — nothing unneutralized reaches a model, and every error
resolves to quarantine (`TC-INGEST-C13`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — #42 landed the
sanitizer and the fail-closed V0 stage. The real `PypdfSanitizer` over the
generated F-ADV-PDF corpus (`tests.support.corpora.materialize_adv_pdfs`, the
manifest's digest-verified constructs), scripted seams at the remaining two;
the ceilings carry their small test values through the declared knobs
(`CLAUDE.md` seam 3).

The clause: active PDF content is stripped or neutralized **before any
rasterization** (FR-INGEST-33); a file whose active content cannot be removed
quarantines and reaches no model call; resource ceilings are enforced **before
allocation** (FR-INGEST-34); and ANY error in either resolves to quarantine,
never to processing (NFR-INGEST-08). Downstream modules may treat all content
reaching them as already neutralized.

The named adversarial constructions, each executable here:

- *"move neutralization after rasterization because the rasterizer already
  sandboxes it"* — the event-order oracle is the discriminator: sanitizer and
  rasterizer both append to ONE shared timeline, so a real reorder lands in
  the very list the checker reads
  (`..._neutralization_precedes_rasterization_event_for_event`); the same
  checker applied to the mutant's hand-reordered event list goes red
  (`..._the_event_order_oracle_rejects_the_reordered_pipeline`), while every
  `FR-INGEST-*`/`SEC-*` case — which assert the outcome, not the order — stays
  green. (Second, independent teeth: the marker-absence check on the bytes
  rasterization actually read catches an unneutralized copy regardless of
  recorded order.)
- *"convert one parser exception to warn-and-continue"* — the per-class oracle
  is the discriminator: the same oracle against a warn-and-continue sanitizer
  double (fault swallowed, ORIGINAL bytes returned) sees the unsanitizable
  construct processed unneutralized and goes red
  (`..._the_warn_and_continue_mutant_turns_this_oracle_red`).

The rung-4 downstream guarantee (content reaching any other module is already
neutralized) is deferred with disclosure — M-ORCH/M-CONSOLE/M-EXTRACT do not
exist yet (stories #59..#66, #123..#130, #68..#71); the producer half held
here is what they would rely on: the sanitized copy is the only thing ever
handed to the rasterizer, asserted on the recorded bytes.
"""

from __future__ import annotations

import os
import tracemalloc
from dataclasses import dataclass, field

import pytest

from aeh.ingest import (
    MAX_DECOMPRESSED_BYTES_ENV,
    MAX_FILE_SECONDS_ENV,
    Ingestor,
    PageImage,
    PypdfSanitizer,
    SanitizeResult,
)
from aeh.prov import SamplingParams
from tests.contract.ingest._doubles import (
    COHORT,
    Contract,
    ScriptedProvider,
)
from tests.support.corpora import materialize_adv_pdfs

pytestmark = pytest.mark.contract

#: The plan's named active-content classes → the neutralization name the
#: sanitizer records and the PDF marker that must not survive into the copy
#: rasterization reads.
ACTIVE_CLASSES = {
    "ADV-PDF-01": ("javascript", b"/JavaScript"),
    "ADV-PDF-04": ("launch", b"/Launch"),
    "ADV-PDF-05": ("embedded_file", b"/EmbeddedFile"),
    "ADV-PDF-06": ("uri", b"/URI"),
}
#: The plan's decompression bomb (65 KB in, ~64 MiB declared out) and the
#: constructs the sanitizer cannot read through.
BOMB_FIXTURE = "ADV-PDF-09"
BOMB_CEILING_BYTES = 1_000_000
BOMB_DECLARED_DECOMPRESSED = 67_108_864
UNSANITIZABLE = ("ADV-PDF-12", "ADV-PDF-14")


class OrderingSanitizer(PypdfSanitizer):
    """The real sanitizer, recording when it ran — the event-order oracle's
    instrument: `("sanitize", bytes)` per call, in order. When built with a
    SHARED timeline, every event lands in that one list too, interleaved with
    the rasterizer's — the order facts then come from one instrument, not two
    reconciled logs."""

    def __init__(self, timeline: list | None = None) -> None:
        super().__init__()
        self.events: list[tuple[str, bytes]] = []
        self._timeline = timeline

    def sanitize(self, pdf_bytes, *, strip=True, **kwargs):
        self.events.append(("sanitize", bytes(pdf_bytes)))
        if self._timeline is not None:
            self._timeline.append(("sanitize", bytes(pdf_bytes)))
        return super().sanitize(pdf_bytes, strip=strip, **kwargs)


class OrderingRasterizer:
    """A scripted rasterizer that records when it ran and what bytes it was
    handed — `("rasterize", bytes)`; the bytes are the output oracle. Accepts
    the same SHARED timeline as the sanitizer."""

    def __init__(self, fault: bool = False, timeline: list | None = None) -> None:
        self.events: list[tuple[str, bytes]] = []
        self._timeline = timeline
        self.fault = fault

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.events.append(("rasterize", bytes(pdf_bytes)))
        if self._timeline is not None:
            self._timeline.append(("rasterize", bytes(pdf_bytes)))
        if self.fault:
            raise RuntimeError("injected: the rasterizer faulted")
        return [PageImage(page_no=1, png=b"page-one", width_px=100,
                          height_px=140)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class WarnAndContinueSanitizer(PypdfSanitizer):
    """The adversarial construction: the real stripper with its exceptions
    converted to warn-and-continue — the fault is swallowed and the ORIGINAL,
    unneutralized bytes proceed."""

    def sanitize(self, pdf_bytes, *, strip=True, **kwargs):
        try:
            return super().sanitize(pdf_bytes, strip=strip, **kwargs)
        except Exception:  # noqa: BLE001 -- the mutant's whole point
            return SanitizeResult(pdf_bytes=bytes(pdf_bytes))


#: A tiny benign one-pager whose only job is to pay pypdf's lazy import cost
#: OUTSIDE a traced window: first use of `PypdfSanitizer` imports pypdf, and
#: that import allocates ~9.6 MiB — toolchain overhead, not the run's
#: allocation. Without the warmup the peak cells are order-dependent on
#: whether an earlier test in the session happened to import pypdf first
#: (the TS-18 watermark finding, #47's B2).
_WARMUP_PDF = (b"%PDF-1.4\n"
               b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
               b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
               b"3 0 obj << /Type /Page /Parent 2 0 R >> endobj\n"
               b"4 0 obj << /Length 0 >>\nstream\n\nendstream\nendobj\n"
               b"xref\n0 5\n0000000000 65535 f \n"
               b"trailer << /Size 5 /Root 1 0 R >>\n"
               b"startxref\n0\n%%EOF")


@dataclass
class NeutralizationRun:
    """One corpus construct through the real pipeline: the report, the
    sanitizer's and rasterizer's event lists, the provider's calls, and the
    tracemalloc peak when the run was traced."""
    report: object
    sanitizer_events: list = field(default_factory=list)
    rasterizer_events: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    provider_calls: list = field(default_factory=list)
    traced_peak: int | None = None

    @property
    def rasterized_payloads(self) -> list[bytes]:
        return [payload for kind, payload in self.rasterizer_events
                if kind == "rasterize"]


def _run(tmp_data_dir, name: str, construct_id: str, *, sanitizer=None,
         fault_rasterizer: bool = False, env: dict | None = None,
         trace: bool = False) -> NeutralizationRun:
    """Materialize the construct into a fresh contract fixture's blob store and
    run it through the submission gateway with the real sanitizer."""
    if env:
        for key, value in env.items():
            os.environ[key] = value
    fx = Contract(tmp_data_dir, name)
    # ONE shared timeline for the sanitizer's and the rasterizer's events: the
    # event-order oracle reads completion order from a single instrument, so a
    # pipeline that reordered the stages would land the reorder in the list it
    # is checked against (the C18 construction).
    timeline: list[tuple[str, bytes]] = []
    try:
        sanitizer = sanitizer or OrderingSanitizer(timeline=timeline)
        rasterizer = OrderingRasterizer(fault=fault_rasterizer, timeline=timeline)
        provider = ScriptedProvider()
        fx.ingestor = Ingestor(
            fx.handle, fx.blobs, provider, fx.model,
            SamplingParams(temperature=0.0), rasterizer, residency=fx.residency,
            sanitizer=sanitizer)
        fx.add_roster("gus")
        paths = materialize_adv_pdfs(fx.root / "adv-pdf", ids=[construct_id])
        original = paths[construct_id].read_bytes()
        source = fx.put(original)
        provider.texts[(source, 1)] = "Student: gus\nplain page"
        if trace:
            # Warm pypdf's lazy import outside the traced window — a first-use
            # import allocates ~9.6 MiB and would be charged to this run's
            # peak, making the cell order-dependent instead of about the
            # ceiling (the TS-18 watermark convention, #47's B2).
            PypdfSanitizer().sanitize(_WARMUP_PDF, strip=True,
                                      max_decompressed_bytes=None,
                                      max_embedded_objects=None,
                                      deadline=None)
            tracemalloc.start()
        try:
            report = fx.ingestor.ingest_submission(
                [source], cohort_id=COHORT, package_version="v0",
                filenames={source: "attack.pdf"})
        finally:
            peak = None
            if trace:
                _current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
        return NeutralizationRun(
            report=report,
            sanitizer_events=getattr(sanitizer, "events", []),
            rasterizer_events=rasterizer.events,
            timeline=timeline,
            provider_calls=provider.calls, traced_peak=peak)
    finally:
        for key in (env or {}):
            os.environ.pop(key, None)
        fx.close()


def _check_event_order(events: list[tuple[str, bytes]]) -> None:
    """The step-1 oracle: no rasterization event precedes the first
    neutralization event."""
    kinds = [kind for kind, _ in events]
    if "rasterize" not in kinds:
        return  # nothing was rasterized — a quarantine; the order is vacuous
    if "sanitize" not in kinds:
        raise AssertionError(
            f"TC-INGEST-C13: the pipeline rasterized {kinds} with no "
            "neutralization event at all (FR-INGEST-33)."
        )
    if kinds.index("sanitize") > kinds.index("rasterize"):
        raise AssertionError(
            f"TC-INGEST-C13: the event sequence rasterizes before "
            f"neutralization ({kinds}) — the exploit runs in the decoder "
            "(FR-INGEST-33)."
        )


def _assert_neutralized_or_quarantined(run: NeutralizationRun, name: str,
                                       neutral: str, marker: bytes) -> None:
    """The per-class oracle: the construct is either stripped (recorded as
    neutralized, its marker absent from the bytes rasterization read, the work
    processed) or the file quarantined having reached NO model call."""
    report = run.report
    if report.gates["v0"] == "fail":
        assert len(run.provider_calls) == 0, (
            f"TC-INGEST-C13 ({name}): the quarantined construct reached "
            f"{len(run.provider_calls)} model call(s) — the exact zero oracle."
        )
        return
    neutralized = {name for names in report.detail["neutralized"].values()
                   for name in names}
    assert neutral in neutralized, (
        f"TC-INGEST-C13 ({name}): the construct was neither quarantined nor "
        f"recorded neutralized ({sorted(neutralized)!r}) — it processed with "
        "active content (FR-INGEST-33)."
    )
    assert run.rasterized_payloads, (
        f"TC-INGEST-C13 ({name}): the stripped copy was never rasterized."
    )
    assert all(marker not in payload for payload in run.rasterized_payloads), (
        f"TC-INGEST-C13 ({name}): the construct's marker survived into the "
        "sanitized copy rasterization actually reads."
    )


# -- step 1: the event order -----------------------------------------------------------


def test_tc_ingest_c13_neutralization_precedes_rasterization_event_for_event(
        tmp_data_dir):
    """`TC-INGEST-C13` step 1 — for an actively malicious source the instrument
    sees both events and no rasterization precedes the first neutralization;
    the copy rasterization reads carries no active marker. The order is read
    from ONE shared timeline the sanitizer and the rasterizer both append to,
    so a pipeline that reordered the stages would record the reorder in the
    very list this oracle checks."""
    run = _run(tmp_data_dir, "c13-order", "ADV-PDF-01")
    kinds = {kind for kind, _ in run.sanitizer_events}
    assert "sanitize" in kinds, (
        "TC-INGEST-C13: the instrument saw no sanitize event — the pipeline "
        "did not run and the ordering oracle would be vacuous."
    )
    assert run.rasterized_payloads, (
        "TC-INGEST-C13: the instrument saw no rasterization — the oracle would "
        "be vacuous."
    )
    assert {kind for kind, _ in run.timeline} == {"sanitize", "rasterize"}, (
        f"TC-INGEST-C13: the shared timeline reads "
        f"{[k for k, _ in run.timeline]} — one instrument did not record; the "
        "order fact would not be observable."
    )
    _check_event_order(run.timeline)
    _assert_neutralized_or_quarantined(run, "ADV-PDF-01", "javascript",
                                       b"/JavaScript")


def test_tc_ingest_c13_the_event_order_oracle_rejects_the_reordered_pipeline():
    """`TC-INGEST-C13` step 1's adversarial construction, executable — the
    checker passes the compliant sequence and goes red on the mutant's
    (neutralization moved after rasterization)."""
    _check_event_order([("sanitize", b"A"), ("rasterize", b"A-stripped")])
    with pytest.raises(AssertionError, match="rasterizes before"):
        _check_event_order([("rasterize", b"A"), ("sanitize", b"A")])
    with pytest.raises(AssertionError, match="no.*neutralization event"):
        _check_event_order([("rasterize", b"A")])


# -- step 2: the per-class sweep -------------------------------------------------------


@pytest.mark.parametrize("construct_id", sorted(ACTIVE_CLASSES))
def test_tc_ingest_c13_every_active_class_is_neutralized_or_quarantined(
        tmp_data_dir, construct_id):
    """`TC-INGEST-C13` step 2 — one fixture per named class (embedded
    JavaScript, launch actions, embedded files, external references): stripped
    and processed, or quarantined with exactly zero model calls; the marker
    never survives into the sanitized copy."""
    neutral, marker = ACTIVE_CLASSES[construct_id]
    run = _run(tmp_data_dir, f"c13-{construct_id}", construct_id)
    _assert_neutralized_or_quarantined(run, construct_id, neutral, marker)


@pytest.mark.parametrize("construct_id", UNSANITIZABLE)
def test_tc_ingest_c13_an_unsanitizable_construct_reaches_no_model_call(
        tmp_data_dir, construct_id):
    """`TC-INGEST-C13` step 2's refusal half — the constructs the sanitizer
    cannot read through (RC4-encrypted, truncated mid-object): quarantined as
    `unreadable` with zero model calls and zero rasterization."""
    run = _run(tmp_data_dir, f"c13-refuse-{construct_id}", construct_id)
    assert run.report.ingest_status == "unreadable" \
        and run.report.gates["v0"] == "fail", (
        f"TC-INGEST-C13 ({construct_id}): expected a V0 quarantine, got "
        f"{run.report.ingest_status!r}."
    )
    assert len(run.provider_calls) == 0, (
        f"TC-INGEST-C13 ({construct_id}): a refused artifact reached the model."
    )
    assert not run.rasterized_payloads, (
        f"TC-INGEST-C13 ({construct_id}): a refused artifact was rasterized."
    )


# -- step 3: the ceiling is pre-allocation ---------------------------------------------


def test_tc_ingest_c13_the_decompression_ceiling_refuses_before_the_allocation(
        tmp_data_dir):
    """`TC-INGEST-C13` step 3 — the decompression bomb (65 KB in, ~64 MiB
    declared out) under the ceiling knob at 1 MiB, the run traced: quarantined
    as `unreadable`, zero model calls, and the traced peak two orders of
    magnitude under the declared expansion — the refusal happened BEFORE the
    allocation (FR-INGEST-34), which is what watching peak memory sees and an
    exception-catch afterwards cannot."""
    run = _run(tmp_data_dir, "c13-bomb", BOMB_FIXTURE,
               env={MAX_DECOMPRESSED_BYTES_ENV: str(BOMB_CEILING_BYTES)},
               trace=True)
    assert run.report.ingest_status == "unreadable" \
        and run.report.gates["v0"] == "fail", (
        f"TC-INGEST-C13: the bomb did not quarantine at the ceiling: "
        f"{run.report.ingest_status}."
    )
    assert len(run.provider_calls) == 0, (
        "TC-INGEST-C13: the ceiling-refused bomb reached the model."
    )
    assert run.traced_peak is not None, (
        "TC-INGEST-C13: the run was not traced — the pre-allocation oracle is "
        "vacuous."
    )
    assert run.traced_peak < BOMB_DECLARED_DECOMPRESSED / 10, (
        f"TC-INGEST-C13: the refused ingest traced a peak of "
        f"{run.traced_peak} bytes — an allocation comparable to the bomb's "
        f"{BOMB_DECLARED_DECOMPRESSED}-byte expansion happened before the "
        "refusal."
    )


# -- step 4: the fail-closed sweep -----------------------------------------------------


class _FaultySanitizer(PypdfSanitizer):
    """The real stripper with a fault injected — before the parser runs, and
    after a successful strip (a crash on the way out)."""

    def __init__(self, when: str) -> None:
        super().__init__()
        self._when = when

    def sanitize(self, pdf_bytes, *, strip=True, **kwargs):
        if self._when == "entry":
            raise RuntimeError("injected: the stripper died on entry")
        result = super().sanitize(pdf_bytes, strip=strip, **kwargs)
        if self._when == "exit":
            raise RuntimeError("injected: the stripper died after stripping")
        return result


@pytest.mark.parametrize("fault", ["entry", "exit"])
def test_tc_ingest_c13_a_sanitizer_fault_resolves_to_quarantine(
        tmp_data_dir, fault):
    """`TC-INGEST-C13` step 4 — an exception injected inside the stripper at
    either side of the work: each resolves to a V0 quarantine, zero model
    calls, zero rasterization."""
    run = _run(tmp_data_dir, f"c13-fault-{fault}", "ADV-PDF-01",
               sanitizer=_FaultySanitizer(fault))
    assert run.report.ingest_status == "unreadable" \
        and run.report.gates["v0"] == "fail", (
        f"TC-INGEST-C13 ({fault}): a stripper fault resolved to "
        f"{run.report.ingest_status!r}, not quarantine."
    )
    assert len(run.provider_calls) == 0, (
        f"TC-INGEST-C13 ({fault}): the faulted artifact reached the model."
    )
    assert not run.rasterized_payloads, (
        f"TC-INGEST-C13 ({fault}): the faulted artifact was rasterized."
    )


def test_tc_ingest_c13_a_rasterizer_fault_and_an_expired_deadline_quarantine(
        tmp_data_dir):
    """`TC-INGEST-C13` step 4 — the two non-sanitizer steps of the
    neutralization path: a fault inside the rasterizer (post-strip), and a
    deadline expired before the strip can run. Both resolve to quarantine with
    zero model calls — never to processing."""
    raster_fault = _run(tmp_data_dir, "c13-raster-fault", "ADV-PDF-01",
                        fault_rasterizer=True)
    assert raster_fault.report.ingest_status == "unreadable" \
        and raster_fault.report.gates["v0"] == "fail", (
        f"TC-INGEST-C13: the rasterizer fault resolved to "
        f"{raster_fault.report.ingest_status!r}."
    )
    assert len(raster_fault.provider_calls) == 0, (
        "TC-INGEST-C13: the raster-faulted artifact reached the model."
    )
    deadline = _run(tmp_data_dir, "c13-deadline", "ADV-PDF-01",
                    env={MAX_FILE_SECONDS_ENV: "0"})
    assert deadline.report.ingest_status == "unreadable" \
        and deadline.report.gates["v0"] == "fail", (
        f"TC-INGEST-C13: an expired deadline resolved to "
        f"{deadline.report.ingest_status!r}."
    )
    assert len(deadline.provider_calls) == 0, (
        "TC-INGEST-C13: the deadline-expired artifact reached the model."
    )


def test_tc_ingest_c13_the_warn_and_continue_mutant_turns_this_oracle_red(
        tmp_data_dir):
    """`TC-INGEST-C13`'s adversarial construction, executable — the same
    per-class oracle against a sanitizer whose parser exception is converted to
    warn-and-continue: the unsanitizable construct PROCESSES unneutralized
    (premise asserted), and the oracle goes red on it. The compliant pipeline's
    green on the same fixture is `..._an_unsanitizable_construct...` above."""
    run = _run(tmp_data_dir, "c13-mutant", "ADV-PDF-12",
               sanitizer=WarnAndContinueSanitizer())
    processed = (run.report.gates["v0"] == "pass"
                 and len(run.provider_calls) > 0)
    assert processed, (
        f"TC-INGEST-C13: the mutant fixture did not process the unsanitizable "
        f"construct (status {run.report.ingest_status}, calls "
        f"{len(run.provider_calls)}) — the demo's premise does not hold "
        "against the shipped seams, so the red cannot be demonstrated."
    )
    with pytest.raises(AssertionError, match="neither quarantined nor"):
        _assert_neutralized_or_quarantined(run, "ADV-PDF-12-mutant",
                                           "javascript", b"/Encrypt")
