"""Span verification: is each span's text really in the document, byte for byte."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# --- the duck-typed reads (a fault is a value: None means "could not read") -----------------------

#: The sentinel a gate read returns when the view itself faulted — distinct from
#: `None`, which for the second family means "no second extraction ran", a
#: measured absence the tri-state must preserve.
_FAULT = object()


def _document_raw_bytes(doc: Any) -> "bytes | None":
    """The document's canonical bytes, from whatever form the caller passed.

    A plain `str` IS the Markdown; bytes/bytearray are taken as-is; anything
    with a `.markdown` attribute (or a mapping under the `"markdown"` key)
    contributes that value's bytes. Anything else — including a read that
    raises — is a fault: `None`, and the caller treats the document as unread.
    """
    try:
        if isinstance(doc, (bytes, bytearray)):
            return bytes(doc)
        if isinstance(doc, str):
            return doc.encode("utf-8")
        markdown = getattr(doc, "markdown", None)
        if markdown is None and isinstance(doc, dict):
            markdown = doc.get("markdown")
        if isinstance(markdown, (bytes, bytearray)):
            return bytes(markdown)
        if isinstance(markdown, str):
            return markdown.encode("utf-8")
    except Exception:
        return None
    return None


def _span_item(span: Any) -> "tuple[int, int, bytes] | None":
    """One span as `(start, end, text_bytes)`, or None when it is malformed."""
    try:
        if isinstance(span, dict):
            start = span.get("start")
            end = span.get("end")
            text = span.get("text")
        else:
            start = getattr(span, "start", None)
            end = getattr(span, "end", None)
            text = getattr(span, "text", None)
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        if isinstance(text, str):
            return (start, end, text.encode("utf-8"))
        if isinstance(text, (bytes, bytearray)):
            return (start, end, bytes(text))
    except Exception:
        return None
    return None


def _span_items(spans: Any) -> "list[tuple[int, int, bytes]] | None":
    """A list of spans as items, or None if any span is malformed."""
    if isinstance(spans, (str, bytes, bytearray)):
        return None
    try:
        candidate = tuple(spans)
    except Exception:
        return None
    items: "list[tuple[int, int, bytes]]" = []
    for span in candidate:
        item = _span_item(span)
        if item is None:
            return None
        items.append(item)
    return items


def _region_items(regions: Any) -> "tuple[tuple[Any, int, int, Any, Any], ...] | None":
    """The regions as `(region_kind, start, end, ocr_conf, crop_ref)` tuples, or None if malformed.
    """
    if isinstance(regions, (str, bytes, bytearray)):
        return None
    try:
        candidate = tuple(regions)
    except Exception:
        return None
    items: "list[tuple[Any, int, int, Any, Any]]" = []
    for region in candidate:
        if isinstance(region, dict):
            kind = region.get("region_kind")
            start = region.get("start")
            end = region.get("end")
            conf = region.get("ocr_conf")
            crop = region.get("crop_ref")
        else:
            kind = getattr(region, "region_kind", None)
            start = getattr(region, "start", None)
            end = getattr(region, "end", None)
            conf = getattr(region, "ocr_conf", None)
            crop = getattr(region, "crop_ref", None)
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        items.append((kind, start, end, conf, crop))
    return tuple(items)


# --- the pure verifier (TC-INTEG-01/09, FUZZ-03, CT-INTEG-01) --------------------------------------


def verify_span(doc: Any, span: Any) -> bool:
    """Whether the span's bytes appear, exactly, in the document's canonical bytes.

    Pure, deterministic, zero-cost: a function of the document BYTES handed to
    it and the span's byte offsets — no store, no model, no network, and it
    never raises (a malformed document or span verifies False, NFR-INTEG-03's
    fail-closed reading applied to a pure function). The verdict is exactly the
    shared invariant: `0 <= start <= end <= len(raw)` AND
    `raw[start:end] == text.encode("utf-8")` — so a zero-length span at any
    in-bounds offset verifies, a span ending one byte past the document does
    not, and a boundary landing mid-codepoint is rejected rather than repaired.
    """
    try:
        raw = _document_raw_bytes(doc)
        if raw is None:
            return False
        item = _span_item(span)
        if item is None:
            return False
        start, end, text_bytes = item
        if start < 0 or end < start or end > len(raw):
            return False
        return raw[start:end] == text_bytes
    except Exception:
        return False


# --- region markup and quote-anchored relocation (FR-INTEG-13/14, CT-INTEG-19/20) ------------------


@dataclass(frozen=True)
class Span:
    """A byte span of the canonical document and the text it addresses: what `relocate_span` and
    `answer_regions` return. `verify_span(doc, span)` holds for every `Span` they return."""

    start: int
    end: int
    text: str


#: The ingest region-marker protocol (`aeh.ingest`'s `REGION_OPEN` / `REGION_CLOSE`), restated here
#: as bytes rather than imported: M-INTEG certifies what the extractor produced and shares no code
#: path with the modules that produce it (CT-INTEG-05). A header is `<!-- region: ... -->` with its
#: attributes; the close is exactly `<!-- /region -->`.
_REGION_HEADER = re.compile(rb"<!-- region:[^>]*?-->")


_REGION_CLOSE = b"<!-- /region -->"


#: One whole region: its header, its answer body, its close. The body is the region's answer text.
_REGION_BLOCK = re.compile(
    rb"<!-- region:(?P<header>[^>]*?)-->(?P<body>.*?)" + re.escape(_REGION_CLOSE),
    re.DOTALL,
)


def _marker_extents(raw: bytes) -> "list[tuple[int, int]]":
    """The byte extents of every region marker in the document: headers and closes."""
    extents = [(match.start(), match.end()) for match in _REGION_HEADER.finditer(raw)]
    position = raw.find(_REGION_CLOSE)
    while position != -1:
        extents.append((position, position + len(_REGION_CLOSE)))
        position = raw.find(_REGION_CLOSE, position + 1)
    return extents


def _overlaps_marker(raw: bytes, start: int, end: int) -> bool:
    """Whether the byte range `[start, end)` includes any byte of a region marker. A zero-length
    range includes no byte, so it never overlaps."""
    return any(start < marker_end and marker_start < end
               for marker_start, marker_end in _marker_extents(raw))


def _offsets_of(item: Any) -> "tuple[int, int] | None":
    """`(start, end)` from a mapping or an object with integer offsets, or None."""
    if isinstance(item, dict):
        start, end = item.get("start"), item.get("end")
    else:
        start, end = getattr(item, "start", None), getattr(item, "end", None)
    if (isinstance(start, int) and isinstance(end, int)
            and not isinstance(start, bool) and not isinstance(end, bool)):
        return (start, end)
    return None


def clear_of_region_markup(doc: Any, span: Any) -> bool:
    """Whether the span includes no byte of an ingest region marker (FR-INTEG-14, CT-INTEG-20).

    The companion predicate to `verify_span`, which stays the strict byte-equality check
    (FR-INTEG-01): a citation is accepted only when both hold. A span ending exactly where a
    marker begins, or starting exactly where one ends, is clear; one byte into either side is
    not. Pure and never raises: an unreadable document or a malformed span is not clear
    (fail-closed, like `verify_span`)."""
    try:
        raw = _document_raw_bytes(doc)
        offsets = _offsets_of(span)
        if raw is None or offsets is None:
            return False
        return not _overlaps_marker(raw, *offsets)
    except Exception:
        return False


def _declared_question(header: bytes) -> "bytes | None":
    """The `question_id=` value a region header declares, or None."""
    for token in header.split():
        if token.startswith(b"question_id="):
            return token[len(b"question_id="):] or None
    return None


def answer_regions(doc: Any, question_id: str) -> "tuple[Span, ...]":
    """The answer text of the question's regions, in document order.

    A region belongs to the question in force, the way ingest attributes it
    (`aeh.ingest`'s region parser): a region tagged `question_id=<question_id>` and every
    untagged region after it (a continuation line, the described diagram), up to the next
    region tagged with another question. Untagged regions before any tag belong to no question.
    Ingest restarts the question in force on each page; the canonical document carries no
    page boundary this reader can see, so an answer continuing onto the next page stays with
    its question until another question is tagged.

    Each `Span` covers a region's BODY only (the bytes between its header's `-->` and its
    `<!-- /region -->`), so no marker byte is inside it. This is the `region` the judge hands
    `relocate_span` (ADR-63). A document with no region for the question gives the empty
    tuple, and a relocation scoped to it finds nothing. Pure and never raises."""
    try:
        raw = _document_raw_bytes(doc)
        if raw is None or not isinstance(question_id, str) or not question_id:
            return ()
        wanted = question_id.encode("utf-8")
        in_force: "bytes | None" = None
        regions: list[Span] = []
        for match in _REGION_BLOCK.finditer(raw):
            declared = _declared_question(match.group("header"))
            if declared is not None:
                in_force = declared
            if in_force != wanted:
                continue
            start, end = match.start("body"), match.end("body")
            try:
                text = raw[start:end].decode("utf-8")
            except UnicodeDecodeError:
                continue
            regions.append(Span(start=start, end=end, text=text))
        return tuple(regions)
    except Exception:
        return ()


def _region_extents(region: Any) -> "list[tuple[int, int]] | None":
    """The byte extents a `region` argument names: None for no region (search the whole document),
    one extent for an object or mapping with integer `start`/`end`, or one per member of a sequence
    of them. A malformed member contributes nothing, so a bad region narrows the search to nothing
    rather than widening it to the document."""
    if region is None:
        return None
    single = _offsets_of(region)
    if single is not None:
        return [single]
    if isinstance(region, (str, bytes, bytearray, dict)):
        return []
    try:
        members = tuple(region)
    except TypeError:
        return []
    return [found for found in (_offsets_of(member) for member in members) if found is not None]


def relocate_span(doc: Any, span: Any, region: Any = None) -> "Span | None":
    """The span over the UNIQUE occurrence of `span`'s quoted text, or None (FR-INTEG-13).

    For a citation whose offsets are wrong but whose words are the document's own (a model
    cannot count bytes, ADR-54). The search is byte-exact (no case folding, no whitespace or
    Unicode normalization), so forgery protection is unchanged: the returned span's bytes ARE
    the quoted text, and `verify_span(doc, result)` holds.

    `region` scopes the search (ADR-63, D7). With the unit's region (a `Span`, or anything with
    integer `start`/`end` byte offsets of its answer text, or a sequence of them) only
    occurrences lying wholly inside it count, so a quote found only in another question's
    answer is None. With `region=None` the whole document is searched (callers without a
    region).

    None when the text is missing or empty, occurs zero times or more than once (overlapping
    occurrences count: a relocation is never a guess), or when the unique occurrence includes
    region-marker bytes (FR-INTEG-14). Pure, model-free, zero-cost and never raises, like
    `verify_span` (CT-INTEG-19); `verify_span` itself is unchanged."""
    try:
        raw = _document_raw_bytes(doc)
        if raw is None:
            return None
        text = span.get("text") if isinstance(span, dict) else getattr(span, "text", None)
        if not isinstance(text, str) or not text:
            return None
        needle = text.encode("utf-8")
        extents = _region_extents(region)
        if extents is None:
            extents = [(0, len(raw))]
        hits: set[int] = set()
        for low, high in extents:
            low, high = max(low, 0), min(high, len(raw))
            position = raw.find(needle, low)
            while position != -1 and position + len(needle) <= high:
                hits.add(position)
                if len(hits) > 1:
                    return None
                position = raw.find(needle, position + 1)
        if len(hits) != 1:
            return None
        start = hits.pop()
        end = start + len(needle)
        if _overlaps_marker(raw, start, end):
            return None
        return Span(start=start, end=end, text=text)
    except Exception:
        return None
