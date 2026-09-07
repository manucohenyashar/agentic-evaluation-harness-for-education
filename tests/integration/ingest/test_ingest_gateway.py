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
import pathlib
import sqlite3
import threading

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    DOCUMENT_KINDS,
    IngestError,
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
        document_id = ingestor.ingest_document([source], kind=kind)
        row = store.cohort("c-36").query(statement(
            "SELECT kind FROM document WHERE document_id = :d", issue=ISSUE),
            d=document_id)[0]
        assert row["kind"] == kind
        assert len(provider.calls) - before == 2, (
            f"TC-INGEST-02: kind {kind!r} made {len(provider.calls) - before} VLM "
            "calls for a two-page PDF — every page is transcribed with exactly one "
            "call (FR-INGEST-02)."
        )
        total_calls += len(provider.calls) - before
    assert total_calls == 8
    assert set(rasterizer.dpi_seen) == {200}, (
        "TC-INGEST-02: the rasterization DPI is not the pinned default."
    )
    # No per-kind alternative path: the pipeline never branches on kind.
    module_source = pathlib.Path("src", "aeh", "ingest.py").read_text(encoding="utf-8")
    dispatch_branches = [
        line.strip() for line in module_source.splitlines()
        if "kind ==" in line or 'kind in' in line and "if" in line
    ]
    assert dispatch_branches == [], (
        f"TC-INGEST-02: the dispatch branches on kind: {dispatch_branches}. There is "
        "one pipeline for all four kinds (FR-INGEST-02)."
    )
    # The env knob moves the pinned DPI (seam 3):
    patch = pytest.MonkeyPatch()
    patch.setenv("HARNESS_INGEST_DPI", "150")
    try:
        ingestor.ingest_document([source], kind="submission")
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
    first = ingestor.ingest_document([source], kind="assessment")
    second = ingestor.ingest_document([source], kind="reference")
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
    original = ingestor.ingest_document([source], kind="submission")
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
    ingestor.ingest_document([source], kind="submission")
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
    # And a policy admitting both roles yields the coexistence form:
    shared = ResidencySlot.for_policy(("judge", "transcriber"))
    assert shared._exclusive is False
    store.close()
