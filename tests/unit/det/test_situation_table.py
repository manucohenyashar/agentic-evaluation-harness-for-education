"""`TC-DET-01` and `TC-DET-03` — the §7.8 situation table, swept exhaustively, and the
exact-comparison bands a resolved selection produces. Test plan §5.11; issue #88.

Oracle: **exact value per cell** — band, state, routing, credit and reason are all
asserted, not just the band — plus a call-count assertion that **zero model calls occur
in any cell** (`network_guard.assert_no_network()` over the whole sweep; the guard is
autouse and records every attempt, so a swallowed call cannot hide).

RISK-03 lives here in its purest form: cells 3, 4 and 5 are the requirement — an
unreadable mark is a scanning problem routed to the operator, and there is **no path by
which it becomes an `incorrect`** — and cell 6 is the mirror: a genuinely empty answer IS
a zero. Collapsing the distinction in either direction silently grades students down for
their scanner.

**Isolation: rung 0** — the module-level `evaluate` kernel is a pure function of
(selection, key, policy) plus the two states M-INGEST recorded; no store, no doubles.
"""

from __future__ import annotations

import pytest

from aeh.det import (
    BAND_CORRECT,
    BAND_INCORRECT,
    BAND_UNRESOLVED,
    REASON_ABSENT_REGION,
    REASON_AMBIGUOUS_MARK,
    REASON_BLANK,
    REASON_KEY_MATCH,
    REASON_KEY_MISS,
    REASON_MULTIPLE_MARKS,
    REASON_SELECTION_OUTSIDE_OPTION_SET,
    ROUTING_AUTO,
    ROUTING_TRIAGE,
    STATE_FINAL,
    STATE_UNRESOLVED_SELECTION,
    UndeclaredPartialCreditPolicy,
    evaluate,
)

ISSUE = "#88"

#: The two criteria the plan's preconditions fix: a single-select keyed to B; a
#: multi-select keyed to B and D, once per partial-credit policy.
_SINGLE_KEY = ("B",)
_MULTI_KEY = ("B", "D")


# --- helpers -------------------------------------------------------------------------------


def _single(content_state="present", selection_state="resolved", selection=("B",)):
    return dict(
        content_state=content_state,
        selection_state=selection_state,
        selection=selection,
        key=_SINGLE_KEY,
    )


def _multi(selection, partial_credit):
    return dict(
        content_state="present",
        selection_state="resolved",
        selection=selection,
        key=_MULTI_KEY,
        multi_select=True,
        partial_credit=partial_credit,
    )


def _assert_scored(outcome, *, band, credit, reason, selection_read):
    """The exact scored shape: final/auto, the band and credit, the reason named."""
    assert outcome.band == band, (
        f"expected band {band!r}, got {outcome.band!r} (reason {outcome.reason!r})"
    )
    assert outcome.state == STATE_FINAL
    assert outcome.routing == ROUTING_AUTO
    assert outcome.credit == credit, (
        f"expected credit {credit!r}, got {outcome.credit!r} for reason {reason!r}"
    )
    assert outcome.reason == reason
    assert outcome.selection_read == selection_read


def _assert_unresolved(outcome, *, reason):
    """The exact unresolved shape (cells 3/4/5): never a score, never a zero.

    The band column carries the marker `'unresolved'` — no criterion band is borrowed for
    a row that was never scored — and the credit is exactly 0.0 without being a zero the
    student earned: the row has no score at all.
    """
    assert outcome.band == BAND_UNRESOLVED, (
        f"an unreadable mark scored as {outcome.band!r} — RISK-03's defect: a scanning "
        f"problem must never become a wrong answer (reason was {reason!r})"
    )
    assert outcome.band != BAND_INCORRECT
    assert outcome.state == STATE_UNRESOLVED_SELECTION
    assert outcome.routing == ROUTING_TRIAGE
    assert outcome.credit == 0.0
    assert outcome.reason == reason
    assert outcome.selection_read is None


# --- TC-DET-01 ------------------------------------------------------------------------------


def test_tc_det_01_exact_comparison_produces_the_two_bands(network_guard):
    """`TC-DET-01` — a resolved selection against a key bands exactly `correct` or
    `incorrect`, with the reason naming which; the socket guard confirms zero model calls
    anywhere in the module."""
    hit = evaluate(**_single(selection=("B",)))
    _assert_scored(
        hit, band=BAND_CORRECT, credit=1.0, reason=REASON_KEY_MATCH, selection_read=("B",)
    )
    miss = evaluate(**_single(selection=("C",)))
    _assert_scored(
        miss, band=BAND_INCORRECT, credit=0.0, reason=REASON_KEY_MISS, selection_read=("C",)
    )
    # Both directions of the comparison, so a detector that always says "correct"
    # (or always "incorrect") cannot pass: the pair is the oracle.
    assert hit.band != miss.band
    network_guard.assert_no_network()


# --- TC-DET-03: the eleven cells ------------------------------------------------------------


def test_tc_det_03_cell_1_2_single_select_key_comparison(network_guard):
    """Cells 1-2 — a resolved single-select reads the key: B is `correct`, C is
    `incorrect`, each with its exact reason and credit."""
    _assert_scored(
        evaluate(**_single(selection=("B",))),
        band=BAND_CORRECT,
        credit=1.0,
        reason=REASON_KEY_MATCH,
        selection_read=("B",),
    )
    _assert_scored(
        evaluate(**_single(selection=("C",))),
        band=BAND_INCORRECT,
        credit=0.0,
        reason=REASON_KEY_MISS,
        selection_read=("C",),
    )


def test_tc_det_03_cell_3_ambiguous_is_unresolved_never_incorrect(network_guard):
    """Cell 3 — an ambiguous mark is `unresolved_selection` routed to `triage`; there is
    NO path by which it becomes `incorrect`. This is the requirement, not decoration."""
    _assert_unresolved(evaluate(**_single(selection_state="ambiguous", selection=None)),
                       reason=REASON_AMBIGUOUS_MARK)


def test_tc_det_03_cell_4_multiple_marks_are_unresolved(network_guard):
    """Cell 4 — multiple marks (B, C) are `unresolved_selection` routed to `triage`,
    never "the darkest one" — the heuristic this module exists to refuse."""
    _assert_unresolved(
        evaluate(**_single(selection_state="multiple_marks", selection=("B", "C"))),
        reason=REASON_MULTIPLE_MARKS,
    )


def test_tc_det_03_cell_5_absent_region_is_unresolved(network_guard):
    """Cell 5 — no answer region at all is a scanning problem routed to the operator,
    never a zero the student earned."""
    _assert_unresolved(evaluate(content_state="absent", key=_SINGLE_KEY),
                       reason=REASON_ABSENT_REGION)


def test_tc_det_03_cell_6_blank_is_a_legitimate_zero(network_guard):
    """Cell 6 — the mirror of cells 3/4/5: a genuinely empty answer IS a zero, band
    `incorrect`, counted in blank_count and never in unresolved_count (the counting
    itself is TC-DET-05's oracle; here the cell's exact shape is)."""
    blank = evaluate(content_state="blank", key=_SINGLE_KEY)
    _assert_scored(
        blank, band=BAND_INCORRECT, credit=0.0, reason=REASON_BLANK, selection_read=None
    )
    # And it is NOT the unresolved shape — the two zeros must never be conflated.
    assert blank.state == STATE_FINAL
    assert blank.routing == ROUTING_AUTO
    assert blank.reason != REASON_ABSENT_REGION


def test_tc_det_03_cell_7_multi_select_all_or_nothing_exact_match(network_guard):
    """Cell 7 — B, D against key (B, D) under `all_or_nothing` is `correct`."""
    _assert_scored(
        evaluate(**_multi(("B", "D"), "all_or_nothing")),
        band=BAND_CORRECT,
        credit=1.0,
        reason=REASON_KEY_MATCH,
        selection_read=("B", "D"),
    )


def test_tc_det_03_cell_8_multi_select_all_or_nothing_subset_is_incorrect(network_guard):
    """Cell 8 — B only against key (B, D) under `all_or_nothing` is `incorrect`: a
    subset and a superset are equally not the answer."""
    _assert_scored(
        evaluate(**_multi(("B",), "all_or_nothing")),
        band=BAND_INCORRECT,
        credit=0.0,
        reason=REASON_KEY_MISS,
        selection_read=("B",),
    )


def test_tc_det_03_cell_9_multi_select_per_option_partial(network_guard):
    """Cell 9 — B only against key (B, D) under `per_option` is partial per the declared
    policy: one earned credit of two, band still `incorrect` (only an exact match bands
    `correct`), credit 0.5."""
    _assert_scored(
        evaluate(**_multi(("B",), "per_option")),
        band=BAND_INCORRECT,
        credit=0.5,
        reason=REASON_KEY_MISS,
        selection_read=("B",),
    )


def test_tc_det_03_cell_10_per_option_over_selection_floored_at_zero(network_guard):
    """Cell 10 — B, D, E under `per_option`: the over-selection rule must be STATED, and
    det.py states it — each non-key selection cancels one earned credit, floored at
    zero. Two earned, one cancelled: credit 0.5, band `incorrect`."""
    _assert_scored(
        evaluate(**_multi(("B", "D", "E"), "per_option")),
        band=BAND_INCORRECT,
        credit=0.5,
        reason=REASON_KEY_MISS,
        selection_read=("B", "D", "E"),
    )
    # The floor: three non-key selections cancel both earned credits exactly, and a
    # fourth would not drive the credit negative.
    all_wrong = evaluate(**_multi(("A", "C", "E"), "per_option"))
    _assert_scored(
        all_wrong,
        band=BAND_INCORRECT,
        credit=0.0,
        reason=REASON_KEY_MISS,
        selection_read=("A", "C", "E"),
    )


def test_tc_det_03_cell_11_undeclared_policy_is_never_inferred(network_guard):
    """Cell 11 — the module NEVER infers a policy: a multi-select criterion with no
    declared policy is a package-integrity failure (the criterion's refusal, not a
    runtime default), raised the moment the criterion says multi-select and the package
    declares nothing."""
    with pytest.raises(UndeclaredPartialCreditPolicy):
        evaluate(**_multi(("B",), None))
    # The refusal is the criterion's, not the cell's: a blank multi-select read is
    # scored by the same nonexistent rule, so it raises too rather than being scored
    # around (det.py's committed interpretation of FR-DET-05).
    with pytest.raises(UndeclaredPartialCreditPolicy):
        evaluate(
            content_state="blank",
            key=_MULTI_KEY,
            multi_select=True,
            partial_credit=None,
        )


# --- the zero-model-call oracle over every cell ----------------------------------------------


def test_tc_det_03_zero_model_calls_in_every_cell(network_guard):
    """The table's second oracle, swept: evaluating EVERY cell of §7.8 makes zero model
    calls — `evaluate` is a pure function of (selection, key, policy), and a single
    recorded attempt anywhere in the sweep fails the case."""
    cells = [
        _single(selection=("B",)),
        _single(selection=("C",)),
        _single(selection_state="ambiguous", selection=None),
        _single(selection_state="multiple_marks", selection=("B", "C")),
        dict(content_state="absent", key=_SINGLE_KEY),
        dict(content_state="blank", key=_SINGLE_KEY),
        _multi(("B", "D"), "all_or_nothing"),
        _multi(("B",), "all_or_nothing"),
        _multi(("B",), "per_option"),
        _multi(("B", "D", "E"), "per_option"),
    ]
    outcomes = [evaluate(**cell) for cell in cells]
    network_guard.assert_no_network()
    # Every cell produced a declared outcome — none of the bands outside the vocabulary.
    for outcome in outcomes:
        assert outcome.band in (BAND_CORRECT, BAND_INCORRECT, BAND_UNRESOLVED)


# --- the plan's variants ----------------------------------------------------------------------


def test_tc_det_03_variant_selection_outside_the_option_set(network_guard):
    """Variant 1 — a selection whose option id is not in the option set at all routes
    unresolved: the module refuses to guess what a mark outside the declared option set
    means (it cannot be compared to the key, and it is not a zero)."""
    _assert_unresolved(
        evaluate(**_single(selection=("Z",)), option_set=("A", "B", "C")),
        reason=REASON_SELECTION_OUTSIDE_OPTION_SET,
    )
    # A valid selection in the same option set still scores — the refusal is per read,
    # not per criterion.
    _assert_scored(
        evaluate(**_single(selection=("B",)), option_set=("A", "B", "C")),
        band=BAND_CORRECT,
        credit=1.0,
        reason=REASON_KEY_MATCH,
        selection_read=("B",),
    )


def test_tc_det_03_variant_key_references_a_removed_option(network_guard):
    """Variant 2 — a key referencing an option that was removed by a later version.

    The shipped reading (det.py): the kernel validates SELECTIONS against the option
    set, never the key — a corrected key is a new version's own column (`FR-PKG-18`), and
    a key naming an option no longer in the set is scoreable but can never match: every
    in-set resolved selection bands `incorrect`, and a selection naming the removed
    option routes unresolved. The cell below pins both halves: no crash, no guess, and
    no path by which the impossible key produces a `correct`.
    """
    outcome = evaluate(
        content_state="present",
        selection_state="resolved",
        selection=("A",),
        key=("Z",),
        option_set=("A", "B"),
    )
    _assert_scored(
        outcome, band=BAND_INCORRECT, credit=0.0, reason=REASON_KEY_MISS,
        selection_read=("A",),
    )
    outside = evaluate(
        content_state="present",
        selection_state="resolved",
        selection=("Z",),
        key=("Z",),
        option_set=("A", "B"),
    )
    _assert_unresolved(outside, reason=REASON_SELECTION_OUTSIDE_OPTION_SET)
