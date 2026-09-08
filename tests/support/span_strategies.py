"""The hypothesis strategies `TC-INTEG-09` and `FUZZ-03` depend on, asserted before
anything depends on them (issue #75; the `test_fuzz_generators.py` precedent for
FUZZ-06/07, applied to §6.7's `FUZZ-03` row).

§6.7 declares the generator as a spec, not a detail: *"Generated documents (ASCII,
multi-byte UTF-8, CRLF, empty) crossed with generated spans (in-bounds, out-of-bounds,
negative, inverted, mid-codepoint)"*. The strategies below are that row, and
`tests/property/test_span_corpus_generators.py` holds the degeneracy guard that keeps
them honest — because the failure mode of a fuzz case is not "the invariant failed",
it is "the invariant passed over a corpus that never contained a counterexample".
"""

from __future__ import annotations

from hypothesis import strategies as st

from tests.support.integ_vocabulary import Doc, Span

#: §6.7's *"1,000 in CI"*. The shared `ci` profile registers 200; the case-specific row
#: wins (see the note in `test_fuzz_07_blobs_and_write_queue.py`).
FUZZ_EXAMPLES = 1000

_DOCUMENT_BODIES = st.sampled_from([
    "",  # empty
    "plain ASCII answer text.\n",
    "A café claim, two bytes wide.\r\nwith CRLF inside.\r\n",  # CRLF + 2-byte
    "数学 counts as a three-byte run, emoji 🧪 four.\n",  # 3-byte + 4-byte
])
_UTF8_CHARACTERS = st.sampled_from(["a", "é", "中", "🧪", "\r\n", " ", "x"])

DOCUMENTS = st.builds(
    lambda body, tail: body + tail,
    _DOCUMENT_BODIES,
    st.lists(_UTF8_CHARACTERS, min_size=0, max_size=12).map("".join),
)

_SPAN_KINDS = (
    "in-bounds", "in-bounds", "in-bounds",  # weighted: the true cases must dominate
    "out-of-bounds", "negative", "inverted", "mid-codepoint",
)


@st.composite
def spans_over(draw, documents=None):
    """Every declared span kind over the drawn document.

    In-bounds spans are drawn with the exact slice, a one-byte near miss, or a
    whitespace-mutated text — the three mutants a byte-exact `verify_span` must reject
    and a fuzzy one would accept.
    """
    doc = Doc(markdown=draw(documents or DOCUMENTS))
    n = len(doc.markdown)
    kind = draw(st.sampled_from(_SPAN_KINDS))
    if kind == "in-bounds":
        start = draw(st.integers(0, n))
        end = draw(st.integers(start, n))
        text = draw(st.sampled_from([
            doc.markdown[start:end],  # the exact slice — the True case
            doc.markdown[start:end] + "x",  # one byte off — the near miss
            doc.markdown[start:end].rstrip() if doc.markdown[start:end] else "",  # whitespace
        ]))
    elif kind == "out-of-bounds":
        start = draw(st.integers(0, max(n, 1)))
        end = draw(st.integers(n + 1, n + 8)) if n else draw(st.integers(1, 8))
        text = draw(st.text(max_size=8))
    elif kind == "negative":
        start = draw(st.integers(-8, -1))
        end = draw(st.integers(start, n))
        text = draw(st.text(max_size=8))
    elif kind == "inverted":
        start = draw(st.integers(1, n))
        end = draw(st.integers(0, start - 1))
        text = draw(st.text(max_size=8))
    else:  # mid-codepoint
        multibyte = [i for i, ch in enumerate(doc.markdown) if ord(ch) > 0x7F]
        if not multibyte:
            start = draw(st.integers(0, n))
        else:
            start = draw(st.sampled_from(multibyte)) + draw(st.sampled_from([1, 2]))
        end = min(start + draw(st.integers(1, 4)), n + 4)
        text = draw(st.sampled_from(["é", "中", "🧪", "x"]))
    return doc, Span(start, end, text), kind


def in_bounds(doc: Doc, span: Span) -> bool:
    """The bounds half of the invariant: `0 <= start <= end <= len(markdown)`."""
    return 0 <= span.start <= span.end <= len(doc.markdown)


def expected_verify(doc: Doc, span: Span) -> bool:
    """The invariant's right-hand side, stated once: bytes match AND in bounds."""
    return in_bounds(doc, span) and doc.markdown[span.start:span.end] == span.text
