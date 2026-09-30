"""The live completion providers: an on-premise OpenAI-compatible server, and OpenRouter."""

from __future__ import annotations

import dataclasses
import random
import os
from collections.abc import Sequence
from typing import Callable
from decimal import Decimal
from typing import Any

from aeh.conf import ConfigurationError, ModelRef

from .settings import (
    DEFAULT_LOCAL_INFERENCE_BASE_URL,
    DEFAULT_OPENROUTER_BASE_URL,
    LOCAL_INFERENCE_BASE_URL_ENV,
    _LOGGER,
    OPENROUTER_API_KEY_ENV,
    OPENROUTER_BASE_URL_ENV,
)
from .errors import MalformedResponseError, RetentionPolicyError, TransportError
from .records import (
    CallPlan,
    Capabilities,
    Completion,
    CostEstimate,
    PromptPayload,
    RetentionReport,
    SamplingParams,
)
from .transport import Clock, _DefaultTransport, HttpRequest, HttpResponse, SystemClock, Transport
from .retry import ConcurrencyGovernor, dispatch_with_retries, RetryPolicy
from .counters import BuildWatch, RunCounters, RunCountersTracker


#: The answers `verify_retention` treats as a zero-retention confirmation. Deliberately a
#: strict, closed set: the wire shape of a confirmation is design §3.2's open TBD, and the
#: seam abstracts it — but the *evaluation* must be fail-closed regardless (`TC-PROV-17`):
#: absent, empty, hedged ("mostly", "unknown"), or verbose answers are unconfirmed. This
#: set is what TC-PROV-20's nightly observation revisits, not a guessed response schema.
RETENTION_CONFIRMED_ANSWERS: frozenset[str] = frozenset(
    {"yes", "true", "confirmed", "zero-retention"}
)


def _is_retention_confirmed(answer: object) -> bool:
    """Is this retention answer an explicit zero-retention confirmation? **Fail-closed.**

    `True` (a boolean) confirms; a string confirms only if it is exactly one of
    `RETENTION_CONFIRMED_ANSWERS`; everything else — `False`, `None`, empty, hedged,
    verbose — is unconfirmed. `bool(answer)` would read "unknown" as a yes and pass every
    exception-type assertion while disclosing a cohort's work (the exact bug `SEC-03`'s
    parametrization exists to catch)."""
    if isinstance(answer, bool):
        return answer
    if not isinstance(answer, str):
        return False
    return answer.strip().lower() in RETENTION_CONFIRMED_ANSWERS


#: Scoring/extraction criteria are the calls `FR-PROV-11` forbids price-based routing on:
#: the cheapest path must never decide a judgment. Extraction joins scoring because a
#: transcription that fed a judgment is part of the judgment's evidence.
ROUTING_PROHIBITED_KINDS: frozenset[str] = frozenset({"scoring", "extraction"})


# --- the live implementations (FR-PROV-03, FR-PROV-14, FR-PROV-15) ------------------------------
#
# Both providers share one shape: an OpenAI-compatible chat-completions request, dispatched
# through `dispatch_with_retries` over an injected `Transport`, parsed into a `Completion`.
# LiteLLM (ADR-2) is the deployment-time shim; through the `Transport` seam the wire shape
# is plain and the tests program responses without stubbing the provider.
#
# **Substitutability** (`FR-PROV-03`): a caller written against one implementation runs
# unchanged against the others with only `RunConfig` differing. The constructors below take
# the same seam arguments (`transport`, `clock`, `rng`, `counters`, `build_watch`,
# `governor`, `retention_answers`, `on_dispatch`) defaulting to the real ones, behaviour-
# neutrally — `FR-PROV-15`.


def _openai_body(prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams) -> bytes:
    """The dispatched body. The payload is carried **unchanged**: every `(name, value)`
    field appears verbatim, in declaration order — no added field, no reordering, no
    templating (`FR-PROV-13`, `TC-PROV-03`'s differential oracle). NFR-PROV-04: identity
    reaches the body as the caller's `student_ref` field values (the roster mapping happened
    in `M-INGEST`); no student name exists anywhere in the payload to leak."""
    import json

    body = {
        "model": model_ref.build_id,
        "prompt": {"fields": [[name, value] for name, value in prompt.fields]},
        "temperature": params.temperature,
    }
    if params.seed is not None:
        body["seed"] = params.seed
    if params.max_tokens is not None:
        body["max_tokens"] = params.max_tokens
    if params.top_p is not None:
        body["top_p"] = params.top_p
    if params.stop:
        body["stop"] = list(params.stop)
    return json.dumps(body, ensure_ascii=False, sort_keys=False).encode("utf-8")


def _parse_completion(response: HttpResponse, model_ref: ModelRef) -> "Completion":
    """OpenAI-shaped response to a `Completion`, or `MalformedResponseError`.

    The resolved build is what the response *reported* (the body's `model` field, falling
    back to the `x-served-build` header) — never the requested ref (`FR-PROV-04`)."""
    import json

    body = response.body
    if isinstance(body, dict):
        document = body  # a programmed transport may hand the parsed document straight over
    else:
        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MalformedResponseError(
                f"the response body is not valid JSON: {error}"
            ) from error
    if not isinstance(document, dict):
        raise MalformedResponseError("the response body is JSON but not an object")
    usage = document.get("usage") or {}
    if not isinstance(usage, dict):
        raise MalformedResponseError("the response 'usage' is not an object")
    cached = usage.get("cached_prefix_tokens")
    if cached is None and isinstance(usage.get("prompt_tokens_details"), dict):
        cached = usage["prompt_tokens_details"].get("cached_tokens", 0)
    cost: Decimal | None = None
    if usage.get("cost") is not None:
        # A backend that reports what it billed is believed — *measured*, not derived
        # (CT-PROV-03: on cloud, cost is the measured fact beside the usage). OpenRouter's
        # usage carries it; a value that will not parse is a structurally broken response,
        # not a missing one, and belongs to the taxonomy.
        try:
            cost = Decimal(str(usage["cost"]))
        except Exception as error:  # noqa: BLE001 — Decimal raises ValueError/TypeError/InvalidOperation
            raise MalformedResponseError(
                f"the response 'usage.cost' is not a decimal: {usage['cost']!r}"
            ) from error
    if "choices" in document:
        # An OpenAI-shaped response: the completion text hides in the first choice.
        choices = document["choices"]
        if not isinstance(choices, list) or not choices:
            raise MalformedResponseError("the response carries no choices")
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        text = message.get("content")
        if not isinstance(text, str):
            raise MalformedResponseError(
                "the first choice carries no message content string")
    elif "text" in document:
        # The module's own flat shape — the one `TC-PROV-18`'s programmed transport speaks:
        # text verbatim, usage beside it, the served build in `model`.
        text = document["text"]
        if not isinstance(text, str):
            raise MalformedResponseError("the response 'text' is not a string")
    else:
        raise MalformedResponseError(
            "the response carries neither a choices list nor a text field"
        )
    served = document.get("model")
    if not isinstance(served, str) or not served:
        served = response.headers.get("x-served-build", model_ref.build_id)

    return Completion(
        text=text,
        tokens_in=int(usage.get("prompt_tokens", 0)),
        tokens_out=int(usage.get("completion_tokens", 0)),
        latency_ms=0,
        resolved_build=served,
        cached_prefix_tokens=int(cached or 0),
        cost=cost,
    )


class _BaseLiveProvider:
    """The shared dispatch machinery of the two live providers.

    Not part of the public surface (`CT-PROV-01` closes it): the two classes below are the
    implementations, and this class exists so the request/parse/display logic is written
    once. Every constructor argument is `FR-PROV-15`'s seam, defaulting to the real thing,
    behaviour-neutrally."""

    def __init__(
        self, *,
        transport: Transport | None = None,
        clock: Clock | None = None,
        rng: random.Random | None = None,
        counters: RunCountersTracker | None = None,
        build_watch: BuildWatch | None = None,
        governor: ConcurrencyGovernor | None = None,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._transport = transport if transport is not None else _DefaultTransport()
        self._clock = clock if clock is not None else SystemClock()
        self._rng = rng if rng is not None else random.Random()
        self._counters = counters if counters is not None else RunCountersTracker()
        self._build_watch = build_watch if build_watch is not None else BuildWatch()
        self._governor = governor
        self._policy = policy if policy is not None else RetryPolicy.from_environment()

    @property
    def counters(self) -> RunCounters:
        """`CT-PROV-11`'s surface: the six names, for `M-ORCH` to persist."""
        return self._counters.snapshot()

    def record_run_build(self, model_key: str, build_id: str) -> None:
        """The run-start build record `BuildWatch` guards (`FR-PROV-05`)."""
        self._build_watch.record(model_key, build_id)

    def _dispatch(self, model_ref: ModelRef, prompt: PromptPayload,
                  params: SamplingParams) -> "Completion":
        body = _openai_body(prompt, model_ref, params)
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        model_key = f"{model_ref.provider}:{model_ref.build_id}"
        retries_before = self._counters.snapshot().transport_retries
        started = self._clock.monotonic()
        completion = dispatch_with_retries(
            self._transport,
            lambda: HttpRequest("POST", self._url_for(model_ref), headers, body),
            lambda response: _parse_completion(response, model_ref),
            policy=self._policy, clock=self._clock, rng=self._rng,
            governor=self._governor, counters=self._counters,
            build_watch=self._build_watch, model_key=model_key,
        )
        # Latency is measured, not echoed: FR-PROV-01 returns it as data, the per-call
        # DEBUG line reports it (CT-PROV-14), and a hardcoded 0 would have the nightly
        # describe a server that answers in no time at all. Measured through the clock
        # seam, so an injected clock makes it exact and the default clock makes it real.
        elapsed_ms = int(round((self._clock.monotonic() - started) * 1000))
        if self._billed:
            if completion.cost is None:
                # CT-PROV-03: cost is null on edge-local and fixture — a billed backend
                # answers with the measured fact. When the wire reported no cost, the
                # declared per-token rates turn the measured usage into the per-call cost:
                # derived, and derived from *declared* figures, which is why the estimate
                # and the actuals can never disagree about the price sheet.
                completion = dataclasses.replace(
                    completion,
                    cost=(Decimal(completion.tokens_in) * self._cost_per_token_in
                          + Decimal(completion.tokens_out) * self._cost_per_token_out),
                )
        elif completion.cost is not None:
            # The unbilled side is enforced, not assumed: a local server (or a proxy in
            # front of one) that reports a cost in its usage would otherwise put a
            # non-null cost on an edge-local completion — the clause violation the
            # fixture refuses at record and at read.
            completion = dataclasses.replace(completion, cost=None)
        completion = dataclasses.replace(completion, latency_ms=elapsed_ms)
        self._counters.on_usage(
            completion.tokens_in, completion.tokens_out, completion.cached_prefix_tokens)
        # CT-PROV-14's per-call DEBUG line, on the live path exactly as the fixture path
        # emits it: metadata only, never a payload value (`CT-PROV-13`).
        _LOGGER.debug(
            "provider call",
            extra={
                "model_ref": model_ref.build_id,
                "resolved_build": completion.resolved_build,
                "latency_ms": completion.latency_ms,
                "tokens_in": completion.tokens_in,
                "tokens_out": completion.tokens_out,
                "retry_count": self._counters.snapshot().transport_retries - retries_before,
            },
        )
        return completion

    def estimate_cost(self, plan: CallPlan) -> CostEstimate:
        """`FR-PROV-09`: a pure function of the plan and the declared per-token costs.
        Dispatches nothing — the estimator reads the plan's call count and per-call token
        budgets against the implementation's own declared rate (`TC-PROV-12`'s
        hand-computed reference); the run's *actual* cost accumulates in the counters."""
        per_call_cost = (Decimal(plan.tokens_in_per_call) * self._cost_per_token_in
                         + Decimal(plan.tokens_out_per_call) * self._cost_per_token_out)
        return CostEstimate(
            calls=plan.calls,
            tokens_in=plan.tokens_in_per_call * plan.calls,
            tokens_out=plan.tokens_out_per_call * plan.calls,
            cost=per_call_cost * plan.calls,
        )

    def _url_for(self, model_ref: ModelRef) -> str:
        raise NotImplementedError


class LocalServerProvider(_BaseLiveProvider):
    """The on-premise OpenAI-compatible server (`FR-PROV-11`'s first implementation).

    Retention is trivially confirmed — the model runs on school hardware, and no bytes
    leave the building. `verify_retention` answers from that fact, not from a network
    call."""

    #: Edge-local: nothing is billed, so `Completion.cost` is null (`CT-PROV-03`).
    _billed = False

    def __init__(self, *, base_url: str | None = None, api_key: str = "",
                 **seams: Any) -> None:
        super().__init__(**seams)
        self._base_url = (
            base_url if base_url is not None
            else os.environ.get(LOCAL_INFERENCE_BASE_URL_ENV,
                                DEFAULT_LOCAL_INFERENCE_BASE_URL))
        self._api_key = api_key
        self._cost_per_token_in = __import__("decimal").Decimal("0")
        self._cost_per_token_out = __import__("decimal").Decimal("0")

    def _url_for(self, model_ref: ModelRef) -> str:
        return f"{self._base_url}/chat/completions"

    def complete(
        self, prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams
    ) -> Completion:
        return self._dispatch(model_ref, prompt, params)

    def capabilities(self, model_ref: ModelRef) -> Capabilities:
        """Declared statically (`CT-PROV-04`): no network call during capabilities()."""
        import decimal

        return Capabilities(
            supports_seed=True, supports_prefix_cache=False, max_concurrency=1,
            deterministic_at_temperature_zero=True,
            cost_per_token=(decimal.Decimal("0"), decimal.Decimal("0")),
        )

    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport:
        """Local inference: nothing is dispatched off the machine, so zero-retention holds
        for every panel member by construction (`CT-PROV-09`'s report shape).

        The report carries the panel members themselves, in the same shape
        `OpenRouterProvider` returns — the report is contract, and a caller that consumes
        `report.confirmed` must not receive display strings from one implementation and
        `ModelRef`s from another (`FR-PROV-03`: the same caller runs unchanged).
        """
        return RetentionReport(confirmed=tuple(model_refs), unconfirmed=())


class OpenRouterProvider(_BaseLiveProvider):
    """The OpenRouter hosted provider, with the retention gate and the routing prohibition
    (`FR-PROV-11`, `FR-PROV-14`).

    `retention_answers` is `FR-PROV-15`'s seam for the open TBD: the wire shape of a
    zero-retention confirmation is unknown, so the gate takes a *source of answers*
    (callable: model key → answer string) and evaluates fail-closed. `on_dispatch` observes
    every dispatch the moment it happens — the hook a run-start retention gate and an
    operator's log both read."""

    #: Cloud-hosted: calls are billed, so `Completion.cost` is a measured or derived
    #: Decimal — never null, never zero-by-default (`CT-PROV-03`).
    _billed = True

    def __init__(
        self, *,
        base_url: str | None = None, api_key: str | None = None,
        retention_answers: Callable[[str], str] | None = None,
        on_dispatch: Callable[[HttpRequest], None] | None = None,
        **seams: Any,
    ) -> None:
        super().__init__(**seams)
        self._base_url = (
            base_url if base_url is not None
            else os.environ.get(OPENROUTER_BASE_URL_ENV, DEFAULT_OPENROUTER_BASE_URL))
        # The key is enforced at DISPATCH, not construction: the retention gate makes no
        # model call, and a run that never leaves the gate (FR-PROV-14 refusal) is not a
        # configuration error — it is the gate working.
        self._api_key = (
            api_key if api_key is not None
            else os.environ.get(OPENROUTER_API_KEY_ENV))
        self._retention_answers = retention_answers
        self._on_dispatch = on_dispatch
        self._retention_gate_failed = False
        import decimal

        self._cost_per_token_in = decimal.Decimal("0.000001")
        self._cost_per_token_out = decimal.Decimal("0.000002")

    def _url_for(self, model_ref: ModelRef) -> str:
        return f"{self._base_url}/chat/completions"

    def complete(
        self, prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams
    ) -> Completion:
        if self._retention_gate_failed:
            # A caller that ignored verify_retention's raise still cannot reach the
            # provider (CT-PROV-13): the gate's refusal outlives the exception.
            raise RetentionPolicyError(
                "zero-retention routing was not confirmed for this panel at run start; "
                "the gate refused and no payload has been or will be dispatched."
            )
        if self._api_key is None:
            raise ConfigurationError(
                "OpenRouterProvider needs an API key: pass api_key= or set "
                f"{OPENROUTER_API_KEY_ENV}. A provider that cannot authenticate would fail "
                "every dispatch with a 401 the retry loop classifies as unavailable, "
                "quarantining the whole run for a configuration mistake."
            )
        request = HttpRequest(
            "POST", self._url_for(model_ref),
            {"Authorization": f"Bearer {self._api_key}",
             "Content-Type": "application/json"},
            _openai_body(prompt, model_ref, params))
        if self._on_dispatch is not None:
            self._on_dispatch(request)
        return self._dispatch(model_ref, prompt, params)

    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport:
        """Zero-retention confirmation for every panel member, **fail-closed**.

        The answers come from the injected source (or the provider's endpoint via the
        transport when no source is given — the same fail-closed evaluation either way).
        Absent, empty, hedged or otherwise non-explicit answers leave the model
        unconfirmed: `bool(answer)` reads "unknown" as a yes, and this gate exists because
        that reads a privacy promise out of a hedge."""
        confirmed: list[ModelRef] = []
        unconfirmed: list[ModelRef] = []
        for ref in model_refs:
            key = ref.build_id  # the seam's key: the build the answer speaks about
            if self._retention_answers is not None:
                source = self._retention_answers
                answer = source(key) if callable(source) else source.get(key)
            else:
                try:
                    response = self._transport.send(HttpRequest(
                        "GET", f"{self._base_url}/retention/{key}", {}, b""))
                    answer = response.body.decode("utf-8", errors="replace")
                except TransportError as error:
                    answer = f"unreachable: {error}"
            if _is_retention_confirmed(answer):
                confirmed.append(ref)
            else:
                unconfirmed.append(ref)
        if unconfirmed:
            # The gate is the run-start defense (FR-PROV-14): an unconfirmed panel member
            # stops the run HERE, naming which models failed — not in a report a caller
            # might ignore. The flag also arms complete()'s refusal, so a caller that
            # ignores this error still cannot reach the provider (CT-PROV-13's ordering).
            self._retention_gate_failed = True
            raise RetentionPolicyError(
                f"zero-retention routing unconfirmed for {len(unconfirmed)} of "
                f"{len(model_refs)} panel members: "
                f"{'; '.join(f'{r.provider}:{r.build_id}' for r in unconfirmed)}. "
                "A cloud-hosted run does not start until every member is confirmed, and "
                "nothing has been dispatched."
            )
        return RetentionReport(
            confirmed=tuple(confirmed), unconfirmed=(),
        )

    def require_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport:
        """`cloud-hosted`'s gate, as an explicit name: `verify_retention` raises on any
        unconfirmed panel member (naming which), and returns the report when the whole
        panel is cleared. The alias exists so a caller's intent reads at the call site."""
        return self.verify_retention(model_refs)

    def capabilities(self, model_ref: ModelRef) -> Capabilities:
        """Declared statically (`CT-PROV-04`). The hosted provider supports prefix caching
        and seeds; concurrency is the run-config's to decide, so the declared ceiling is
        generous and `FR-PROV-07`'s governor throttles in flight."""
        return Capabilities(
            supports_seed=True, supports_prefix_cache=True, max_concurrency=8,
            deterministic_at_temperature_zero=False,
            cost_per_token=(self._cost_per_token_in, self._cost_per_token_out),
        )

    def enforce_routing_rule(self, model_ref: ModelRef, kind: str) -> None:
        """`FR-PROV-11`: price-based routing across providers is refused for scoring and
        extraction calls — the cheapest path must never decide a judgment. Permitted
        elsewhere (formatting, embedding); where the API permits it, the upstream provider
        is pinned via the model suffix `:upstream` convention (detection of drift stays
        with `FR-PROV-05` — prevention is design §3.2's open TBD and is not claimed)."""
        if kind.lower() in ROUTING_PROHIBITED_KINDS:
            raise ConfigurationError(
                f"price-based routing across providers is refused for {kind} calls "
                f"(FR-PROV-11): the cheapest path must never decide a judgment. Pin the "
                f"upstream provider for {model_ref.build_id!r} in the run configuration."
            )


#: The provider names served by the on-premise OpenAI-compatible server. M-PROV owns the
#: backend identities (`CT-PROV-15`: this module is the only place in the tree that names
#: one), so the name → implementation mapping lives here and nowhere else.
_LOCAL_SERVER_PROVIDER_NAMES = frozenset({"local", "local-server", "ollama", "vllm-mlx"})
