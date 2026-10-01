"""Tolerant reads of stored score rows and of their integrity signals (which values are adverse)."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any


#: The favourable polarity of each signal — the value meaning "nothing wrong"
#: (§3.12): `spans_verified` and `evidence_present` are favourable when True;
#: the other four are favourable when False (e.g. `ocr_overlap_risk = False` is
#: no overlap risk). Any other value — the opposite boolean, or `None` = "not
#: measured" — is adverse, fail-closed. One map, so the adverse reading is
#: computed from ONE definition everywhere (the test vocabulary's `FAVOURABLE`
#: precedent, mirrored here as production data).
#:
#: §3.12's cap table declares one cap conditional — `evidence_present` binds
#: only where "evidence is required". The criterion expresses that through
#: `evidence_required` (M-PKG's citation-requiring reading); a criterion that
#: does not declare the flag is read as requiring evidence — fail-closed: the
#: cap can bind, never be skipped by an omission.
_AGG_FAVOURABLE = MappingProxyType({
    "spans_verified": True,
    "evidence_present": True,
    "sufficiency_flag": False,
    "ocr_overlap_risk": False,
    "described_evidence": False,
    "extractor_disagreement": False,
})


#: The four integrity inputs recorded on every score row since cohort migration
#: v16 — the inputs `recompute_confidence` re-applies from any stored row.
_RECORDED_SIGNAL_FIELDS: tuple[str, ...] = (
    "spans_verified",
    "evidence_present",
    "sufficiency_flag",
    "ocr_overlap_risk",
)


#: `FR-AGG-13` amended (#360): the two signals `write_score` records beside the
#: four, so the stored row carries all six. They are re-applied only from a row
#: `write_score` wrote — one whose `caps_fired` is recorded — because an older
#: row's `NULL` in these columns means "column did not exist", not "not
#: measured", and reading it adverse would re-derive a figure lower than the one
#: that was stored.
_WRITTEN_SIGNAL_FIELDS: tuple[str, ...] = ("described_evidence", "extractor_disagreement")


def _signal_adverse(value: Any, favourable: bool) -> bool:
    """Whether one integrity signal's value is adverse. Unknown values count as adverse (design
    §3.12).

    `None` means "not measured" — no second extraction ran, the span check did
    not fire — and is adverse, never favourable and never absent (CT-INTEG-02's
    reading: a consumer that collapses `None` into `False` reads "not measured"
    as "measured, and agreed", the equivalence the clause names wrong by name).
    Otherwise the value is adverse exactly when it is not the signal's
    favourable polarity (`_AGG_FAVOURABLE`).
    """
    if value is None:
        return True
    return bool(value) != favourable


def adverse_signal_count(row: Any) -> int:
    """How many of a score row's stored integrity signals are adverse (FR-REVIEW-18).

    M-REVIEW's ranking input, computed HERE because the polarity that makes a signal
    adverse is declared here once (`_AGG_FAVOURABLE`) and a second copy in the ranker
    could disagree with the confidence the same row already carries.

    The field set follows `recompute_confidence`'s rule exactly: the four recorded since
    cohort v16, plus the two `write_score` adds only when the row's `caps_fired` is
    recorded. A `NULL` in `described_evidence` on a row without `caps_fired` means "this
    column did not exist when the row was written", not "not measured", and counting it
    adverse would rank an old row above a new one for having been written earlier.
    Within the selected fields `None` IS adverse, fail-closed, as everywhere else.
    """
    fields = _RECORDED_SIGNAL_FIELDS
    if _row_value(row, "caps_fired") is not None:
        fields = fields + _WRITTEN_SIGNAL_FIELDS
    return sum(
        1
        for field in fields
        if _signal_adverse(_row_value(row, field), _AGG_FAVOURABLE[field])
    )


# --- the re-derivation: confidence from the stored row alone (`NFR-AGG-04`) ------------------------


def _row_value(row: Any, field: str) -> Any:
    """Read one field of a stored score row, whatever shape the row has.

    `row` is the stored `criterion_score` mapping — a `sqlite3.Row`, a `dict`,
    or a dataclass; the accessor is whichever the row answers to. A missing
    field reads as `None` ("not recorded"), which is exactly how the migration
    leaves every pre-existing row.
    """
    if isinstance(row, dict):
        return row.get(field)
    if hasattr(row, "keys"):
        try:
            return row[field] if field in row.keys() else None
        except (IndexError, KeyError):
            return None
    return getattr(row, field, None)


def _stored_signal(value: Any) -> int | None:
    """An integrity signal as the row stores it: 0 or 1, or NULL for "not measured"."""
    return None if value is None else int(bool(value))


# --- #93: the escalation policy (`FR-AGG-08/09`, §3.8) ----------------------------------------------
#
# The decision M-AGG returns to M-ORCH: whether a criterion score warrants a
# bigger panel, decided from OBSERVABLE signals — the row's interior band
# position, its recorded integrity inputs, the uncited mark, the criterion's
# override history, the distributional position against the package baseline —
# with model self-confidence one weighted input and structurally incapable of
# triggering alone (R22). The ENQUEUE the decision feeds is M-ORCH's
# (`FR-ORCH-09`): this module imports no orchestrator and offers no enqueue —
# the dependency stays one-way (`FR-AGG-14`).

#: A sentinel distinguishing "the row does not carry this field" from "the row
#: carries it as `None`". The escalation policy reads them differently — an
#: absent signal is no claim at all and its limb is skipped; a recorded `None`
#: is "measured, and inconclusive", which is adverse fail-closed wherever a
#: value is consumed (the `_signal_adverse` reading). The confidence surface
#: does not need the distinction (a row's recorded fields are always present,
#: `None`-valued or not); the escalation policy does, because it reads rows
#: both this module produced (all fields present) and stand-ins that name only
#: the fields their story varies.
_AGG_ABSENT = object()


def _row_field(row: Any, field: str) -> Any:
    """Read one field of a row, telling a missing field apart from a field that holds None (see
    `_AGG_ABSENT`).

    The same accessor forms `_row_value` accepts — a mapping, a `sqlite3.Row`,
    an object — returning the `_AGG_ABSENT` sentinel where `_row_value` would
    return `None`, so a caller can tell "the row says nothing about it" from
    "the row recorded that it was not measured".
    """
    if isinstance(row, dict):
        return row[field] if field in row else _AGG_ABSENT
    if hasattr(row, "keys"):
        try:
            return row[field] if field in row.keys() else _AGG_ABSENT
        except (IndexError, KeyError):
            return _AGG_ABSENT
    return getattr(row, field, _AGG_ABSENT)
