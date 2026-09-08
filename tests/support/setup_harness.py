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


def ingest_document(store, ingestor: Ingestor, *, kind: str = "assessment",
                    name: str = "assessment.pdf") -> str:
    """Ingest one single-page document of `kind` and return its document id."""
    assert kind in DOCUMENT_KINDS, f"{kind!r} is not a document kind"
    source = store.blobs().put(f"{kind} bytes".encode())
    return ingestor.ingest_document([source], kind=kind, filenames={source: name})


def make_setup_service(catalog, ingestor, provider):
    """A `SetupService` over the given pieces with the scripted setup build.

    Kept as a function (not a fixture) so rung-0 files can hand it a pure double and
    integration files a real catalog without two fixture trees.
    """
    from aeh.setup import SetupService

    return SetupService(catalog, ingestor, provider,
                        ModelRef(role="extractor", provider="local",
                                 build_id=SETUP_BUILD, quantization="q4"))
