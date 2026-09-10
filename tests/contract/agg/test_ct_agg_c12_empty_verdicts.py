"""`TC-AGG-C12` — an empty panel is a loud programming error, never a substitute (§6.11.12).

`CT-AGG-12`: "Aggregating over an empty verdict set is a **programming error** and
raises — it is never a zero, a lowest band, or a null score. A band absent from the
criterion's set never reaches here; `M-JUDGE` rejects it first (`CT-JUDGE-04`)."

The case has two limbs:

- **the exact exception, swept over the three forbidden substitutes**: the empty
  set raises `EmptyVerdictsError` — *that class*, not a bare `ValueError` stand-in
  (it subclasses one, so only a type-exact check tells the declared refusal from
  any caller's loose error) — under every entry mark (`fallback=`,
  `breaker_tripped=`), because a mark that bypassed the refusal would be a silent
  path around the contract. Each of the three substitutes — a zero, the lowest
  band, a null score — is swept as the outcome the raise forbids: a graceful
  default here is precisely how absent evidence becomes a low band (RISK-03);
- **the precondition's second line of defense**: a panel whose median names an
  ordinal the criterion never declared refuses with `PackageError` — the same
  refusal `M-PKG`'s lookup raises — so an out-of-vocabulary band cannot be silently
  aggregated even if it arrived. `M-JUDGE` rejects it first (`CT-JUDGE-04`'s case,
  the M-JUDGE suite, #80); this module's own refusal is the second gate, and the
  case asserts it holds.

Isolation: rung 0 — pure calls, no store; the socket guard is autouse.
"""

from __future__ import annotations

import pytest

from aeh.agg import EmptyVerdictsError
from aeh.pkg import PackageError
from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    verdict,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require

pytestmark = [pytest.mark.contract]

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))


@pytest.mark.parametrize(
    "forbidden",
    [
        "a zero — absent evidence scored as nought rather than refused",
        "the lowest band — absent evidence becoming a low band (RISK-03)",
        "a null score — absent evidence rendered as None rather than refused",
    ],
    ids=["never_zero", "never_lowest_band", "never_null_score"],
)
def test_tc_agg_c12_an_empty_verdict_set_raises_and_never_substitutes(forbidden):
    """`TC-AGG-C12` (`CT-AGG-12`, error / rung 0, exact exception, P0) — over an
    empty verdict set the module RAISES, and what it raises is exactly
    `EmptyVerdictsError`: never one of the three substitutes the clause forbids.
    The programming error is the loud failure; each param names the quiet
    substitute a wrong implementation would return instead."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")

    with pytest.raises(EmptyVerdictsError) as raised:
        aggregate([], _FOUR_BAND, signals(), config=agg_config())

    assert type(raised.value) is EmptyVerdictsError, (
        f"the empty set refused as {type(raised.value).__name__!r} — the clause "
        "pins the exact exception: `EmptyVerdictsError` subclasses `ValueError`, "
        "so only a type-exact check tells the declared refusal from any caller's "
        "loose error (CT-AGG-12)"
    )
    # The three forbidden outcomes are what a compliant call cannot produce: the
    # refusal carries no score value at all — no points, no band, no None.
    assert not hasattr(raised.value, "points") and not hasattr(raised.value, "band"), (
        f"the refusal carries a score-like payload — {forbidden} reached through "
        "the exception's own shape (CT-AGG-12)"
    )


@pytest.mark.parametrize(
    "marks",
    [
        {},
        {"fallback": True},
        {"breaker_tripped": True},
        {"fallback": True, "breaker_tripped": True},
    ],
    ids=["no_marks", "fallback", "breaker", "fallback_and_breaker"],
)
def test_tc_agg_c12_no_entry_mark_bypasses_the_empty_panel_refusal(marks):
    """`TC-AGG-C12` (`CT-AGG-12` × `FR-AGG-11/12`, error / rung 0, refusal sweep,
    P0) — the fallback mark (the two-verdict discard) and the breaker mark change
    nothing about an EMPTY panel: the refusal precedes every mark. A mark that
    quietly produced the discard's single-judge score, or the breaker's
    ungradeable row, from an empty set would be a silent path around the
    contract — absent evidence wearing a legitimate state."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")

    with pytest.raises(EmptyVerdictsError) as raised:
        aggregate([], _FOUR_BAND, signals(), config=agg_config(), **marks)

    assert type(raised.value) is EmptyVerdictsError, (
        f"marks {sorted(marks)} changed the empty-panel outcome to "
        f"{type(raised.value).__name__!r} — the refusal precedes every entry "
        "mark: `fallback` marks a panel LEFT at two, never an empty one, and a "
        "tripped breaker refuses the score, it does not manufacture one "
        "(CT-AGG-12, FR-AGG-12)"
    )


def test_tc_agg_c12_an_undeclared_band_refuses_at_the_package_lookup():
    """`TC-AGG-C12` (`CT-AGG-12` × `CT-JUDGE-04`, error / rung 0, precondition,
    P0) — a verdict naming an ordinal the criterion never declared cannot be
    aggregated: the band lookup refuses with `PackageError`. `M-JUDGE` rejects the
    undeclared band first (`CT-JUDGE-04`; the M-JUDGE suite's case) — this is the
    second gate, asserted so the aggregation's own refusal is loud too: a silent
    skip here would aggregate a panel whose median names a band the package never
    declared, and the score would cite a band the instrument does not have."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")

    # A panel whose MEDIAN is the undeclared ordinal: three judges, two of them
    # at an ordinal the four-band criterion never declared.
    undeclared = [
        verdict("B3", 3), verdict("B9", 9), verdict("B9", 9),
    ]

    with pytest.raises(PackageError) as raised:
        aggregate(undeclared, _FOUR_BAND, signals(), config=agg_config())

    assert "declares no band at ordinal 9" in str(raised.value), (
        f"the undeclared median refused as {raised.value!r} — the refusal is the "
        "package lookup's (`PackageError`), naming the undeclared ordinal, never "
        "a silent clamp to the nearest declared band (CT-AGG-12's precondition; "
        "M-JUDGE rejects it first, CT-JUDGE-04)"
    )
