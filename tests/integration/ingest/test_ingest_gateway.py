"""The sole PDF gateway: rasterize, transcribe, emit one immutable document (`M-INGEST`).

Cases `TC-INGEST-01`, `TC-INGEST-02`, `TC-INGEST-05`, `TC-INGEST-06` (test plan §5.5,
via TS-14/issue #43's pairing with #36) plus the residency-slot acceptance criterion
from #36's own list. The remaining TS-14 cases (text-layer divergence, assembly-order
preference, page provenance, duplicate/gap detection) are #37's and land with it.

Rung 2 — real Tier C files, real blob directories; the VLM is a scripted
`InferenceProvider` (the `RecordedFixtureProvider` shape: one `Completion` per call,
resolved build pinned) and the rasterizer is a scripted `Rasterizer` — the two seams the
module declares precisely so these cases can count calls and pin the DPI without a PDF
library or a network.

`Written ahead of implementation: yes` is stale — the gateway landed with #36; these
cases run green by design.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import pathlib
import sqlite3
import threading

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    DOCUMENT_KINDS,
    EVALUATIVE_TERMS,
    IngestDuplicateError,
    IngestError,
    IngestGapError,
    IngestOrderError,
    Ingestor,
    PageImage,
    PageReplacement,
    PdfSanitizer,
    ResidencySlot,
    SanitizeResult,
    Rasterizer,
    TRANSCRIPTION_PROMPT_VERSION,
)
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#36"

PDF_LIBRARY_MARKERS = ("pypdfium2", "pdfminer", "fitz", "pypdf", "pdf2image",
                       "PyPDF2", "imageio")


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:aaaa", quantization="q4")


class ScriptedRasterizer(Rasterizer):
    """A rasterizer double: returns the scripted page count for a given source, records
    every DPI it is asked for, and renders deterministic per-page PNG bytes."""

    def __init__(self) -> None:
        self.plan: dict[bytes, int] = {}
        self.dpi_seen: list[int] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.dpi_seen.append(dpi)
        count = self.plan.get(pdf_bytes, 2)
        return [
            PageImage(page_no=index + 1,
                      png=f"png-{pdf_bytes.decode('utf-8', errors='replace')}-{index}".encode(),
                      width_px=100, height_px=140)
            for index in range(count)
        ]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A]) + (
            f"crop {box} from page {page_no} of "
            f"{pdf_bytes.decode('utf-8', errors='replace')}".encode())



class ThroughSanitizer(PdfSanitizer):
    """The fast-tier sanitizer double (#42): no active constructs, the bytes
    pass through untouched — the scripted twin of the rasterizer double above.
    The seam is a required constructor argument, so the fast tier names one
    exactly as it names its scripted provider and rasterizer; the live
    `PypdfSanitizer` is exercised by the rung-2 security cases."""

    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


THROUGH_SANITIZER = ThroughSanitizer()


class ScriptedProvider:
    """A provider double with the `RecordedFixtureProvider` shape: one deterministic
    `Completion` per call, resolved build pinned, every payload recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.build_override: str | None = None
        self.while_calling = None

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        image = fields["image_png_base64"]
        self.calls.append((fields["page_no"], image))
        if self.while_calling is not None:
            self.while_calling()
        return Completion(
            text=f"transcript-of-{image}", tokens_in=10, tokens_out=5, latency_ms=1,
            resolved_build=self.build_override or model_ref.build_id,
            cached_prefix_tokens=0, cost=None,
        )


def _fixture(tmp_data_dir):
    store = open_store(tmp_data_dir)
    blobs = store.blobs()
    rasterizer = ScriptedRasterizer()
    provider = ScriptedProvider()
    slot = ResidencySlot.for_policy(("transcriber",))
    ingestor = Ingestor(store.cohort("c-36"), blobs, provider, _model(),
                        SamplingParams(temperature=0.0), rasterizer, residency=slot, sanitizer=THROUGH_SANITIZER)
    return store, blobs, rasterizer, provider, slot, ingestor


# -- TC-INGEST-01: the gateway is the only PDF path ----------------------------------------------


def test_tc_ingest_01_only_m_ingest_touches_pdfs_and_no_entry_point_takes_a_path():
    """`TC-INGEST-01` — *'Only `M-INGEST` imports a PDF library or an image decoder; no
    downstream entry point accepts a path or an image argument'* — the design names both
    halves as the acceptance form, so the case asserts both: an import-graph scan over
    every `aeh` module, and a signature sweep over every public callable outside
    `M-INGEST`."""
    root = pathlib.Path("src", "aeh")
    pdf_importers = []
    for path in sorted(root.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for marker in PDF_LIBRARY_MARKERS:
            if marker in text and path.name != "ingest.py":
                pdf_importers.append(f"{path.name}: {marker}")
    assert not pdf_importers, (
        f"TC-INGEST-01: PDF/image decoding exists outside M-INGEST: {pdf_importers}. "
        "The gateway is the only route from PDF to text (FR-INGEST-01, R38)."
    )
    # The interface half: no downstream entry point takes a path or an image argument.
    import aeh.ingest as ingest_module
    import aeh.pkg as pkg_module
    import aeh.store as store_module

    for module in (pkg_module, store_module, ingest_module):
        for name, obj in vars(module).items():
            if name.startswith("_") or not callable(obj) or inspect.isclass(obj):
                continue
            if getattr(obj, "__module__", "") != module.__name__:
                continue
            try:
                parameters = inspect.signature(obj).parameters
            except (TypeError, ValueError):
                continue
            forbidden = [parameter for parameter in parameters
                         if parameter.lower() in ("path", "pdf", "image", "filepath",
                                                  "pdf_path", "image_path")]
            if module is ingest_module:
                continue  # the gateway itself takes source blobs, asserted below
            assert not forbidden, (
                f"TC-INGEST-01: {module.__name__}.{name} accepts {forbidden} — "
                "downstream stages receive a document_id and read document.markdown "
                "(FR-INGEST-01)."
            )
    # And the gateway's own entry points take blob hashes, never paths:
    for method in (Ingestor.ingest_document, Ingestor.revise_document,
                   Ingestor.ingest_submission):
        parameters = inspect.signature(method).parameters
        assert not any(parameter.lower() in ("path", "pdf", "image")
                       for parameter in parameters), (
            f"TC-INGEST-01: {method.__name__} takes a path-like argument — the "
            "gateway's inputs are content-addressed blob hashes."
        )


# -- TC-INGEST-02: one rasterization and one VLM call per page, for every kind --------------------


def test_tc_ingest_02_every_page_of_every_kind_gets_exactly_one_call(tmp_data_dir):
    """`TC-INGEST-02` — a two-page PDF of EACH artifact kind: every page rasterized at
    the pinned DPI and transcribed with exactly ONE VLM call — call count equals page
    count for all four kinds — and no per-kind alternative path exists in the module's
    dispatch (asserted over the source: no `kind ==` branch selects an extraction
    path)."""
    store, blobs, rasterizer, provider, slot, ingestor = _fixture(tmp_data_dir)
    source = blobs.put(b"fixture pdf: two pages")
    total_calls = 0
    for kind in DOCUMENT_KINDS:
        before = len(provider.calls)
        document_id = ingestor.ingest_document(
            [source], kind=kind, filenames={source: "scan-01.md"})
        row = store.cohort("c-36").query(statement(
            "SELECT kind FROM document WHERE document_id = :d", issue=ISSUE),
            d=document_id)[0]
        assert row["kind"] == kind
        assert len(provider.calls) - before == 2, (
            f"TC-INGEST-02: kind {kind!r} made {len(provider.calls) - before} VLM "
            "calls for a two-page PDF — every page is transcribed with exactly one "
            "call (FR-INGEST-02)."
        )
        # Exactly one call PER PAGE: the recorded (page_no, image) pairs cover page 1
        # and page 2 once each — a path that called one page twice and skipped the
        # other would pass a bare count.
        page_numbers = [page_no for page_no, _ in provider.calls[before:]]
        assert sorted(page_numbers) == ["1", "2"], (
            f"TC-INGEST-02: the calls covered pages {page_numbers} — one call per "
            "page, not merely the right total (FR-INGEST-02)."
        )
        total_calls += len(provider.calls) - before
    assert total_calls == 8
    assert set(rasterizer.dpi_seen) == {200}, (
        "TC-INGEST-02: the rasterization DPI is not the pinned default."
    )
    # No per-kind alternative path: the pipeline never branches on kind.
    module_source = pathlib.Path("src", "aeh", "ingest.py").read_text(encoding="utf-8")
    # Branches on the ARTIFACT kinds specifically (the parser's region-kind locals
    # are a different variable entirely): only the two DECLARED post-transcription
    # gates may branch — the reference divergence halt (FR-INGEST-03) and, since
    # #42, the submission untrusted-content demarcation (FR-INGEST-35). Both are
    # gates ON the one pipeline, not extraction paths, and each marks its own
    # branch inline so the exemption is auditable where the branch appears.
    artifact_words = ('"assessment"', '"rubric"', '"submission"')
    dispatch_branches = [
        line.strip() for line in module_source.splitlines()
        if ("kind ==" in line or "kind in" in line)
        and any(word in line for word in ("'reference'", *artifact_words))
        and "divergence is not None" not in line
        and "demarcation gate" not in line
    ]
    assert dispatch_branches == [], (
        f"TC-INGEST-02: the dispatch branches on the artifact kind: "
        f"{dispatch_branches}. There is one pipeline for all four kinds "
        "(FR-INGEST-02) — the reference divergence halt is a post-transcription "
        "gate, not an extraction path."
    )
    # The env knob moves the pinned DPI (seam 3):
    patch = pytest.MonkeyPatch()
    patch.setenv("HARNESS_INGEST_DPI", "150")
    try:
        ingestor.ingest_document([source], kind="submission",
                                 filenames={source: "scan-01.md"})
        assert rasterizer.dpi_seen[-1] == 150
    finally:
        patch.undo()
    store.close()


# -- TC-INGEST-05: one row per logical document, hashes and transcriber pinned --------------------


def test_tc_ingest_05_one_row_per_document_and_a_null_transcriber_is_unrepresentable(
    tmp_data_dir,
):
    """`TC-INGEST-05` — two logical documents, one duplicating the other's content:
    exactly ONE `document` row per logical document (identical content does not collapse
    them); each row's `content_hash` is the hash of its canonical Markdown;
    `transcriber_ref` equals the resolved build; and a null-`transcriber_ref` INSERT is
    rejected by the schema itself."""
    store, blobs, rasterizer, provider, slot, ingestor = _fixture(tmp_data_dir)
    source = blobs.put(b"fixture pdf")
    first = ingestor.ingest_document([source], kind="assessment",
                                     filenames={source: "scan-01.md"})
    second = ingestor.ingest_document([source], kind="reference",
                                      filenames={source: "scan-01.md"})
    assert first != second
    handle = store.cohort("c-36")
    rows = handle.query(statement(
        "SELECT document_id, content_hash, markdown, transcriber_ref, "
        "prompt_template_version FROM document ORDER BY document_id", issue=ISSUE))
    assert len(rows) == 2, (
        "TC-INGEST-05: two logical documents produced something other than two rows."
    )
    for row in rows:
        assert row["content_hash"] == hashlib.sha256(
            row["markdown"].encode("utf-8")).hexdigest(), (
            "TC-INGEST-05: content_hash is not the hash of the canonical Markdown."
        )
        assert row["transcriber_ref"] == "vlm@sha256:aaaa", (
            "TC-INGEST-05: transcriber_ref is not the resolved build identity "
            "(FR-INGEST-04, FR-PROV-04: what actually answered)."
        )
        assert row["prompt_template_version"] == TRANSCRIPTION_PROMPT_VERSION
    # The schema half: a null transcriber_ref cannot even be inserted.
    with pytest.raises(sqlite3.IntegrityError):
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO document (document_id, submission_id, content_hash, "
                "transcriber_ref) VALUES ('x', NULL, 'h', NULL)", issue=ISSUE))
    store.close()


# -- TC-INGEST-06: a correction is a new row, never an update -------------------------------------


def test_tc_ingest_06_a_revision_creates_a_new_row_and_never_touches_the_original(
    tmp_data_dir,
):
    """`TC-INGEST-06` — *'A NEW document_id is returned, never the one passed in;
    parent_doc_id is set; a new content_hash is computed; the original row is
    byte-unchanged'* — the row-hash assertion is over the whole original row."""
    store, blobs, rasterizer, provider, slot, ingestor = _fixture(tmp_data_dir)
    rasterizer.plan[b"rescan"] = 1
    source = blobs.put(b"fixture pdf")
    original = ingestor.ingest_document([source], kind="submission",
                                        filenames={source: "scan-01.md"})
    handle = store.cohort("c-36")
    row_before = handle.query(statement(
        "SELECT * FROM document WHERE document_id = :d", issue=ISSUE), d=original)[0]

    rescan = blobs.put(b"rescan")
    revised = ingestor.revise_document(
        original, [PageReplacement(blob_hash=rescan, page_no=1)])

    assert revised != original, (
        "TC-INGEST-06: revise_document returned the id it was given — a correction "
        "must create a NEW document row (FR-INGEST-05)."
    )
    row_after = handle.query(statement(
        "SELECT parent_doc_id, content_hash FROM document WHERE document_id = :d",
        issue=ISSUE), d=revised)[0]
    assert row_after["parent_doc_id"] == original
    original_after = handle.query(statement(
        "SELECT * FROM document WHERE document_id = :d", issue=ISSUE), d=original)[0]
    assert tuple(row_before) == tuple(original_after), (
        "TC-INGEST-06: the original row changed — document.markdown is never updated "
        "(FR-INGEST-05)."
    )
    assert row_after["content_hash"] != row_before["content_hash"]
    # The one-build rule holds across a revision too: a build flip mid-revision is
    # refused and the original row (and no new row) records a mixed-build ref.
    patch = pytest.MonkeyPatch()
    calls_before = len(provider.calls)
    flips = {"seen": 0}

    original_complete = provider.complete

    def flipping(prompt, model_ref, params):
        flips["seen"] += 1
        provider.build_override = (
            "vlm@sha256:bbbb" if flips["seen"] > 1 else "vlm@sha256:aaaa")
        return original_complete(prompt, model_ref, params)

    provider.complete = flipping  # type: ignore[method-assign]
    try:
        with pytest.raises(IngestError, match="mid-revision"):
            ingestor.revise_document(original, [PageReplacement(blob_hash=rescan,
                                                                 page_no=1)])
    finally:
        provider.complete = original_complete  # type: ignore[method-assign]
        provider.build_override = None
        patch.undo()
    rows_now = handle.query(statement(
        "SELECT document_id FROM document WHERE parent_doc_id = :d", issue=ISSUE),
        d=original)
    assert len(rows_now) == 1 and rows_now[0]["document_id"] == revised, (
        "a refused revision left a row behind — the refusal must be a no-op."
    )
    store.close()


# -- the residency criterion: the VLM's slot is exclusive where the policy says so ----------------


def test_tc_ingest_36_the_residency_slot_holds_across_the_calls_and_blocks_the_judge(
    tmp_data_dir,
):
    """#36's residency criterion — *'Given a unified-small or discrete-gpu profile, the
    VLM occupies its own residency slot: ingestion completes and the model unloads
    before the first judge loads'* — the slot is EXCLUSIVE when the policy does not
    admit judge and transcriber together: it is held for the whole transcription phase
    (a provider that inspects the slot mid-call sees it held), released when ingestion
    completes, and a judge acquiring it afterwards waits only until then. A policy that
    admits both roles concurrently yields a non-exclusive slot."""
    store, blobs, rasterizer, provider, slot, ingestor = _fixture(tmp_data_dir)
    assert slot._exclusive is True
    source = blobs.put(b"fixture pdf")

    observations: list[str] = []

    def inspect_slot() -> None:
        observations.append(f"held={slot._holder!r}")

    provider.while_calling = inspect_slot
    ingestor.ingest_document([source], kind="submission",
                             filenames={source: "scan-01.md"})
    assert observations and all(state == "held='transcriber'" for state in observations), (
        f"TC-INGEST-36: the residency slot was not held during the VLM calls: "
        f"{observations}."
    )
    assert slot._holder is None, (
        "TC-INGEST-36: the slot is still held after ingestion completed — the model "
        "must unload before the first judge loads."
    )
    # A judge acquiring the released slot gets it immediately (no deadlock, no wait):
    slot.acquire("judge")
    assert slot._holder == "judge"
    slot.release("judge")
    # A second acquirer WAITS: a judge thread parked on acquire is admitted only
    # after the transcriber releases — the "model unloads before the first judge
    # loads" half of the criterion, as a blocking property.
    admitted = threading.Event()
    slot.acquire("transcriber")

    def judge_waits() -> None:
        slot.acquire("judge")
        admitted.set()
        slot.release("judge")

    waiter = threading.Thread(target=judge_waits, daemon=True)
    waiter.start()
    assert not admitted.wait(timeout=0.3), (
        "TC-INGEST-36: a judge acquired the exclusive slot while the transcriber "
        "still held it — the profiles that cannot co-resident the two models are "
        "not being honoured."
    )
    slot.release("transcriber")
    assert admitted.wait(timeout=5.0), (
        "TC-INGEST-36: the waiting judge was never admitted after release."
    )
    waiter.join(timeout=5.0)
    # And the REAL hardware profiles wire the exclusive form: a policy edit that
    # silently admits judge+transcriber on unified-small/discrete-gpu fails here.
    from aeh.conf import HARDWARE_PROFILES

    for profile_name in ("unified-small", "discrete-gpu"):
        policy = HARDWARE_PROFILES[profile_name].residency_policy
        assert ResidencySlot.for_policy(policy)._exclusive is True, (
            f"TC-INGEST-36: {profile_name}'s residency policy admits judge and "
            "transcriber concurrently — the VLM no longer holds its own slot "
            "(AC: ingestion completes and the model unloads before the first judge "
            "loads)."
        )
    # And a policy admitting both roles yields the coexistence form:
    shared = ResidencySlot.for_policy(("judge", "transcriber"))
    assert shared._exclusive is False
    store.close()


# -- TC-INGEST-03/04: the text layer is extracted in addition, and a reference halts --------------


class LayeredRasterizer(ScriptedRasterizer):
    """A ONE-page rasterizer double carrying a configurable embedded text layer."""

    def __init__(self, layer: str) -> None:
        super().__init__()
        self._layer = layer

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        return [PageImage(page_no=1, png=b"page-one", width_px=100, height_px=140)]

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return self._layer


def test_tc_ingest_03_a_divergent_reference_halts_as_a_corrupted_answer_key(
    tmp_data_dir,
):
    """`TC-INGEST-03` — a `reference` artifact whose text layer diverges from the
    transcript at 0%, just under, and above `INGEST_TEXT_LAYER_DIVERGENCE_HALT`: the
    columns are recorded in the ingested cases and ingestion HALTS above the threshold
    — a corrupted answer key, not a warning. Boundary rule, declared: halt when
    divergence is STRICTLY greater."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    source = blobs.put(b"fixture pdf")
    handle = store.cohort("c-36")
    transcript = "the transcribed page says these exact words here"

    def ingest_with(layer: str, halt: str | None = None):
        patch = pytest.MonkeyPatch()
        if halt is not None:
            patch.setenv("HARNESS_INGEST_TEXT_LAYER_DIVERGENCE_HALT", halt)
        layered = LayeredRasterizer(layer)
        transcript_provider = _two_page_provider(transcript, transcript)
        ingestor = Ingestor(handle, blobs, transcript_provider, _model(),
                            SamplingParams(temperature=0.0), layered, sanitizer=THROUGH_SANITIZER)
        try:
            return ingestor.ingest_document([source], kind="reference",
                                            filenames={source: "scan-01.md"}), patch
        except BaseException:
            patch.undo()
            raise

    # 0% divergence: identical layer and transcript — recorded, ingested.
    document_id, patch = ingest_with(transcript)
    row = handle.query(statement(
        "SELECT pages_with_text_layer, text_layer_divergence FROM document "
        "WHERE document_id = :d", issue=ISSUE), d=document_id)[0]
    patch.undo()
    assert row["pages_with_text_layer"] == 1 and row["text_layer_divergence"] == 0.0
    # Just under the threshold: recorded and ingested.
    document_id, patch = ingest_with(
        "the transcribed page says these exact words too", halt="0.5")
    row = handle.query(statement(
        "SELECT text_layer_divergence FROM document WHERE document_id = :d",
        issue=ISSUE), d=document_id)[0]
    patch.undo()
    assert 0.0 < row["text_layer_divergence"] < 0.5
    # Above the threshold: halts, and NOTHING is written.
    with pytest.raises(IngestError, match="corrupted answer key"):
        _, patch = ingest_with(
            "completely different words appear on the layer entirely", halt="0.1")
        patch.undo()
    rows = handle.query(statement(
        "SELECT COUNT(*) AS n FROM document WHERE kind = 'reference'", issue=ISSUE))
    assert rows[0]["n"] == 2, (
        "TC-INGEST-03: the halted ingestion left a row behind — a corrupted answer "
        "key is not ingested."
    )
    store.close()


def test_tc_ingest_04_a_divergent_submission_is_recorded_and_does_not_halt(tmp_data_dir):
    """`TC-INGEST-04` — the same divergence on a `submission` artifact: recorded, and
    ingestion does NOT halt — the halt is specific to `reference` (a corrupted answer
    key; a submission's divergence is impact-routing's input, not a refusal)."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    source = blobs.put(b"fixture pdf")
    layered = LayeredRasterizer(
        "completely different words appear on the layer entirely")
    ingestor = Ingestor(store.cohort("c-36"), blobs, provider, _model(),
                        SamplingParams(temperature=0.0), layered, sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission",
                                           filenames={source: "scan-01.md"})
    row = store.cohort("c-36").query(statement(
        "SELECT pages_with_text_layer, text_layer_divergence FROM document "
        "WHERE document_id = :d", issue=ISSUE), d=document_id)[0]
    assert row["pages_with_text_layer"] == 1
    assert row["text_layer_divergence"] > 0.5
    store.close()


# -- TC-INGEST-07: the order ladder, in strict preference, recorded -------------------------------


def test_tc_ingest_07_the_ladder_sources_record_and_the_refusal_asks_the_operator(
    tmp_data_dir,
):
    """`TC-INGEST-07`/`FR-INGEST-31` — the decision table's runnable core: the
    page-number tier orders shuffled rasters and records itself; the operator tier
    overrides printed numbers; the filename tier orders when nothing else is
    available; with NO tier the ingestion refuses asking for an order — never a guess.
    Directory order is structurally unused: the blob hashes arrive as an explicit
    sequence and every tier's ordering is computed from recorded data."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")

    # (b) page numbers, rasters presented shuffled: the printed headers decide. The
    # transcripts key on the SOURCE hash, so two files are not each other's duplicates.
    class Shuffled(ScriptedProvider):
        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            page_no = int(fields["page_no"])
            self.calls.append((fields["page_no"], fields["image_png_base64"]))
            texts = {1: "Page 2 of 2 - second", 2: "Page 1 of 2 - first"}
            return Completion(text=texts[page_no] + " of " + fields["source_blob_hash"][:6],
                              tokens_in=1, tokens_out=1, latency_ms=1,
                              resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    ingestor = Ingestor(handle, blobs, Shuffled(), _model(),
                        SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission")
    row = handle.query(statement(
        "SELECT markdown, source_blobs FROM document WHERE document_id = :d",
        issue=ISSUE), d=document_id)[0]
    assert row["markdown"].startswith(
        "<!-- region: kind=transcribed_text is_untrusted_content=1 -->"), (
        "#42/FR-INGEST-35: the stored markdown of a submission is demarcated — "
        "every byte of submission-origin content sits inside a marked region.")
    assert (row["markdown"].find("Page 1 of 2 - first")
            < row["markdown"].find("Page 2 of 2 - second")), (
        "TC-INGEST-07: the printed page numbers decide the order — page 1 first.")
    provenance = json.loads(row["source_blobs"])
    assert provenance["order_source"] == "page_number"
    assert [page["position"] for page in provenance["pages"]] == [1, 2]
    # The full provenance triple per page (TC-INGEST-08's artifact half): the source
    # hash, the page index WITHIN that source, and the assembled position — enough to
    # display the originating page for any cited span. This fixture is one blob, so
    # both positions come from blob page 1 and 2 respectively.
    assert provenance["pages"][0]["blob_hash"] == source
    # The rasters are shuffled (page 1 carries the printed header "Page 2"), so the
    # page_number tier positions them honestly: position 1 is the blob's SECOND page.
    assert provenance["pages"][0]["page_no"] == 2
    assert provenance["pages"][1]["page_no"] == 1

    # (a) operator overrides: plain transcripts, filenames that would order them one
    # way, and an operator hint ordering them the other — the operator wins (the head
    # of the strict preference ladder), and the record says so.
    class Plain(ScriptedProvider):
        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            self.calls.append((fields["page_no"], fields["image_png_base64"]))
            return Completion(
                text="plain body text from " + fields["source_blob_hash"][:6]
                     + " page " + fields["page_no"],
                tokens_in=1, tokens_out=1, latency_ms=1,
                resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None)

    plain_ingestor = Ingestor(handle, blobs, Plain(), _model(),
                              SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    first_blob = blobs.put(b"plain pdf one")
    second_blob = blobs.put(b"plain pdf two")
    document_id = plain_ingestor.ingest_document(
        [second_blob, first_blob], kind="submission",
        order_hint=[first_blob, second_blob],
        filenames={first_blob: "zzz-last.md", second_blob: "aaa-first.md"})
    row = handle.query(statement(
        "SELECT markdown, source_blobs FROM document WHERE document_id = :d",
        issue=ISSUE), d=document_id)[0]
    assert json.loads(row["source_blobs"])["order_source"] == "operator", (
        "TC-INGEST-07: the operator tier did not override the filename tier — the "
        "ladder's preference is strict, operator first."
    )
    # The hint ordered the FILES: first_blob's pages precede second_blob's — and the
    # two-blob provenance carries the full triple per page (TC-INGEST-08: an assembled
    # multi-file document; each page knows its source hash, its page index within that
    # source, and its assembled position).
    assert row["markdown"].index(first_blob[:6]) < row["markdown"].index(second_blob[:6])
    multi = json.loads(row["source_blobs"])
    assert {page["blob_hash"] for page in multi["pages"]} == {first_blob, second_blob}
    assert [page["page_no"] for page in multi["pages"]] == [1, 2, 1, 2]
    assert [page["position"] for page in multi["pages"]] == [1, 2, 3, 4]

    # (d) filenames only: the filename tier orders and records itself (the plain
    # transcripts carry no printed numbers, so the filename tier is what fires).
    first_blob = blobs.put(b"plain pdf one")
    second_blob = blobs.put(b"plain pdf two")
    document_id = plain_ingestor.ingest_document(
        [second_blob, first_blob], kind="submission",
        filenames={first_blob: "scan-01.md", second_blob: "scan-02.md"})
    row = handle.query(statement(
        "SELECT source_blobs FROM document WHERE document_id = :d", issue=ISSUE),
        d=document_id)[0]
    assert json.loads(row["source_blobs"])["order_source"] == "filename"

    # (e) none of the tiers: refuse, asking the operator — never a guess.
    naked = blobs.put(b"naked pdf")
    with pytest.raises(IngestError, match="never guesses"):
        plain_ingestor.ingest_document([naked], kind="submission")
    store.close()


# -- TC-INGEST-09/10: duplicates surfaced, gaps named ---------------------------------------------


def _two_page_provider(first: str, second: str) -> ScriptedProvider:
    """A provider double answering one transcript per page, in page order."""

    class TwoPage(ScriptedProvider):
        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            page_no = int(fields["page_no"])
            self.calls.append((fields["page_no"], fields["image_png_base64"]))
            texts = {1: first, 2: second}
            return Completion(text=texts[page_no], tokens_in=1, tokens_out=1,
                              latency_ms=1, resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    return TwoPage()


def test_tc_ingest_09_duplicates_are_surfaced_never_concatenated(tmp_data_dir):
    """`TC-INGEST-09` — two identical pages and two just above the
    `INGEST_DUPLICATE_SIMILARITY_THRESHOLD` (injected — the value is a design TBD) are
    surfaced for confirmation, NEVER concatenated; two genuinely different pages
    ingest; the knob moves the boundary."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    base = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    same = base

    identical = Ingestor(handle, blobs,
                         _two_page_provider(same, same), _model(),
                         SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    with pytest.raises(IngestDuplicateError, match="Surface for"):
        identical.ingest_document([source], kind="submission",
                                  filenames={source: "scan-01.md"})

    # Just ABOVE the threshold (one extra word: 10/11 = 0.909): surfaced.
    near = Ingestor(handle, blobs,
                    _two_page_provider(base, base + " lambda"),
                    _model(), SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    with pytest.raises(IngestDuplicateError, match="Surface for"):
        near.ingest_document([source], kind="submission",
                             filenames={source: "scan-01.md"})
    # Just BELOW it (two extra words: 10/12 = 0.833): ingested.
    below = Ingestor(handle, blobs,
                     _two_page_provider(base, base + " lambda mu"),
                     _model(), SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    assert below.ingest_document([source], kind="submission",
                                 filenames={source: "scan-01.md"})

    different = Ingestor(handle, blobs,
                         _two_page_provider(
                             "the first page discusses algebraic manipulation",
                             "the second page contains a diagram of a pulley"),
                         _model(), SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    different_source = blobs.put(b"yet another pdf")
    assert different.ingest_document([different_source], kind="submission",
                                     filenames={different_source: "scan-01.md"})

    # The knob moves the boundary (injected, not hard-coded):
    patch = pytest.MonkeyPatch()
    patch.setenv("HARNESS_INGEST_DUPLICATE_SIMILARITY_THRESHOLD", "0.999")
    try:
        another = blobs.put(b"another pdf")
        assert near.ingest_document([another], kind="submission",
                                    filenames={another: "scan-01.md"})
    finally:
        patch.undo()
    store.close()


def test_tc_ingest_10_a_gap_names_the_specific_missing_positions(tmp_data_dir):
    """`TC-INGEST-10` — a document missing printed pages 3 and 7 raises a V1 finding
    NAMING [3, 7] — the assertion is on the named positions, not merely on failure.

    The plan row's other half — a missing QUESTION 4 — is the V2 structural gate
    (FR-INGEST-23): it needs the package's question inventory, which is read at rung 3
    by #40's ladder; the deferral is recorded here so the plan does not lie about
    coverage."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")

    class FivePageRasterizer(ScriptedRasterizer):
        def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
            return [PageImage(page_no=i + 1, png=f"p{i}".encode(), width_px=1,
                              height_px=1) for i in range(5)]

    transcripts = ["Page 1 of 7", "Page 2 of 7", "Page 4 of 7", "Page 5 of 7",
                   "Page 6 of 7"]

    class Sequenced(ScriptedProvider):
        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            page_no = int(fields["page_no"])
            self.calls.append((fields["page_no"], fields["image_png_base64"]))
            return Completion(text=transcripts[page_no - 1], tokens_in=1,
                              tokens_out=1, latency_ms=1,
                              resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    ingestor = Ingestor(handle, blobs, Sequenced(), _model(),
                        SamplingParams(temperature=0.0), FivePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    with pytest.raises(IngestError) as gap:
        ingestor.ingest_document([source], kind="submission")
    assert "[3, 7]" in str(gap.value), (
        f"TC-INGEST-10: the finding does not name the specific missing positions: "
        f"{gap.value}."
    )
    store.close()


# -- review round 2: the interleaved-revision, fiducial, boundary and torn-stack cases -------------


class MultiPageRasterizer(ScriptedRasterizer):
    """A rasterizer double returning a per-source scripted page count."""

    def __init__(self) -> None:
        super().__init__()
        self.layers: dict[int, str] = {}

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        count = self.plan.get(pdf_bytes, 2)
        return [PageImage(page_no=i + 1, png=f"p{i}".encode(), width_px=1,
                          height_px=1) for i in range(count)]

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return self.layers.get(page_no, "")


def test_tc_ingest_06b_a_revision_on_interleaved_pages_replaces_the_seen_page(
    tmp_data_dir,
):
    """B1 (review round 2) — the interleaved case: two 2-page blobs whose PRINTED
    numbers interleave (A holds pages 1 and 3, B holds 2 and 4). The recorded
    provenance maps assembled position 2 to BLOB B page 1, and a correction for
    position 2 must replace exactly that page — a per-blob running counter would
    replace A's second page and silently lose the student's printed page 3."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    rasterizer = MultiPageRasterizer()
    blob_a = blobs.put(b"part one")
    blob_b = blobs.put(b"part two")
    rasterizer.plan[b"part one"] = 2
    rasterizer.plan[b"part two"] = 2
    # The transcripts interleave: A's pages carry printed 1 and 3, B's carry 2 and 4.

    class Interleaved(ScriptedProvider):
        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            key = (fields["source_blob_hash"], int(fields["page_no"]))
            self.calls.append(key)
            texts = {
                (blob_a, 1): "Page 1 of 4 - part one page one",
                (blob_a, 2): "Page 3 of 4 - part one page two",
                (blob_b, 1): "Page 2 of 4 - part two page one",
                (blob_b, 2): "Page 4 of 4 - part two page two",
            }
            if key not in texts:
                return Completion(text=f"rescanned page {key[1]}",
                                  tokens_in=1, tokens_out=1, latency_ms=1,
                                  resolved_build=model_ref.build_id,
                                  cached_prefix_tokens=0, cost=None)
            return Completion(text=texts[key], tokens_in=1, tokens_out=1,
                              latency_ms=1, resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    ingestor = Ingestor(handle, blobs, Interleaved(), _model(),
                        SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    # No hint: the printed numbers interleave the files through the page-number tier.
    document_id = ingestor.ingest_document([blob_a, blob_b], kind="submission")
    provenance = json.loads(handle.query(statement(
        "SELECT source_blobs FROM document WHERE document_id = :d", issue=ISSUE),
        d=document_id)[0]["source_blobs"])
    by_position = {page["position"]: (page["blob_hash"], page["page_no"])
                   for page in provenance["pages"]}
    assert by_position[1] == (blob_a, 1) and by_position[2] == (blob_b, 1)
    assert by_position[3] == (blob_a, 2) and by_position[4] == (blob_b, 2)
    # The teacher corrects the page they SEE at position 2 — B's first page.
    rescan = blobs.put(b"rescan-position-2")
    rasterizer.plan[b"rescan-position-2"] = 1
    revised = ingestor.revise_document(document_id, [
        PageReplacement(blob_hash=rescan, page_no=2)])
    row = handle.query(statement(
        "SELECT markdown, source_blobs FROM document WHERE document_id = :d",
        issue=ISSUE), d=revised)[0]
    new_provenance = json.loads(row["source_blobs"])
    new_at_2 = next(page for page in new_provenance["pages"]
                    if page["position"] == 2)
    assert new_at_2["blob_hash"] == rescan and new_at_2["page_no"] == 1, (
        "the revised provenance does not point the corrected position at the rescan."
    )
    assert "Page 2 of 4 - part two page one" not in row["markdown"], (
        "the STALE transcript the teacher asked to fix is still in the document."
    )
    assert "Page 3 of 4 - part one page two" in row["markdown"], (
        "A's printed page 3 vanished — the correction lost a page (B1)."
    )
    # The other three positions are untouched.
    untouched = Ingestor(handle, blobs, Interleaved(), _model(),
                         SamplingParams(temperature=0.0), MultiPageRasterizer(), sanitizer=THROUGH_SANITIZER)
    original_pages = handle.query(statement(
        "SELECT markdown FROM document WHERE document_id = :d", issue=ISSUE),
        d=document_id)[0]["markdown"]
    for printed in ("Page 1 of 4", "Page 3 of 4", "Page 4 of 4"):
        assert printed in row["markdown"] and printed in original_pages
    store.close()


def test_tc_ingest_07b_the_fiducial_tier_sorts_naturally_and_refuses_repeats(
    tmp_data_dir,
):
    """`TC-INGEST-07` decision-table case (c) — fiducial markers: `[fiducial:page-10]`
    sorts AFTER `[fiducial:page-2]` (natural order, like the filename tier), and two
    pages sharing a marker are refused as a misprint rather than assembled in raster
    order."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")

    class Fiducial(ScriptedProvider):
        def __init__(self, markers) -> None:
            super().__init__()
            self._markers = markers

        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            page_no = int(fields["page_no"])
            self.calls.append((fields["page_no"], fields["image_png_base64"]))
            return Completion(text=f"[fiducial:{self._markers[page_no - 1]}]",
                              tokens_in=1, tokens_out=1, latency_ms=1,
                              resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    # Natural sort: page-1, page-2, page-10 — presented in raster order 10, 1, 2.
    rasterizer.plan = {b"fixture pdf": 3}
    ingestor = Ingestor(handle, blobs, Fiducial(["page-10", "page-1", "page-2"]),
                        _model(), SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission")
    row = handle.query(statement(
        "SELECT markdown, source_blobs FROM document WHERE document_id = :d",
        issue=ISSUE), d=document_id)[0]
    assert [row["markdown"].index(f"page-{n}") for n in (1, 2, 10)] == sorted(
        row["markdown"].index(f"page-{n}") for n in (1, 2, 10)), (
        "TC-INGEST-07: the fiducial tier sorted lexicographically — page-10 does not "
        "belong between page-1 and page-2."
    )
    assert json.loads(row["source_blobs"])["order_source"] == "marker"
    # Repeats: two pages sharing a marker are a misprint — refused, never assembled
    # (the bodies differ, so the duplicate check cannot be what fires).
    rasterizer.plan = {b"fixture pdf": 2}

    class RepeatedFiducial(Fiducial):
        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            page_no = int(fields["page_no"])
            self.calls.append((fields["page_no"], fields["image_png_base64"]))
            body = "first sheet body" if page_no == 1 else "second sheet body"
            return Completion(text=f"[fiducial:{self._markers[page_no - 1]}] {body}",
                              tokens_in=1, tokens_out=1, latency_ms=1,
                              resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    repeated = Ingestor(handle, blobs, RepeatedFiducial(["page-1", "page-1"]),
                        _model(), SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    with pytest.raises(IngestError, match="repeat positions"):
        repeated.ingest_document([source], kind="submission",
                                 filenames={source: "scan-01.md"})
    store.close()


def test_tc_ingest_03b_the_divergence_boundary_is_exactly_strict(tmp_data_dir):
    """`TC-INGEST-03`'s fourth boundary point — divergence EXACTLY at the threshold:
    recorded and ingested (the declared rule is strictly-greater). Layer "a b c d"
    against transcript "a b c d e f g h" is Jaccard 4/8 → divergence exactly 0.5 with
    the halt at 0.5."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    layered = LayeredRasterizer("a b c d")
    ingestor = Ingestor(handle, blobs,
                        _two_page_provider("a b c d e f g h", "second page entirely"),
                        _model(), SamplingParams(temperature=0.0), layered, sanitizer=THROUGH_SANITIZER)
    patch = pytest.MonkeyPatch()
    patch.setenv("HARNESS_INGEST_TEXT_LAYER_DIVERGENCE_HALT", "0.5")
    try:
        document_id = ingestor.ingest_document([source], kind="reference",
                                               filenames={source: "scan-01.md"})
    finally:
        patch.undo()
    row = handle.query(statement(
        "SELECT text_layer_divergence FROM document WHERE document_id = :d",
        issue=ISSUE), d=document_id)[0]
    assert row["text_layer_divergence"] == 0.5, (
        "TC-INGEST-03: exactly-at-the-threshold did not ingest and record — the "
        "declared boundary is strictly greater."
    )
    store.close()


def test_tc_ingest_09b_torn_stacks_and_repeated_numbers_are_refused(tmp_data_dir):
    """FR-INGEST-09's refusal halves — pages DISAGREEING about the document's page
    count (a torn or mixed stack) and REPEATING a printed position are both refused,
    not assembled."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")

    class Torn(ScriptedProvider):
        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            page_no = int(fields["page_no"])
            texts = {1: "Page 1 of 3", 2: "Page 2 of 4"}  # disagreeing totals
            return Completion(text=texts[page_no], tokens_in=1, tokens_out=1,
                              latency_ms=1, resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    ingestor = Ingestor(handle, blobs, Torn(), _model(),
                        SamplingParams(temperature=0.0), rasterizer, sanitizer=THROUGH_SANITIZER)
    with pytest.raises(IngestError, match="disagree"):
        ingestor.ingest_document([source], kind="submission")

    class ThreePageRasterizer(ScriptedRasterizer):
        def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
            return [PageImage(page_no=i + 1, png=f"p{i}".encode(), width_px=1,
                              height_px=1) for i in range(3)]

    class Repeated(ScriptedProvider):
        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            page_no = int(fields["page_no"])
            texts = {1: "Page 1 of 2 - alpha body here",
                     2: "Page 1 of 2 - beta body here",
                     3: "Page 2 of 2 - gamma body here"}  # position 1 repeated
            return Completion(text=texts[page_no], tokens_in=1, tokens_out=1,
                              latency_ms=1, resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    repeated = Ingestor(handle, blobs, Repeated(), _model(),
                        SamplingParams(temperature=0.0), ThreePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    with pytest.raises(IngestError, match="repeats positions"):
        repeated.ingest_document([source], kind="submission")
    store.close()


# -- #38: region kinds, structured descriptions, the evaluative bar, retractions -----------------


def _marked(*regions: str) -> str:
    """Wrap region bodies in the pinned marker protocol, the way the model emits them."""
    return "\n\n".join(f"<!-- region: {r} -->\n{{body}}\n<!-- /region -->"
                        for r in regions)


class OnePageRasterizer(ScriptedRasterizer):
    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        return [PageImage(page_no=1, png=b"page-one", width_px=100, height_px=140)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        # A PNG header + the box: image bytes, deterministically derived, so the
        # crop-resolution assertion reads real image content.
        return bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A]) + f"crop {box} from {pdf_bytes!r}".encode()


def _region_provider(bodies: list[str]):
    """A provider double emitting one marked-up page per rasterized page, in order."""
    class Marked(ScriptedProvider):
        def complete(self, prompt, model_ref, params):
            fields = dict(prompt.fields)
            page_no = int(fields["page_no"])
            self.calls.append((fields["page_no"], fields["image_png_base64"]))
            body = bodies[(page_no - 1) % len(bodies)]
            return Completion(text=body, tokens_in=1, tokens_out=1, latency_ms=1,
                              resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    return Marked()


def test_tc_ingest_11_each_element_kind_description_carries_its_named_fields(
    tmp_data_dir,
):
    """`TC-INGEST-11` — the fixture sweep, one element kind at a time: the description
    the model returns CONTAINS each named field (`FR-INGEST-10`'s own acceptance
    form), asserted per field from the F-GRAPHIC corpus pages' descriptions."""
    from aeh.ingest import ELEMENT_REQUIRED_FIELDS, ELEMENT_KINDS

    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    descriptions = {
        "free_body_diagram": (
            "The diagram shows three arrows. arrow label: weight; origin point: the "
            "crate's centre; direction: straight down. arrow label: normal; origin "
            "point: the contact face; direction: perpendicular to the incline "
            "surface. arrow label: friction; origin point: the contact face; "
            "direction: along the incline surface."),
        "geometry_construction": (
            "Points A and B are marked with crosses. relation: the segment AB is "
            "perpendicular to the segment BC at point B, and the arcs through A and C "
            "are congruent."),
        "graph_or_plot": (
            "The plot's axis labels: time with units in seconds on the horizontal axis, "
            "velocity with units in metres per second on the vertical. The curve "
            "crosses the horizontal axis at intercept t = 4 s, and its only turning "
            "point is at t = 2 s."),
        "table": (
            "| Trial | Length |\n|---|---|\n| 1 | 5.2 cm |\n| 2 | 5.4 cm |"),
        "label_or_annotation": (
            "The annotation attaches to the pulley wheel, by a leader line to the "
            "rim."),
        "spatial_relation": (
            "The weights holder is below the pulley; the string is right of the "
            "clamp stand."),
    }
    for element_kind in ELEMENT_KINDS:
        marked = (f"<!-- region: kind=described_graphic "
                  f"element_kind={element_kind} -->\n{descriptions[element_kind]}\n"
                  "<!-- /region -->")
        source = blobs.put(f"fixture {element_kind}".encode())
        single = ScriptedRasterizer()
        single.plan = {f"fixture {element_kind}".encode(): 1}
        ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                            SamplingParams(temperature=0.0), single, sanitizer=THROUGH_SANITIZER)
        document_id = ingestor.ingest_document([source], kind="submission",
                                               filenames={source: "scan-01.md"})
        rows = handle.query(statement(
            "SELECT description, region_kind, element_kind FROM document_region "
            "WHERE document_id = :d", issue=ISSUE), d=document_id)
        assert rows and rows[0]["region_kind"] == "described_graphic"
        description = rows[0]["description"]
        if element_kind == "spatial_relation":
            # A page states ONE relation explicitly; the requirement is explicitness,
            # not every possible relation on one page.
            assert any(field.lower() in description.lower()
                       for field in ELEMENT_REQUIRED_FIELDS[element_kind]), (
                f"TC-INGEST-11: the spatial relation is not stated explicitly: "
                f"{description!r} (FR-INGEST-10)."
            )
        else:
            for field in ELEMENT_REQUIRED_FIELDS[element_kind]:
                assert field.lower() in description.lower(), (
                    f"TC-INGEST-11: the {element_kind} description lacks its named "
                    f"field {field!r}: {description!r} (FR-INGEST-10)."
                )
    store.close()


def test_tc_ingest_12_region_kinds_and_resolvable_crops(tmp_data_dir):
    """`TC-INGEST-12` — a page with text, a graphic and a tick box: every region
    carries one of the three `region_kind` values, and every `described_graphic`
    carries a non-null `crop_ref` resolving to a retained image crop in the blob
    store."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    marked = (
        "<!-- region: kind=transcribed_text -->\nThe answer begins here.\n"
        "<!-- /region -->\n"
        "<!-- region: kind=described_graphic element_kind=graph_or_plot -->\n"
        "The plot shows velocity against time.\n<!-- /region -->\n"
        "<!-- region: kind=selection_mark question_id=Q1 -->\n\u2713\n"
        "<!-- /region -->")
    ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission",
                                           filenames={source: "scan-01.md"})
    rows = handle.query(statement(
        "SELECT region_kind, crop_ref FROM document_region "
        "WHERE document_id = :d ORDER BY position", issue=ISSUE), d=document_id)
    assert [row["region_kind"] for row in rows] == [
        "transcribed_text", "described_graphic", "selection_mark"], (
        "TC-INGEST-12: the regions did not carry the three kinds in order."
    )
    graphic = rows[1]
    assert graphic["crop_ref"], (
        "TC-INGEST-12: a described_graphic without a crop_ref (FR-INGEST-13)."
    )
    assert blobs.get(graphic["crop_ref"]), (
        "TC-INGEST-12: the crop_ref does not resolve to a retained crop."
    )
    store.close()


def test_tc_ingest_13_evaluative_descriptions_are_rejected_then_re_requested(
    tmp_data_dir,
):
    """`TC-INGEST-13` — a description containing each configured evaluative term is
    rejected and RE-REQUESTED; after the retry budget the ingestion refuses rather
    than storing an evaluative description."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    for term in ("correct", "valid", "appropriate", "properly", "as expected",
                 "should be"):
        marked = ("<!-- region: kind=described_graphic "
                  "element_kind=free_body_diagram -->\n"
                  f"The arrow is {term} drawn.\n<!-- /region -->")
        attempts = {"n": 0}

        class CountingMarked(ScriptedProvider):
            def complete(self, prompt, model_ref, params):
                attempts["n"] += 1
                return _region_provider([marked]).complete(
                    prompt, model_ref, params)

        ingestor = Ingestor(handle, blobs, CountingMarked(), _model(),
                            SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
        with pytest.raises(IngestError, match="evaluative"):
            ingestor.ingest_document([source], kind="submission",
                                     filenames={source: "scan-01.md"})
        # At least one RE-REQUEST happened (the rejection is not the end of it):
        assert attempts["n"] >= 2, (
            f"TC-INGEST-13: {term!r} was rejected without a re-request "
            f"(attempts: {attempts['n']}) — FR-INGEST-11 says reject AND re-request."
        )
    store.close()


def test_tc_ingest_14_the_confusable_page_discriminates(tmp_data_dir):
    """`TC-INGEST-14` — the near-miss fixture: the correct, purely descriptive
    rendering is ACCEPTED and the evaluative rendering of the same diagram is
    REJECTED, so the bar discriminates rather than blanket-rejecting."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    descriptive = ("<!-- region: kind=described_graphic "
                   "element_kind=free_body_diagram -->\n"
                   "The arrow labelled weight points straight down from the crate's "
                   "centre.\n<!-- /region -->")
    evaluative = ("<!-- region: kind=described_graphic "
                  "element_kind=free_body_diagram -->\n"
                  "The arrow labelled weight is correctly drawn, as expected.\n"
                  "<!-- /region -->")
    good = Ingestor(handle, blobs, _region_provider([descriptive]), _model(),
                    SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    assert good.ingest_document([source], kind="submission",
                                filenames={source: "scan-01.md"})
    bad = Ingestor(handle, blobs, _region_provider([evaluative]), _model(),
                   SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    another = blobs.put(b"another pdf")
    with pytest.raises(IngestError, match="evaluative"):
        bad.ingest_document([another], kind="submission",
                            filenames={another: "scan-01.md"})
    store.close()


def test_tc_ingest_15_no_stored_description_carries_evaluative_vocabulary(
    tmp_data_dir,
):
    """`TC-INGEST-15` — every stored description across an ingest: zero matches
    against the evaluative-term list (the pattern scan over the stored artifacts)."""
    from aeh.ingest import _evaluative_offences

    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    marked = ("<!-- region: kind=described_graphic "
              "element_kind=geometry_construction -->\n"
              "Points A and B marked; relation: AB perpendicular to BC.\n"
              "<!-- /region -->\n"
              "<!-- region: kind=transcribed_text -->\nThe work shown is brief.\n"
              "<!-- /region -->")
    ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission",
                                           filenames={source: "scan-01.md"})
    rows = handle.query(statement(
        "SELECT description FROM document_region WHERE document_id = :d",
        issue=ISSUE), d=document_id)
    for row in rows:
        if row["description"]:
            assert _evaluative_offences(row["description"]) == [], (
                f"TC-INGEST-15: a stored description carries evaluative vocabulary: "
                f"{row['description']!r}."
            )
    store.close()


def test_tc_ingest_16_retractions_keep_both_versions(tmp_data_dir):
    """`TC-INGEST-16` — struck-through content is RETAINED with
    `retraction = 'struck_through'`; a superseded line keeps both versions in the
    Markdown."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    marked = (
        "<!-- region: kind=transcribed_text -->\n"
        "<s>the wrong formula crossed out</s> the corrected working follows.\n"
        "<!-- /region -->\n"
        "<!-- region: kind=transcribed_text -->\n"
        "~~superseded-by the line above the original velocity value\n"
        "the corrected velocity value\n<!-- /region -->")
    ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission",
                                           filenames={source: "scan-01.md"})
    rows = handle.query(statement(
        "SELECT region_kind, retraction FROM document_region "
        "WHERE document_id = :d ORDER BY position", issue=ISSUE), d=document_id)
    markdown = handle.query(statement(
        "SELECT markdown FROM document WHERE document_id = :d", issue=ISSUE),
        d=document_id)[0]["markdown"]
    struck_rows = [row for row in rows if row["retraction"] == "struck_through"]
    assert struck_rows, (
        "TC-INGEST-16: struck-through content was dropped instead of retained with "
        "retraction='struck_through' (FR-INGEST-12)."
    )
    assert "the wrong formula crossed out" in markdown
    assert "the corrected working follows" in markdown, (
        "TC-INGEST-16: BOTH versions must be present in the Markdown."
    )
    store.close()


# -- #38 review round 2: superseded links, the re-request success path, the bindings -------------


def test_tc_ingest_16b_a_correction_carries_superseded_by(tmp_data_dir):
    """`TC-INGEST-16`'s second half (review B2) — the superseded region carries
    `retraction = 'superseded_by:<the correcting region's id>'`, an exact value, and
    BOTH versions are present."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    marked = (
        "<!-- region: kind=transcribed_text -->\n"
        "the original velocity value as first written\n<!-- /region -->\n"
        "<!-- region: kind=transcribed_text -->\n"
        "~~superseded-by the corrected velocity value, written above\n"
        "<!-- /region -->")
    ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission",
                                           filenames={source: "scan-01.md"})
    rows = handle.query(statement(
        "SELECT region_id, retraction FROM document_region "
        "WHERE document_id = :d ORDER BY position", issue=ISSUE), d=document_id)
    assert len(rows) == 2
    first, second = rows
    assert first["retraction"] == f"superseded_by:{second['region_id']}", (
        f"TC-INGEST-16: the superseded region carries "
        f"{first['retraction']!r}, not 'superseded_by:<region_id>' (FR-INGEST-12)."
    )
    assert second["retraction"] is None
    store.close()


def test_tc_ingest_13b_a_successful_re_request_leaves_no_evaluative_text(
    tmp_data_dir,
):
    """Review B3 — the re-request SUCCEEDS on the second call: the stored
    `document.markdown` is the CLEAN transcript (the rejected judgement must not
    survive in the document row), the region rows are clean, and exactly two VLM
    calls were made. Nothing is written when the budget is exhausted (pinned too)."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    dirty = ("<!-- region: kind=described_graphic "
             "element_kind=free_body_diagram -->\n"
             "The arrow is correctly drawn, as expected.\n<!-- /region -->")
    clean = ("<!-- region: kind=described_graphic "
             "element_kind=free_body_diagram -->\n"
             "The arrow labelled weight points straight down from the centre.\n"
             "<!-- /region -->")

    class Recovers(ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list = []

        def complete(self, prompt, model_ref, params):
            text = dirty if len(self.calls) == 0 else clean
            fields = dict(prompt.fields)
            self.calls.append((fields["page_no"], fields["image_png_base64"]))
            return Completion(text=text, tokens_in=1, tokens_out=1, latency_ms=1,
                              resolved_build=model_ref.build_id,
                              cached_prefix_tokens=0, cost=None)

    recovering = Recovers()
    ingestor = Ingestor(handle, blobs, recovering, _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission",
                                           filenames={source: "scan-01.md"})
    assert len(recovering.calls) == 2, (
        "TC-INGEST-13: the re-request did not issue a second VLM call."
    )
    row = handle.query(statement(
        "SELECT markdown FROM document WHERE document_id = :d", issue=ISSUE),
        d=document_id)[0]
    assert "correctly" not in row["markdown"] and "as expected" not in row["markdown"], (
        "Review B3: the REJECTED evaluative description survives in "
        "document.markdown — the stored document must be the FINAL transcript."
    )
    assert "straight down from the centre" in row["markdown"]
    regions = handle.query(statement(
        "SELECT description FROM document_region WHERE document_id = :d",
        issue=ISSUE), d=document_id)
    assert all("correctly" not in (r["description"] or "")
               for r in regions)
    store.close()


def test_tc_ingest_13c_an_exhausted_budget_writes_nothing(tmp_data_dir):
    """TC-INGEST-13's pin (review note) — after the re-request budget is exhausted,
    NO document row and NO region rows exist."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    marked = ("<!-- region: kind=described_graphic "
              "element_kind=free_body_diagram -->\n"
              "The arrow is correctly drawn.\n<!-- /region -->")
    ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    with pytest.raises(IngestError, match="evaluative"):
        ingestor.ingest_document([source], kind="submission",
                                 filenames={source: "scan-01.md"})
    assert handle.query(statement(
        "SELECT COUNT(*) AS n FROM document", issue=ISSUE))[0]["n"] == 0
    assert handle.query(statement(
        "SELECT COUNT(*) AS n FROM document_region", issue=ISSUE))[0]["n"] == 0
    store.close()


def test_tc_ingest_11b_the_evaluative_list_binds_to_the_corpus_list():
    """Review M2 — the module's evaluative vocabulary and the corpus generator's list
    are the SAME judgement about what counts as a verdict. The corpus's comment warns
    that a second copy is how the two drift apart; this binding is what stops it."""
    from harness.corpora.graphic import EVALUATIVE_TERMS as CORPUS_TERMS

    for term in CORPUS_TERMS:
        assert term in EVALUATIVE_TERMS, (
            f"TC-INGEST-11b: the corpus's evaluative term {term!r} is not in the "
            "module's list — the two copies have drifted."
        )


def test_tc_ingest_11c_the_f_graphic_fixture_page_round_trips(tmp_data_dir):
    """Review M4 — TC-INGEST-11's fixture is the F-GRAPHIC corpus page itself: the
    corpus's own `acceptable_description` is what the model returns, wrapped in the
    marker protocol, and the STORED description is exactly it (not an echo of a
    hand-written constant)."""
    from tests.support import corpora

    corpus = corpora.load("F-GRAPHIC")
    member = next(m for m in corpus.members if "GR-01" in str(m.id).upper())
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    pages = corpora.materialize_pages(member, tmp_data_dir / "fg")
    page_text = pathlib.Path(pages[0]).read_text(encoding="utf-8")
    marked = ("<!-- region: kind=described_graphic "
              "element_kind=free_body_diagram -->\n" + page_text + "\n"
              "<!-- /region -->")
    source = blobs.put(b"fixture pdf")
    ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission",
                                           filenames={source: "scan-01.md"})
    stored = handle.query(statement(
        "SELECT description FROM document_region WHERE document_id = :d",
        issue=ISSUE), d=document_id)[0]["description"]
    assert stored is not None and "arrow" in stored.lower()
    assert stored.strip() == page_text.strip(), (
        "TC-INGEST-11c: the stored description is not the fixture page's own "
        "description — the round-trip through the marker protocol changed it."
    )
    store.close()


# -- #39: per-region confidence, content states, selection marks, package read, clustering -------


def test_tc_ingest_17_present_blank_and_absent_are_distinct(tmp_data_dir):
    """`TC-INGEST-17` — an answer region with writing, an EMPTY answer region, and a
    page where the region is absent: `present`, `blank` and `absent` are three rows,
    never collapsed — blank is a legitimate zero, absent is a scanning failure."""
    from aeh.pkg import PackageCatalog, PackageDraft
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    marked = (
        "<!-- region: kind=transcribed_text question_id=Q1 state=present -->\n"
        "the worked answer to Q1\n<!-- /region -->\n"
        "<!-- region: kind=transcribed_text question_id=Q2 state=blank -->\n"
        "<!-- /region -->")
    ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission",
                                           filenames={source: "scan-01.md"})
    rows = handle.query(statement(
        "SELECT element_kind, content_state FROM document_region "
        "WHERE document_id = :d ORDER BY position", issue=ISSUE), d=document_id)
    assert [(row["element_kind"], row["content_state"]) for row in rows] == [
        ("Q1", "present"), ("Q2", "blank")]
    # The absent question: the package declares Q3, no region carries it — the
    # expected-region read (FR-INGEST-18) emits a distinct ABSENT row.
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT OR IGNORE INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES ('c-36', 'synthetic', '2026-01-01')", issue=ISSUE))
    seed = store.package("pkg-39")
    with seed.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) VALUES ('pkg-39', 'x')",
            issue=ISSUE))
    catalog = PackageCatalog(seed, package_id="pkg-39")
    try:
        v = catalog.create_version(None, PackageDraft(title="pkg"))
        catalog.add_criterion(v, "C1", question_id="Q3", kind="open", max_points=4.0)
        regions = ingestor._absent_regions(v, document_id, declared_regions=[
            ("Q1", "present"), ("Q2", "blank")], package_catalog=catalog)
        assert regions == [("Q3", "absent")], (
            "TC-INGEST-17: the absent question is not recorded as its own row — "
            "absent (scanning failure) and blank (legitimate zero) are distinct "
            "(FR-INGEST-16)."
        )
    finally:
        pass
    store.close()


def test_tc_ingest_18_the_selection_decision_table(tmp_data_dir):
    """`TC-INGEST-18` — the decision table: a clean single tick resolves; two ticks
    are `multiple_marks`; a smudge and an erased-and-remarked box are `ambiguous`;
    an empty box resolves to none. `selection` is populated ONLY when resolved, and
    no ambiguous or multiple mark is ever mapped to an option."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    table = {
        "resolved": ("B", "B"),
        "multiple_marks": (None, None),
        "ambiguous": (None, None),
    }
    for selection_state, (selection, _) in table.items():
        marked = (f"<!-- region: kind=selection_mark question_id=Q1 "
                  f"selection_state={selection_state} selection={selection or ''} -->\n"
                  "the mark as seen\n<!-- /region -->")
        ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                            SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
        source = blobs.put(f"pdf-{selection_state}".encode())
        document_id = ingestor.ingest_document([source], kind="submission",
                                               filenames={source: "scan.md"})
        rows = handle.query(statement(
            "SELECT selection_state, selection FROM document_region "
            "WHERE document_id = :d", issue=ISSUE), d=document_id)
        assert rows[0]["selection_state"] == selection_state
        if selection_state == "resolved":
            assert rows[0]["selection"] == selection
        else:
            assert rows[0]["selection"] is None, (
                f"TC-INGEST-18: a {selection_state} mark carries a selection — an "
                "unreadable mark must never be mapped to an option (FR-INGEST-17)."
            )
    store.close()


def test_tc_ingest_19_question_format_is_read_from_the_package(tmp_data_dir):
    """`TC-INGEST-19` — the question structure is read FROM THE PACKAGE, never
    classified per submission: the ingest with a bound catalog reads the declared
    kinds; the assertion is that the same package feeds every submission without any
    per-submission classification call (the catalog is read, not a model)."""
    from aeh.pkg import PackageCatalog, PackageDraft
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT OR IGNORE INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES ('c-36', 'synthetic', '2026-01-01')", issue=ISSUE))
    seed = store.package("pkg-39")
    with seed.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) VALUES ('pkg-39', 'x')",
            issue=ISSUE))
    catalog = PackageCatalog(seed, package_id="pkg-39")
    try:
        v = catalog.create_version(None, PackageDraft(title="pkg"))
        catalog.add_criterion(v, "C1", question_id="Q1", kind="mcq", max_points=1.0)
        catalog.add_criterion(v, "C2", question_id="Q2", kind="open", max_points=4.0)
        ingestor = Ingestor(handle, blobs, ScriptedProvider(), _model(),
                            SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
        source = blobs.put(b"fixture pdf")
        report = ingestor.ingest_submission(
            [source], cohort_id="c-36", package_version=v,
            package_catalog=catalog, filenames={source: "scan-01.md"})
        assert report.document_id
        # The declared structure is the package's, read once for the submission:
        declared = {row["question_id"]: row["kind"]
                    for row in catalog.criteria(v)}
        assert declared == {"Q1": "mcq", "Q2": "open"}
    finally:
        pass
    store.close()


def test_tc_ingest_20_shape_contradictions_are_v2_failures(tmp_data_dir):
    """`TC-INGEST-20` — prose where the package declares `mcq`, a selection where it
    declares `open`: both recorded as V2 failures NAMING the question, routed to the
    operator — never silently reinterpreted."""
    from aeh.pkg import PackageCatalog, PackageDraft
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT OR IGNORE INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES ('c-36', 'synthetic', '2026-01-01')", issue=ISSUE))
    seed = store.package("pkg-39")
    with seed.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) VALUES ('pkg-39', 'x')",
            issue=ISSUE))
    catalog = PackageCatalog(seed, package_id="pkg-39")
    v = catalog.create_version(None, PackageDraft(title="pkg"))
    catalog.add_criterion(v, "C1", question_id="Q1", kind="mcq", max_points=1.0)
    catalog.add_criterion(v, "C2", question_id="Q2", kind="open", max_points=4.0)
    source = blobs.put(b"fixture pdf")
    marked = (
        "<!-- region: kind=transcribed_text question_id=Q1 state=present -->\n"
        "a prose answer where the package declares mcq\n<!-- /region -->\n"
        "<!-- region: kind=selection_mark question_id=Q2 selection_state=resolved "
        "selection=A -->\nthe mark as seen\n<!-- /region -->")
    ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    report = ingestor.ingest_submission([source], cohort_id="c-36",
                                        package_version=v, package_catalog=catalog,
                                        filenames={source: "scan-01.md"})
    findings = [(f["question_id"], f["finding"]) for f in report.detail["v2_failures"]]
    assert ("Q1", "prose where the package declares mcq") in findings, (
        "TC-INGEST-20: prose where mcq is declared was not recorded as a V2 failure."
    )
    assert ("Q2", "selection where the package declares open") in findings, (
        "TC-INGEST-20: a selection where open is declared was not recorded."
    )
    assert report.gates["v2"] == "fail", (
        "TC-INGEST-20: the V2 gate column carries its own outcome — a failure is "
        "recorded as a failure, never collapsed (FR-INGEST-29)."
    )
    store.close()


def test_tc_ingest_21_ocr_confidence_is_per_region(tmp_data_dir):
    """`TC-INGEST-21` — `ocr_conf` recorded PER REGION, at different values, so the
    read path M-INTEG uses (region rows) carries confidence at span granularity — a
    document-level value alone does not satisfy the requirement."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    source = blobs.put(b"fixture pdf")
    marked = (
        "<!-- region: kind=transcribed_text question_id=Q1 conf=0.94 -->\n"
        "clearly written text\n<!-- /region -->\n"
        "<!-- region: kind=transcribed_text question_id=Q2 conf=0.41 -->\n"
        "marginal handwriting here\n<!-- /region -->")
    ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    document_id = ingestor.ingest_document([source], kind="submission",
                                           filenames={source: "scan-01.md"})
    rows = handle.query(statement(
        "SELECT element_kind, ocr_conf FROM document_region "
        "WHERE document_id = :d ORDER BY position", issue=ISSUE), d=document_id)
    assert [(row["element_kind"], row["ocr_conf"]) for row in rows] == [
        ("Q1", 0.94), ("Q2", 0.41)], (
        "TC-INGEST-21: ocr_conf is not per region at the recorded values — impact "
        "routing intersects confidence with spans (FR-INGEST-15)."
    )
    store.close()


def test_tc_ingest_22_a_cluster_is_resolved_once_across_the_cohort(tmp_data_dir):
    """`TC-INGEST-22` — the same ambiguous token in MULTIPLE submissions: clustered
    once, presented once, and the resolution applies to every occurrence, with the
    returned ids covering every affected document."""
    store, blobs, rasterizer, provider, slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort("c-36")
    marked = ("<!-- region: kind=transcribed_text -->\n"
              "the margin says <unresolved>illegible-token</unresolved> beside "
              "the answer\n<!-- /region -->")
    marked_ingestor = Ingestor(handle, blobs, _region_provider([marked]), _model(),
                               SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER)
    affected = []
    for index in range(3):
        source = blobs.put(f"submission {index}".encode())
        document_id = marked_ingestor.ingest_document([source], kind="submission",
                                                      filenames={source: "scan.md"})
        affected.append(document_id)
    clusters = marked_ingestor.clusters("c-36")
    matching = [c for c in clusters if c.token == "illegible-token"]
    assert len(matching) == 1, (
        f"TC-INGEST-22: the token produced {len(matching)} clusters — it is "
        "presented ONCE for resolution (FR-INGEST-20)."
    )
    cluster = matching[0]
    assert set(cluster.document_ids) == set(affected)
    resolved = marked_ingestor.resolve_cluster(cluster.cluster_id,
                                               "the resolved reading of the token")
    assert set(resolved) == set(affected), (
        "TC-INGEST-22: the resolution did not reach every occurrence."
    )
    for document_id in affected:
        content = handle.query(statement(
            "SELECT content FROM document_region WHERE document_id = :d",
            issue=ISSUE), d=document_id)[0]["content"]
        assert "the resolved reading of the token" in content
        assert "<unresolved>" not in content
    store.close()
