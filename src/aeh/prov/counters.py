"""The per-run counters, and the guard that refuses a model build that changed mid-run."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal

from .errors import BuildChangedError


# --- run counters and the build-change guard (FR-PROV-09, FR-PROV-12, FR-PROV-05) --------------

#: The six counter names, contract per `CT-PROV-11` — read by name for persistence into
#: `run_metrics`. Not a partition: a call answered 429 once then succeeding increments
#: **both** `transport_retries` (every attempt beyond the first, whatever provoked it —
#: `FR-PROV-06` classifies 429 as transport-class) and `rate_limited_calls` (calls throttled
#: at least once). Design v1.5 settles the semantics because the partitioning reading is
#: defensible and reports a different number — and `rate_limited_calls`' consumer is an
#: alert on its *share of dispatch*, which needs the per-call count.
COUNTER_NAMES: tuple[str, ...] = (
    "transport_retries",
    "rate_limited_calls",
    "rate_limit_wait_s",
    "tokens_in",
    "tokens_out",
    "cache_hit_rate",
)


@dataclass(frozen=True)
class RunCounters:
    """The six counters as `counters()` returns them (`CT-PROV-11`'s surface).

    `cache_hit_rate` is the token-weighted `cached_prefix_tokens / tokens_in` over the run —
    a rate in `[0, 1]`, never a count. HLD §9.7 treats a drop below the historical band as
    a build failure with no error (the symptom of losing prefix ordering is a fivefold
    slowdown), which is why the unit is a rate and the name is contract."""

    transport_retries: int
    rate_limited_calls: int
    rate_limit_wait_s: float
    tokens_in: int
    tokens_out: int
    cache_hit_rate: float


class RunCountersTracker:
    """The in-memory accumulator behind `counters()`. This module writes nothing directly:
    `M-ORCH` reads `counters()` and persists to `run_metrics` on the ordinary commit cadence
    (`CT-PROV-11`)."""

    def __init__(self) -> None:
        self._transport_retries = 0
        self._rate_limited_calls = 0
        self._rate_limit_wait_s = 0.0
        self._tokens_in = 0
        self._tokens_out = 0
        self._cached_prefix_tokens = 0
        self._decision_calls = 0
        self._decision_tokens_in = 0
        self._decision_transport_retries = 0
        self._decision_rate_limited_calls = 0
        self._decision_actual_cost = Decimal(0)
        self._decision_provider_unreported = 0
        self._lock = threading.Lock()

    def on_retry(self) -> int:
        """One more attempt beyond the first, whatever provoked it (429 included)."""
        with self._lock:
            self._transport_retries += 1
            return self._transport_retries

    def on_rate_limited(self, waited_s: float, *, first_for_call: bool = True) -> None:
        """The call was throttled at least once — counted once per call (`first_for_call`),
        with every wait it incurred accumulated under `rate_limit_wait_s` (FR-PROV-12)."""
        with self._lock:
            if first_for_call:
                self._rate_limited_calls += 1
            self._rate_limit_wait_s += waited_s

    def on_usage(self, tokens_in: int, tokens_out: int, cached_prefix_tokens: int) -> None:
        with self._lock:
            self._tokens_in += tokens_in
            self._tokens_out += tokens_out
            self._cached_prefix_tokens += cached_prefix_tokens

    def on_decision(self, *, tokens_in: int, transport_retries: int, rate_limited: bool,
                    cost: Decimal | None) -> None:
        """One completed `decide` call (FR-PROV-29). Kept apart from the six LLM counters so
        a decision retry never moves `transport_retries`, whose values TC-PROV-18 pins."""
        with self._lock:
            self._decision_calls += 1
            self._decision_tokens_in += tokens_in
            self._decision_transport_retries += transport_retries
            self._decision_rate_limited_calls += 1 if rate_limited else 0
            if cost is not None:
                self._decision_actual_cost += cost

    def on_decision_provider_unreported(self) -> None:
        """An OpenRouter decision response that carried no `provider` field (FR-PROV-43): the
        per-call routing check could not run on it. Counted, not refused (the field is optional)."""
        with self._lock:
            self._decision_provider_unreported += 1

    def decision_snapshot(self) -> "DecisionCounters":
        """CT-PROV-24's names. `decision_actual_cost` is what `M-ORCH` adds to the run's
        `actual_cost`, so the ceiling check reads one figure."""
        with self._lock:
            return DecisionCounters(
                decision_calls=self._decision_calls,
                decision_tokens_in=self._decision_tokens_in,
                decision_transport_retries=self._decision_transport_retries,
                decision_rate_limited_calls=self._decision_rate_limited_calls,
                decision_actual_cost=self._decision_actual_cost,
                decision_provider_unreported=self._decision_provider_unreported,
            )

    def snapshot(self) -> RunCounters:
        with self._lock:
            rate = (
                self._cached_prefix_tokens / self._tokens_in if self._tokens_in else 0.0
            )
            return RunCounters(
                transport_retries=self._transport_retries,
                rate_limited_calls=self._rate_limited_calls,
                rate_limit_wait_s=self._rate_limit_wait_s,
                tokens_in=self._tokens_in,
                tokens_out=self._tokens_out,
                cache_hit_rate=rate,
            )


class BuildWatch:
    """The run-start build record, and the guard that refuses a changed panel (`FR-PROV-05`).

    `record` is called at run start with the builds the panel expects; `check` is called per
    response with the build that actually served it. A mismatch raises `BuildChangedError`
    — terminal, **not retried** (`FR-PROV-05`: a retry that landed back on the original
    build would hide the fact that the panel changed mid-run). The comparison is exact-case
    and whole-string (`TC-PROV-08`'s boundary: case differences and revision suffixes are
    different builds — a declared rule, stated here rather than left incidental)."""

    def __init__(self) -> None:
        self._expected: dict[str, str] = {}

    def record(self, model_key: str, build_id: str) -> None:
        self._expected[model_key] = build_id

    def check(self, model_key: str, served_build: str) -> None:
        expected = self._expected.get(model_key)
        if expected is None:
            return  # no run-start record for this model: nothing to guard yet
        if served_build != expected:
            raise BuildChangedError(
                f"the panel changed mid-run: {model_key} was built {expected!r} at run "
                f"start and {served_build!r} served this response. Not retried (FR-PROV-05) "
                f"— a retry landing on the original build would hide the change."
            )


@dataclass(frozen=True)
class DecisionCounters:
    """FR-PROV-29 / CT-PROV-24: the decision counters, by their contract names."""

    decision_calls: int
    decision_tokens_in: int
    decision_transport_retries: int
    decision_rate_limited_calls: int
    decision_actual_cost: Decimal
    #: Design 1.8 (FR-PROV-43): OpenRouter responses with no `provider` field.
    decision_provider_unreported: int = 0
