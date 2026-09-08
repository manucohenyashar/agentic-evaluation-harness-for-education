"""The hypothesis strategies `TC-INTEG-09` and `FUZZ-03` depend on, asserted before
anything depends on them (issue #75; the `test_fuzz_generators.py` precedent for
FUZZ-06/07, applied to §6.7's `FUZZ-03` row).

§6.7 declares the generator as a spec, not a detail: *"Generated documents (ASCII,
multi-byte UTF-8, CRLF, empty) crossed with generated spans (in-bounds, out-of-bounds,
negative, inverted, mid-codepoint)"*. The strategies below are that row, and
`tests/property/test_span_corpus_generators.py` holds the degeneracy guard that keeps
them honest — because the failure mode of a fuzz case is not "the invariant failed",
it is "the invariant passed over a corpus that never contained a counterexample".

**The coordinate system is bytes** (review finding, reconciled): CT-INGEST-03 fixes
byte offsets into `document.markdown` as "the coordinate system every later stage
uses", NFR-INTEG-02 calls `verify_span` "a pure function of (document **bytes**, span)",
and FUZZ-03's invariant is "the **bytes** match". Every offset drawn or asserted here
is therefore a UTF-8 **byte** offset, and `expected_verify` compares encoded bytes —
a codepoint-slicing implementation that mis-verifies real extractor payloads on
multibyte documents fails these properties immediately. The in-bounds arm draws
offsets only at character boundaries (so the span's `text` is a well-formed `str` and
the exact-slice mutant is expressible); the mid-codepoint arm deliberately does not.
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


def _byte_length(doc: Doc) -> int:
    """The document's size in the coordinate system spans address: UTF-8 bytes."""
    return len(doc.markdown.encode("utf-8"))


def _char_boundary_offsets(doc: Doc) -> list[int]:
    """Every byte offset that starts a character (plus the end offset).

    In-bounds spans are drawn between two of these so `span.text` stays a well-formed
    `str` — a slice between boundaries decodes cleanly, which is what makes the
    exact-slice (`True`) mutant expressible alongside the one-byte-off and whitespace
    near misses.
    """
    markdown = doc.markdown
    return [len(markdown[:i].encode("utf-8")) for i in range(len(markdown) + 1)]


@st.composite
def spans_over(draw, documents=None):
    """Every declared span kind over the drawn document, offsets in bytes.

    In-bounds spans are drawn with the exact slice, a one-byte near miss, or a
    whitespace-mutated text — the three mutants a byte-exact `verify_span` must reject
    and a fuzzy one would accept.
    """
    doc = Doc(markdown=draw(documents or DOCUMENTS))
    n = _byte_length(doc)
    kind = draw(st.sampled_from(_SPAN_KINDS))
    if kind == "in-bounds":
        boundaries = _char_boundary_offsets(doc)
        i = draw(st.integers(0, len(boundaries) - 1))
        j = draw(st.integers(i, len(boundaries) - 1))
        start, end = boundaries[i], boundaries[j]
        text = draw(st.sampled_from([
            doc.markdown[i:j],  # the exact slice — the True case
            doc.markdown[i:j] + "x",  # one byte off — the near miss
            doc.markdown[i:j].rstrip() if doc.markdown[i:j] else "",  # whitespace
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
        # start > end is the point; over an empty document the offsets are still drawn
        # (both out of bounds), so the kind survives the empty-document arm.
        start = draw(st.integers(1, n)) if n >= 1 else draw(st.integers(1, 4))
        end = draw(st.integers(0, max(start - 1, 0)))
        text = draw(st.text(max_size=8))
    else:  # mid-codepoint — only meaningful in byte coordinates
        markdown_bytes = doc.markdown.encode("utf-8")
        multibyte = [
            i
            for i in range(len(markdown_bytes))
            if (markdown_bytes[i] & 0xC0) == 0xC0
        ]  # lead bytes of multi-byte sequences
        if not multibyte:
            start = draw(st.integers(0, max(n, 1)))
        else:
            # One or two bytes INTO a multi-byte sequence: a continuation byte, not a
            # character boundary — exactly the drift an extractor's byte offsets make.
            start = draw(st.sampled_from(multibyte)) + draw(st.sampled_from([1, 2]))
        end = min(start + draw(st.integers(1, 4)), n + 4)
        text = draw(st.sampled_from(["é", "中", "🧪", "x"]))
    return doc, Span(start, end, text), kind


def in_bounds(doc: Doc, span: Span) -> bool:
    """The bounds half of the invariant: `0 <= start <= end <= len(markdown)` in bytes."""
    return 0 <= span.start <= span.end <= _byte_length(doc)


def expected_verify(doc: Doc, span: Span) -> bool:
    """The invariant's right-hand side, stated once: the BYTES match AND in bounds.

    NFR-INTEG-02: "a pure function of (document bytes, span)"; FUZZ-03: "`True`
    exactly when the bytes match and the span is in bounds".
    """
    return in_bounds(doc, span) and (
        doc.markdown.encode("utf-8")[span.start:span.end] == span.text.encode("utf-8")
    )
