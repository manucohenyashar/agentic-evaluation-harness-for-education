"""Turning the model's reply into spans, checked against the document's regions."""

from __future__ import annotations

import json
import re
from typing import Any, Sequence

from aeh.ingest import REGION_CLOSE, REGION_KINDS, REGION_OPEN
from aeh.ingest.identity import pseudonymize_name
from aeh.integ import Span, answer_regions, clear_of_region_markup, relocate_span
from aeh.prov import json_from_reply

from .records import ExtractionSpan, _offset_of


# --- reply parsing (FR-EXTRACT-01, NFR-EXTRACT-02, FR-EXTRACT-09) --------------------------------

_REGION_BLOCK = re.compile(
    re.escape(REGION_OPEN)
    + r"(?P<header>[^>]*?)-->"
    + r"(?P<body>.*?)"
    + re.escape(REGION_CLOSE),
    re.DOTALL,
)


def _kind_of(header: str) -> str | None:
    """The region kind a region header declares (`kind=x` among its attributes, in any order). A
    header with no known kind is unusable."""
    for token in header.split():
        if token.startswith("kind="):
            kind = token[len("kind="):]
            return kind if kind in REGION_KINDS else None
    return None


def _region_index(markdown: str, byte_offsets: Sequence[int]) -> tuple:
    """`(start_byte, end_byte, kind)` for each region, in document order. It converts the regex's
    character positions into the byte positions spans use."""
    regions = []
    for match in _REGION_BLOCK.finditer(markdown):
        kind = _kind_of(match.group("header"))
        if kind is None:
            continue
        regions.append((
            byte_offsets[match.start()],
            byte_offsets[match.end()],
            kind,
        ))
    return tuple(regions)


def _answer_texts(markdown: str, byte_offsets: Sequence[int], total: int) -> tuple[Span, ...]:
    """The answer text of every region, in document order: each region's body, from just after its
    header's `-->` to just before its `<!-- /region -->`. A document with no regions is answer text
    throughout (a typed submission carries no region markup)."""
    bodies = tuple(
        Span(start=byte_offsets[match.start("body")], end=byte_offsets[match.end("body")],
             text=match.group("body"))
        for match in _REGION_BLOCK.finditer(markdown)
    )
    return bodies or (Span(start=0, end=total, text=markdown),)


def unit_region(markdown_bytes: bytes, question_id: str | None) -> Any:
    """The answer text an extraction unit's spans are relocated within (FR-EXTRACT-14, ADR-63, the
    judge's rule for its citations): the answer text of the question's regions
    (`answer_regions`); `None` (every region's answer text, `parse_spans`'s default) for a
    criterion with no question or a document with no regions; and nothing, `()`, when the unit's
    question could not be resolved, so an unknown scope narrows the search and never widens it."""
    if question_id is None:
        return ()
    if not question_id or REGION_OPEN.encode("utf-8") not in markdown_bytes:
        return None
    return answer_regions(markdown_bytes, question_id)


def _relocated(markdown_bytes: bytes, quoted: str, region: Any,
               roster_name: Any, student_ref: Any) -> Span | None:
    """The unique occurrence of the quoted words within `region`, or None (FR-INTEG-13).

    The model read the pseudonymized submission (#593), so a quote may carry the student's ref
    where the document holds the roster name: with both known it is tried again with the name
    restored, and accepted only if the found bytes, pseudonymized, are exactly the quote."""
    found = relocate_span(markdown_bytes, {"text": quoted}, region)
    if found is not None:
        return found
    if not (isinstance(roster_name, str) and roster_name and isinstance(student_ref, str)
            and student_ref and student_ref in quoted):
        return None
    found = relocate_span(
        markdown_bytes, {"text": quoted.replace(student_ref, roster_name)}, region)
    if found is None or pseudonymize_name(found.text, roster_name, student_ref) != quoted:
        return None
    return found


def parse_spans(
    reply_text: str,
    markdown_bytes: bytes | None = None,
    *,
    region: Any = None,
    roster_name: Any = None,
    student_ref: Any = None,
) -> tuple[ExtractionSpan, ...]:
    """Turn the model's reply into spans, before anything is stored (NFR-EXTRACT-02).

    The reply is the disclosed format (`span_completion`'s shape): a JSON object with
    a `spans` list of `{start, end, ...}` — a bare list also parses. Every span is
    REFUSED, not clamped or dropped, unless `0 <= start <= end` and — when the
    document's bytes are given — `end <= len(bytes)` and neither boundary splits a
    UTF-8 code point: a clamp would rewrite the address, a silent drop would let the
    caller believe the set held. With the bytes, `text` is DERIVED from what the
    offsets address — a reply's own text can never disagree with its offsets. Without
    them (the pure-conversion mode the schema assertions drive, no document to
    address) the reply's own `text` is taken and the byte-boundary checks cannot
    apply. `region_kind` is the reply's when it supplies one (checked against the
    ingest region kinds), else the region the span sits in per the canonical
    artifact's region headers, else `transcribed_text`.

    With the bytes, every span lands on answer text (FR-EXTRACT-14, CT-EXTRACT-18). The offsets
    are the model's own count (it is asked for byte offsets and the passage, copied), and a model
    cannot count bytes: a span is taken at its offsets only when they address exactly the passage
    it quoted (or it quoted none) AND lie wholly inside one region's answer text, clear of every
    region marker. Otherwise its quoted words are re-anchored to their unique occurrence within
    `region` (the unit's answer text, `unit_region`; `None` means every region's answer text),
    the relocation FR-INTEG-13 applies to judge citations. A span that does neither is refused:
    never stored inside a marker, never given offsets a guess chose.
    """
    try:
        # A fenced or prefaced JSON reply reads as its JSON (TC-REG-16); prose never does.
        reply = json_from_reply(reply_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"extractor reply is not JSON: {error}") from error
    raw_spans = reply.get("spans") if isinstance(reply, dict) else reply
    if not isinstance(raw_spans, list):
        raise ValueError(
            f"extractor reply carries no span list: {type(raw_spans).__name__}"
        )
    regions: tuple = ()
    byte_offsets: list[int] = []
    total: int | None = None
    if markdown_bytes is not None:
        markdown = markdown_bytes.decode("utf-8")
        byte_offsets = [0]
        step = 0
        for char in markdown:
            step += len(char.encode("utf-8"))
            byte_offsets.append(step)
        regions = _region_index(markdown, byte_offsets)
        total = len(markdown_bytes)
        answer_texts = _answer_texts(markdown, byte_offsets, total)
        if region is None:
            region = answer_texts
    spans: list[ExtractionSpan] = []
    for index, raw in enumerate(raw_spans):
        if not isinstance(raw, dict):
            raise ValueError(
                f"extractor reply span {index} is {type(raw).__name__}, not a "
                f"mapping of span fields"
            )
        start = _offset_of(raw.get("start"), where=f"reply span {index} start")
        end = _offset_of(raw.get("end"), where=f"reply span {index} end")
        if markdown_bytes is not None:
            start, end = _anchored(
                index, raw.get("text"), start, end, markdown_bytes, byte_offsets,
                answer_texts, region, roster_name, student_ref)
        if total is not None and not (0 <= start <= end <= total):
            raise ValueError(
                f"reply span {index} [{start}:{end}] violates the span invariant "
                f"over a {total}-byte document — refused, not clamped or dropped"
            )
        if not (0 <= start <= end):
            raise ValueError(
                f"reply span {index} [{start}:{end}] violates the span invariant "
                f"— refused, not clamped or dropped"
            )
        if markdown_bytes is not None and (
            start not in byte_offsets or end not in byte_offsets
        ):
            raise ValueError(
                f"reply span {index} [{start}:{end}] splits a UTF-8 code point — "
                f"refused"
            )
        region_kind = raw.get("region_kind")
        if region_kind is not None and region_kind not in REGION_KINDS:
            raise ValueError(
                f"reply span {index} carries region_kind {region_kind!r}, outside "
                f"{REGION_KINDS}"
            )
        if region_kind is None:
            region_kind = "transcribed_text"
            for region_start, region_end, kind in regions:
                if region_start <= start < region_end:
                    region_kind = kind
                    break
        if markdown_bytes is not None:
            text = markdown_bytes[start:end].decode("utf-8")
        else:
            text = str(raw.get("text", ""))
        spans.append(ExtractionSpan(
            start=start,
            end=end,
            text=text,
            region_kind=region_kind,
        ))
    return tuple(spans)


def _anchored(
    index: int, quoted: Any, start: int, end: int, markdown_bytes: bytes,
    byte_offsets: Sequence[int], answer_texts: tuple[Span, ...], region: Any,
    roster_name: Any, student_ref: Any,
) -> tuple[int, int]:
    """The offsets a reply span is stored at: its own when they address its quote on answer text,
    else its quote's unique occurrence in `region` (FR-EXTRACT-14). A span with no quote keeps its
    offsets, which must then lie on answer text; bounds and code-point checks stay the caller's."""
    if not isinstance(quoted, str) or not quoted:
        quoted = None
    in_bounds = (0 <= start <= end <= len(markdown_bytes)
                 and start in byte_offsets and end in byte_offsets)
    if not in_bounds and quoted is None:
        return start, end  # the caller refuses it with the bounds / code-point message
    on_answer_text = in_bounds and (
        any(text.start <= start and end <= text.end for text in answer_texts)
        and clear_of_region_markup(markdown_bytes, {"start": start, "end": end}))
    if on_answer_text and (
            quoted is None or markdown_bytes[start:end] == quoted.encode("utf-8")):
        return start, end
    if quoted is not None:
        found = _relocated(markdown_bytes, quoted, region, roster_name, student_ref)
        if found is not None:
            return found.start, found.end
        raise ValueError(
            f"reply span {index} [{start}:{end}] does not address its quoted passage on "
            f"the answer text, and the passage has no unique occurrence in the unit's "
            f"answer text to re-anchor to: refused, never stored on region markup or "
            f"at a guessed position (FR-EXTRACT-14)"
        )
    raise ValueError(
        f"reply span {index} [{start}:{end}] lies outside the answer text of the "
        f"document's regions (it includes region markup or crosses a region boundary) "
        f"and quotes no passage to re-anchor: refused (FR-EXTRACT-14)"
    )
