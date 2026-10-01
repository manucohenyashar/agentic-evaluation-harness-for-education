"""Which labels may count toward a validity figure, and why each excluded one was excluded."""

from __future__ import annotations

from typing import Any, Mapping


# --- the admissibility filter (NFR-STATS-04) ------------------------------------------------------
#
# The predicate exists exactly once in the source (`NFR-STATS-04`) and is
# reused: ``ValidationStats.admissible_labels()`` applies it and every figure
# routes through that application, so R20 and R53 cannot be violated by a new
# caller — the second figure the clause ("none will be added") exists to
# prevent has no door to enter by.
#
# The predicate is the conjunction the contract states, and it reads the two
# columns that own their own enforcement: ``saw_system_output`` is M-REVIEW's
# (`CT-REVIEW-08`) and ``evaluation_mode`` is `CT-DET-06`'s, which is what
# makes the exclusion enforceable from the data rather than by convention.


#: #356 (`FR-STATS-22`, `CT-STATS-23`): the consumer-side treatment of an unrecorded
#: visibility flag. `True` is the standing declaration that a `None` or absent
#: ``saw_system_output`` is **inadmissible**, never read as blind — the distinction the
#: producers' own enforcement cannot make for a duck-typed shape that never had the column.
SAW_SYSTEM_OUTPUT_NULL_IS_INADMISSIBLE = True


#: The name the exclusion is counted under when the flag is unrecorded.
SAW_SYSTEM_OUTPUT_UNRECORDED = "saw_system_output_unrecorded"


def _saw_system_output_recorded_zero(label: Any) -> bool:
    """Whether the label's `saw_system_output` flag is present and equal to 0 (FR-STATS-22).

    Present and 0 is the only admitting reading. A 1 excludes for the obvious reason; a
    ``None`` and a missing attribute both mean *nobody recorded whether this teacher saw the
    system's band*, and an unrecorded flag read as "did not see it" is how an un-blind label
    enters a validity claim — the figure then carries agreement the system partly authored
    (R20/R53). The store cannot hold a null (`NOT NULL DEFAULT 1`), so this decides the
    duck-typed shapes the column predates, which is exactly where the accommodation used to
    admit them.
    """
    sentinel = object()
    flag = getattr(label, "saw_system_output", sentinel)
    if flag is sentinel or flag is None:
        return False
    return int(bool(flag)) == 0


def _is_admissible(label: Any) -> bool:
    """Whether one label may count toward a validity claim.

    Admissible means ``label_type = 'blind'`` **and** ``evaluation_mode = 'judged'``
    (R20/R53) **and** a visibility flag that is present and 0 (`FR-STATS-22`): a label may
    carry ``label_type = 'blind'`` and still have been produced by a teacher who reached the
    system's output, so the flag's truthfulness is the third condition — a 1 excludes, and so
    does an unrecorded flag (`None`, or no attribute at all). The older reading admitted a
    missing attribute deliberately, for in-memory shapes that predate the column; #356 closes
    that door, because "not recorded" and "recorded as unseen" are different facts and only
    one of them is evidence. This function is the filter's single definition; every figure
    this module emits is computed over the population it admits (`NFR-STATS-04`), and
    `TC-STATS-C01` asserts that the definition exists exactly once.
    """
    return (
        getattr(label, "label_type", "") == "blind"
        and getattr(label, "evaluation_mode", "") == "judged"
        and _saw_system_output_recorded_zero(label)
    )


#: FR-REVIEW-23 / CT-STATS-04 (#514): an admissible label that records no backend is not
#: attributable to one, so a backend-scoped figure excludes it under this name.
BACKEND_NOT_RECORDED = "backend_not_recorded"


def _label_backend(label: Any) -> str | None:
    return getattr(label, "backend_profile", None) or None


def exclusion_reasons(labels: Any, backend_profile: str | None = None,
                      criterion_id: str | None = None) -> dict[str, int]:
    """Why each excluded label was excluded, by name (FR-STATS-22).

    A bare ``excluded_count`` says how many labels are not evidence; this says what is wrong
    with them, so "20 excluded" is actionable rather than mysterious. The unrecorded-flag
    count is its own name — `saw_system_output_unrecorded` — because it is the one exclusion
    a deployment can FIX by recording the column, and the one an earlier reading silently
    admitted.
    """
    reasons: dict[str, int] = {}
    sentinel = object()
    for label in labels or ():
        if _is_admissible(label):
            continue
        # The conjunction itself is `_is_admissible`'s alone (`NFR-STATS-04`,
        # `TC-STATS-C01`: one definition). This names the visibility flag's own reading —
        # the distinction #356 adds — and reports everything else as the generic exclusion
        # rather than re-deciding what admissible means.
        flag = getattr(label, "saw_system_output", sentinel)
        if flag is sentinel or flag is None:
            key = SAW_SYSTEM_OUTPUT_UNRECORDED
        elif int(bool(flag)) == 1:
            key = "saw_system_output"
        else:
            key = "not_blind_or_not_judged"
        reasons[key] = reasons.get(key, 0) + 1
    if backend_profile is not None:
        # A backend-scoped read (#514): admissible labels no backend can claim are excluded
        # from it, and said so, rather than pooled into whichever backend was asked for.
        # Keyed like the figure: within `criterion_id` when one is named.
        unattributed = sum(1 for label in labels or ()
                           if _is_admissible(label) and _label_backend(label) is None
                           and (criterion_id is None
                                or getattr(label, "criterion_id", "") == criterion_id))
        if unattributed:
            reasons[BACKEND_NOT_RECORDED] = unattributed
    return reasons


def _system_side(label: Any) -> Any:
    """The label's system-side band, from whichever attribute carries it.

    The review service's labels name the pair ``system_band``/``teacher_band``
    (`CT-REVIEW-08`); the collection fixtures name the system side ``band``
    with the teacher's band beside it. Both shapes carry the same two facts,
    so the extraction reads the pair whichever way it is spelled, and the
    figure's ``input_fields`` disclosure names the attributes actually read —
    never a points field (`CT-REVIEW-07`).

    A stored label whose ``system_band`` column is NULL (the blind flow's —
    #111) returns ``None``: the pair is genuinely one-sided, and the label
    stays in ``n`` while dropping out of the statistic rather than borrowing
    the teacher's side of the pair, which would manufacture agreement."""
    if hasattr(label, "system_band"):
        return label.system_band
    return getattr(label, "band", None)


class _StoredLabel:
    """One stored `label` row, with its columns mapped to the names the filter uses.

    `band` is the band the label stands for (FR-REVIEW-09), and `teacher_band` falls back to it
    when the column is NULL. `routing` feeds the routing-policy arms (FR-STATS-08); old rows
    without it read as None and are kept out of both arms. `origin` is the evidence class
    (FR-STATS-14, CT-STATS-06). `cohort_id` is the administration that claimed the label, or None
    before any has."""

    def __init__(self, mapping: Mapping[str, Any]) -> None:
        # The stored row as read, kept beside the mapped vocabulary (`FR-STATS-23`).
        # The named attributes below are the FILTER's reading — the handful of columns
        # the statistics actually branch on — and the long-horizon export needs the rest
        # (`#368`'s `agreed`, `band_distance`, `package_version_id` among them). Keeping
        # the row here is what lets the export stay faithful WITHOUT reopening a
        # database, which is the property that makes it safe to run beside a live
        # scoring run. It is never read by a statistic: adding an attribute above is how
        # a column enters the filter, deliberately.
        self._row = dict(mapping)
        self.label_id = mapping.get("label_id")
        self.criterion_id = mapping.get("criterion_id") or ""
        self.label_type = mapping.get("label_type") or ""
        self.evaluation_mode = mapping.get("evaluation_mode") or ""
        # #356 (`FR-STATS-22`): a NULL column and an absent key both mean UNRECORDED, and
        # the adapter must not resolve them to a recorded 0 — that is the very coercion the
        # predicate exists to refuse, and doing it here would admit every stored label
        # whatever the column says.
        _saw = mapping.get("saw_system_output")
        self.saw_system_output = None if _saw is None else int(_saw)
        self.system_band = mapping.get("system_band")
        self.teacher_band = (
            mapping["teacher_band"]
            if mapping.get("teacher_band") is not None
            else mapping.get("band")
        )
        self.routing = mapping.get("routing")
        self.origin = mapping.get("origin")
        self.cohort_id = mapping.get("cohort_id")
        # FR-REVIEW-23 (#514): the backend the label's run used; NULL on pre-migration rows,
        # which a backend-scoped figure excludes as `backend_not_recorded` (CT-STATS-04).
        self.backend_profile = mapping.get("backend_profile") or None


def _row_mapping(row: Any) -> dict[str, Any]:
    """A store row as a plain mapping, whatever row type the tier returns."""
    try:
        return {key: row[key] for key in row.keys()}
    except AttributeError:
        return dict(row)
