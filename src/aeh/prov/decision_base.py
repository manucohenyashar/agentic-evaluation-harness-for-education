"""`DecisionProvider`, and the HTTP machinery the live decision providers share."""

from __future__ import annotations

import dataclasses
import random
import threading
import json
import math
import os
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from aeh.conf import ConfigurationError, ModelRef

from .settings import _LOGGER
from .errors import (
    BuildChangedError,
    DecisionRequestRejectedError,
    MalformedResponseError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
    RetentionPolicyError,
    TransportError,
)
from .records import CallPlan, CostEstimate, RetentionReport
from .request_key import _MODEL_REF_FIELDS
from .transport import Clock, _DefaultTransport, HttpRequest, HttpResponse, SystemClock, Transport
from .retry import dispatch_with_retries, RetryPolicy
from .counters import BuildWatch, DecisionCounters, RunCountersTracker
from .decision_types import CHOICE_MAX_OPTIONS, Decision, DecisionCapabilities, DecisionRequest
from .decision_parsing import confidence_rule, decision_questions_document, parse_decision


@runtime_checkable
class DecisionProvider(Protocol):
    """FR-PROV-16. `decide` is synchronous and blocking; one call is one engine request."""

    def decide(self, request: DecisionRequest, model_ref: ModelRef) -> Decision: ...

    def decision_capabilities(self, model_ref: ModelRef) -> DecisionCapabilities: ...

    def estimate_cost(self, plan: CallPlan) -> CostEstimate: ...

    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport: ...


#: The declared limits of the fixture double: the widest published object model, so a request
#: a live backend accepts is never refused by its double.
_FIXTURE_DECISION_CAPABILITIES = DecisionCapabilities(
    max_context_tokens=32_000, max_choice_options=CHOICE_MAX_OPTIONS, max_questions=64,
    cost_per_input_token=None, deterministic=True)


#: Decision provider names and the stories that ship them. Named so an unshipped one refuses
#: with a reason rather than falling through to another backend (CT-PROV-21).
_UNSHIPPED_DECISION_PROVIDERS: dict[str, str] = {}


#: Every error a live decision provider can raise (FR-PROV-23), so the double can declare each.
_DECISION_ERRORS: dict[str, type[Exception]] = {
    cls.__name__: cls for cls in (
        ConfigurationError, DecisionRequestRejectedError, MalformedResponseError, TransportError, RateLimitedError,
        ProviderUnavailableError, BuildChangedError, RetentionPolicyError)
}


def _decision_request_record(request: DecisionRequest, model_ref: ModelRef) -> dict[str, Any]:
    return {"state": request.state, "questions": decision_questions_document(request),
            "model_ref": {name: getattr(model_ref, name) for name in _MODEL_REF_FIELDS}}


JEV_TIMEOUT_S_ENV = "HARNESS_JEV_TIMEOUT_S"


DEFAULT_JEV_TIMEOUT_S = 10.0


def _env_decimal(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = Decimal(raw.strip())
    except Exception:  # noqa: BLE001 - InvalidOperation and friends
        raise ConfigurationError(f"{name} must be a decimal number, got {raw!r}.") from None
    if not value.is_finite() or value < 0:
        raise ConfigurationError(f"{name} must be a non-negative decimal, got {raw!r}.")
    return value


def _env_positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        raise ConfigurationError(f"{name} must be a number of seconds, got {raw!r}.") from None
    if not math.isfinite(value) or value <= 0:
        raise ConfigurationError(f"{name} must be positive, got {raw!r}.")
    return value


def _safe_excerpt(body: Any, state: str) -> str:
    """The engine's own short error message, for diagnosis, only when it cannot carry student
    work (FR-PROV-23: no request bytes in an exception). Only `error.message`/`error.code`/
    `message` fields are read, never the raw body, so a JSON-escaped echo is compared as the
    string it decodes to. A message sharing any 12-character run with the state is dropped."""
    try:
        document = body if isinstance(body, dict) else json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return "(body withheld)"
    candidates = []
    if isinstance(document, dict):
        error = document.get("error")
        if isinstance(error, dict):
            candidates += [error.get("message"), error.get("code")]
        elif isinstance(error, str):
            candidates.append(error)
        candidates.append(document.get("message"))
    parts = [c for c in candidates if isinstance(c, (str, int)) and str(c).strip()]
    text = "; ".join(str(c) for c in parts)[:200]
    window = 12
    if not text or any(state[i:i + window] in text for i in range(0, max(len(state) - window + 1, 1))):
        return "(body withheld)"
    return text


def _decision_status_error(response: HttpResponse, state: str = "") -> ProviderError | ConfigurationError | None:
    """FR-PROV-23's non-retried statuses. 429 and 5xx never reach here: the shared loop retries
    them (and surfaces `ProviderUnavailableError` past the budget, CT-PROV-07)."""
    status = response.status
    if 200 <= status <= 299:
        return None
    excerpt = _safe_excerpt(response.body, state)
    if status in (400, 422):
        return DecisionRequestRejectedError(
            f"the decision engine rejected the request (HTTP {status}): {excerpt}")
    if status in (401, 403):
        return ConfigurationError(
            f"the decision engine refused the credentials (HTTP {status}); check the API key.")
    if status == 402:
        return ProviderUnavailableError(
            "the decision engine reports insufficient credits (HTTP 402); the run pauses rather "
            "than degrading (FR-PROV-23).")
    return MalformedResponseError(f"unexpected HTTP {status} from the decision engine: {excerpt}")


class _BaseDecisionProvider:
    """Shared HTTP machinery of the live decision providers: the one retry loop, the status map,
    validation through `parse_decision`, build watching, latency and the decision counters. Each
    subclass supplies its URL, headers, body and capabilities. Not public surface."""

    #: Whether calls are billed: a billed provider always returns a cost (measured, else derived).
    _billed = False

    def __init__(self, *, transport: Transport | None = None, clock: Clock | None = None,
                 rng: random.Random | None = None, counters: RunCountersTracker | None = None,
                 build_watch: BuildWatch | None = None, policy: RetryPolicy | None = None,
                 timeout_s: float = DEFAULT_JEV_TIMEOUT_S) -> None:
        self._transport = transport if transport is not None else _DefaultTransport(timeout_s)
        self._clock = clock if clock is not None else SystemClock()
        self._rng = rng if rng is not None else random.Random()
        self._counters = counters if counters is not None else RunCountersTracker()
        self._build_watch = build_watch if build_watch is not None else BuildWatch()
        self._policy = policy if policy is not None else RetryPolicy.from_environment()
        self._build_lock = threading.Lock()

    @property
    def decision_counters(self) -> DecisionCounters:
        return self._counters.decision_snapshot()

    def record_run_build(self, model_ref: ModelRef, served_build: str) -> None:
        """The run-start served build `BuildWatch` guards (FR-PROV-24). `served_build` is what
        the engine *reports* (`Decision.resolved_build`, e.g. `typesafe/jev-1.13-20260917`),
        never the requested wire slug — recording the slug would fail the first call."""
        self._build_watch.record(self._model_key(model_ref), served_build)

    @staticmethod
    def _model_key(model_ref: ModelRef) -> str:
        return f"decision:{model_ref.provider}:{model_ref.build_id}"

    def capabilities(self, model_ref: ModelRef) -> DecisionCapabilities:
        """Alias of `decision_capabilities` on the decision-only providers (FR-PROV-16)."""
        return self.decision_capabilities(model_ref)

    def decision_capabilities(self, model_ref: ModelRef) -> DecisionCapabilities:
        raise NotImplementedError

    def estimate_cost(self, plan: CallPlan) -> CostEstimate:
        """Input tokens only: decision output tokens are free (design §1.2)."""
        tokens_in = plan.calls * plan.tokens_in_per_call
        per_token = self._cost_per_input_token()
        return CostEstimate(calls=plan.calls, tokens_in=tokens_in, tokens_out=0,
                            cost=None if per_token is None else Decimal(tokens_in) * per_token)

    def _cost_per_input_token(self) -> Decimal | None:
        return None

    def _prepare_document(self, document: Any) -> Any:
        """The decoded response before validation; a provider may drop what it must not trust."""
        return document

    def _decide_http(self, request: DecisionRequest, model_ref: ModelRef, url: str,
                     headers: dict[str, str], body: bytes, fallback_build: str,
                     transport: Any = None) -> Decision:
        request.validate_for(self.decision_capabilities(model_ref))
        call_counters = RunCountersTracker()
        model_key = self._model_key(model_ref)
        started = self._clock.monotonic()

        def parse(response: HttpResponse) -> Decision:
            error = _decision_status_error(response, request.state)
            if error is not None:
                raise error
            raw = response.body
            if isinstance(raw, dict):
                document = raw
            else:
                try:
                    document = json.loads(bytes(raw).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise MalformedResponseError(f"the decision response is not JSON: {exc}") from exc
            document = self._prepare_document(document)
            usage = document.get("usage") if isinstance(document, dict) else None
            cost = None
            if self._billed and isinstance(usage, dict) and usage.get("cost") is not None:
                try:
                    cost = Decimal(str(usage["cost"]))
                except Exception as exc:  # noqa: BLE001
                    raise MalformedResponseError(f"usage.cost is not a decimal: {usage['cost']!r}") from exc
                if not cost.is_finite() or cost < 0:
                    # A NaN, infinite or negative cost would poison `decision_actual_cost` and
                    # the ceiling that reads it (TC-PROV-47).
                    raise MalformedResponseError(f"usage.cost must be a finite, non-negative decimal: {usage['cost']!r}")
            return parse_decision(document, request, fallback_build=fallback_build, cost=cost,
                                  rule=confidence_rule(model_ref))

        decision = dispatch_with_retries(
            transport if transport is not None else self._transport,
            lambda: HttpRequest("POST", url, headers, body), parse,
            policy=self._policy, clock=self._clock, rng=self._rng, counters=call_counters,
            build_watch=self._build_watch, model_key=model_key)
        with self._build_lock:
            # The first answer of the run fixes the served build unless run start recorded one;
            # any later difference raises BuildChangedError (FR-PROV-24). Under a lock so two
            # concurrent first calls served different builds cannot both pass.
            if self._build_watch._expected.get(model_key) is None:
                self._build_watch.record(model_key, decision.resolved_build)
            else:
                self._build_watch.check(model_key, decision.resolved_build)
        elapsed_ms = int(round((self._clock.monotonic() - started) * 1000))
        cost = decision.cost
        if self._billed and cost is None:
            per_token = self._cost_per_input_token()
            cost = None if per_token is None else Decimal(decision.tokens_in) * per_token
        if not self._billed:
            cost = None
        decision = dataclasses.replace(decision, latency_ms=elapsed_ms, cost=cost)
        snap = call_counters.snapshot()
        self._counters.on_decision(tokens_in=decision.tokens_in,
                                   transport_retries=snap.transport_retries,
                                   rate_limited=snap.rate_limited_calls > 0, cost=cost)
        _LOGGER.debug("decision call", extra={
            "model_ref": model_ref.build_id, "resolved_build": decision.resolved_build,
            "latency_ms": elapsed_ms, "tokens_in": decision.tokens_in,
            "questions": len(request.questions), "retry_count": snap.transport_retries})
        return decision
