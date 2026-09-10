"""`TC-JUDGE-C05` — the reply contract's pinned field order (§6.11.10).

`CT-JUDGE-05` (data): *"Assert the response schema requires fields in the order
`cited_spans`, `evidence_assessment`, `evidence_sufficient`, `band`, `self_confidence`.
Then the assertion the clause exists for: a response whose fields arrive in a
**different order is rejected rather than reordered and accepted**. The ordering is
the mitigation — it forces evidence before verdict — so silently repairing it would
remove the thing being tested while every parse succeeded. Sweep several
permutations."* (plan §6.11.10, verbatim)

The three steps, as implemented here:

1. **the pinned order, single-sourced** — `aeh.judge:REPLY_FIELDS` is exactly the
   declared literal, restated in `judge_vocabulary.REPLY_FIELD_ORDER` (the
   vocabulary centralizes the declared surface — reconcile, never rename); and
   the evidence fields occupy the first three positions, the verdict fields the
   last two — the ordering IS the mitigation, so the order's shape is asserted,
   not just its identity;
2. **exact rejection per permutation** — the FULL 120-permutation sweep (the plan
   asks for several; all of them costs nothing at rung 0) through the real
   parser `_verdict_of`: every reordered reply refuses with the pinned message,
   naming what arrived and that reordering is not a format variation
   (`FR-JUDGE-09`); the canonical reply alone parses, and parses to the verdict
   the reply declared;
3. **the refusal is load-bearing at the boundary** — one permuted reply through
   the REAL `dispatch` (store-backed request, budget 1) is struck and
   quarantined as `JudgmentError` with no verdict row, while the canonical
   reply through the same boundary persists its verdict: the parser's refusal
   is load-bearing at the boundary, not decoration.

Cross-references, not duplicates: no shipped suite drives `REPLY_FIELDS` (the
TS-31 response symbols rest in `judge_vocabulary` for the security suite's
prefix/efficiency cases, `TC-JUDGE-21`'s file); the malformed-reply shapes it
DOES drive are C11's refusal-path enumeration — here the order clause gets its
own exhaustive sweep. `TC-JUDGE-C04` is the sibling content gate (the band's
VALUE); this file is the order gate (`FR-JUDGE-09`).

Isolation: rung 0 for the sweep — `_verdict_of` is pure, and the hand-built
request carries a declared band set; the boundary limb is rung 2 (real store,
transport double at the model boundary).
"""

from __future__ import annotations

import json
from itertools import permutations
from typing import Any

import pytest

from aeh.store import open_store
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import REPLY_FIELD_ORDER

pytestmark = [pytest.mark.contract]

#: The story that owns the response contract (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

#: The budget-1 override for the dispatch limb: one strike, then quarantine — the
#: refusal-path call count stays 1 while the clause's default budget is C11's sweep.
_ATTEMPTS_ENV = "HARNESS_JUDGE_MAX_ATTEMPTS"


def _canonical_values() -> dict[str, Any]:
    """The five fields' VALID values, so the ONLY contract dimension under test is
    the order: a valid cited span, a real assessment, a declared band."""
    from tests.contract.judge._drive import spans

    return {
        "cited_spans": spans(),
        "evidence_assessment": "the cited spans support the band",
        "evidence_sufficient": True,
        "band": "secure",
        "self_confidence": 0.9,
    }


def _reply_text(order: tuple[str, ...]) -> str:
    """The reply JSON with the fields in `order` — `json.dumps` preserves insertion
    order, so the parser's `list(reply.keys())` sees exactly this order."""
    values = _canonical_values()
    return json.dumps({name: values[name] for name in order})


def _completion(text: str) -> Any:
    """A `Completion` carrying `text` — the transport's only degree of freedom."""
    Completion = require("aeh.prov", "Completion", issue=ISSUE)
    return Completion(
        text=text,
        tokens_in=0, tokens_out=0, latency_ms=0,
        resolved_build="build-judge-contract",
        cached_prefix_tokens=0, cost=None,
    )


def test_tc_judge_c05_the_pinned_order_is_single_sourced():
    """`TC-JUDGE-C05` step 1 (`CT-JUDGE-05`, surface assertion, rung 0, P0) — the
    pinned order is the declared literal, single-sourced between the module and the
    vocabulary, and it forces evidence before verdict: that ordering is the
    mitigation the clause exists for."""
    REPLY_FIELDS = require(JUDGE_MODULE, "REPLY_FIELDS", issue=ISSUE)

    assert tuple(REPLY_FIELDS) == tuple(REPLY_FIELD_ORDER), (
        f"`aeh.judge:REPLY_FIELDS` is {tuple(REPLY_FIELDS)}, the vocabulary's "
        f"declared order is {REPLY_FIELD_ORDER} — reconcile the restatement, never "
        "rename a field past it (CT-JUDGE-05; the vocabulary is the declared "
        "surface this suite centralizes)"
    )
    assert tuple(REPLY_FIELD_ORDER) == (
        "cited_spans", "evidence_assessment", "evidence_sufficient",
        "band", "self_confidence",
    ), (
        f"the declared order drifted to {REPLY_FIELD_ORDER} — the pinned order is "
        "the clause's own enumeration; a change is a contract change and edits this "
        "file in the same PR (CT-JUDGE-05)"
    )
    # The mitigation's shape: every evidence field precedes every verdict field.
    evidence = ("cited_spans", "evidence_assessment", "evidence_sufficient")
    verdict = ("band", "self_confidence")
    positions = [REPLY_FIELD_ORDER.index(name) for name in REPLY_FIELD_ORDER]
    assert max(REPLY_FIELD_ORDER.index(n) for n in evidence) < min(
        REPLY_FIELD_ORDER.index(n) for n in verdict
    ), (
        f"the pinned order no longer forces evidence before verdict "
        f"({REPLY_FIELD_ORDER}) — the ordering is the mitigation, and a verdict "
        "field that can arrive before its evidence removes it (CT-JUDGE-05)"
    )
    assert positions == sorted(positions) and len(set(positions)) == 5, (
        "the pinned order carries a duplicate or an unsorted position — the order "
        "contract is positional, and `list(reply.keys()) != list(REPLY_FIELDS)` is "
        "the gate (CT-JUDGE-05)"
    )


def test_tc_judge_c05_every_reordered_reply_is_rejected_not_reordered():
    """`TC-JUDGE-C05` step 2 (`CT-JUDGE-05`, exact rejection per permutation, rung 0,
    P0) — the FULL 120-permutation sweep through the real parser: every reordered
    reply raises the pinned refusal, and the one canonical order parses to the
    verdict the reply declared. Values are held valid throughout, so a failure here
    can only be the order gate."""
    verdict_of = require(JUDGE_MODULE, "_verdict_of", issue=ISSUE)
    MalformedResponseError = require("aeh.prov", "MalformedResponseError", issue=ISSUE)
    from tests.contract.judge._drive import offline_request

    request = offline_request()
    canonical = tuple(REPLY_FIELD_ORDER)

    refusals = 0
    for order in permutations(canonical):
        text = _reply_text(order)
        if order == canonical:
            continue
        with pytest.raises(MalformedResponseError) as raised:
            verdict_of(text, request)
        message = str(raised.value)
        assert "not the pinned order" in message, (
            f"the reordered reply {list(order)} was refused as {message!r} — the "
            "refusal must name the order clause it enforces (CT-JUDGE-05)"
        )
        assert "reordering is not a format variation" in message, (
            f"the refusal for {list(order)} dropped the clause's own reading: "
            f"{message!r} (CT-JUDGE-05, FR-JUDGE-09)"
        )
        refusals += 1
    assert refusals == 119, (
        f"the sweep refused {refusals} permutation(s), not the 119 non-canonical "
        "orderings of five fields — the sweep must be exhaustive, not sampled "
        "(CT-JUDGE-05)"
    )

    # The canonical order parses, to the verdict the reply declared.
    parsed = verdict_of(_reply_text(canonical), request)
    values = _canonical_values()
    assert parsed.band == values["band"], (
        f"the canonical reply parsed to band {parsed.band!r} — the pinned order's "
        "acceptance path must be the ordinary one (CT-JUDGE-05)"
    )
    assert parsed.band_ordinal == 1, (
        f"the parsed verdict's ordinal is {parsed.band_ordinal} — the declared "
        "band's own ordinal rides beside it (CT-JUDGE-05, CT-JUDGE-04)"
    )
    assert parsed.evidence_sufficient is values["evidence_sufficient"], (
        "the parsed verdict lost the reply's evidence_sufficient (CT-JUDGE-05)"
    )


def test_tc_judge_c05_the_refusal_is_load_bearing_at_the_dispatch_boundary(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """`TC-JUDGE-C05` step 3 (`CT-JUDGE-05`, boundary limb, rung 2, P0) — one permuted
    reply through the REAL dispatch (budget 1) strikes once and quarantines as
    `JudgmentError` with no verdict row; the canonical reply through the same
    boundary persists its verdict. Silently repairing the order would show up here
    as a verdict row where none may exist."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        from tests.contract.judge._drive import (
            PANEL_REFS,
            RecordingTransport,
            drive_extract,
            lease_score_units,
            seed_world,
            verdict_rows,
        )

        orchestrator, run_id, _version = seed_world(store)
        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        unit = units[0]
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, PANEL_REFS[0]
        )
        request = worker.assemble(unit)

        monkeypatch.setenv(_ATTEMPTS_ENV, "1")
        JudgmentError = require(JUDGE_MODULE, "JudgmentError", issue=ISSUE)

        # The reordered reply: refused at the boundary, quarantined, nothing persisted.
        permuted = tuple(reversed(canonical_order()))
        transport = RecordingTransport(_completion(_reply_text(permuted)))
        bound = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, transport, PANEL_REFS[0]
        )
        with pytest.raises(JudgmentError) as raised:
            bound.dispatch(request, PANEL_REFS[0])
        message = str(raised.value)
        assert "not the pinned order" in message, (
            f"the dispatch refusal surfaced {message!r} — the parser's order refusal "
            "must be the last refusal the quarantine reports (CT-JUDGE-05)"
        )
        assert "refused after 1 attempt(s)" in message, (
            f"the permuted reply was retried past the budget of one: {message!r} "
            "(CT-JUDGE-05; the retry shape itself is C11's sweep)"
        )
        assert len(transport.calls) == 1, (
            f"the reordered reply drew {len(transport.calls)} call(s) under a budget "
            "of one (CT-JUDGE-05)"
        )
        assert verdict_rows(store, run_id, unit.submission_id, unit.criterion_id) == [], (
            "the reordered reply left a persisted verdict — a re-ordered reply is "
            "rejected, never reordered and accepted (CT-JUDGE-05)"
        )

        # The canonical reply: the same boundary, accepted and persisted.
        good = RecordingTransport(_completion(_reply_text(canonical_order())))
        bound = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, good, PANEL_REFS[0]
        )
        result = bound.dispatch(request, PANEL_REFS[0])
        assert result.band == "secure", (
            f"the canonical reply was refused at the boundary ({result!r}) — the "
            "order gate must accept the pinned order it demands (CT-JUDGE-05)"
        )
        bound.persist(unit, result)
        rows = verdict_rows(store, run_id, unit.submission_id, unit.criterion_id)
        assert len(rows) == 1 and rows[0]["band"] == "secure", (
            f"the canonical reply persisted {rows!r} — the boundary's acceptance is "
            "the ordinary verdict path (CT-JUDGE-05)"
        )
    finally:
        store.close()


def canonical_order() -> tuple[str, ...]:
    return tuple(REPLY_FIELD_ORDER)