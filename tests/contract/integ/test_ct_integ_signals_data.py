"""`CT-INTEG-02` — exactly six fields, five booleans, one tri-state, and the
consumer that may not collapse `None` into `False` (`TC-INTEG-C02`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#74` (the
`IntegritySignals` half) and `#92` (the `M-AGG` consumer half).

The clause: `IntegritySignals` carries **exactly six** fields; five are
booleans and `extractor_disagreement` is the only tri-state; `None` means
**"not measured"** (no second extraction ran), never "no disagreement" — and
*a consumer that treats the two as equivalent is wrong*, so the case asserts
the consumer, not just the type: at rung 3 the same panel over `None` and over
`False` must not produce the same verdict from `M-AGG`'s declared pure surface
(`aggregate`, §3.12), because a collapsed consumer reads "not measured" as
"measured, and agreed".

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| `aeh.integ.IntegritySignals` | design-declared (§3.9), the #74 key |
| `aeh.agg.aggregate` | design-declared (§3.12 Protocol member); lands with the confidence story, `#92` |
| outcome fields `.confidence` / `.routing` | the `#76` precedent's reading of `aggregate`'s `CriterionScore`; reconcile when M-AGG lands its dataclass |
| differential direction | "treats `None` differently from `False`" is asserted as: outcomes differ, **and** `None` is never the more permissive of the two (the adverse-safe reading — measured agreement is the trusting case). The direction choice is disclosed; a declared M-AGG semantics that pins it tighter supersedes at `#92`'s landing |
| `M-CONSOLE` half | deferred with disclosure: M-CONSOLE does not exist yet (stories #123..#130); the type and consumer limbs here are what its presentation would read |
"""

from __future__ import annotations

import dataclasses
import typing

import pytest

from tests.contract.integ._doubles import Criterion, unanimous_panel
from tests.support.impl import AGG_MODULE, INTEG_MODULE, require
from tests.support.integ_vocabulary import Span

pytestmark = pytest.mark.contract

#: The six field names CT-INTEG-02 spells, in the order §3.9 declares them.
DECLARED_FIELDS = (
    "spans_verified",
    "evidence_present",
    "sufficiency_flag",
    "ocr_overlap_risk",
    "described_evidence",
    "extractor_disagreement",
)

_TRI_STATE = "extractor_disagreement"

_NONE = type(None)


# --- the type half -------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c02_signal_fields_are_exactly_six_with_one_tri_state():
    """`TC-INTEG-C02` — field-set equality: exactly the six declared names (an
    added field fails, a renamed one fails), five annotated `bool` and
    `extractor_disagreement` the only annotation that admits `None`. Set
    equality, not subset: the clause's point is that there is no seventh."""
    IntegritySignals = require(INTEG_MODULE, "IntegritySignals", issue="#74")
    assert dataclasses.is_dataclass(IntegritySignals), (
        "IntegritySignals is not a dataclass — consumers construct it directly "
        "(§3.9's compatibility note), and the field set below is the contract"
    )
    hints = typing.get_type_hints(IntegritySignals)
    assert set(hints) == set(DECLARED_FIELDS), (
        f"IntegritySignals carries {sorted(hints)}; CT-INTEG-02 fixes exactly six "
        f"fields: {sorted(DECLARED_FIELDS)}"
    )
    collapsed = {
        name: hint for name, hint in hints.items()
        if _admits_none(hint)
    }
    assert set(collapsed) == {_TRI_STATE}, (
        f"annotations admitting None: {sorted(collapsed)} — exactly "
        f"{_TRI_STATE!r} may be tri-state; every other signal is a boolean, and a "
        "second tri-state would give consumers a second 'not measured' to collapse"
    )


def _admits_none(hint: object) -> bool:
    """Whether a resolved type annotation admits `None` (bool | None, Optional[bool])."""
    if typing.get_origin(hint) is typing.Union:
        return _NONE in typing.get_args(hint)
    return hint is _NONE


@pytest.mark.writtenahead
def test_tc_integ_c02_all_three_states_construct_and_the_none_one_is_not_falsy_collapsible():
    """`TC-INTEG-C02` — the three states construct directly (the compatibility
    note's own form): no second extraction (`None`), second family agrees
    (`False`), second family disagrees (`True`). The constructed values are
    then distinguished by identity against the tri-state, not truthiness —
    `not None` and `not False` are the same, which is exactly the collapse the
    clause declares wrong."""
    IntegritySignals = require(INTEG_MODULE, "IntegritySignals", issue="#74")

    def signals(disagreement: bool | None) -> object:
        return IntegritySignals(
            spans_verified=True, evidence_present=True, sufficiency_flag=False,
            ocr_overlap_risk=False, described_evidence=False,
            extractor_disagreement=disagreement,
        )

    not_measured, agreed, disagreed = signals(None), signals(False), signals(True)
    assert not_measured.extractor_disagreement is None
    assert agreed.extractor_disagreement is False
    assert disagreed.extractor_disagreement is True
    assert not_measured.extractor_disagreement is not agreed.extractor_disagreement, (
        "the None state and the False state collapsed at construction — 'not "
        "measured' and 'measured, and agreed' are contractually different "
        "(CT-INTEG-02)"
    )


# --- the consumer half (rung 3) -------------------------------------------------------------
#
# The checker is the oracle; the executable mutant proves it has teeth NOW, so the
# #92 landing cannot satisfy the case with a collapsed consumer while every
# FR-* case stays green.


def _assert_none_is_never_collapsed_into_false(none_outcome, false_outcome) -> None:
    """The consumer oracle: outcomes for the None set and the False set differ,
    and None is never the more permissive."""
    none_conf = getattr(none_outcome, "confidence", none_outcome)
    false_conf = getattr(false_outcome, "confidence", false_outcome)
    none_route = getattr(none_outcome, "routing", None)
    false_route = getattr(false_outcome, "routing", None)
    same = (none_conf == false_conf) and (none_route == false_route)
    assert not same, (
        "M-AGG produced identical outcomes for extractor_disagreement=None and "
        "=False — 'not measured' was read as 'measured, and agreed', the collapse "
        "CT-INTEG-02 declares wrong"
    )
    assert none_conf <= false_conf, (
        f"the not-measured outcome ({none_conf}) is more permissive than the "
        f"measured-agreement outcome ({false_conf}) — unmeasured disagreement "
        "consumed as agreement, in the one direction the clause forbids"
    )


def test_tc_integ_c02_the_collapsing_consumer_mutant_turns_this_oracle_red():
    """`TC-INTEG-C02`'s executable construction — a consumer that collapses
    (`None if x is None else x == x` flattened into `x == x`, or an `or`-default)
    produces identical outcomes for the two states, and the oracle goes red on
    it. Runs green now: it asserts the oracle's teeth, not the implementation."""
    from types import SimpleNamespace

    # A faithful consumer: different confidence for the two states — passes.
    _assert_none_is_never_collapsed_into_false(
        SimpleNamespace(confidence=0.55, routing="review"),
        SimpleNamespace(confidence=0.70, routing="auto"),
    )
    # The collapsing mutant: `disagreement is not False` read as a boolean gate —
    # both states take the same branch, same outcome. The oracle reds.
    collapsed = SimpleNamespace(confidence=0.70, routing="auto")
    with pytest.raises(AssertionError, match="identical outcomes"):
        _assert_none_is_never_collapsed_into_false(collapsed, collapsed)
    # The inverse-collapse mutant: None read as BETTER than measured agreement.
    with pytest.raises(AssertionError, match="more permissive"):
        _assert_none_is_never_collapsed_into_false(
            SimpleNamespace(confidence=0.80, routing="auto"),
            SimpleNamespace(confidence=0.70, routing="auto"),
        )


@pytest.mark.writtenahead
def test_tc_integ_c02_m_agg_treats_not_measured_differently_from_measured_agreement():
    """`TC-INTEG-C02`'s rung-3 limb — the same unanimous panel over the same
    verified, present, not-at-risk evidence, differing ONLY in
    `extractor_disagreement` (`None` vs `False`): `aggregate` must not produce
    the same verdict, and `None` must not come out more permissive. A consumer
    collapsing the two reads 'no second extraction ran' as 'the second family
    agreed' — the equivalence the clause names wrong by name."""
    IntegritySignals = require(INTEG_MODULE, "IntegritySignals", issue="#74")
    aggregate = require(AGG_MODULE, "aggregate", issue="#92")

    def signals(disagreement: bool | None) -> object:
        return IntegritySignals(
            spans_verified=True, evidence_present=True, sufficiency_flag=False,
            ocr_overlap_risk=False, described_evidence=False,
            extractor_disagreement=disagreement,
        )

    panel = unanimous_panel("B2")
    criterion = Criterion("C1")
    none_outcome = aggregate(panel, criterion, signals(None))
    false_outcome = aggregate(panel, criterion, signals(False))
    _assert_none_is_never_collapsed_into_false(none_outcome, false_outcome)
