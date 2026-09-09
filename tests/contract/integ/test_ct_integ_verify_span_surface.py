"""`CT-INTEG-01` — `verify_span` is pure, deterministic and zero-cost, and the
boundary set is rejected exactly (`TC-INTEG-C01`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#73` (test plan
§8.2): every case below fails only through `NotImplementedYet` naming `#73`,
and turns green the moment `aeh.integ:verify_span` lands.

The clause: `verify_span(doc, span) -> bool` is **pure, deterministic, and
zero-cost** — no model call, no network call, and no store read beyond the
document bytes handed to it — and is exhaustively unit-testable including the
boundary cases: zero-length span, span at end of document, multi-byte UTF-8
boundaries (NFR-INTEG-02). The clause's own enforcement shape is followed
literally: all three surfaces are **blocked** during the purity call, so a
violation raises rather than passing slowly.

**Disclosures register** (invented-or-reconciled names this file relies on;
nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| `aeh.integ.verify_span(doc, span) -> bool` | the #75-disclosed module-level key (`tests/support/integ_vocabulary.py`); design §3.9 declares it as an `IntegrityGate` method — the two reconcile at `#73`'s landing |
| `tests.support.span_strategies.expected_verify` | the shared invariant's right-hand side (`True` exactly when the bytes match and the span is in bounds), reused as this case's oracle so the clause case and the FUZZ-03 property cannot drift apart |
| blocked surfaces | test-side technique, no seam: `aeh.prov` and `aeh.store` public callables are replaced with raisers (`_doubles.RefusingSurface`) and the TS-00 socket guard is active — the clause's "enforced with all three blocked". Disclosed limit: a name `aeh.integ` bound with `from ... import` at its own import time keeps the original binding (module-level patching cannot rewire an already-imported reference), so the store limb catches lazy and attribute-style access; the socket guard is the load-bearing block for egress, and CT-INTEG-05's import-graph assertion is the structural half |

**Coordinates are BYTE offsets** into `document.markdown` (CT-INGEST-03;
NFR-INTEG-02: "a pure function of (document **bytes**, span)") — every offset
below is computed on the UTF-8 encoding, and the mid-codepoint arms exist
precisely because a codepoint-slicing implementation silently truncates there.
"""

from __future__ import annotations

import aeh.prov
import aeh.store
import pytest

from tests.contract.integ._doubles import RefusingSurface, block_module_surfaces, byte_span
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import Doc, Span
from tests.support.span_strategies import expected_verify

pytestmark = pytest.mark.contract

#: A document whose multibyte runs make every codepoint-slicing mutant visible:
#: ASCII prefix, two-byte é, three-byte 中, four-byte emoji, CRLF, ASCII tail.
_MULTIBYTE_MARKDOWN = "claim: café, 数学, 🧪\r\nplain tail\n"

_RUN = "run-integ-c01"


def _doc() -> Doc:
    return Doc(markdown=_MULTIBYTE_MARKDOWN)


# --- the purity limb, with all three surfaces blocked --------------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c01_verify_span_is_pure_with_model_network_and_store_blocked(
        network_guard, monkeypatch):
    """`TC-INTEG-C01` — the call runs under the TS-00 socket guard with every
    public callable on `aeh.prov` (the model boundary) and `aeh.store` (the
    store boundary) replaced by a raiser: a violation raises rather than
    passing slowly. The oracle is the shared byte-exact invariant, and
    determinism is the one behavioural corollary of purity checkable at rung 0:
    the same inputs, evaluated again, return the same verdict."""
    verify_span = require(INTEG_MODULE, "verify_span", issue="#73")
    block_module_surfaces(monkeypatch, aeh.prov)
    block_module_surfaces(monkeypatch, aeh.store)

    doc = _doc()
    span = byte_span(doc.markdown, "数学")
    verdict = verify_span(doc, span)
    assert verdict is expected_verify(doc, span) is True, (
        f"verify_span returned {verdict!r} for an exact byte slice — the oracle is "
        "the shared invariant (bytes match and in bounds), and a different answer "
        "here means the contract case and the FUZZ-03 property have drifted apart"
    )

    again = verify_span(doc, span)
    assert again is verdict, (
        "verify_span is not deterministic — the same (doc, span) produced two "
        "different verdicts, so it is not a pure function of (document bytes, span) "
        "(NFR-INTEG-02)"
    )
    network_guard.assert_no_network()


@pytest.mark.writtenahead
def test_tc_integ_c01_a_failing_span_verifies_under_blocked_surfaces_too(
        network_guard, monkeypatch):
    """`TC-INTEG-C01`'s negative control — rejection must also be computable
    with every surface blocked: a verifier that smuggles its real work behind a
    network or store round-trip would otherwise pass the True case above while
    failing exactly the case RISK-01 needs it to catch."""
    verify_span = require(INTEG_MODULE, "verify_span", issue="#73")
    block_module_surfaces(monkeypatch, aeh.prov)
    block_module_surfaces(monkeypatch, aeh.store)

    doc = _doc()
    start = byte_span(doc.markdown, "café").start
    mutant = Span(start, start + 5, "cafém")  # same length, one byte wrong
    assert verify_span(doc, mutant) is expected_verify(doc, mutant) is False
    network_guard.assert_no_network()


# --- the boundary set, enumerated -----------------------------------------------------------
#
# The clause names three boundary families; the table is the exhaustive set over them
# on one document, each row asserting the EXACT verdict (the oracle is "exact values
# over an enumerated boundary set", not an invariant sample). Byte anatomy of the
# fixture "claim: café, 数学, 🧪\r\nplain tail\n": "claim: " is 7 bytes; "café"
# occupies [7,12) with é's lead at 10 and its CONTINUATION byte at 11; "数学"
# occupies [14,20) (three bytes each); "🧪" occupies [22,26); the document is 39
# bytes. Every offset in the table is one of those numbers, not a codepoint index
# (the document has 31 codepoints — a slicing mutant mixes the two).
#
# The "rejected, not silently truncated" requirement is what the mid-codepoint rows
# pin: a decoder-tolerant or codepoint-slicing implementation truncates (or repairs)
# the partial sequence and accepts; the clause requires False. Row 8 is the sharpest
# of them: offsets (11, 13) are é's continuation byte and the comma, whose
# CODEPOINT slice is exactly ", " — the text a slicing mutant extracts and accepts;
# the byte slice is b'\xa9,' and must be rejected.
#
# Deliberately unpinned, disclosed: the degenerate zero-length span AT a
# mid-codepoint offset (e.g. (15, 15, "")). §6.7's declared invariant — `True`
# exactly when the bytes match and the span is in bounds — accepts it (the empty
# bytes match), while the clause's "a span starting or ending mid-codepoint must be
# rejected" read strictly refuses it. The case does not invent a third position:
# the rows here pin only the cells both statements agree on, and the degenerate
# cell is flagged for #73's reconcile-at-landing conversation.


def _boundary_cases() -> list[tuple[str, Span, bool]]:
    markdown = _MULTIBYTE_MARKDOWN
    n = len(markdown.encode("utf-8"))
    assert (n, len(markdown)) == (39, 31), (
        "the boundary table is written against the fixture's byte anatomy; the "
        "fixture changed and every hardcoded offset below must be re-derived"
    )
    math_start, math_end = 14, 20  # 数学's byte extent
    return [
        # -- zero-length spans (empty slice, empty text) ----------------------------------
        ("zero-length at a character boundary", Span(math_start, math_start, ""), True),
        ("zero-length at end of document", Span(n, n, ""), True),
        # -- span at end of document ------------------------------------------------------
        ("exact slice ending at end of document", byte_span(markdown, "plain tail"), True),
        # A clamping implementation slices bytes[37:40] to "l\n", matches the text and
        # accepts; end past the document is out of bounds and must refuse.
        ("end one byte past the document", Span(n - 2, n + 1, "l\n"), False),
        # -- multi-byte UTF-8 boundaries: start or end mid-codepoint is rejected ----------
        ("start mid-codepoint, full codepoint text", Span(math_start + 1, math_end, "学"), False),
        ("end mid-codepoint", Span(math_start, math_end - 1, "数"), False),
        ("both boundaries mid-codepoint", Span(math_start + 1, 25, "学🧪"), False),
        ("codepoint indices used as byte offsets", Span(11, 13, ", "), False),
        # -- the True anchors either side of every boundary family -------------------------
        ("full multibyte span on codepoint boundaries", byte_span(markdown, "数学"), True),
        ("emoji span on codepoint boundaries", byte_span(markdown, "🧪"), True),
        ("span crossing CRLF on boundaries", byte_span(markdown, "🧪\r\nplain"), True),
    ]


_BOUNDARY_NAMES = [name for name, _, _ in _boundary_cases()]


@pytest.mark.writtenahead
@pytest.mark.parametrize("name, span, expected", _boundary_cases(), ids=_BOUNDARY_NAMES)
def test_tc_integ_c01_every_enumerated_boundary_verdicts_exactly(name, span, expected):
    """`TC-INTEG-C01` — the boundary set the clause names, one exact verdict per
    row, each cross-checked against the shared invariant: zero-length spans, the
    end-of-document span, and the multi-byte UTF-8 boundaries. A span starting
    or ending mid-codepoint is **rejected** — the False is the requirement, and
    a silently truncated (or repaired) acceptance fails here."""
    verify_span = require(INTEG_MODULE, "verify_span", issue="#73")
    doc = _doc()
    verdict = verify_span(doc, span)
    assert verdict is expected, (
        f"{name}: verify_span returned {verdict!r}, the boundary table requires "
        f"{expected!r} — and the shared invariant agrees: {expected_verify(doc, span)}"
    )
    assert verdict is expected_verify(doc, span), (
        f"{name}: the clause verdict and the shared byte-exact invariant disagree — "
        "the contract case and FUZZ-03 must not drift apart"
    )


@pytest.mark.writtenahead
def test_tc_integ_c01_boundary_verdicts_are_independent_of_call_order():
    """`TC-INTEG-C01`'s purity corollary over the whole boundary set — the same
    calls in a different order return the same verdicts: no cached-by-position
    state, no one-shot decoder whose second call on a partial sequence behaves
    differently."""
    verify_span = require(INTEG_MODULE, "verify_span", issue="#73")
    doc = _doc()
    cases = _boundary_cases()
    forward = [verify_span(doc, span) for _, span, _ in cases]
    backward = [verify_span(doc, span) for _, span, _ in reversed(cases)]
    assert forward == backward[::-1], (
        "verify_span's verdicts depend on call order — state somewhere in the "
        "'pure' function (NFR-INTEG-02)"
    )
