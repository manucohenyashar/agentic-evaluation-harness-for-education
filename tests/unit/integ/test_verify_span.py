"""`TC-INTEG-01` — `verify_span` is exact at every boundary, with no model call.

Test plan §5.9 block form, case for `FR-INTEG-01`, `NFR-INTEG-01`, `NFR-INTEG-02`
(RISK-01, Critical, P0). Written ahead of `#73` (test plan §8.2): the module does not
exist yet, so every case here fails only through `NotImplementedYet` naming `#73` and
turns green the moment `aeh.integ` lands `verify_span` — no edit to this file.

**The coordinate system is bytes** (review finding, reconciled): CT-INGEST-03 fixes
byte offsets into `document.markdown` as "the coordinate system every later stage
uses" and NFR-INTEG-02 calls `verify_span` "a pure function of (document **bytes**,
span)". Every offset in the boundary table below is a UTF-8 **byte** offset — which is
what makes row 9 (a span starting mid-way through a 3-byte character) expressible at
all, and what makes rows 1/5/10 bite on documents that actually contain multibyte
characters rather than degenerating to codepoint indexing.

**The boundary table is the spec** (§5.9's ten rows, copied so a reader needs no second
tab). Rows 6-9 are the ones that decide whether a hallucinated span crashes the run or
silently passes — neither is acceptable; `False` with no exception is the requirement.
The document carries ASCII, a 2-byte character (é), a 3-byte character (中), a 4-byte
character (an emoji), a CRLF sequence and a trailing newline, so every multi-byte
boundary in NFR-INTEG-02 is exercised against real bytes rather than a synthetic
alphabet.

**The no-model-call oracle** (FR-INTEG-01: "this check shall involve no model call") is
asserted three ways, all disclosed here rather than hidden in a helper:

1. the socket guard is autouse for every test in this suite (TS-00's `network_guard`),
   so any network attempt fails the test;
2. an **import-graph assertion**: the module under test must not import `aeh.prov` at
   all — the same scan TC-INTEG-10 runs over the write columns, applied to the
   provider seam, so a provider dependency that needs no network cannot hide either
   (the plan names a call-count oracle; with no provider seam there are no calls to
   count, and the import is the call's only door);
3. a timing assertion: the boundary sweep below must complete inside
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

import ast
import time
from pathlib import Path

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


def _byte_offset(markdown: str, needle: str) -> int:
    """`needle`'s offset in the coordinate system spans address: UTF-8 bytes."""
    return markdown.encode("utf-8").index(needle.encode("utf-8"))


def _byte_span(markdown: str, needle: str) -> tuple[int, int]:
    """The (start, end) byte offsets bracketing `needle` in the Markdown."""
    start = _byte_offset(markdown, needle)
    return start, start + len(needle.encode("utf-8"))


def _verify_span():
    return require(INTEG_MODULE, "verify_span", issue="#73")


def _sweep_budget() -> float:
    import os

    raw = os.environ.get(_SWEEP_BUDGET_S_ENV)
    return float(raw) if raw and raw.strip() else _SWEEP_BUDGET_S


# --- the ten-row boundary table -----------------------------------------------------------

def test_tc_integ_01_row_1_exactly_matching_substring_is_true():
    """Row 1 — exactly matching a substring: `True` (byte offsets bracket "café",
    whose 2-byte é puts the end offset 5 bytes past the start)."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    start, end = _byte_span(doc.markdown, "café")
    assert verify_span(doc, Span(start, end, "café")) is True


def test_tc_integ_01_row_2_one_character_difference_is_false():
    """Row 2 — text differing by one character: `False`."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    start, end = _byte_span(doc.markdown, "café")
    assert verify_span(doc, Span(start, end, "cafa")) is False


def test_tc_integ_01_row_3_trailing_whitespace_difference_is_false():
    """Row 3 — differing by trailing whitespace only: `False`.

    Normalization would let a hallucinated span pass: the comparison is byte-exact.
    """
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    start, end = _byte_span(doc.markdown, "café")
    assert verify_span(doc, Span(start, end, "café ")) is False


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
    """Row 5 — span ending exactly at the document's last byte: `True`."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    doc_bytes = doc.markdown.encode("utf-8")
    tail = doc_bytes[-6:].decode("utf-8")
    assert tail.endswith("\n")
    assert verify_span(doc, Span(len(doc_bytes) - 6, len(doc_bytes), tail)) is True


def test_tc_integ_01_row_6_end_beyond_document_is_false_without_exception():
    """Row 6 — `end == len(document bytes) + 1`: `False`, no exception."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    doc_bytes = doc.markdown.encode("utf-8")
    assert verify_span(doc, Span(0, len(doc_bytes) + 1, doc.markdown)) is False


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
    raise, and not to silently truncate. In byte coordinates the start offset lands on
    a continuation byte of 数, so a decode-based implementation is exactly what would
    raise here. The degenerate twin (garbage text that equals the garbage slice) is
    *not* asserted in this unit case: TC-INTEG-09's invariant says `True` iff the bytes
    equal the text and the span is in bounds, and the property suite holds that
    invariant uniformly, mid-codepoint included.
    """
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    lead = _byte_offset(doc.markdown, "数")
    assert verify_span(doc, Span(lead + 1, lead + 4, "学")) is False
    try:
        verify_span(doc, Span(lead + 2, lead + 5, "x"))
    except UnicodeDecodeError:
        pytest.fail("a mid-codepoint span must not leak UnicodeDecodeError — return False")


def test_tc_integ_01_row_10_span_over_crlf_is_true_when_bytes_match():
    """Row 10 — span spanning a CRLF: `True` when the bytes match exactly. The span
    crosses the 4-byte emoji before the CRLF, so its byte extent is longer than its
    codepoint count — a codepoint implementation computes a different slice."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    doc_bytes = doc.markdown.encode("utf-8")
    start = _byte_offset(doc.markdown, "An emoji")
    end = doc_bytes.index(b"\r\n", start) + 2
    text = doc_bytes[start:end].decode("utf-8")
    assert verify_span(doc, Span(start, end, text)) is True


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
    start, end = _byte_span(original.markdown, "café")
    span = Span(start, end, "café")
    assert verify_span(original, span) is True
    revised = Doc(markdown=_markdown().replace("café", "kaffee"))
    assert verify_span(revised, span) is False, (
        "the span's offsets address the superseded bytes; a function that consulted "
        "current state rather than its arguments would pass this and break CT-INGEST-02"
    )


# --- the no-model-call and timing oracles --------------------------------------------------

def test_tc_integ_01_verify_span_imports_no_provider_seam():
    """The import-graph half of the no-model-call oracle: the module that lands
    `verify_span` must not import `aeh.prov` — a provider dependency is the only door
    a model call has, and this closes it structurally (the TC-INTEG-10 scan pattern,
    applied to the seam instead of the write columns). The require above keeps the
    pre-landing failure on the designed blocker."""
    require(INTEG_MODULE, "verify_span", issue="#73")
    module_path = Path(__file__).resolve().parents[3] / "src" / "aeh" / "integ.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    def imports_provider(node: ast.AST) -> bool:
        if isinstance(node, ast.Import):
            return any("prov" in alias.name for alias in node.aliases)
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            return "prov" in module or any("prov" in a.name for a in node.aliases)
        return False

    provider_imports = [
        node for node in ast.walk(tree) if imports_provider(node)
    ]
    assert not provider_imports, (
        "aeh.integ imports a provider seam — verify_span must involve no model call "
        "(FR-INTEG-01), and an import of aeh.prov is a model call's only door"
    )


def test_tc_integ_01_boundary_sweep_is_within_the_no_model_call_budget():
    """The timing half of the oracle (NFR-INTEG-01): a sweep spanning every row's shape
    — exact slice, near miss, whitespace, zero-length, out-of-bounds, negative,
    inverted, mid-codepoint, CRLF — completes inside `_SWEEP_BUDGET_S`: cheap enough
    that a model call inside `verify_span` cannot hide, with the socket guard and the
    import scan backing it up."""
    verify_span = _verify_span()
    doc = Doc(markdown=_markdown())
    doc_bytes = doc.markdown.encode("utf-8")
    lead = _byte_offset(doc.markdown, "数")
    crlf_start = _byte_offset(doc.markdown, "An emoji")
    cases = [
        Span(0, 4, doc.markdown[:4]),          # row 1's shape: exact slice
        Span(0, 4, "xxxx"),                    # row 2's shape: one character off
        Span(0, 4, doc.markdown[:4] + " "),    # row 3's shape: whitespace tail
        Span(5, 5, ""),                        # row 4: zero-length
        Span(len(doc_bytes) - 6, len(doc_bytes), doc_bytes[-6:].decode("utf-8")),
        Span(0, len(doc_bytes) + 1, doc.markdown),  # row 6: out of bounds
        Span(-1, 4, "x"),                      # row 7: negative
        Span(10, 4, "x"),                      # row 8: inverted
        Span(lead + 1, lead + 4, "学"),         # row 9: mid-codepoint
        Span(crlf_start, crlf_start + 30, "x"),  # row 10's shape: CRLF crossing
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
    start, end = _byte_span(doc.markdown, "café")
    first = verify_span(doc, Span(start, end, "café"))
    second = verify_span(doc, Span(start, end, "café"))
    assert first is second is True
