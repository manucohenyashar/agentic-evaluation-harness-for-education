"""`TC-JUDGE-C11` — retries are transport and parse only, and no path has a fallback
(§6.11.10).

`CT-JUDGE-11` (error): *"Assert retries are **transport and parse only** — a verdict
is **never re-sampled**. Sweep semantically odd but structurally valid verdicts and
assert the call count is exactly 1 for each. Then assert a band outside the declared
set or a wrong field order is a contract violation: retry, then quarantine. The
prohibition that matters: assert there is **no fallback band and no default verdict on
any path**, by enumerating the paths rather than sampling them. A default verdict
would convert a broken judge into a confident grade."* (plan §6.11.10, verbatim)

Three cases carry the clause:

1. **odd-but-valid verdicts are never re-sampled** — semantically odd replies that
   are structurally VALID under the response contract (the other declared band at
   zero confidence, uncited yet declared sufficient; the top band at full
   confidence, cited yet declared insufficient; the middle of the range) each
   dispatch in EXACTLY ONE transport call, and the odd values ride the result
   verbatim and persist verbatim: the retry loop exists for refusals, and an odd
   reply is not a refusal — a second call for a valid verdict would be a
   re-sampled verdict, which the clause forbids;
2. **the refusal paths, enumerated** — one representative per refusal class the
   dispatch loop strikes, each driven to budget exhaustion through the real
   workers over a real run: the transport raising, invalid JSON, a wrong field
   order, a band outside the declared set, an empty band, a non-boolean
   sufficiency, a non-numeric confidence, a forged citation (byte-exact span
   verification fails), and the recurring prose-only assessment (amended once,
   then struck — three calls, the amendment's re-request counted). EVERY path ends
   the same way: `JudgmentError` carrying `No fallback verdict exists
   (NFR-JUDGE-05)` — the enumeration, not a sample;
3. **the contrast cases that keep the enumeration honest** — a plain valid verdict
   persists (the positive control: the paths above refuse, a good reply does not,
   in exactly one call), and the amendment's designed form accepts: prose once,
   then a valid reply on the AMENDED payload, is accepted WITH the
   `ASSESSMENT_AMENDED` integrity flag in exactly two calls, the amended payload
   carrying the re-request field before the submission, which stays last — the
   re-request being a modified prompt, never a verbatim replay (`FR-PROV-06`),
   and never a re-sampled verdict.

Cross-references, not duplicates: `TC-JUDGE-C04`'s second test is the band-set
refusal's DEEP form (three distinct repair shapes, exact per-repair messages); this
file carries the band path once, as one entry of the enumeration. `TC-JUDGE-C05`'s
boundary limb and the shipped suite own the order refusal at their scales; the
`TC-JUDGE-21..23` security cases cover the injection-adjacent refusals. The
quarantine's ledger shape is `M-ORCH`'s (`CT-ORCH-11`'s strike accounting, #61's
suite) — this file asserts the judge-side contract the quarantine consumes: nothing
persisted on any refusal path.

Isolation: rung 2 — real store, real workers, a transport double at the model
boundary (the call COUNT is the oracle, and the fixture key's replay collapses
counts by construction); the socket guard is autouse.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from aeh.prov import Completion, ProviderError
from aeh.store import open_store
from tests.contract.judge._drive import (
    PANEL_REFS,
    RecordingTransport,
    drive_extract,
    lease_score_units,
    seed_world,
    spans,
    verdict_rows,
)
from tests.support.extract_vocabulary import verdict_completion
from tests.support.impl import JUDGE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

#: The story that owns the response contract (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

#: The strike budget's production default (`ORCH_MAX_ATTEMPTS`) — the transport's
#: observed call count for every refusal path that exhausts it, asserted against the
#: module's own constant so the enumeration's assumption is pinned where it lives.
_BUDGET = 3

#: The canonical assessment — an inventory under `FR-JUDGE-10`'s reading (it names
#: the spans channel), so the odd-but-valid sweep never trips the prose gate.
_ASSESSMENT = "the cited spans support the band"

#: A magnitude-only assessment with no span and no band reference — the
#: `ProseAssessmentError` trigger, per the configured vocabulary's own semantics.
_PROSE_ONLY = "good work throughout"

#: The text a forged citation claims the document carries — the fixture transcript
#: does not carry it, so `verify_span` refuses: the offsets are real, the bytes are
#: not the document's own (`FR-JUDGE-17`).
_FORGED_TEXT = "the document never carried this sentence"


def _reply(*, cited: Any = None, band: str = "secure",
           confidence: Any = 0.9, sufficient: Any = True,
           assessment: str = _ASSESSMENT) -> str:
    """One reply in the pinned order, with every field controllable — the sweep's
    generator (the order is canonical; oddness is semantic only)."""
    return json.dumps({
        "cited_spans": cited,
        "evidence_assessment": assessment,
        "evidence_sufficient": sufficient,
        "band": band,
        "self_confidence": confidence,
    })


def _raw_reply(text: str) -> Any:
    """A `Completion` whose text is whatever the path needs — a raw wire answer, for
    the paths that refuse before any field can be trusted."""
    from aeh.prov import SamplingParams  # noqa: F401  (import-chain pin, see conftest)

    return Completion(
        text=text, tokens_in=0, tokens_out=0, latency_ms=0,
        resolved_build="build-judge-contract", cached_prefix_tokens=0, cost=None,
    )


def _permutation() -> str:
    """The canonical reply with its keys reversed — a different contract (`FR-JUDGE-09`
    rejects the reorder; here it is the enumeration's wrong-order entry)."""
    reply = json.loads(_reply(cited=spans()))
    return json.dumps(dict(reversed(list(reply.items()))))


#: A cited span whose offsets are real but whose text is not the document's bytes —
#: the forged citation (`FR-JUDGE-17`): verification fails byte-exactly.
_FORGED_SPANS = [dict(spans()[0], text=_FORGED_TEXT)]


def _raise_provider_error(_index: int, _payload: Any) -> Any:
    """The transport itself failing — the first refusal class (`ProviderError`)."""
    raise ProviderError("the boundary is down")


#: Semantically odd, structurally valid: (label, band, self_confidence, cited,
#: evidence_sufficient). None is a refusal — every one is a legal verdict.
_ODD_BUT_VALID: tuple[tuple[str, str, float, bool, bool], ...] = (
    ("the other declared band at zero confidence, uncited yet declared sufficient",
     "emerging", 0.0, False, True),
    ("the top band at full confidence, cited yet declared insufficient",
     "secure", 1.0, True, False),
    ("the middle of the range",
     "secure", 0.5, True, True),
)


#: The refusal paths, enumerated: (label, transport program). One representative per
#: refusal class the dispatch loop strikes — the transport raising, the parse
#: refusals, the field-order refusal, the semantic gates, the forged citation and
#: the recurring prose. `pytest.raises` at every one.
_REFUSAL_PATHS: tuple[tuple[str, Any], ...] = (
    ("the transport raises", _raise_provider_error),
    ("the reply is not JSON", _raw_reply("this is not a json document")),
    ("the fields arrive out of order", _raw_reply(_permutation())),
    ("the band is outside the declared set",
     verdict_completion("excellent", 0.9, build_id="build-judge-contract",
                        cited_spans=spans())),
    ("the band is empty",
     verdict_completion("", 0.9, build_id="build-judge-contract",
                        cited_spans=spans())),
    ("the sufficiency is not a boolean",
     _raw_reply(_reply(cited=spans(), sufficient="yes"))),
    ("the confidence is not a number",
     _raw_reply(_reply(cited=spans(), confidence="high"))),
    ("the citation fails byte-exact verification",
     verdict_completion("secure", 0.9, build_id="build-judge-contract",
                        cited_spans=_FORGED_SPANS)),
    ("the prose assessment recurs",
     verdict_completion("secure", 0.9, build_id="build-judge-contract",
                        cited_spans=spans(), evidence_assessment=_PROSE_ONLY)),
)


def _one_world(
    tmp_data_dir: Any, make_fixture_provider: Any
) -> tuple[Any, str, Any, Any, Any]:
    """One seeded, extracted run with its single score unit and assembled request —
    `(store, run_id, unit, judge_ref, request)`; the store stays OPEN (the caller
    closes it)."""
    store = open_store(tmp_data_dir)
    orchestrator, run_id, _version = seed_world(store)
    drive_extract(orchestrator, store, make_fixture_provider())
    units = lease_score_units(orchestrator)
    assert len(units) == 1, (
        f"fixture bug: the drive leased {len(units)} units — the clause's paths "
        "dispatch one request, assembled once"
    )
    unit = units[0]
    refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
    judge_ref = refs_by_build[unit.judge]
    request = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
        store, None, judge_ref
    ).assemble(unit)
    return store, run_id, unit, judge_ref, request


def test_tc_judge_c11_odd_but_valid_verdicts_are_never_resampled(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C11` case 1 (`CT-JUDGE-11`, the re-sample prohibition, rung 2, P0)
    — every semantically odd but structurally valid reply dispatches in EXACTLY one
    transport call, its odd values ride the result verbatim, and the last one
    persists verbatim: the retry loop exists for refusals, and an odd verdict is
    not a refusal."""
    store, _run_id, unit, judge_ref, request = _one_world(
        tmp_data_dir, make_fixture_provider
    )
    try:
        assert int(require(JUDGE_MODULE, "ORCH_MAX_ATTEMPTS", issue=ISSUE)) == _BUDGET, (
            "fixture bug: the production strike budget moved — the enumeration "
            "below pins its paths to the budget the module ships"
        )
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, judge_ref
        )
        for label, band, confidence, cited, sufficient in _ODD_BUT_VALID:
            transport = RecordingTransport(verdict_completion(
                band, confidence,
                build_id="build-judge-contract",
                cited_spans=spans() if cited else None,
                evidence_sufficient=sufficient,
            ))
            sweeper = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, transport, judge_ref
            )
            result = sweeper.dispatch(request, judge_ref)
            assert len(transport.calls) == 1, (
                f"{label}: the valid reply took {len(transport.calls)} transport "
                "call(s) — a structurally valid verdict is never re-sampled, so "
                "the count is exactly 1 (CT-JUDGE-11)"
            )
            assert result.band == band and result.attempts == 1, (
                f"{label}: the odd verdict came back {result.band!r} after "
                f"{result.attempts} attempt(s) — an odd reply is accepted as it "
                "arrived, not struck or re-asked (CT-JUDGE-11)"
            )
        # The sweep's last odd verdict persists with its odd values verbatim.
        worker.persist(unit, result)
        rows = verdict_rows(store, _run_id, unit.submission_id, unit.criterion_id)
        assert len(rows) == 1 and rows[0]["band"] == "secure", (
            f"fixture bug: the persisted verdict is {rows} — the sweep's last "
            "verdict is the row check, so the sweep must end before it"
        )
        assert abs(rows[0]["self_confidence"] - 0.5) < 1e-9, (
            f"the persisted row carries confidence {rows[0]['self_confidence']!r} "
            "— an odd verdict persists VERBATIM: nothing normalises it "
            "(CT-JUDGE-11)"
        )
    finally:
        store.close()


def test_tc_judge_c11_every_refusal_path_is_enumerated_and_persists_nothing(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C11` case 2 (`CT-JUDGE-11`, the prohibition, rung 2, P0) — every
    refusal path the dispatch loop knows, driven to budget exhaustion: each ends in
    `JudgmentError` carrying `No fallback verdict exists (NFR-JUDGE-05)`, makes
    exactly the budget's calls, and leaves the ledger EMPTY — the enumeration, not
    a sample."""
    store, run_id, unit, judge_ref, request = _one_world(
        tmp_data_dir, make_fixture_provider
    )
    try:
        JudgmentError = require(JUDGE_MODULE, "JudgmentError", issue=ISSUE)
        for label, program in _REFUSAL_PATHS:
            transport = RecordingTransport(program)
            worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, transport, judge_ref
            )
            with pytest.raises(JudgmentError) as raised:
                worker.dispatch(request, judge_ref)
            assert "No fallback verdict exists (NFR-JUDGE-05)" in str(raised.value), (
                f"{label}: the refusal's message does not carry the prohibition — "
                f"the error surfaced {raised.value!r}, which a caller could read "
                "as a recoverable failure rather than the verdict-shaped dead end "
                "the prohibition demands (CT-JUDGE-11, NFR-JUDGE-05)"
            )
            assert f"after {_BUDGET} attempt(s)" in str(raised.value), (
                f"{label}: the refusal does not name its budget — the message must "
                "carry the attempt accounting the quarantine's strike ledger reads "
                f"(CT-JUDGE-11): {raised.value!r}"
            )
            assert len(transport.calls) == _BUDGET, (
                f"{label}: the refusal path made {len(transport.calls)} transport "
                f"call(s), not the budget's {_BUDGET} — a strike that gives up "
                "early hides a repairable refusal, and one that never exhausts "
                "the budget never reaches the quarantine (CT-JUDGE-11)"
            )
            assert verdict_rows(store, run_id, unit.submission_id,
                                unit.criterion_id) == [], (
                f"{label}: a verdict row persisted on a refusal path — a fallback "
                "band or a default verdict on ANY path converts a broken judge "
                "into a confident grade (CT-JUDGE-11, NFR-JUDGE-05)"
            )
        # And the whole ledger is empty — nothing anywhere, not just this pair.
        handle = store.cohort(ORCH_COHORT_ID)
        rows = handle.query("SELECT COUNT(*) AS n FROM verdict")
        assert rows[0]["n"] == 0, (
            f"the refusal enumeration left {rows[0]['n']} verdict row(s) in the "
            "ledger — no path persists anything (CT-JUDGE-11, NFR-JUDGE-05)"
        )
    finally:
        store.close()


def test_tc_judge_c11_a_valid_verdict_persists_and_the_amendment_accepts(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C11` case 3 (`CT-JUDGE-11`, the contrast that keeps the enumeration
    honest, rung 2, P0) — a plain valid verdict persists in one call, and the
    amendment's designed form accepts: prose once, then a valid reply on the
    AMENDED payload, accepted with the `ASSESSMENT_AMENDED` flag in exactly two
    calls, the re-request field inserted before the submission, which stays last."""
    store, run_id, unit, judge_ref, request = _one_world(
        tmp_data_dir, make_fixture_provider
    )
    try:
        # The positive control: the paths above refuse; a good reply does not —
        # exactly one call, and the verdict row exists.
        transport = RecordingTransport(verdict_completion(
            "secure", 0.9, build_id="build-judge-contract", cited_spans=spans(),
        ))
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, transport, judge_ref
        )
        result = worker.dispatch(request, judge_ref)
        assert len(transport.calls) == 1, (
            "the positive control took more than one call — the enumeration's "
            "refusals must refuse a VALID reply never, or the sweep's contrast "
            "is void (CT-JUDGE-11)"
        )
        worker.persist(unit, result)
        rows = verdict_rows(store, run_id, unit.submission_id, unit.criterion_id)
        assert len(rows) == 1 and rows[0]["band"] == "secure", (
            f"fixture bug: the positive control's verdict is {rows} — the paths "
            "refuse, a good reply persists"
        )

        # The amendment's designed form: prose once, then a valid reply ON THE
        # AMENDED PROMPT — accepted, flagged, in exactly two calls.
        prose = verdict_completion(
            "secure", 0.9, build_id="build-judge-contract",
            cited_spans=spans(), evidence_assessment=_PROSE_ONLY,
        )
        valid = verdict_completion(
            "emerging", 0.4, build_id="build-judge-contract",
            cited_spans=spans(), evidence_assessment=_ASSESSMENT,
        )
        transport = RecordingTransport([prose, valid])
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, transport, judge_ref
        )
        result = worker.dispatch(request, judge_ref)
        assert len(transport.calls) == 2, (
            f"the amendment's designed form took {len(transport.calls)} call(s) "
            "— prose once is ONE amendment's re-request, and the second reply is "
            "the verdict (CT-JUDGE-11, FR-JUDGE-10)"
        )
        assert result.band == "emerging" and result.attempts == 2, (
            f"the amended re-request's verdict is {result.band!r} after "
            f"{result.attempts} attempt(s) — the valid reply on the amended "
            "prompt IS the verdict (CT-JUDGE-11)"
        )
        amended_flag = require(JUDGE_MODULE, "ASSESSMENT_AMENDED", issue=ISSUE)
        assert amended_flag in result.integrity_flags, (
            f"the amendment accepted without the {amended_flag!r} integrity flag "
            f"({result.integrity_flags}) — the re-request must be visible in the "
            "result's accounting (CT-JUDGE-11, FR-JUDGE-10)"
        )

        # The re-request was a MODIFIED prompt, never a verbatim replay
        # (`FR-PROV-06`): the second payload carries the amendment field, the
        # first does not, and the submission stays the last field on both.
        amendment_field = require(
            JUDGE_MODULE, "_ASSESSMENT_AMENDMENT_FIELD", issue=ISSUE
        )
        first_names = [name for name, _value in transport.payloads()[0].fields]
        second_names = [name for name, _value in transport.payloads()[1].fields]
        assert amendment_field not in first_names and amendment_field in second_names, (
            f"the amendment's re-request payload does not carry "
            f"{amendment_field!r} (first payload {first_names}, second "
            f"{second_names}) — the re-request must be a modified prompt, not a "
            "replay of the refused one (CT-JUDGE-11, FR-PROV-06)"
        )
        assert first_names[-1] == "submission" and second_names[-1] == "submission", (
            f"the amendment moved the last field (first payload ends "
            f"{first_names[-1]!r}, second {second_names[-1]!r}) — the re-request "
            "amends the instructions, never the structure (CT-JUDGE-09, "
            "CT-JUDGE-11)"
        )
        assert transport.payloads()[0].fields != transport.payloads()[1].fields, (
            "the amendment's re-request payload is byte-identical to the refused "
            "one — a verbatim replay is not a re-request (CT-JUDGE-11, FR-PROV-06)"
        )
    finally:
        store.close()