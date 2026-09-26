"""`M-PROV` — Inference Provider Abstraction (design §3.2).

One `InferenceProvider` interface, and the only path by which a model call leaves the harness.
A caller holding this module holds *"text in, text out, accounted for"* and no knowledge
whatever of which backend answered (`CT-PROV`).

Scope of this file today
------------------------
`M-PROV` ships across four stories. **#18** (this file's first commit) lands `FR-PROV-01`,
`FR-PROV-02`, `FR-PROV-13`, `NFR-PROV-02`, `NFR-PROV-05`: the interface, the boundary types,
the canonical request encoding that makes payload passthrough byte-identical, and
`RecordedFixtureProvider` — the fast tier's deterministic transport.

Still to land, and deliberately absent rather than stubbed:

| Story | What it adds |
|---|---|
| #19 | `FR-PROV-06`/`-07`/`-08` — the retry loop, 429 backpressure, the no-fallback rule. The taxonomy below is *declared* here so #19 does not have to reshape it (a breaking change, per §3.2 Compatibility) |
| #20 | `FR-PROV-04`/`-05`/`-09`/`-12` — resolved-build comparison, `BuildChangedError`, `actual_cost` accumulation, the six run counters |
| #21 | `FR-PROV-03`/`-10`/`-11`/`-14` — `LocalServerProvider`, `OpenRouterProvider`, the import-graph assertion, retention verification, pseudonymized payloads |

`RecordedFixtureProvider` is here rather than with #21 because it is the only implementation
that reaches no network, and #18's own acceptance criteria — *"returns a fully-populated
`Completion`"*, *"captured at the caller and on the wire"* — are unassertable against a
Protocol with no implementation behind it. `tests/support/impl.py` names #18 as the blocker
for `tests/unit/prov/test_recorded_fixture_provider.py` for the same reason.

Why the fixture provider is not a test double
---------------------------------------------
Test plan §4.2 calls it *"a shipped implementation, not a test fake"*, and RISK-37 is why:
almost every case in the plan runs against it, so if it drifts from the contract the live
providers keep — stops raising what they raise, populates a field they leave `None` — the fast
tier stays green while describing a system that does not exist. That is a **critical** risk
whose symptom is a passing suite. Every decision below that looks over-careful for a fixture
reader is paying that risk down.

Decisions this file fixes, that the design underdetermines
----------------------------------------------------------
Recorded here rather than in a commit message because `TS-05` (#22), `TS-06` (#23), `TS-07`
(#24) and `TS-59` (#25) are written **against whatever this module ships**, and a signature
they have to guess is a suite that asserts the wrong thing.

| Decision | Choice | Forced by |
|---|---|---|
| `PromptPayload`'s shape | `fields: tuple[tuple[str, str], ...]` — ordered, named, values opaque | Named but unspecified in §3.2; `TS-00` constructs it this way, and `CT-PROV-05` forbids reordering, so a mapping would have been the wrong type |
| `SamplingParams`' shape | `temperature` plus four optional knobs, all part of the request key | Named but unspecified in §3.2 |
| `record()` | The recording half of `FR-PROV-10`, on the fixture implementation only | §4.4 regenerates `F-RECORDED` nightly, so a recording path must exist; **nothing in the design names it**. Raised as a finding on the PR |
| Request key | `sha256` over a **length-framed** encoding — never a separator join | Injectivity. The same defect the reviewer found in `compute_panel_build_ref` on #4; here it cannot be closed by refusing control characters, because payload values are submission prose |
| The key covers payload, `ModelRef` **and every** `SamplingParams` field | Derived from `dataclasses.fields`, so a knob added later changes the key | `FR-PROV-10` says "the fully-assembled request"; `TC-PROV-14`'s five mutations each kill one naive key |
| `request_key` streams into the hasher | No buffer holding the assembled request is ever materialized | `NFR-PROV-02`: no per-call copy of the invariant prefix |
| `record()` refuses a non-null `cost` | `ValueError`, naming `CT-PROV-03` | Fixture ⇒ `cost is None`. Storing a cloud cost would make the canonical double contradict the clause every consumer tests against (RISK-37); normalizing it silently would hide the same thing |
| The **reader** refuses one too | `FixtureMissingError`, not a silent `None` | The writer is loud and the reader is the path every fast-tier test runs; normalizing on read would make the rule silent exactly where it matters |
| Every unusable fixture file raises inside the taxonomy | Bad JSON, a wrong `schema`, a moved `key`, a missing or ill-typed field: all `FixtureMissingError` | `CT-PROV-07` is what a caller catches. A bare `JSONDecodeError` out of a hand-edited recording is a hole in it, and §4.4 regenerates `F-RECORDED` nightly |
| One payload encoder, shared | `_emit_payload`, used by both `payload_bytes` and `request_key` | Two copies of one encoding drift: once #21 derives the wire body from `payload_bytes`, a change to it must move the key |
| A non-finite `temperature`/`top_p` | Refused at construction | It records and then never matches itself (`nan != nan`), so the recording would exist on disk and miss forever |
| `latency_ms` is replayed, never measured | The stored `Completion` is returned unchanged | `TC-PROV-13` compares the whole value by equality; a measured latency makes replay non-deterministic |
| A fixture file stores the **request** as well as the response | Verified on read; a mismatch is a miss | Turns a key collision into a loud `FixtureMissingError` instead of a stale answer — the exact RISK-37 failure `TC-PROV-14` exists to prevent |
| Error taxonomy | Seven **siblings** under a neutral `ProviderError`; all declared, one raised here | `CT-PROV-07` names six and asserts retryability *per error*; siblings keep every "exact exception type" oracle discriminating, and reshaping the hierarchy later is a breaking change |
| `Capabilities` resolved once, in `__init__` | Never re-read from the environment per call | `CT-PROV-04`: declared, not discovered, and "stable for the life of the run" |
| Fixture declares `supports_prefix_cache=True` | It replays the recorded backend's prefix accounting | Declaring `False` would send consumers down a different code path against the double than against a live backend — verbatim the drift `NFR-PROV-01` forbids |
| `estimate_cost` uses the *implementation's* declared `cost_per_token` | `CallPlan` carries call count and per-call token budgets only | §3.2's signature takes no `ModelRef`; `FR-PROV-09` says "planned call count and per-call token budgets" |

The four seams (`CLAUDE.md`)
----------------------------
1. **Headless driver** — this is a library; every operation is a plain synchronous call and
   nothing here touches a console.
2. **Deterministic transport** — `RecordedFixtureProvider`, landing in the same commit as the
   interface whose dependency it stands in for. It reaches no network on any code path.
3. **Env-gated knobs** — `HARNESS_FIXTURE_DIR` and `HARNESS_FIXTURE_MAX_CONCURRENCY`, both
   read once at construction. `HARNESS_RETRY_MAX` and `HARNESS_BACKOFF_BASE_MS` arrive with
   #19, which owns the loop that reads them.
4. **Stage-level observability** — `Completion` carries the per-call detail next to the text
   (`tokens_in`, `tokens_out`, `latency_ms`, `resolved_build`, `cached_prefix_tokens`), and
   the per-call DEBUG line of `CT-PROV-14` is emitted here. It names metadata only: payload
   values are student work, so no field value reaches a log line (`CT-PROV-13`).
"""

from __future__ import annotations

import dataclasses
import random
import threading
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Callable
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from aeh.conf import ConfigurationError, ModelRef

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
    "decision_questions_document",
    "decision_request_key",
    "derived_confidence",
    "parse_decision",
]

LOGGER_NAME = "aeh.prov"
_LOGGER = logging.getLogger(LOGGER_NAME)

#: Design §3.2 Configuration. Read once at construction, never per call (`CT-PROV-04`).
FIXTURE_DIR_ENV = "HARNESS_FIXTURE_DIR"

#: Seam 3. The fixture backend's declared `max_concurrency`: it is bounded by filesystem
#: parallelism, which differs by an order of magnitude between a laptop SSD and a shared CI
#: volume. The default is HLD §8.4's reference figure so the double declares what the local
#: server declares — a double advertising a *different* ceiling sends `M-ORCH` down a
#: different scheduling path than the backend it stands in for (RISK-37).
FIXTURE_MAX_CONCURRENCY_ENV = "HARNESS_FIXTURE_MAX_CONCURRENCY"
DEFAULT_FIXTURE_MAX_CONCURRENCY = 32


# --- errors ----------------------------------------------------------------------------------


class ProviderError(Exception):
    """Base for every `M-PROV` failure.

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
    """HTTP 429. Retryable *with a wait* — `Retry-After` when present, jittered backoff
    otherwise (`FR-PROV-07`, #19)."""

    retryable = True


class MalformedResponseError(ProviderError):
    """The response failed structural parsing.

    Retryable up to the retry budget; past it the *unit* quarantines and the run continues
    (`CT-PROV-07`, HLD §9.11 "fail the unit, never the run").
    """

    retryable = True


class ProviderUnavailableError(ProviderError):
    """Repeated 5xx or timeout beyond the retry budget. Terminal for the run.

    Never retried, and never a trigger for substitution: `CT-PROV-08` lets a caller receiving
    this rely on the fact that nothing was silently graded by something else.
    """


class BuildChangedError(ProviderError):
    """A response reported a served build differing from the one recorded at run start.

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


# --- boundary types ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptPayload:
    """An assembled prompt, exactly as its caller built it.

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
    """The sampling knobs of one call.

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
        """Refuse a non-finite float, because the alternative failure is confusing.

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
    """One model answer, with its accounting. Design §3.2 Interfaces, `CT-PROV-03`.

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
        """Shape only, on construction, so a malformed value cannot reach a consumer.

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
    """What an implementation *declares* about itself. `FR-PROV-02`, `CT-PROV-04`.

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
    """A planned batch, for `estimate_cost`. `FR-PROV-09`.

    Call count and per-call token budgets only — design §3.2's signature takes no `ModelRef`,
    so the per-token price comes from the implementation's own `Capabilities`.
    """

    calls: int
    tokens_in_per_call: int
    tokens_out_per_call: int


@dataclass(frozen=True)
class CostEstimate:
    """The pure result of `estimate_cost`. `cost` is `None` where nothing is billed."""

    calls: int
    tokens_in: int
    tokens_out: int
    cost: Decimal | None


@dataclass(frozen=True)
class RetentionReport:
    """The result of `verify_retention`. `FR-PROV-14`, `CT-PROV-13`.

    Carries both halves rather than a boolean, because the operator has to be told *which*
    panel member could not be confirmed — `TC-PROV-16` is "confirmed for two of three".
    """

    confirmed: tuple[ModelRef, ...]
    unconfirmed: tuple[ModelRef, ...]

    @property
    def all_confirmed(self) -> bool:
        return not self.unconfirmed


# --- the canonical request encoding -------------------------------------------------------------
#
# `FR-PROV-13`/`CT-PROV-05` (dispatch the payload byte-identically) and `FR-PROV-10` (key the
# fixture on a hash of the fully-assembled request) are the same problem seen from two sides,
# so they share one encoding. Both are served by *framing*: every component goes into the
# stream as an 8-byte big-endian length followed by its bytes.
#
# Framing rather than a separator join, and that is the whole point of this block. A join over
# `(name, value)` pairs is not injective when a value may contain the separator — and payload
# values are submission prose, which legitimately contains newlines, tabs and every byte a
# separator could be. `ModelRef` closed the same hole on #4 by refusing control characters;
# that fix is unavailable here. Without framing, a single field reading
# `"...\x1fsubmission\x1f..."` can produce the key of a *different* two-field payload — a
# stale fixture silently answering a changed prompt, which is verbatim the RISK-37 failure
# `TC-PROV-14` exists to prevent, arriving through the encoding rather than through the hash.

#: Bumping this invalidates every stored key, which is exactly what an encoding change should
#: do: a fixture recorded under a different scheme misses loudly instead of answering.
KEY_SCHEME = b"aeh.prov/request-key/1"

_FRAME_WIDTH = 8

_TAG_NONE = b"\x00"
_TAG_BOOL = b"\x01"
_TAG_INT = b"\x02"
_TAG_FLOAT = b"\x03"
_TAG_STR = b"\x04"
_TAG_DECIMAL = b"\x05"
_TAG_SEQ = b"\x06"

#: Named explicitly rather than read from `dataclasses.fields(ModelRef)`: `M-CONF` owns that
#: type, and a field added there must be a deliberate decision here — silently rekeying every
#: recording in the repository is not something `M-CONF` should be able to do by accident.
_MODEL_REF_FIELDS = ("role", "provider", "build_id", "quantization")


def _frame(chunk: bytes) -> bytes:
    """`chunk`, length-prefixed, so a concatenation of frames decodes unambiguously."""
    return len(chunk).to_bytes(_FRAME_WIDTH, "big") + chunk


def _emit_framed(emit: Any, chunk: bytes) -> None:
    """`_frame`, without the concatenation. Two emits, byte-identical to one framed chunk.

    `emit` is `hashlib`'s `update` or a `bytearray`'s `extend`. Split in two because
    `_frame(value)` allocates a second copy of every field value, and field values are the
    invariant prefix `NFR-PROV-02` forbids copying per call.
    """
    emit(len(chunk).to_bytes(_FRAME_WIDTH, "big"))
    emit(chunk)


def _emit_payload(emit: Any, prompt: PromptPayload) -> None:
    """The payload's canonical encoding, emitted in the caller's field order.

    **The only place a `PromptPayload` is encoded.** `payload_bytes` and `request_key` both go
    through here, so the wire body and the fixture key can never disagree about what the
    payload was — which is what would otherwise let a change to one silently fail to move the
    other once #21 derives its request body from `payload_bytes`.

    A value that is not encodable as UTF-8 (a lone surrogate) raises `UnicodeEncodeError`,
    which is a `ValueError` — the same class `PromptPayload.__post_init__` raises for every
    other malformed payload, and not part of the `ProviderError` taxonomy, because a payload
    that cannot be encoded is a caller defect rather than a provider failure.
    """
    for name, value in prompt.fields:
        _emit_framed(emit, name.encode("utf-8"))
        _emit_framed(emit, value.encode("utf-8"))


def _encode_scalar(value: Any) -> bytes:
    """One `ModelRef` or `SamplingParams` value, type-tagged and framed.

    The tag is what keeps `0`, `0.0`, `"0"` and `Decimal("0")` four distinct requests. Floats
    go in as `float.hex`, which is exact and canonical — `str(0.1)` is neither across
    platforms, and a key that drifts by platform is a fixture set that misses on CI only.
    """
    if value is None:
        return _TAG_NONE + _frame(b"")
    if isinstance(value, bool):  # before int: bool is a subclass of it
        return _TAG_BOOL + _frame(b"1" if value else b"0")
    if isinstance(value, int):
        return _TAG_INT + _frame(str(value).encode("utf-8"))
    if isinstance(value, float):
        return _TAG_FLOAT + _frame(float.hex(value).encode("ascii"))
    if isinstance(value, str):
        return _TAG_STR + _frame(value.encode("utf-8"))
    if isinstance(value, Decimal):
        return _TAG_DECIMAL + _frame(str(value).encode("ascii"))
    if isinstance(value, (tuple, list)):
        body = b"".join(_encode_scalar(item) for item in value)
        return _TAG_SEQ + _frame(len(value).to_bytes(_FRAME_WIDTH, "big") + body)
    raise ValueError(
        f"cannot encode {type(value).__name__} into a request key. Every part of the "
        f"assembled request must have a canonical encoding (FR-PROV-10); add a tag above "
        f"rather than letting an unencodable value fall through to a shared key."
    )


def payload_bytes(prompt: PromptPayload) -> bytes:
    """The caller's assembled payload, serialized without adding, reordering or normalizing.

    The single point at which a `PromptPayload` becomes bytes, so `CT-PROV-05`'s byte-level
    differential has one thing to compare against. Field order is the caller's, names and
    values are verbatim, and nothing is inserted between them but the frame lengths.

    `complete()` does **not** call this — the fixture path needs only the key, and hashing
    streams (see `request_key`). It exists for the live implementations of #21, which derive
    their wire body from it, and for the differential itself. Both go through `_emit_payload`,
    so this function and the key can never encode the same payload differently.
    """
    buffer = bytearray()
    _emit_payload(buffer.extend, prompt)
    return bytes(buffer)


def request_key(
    prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams
) -> str:
    """`sha256` over the fully-assembled request: payload, model ref and sampling params.

    Everything that would change what a backend returns is in here, which is what makes
    `TC-PROV-14` pass for the right reason: a punctuation byte, a whitespace change, a case
    change, a different build and a different temperature each move the key, because each is
    part of the request rather than of a normalized view of it.

    Streamed into the hasher rather than assembled into a buffer, and framed without
    concatenation (`_emit_framed`), so the only copy of a field value made per call is the one
    `str.encode` must make for `hashlib`. `NFR-PROV-02` forbids a per-call copy of the
    invariant prefix — the prefix is a shared string the caller owns, and hashing it in place
    means an observed `cache_hit_rate` reflects the caller's prompt ordering rather than this
    module's allocation behaviour (`CT-PROV-12`).

    The element counts go in ahead of the elements. Framing alone decodes unambiguously
    *within* a section; the counts are what keep a payload field named `"model_ref"` from
    being read as the start of the next section.
    """
    digest = hashlib.sha256()
    digest.update(_frame(KEY_SCHEME))

    digest.update(_frame(b"payload"))
    digest.update(len(prompt.fields).to_bytes(_FRAME_WIDTH, "big"))
    _emit_payload(digest.update, prompt)

    digest.update(_frame(b"model_ref"))
    for name in _MODEL_REF_FIELDS:
        digest.update(_frame(name.encode("utf-8")))
        digest.update(_encode_scalar(getattr(model_ref, name)))

    digest.update(_frame(b"params"))
    param_fields = dataclasses.fields(params)
    digest.update(len(param_fields).to_bytes(_FRAME_WIDTH, "big"))
    for field in param_fields:
        digest.update(_frame(field.name.encode("utf-8")))
        digest.update(_encode_scalar(getattr(params, field.name)))

    return "sha256:" + digest.hexdigest()


# --- the interface -------------------------------------------------------------------------------


# --- the transport and clock seam (FR-PROV-15, design v1.5) ------------------------------------
#
# The seam this story owns. Design §3.2's v1.5 text: the real providers take `transport`,
# `clock`, `retention_answers` and `on_dispatch` as constructor arguments defaulting to the
# real ones, behaviour-neutrally. The point is not convenience — it is that the retry
# taxonomy below is *stated and assertable*: the only way to program a 429 without the seam
# was to stub the provider, which replaces the very code under test. A `Transport` is one
# HTTP attempt and nothing else; retry classification lives here, in this module, where
# `FR-PROV-06`'s rule can hold it.


@dataclass(frozen=True)
class HttpRequest:
    """One request as a `Transport` receives it. Plain data, no logic."""

    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class HttpResponse:
    """One response as a `Transport` returns it. `status` is the HTTP code; a connection
    failure never produces an `HttpResponse` — it raises `TransportError`, which is the
    classification the retry loop trusts."""

    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    """One HTTP attempt, and no retry logic (`FR-PROV-15`).

    Implementations raise `TransportError` for a connection failure or timeout, and return
    an `HttpResponse` otherwise — including for 429 and 5xx, whose *classification* is this
    module's job, not the transport's. A transport that retried internally would make
    `HARNESS_RETRY_MAX` a lie; the protocol's docstring is part of the contract for that
    reason.
    """

    def send(self, request: HttpRequest) -> HttpResponse: ...


class Clock(Protocol):
    """The two things a retry loop needs from time: a monotonic reading and a way to wait.

    Injected so `Retry-After: 2` honoured twenty times consumes no wall time in a test —
    test plan §4.6 makes `TC-ORCH-09` the suite's one sanctioned sleep, and a retry loop
    that slept for real would spend the whole budget on the first case that exercised it.
    """

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """The real clock. The default, and the only thing in the module that touches `time`."""

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def _wait(clock, seconds: float) -> None:
    """Wait `seconds`, through whatever the injected clock offers.

    `SystemClock` sleeps for real. A test clock implements `advance` (the suite's
    `FrozenClock` does), and advancing is the honest equivalent: the wait consumes fake
    time, `rate_limit_wait_s` stays assertable, and §4.6's one-sanctioned-sleep rule is
    not spent by a retry loop. A clock with neither is treated as instantaneous."""
    sleeper = getattr(clock, "sleep", None)
    if callable(sleeper):
        sleeper(seconds)
        return
    advancer = getattr(clock, "advance", None)
    if callable(advancer):
        advancer(seconds)


# --- the knobs (seam 3: production value is the default) ---------------------------------------

#: `HARNESS_RETRY_MAX` (default 3) — the retry budget `FR-PROV-06` names. Attempts, not
#: retries: a budget of 3 is one first attempt and two retries.
RETRY_MAX_ENV = "HARNESS_RETRY_MAX"
DEFAULT_RETRY_MAX = 3

#: `HARNESS_BACKOFF_BASE_MS` (default 250) — the exponential backoff's base, before jitter.
BACKOFF_BASE_MS_ENV = "HARNESS_BACKOFF_BASE_MS"
DEFAULT_BACKOFF_BASE_MS = 250

#: `HARNESS_RETRY_AFTER_CEILING_S` (default 120) — a `Retry-After` above the ceiling is
#: treated as malformed: a provider answering "come back in an hour" is unavailable for a
#: school-day run, and waiting would hold the run hostage to a figure the provider made up.
RETRY_AFTER_CEILING_S_ENV = "HARNESS_RETRY_AFTER_CEILING_S"
DEFAULT_RETRY_AFTER_CEILING_S = 120.0

#: `HARNESS_CONCURRENCY_FLOOR` (default 1) — where in-flight dispatches ratchet down to on
#: repeated 429s (`FR-PROV-07`: "toward the configured floor rather than the full batch").
CONCURRENCY_FLOOR_ENV = "HARNESS_CONCURRENCY_FLOOR"
DEFAULT_CONCURRENCY_FLOOR = 1

#: The two live providers' endpoints and credential (`CT-PROV-15`: this module is the only
#: place in the tree that names a model endpoint).
OPENROUTER_BASE_URL_ENV = "OPENROUTER_BASE_URL"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
LOCAL_INFERENCE_BASE_URL_ENV = "LOCAL_INFERENCE_BASE_URL"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LOCAL_INFERENCE_BASE_URL = "http://127.0.0.1:8080/v1"

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


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name}={raw!r} is not an integer") from error
    if value < 0:
        raise ConfigurationError(f"{name}={value} must not be negative")
    return value


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name}={raw!r} is not a number") from error
    if value < 0:
        raise ConfigurationError(f"{name}={value} must not be negative")
    return value


@dataclass(frozen=True)
class RetryPolicy:
    """The retry budget, resolved once. The figures are env-gated (`CLAUDE.md` seam 3) and
    frozen at construction — `TC-PROV-C07`'s per-error assertions and `TC-STORE-C05`'s
    lesson both say a policy that re-read the environment would be unassertable."""

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
    """`Retry-After` as seconds-to-wait, or `None` when it must not be honoured.

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
    """Full jitter (`AWS architecture blog`'s formulation, which the design's "exponential
    with jitter" cites in spirit): uniform between 0 and the exponential cap. Full jitter
    beats equal-jitter for thundering herds, which is the failure mode `FR-PROV-07`'s
    concurrency floor exists to contain. `rng` is injected — a test asserting a wait
    pins the sequence, not the wall clock."""
    cap_ms = base_ms * (2 ** min(attempt, 30))
    return rng.uniform(0, cap_ms) / 1000.0


class ConcurrencyGovernor:
    """In-flight dispatch accounting, ratcheted down toward the configured floor on 429s
    (`FR-PROV-07`: "toward the configured floor rather than the full batch being
    dispatched").

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
        """Whether one more dispatch may start given the current permission level."""
        with self._lock:
            return in_flight < self._permitted

    def on_rate_limited(self) -> int:
        """Halve the permission, never below the floor. Returns the new level — the number
        an observability consumer reads (`CT-PROV-09`)."""
        with self._lock:
            self._permitted = max(self._floor, self._permitted // 2)
            return self._permitted

    def on_success(self) -> int:
        """One recovered dispatch lifts the permission back by one, never above the start."""
        with self._lock:
            self._permitted = min(self._floor * 8, self._permitted + 1)
            return self._permitted


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
        self._lock = threading.Lock()

    def on_retry(self) -> int:
        """One more attempt beyond the first, whatever provoked it (429 included)."""
        with self._lock:
            self._transport_retries += 1
            return self._transport_retries

    def on_rate_limited(self, waited_s: float) -> None:
        """The call was throttled at least once — counted once per call, with the whole
        wait it incurred accumulated under `rate_limit_wait_s`."""
        with self._lock:
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
    """Attempt one request through `transport`, retrying only what `FR-PROV-06` permits.

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
                    counters.on_rate_limited(wait)
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


@runtime_checkable
class InferenceProvider(Protocol):
    """The one interface. Design §3.2, `CT-PROV-01`.

    All four operations are **synchronous and blocking**, and exactly one of them —
    `complete` — makes a model call. One `complete` is one model call: no batching, no
    coalescing, no speculative second sample.

    This module starts no thread and owns no queue. Concurrency belongs to `M-ORCH`, and an
    internal worker pool here would take it away silently — along with `M-JUDGE`'s isolation
    between scoring contexts, which rests on the caller deciding what runs beside what.
    """

    def complete(
        self, prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams
    ) -> Completion: ...

    def capabilities(self, model_ref: ModelRef) -> Capabilities: ...

    def estimate_cost(self, plan: CallPlan) -> CostEstimate: ...

    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport: ...


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


class _DefaultTransport:
    """The real transport: one HTTP POST/GET via urllib, raising `TransportError` for any
    connection failure or timeout. This is the module's egress point (`CT-PROV-15`) — the
    only code in the tree that opens a socket to a model endpoint."""

    def __init__(self, timeout_s: float = 120.0) -> None:
        self._timeout_s = timeout_s

    def send(self, request: HttpRequest) -> HttpResponse:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            request.url, data=request.body if request.body else None,
            headers=request.headers, method=request.method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as response:
                return HttpResponse(
                    status=response.status,
                    headers={k: v for k, v in response.headers.items()},
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                status=error.code,
                headers={k: v for k, v in error.headers.items()},
                body=error.read(),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TransportError(f"transport failure reaching {request.url}: {error}") from error


#: The provider names served by the on-premise OpenAI-compatible server. M-PROV owns the
#: backend identities (`CT-PROV-15`: this module is the only place in the tree that names
#: one), so the name → implementation mapping lives here and nowhere else.
_LOCAL_SERVER_PROVIDER_NAMES = frozenset({"local", "local-server", "ollama", "vllm-mlx"})


def provider_for(model_ref: ModelRef, **seams: Any) -> "InferenceProvider":
    """The live transport a model ref's declared provider name selects (`FR-PROV-11`).

    A consumer asks for the transport **by ref** and names no backend itself: the
    name → implementation mapping is M-PROV's, so a module outside `M-PROV` never carries
    a backend-specific constant (`TC-PROV-05`'s scan reads the tree for exactly that).
    Unknown names refuse — an unserved backend is a configuration error, never a silent
    fall-back to a transport the caller did not ask for.
    """
    name = str(getattr(model_ref, "provider", "") or "")
    if name in _LOCAL_SERVER_PROVIDER_NAMES:
        return LocalServerProvider(**seams)
    if name == "openrouter":
        return OpenRouterProvider(**seams)
    raise ProviderUnavailableError(f"no shipped live transport for provider {name!r}")


# --- the decision surface (Jev design delta §3.1, FR-PROV-16…20/25…27/29) -----------------------
#
# A second provider surface beside `InferenceProvider`: typed questions in, typed probabilistic
# answers out. It exists for the decision engine (Jev) that `M-JUDGE` pre-screens the decision
# seat with. Three rules from the design shape everything below:
#
# - **Refuse, never repair** (FR-PROV-20). A response whose distribution does not sum to one, or
#   whose Score legend names a different level, is a `MalformedResponseError` — retryable per
#   CT-PROV-06 like any structural parse failure. Renormalising it would hide an engine or wire
#   defect behind a plausible-looking band.
# - **One statistic for confidence** (FR-PROV-19). A reported confidence is used when present;
#   otherwise, and always for a Noul, it is `(n·peak − 1)/(n − 1)` over the answer's own
#   distribution. Consumers never see a missing confidence.
# - **No substitution** (CT-PROV-21). A failing `decide` raises; choosing to ask an LLM instead is
#   `M-JUDGE`'s decision on a *confidence* outcome, never this module's on a *failure*.
#
# **Deviation, recorded:** design FR-PROV-16 names the per-implementation limits method
# `capabilities`. `RecordedFixtureProvider` serves both surfaces, and its `capabilities` already
# returns the `InferenceProvider`'s `Capabilities` (CT-PROV-04), so the decision surface's method
# is `decision_capabilities`. The decision-only live providers also answer to `capabilities`.

#: A question key: lowercase letters and underscores, no digits — so a key can never carry a
#: numeral into the request's rubric surface (FR-JUDGE-03, FR-PROV-17).
_DECISION_KEY = re.compile(r"\A[a-z][a-z_]{0,31}\Z")

#: Universal limits from the published object model (design §1.2). Per-implementation limits
#: are tighter and live on `DecisionCapabilities` (`DecisionRequest.validate_for`).
CHOICE_MAX_OPTIONS = 255
SCORE_MIN_LEVELS = 2
SCORE_MAX_LEVELS = 10
#: Every shipped implementation declares 64 (FR-PROV-27/32), so the cap is universal and
#: checked at construction (TC-PROV-23 j); `validate_for` still applies a tighter declared one.
DECISION_MAX_QUESTIONS = 64
#: FR-PROV-20: a distribution sums to 1 within this tolerance or the response is malformed.
PROBABILITY_SUM_TOLERANCE = 1e-3

DECISION_KEY_SCHEME = b"aeh.prov/decision-key/1"
DECISION_FIXTURE_SCHEMA = "aeh.prov/decision-fixture/1"


class DecisionRequestError(ValueError):
    """A `DecisionRequest` that cannot be sent: a caller defect caught at construction (or at
    `validate_for`), before anything leaves the process. A `ValueError`, not a `ProviderError`,
    for the reason `PromptPayload` raises one: a malformed request is not a provider failure."""


class DecisionRequestRejectedError(ProviderError):
    """The engine refused the request (HTTP 400/422). **Not retryable** (CT-PROV-20): the same
    bytes would be refused again. `M-JUDGE` treats it as a `rejected` pre-screen and falls back
    to the LLM path; a harness that keeps producing rejected requests has a defect, which the
    `decision_requests_rejected` alert surfaces."""

    retryable = False


def _check_key(key: Any) -> None:
    if not isinstance(key, str) or not _DECISION_KEY.match(key):
        raise DecisionRequestError(
            f"question key {key!r} must match {_DECISION_KEY.pattern} — lowercase letters and "
            f"underscores, no digits (FR-PROV-17)."
        )


def _check_text(value: Any, what: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not value.strip():
        raise DecisionRequestError(f"{what} must be a non-empty string, got {value!r}.")


@dataclass(frozen=True)
class ChoiceQuestion:
    """Pick one of 2…255 unordered options. `options` is `((label, description | None), …)`."""

    key: str
    instructions: str
    options: tuple[tuple[str, str | None], ...]

    def __post_init__(self) -> None:
        _check_key(self.key)
        _check_text(self.instructions, f"{self.key}.instructions")
        if not isinstance(self.options, tuple):
            raise DecisionRequestError(f"{self.key}.options must be a tuple of (label, description) pairs.")
        if not 2 <= len(self.options) <= CHOICE_MAX_OPTIONS:
            raise DecisionRequestError(
                f"Choice {self.key!r} has {len(self.options)} options; 2…{CHOICE_MAX_OPTIONS} are allowed.")
        labels = []
        for pair in self.options:
            if not (isinstance(pair, tuple) and len(pair) == 2):
                raise DecisionRequestError(f"{self.key}.options entries must be (label, description) pairs.")
            _check_text(pair[0], f"{self.key} option label")
            _check_text(pair[1], f"{self.key} option description", optional=True)
            labels.append(pair[0])
        if len(set(labels)) != len(labels):
            raise DecisionRequestError(f"Choice {self.key!r} repeats an option label.")

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(label for label, _ in self.options)


@dataclass(frozen=True)
class ScoreQuestion:
    """Place the state on an ordered scale of 2…10 level descriptions, lowest first."""

    key: str
    instructions: str
    levels: tuple[str, ...]

    def __post_init__(self) -> None:
        _check_key(self.key)
        _check_text(self.instructions, f"{self.key}.instructions")
        if not isinstance(self.levels, tuple):
            raise DecisionRequestError(f"{self.key}.levels must be a tuple of level descriptions.")
        if not SCORE_MIN_LEVELS <= len(self.levels) <= SCORE_MAX_LEVELS:
            raise DecisionRequestError(
                f"Score {self.key!r} has {len(self.levels)} levels; "
                f"{SCORE_MIN_LEVELS}…{SCORE_MAX_LEVELS} are allowed.")
        for level in self.levels:
            _check_text(level, f"{self.key} level")


@dataclass(frozen=True)
class NoulQuestion:
    """A yes/no statement; the answer is the probability it is true."""

    key: str
    instructions: str
    when_true: str | None = None
    when_false: str | None = None

    def __post_init__(self) -> None:
        _check_key(self.key)
        _check_text(self.instructions, f"{self.key}.instructions")
        _check_text(self.when_true, f"{self.key}.when_true", optional=True)
        _check_text(self.when_false, f"{self.key}.when_false", optional=True)


DecisionQuestion = ChoiceQuestion | ScoreQuestion | NoulQuestion


@dataclass(frozen=True)
class DecisionCapabilities:
    """What a decision implementation declares about itself (FR-PROV-27, the CT-PROV-04
    posture): declared, never discovered, stable for the run."""

    max_context_tokens: int
    max_choice_options: int
    max_questions: int
    cost_per_input_token: Decimal | None
    deterministic: bool


@dataclass(frozen=True)
class DecisionRequest:
    """The closed, frozen request (FR-PROV-17): a state and an ordered tuple of questions."""

    state: str
    questions: tuple[DecisionQuestion, ...]

    def __post_init__(self) -> None:
        _check_text(self.state, "DecisionRequest.state")
        if not isinstance(self.questions, tuple) or not self.questions:
            raise DecisionRequestError("DecisionRequest.questions must be a non-empty tuple.")
        if len(self.questions) > DECISION_MAX_QUESTIONS:
            raise DecisionRequestError(
                f"{len(self.questions)} questions exceed the {DECISION_MAX_QUESTIONS}-question cap.")
        keys = []
        for question in self.questions:
            if not isinstance(question, (ChoiceQuestion, ScoreQuestion, NoulQuestion)):
                raise DecisionRequestError(
                    f"DecisionRequest.questions holds a {type(question).__name__}; only "
                    f"ChoiceQuestion, ScoreQuestion and NoulQuestion exist (FR-PROV-17).")
            keys.append(question.key)
        if len(set(keys)) != len(keys):
            raise DecisionRequestError(f"DecisionRequest repeats a question key: {keys}.")

    def validate_for(self, capabilities: DecisionCapabilities) -> None:
        """The per-implementation half of FR-PROV-17: question count and Choice width against
        the implementation's declared limits. Called by every `decide` before anything is sent."""
        if len(self.questions) > capabilities.max_questions:
            raise DecisionRequestError(
                f"{len(self.questions)} questions exceed this implementation's "
                f"max_questions={capabilities.max_questions}.")
        for question in self.questions:
            if isinstance(question, ChoiceQuestion) and len(question.options) > capabilities.max_choice_options:
                raise DecisionRequestError(
                    f"Choice {question.key!r} has {len(question.options)} options; this "
                    f"implementation allows {capabilities.max_choice_options}.")


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    probabilities: Mapping[str, float]
    confidence: float
    confidence_source: str


@dataclass(frozen=True)
class ScoreAnswer:
    """`probabilities[i]` is the probability of `levels[i]`. `score` is the probability-weighted
    position; a consumer takes the band from the argmax, never from `score` (ADR-22)."""

    score: float
    probabilities: tuple[float, ...]
    confidence: float
    confidence_source: str


@dataclass(frozen=True)
class NoulAnswer:
    p_true: float
    confidence: float
    confidence_source: str = "derived"


DecisionAnswer = ChoiceAnswer | ScoreAnswer | NoulAnswer


@dataclass(frozen=True)
class Decision:
    """One answered request (FR-PROV-18): exactly one answer per question key, typed as its
    question. `cost` is null on edge-local and fixture (the CT-PROV-03 posture)."""

    answers: Mapping[str, DecisionAnswer]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    resolved_build: str
    cost: Decimal | None


def derived_confidence(probabilities: Sequence[float]) -> float:
    """TypeSafe's published statistic, `(n·peak − 1)/(n − 1)` (FR-PROV-19). With `n = 2` over
    `{p, 1 − p}` it is `|2p − 1|`, which is a Noul's confidence."""
    values = list(probabilities)
    n = len(values)
    if n < 2:
        raise ValueError("a confidence needs at least two outcomes")
    return max(0.0, min(1.0, (n * max(values) - 1.0) / (n - 1)))


def _number(value: Any, where: str) -> float:
    """A JSON number in [0, 1], or a `MalformedResponseError`. Booleans are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MalformedResponseError(f"{where} is {value!r}, not a number")
    if not 0.0 <= float(value) <= 1.0:
        raise MalformedResponseError(f"{where} = {value!r} lies outside [0, 1]")
    return float(value)


def _distribution(values: Sequence[float], where: str) -> None:
    total = math.fsum(values)
    if abs(total - 1.0) > PROBABILITY_SUM_TOLERANCE:
        raise MalformedResponseError(
            f"{where} sums to {total!r}, not 1 ± {PROBABILITY_SUM_TOLERANCE}; the answer is "
            f"refused, never renormalised (FR-PROV-20)")


def _confidence(answer: Mapping[str, Any], values: Sequence[float], where: str) -> tuple[float, str]:
    reported = answer.get("confidence")
    if reported is None:
        return derived_confidence(values), "derived"
    return _number(reported, f"{where}.confidence"), "reported"


def parse_decision(document: Any, request: DecisionRequest, *, fallback_build: str,
                   latency_ms: int = 0, cost: Decimal | None = None) -> Decision:
    """A §1.2-shaped response document to a validated `Decision`, or `MalformedResponseError`.

    The only place a decision response is interpreted, shared by every implementation so the
    fixture double refuses exactly what a live provider refuses (CT-PROV-18, CT-PROV-23)."""
    if not isinstance(document, dict):
        raise MalformedResponseError("the decision response is not a JSON object")
    answers = document.get("answers")
    if not isinstance(answers, dict):
        raise MalformedResponseError("the decision response carries no 'answers' object")
    expected = [question.key for question in request.questions]
    if set(answers) != set(expected):
        raise MalformedResponseError(
            f"answer keys {sorted(answers)} do not equal question keys {sorted(expected)}")
    parsed: dict[str, DecisionAnswer] = {}
    for question in request.questions:
        where = f"answers.{question.key}"
        raw = answers[question.key]
        if not isinstance(raw, dict):
            raise MalformedResponseError(f"{where} is not an object")
        kind = {ChoiceQuestion: "choice", ScoreQuestion: "score", NoulQuestion: "noul"}[type(question)]
        if raw.get("type") != kind:
            raise MalformedResponseError(f"{where}.type is {raw.get('type')!r}, the question is {kind!r}")
        if isinstance(question, NoulQuestion):
            p = _number(raw.get("noul"), f"{where}.noul")
            parsed[question.key] = NoulAnswer(p_true=p, confidence=derived_confidence((p, 1.0 - p)))
        elif isinstance(question, ChoiceQuestion):
            probabilities = raw.get("probabilities")
            if not isinstance(probabilities, dict) or set(probabilities) != set(question.labels):
                raise MalformedResponseError(f"{where}.probabilities keys do not equal the options")
            values = {label: _number(probabilities[label], f"{where}.probabilities.{label}")
                      for label in question.labels}
            _distribution(list(values.values()), f"{where}.probabilities")
            choice = raw.get("choice")
            if choice not in values:
                raise MalformedResponseError(f"{where}.choice {choice!r} is not one of the options")
            confidence, source = _confidence(raw, list(values.values()), where)
            parsed[question.key] = ChoiceAnswer(choice, values, confidence, source)
        else:
            count = len(question.levels)
            indices = [str(i) for i in range(count)]
            probabilities = raw.get("probabilities")
            if not isinstance(probabilities, dict) or set(probabilities) != set(indices):
                raise MalformedResponseError(f"{where}.probabilities must cover exactly indices 0…{count - 1}")
            legend = raw.get("legend")
            # Required, not optional: the legend is the only evidence that index i means
            # levels[i], and an off-by-one there is a plausible wrong band (RISK-62).
            if not isinstance(legend, dict) or set(legend) != set(indices) or any(
                    legend[str(i)] != question.levels[i] for i in range(count)):
                raise MalformedResponseError(f"{where}.legend is missing or does not name the requested levels in order")
            values = tuple(_number(probabilities[i], f"{where}.probabilities.{i}") for i in indices)
            _distribution(values, f"{where}.probabilities")
            score = raw.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise MalformedResponseError(f"{where}.score is {score!r}, not a number")
            confidence, source = _confidence(raw, values, where)
            parsed[question.key] = ScoreAnswer(float(score), values, confidence, source)
    usage = document.get("usage") or {}
    if not isinstance(usage, dict):
        raise MalformedResponseError("the decision response 'usage' is not an object")
    tokens = {}
    for name in ("input_tokens", "output_tokens"):
        value = usage.get(name, 0) or 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MalformedResponseError(f"usage.{name} is {value!r}, not a non-negative integer")
        tokens[name] = value
    served = document.get("model") or document.get("provider")
    return Decision(
        answers=MappingProxyType(parsed),
        tokens_in=tokens["input_tokens"],
        tokens_out=tokens["output_tokens"],
        latency_ms=int(latency_ms),
        resolved_build=served if isinstance(served, str) and served else fallback_build,
        cost=cost,
    )


def decision_questions_document(request: DecisionRequest) -> dict[str, Any]:
    """The §1.2 `questions` object, in the caller's question order. The one encoder the live
    providers build their bodies from, so every backend receives the same questions."""
    out: dict[str, Any] = {}
    for q in request.questions:
        if isinstance(q, ChoiceQuestion):
            out[q.key] = {"type": "choice", "instructions": q.instructions,
                          "criteria": {label: desc for label, desc in q.options}}
        elif isinstance(q, ScoreQuestion):
            out[q.key] = {"type": "score", "instructions": q.instructions, "criteria": list(q.levels)}
        else:
            entry: dict[str, Any] = {"type": "noul", "instructions": q.instructions}
            if q.when_true is not None or q.when_false is not None:
                entry["criteria"] = {"true": q.when_true, "false": q.when_false}
            out[q.key] = entry
    return out


def decision_request_key(request: DecisionRequest, model_ref: ModelRef) -> str:
    """`sha256` over the full `DecisionRequest` and `ModelRef` (FR-PROV-25), framed as
    `request_key` is. A distinct scheme tag, so no completion fixture can answer a decision."""
    digest = hashlib.sha256()
    digest.update(_frame(DECISION_KEY_SCHEME))
    digest.update(_frame(b"state"))
    _emit_framed(digest.update, request.state.encode("utf-8"))
    digest.update(_frame(b"questions"))
    digest.update(len(request.questions).to_bytes(_FRAME_WIDTH, "big"))
    for q in request.questions:
        if isinstance(q, ChoiceQuestion):
            parts: tuple[Any, ...] = ("choice", q.key, q.instructions,
                                      tuple(item for pair in q.options for item in pair))
        elif isinstance(q, ScoreQuestion):
            parts = ("score", q.key, q.instructions, q.levels)
        else:
            parts = ("noul", q.key, q.instructions, q.when_true, q.when_false)
        for part in parts:
            digest.update(_encode_scalar(part))
    digest.update(_frame(b"model_ref"))
    for name in _MODEL_REF_FIELDS:
        digest.update(_frame(name.encode("utf-8")))
        digest.update(_encode_scalar(getattr(model_ref, name)))
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class DecisionCounters:
    """FR-PROV-29 / CT-PROV-24: the decision counters, by their contract names."""

    decision_calls: int
    decision_tokens_in: int
    decision_transport_retries: int
    decision_rate_limited_calls: int
    decision_actual_cost: Decimal


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
_UNSHIPPED_DECISION_PROVIDERS = {
    "openjev": "OpenJevLocalProvider (#443)",
    "openjev-small": "OpenJevSmallLocalProvider (#455)",
}


def decision_provider_for(model_ref: ModelRef, **seams: Any) -> "DecisionProvider":
    """The only construction path for a decision provider (FR-PROV-26), by `ModelRef.provider`.
    Unknown names raise `ConfigurationError`; nothing is substituted."""
    name = str(getattr(model_ref, "provider", "") or "")
    if name == "fixture":
        return RecordedFixtureProvider(**seams)
    if name == "openrouter-jev":
        return JevOpenRouterProvider(**seams)
    if name in _UNSHIPPED_DECISION_PROVIDERS:
        raise ConfigurationError(
            f"decision provider {name!r} is designed but not shipped yet: "
            f"{_UNSHIPPED_DECISION_PROVIDERS[name]}.")
    raise ConfigurationError(
        f"no decision provider is named {name!r}; the decision providers are "
        f"{sorted(['fixture', 'openrouter-jev', *_UNSHIPPED_DECISION_PROVIDERS])} (FR-PROV-26).")


#: Every error a live decision provider can raise (FR-PROV-23), so the double can declare each.
_DECISION_ERRORS: dict[str, type[Exception]] = {
    cls.__name__: cls for cls in (
        ConfigurationError, DecisionRequestRejectedError, MalformedResponseError, TransportError, RateLimitedError,
        ProviderUnavailableError, BuildChangedError, RetentionPolicyError)
}


def _decision_request_record(request: DecisionRequest, model_ref: ModelRef) -> dict[str, Any]:
    return {"state": request.state, "questions": decision_questions_document(request),
            "model_ref": {name: getattr(model_ref, name) for name in _MODEL_REF_FIELDS}}



# --- the live decision providers (FR-PROV-21…24, FR-PROV-28) --------------------------------------

JEV_OPENROUTER_URL_ENV = "HARNESS_JEV_OPENROUTER_URL"
DEFAULT_JEV_OPENROUTER_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_OPENROUTER_PROVIDER_ENV = "HARNESS_JEV_OPENROUTER_PROVIDER"
#: The upstream OpenRouter routes Jev to, pinned in `provider.order` (FR-PROV-11/21).
#: Assumption: TypeSafe serves its own model; the knob exists for when that is not so.
DEFAULT_JEV_OPENROUTER_PROVIDER = "typesafe"
JEV_COST_PER_MTOK_IN_ENV = "HARNESS_JEV_COST_PER_MTOK_IN"
DEFAULT_JEV_COST_PER_MTOK_IN = Decimal("0.042")
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

    def _decide_http(self, request: DecisionRequest, model_ref: ModelRef, url: str,
                     headers: dict[str, str], body: bytes, fallback_build: str) -> Decision:
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
            usage = document.get("usage") if isinstance(document, dict) else None
            cost = None
            if self._billed and isinstance(usage, dict) and usage.get("cost") is not None:
                try:
                    cost = Decimal(str(usage["cost"]))
                except Exception as exc:  # noqa: BLE001
                    raise MalformedResponseError(f"usage.cost is not a decimal: {usage['cost']!r}") from exc
            return parse_decision(document, request, fallback_build=fallback_build, cost=cost)

        decision = dispatch_with_retries(
            self._transport, lambda: HttpRequest("POST", url, headers, body), parse,
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


def _jev_wire_model(build_id: str) -> str:
    """The OpenRouter model slug for a pinned build: `openrouter/` and `@<pin>` removed
    (FR-PROV-21). A floating alias is refused: the grader must not change under a run."""
    slug = build_id[len("openrouter/"):] if build_id.startswith("openrouter/") else build_id
    slug = slug.split("@", 1)[0]
    if not slug or slug.startswith("~") or slug.endswith("-latest") or ":latest" in slug:
        raise ConfigurationError(
            f"decision build {build_id!r} names a floating alias; pin a versioned Jev slug such "
            f"as 'openrouter/typesafe/jev-1.13@<pin>' (FR-PROV-21, FR-CONF-20).")
    return slug


class JevOpenRouterProvider(_BaseDecisionProvider):
    """Jev on OpenRouter — the connected configuration's decision engine (FR-PROV-21).

    POSTs typed questions to OpenRouter's Decisions API for a pinned Jev build, with the
    upstream pinned, fallbacks disabled and zero-retention routing requested. Separate from the
    local providers by design (user directive); it shares only `_BaseDecisionProvider`."""

    _billed = True

    def __init__(self, *, api_key: str | None = None, url: str | None = None,
                 session_id: str | None = None,
                 retention_answers: Callable[[str], str] | None = None, **seams: Any) -> None:
        seams.setdefault("timeout_s", _env_positive_float(JEV_TIMEOUT_S_ENV, DEFAULT_JEV_TIMEOUT_S))
        super().__init__(**seams)
        self._api_key = api_key if api_key is not None else os.environ.get(OPENROUTER_API_KEY_ENV)
        self._url = url if url is not None else (os.environ.get(JEV_OPENROUTER_URL_ENV) or DEFAULT_JEV_OPENROUTER_URL)
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
        document: dict[str, Any] = {
            "model": wire_model,
            "state": request.state,
            "questions": decision_questions_document(request),
            "provider": {"order": [self._upstream], "allow_fallbacks": False,
                         "data_collection": "deny", "zdr": True},
        }
        document["session_id"] = self._session_id
        body = json.dumps(document, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        return self._decide_http(request, model_ref, self._url, headers, body, fallback_build=wire_model)

    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport:
        """Zero-retention confirmation for the decision model, fail-closed exactly as
        `OpenRouterProvider.verify_retention` (FR-PROV-28). An unconfirmed model raises and
        arms `decide`'s refusal."""
        confirmed: list[ModelRef] = []
        unconfirmed: list[ModelRef] = []
        for ref in model_refs:
            if self._retention_answers is not None:
                answer = self._retention_answers(ref.build_id)
            else:
                answer = None  # no confirmation source: unconfirmed, fail-closed
            (confirmed if _is_retention_confirmed(answer) else unconfirmed).append(ref)
        if unconfirmed:
            self._retention_gate_failed = True
            raise RetentionPolicyError(
                f"zero-retention routing unconfirmed for decision model(s): "
                f"{'; '.join(r.build_id for r in unconfirmed)}. The run does not start (FR-PROV-28).")
        return RetentionReport(confirmed=tuple(confirmed), unconfirmed=())

# --- the recorded-fixture implementation ------------------------------------------------------

#: Bumping this makes every existing fixture file unreadable, which is the correct behaviour
#: for a format change: a recording whose shape this code no longer understands must miss,
#: not be half-parsed.
FIXTURE_SCHEMA = "aeh.prov/fixture/1"


class RecordedFixtureProvider:
    """`FR-PROV-10` — the hermetic model boundary, and the fast tier's whole model story.

    A recording is looked up by `request_key` under `fixture_dir`, content-addressed one file
    per request. An unknown request raises `FixtureMissingError`; there is no code path from
    here to a socket, so the hermeticity `CT-PROV-10` claims holds with the network wide open
    rather than only under a guard.

    What it deliberately does *not* do:

    - **Measure anything.** `latency_ms` and the token counts are replayed from the recording.
      A measured latency would make two replays of one fixture unequal, and `TC-PROV-13`
      compares the whole `Completion` by equality.
    - **Normalize the request.** There is one key and it is the hash of the assembled request;
      a changed prompt is a different request and misses.
    - **Fall back.** `CT-PROV-08` has no exception for the test tier.
    """

    def __init__(self, fixture_dir: str | os.PathLike[str] | None = None) -> None:
        """Bind a fixture directory and freeze the declared capabilities.

        `fixture_dir` defaults to `HARNESS_FIXTURE_DIR` (design §3.2 Configuration). The
        environment is read **here and never again**: `CT-PROV-04` requires the declared
        capabilities to be stable for the life of the run, and a `capabilities()` that
        re-read `os.environ` would answer differently after any test that touched it.
        """
        configured = fixture_dir if fixture_dir is not None else os.environ.get(FIXTURE_DIR_ENV)
        if configured is None or (isinstance(configured, str) and not configured.strip()):
            raise ConfigurationError(
                f"RecordedFixtureProvider needs a fixture directory: pass fixture_dir= or set "
                f"{FIXTURE_DIR_ENV}. It is not defaulted, because a provider silently pointed "
                f"at an empty directory reports every request as missing (FR-PROV-10)."
            )
        self._fixture_dir = Path(configured)
        self._capabilities = Capabilities(
            supports_seed=True,
            # True, although nothing here caches: the fixture replays the recorded backend's
            # `cached_prefix_tokens`, and a double that declared `False` would send `M-JUDGE`
            # down a different prompt-ordering path than the backend it stands in for — the
            # drift NFR-PROV-01 forbids and RISK-37 describes.
            supports_prefix_cache=True,
            max_concurrency=_fixture_max_concurrency(),
            # A claim, per CT-PROV-04 — and for this implementation a true one: replay of a
            # stored response is deterministic by construction. That does not make CT-PROV-16
            # any less a non-promise for the backends this stands in for.
            deterministic_at_temperature_zero=True,
            # Nothing is billed, so nothing is measured (CT-PROV-03).
            cost_per_token=None,
        )

    @property
    def fixture_dir(self) -> Path:
        return self._fixture_dir

    # -- the interface -----------------------------------------------------------------------

    def complete(
        self, prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams
    ) -> Completion:
        """Return the recording for this exact request, or raise. Never reaches the network."""
        key = request_key(prompt, model_ref, params)
        path = self._path_for(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # FileNotFoundError only. A permission error is an environment problem and
            # surfaces as itself: reporting it as a miss would send whoever reads the failure
            # looking for a recording that is sitting right there.
            raise FixtureMissingError(
                f"no recording for request {key} under {self._fixture_dir}. The key covers "
                f"the assembled payload, the model ref and every sampling parameter "
                f"(FR-PROV-10), so a changed prompt misses rather than being answered by a "
                f"stale recording. Record it, or fix the prompt that changed."
            ) from None

        document = _fixture_document(raw, path, key)
        if document.get("request") != _request_record(prompt, model_ref, params):
            # Only reachable through a sha256 collision or a hand-edited file. Loud either
            # way: the failure this whole module is arranged around is a stale recording
            # answering a request it never saw.
            raise FixtureMissingError(
                f"the recording at {path} is keyed {key} but stores a different request. "
                f"Treated as a miss: answering it would be exactly the stale-fixture failure "
                f"TC-PROV-14 exists to prevent."
            )

        completion = _completion_from_document(document, path)
        _LOGGER.debug(
            # CT-PROV-14's per-call fields, by name. Metadata only — payload values are
            # student work and never reach a log line (CT-PROV-13).
            "provider call",
            extra={
                "model_ref": model_ref.build_id,
                "resolved_build": completion.resolved_build,
                "latency_ms": completion.latency_ms,
                "tokens_in": completion.tokens_in,
                "tokens_out": completion.tokens_out,
                "retry_count": 0,  # replay cannot fail transiently; #19 owns the loop
                "request_key": key,
            },
        )
        return completion

    def capabilities(self, model_ref: ModelRef) -> Capabilities:
        """Declared, not discovered — answers with the transport blocked (`CT-PROV-04`).

        `model_ref` is accepted and unused: the declaration is a property of the
        implementation, and every ref this provider serves is served by replay.
        """
        return self._capabilities

    def estimate_cost(self, plan: CallPlan) -> CostEstimate:
        """A pure function of the plan and the declared per-token cost. Dispatches nothing.

        `cost` is `None` here because `cost_per_token` is: replay is not billed, and a figure
        of zero would read as a measured price rather than an absent one (`CT-PROV-03`).
        `FR-PROV-09`'s running `actual_cost` arrives with #20.
        """
        for name in ("calls", "tokens_in_per_call", "tokens_out_per_call"):
            value = getattr(plan, name)
            if value < 0:
                raise ValueError(f"CallPlan.{name} must be non-negative, got {value}.")
        tokens_in = plan.calls * plan.tokens_in_per_call
        tokens_out = plan.calls * plan.tokens_out_per_call
        per_token = self._capabilities.cost_per_token
        cost = None if per_token is None else Decimal(tokens_in + tokens_out) * per_token
        return CostEstimate(
            calls=plan.calls, tokens_in=tokens_in, tokens_out=tokens_out, cost=cost
        )

    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport:
        """Every ref confirmed: replay sends nothing anywhere, so nothing can be retained.

        Stated rather than skipped. `CT-PROV-13` asserts the *call order* — retention
        confirmed for every panel member before the first dispatch — and a fixture provider
        that raised `NotImplementedError` here would make that ordering unassertable in the
        fast tier, leaving it to the nightly live runs alone.
        """
        return RetentionReport(confirmed=tuple(model_refs), unconfirmed=())

    # -- the decision surface (FR-PROV-25) --------------------------------------------------

    def decide(self, request: DecisionRequest, model_ref: ModelRef) -> Decision:
        """The recorded answer to this exact `DecisionRequest`, or raise. Never reaches the
        network (CT-PROV-23). A stored answer passes through `parse_decision`, so a malformed
        recording is refused exactly as a malformed live response would be (CT-PROV-18), and
        a recording that declares an error raises that error by type."""
        if not isinstance(request, DecisionRequest):
            raise TypeError(f"decide takes a DecisionRequest, got {type(request).__name__}")
        request.validate_for(_FIXTURE_DECISION_CAPABILITIES)
        key = decision_request_key(request, model_ref)
        path = self._path_for(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FixtureMissingError(
                f"no decision recording for request {key} under {self._fixture_dir}. The key "
                f"covers the state, every question and the model ref (FR-PROV-25), so a "
                f"changed request misses rather than being answered by a stale recording."
            ) from None
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FixtureMissingError(f"the decision recording at {path} is not valid JSON ({exc}).") from None
        if not isinstance(document, dict) or document.get("schema") != DECISION_FIXTURE_SCHEMA:
            raise FixtureMissingError(
                f"the recording at {path} is not a {DECISION_FIXTURE_SCHEMA} document.")
        if document.get("key") != key or document.get("request") != _decision_request_record(request, model_ref):
            raise FixtureMissingError(
                f"the recording at {path} is keyed or stored for a different request; treated "
                f"as a miss (the stale-fixture failure TC-PROV-14 guards).")
        error = document.get("error")
        if error is not None:
            cls = _DECISION_ERRORS.get(str(error.get("type")) if isinstance(error, dict) else "")
            if cls is None:
                raise FixtureMissingError(f"the recording at {path} declares an unknown error {error!r}.")
            raise cls(str(error.get("message") or f"recorded {cls.__name__}"))
        response = document.get("response")
        if isinstance(response, dict) and (response.get("usage") or {}).get("cost") is not None:
            raise FixtureMissingError(
                f"the recording at {path} stores a cost; fixture decisions are unbilled "
                f"(the CT-PROV-03 posture), and record_decision refuses to write one.")
        return parse_decision(response, request, fallback_build=model_ref.build_id,
                              latency_ms=int(document.get("latency_ms", 0) or 0), cost=None)

    def decision_capabilities(self, model_ref: ModelRef) -> DecisionCapabilities:
        """Declared, not discovered (FR-PROV-27): the widest published limits, unbilled."""
        return _FIXTURE_DECISION_CAPABILITIES

    def record_decision(self, request: DecisionRequest, model_ref: ModelRef,
                        response: Mapping[str, Any] | None = None, *,
                        error: tuple[str, str] | None = None, latency_ms: int = 0) -> str:
        """Store a §1.2 response document (or a declared error, `(type_name, message)`) as the
        answer to this exact request. Returns the key. Exactly one of `response`/`error`."""
        if (response is None) == (error is None):
            raise ValueError("record_decision takes exactly one of response= or error=")
        if error is not None and error[0] not in _DECISION_ERRORS:
            raise ValueError(f"unknown decision error type {error[0]!r}; one of {sorted(_DECISION_ERRORS)}")
        if response is not None:
            if (response.get("usage") or {}).get("cost") is not None:
                raise ValueError("fixture decisions are unbilled; strip usage.cost before recording")
            parse_decision(dict(response), request, fallback_build=model_ref.build_id)
        key = decision_request_key(request, model_ref)
        document = {
            "schema": DECISION_FIXTURE_SCHEMA, "key": key,
            "request": _decision_request_record(request, model_ref),
            "latency_ms": int(latency_ms),
        }
        if response is not None:
            document["response"] = dict(response)
        else:
            document["error"] = {"type": error[0], "message": error[1]}
        self._fixture_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(key)
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return key

    # -- the recording half ------------------------------------------------------------------

    def record(
        self,
        prompt: PromptPayload,
        model_ref: ModelRef,
        params: SamplingParams,
        completion: Completion,
    ) -> str:
        """Store `completion` as the answer to this exact request. Returns the key.

        The one operation here that the design does not name. `FR-PROV-10` fixes the *lookup*
        and test plan §4.4 says `F-RECORDED` is "regenerated nightly", so a recording path
        must exist — but nothing specifies it, so the name and signature are chosen here and
        raised as a finding on the PR.

        A non-null `cost` is refused rather than stored. `CT-PROV-03` makes fixture ⇒ `cost is
        None`, so a recording carrying a cloud cost would put the canonical double in direct
        contradiction with the clause every consumer above it tests against (RISK-37). The
        nightly regeneration path nulls the cost before recording; storing it silently, or
        normalizing it here without saying so, both end with the double drifting.
        """
        if completion.cost is not None:
            raise ValueError(
                f"refusing to record a Completion carrying cost={completion.cost!r}: "
                f"CT-PROV-03 makes cost null on fixture and edge-local, so a stored cost "
                f"would make this double contradict the clause its consumers test against. "
                f"Null the cost when regenerating from a live backend."
            )

        key = request_key(prompt, model_ref, params)
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema": FIXTURE_SCHEMA,
            "key": key,
            "request": _request_record(prompt, model_ref, params),
            "completion": {
                **{name: getattr(completion, name) for name in _COMPLETION_FIELDS},
                # Never `completion.cost`: refused above, and written as null so the file
                # cannot disagree with CT-PROV-03 even if this branch is ever reached.
                "cost": None,
            },
        }
        # Written whole and then moved into place: a half-written recording read by a
        # concurrent reader would raise a JSON error, which is neither a hit nor the miss the
        # caller could act on. The temp name is unique rather than derived from the key, so
        # two writers recording the same request cannot contend on one path.
        handle, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=path.name + ".", suffix=".partial"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, path)
        except BaseException:
            # A temp file left behind is not a recording, but it is litter in a directory the
            # nightly regeneration diffs by hand.
            Path(temporary).unlink(missing_ok=True)
            raise
        return key

    # -- internals ---------------------------------------------------------------------------

    def _path_for(self, key: str) -> Path:
        # The key is `sha256:<hex>`; the colon is illegal in a Windows filename and is an NTFS
        # alternate-data-stream separator, so it is replaced rather than escaped.
        return self._fixture_dir / f"{key.replace(':', '-')}.json"


def _fixture_max_concurrency() -> int:
    """`HARNESS_FIXTURE_MAX_CONCURRENCY`, or the reference figure. Seam 3."""
    raw = os.environ.get(FIXTURE_MAX_CONCURRENCY_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_FIXTURE_MAX_CONCURRENCY
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigurationError(
            f"{FIXTURE_MAX_CONCURRENCY_ENV} must be a positive integer, got {raw!r}."
        ) from None
    if value < 1:
        raise ConfigurationError(
            f"{FIXTURE_MAX_CONCURRENCY_ENV} must be at least 1, got {value}."
        )
    return value


def _jsonable(value: Any) -> Any:
    """A `SamplingParams` value as JSON, so a stored request compares equal to a fresh one.

    JSON has no tuple, so `stop=()` round-trips as `[]`; building the record with lists from
    the start is what keeps the comparison in `complete()` an equality rather than a
    normalization pass with its own bugs.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    raise ValueError(
        f"cannot store {type(value).__name__} in a fixture request record. Add a branch here "
        f"when adding a SamplingParams field of a new type."
    )


def _request_record(
    prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams
) -> dict[str, Any]:
    """The assembled request, as the fixture file stores it.

    Stored alongside the response so a recording can be read by a human and so a key that
    somehow matched the wrong request fails loudly. Not the key itself — `request_key` hashes
    a framed encoding, and this is JSON.
    """
    return {
        "fields": [[name, value] for name, value in prompt.fields],
        "model_ref": {name: getattr(model_ref, name) for name in _MODEL_REF_FIELDS},
        "params": {
            field.name: _jsonable(getattr(params, field.name))
            for field in dataclasses.fields(params)
        },
    }


_COMPLETION_FIELDS = (
    "text",
    "tokens_in",
    "tokens_out",
    "latency_ms",
    "resolved_build",
    "cached_prefix_tokens",
)


def _fixture_document(raw: str, path: Path, key: str) -> dict[str, Any]:
    """Parse a fixture file and check its identity, or raise `FixtureMissingError`.

    Every way a file on disk can fail to be a usable recording lands inside the taxonomy
    (`CT-PROV-07`): a caller catching `ProviderError` is catching what this module promised to
    raise, and a bare `JSONDecodeError` or `AttributeError` out of a corrupt fixture is a hole
    in that promise. The fast tier is where corrupt fixtures actually appear — `F-RECORDED` is
    regenerated nightly and its diffs are read by hand (test plan §4.4).

    The schema check is what makes bumping `FIXTURE_SCHEMA` mean anything. Without it the
    constant is decoration: a recording written under a format this code no longer understands
    would be half-parsed rather than missed.
    """
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FixtureMissingError(
            f"the recording at {path} is not valid JSON ({exc}). Unusable rather than absent: "
            f"the file is there, and it is the file that is wrong."
        ) from None
    if not isinstance(document, dict):
        raise FixtureMissingError(
            f"the recording at {path} is a {type(document).__name__}, not a "
            f"{FIXTURE_SCHEMA} document."
        )
    schema = document.get("schema")
    if schema != FIXTURE_SCHEMA:
        raise FixtureMissingError(
            f"the recording at {path} declares schema {schema!r}, not {FIXTURE_SCHEMA!r}. A "
            f"recording whose shape this code no longer understands must miss, not be "
            f"half-parsed."
        )
    stored_key = document.get("key")
    if stored_key != key:
        raise FixtureMissingError(
            f"the recording at {path} declares key {stored_key!r} but was found under {key}. "
            f"A file moved between key paths cannot be trusted to answer either."
        )
    return document


def _completion_from_document(document: dict[str, Any], path: Path) -> Completion:
    """Rebuild a `Completion` from a parsed recording, or say which file is wrong.

    A stored non-null `cost` is **refused, not normalized**. `record()` refuses to write one
    (`CT-PROV-03`: fixture ⇒ null), and the reader is the path every fast-tier test runs — so
    quietly reading it back as `None` would make the loud rule silent exactly where it
    matters. Refusing gives the same protection and says so.
    """
    completion = document.get("completion")
    if not isinstance(completion, dict):
        raise FixtureMissingError(
            f"the recording at {path} has no completion object; it is not a "
            f"{FIXTURE_SCHEMA} fixture."
        )
    if completion.get("cost") is not None:
        raise FixtureMissingError(
            f"the recording at {path} stores cost={completion['cost']!r}. CT-PROV-03 makes "
            f"cost null on fixture and edge-local, so this file contradicts the clause its "
            f"consumers test against, and record() refuses to write one."
        )
    try:
        fields = {name: completion[name] for name in _COMPLETION_FIELDS}
    except KeyError as exc:
        raise FixtureMissingError(
            f"the recording at {path} is missing {exc.args[0]!r}. Every Completion field but "
            f"cost is non-nullable (CT-PROV-03), so a partial recording is not a hit."
        ) from None
    try:
        return Completion(cost=None, **fields)
    except ValueError as exc:
        # `Completion.__post_init__` guards shape. Reached only from a hand-edited file, so it
        # is a bad fixture rather than a caller defect, and belongs in the taxonomy.
        raise FixtureMissingError(
            f"the recording at {path} does not hold a well-formed Completion: {exc}"
        ) from None
