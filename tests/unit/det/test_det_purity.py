"""`TC-DET-12` — the evaluator is a pure function of (selection, key, policy).
Test plan §5.11 (`NFR-DET-02`); issue #88.

Oracle: **invariant**, over generated (selection, key, policy) triples:

1. **Determinism** — the same inputs give the same output (frozen-dataclass equality on
   a double call), the property a byte-reproducible module cannot slide on.
2. **Output domain** — every output is one of the declared bands (`correct` /
   `incorrect`) or the `'unresolved'` marker with state `unresolved_selection` routed to
   `triage` — never anything else; a scored cell is final/auto with credit in [0, 1].
3. **The RISK-03 negative as an invariant** — no input in the unreadable half of the
   table (absent region, ambiguous mark, multiple marks, a present region with no
   selection read) can produce band `incorrect`. There is no path; the property proves
   the absence over the whole generated space, not just the eleven enumerated cells
   (`TC-DET-03`).
4. **The blank/zero half** — a genuinely empty answer always bands `incorrect` with the
   blank reason, never unresolved: the mirror must hold everywhere too.
5. **Multi-select** — under a declared policy the credit stays in [0, 1] and only an
   exact match bands/pays `correct`/1.0; and no multi-select call with an undeclared
   policy ever returns a score (cell 11 as an invariant, not a cell).
6. **No I/O** — the autouse socket guard records every connection attempt across all
   examples; zero attempts is asserted for the whole property.

**Isolation: rung 0** — the module-level `evaluate` kernel only; no store, no doubles.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aeh.det import (
    BAND_CORRECT,
    BAND_INCORRECT,
    BAND_UNRESOLVED,
    REASON_BLANK,
    ROUTING_AUTO,
    ROUTING_TRIAGE,
    STATE_FINAL,
    STATE_UNRESOLVED_SELECTION,
    UndeclaredPartialCreditPolicy,
    evaluate,
)

pytestmark = pytest.mark.property

ISSUE = "#88"

_OPTIONS = st.sampled_from(("A", "B", "C", "D", "E", "F"))

#: A single-select key: exactly one option (a wider key is `MalformedAnswerKey`'s
#: territory — FR-SETUP-03 makes it unpublished, so the property targets the scoreable
#: domain the §7.8 table enumerates).
_SINGLE_KEY = st.tuples(_OPTIONS)

_MULTI_KEY = st.lists(_OPTIONS, min_size=1, max_size=3, unique=True)

#: Selections: 0-3 distinct options — the empty tuple is how the kernel receives a
#: resolved mark with no populated selection (CT-INGEST-04's violated contract), which
#: must route, never score.
_SELECTION = st.lists(_OPTIONS, min_size=0, max_size=3, unique=True)

_OPTION_SET = st.none() | st.lists(_OPTIONS, min_size=2, max_size=6,
                                   unique=True).map(tuple)

_TRIPLE = st.fixed_dictionaries(
    {
        "content_state": st.sampled_from(("present", "blank", "absent")),
        "selection_state": st.none()
        | st.sampled_from(("ambiguous", "multiple_marks", "resolved")),
        "selection": st.none() | _SELECTION.map(tuple),
        "key": _SINGLE_KEY,
        "option_set": _OPTION_SET,
    }
)


def _kwargs(triple):
    return dict(
        content_state=triple["content_state"],
        selection_state=triple["selection_state"],
        selection=triple["selection"],
        key=triple["key"],
        option_set=triple["option_set"],
    )


@given(triple=_TRIPLE)
def test_tc_det_12_deterministic_and_in_domain(triple, network_guard):
    """Same inputs, same output; every output is a declared band or the unresolved
    marker — never anything else."""
    first = evaluate(**_kwargs(triple))
    second = evaluate(**_kwargs(triple))
    assert first == second, (
        "the evaluator returned different outcomes for identical inputs — "
        "NFR-DET-02's purity contract is broken"
    )
    assert first.band in (BAND_CORRECT, BAND_INCORRECT, BAND_UNRESOLVED)
    if first.band == BAND_UNRESOLVED:
        assert first.state == STATE_UNRESOLVED_SELECTION
        assert first.routing == ROUTING_TRIAGE
        assert first.credit == 0.0
        assert first.selection_read is None
    else:
        assert first.state == STATE_FINAL
        assert first.routing == ROUTING_AUTO
        assert 0.0 <= first.credit <= 1.0
    network_guard.assert_no_network()


@given(triple=_TRIPLE)
def test_tc_det_12_unreadable_never_becomes_incorrect(triple):
    """RISK-03 as an invariant: an absent region, an ambiguous mark, multiple marks, or
    a present region with no selection read NEVER bands `incorrect` — over the whole
    generated space, not just the enumerated cells."""
    unreadable = triple["content_state"] == "absent" or (
        triple["content_state"] == "present"
        and (
            triple["selection_state"] in ("ambiguous", "multiple_marks", None)
            # A resolved mark with no populated selection is the CT-INGEST-04
            # contract violated — the kernel cannot score what it did not read,
            # so it routes (REASON_NO_SELECTION_READ). Part of the invariant:
            # scoring it would be a mark against the student from nothing.
            or not triple["selection"]
        )
    )
    if not unreadable:
        return
    outcome = evaluate(**_kwargs(triple))
    assert outcome.band == BAND_UNRESOLVED, (
        f"an unreadable read ({triple['content_state']!r}, "
        f"{triple['selection_state']!r}) scored as {outcome.band!r} — a scanning "
        "problem became a wrong answer (RISK-03)"
    )
    assert outcome.state == STATE_UNRESOLVED_SELECTION
    assert outcome.routing == ROUTING_TRIAGE


@given(key=_SINGLE_KEY, option_set=_OPTION_SET)
def test_tc_det_12_blank_is_always_a_legitimate_zero(key, option_set):
    """The mirror invariant: a genuinely empty answer ALWAYS bands `incorrect` with the
    blank reason — never unresolved, never correct — wherever it appears in the
    generated space."""
    outcome = evaluate(content_state="blank", key=key, option_set=option_set)
    assert outcome.band == BAND_INCORRECT
    assert outcome.reason == REASON_BLANK
    assert outcome.state == STATE_FINAL
    assert outcome.routing == ROUTING_AUTO
    assert outcome.credit == 0.0


@given(
    key=_MULTI_KEY,
    partial_credit=st.sampled_from(("all_or_nothing", "per_option")),
    selection=_SELECTION.map(tuple),
    option_set=_OPTION_SET,
)
def test_tc_det_12_multi_select_declared_policy_holds(key, partial_credit, selection,
                                                      option_set):
    """Multi-select cells under a declared policy: `all_or_nothing` pays only on an
    exact set match; `per_option` pays a fraction in [0, 1] that only an exact match
    drives to 1.0; and NO multi-select call with an undeclared policy ever returns —
    cell 11 as an invariant, not a cell."""
    outcome = evaluate(
        content_state="present",
        selection_state="resolved",
        selection=selection,
        key=key,
        multi_select=True,
        partial_credit=partial_credit,
        option_set=option_set,
    )
    # Determinism over the multi-select subspace too: the same triple gives the same
    # outcome (a defective implementation deriving selection_read or credit from set
    # iteration would drift here and only here).
    assert outcome == evaluate(
        content_state="present",
        selection_state="resolved",
        selection=selection,
        key=key,
        multi_select=True,
        partial_credit=partial_credit,
        option_set=option_set,
    )
    exact = len(selection) > 0 and set(selection) == set(key)
    if outcome.band == BAND_UNRESOLVED:
        # The two routings out of a resolved multi-select read: an empty selection (a
        # resolved mark with no populated selection — CT-INGEST-04's violated contract)
        # or a selection naming an option outside the declared set (the option_set draw
        # is independent of the key/selection draws). The policy never fires on a read
        # it cannot score.
        assert not selection or (
            option_set is not None
            and any(option not in option_set for option in selection)
        ), "an in-set, populated multi-select read resolved unresolved"
        return
    if partial_credit == "all_or_nothing":
        if exact:
            assert outcome.band == BAND_CORRECT and outcome.credit == 1.0
        else:
            assert outcome.band == BAND_INCORRECT and outcome.credit == 0.0
    else:
        assert 0.0 <= outcome.credit <= 1.0
        if outcome.credit == 1.0:
            assert outcome.band == BAND_CORRECT
        else:
            assert outcome.band == BAND_INCORRECT
    # And the undeclared-policy refusal, swept: no generated multi-select read is ever
    # scored around a missing policy.
    try:
        evaluate(
            content_state="present",
            selection_state="resolved",
            selection=selection,
            key=key,
            multi_select=True,
            partial_credit=None,
            option_set=option_set,
        )
    except UndeclaredPartialCreditPolicy:
        pass
    else:
        raise AssertionError(
            "a multi-select criterion with no declared policy was scored — "
            "FR-DET-05 forbids inferring one (TC-DET-03 cell 11)"
        )
