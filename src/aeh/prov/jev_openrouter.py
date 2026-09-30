"""Jev on OpenRouter: the connected configuration's decision engine, via the TypeSafe SDK."""

from __future__ import annotations

import threading
import json
import logging
import os
import uuid
from collections.abc import Sequence
from typing import Callable
from decimal import Decimal
from typing import Any

from aeh.conf import ConfigurationError, ModelRef

from .settings import OPENROUTER_API_KEY_ENV
from .errors import ProviderUnavailableError, RetentionPolicyError, TransportError
from .records import RetentionReport
from .transport import HttpRequest, HttpResponse, Transport
from .live import _is_retention_confirmed
from .decision_types import (
    CHOICE_MAX_OPTIONS,
    Decision,
    DECISION_MAX_QUESTIONS,
    DecisionCapabilities,
    DecisionRequest,
)
from .decision_parsing import decision_questions_document
from .decision_base import (
    _BaseDecisionProvider,
    DEFAULT_JEV_TIMEOUT_S,
    _env_decimal,
    _env_positive_float,
    JEV_TIMEOUT_S_ENV,
)


# --- the live decision providers (FR-PROV-21…24, FR-PROV-28) --------------------------------------

JEV_OPENROUTER_URL_ENV = "HARNESS_JEV_OPENROUTER_URL"


#: Design 1.8 (ADR-28): the TypeSafe SDK's endpoint on OpenRouter. The SDK posts to
#: `<base_url>/v1/systemone`, so the knob must name a URL ending in that path.
DEFAULT_JEV_OPENROUTER_URL = "https://openrouter.ai/api/v1/systemone"


JEV_SDK_PATH = "/v1/systemone"


#: The pip extra that carries the SDK (FR-PROV-42); the core install never needs it (ADR-11).
JEV_SDK_EXTRA = "jev-cloud"


#: The SDK's logger. It logs request and response bodies at DEBUG (design §1.2), so the provider
#: filters out everything below WARNING on it (NFR-PROV-11).
TYPESAFE_SDK_LOGGER = "typesafe_sdk"


JEV_OPENROUTER_PROVIDER_ENV = "HARNESS_JEV_OPENROUTER_PROVIDER"


#: The upstream OpenRouter routes Jev to, pinned in `provider.order` (FR-PROV-11/21).
#: Assumption: TypeSafe serves its own model; the knob exists for when that is not so.
DEFAULT_JEV_OPENROUTER_PROVIDER = "typesafe"


JEV_COST_PER_MTOK_IN_ENV = "HARNESS_JEV_COST_PER_MTOK_IN"


DEFAULT_JEV_COST_PER_MTOK_IN = Decimal("0.042")


def _jev_wire_model(build_id: str) -> str:
    """The hosted router's model name for a pinned build, with the `openrouter/` prefix and the
    `@<pin>` suffix removed (FR-PROV-21). A floating alias is refused: the grader must not change
    during a run."""
    slug = build_id[len("openrouter/"):] if build_id.startswith("openrouter/") else build_id
    slug = slug.split("@", 1)[0]
    if not slug or slug.startswith("~") or slug.endswith("-latest") or ":latest" in slug:
        raise ConfigurationError(
            f"decision build {build_id!r} names a floating alias; pin a versioned Jev slug such "
            f"as 'openrouter/typesafe/jev-1.13@<pin>' (FR-PROV-21, FR-CONF-20).")
    return slug


class _BelowWarningFilter(logging.Filter):
    """Drops every `typesafe_sdk` log record below WARNING (NFR-PROV-11). It is a filter rather
    than a log level, so a later logging change cannot turn the SDK's debug logging of request
    bodies back on and put student text in a log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


def _load_typesafe_sdk() -> Any:
    """Import the TypeSafe SDK, only here and only when first needed (FR-PROV-39, CT-PROV-29).
    `import aeh.prov` never loads it, and nothing outside this file imports it."""
    try:
        import typesafe_sdk
    except ImportError:
        raise ConfigurationError(
            f"the openrouter-jev decision provider needs the TypeSafe SDK: install the "
            f"'{JEV_SDK_EXTRA}' extra (pip install '.[{JEV_SDK_EXTRA}]') (FR-PROV-42).") from None
    logger = logging.getLogger(TYPESAFE_SDK_LOGGER)
    if not any(isinstance(f, _BelowWarningFilter) for f in logger.filters):
        logger.addFilter(_BelowWarningFilter())
    return typesafe_sdk


def _sdk_response(status: int, headers: Any, body: Any) -> HttpResponse:
    """An SDK error's status, headers and body as the `HttpResponse` the shared retry loop reads.
    The SDK's HTTP layer lowercases header names, so `Retry-After` is restored under the name the
    loop reads."""
    plain = {str(k): str(v) for k, v in dict(headers or {}).items()}
    for name, value in list(plain.items()):
        if name.lower() == "retry-after":
            plain["Retry-After"] = value
    if isinstance(body, bytes):
        raw = body
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
    return HttpResponse(status, plain, raw)


def _transport_adapter(transport: Transport) -> Any:
    """An SDK transport whose `handle_request` calls the harness `Transport`, so every byte the SDK
    sends passes through the recordable seam (CT-PROV-10, FR-PROV-40). Errors from the harness
    transport pass through the SDK unchanged to the retry loop."""
    import httpx2

    class _Adapter(httpx2.BaseTransport):
        def handle_request(self, request: Any) -> Any:
            response = transport.send(HttpRequest(request.method, str(request.url),
                                                  {str(k): str(v) for k, v in request.headers.items()},
                                                  request.read()))
            body = response.body
            content = json.dumps(body).encode("utf-8") if isinstance(body, dict) else bytes(body)
            return httpx2.Response(response.status, headers=dict(response.headers or {}),
                                   content=content, request=request)

    return _Adapter()


class _SdkCall:
    """One SDK call, shaped as a `Transport` so the shared retry loop can call `send` once per
    attempt. It returns the raw response (the SDK decodes, but the raw bytes decide) and maps every
    SDK error (FR-PROV-41), raising the mapped error outside the handler so neither the SDK error
    nor the body bytes it carries can be reached from it."""

    def __init__(self, client: Any, sdk: Any, state: str, questions: Any, model: str, extra_body: Any) -> None:
        self._client, self._sdk = client, sdk
        self._args = (state, questions)
        self._model, self._extra = model, extra_body

    def send(self, _request: HttpRequest) -> HttpResponse:
        sdk = self._sdk
        mapped: Exception | None = None
        try:
            result = self._client.system_one(*self._args, model=self._model, extra_body=self._extra)
        except sdk.TypeSafeAPIResponseValidationError as error:
            # 1. A body failing the SDK's schema (it carries HTTP 200): handed back raw, so the
            # harness's own validation decides, including the no-retry missing-confidence rule.
            return _sdk_response(error.status, error.headers, error.body)
        except sdk.TypeSafeAPIConnectionError as error:
            # 2. Connection and timeout errors (the SDK's own; the harness transport's errors
            # pass through untouched).
            mapped = TransportError(f"the decision engine could not be reached: {type(error).__name__}")
        except sdk.TypeSafeAPIError as error:
            # 3. Every other HTTP failure by its status, through the loop and FR-PROV-23's table.
            # A status that table does not name is unavailability, never a leaked SDK type.
            if error.status in (400, 401, 402, 403, 422, 429) or 500 <= error.status <= 599:
                return _sdk_response(error.status, error.headers, error.body)
            if error.status == 408:
                # OpenRouter's request timeout: a transport failure (FR-PROV-23), retried.
                mapped = TransportError("the decision engine timed out the request (HTTP 408)")
            else:
                mapped = ProviderUnavailableError(
                    f"unexpected HTTP {error.status} from the decision engine (FR-PROV-41).")
        except sdk.TypeSafeError as error:
            raise ProviderUnavailableError(
                f"the TypeSafe SDK failed: {type(error).__name__} (FR-PROV-41).") from error
        if mapped is not None:
            raise mapped
        raw = result.raw_http_response
        return HttpResponse(raw.status_code, {str(k): str(v) for k, v in raw.headers.items()}, raw.content)


class JevOpenRouterProvider(_BaseDecisionProvider):
    """Jev served through the hosted router: the decision engine of the connected configuration
    (FR-PROV-21).

    Design 1.8 (FR-PROV-38…43, ADR-28): the request is sent through the TypeSafe SDK to
    OpenRouter's `/api/v1/systemone`, for a pinned Jev build, with the upstream pinned,
    fallbacks disabled and zero-retention routing requested. The SDK stays inside this class:
    its HTTP goes through the injected `Transport` (an `httpx2` transport adapter), its retries
    are off so the shared loop owns them, every kept value is read from the raw response body,
    and every SDK error is mapped to a harness error. Separate from the local providers by
    design (user directive); it shares only `_BaseDecisionProvider`."""

    _billed = True

    def __init__(self, *, api_key: str | None = None, url: str | None = None,
                 session_id: str | None = None,
                 retention_answers: Callable[[str], str] | None = None, **seams: Any) -> None:
        seams.setdefault("timeout_s", _env_positive_float(JEV_TIMEOUT_S_ENV, DEFAULT_JEV_TIMEOUT_S))
        super().__init__(**seams)
        raw_key = api_key if api_key is not None else os.environ.get(OPENROUTER_API_KEY_ENV)
        # Stripped here, so a pasted key with a trailing newline or blanks is treated as the key
        # it is, and an all-blank one as absent (never handed to the SDK to reject).
        self._api_key = raw_key.strip() if isinstance(raw_key, str) else raw_key
        self._url = url if url is not None else (os.environ.get(JEV_OPENROUTER_URL_ENV) or DEFAULT_JEV_OPENROUTER_URL)
        if not self._url.rstrip("/").endswith(JEV_SDK_PATH):
            raise ConfigurationError(
                f"{JEV_OPENROUTER_URL_ENV} must name the TypeSafe SDK endpoint, a URL ending in "
                f"{JEV_SDK_PATH} (default {DEFAULT_JEV_OPENROUTER_URL}); got {self._url!r} (ADR-28).")
        self._sdk = _load_typesafe_sdk()
        self._timeout_s = float(seams["timeout_s"])
        self._client: Any = None
        self._client_lock = threading.Lock()
        self._unreported = threading.local()
        self._upstream = os.environ.get(JEV_OPENROUTER_PROVIDER_ENV) or DEFAULT_JEV_OPENROUTER_PROVIDER
        # FR-PROV-21: every request carries a session id. The composer passes the run id; a
        # provider built without one groups its own lifetime's calls under a fresh id.
        if session_id is not None and (not isinstance(session_id, str) or not 0 < len(session_id) <= 256):
            raise ConfigurationError("session_id must be a non-empty string of at most 256 characters.")
        self._session_id = session_id if session_id is not None else uuid.uuid4().hex
        self._retention_answers = retention_answers
        self._retention_gate_failed = False

    def _cost_per_input_token(self) -> Decimal:
        return _env_decimal(JEV_COST_PER_MTOK_IN_ENV, DEFAULT_JEV_COST_PER_MTOK_IN) / Decimal(1_000_000)

    def decision_capabilities(self, model_ref: ModelRef) -> DecisionCapabilities:
        return DecisionCapabilities(max_context_tokens=32_000, max_choice_options=CHOICE_MAX_OPTIONS,
                                    max_questions=DECISION_MAX_QUESTIONS,
                                    cost_per_input_token=self._cost_per_input_token(), deterministic=True)

    def decide(self, request: DecisionRequest, model_ref: ModelRef) -> Decision:
        if not isinstance(request, DecisionRequest):
            raise TypeError(f"decide takes a DecisionRequest, got {type(request).__name__}")
        if self._retention_gate_failed:
            raise RetentionPolicyError(
                "zero-retention routing was not confirmed for the decision model at run start; "
                "nothing has been or will be dispatched (FR-PROV-28).")
        wire_model = _jev_wire_model(model_ref.build_id)
        if not self._api_key:
            raise ConfigurationError(
                f"JevOpenRouterProvider needs an API key: pass api_key= or set {OPENROUTER_API_KEY_ENV}.")
        extra_body = {
            "provider": {"order": [self._upstream], "allow_fallbacks": False,
                         "data_collection": "deny", "zdr": True},
            "session_id": self._session_id,
        }
        call = _SdkCall(self._sdk_client(wire_model), self._sdk, request.state,
                        decision_questions_document(request), wire_model, extra_body)
        self._unreported.flag = False
        # The shared loop drives the SDK call as its transport: one SDK call per attempt, our
        # retry budget, `Retry-After`, status table and raw-body validation unchanged. Passed per
        # call, never swapped onto `self`, so concurrent `decide`s cannot cross.
        decision = self._decide_http(request, model_ref, self._url, {}, b"", fallback_build=wire_model,
                                     transport=call)
        if self._unreported.flag:
            self._counters.on_decision_provider_unreported()
        return decision

    def _sdk_client(self, wire_model: str) -> Any:
        """One SDK client per provider, with every argument explicit, so the SDK's own environment
        variables can never redirect the request, change the key, or select a floating model
        (FR-PROV-38). Its HTTP goes through the injected `Transport`, and its own retries are off
        (FR-PROV-40)."""
        with self._client_lock:
            if self._client is None:
                base_url = self._url.rstrip("/")[: -len(JEV_SDK_PATH)]
                refused: str | None = None
                try:
                    self._client = self._sdk.TypeSafeClient(
                        api_key=self._api_key, base_url=base_url, model=wire_model,
                        retry=self._sdk.RetryPolicy(max_retries=0), timeout=self._timeout_s,
                        transport=_transport_adapter(self._transport))
                except self._sdk.TypeSafeError as error:
                    # The SDK rejects a malformed key or timeout. Its message names the SDK's
                    # own environment variable, which never applies here (FR-PROV-38), so the
                    # refusal is restated, and raised outside the handler so no SDK error is
                    # reachable from it (CT-PROV-29).
                    refused = type(error).__name__
                if refused is not None:
                    raise ConfigurationError(
                        f"the OpenRouter API key or HARNESS_JEV_TIMEOUT_S was refused by the TypeSafe "
                        f"SDK ({refused}); check {OPENROUTER_API_KEY_ENV} (printable ASCII, no spaces).")
            return self._client

    def _prepare_document(self, document: Any) -> Any:
        """The per-call routing check on the raw response (FR-PROV-43): a response served by an
        upstream outside the pinned list raises `RetentionPolicyError`, which is final and never
        retried. A missing `provider` field is counted as unreported, not refused."""
        if isinstance(document, dict):
            served = document.get("provider")
            # Per attempt: only the attempt whose body is accepted decides the count.
            self._unreported.flag = served is None
            if served is None:
                pass
            elif str(served).strip().lower() != self._upstream.strip().lower():
                raise RetentionPolicyError(
                    f"the decision response was served by {served!r}, outside the pinned provider "
                    f"order [{self._upstream!r}]; zero-retention routing is not assured (FR-PROV-43).")
        return document

    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport:
        """Confirm zero retention for the decision model, refusing when it cannot be confirmed, as
        `OpenRouterProvider.verify_retention` does (FR-PROV-28). An unconfirmed model raises and
        makes `decide` refuse."""
        confirmed: list[ModelRef] = []
        unconfirmed: list[ModelRef] = []
        for ref in model_refs:
            if self._retention_answers is not None:
                try:
                    answer = self._retention_answers(ref.build_id)
                except (TransportError, ProviderUnavailableError, OSError) as error:
                    # An unreachable confirmation source is an unconfirmed model, and it must
                    # arm the refusal like any other: a raise here that escaped would leave
                    # `decide` open (TC-PROV-33, RISK-64).
                    answer = f"unreachable: {error}"
            else:
                answer = None  # no confirmation source: unconfirmed, fail-closed
            (confirmed if _is_retention_confirmed(answer) else unconfirmed).append(ref)
        if unconfirmed:
            self._retention_gate_failed = True
            raise RetentionPolicyError(
                f"zero-retention routing unconfirmed for decision model(s): "
                f"{'; '.join(r.build_id for r in unconfirmed)}. The run does not start (FR-PROV-28).")
        return RetentionReport(confirmed=tuple(confirmed), unconfirmed=())
