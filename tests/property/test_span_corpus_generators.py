"""The `FUZZ-03` strategies asserted before anything depends on them (issue #75).

The `test_fuzz_generators.py` precedent for `FUZZ-06`/`FUZZ-07`, applied to `FUZZ-03`:
the fuzz cases themselves are written ahead of `#73`, but the *generator* is runnable
today, and a degenerate corpus is the one failure the invariant cannot catch — it would
pass green over input that never contained a counterexample.

**How a whole corpus is collected.** `@given` hands over one example at a time and
cannot express "all declared kinds appeared". Drawing fixed-size lists looks like the
answer and is not (see `test_fuzz_generators.py`'s module docstring). So the case runs
its own `@given` function to completion and asserts on what accumulated — the real
strategies under the real profile.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings

from tests.support.span_strategies import DOCUMENTS, spans_over

pytestmark = pytest.mark.property


def _kind_of_document(markdown: str) -> str:
    if not markdown:
        return "empty"
    if "\r\n" in markdown:
        return "crlf"
    if any(ord(ch) > 0xFFFF for ch in markdown):
        return "4-byte"
    if any(ord(ch) > 0x7F for ch in markdown):
        return "multibyte"
    return "ascii"


def test_fuzz_03_corpus_contains_every_declared_document_kind():
    """§6.7's document column: ASCII, multi-byte UTF-8, CRLF, empty — all four must
    appear, or the property runs green over a corpus missing the encodings it exists
    for."""
    seen: set[str] = set()

    @settings(max_examples=200, deadline=None)
    @given(DOCUMENTS)
    def collect(markdown: str) -> None:
        seen.add(_kind_of_document(markdown))

    collect()

    assert {"empty", "ascii", "crlf", "multibyte"} <= seen, (
        f"document generator covers only {sorted(seen)} — §6.7 declares all four kinds"
    )


def test_fuzz_03_corpus_contains_every_declared_span_kind_and_true_cases():
    """§6.7's span column: in-bounds, out-of-bounds, negative, inverted, mid-codepoint —
    and at least one in-bounds exact match, so the invariant's True arm cannot go
    vacuous (a `verify_span` that always returns `False` would pass it)."""
    seen_kinds: set[str] = set()
    true_cases = 0

    @settings(max_examples=300, deadline=None)
    @given(spans_over())
    def collect(case) -> None:
        nonlocal true_cases
        doc, span, kind = case
        seen_kinds.add(kind)
        if 0 <= span.start <= span.end <= len(doc.markdown):
            if doc.markdown[span.start:span.end] == span.text:
                true_cases += 1

    collect()

    assert {
        "in-bounds", "out-of-bounds", "negative", "inverted", "mid-codepoint"
    } <= seen_kinds, (
        f"span generator covers only {sorted(seen_kinds)} — the near-miss kinds are "
        "the ones a fuzzy verify_span survives"
    )
    assert true_cases > 0, (
        "no generated case is an exact in-bounds match — the True arm of the "
        "verify_span invariant would be vacuous"
    )
