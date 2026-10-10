"""`TC-REG-15`, `TC-INGEST-56`, `TC-INGEST-57` — the transcription request carries the region
protocol, and a real reader's per-option tick boxes are read, not parked.

Inline defect regression (test plan §6.9). The first live run (2026-10-09, `aeh-live-1`)
parked every physics sheet: the page reader read each page correctly but wrote one
`selection_mark` region per printed option (`[ ] A` … `[X] C`) with no `selection=`, left
written answers untagged, and named sub-question `Q5` where the package declares `Q5a`/`Q5b`.
The pinned prompt (v4) never asked for `selection=`, never said one mark per question, never
put `question_id=` on a written answer, and the page request carried no declared question
ids — so the model could not have known. Every scripted reader in the suite ignored the prompt
and returned perfect markup, which is why no test caught it.

`data/reg_15_live_s9_002.md` is that run's stored transcript of `S9-002-middle.pdf`, verbatim
(synthetic sample sheet, made-up student). The cases here fail against the v4 code: the request
carries no inventory and no protocol rules, and the live tick boxes store as `ambiguous`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aeh.conf import ModelRef
from aeh.ingest import Ingestor, PageImage, PdfSanitizer, ResidencySlot, SanitizeResult
from aeh.ingest.regions import _parse_regions
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store

ISSUE = "TC-REG-15"

DATA = Path(__file__).parent / "data"

#: The first live run's (v4) transcript of `S9-002-middle.pdf`.
LIVE_TRANSCRIPT = (DATA / "reg_15_live_s9_002.md").read_text(encoding="utf-8")

#: The second live run's (v5) transcripts, same reader: the printed test paper, a correctly
#: answered sheet, and the wrong-test sheet. The v5 reader followed the protocol exactly, and
#: the sheet still parked — on the right-test gate's semantic signal (see the case below).
LIVE_V5_TEST_PAPER = (DATA / "reg_15_live_v5_test_paper.md").read_text(encoding="utf-8")
LIVE_V5_S9_001 = (DATA / "reg_15_live_v5_s9_001.md").read_text(encoding="utf-8")
LIVE_V5_S9_005 = (DATA / "reg_15_live_v5_s9_005.md").read_text(encoding="utf-8")

#: The PS9-FORCES-01 inventory (docs/live-tests/config/ps9-forces-01.package.toml).
PS9_QUESTIONS = (
    ("C1", "Q1", "mcq", ("A", "B", "C", "D")),
    ("C2", "Q2", "mcq", ("A", "B", "C", "D")),
    ("C3", "Q3", "mcq", ("A", "B", "C", "D")),
    ("C4", "Q4", "open", ()),
    ("C5a", "Q5a", "mcq", ("A", "B", "C")),
    ("C5b", "Q5b", "open", ()),
)

EXPECTED_DECLARED = [
    "Q1: multiple choice, options A B C D",
    "Q2: multiple choice, options A B C D",
    "Q3: multiple choice, options A B C D",
    "Q4: written answer",
    "Q5a: multiple choice, options A B C",
    "Q5b: written answer",
]


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:bbbb", quantization="q4")


class _ThroughSanitizer(PdfSanitizer):
    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class _OnePageRasterizer:
    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        return [PageImage(page_no=1, png=b"page-" + bytes(pdf_bytes),
                          width_px=1000, height_px=1400)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class _RecordingReader:
    """Answers each page with its staged transcript and keeps every request's fields."""

    def __init__(self) -> None:
        self.texts: dict[str, str] = {}
        self.requests: list[dict[str, str]] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        self.requests.append(fields)
        return Completion(text=self.texts.get(fields.get("source_blob_hash", ""),
                                              "uncertain"),
                          tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class _World:
    """A store, a cohort with roster refs `S9-001`/`-002`/`-005`, the PS9 package, and an
    ingestor."""

    def __init__(self, tmp_data_dir: Path, name: str, *, bind_package: bool = True) -> None:
        from aeh.pkg import PackageCatalog, PackageDraft

        self.store = open_store(tmp_data_dir / f"reg15-{name}")
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort("c-reg15")
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                       "created_at) VALUES ('c-reg15', 'synthetic', 'x')")
            for ref in ("S9-001", "S9-002", "S9-005"):
                tx.execute("INSERT INTO roster (cohort_id, student_ref) "
                           "VALUES ('c-reg15', :ref)", ref=ref)
        seed = self.store.package("PS9-FORCES-01")
        with seed.transaction() as tx:
            tx.execute("INSERT INTO package (package_id, created_at) "
                       "VALUES ('PS9-FORCES-01', 'x')")
        self.catalog = PackageCatalog(seed, package_id="PS9-FORCES-01")
        self.version = self.catalog.create_version(None, PackageDraft(title="ps9"))
        for criterion_id, question_id, kind, options in PS9_QUESTIONS:
            self.catalog.add_criterion(self.version, criterion_id,
                                       question_id=question_id, kind=kind,
                                       max_points=1.0)
            if options:
                self.catalog.set_mcq_options(self.version, criterion_id,
                                             [(option, option) for option in options])
        self.reader = _RecordingReader()
        self.ingestor = Ingestor(
            self.handle, self.blobs, self.reader, _model(),
            SamplingParams(temperature=0.0), _OnePageRasterizer(),
            residency=ResidencySlot.for_policy(("transcriber",)),
            sanitizer=_ThroughSanitizer(),
            package_catalog=self.catalog if bind_package else None,
            package_version=self.version if bind_package else None)

    def ingest(self, transcript: str, *, with_package: bool = True):
        source = self.blobs.put(transcript.encode("utf-8"))
        self.reader.texts[source] = transcript
        return self.ingestor.ingest_submission(
            [source], cohort_id="c-reg15", package_version=self.version,
            package_catalog=self.catalog if with_package else None,
            filenames={source: "S9-002-middle.pdf"})

    def marks(self, document_id: str) -> dict[str, tuple]:
        rows = self.handle.query(
            "SELECT element_kind, selection_state, selection FROM document_region "
            "WHERE document_id = :d AND region_kind = 'selection_mark'", d=document_id)
        found: dict[str, list] = {}
        for row in rows:
            found.setdefault(row["element_kind"], []).append(
                (row["selection_state"], row["selection"]))
        return {question: tuple(states) for question, states in found.items()}

    def transcription_requests(self) -> list[dict[str, str]]:
        return [fields for fields in self.reader.requests if "page_no" in fields]

    def close(self) -> None:
        self.store.close()


def _live_with_v5_ids(transcript: str) -> str:
    """The live reading with the ids a v5 prompt supplies and asks for — `question_id` on the
    two written answers, `Q5a` for the cyclist mark — but the tick boxes left exactly as the
    live model wrote them, one region per printed option."""
    tagged = transcript.replace("question_id=Q5 ", "question_id=Q5a ")
    tagged = tagged.replace("kind=transcribed_text conf=0.97 state=present",
                            "kind=transcribed_text question_id=Q4 conf=0.97 state=present")
    tagged = tagged.replace("kind=transcribed_text conf=0.99 state=present",
                            "kind=transcribed_text question_id=Q5b conf=0.99 state=present")
    assert tagged.count("question_id=Q4") == 1 and tagged.count("question_id=Q5b") == 1
    return tagged


def _mark(question_id: str, state: str, selection: str = "") -> str:
    selection_attr = f" selection={selection}" if selection else ""
    return (f"<!-- region: kind=selection_mark question_id={question_id} conf=0.99 "
            f"selection_state={state}{selection_attr} -->\n{selection or 'mark'}\n"
            "<!-- /region -->")


def _answer(question_id: str, body: str) -> str:
    return (f"<!-- region: kind=transcribed_text question_id={question_id} conf=0.97 "
            f"state=present -->\n{body}\n<!-- /region -->")


#: The same reading as the live transcript, in the shape the v5 prompt asks for.
V5_CONFORMANT = "\n".join([
    "Assessment: PS9-FORCES-01", "Student: S9-002",
    "<!-- region: kind=transcribed_text conf=0.99 -->\nQ1. An object is moving at a steady "
    "speed in a straight line.\n<!-- /region -->",
    _mark("Q1", "resolved", "C"),
    _mark("Q2", "resolved", "B"),
    _mark("Q3", "resolved", "B"),
    _answer("Q4", "Gravity is pulling the book down and the table is pushing it up."),
    _mark("Q5a", "resolved", "A"),
    _answer("Q5b", "The forces are balanced so they cancel each other out."),
    "Page 1 of 1",
])


# -- TC-INGEST-56: the request carries the protocol and the declared inventory ---------------------


def test_tc_ingest_56_the_page_request_carries_the_declared_inventory_and_protocol(
        tmp_data_dir):
    """`TC-INGEST-56` — every transcription request for a package-bound document names the
    package's question ids (with each multiple-choice question's option ids) and states the
    mark/answer protocol the parser and the V2/V4 gates read; a request with no package bound
    carries no inventory. Fails on v4: no `declared_questions` field and no such rules."""
    world = _World(tmp_data_dir, "request")
    world.ingest(V5_CONFORMANT)
    requests = world.transcription_requests()
    assert requests, "TC-INGEST-56: no transcription request was made."
    for fields in requests:
        assert fields.get("prompt_template_version") == "ingest-transcribe-v5", (
            "TC-INGEST-56: the protocol change is a deliberate prompt bump (NFR-INGEST-05), "
            f"got {fields.get('prompt_template_version')!r}.")
        declared = fields.get("declared_questions")
        assert declared is not None, (
            "TC-INGEST-56: the page request carries no declared question ids — the reader "
            "cannot know the package calls question 5's parts Q5a and Q5b.")
        lines = [line.strip() for line in declared.splitlines()
                 if re.match(r"^\s*Q\w+:", line)]
        assert lines == EXPECTED_DECLARED, (
            f"TC-INGEST-56: the declared inventory is {lines!r}, expected "
            f"{EXPECTED_DECLARED!r}.")
        instruction = fields["instruction"]
        assert "selection=" in instruction, (
            "TC-INGEST-56: the prompt never asks for `selection=<option>` — without it every "
            "mark stores as ambiguous (FR-INGEST-17).")
        assert re.search(r"exactly one\b.{0,40}selection_mark.{0,60}per multiple-choice "
                         r"question", instruction, re.I | re.S), (
            "TC-INGEST-56: the prompt does not ask for exactly one mark region per "
            "multiple-choice question.")
        assert re.search(r"never one per (printed )?option", instruction, re.I), (
            "TC-INGEST-56: the prompt does not forbid one region per option.")
        assert "kind=transcribed_text question_id=" in instruction, (
            "TC-INGEST-56: the prompt never shows a written answer tagged with its question.")

    # No package bound anywhere: the request keeps its shape and carries no inventory.
    bare = _World(tmp_data_dir, "request-bare", bind_package=False)
    bare.ingest(V5_CONFORMANT, with_package=False)
    for fields in bare.transcription_requests():
        assert "declared_questions" not in fields, (
            "TC-INGEST-56: a request with no package bound must not invent an inventory.")
    world.close()
    bare.close()


def test_tc_ingest_56_the_assessment_paper_request_carries_the_inventory(tmp_data_dir):
    """`TC-INGEST-56` (the test paper) — `aeh ingest` reads the printed test with the
    ingestor's bound package; that request names the same declared ids."""
    world = _World(tmp_data_dir, "request-assessment")
    source = world.blobs.put(b"the printed test")
    world.reader.texts[source] = "Assessment: PS9-FORCES-01\nQ1. An object ..."
    world.ingestor.ingest_document([source], kind="assessment", order_hint=[source],
                                   package_version=world.version)
    declared = world.transcription_requests()[0].get("declared_questions") or ""
    lines = [line.strip() for line in declared.splitlines() if re.match(r"^\s*Q\w+:", line)]
    assert lines == EXPECTED_DECLARED, (
        f"TC-INGEST-56: the test paper's request names {lines!r}.")
    world.close()


# -- TC-REG-15: the live transcript ------------------------------------------------------------------


def test_tc_reg_15_live_tick_boxes_resolve_to_the_ticked_option(tmp_data_dir):
    """`TC-REG-15` (a) — the live S9-002 transcript, verbatim. Its tick boxes now fold to one
    resolved mark per question (Q1=C, Q2=B, Q3=B), so V2 no longer names Q1–Q3. What V2 still
    names is what the v4 prompt never asked for and the live reader therefore never wrote: the
    written answers' tags and the package's sub-question ids. Fails on v4: every box stores as
    `ambiguous` and V2 names Q1, Q2 and Q3."""
    world = _World(tmp_data_dir, "live-verbatim")
    report = world.ingest(LIVE_TRANSCRIPT)
    marks = world.marks(report.document_id)
    for question, option in (("Q1", "C"), ("Q2", "B"), ("Q3", "B")):
        assert marks.get(question) == (("resolved", option),), (
            f"TC-REG-15: the live tick boxes for {question} stored {marks.get(question)!r}, "
            f"expected one resolved mark selecting {option!r}.")
    named = {failure["question_id"] for failure in report.detail.get("v2_failures", [])}
    assert not named & {"Q1", "Q2", "Q3"}, (
        f"TC-REG-15: V2 still names a correctly ticked question: "
        f"{report.detail.get('v2_failures')!r}.")
    assert named <= {"Q4", "Q5", "Q5a", "Q5b"}, (
        f"TC-REG-15: V2 names something other than the untagged answers and Q5: {named!r}.")
    world.close()


@pytest.mark.parametrize("shape", ["tick_boxes_with_v5_ids", "v5_conformant"])
def test_tc_reg_15_a_correct_reading_of_s9_002_is_accepted(tmp_data_dir, shape):
    """`TC-REG-15` (b) — the same reading with the ids the v5 request supplies is accepted:
    every gate passes, status `ok`, and the stored selections are the ticked options — both when
    the reader obeys the v5 mark rule and when it still writes one region per printed option.
    The tick-box shape fails on v4 (every box `ambiguous`, V2 fails)."""
    world = _World(tmp_data_dir, f"accepted-{shape}")
    transcript = (_live_with_v5_ids(LIVE_TRANSCRIPT) if shape == "tick_boxes_with_v5_ids"
                  else V5_CONFORMANT)
    report = world.ingest(transcript)
    assert report.gates == {"v0": "pass", "v1": "pass", "v2": "pass", "v3": "pass",
                            "v4": "match"}, (
        f"TC-REG-15 ({shape}): gates {report.gates!r}, V2 findings "
        f"{report.detail.get('v2_failures')!r}, V4 {report.v4_signals.get('structural')!r}.")
    assert report.ingest_status == "ok"
    assert world.marks(report.document_id) == {
        "Q1": (("resolved", "C"),), "Q2": (("resolved", "B"),),
        "Q3": (("resolved", "B"),), "Q5a": (("resolved", "A"),)}
    world.close()


# -- TC-INGEST-57: the tick-box fold decision table --------------------------------------------------


def _boxes(question_id: str, ticks: dict[str, str], extra: str = "",
           declared: str = "resolved") -> str:
    """One mark region per printed option, as the live reader wrote them — each tagged
    `resolved`, which is what it did; `declared=""` gives boxes with no declared state."""
    state = f" selection_state={declared}" if declared else ""
    return "\n".join(
        f"<!-- region: kind=selection_mark question_id={question_id} conf={0.99 - i / 100}"
        f"{state}{extra} -->\n[{tick}] {option}\n<!-- /region -->"
        for i, (option, tick) in enumerate(ticks.items()))


def _marks_of(transcript: str) -> list[dict]:
    return [region for region in _parse_regions(transcript, "h" * 64, 1, 0, "submission")
            if region["region_kind"] == "selection_mark"]


@pytest.mark.parametrize("ticks, declared, state, selection, content_state", [
    ({"A": " ", "B": " ", "C": "X", "D": " "}, "resolved", "resolved", "C", "present"),
    ({"A": "x", "B": " ", "C": " "}, "resolved", "resolved", "A", "present"),
    ({"A": " ", "B": "✓", "C": " "}, "resolved", "resolved", "B", "present"),
    ({"A": "X", "B": " ", "C": "X", "D": " "}, "resolved", "multiple_marks", None, "present"),
    # The reader said it saw a resolved mark yet ticked no box: unreadable, never blank.
    ({"A": " ", "B": " ", "C": " ", "D": " "}, "resolved", "ambiguous", None, "present"),
    ({"A": " ", "B": " ", "C": " ", "D": " "}, "", None, None, "blank"),
    # A box the reader itself called ambiguous makes the whole mark ambiguous.
    ({"A": " ", "B": "X", "C": " "}, "ambiguous", "ambiguous", None, "present"),
])
def test_tc_ingest_57_a_run_of_tick_boxes_folds_to_one_mark(ticks, declared, state, selection,
                                                             content_state):
    """`TC-INGEST-57` — a run of tick-box regions for one question becomes ONE mark: one ticked
    box resolves to it, two or more are `multiple_marks`, none is a blank answer unless the
    reader claimed a resolved mark it did not tick (`ambiguous`). `selection` is set only when
    resolved (CT-INGEST-05); the folded body keeps every box as read, and its confidence is the
    run's lowest."""
    marks = _marks_of(_boxes("Q1", ticks, declared=declared))
    assert len(marks) == 1, f"TC-INGEST-57: {len(marks)} mark regions, expected one."
    mark = marks[0]
    assert (mark["selection_state"], mark["selection"], mark["content_state"]) == (
        state, selection, content_state)
    assert (mark["selection"] is not None) == (mark["selection_state"] == "resolved")
    for option in ticks:
        assert f"] {option}" in mark["content"], "TC-INGEST-57: a box was dropped."
    assert mark["ocr_conf"] == pytest.approx(0.99 - (len(ticks) - 1) / 100)


@pytest.mark.parametrize("transcript, expected", [
    # A well-formed mark is never touched, whatever follows it.
    (_mark("Q1", "resolved", "C") + "\n" + _mark("Q2", "resolved", "B"),
     [("Q1", "resolved", "C"), ("Q2", "resolved", "B")]),
    # A run that already names its selection is the model's own reading, not tick boxes.
    (_boxes("Q1", {"A": " ", "B": "X"}, extra=" selection=B"),
     [("Q1", "resolved", "B"), ("Q1", "resolved", "B")]),
    # A body that is not a tick box is not folded.
    (_mark("Q1", "ambiguous") + "\n" + _mark("Q1", "ambiguous"),
     [("Q1", "ambiguous", None), ("Q1", "ambiguous", None)]),
    # Boxes of different questions never merge.
    (_boxes("Q1", {"A": "X"}) + "\n" + _boxes("Q2", {"A": " ", "B": "X"}),
     [("Q1", "resolved", "A"), ("Q2", "resolved", "B")]),
    # Several boxes in one region are not ONE box: reading only the first would turn a
    # double mark into a clean answer.
    ("<!-- region: kind=selection_mark question_id=Q1 selection_state=resolved -->\n"
     "[X] A   [X] C\n<!-- /region -->", [("Q1", "ambiguous", None)]),
    ("<!-- region: kind=selection_mark question_id=Q1 selection_state=resolved -->\n"
     "[ ] A [ ] B [X] C [ ] D\n<!-- /region -->", [("Q1", "ambiguous", None)]),
    # A box carrying a note reports more than a tick: the run is not folded.
    (_boxes("Q1", {"A": " ", "B (circled)": " ", "C": " "}),
     [("Q1", "ambiguous", None)] * 3),
    # A word-length "id" is printed option text, not an option id.
    (_boxes("Q1", {"Option": "X", "Other": " "}),
     [("Q1", "ambiguous", None)] * 2),
])
def test_tc_ingest_57_what_is_not_a_tick_box_run_is_left_alone(transcript, expected):
    """`TC-INGEST-57` (the boundary) — only an unambiguous run of tick boxes folds."""
    found = [(m["element_kind"], m["selection_state"], m["selection"])
             for m in _marks_of(transcript)]
    assert found == expected


def test_tc_reg_15_a_v5_live_sheet_matches_its_test_paper(tmp_data_dir):
    """`TC-REG-15` (c) — the second live run's v5 transcripts, with the printed test paper read
    into the store first, as `aeh ingest --assessment` does. The reader followed v5 exactly
    (one mark per question with `selection=`, tagged answers, `Q5a`/`Q5b`), and S9-001 still
    parked: the paper's regions carry no question tags, so the semantic signal falls back to a
    whole-paper comparison — which compared only the sheet's TAGGED answers with the entire
    test paper (0.07, under the 0.10 floor). Whole paper against whole paper it is 0.28, while
    the wrong-test sheet stays at 0.03 and is still a mismatch. Fails before that fix: S9-001's
    semantic signal is `mismatch` and the gate `uncertain`."""
    world = _World(tmp_data_dir, "v5-semantic")
    paper = world.blobs.put(b"the printed PS9 test paper")
    world.reader.texts[paper] = LIVE_V5_TEST_PAPER
    world.ingestor.ingest_document([paper], kind="assessment", order_hint=[paper],
                                   package_version=world.version)

    good = world.ingest(LIVE_V5_S9_001)
    semantic = good.v4_signals["semantic"]
    assert semantic["signal"] == "match" and semantic["score"] >= 0.2, (
        f"TC-REG-15 (c): a correctly answered v5 sheet reads as another test: {semantic!r}.")
    assert good.gates == {"v0": "pass", "v1": "pass", "v2": "pass", "v3": "pass",
                          "v4": "match"}, (good.gates, good.v4_signals)
    assert good.ingest_status == "ok"
    assert world.marks(good.document_id) == {
        "Q1": (("resolved", "C"),), "Q2": (("resolved", "B"),),
        "Q3": (("resolved", "B"),), "Q5a": (("resolved", "B"),)}

    wrong = world.ingest(LIVE_V5_S9_005)
    assert wrong.v4_signals["semantic"]["signal"] == "mismatch", wrong.v4_signals["semantic"]
    assert (wrong.gates["v4"], wrong.ingest_status) == ("mismatch", "unmatched_assessment")
    world.close()
