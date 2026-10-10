"""`TC-REG-16`, `TC-INGEST-58` — inline header markers, and the reply formats the extractor and
the judge are told.

Inline defect regression (test plan §6.9). The third live run (2026-10-10, cohort
`ps9-class-2`, after the v5 transcription fix) found two more defects:

- **Intake.** On S9-005 the reader wrote its header lines with the region marker on the same
  line — `<!-- region: … -->Assessment: ENG7-READ-01<!-- /region -->`. The header readers were
  line-anchored, so the paper read as naming no test and no student: V4 said `uncertain`
  instead of `mismatch`, the operator was told "no student identity found", and — the same
  parse feeding `redact_identity_head` — the written name reached a model request unredacted.
- **Grading.** Every extraction of a written answer failed: the extraction directive never
  stated the reply format, and the live extractor answered in prose ("…half-open range:
  **[1610, 1835)**."). The judge directive had the same gap — "the reply fields in their
  pinned order", with the five field names rendered nowhere. Every parser also refused a
  reply wrapped in a ```json fence.

`data/reg_16_live_s9_005_inline_headers.md` is that run's stored transcript of
`S9-005-wrong-test.pdf`, verbatim (synthetic sample sheet, made-up student).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.regression.test_reg_15_transcription_protocol import _World

DATA = Path(__file__).parent / "data"
LIVE_S9_005_INLINE = (DATA / "reg_16_live_s9_005_inline_headers.md").read_text(encoding="utf-8")
LIVE_V5_TEST_PAPER = (DATA / "reg_15_live_v5_test_paper.md").read_text(encoding="utf-8")

#: The live extractor's reply, verbatim (run 3, S9-001's C4 replayed).
LIVE_PROSE_REPLY = ("Zero-based byte offsets within the untrusted-content block, using a "
                    "half-open range: **[1610, 1835)**.")


# -- TC-INGEST-58: header lines with inline region markers -------------------------------------------


@pytest.mark.parametrize("line", [
    "Assessment: ENG7-READ-01",
    "<!-- region: kind=transcribed_text conf=0.99 -->Assessment: ENG7-READ-01",
    "Assessment: ENG7-READ-01<!-- /region -->",
    "<!-- region: kind=transcribed_text conf=0.99 is_untrusted_content=1 -->"
    "Assessment: ENG7-READ-01<!-- /region -->",
    "  <!-- region: kind=transcribed_text -->  Assessment:  ENG7-READ-01  <!-- /region -->  ",
])
def test_tc_ingest_58_the_test_name_is_read_beside_inline_markers(line):
    """`TC-INGEST-58` — the printed test name is read whether or not the region marker shares
    its line, and the marker is never part of the name."""
    from aeh.ingest.submissions import SubmissionIngestionMixin

    named = SubmissionIngestionMixin._extract_assessment_identifier(f"{line}\nQ1. Something\n")
    assert named == "ENG7-READ-01", f"TC-INGEST-58: read {named!r} from {line!r}."


@pytest.mark.parametrize("line, name", [
    ("Student: Amara Okafor", "Amara Okafor"),
    ("**Student:** Amara Okafor", "Amara Okafor"),
    ("<!-- region: kind=transcribed_text conf=0.99 -->Student: Amara Okafor", "Amara Okafor"),
    ("Student: Amara Okafor<!-- /region -->", "Amara Okafor"),
    ("<!-- region: kind=transcribed_text is_untrusted_content=1 -->Student: Amara Okafor"
     "<!-- /region -->", "Amara Okafor"),
    # A marker between the label and the name, and markers inside the name: read without them.
    ("Student: <!-- region: name -->Amara Okafor<!-- /region -->", "Amara Okafor"),
    ("**Student:** <!-- r -->Amara Okafor<!-- /r -->", "Amara Okafor"),
    ("Student: Amara <!-- uncertain --> Okafor<!-- /region -->", "Amara Okafor"),
])
def test_tc_ingest_58_the_student_name_is_read_and_redacted_beside_inline_markers(line, name):
    """`TC-INGEST-58` — the `Student:` head is read beside inline markers, and the SAME parse
    redacts it: the written name never survives `redact_identity_head` (NFR-PROV-04,
    CT-INGEST-23), and the markers around it are kept."""
    from aeh.ingest.identity import redact_identity_head, written_identity

    markdown = f"Assessment: PS9-FORCES-01\n{line}\nQ1. Something\n"
    assert written_identity(markdown)[0] == name
    redacted = redact_identity_head(markdown, "r-123")
    assert "Okafor" not in redacted and "Amara" not in redacted, (
        f"TC-INGEST-58: the written name survived redaction: {redacted!r}.")
    assert "Q1. Something" in redacted, "redaction reached past the head line"


@pytest.mark.parametrize("markdown, kept", [
    # A bare label never adopts a next line that opens a region: it may be student work.
    ("Student:\n<!-- region: kind=transcribed_text -->The mitochondria is the powerhouse.\n",
     "The mitochondria is the powerhouse."),
    # A label whose only value is a marker keeps the next line out of it.
    ("Student: <!-- illegible -->\nQuestion 1: The answer\n", "Question 1: The answer"),
])
def test_tc_ingest_58_redaction_never_takes_student_work(markdown, kept):
    """`TC-INGEST-58` — the head's value is found on its own line; a line of student work is
    never read as a name nor redacted as one."""
    from aeh.ingest.identity import redact_identity_head

    assert kept in redact_identity_head(markdown, "r-123")


def test_tc_ingest_58_marker_heavy_lines_parse_in_linear_time():
    """`TC-INGEST-58` — a transcript line packed with markers cannot stall the header parse
    (the tempered, bounded marker: no catastrophic backtracking)."""
    import time

    from aeh.ingest.identity import redact_identity_head, written_identity
    from aeh.ingest.submissions import SubmissionIngestionMixin

    for line in ("Student: x" + "<!--a-->" * 4000 + "y", "Student: " + "<!--" * 20000,
                 "Assessment: " + "<!--" * 20000, "Student:\nx" + "<!--a-->" * 4000 + "y"):
        started = time.perf_counter()
        written_identity(line)
        redact_identity_head(line, "r-1")
        SubmissionIngestionMixin._extract_assessment_identifier(line)
        assert time.perf_counter() - started < 2.0, f"slow on a {len(line)}-char line"


def test_tc_reg_16_live_inline_header_sheet_is_named_the_wrong_test(tmp_data_dir):
    """`TC-REG-16` (a) — the live S9-005 transcript, verbatim, against the PS9 test paper: the
    identifier reads `ENG7-READ-01`, the student `S9-005`, all three right-test signals disagree,
    so the gate says `mismatch` and the sheet is `unmatched_assessment`. Before the fix: no test
    name, no student, V4 `uncertain`, status `incomplete`."""
    world = _World(tmp_data_dir, "inline-headers")
    paper = world.blobs.put(b"the printed PS9 test paper")
    world.reader.texts[paper] = LIVE_V5_TEST_PAPER
    world.ingestor.ingest_document([paper], kind="assessment", order_hint=[paper],
                                   package_version=world.version)
    report = world.ingest(LIVE_S9_005_INLINE)
    identifier = report.v4_signals["identifier"]
    assert identifier.get("printed") == "ENG7-READ-01", identifier
    assert report.gates["v3"] == "pass", (
        f"TC-REG-16: the `Student:` head beside its marker was not read: {report.gates!r}.")
    assert (report.gates["v4"], report.ingest_status) == ("mismatch", "unmatched_assessment"), (
        report.gates, report.v4_signals)
    world.close()


# -- TC-REG-16 (b): the extraction reply format ------------------------------------------------------


def test_tc_reg_16_the_extraction_directive_states_the_reply_format():
    """`TC-REG-16` (b) — the extraction request tells the model the exact reply: JSON only, a
    `spans` list of `start`/`end` byte offsets, and where the offsets are counted from. Fails
    before the fix: the directive said only "Reply with the byte offsets"."""
    from aeh.extract.prompt import _DIRECTIVE
    from aeh.ingest import UNTRUSTED_OPEN

    assert re.search(r"JSON only", _DIRECTIVE), _DIRECTIVE
    for token in ('"spans"', '"start"', '"end"'):
        assert token in _DIRECTIVE, f"TC-REG-16: the directive never names {token}."
    assert '{"spans": []}' in _DIRECTIVE, "the empty answer is not shown"
    assert UNTRUSTED_OPEN in _DIRECTIVE and "newline" in _DIRECTIVE, (
        "TC-REG-16: the directive does not say where the offsets are counted from.")


@pytest.mark.parametrize("reply", [
    '{"spans": [{"start": 2, "end": 7, "text": "llo w"}]}',
    '```json\n{"spans": [{"start": 2, "end": 7, "text": "llo w"}]}\n```',
    '```\n{"spans": [{"start": 2, "end": 7}]}\n```',
    'Here are the spans:\n{"spans": [{"start": 2, "end": 7}]}',
])
def test_tc_reg_16_an_extraction_reply_in_json_parses_fenced_or_not(reply):
    """`TC-REG-16` (b) — a JSON reply parses with or without a code fence or a leading sentence;
    the span text is still derived from the offsets, never taken from the reply."""
    from aeh.extract.spans import parse_spans

    spans = parse_spans(reply, b"hello world")
    assert [(s.start, s.end, s.text) for s in spans] == [(2, 7, "llo w")]


@pytest.mark.parametrize("reply", [
    LIVE_PROSE_REPLY,
    # A sentence ending in a list is not an answer.
    "No passages evidence this criterion. []",
    # Two objects in one reply: neither is chosen.
    'I found {"spans": [{"start": 0, "end": 5}]} but the student also wrote {"x": 1}',
])
def test_tc_reg_16_prose_is_still_refused(reply):
    """`TC-REG-16` (b) — leniency reads ONE JSON object out of a reply; it never reads offsets
    or lists out of prose."""
    from aeh.extract.spans import parse_spans

    with pytest.raises(ValueError, match="not JSON"):
        parse_spans(reply, b"x" * 4000)


# -- TC-REG-16 (c): the judge reply format -----------------------------------------------------------


def test_tc_reg_16_the_judge_directive_names_the_reply_fields_in_order():
    """`TC-REG-16` (c) — the judge request names its five reply fields, in the pinned order, and
    asks for JSON only. Fails before the fix: "the reply fields in their pinned order" with the
    names rendered nowhere."""
    from aeh.judge.prompt import REPLY_FIELDS, _render_directive

    directive = _render_directive()
    positions = [directive.find(f'"{name}"') for name in REPLY_FIELDS]
    assert all(position >= 0 for position in positions), (
        f"TC-REG-16: the judge directive does not name every reply field: {directive!r}.")
    assert positions == sorted(positions), "the fields are not shown in the pinned order"
    assert "JSON only" in directive


def test_tc_reg_16_a_fenced_verdict_parses_and_a_reordered_one_is_still_refused():
    """`TC-REG-16` (c) — a verdict in a ```json fence parses; leniency never relaxes the order
    contract (FR-JUDGE-09)."""
    from aeh.judge import _verdict_of
    from aeh.prov import MalformedResponseError
    from tests.unit.judge import test_ts109_decision_logic as ts109

    request = ts109._request(3)
    ordered = {"cited_spans": [], "evidence_assessment": "the band condition holds: x",
               "evidence_sufficient": True, "band": "Proficient", "self_confidence": 0.7}
    verdict = _verdict_of(f"```json\n{json.dumps(ordered)}\n```", request)
    assert verdict.band == "Proficient"
    reordered = {key: ordered[key] for key in ("band", "cited_spans", "evidence_assessment",
                                               "evidence_sufficient", "self_confidence")}
    with pytest.raises(MalformedResponseError):
        _verdict_of(f"```json\n{json.dumps(reordered)}\n```", request)


def test_tc_reg_16_a_fenced_narrative_parses():
    """`TC-REG-16` — the synthesizer reads the same lenient way."""
    from aeh.synth.prompts import parse_narrative

    narrative, citations = parse_narrative('```json\n{"narrative": "Good.", "citations": ["C4"]}\n```')
    assert (narrative, citations) == ("Good.", ("C4",))
