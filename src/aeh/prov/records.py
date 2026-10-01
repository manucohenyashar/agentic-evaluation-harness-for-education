"""The data of one completion call: the payload, sampling knobs, the answer and capabilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from aeh.conf import ModelRef


# --- boundary types ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptPayload:
    """An assembled prompt, exactly as the caller built it.

    `fields` is an **ordered** sequence of `(name, value)` pairs and not a mapping, because
    `CT-PROV-05` forbids reordering and a mapping makes order an implementation detail of
    whoever iterates it. This module never reads a field by name, never adds one, and never
    templates a value: prompt construction belongs to `M-JUDGE`, `M-EXTRACT`, `M-SYNTH`,
    `M-INGEST` and `M-SETUP` (`FR-PROV-13`).

    Values are opaque student and rubric text. Nothing here inspects, normalizes or logs them.
    """

    fields: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fields, tuple):
            raise ValueError(
                f"PromptPayload.fields must be a tuple of (name, value) pairs, got "
                f"{type(self.fields).__name__}. A list would make the payload unhashable and "
                f"its order an accident; CT-PROV-05 makes order contract."
            )
        for index, pair in enumerate(self.fields):
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError(
                    f"PromptPayload.fields[{index}] must be a (name, value) pair, got {pair!r}."
                )
            name, value = pair
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"PromptPayload.fields[{index}] name must be a non-empty string, got "
                    f"{name!r}."
                )
            if not isinstance(value, str):
                raise ValueError(
                    f"PromptPayload.fields[{index}] value must be a string, got "
                    f"{type(value).__name__}. This module dispatches the payload byte-"
                    f"identically (CT-PROV-05); it does not serialize objects for a caller."
                )


@dataclass(frozen=True)
class SamplingParams:
    """The sampling settings for one call.

    Named but unspecified in design §3.2, so the field set is chosen here. Every field is part
    of the request key: `FR-PROV-10` keys the fixture on the *fully-assembled request*, and
    `TC-PROV-14` includes a `temperature` mutation precisely to kill a key that ignores these.

    Adding a field later changes every stored key. That is the safe direction — a fixture set
    recorded under the old shape misses loudly rather than answering a request it never saw.
    """

    temperature: float
    max_tokens: int | None = None
    top_p: float | None = None
    seed: int | None = None
    stop: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a float that is not finite; the failure it would cause later is confusing.

        `float("nan")` keys and records perfectly well and can then never be read back: the
        stored request is compared for equality on the way out, and `nan != nan`. The result
        is a recording that exists on disk and misses forever, which reads as a key bug rather
        than as the nonsense sampling parameter it is. Refused at construction instead.
        """
        for name in ("temperature", "top_p"):
            value = getattr(self, name)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(
                    f"SamplingParams.{name} must be finite, got {value!r}. A non-finite value "
                    f"records and then never matches itself, so the recording would exist and "
                    f"miss forever."
                )


@dataclass(frozen=True)
class Completion:
    """One model answer, with its token counts, latency and cost (design §3.2, CT-PROV-03).

    `cost` is the **only** nullable field, and null only on `edge-local` and fixture — where
    nothing was billed and therefore nothing was measured. A `cost` of `Decimal("0")` on a
    cloud call is a defect and not a saving: *not measured* and *measured zero* are different
    facts, and `M-ORCH`'s ceiling cannot tell them apart once they share a representation.

    `resolved_build` is what actually answered, never what was requested (`FR-PROV-04`).
    `text` is verbatim and unparsed — this module has no opinion about what a judge said.
    """

    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    resolved_build: str
    cached_prefix_tokens: int
    cost: Decimal | None

    def __post_init__(self) -> None:
        """Check field types when built, so a malformed value never reaches a consumer.

        `ValueError` rather than `MalformedResponseError`: this is a type-level guard against a
        caller building a nonsense value, not the classification of a provider response. #19's
        parser raises the taxonomy error when a *response* fails to parse.
        """
        if not isinstance(self.text, str):
            raise ValueError(
                f"Completion.text must be a string, got {type(self.text).__name__}. It is "
                f"returned verbatim and unparsed (CT-PROV-03)."
            )
        if not isinstance(self.resolved_build, str) or not self.resolved_build.strip():
            raise ValueError(
                "Completion.resolved_build must be a non-empty string: it is what actually "
                "answered, and it reaches run_metrics.resolved_builds (FR-PROV-04)."
            )
        for name in ("tokens_in", "tokens_out", "latency_ms", "cached_prefix_tokens"):
            value = getattr(self, name)
            # `bool` is an `int`; a True that meant one token is a bug worth refusing.
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"Completion.{name} must be a non-negative int, got {value!r}."
                )
        if self.cost is not None and not isinstance(self.cost, Decimal):
            raise ValueError(
                f"Completion.cost must be a Decimal or None, got "
                f"{type(self.cost).__name__}. A float cannot represent a currency amount "
                f"exactly, and this figure is compared against M-ORCH's ceiling."
            )


@dataclass(frozen=True)
class Capabilities:
    """What a provider declares about itself (FR-PROV-02, CT-PROV-04).

    Declared per implementation, never discovered at call time — `capabilities()` answers with
    the transport hard-blocked, and the answer is stable for the life of the run.

    `deterministic_at_temperature_zero` is the backend's **claim**, not a measurement.
    `M-STATS` (`FR-STATS-16`) measures the reality separately, and the two disagreeing is a
    finding there, not an error here. `CT-PROV-16` is the matching non-promise: identical
    inputs are not guaranteed to produce identical text on any backend.

    `cost_per_token` is `None` where nothing is billed, for the same reason `Completion.cost`
    is: a declared zero would read as a measured price of nothing.
    """

    supports_seed: bool
    supports_prefix_cache: bool
    max_concurrency: int
    deterministic_at_temperature_zero: bool
    cost_per_token: Decimal | None


@dataclass(frozen=True)
class CallPlan:
    """A planned batch of calls, for `estimate_cost` (FR-PROV-09).

    Call count and per-call token budgets only — design §3.2's signature takes no `ModelRef`,
    so the per-token price comes from the implementation's own `Capabilities`.
    """

    calls: int
    tokens_in_per_call: int
    tokens_out_per_call: int


@dataclass(frozen=True)
class CostEstimate:
    """What `estimate_cost` returns. `cost` is None where nothing is billed."""

    calls: int
    tokens_in: int
    tokens_out: int
    cost: Decimal | None


@dataclass(frozen=True)
class RetentionReport:
    """What `verify_retention` returns (FR-PROV-14, CT-PROV-13).

    Carries both halves rather than a boolean, because the operator has to be told *which*
    panel member could not be confirmed — `TC-PROV-16` is "confirmed for two of three".
    """

    confirmed: tuple[ModelRef, ...]
    unconfirmed: tuple[ModelRef, ...]

    @property
    def all_confirmed(self) -> bool:
        return not self.unconfirmed
