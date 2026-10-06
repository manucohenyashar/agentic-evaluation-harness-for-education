"""Issue #637 (TS-150) — the `CT-HELP` clause suite, `TC-HELP-C01..C05` (operator plan §6.11).

Each case breaks on its named regression:

* C01 (surface): a second public operation on the assistant, a second help route, or a help
  route that writes a control row.
* C02 (behaviour, P0): a citation that resolves to no manual anchor, or a no-grounding question
  answered with the model's unsourced reply.
* C03 (security, P0): any store-derived identifier in any model request, across the grounded,
  not-found, action, student and injection questions over a seeded store.
* C04 (state): any write outside the module's own log — across five asks only one Tier D table
  changes, by exactly five rows.
* C05 (observe): a log entry missing a key, or carrying a value that is not the exchange's own
  (question, the answer's anchors, the model asked, the recorded tokens, the outcome).

**Written ahead of #636**; the names are `tests/support/help_vocabulary.py`'s. The provider is
the recorded QA double, which answers by replaying through `RecordedFixtureProvider` — the
`fixture` implementation `CT-PROV`'s own clause suite already holds.
"""

from __future__ import annotations

import pytest

from tests.support import help_vocabulary as hv

pytestmark = [pytest.mark.contract]

_ASKED = (hv.GROUNDED_T, hv.NOT_FOUND_T, hv.ACTION_T, hv.STUDENT_T, hv.INJECTION_T)


@pytest.mark.writtenahead
def test_tc_help_c01_one_read_only_endpoint(tmp_path, tmp_data_dir):
    """CT-HELP-01: `ask(question) -> {answer, citations[]}` is the only operation; one help route,
    a read; the answer carries those two fields and nothing operational."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec")
    problems = []
    public = sorted(n for n in dir(rig.assistant)
                    if not n.startswith("_") and callable(getattr(rig.assistant, n)))
    if public != [hv.ASK]:
        problems.append(f"public operations {public} != ['ask']")
    help_routes = [r for r in hv.route_table() if r[1].startswith(hv.HELP_API_PREFIX)]
    if [(m, p, c) for m, p, c in help_routes] != [(*hv.ASK_ROUTE, None)]:
        problems.append(f"help routes {help_routes} != exactly [{(*hv.ASK_ROUTE, None)}]")
    result = rig.assistant.ask(hv.QA_MANUALS_QUESTION)
    if not isinstance(hv.answer_text(result), str):
        problems.append(f"the answer is not prose: {type(hv.answer_text(result)).__name__}")
    extra = hv.result_fields(result) - {"answer", "citations"}
    if extra:
        problems.append(f"the answer carries fields beyond {{answer, citations}}: {sorted(extra)}")
    rig.store.close()
    assert not problems, "\n".join(problems)


@pytest.mark.writtenahead
def test_tc_help_c02_citations_resolve_and_not_found_is_explicit(tmp_path, tmp_data_dir):
    """CT-HELP-02 (P0): every citation of every answer resolves to a real anchor; the
    no-grounding question returns no citation and never the model's unsourced reply."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec")
    anchors = hv.anchors_of(hv.load_manuals())
    problems = []
    for transcript in (hv.GROUNDED_T, hv.ACTION_T, *hv.REFERENCE_SET[:5]):
        result = rig.assistant.ask(transcript.question)
        problems += [f"{transcript.question!r}: citation {p} resolves to no anchor"
                     for p in hv.citations(result) if p not in anchors]
    grounded = rig.assistant.ask(hv.GROUNDED_T.question)
    if not hv.citations(grounded):
        problems.append("the grounded question was answered with no citation")
    nf = rig.assistant.ask(hv.NOT_FOUND_T.question)
    if hv.citations(nf):
        problems.append(f"not-found carries citations {hv.citations(nf)}")
    if hv.norm(hv.NOT_FOUND_T.reply) in hv.norm(hv.answer_text(nf)):
        problems.append("the unsourced reply reached the not-found answer")
    rig.store.close()
    assert not problems, "\n".join(problems)


@pytest.mark.writtenahead
def test_tc_help_c03_no_student_data_in_any_request(tmp_path, tmp_data_dir):
    """CT-HELP-03 (P0): over a seeded store, no request for any question carries a store-derived
    identifier; a named student's name appears only inside the question that named her."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec", seed=True)
    for transcript in _ASKED:
        rig.assistant.ask(transcript.question)
    problems = []
    assert rig.double.calls, "no request reached the provider — nothing was swept"
    for call in rig.double.calls:
        text = hv.payload_text(call.prompt)
        problems += [f"{call.transcript.question!r}: {hit}" for hit in hv.sweep(text, rig.world.forbidden)]
        problems += [f"{call.transcript.question!r}: Zelda's name outside the question"
                     for _ in hv.sweep(text, {"n": rig.world.zelda_name}, allow_in=call.transcript.question)]
    rig.store.close()
    assert not problems, "\n".join(problems)


@pytest.mark.writtenahead
def test_tc_help_c04_writes_only_its_own_log(tmp_path, tmp_data_dir):
    """CT-HELP-04: five asks over a seeded store; across every tier (every table of every SQLite
    file, every blob) exactly one Tier D table changed, by exactly five rows."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec", seed=True)
    rig.assistant.ask(hv.REFERENCE_SET[1].question)  # the log table exists before the baseline
    before = hv.settled_snapshot(rig)
    for transcript in _ASKED:
        rig.assistant.ask(transcript.question)
    after = hv.settled_snapshot(rig)
    problems = hv.only_the_log_grew(hv.snapshot_diff(before, after), added=len(_ASKED))
    assert not problems, "\n".join(problems)


@pytest.mark.writtenahead
def test_tc_help_c05_the_log_records_each_exchange_exactly(tmp_path, tmp_data_dir):
    """CT-HELP-05: one entry per exchange, carrying exactly `QA_LOG_KEYS`, whose values are the
    exchange's own: the question verbatim, the answer's anchors, the model asked, the recorded
    token counts (zero/absent only when no model was called), a latency, the outcome."""
    from tests.support.conf_builders import HOSTED_JUDGE

    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec", model_ref=HOSTED_JUDGE)
    problems = []
    start = len(hv.read_log(rig.store))
    for transcript, outcome in ((hv.GROUNDED_T, hv.GROUNDED), (hv.NOT_FOUND_T, hv.NOT_FOUND)):
        calls_before = len(rig.double.calls)
        result = rig.assistant.ask(transcript.question)
        new = rig.double.calls[calls_before:]
        log = hv.read_log(rig.store)
        if len(log) != start + 1:
            problems.append(f"{transcript.question!r}: log went {start} -> {len(log)} entries")
            start = len(log)
            continue
        start, entry = len(log), log[-1]
        if not hv.QA_LOG_KEYS <= set(entry):
            problems.append(f"log entry lacks {sorted(hv.QA_LOG_KEYS - set(entry))}")
        if entry.get("question") != transcript.question:
            problems.append(f"logged question {entry.get('question')!r}")
        if entry.get("outcome") != outcome:
            problems.append(f"{transcript.question!r}: outcome {entry.get('outcome')!r} != {outcome!r}")
        cited, logged = hv.cited_anchor_strings(result), hv.logged_anchors(entry)
        if logged != cited:
            problems.append(f"logged anchors {logged} != the answer's {cited}")
        if HOSTED_JUDGE.build_id not in str(entry.get("model_ref")):
            problems.append(f"logged model_ref {entry.get('model_ref')!r} is not {HOSTED_JUDGE.build_id!r}")
        if new:
            if (entry.get("tokens_in"), entry.get("tokens_out")) != (transcript.tokens_in, transcript.tokens_out):
                problems.append(f"logged tokens {(entry.get('tokens_in'), entry.get('tokens_out'))} != "
                                f"recorded {(transcript.tokens_in, transcript.tokens_out)}")
        elif entry.get("tokens_in") not in (0, None) or entry.get("tokens_out") not in (0, None):
            problems.append(f"no model call, yet tokens logged {entry.get('tokens_in')}/{entry.get('tokens_out')}")
        latency = entry.get("latency_ms")
        if not isinstance(latency, (int, float)) or latency < 0:
            problems.append(f"logged latency {latency!r} is not a non-negative number")
    rig.store.close()
    assert not problems, "\n".join(problems)
