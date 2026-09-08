"""`M-SETUP` Stage A's decomposability decision table — written ahead of **#52** (issue #54).

Cases `TC-SETUP-08`, `TC-SETUP-09` and `TC-SETUP-10` (test plan §5.6, P0/P1), all planned
unit / 0 and all honored at that rung: the service runs over the pure in-memory doubles in
`tests/support/setup_harness.py`, no store at all. They carry `writtenahead` and sit
outside `TEST_CMD` until #52 lands `classify_decomposability` together with
`SETUP_MAX_CONFIRMATIONS`; the "#52 decomposition" entry in `tests/support/impl.py` is a
`symbols` conjunction over both, so the gate fires exactly when the file can run.

`TC-SETUP-09` arrived with TS-21 (issue #55) and lives here rather than in its own file
because it is the same classifier at the same rung over the same doubles: the
repetition invariant of the NFR-SETUP-02 default that `TC-SETUP-08`'s "unclear" cell
asserts once. Its blocker set is the classifier alone — already covered by this file's
registered conjunction, so the "#52 decomposition" entry needed no new key.

`TC-SETUP-13` (the dependency proposals) is **not** in this file, and that is deliberate:
its criteria come out of the read back, so it needs #51's `read_back_rubric` as well as
#52's `propose_dependencies`. It lives in `test_setup_dependencies_pending.py`, keyed on
the pair — a conjunction here would hold two unit cases outside the gate for a story
neither of them needs.

What gives the decision table its teeth: the scripted reply carries the §5.3 **answers**,
never a classification. The module owns the table (FR-SETUP-06) — fail one question and
the classification follows it; answer unclear and the NFR-SETUP-02 default (`holistic`,
never `atomic`) applies. A module that merely echoed a scripted verdict cannot pass,
because no verdict is scripted.

The payload shape below is this file's stated bet, not a pinned interface: §3.6 pins the
method's signature and `DecomposabilityVerdict`'s fields, not the model reply or the
`CriterionDraft` construction. When #52 lands, align the scripting and the `_draft`
helper to its shapes — the per-cell expectations do not change.
"""

from __future__ import annotations

import json

import pytest

from tests.support.impl import SETUP_MODULE, require, require_attr
from tests.support.setup_harness import (
    ScriptedCatalog,
    ScriptedIngestor,
    ScriptedSetupProvider,
    make_setup_service,
)

pytestmark = pytest.mark.writtenahead

ISSUE = "#52"

#: The five §5.3 questions, in the order the HLD names them.
FIVE_QUESTIONS = ("completeness", "non_interference", "independence", "additivity", "gates")


def _draft(criterion_id: str) -> dict:
    """A criterion draft for `classify_decomposability`.

    A dict, not a constructed `CriterionDraft`: §3.6 names the parameter type but defines
    no fields for it. If #52 lands a dataclass, this helper is the one line that moves.
    """
    return {
        "criterion_id": criterion_id,
        "question_id": "Q1",
        "kind": "open",
        "construct": f"the response does the thing {criterion_id} names",
    }


def _answers_reply(criterion_id: str, *, failing: str | None = None,
                   warning_signs: list[str] | None = None) -> str:
    """One scripted §5.3 answer set: every question `yes`, except what the cell fails."""
    answers = {question: "yes" for question in FIVE_QUESTIONS}
    if failing == "unclear":
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


# --- TC-SETUP-08 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failing", "expected", "decider"),
    [
        # The five §5.3 questions in turn, one criterion failing each ...
        ("completeness", "holistic", "completeness"),
        ("non_interference", "holistic", "non_interference"),
        ("independence", "holistic", "independence"),
        ("additivity", "holistic", "additivity"),
        ("gates", "atomic_with_gate", "gates"),
        # ... one failing none, and one where the answer is genuinely unclear.
        (None, "atomic", None),
        ("unclear", "holistic", None),
    ],
    ids=["completeness", "non_interference", "independence", "additivity", "gates",
         "fails-none", "unclear"],
)
def test_tc_setup_08_the_five_question_decision_table_classifies_per_cell(
    failing, expected, decider,
):
    """`TC-SETUP-08` (FR-SETUP-06, P0) — the decision table: one criterion failing each of
    the five §5.3 questions in turn, one failing none, one genuinely unclear. The
    classification is the table's, `decomposition_basis` (the verdict's
    `deciding_question`) names **which question decided it**, and the unclear case
    classifies `holistic` — NFR-SETUP-02's default, never `atomic` (RISK-27)."""
    setup = require(SETUP_MODULE, "SetupService", issue=ISSUE)
    require_attr(setup, "classify_decomposability", issue=ISSUE)

    service = _service([_answers_reply("CRIT-T", failing=failing)])
    verdict = service.classify_decomposability(_draft("CRIT-T"))

    assert verdict.classification == expected, (
        f"TC-SETUP-08: a criterion failing {failing!r} must classify {expected!r} — "
        "the table is the module's (FR-SETUP-06), and an unclear answer defaults "
        "holistic, never atomic (NFR-SETUP-02, RISK-27)"
    )
    assert verdict.deciding_question == decider, (
        f"TC-SETUP-08: decomposition_basis must name the question that decided "
        f"{expected!r}, not merely carry a classification"
    )
    assert verdict.reasoning
    if failing == "unclear":
        assert verdict.needs_teacher_confirmation is True, (
            "TC-SETUP-08: the unclear case surfaces for the teacher rather than "
            "silently defaulting — that is what makes the default auditable"
        )
    elif failing is None:
        assert verdict.needs_teacher_confirmation is False, (
            "TC-SETUP-08: a criterion whose §5.3 answers all pass was surfaced for "
            "confirmation — FR-SETUP-07 surfaces only borderline or warning-sign "
            "criteria, and NFR-SETUP-01's teacher-time promise depends on it"
        )


# --- TC-SETUP-10 ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [5, 6, 7])
def test_tc_setup_10_borderline_confirmations_capped_at_setup_max_confirmations(count):
    """`TC-SETUP-10` (FR-SETUP-07, P1) — a package producing 5, 6 and 7 borderline
    criteria: only borderline (or warning-sign) criteria surface for confirmation, and the
    count requested is capped at `SETUP_MAX_CONFIRMATIONS` — at 7, the seventh is not
    requested. A clean criterion (no warning signs) is included as a control: it must not
    surface at all. The cap is the module's to enforce (CT-SETUP-13), not the console's.

    Stated bet, alongside the payload-shape one in the module docstring: FR-SETUP-07 caps
    the confirmations *requested per package*, while this test reads the cap off
    per-verdict `needs_teacher_confirmation` flags. If #52 enforces the cap at the
    surfacing layer instead (trimming the returned request list), this assertion reds on
    correct behavior and moves to that return value — the bet is stated, not hidden."""
    cap = require(SETUP_MODULE, "SETUP_MAX_CONFIRMATIONS", issue=ISSUE)
    assert cap == 6, (
        "TC-SETUP-10: SETUP_MAX_CONFIRMATIONS is the Configuration block's declared cap "
        "(matching §6.4's elicitation ceiling); a different cap changes NFR-SETUP-01's "
        "teacher-time promise"
    )
    setup = require(SETUP_MODULE, "SetupService", issue=ISSUE)
    require_attr(setup, "classify_decomposability", issue=ISSUE)

    ids = [f"CRIT-B{index}" for index in range(count)]
    # Every borderline draft: the §5.3 answers pass, but each carries a warning sign —
    # the population FR-SETUP-07 says is the only one surfaced. The clean control carries
    # no warning sign and must not surface at all.
    clean_id = "CRIT-CLEAN"
    service = _service(
        [_answers_reply(criterion_id, warning_signs=["straddles two constructs"])
         for criterion_id in ids]
        + [_answers_reply(clean_id)]
    )
    verdicts = {cid: service.classify_decomposability(_draft(cid))
                for cid in ids + [clean_id]}

    surfaced = [cid for cid in ids if verdicts[cid].needs_teacher_confirmation]
    assert len(surfaced) == min(count, cap), (
        f"TC-SETUP-10: {count} borderline criteria surfaced {len(surfaced)} confirmation "
        f"requests, expected {min(count, cap)} — the cap is enforced by the module "
        "(CT-SETUP-13), and the criterion beyond it is not requested"
    )
    assert verdicts[clean_id].needs_teacher_confirmation is False, (
        "TC-SETUP-10: a criterion with no warning signs was surfaced for confirmation — "
        "FR-SETUP-07 surfaces only borderline or warning-sign criteria; an "
        "implementation that surfaces every criterion must fail here"
    )


# --- TC-SETUP-09 (issue #55, TS-21) ---------------------------------------------------------


#: The ambiguity space the invariant runs over. Each variant is a genuine "unclear" under
#: NFR-SETUP-02 — no question answered `no`, so the `gates` route to `atomic_with_gate` is
#: closed too — and cycling them (rather than repeating one reply) is what makes the
#: invariant bite over the ambiguity space instead of over one input.
_AMBIGUOUS_VARIANTS = (
    ("one-unclear", {"additivity": "unclear"}, ()),
    ("all-unclear", {question: "unclear" for question in FIVE_QUESTIONS}, ()),
    ("mixed-yes-unclear", {"completeness": "yes", "non_interference": "unclear",
                           "independence": "yes", "additivity": "unclear",
                           "gates": "yes"}, ()),
    ("unclear-with-warning-sign", {"additivity": "unclear"},
     ("straddles two constructs",)),
)

TC_SETUP_09_RUNS = 20


def _ambiguous_reply(criterion_id: str, answers: dict, warning_signs: tuple) -> str:
    """One scripted ambiguous §5.3 answer set — same reply shape as `_answers_reply`,
    with the answer values themselves carrying the ambiguity."""
    reply = {
        "criterion_id": criterion_id,
        "answers": answers,
        "reasoning": f"scripted ambiguous §5.3 answers for {criterion_id}",
    }
    if warning_signs:
        reply["warning_signs"] = list(warning_signs)
    return json.dumps(reply)


def test_tc_setup_09_ambiguous_criterion_is_never_auto_classified_atomic_in_any_run():
    """`TC-SETUP-09` (NFR-SETUP-02, P0) — an ambiguous fixture criterion, run 20 times,
    is never auto-classified `atomic` in any run: the exact assertion NFR-SETUP-02 names
    ("a test shall assert that an ambiguous fixture criterion is never auto-classified
    `atomic`") and CT-SETUP-04 repeats ("the classifier's default on any unclear case is
    `holistic` — never `atomic`"). The oracle is the invariant over repetitions, so the
    20-run loop lives inside the test and each run's outcome is asserted with its run
    number in the message.

    The ambiguity is varied over four scripted reply variants — one unclear answer, all
    five unclear, a yes/unclear mix, and an unclear answer plus a warning sign — cycled
    five times. Every run must classify the default `holistic` (RISK-27: a default of
    `atomic` gives the criterion panel depth 1 and a higher auto-accept ceiling than it
    deserves, and nothing downstream would notice) and surface for the teacher, which is
    what makes the default auditable rather than silent."""
    setup = require(SETUP_MODULE, "SetupService", issue=ISSUE)
    require_attr(setup, "classify_decomposability", issue=ISSUE)

    classifications: list[str] = []
    for run in range(TC_SETUP_09_RUNS):
        name, answers, warning_signs = _AMBIGUOUS_VARIANTS[run % len(_AMBIGUOUS_VARIANTS)]
        service = _service([_ambiguous_reply("CRIT-AMB", answers, warning_signs)])
        verdict = service.classify_decomposability(_draft("CRIT-AMB"))

        assert verdict.classification != "atomic", (
            f"TC-SETUP-09 run {run + 1}/{TC_SETUP_09_RUNS} ({name}): the ambiguous "
            "criterion was auto-classified 'atomic' — NFR-SETUP-02's default is "
            "'holistic' on any unclear case, never 'atomic' (CT-SETUP-04, RISK-27)"
        )
        assert verdict.classification == "holistic", (
            f"TC-SETUP-09 run {run + 1}/{TC_SETUP_09_RUNS} ({name}): an unclear "
            f"classification must default to 'holistic', got "
            f"{verdict.classification!r}"
        )
        assert verdict.needs_teacher_confirmation is True, (
            f"TC-SETUP-09 run {run + 1}/{TC_SETUP_09_RUNS} ({name}): the unclear case "
            "must surface for the teacher rather than silently defaulting — the "
            "auditability half of the NFR-SETUP-02 default (TC-SETUP-08's unclear cell)"
        )
        classifications.append(verdict.classification)

    assert classifications.count("holistic") == TC_SETUP_09_RUNS, (
        f"TC-SETUP-09: the 20-run invariant broke — "
        f"{classifications.count('holistic')}/{TC_SETUP_09_RUNS} runs classified the "
        f"ambiguous criterion 'holistic' ({classifications}); NFR-SETUP-02 requires it "
        "in every run"
    )
