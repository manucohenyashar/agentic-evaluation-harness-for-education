"""`TC-JUDGE-11` — the response contract's pinned field order (`FR-JUDGE-09`,
`CT-JUDGE-05`; issue #83 (TS-31)).

Four input families, per the case table: the five fields in declared order (accepted);
a permuted order (**rejected as a contract violation rather than reordered and
accepted**); one field missing; an extra field. The oracle is the exact exception:
every non-declared shape is refused with `MalformedResponseError` naming the pinned
order it did not arrive in.

A permuted reply is not a format variation — it is a different contract. The suite
asserts that over EVERY permutation of the five fields (all 120, identity included:
exactly the declared one is accepted), because "some permutations happen to be
refused" is not the contract; "a reply whose keys arrive in another order is refused"
is.

Isolation: rung 0 — pure parser, whitelist request, no store, no provider, no model.
"""

from __future__ import annotations

import itertools
import json

import pytest

from tests.support.extract_vocabulary import JUDGE_ISSUE
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import (
    MALFORMED_ERROR,
    REPLY_FIELD_ORDER,
    RESPONSE_PARSER,
    TS31_REPLY_FIELDS,
)

#: A legal reply body, one value per declared field — built in `REPLY_FIELD_ORDER`'s
#: order so the serialization's key order IS the declared order (`verdict_completion`'s
#: disclosed stand-in serializes the same way). The assessment names the spans
#: channel, so it is an inventory and the prose gate (`FR-JUDGE-10`) stays out of the
#: way; the band is in the declared set below.
LEGAL_REPLY = {
    "cited_spans": [],
    "evidence_assessment": "the cited spans support the band",
    "evidence_sufficient": True,
    "band": "secure",
    "self_confidence": 0.5,
}

#: Every ordering of the five keys, identity included — 120 cases; exactly the declared
#: one may parse.
ALL_ORDERS = tuple(itertools.permutations(REPLY_FIELD_ORDER))

#: The non-identity permutations — every one of these is a contract violation.
PERMUTED_ORDERS = tuple(order for order in ALL_ORDERS if order != REPLY_FIELD_ORDER)

#: Each field dropped once, its remaining fields in declared order.
MISSING_ORDERS = tuple(
    tuple(name for name in REPLY_FIELD_ORDER if name != dropped)
    for dropped in REPLY_FIELD_ORDER
)

#: One extra field, in three positions — before, between, after — over the declared
#: five, which stay in their pinned order among themselves.
EXTRA_ORDERS = (
    ("extra_field",) + REPLY_FIELD_ORDER,
    REPLY_FIELD_ORDER[:3] + ("extra_field",) + REPLY_FIELD_ORDER[3:],
    REPLY_FIELD_ORDER + ("extra_field",),
)


def _request():
    """A whitelist-built `ScoringRequest` with the declared set `LEGAL_REPLY` uses."""
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
        work_id="w-tj11",
        criterion=CriterionView(
            criterion_id="C1",
            text="explain X",
            bands=(
                BandView(
                    band="emerging", ordinal=0, descriptor="the criterion is partly met"
                ),
                BandView(band="secure", ordinal=1, descriptor="the criterion is met"),
            ),
        ),
        question=QuestionView(prompt_text="prompt", reference_solution="ref"),
        evidence=(),
        dependency_evidence=(),
        submission=SubmissionView(submission_id="s-1", student_ref="ref-1"),
        submission_text="the submission text",
    )


def _malformed_error():
    """The exact exception the case table pins."""
    return require("aeh.prov", MALFORMED_ERROR, issue=JUDGE_ISSUE)


def _parser():
    """The response contract's one parse-and-validate door."""
    return require(JUDGE_MODULE, RESPONSE_PARSER, issue=JUDGE_ISSUE)


def _text(order) -> str:
    """Serialize `LEGAL_REPLY`'s values under `order`'s key sequence — `json.dumps`
    writes a dict's keys in insertion order, so the wire text carries exactly the
    order given."""
    return json.dumps({name: LEGAL_REPLY[name] for name in order})


def _refused(order):
    """Parse the reply serialized in `order`'s order and return the raised
    `MalformedResponseError`, asserting the refusal happened."""
    MalformedResponseError = _malformed_error()
    try:
        verdict = _parser()(_text(order), _request())
    except MalformedResponseError as error:
        return error
    raise AssertionError(
        f"a reply with fields {list(order)} was ACCEPTED as {verdict!r} — a "
        f"non-declared field order was reordered-and-accepted, the exact failure "
        f"FR-JUDGE-09 forbids (reordering is not a format variation)"
    )


# --- declared order accepted -----------------------------------------------------------------------


def test_tc_judge_11_a_declared_order_is_accepted_and_carries_the_reply_s_values():
    """The declared order parses, and the verdict carries the reply's own values:
    band, its declared ordinal, confidence, sufficiency, the (empty) span inventory."""
    parser, REPLY_FIELDS = require(
        JUDGE_MODULE, RESPONSE_PARSER, TS31_REPLY_FIELDS, issue=JUDGE_ISSUE
    )
    assert tuple(REPLY_FIELDS) == REPLY_FIELD_ORDER, (
        "precondition: the module's declared order is the pinned one"
    )
    verdict = parser(_text(REPLY_FIELD_ORDER), _request())
    assert verdict.band == LEGAL_REPLY["band"]
    assert verdict.band_ordinal == 1
    assert verdict.self_confidence == LEGAL_REPLY["self_confidence"]
    assert verdict.evidence_sufficient is LEGAL_REPLY["evidence_sufficient"]
    assert verdict.cited_spans == ()


def test_tc_judge_11_b_a_json_object_reserialized_in_declared_order_still_parses():
    """The contract is about the WIRE text's key order: the declared-order reply is
    accepted when it arrives as the provider would send it (compact separators), not
    only as the exact fixture string."""
    parser = _parser()
    text = json.dumps(LEGAL_REPLY)  # dict insertion order == REPLY_FIELD_ORDER
    verdict = parser(text, _request())
    assert verdict.band == "secure"


# --- permuted orders: every one refused --------------------------------------------------------------


@pytest.mark.parametrize(
    "order", PERMUTED_ORDERS, ids=["-".join(order) for order in PERMUTED_ORDERS]
)
def test_tc_judge_11_b_every_permuted_order_is_refused(order):
    """A permuted reply is refused as a contract violation — never reordered and
    accepted (`FR-JUDGE-09`). Over all 119 non-identity orderings."""
    error = _refused(order)
    assert isinstance(error, _malformed_error()), (
        f"order {list(order)} was refused with {type(error).__name__}, not "
        f"{MALFORMED_ERROR}: a contract violation must surface as the one exception "
        f"the strike loop knows"
    )


def test_tc_judge_11_c_the_refusal_names_the_pinned_order():
    """The refusal says what arrived and what the pinned order is — actionable at the
    strike, not a bare rejection."""
    error = _refused(("band",) + REPLY_FIELD_ORDER[:4])
    for name in REPLY_FIELD_ORDER:
        assert name in str(error), (
            f"the refusal should name pinned field {name!r}: {error}"
        )
    assert "FR-JUDGE-09" in str(error) or "pinned order" in str(error), (
        f"the refusal should say the order is the contract's: {error}"
    )


# --- missing and extra fields ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "order",
    MISSING_ORDERS,
    ids=["missing-" + name for name in REPLY_FIELD_ORDER],
)
def test_tc_judge_11_d_a_missing_field_is_refused(order):
    """A reply with one field dropped is not a shorter contract — it is refused with
    the exact exception, for every one of the five fields."""
    error = _refused(order)
    assert isinstance(error, _malformed_error())


@pytest.mark.parametrize(
    "order",
    EXTRA_ORDERS,
    ids=["extra-before", "extra-middle", "extra-last"],
)
def test_tc_judge_11_e_an_extra_field_is_refused(order):
    """A reply with an extra field is not a superset contract — refused with the
    exact exception, wherever the extra field sits."""
    MalformedResponseError = _malformed_error()
    body = {
        name: (1 if name == "extra_field" else LEGAL_REPLY[name]) for name in order
    }
    text = json.dumps(body)  # key order == `order`, extra field in its true position
    try:
        verdict = _parser()(text, _request())
    except MalformedResponseError as error:
        assert isinstance(error, MalformedResponseError)
        return
    raise AssertionError(
        f"a reply carrying an extra field {order!r} was ACCEPTED as {verdict!r} "
        f"(FR-JUDGE-09: the whitelist is closed, an extra field is a refusal)"
    )


def test_tc_judge_11_f_the_exact_identity_is_the_only_accepted_order():
    """The census statement of the contract: over ALL 120 orderings of the five
    fields, exactly the declared one parses and the other 119 raise the pinned
    exception."""
    accepted = 0
    for order in ALL_ORDERS:
        MalformedResponseError = _malformed_error()
        try:
            _parser()(_text(order), _request())
        except MalformedResponseError:
            continue
        accepted += 1
        assert order == REPLY_FIELD_ORDER, (
            f"order {list(order)} parsed but is not the pinned order — the field "
            f"order contract is broken"
        )
    assert accepted == 1, (
        f"{accepted} of {len(ALL_ORDERS)} field orders parsed — only the pinned "
        f"order may (FR-JUDGE-09)"
    )