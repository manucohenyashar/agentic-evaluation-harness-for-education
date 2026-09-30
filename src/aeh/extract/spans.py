"""Turning the model's reply into spans, checked against the document's regions."""

from __future__ import annotations

import json
import re
from typing import Sequence

from aeh.ingest import REGION_CLOSE, REGION_KINDS, REGION_OPEN

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


def parse_spans(
    reply_text: str, markdown_bytes: bytes | None = None
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
    """
    try:
        reply = json.loads(reply_text)
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
    spans: list[ExtractionSpan] = []
    for index, raw in enumerate(raw_spans):
        if not isinstance(raw, dict):
            raise ValueError(
                f"extractor reply span {index} is {type(raw).__name__}, not a "
                f"mapping of span fields"
            )
        start = _offset_of(raw.get("start"), where=f"reply span {index} start")
        end = _offset_of(raw.get("end"), where=f"reply span {index} end")
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
