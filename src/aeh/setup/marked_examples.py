"""The teacher's marked examples: upload, the clean-copy check, the form's bands, the skip.

FR-SETUP-20 (amends FR-SETUP-15): per package version, 1 to 25 answer sheets the teacher has
marked (10 to 15 recommended), with the teacher's band for every judged criterion entered on a
form, never read from the scan. The bands are stored through M-PKG in Tier P (migration P1,
`calibration_example_mark`). The step is recommended and never blocks publication: skipping it
records the default taken (FR-SETUP-14).

FR-SETUP-21: the step asks for unmarked copies, and refuses a page whose transcription shows
marking annotations, naming the page. OQ-4 (delta §10 Q7) asked how the marks are detected;
the answer here is **a deterministic check over the stored transcript** (`marked_pages`), not a
new transcriber instruction. Changing the version-pinned transcription prompt would change every
transcript and every recording keyed on it (NFR-INGEST-05), for a step that reads only a handful
of sheets. The check is named and versioned (`CLEAN_COPY_CHECK`) and recorded on the step, so a
later mechanism is a new version, not a silent change.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any, Mapping

from aeh.ingest import DocumentId, PAGE_BREAK
from aeh.pkg import PackageVersionId

from .settings import LOGGER, _now
from .errors import MarkedExampleRefused, SetupOrderError


#: The step's record id on the package version (`setup_step_record`).
MARKED_EXAMPLES_STEP = "marked_examples"


#: FR-SETUP-20's limits: at most this many marked examples per package version. A product
#: limit, not an environment-sensitive constant, so no knob.
MARKED_EXAMPLES_MAX = 25


#: FR-SETUP-20's recommendation, which the teacher is shown beside the limit.
MARKED_EXAMPLES_RECOMMENDED = (10, 15)


#: The clean-copy check's name and version (OQ-4's answer), recorded on the step.
CLEAN_COPY_CHECK = "transcript-marks-v1"


# What the check reads as a marker's annotation on a page of the transcript:
#
# 1. A tick or cross glyph (not a checkbox glyph, which a printed or student box may be)
#    anywhere outside a multiple-choice mark region — a student's chosen option is that
#    region's business, not a marking annotation.
# 2. An awarded score: a fraction standing alone on its line ("3/5", "(2/4)") or a labelled one
#    ("Total: 18/20", "Score 3/5"). Inside a student's answer region (one carrying
#    `question_id=`) a lone fraction counts only beside other answer lines, so a student whose
#    whole answer is "3/5" is not refused. Printed allocations ("(3 marks)") and bare numbers
#    are not scores: every exam paper prints them.
# 3. A described region whose description attributes writing to another hand: the teacher's,
#    the marker's or examiner's, red ink, a second or different hand. A bare "margin" is not
#    enough — students write in margins too.
#
# Known limit: a margin comment the transcriber writes down as plain text, without saying it is
# in another hand, cannot be told from the student's own words on the transcript alone. Closing
# that needs the transcriber to tag annotations (OQ-4's other option, a prompt version bump) —
# a later `CLEAN_COPY_CHECK` version.
_TICK_GLYPHS = frozenset("✓✔✗✘✅❌")

_REGION = re.compile(
    r"<!--\s*region:(?P<attrs>.*?)-->(?P<body>.*?)<!--\s*/region\s*-->", re.DOTALL)

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

_FRACTION = r"\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?"

_LONE_SCORE = re.compile(rf"^\(?\s*{_FRACTION}\s*\)?$")

_LABELLED_SCORE = re.compile(
    rf"^(?:total|score|mark|marks|grade)\b\s*[:=]?\s*\(?\s*{_FRACTION}\s*\)?$",
    re.IGNORECASE,
)

_OTHER_HAND = re.compile(
    r"\b(?:marker'?s?|teacher'?s?|grader'?s?|examiner'?s?|red (?:ink|pen)"
    r"|second hand|different hand(?:writing)?|another hand)\b",
    re.IGNORECASE,
)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in _COMMENT.sub("\n", text).splitlines() if line.strip()]


def _has_score(text: str, *, answer: bool = False) -> bool:
    lines = _lines(text)
    if any(_LABELLED_SCORE.match(line) for line in lines):
        return True
    lone = [line for line in lines if _LONE_SCORE.match(line)]
    if not answer:
        return bool(lone)
    # In an answer region a lone fraction is a mark only when it stands beside the answer.
    return bool(lone) and len(lone) < len(lines)


def _page_has_marks(page: str) -> bool:
    outside = _REGION.sub("\n", page)
    if _TICK_GLYPHS.intersection(outside) or _has_score(outside):
        return True
    for region in _REGION.finditer(page):
        attrs, body = region.group("attrs"), region.group("body")
        if "kind=selection_mark" in attrs:
            continue
        if _TICK_GLYPHS.intersection(body):
            return True
        if _has_score(body, answer="question_id=" in attrs):
            return True
        if "kind=described_graphic" in attrs and _OTHER_HAND.search(body):
            return True
    return False


def marked_pages(markdown: str) -> tuple[int, ...]:
    """The 1-based numbers of the pages whose transcript shows marking annotations (FR-SETUP-21,
    `CLEAN_COPY_CHECK`): a tick or cross, an awarded score, or writing described as in another
    hand (the marker's, red ink). Pages are the pieces of the canonical Markdown between page-break
    markers, in document order. Empty for a clean copy."""
    pages = str(markdown).split(PAGE_BREAK)
    return tuple(number for number, page in enumerate(pages, start=1)
                 if _page_has_marks(page))


def _file_label(name: str) -> str:
    """The file name the teacher chose, without any folder (no path reaches teacher text)."""
    label = PureWindowsPath(str(name)).name.strip()
    return label or "this file"


def _marked_page_message(offenders: list[tuple[str, int]]) -> str:
    if len(offenders) == 1:
        file_name, page = offenders[0]
        return (f"Page {page} of {file_name} has marks on it. Please upload an unmarked "
                "copy, and enter your marks in the form.")
    pages = " ".join(f"Page {page} of {file_name} has marks on it."
                     for file_name, page in offenders)
    return f"{pages} Please upload unmarked copies, and enter your marks in the form."


def judged_criteria(catalog: Any, v: PackageVersionId) -> dict[str, frozenset[str]]:
    """The criteria the teacher marks by hand, each with the bands it declares: evaluation
    mode `judged`, excluding `evidence_sum` composites, which are never judged themselves
    (their aspects are, FR-JUDGE-38). Deterministic criteria are keyed, not marked."""
    rows = catalog.criteria(v)
    return {
        row["criterion_id"]: frozenset(
            band["band"] for band in catalog.bands(row["criterion_id"]))
        for row in rows
        if row.get("evaluation_mode") == "judged"
        and row.get("score_method") != "evidence_sum"
    }


def check_example_bands(catalog: Any, v: PackageVersionId, bands: Mapping[str, str],
                        file_label: str) -> None:
    """Refuse a marking form that is not a band for every judged criterion, each one a band the
    criterion declares (FR-SETUP-20). `file_label` names the example in the refusal. Raises
    `MarkedExampleRefused` in the teacher's words; a look only, nothing is written. The console's
    examples step checks a form this way before it stores the bands (FR-CONSOLE-87)."""
    judged = judged_criteria(catalog, v)
    if not judged:
        raise MarkedExampleRefused(
            "This test has no parts you mark by hand yet, so there is nothing to enter "
            "on the form. Finish reading the rubric first.")
    not_asked = [criterion_id for criterion_id in bands if criterion_id not in judged]
    if not_asked:
        raise MarkedExampleRefused(
            f"The form for {file_label} gives a mark for "
            f"{len(not_asked)} question part(s) that are marked automatically or are "
            "not on this test. Only the parts you mark by hand need a mark.")
    missing = [criterion_id for criterion_id in judged if criterion_id not in bands]
    if missing:
        raise MarkedExampleRefused(
            f"Enter a mark for every part of {file_label} you mark by hand: "
            f"{len(missing)} of {len(judged)} still need one.")
    unknown = [criterion_id for criterion_id, band in bands.items()
               if band not in judged[criterion_id]]
    if unknown:
        raise MarkedExampleRefused(
            f"{len(unknown)} mark(s) on the form for {file_label} are not one of "
            "the levels that part offers. Choose a level from the list.")


@dataclass(frozen=True)
class MarkedExamplesStep:
    """What the marked-examples step holds after an upload, a marking or a skip (FR-SETUP-20).

    `examples` is every uploaded example as (document id, file name), in upload order;
    `marked` the document ids whose every judged criterion has the teacher's band; `status`
    the step record's status (`uploaded`, `marked` or `default_taken`); `limit` and
    `recommended` the figures the teacher is shown; `clean_copy_check` the mechanism that
    checked the scans (OQ-4)."""

    package_version_id: PackageVersionId
    status: str
    examples: tuple[tuple[str, str], ...]
    marked: tuple[str, ...]
    limit: int = MARKED_EXAMPLES_MAX
    recommended: tuple[int, int] = MARKED_EXAMPLES_RECOMMENDED
    clean_copy_check: str = CLEAN_COPY_CHECK

    @property
    def total(self) -> int:
        """How many marked examples the version holds."""
        return len(self.examples)


class MarkedExamplesMixin:
    """The marked-examples step (FR-SETUP-20/21): upload with the clean-copy check, the form's
    bands per judged criterion, and the skip. Recommended, never blocking (FR-SETUP-14)."""

    def add_marked_examples(
        self, examples: Mapping[DocumentId, str],
    ) -> MarkedExamplesStep:
        """Add marked examples to the draft: `examples` maps each ingested document's id to the
        file name the teacher uploaded it as (the name the refusal shows).

        Everything is checked before anything is stored, so a refused upload leaves the step
        as it was. The version may hold at most `MARKED_EXAMPLES_MAX` examples across uploads
        (a document already added does not count twice); more is refused naming the limit.
        Each document's stored transcript is then read through M-INGEST and checked for
        marking annotations (`marked_pages`): any page with marks refuses the upload with that
        page named (FR-SETUP-21). Without a document reader bound, the check cannot run, and
        the upload is refused rather than accepted unchecked."""
        v = self._require_draft_version()
        incoming = {str(document_id): _file_label(name)
                    for document_id, name in examples.items()}
        if not incoming:
            raise MarkedExampleRefused(
                "Choose at least one marked example to upload "
                f"(up to {MARKED_EXAMPLES_MAX}; {MARKED_EXAMPLES_RECOMMENDED[0]} to "
                f"{MARKED_EXAMPLES_RECOMMENDED[1]} is enough).")
        record = self._marked_examples_payload(v)
        held = dict(record["examples"])
        total = len(held) + sum(1 for document_id in incoming if document_id not in held)
        if total > MARKED_EXAMPLES_MAX:
            raise MarkedExampleRefused(
                f"You can upload at most {MARKED_EXAMPLES_MAX} marked examples, and this "
                f"would make {total}. {MARKED_EXAMPLES_RECOMMENDED[0]} to "
                f"{MARKED_EXAMPLES_RECOMMENDED[1]} is enough.")
        if self._ingestor is None:
            raise SetupOrderError(
                "marked examples cannot be accepted here: no document reader is bound to "
                "setup, so the clean-copy check (FR-SETUP-21) cannot read the scans — bind "
                "an ingestor over the cohort that holds them.")
        offenders: list[tuple[str, int]] = []
        for document_id, file_name in incoming.items():
            markdown = self._ingestor.read_document(document_id)
            offenders.extend((file_name, page) for page in marked_pages(markdown))
        if offenders:
            LOGGER.info(
                "refused %d marked example(s) for version %s: %d page(s) carry marks "
                "(FR-SETUP-21, %s)", len(incoming), v, len(offenders), CLEAN_COPY_CHECK,
            )
            raise MarkedExampleRefused(_marked_page_message(offenders),
                                       marked_pages=tuple(offenders))
        held.update(incoming)
        record["examples"] = list(held.items())
        step = self._write_marked_examples_record(v, record)
        LOGGER.info(
            "accepted %d marked example(s) for version %s; it now holds %d of at most %d "
            "(FR-SETUP-20)", len(incoming), v, step.total, MARKED_EXAMPLES_MAX,
        )
        return step

    def mark_example(
        self, document_id: DocumentId, bands: Mapping[str, str],
    ) -> MarkedExamplesStep:
        """Store the teacher's band for every judged criterion of one uploaded example, as
        entered on the form (FR-SETUP-20). Every judged criterion must have a band, each band
        must be one the criterion declares, and a deterministic criterion is not asked (it is
        keyed, not marked), so naming one is refused. All-or-nothing: a refused form stores
        nothing. Re-marking an example replaces its bands."""
        v = self._require_draft_version()
        document_id = str(document_id)
        record = self._marked_examples_payload(v)
        held = dict(record["examples"])
        if document_id not in held:
            raise SetupOrderError(
                f"document {document_id!r} is not one of this draft's marked examples — "
                "add_marked_examples first; the form marks an uploaded example.")
        check_example_bands(self._catalog, v, bands, held[document_id])
        self._catalog.record_example_marks(
            v, document_id=document_id, bands=dict(bands), marked_at=_now())
        marked = set(record["marked"])
        marked.add(document_id)
        record["marked"] = sorted(marked)
        return self._write_marked_examples_record(v, record)

    def skip_marked_examples(self) -> MarkedExamplesStep:
        """Skip the step explicitly: the default taken is recorded now, and publication proceeds
        exactly as without examples (FR-SETUP-14). A step that already holds examples is not
        overwritten — its record stands."""
        v = self._require_draft_version()
        self._record_marked_examples_default(v)
        return self._marked_examples_step(v)

    def marked_examples(self) -> MarkedExamplesStep:
        """The draft's marked-examples step as stored: what was uploaded, what is marked."""
        return self._marked_examples_step(self._require_draft_version())

    # -- helpers ------------------------------------------------------------------------------

    def _judged_criteria(self, v: PackageVersionId) -> dict[str, frozenset[str]]:
        return judged_criteria(self._catalog, v)

    def _marked_examples_payload(self, v: PackageVersionId) -> dict:
        stored = self._catalog.step_record(v, MARKED_EXAMPLES_STEP)
        payload: dict = {}
        if stored and stored.get("payload"):
            try:
                payload = json.loads(stored["payload"])
            except (TypeError, ValueError):
                payload = {}
        return {
            "examples": [tuple(pair) for pair in payload.get("examples", ())],
            "marked": list(payload.get("marked", ())),
            "status": stored.get("status") if stored else None,
        }

    def _write_marked_examples_record(self, v: PackageVersionId,
                                      record: dict) -> MarkedExamplesStep:
        examples = [list(pair) for pair in record["examples"]]
        marked = [document_id for document_id in record["marked"]
                  if document_id in {pair[0] for pair in examples}]
        status = "marked" if examples and len(marked) == len(examples) else "uploaded"
        self._catalog.record_step(
            v, step_id=MARKED_EXAMPLES_STEP, status=status,
            payload=json.dumps({
                "examples": examples,
                "marked": marked,
                "limit": MARKED_EXAMPLES_MAX,
                "recommended": list(MARKED_EXAMPLES_RECOMMENDED),
                "clean_copy_check": CLEAN_COPY_CHECK,
            }, sort_keys=True),
            recorded_at=_now(),
        )
        return self._marked_examples_step(v)

    def _marked_examples_step(self, v: PackageVersionId) -> MarkedExamplesStep:
        record = self._marked_examples_payload(v)
        return MarkedExamplesStep(
            package_version_id=v,
            status=record["status"] or "not_started",
            examples=tuple((str(a), str(b)) for a, b in record["examples"]),
            marked=tuple(record["marked"]),
        )

    def _record_marked_examples_default(self, v: PackageVersionId) -> bool:
        """Record the step's default when it holds nothing of its own (FR-SETUP-14): no examples,
        so no reference set and no clarifying questions; grading uses the rubric as written. A
        step that already recorded examples is never overwritten. Returns whether a row was
        written."""
        record = getattr(self._catalog, "record_default_step", None)
        if record is None:
            return False
        written = record(
            v, step_id=MARKED_EXAMPLES_STEP, status="default_taken",
            payload=json.dumps({
                "default": (
                    "the marked-examples step was skipped: no marked examples are held, "
                    "so no differences or clarifying questions come from them and the "
                    "package is graded with its rubric as written (FR-SETUP-20, "
                    "FR-SETUP-14)."
                ),
                "examples": [],
                "marked": [],
            }, sort_keys=True),
            recorded_at=_now(),
        )
        if written:
            LOGGER.info(
                "recorded the marked-examples step's default for version %s — the skip "
                "is stored provenance, not silence (FR-SETUP-14)", v,
            )
        return bool(written)
