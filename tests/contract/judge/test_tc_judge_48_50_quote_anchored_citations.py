"""TC-JUDGE-48…50 (#894): quote-anchored citations that survive, on every seat.

Traces: FR-JUDGE-40, FR-JUDGE-41, FR-JUDGE-42, CT-JUDGE-31, CT-JUDGE-32; RSV-01.
Source: `docs/design/statistical_validity_test_plan.md` §3.1, story T1. The implementing story
#863 (PR #918) is merged, so these cases are not written ahead: they pass against main.

| Case | Asserted |
|---|---|
| TC-JUDGE-48 | Named journey 1. The reply format is parsed out of the RENDERED prompt text (nothing imported from `aeh.judge.prompt`), a reply is built field for field from it with `cited_spans` offsets matching no offered extracted span, and it goes through the real parser and citation gate in the real worker. (a) stored cited, spans as built, `reanchored = 0`; (b) offsets +3, stored at the true occurrence, `reanchored = 1`. Sensitivity arm: with the rendered declaration reverted to `{start, end}` (the `a56e74c` defect) the same construction yields a text-less reply that is refused |
| TC-JUDGE-49 | The decision table, once per seat (the LLM seat, the decision seat, the pseudonymized-citation path of #593): verifies / off by 3 and unique / occurs twice / absent / one verifies + one relocates / correct text at another sentence's offsets. Oracle: the stored verdict row (`cited_spans`, `uncited`, `reanchored`, `scoring_engine`) or each seat's own refusal |
| TC-JUDGE-50 | A text-less span whose offsets equal an offered extracted span takes its text and is stored; one byte off is refused; offsets of a span offered to a different unit are refused |

**What "refused as today" means per seat (TC-JUDGE-49 (c)/(d), OQ-5 pinned from the code).**
- LLM seat: the citation refuses the whole reply (`MalformedResponseError`), struck on every
  attempt of the budget, then `JudgmentError`. Nothing is persisted: no verdict row.
- Decision seat: the pre-screen is written `below_gate` with reason `citation_unverified`, and the
  unit falls back to the LLM with the engine-off request (no strike); the stored verdict is the
  LLM's.
- Pseudonymized path: as the LLM seat.

**A finding pinned, not endorsed.** A relocated span whose quote is pseudonymized evidence is
stored at the real name's byte offsets with the pseudonymized text. Plain `verify_span` is False
for it; it verifies only through `_verifies_as_pseudonymized`. CT-JUDGE-32's stored invariant
("`verify_span(doc, span)` true on every stored span", TC-JUDGE-51's property arm) does not hold
for such a span. The pseudonymized seat's rows assert the `_verifies_as_pseudonymized` half only,
so a later fix to the stored form does not turn this case red.

Isolation: rung 1 on a real store, real M-INTEG, the real canonical document of ENG7 E7-001 from
the operator ingest (`tests/support/citation_world.py`). The model boundary is
`RecordedFixtureProvider`; the decision engine is a programmed `decide` double (the TS-110
precedent). Replies are built from the rendered prompt or the document's own bytes.
"""

from __future__ import annotations

import dataclasses
import json
import re

import pytest

from aeh.integ import verify_span
from aeh.store import open_store
from tests.support.citation_world import byte_span, citation_world, region_body

pytestmark = pytest.mark.contract

#: The offered extracted span on the judged C2 unit (Q2's answer).
OFFERED = "Someone might still need the light."
#: Q2 answer phrases that are NOT offered evidence.
QUOTE_A = "A small fishing boat came out of the dark"
QUOTE_B = "used the light to find the safe channel"
#: Occurs twice inside Q2's answer region (the printed question and the student's answer).
TWICE = "even though the big ships"
ABSENT = "the lighthouse was painted red"


def _off(span: dict, by: int = 3) -> dict:
    return dict(span, start=span["start"] + by, end=span["end"] + by)


def _core(span: dict) -> dict:
    return {key: span[key] for key in ("start", "end", "text")}


@pytest.fixture
def store(tmp_data_dir):
    handle = open_store(tmp_data_dir)
    try:
        yield handle
    finally:
        handle.close()


# --- TC-JUDGE-48: the reply-shape round trip --------------------------------------------------

_FORMAT = re.compile(r"in exactly this order: (\{.*\})\.\s*$", re.S)
_TOP_FIELD = re.compile(r'"(\w+)": (\[\{.*?\}\]|"[^"]*"|[^,{}]+?)(?=, "\w+": |\}$)')
_INNER_FIELD = re.compile(r'"(\w+)": ("[^"]*"|<[^>]*>)')


def _declared_reply_shape(payload) -> list[tuple[str, str]]:
    """`(field, what it holds)` pairs, in order, read from the rendered prompt text alone."""
    text = "\n".join(value for _name, value in payload.fields)
    found = _FORMAT.search(dict(payload.fields)["directive"])
    assert found, f"the rendered prompt declares no reply format: {text[:400]!r}"
    return _TOP_FIELD.findall(found.group(1))


def _band_names(payload) -> list[str]:
    return re.findall(r"^- ([^:\n]+)", dict(payload.fields)["bands"], re.M)


def _reply_from_declaration(payload, doc: bytes, start: int, end: int, *, shift: int = 0) -> dict:
    """Build a reply field for field from what the prompt declares. A cited span gets the true
    `start`/`end` (shifted by `shift`, a model that mis-counted) and, IF the declaration names a
    quoted field, the document's own bytes at the true offsets."""
    reply: dict = {}
    for field, holds in _declared_reply_shape(payload):
        if holds.startswith("[{"):
            item: dict = {}
            for key, inner in _INNER_FIELD.findall(holds):
                if "byte offset" in inner:
                    item[key] = (start if "start" in key else end) + shift
                elif inner.startswith('"'):
                    item[key] = doc[start:end].decode("utf-8")
                else:
                    raise AssertionError(f"undeclared kind of span field {key}: {inner}")
            reply[field] = [item]
        elif "band name" in holds:
            reply[field] = _band_names(payload)[-1]
        elif holds == "true or false":
            reply[field] = True
        elif "number from zero to one" in holds:
            reply[field] = 0.8
        elif holds.startswith('"'):
            reply[field] = "The cited span gives the boat that used the light as the reason."
        else:
            raise AssertionError(f"the prompt declares {field} as {holds!r}, which this case cannot fill")
    return reply


def _round_trip_world(store, make_fixture_provider):
    world = citation_world(store, make_fixture_provider(),
                           offered=[byte_span(eng7_doc(), OFFERED)])
    target = byte_span(world.doc, QUOTE_A)
    offered = {(span["start"], span["end"]) for span in world.request.evidence}
    assert offered and (target["start"], target["end"]) not in offered
    assert (target["start"] + 3, target["end"] + 3) not in offered
    return world, target


def eng7_doc() -> bytes:
    from tests.support.citation_world import eng7_canonical

    return eng7_canonical().encode("utf-8")


@pytest.mark.parametrize("arm, shift", [("a", 0), ("b", 3)])
def test_tc_judge_48_a_reply_built_from_the_rendered_prompt_is_stored_cited(
        arm, shift, store, make_fixture_provider):
    """TC-JUDGE-48 (a) and (b)."""
    from aeh.judge import prompt_fields

    world, target = _round_trip_world(store, make_fixture_provider)
    payload = prompt_fields(world.request)
    reply = _reply_from_declaration(payload, world.doc, target["start"], target["end"], shift=shift)
    assert list(reply) == [field for field, _ in _declared_reply_shape(payload)]
    row = world.judge_and_store(reply)
    assert row["uncited"] == 0
    assert [_core(span) for span in row["cited_spans"]] == [target]
    assert row["reanchored"] == (1 if arm == "b" else 0)
    assert verify_span(world.doc, row["cited_spans"][0])


def test_tc_judge_48_sensitivity_the_reverted_declaration_is_refused(
        store, make_fixture_provider, monkeypatch):
    """TC-JUDGE-48's named mutation, run as a sensitivity arm: the rendered declaration reverted
    to `[{"start", "end"}]` (what `a56e74c` shipped). A reply built from it has no `text`; its
    offsets match no offered span, so FR-JUDGE-41 has nothing to fill in, and the reply is
    refused. This is the failure arm (a) exists to catch."""
    import aeh.judge.prompt as prompt
    from aeh.judge import JudgmentError, prompt_fields

    declared = re.search(r'"cited_spans": (\[\{.*?\}\])', prompt._REPLY_FORMAT).group(1)
    monkeypatch.setattr(prompt, "_REPLY_FORMAT", prompt._REPLY_FORMAT.replace(
        declared, '[{"start": <byte offset>, "end": <byte offset>}]'))
    world, target = _round_trip_world(store, make_fixture_provider)
    reply = _reply_from_declaration(prompt_fields(world.request), world.doc,
                                    target["start"], target["end"])
    assert set(reply["cited_spans"][0]) == {"start", "end"}
    with pytest.raises(JudgmentError):
        world.judge_and_store(reply)
    assert world.verdict_rows() == []


# --- TC-JUDGE-49: the decision table, once per seat --------------------------------------------

def _llm_rows(doc: bytes) -> dict[str, tuple[list[dict], list[dict] | None, int]]:
    """row -> (cited spans, expected stored spans or None for refused, expected reanchored)."""
    a, b = byte_span(doc, QUOTE_A), byte_span(doc, QUOTE_B)
    offered = byte_span(doc, OFFERED)
    q2 = region_body(doc, "Q2")
    twice = byte_span(doc, TWICE)
    assert doc[q2[0]:q2[1]].count(TWICE.encode()) == 2, "fixture bug: (c) needs two occurrences"
    return {
        "a verifies": ([a], [a], 0),
        "b off by 3, unique": ([_off(b)], [b], 1),
        "c off, occurs twice": ([_off(twice)], None, 0),
        "d absent": ([dict(a, text=ABSENT)], None, 0),
        "e one verifies, one relocates": ([a, _off(b)], [a, b], 1),
        "f offsets at another sentence": ([dict(b, start=offered["start"], end=offered["end"])],
                                          [b], 1),
    }


_ROWS = ["a verifies", "b off by 3, unique", "c off, occurs twice", "d absent",
         "e one verifies, one relocates", "f offsets at another sentence"]


def _reply(cited: list[dict]) -> dict:
    return {"cited_spans": cited, "evidence_assessment": "The cited spans give the reason.",
            "evidence_sufficient": True, "band": "full", "self_confidence": 0.8}


@pytest.mark.parametrize("row", _ROWS)
def test_tc_judge_49_llm_seat(row, store, make_fixture_provider):
    """TC-JUDGE-49 on the LLM seat."""
    from aeh.judge import JudgmentError

    world = citation_world(store, make_fixture_provider(), offered=[byte_span(eng7_doc(), OFFERED)])
    cited, expected, reanchored = _llm_rows(world.doc)[row]
    if expected is None:
        with pytest.raises(JudgmentError, match="fails byte-exact verification"):
            world.judge_and_store(_reply(cited))
        assert world.verdict_rows() == [], "a refused reply must leave no verdict"
        return
    stored = world.judge_and_store(_reply(cited))
    assert [_core(span) for span in stored["cited_spans"]] == expected
    assert (stored["uncited"], stored["reanchored"], stored["scoring_engine"]) == (0, reanchored, "llm")
    assert all(verify_span(world.doc, span) for span in stored["cited_spans"])


JEV_BUILD = "/models/jev-fixture/model.safetensors@sha256:" + "fe" * 32


def _engine_config(fixture_dir):
    from aeh.conf import CohortRef, resolve_run_config
    from tests.support.conf_builders import edge_cfg, edge_panel
    from tests.support.orch_run import ORCH_COHORT_ID

    return resolve_run_config(
        edge_cfg(panel=edge_panel(1), HARNESS_DECISION_ENGINE="jev",
                 HARNESS_DECISION_PROVIDER="fixture", HARNESS_JEV_BUILD=JEV_BUILD,
                 HARNESS_JEV_QUANTIZATION="bf16", HARNESS_FIXTURE_DIR=str(fixture_dir),
                 # The decision verdict stands without FR-JUDGE-39's confirming call, so the
                 # stored row IS the decision seat's (the TS-110 setting).
                 HARNESS_JEV_FINAL_ON_ACCEPT="false"),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"))


class _Decider:
    """`decide` answering a confident band (top-three of four) citing every offered span."""

    def __init__(self):
        self.calls = 0

    def decision_capabilities(self, model_ref):  # noqa: ANN001
        from aeh.prov import DecisionCapabilities

        return DecisionCapabilities(32000, 255, 64, None, True)

    def decide(self, request, model_ref):  # noqa: ANN001
        from types import MappingProxyType

        from aeh.prov import Decision, NoulAnswer, ScoreAnswer, derived_confidence

        self.calls += 1
        probs = (.02, .02, .94, .02)
        answers = {"band": ScoreAnswer(sum(i * p for i, p in enumerate(probs)), probs,
                                       derived_confidence(probs), "reported"),
                   "evidence_sufficient": NoulAnswer(.97, .97, "reported")}
        for question in request.questions:
            if question.key.startswith("cite_"):
                answers[question.key] = NoulAnswer(.9, .9, "reported")
        return Decision(MappingProxyType(answers), 120, 0, 250, "typesafe/jev-1.13", None)


@pytest.mark.parametrize("row", _ROWS)
def test_tc_judge_49_decision_seat(row, store, make_fixture_provider, tmp_path):
    """TC-JUDGE-49 on the decision seat. The engine cites the request's own evidence spans, so each
    row's spans are offered as the unit's evidence (the TC-JUDGE-36 construction)."""
    world = citation_world(store, make_fixture_provider(), offered=[byte_span(eng7_doc(), OFFERED)])
    cited, expected, reanchored = _llm_rows(world.doc)[row]
    request = dataclasses.replace(world.request, evidence=tuple(
        dict(span, region_kind="transcribed_text") for span in cited))
    # The engine-off LLM answer the fallback rows reach: uncited, so only the seat's own
    # citation outcome is under test.
    world.record({"cited_spans": [], "evidence_assessment": "No span is cited for the band.",
                  "evidence_sufficient": False, "band": "limited", "self_confidence": 0.4},
                 request=request)
    decider = _Decider()
    worker = world.worker(decision_provider=decider, run_config=_engine_config(tmp_path / "jev"))
    result = worker.dispatch(request, world.judge)
    worker.persist(world.unit, result)
    stored = world.verdict_row()
    prescreen = _prescreen(store, world.unit.work_id)
    assert decider.calls == 1
    if expected is None:
        assert prescreen == [("below_gate", "citation_unverified")]
        assert (stored["scoring_engine"], stored["band"], stored["uncited"]) == ("llm", "limited", 1)
        assert stored["reanchored"] == 0
        return
    assert prescreen == [("accepted", None)]
    assert stored["scoring_engine"] == "decision"
    assert [_core(span) for span in stored["cited_spans"]] == expected
    assert (stored["uncited"], stored["reanchored"]) == (0, reanchored)
    assert all(verify_span(world.doc, span) for span in stored["cited_spans"])


def _prescreen(store, work_id):
    from tests.support.orch_run import ORCH_COHORT_ID

    return [(r["outcome"], r["reason"]) for r in store.cohort(ORCH_COHORT_ID).query(
        "SELECT outcome, reason FROM decision_prescreen WHERE work_id = :w", w=work_id)]


#: The pseudonymized seat: the roster name is set to a word E7-001's answers contain, so the
#: pseudonymization boundary rewrites answer text (as it would a student's own name written in an
#: answer) and the judge quotes the pseudonymized words back. The unit is C3 / Q3, whose answer
#: region names Tomas twice.
NAME = "Tomas"
P_QUOTE = "At first Tomas is not sure the lamp matters"
P_OTHER = "how Tomas changes by the end"
P_ELSEWHERE = "he climbs the steps a little taller"


def _pseudonymized_rows(doc: bytes, ref: str):
    def pseudo(span: dict) -> dict:
        return dict(span, text=span["text"].replace(NAME, ref))

    p, other = byte_span(doc, P_QUOTE), byte_span(doc, P_OTHER)
    elsewhere = byte_span(doc, P_ELSEWHERE)
    q3 = region_body(doc, "Q3")
    assert doc[q3[0]:q3[1]].count(NAME.encode()) == 2, "fixture bug: (c) needs the name twice"
    return {
        "a verifies": ([pseudo(p)], [pseudo(p)], 0),
        "b off by 3, unique": ([_off(pseudo(p))], [pseudo(p)], 1),
        "c off, occurs twice": ([dict(p, text=ref)], None, 0),
        "d absent": ([dict(p, text=f"{ref} painted the lighthouse red")], None, 0),
        "e one verifies, one relocates": ([pseudo(p), _off(pseudo(other))],
                                          [pseudo(p), pseudo(other)], 1),
        "f offsets at another sentence": ([dict(pseudo(p), start=elsewhere["start"],
                                                end=elsewhere["end"])], [pseudo(p)], 1),
    }


@pytest.mark.parametrize("row", _ROWS)
def test_tc_judge_49_pseudonymized_citation_path(row, store, make_fixture_provider):
    """TC-JUDGE-49 through `_verifies_as_pseudonymized` and its relocation (#593)."""
    from aeh.judge import JudgmentError
    from aeh.judge.replies import _verifies_as_pseudonymized

    world = citation_world(store, make_fixture_provider(), criterion_id="C3", question_id="Q3",
                           roster_name=NAME)
    assert world.worker()._roster_name_of(world.request) == NAME
    assert NAME not in dict(_payload_fields(world))["submission"], "precondition: names pseudonymized"
    cited, expected, reanchored = _pseudonymized_rows(world.doc, world.student_ref)[row]
    if expected is None:
        with pytest.raises(JudgmentError, match="fails byte-exact verification"):
            world.judge_and_store(_reply(cited))
        assert world.verdict_rows() == []
        return
    stored = world.judge_and_store(_reply(cited))
    assert [_core(span) for span in stored["cited_spans"]] == expected
    assert (stored["uncited"], stored["reanchored"]) == (0, reanchored)
    for span in stored["cited_spans"]:
        # Stored at the real name's offsets with the pseudonymized words: it verifies through
        # the pseudonymized check (#593). Plain verify_span is deliberately NOT asserted either
        # way: today it is False for these spans (the finding above), and pinning that would
        # turn a fix of CT-JUDGE-32 compliance red.
        assert _verifies_as_pseudonymized(world.doc, span, NAME, world.student_ref)


def _payload_fields(world):
    from aeh.judge import prompt_fields

    return prompt_fields(world.request).fields


# --- TC-JUDGE-50: offsets copied from offered evidence -----------------------------------------

def test_tc_judge_50_a_text_less_span_on_offered_offsets_takes_the_offered_text(
        store, make_fixture_provider):
    """TC-JUDGE-50: `{start, end}` equal to offered span X, no `text`: stored with X's text."""
    x = byte_span(eng7_doc(), OFFERED)
    world = citation_world(store, make_fixture_provider(), offered=[x])
    stored = world.judge_and_store(_reply([{"start": x["start"], "end": x["end"]}]))
    assert [_core(span) for span in stored["cited_spans"]] == [x]
    assert (stored["uncited"], stored["reanchored"]) == (0, 0)


@pytest.mark.parametrize("start_shift, end_shift", [(1, 0), (0, -1), (-1, 0), (0, 1)],
                         ids=["start+1", "end-1", "start-1", "end+1"])
def test_tc_judge_50_one_byte_off_the_offered_offsets_is_refused(
        start_shift, end_shift, store, make_fixture_provider):
    """TC-JUDGE-50's boundary: `(start+1, end)` (and its three neighbours) with no text matches
    no offered span, carries no quote to re-anchor, and is refused."""
    from aeh.judge import JudgmentError

    x = byte_span(eng7_doc(), OFFERED)
    world = citation_world(store, make_fixture_provider(), offered=[x])
    with pytest.raises(JudgmentError, match="fails byte-exact verification"):
        world.judge_and_store(_reply([{"start": x["start"] + start_shift,
                                       "end": x["end"] + end_shift}]))
    assert world.verdict_rows() == []


def test_tc_judge_50_offsets_offered_to_a_different_unit_are_refused(
        store, make_fixture_provider):
    """TC-JUDGE-50's negative: the run's C3 unit was offered Y (Q3's answer); the C2 unit's reply
    cites Y's offsets with no text. Y was not offered in THIS unit's request, so it is refused."""
    from aeh.judge import JudgmentError

    doc = eng7_doc()
    x, y = byte_span(doc, OFFERED), byte_span(doc, P_QUOTE)
    world = citation_world(store, make_fixture_provider(), offered=[x],
                           others=[("C3", "Q3", [y])])
    assert [(s["start"], s["end"]) for s in world.request.evidence] == [(x["start"], x["end"])]
    with pytest.raises(JudgmentError, match="fails byte-exact verification"):
        world.judge_and_store(_reply([{"start": y["start"], "end": y["end"]}]))
    assert world.verdict_rows() == []
