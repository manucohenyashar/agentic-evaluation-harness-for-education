"""`FUZZ-04` — the model-response parser over generated JSON replies (§6.7; issue #83,
TS-31). Traces to `FR-JUDGE-09`, `FR-JUDGE-04`.

§6.7's row, verbatim. Generator: *"valid; field-permuted; missing fields; extra fields;
wrong types; truncated mid-token; deeply nested; enormous strings"*. Invariant:
*"Parsing either yields a valid `ScoringResult` or raises `MalformedResponseError`;
never any other exception; a permuted field order is always a contract violation"*.

**The door the property drives.** `judge_vocabulary.RESPONSE_PARSER` — the shipped
`_verdict_of(text, request)`, the one parse-and-validate door every reply goes
through; `ScoringWorker.dispatch` calls it inside the strike loop, so a parser-level
oracle IS the dispatch loop's own refusal shape. The row's "valid `ScoringResult`"
reads here as the verdict the result is built FROM (the parser returns the verdict;
the `ScoringResult` wrapper and its persistence are pinned by `TC-JUDGE-15/16/18`) —
disclosed, because the parser is where the invariant's exception channel lives.

**The direction is pinned, not only the channel.** The generator hands back
`expected` beside the text: `None` for the six refusal arms (the reply MUST raise
`MalformedResponseError`) and the expected verdict fields for the two acceptance
cases (the reply MUST parse, and to what it carried). An oracle that asserted only
"verdict or `MalformedResponseError`" would pass against a parser that refuses
EVERYTHING — every refusal arm satisfied, no acceptance ever exercised. The valid
arm's expectation is what fails such a parser, and the corpus guard below keeps the
acceptance arm non-vacuous (the `test_span_corpus_generators.py` discipline).

**Fixed seed set** (§6.7's last column): the suite's hypothesis profiles are
`derandomize=True` (conftest, §4.6's flake policy), so every run replays the same
example set — the plan's "fixed seed set" is the derandomized profile, and a failure
reproduces by re-running the tier.

**Disclosed bounds.** The "deeply nested" arm is generated up to
`fuzz_strategies.MAX_REPLY_NESTING` — deliberately far below CPython's `json` scanner
recursion limit, past which `json.loads` raises `RecursionError` before any parser
code runs, so no `MalformedResponseError` can name it; the oracle is the reply
contract, not the interpreter's stack. "Enormous strings" is bounded by
`MAX_REPLY_STRING` for the same reason: the oracle is the exception channel, not a
memory-exhaustion probe.

Isolation: rung 0 — the parser is pure, driven with a whitelist-built request; no
store, no provider, no model.
"""

from __future__ import annotations

import itertools
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.support.extract_vocabulary import JUDGE_ISSUE
from tests.support.fuzz_strategies import (
    FUZZ04_BANDS,
    FUZZ04_BAND_NAMES,
    REPLY_ARMS,
    judge_replies,
)
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import (
    MALFORMED_ERROR,
    REPLY_FIELD_ORDER,
    RESPONSE_PARSER,
    TS31_REPLY_FIELDS,
)
from tests.support.span_strategies import FUZZ_EXAMPLES

pytestmark = pytest.mark.property


def _request():
    """A whitelist-built `ScoringRequest` carrying the generator's declared bands —
    the same construction `TC-JUDGE-09`'s suite drives the parser with."""
    ScoringRequest, CriterionView, BandView, QuestionView, SubmissionView = require(
        JUDGE_MODULE,
        "ScoringRequest",
        "CriterionView",
        "BandView",
        "QuestionView",
        "SubmissionView",
        issue=JUDGE_ISSUE,
    )
    return ScoringRequest(
        work_id="w-fuzz04",
        criterion=CriterionView(
            criterion_id="C1",
            text="explain X",
            bands=tuple(
                BandView(band=name, ordinal=ordinal, descriptor=descriptor)
                for name, ordinal, descriptor in FUZZ04_BANDS
            ),
        ),
        question=QuestionView(prompt_text="prompt", reference_solution="ref"),
        evidence=(),
        dependency_evidence=(),
        submission=SubmissionView(submission_id="s-fuzz04", student_ref="ref-1"),
        submission_text="the submission text",
    )


# --- the property ---------------------------------------------------------------------------------


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(judge_replies())
def test_fuzz_04_parsing_yields_a_verdict_or_the_named_refusal_never_anything_else(
    case,
):
    """`FUZZ-04` — parsing either yields the verdict the reply carried, or raises
    `MalformedResponseError`; no other exception ever escapes; and the arms that are
    contract violations by declaration are refused, never accepted."""
    parser = require(JUDGE_MODULE, RESPONSE_PARSER, issue=JUDGE_ISSUE)
    MalformedResponseError = require("aeh.prov", MALFORMED_ERROR, issue=JUDGE_ISSUE)
    text, kind, expected = case
    try:
        verdict = parser(text, _request())
    except MalformedResponseError as error:
        if expected is not None:
            pytest.fail(
                f"the {kind} arm was refused ({error!r}) over {text[:120]!r} — the "
                f"generator's declared acceptance case must parse (FR-JUDGE-09/04: "
                f"a legal reply is never refused)"
            )
        return
    except Exception as error:  # noqa: BLE001 - the invariant forbids any other escape
        pytest.fail(
            f"parsing a {kind} reply raised {type(error).__name__}: {error!r} over "
            f"{text[:120]!r} — the invariant admits only MalformedResponseError, "
            f"never any other exception (FR-JUDGE-09, FR-JUDGE-04)"
        )
    assert expected is not None, (
        f"a {kind} reply parsed as a verdict {verdict!r} — §6.7 declares {kind} "
        f"replies contract violations (FR-JUDGE-09; a contract violation is refused, "
        f"never repaired and never answered with a fallback)"
    )
    assert verdict.band == expected["band"], (
        f"the parsed band is {verdict.band!r}, the reply carried "
        f"{expected['band']!r} (FR-JUDGE-04: the band travels verbatim)"
    )
    assert verdict.band_ordinal == expected["ordinal"], (
        f"the parsed ordinal is {verdict.band_ordinal!r}, the declared set says "
        f"{expected['ordinal']} for {expected['band']!r} — never a guessed position"
    )
    assert verdict.self_confidence == expected["confidence"], (
        f"the parsed confidence is {verdict.self_confidence!r}, the reply carried "
        f"{expected['confidence']!r}"
    )
    assert verdict.evidence_assessment == expected["assessment"], (
        f"the parsed assessment is {verdict.evidence_assessment[:80]!r}, the reply "
        f"carried {expected['assessment'][:80]!r} (FR-JUDGE-09: the assessment "
        f"travels verbatim)"
    )
    assert verdict.evidence_sufficient is expected["sufficient"]
    assert verdict.cited_spans == expected["spans"], (
        f"the parsed span inventory is {verdict.cited_spans!r}, the reply carried "
        f"{expected['spans']!r} — an inventory travels verbatim"
    )


# --- the "always" clause, exhaustively --------------------------------------------------------------


def test_fuzz_04_permuted_field_order_is_always_a_contract_violation():
    """The invariant's third clause, exhaustively: EVERY non-identity permutation of
    the five pinned fields raises `MalformedResponseError`, and the identity control
    parses — 5! = 120 orders, all of them, because "always" is not a sample."""
    parser, REPLY_FIELDS = require(
        JUDGE_MODULE, RESPONSE_PARSER, TS31_REPLY_FIELDS, issue=JUDGE_ISSUE
    )
    MalformedResponseError = require("aeh.prov", MALFORMED_ERROR, issue=JUDGE_ISSUE)
    request = _request()
    legal = {
        "cited_spans": [],
        "evidence_assessment": "the cited spans support the band",
        "evidence_sufficient": True,
        "band": "secure",
        "self_confidence": 0.62,
    }
    identity = list(REPLY_FIELD_ORDER)
    assert list(REPLY_FIELDS) == identity == list(REPLY_FIELD_ORDER), (
        f"the shipped field order is {list(REPLY_FIELDS)}, the suite pins "
        f"{list(REPLY_FIELD_ORDER)}"
    )
    refused = 0
    for order in itertools.permutations(identity):
        text = json.dumps({name: legal[name] for name in order})
        if list(order) == identity:
            verdict = parser(text, request)
            assert verdict.band == "secure" and verdict.band_ordinal == 1, (
                f"the identity control must parse: {verdict!r}"
            )
            continue
        try:
            verdict = parser(text, request)
        except MalformedResponseError:
            refused += 1
            continue
        pytest.fail(
            f"the permuted field order {list(order)} parsed as {verdict!r} — reordering "
            f"is not a format variation, it is a different contract (FR-JUDGE-09)"
        )
    assert refused == 120 - 1, (
        f"{refused} of the 119 non-identity permutations were refused — every one of "
        f"them is a contract violation"
    )


# --- the corpus guard -------------------------------------------------------------------------------


def test_fuzz_04_corpus_contains_every_declared_arm_and_true_cases():
    """§6.7's generator column, all eight arms — and acceptance coverage over both
    declared bands and an uncited inventory, so the valid arm cannot go vacuous (a
    parser that refuses everything would pass the refusal arms green)."""
    seen_kinds: set[str] = set()
    valid_bands: set[str] = set()
    valid_span_counts: set[int] = set()

    @settings(max_examples=300, deadline=None)
    @given(judge_replies())
    def collect(case) -> None:
        _text, kind, expected = case
        seen_kinds.add(kind)
        if expected is not None:
            valid_bands.add(expected["band"])
            valid_span_counts.add(len(expected["spans"]))

    collect()

    assert set(REPLY_ARMS) <= seen_kinds, (
        f"reply generator covers only {sorted(seen_kinds)} — §6.7 declares all eight "
        f"arms (valid; field-permuted; missing; extra; wrong types; truncated "
        f"mid-token; deeply nested; enormous strings)"
    )
    assert valid_bands == set(FUZZ04_BAND_NAMES), (
        f"the acceptance arm covered bands {sorted(valid_bands)} — both declared "
        f"bands must parse"
    )
    assert 0 in valid_span_counts and 1 in valid_span_counts, (
        f"the acceptance arm carried span inventories {sorted(valid_span_counts)} — "
        f"the uncited (empty) and cited shapes must both parse (FR-JUDGE-12's mark "
        f"starts here)"
    )