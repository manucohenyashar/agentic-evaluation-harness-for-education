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
    IngestDuplicateError,
    IngestError,
    IngestGapError,
    IngestOrderError,
    Ingestor,
    PageImage,
    PageReplacement,
    ResidencySlot,
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
                        SamplingParams(temperature=0.0), rasterizer, residency=slot)
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
    allowed = {'if kind == "reference" and divergence is not None:'}
    dispatch_branches = [
        line.strip() for line in module_source.splitlines()
        if ("kind ==" in line or 'kind in' in line and "if" in line)
        and line.strip() not in allowed
    ]
    assert dispatch_branches == [], (
        f"TC-INGEST-02: the dispatch branches on kind: {dispatch_branches}. There is "
        "one pipeline for all four kinds (FR-INGEST-02) — the reference divergence "
        "halt is a post-transcription gate, not an extraction path."
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
                            SamplingParams(temperature=0.0), layered)
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
                        SamplingParams(temperature=0.0), layered)
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
                        SamplingParams(temperature=0.0), rasterizer)
    document_id = ingestor.ingest_document([source], kind="submission")
    row = handle.query(statement(
        "SELECT markdown, source_blobs FROM document WHERE document_id = :d",
        issue=ISSUE), d=document_id)[0]
    assert row["markdown"].startswith("Page 1 of 2 - first")
    provenance = json.loads(row["source_blobs"])
    assert provenance["order_source"] == "page_number"
    assert [page["position"] for page in provenance["pages"]] == [1, 2]

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
                              SamplingParams(temperature=0.0), rasterizer)
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
    # The hint ordered the FILES: first_blob's pages precede second_blob's.
    assert row["markdown"].index(first_blob[:6]) < row["markdown"].index(second_blob[:6])

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
                         SamplingParams(temperature=0.0), rasterizer)
    with pytest.raises(IngestDuplicateError, match="Surface for"):
        identical.ingest_document([source], kind="submission",
                                  filenames={source: "scan-01.md"})

    # Just ABOVE the threshold (one extra word: 10/11 = 0.909): surfaced.
    near = Ingestor(handle, blobs,
                    _two_page_provider(base, base + " lambda"),
                    _model(), SamplingParams(temperature=0.0), rasterizer)
    with pytest.raises(IngestDuplicateError, match="Surface for"):
        near.ingest_document([source], kind="submission",
                             filenames={source: "scan-01.md"})
    # Just BELOW it (two extra words: 10/12 = 0.833): ingested.
    below = Ingestor(handle, blobs,
                     _two_page_provider(base, base + " lambda mu"),
                     _model(), SamplingParams(temperature=0.0), rasterizer)
    assert below.ingest_document([source], kind="submission",
                                 filenames={source: "scan-01.md"})

    different = Ingestor(handle, blobs,
                         _two_page_provider(
                             "the first page discusses algebraic manipulation",
                             "the second page contains a diagram of a pulley"),
                         _model(), SamplingParams(temperature=0.0), rasterizer)
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
    NAMING [3, 7] — the assertion is on the named positions, not merely on failure."""
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
                        SamplingParams(temperature=0.0), FivePageRasterizer())
    with pytest.raises(IngestError) as gap:
        ingestor.ingest_document([source], kind="submission")
    assert "[3, 7]" in str(gap.value), (
        f"TC-INGEST-10: the finding does not name the specific missing positions: "
        f"{gap.value}."
    )
    store.close()
