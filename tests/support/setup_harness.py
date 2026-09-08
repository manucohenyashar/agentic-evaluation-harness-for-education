"""Scripted transport doubles and the Stage A chain, shared by the `M-SETUP` test files.

Stage A (issue #54) spans two subsystems: an assessment document must pass through a real
`Ingestor` — rung 2 means real tiers, so the doubles are confined to the model boundary —
before `SetupService.propose_inventory` can read its canonical transcript. Several files
need that chain (`tests/integration/setup/test_setup_stage_a.py` and the written-ahead
readback/decomposition/policy files), so the scripted transport lives here once rather than
being re-typed per file, mirroring the reference pattern in
`tests/integration/ingest/test_ingest_gateway.py`.

Everything the model boundary receives is scripted and recorded; nothing here reaches the
network, and the socket guard installed for non-live tiers would fail any attempt.
"""

from __future__ import annotations

import json

from aeh.conf import ModelRef
from aeh.ingest import (
    DOCUMENT_KINDS,
    Ingestor,
    PageImage,
    PdfSanitizer,
    ResidencySlot,
    Rasterizer,
    SanitizeResult,
)
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store

#: The assessment under test, matching `TC-SETUP-01`'s precondition exactly: three open
#: questions, two MCQ, one mixed (an MCQ part and an open part on one question).
ASSESSMENT_MD = (
    "Assessment — Physics 102\n"
    "\n"
    "Q1. Define impulse in one sentence. (4 marks)\n"
    "\n"
    "Q2. Derive the range equation for projectile motion. (5 marks)\n"
    "\n"
    "Q3. A 2 kg cart ... show your reasoning. (6 marks)\n"
    "\n"
    "Q4. Circle one: (A) 9.8 (B) 1.6 (C) 3.7 (D) 0 (2 marks)\n"
    "\n"
    "Q5. Circle one: (A) rises (B) falls (C) stays (2 marks)\n"
    "\n"
    "Q6. Part (a) circle one: (A) yes (B) no. Part (b) explain. (3 marks)\n"
)

#: The rubric the read-back cases consume: two criteria whose constructs the scripted
#: replies elaborate into band sets. Kept distinct from `ASSESSMENT_MD` so a #51 that
#: reads or validates the rubric document is never satisfied by the assessment's text.
RUBRIC_MD = (
    "Marking rubric — Physics 102\n"
    "\n"
    "CRIT-IMP (Q1). The response defines impulse as force acting over contact time.\n"
    "\n"
    "CRIT-STEPS (Q3). The response carries the derivation through to a stated result.\n"
)

#: The student submission the ingest-side cases use (a scan of an answer script): distinct
#: from the assessment it answers, and carrying answers rather than questions.
SUBMISSION_MD = (
    "Submission — Physics 102, student 2101\n"
    "\n"
    "Q1. Impulse is the net force acting over the contact time.\n"
    "\n"
    "Q3. Starting from impulse, the range follows by eliminating the flight time.\n"
    "\n"
    "Q4. (A)\n"
)

#: The proposal the scripted setup transport returns for `ASSESSMENT_MD`: one entry per
#: question, with option sets only where the plan says they belong (`mcq` and `mixed`).
INVENTORY_REPLY = json.dumps({"questions": [
    {"question_id": "Q1", "ordinal": 1, "prompt_text": "Define impulse in one sentence.",
     "question_type": "open", "max_points": 4, "options": []},
    {"question_id": "Q2", "ordinal": 2,
     "prompt_text": "Derive the range equation for projectile motion.",
     "question_type": "open", "max_points": 5, "options": []},
    {"question_id": "Q3", "ordinal": 3, "prompt_text": "A 2 kg cart ... show your reasoning.",
     "question_type": "open", "max_points": 6, "options": []},
    {"question_id": "Q4", "ordinal": 4,
     "prompt_text": "Circle one: (A) 9.8 (B) 1.6 (C) 3.7 (D) 0",
     "question_type": "mcq", "max_points": 2,
     "options": [{"option_id": "A", "ordinal": 0, "label": "9.8"},
                 {"option_id": "B", "ordinal": 1, "label": "1.6"},
                 {"option_id": "C", "ordinal": 2, "label": "3.7"},
                 {"option_id": "D", "ordinal": 3, "label": "0"}]},
    {"question_id": "Q5", "ordinal": 5,
     "prompt_text": "Circle one: (A) rises (B) falls (C) stays",
     "question_type": "mcq", "max_points": 2,
     "options": [{"option_id": "A", "ordinal": 0, "label": "rises"},
                 {"option_id": "B", "ordinal": 1, "label": "falls"},
                 {"option_id": "C", "ordinal": 2, "label": "stays"}]},
    {"question_id": "Q6", "ordinal": 6,
     "prompt_text": "Part (a) circle one: (A) yes (B) no. Part (b) explain.",
     "question_type": "mixed", "max_points": 3,
     "options": [{"option_id": "A", "ordinal": 0, "label": "yes"},
                 {"option_id": "B", "ordinal": 1, "label": "no"}]},
]})

TRANSCRIBER_BUILD = "vlm@sha256:aaaa"
SETUP_BUILD = "vlm@sha256:bbbb"

#: Distinct builds for the two transports, so a test asserting the recorded `model_ref`
#: reads the *setup* transport's build and cannot be satisfied by the transcriber's.


class ScriptedSanitizer(PdfSanitizer):
    """Pass-through sanitizer: the medium is not what any setup case is about."""

    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class ScriptedRasterizer(Rasterizer):
    """One scripted page per document; records the rasterize calls it received."""

    def __init__(self) -> None:
        self.calls = 0

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.calls += 1
        return [PageImage(page_no=1, png=b"page-raster", width_px=100, height_px=140)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"page-raster"


class ScriptedIngestProvider:
    """Transcription transport that always returns `transcript`. Records its calls."""

    def __init__(self, transcript: str = ASSESSMENT_MD) -> None:
        self.transcript = transcript
        self.calls: list[dict] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        self.calls.append(dict(prompt.fields))
        return Completion(text=self.transcript, tokens_in=10, tokens_out=5,
                          latency_ms=1, resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class ScriptedSetupProvider:
    """The setup model boundary: replays `replies`, then defaults to `INVENTORY_REPLY`.

    Records every call's prompt fields — the spy half of `TC-SETUP-01`'s "exactly once"
    and the prompt-shape half of `TC-SETUP-22` (the template's rendered fields).
    """

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        self.calls.append(dict(prompt.fields))
        text = self.replies.pop(0) if self.replies else INVENTORY_REPLY
        return Completion(text=text, tokens_in=10, tokens_out=5, latency_ms=1,
                          resolved_build=SETUP_BUILD, cached_prefix_tokens=0, cost=None)


def build_ingestor(store, transcript: str = ASSESSMENT_MD) -> Ingestor:
    """A real `Ingestor` over the store's tiers with every model call scripted."""
    return Ingestor(
        store.cohort("c-setup"), store.blobs(), ScriptedIngestProvider(transcript),
        ModelRef(role="transcriber", provider="local", build_id=TRANSCRIBER_BUILD,
                 quantization="q4"),
        SamplingParams(temperature=0.0), ScriptedRasterizer(),
        residency=ResidencySlot.for_policy(("transcriber",)),
        sanitizer=ScriptedSanitizer(),
    )


#: Per-kind canonical transcripts: what the transcriber returns for each document kind.
KIND_TRANSCRIPTS = {"assessment": ASSESSMENT_MD, "rubric": RUBRIC_MD,
                    "submission": SUBMISSION_MD}


def ingest_document(store, *, kind: str = "assessment",
                    name: str | None = None) -> str:
    """Ingest one single-page document of `kind` and return its document id.

    The transcriber is built per call so the canonical transcript matches the document's
    `kind` — a rubric is never transcribed as the assessment. A kind missing from
    `KIND_TRANSCRIPTS` fails loudly here rather than transcribing as another kind.
    """
    assert kind in DOCUMENT_KINDS, f"{kind!r} is not a document kind"
    assert kind in KIND_TRANSCRIPTS, (
        f"{kind!r} has no canonical transcript in setup_harness — add one to "
        "KIND_TRANSCRIPTS rather than transcribing it as a different kind"
    )
    source = store.blobs().put(f"{kind} bytes".encode())
    doc_ingestor = build_ingestor(store, KIND_TRANSCRIPTS[kind])
    return doc_ingestor.ingest_document([source], kind=kind,
                                        filenames={source: name or f"{kind}.pdf"})


class ScriptedCatalog:
    """The catalog surface `SetupService` touches, as a pure in-memory double.

    Rung 0: no store. `record_proposal` records its call verbatim — the observation
    surface `TC-SETUP-22` asserts on — and `proposal(v)` hands the same row back, so the
    resume-first path and `current_proposal` behave over the double exactly as over
    `aeh.pkg.PackageCatalog`. Members the later setup stories will write through
    (`add_criterion`, band sets) are deliberately absent: a rung-0 test that needs them
    names that in its own file, rather than the double guessing #51/#52/#53's writes.
    """

    def __init__(self, package_id: str = "pkg-surface") -> None:
        self.package_id = package_id
        self.versions: list[str] = []
        self.proposals: dict[str, dict] = {}
        self.criteria_rows: tuple[dict, ...] = ()
        self.recorded: list[dict] = []

    def draft_version(self):
        return self.versions[-1] if self.versions else None

    def has_version(self) -> bool:
        return bool(self.versions)

    def ensure_package(self) -> None:
        pass

    def create_version(self, approved_by) -> str:
        version = f"{self.package_id}@{len(self.versions) + 1:03d}"
        self.versions.append(version)
        return version

    def proposal(self, v):
        return self.proposals.get(v)

    def record_proposal(self, v, **kwargs) -> None:
        row = dict(kwargs)
        row["confirmed_at"] = None
        self.proposals[v] = row
        self.recorded.append(row)

    def criteria(self, v):
        return self.criteria_rows


class ScriptedIngestor:
    """Just `read_document`: the only ingest member the proposal path touches at rung 0."""

    def __init__(self, transcript: str = ASSESSMENT_MD) -> None:
        self.transcript = transcript

    def read_document(self, document_id) -> str:
        return self.transcript


def make_setup_service(catalog, ingestor, provider):
    """A `SetupService` over the given pieces with the scripted setup build.

    Kept as a function (not a fixture) so rung-0 files can hand it a pure double and
    integration files a real catalog without two fixture trees.
    """
    from aeh.setup import SetupService

    return SetupService(catalog, ingestor, provider,
                        ModelRef(role="extractor", provider="local",
                                 build_id=SETUP_BUILD, quantization="q4"))


def stage_chain(data_dir, package_id: str = "pkg-setup"):
    """The full Stage A chain over real tiers: store, ingestor, catalog, service.

    One call builds what every rung-2 setup test drives; the scripted transports are the
    only doubles. `package_id` names the package the catalog is opened on — a test that
    resumes with a *fresh* service re-opens the same package id over the same tiers.
    """
    from types import SimpleNamespace

    from aeh.pkg import PackageCatalog

    store = open_store(data_dir)
    ingestor = build_ingestor(store)
    catalog = PackageCatalog(store.package(package_id), package_id=package_id)
    provider = ScriptedSetupProvider()
    return SimpleNamespace(store=store, package_id=package_id, ingestor=ingestor,
                           catalog=catalog, provider=provider,
                           service=make_setup_service(catalog, ingestor, provider))
