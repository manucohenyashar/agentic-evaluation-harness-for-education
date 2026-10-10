"""Parsing a page transcript into regions, and wrapping student text in untrusted markers."""

from __future__ import annotations

import math
import re
from typing import Any, Sequence

from .settings import _configured_evaluative_terms, _ocr_conf_floor, REGION_KINDS
from .markup import (
    REGION_CLOSE,
    REGION_OPEN,
    STRUCK_CLOSE,
    STRUCK_OPEN,
    SUPERSEDED_PREFIX,
    UNTRUSTED_CLOSE,
    UNTRUSTED_OPEN,
)
from .errors import IngestError


def _evaluative_offences(description: str,
                         terms: Sequence[str] | None = None) -> list[str]:
    """The evaluative words a description contains (FR-INGEST-11): prefix matches against the
    configured list, allowing a negating prefix ("in-", "in", "un") and any suffix."""
    configured = terms if terms is not None else _configured_evaluative_terms()
    lowered = description.lower()
    offences: list[str] = []
    for term in configured:
        stem = term.lower()
        if " " in stem:
            # Multi-word terms match verbatim ("as expected", "should be").
            if stem in lowered:
                offences.append(term)
            continue
        if re.search(r"\b(?:in-?|un)?" + re.escape(stem) + r"\w*", lowered):
            offences.append(term)
    return offences


def _parse_region_attributes(header: str) -> dict[str, str]:
    """Parse region attributes such as `kind=x element_kind=y crop=1,2,3,4` in any order, so a
    model that reorders or adds attributes still parses."""
    attributes: dict[str, str] = {}
    for token in header.split():
        if "=" in token:
            key, _, value = token.partition("=")
            attributes[key.strip().lower()] = value.strip()
    return attributes


_UNTRUSTED_ATTR = re.compile(r"\bis_untrusted_content(?:=\w+)?")


def _wrap_untrusted(body: str) -> str:
    """Wrap one piece of student text in a region marked as data (FR-INGEST-35)."""
    return (f"{REGION_OPEN} kind=transcribed_text is_untrusted_content=1 -->\n"
            f"{body}\n{REGION_CLOSE}")


#: The closing marker's escaped form: visually adjacent to the original, a legal
#: Markdown text span, and byte-different from the terminator the template splits
#: on — so the escaped content stays readable while the boundary stays singular.
_ESCAPED_UNTRUSTED_CLOSE = "<\\/" + UNTRUSTED_CLOSE[2:]


def _fence_untrusted_content(content: str) -> str:
    """Put student text inside the block the prompt declares as data, for the V4 escalation prompt
    (FR-INGEST-35). Every closing marker inside the text is escaped, so the only terminator is the
    harness's own and no student text can step outside the block. (A transcript containing a
    literal closing marker once ended the fence early.) Text without a marker is unchanged."""
    escaped = content.replace(UNTRUSTED_CLOSE, _ESCAPED_UNTRUSTED_CLOSE)
    return f"{UNTRUSTED_OPEN}\n{escaped}\n{UNTRUSTED_CLOSE}"


def _mark_untrusted_content(transcript: str) -> str:
    """Mark all of a submission's transcript as untrusted (FR-INGEST-35), done by the harness
    rather than trusted to the model: every region header gets `is_untrusted_content=1`, and any
    text outside the region markers is wrapped in a marked region. Prompt assembly (M-EXTRACT,
    M-JUDGE) can then enclose it in one delimited block. Setup documents are never marked
    (TC-INGEST-36): they are the teacher's, and marking them would put the answer key inside the
    untrusted block.

    The model is not trusted to have added the marker, and the transform is
    idempotent: a header already carrying the attribute is rewritten to `=1`, not
    appended to. A transcript with an unterminated marker is returned unchanged —
    the parser refuses it as malformed output, and a partial rewrite must not
    precede that refusal."""
    pattern = re.compile(
        re.escape(REGION_OPEN) + r"(?P<header>[^>]*?)-->"
        r"(?P<body>.*?)" + re.escape(REGION_CLOSE),
        re.DOTALL,
    )
    matches = list(pattern.finditer(transcript))
    if not matches:
        if REGION_OPEN in transcript:
            return transcript  # unterminated marker: the parser refuses it as-is
        body = transcript.strip()
        return transcript if not body else _wrap_untrusted(body)

    parts: list[str] = []
    cursor = 0
    for match in matches:
        outside = transcript[cursor:match.start()].strip()
        if outside:
            parts.append(_wrap_untrusted(outside))
        header = match.group("header")
        # The model is not trusted to have emitted a well-formed marker: a bare
        # token, a wrong value or an absent one all rewrite to `=1` (review S1)
        # — strip any occurrence, then append the authoritative one.
        header = f"{_UNTRUSTED_ATTR.sub(' ', header)} is_untrusted_content=1"
        # The canonical spacing (one space between tokens, one each side) is what
        # makes the transform idempotent: a re-run captures this exact header and
        # re-emits it byte-for-byte.
        parts.append(f"{REGION_OPEN} {' '.join(header.split())} -->"
                     f"{match.group('body')}{REGION_CLOSE}")
        cursor = match.end()
    outside = transcript[cursor:].strip()
    if outside:
        parts.append(_wrap_untrusted(outside))
    return "\n".join(parts)


def _parse_regions(transcript: str, source_hash: str, page_no: int,
                   position_start: int, kind_of_page: str) -> list[dict]:
    """Parse one page's transcript into region records.

    The pinned prompt asks the model to wrap every region in the marker protocol. A
    transcript with NO markers is one transcribed_text region (a text-only page is
    the common case, and the protocol is additive). Text OUTSIDE complete markers
    also becomes transcribed_text regions — the Markdown and the region rows must
    describe the same content. A transcript carrying an OPENING marker but no
    complete pair is MALFORMED model output and refuses here rather than storing
    protocol comments as student text (review M3). Struck-through spans become
    regions with `retraction='struck_through'`; a '~~superseded-by' note marks the
    correcting region, whose id the PREVIOUS region then carries as
    `retraction='superseded_by:<region_id>'` — BOTH versions stay (`FR-INGEST-12`,
    review B2)."""
    import uuid as _uuid

    def new_region(position: int, **overrides: Any) -> dict:
        region: dict[str, Any] = {
            "region_id": f"reg-{_uuid.uuid4().hex[:12]}",
            "page_no": page_no,
            "element_kind": "text",
            "region_kind": "transcribed_text",
            "description": None,
            "content": "",
            "retraction": None,
            "ocr_conf": None,
            "content_state": "present",
            "selection_state": None,
            "selection": None,
            "crop_box": None,
            "source_hash": source_hash,
            "page_index": page_no,
            "position": position,
            "is_untrusted_content": 1 if kind_of_page == "submission" else 0,
            "supersedes_previous": False,
        }
        region.update(overrides)
        return region

    regions: list[dict] = []
    pattern = re.compile(
        re.escape(REGION_OPEN) + r"(?P<header>[^>]*?)-->"
        r"(?P<body>.*?)" + re.escape(REGION_CLOSE),
        re.DOTALL,
    )
    matches = list(pattern.finditer(transcript))
    if not matches:
        if REGION_OPEN in transcript:
            raise IngestError(
                f"page {page_no}'s transcript carries an unterminated region marker "
                "— malformed model output (design §3.5's failure taxonomy); the "
                "page refuses rather than storing protocol comments as student text."
            )
        body = transcript.strip()
        if body:
            regions.append(new_region(position_start, content=body))
        # CT-INGEST-04 (#221): the marker-less page backfills TOO — a setup
        # artifact (assessment/reference/rubric) ingests exactly this shape,
        # its transcripts carrying no region protocol at all, so only the
        # submission path (whose transcript the untrusted-content fence wraps
        # into markers) could ever skip the backfill by accident.
        return _backfill_region_conf(regions)

    position = position_start
    cursor = 0
    supersede_requests: list[int] = []
    # `#373`: the question the regions being read now belong to. A transcript names a
    # question once, on the region that carries its text, and everything that follows until
    # the next named question is part of that question — a graphic, a selection mark, a
    # continuation. Carrying it forward here is what lets `document_region.question_id` be a
    # PARSED fact for every region rather than one the reader has to reconstruct from
    # position order. It stays `None` until the transcript names its first question, so a
    # region that genuinely precedes any question (a header, a name field) records no owner
    # instead of being adopted by the first question that happens to follow it.
    current_question: str | None = None
    for match in matches:
        outside = transcript[cursor:match.start()].strip()
        if outside:
            regions.append(new_region(position, content=outside))
            position += 1
        cursor = match.end()
        attributes = _parse_region_attributes(match.group("header"))
        kind = attributes.get("kind", "transcribed_text")
        if kind not in REGION_KINDS:
            raise IngestError(
                f"page {page_no}'s region declares kind {kind!r}, which is not one "
                f"of {REGION_KINDS} — malformed model output."
            )
        # FR-INGEST-15: the per-region reading confidence, as the model tagged it.
        # A non-numeric or NON-FINITE tag is malformed model output — the same
        # refusal taxonomy as a bad kind or state (#221: a raw ValueError used
        # to escape, and `nan` used to pass float() and store as NULL — SQLite
        # has no NaN — reopening the G2 hole through the tagged front door,
        # worse still poisoning `min()` for every region on the page).
        try:
            ocr_conf = (float(attributes["conf"])
                        if attributes.get("conf") else None)
        except ValueError as error:
            raise IngestError(
                f"page {page_no}'s region declares conf "
                f"{attributes['conf']!r}, which is not a number — malformed "
                "model output.") from error
        if ocr_conf is not None and not math.isfinite(ocr_conf):
            raise IngestError(
                f"page {page_no}'s region declares conf "
                f"{attributes['conf']!r}, which is not a finite number — "
                "malformed model output.")
        # FR-INGEST-16: present / blank / absent, as tagged; described_graphic is
        # present by definition.
        content_state = attributes.get("state", "present")
        if content_state not in ("present", "blank", "absent"):
            raise IngestError(
                f"page {page_no}'s region declares content_state "
                f"{content_state!r}, which is not one of present/blank/absent — "
                "malformed model output."
            )
        declared_question = attributes.get("question_id")
        if declared_question:
            current_question = str(declared_question)
        element = declared_question or attributes.get("element_kind") or (
            "text" if kind == "transcribed_text" else "graphic")
        body = match.group("body").strip()
        if not body and "state" not in attributes:
            continue  # a truly empty marker carries nothing to record
        # A tagged-but-empty region (state=blank) is a ROW, not a skip — blank and
        # absent are distinct states (FR-INGEST-16); its body stays empty.
        retraction = None
        struck = re.search(re.escape(STRUCK_OPEN) + r"(.*?)" + re.escape(STRUCK_CLOSE),
                           body, re.DOTALL)
        if struck:
            retraction = "struck_through"
        supersedes = SUPERSEDED_PREFIX in body
        crop_box = None
        if "crop" in attributes:
            parts = attributes["crop"].split(",")
            if len(parts) != 4:
                raise IngestError(
                    f"page {page_no}'s crop attribute {attributes['crop']!r} is not "
                    "x,y,w,h.")
            try:
                crop_box = tuple(int(part) for part in parts)
            except ValueError as error:
                raise IngestError(
                    f"page {page_no}'s crop attribute "
                    f"{attributes['crop']!r} is not x,y,w,h.") from error
        # FR-INGEST-17 / CT-INGEST-05: the stored mark state is HONEST. The
        # transcript's own claim counts only when it is complete — a state
        # outside the triad, a missing state, or `resolved` naming no option is
        # a mark that could NOT be resolved, and stores as `ambiguous` with no
        # selection, never as `resolved` with a NULL selection (the disclosed
        # C05 biconditional hole, #219). An ambiguous or multiple_marks mark is
        # never mapped to an option or to an incorrect answer.
        mark_state: str | None = None
        mark_option: str | None = None
        declared_state = None
        if kind == "selection_mark":
            declared_state = attributes.get("selection_state")
            if declared_state in ("ambiguous", "multiple_marks"):
                mark_state = declared_state
            elif declared_state == "resolved" and attributes.get("selection"):
                mark_state, mark_option = "resolved", attributes["selection"]
            else:
                mark_state = "ambiguous"
        regions.append(new_region(
            position,
            element_kind=element,
            region_kind=kind,
            description=body if kind == "described_graphic" else None,
            content=body,
            retraction=retraction,
            crop_box=crop_box,
            ocr_conf=ocr_conf,
            content_state=(content_state if kind != "described_graphic"
                           else "present"),
            selection_state=(None if kind != "selection_mark"
                             else mark_state),
            # FR-INGEST-17: `selection` is the OPTION the mark resolves to, populated
            # ONLY when resolved — an ambiguous, multiple or unreadable mark is never
            # mapped to an option or to an incorrect answer.
            selection=(None if kind != "selection_mark" else mark_option),
            supersedes_previous=supersedes,
            # The declared question when the region names one, the question in force
            # otherwise — never `element_kind`, which carries the question id only when it
            # was declared and a generic kind the rest of the time.
            question_id=current_question,
            # The state the model wrote, read (and removed) by `_fold_option_marks`.
            _declared_selection_state=declared_state,
        ))
        if supersedes:
            supersede_requests.append(len(regions) - 1)
        position += 1
    outside = transcript[cursor:].strip()
    if outside:
        regions.append(new_region(position, content=outside))
        position += 1
    # B2: each superseding region's id lands on the region it replaces — the earlier
    # version carries 'superseded_by:<the correcting region's id>'.
    for index in supersede_requests:
        if index > 0 and regions[index - 1]["retraction"] is None:
            # A struck-through region's own retraction is the more specific visual
            # fact and is not overwritten by the supersession link.
            regions[index - 1]["retraction"] = (
                f"superseded_by:{regions[index]['region_id']}")
    return _backfill_region_conf(_fold_option_marks(regions, position_start))


#: ONE printed option's tick box as a reader transcribes it: `[X] C`, `[ ] A`,
#: `[✓] B. newton`. Group 1 is the box (empty = unticked), group 2 the option id — a
#: single letter or a one- or two-digit number. Deliberately narrow: a body with a second
#: box (`[X] A [X] C`), a note (`(circled)`, `(crossed out)`), a multi-line body or a
#: word-length id is not ONE plain box, and folding it could hide a second mark or a
#: correction — such a region is left as parsed (unresolved), never read as a box.
_TICK_BOX = re.compile(
    r"^\[\s*([xX✓✔]?)\s*\]\s*([A-Za-z]|\d{1,2})(?:[.):]?(?:\s+[^\[\]()\n]*)?)?$")


def _tick_box(region: dict) -> tuple[bool, str] | None:
    """`(ticked, option id)` when the region is one printed option's tick box with no
    `selection=` of its own — the shape a reader writes when it transcribes the option list
    rather than the mark — else None."""
    if (region["region_kind"] != "selection_mark" or region["selection"] is not None
            or region["retraction"] is not None or region["supersedes_previous"]
            or region["element_kind"] in ("text", "graphic")):
        return None
    match = _TICK_BOX.match((region["content"] or "").strip())
    if match is None:
        return None
    return bool(match.group(1)), match.group(2)


def _fold_option_marks(regions: list[dict], position_start: int) -> list[dict]:
    """Fold each run of tick-box regions for one question into ONE mark (TC-INGEST-57).

    A reader that writes the printed options as separate mark regions (`[ ] A`, `[X] C`, …)
    has still reported, box by box, what the page shows. Read as written, each box would be a
    mark with no option — `ambiguous` — and the question would never score (TC-REG-15). The
    run becomes the one mark the protocol asks for, decided only from the boxes: exactly one
    ticked → `resolved` with that option; two or more → `multiple_marks`; none → a blank
    answer, unless the reader called a box `resolved` (it saw a mark it did not draw as a
    tick), which is `ambiguous`.
    A box the reader itself called `ambiguous` or `multiple_marks` carries that state to the
    whole mark. Nothing is guessed: `selection` is set only when resolved (CT-INGEST-05), every
    box stays in the body as read, and the confidence is the run's lowest. Anything that is not
    an unbroken run of tick boxes under one declared question is left exactly as parsed.
    The folded region records `folded_boxes`, so the stage detail can say it happened."""
    folded: list[dict] = []
    index = 0
    while index < len(regions):
        region = regions[index]
        box = _tick_box(region)
        if box is None:
            folded.append(region)
            index += 1
            continue
        run = [(region, box)]
        while index + len(run) < len(regions):
            following = regions[index + len(run)]
            following_box = _tick_box(following)
            if (following_box is None
                    or following["element_kind"] != region["element_kind"]):
                break
            run.append((following, following_box))
        index += len(run)
        declared = {member.get("_declared_selection_state") for member, _ in run}
        ticked = [option for _, (is_ticked, option) in run if is_ticked]
        mark = dict(region)
        if "multiple_marks" in declared or len(ticked) > 1:
            state, selection = "multiple_marks", None
        elif "ambiguous" in declared:
            state, selection = "ambiguous", None
        elif len(ticked) == 1:
            state, selection = "resolved", ticked[0]
        elif "resolved" in declared:
            # No box ticked, yet the reader said it saw a resolved mark: it saw something
            # it did not draw as a tick (a circle, an odd glyph). Unreadable, never blank —
            # a blank scores as no answer (FR-INGEST-17).
            state, selection = "ambiguous", None
        else:
            state, selection = None, None
        confs = [member["ocr_conf"] for member, _ in run if member["ocr_conf"] is not None]
        mark.update(
            content="\n".join(member["content"].strip() for member, _ in run),
            ocr_conf=min(confs) if confs else None,
            content_state="present" if (ticked or state is not None) else "blank",
            selection_state=state,
            selection=selection,
            folded_boxes=len(run),
        )
        folded.append(mark)
    for offset, region in enumerate(folded):
        region.pop("_declared_selection_state", None)
        region["position"] = position_start + offset
    return folded


def _backfill_region_conf(regions: list[dict]) -> list[dict]:
    """Give every stored region an `ocr_conf` value (CT-INGEST-04). The model only tags confidence
    inside region markers, so text outside them (such as the `Student:` and `Assessment:` header)
    and untagged regions arrive with none. They get the page's lowest tagged confidence, the
    cautious choice: an unvouched reading is treated as no better than the page's worst vouched
    one. A page with no tagged confidence at all records the floor itself, which does not flag the
    submission by itself."""
    tagged_confs = [region["ocr_conf"] for region in regions
                    if region["ocr_conf"] is not None]
    fallback = min(tagged_confs) if tagged_confs else _ocr_conf_floor()
    for region in regions:
        if region["ocr_conf"] is None:
            region["ocr_conf"] = fallback
    return regions
