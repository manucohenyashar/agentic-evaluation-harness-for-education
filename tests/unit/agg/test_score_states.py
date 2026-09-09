"""`TC-AGG-12/13/14` — score states: the two-verdict discard, the deterministic
pass-through, and the state-per-cause enum.

Test plan §5.12 (row forms), issue #95 (TS-36). Traces to `FR-AGG-12`, `FR-AGG-10`,
`FR-AGG-11`; RISK-18's module half. **Landed at #93** (the state assignment; the
`aggregate` core is #91's, the confidence surface #92's).

**The composition with TC-AGG-04 is the point of TC-AGG-12.** #94 pinned that a raw
even panel raises `EvenPanelError` — a failed write, never a rounded verdict. #95's
case covers the OTHER branch of the same clause (CT-AGG-03): a panel *left at two by
an unrecoverable failure* discards the second verdict and records the base
single-judge band as provisional, rather than adjudicating between two. The two
compose only if the caller can mark the fallback case, so the surface carries an
explicit `fallback=True` keyword — **landed at #93 as declared**. The test asserts
the composition directly: the same panel refuses without the mark and discards
with it.

**Interface of #93, as declared and as landed** (continuing
`test_routing_and_escalation.py`'s table):

| Name | Status |
|---|---|
| `aggregate(..., fallback=False)` | **landed at #93 with this keyword**: two verdicts left by an unrecoverable failure → discard the second, record the base single-judge band provisional (`provisional_unreviewed`). |
| `aggregate(..., breaker_tripped=False)` | **landed at #93 with this keyword**: FR-AGG-11's state for criteria the `M-ORCH` breaker tripped (`ungradeable_by_panel`, routed `provisional`). The tripping itself is shipped (`aeh.orch:criterion_breaker_tripped`, #60). |
| `aggregate(..., deterministic_score=row)` | **landed at #93 with this keyword**: FR-AGG-10's pass-through, echoing the row (`judge_count = 0`, agreement `None`, the row's own `state`/`routing`). |
| score `.state` | **landed at #93, assigned per cause** — the shipped migration v9 CHECK set: `{'final', 'provisional_unreviewed', 'ungradeable_by_panel', 'unresolved_selection'}`, enforced by the schema. |

Isolation: rung 0 — pure function; the socket guard is autouse.
"""

from __future__ import annotations

import pytest

from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])

#: Two verdicts left by an unrecoverable failure — deliberately DIFFERENT bands, so
#: "the base single-judge band" is distinguishable from any adjudication between the
#: two (a median, a mean or a coin-flip between B1 and B3 is not B1-with-judge_count-1).
_TWO_LEFT = panel(("B1", 1), ("B3", 3))

_DETERMINISTIC_ROW = {
    "submission_id": "s-agg-13",
    "criterion_id": "C-AGG",
    "band": "B2",
    "points": 3.0,
    "judge_count": 0,
    "agreement": None,
    "state": "final",
    "routing": "auto",
}


def test_tc_agg_12_two_verdicts_left_by_failure_discard_the_second_and_record_provisional():
    """`TC-AGG-12` (`FR-AGG-12`, unit / rung 0, exact value, P0) — a panel left with
    exactly two verdicts by an unrecoverable failure: the SECOND verdict is discarded,
    the base single-judge band is recorded as provisional, and no adjudication between
    the two occurs."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    score = aggregate(_TWO_LEFT, _FOUR_BAND, signals(), fallback=True,
                      config=agg_config())

    assert score.band == "B1", (
        f"the fallback recorded band {score.band!r} from a [B1, B3] pair — the base "
        "(first) judge's band stands and the second verdict is discarded; any "
        "adjudication between two would land elsewhere (FR-AGG-12)"
    )
    assert score.judge_count == 1, (
        f"the fallback recorded judge_count {score.judge_count!r} — the panel "
        "collapsed to its single base judge (FR-AGG-12; the odd-judge_count CHECK "
        "admits 1)"
    )
    assert score.state == "provisional_unreviewed", (
        f"the fallback recorded state {score.state!r} — the base single-judge band is "
        "recorded provisional (FR-AGG-12; TC-AGG-14's provisional cell)"
    )


def test_tc_agg_12_the_same_panel_without_the_mark_is_still_a_refusal():
    """`TC-AGG-12` composition limb (`FR-AGG-03` vs `FR-AGG-12`, unit / rung 0, P0) —
    the fallback mark is what separates the two clauses of CT-AGG-03: the SAME
    two-verdict panel without the mark still refuses with `EvenPanelError` (#94's
    TC-AGG-04 pin). A discard that fires on every even panel would have rounded
    TC-AGG-04's case instead of refusing it."""
    aggregate, even_panel_error = require(
        AGG_MODULE, "aggregate", "EvenPanelError", issue="#93"
    )

    with pytest.raises(even_panel_error):
        aggregate(_TWO_LEFT, _FOUR_BAND, signals(), config=agg_config())


def test_tc_agg_13_a_deterministic_score_passes_through_unchanged():
    """`TC-AGG-13` (`FR-AGG-10`, unit / rung 0, exact value, P0) — a deterministic
    criterion's score passes through aggregation unchanged: `judge_count = 0`,
    `agreement = NULL`, the band and points unmapped, and routing `auto` or `triage`
    — **never** `queued`."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    score = aggregate([], _FOUR_BAND, signals(), deterministic_score=_DETERMINISTIC_ROW,
                      config=agg_config())

    assert score.judge_count == 0, (
        f"the pass-through returned judge_count {score.judge_count!r} — a "
        "deterministic score arrives complete and passes through unchanged "
        "(FR-AGG-10)"
    )
    assert score.agreement is None, (
        f"the pass-through returned agreement {score.agreement!r} — there are no "
        "judges, so agreement is NULL, not a computed substitute (FR-AGG-10)"
    )
    assert score.band == "B2" and score.points == 3.0, (
        f"the pass-through returned band {score.band!r} / points {score.points!r} — "
        "unchanged means unchanged: no re-aggregation, no re-mapping (FR-AGG-10)"
    )
    assert score.routing in ("auto", "triage"), (
        f"the pass-through routed {score.routing!r} — a deterministic score is 'auto' "
        "or 'triage' and is NEVER assigned 'queued' (FR-AGG-10, CT-AGG-06)"
    )
    assert score.routing == "auto", (
        f"the pass-through changed routing to {score.routing!r} — the row arrived "
        "routing 'auto' and passes through unchanged"
    )


@pytest.mark.parametrize(
    ("cell", "expected_state"),
    [
        ("normal_panel", "final"),
        ("provisional_fallback", "provisional_unreviewed"),
        ("tripped_breaker", "ungradeable_by_panel"),
        ("unresolved_selection", "unresolved_selection"),
    ],
)
def test_tc_agg_14_the_state_matches_the_cause(cell, expected_state):
    """`TC-AGG-14` (`FR-AGG-11`, unit / rung 0, exact value per cell, P0) —
    `criterion_score.state` takes exactly one of the four declared values, matching
    the cause: a normal panel is `final`; the single-judge fallback is
    `provisional_unreviewed`; a criterion the M-ORCH breaker tripped is
    `ungradeable_by_panel`; an unresolved selection stays `unresolved_selection`."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    if cell == "normal_panel":
        score = aggregate(
            panel(("B2", 2), ("B2", 2), ("B3", 3)), _FOUR_BAND, signals(),
            config=agg_config(),
        )
    elif cell == "provisional_fallback":
        score = aggregate(
            panel(("B1", 1), ("B3", 3)), _FOUR_BAND, signals(), fallback=True,
            config=agg_config(),
        )
    elif cell == "tripped_breaker":
        score = aggregate(
            panel(("B2", 2), ("B2", 2), ("B3", 3)), _FOUR_BAND, signals(),
            breaker_tripped=True, config=agg_config(),
        )
    else:
        row = dict(_DETERMINISTIC_ROW, state="unresolved_selection", routing="triage",
                   points=None)
        score = aggregate([], _FOUR_BAND, signals(), deterministic_score=row,
                          config=agg_config())

    assert score.state == expected_state, (
        f"the {cell} cell recorded state {score.state!r}, expected "
        f"{expected_state!r} — the state names the cause (FR-AGG-11, R26; the "
        "shipped migration v9 CHECK enforces the set)"
    )
