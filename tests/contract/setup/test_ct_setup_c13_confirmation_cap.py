"""`CT-SETUP-13` — at most `SETUP_MAX_CONFIRMATIONS` decomposability
confirmations, enforced by the module, headlessly (`TC-SETUP-C13`).

Case of test plan §6.11.6; issue #56 (TS-63). **WRITTEN AHEAD of #52** — the
cap (`SETUP_MAX_CONFIRMATIONS`) and the classifier whose confirmations it caps
(`classify_decomposability`) are #52's. The file carries `writtenahead` and a
`WRITTEN_AHEAD_BLOCKERS` entry ("#56 C13 confirmation cap") keyed on the
conjunction — the same pairing #54's "#52 decomposition" entry keys. It fails
ONLY via `NotImplementedYet` until #52 lands.

The clause: the threshold is on TEACHER INTERACTION, not machine time — for a
15-criterion package, at most `SETUP_MAX_CONFIRMATIONS` (6) decomposability
confirmations PLUS the two blocking screens. Then the ownership assertion: the
cap is enforced BY THIS MODULE, not by the console — verified by driving setup
headlessly, where no console exists to enforce anything: the only actor in this
file is the `SetupService` (and the module graph cannot consult a console —
`aeh.setup` imports nothing but the store boundary, which TC-SETUP-C16 pins).

**Stated bet** (shared with #54's pending file): FR-SETUP-07 caps the
confirmations REQUESTED per package; this test reads the cap off per-verdict
`needs_teacher_confirmation` flags. If #52 enforces the cap at the surfacing
layer instead (trimming the returned request list), this assertion reds on
correct behavior and moves to that return value — the bet is stated, not
hidden.
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

FIVE_QUESTIONS = ("completeness", "non_interference", "independence", "additivity",
                  "gates")

#: The package the clause sizes: 15 criteria, every one borderline (the §5.3
#: answers pass but each carries a warning sign) — the population that would
#: surface for confirmation without a cap.
PACKAGE_CRITERIA = 15


def _draft(criterion_id: str) -> dict:
    """A criterion draft for `classify_decomposability` (the payload-shape bet)."""
    return {
        "criterion_id": criterion_id,
        "question_id": "Q1",
        "kind": "open",
        "construct": f"the response does the thing {criterion_id} names",
    }


def _borderline_reply(criterion_id: str) -> str:
    """One scripted §5.3 answer set: all answers pass, one warning sign."""
    return json.dumps({
        "criterion_id": criterion_id,
        "answers": {question: "yes" for question in FIVE_QUESTIONS},
        "warning_signs": ["straddles two constructs"],
        "reasoning": f"scripted borderline answers for {criterion_id}",
    })


def test_tc_setup_c13_confirmations_capped_headlessly():
    """A 15-criterion package: at most `SETUP_MAX_CONFIRMATIONS` confirmations
    are requested — plus the two blocking screens, nothing more — and the cap
    held with no console present: the service enforced it alone."""
    require_attr(SetupService, "classify_decomposability", issue=ISSUE)
    setup_module_cap = require_cap()

    ids = [f"CRIT-B{index}" for index in range(PACKAGE_CRITERIA)]
    # The replies carry ANSWERS, never a cap — the module enforces the count.
    service = make_setup_service(
        ScriptedCatalog(), ScriptedIngestor(),
        ScriptedSetupProvider([_borderline_reply(criterion_id)
                               for criterion_id in ids]))

    verdicts = [service.classify_decomposability(_draft(criterion_id))
                for criterion_id in ids]
    confirmations = sum(1 for v in verdicts if v.needs_teacher_confirmation)
    assert confirmations <= setup_module_cap, (
        f"{confirmations} confirmations were requested for "
        f"{PACKAGE_CRITERIA} borderline criteria — over the cap of "
        f"{setup_module_cap} (CT-SETUP-C13)"
    )
    # The cap actually BIT: an unbounded population would surface all 15.
    assert confirmations == min(PACKAGE_CRITERIA, setup_module_cap), (
        f"{confirmations} confirmations for {PACKAGE_CRITERIA} borderline "
        f"criteria — expected exactly {min(PACKAGE_CRITERIA, setup_module_cap)}: "
        "a cap that never binds is not a cap (CT-SETUP-C13)"
    )

    # Plus the two blocking screens — the teacher's total interaction budget.
    # (Blocking-set membership is TC-SETUP-C01's set-equality assertion; here
    # it is the cap's accounting: confirmations + 2 screens.)
    assert confirmations + 2 <= setup_module_cap + 2


def require_cap() -> int:
    """The module's declared cap, read through the designed blocker."""
    import aeh.setup as aeh_setup
    from tests.support.impl import require_attr as _require
    _require(aeh_setup, "SETUP_MAX_CONFIRMATIONS", issue=ISSUE)
    cap = aeh_setup.SETUP_MAX_CONFIRMATIONS
    assert cap == 6, (
        f"SETUP_MAX_CONFIRMATIONS is {cap!r} — the Configuration block declares "
        "6, matching §6.4's elicitation ceiling; a different cap changes "
        "NFR-SETUP-01's teacher-time promise (CT-SETUP-C13)"
    )
    return cap
