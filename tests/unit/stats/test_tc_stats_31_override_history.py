"""`TS-89` (issue #383) — `TC-STATS-31`: one criterion's override history (`FR-STATS-24`,
`CT-STATS-09`).

| Arm | Population | Expected |
|---|---|---|
| 1 | no labels | `NoValidationData` |
| 2 | 4 labels | `NoValidationData` (below min n, the same threshold as `TC-REVIEW-25`) |
| 3 | 5 labels, 2 overrides | `n=5, overrides=2, rate=0.4` |
| 4 | — | `should_escalate`'s `history` argument and `FR-REVIEW-18` both consume this exact object |

**Arm 1's distinction is the whole clause.** A zero rate on a *reviewed* criterion is evidence
that the criterion works; a zero on an *unreviewed* one is evidence of nothing. They rank
oppositely in exactly the queue that decides what gets looked at next, so a fabricated `0.0`
would rank an unexamined criterion as the safest thing in the cohort.

**Arms 2 and 4 are `writtenahead`, keyed to #433 — and finding that is this file's main
result.** Two things the plan asks for are not built:

* **The minimum-n threshold is not applied anywhere.** `REVIEW_OVERRIDE_MIN_N = 5` is declared
  and the `override_min_n` knob is read into `_knobs()`, but `grep -rn "override_min_n" src/`
  finds no third site: nothing consumes it. `criterion_override_history` returns a figure for
  any non-empty population, so four judgments and one override read as a 25% override rate —
  which is the reading the constant's own comment forbids ("Four teachers who overrode once
  are not a 25% override rate; they are four teachers").
* **The consumer is not wired.** `_ScoreRowContext` is constructed with `weights`, `models`,
  `boundary_deltas` and `knobs` and **never** with `override_rates`, so
  `_ScoreRowContext.override_rate` returns `None` for every criterion and
  `_StoredScoreRow.historical_override_rate` is `None` on every store-backed row.

Both are #433's subject exactly ("settle D-5's override-rate population and wire
FR-REVIEW-18's eighth input"), and #433 is open. #368 **deliberately withdrew** a private
override-rate derivation inside `aeh.review` rather than ship a second definition under one
name, which is the right call and the reason the input is inert rather than wrong. So the two
arms are written against the interface and marked, and the blocker's probe is the wiring
itself.

**Isolation: rung 0** — `ValidationStats` over an in-memory label population. The plan says
rung 2; the figure is computed entirely from `admissible_labels()` and reads no store, so a
real store would add a dependency the oracle does not use. Reported rather than staged.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from aeh.stats import (
    CriterionOverrideHistory,
    NoValidationData,
    ValidationStats,
)

CRITERION = "C1"

#: `REVIEW_OVERRIDE_MIN_N`'s value, named here so arm 2 and `TC-REVIEW-25`'s sweep row agree
#: about which threshold they are asserting.
MIN_N = 5


@dataclass(frozen=True)
class _Label:
    """An admissible label — blind, judged, visibility flag recorded as 0. `origin` is what
    marks an override, which is how `criterion_override_history` counts them."""

    label_id: str
    origin: str = "blind_sample"
    criterion_id: str = CRITERION
    label_type: str = "blind"
    evaluation_mode: str = "judged"
    saw_system_output: int = 0


def _stats(labels) -> ValidationStats:
    return ValidationStats(labels=labels)


def _population(n: int, overrides: int) -> tuple[_Label, ...]:
    return tuple(
        _Label(f"L{index}", origin="override" if index < overrides else "blind_sample")
        for index in range(n)
    )


# --- TC-STATS-31 ----------------------------------------------------------------------------


def test_tc_stats_31_arm_1_a_criterion_nobody_reviewed_has_no_data():
    """Arm 1 — no labels: `NoValidationData`, never a rate of zero.

    The asserted type is the requirement. A `0.0` here is not a smaller version of the right
    answer; it is the opposite claim, and it sorts an unexamined criterion to the bottom of the
    queue that would have examined it.
    """
    answer = _stats(()).criterion_override_history(CRITERION)

    assert isinstance(answer, NoValidationData), (
        f"an unreviewed criterion answered {answer!r}. CT-STATS-09: a zero rate on a reviewed "
        "criterion is evidence the criterion works, a zero on an unreviewed one is evidence of "
        "nothing, and the two must not be the same value"
    )
    assert getattr(answer, "n", None) == 0


def test_tc_stats_31_arm_3_five_labels_with_two_overrides_read_as_a_rate_of_zero_point_four():
    """Arm 3 — `n=5`, `override_count=2`, `override_rate=0.4`, hand-computed.

    The field names are the shipped `CriterionOverrideHistory`'s. The plan writes
    `OverrideHistory(n=5, overrides=2, rate=0.4)`; no such class or field spelling exists in
    `aeh.stats`, so the values are asserted under the names that ship and #383 reports the
    naming.
    """
    answer = _stats(_population(5, overrides=2)).criterion_override_history(CRITERION)

    assert isinstance(answer, CriterionOverrideHistory), (
        f"a reviewed criterion answered {answer!r} rather than a figure"
    )
    assert (answer.n, answer.override_count, answer.override_rate) == (5, 2, 0.4), (
        f"the history reads n={answer.n}, overrides={answer.override_count}, "
        f"rate={answer.override_rate}; two overrides in five reviews is 0.4"
    )


def test_tc_stats_31_only_labels_of_the_named_criterion_are_counted():
    """A second criterion's overrides do not enter C1's figure.

    Not a plan row, and the guard that keeps arm 3 honest: a figure computed over the whole
    label population would also read 0.4 for a fixture that happened to balance, and would
    report one criterion's teachers disagreeing about another's.
    """
    other = tuple(
        _Label(f"X{index}", origin="override", criterion_id="C2") for index in range(4)
    )
    answer = _stats((*_population(5, overrides=2), *other)).criterion_override_history(
        CRITERION
    )

    assert (answer.n, answer.override_count) == (5, 2), (
        f"C1's history counted C2's labels: n={answer.n}, overrides={answer.override_count}"
    )


def test_tc_stats_31_an_inadmissible_label_never_enters_the_figure():
    """The population is the admissible one — the filter exists once (`NFR-STATS-04`).

    A label whose visibility flag is unrecorded is not evidence for a κ and is not evidence
    here either. Without this, the figure would route around `_is_admissible` and M-STATS would
    hold two populations under one name — the defect D-5 exists to prevent.
    """
    contaminated = (
        *_population(5, overrides=2),
        _Label("U1", origin="override", saw_system_output=1),
    )
    answer = _stats(contaminated).criterion_override_history(CRITERION)

    assert (answer.n, answer.override_count) == (5, 2), (
        f"an inadmissible label entered the override history: n={answer.n}, "
        f"overrides={answer.override_count}. Every figure this module emits is computed over "
        "the population `_is_admissible` admits (NFR-STATS-04)"
    )


# --- The two arms #433 has to land ----------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_31_arm_2_a_population_below_the_minimum_is_no_data():
    """Arm 2 — four labels: `NoValidationData`, because four teachers are not a rate.

    **Red until #433.** `REVIEW_OVERRIDE_MIN_N = 5` is declared and its knob is read, and
    nothing consumes either: `criterion_override_history` returns a figure for any non-empty
    population. Four judgments with one override therefore read as a 25% override rate, which
    the constant's own comment names as the wrong reading.

    Which threshold applies — and whether it belongs to M-STATS or to the M-REVIEW consumer —
    is part of #433's D-5 decision, so this case is written against the plan's reading and
    left for that story to settle.
    """
    answer = _stats(_population(4, overrides=1)).criterion_override_history(CRITERION)

    assert isinstance(answer, NoValidationData), (
        f"four judgments with one override answered {answer!r}. Below n={MIN_N} the figure is "
        "no data: four teachers who overrode once are not a 25% override rate, they are four "
        "teachers (FR-STATS-24, CT-STATS-09)"
    )


@pytest.mark.writtenahead
def test_tc_stats_31_arm_4_the_review_ranking_consumes_this_figure():
    """Arm 4 — `FR-REVIEW-18`'s eighth input reads this object rather than staying `None`.

    **Red until #433.** `_ScoreRowContext` is constructed with `weights`, `models`,
    `boundary_deltas` and `knobs`, never with `override_rates`, so every store-backed row's
    `historical_override_rate` is `None` and one of the eight ranking inputs is inert.

    Asserted at the seam rather than through a ranked queue: the wiring is the fact in
    question, and a rank comparison would also move if any of the other seven inputs changed.
    """
    import inspect

    import aeh.review as review

    source = inspect.getsource(review)
    assert "override_rates=" in source, (
        "`aeh.review` never passes `override_rates=` to `_ScoreRowContext`, so "
        "`_StoredScoreRow.historical_override_rate` is None on every store-backed row and "
        "FR-REVIEW-18's eighth ranking input is inert (#433)"
    )
