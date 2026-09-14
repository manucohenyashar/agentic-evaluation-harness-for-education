"""`TC-INGEST-38` — the FR-INGEST-14 second-description pass (#236, TS-15 remainder).

A criterion on the injected Phase-1 high-risk list, with a described graphic: a second
description of the same crop is produced with a different model family, and disagreement
on a load-bearing fact is recorded as an integrity signal `M-INTEG` reads. Q-12 leaves the
register's contents TBD, so the list is injected (`high_risk_criterion_ids=`).

Rung 2: a real store and blob directory; both models answer through one scripted provider
double that keys on the requested `ModelRef` and pins `resolved_build` to what it was asked
for (the deterministic-transport discipline, FR-PROV-04), so the second call's attribution
is the recorded build and nothing reaches the network.

The page follows the pinned transcription prompt's tagging: a question's text region, then
its graphic tagged by `element_kind` only. #233's recorded reading makes the graphic belong
to the question region that precedes it.

Interpretations under test, all #233's (the design is silent): "different family" is a
different `(provider, build_id)` pair; a load-bearing fact is a number in the description,
compared as a multiset, beside a content-word similarity floor.
"""

from __future__ import annotations

import base64
import json

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    IngestError,
    Ingestor,
    PageImage,
    Rasterizer,
    PdfSanitizer,
    ResidencySlot,
    SanitizeResult,
    description_integrity_signals,
    second_description_pass,
)
from aeh.pkg import PackageCatalog, PackageDraft
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store

pytestmark = pytest.mark.integration

COHORT = "c-238"
TRANSCRIBER = ModelRef(role="transcriber", provider="local",
                       build_id="vlm@sha256:aaaa", quantization="q4")
SECOND = ModelRef(role="transcriber", provider="fixture-b",
                  build_id="/models/qwen-vl.gguf@sha256:bbbb", quantization="q4")

INCLINE = "A block on a 30 degree incline with a 5 N applied force arrow"
PULLEY = "A pulley with two masses of 2 kg and 3 kg"


def _page(*questions: tuple[str, str]) -> str:
    """One transcript: per (question_id, graphic description), a text region naming the
    question and then a graphic tagged the pinned prompt's way (no question_id)."""
    parts = []
    for question_id, graphic in questions:
        parts.append(f"<!-- region: kind=transcribed_text question_id={question_id} "
                     f"state=present -->\nAnswer to {question_id}.\n<!-- /region -->")
        parts.append("<!-- region: kind=described_graphic element_kind=free_body_diagram -->"
                     f"\n{graphic}\n<!-- /region -->")
    return "\n".join(parts)


class _Rasterizer(Rasterizer):
    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        return [PageImage(page_no=1, png=b"png-" + pdf_bytes, width_px=1000, height_px=1400)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"\x89PNG crop of " + pdf_bytes + f" p{page_no} {box}".encode()


class _Through(PdfSanitizer):
    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class _TwoModels:
    """Answers the transcriber with the page and the second model with `second`
    (a string, an exception to raise, or None for a build override test). Records every
    call as (build requested, fields, the slot holder at call time)."""

    def __init__(self, page: str, second, *, second_resolves_to: str | None = None,
                 slot: ResidencySlot | None = None) -> None:
        self.page, self.second, self.slot = page, second, slot
        self.second_resolves_to = second_resolves_to
        self.calls: list[tuple[str, dict, object]] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        holder = self.slot.snapshot()["holder"] if self.slot is not None else None
        self.calls.append((model_ref.build_id, fields, holder))
        if model_ref.build_id == SECOND.build_id:
            if isinstance(self.second, Exception):
                raise self.second
            text, resolved = self.second, self.second_resolves_to or model_ref.build_id
        else:
            text, resolved = self.page, model_ref.build_id
        return Completion(text=text, tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=resolved, cached_prefix_tokens=0, cost=None)

    def second_calls(self):
        return [call for call in self.calls if call[0] == SECOND.build_id]


class _World:
    def __init__(self, tmp_data_dir, provider, *, high_risk=("C1",), slot=None) -> None:
        self.store = open_store(tmp_data_dir)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute("INSERT INTO cohort (cohort_id, consent_class, created_at) "
                       "VALUES (:c, 'synthetic', '2026-01-01')", c=COHORT)
        package = self.store.package("pkg-238")
        with package.transaction() as tx:
            tx.execute("INSERT INTO package (package_id, created_at) VALUES ('pkg-238', 'x')")
        self.catalog = PackageCatalog(package, package_id="pkg-238")
        self.version = self.catalog.create_version(None, PackageDraft(title="pkg"))
        self.catalog.add_criterion(self.version, "C1", question_id="Q1", kind="open",
                                   max_points=4.0)
        self.catalog.add_criterion(self.version, "C2", question_id="Q2", kind="open",
                                   max_points=4.0)
        self.provider = provider
        self.ingestor = Ingestor(self.handle, self.blobs, provider, TRANSCRIBER,
                                 SamplingParams(temperature=0.0), _Rasterizer(),
                                 sanitizer=_Through(), residency=slot,
                                 high_risk_criterion_ids=high_risk, second_model_ref=SECOND)

    def ingest(self):
        source = self.blobs.put(b"scan-238")
        report = self.ingestor.ingest_submission(
            [source], cohort_id=COHORT, package_version=self.version,
            package_catalog=self.catalog, filenames={source: "scan-01.md"})
        rows = self.handle.query(
            "SELECT region_id, region_kind, element_kind, crop_ref, description, "
            "description_secondary FROM document_region WHERE document_id = :d "
            "ORDER BY position", d=report.document_id)
        graphics = [dict(row) for row in rows if row["region_kind"] == "described_graphic"]
        return report, graphics

    def close(self):
        self.store.close()


def test_tc_ingest_38_the_listed_graphic_is_described_again_and_disagreement_is_recorded(
        tmp_data_dir):
    """`TC-INGEST-38` — the high-risk graphic (C1 → Q1) gets a second description from
    the second family, of the same crop; the 30 → 45 disagreement is recorded with its
    exact shape; the unlisted Q2 graphic is described exactly once."""
    provider = _TwoModels(_page(("Q1", INCLINE), ("Q2", PULLEY)),
                          "A block on a 45 degree incline with a 5 N applied force arrow")
    world = _World(tmp_data_dir, provider)
    try:
        report, graphics = world.ingest()
        incline, pulley = graphics
        assert (incline["description"], pulley["description"]) == (INCLINE, PULLEY)

        # Exactly one second call — for the listed graphic only, on its own crop.
        second = provider.second_calls()
        assert len(second) == 1, f"TC-INGEST-38: {len(second)} second-model calls, want 1"
        fields = second[0][1]
        crop_bytes = world.blobs.get(incline["crop_ref"])
        assert fields["crop_ref"] == incline["crop_ref"]
        assert base64.b64decode(fields["image_png_base64"]) == crop_bytes, (
            "TC-INGEST-38: the second description must be of the SAME crop")
        assert incline["description_secondary"] == (
            "A block on a 45 degree incline with a 5 N applied force arrow")
        assert pulley["description_secondary"] is None, (
            "TC-INGEST-38: an unlisted criterion's graphic got a second description")

        # The pass record: attribution to the resolved second build, the exact verdict.
        record = report.detail["second_description_pass"]
        assert {k: record[k] for k in ("status", "declared_criteria", "high_risk_questions",
                                       "graphics", "matched", "described", "failed",
                                       "disagreements")} == {
            "status": "ran", "declared_criteria": ["C1"], "high_risk_questions": ["Q1"],
            "graphics": 2, "matched": 1, "described": 1, "failed": 0, "disagreements": 1}
        (entry,) = report.detail["second_descriptions"]
        assert entry["resolved_build"] == SECOND.build_id
        assert entry["second_model"] == {"provider": SECOND.provider,
                                         "build_id": SECOND.build_id}
        verdict = entry["disagreement"]
        assert (verdict["disagrees"], verdict["reasons"], verdict["facts_only_primary"],
                verdict["facts_only_secondary"]) == (True, ["facts"], ["30"], ["45"]), verdict

        # The integrity signal M-INTEG reads — from the store, not the report.
        signals = description_integrity_signals(world.handle, report.document_id)
        assert [(s.region_id, s.status, s.description, s.description_secondary)
                for s in signals] == [(incline["region_id"], "described", INCLINE,
                                       incline["description_secondary"])]
        assert signals[0].disagreement == verdict, (
            "TC-INGEST-38: the stored signal must carry the verdict ingest decided")
        stored = second_description_pass(world.handle, report.document_id)
        assert stored["disagreements"] == 1 and stored["regions"][0]["status"] == "described"
    finally:
        world.close()


def test_tc_ingest_38_agreeing_descriptions_record_no_disagreement(tmp_data_dir):
    """Negative control for the verdict: the same facts in other words agree, so a
    verdict that always read `disagrees` would fail here."""
    provider = _TwoModels(_page(("Q1", INCLINE)),
                          "Block resting on an incline at 30 degrees; applied force arrow of 5 N")
    world = _World(tmp_data_dir, provider)
    try:
        report, _graphics = world.ingest()
        (signal,) = description_integrity_signals(world.handle, report.document_id)
        assert (signal.status, signal.disagreement["disagrees"],
                signal.disagreement["reasons"]) == ("described", False, [])
        assert report.detail["second_description_pass"]["disagreements"] == 0
    finally:
        world.close()


def test_tc_ingest_38_an_unlisted_criterion_gets_exactly_one_description(tmp_data_dir):
    """No blanket second pass: the register lists C1, the paper's only graphic is Q2's —
    zero second calls, and the pass record says it ran and matched nothing."""
    provider = _TwoModels(_page(("Q2", PULLEY)), "unused")
    world = _World(tmp_data_dir, provider)
    try:
        report, graphics = world.ingest()
        assert provider.second_calls() == []
        assert [g["description_secondary"] for g in graphics] == [None]
        record = report.detail["second_description_pass"]
        assert (record["status"], record["graphics"], record["matched"]) == ("ran", 1, 0)
        assert description_integrity_signals(world.handle, report.document_id) == ()
    finally:
        world.close()


@pytest.mark.parametrize("failure", ["raises", "same-build"])
def test_tc_ingest_38_a_second_model_failure_is_recorded_never_agreement(tmp_data_dir, failure):
    """A second call that raises, or answers from the transcriber's own build, is a
    `failed` signal with no comparison — not an agreement and not silence."""
    if failure == "raises":
        provider = _TwoModels(_page(("Q1", INCLINE)), RuntimeError("second model down"))
    else:
        provider = _TwoModels(_page(("Q1", INCLINE)), INCLINE,
                              second_resolves_to=TRANSCRIBER.build_id)
    world = _World(tmp_data_dir, provider)
    try:
        report, graphics = world.ingest()
        assert len(provider.second_calls()) == 1
        assert [g["description_secondary"] for g in graphics] == [None]
        record = report.detail["second_description_pass"]
        assert (record["described"], record["failed"], record["disagreements"]) == (0, 1, 0)
        (signal,) = description_integrity_signals(world.handle, report.document_id)
        assert (signal.status, signal.disagreement, signal.description_secondary) == (
            "failed", None, None), signal
        assert signal.error, "TC-INGEST-38: the failure must say what went wrong"
    finally:
        world.close()


def test_tc_ingest_38_the_second_call_holds_the_residency_slot(tmp_data_dir):
    """The second VLM call runs inside the exclusive residency slot under its own role."""
    slot = ResidencySlot(exclusive=True)
    provider = _TwoModels(_page(("Q1", INCLINE)), INCLINE, slot=slot)
    world = _World(tmp_data_dir, provider, slot=slot)
    try:
        world.ingest()
        holders = {build: holder for build, _fields, holder in provider.calls}
        assert holders == {TRANSCRIBER.build_id: "transcriber",
                           SECOND.build_id: "second_describer"}, holders
        assert slot.snapshot()["holder"] is None
    finally:
        world.close()


@pytest.mark.parametrize("kwargs, needle", [
    ({"high_risk_criterion_ids": ("C1",)}, "without a second_model_ref"),
    ({"high_risk_criterion_ids": ("C1",), "second_model_ref": TRANSCRIBER}, "repeats"),
])
def test_tc_ingest_38_a_register_without_a_second_family_is_refused(tmp_data_dir, kwargs, needle):
    """The register cannot be declared with no second model, or with the transcriber's
    own (provider, build) as the second family."""
    store = open_store(tmp_data_dir)
    try:
        with pytest.raises(IngestError, match=needle):
            Ingestor(store.cohort(COHORT), store.blobs(), _TwoModels("", ""), TRANSCRIBER,
                     SamplingParams(temperature=0.0), _Rasterizer(), sanitizer=_Through(),
                     **kwargs)
    finally:
        store.close()


def test_tc_ingest_38_no_register_records_no_pass(tmp_data_dir):
    """Without an injected register the pass does not run and says nothing: the record
    is absent (None), distinguishable from a pass that ran and matched nothing."""
    provider = _TwoModels(_page(("Q1", INCLINE)), "unused")
    store = open_store(tmp_data_dir)
    try:
        handle = store.cohort(COHORT)
        with handle.transaction() as tx:
            tx.execute("INSERT INTO cohort (cohort_id, consent_class, created_at) "
                       "VALUES (:c, 'synthetic', '2026-01-01')", c=COHORT)
        ingestor = Ingestor(handle, store.blobs(), provider, TRANSCRIBER,
                            SamplingParams(temperature=0.0), _Rasterizer(), sanitizer=_Through())
        source = store.blobs().put(b"scan-238")
        document_id = ingestor.ingest_document([source], kind="submission",
                                               filenames={source: "scan-01.md"},
                                               submission_id=None)
        assert provider.second_calls() == []
        assert second_description_pass(handle, document_id) is None
        assert json.loads(handle.query("SELECT source_blobs FROM document WHERE document_id = :d",
                                       d=document_id)[0]["source_blobs"]).get(
            "second_description_pass") is None
    finally:
        store.close()
