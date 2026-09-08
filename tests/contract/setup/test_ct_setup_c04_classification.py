"""`CT-SETUP-04` — the classification sweep and the asymmetric unclear default
(`TC-SETUP-C04`).

Case of test plan §6.11.6; issue #56 (TS-63). **WRITTEN AHEAD of #52** — both
halves drive `SetupService.classify_decomposability`, which does not exist yet
(FR-SETUP-06's decision table lands with #52). The file carries `writtenahead`
and a `WRITTEN_AHEAD_BLOCKERS` entry ("#56 C04 classification") keyed on the
method; it fails ONLY via `NotImplementedYet` until #52 lands.

The clause: sweep `classification` over its three values (`atomic`,
`holistic`, `atomic_with_gate`) and assert `deciding_question` names **which of
the five §5.3 questions decided it** — a null or generic value fails. Then the
asymmetric default that carries RISK-27: deliberately unclear criteria default
to **`holistic`, never `atomic`**, asserted directionally over the whole unclear
partition — a default of `atomic` gives a criterion panel depth 1 and a higher
auto-acceptance ceiling than it deserves, and nothing downstream would notice.

Rung 0, per the plan: the classifier is a pure decision table, so the service
runs over the in-memory doubles (`tests/support/setup_harness.py`) with no
store. The scripted reply carries the §5.3 **answers**, never a classification —
the module owns the table, so a module that merely echoes a scripted verdict
cannot pass these cells.

Two stated bets, aligned with #54's already-shipped pending file
(`tests/integration/setup/test_setup_decomposition_pending.py`):

- **Deciding-question nulls.** For every cell where a question DECIDED, the
  verdict's `deciding_question` is that question, exactly. For the two cells
  where nothing decided (all answers pass; the unclear default), #54 shipped the
  bet that the field is None — this case aligns with it and adds the clause's
  other tooth: the field may never carry a GENERIC string ("default",
  "unclear", "table"). When #52 lands a named decider for those cells, this
  assertion widens, never weakens.
- **The payload shape** (§5.3 answers in the scripted reply; a dict for the
  criterion draft) is this suite's bet, not a pinned interface — align the
  scripting when #52 lands; the per-cell expectations do not change.
"""
from __future__ import annotations

import json

import pytest

from aeh.setup import SetupService
from tests.contract.setup._doubles import make_setup_service
from tests.support.impl import require_attr
from tests.support.setup_harness import (
    ScriptedCatalog,
    ScriptedIngestor,
    ScriptedSetupProvider,
)

pytestmark = pytest.mark.writtenahead

ISSUE = "#52"

#: The five §5.3 questions, in the order the HLD names them.
FIVE_QUESTIONS = ("completeness", "non_interference", "independence", "additivity",
                  "gates")

#: Generic deciding-question values the clause forbids: the field must name a
#: QUESTION, never a disposition.
GENERIC_DECIDERS = ("default", "unclear", "table", "fallback", "none", "")


def _draft(criterion_id: str) -> dict:
    """A criterion draft for `classify_decomposability` (the payload-shape bet)."""
    return {
        "criterion_id": criterion_id,
        "question_id": "Q1",
        "kind": "open",
        "construct": f"the response does the thing {criterion_id} names",
    }


def _answers_reply(criterion_id: str, *, failing: str | None = None,
                   unclear_question: str | None = None,
                   warning_signs: list[str] | None = None) -> str:
    """One scripted §5.3 answer set: every question `yes`, except what the cell fails.

    `failing` scripts a DECIDED failure (`no`); `unclear_question` scripts the
    genuinely-unclear answer the default exists for. They are different inputs
    and must never be conflated — a `no` on gates decides `atomic_with_gate`,
    while an unclear answer anywhere defaults `holistic`."""
    answers = {question: "yes" for question in FIVE_QUESTIONS}
    if unclear_question is not None:
        answers[unclear_question] = "unclear"
    if failing == "unclear":  # the sweep's sentinel cell: additivity unclear
        answers["additivity"] = "unclear"
    elif failing is not None:
        answers[failing] = "no"
    reply = {
        "criterion_id": criterion_id,
        "answers": answers,
        "reasoning": f"scripted §5.3 answers for {criterion_id}",
    }
    if warning_signs:
        reply["warning_signs"] = warning_signs
    return json.dumps(reply)


def _service(replies: list[str]):
    """A rung-0 `SetupService` over the pure doubles, scripted to reply in order."""
    return make_setup_service(ScriptedCatalog(), ScriptedIngestor(),
                              ScriptedSetupProvider(replies))


def _verdict(criterion_id: str, **reply_kwargs):
    """One classify call over a scripted answer set."""
    require_attr(SetupService, "classify_decomposability", issue=ISSUE)
    service = _service([_answers_reply(criterion_id, **reply_kwargs)])
    return service.classify_decomposability(_draft(criterion_id))


def test_tc_setup_c04_sweep_three_values_with_question_level_deciders():
    """The decision table swept over all three classification values: each is
    reachable, the decided cells name their deciding question EXACTLY, and no
    cell ever carries a generic decider."""
    require_attr(SetupService, "classify_decomposability", issue=ISSUE)
    # The sweep: five cells failing one question each (holistic x4,
    # atomic_with_gate for the gates failure), the all-yes cell (atomic), and
    # the unclear cell (the default). No classification is scripted — the
    # module's table produces every value below.
    cells = [
        ("completeness", "holistic", "completeness"),
        ("non_interference", "holistic", "non_interference"),
        ("independence", "holistic", "independence"),
        ("additivity", "holistic", "additivity"),
        ("gates", "atomic_with_gate", "gates"),
        (None, "atomic", None),
        ("unclear", "holistic", None),
    ]
    seen: set[str] = set()
    for failing, expected, decider in cells:
        verdict = _verdict("CRIT-T", failing=failing)
        assert verdict.classification == expected, (
            f"a criterion failing {failing!r} must classify {expected!r} — the "
            "table is the module's (FR-SETUP-06), and a scripted verdict could "
            "not have produced this cell (CT-SETUP-C04)"
        )
        seen.add(verdict.classification)
        if decider is not None:
            # A question decided: the field names THAT question, exactly.
            assert verdict.deciding_question == decider, (
                f"the {expected!r} cell's deciding_question is "
                f"{verdict.deciding_question!r}, not the question that decided "
                f"it ({decider!r}) — a null or generic value fails "
                "(CT-SETUP-C04)"
            )
        assert verdict.deciding_question not in GENERIC_DECIDERS, (
            f"the {expected!r} cell carries a GENERIC deciding_question "
            f"({verdict.deciding_question!r}) — the field must name one of the "
            "five §5.3 questions or be honestly empty (CT-SETUP-C04)"
        )
        assert verdict.reasoning
    # The sweep really covered the classification's whole vocabulary.
    assert seen == {"atomic", "holistic", "atomic_with_gate"}, (
        f"the sweep produced {sorted(seen)} — the classification vocabulary "
        "changed; update the sweep, never narrow it (CT-SETUP-C04)"
    )


@pytest.mark.parametrize(
    ("unclear_question", "warning_signs"),
    [
        ("completeness", None),
        ("non_interference", None),
        ("independence", None),
        ("additivity", None),
        ("gates", None),
        (None, ["straddles two constructs"]),
        (None, ["the wording mixes two scales"]),
    ],
    ids=["q1-unclear", "q2-unclear", "q3-unclear", "q4-unclear", "q5-unclear",
         "warning-only-straddle", "warning-only-mixed-scale"],
)
def test_tc_setup_c04_unclear_partition_defaults_holistic_never_atomic(
        unclear_question, warning_signs):
    """The RISK-27 partition, directionally: EVERY deliberately unclear input —
    any question's answer UNCLEAR (a `no` would be a decided failure, a
    different cell), or warning signs with no unclear answer — classifies
    `holistic`, never `atomic`. The default is asymmetric on purpose: `atomic`
    grants panel depth 1 and a higher auto-acceptance ceiling than an unclear
    criterion deserves, and nothing downstream would notice."""
    verdict = _verdict("CRIT-U", unclear_question=unclear_question,
                       warning_signs=warning_signs)
    assert verdict.classification == "holistic", (
        f"an unclear input (unclear={unclear!r}, warnings={warning_signs!r}) "
        f"classified {verdict.classification!r} — the default is `holistic`, "
        "never `atomic` (NFR-SETUP-02, RISK-27; CT-SETUP-C04 directional "
        "assertion)"
    )
    # And the default is AUDITABLE: the unclear case surfaces for the teacher
    # rather than silently passing.
    assert verdict.needs_teacher_confirmation is True, (
        "the unclear default was applied silently — a default indistinguishable "
        "from a decided classification destroys the audit trail (CT-SETUP-C04)"
    )
