"""Span verification: is each span's text really in the document, byte for byte."""

from __future__ import annotations

from typing import Any


# --- the duck-typed reads (a fault is a value: None means "could not read") -----------------------

#: The sentinel a gate read returns when the view itself faulted — distinct from
#: `None`, which for the second family means "no second extraction ran", a
#: measured absence the tri-state must preserve.
_FAULT = object()


def _document_raw_bytes(doc: Any) -> "bytes | None":
    """The document's canonical bytes, from whatever the caller handed over.

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
    """One span as `(start, end, text_bytes)`, or None when malformed."""
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
    """A span sequence as items, or None on any malformation (a fault)."""
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
    """Regions as `(region_kind, start, end, ocr_conf, crop_ref)`, or None."""
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
    """Whether `span`'s bytes appear verbatim in `doc`'s canonical bytes.

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
