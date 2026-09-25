"""`TS-89` (issue #383) — `TC-STATS-29`: an unrecorded visibility flag is inadmissible
(`FR-STATS-22`, `CT-STATS-23`).

| Labels | Expected |
|---|---|
| L1 `saw_system_output=0`; L2 `=1`; L3 `=None`; L4 attribute absent | admitted `{L1}`; `excluded_count` includes L3 and L4 under reason `saw_system_output_unrecorded`, and L2 under the operational reason |

**"Not recorded" and "recorded as unseen" are different facts, and only one is evidence.** The
older reading admitted a missing attribute deliberately, to accommodate in-memory shapes that
predated the column. #356 closed that door because an unrecorded flag read as "did not see it"
is how an un-blind label enters a validity claim — and the resulting figure carries agreement
the system itself partly authored (R20/R53). The κ then measures the system agreeing with a
teacher who was looking at the system's answer.

**L3 and L4 are separate rows for a reason.** `None` and *no attribute at all* reach the
predicate by different routes — a store row with a null column versus a duck-typed object that
never had one — and an implementation that guarded only `is None` admits L4 silently. The
store cannot hold a null (`NOT NULL DEFAULT 1`), so L4's shape is the one that actually occurs.

**The unrecorded exclusion has its own name.** `saw_system_output_unrecorded` is separate from
the operational `saw_system_output` because it is the one exclusion a deployment can **fix**,
by recording the column. Collapsing the two would turn an actionable count into a mysterious
one, which is what seam 4 exists to prevent.

**Isolation: rung 0** — the admissibility predicate and the exclusion counter are pure
functions over label shapes; no store is involved and none is needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from aeh.stats import (
    SAW_SYSTEM_OUTPUT_UNRECORDED,
    _is_admissible,
    exclusion_reasons,
)

#: The operational exclusion — the teacher demonstrably saw the system's band.
SAW_IT = "saw_system_output"


@dataclass(frozen=True)
class _Label:
    """A label carrying the four columns the predicate reads. `saw_system_output` is declared
    here so L1, L2 and L3 can set it; L4 uses `_LabelWithoutFlag`, which does not declare it
    at all — the two absences are different shapes and the case needs both."""

    label_id: str
    saw_system_output: int | None
    label_type: str = "blind"
    evaluation_mode: str = "judged"


@dataclass(frozen=True)
class _LabelWithoutFlag:
    """L4 — a duck-typed label that never had the column. `getattr` finds nothing, which is a
    different path through the predicate from a declared `None`."""

    label_id: str
    label_type: str = "blind"
    evaluation_mode: str = "judged"


L1 = _Label("L1", saw_system_output=0)
L2 = _Label("L2", saw_system_output=1)
L3 = _Label("L3", saw_system_output=None)
L4 = _LabelWithoutFlag("L4")
POPULATION = (L1, L2, L3, L4)


# --- TC-STATS-29 ----------------------------------------------------------------------------


def test_tc_stats_29_only_a_recorded_zero_is_admitted():
    """Admitted is exactly `{L1}` — present and 0 is the only admitting reading.

    Asserted as the whole set rather than per label, so an implementation that admitted one
    extra shape shows up here as a membership difference rather than as a case nobody wrote.
    """
    admitted = {label.label_id for label in POPULATION if _is_admissible(label)}

    assert admitted == {"L1"}, (
        f"admitted {sorted(admitted)}; only a visibility flag that is PRESENT and 0 is "
        "evidence (FR-STATS-22). A 1 means the teacher saw the system's band; a None or an "
        "absent attribute means nobody recorded whether they did, and an unrecorded flag read "
        "as 'did not see it' is how an un-blind label enters a validity claim (R20/R53)"
    )


@pytest.mark.parametrize(
    "label,why",
    (
        (L2, "the teacher demonstrably saw the system's band"),
        (L3, "the flag is declared but null — nobody recorded it"),
        (L4, "the shape never had the column at all"),
    ),
)
def test_tc_stats_29_each_inadmissible_shape_is_refused_on_its_own(label, why):
    """Each of L2, L3 and L4 separately, so a passing set-equality cannot hide one.

    L4 is the shape that actually occurs: the store's column is `NOT NULL DEFAULT 1`, so a
    real null cannot be stored, and the unrecorded case arrives as a duck-typed object the
    column predates. An implementation guarding only `is None` passes for L3 and admits L4.
    """
    assert _is_admissible(label) is False, (
        f"{label.label_id} was admitted although {why}"
    )


def test_tc_stats_29_the_unrecorded_flag_is_counted_under_its_own_reason():
    """L3 and L4 count under `saw_system_output_unrecorded`; L2 under the operational reason.

    The separation is the requirement. `saw_system_output_unrecorded` is the one exclusion a
    deployment can fix by recording the column; folding it into the operational count would
    tell an operator that two teachers peeked when in fact nobody wrote the flag down.
    """
    reasons = exclusion_reasons(POPULATION)

    assert reasons.get(SAW_SYSTEM_OUTPUT_UNRECORDED) == 2, (
        f"the unrecorded reason counts {reasons.get(SAW_SYSTEM_OUTPUT_UNRECORDED)!r}, not 2 "
        f"(L3 and L4): {reasons}"
    )
    assert reasons.get(SAW_IT) == 1, (
        f"the operational reason counts {reasons.get(SAW_IT)!r}, not 1 (L2): {reasons}. "
        "An unrecorded flag and a teacher who saw the band are different findings and a "
        "deployment acts differently on each"
    )
    assert sum(reasons.values()) == 3, (
        f"three of the four labels are inadmissible; the reasons total "
        f"{sum(reasons.values())}: {reasons}"
    )


def test_tc_stats_29_an_admitted_label_is_counted_under_no_reason():
    """The positive control: L1 alone produces an empty reason map.

    Without it, every count above would also pass against a counter that attributed a reason
    to every label it saw, admissible or not — and `excluded_count` would then exceed the
    number of labels actually excluded.
    """
    assert exclusion_reasons((L1,)) == {}, (
        f"an admissible label was given an exclusion reason: {exclusion_reasons((L1,))}"
    )


def test_tc_stats_29_a_non_blind_or_non_judged_label_is_a_different_reason():
    """The generic exclusion stays generic — the flag's reading does not swallow it.

    `_is_admissible` is a three-way conjunction, and this pins that the reason counter reports
    the other two conditions under their own name rather than mislabelling them as a
    visibility problem an operator would then try to fix by recording a column.
    """
    not_blind = _Label("L5", saw_system_output=0, label_type="review")
    not_judged = _Label("L6", saw_system_output=0, evaluation_mode="deterministic")

    reasons = exclusion_reasons((not_blind, not_judged))

    assert reasons == {"not_blind_or_not_judged": 2}, (
        f"a non-blind and a non-judged label were counted as {reasons}; neither has anything "
        "wrong with its visibility flag, and reporting them there would send an operator "
        "after the wrong column"
    )
