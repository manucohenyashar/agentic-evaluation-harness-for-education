"""`TC-JUDGE-C02` — `ScoringRequest` is a closed whitelist schema (§6.11.10).

`CT-JUDGE-02`: *"The `ScoringRequest` schema is a closed whitelist — it has exactly
the fields HLD §9.9 lists and nothing else. No field may carry: another judge's
verdict, this judge's verdict on another criterion, another submission's text, prior
cohort state, student identity or history, or any running score. An undeclared field
fails validation and is not dispatched."* — a §4.7 safety property behind RISK-02,
whose plan steps this file follows:

1. field-set **equality** against the declared whitelist — not a subset check,
   which would permit additions — twice: at the schema's own surface
   (`dataclasses.fields`) and over the FULLY ASSEMBLED nested value, whose name
   universe is asserted equal to one LITERAL declared set (step 4's single-source
   consequence: the universe a request can present is fixed here, so a new nested
   field fails the case in review, not silently);
2. six explicit absence assertions — one per contaminating class, one assertion
   each, because a single combined assertion silently stops covering whatever is
   added to the forbidden list later;
3. an undeclared field **fails and is not dispatched** — the adversarial
   construction (`prior_context`, "for the Phase 3 calibration flow"), a nested
   unknown key, and a frozen-slot write — and the refusal is STRUCTURAL: a
   construction that raised left no request object, so there is nothing a
   lenient path COULD dispatch (dropping-and-sending is the plausible lenient
   implementation and would defeat the clause, but it needs a request to drop);
4. the enforcement is a **schema change, not a call-site change**: no second
   dataclass in `aeh.judge` carries the whitelist's defining pair, so the
   constructor is the single enforcement site — the property that makes Rule 1
   mechanically enforceable rather than a convention.

Cross-references, not duplicates: the shipped rung-0 file
`tests/artifact/test_scoring_isolation.py` walks the same six contaminations
(`TC-JUDGE-01`'s recursive scan, plus its positive shape) over the flat
constructor bet; this file is the plan's schema-level form — set equality, the
nested name universe, the six absences as distinct assertions, and the
single-source property. `TC-JUDGE-C01` asserts the machine check fires;
this file asserts the SCHEMA refuses earlier where it can. The dispatch
boundary's refusal shape (a re-ordered or out-of-set reply refused at the
strike loop) is `TC-JUDGE-C04`'s and `TC-JUDGE-C05`'s; this file's door is the
constructor, which is the clause's enforcement site.

Isolation: rung 0 — pure values; the socket guard is autouse.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import (
    REQUEST_TYPE,
    field_names,
)

pytestmark = [pytest.mark.contract]

#: The story that owns the whitelist (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

#: The seven-name whitelist, as the plan's step 1 declares it — the equality target,
#: not a derivation from the type (an equality against the type's own names would
#: pass a schema that silently renamed a field).
WHITELIST: frozenset[str] = frozenset({
    "work_id",
    "criterion",
    "question",
    "evidence",
    "dependency_evidence",
    "submission",
    "submission_text",
})

#: The nested name universe a fully-built request can reach — every field name the
#: walker can reach over the request value, DECLARED here as one literal. The views'
#: own fields (a `BandView`'s `band`/`ordinal`/`descriptor`, an `ExemplarView`'s
#: `exemplar_id`/`band`/`text`, and the evidence spans' keys) are part of the closed
#: universe: a new leaf name anywhere in the tree must edit this set first.
DECLARED_UNIVERSE: frozenset[str] = frozenset({
    # the seven whitelist fields themselves
    "work_id", "criterion", "question", "evidence", "dependency_evidence",
    "submission", "submission_text",
    # CriterionView
    "criterion_id", "text", "bands", "exemplars",
    # BandView / ExemplarView
    "band", "ordinal", "descriptor", "exemplar_id",
    # QuestionView
    "prompt_text", "reference_solution",
    # SubmissionView — the pseudonymous handle and the id, and NOTHING else
    "submission_id", "student_ref",
    # the evidence span documents the extractor wrote (the request carries them
    # verbatim; keys are the extractor's span shape)
    "start", "end",
})

#: The six contaminating classes, each with its own absence assertion (step 2) —
#: the names are the SAME six C01's machine check feeds `assert_isolated`, kept
#: adjacent on purpose so the two halves of the clause stay visibly one list.
_ABSENT_CLASSES: tuple[tuple[str, str], ...] = (
    ("another judge's verdict", "other_judge_verdict"),
    ("this judge's verdict on another criterion", "criterion_verdict"),
    ("another submission", "other_submission_text"),
    ("prior cohort state", "prior_cohort_state"),
    ("student identity or history", "student_name"),
    ("any running score", "running_score"),
)


def _built_request() -> Any:
    """A fully-assembled request through the construction door, with every nested
    slot populated — bands, exemplars, question and an evidence span — so the name
    universe the walk returns is the WHOLE universe, not the empty-slot subset."""
    from tests.contract.judge._drive import offline_request

    return offline_request(
        exemplars=(("ex-1", "secure", "a worked answer naming the force at rest"),),
        evidence=[{"start": 0, "end": 12, "text": "a quoted span of the document"}],
    )


def test_tc_judge_c02_the_field_set_equals_the_whitelist_not_a_subset():
    """`TC-JUDGE-C02` step 1 (`CT-JUDGE-02`, schema-level, P0) — the dataclass's
    field names are set-EQUAL to the declared whitelist: an addition fails, a
    rename fails, a removal fails. Subset checks are explicitly not the oracle."""
    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)

    actual = {field.name for field in dataclasses.fields(ScoringRequest)}
    assert actual == set(WHITELIST), (
        f"`ScoringRequest`'s fields are {sorted(actual)}, the whitelist is "
        f"{sorted(WHITELIST)} — set equality, not a subset check, is the oracle "
        "(CT-JUDGE-02: a closed whitelist; an addition is one call-site away from "
        "correlating every grade in the cohort)"
    )


def test_tc_judge_c02_the_nested_name_universe_is_the_declared_set():
    """`TC-JUDGE-C02` step 1 continued (`CT-JUDGE-02`, set equality, P0) — over a
    fully-assembled nested value, every field NAME reachable at any depth belongs
    to one literal declared universe. The whitelist alone does not close the
    schema: a contaminating field smuggled INSIDE a view (`submission.name`) would
    pass a top-level equality, so the walk covers the leaves too."""
    names = set(field_names(_built_request()))
    undeclared = names - set(DECLARED_UNIVERSE)
    missing = set(DECLARED_UNIVERSE) - names
    assert not undeclared, (
        f"the assembled request carries field name(s) outside the declared "
        f"universe: {sorted(undeclared)} — the schema is closed at every depth, "
        "and a new leaf must edit this test's universe in the same change "
        "(CT-JUDGE-02)"
    )
    assert not missing, (
        f"declared universe name(s) {sorted(missing)} no longer appear — the "
        "universe in this file has drifted from the shipped views; reconcile, "
        "never weaken"
    )


def test_tc_judge_c02_no_field_for_each_of_the_six_contaminating_classes():
    """`TC-JUDGE-C02` step 2 (`CT-JUDGE-02`, six explicit absences, P0) — one
    assertion PER contaminating class, not one combined assertion: a single
    "no forbidden fields" check silently stops covering whatever is added to the
    forbidden list later, which is the failure this step exists to make visible."""
    names = set(field_names(_built_request()))
    for label, forbidden in _ABSENT_CLASSES:
        assert forbidden not in names and not any(
            forbidden in name for name in names
        ), (
            f"the whitelist carries a field for {label} ({forbidden!r}) — the six "
            "absences are the clause's own enumeration, each asserted on its own "
            "line so one cannot silently stop covering the others (CT-JUDGE-02)"
        )


def test_tc_judge_c02_an_undeclared_field_fails_and_is_not_dispatched(
    network_guard,
):
    """`TC-JUDGE-C02` step 3 (`CT-JUDGE-02`, exact validation failure per injected
    field, P0) — the adversarial construction (`prior_context`, "for the Phase 3
    calibration flow") refuses at the constructor, and a contaminating key inside
    a coerced dict refuses at the view's own whitelist. "Not dispatched" is
    carried STRUCTURALLY: the construction raises, so no request object ever
    exists to hand to a transport — there is nothing a lenient drop-and-send
    path could send, and this test runs at rung 0 where the worker is pure
    assembly with no transport seam to bind."""
    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)

    # The plan's own adversarial construction: an optional `prior_context` field,
    # "for the Phase 3 calibration flow", unset by default. The constructor is
    # the enforcement: the field cannot exist, not merely be filtered.
    with pytest.raises(TypeError) as raised:
        ScoringRequest(
            work_id="sha256:c02-prior-context",
            criterion={"criterion_id": "C1", "text": "States the claim.", "bands": ()},
            question={"prompt_text": "Q", "reference_solution": "A"},
            evidence=(),
            dependency_evidence=(),
            submission={"submission_id": "SYN-001", "student_ref": "ref-001"},
            submission_text="the submission text",
            prior_context="for the Phase 3 calibration flow",
        )
    assert "prior_context" in str(raised.value), (
        f"the undeclared-field refusal named {str(raised.value)!r} — the message "
        "should name the injected field, or the refusal is a generic error the "
        "call site cannot diagnose"
    )

    # The same refusal at a nested door: a contaminating key inside a coerced
    # mapping is refused by the view's own whitelist, not silently dropped.
    with pytest.raises(ValueError):
        ScoringRequest(
            work_id="sha256:c02-nested-name",
            criterion={"criterion_id": "C1", "text": "States the claim.", "bands": ()},
            question={"prompt_text": "Q", "reference_solution": "A"},
            evidence=(),
            dependency_evidence=(),
            submission={
                "submission_id": "SYN-001",
                "student_ref": "ref-001",
                "student_name": "Jane Doe",
            },
            submission_text="the submission text",
        )

    # Neither refusal leaves a request behind: TypeError/ValueError raised at
    # construction mean no `ScoringRequest` ever existed to hand to a transport,
    # so a refusal cannot silently become a dispatch (CT-JUDGE-02).


def test_tc_judge_c02_the_schema_is_frozen_and_single_sourced():
    """`TC-JUDGE-C02` step 4 (`CT-JUDGE-02`, single-source, P0) — the enforcement is
    a schema change, not a call-site change: the request is frozen (no post-hoc
    field write can smuggle contamination past the constructor), and no second
    dataclass in `aeh.judge` carries the whitelist's defining pair, so the
    constructor IS the one place the whitelist is defined."""
    import aeh.judge as judge_module

    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)

    built = _built_request()
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.submission_text = "a post-hoc write would bypass every constructor door"

    # Single source: exactly one dataclass in the module carries the defining
    # (work_id, criterion) pair — a second writable schema would let a call site
    # build a contaminating request without touching the whitelist.
    carriers = []
    for name in dir(judge_module):
        obj = getattr(judge_module, name)
        if dataclasses.is_dataclass(obj):
            fields_of_type = {field.name for field in dataclasses.fields(obj)}
            if {"work_id", "criterion"} <= fields_of_type:
                carriers.append(name)
    assert carriers == ["ScoringRequest"], (
        f"{carriers} carry the whitelist's defining pair — the schema must live in "
        "exactly one place, or a call site could build a request the whitelist never "
        "blessed (CT-JUDGE-02 step 4: a schema change, not a call-site change)"
    )
    # ... and the product of the one door is the type the dispatcher consumes.
    assert dataclasses.fields(ScoringRequest)[0].name == "work_id", (
        "the whitelist's first field is the work id — the request's identity is the "
        "content address, and the whitelist's order is part of the pinned schema"
    )