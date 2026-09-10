"""`TC-JUDGE-C01` — `assemble` is pure, and separated from `dispatch` (§6.11.10).

`CT-JUDGE-01`: *"`assemble(unit) -> ScoringRequest` is **pure**: no store access, no
model call, no clock. It is separated from `dispatch` precisely so every isolation
property is asserted against a value in a unit test (NFR-JUDGE-03).
`assert_isolated(req)` raises `IsolationViolation` and is the machine-checkable form
of §7.2 Rule 1."* — design §3.10, verbatim.

The test plan's own reading is why this case runs first: *"every other case here
depends on that separation holding"*. A merged assemble-and-dispatch path would force
the whole suite to rung 2 and quietly weaken it, so the separation is asserted here as
a signature property of the worker (`assemble` takes exactly one unit; `dispatch`
consumes the assembled value and refuses a unit — there is no path from a unit to a
model call that does not go through `assemble`).

Cross-references, not duplicates: the shipped rung-0 file
`tests/artifact/test_scoring_isolation.py` carries `TC-JUDGE-19` (the same purity
property, under the no-boundary constructor, disclosed there as structural) and the
TS-30 suite's fresh-context and pseudonymization cases. This file strengthens the
model half to the behavioural form the shipped test discloses it is not — a provider
IS bound, and the pure door still must not reach it — and asserts the machine check
and the separation, which the shipped file does not. The store half stays structural
here for the same disclosed reason: the pure door binds no store, so none is
reachable (`aeh.judge:assemble`'s own disclosure — the lease resolves identities, the
assembler the words and the rubric, and only through the explicit `store=` door).

Isolation: rung 0 — the socket guard (autouse) blocks and records any connect
attempt, the frozen clock steps between two assemblies.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any

import pytest

from tests.support.impl import JUDGE_MODULE, ORCH_MODULE, require
from tests.support.judge_vocabulary import (
    PROMPT_FIELDS,
    REQUEST_TYPE,
    ISOLATED_CHECK,
    VIOLATION,
    WORKER,
    fields_of,
)

pytestmark = [pytest.mark.contract]

#: The story that owns every name resolved here. `M-JUDGE` is complete (#78/#79/#80/#81),
#: so these resolve — the `issue=` keeps the ownership legible, as the landed suites do.
ISSUE = "#78"

#: The six contaminating-capable field names `CT-JUDGE-02`'s block form enumerates, one
#: representative each. `assert_isolated` refuses by STEM (`aeh.judge:_PROHIBITED_STEMS`),
#: so each class below is carried by a name containing at least one refused stem —
#: `prior_context` is the issue's own adversarial construction ("for the Phase 3
#: calibration flow"), unset by default: every functional case stays green while the
#: machine check alone goes red.
_CONTAMINATING_FIELDS: tuple[tuple[str, str], ...] = (
    ("other_judge_verdict", "B"),      # another judge's verdict
    ("criterion_verdict", "B"),        # this judge's verdict on another criterion
    ("other_submission_text", "x"),    # another submission
    ("prior_cohort_state", "c-1"),     # prior cohorts
    ("student_name", "Jane Doe"),      # student identity
    ("running_score", 7),              # any running score
)


class _ModelCallSpy:
    """The dispatch double: records every payload a model boundary would receive,
    failing the test the moment one is attempted."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def complete(self, payload: Any, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(payload)
        raise AssertionError(
            "a model call was attempted during `assemble` — the provider boundary is "
            "`dispatch`'s alone (CT-JUDGE-01: no model call)"
        )


def _resolved_unit() -> Any:
    """One resolved score unit as a pure value — the lease surface's documented job
    (identity + words onto the unit) done by hand, as `test_scoring_isolation.py`'s
    `_unit` does. `student_name` is ON the unit deliberately (§3.7): the pseudonym
    boundary is at assembly, and the pure door below must simply never reach a seam."""
    WorkUnit, STAGE_SCORE = require(
        ORCH_MODULE, "WorkUnit", "STAGE_SCORE", issue="#61"
    )
    return WorkUnit(
        work_id="sha256:c01-purity-0",
        run_id="run-c01-purity",
        stage=STAGE_SCORE,
        student_ref="ref-s231",
        student_name="Jane Doe",
        submission_id="SYN-231",
        criterion_id="C-01",
        submission_text=(
            "The crate does not slide because static friction balances the ramp's "
            "along-slope component of its weight."
        ),
        judge="judge-1",
        attempt=0,
    )


def _rendered(payload_fn: Any, request: Any) -> str:
    """The assembled request as one canonical byte string — the differential's value."""
    return "\n".join(f"{name}={value}" for name, value in fields_of(payload_fn, request))


def test_tc_judge_c01_assemble_is_pure_under_blocked_io(network_guard, frozen_clock):
    """`TC-JUDGE-C01` (`CT-JUDGE-01`, surface, rung 0, purity assertion under blocked
    I/O, P0) — `assemble` renders the same unit byte-identically with the socket
    guard armed (any connect is blocked AND recorded), no model call despite a
    provider being bound, no clock read (sixty simulated seconds move nothing), and
    no hidden state (a fresh twin unit renders identically)."""
    Worker = require(JUDGE_MODULE, WORKER, issue=ISSUE)
    payload_fn = require(JUDGE_MODULE, PROMPT_FIELDS, issue=ISSUE)

    provider_spy = _ModelCallSpy()
    worker = Worker(store=None, provider=provider_spy, judge=None)

    unit = _resolved_unit()
    first = worker.assemble(unit)
    rendered_first = _rendered(payload_fn, first)
    assert rendered_first, "fixture bug: the assembly rendered nothing"

    # No clock: sixty simulated seconds later, the same unit renders byte-identically.
    frozen_clock.advance(60)
    rendered_second = _rendered(payload_fn, worker.assemble(unit))
    assert rendered_first == rendered_second, (
        "the same unit assembled at two different times renders differently — "
        "`assemble` reads a clock (CT-JUDGE-01: no store access, no model call, no clock)"
    )

    # No hidden counter: a fresh but identical unit renders identically too.
    rendered_twin = _rendered(payload_fn, worker.assemble(_resolved_unit()))
    assert rendered_first == rendered_twin, (
        "two identical units assemble differently — `assemble` carries hidden state "
        "(CT-JUDGE-01)"
    )

    # The model half, behavioural where TC-JUDGE-19's is structural: the provider
    # IS bound, and the pure door must not reach it.
    assert provider_spy.calls == [], (
        f"the pure assembly called the model boundary {len(provider_spy.calls)} "
        "time(s) — `assemble` produces a value; the provider is `dispatch`'s "
        "boundary alone (CT-JUDGE-01: no model call)"
    )


def test_tc_judge_c01_assert_isolated_is_the_machine_check_of_rule_1():
    """`TC-JUDGE-C01` (`CT-JUDGE-01`, exact exception, P0) — `assert_isolated`
    exists, is the machine-checkable form of §7.2 Rule 1, and is verified by
    feeding it a request that violates `CT-JUDGE-02`: one contaminating field per
    class, each raising `IsolationViolation`, while a clean request raises nothing.
    An inert extra name is left to the construction door (the machine check catches
    the contaminating NAMES; the whitelist catches the rest — `TC-JUDGE-C02`)."""
    assert_isolated = require(JUDGE_MODULE, ISOLATED_CHECK, issue=ISSUE)
    IsolationViolation = require(JUDGE_MODULE, VIOLATION, issue=ISSUE)
    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)

    clean = ScoringRequest(
        work_id="sha256:c01-clean",
        criterion={"criterion_id": "C1", "text": "States the claim.", "bands": ()},
        question={"prompt_text": "Q", "reference_solution": "A"},
        evidence=(),
        dependency_evidence=(),
        submission={"submission_id": "SYN-001", "student_ref": "ref-001"},
        submission_text="the submission text",
    )
    assert_isolated(clean)  # raises nothing for a request built clean

    for field, value in _CONTAMINATING_FIELDS:
        poisoned = {"work_id": "sha256:c01-poisoned", field: value}
        with pytest.raises(IsolationViolation) as raised:
            assert_isolated(poisoned)
        message = str(raised.value)
        assert field in message or "contaminating" in message, (
            f"`assert_isolated` refused the {field!r} request but its message names "
            f"neither the field nor the class — {message!r} (a refusal that cannot "
            "name its cause is not the machine-checkable form)"
        )


def test_tc_judge_c01_assembly_is_separated_from_dispatch():
    """`TC-JUDGE-C01` (`CT-JUDGE-01`, surface assertion, P0) — the separation is
    what makes every clause below unit-testable, so it is asserted at the type
    level: `assemble` takes exactly ONE unit-shaped parameter (no second
    criterion-shaped parameter can exist — `FR-JUDGE-16`), and `dispatch`
    consumes the assembled value and refuses anything else, so there is no path
    from a unit to a model call that does not go through `assemble`'s product."""
    Worker = require(JUDGE_MODULE, WORKER, issue=ISSUE)
    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)

    assemble_params = [
        p for p in inspect.signature(Worker.assemble).parameters.values()
        if p.name != "self"
    ]
    assert [p.name for p in assemble_params] == ["unit"], (
        f"`assemble` takes {[p.name for p in assemble_params]} — a second "
        "criterion-shaped parameter cannot exist for a multi-criterion prompt to "
        "return through (FR-JUDGE-16); a merged path would force every isolation "
        "assertion in this suite to rung 2 (CT-JUDGE-01)"
    )

    dispatch_params = [
        p.name for p in inspect.signature(Worker.dispatch).parameters.values()
        if p.name != "self"
    ]
    assert dispatch_params == ["request", "judge"], (
        f"`dispatch` takes {dispatch_params} — it consumes the assembled REQUEST, "
        "never a unit: the separation is the type's, not a convention"
    )

    # The separation is enforced, not documented: dispatch refuses the unit itself.
    unit = _resolved_unit()
    with pytest.raises(TypeError) as raised:
        Worker().dispatch(unit, judge=None)
    assert "ScoringRequest" in str(raised.value), (
        f"`dispatch` accepted a unit-shaped value ({type(unit).__name__}) — a merged "
        "path would re-assemble internally and every case below would lose its value"
    )

    # And the product dispatch consumes is the whitelist request itself.
    assert dataclasses.is_dataclass(ScoringRequest), (
        "the dispatch input type is not the request dataclass — the assembled value "
        "is what every isolation property below is asserted against"
    )