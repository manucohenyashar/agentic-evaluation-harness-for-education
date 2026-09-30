"""The errors M-AGG raises when a panel cannot be aggregated."""

from __future__ import annotations


# --- errors ----------------------------------------------------------------------------------------


class AggregateError(Exception):
    """Base class for the aggregation refusals, so callers can catch the module's
    own failures without catching the package's too."""


class EmptyVerdictsError(AggregateError, ValueError):
    """An aggregation over an empty verdict set (`CT-AGG-12`).

    A programming error, raised: it is never a zero, a lowest band, or a null
    score. Distinct from `EvenPanelError` because the design refuses the two on
    different clauses — an empty panel is a caller bug (`CT-AGG-12`), an even
    panel is a real panel the contract refuses to adjudicate (`FR-AGG-03`).
    """


class PanelCorrelationError(AggregateError, ValueError):
    """A panel carrying two or more decision-engine verdicts (Jev design delta FR-AGG-18,
    CT-AGG-22). The decision engine answers identical input near-identically, so two of its
    verdicts in one panel would manufacture unanimity (alpha near 1) rather than measure it.
    The seat rule (CT-JUDGE-21) makes this unreachable; the refusal is what makes a future
    break of that rule fail loudly instead of auto-accepting. Not retryable; nothing is written.
    """

    retryable = False


class EvenPanelError(AggregateError, ValueError):
    """An aggregation whose `judge_count` is even (`FR-AGG-03`).

    An even panel is a failed write, not a rounded verdict: the median ordinal of
    an even panel is a choice between two bands, and any tie-break would be a
    hidden thumb on the scale (HLD §9.9). The `criterion_score.judge_count` CHECK
    (`judge_count = 0 OR judge_count % 2 = 1`, det migration v9) enforces the same
    refusal at the store, which is what makes this a *failed write* rather than a
    convention (`CT-STORE-13`).
    """
