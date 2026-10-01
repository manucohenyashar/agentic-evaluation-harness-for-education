"""The errors M-AGG raises when a panel cannot be aggregated."""

from __future__ import annotations


# --- errors ----------------------------------------------------------------------------------------


class AggregateError(Exception):
    """Base class for M-AGG's refusals, so a caller can catch these without also catching M-PKG's
    errors."""


class EmptyVerdictsError(AggregateError, ValueError):
    """Aggregation was asked to combine no verdicts at all (CT-AGG-12).

    A programming error, raised: it is never a zero, a lowest band, or a null
    score. Distinct from `EvenPanelError` because the design refuses the two on
    different clauses — an empty panel is a caller bug (`CT-AGG-12`), an even
    panel is a real panel the contract refuses to adjudicate (`FR-AGG-03`).
    """


class PanelCorrelationError(AggregateError, ValueError):
    """A panel held two or more decision-engine verdicts (FR-AGG-18, CT-AGG-22). The engine gives
    near-identical answers to identical input, so two of its verdicts would fake agreement instead
    of measuring it. The seat rule (CT-JUDGE-21) should make this impossible; this error makes a
    future break of that rule fail loudly. Not retryable, and nothing is written."""

    retryable = False


class EvenPanelError(AggregateError, ValueError):
    """Aggregation was given an even number of judges (FR-AGG-03).

    An even panel is a failed write, not a rounded verdict: the median ordinal of
    an even panel is a choice between two bands, and any tie-break would be a
    hidden thumb on the scale (HLD §9.9). The `criterion_score.judge_count` CHECK
    (`judge_count = 0 OR judge_count % 2 = 1`, det migration v9) enforces the same
    refusal at the store, which is what makes this a *failed write* rather than a
    convention (`CT-STORE-13`).
    """
