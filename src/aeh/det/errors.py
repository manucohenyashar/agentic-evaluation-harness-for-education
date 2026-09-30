"""The errors M-DET raises. None of them is transient, so none is retried."""

from __future__ import annotations


# --- errors ----------------------------------------------------------------------------------------


class DeterministicError(Exception):
    """Base for every `M-DET` refusal. Nothing here is transient; no caller
    should retry (`CT-DET-10`), so there is deliberately no retry taxonomy."""


class MalformedSelectionRead(DeterministicError):
    """A region state outside the declared vocabularies — impossible from a
    migrated store, so it means a caller bypassed the store's CHECKs."""


class MalformedAnswerKey(DeterministicError):
    """A key that cannot be compared: empty, bad JSON, or shaped for a
    different select count. `FR-SETUP-03` makes a missing key a
    publication-time failure, so this cannot be raised by a published
    package — the guard exists to name the impossible situation loudly."""


class UndeclaredPartialCreditPolicy(DeterministicError):
    """A multi-select criterion scored with no declared policy (`TC-DET-03`
    cell 11). The module never infers one."""


class UnknownPartialCreditPolicy(DeterministicError):
    """A declared policy outside the closed vocabulary."""


class NotDeterministicCriterion(DeterministicError):
    """A criterion whose evaluation is not lookup reached the lookup module —
    an `M-ORCH` admission failure (`FR-ORCH-08`), never a scoring outcome."""


class UnknownCriterion(DeterministicError):
    """No such criterion in the named package version."""


class UnknownRun(DeterministicError):
    """No run row in any cohort ledger for the given run id."""


class UnknownCohort(DeterministicError):
    """No cohort ledger on file for the given cohort id. Opening the tier handle
    would CREATE the file, so the lookup checks the ledger directory first — a
    typo'd cohort id must be named, not silently materialized."""
