"""M-PROV: the only place the system talks to a model (design §3.2).

Every model call in the system goes through an `InferenceProvider` (text completions) or a
`DecisionProvider` (the Jev decision engine). No other module imports an HTTP client or a
provider SDK. Each call is identified by a hash over the fully assembled request, which is also
how the `RecordedFixtureProvider` finds its recording, so the whole system can run with no
network. Retries, rate limits, concurrency back-off, the run's build pinning and the run
counters are handled here, once, for every provider.

Files:
    settings.py         logger, fixture directory, retry and endpoint knobs
    errors.py           the errors this package raises, and which are retryable
    records.py          the payload, sampling, completion and capability types
    request_key.py      the canonical request encoding and its hash
    transport.py        one HTTP attempt (`Transport`), the clock, the default urllib transport
    retry.py            the retry policy, back-off, concurrency governor and `dispatch_with_retries`
    counters.py         the run counters and the build watch
    interface.py        `InferenceProvider`, the one completion interface
    live.py             the live completion providers (local server, OpenRouter)
    decision_types.py   decision requests, questions, answers and `Decision`
    decision_parsing.py parsing an engine reply, confidence rules and the decision request key
    decision_base.py    `DecisionProvider` and the shared HTTP machinery of live decision providers
    jev_openrouter.py   Jev on OpenRouter, through the TypeSafe SDK
    openjev_local.py    OpenJev and OpenJevSmall served on loopback
    fixtures.py         `RecordedFixtureProvider`, the network-free provider used by tests
    factories.py        choosing the provider a model reference names
"""

from __future__ import annotations

from aeh.conf import ConfigurationError, ModelRef

from .settings import (
    BACKOFF_BASE_MS_ENV,
    CONCURRENCY_FLOOR_ENV,
    DEFAULT_BACKOFF_BASE_MS,
    DEFAULT_CONCURRENCY_FLOOR,
    DEFAULT_FIXTURE_MAX_CONCURRENCY,
    DEFAULT_LOCAL_INFERENCE_BASE_URL,
    DEFAULT_OPENROUTER_BASE_URL,
    DEFAULT_RETRY_AFTER_CEILING_S,
    DEFAULT_RETRY_MAX,
    FIXTURE_DIR_ENV,
    FIXTURE_MAX_CONCURRENCY_ENV,
    LOCAL_INFERENCE_BASE_URL_ENV,
    LOGGER_NAME,
    OPENROUTER_API_KEY_ENV,
    OPENROUTER_BASE_URL_ENV,
    RETRY_AFTER_CEILING_S_ENV,
    RETRY_MAX_ENV,
)
from .errors import (
    BuildChangedError,
    DecisionRequestError,
    DecisionRequestRejectedError,
    FixtureMissingError,
    MalformedResponseError,
    MissingConfidenceError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
    RetentionPolicyError,
    TransportError,
)
from .records import (
    CallPlan,
    Capabilities,
    Completion,
    CostEstimate,
    PromptPayload,
    RetentionReport,
    SamplingParams,
)
from .request_key import KEY_SCHEME, payload_bytes, request_key
from .transport import Clock, _DefaultTransport, HttpRequest, HttpResponse, SystemClock, Transport
from .retry import (
    ConcurrencyGovernor,
    dispatch_with_retries,
    jittered_backoff,
    parse_retry_after,
    RetryPolicy,
)
from .counters import BuildWatch, COUNTER_NAMES, DecisionCounters, RunCounters, RunCountersTracker
from .interface import InferenceProvider
from .live import (
    LocalServerProvider,
    OpenRouterProvider,
    RETENTION_CONFIRMED_ANSWERS,
    ROUTING_PROHIBITED_KINDS,
)
from .decision_types import (
    CHOICE_MAX_OPTIONS,
    ChoiceAnswer,
    ChoiceQuestion,
    Decision,
    DECISION_FIXTURE_SCHEMA,
    DECISION_KEY_SCHEME,
    DECISION_MAX_QUESTIONS,
    DecisionAnswer,
    DecisionCapabilities,
    DecisionQuestion,
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
    PROBABILITY_SUM_TOLERANCE,
    SCORE_MAX_LEVELS,
    SCORE_MIN_LEVELS,
    ScoreAnswer,
    ScoreQuestion,
)
from .decision_parsing import (
    confidence_rule,
    CONFIDENCE_RULES,
    decision_questions_document,
    decision_request_key,
    derived_confidence,
    parse_decision,
)
from .decision_base import (
    _decision_status_error,
    DecisionProvider,
    DEFAULT_JEV_TIMEOUT_S,
    JEV_TIMEOUT_S_ENV,
)
from .jev_openrouter import (
    DEFAULT_JEV_COST_PER_MTOK_IN,
    DEFAULT_JEV_OPENROUTER_PROVIDER,
    DEFAULT_JEV_OPENROUTER_URL,
    JEV_COST_PER_MTOK_IN_ENV,
    JEV_OPENROUTER_PROVIDER_ENV,
    JEV_OPENROUTER_URL_ENV,
    JEV_SDK_EXTRA,
    JEV_SDK_PATH,
    JevOpenRouterProvider,
    TYPESAFE_SDK_LOGGER,
)
from .openjev_local import (
    DEFAULT_OPENJEV_BASE_URL,
    DEFAULT_OPENJEV_MODEL_NAME,
    DEFAULT_OPENJEV_SMALL_BASE_URL,
    DEFAULT_OPENJEV_SMALL_MODEL_NAME,
    DEFAULT_OPENJEV_VLLM_URL,
    OPENJEV_ALLOW_REMOTE_ENV,
    OPENJEV_BASE_URL_ENV,
    OPENJEV_BUILD_PROBE_EVERY_ENV,
    OPENJEV_MAX_CHOICE_OPTIONS,
    OPENJEV_MAX_CONTEXT_TOKENS,
    OPENJEV_MAX_MODEL_LEN_ENV,
    OPENJEV_MODEL_NAME_ENV,
    OPENJEV_SMALL_ALLOW_REMOTE_ENV,
    OPENJEV_SMALL_BASE_URL_ENV,
    OPENJEV_SMALL_BUILD_PROBE_EVERY_ENV,
    OPENJEV_SMALL_MAX_CHOICE_OPTIONS,
    OPENJEV_SMALL_MAX_STATE_TOKENS,
    OPENJEV_SMALL_MAX_STATE_TOKENS_ENV,
    OPENJEV_SMALL_MODEL_NAME_ENV,
    OPENJEV_SMALL_TIMEOUT_S_ENV,
    OPENJEV_TIMEOUT_S_ENV,
    OPENJEV_VLLM_URL_ENV,
    OpenJevLocalProvider,
    OpenJevSmallLocalProvider,
)
from .fixtures import FIXTURE_SCHEMA, RecordedFixtureProvider
from .factories import decision_provider_for, provider_for


__all__ = [
    "BuildChangedError",
    "CallPlan",
    "Capabilities",
    "Completion",
    "ConfigurationError",
    "CostEstimate",
    "DEFAULT_FIXTURE_MAX_CONCURRENCY",
    "FIXTURE_DIR_ENV",
    "BuildWatch",
    "Clock",
    "ConcurrencyGovernor",
    "LocalServerProvider",
    "OpenRouterProvider",
    "provider_for",
    "RunCounters",
    "HttpRequest",
    "HttpResponse",
    "RetryPolicy",
    "SystemClock",
    "Transport",
    "dispatch_with_retries",
    "jittered_backoff",
    "parse_retry_after",
    "FIXTURE_MAX_CONCURRENCY_ENV",
    "FIXTURE_SCHEMA",
    "FixtureMissingError",
    "InferenceProvider",
    "KEY_SCHEME",
    "LOGGER_NAME",
    "MalformedResponseError",
    "MissingConfidenceError",
    "confidence_rule",
    "payload_bytes",
    "PromptPayload",
    "ProviderError",
    "ProviderUnavailableError",
    "RateLimitedError",
    "RecordedFixtureProvider",
    "request_key",
    "RetentionPolicyError",
    "RetentionReport",
    "SamplingParams",
    "TransportError",
    # the decision surface (Jev design delta §3.1)
    "CHOICE_MAX_OPTIONS",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "DECISION_FIXTURE_SCHEMA",
    "DECISION_KEY_SCHEME",
    "Decision",
    "DecisionCapabilities",
    "DecisionCounters",
    "DecisionProvider",
    "DecisionRequest",
    "DecisionRequestError",
    "DecisionRequestRejectedError",
    "NoulAnswer",
    "NoulQuestion",
    "PROBABILITY_SUM_TOLERANCE",
    "SCORE_MAX_LEVELS",
    "SCORE_MIN_LEVELS",
    "ScoreAnswer",
    "ScoreQuestion",
    "decision_provider_for",
    "JevOpenRouterProvider",
    "OpenJevLocalProvider",
    "decision_questions_document",
    "decision_request_key",
    "derived_confidence",
    "parse_decision",
]
