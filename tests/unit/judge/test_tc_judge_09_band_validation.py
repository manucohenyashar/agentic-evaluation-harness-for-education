"""`TC-JUDGE-09` — band validation against the criterion's declared set (`FR-JUDGE-04`;
issue #83 (TS-31)).

Five inputs, per the case table: one band IN the declared set (accepted, carrying its
declared ordinal), one plainly not in it, one differing only by case, one empty string,
one numeral. Only a band from the declared set is accepted — the others are refused as
contract violations with the exact exception, `MalformedResponseError` (`aeh.prov`'s,
the `ProviderError` the strike loop knows).

**Case-sensitivity is declared and asserted**: matching is the declared set's own
exact-match reading — `"SECURE"` is NOT `"secure"`, so a case-differing band is refused
with the same refusal an out-of-set name gets. The refusal message names the
criterion's declared set (sorted), which is what makes the strike actionable at the
boundary it fires at.

Isolation: rung 0 — the parser is pure, driven through the declared door
(`judge_vocabulary.RESPONSE_PARSER`, `_verdict_of`) with a whitelist-built request; no
store, no provider, no model. A refusal never becomes a verdict on any path this file
exercises, so no fallback band can hide here (`CT-JUDGE-11`, `NFR-JUDGE-05`).
"""

from __future__ import annotations

import json

from tests.support.extract_vocabulary import JUDGE_ISSUE
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import (
    MALFORMED_ERROR,
    REPLY_FIELD_ORDER,
    RESPONSE_PARSER,
    TS31_REPLY_FIELDS,
)

#: The declared set the criterion in these cases carries — two bands, distinct
#: ordinals and descriptors, exactly the shape `_rubric_of` builds from the store.
DECLARED_BANDS = (
    ("emerging", 0, "the criterion is partly met"),
    ("secure", 1, "the criterion is met"),
)
DECLARED_ORDINALS = {name: ordinal for name, ordinal, _d in DECLARED_BANDS}

#: The reply's five fields in their pinned order, with the assessment phrased as an
#: inventory (it names the spans channel), so the ONLY variable under test is the band.
_LEGAL_ASSESSMENT = "the cited spans support the band"


def _request(work_id: str = "w-tj09"):
    """A whitelist-built `ScoringRequest` carrying `DECLARED_BANDS` (rung 0: pure)."""
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
        work_id=work_id,
        criterion=CriterionView(
            criterion_id="C1",
            text="explain X",
            bands=tuple(
                BandView(band=name, ordinal=ordinal, descriptor=descriptor)
                for name, ordinal, descriptor in DECLARED_BANDS
            ),
        ),
        question=QuestionView(prompt_text="prompt", reference_solution="ref"),
        evidence=(),
        dependency_evidence=(),
        submission=SubmissionView(submission_id="s-1", student_ref="ref-1"),
        submission_text="the submission text",
    )


def _reply(band: str, request=None) -> str:
    """A legal five-field reply whose ONLY varied part is the band."""
    return json.dumps(
        {
            "cited_spans": [],
            "evidence_assessment": _LEGAL_ASSESSMENT,
            "evidence_sufficient": True,
            "band": band,
            "self_confidence": 0.5,
        }
    )


def _malformed_error():
    """The exact exception the case table pins, resolved from where it lives."""
    return require("aeh.prov", MALFORMED_ERROR, issue=JUDGE_ISSUE)


def _parse(band: str, request) -> object:
    """Parse a reply carrying `band` against `request` — raising whatever the parser
    raises, returning the verdict when it accepts."""
    parser = require(JUDGE_MODULE, RESPONSE_PARSER, issue=JUDGE_ISSUE)
    return parser(_reply(band), request)


def _parse_refusing(band: str, request=None):
    """Parse a reply carrying `band` and return the raised `MalformedResponseError`,
    asserting the refusal happened — the shared shape of the negative cases."""
    MalformedResponseError = _malformed_error()
    request = request if request is not None else _request()
    try:
        verdict = _parse(band, request)
    except MalformedResponseError as error:
        return error
    raise AssertionError(
        f"band {band!r} produced a verdict {verdict!r} instead of a refusal — a "
        f"contract violation was accepted or answered with a fallback "
        f"(FR-JUDGE-04, CT-JUDGE-11, NFR-JUDGE-05)"
    )


# --- the accepted input --------------------------------------------------------------------------


def test_tc_judge_09_a_band_in_the_declared_set_is_accepted_with_its_declared_ordinal():
    """The in-set case: the reply parses, the band is the name given, and the
    `band_ordinal` is the DECLARED set's ordinal for it — never a position guessed
    from anything else (`FR-JUDGE-04`)."""
    parser, REPLY_FIELDS = require(
        JUDGE_MODULE, RESPONSE_PARSER, TS31_REPLY_FIELDS, issue=JUDGE_ISSUE
    )
    for name, ordinal, _descriptor in DECLARED_BANDS:
        verdict = _parse(name, _request())
        assert verdict.band == name
        assert verdict.band_ordinal == DECLARED_ORDINALS[name] == ordinal


def test_tc_judge_09_the_declared_set_the_parser_checks_against_is_the_request_s():
    """The parser reads the declared set off the request's criterion, not off a module
    constant: a request built with a DIFFERENT set accepts and refuses different
    bands, in exactly the same way."""
    ScoringRequest, CriterionView, BandView, QuestionView, SubmissionView = require(
        JUDGE_MODULE,
        "ScoringRequest",
        "CriterionView",
        "BandView",
        "QuestionView",
        "SubmissionView",
        issue=JUDGE_ISSUE,
    )
    request = ScoringRequest(
        work_id="w-tj09-alt",
        criterion=CriterionView(
            criterion_id="C1",
            text="explain X",
            bands=(
                BandView(band="novice", ordinal=0, descriptor="not yet met"),
                BandView(band="proficient", ordinal=1, descriptor="the criterion is met"),
            ),
        ),
        question=QuestionView(prompt_text="prompt", reference_solution="ref"),
        evidence=(),
        dependency_evidence=(),
        submission=SubmissionView(submission_id="s-1", student_ref="ref-1"),
        submission_text="the submission text",
    )
    verdict = _parse("proficient", request)
    assert verdict.band == "proficient" and verdict.band_ordinal == 1
    # "secure" was legal under the first criterion and is refused under this one —
    # the set being checked is the request's own.
    error = _parse_refusing("secure", request)
    assert "'secure'" in str(error), f"the refusal must name the band: {error}"


# --- the four refused inputs ----------------------------------------------------------------------


def test_tc_judge_09_b_out_of_set_band_is_refused_with_the_exact_exception():
    """A band the criterion never declared is a contract violation: refused with the
    exact exception, never answered with a fallback (`CT-JUDGE-11`, `NFR-JUDGE-05`)."""
    error = _parse_refusing("outstanding")
    assert isinstance(error, _malformed_error())
    assert "'outstanding'" in str(error), f"the refusal must name the band: {error}"
    assert "outside the criterion's declared set" in str(error)


def test_tc_judge_09_c_case_differing_band_is_refused_case_sensitively():
    """`"SECURE"` is not `"secure"`: the declared-set check is case-sensitive exact
    match, and the case-differing input is refused with the same exception an
    out-of-set name gets (the case-sensitivity behaviour the case table declares)."""
    error = _parse_refusing("SECURE")
    assert isinstance(error, _malformed_error())
    assert "'SECURE'" in str(error), f"the refusal must name the band: {error}"
    assert "outside the criterion's declared set" in str(error)


def test_tc_judge_09_d_empty_band_string_is_refused():
    """The empty string is not a band: refused as a `MalformedResponseError` — never
    accepted as 'no band given'."""
    error = _parse_refusing("")
    assert isinstance(error, _malformed_error())
    assert "band" in str(error), f"the refusal must be about the band: {error}"


def test_tc_judge_09_e_numeral_band_is_refused():
    """`"95"` is a score, not a band name — a numeral masquerading as a band label is
    exactly the input the prohibition exists to refuse (`FR-JUDGE-04`; R40's judge
    half)."""
    error = _parse_refusing("95")
    assert isinstance(error, _malformed_error())
    assert "'95'" in str(error), f"the refusal must name the band: {error}"


def test_tc_judge_09_f_no_refused_band_produces_a_fallback_verdict():
    """The refusal is the WHOLE story at the parser: no nearest-band repair, no
    default. Every refusal-shaped input raises; none returns a verdict at all."""
    for band in ("outstanding", "SECURE", "", "95", "Secure", "secure ", "secure."):
        error = _parse_refusing(band)
        assert isinstance(error, _malformed_error()), (
            f"band {band!r} was refused with {type(error).__name__}, not "
            f"{MALFORMED_ERROR}: the contract's one refusal exception is being "
            f"bypassed (FUZZ-04's oracle reads the same door)"
        )


def test_tc_judge_09_g_the_refusal_message_names_the_declared_set():
    """The refusal is actionable where it fires: the message carries the criterion's
    declared set, so whoever reads the strike sees what WOULD have been accepted."""
    error = _parse_refusing("outstanding")
    for name in DECLARED_ORDINALS:
        assert name in str(error), (
            f"the refusal should name declared band {name!r}: {error}"
        )


def test_tc_judge_09_h_the_field_order_the_replies_are_built_in_is_the_pinned_one():
    """The five fields this suite builds replies in are the contract's five, in the
    pinned order — the declared-order check (`TC-JUDGE-11`'s oracle) reads the same
    tuple this file asserts against."""
    REPLY_FIELDS = require(JUDGE_MODULE, TS31_REPLY_FIELDS, issue=JUDGE_ISSUE)
    assert tuple(REPLY_FIELDS) == REPLY_FIELD_ORDER