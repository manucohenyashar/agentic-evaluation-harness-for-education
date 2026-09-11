"""`TC-STATS-18` — agreement per assignment type, and the spanning refusal.

Test plan §5.16 (`TC-STATS-18`), issue #120 (TS-43). Traces to `FR-STATS-17`.
The plan's row: *"Labels spanning two `assignment_type` values. Agreement
reported separately per assignment type; the module **refuses** to emit a
figure spanning them."* Exact refusal, P0.

MVVP step 4 is the protocol's cross-validation leg: one assignment type's
figures, per criterion, with the spanning refusal structural — one
``assignment_type`` is a *field* of the outcome, not a dimension that could
be summed over, so the spanning claim has no surface to render on. This file
pins the three shapes that surface takes over an in-memory population, plus
the refusal when the dimension is not recorded at all:

- **named type over two types' labels** — the figures are that type's own
  population only, hand-counted: a figure computed over the union of both
  types is exactly the spanning figure the requirement refuses, and its n
  would be the tell;
- **typed labels, no type named** — the disclosed refusal
  (`no_assignment_type_named`, no figures, never a pooled figure under
  either flag);
- **a named type with no labels of it** — `no_labels_for_assignment_type`,
  the honest absence for a type the store's labels do not carry;
- **labels carrying no type at all** — `assignment_type_not_recorded`, the
  disclosure the store's label table produces (it predates the column), which
  is the leg the integration tier's `run_mvvp` over a real store asserts
  (`test_tc_stats_15_mvvp_over_store.py`).

The two-type population is built on a `TypedLabel` — `broken.Label` plus the
``assignment_type`` the dimension is duck-typed off — because the store's
label table has no such column: the *declared* carrying of the dimension is
the caller's, exactly as `agreement()`'s population scope keys are.

`CT-STATS-C04` (`test_ct_stats_figures_and_keying.py`'s
`test_tc_stats_c04_an_aggregate_spanning_a_forbidden_dimension_is_refused`,
which sweeps `assignment_type` among `NON_AGGREGABLE_DIMENSIONS`) pins the
behavioural refusal on the aggregate surface; this file pins step 4's own
outcome — cross-referenced, not repeated.

Isolation: rung 0 — in-memory labels through `build_stats`. Interface: the
landed `run_mvvp`/step-4 surface (#116).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support.impl import STATS_MODULE, require

pytestmark = pytest.mark.contract

CRITERION = "C-01"
EXTENDED = "extended_response"
SHORT = "short_answer"

#: The two populations the step must never blend. Hand-counted: 12 labels on
#: the extended-response type (2 of them disagreeing), 8 on short-answer
#: (2 disagreeing). A pooled figure would carry n = 20 — the tell the per-type
#: figures are asserted against.
EXTENDED_N = 12
SHORT_N = 8


@dataclass(frozen=True)
class TypedLabel(broken.Label):
    """`broken.Label` plus the assignment-type dimension, duck-typed the way
    `_cross_validation_outcome` reads it (`getattr(label, "assignment_type",
    None)`)."""

    assignment_type: str | None = None


def _population() -> list:
    """Two types' blind judged labels on the one criterion, hand-counted."""
    labels: list = []
    labels += [
        TypedLabel(
            label_id=f"ext-{i}",
            criterion_id=CRITERION,
            band=3 if i % 4 else 1,
            teacher_band=3,
            assignment_type=EXTENDED,
        )
        for i in range(EXTENDED_N)
    ]
    labels += [
        TypedLabel(
            label_id=f"short-{i}",
            criterion_id=CRITERION,
            band=2,
            teacher_band=2 if i < SHORT_N - 2 else 4,
            assignment_type=SHORT,
        )
        for i in range(SHORT_N)
    ]
    return labels


def _build():
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    return build_stats(
        _population(),
        scoring_models={CRITERION: "atomic"},
        band_counts={CRITERION: 4},
    )


def _step4(report):
    return report.steps[4].outcome


def _run_mvvp(stats, assignment_type):
    return require(STATS_MODULE, "run_mvvp", issue="#116")(
        stats, assignment_type=assignment_type
    )


# --- the per-type separation ---------------------------------------------------------------


def test_tc_stats_18_a_named_type_figures_only_that_types_population():
    """Step 4 with a type named: the figures are that type's own, exactly.

    The extended-response figure is computed over the 12 extended labels —
    the 8 short-answer labels are not in it. `n` is the tell a pooled figure
    cannot survive: the union would carry 20, and anything other than the
    named type's own hand-count means the figure spans."""
    stats = _build()
    outcome = _step4(_run_mvvp(stats, EXTENDED))

    assert outcome.assignment_type == EXTENDED
    assert outcome.assignment_type_recorded is True
    assert outcome.spanning_refused is True
    assert outcome.reason == ""
    assert set(outcome.figures) == {CRITERION}
    figure = outcome.figures[CRITERION]
    assert figure.n == EXTENDED_N, (
        f"the extended-response figure carried n={figure.n}; the named type's "
        f"population is {EXTENDED_N}, and the other type's {SHORT_N} labels "
        "are not in it — a figure over the union is the spanning figure "
        "FR-STATS-17 refuses"
    )


def test_tc_stats_18_the_other_type_gets_its_own_figures_on_its_own_call():
    """The same protocol, the other type named: a different population, the
    same structural shape.

    Reported separately means each call figures only its type — and the two
    calls' figures are not the same figure re-keyed: the short-answer
    population disagrees where extended agrees, so a shared pooled figure
    cannot satisfy both n's."""
    stats = _build()
    short_outcome = _step4(_run_mvvp(stats, SHORT))
    ext_outcome = _step4(_run_mvvp(stats, EXTENDED))

    assert short_outcome.figures[CRITERION].n == SHORT_N
    assert ext_outcome.figures[CRITERION].n == EXTENDED_N
    assert short_outcome.spanning_refused is True
    # The disagreement shapes differ, hand-planted: the extended population
    # is unanimous (band 3 vs teacher 3, with three band-1 dissenters at
    # i % 4 == 0), the short one carries 2 disagreements. A pooled κ would
    # blend them; the two n's above already refuse that — this pins that the
    # populations are the *types'* by their own agreement behaviour, not by
    # count alone.
    assert short_outcome.figures[CRITERION].kappa is not None, (
        "the short-answer population's figure was an absence; its 8 labels "
        "are judged and paired, so a figure is computable and the per-type "
        "call must compute it"
    )


# --- the refusals, exact ---------------------------------------------------------------------


def test_tc_stats_18_typed_labels_with_no_type_named_refuse_to_pool():
    """Typed labels, no type named: `no_assignment_type_named`, no figures.

    A figure over the union of every type is exactly the spanning figure the
    requirement refuses — the refusal is the *disclosure*, not a silent empty
    result: `assignment_type_recorded` says the labels carry types (so the
    caller could have named one), `spanning_refused` says no pooled figure
    was computed, and `figures` is empty."""
    stats = _build()
    outcome = _step4(_run_mvvp(stats, None))

    assert outcome.assignment_type is None
    assert outcome.assignment_type_recorded is True
    assert outcome.spanning_refused is True
    assert outcome.figures == {}, (
        f"the unnamed-type call returned figures {dict(outcome.figures)!r}; "
        "the labels carry types and none was named, so a figure here is "
        "computed over the union of every type — the spanning figure "
        "FR-STATS-17 refuses"
    )
    assert outcome.reason == "no_assignment_type_named"


def test_tc_stats_18_labels_without_the_dimension_disclose_its_absence():
    """Labels carrying no assignment type: `assignment_type_not_recorded`.

    The store's label table predates the column, so a store-backed run's
    labels carry no type; the refusal is the *disclosure* of that fact —
    `assignment_type_recorded` False, `figures` empty — never a figure over a
    population nobody split. (The integration tier's store leg
    `test_tc_stats_15_mvvp_over_store.py` asserts the same refusal over the
    real `label` table's rows; this is the same branch at rung 0.)"""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(
        broken.agreeing_population(),
        scoring_models={CRITERION: "atomic"},
        band_counts={CRITERION: 4},
    )
    outcome = _step4(_run_mvvp(stats, EXTENDED))

    assert outcome.assignment_type_recorded is False, (
        "untyped labels were read as carrying an assignment type; the "
        "dimension is duck-typed off the labels, and its absence is the "
        "disclosure"
    )
    assert outcome.figures == {}
    assert outcome.reason == "assignment_type_not_recorded"
    assert outcome.spanning_refused is True


def test_tc_stats_18_a_named_type_with_no_labels_is_the_named_absence():
    """A type named that the labels do not carry: `no_labels_for_assignment_type`.

    The refusal is the honest answer for a typed population that does not
    include the requested type — not a figure over some other type's labels
    under the requested name, which would be a mislabeled claim."""
    stats = _build()
    outcome = _step4(_run_mvvp(stats, "portfolio_review"))

    assert outcome.assignment_type == "portfolio_review"
    assert outcome.assignment_type_recorded is True
    assert outcome.figures == {}, (
        "a type the labels do not carry returned figures; the population for "
        "'portfolio_review' is empty and the honest answer is the disclosed "
        "refusal, not another type's figure under this name"
    )
    assert outcome.reason == "no_labels_for_assignment_type"