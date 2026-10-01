"""Retrying: the policy, jittered back-off, `Retry-After`, the concurrency governor, the loop."""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from typing import Callable
from typing import Any

from .settings import (
    BACKOFF_BASE_MS_ENV,
    CONCURRENCY_FLOOR_ENV,
    DEFAULT_BACKOFF_BASE_MS,
    DEFAULT_CONCURRENCY_FLOOR,
    DEFAULT_RETRY_AFTER_CEILING_S,
    DEFAULT_RETRY_MAX,
    _float_env,
    _int_env,
    RETRY_AFTER_CEILING_S_ENV,
    RETRY_MAX_ENV,
)
from .errors import (
    MalformedResponseError,
    MissingConfidenceError,
    ProviderUnavailableError,
    RateLimitedError,
    TransportError,
)
from .transport import Clock, HttpRequest, HttpResponse, SystemClock, Transport, _wait
from .counters import BuildWatch, RunCountersTracker


@dataclass(frozen=True)
class RetryPolicy:
    """The retry budget, read from its knobs once and then fixed. A policy that re-read the
    environment on each call could not be tested reliably."""

    max_attempts: int = DEFAULT_RETRY_MAX
    backoff_base_ms: int = DEFAULT_BACKOFF_BASE_MS
    retry_after_ceiling_s: float = DEFAULT_RETRY_AFTER_CEILING_S

    @classmethod
    def from_environment(cls) -> "RetryPolicy":
        return cls(
            max_attempts=_int_env(RETRY_MAX_ENV, DEFAULT_RETRY_MAX),
            backoff_base_ms=_int_env(BACKOFF_BASE_MS_ENV, DEFAULT_BACKOFF_BASE_MS),
            retry_after_ceiling_s=_float_env(
                RETRY_AFTER_CEILING_S_ENV, DEFAULT_RETRY_AFTER_CEILING_S),
        )


def parse_retry_after(value: str | None, *, ceiling_s: float) -> float | None:
    """A `Retry-After` header as seconds to wait, or None when it must not be followed.

    `TC-PROV-11`'s boundary table: `0` is honoured (wait 0), `3600` is honoured **subject
    to the declared ceiling** — a provider saying "an hour" is unavailable for a school-day
    run, and the ceiling converts it to not-honoured so the jittered backoff and the
    budget's exhaustion decide instead. Absent → `None`. Malformed → `None`: a garbage
    header must not crash the dispatch, and it must not be guessed at either.

    HTTP-date `Retry-After` values are deliberately out of scope: the providers this
    module fronts return seconds (measured against `TC-PROV-20`'s nightly observation),
    and a date parser here would be code with no producer.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if not text.isdigit():
        return None
    seconds = float(text)
    if seconds > ceiling_s:
        return None
    return seconds


def jittered_backoff(base_ms: int, attempt: int, rng: random.Random) -> float:
    """Full-jitter back-off: a wait chosen uniformly between 0 and the exponential cap. Full jitter
    spreads out retries best when many callers are throttled at once. `rng` is passed in, so a test
    can fix the sequence."""
    cap_ms = base_ms * (2 ** min(attempt, 30))
    return rng.uniform(0, cap_ms) / 1000.0


class ConcurrencyGovernor:
    """Tracks calls in flight, and lowers the number allowed toward the configured floor on each
    429 (FR-PROV-07).

    `M-ORCH` owns the batch and the worker pool; this module owns the *signal*. The
    governor does not block anything — `reduce()` lowers the permitted in-flight count and
    `admits()` answers whether one more dispatch may start. The ratchet is one-way per
    incident: a successful dispatch after the cooldown lifts the count back by one, so a
    provider that recovered is used again rather than avoided forever.
    """

    def __init__(self, *, floor: int | None = None) -> None:
        self._floor = floor if floor is not None else _int_env(
            CONCURRENCY_FLOOR_ENV, DEFAULT_CONCURRENCY_FLOOR)
        self._permitted = self._floor * 8  # starts generous; 429s ratchet it toward the floor
        self._lock = threading.Lock()

    @property
    def permitted(self) -> int:
        with self._lock:
            return self._permitted

    @property
    def floor(self) -> int:
        return self._floor

    def admits(self, in_flight: int) -> bool:
        """Whether one more call may start at the current limit."""
        with self._lock:
            return in_flight < self._permitted

    def on_rate_limited(self) -> int:
        """Halve the limit, never below the floor, and return the new limit (CT-PROV-09)."""
        with self._lock:
            self._permitted = max(self._floor, self._permitted // 2)
            return self._permitted

    def on_success(self) -> int:
        """Raise the limit by one after a successful call, never above the starting limit."""
        with self._lock:
            self._permitted = min(self._floor * 8, self._permitted + 1)
            return self._permitted


# --- the one dispatch loop (FR-PROV-06/-07/-08) -------------------------------------------------


#: The attempt budget counts first attempts too, so `max_attempts - 1` is the retry count.
def dispatch_with_retries(
    transport: Transport,
    request_factory: Callable[[], HttpRequest],
    parse: Callable[[HttpResponse], Any],
    *,
    policy: RetryPolicy | None = None,
    clock: Clock | None = None,
    rng: random.Random | None = None,
    governor: ConcurrencyGovernor | None = None,
    counters: RunCountersTracker | None = None,
    build_watch: BuildWatch | None = None,
    model_key: str = "",
) -> Any:
    """Send one request through `transport`, retrying only the failures FR-PROV-06 allows.

    The loop, in the order the classification demands:

    1. `transport.send` — a raised `TransportError` is retryable (connection failed,
       timeout); any other error propagates untouched.
    2. The response's status: 429 → wait (`Retry-After` honoured, jittered backoff
       otherwise) and tell the governor; 5xx → retry; anything else → parse.
    3. `parse(response)` — a raised `MalformedResponseError` is retryable up to the budget;
       past it the error surfaces *as itself* so the caller can quarantine the unit.
    4. A parse that **succeeds returns immediately** — the attempt loop is exited at the
       first parsed response, which is the code shape of "one judgment, one sample". There
       is no flag, parameter or hook that re-enters the loop after a parse succeeds, and
       `FR-PROV-06`'s surface assertion (TC-PROV-10) holds because there is nothing to flip.

    Budget exhaustion on transport/5xx/429 raises `ProviderUnavailableError` with the last
    error chained — terminal for the run, and the reason no provider substitution exists
    downstream (`FR-PROV-08`): a caller that received this was told, loudly, that the panel
    member it asked for did not answer. Budget exhaustion on malformed responses surfaces
    `MalformedResponseError` as itself — the *unit* quarantines and the run continues.
    """
    resolved_policy = policy if policy is not None else RetryPolicy.from_environment()
    resolved_clock = clock if clock is not None else SystemClock()
    resolved_rng = rng if rng is not None else random.Random()
    last_error: Exception | None = None
    throttled = False

    for attempt in range(resolved_policy.max_attempts):
        try:
            response = transport.send(request_factory())
        except TransportError as error:
            last_error = error
        except (ConnectionResetError, TimeoutError, OSError) as error:
            # A raw connection failure — reset, timeout, unreachable host — is the
            # transport failure `FR-PROV-06` names, whatever exception class the platform
            # raises it through. `TC-PROV-10`'s decision table programs exactly this shape.
            last_error = TransportError(f"transport failure: {error}")
        else:
            if response.status == 429:
                wait = parse_retry_after(
                    response.headers.get("Retry-After"),
                    ceiling_s=resolved_policy.retry_after_ceiling_s,
                )
                if wait is None:
                    wait = jittered_backoff(
                        resolved_policy.backoff_base_ms, attempt, resolved_rng)
                if governor is not None:
                    governor.on_rate_limited()
                if counters is not None:
                    # A call throttled twice is ONE rate-limited call (FR-PROV-12, #538).
                    counters.on_rate_limited(wait, first_for_call=not throttled)
                throttled = True
                last_error = RateLimitedError(
                    f"HTTP 429 from the provider (attempt {attempt + 1})")
                _wait(resolved_clock, wait)
                if counters is not None and attempt > 0:
                    counters.on_retry()
                continue
            if 500 <= response.status <= 599:
                last_error = TransportError(
                    f"HTTP {response.status} from the provider (attempt {attempt + 1})")
                if counters is not None and attempt > 0:
                    counters.on_retry()
                _wait(resolved_clock, jittered_backoff(
                    resolved_policy.backoff_base_ms, attempt, resolved_rng))
                continue
            try:
                parsed = parse(response)
                if build_watch is not None:
                    build_watch.check(model_key, getattr(parsed, "resolved_build", ""))
                if counters is not None and attempt > 0:
                    counters.on_retry()
                return parsed
            except MissingConfidenceError:
                # Not transient (design 1.8): surfaces after this one send.
                if counters is not None and attempt > 0:
                    counters.on_retry()
                raise
            except MalformedResponseError as error:
                last_error = error
                _wait(resolved_clock, jittered_backoff(
                    resolved_policy.backoff_base_ms, attempt, resolved_rng))
                if counters is not None and attempt > 0:
                    counters.on_retry()
                continue
        if counters is not None and attempt > 0:
            counters.on_retry()
        _wait(resolved_clock, jittered_backoff(
            resolved_policy.backoff_base_ms, attempt, resolved_rng))

    if isinstance(last_error, MalformedResponseError):
        # Structural parse failures past the budget quarantine the unit — the caller sees
        # the malformed error itself, not an availability error, because the provider was
        # reachable and answering nonsense (CT-PROV-07's per-error state assertion).
        raise last_error
    raise ProviderUnavailableError(
        f"the provider did not answer within the retry budget "
        f"({resolved_policy.max_attempts} attempts, HARNESS_RETRY_MAX). No substitute "
        f"provider or model exists (FR-PROV-08) — the unit fails and the run continues."
    ) from last_error
