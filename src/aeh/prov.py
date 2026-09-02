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
import hashlib
import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
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
    their wire body from it, and for the differential itself.
    """
    return b"".join(
        _frame(name.encode("utf-8")) + _frame(value.encode("utf-8"))
        for name, value in prompt.fields
    )


def request_key(
    prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams
) -> str:
    """`sha256` over the fully-assembled request: payload, model ref and sampling params.

    Everything that would change what a backend returns is in here, which is what makes
    `TC-PROV-14` pass for the right reason: a punctuation byte, a whitespace change, a case
    change, a different build and a different temperature each move the key, because each is
    part of the request rather than of a normalized view of it.

    Streamed into the hasher rather than assembled into a buffer. `NFR-PROV-02` forbids a
    per-call copy of the invariant prefix — the prefix is a shared string the caller owns, and
    hashing it in place means an observed `cache_hit_rate` reflects the caller's prompt
    ordering rather than this module's allocation behaviour (`CT-PROV-12`).

    The element counts go in ahead of the elements. Framing alone decodes unambiguously
    *within* a section; the counts are what keep a payload field named `"model_ref"` from
    being read as the start of the next section.
    """
    digest = hashlib.sha256()
    digest.update(_frame(KEY_SCHEME))

    digest.update(_frame(b"payload"))
    digest.update(len(prompt.fields).to_bytes(_FRAME_WIDTH, "big"))
    for name, value in prompt.fields:
        digest.update(_frame(name.encode("utf-8")))
        digest.update(_frame(value.encode("utf-8")))

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
            # FileNotFoundError only: a permission or decoding error is a broken fixture set,
            # and reporting it as a miss would send whoever reads the failure looking for a
            # recording that is sitting right there.
            raise FixtureMissingError(
                f"no recording for request {key} under {self._fixture_dir}. The key covers "
                f"the assembled payload, the model ref and every sampling parameter "
                f"(FR-PROV-10), so a changed prompt misses rather than being answered by a "
                f"stale recording. Record it, or fix the prompt that changed."
            ) from None

        record = json.loads(raw)
        if record.get("request") != _request_record(prompt, model_ref, params):
            # Only reachable through a sha256 collision or a hand-edited file. Loud either
            # way: the failure this whole module is arranged around is a stale recording
            # answering a request it never saw.
            raise FixtureMissingError(
                f"the recording at {path} is keyed {key} but stores a different request. "
                f"Treated as a miss: answering it would be exactly the stale-fixture failure "
                f"TC-PROV-14 exists to prevent."
            )

        completion = _completion_from_record(record.get("completion"), path)
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
        if plan.calls < 0:
            raise ValueError(f"CallPlan.calls must be non-negative, got {plan.calls}.")
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
                "text": completion.text,
                "tokens_in": completion.tokens_in,
                "tokens_out": completion.tokens_out,
                "latency_ms": completion.latency_ms,
                "resolved_build": completion.resolved_build,
                "cached_prefix_tokens": completion.cached_prefix_tokens,
                "cost": None,
            },
        }
        # Written whole and then moved into place: a half-written recording read by a
        # concurrent reader would raise a JSON error, which is neither a hit nor the miss the
        # caller could act on.
        temporary = path.with_name(path.name + ".partial")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)
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


def _completion_from_record(raw: Any, path: Path) -> Completion:
    """Rebuild a `Completion` from a fixture file, or say which file is wrong.

    `cost` is read back as `None` unconditionally rather than parsed: `record()` refuses to
    store anything else, so a non-null value here means the file was hand-edited into
    contradiction with `CT-PROV-03`, and honouring it would let an edited fixture teach a
    consumer that fixture calls carry a cost.
    """
    if not isinstance(raw, dict):
        raise FixtureMissingError(
            f"the recording at {path} has no completion object; it is not a "
            f"{FIXTURE_SCHEMA} fixture."
        )
    try:
        return Completion(
            text=raw["text"],
            tokens_in=raw["tokens_in"],
            tokens_out=raw["tokens_out"],
            latency_ms=raw["latency_ms"],
            resolved_build=raw["resolved_build"],
            cached_prefix_tokens=raw["cached_prefix_tokens"],
            cost=None,
        )
    except KeyError as exc:
        raise FixtureMissingError(
            f"the recording at {path} is missing {exc.args[0]!r}. Every Completion field but "
            f"cost is non-nullable (CT-PROV-03), so a partial recording is not a hit."
        ) from None
