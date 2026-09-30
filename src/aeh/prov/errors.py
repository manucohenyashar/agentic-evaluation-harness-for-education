"""The errors M-PROV raises. Each one says whether a retry can help."""

from __future__ import annotations


# --- errors ----------------------------------------------------------------------------------


class ProviderError(Exception):
    """Base class for every M-PROV failure.

    A **neutral** base with siblings under it, never a chain. `CT-PROV-07` asserts one case per
    named error with the *exact* type, so if `ProviderUnavailableError` subclassed
    `TransportError` a `pytest.raises(TransportError)` would pass against the wrong failure and
    the retryability assertion underneath it would prove nothing.

    `retryable` is a class attribute rather than prose because `CT-PROV-07` asserts *"the
    retryability the clause claims"* per error rather than inferring it from observed behaviour
    — design §3.2 calls this one of the two most-missed breaking changes (RISK-34).
    """

    retryable = False


class TransportError(ProviderError):
    """The call did not reach the provider, or the connection failed mid-response.

    Retryable, and retried internally by #19's loop before it surfaces.
    """

    retryable = True


class RateLimitedError(ProviderError):
    """HTTP 429. Retryable after a wait: `Retry-After` when present, jittered back-off otherwise
    (FR-PROV-07)."""

    retryable = True


class MalformedResponseError(ProviderError):
    """The response could not be parsed into the expected structure.

    Retryable up to the retry budget; past it the *unit* quarantines and the run continues
    (`CT-PROV-07`, HLD §9.11 "fail the unit, never the run").
    """

    retryable = True


class MissingConfidenceError(MalformedResponseError):
    """A Jev build's choice or score answer has no `confidence` (missing or null).

    Design 1.8 (FR-PROV-19/20, CT-PROV-20): the confidence that decides whether Jev or the LLM
    grades a unit is Jev's own, so the harness never derives one for a Jev build. Absence is a
    property of the backend, not a transient fault, so it is **not retried**: it surfaces on
    the first send, spending no retry budget and billing no second call. It is still a
    `MalformedResponseError`, so every caller's fallback handling applies unchanged.
    """

    retryable = False


class ProviderUnavailableError(ProviderError):
    """Repeated 5xx responses or timeouts beyond the retry budget. The run cannot continue.

    Never retried, and never a trigger for substitution: `CT-PROV-08` lets a caller receiving
    this rely on the fact that nothing was silently graded by something else.
    """


class BuildChangedError(ProviderError):
    """A response reported a different served build from the one recorded at run start.

    Terminal for the run and explicitly **not** retried (`FR-PROV-05`), because a retry that
    happened to land on the original build would hide the fact that the panel changed
    mid-run. Raised by #20.
    """


class FixtureMissingError(ProviderError):
    """No recording matches the assembled request.

    Terminal for the test tier, and never a fall-through to a network call — that fall-through
    is what `CT-PROV-10` exists to forbid and what makes "no live call in CI" a fact rather
    than a hope.
    """


class RetentionPolicyError(ProviderError):
    """Zero-retention routing could not be confirmed for a panel member on `cloud-hosted`.

    Terminal, and fail-closed: an ambiguous or absent answer counts as unconfirmed
    (`FR-PROV-14`, `TC-PROV-17`). Declared here, raised by #21.
    """


class DecisionRequestError(ValueError):
    """A `DecisionRequest` that cannot be sent: a caller mistake caught when it is built (or in
    `validate_for`), before anything leaves the process. It is a `ValueError`, not a
    `ProviderError`, because a malformed request is not the provider's failure."""


class DecisionRequestRejectedError(ProviderError):
    """The engine refused the request (HTTP 400 or 422). Not retryable: the same bytes would be
    refused again (CT-PROV-20). M-JUDGE records it as a `rejected` pre-screen and falls back to the
    LLM path; repeated rejections point to a defect, which the `decision_requests_rejected` alert
    shows."""

    retryable = False
