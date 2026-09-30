"""The errors M-SETUP raises."""

from __future__ import annotations


class SetupError(Exception):
    """Base class for every M-SETUP failure.

    Storage-layer errors (`M-PKG`'s) are deliberately NOT wrapped: they propagate
    unchanged (`CT-SETUP-12`), because a caller branching on a data-layer refusal
    needs the data-layer type, and re-raising it under a setup name would break that
    branch."""

    retryable = False


class SetupOrderError(SetupError):
    """A setup step ran out of order, or a blocking gate is not yet satisfied: confirming before
    proposing, proposing after confirming, or publishing before both gates pass. The message names
    the gate and the step that unblocks it; the console shows it as is."""

    retryable = False


class _ReplyError(Exception):
    """A model reply that did not parse into a valid proposal. It is retried and never shown to
    callers (CT-SETUP-12): the caller sees the re-request, or the fallback proposal with the last
    error recorded in it."""
