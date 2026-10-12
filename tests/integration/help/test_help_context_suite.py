"""Issue #770 — TC-HELP-06, the help context suite (console redesign test plan §3.4).

The implementation landed under #758 (PR #777): `aeh.help.context.ScreenContext` /
`parse_screen_context`, the context parameter on `HelpAssistant.ask`, the `screen_context`
prompt field, and the console edge (`aeh.console.api.ASK_CONTEXT_PARAM`, `ask_payload`,
`_help_ask` — 400 on a malformed context before anything reaches the model). Written
ahead of implementation: **no** — every case here is expected to pass.

Three arms, one test each (plus the edge half of the shape clause):

* **(a)** an ask carrying `{screen: 'wizard-stage-3', refs: [draft_id]}` is answered about
  the current screen: the model is called once, the assembled prompt carries the screen id
  and the ref verbatim in their own delimited field, and the answer references the review
  stage (the reply is the double's scripted text — that half proves the pass-through, the
  same split TC-HELP-03 states).
* **(b)** RS-14, the privacy arm: the *assembled provider prompt* — not the request envelope,
  not the UI — is swept for student text over a seeded store; and a ref that carries prose
  (a student's name) is refused before any model call, at the assistant and at the console
  edge, where a malformed context answers 400.
* **(c)** the no-context ask is byte-identical with today: exactly the pre-`FR-HELP-06`
  field set (a field that only sometimes exists must be absent, not empty — `FR-PROV-10`
  keys the fixture on the whole payload), the same bytes the public `build_prompt`
  assembles, replayed identically by a fresh `RecordedFixtureProvider` over the same
  fixtures, with the recorded reply and citations unchanged.

The model is the recorded QA double (operator plan §4 rule 7) throughout; never a live model.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import urllib.error

import pytest

from aeh.help.context import ScreenContext, parse_screen_context
from aeh.help.prompts import build_prompt
from aeh.help.retrieval import retrieve
from aeh.prov import RecordedFixtureProvider, SamplingParams, request_key
from tests.support import help_vocabulary as hv
from tests.support.conf_builders import HOSTED_JUDGE
from tests.support.guards import loopback_census

pytestmark = [pytest.mark.integration]


def _grounded_or_fail(rig, question: str) -> None:
    """Precondition, checked not assumed: the question shares an informative word with the
    packaged manuals, so the ask grounds and the model IS called (FR-HELP-02)."""
    index = getattr(rig.assistant, hv.ASSISTANT_INDEX)
    if not retrieve(index, question):
        pytest.fail(
            f"precondition: {question!r} grounds on no packaged manual passage — the ask "
            "would take the not-found path and call no model. Re-pick the question."
        )


def _refusal_problems(rig, value, *, label: str) -> list[str]:
    """One smuggled context value: `ask` refuses it with a ValueError and calls no model."""
    calls_before = len(rig.double.calls)
    problems = []
    try:
        rig.assistant.ask(hv.CONTEXT_T.question, value)
    except ValueError:
        pass
    else:
        problems.append(f"{label}: {value!r} was admitted to the ask, not refused")
    if len(rig.double.calls) != calls_before:
        problems.append(
            f"{label}: the refusal came after a model call "
            f"({len(rig.double.calls) - calls_before} call(s) reached the provider)"
        )
    return problems


# --- arm (a): the context ask is answered about the current screen --------------------------


def test_tc_help_06_a_context_ask_answers_about_the_current_screen(tmp_path, tmp_data_dir):
    """`TC-HELP-06(a)` / FR-HELP-06 (P0). The ask carries the plan's context —
    `{screen: 'wizard-stage-3', refs: [draft_id]}` — and is answered about it: exactly one
    model call, the assembled prompt carries the screen id and the ref verbatim inside their
    own delimited field (the field sits between the passages and the question, the assembly's
    fixed order), the answer references the review stage, and the citations resolve to real
    manual anchors. The ref names no stored object on purpose: the assistant never resolves a
    ref (`CT-UI-07`), so an unresolvable id is exactly as answerable as a real one."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec")
    _grounded_or_fail(rig, hv.CONTEXT_T.question)
    context = {"screen": hv.WIZARD_STAGE_3, "refs": [hv.CONTEXT_DRAFT_REF]}

    result = rig.assistant.ask(hv.CONTEXT_T.question, context)

    problems = []
    if len(rig.double.calls) != 1:
        problems.append(f"expected exactly one model call, saw {len(rig.double.calls)}")
    if "review stage" not in hv.norm(hv.answer_text(result)):
        problems.append(f"the answer does not reference the review stage: {hv.answer_text(result)!r}")
    anchors = hv.anchors_of(hv.load_manuals())
    problems += [f"citation {pair} resolves to no manual anchor"
                 for pair in hv.citations(result) if pair not in anchors]

    if rig.double.calls:
        prompt = rig.double.calls[0].prompt
        names = [name for name, _ in prompt.fields]
        if names != ["directive", "passages", "screen_context", "question"]:
            problems.append(
                f"the context ask's payload fields are {names}; the context rides as its own "
                "'screen_context' field between the passages and the question"
            )
        context_field = next((value for name, value in prompt.fields if name == "screen_context"), "")
        if context_field:
            at_open, at_close = context_field.find("<screen-context>"), context_field.find("</screen-context>")
            if not (0 <= at_open < at_close):
                problems.append(f"the screen context is not in its delimited block: {context_field!r}")
            else:
                for what in (f"screen: {hv.WIZARD_STAGE_3}", hv.CONTEXT_DRAFT_REF):
                    at = context_field.find(what)
                    if not (at_open < at < at_close):
                        problems.append(f"the prompt's context block does not carry {what!r} verbatim")
        else:
            problems.append("the context ask's payload carries no 'screen_context' field")
    rig.store.close()
    assert not problems, "\n".join(problems)


# --- arm (b): the prompt never carries student text (RS-14) ---------------------------------


def test_tc_help_06_b_the_context_ask_prompt_carries_no_student_text(tmp_path, tmp_data_dir):
    """`TC-HELP-06(b)` / RS-14 (P0) — the assembled-provider-prompt sweep. Over a store seeded
    with a scored run and two roster students, the context ask's prompt carries NONE of the
    store-derived identifiers (cohort, package, submission ids, student refs), neither
    student's name — and it is not swept vacuously: the same ask demonstrably assembled a
    screen-context block, so the sweep ran over the channel the context opened."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec", seed=True)
    _grounded_or_fail(rig, hv.CONTEXT_T.question)
    context = {"screen": hv.WIZARD_STAGE_3, "refs": [hv.CONTEXT_DRAFT_REF]}

    rig.assistant.ask(hv.CONTEXT_T.question, context)

    problems = []
    if not rig.double.calls:
        problems.append("no request reached the provider — nothing was swept")
    for call in rig.double.calls:
        text = hv.payload_text(call.prompt)
        if "<screen-context>" not in text:
            problems.append("the swept prompt carries no screen-context block: the sweep ran "
                            "over an ask that did not exercise the context channel")
        problems += [f"context ask: {hit}" for hit in hv.sweep(text, rig.world.forbidden)]
        # Neither student's name, anywhere in the prompt: the context question names no one,
        # so unlike CT-HELP-03's sweep there is no `allow_in` refuge here at all.
        problems += [f"context ask: {hit}"
                     for hit in hv.sweep(text, {"Zelda's name": rig.world.zelda_name})]
    rig.store.close()
    assert not problems, "\n".join(problems)


def test_tc_help_06_b_a_prose_ref_is_refused_before_any_model_call(tmp_path, tmp_data_dir):
    """`TC-HELP-06(b)` / RS-14, CT-UI-07 (P0). A ref that carries whitespace is prose, not an
    identifier — a student's name rides that channel if it is admitted — so every smuggled
    shape (a name as a ref, a name glued to an id, a whitespace screen id, a bare string, an
    unknown key a client could carry free text in, a non-object) is refused with a ValueError
    and ZERO model calls; the honest shape alone is admitted, coerced to a `ScreenContext`."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec")
    smuggled = [
        ("a student's name as a ref", {"screen": hv.WIZARD_STAGE_3, "refs": [hv.ZELDA["name"]]}),
        ("a name glued to an id", {"screen": hv.WIZARD_STAGE_3,
                                   "refs": [f"{hv.CONTEXT_DRAFT_REF} Zelda"]}),
        ("the other student's name as a ref", {"screen": hv.WIZARD_STAGE_3,
                                               "refs": [hv.IGNATIUS["name"]]}),
        ("a whitespace screen id", {"screen": "wizard stage 3", "refs": []}),
        ("a bare string", "wizard-stage-3"),
        ("an unknown key", {"screen": hv.WIZARD_STAGE_3, "refs": [],
                            "notes": "free text rides here"}),
        ("a non-object", 7),
    ]

    problems = []
    for label, value in smuggled:
        problems += _refusal_problems(rig, value, label=label)

    admitted = parse_screen_context({"screen": hv.WIZARD_STAGE_3, "refs": [hv.CONTEXT_DRAFT_REF]})
    if admitted != ScreenContext(screen=hv.WIZARD_STAGE_3, refs=(hv.CONTEXT_DRAFT_REF,)):
        problems.append(f"the honest shape parses as {admitted!r}, not the ids it was given")
    if parse_screen_context(admitted) != admitted:
        problems.append("a ScreenContext does not pass through parse_screen_context unchanged")
    rig.store.close()
    assert not problems, "\n".join(problems)


def test_tc_help_06_edge_a_malformed_context_answers_400_before_any_model_call(
        tmp_path, tmp_data_dir, network_guard):
    """`TC-HELP-06(b)`'s edge half / FR-HELP-06, CT-UI-07 (P0). Over the real console server
    with the recorded QA double wired through the `help_assistant` seam: a malformed or
    smuggled `context` query parameter (not JSON, a JSON string, a name in a ref, an unknown
    key) answers 400 with an error body, and not one of them reaches the model — only the
    well-formed context ask that follows does, and it answers 200."""
    from aeh.console import serve_console
    from aeh.store import open_store

    store = open_store(tmp_data_dir)
    # Open the tiers here, on the main thread: a tier first opened lazily on the server's
    # handler thread would leave its own connection owned by that thread, and the
    # main-thread `store.close()` below would fail with the cross-thread ProgrammingError
    # (TC-STORE's threading model), aborting the test after the assertions it exists for.
    store.durable()
    double = hv.QaDouble(tmp_path / "rec")
    assistant = hv.make_assistant(store, double, HOSTED_JUDGE)
    server = serve_console(store=store, help_assistant=assistant)
    try:
        with loopback_census(network_guard):
            base = f"http://127.0.0.1:{server.port}{hv.ASK_ROUTE[1]}"

            def ask_with_context(raw_context: str):
                url = f"{base}?" + urllib.parse.urlencode(
                    {"q": hv.CONTEXT_T.question, "context": raw_context})
                try:
                    with urllib.request.urlopen(url, timeout=10) as response:
                        return response.status, json.loads(response.read())
                except urllib.error.HTTPError as refused:
                    return refused.code, json.loads(refused.read())

            problems = []
            for label, raw in (
                ("not JSON", "nonsense"),
                ("a JSON string", json.dumps("wizard-stage-3")),
                ("a name in a ref", json.dumps({"screen": hv.WIZARD_STAGE_3,
                                                "refs": [hv.ZELDA["name"]]})),
                ("an unknown key", json.dumps({"screen": hv.WIZARD_STAGE_3, "refs": [],
                                               "notes": "free text"})),
            ):
                status, body = ask_with_context(raw)
                if status != 400:
                    problems.append(f"{label}: context {raw!r} answered {status}, not 400")
                elif not str(body.get("error", "")).strip():
                    problems.append(f"{label}: the 400 carries no error body: {body!r}")

            status, body = ask_with_context(json.dumps(
                {"screen": hv.WIZARD_STAGE_3, "refs": [hv.CONTEXT_DRAFT_REF]}))
            if status != 200:
                problems.append(f"the well-formed context ask answered {status}: {body!r}")
            elif "review stage" not in hv.norm(str(body.get("answer", ""))):
                problems.append(f"the well-formed context ask's answer is not about the "
                                f"screen: {body!r}")
    finally:
        server.terminate()
        store.close()

    if len(double.calls) != 1:
        problems.append(
            f"expected exactly one model call (the well-formed ask), saw {len(double.calls)}: "
            "a malformed context reached the model before the edge refused it"
        )
    assert not problems, "\n".join(problems)


# --- arm (c): the no-context ask is byte-identical with today -------------------------------


def test_tc_help_06_c_no_context_ask_is_byte_identical_with_today(tmp_path, tmp_data_dir):
    """`TC-HELP-06(c)` / FR-HELP-06, FR-PROV-10 (P0). An ask with no context argument at all
    sends exactly today's payload: the three pre-`FR-HELP-06` fields and no fourth — absent,
    not empty — byte-identical with what the public `build_prompt(passages, question)`
    assembles, replayed identically by a fresh `RecordedFixtureProvider` over the same
    fixtures, answered with today's recorded reply and citations. And the context-bearing
    payload keys to a DIFFERENT fixture, so a context ask can never replay (or pollute)
    today's contextless recordings."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec")
    _grounded_or_fail(rig, hv.GROUNDED_T.question)

    result = rig.assistant.ask(hv.GROUNDED_T.question)  # no context argument at all

    problems = []
    if len(rig.double.calls) != 1:
        problems.append(f"expected exactly one model call, saw {len(rig.double.calls)}")
    call = rig.double.calls[0] if rig.double.calls else None
    if call is not None:
        names = [name for name, _ in call.prompt.fields]
        if names != ["directive", "passages", "question"]:
            problems.append(
                f"the contextless payload's fields are {names}; today's assembly is exactly "
                "directive, passages, question — a field that only sometimes exists must be "
                "absent, not empty (FR-PROV-10 keys the fixture on the whole payload)"
            )
        if "<screen-context>" in hv.payload_text(call.prompt):
            problems.append("the contextless payload carries a screen-context block")
        params = SamplingParams(temperature=0.0)
        passages = retrieve(rig.assistant.index, hv.GROUNDED_T.question)
        rebuilt = build_prompt(passages, hv.GROUNDED_T.question, None)
        if rebuilt.fields != call.prompt.fields:
            problems.append("build_prompt(passages, question, context=None) does not assemble "
                            "the bytes the contextless ask sent")
        replay = RecordedFixtureProvider(fixture_dir=tmp_path / "rec").complete(
            rebuilt, call.model_ref, params)
        if replay != call.completion:
            problems.append(f"the contextless ask's recording did not replay identically: "
                            f"{replay!r} != {call.completion!r}")
        context_payload = build_prompt(
            passages, hv.GROUNDED_T.question,
            ScreenContext(screen=hv.WIZARD_STAGE_3, refs=(hv.CONTEXT_DRAFT_REF,)))
        if request_key(context_payload, call.model_ref, params) == request_key(
                call.prompt, call.model_ref, params):
            problems.append("the context-bearing payload keys to the same fixture as the "
                            "contextless one: the context did not reach the request key")
    if hv.answer_text(result) != hv.GROUNDED_T.reply:
        problems.append(f"the answer is not today's recorded reply: {hv.answer_text(result)!r}")
    anchors = hv.anchors_of(hv.load_manuals())
    problems += [f"citation {pair} resolves to no manual anchor"
                 for pair in hv.citations(result) if pair not in anchors]
    if not hv.citations(result):
        problems.append("a grounded answer carries no citation")
    rig.store.close()
    assert not problems, "\n".join(problems)
