"""`RecordedFixtureProvider`: answers every call from a recording, with no network."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from aeh.conf import ConfigurationError, ModelRef

from .settings import (
    DEFAULT_FIXTURE_MAX_CONCURRENCY,
    FIXTURE_DIR_ENV,
    FIXTURE_MAX_CONCURRENCY_ENV,
    _LOGGER,
)
from .errors import FixtureMissingError
from .records import (
    CallPlan,
    Capabilities,
    Completion,
    CostEstimate,
    PromptPayload,
    RetentionReport,
    SamplingParams,
)
from .request_key import _MODEL_REF_FIELDS, request_key
from .decision_types import (
    Decision,
    DECISION_FIXTURE_SCHEMA,
    DecisionCapabilities,
    DecisionRequest,
)
from .decision_parsing import confidence_rule, decision_request_key, parse_decision
from .decision_base import (
    _DECISION_ERRORS,
    _decision_request_record,
    _FIXTURE_DECISION_CAPABILITIES,
)


# --- the recorded-fixture implementation ------------------------------------------------------

#: Bumping this makes every existing fixture file unreadable, which is the correct behaviour
#: for a format change: a recording whose shape this code no longer understands must miss,
#: not be half-parsed.
FIXTURE_SCHEMA = "aeh.prov/fixture/1"


class RecordedFixtureProvider:
    """Answers every call from recordings on disk, with no network at all (FR-PROV-10). The fast
    test tier uses only this provider.

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
        """Bind a fixture directory and fix the declared capabilities.

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
        """Return the recording for exactly this request, or raise. Never touches the network."""
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
        """The declared capabilities, available even with the network blocked (CT-PROV-04).

        `model_ref` is accepted and unused: the declaration is a property of the
        implementation, and every ref this provider serves is served by replay.
        """
        return self._capabilities

    def estimate_cost(self, plan: CallPlan) -> CostEstimate:
        """The estimated cost, computed from the plan and the declared per-token cost. Sends
        nothing.

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
        """Confirms every reference: replay sends nothing anywhere, so nothing can be retained.

        Stated rather than skipped. `CT-PROV-13` asserts the *call order* — retention
        confirmed for every panel member before the first dispatch — and a fixture provider
        that raised `NotImplementedError` here would make that ordering unassertable in the
        fast tier, leaving it to the nightly live runs alone.
        """
        return RetentionReport(confirmed=tuple(model_refs), unconfirmed=())

    # -- the decision surface (FR-PROV-25) --------------------------------------------------

    def decide(self, request: DecisionRequest, model_ref: ModelRef) -> Decision:
        """The recorded answer to exactly this `DecisionRequest`, or raise. Never touches the
        network (CT-PROV-23). A stored answer goes through `parse_decision`, so a malformed
        recording is refused just like a malformed live response (CT-PROV-18), and a recording of
        an error raises that error type."""
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
                              latency_ms=int(document.get("latency_ms", 0) or 0), cost=None,
                              rule=confidence_rule(model_ref))

    def decision_capabilities(self, model_ref: ModelRef) -> DecisionCapabilities:
        """The declared decision capabilities (FR-PROV-27): the widest published limits, with no
        billing."""
        return _FIXTURE_DECISION_CAPABILITIES

    def record_decision(self, request: DecisionRequest, model_ref: ModelRef,
                        response: Mapping[str, Any] | None = None, *,
                        error: tuple[str, str] | None = None, latency_ms: int = 0) -> str:
        """Store an engine response document (design §1.2), or an error as `(type_name, message)`,
        as the answer to exactly this request. Returns the key. Pass exactly one of `response` and
        `error`."""
        if (response is None) == (error is None):
            raise ValueError("record_decision takes exactly one of response= or error=")
        if error is not None and error[0] not in _DECISION_ERRORS:
            raise ValueError(f"unknown decision error type {error[0]!r}; one of {sorted(_DECISION_ERRORS)}")
        if response is not None:
            if (response.get("usage") or {}).get("cost") is not None:
                raise ValueError("fixture decisions are unbilled; strip usage.cost before recording")
            parse_decision(dict(response), request, fallback_build=model_ref.build_id,
                           rule=confidence_rule(model_ref))
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
        """Store `completion` as the answer to exactly this request. Returns the key.

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
    """`HARNESS_FIXTURE_MAX_CONCURRENCY`, or the reference value when unset."""
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
    """The assembled request as a fixture file stores it.

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
    """Parse a fixture file and check it is the right recording, or raise `FixtureMissingError`.

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
