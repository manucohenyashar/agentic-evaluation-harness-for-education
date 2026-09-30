"""The errors M-REVIEW raises."""

from __future__ import annotations


# --- errors -----------------------------------------------------------------------------------------


class ReviewError(Exception):
    """Base class for the review module's refusals, so callers can catch the
    module's own failures without catching the package's too."""


class StaleReviewItemError(ReviewError):
    """An action arrived for a score row the queue no longer reflects
    (`CT-REVIEW-15`): the row was superseded by an escalation after this queue
    was built, and acting on the stale copy would overwrite a judgment somebody
    else already made. The message says to refresh the queue."""


class UnknownRunError(LookupError):
    """`open_review` was given a run id no store holds (FR-REVIEW-24). Nothing was created."""
