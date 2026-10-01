"""The errors M-REVIEW raises."""

from __future__ import annotations


# --- errors -----------------------------------------------------------------------------------------


class ReviewError(Exception):
    """Base class for M-REVIEW's refusals, so callers can catch these without also catching M-PKG's
    errors."""


class StaleReviewItemError(ReviewError):
    """An action arrived for a score row the queue no longer reflects (CT-REVIEW-15): an escalation
    replaced the row after the queue was built, and acting on the old copy would overwrite someone
    else's judgment. The message says to refresh the queue."""


class UnknownRunError(LookupError):
    """`open_review` was given a run id that no store holds (FR-REVIEW-24). Nothing was created."""
