"""`TC-JUDGE-15` — the assessment inventory contract and its ONE amendment
re-request (`FR-JUDGE-10`, `FR-PROV-06`, §2.3 Q-13; issue #83 (TS-31)).

Three `evidence_assessment` families, per the case table:

- an inventory referencing **spans** — validates on the first attempt;
- an inventory referencing a **band condition** (a declared descriptor quoted) —
  validates on the first attempt;
- **free evaluative prose** with no span reference — rejected, re-requested **ONCE**,
  then accepted with the `assessment_amended` integrity flag set (the flag asserted,
  not the response discarded), and the re-request asserted to be a **new call with a
  modified payload** — the second call's assembled payload differs from the first's —
  never a re-sample of the same request, which is the `FR-PROV-06` line Q-13 turns on.

The amendment's shape is pinned: exactly one field is inserted (the static
ground-rules correction, `judge_vocabulary.ASSESSMENT_AMENDMENT_FIELD`), immediately
BEFORE the final submission field, so the submission stays LAST (`FR-JUDGE-07`) and
every field other than the insertion is byte-identical. The amendment TEXT is static —
the same bytes for every unit — asserted across two different submissions. The
re-request budget is the `HARNESS_JUDGE_ASSESSMENT_RETRIES` knob, default one, read at
call time: zero is REFUSED (a silent disable would turn the mandated correction into a
no-op), a widened budget earns a second amendment, and a prose-only reply that recurs
after the budget is spent strikes like any other refusal (`JudgmentError` at the
strike budget, `NFR-JUDGE-05`).

Isolation: rung 0 — a scripted in-process provider double (recorded calls, no
transport), `store=None` (the replies are uncited, so the citation gate passes
vacuously and no store exists to verify against), no model, no network.
"""

from __future__ import annotations

import json

import pytest

from tests.support.extract_vocabulary import JUDGE_ISSUE
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import (
    ASSESSMENT_AMENDMENT_FIELD,
    ASSESSMENT_AMENDED_FLAG,
    ASSESSMENT_RETRIES_KNOB,
    MALFORMED_ERROR,
    PROSE_ERROR,
)

#: The build id the dispatches are addressed by (a judge names a build identity,
#: `FR-CONF-03`).
JUDGE_BUILD = "judge-build-tj15"

#: Magnitude-only prose, no evidence channel named — the refused family. Each string
#: matches the configured magnitude phrases and names no span, offset, citation,
#: excerpt, passage or quote.
PROSE_ONLY_ASSESSMENTS = (
    "truly excellent work throughout",
    "good",
    "an adequate attempt",
    "weak overall",
)

#: Inventories that VALIDATE — the two accepted families from the case table.
SPAN_INVENTORY = "the cited spans at the quoted offsets support the band"
BAND_CONDITION_INVENTORY = 'the work meets the declared condition "the criterion is met"'


class ScriptedProvider:
    """The provider double for rung 0: pops one scripted `Completion` per call and
    records every payload it was handed — the record the payload-difference oracle
    reads. `store=None` dispatch never verifies citations here, so no canonical
    document is needed and the double stays transport-free."""

    def __init__(self, completions):
        self._completions = list(completions)
        self.calls = []

    def complete(self, payload, judge, params):
        self.calls.append(payload)
        return self._completions.pop(0)


def _completion(text: str):
    """A raw `Completion` carrying the reply text verbatim — the wire form."""
    from aeh.prov import Completion

    return Completion(
        text=text,
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        resolved_build=JUDGE_BUILD,
        cached_prefix_tokens=0,
        cost=None,
    )


def _reply_text(
    assessment: str,
    *,
    band: str = "secure",
    confidence: float = 0.5,
) -> str:
    """A five-field reply in the pinned order with the given assessment."""
    return json.dumps(
        {
            "cited_spans": [],
            "evidence_assessment": assessment,
            "evidence_sufficient": True,
            "band": band,
            "self_confidence": confidence,
        }
    )


def _request(work_id: str = "w-tj15"):
    """A whitelist-built `ScoringRequest` with a two-band criterion."""
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


def _dispatch(assessments, request=None, work_id: str = "w-tj15"):
    """Dispatch one request against a provider scripted with `assessments` — one
    reply per scripted assessment, in order. Returns `(result_or_error, provider)`;
    a refusal is recorded, not swallowed."""
    provider = ScriptedProvider([_completion(_reply_text(a)) for a in assessments])
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue=JUDGE_ISSUE)
    worker = ScoringWorker(store=None, provider=provider, judge=JUDGE_BUILD)
    request = request if request is not None else _request(work_id)
    try:
        result = worker.dispatch(request, JUDGE_BUILD)
    except Exception as error:
        return error, provider
    return result, provider


# --- the two validating inventories -----------------------------------------------------------------


@pytest.mark.parametrize(
    "assessment",
    [
        "the cited spans at the quoted offsets support the band",
        'the work meets the declared condition "the criterion is met"',
    ],
    ids=["span-inventory", "band-condition-inventory"],
)
def test_tc_judge_15_a_an_inventory_assessment_validates_on_the_first_attempt(
    assessment,
):
    """An assessment that references spans or a band condition is an inventory: it
    parses, is accepted on the FIRST attempt, carries no integrity flag and no strike
    notes — the response is not merely tolerated, it is clean."""
    result, provider = _dispatch([assessment])
    assert result.attempts == 1, f"notes={result.notes!r}"
    assert result.integrity_flags == ()
    assert result.notes is None
    assert result.band == "secure" and result.evidence_sufficient is True
    assert len(provider.calls) == 1, "no re-request happens for an inventory"


def test_tc_judge_15_b_prose_only_refusal_is_the_declared_subtype():
    """At the parser door, the prose-only refusal is the exact `ProseAssessmentError`
    subtype of `MalformedResponseError` — the re-request trigger — while the same
    reply with an evidence reference is not prose and parses."""
    parser, ProseAssessmentError = require(
        JUDGE_MODULE, "_verdict_of", PROSE_ERROR, issue=JUDGE_ISSUE
    )
    malformed = require("aeh.prov", MALFORMED_ERROR, issue=JUDGE_ISSUE)
    request = _request()
    for prose in PROSE_ONLY_ASSESSMENTS:
        with pytest.raises(ProseAssessmentError):
            parser(_reply_text(prose), request)
        assert issubclass(ProseAssessmentError, malformed), (
            "the re-request trigger must ride the malformed-reply strike path"
        )
    verdict = parser(_reply_text(SPAN_INVENTORY), request)
    assert verdict.evidence_assessment == SPAN_INVENTORY


# --- the prose family: refused, re-requested ONCE, accepted with the flag ----------------


@pytest.mark.parametrize(
    "assessment",
    [
        "truly excellent work throughout",
        "good",
        "an adequate attempt",
        "weak overall",
    ],
    ids=["excellent-prose", "good-prose", "adequate-prose", "weak-prose"],
)
def test_tc_judge_15_c_prose_only_assessment_is_re_requested_once_with_a_modified_payload(
    assessment,
):
    """The free-prose family: refused, re-requested ONCE with an amended payload — the
    second call's payload DIFFERS from the first's — then accepted with the integrity
    flag set and `attempts == 2`."""
    result, provider = _dispatch([assessment, SPAN_INVENTORY])

    assert result.attempts == 2, (
        f"the re-request must be the dispatch's second attempt, got {result.attempts} "
        f"(notes={result.notes!r})"
    )
    assert provider.calls[1] != provider.calls[0], (
        "the re-request went out with the SAME payload — a re-sample of the same "
        "request, which FR-PROV-06 forbids (Q-13)"
    )
    assert ASSESSMENT_AMENDED_FLAG in result.integrity_flags, (
        f"the accepted verdict must carry the amendment flag: "
        f"{result.integrity_flags!r}"
    )
    assert result.band == "secure" and result.evidence_sufficient is True, (
        "the re-requested verdict is ACCEPTED, not discarded"
    )
    assert "re-request" in result.notes or "amended" in result.notes, (
        f"the strike record should say the assessment was re-requested: "
        f"{result.notes!r}"
    )


# --- the amendment's exact payload shape ------------------------------------------------------------


def test_tc_judge_15_d_the_amendment_inserts_one_field_and_the_submission_stays_last():
    """The amended payload is the original's field sequence with EXACTLY ONE new field
    inserted immediately before the last — the submission field stays LAST
    (`FR-JUDGE-07`), every other field is byte-identical, and the inserted field is
    the declared amendment field."""
    _result, provider = _dispatch(["truly excellent work throughout", SPAN_INVENTORY])

    original = list(provider.calls[0].fields)
    amended = list(provider.calls[1].fields)
    assert len(amended) == len(original) + 1, (
        "the amendment must INSERT one field, not rewrite the payload"
    )
    names = [name for name, _value in amended]
    inserted = names.index(ASSESSMENT_AMENDMENT_FIELD)
    assert inserted == len(amended) - 2, (
        f"the amendment field sits at position {inserted} of {len(amended)} — it "
        f"must sit immediately before the final (submission) field"
    )
    assert amended[inserted][1], "the amendment carries ground-rules text, not empty"
    assert amended[:inserted] == original[:inserted], (
        "fields before the insertion must be byte-identical"
    )
    assert amended[inserted + 1:] == original[inserted:], (
        "fields after the insertion (the submission, last) must be byte-identical"
    )


def test_tc_judge_15_e_the_amendment_text_is_static_across_units():
    """The amendment is STATIC ground rules — no per-submission byte — so two
    different requests' amended renders carry the same amendment bytes, which keeps
    the invariant prefix prefix-invariant across the batch (`FR-JUDGE-06`)."""
    amendments = []
    for work_id in ("w-tj15-x", "w-tj15-y"):
        _result, provider = _dispatch(
            ["truly excellent work throughout", SPAN_INVENTORY], work_id=work_id
        )
        amendment = [
            value for name, value in provider.calls[1].fields
            if name == ASSESSMENT_AMENDMENT_FIELD
        ]
        assert len(amendment) == 1, (
            f"exactly one amendment field expected, got {len(amendment)}"
        )
        amendments.append(amendment[0])
    assert amendments[0] == amendments[1] and amendments[0], (
        "the amendment text must be the same static bytes for every unit"
    )


# --- the budget: default one, read at call time ------------------------------------------------------


def test_tc_judge_15_f_a_recurring_prose_reply_strikes_out_after_the_budget():
    """A prose-only reply that recurs after the amendment budget (default ONE) is
    spent strikes like any other refusal: the dispatch raises `JudgmentError` at the
    strike budget, no verdict exists, and the payload sequence shows exactly one
    amendment, then re-strikes on the amended render."""
    JudgmentError = require(JUDGE_MODULE, "JudgmentError", issue=JUDGE_ISSUE)
    prose = "truly excellent work throughout"
    error, provider = _dispatch([prose, prose, prose])
    assert isinstance(error, JudgmentError), (
        f"the recurring refusal must surface as JudgmentError, got {error!r}"
    )
    assert "3 attempt" in str(error), (
        f"the strike budget is three by default (ORCH_MAX_ATTEMPTS): {error}"
    )
    assert len(provider.calls) == 3, (
        f"three strikes, three provider calls; got {len(provider.calls)}"
    )
    assert provider.calls[1] != provider.calls[0], "the one amendment went out"
    assert provider.calls[2] != provider.calls[0], (
        "after the budget is spent the strike continues on the amended render"
    )


def test_tc_judge_15_g_a_zero_amendment_budget_refuses_rather_than_disabling(
    monkeypatch,
):
    """`HARNESS_JUDGE_ASSESSMENT_RETRIES=0` is refused, not honored: a misconfigured
    budget silently disabling the re-request would turn FR-JUDGE-10's mandated
    correction into a silent no-op — the knob refuses instead (the same posture every
    integer knob takes, `_env_int`'s refusal shape), and the refusal names the knob
    and the misconfiguration."""
    WorkLedgerError = require("aeh.orch", "WorkLedgerError", issue=JUDGE_ISSUE)
    monkeypatch.setenv(ASSESSMENT_RETRIES_KNOB, "0")
    prose = "truly excellent work throughout"
    error, _provider = _dispatch([prose, prose, prose])
    assert isinstance(error, WorkLedgerError), (
        f"a zero amendment budget must be REFUSED, not honored as 'no re-requests': "
        f"got {error!r}"
    )
    assert "must be positive" in str(error), (
        f"the refusal should name the misconfiguration: {error}"
    )
    assert ASSESSMENT_RETRIES_KNOB in str(error), (
        f"the refusal should name the knob: {error}"
    )


def test_tc_judge_15_h_a_wider_amendment_budget_allows_a_second_amendment(
    monkeypatch,
):
    """`HARNESS_JUDGE_ASSESSMENT_RETRIES=2`, read at call time: two prose-only
    refusals each earn an amendment (a second, differently-shaped amended render),
    and the legal third reply is accepted at `attempts == 3` — the budget the
    operator widened is the budget the dispatch uses."""
    monkeypatch.setenv(ASSESSMENT_RETRIES_KNOB, "2")
    prose = "truly excellent work throughout"
    result, provider = _dispatch([prose, prose, SPAN_INVENTORY])
    assert result.attempts == 3, f"notes={result.notes!r}"
    assert ASSESSMENT_AMENDED_FLAG in result.integrity_flags
    assert len(provider.calls) == 3
    assert provider.calls[1] != provider.calls[0], "the first amendment went out"
    assert provider.calls[2] != provider.calls[1], (
        "the second amendment is a NEW modified payload, not a replay of the first"
    )
    first_amendment = [
        value for name, value in provider.calls[1].fields
        if name == ASSESSMENT_AMENDMENT_FIELD
    ]
    second_amendment = [
        value for name, value in provider.calls[2].fields
        if name == ASSESSMENT_AMENDMENT_FIELD
    ]
    assert len(first_amendment) == 1 and len(second_amendment) == 2, (
        f"the second amendment renders ON TOP of the first: {len(first_amendment)} "
        f"and {len(second_amendment)} amendment fields"
    )