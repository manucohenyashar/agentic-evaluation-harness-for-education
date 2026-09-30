"""The errors M-ORCH raises."""

from __future__ import annotations


# --- errors ------------------------------------------------------------------------------------


class WorkLedgerError(Exception):
    """Base class for the orchestrator's own failures.

    Distinct from `store.StoreError`: the store reports persistence mechanics; this module
    owns the ledger's meaning and its callers distinguish the two.
    """


class CellPhaseError(WorkLedgerError, ValueError):
    """Raised when `mark_cell_phase` refuses (FR-ORCH-28, design 1.9 §3.9, #513). It is a
    `WorkLedgerError`, and also a `ValueError` so older callers that caught `ValueError` still
    work."""


class BrokenLineageError(WorkLedgerError):
    """A work unit's provenance does not reach a source document (#223, `FR-INGEST-01`).

    Raised by `Orchestrator.provenance` when the unit carries no submission, names a
    submission the cohort does not hold, or its submission has no document row. The join
    is refused rather than returned with a NULL `document_id`: a unit that cannot say
    which text it came from must not look traceable."""


class RunNotFoundError(WorkLedgerError):
    """No run has the id the caller gave. `resume()` with no arguments finds runs by itself, so an
    explicit `run_id` that matches nothing is a caller mistake and is reported rather than guessed
    at."""


class RunStateError(WorkLedgerError):
    """A control operation asked for a state change that FR-ORCH-25's state machine does not allow.

    `run.status` follows `pending → running → (paused ↔ running) → complete | failed`
    and nothing else: `start` from anything but `pending`, and the terminal states as
    sources, are refused with this error while the row's state stays exactly where it
    was — the refusal is named, never absorbed, and never a state change."""


class EscalationPlanError(WorkLedgerError):
    """An escalation plan this module refuses to build (FR-ORCH-10).

    The plan builder is a pure function and its refusals are part of its contract
    (`TC-ORCH-20` asserts the exact exception): a plan that does not widen the panel
    (an escalation to the same count, or a reduction) is not an escalation — enqueuing
    it would look like work while adding nothing, which is the silent-no-op shape.
    Even panels raise the subclass, `EvenEscalationPlanError`.
    """


class EvenEscalationPlanError(EscalationPlanError):
    """An escalation plan that would produce an even `judge_count` (FR-ORCH-10, R48).

    A two-way tie broken by rule is a coin flip presented as a judgement — the fairness
    rule the odd-panel requirement exists for (`CT-AGG-03`: `judge_count` is 0 or odd,
    enforced by CHECK at the write). This is the exact exception `TC-ORCH-20` asserts
    for plans producing 2 or 4 judges; the ledger-side CHECK (`det_score_state_columns`)
    is the backstop, this refusal is the front one.
    """
