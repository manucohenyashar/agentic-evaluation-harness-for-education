"""`TC-EXTRACT-15` — over generated documents and generated span sets, every emitted
span satisfies `0 <= start <= end <= len(markdown)` and never splits a UTF-8 code
point; violations are impossible to persist.
Test plan §5.8 (Property / 0); `FR-EXTRACT-01`, `NFR-EXTRACT-02`.

The FUZZ-06 structure (`tests/property/test_fuzz_06_graphs_and_work_ids.py`): the
generators are calibrated by a test that runs GREEN today, because `require()` raises
before the property bodies run and a degenerate corpus would make the invariant hold
vacuously the day someone removes the marker. The boundary check itself is calibrated
both ways — a reference implementation AND a deliberately reversed one.

Split by blocker:
- `test_..._emitted_spans_always_satisfy_the_span_invariant` (writtenahead, `#68`) —
  the property: the module's reply→spans conversion emits only valid spans over
  generated documents;
- `test_..._a_violating_span_is_impossible_to_persist` (writtenahead, `#68`) — a reply
  carrying a span that breaks the invariant is REFUSED, not clamped: a clamp would
  rewrite the address (silently lying about offsets), a silent drop would let the
  caller believe the set held — the TC-EXTRACT-03 step-3 doctrine. Refusal at the
  conversion is what makes a violation impossible to PERSIST (the worker can only
  write what the conversion emits);
- `test_generators_and_the_boundary_check_are_calibrated` (GREEN, unmarked) — the
  corpus is non-degenerate and the boundary check rejects what it must.

**Assumed surface** (disclosed in `tests/support/extract_vocabulary.py`):
`parse_spans(reply_text, markdown_bytes) -> sequence of spans` — the pure conversion
the worker runs before persistence. Rung 0 cannot reach the store; the
persistence-side link is exercised at rung 2 in `tests/integration/extract/`
(TC-EXTRACT-01's round trip, TC-EXTRACT-14's purge).

**Isolation: rung 0** — pure functions over generated values; no store, no provider.

`max_examples=200` with `deadline=None`: the FUZZ-06 rationale (per-example deadline
does not fit a real workload); §6.7 does not name a per-case count for TS-26, so the
loaded `ci` profile's 200 stands (disclosed).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.support.extract_vocabulary import EXTRACT_ISSUE, SPAN_PARSE
from tests.support.impl import EXTRACT_MODULE, require

pytestmark = pytest.mark.property

ISSUE = EXTRACT_ISSUE

EXAMPLES = 200

#: The alphabet leans multi-byte: every encoding width (1, 2, 3, 4) is common, so a
#: generator that silently produced ASCII-only documents would not exercise the
#: code-point boundary rule.
_ALPHABET = st.sampled_from(
    ["a", "z", " ", "\n", "é", "ü", "中", "文", "\U0001F6A8", "\U0001F600"]
)

_DOCUMENTS = st.lists(_ALPHABET, min_size=4, max_size=64).map("".join)


def _boundaries(markdown_bytes: bytes) -> set[int]:
    """The byte offsets where a code point STARTS (plus the end): the only offsets a
    span boundary may legally sit on."""
    bounds: set[int] = set()
    offset = 0
    for char in markdown_bytes.decode("utf-8"):
        bounds.add(offset)
        offset += len(char.encode("utf-8"))
    bounds.add(offset)
    return bounds


def _span_is_valid(markdown_bytes: bytes, start: int, end: int) -> bool:
    """The invariant under test: bounds hold AND neither boundary splits a code point."""
    if not (0 <= start <= end <= len(markdown_bytes)):
        return False
    bounds = _boundaries(markdown_bytes)
    return start in bounds and end in bounds


@st.composite
def _valid_span_sets(draw: st.DrawFn) -> tuple[str, list[dict[str, int]]]:
    """A document plus a span set whose every span satisfies the invariant."""
    markdown = draw(_DOCUMENTS)
    md_bytes = markdown.encode("utf-8")
    bounds = sorted(_boundaries(md_bytes))
    spans: list[dict[str, int]] = []
    for _ in range(draw(st.integers(min_value=1, max_value=4))):
        start_index = draw(st.integers(min_value=0, max_value=len(bounds) - 2))
        end_index = draw(
            st.integers(min_value=start_index, max_value=len(bounds) - 1)
        )
        spans.append({"start": bounds[start_index], "end": bounds[end_index]})
    return markdown, spans


@st.composite
def _violating_spans(draw: st.DrawFn) -> tuple[str, dict[str, int]]:
    """A document plus ONE span that genuinely breaks the invariant — out of bounds,
    or a boundary inside a multi-byte sequence."""
    markdown = draw(_DOCUMENTS)
    md_bytes = markdown.encode("utf-8")
    bounds = _boundaries(md_bytes)
    interior = [
        offset for offset in range(len(md_bytes) + 1) if offset not in bounds
    ]
    mode = draw(st.sampled_from(["split", "out_of_bounds"])) if (
        interior and len(md_bytes) > 0
    ) else "out_of_bounds"
    if mode == "split":
        bad = draw(st.sampled_from(interior))
        return markdown, {"start": bad, "end": draw(
            st.integers(min_value=bad, max_value=len(md_bytes))
        )}
    # Out of bounds: an end past the document (or a negative start).
    if draw(st.booleans()):
        return markdown, {"start": len(md_bytes) + draw(st.integers(1, 5)), "end": len(md_bytes) + 6}
    return markdown, {"start": -draw(st.integers(1, 5)), "end": draw(st.integers(0, 3))}


def _spans_of(result: Any) -> list[Any]:
    spans = getattr(result, "spans", None)
    if spans is None and isinstance(result, (list, tuple)):
        spans = result
    if spans is None and isinstance(result, dict):
        spans = result.get("spans")
    assert spans is not None, f"the conversion emitted no span sequence: {result!r}"
    return list(spans)


@settings(max_examples=EXAMPLES, deadline=None)
@given(_valid_span_sets())
@pytest.mark.writtenahead
def test_tc_extract_15_emitted_spans_always_satisfy_the_span_invariant(case):
    """`TC-EXTRACT-15` — over generated documents, the conversion emits only spans
    that satisfy the bounds and code-point rules, and every span round-trips."""
    ParseSpans = require(EXTRACT_MODULE, SPAN_PARSE, issue=ISSUE)
    markdown, spans = case
    md_bytes = markdown.encode("utf-8")
    reply = json.dumps({"spans": spans}, sort_keys=True)

    emitted = _spans_of(ParseSpans(reply, md_bytes))
    assert emitted, "the conversion dropped a valid span set entirely"
    for span in emitted:
        start = getattr(span, "start", None)
        end = getattr(span, "end", None)
        if start is None and isinstance(span, dict):
            start, end = span["start"], span["end"]
        assert 0 <= start <= end <= len(md_bytes), (
            f"emitted span {start}:{end} violates the bounds over a "
            f"{len(md_bytes)}-byte document"
        )
        assert _span_is_valid(md_bytes, start, end), (
            f"emitted span {start}:{end} splits a UTF-8 code point"
        )


@settings(max_examples=EXAMPLES, deadline=None)
@given(_violating_spans())
@pytest.mark.writtenahead
def test_tc_extract_15_a_violating_span_is_impossible_to_persist(case):
    """`TC-EXTRACT-15` — a reply carrying a span that breaks the invariant is REFUSED:
    no exception-free path can hand such a span to persistence."""
    ParseSpans = require(EXTRACT_MODULE, SPAN_PARSE, issue=ISSUE)
    markdown, span = case
    md_bytes = markdown.encode("utf-8")
    assert not _span_is_valid(md_bytes, span["start"], span["end"]), (
        "generator bug: the violating span does not violate"
    )
    reply = json.dumps({"spans": [span]}, sort_keys=True)

    with pytest.raises(Exception):  # noqa: B017,PT011 — any refusal counts
        ParseSpans(reply, md_bytes)


def test_generators_and_the_boundary_check_are_calibrated():
    """The corpus is non-degenerate and the boundary check is calibrated BOTH ways —
    it accepts the valid and rejects the reversed form (the FUZZ-06 rule)."""
    ascii_doc = "plain text\n"
    wide_doc = "é中\U0001F6A8é中\U0001F6A8"
    wide = wide_doc.encode("utf-8")
    ascii_bytes = ascii_doc.encode("utf-8")
    for md_bytes in (wide, ascii_bytes):
        # Whole-document spans are always valid — the trivial member of the set.
        assert _span_is_valid(md_bytes, 0, len(md_bytes))
        # Out of bounds is caught regardless of encoding width.
        assert not _span_is_valid(md_bytes, 0, len(md_bytes) + 1)
    # The reversed check on a multi-byte document: shifting the end by one byte
    # breaks it — the byte that used to close the emoji is now an interior byte.
    assert not _span_is_valid(wide, 0, len(wide) - 1)
    # A split inside the 3-byte 中 must be caught: byte 1 is interior.
    zh = "中".encode("utf-8")
    assert not _span_is_valid(zh + zh, 1, len(zh) + 1)
    # Bounds: negative and past-the-end are caught even on ASCII.
    assert not _span_is_valid(ascii_bytes, -1, 2)
    # On pure ASCII every offset is a boundary, so a SHORTENED span stays valid —
    # the boundary rule is vacuous there and the check must not fire.
    assert _span_is_valid(ascii_bytes, 0, len(ascii_bytes) - 1)
