"""The schema lock: which fields a published version freezes, and the count of refused edits."""

from __future__ import annotations


class _ViolationCounter:
    """The monotone count of refused §6.2-locked edits (`CT-PKG-16`'s alert signal).

    The NAME is contract (`RISK-35`): a rising `schema_lock_violation_count` means a
    caller is attempting something the design forbids, and an alert on a renamed signal
    is an alert that silently watches nothing. Exposed through
    `schema_lock_violation_count()`; the rate ops alerts on is this counter's
    derivative, which a monitor computes — the module owns the count, not the clock."""

    def __init__(self) -> None:
        self._value = 0

    def increment(self) -> None:
        self._value += 1

    @property
    def value(self) -> int:
        return self._value


#: The stable-name signal itself. Module-level, so every catalog instance's refusals
#: contribute to the one number ops watches.
SCHEMA_LOCK_VIOLATIONS = _ViolationCounter()


def schema_lock_violation_count() -> int:
    """`CT-PKG-16`'s stable-name accessor: §6.2-locked edits refused, monotone over the
    process lifetime. A rising rate is an alert signal meaning a caller is attempting
    something the design forbids."""
    return SCHEMA_LOCK_VIOLATIONS.value


#: The §6.2 schema lock, in exactly one place (`NFR-PKG-03`): every `(table, field)` edit
#: a published version refuses, enumerable at runtime so a test can assert the list
#: matches HLD §6.2 field for field. `question_type` is the HLD's name for the physical
#: `kind` column — the HLD name is what the list carries, because the enumeration test
#: reads it against the HLD text.
SCHEMA_LOCK_FIELDS: tuple[tuple[str, str], ...] = (
    ("criterion", "max_points"),
    ("criterion", "add"),
    ("criterion", "remove"),
    ("criterion", "question_type"),
    ("criterion", "scoring_model"),
    ("criterion", "construct_tag"),
    ("band", "label"),
    ("band", "ordinal"),
    ("band", "descriptor"),
    ("band", "points"),
    ("criterion_dependency", "add"),
    ("criterion_dependency", "remove"),
    ("criterion_dependency", "alter"),
)


#: The HLD §6.2 vocabulary for the lockable fields whose guard string differs from the
#: HLD's own name (`FR-PKG-03` states the lock in the HLD's words: a criterion's
#: `criterion_count` — "adding or removing a criterion" — and its `criterion_band` rows,
#: while the guard's strings are the SQL-shaped `"criterion.add"` / `"band.label"`). A
#: refusal that names only the guard string does not name the field the way the design
#: states it, and `M-CALIB`'s sweep (`CT-CALIB-06`) asserts the refusal in the HLD's
#: vocabulary — so the message carries both. **A message-vocabulary map only**: it names
#: fields in refusals, it never gates them — membership is `SCHEMA_LOCK_FIELDS`'s alone,
#: and this dict deliberately carries no second copy of that list (`NFR-PKG-03`). The
#: keys are the guard strings, not `(table, field)` tuples, for the same single-definition
#: reason: the tuple literals belong to the list above and nowhere else.
_LOCKED_FIELD_HLD_NAMES: dict[str, str] = {
    "criterion.add": "criterion_count",
    "criterion.remove": "criterion_count",
    "band.label": "criterion_band",
    "band.ordinal": "criterion_band",
    "band.descriptor": "criterion_band",
    "band.points": "criterion_band",
}
