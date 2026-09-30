"""The errors M-SETUP raises."""

from __future__ import annotations


class SetupError(Exception):
    """Base for every `M-SETUP` failure — the taxonomy is siblings, never a chain.

    Storage-layer errors (`M-PKG`'s) are deliberately NOT wrapped: they propagate
    unchanged (`CT-SETUP-12`), because a caller branching on a data-layer refusal
    needs the data-layer type, and re-raising it under a setup name would break that
    branch."""

    retryable = False


class SetupOrderError(SetupError):
    """A setup operation ran out of order, or a blocking gate was not yet satisfied
    (`§4.2.1`'s sequence): confirming before proposing, proposing after confirming,
    publishing before both blocking gates hold. The refusal names the gate and the
    step that unblocks it — the console renders this verbatim."""

    retryable = False


class _ReplyError(Exception):
    """A model reply that did not parse into a valid proposal. PRIVATE on purpose:
    it is the retried failure (`CT-SETUP-12`), never surfaced — the caller sees the
    re-request, or the degraded proposal with the last error recorded in it."""
