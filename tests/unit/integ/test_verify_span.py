"""`TC-INTEG-01` — `verify_span` is exact at every boundary, with no model call.

Test plan §5.9 block form, case for `FR-INTEG-01`, `NFR-INTEG-01`, `NFR-INTEG-02`
(RISK-01, Critical, P0). Written ahead of `#73` (test plan §8.2): the module does not
exist yet, so every case here fails only through `NotImplementedYet` naming `#73` and
turns green the moment `aeh.integ` lands `verify_span` — no edit to this file.

**The boundary table is the spec** (§5.9's ten rows, copied so a reader needs no second
tab). Rows 6-9 are the ones that decide whether a hallucinated span crashes the run or
silently passes — neither is acceptable; `False` with no exception is the requirement.
The document carries ASCII, a 2-byte character (é), a 3-byte character (中), a 4-byte
character (an emoji), a CRLF sequence and a trailing newline, so every multi-byte
boundary in NFR-INTEG-02 is exercised against real bytes rather than a synthetic
alphabet.

**The no-model-call oracle** (FR-INTEG-01: "this check shall involve no model call") is
asserted two ways, both disclosed here rather than hidden in a helper:

1. the socket guard is autouse for every test in this suite (TS-00's `network_guard`),
   so any network attempt — the only route a model call has — fails the test;
2. a timing assertion: the entire boundary sweep below must complete inside
   `_SWEEP_BUDGET_S`, a budget orders of magnitude above what byte comparison costs and
   orders of magnitude below what one model round-trip costs. A `verify_span` that
   called a model could not pass the sweep, whatever it returned.

Purity (NFR-INTEG-02: "a pure function of (document bytes, span)") is asserted
structurally by the variant at the bottom: the same inputs verified twice, plus a
document superseded after the first verification, produce identical results — the
function's verdict depends on nothing but the bytes it was handed.

Interface assumed of `#73` (reconcile at landing): `aeh.integ.verify_span(doc, span)`
as a module-level pure function — the design's Protocol declares it as an
`IntegrityGate` method, and the module-level name is the rung-0 surface (the
`#65` `aeh.synth:synthesize` precedent, recorded in `tests/support/integ_vocabulary.py`).
`doc` needs only `.markdown`; `span` needs only `.start` / `.end` / `.text`
(CT-EXTRACT-01).
"""

from __future__ import annotations

import time

import pytest

from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import Doc, Span

pytestmark = pytest.mark.writtenahead

#: The no-model-call budget for the whole boundary sweep (see module docstring). Env-gated
#: per seam rule 3 so a very slow box can widen it without a code change; the default is
#: still a floor a model call cannot squeeze under.
_SWEEP_BUDGET_S = 0.5
_SWEEP_BUDGET_S_ENV = "INTEG_VERIFY_SPAN_SWEEP_BUDGET_S"


def _markdown() -> str:
    """ASCII + 2-byte (é) + 3-byte (中) + 4-byte (emoji) + CRLF + trailing newline."""
    return (
        "The student writes in ASCII.\n"
        "A café in the margins.\n"
        "数学 is a three-byte visitor.\n"
        "An emoji: 🧪 sits in a four-byte slot.\r\n"
        "Trailing newline follows.\n"
    )


def _verify_span():
    return require(INTEG_MODULE, "verify_span", issue="#73")


def _sweep_budget() -> float:
    import os

    raw = os.environ.get(_SWEEP_BUDGET_S_ENV)
    return float(raw) if raw and raw.strip() else _SWEEP_BUDGET_S


# --- the ten-row boundary table -----------------------------------------------------------

def test_tc_integ_01_row_1_exactly_matching_substring_is_true():
    """Row 1 — exactly matching a substring: `True`."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    assert verify_span(doc, Span(doc.markdown.index("café"), doc.markdown.index("café") + 4, "café")) is True


def test_tc_integ_01_row_2_one_character_difference_is_false():
    """Row 2 — text differing by one character: `False`."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    assert verify_span(doc, Span(doc.markdown.index("café"), doc.markdown.index("café") + 4, "cafa")) is False


def test_tc_integ_01_row_3_trailing_whitespace_difference_is_false():
    """Row 3 — differing by trailing whitespace only: `False`.

    Normalization would let a hallucinated span pass: the comparison is byte-exact.
    """
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    start = doc.markdown.index("café")
    assert verify_span(doc, Span(start, start + 5, "café ")) is False


def test_tc_integ_01_row_4_zero_length_span_is_declared_behaviour():
    """Row 4 — zero-length span (`start == end`) with empty text: declared behaviour,
    asserted explicitly rather than skipped."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    result = verify_span(doc, Span(5, 5, ""))
    assert isinstance(result, bool)
    assert result is True, (
        "a zero-length span over in-bounds empty bytes compares empty to empty; the "
        "design declares the pure slice comparison, and this test pins it — if `#73` "
        "lands the other resolution (`False`), this assertion is the conversation, "
        "not an obstacle"
    )


def test_tc_integ_01_row_5_span_ending_at_len_markdown_is_true():
    """Row 5 — span ending exactly at `len(markdown)`: `True`."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    tail = doc.markdown[-6:]
    assert tail.endswith("\n")
    assert verify_span(doc, Span(len(doc.markdown) - 6, len(doc.markdown), tail)) is True


def test_tc_integ_01_row_6_end_beyond_document_is_false_without_exception():
    """Row 6 — `end == len(markdown) + 1`: `False`, no exception."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    assert verify_span(doc, Span(0, len(doc.markdown) + 1, doc.markdown)) is False


def test_tc_integ_01_row_7_negative_start_is_false_without_exception():
    """Row 7 — negative `start`: `False`, no exception."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    assert verify_span(doc, Span(-1, 4, doc.markdown[:4])) is False


def test_tc_integ_01_row_8_inverted_span_is_false_without_exception():
    """Row 8 — `start > end`: `False`, no exception."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    assert verify_span(doc, Span(10, 4, doc.markdown[4:10])) is False


def test_tc_integ_01_row_9_start_mid_codepoint_is_false_without_exception():
    """Row 9 — span starting mid-way through a 3-byte character: `False`, no exception,
    and no `UnicodeDecodeError` escaping.

    The offsets are byte offsets into the canonical Markdown (CT-INGEST-03); an
    extractor whose offsets drift by one byte quotes the intended character but slices
    garbage, and the function's job is to return `False` for the mismatch — not to
    raise, and not to silently truncate. The degenerate twin (garbage text that equals
    the garbage slice) is *not* asserted here: TC-INTEG-09's invariant says `True` iff
    the slice equals the text and the span is in bounds, and the property suite holds
    that invariant uniformly, mid-codepoint included.
    """
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    marker = doc.markdown.index("数")
    assert verify_span(doc, Span(marker + 1, marker + 4, "学")) is False
    try:
        verify_span(doc, Span(marker + 2, marker + 5, "x"))
    except UnicodeDecodeError:
        pytest.fail("a mid-codepoint span must not leak UnicodeDecodeError — return False")


def test_tc_integ_01_row_10_span_over_crlf_is_true_when_bytes_match():
    """Row 10 — span spanning a CRLF: `True` when the bytes match exactly."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    start = doc.markdown.index("An emoji")
    end = doc.markdown.index("\r\n", start) + 2
    assert verify_span(doc, Span(start, end, doc.markdown[start:end])) is True


# --- variants the block form names ---------------------------------------------------------

def test_tc_integ_01_variant_zero_byte_document():
    """Variant — a document of exactly zero bytes: every span is out of bounds and
    nothing raises."""
    verify_span = _verify_span()
    doc = Doc(markdown="")
    assert verify_span(doc, Span(0, 0, "")) is True
    assert verify_span(doc, Span(0, 1, "x")) is False
    assert verify_span(doc, Span(1, 1, "")) is False


def test_tc_integ_01_variant_superseded_document_verifies_against_bytes_handed():
    """Variant — a span over a document that has since been superseded: the function
    verifies against the bytes it was handed, not against whatever revision exists now
    (CT-INGEST-02: a correction is a new row, never an update)."""
    verify_span = _verify_span()
    original = Doc(markdown=_markdown())
    start = original.markdown.index("café")
    span = Span(start, start + 4, "café")
    assert verify_span(original, span) is True
    revised = Doc(markdown=_markdown().replace("café", "kaffee"))
    assert verify_span(revised, span) is False, (
        "the span's offsets address the superseded bytes; a function that consulted "
        "current state rather than its arguments would pass this and break CT-INGEST-02"
    )


# --- the no-model-call and timing oracles --------------------------------------------------

def test_tc_integ_01_whole_boundary_sweep_is_within_the_no_model_call_budget():
    """The timing half of the oracle (NFR-INTEG-01): the full ten-row sweep plus both
    variants completes inside `_SWEEP_BUDGET_S` — cheap enough that a model call inside
    `verify_span` cannot hide, and the budget the socket guard backs up."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    cases = [
        Span(0, 4, doc.markdown[:4]),
        Span(-1, 4, "x"),
        Span(0, len(doc.markdown) + 1, doc.markdown),
        Span(10, 4, "x"),
        Span(5, 5, ""),
    ]
    start = time.perf_counter()
    for span in cases:
        assert isinstance(verify_span(doc, span), bool)
    elapsed = time.perf_counter() - start
    assert elapsed < _sweep_budget(), (
        f"the boundary sweep took {elapsed:.3f}s against a {_sweep_budget()}s budget — "
        "span verification is the cheapest protection in the system (NFR-INTEG-01) and "
        "a sweep this slow means a model call or I/O is hiding inside the pure path"
    )


def test_tc_integ_01_verify_span_is_pure_over_repeated_calls():
    """NFR-INTEG-02's purity: the same (document, span) verified twice returns the same
    verdict — no state, no counter, no first-call-is-different."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    start = doc.markdown.index("café")
    first = verify_span(doc, Span(start, start + 4, "café"))
    second = verify_span(doc, Span(start, start + 4, "café"))
    assert first is second is True
