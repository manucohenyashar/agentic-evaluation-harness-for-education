"""`TC-INTEG-09` (property) and `FUZZ-03` — the `verify_span` invariant over generated
(document, span) pairs.

Test plan §5.9 / §6.7, case for `FR-INTEG-01`, `FR-EXTRACT-01` (P0). Written ahead of
`#73` (test plan §8.2): every case fails only through `NotImplementedYet` naming `#73`.

**The invariant is the whole oracle** (§6.7's crash criterion, verbatim): `verify_span`
returns a bool for every input and never raises, and it is `True` **exactly** when the
bytes match and the span is in bounds — no third state, no exception channel, no
normalization. The generator (`tests/support/span_strategies.py`, guarded by
`test_span_corpus_generators.py`) crosses every declared document kind (ASCII,
multi-byte UTF-8, CRLF, empty) with every declared span kind (in-bounds, out-of-bounds,
negative, inverted, mid-codepoint), so a `verify_span` that special-cases any one of
them — silently truncating a mid-codepoint slice, accepting a whitespace-normalized
quote, letting a negative offset raise — fails here.

Interface assumed of `#73` (reconcile at landing): `aeh.integ.verify_span(doc, span)`
module-level and pure; `doc` needs `.markdown`, `span` needs `.start`/`.end`/`.text`
(CT-EXTRACT-01) — `tests/support/integ_vocabulary.py` supplies both records.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings

from tests.support.impl import INTEG_MODULE, require
from tests.support.span_strategies import (
    FUZZ_EXAMPLES,
    expected_verify,
    spans_over,
)

pytestmark = [pytest.mark.property, pytest.mark.writtenahead]


# --- the property ---------------------------------------------------------------------------

@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(spans_over())
def test_fuzz_03_verify_span_is_true_exactly_when_bytes_match_and_in_bounds(case):
    """`FUZZ-03` — `verify_span` returns a bool for every input, never raises, and is
    `True` exactly when the bytes match and the span is in bounds."""
    verify_span = require(INTEG_MODULE, "verify_span", issue="#73")
    doc, span, _kind = case
    try:
        result = verify_span(doc, span)
    except Exception as error:  # noqa: BLE001 - the invariant forbids *any* escape
        pytest.fail(
            f"verify_span raised {error!r} on start={span.start} end={span.end} "
            f"text={span.text!r} over a {len(doc.markdown)}-byte document — the "
            "invariant is 'returns a bool for every input and never raises'"
        )
    assert isinstance(result, bool)
    assert result is expected_verify(doc, span), (
        f"verify_span returned {result!r} for start={span.start} end={span.end} "
        f"text={span.text!r}; the invariant says {expected_verify(doc, span)} — "
        "byte-exact match and in bounds, nothing else (FR-INTEG-01, no normalization)"
    )


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(spans_over())
def test_tc_integ_09_result_is_a_function_of_the_bytes_alone(case):
    """`TC-INTEG-09`'s purity half: the same bytes and span give the same verdict —
    the invariant holds under repetition, which a memoizing or stateful `verify_span`
    breaks while passing the one-shot property above."""
    verify_span = require(INTEG_MODULE, "verify_span", issue="#73")
    doc, span, _kind = case
    first = verify_span(doc, span)
    second = verify_span(doc, span)
    assert first is second, (
        f"verify_span was not deterministic: {first!r} then {second!r} for the same "
        "inputs — NFR-INTEG-02 declares a pure function of (document bytes, span)"
    )
