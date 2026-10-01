"""The errors M-DET raises. None of them is transient, so none is retried."""

from __future__ import annotations


# --- errors ----------------------------------------------------------------------------------------


class DeterministicError(Exception):
    """Base class for every M-DET refusal. None of them is transient, so none should be retried
    (CT-DET-10)."""


class MalformedSelectionRead(DeterministicError):
    """A region state outside the declared vocabularies. A migrated store's CHECK constraints
    prevent this, so it means a caller bypassed them."""


class MalformedAnswerKey(DeterministicError):
    """An answer key that cannot be compared: empty, not valid JSON, or the wrong shape for the
    question's select count. A published package always has a valid key (FR-SETUP-03), so this only
    names a situation that should be impossible."""


class UndeclaredPartialCreditPolicy(DeterministicError):
    """A multi-select criterion has no declared partial-credit policy (TC-DET-03). M-DET never
    guesses one."""


class UnknownPartialCreditPolicy(DeterministicError):
    """A declared partial-credit policy that is not in the allowed list."""


class NotDeterministicCriterion(DeterministicError):
    """A criterion that is not scored by lookup reached M-DET. That is an M-ORCH admission failure
    (FR-ORCH-08), never a scoring outcome."""


class UnknownCriterion(DeterministicError):
    """The named package version has no such criterion."""


class UnknownRun(DeterministicError):
    """No cohort ledger has a run with this id."""


class UnknownCohort(DeterministicError):
    """No cohort ledger file exists for this cohort id. Opening the tier handle would create the
    file, so the directory is checked first: a mistyped cohort id is reported, not silently
    created."""
