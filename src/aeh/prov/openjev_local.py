"""OpenJev and OpenJevSmall served on loopback: the local decision engines."""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Sequence
from typing import Any

from aeh.conf import ConfigurationError, ModelRef

from .errors import BuildChangedError, MalformedResponseError, ProviderUnavailableError
from .records import RetentionReport
from .transport import HttpRequest
from .decision_types import Decision, DECISION_MAX_QUESTIONS, DecisionCapabilities, DecisionRequest
from .decision_parsing import decision_questions_document
from .decision_base import _BaseDecisionProvider, _env_positive_float


OPENJEV_BASE_URL_ENV = "HARNESS_OPENJEV_BASE_URL"


DEFAULT_OPENJEV_BASE_URL = "http://127.0.0.1:3000"


OPENJEV_MODEL_NAME_ENV = "HARNESS_OPENJEV_MODEL_NAME"


DEFAULT_OPENJEV_MODEL_NAME = "openjev"


OPENJEV_VLLM_URL_ENV = "HARNESS_OPENJEV_VLLM_URL"


DEFAULT_OPENJEV_VLLM_URL = "http://127.0.0.1:8000/v1"


OPENJEV_MAX_MODEL_LEN_ENV = "HARNESS_OPENJEV_MAX_MODEL_LEN"


OPENJEV_ALLOW_REMOTE_ENV = "HARNESS_OPENJEV_ALLOW_REMOTE"


OPENJEV_BUILD_PROBE_EVERY_ENV = "HARNESS_OPENJEV_BUILD_PROBE_EVERY"


OPENJEV_TIMEOUT_S_ENV = "HARNESS_OPENJEV_TIMEOUT_S"


#: OpenJev's published prompt limit (design §1.2) and per-pass option limit.
OPENJEV_MAX_CONTEXT_TOKENS = 16_384


OPENJEV_MAX_CHOICE_OPTIONS = 52


def _url_is_loopback(url: str) -> bool:
    """True only for `localhost` or a loopback IP literal. A look-alike host
    (`127.0.0.1.example.com`) is a DNS name, not an IP, and is not loopback."""
    import ipaddress
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _env_flag(name: str) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in ("", "0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    raise ConfigurationError(f"{name} must be true or false, got {raw!r}.")


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigurationError(f"{name} must be a positive integer, got {raw!r}.") from None
    if value < 1:
        raise ConfigurationError(f"{name} must be at least 1, got {value}.")
    return value


_GENERIC_WEIGHTS_STEMS = frozenset({"model", "pytorch_model", "consolidated", "weights"})


def _weights_names(build_id: str) -> set[str]:
    """The names an edge build's weights can be served under: the final path segment without
    its weights suffix, plus its parent directory — so `/models/openjev-FP8/model.safetensors@
    sha256:ab` (the resolved form FR-CONF-03 requires) matches vLLM serving `/models/openjev-FP8`."""
    from aeh.conf import WEIGHTS_SUFFIXES

    parts = build_id.split("@sha256:", 1)[0].replace("\\", "/").rstrip("/").split("/")
    last = parts[-1]
    for suffix in WEIGHTS_SUFFIXES:
        if last.lower().endswith(suffix):
            stem = last[: -len(suffix)]
            # A generic shard name (`model.safetensors`) identifies nothing; its directory
            # does. A named file (`openjev-Q4.gguf`) is its own identity.
            if stem.lower() in _GENERIC_WEIGHTS_STEMS and len(parts) > 1 and parts[-2]:
                return {parts[-2]}
            return {stem, last}
    return {last} if last else set()


class _LoopbackDecisionProvider(_BaseDecisionProvider):
    """Shared loopback rule for the local decision providers (CT-PROV-22, CT-PROV-26): a
    non-loopback base URL is refused at construction unless the provider's own allow-remote
    knob is set."""

    _allow_remote_env = ""
    _base_url = ""

    def _check_loopback(self, base_url: str, allow_remote: bool | None) -> None:
        allowed = _env_flag(self._allow_remote_env) if allow_remote is None else allow_remote
        if not allowed and not _url_is_loopback(base_url):
            raise ConfigurationError(
                f"{type(self).__name__} base URL {base_url!r} is not loopback. edge-local payloads "
                f"never leave the machine; set {self._allow_remote_env}=true only for a deliberate "
                f"remote decision host (FR-PROV-22).")

    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport:
        """Nothing is retained off-machine on loopback; a deliberately remote host cannot be
        confirmed and is reported unconfirmed (edge-local has no retention gate to raise)."""
        if _url_is_loopback(self._base_url):
            return RetentionReport(confirmed=tuple(model_refs), unconfirmed=())
        return RetentionReport(confirmed=(), unconfirmed=tuple(model_refs))


class OpenJevLocalProvider(_LoopbackDecisionProvider):
    """OpenJev on loopback: the local configuration's decision engine (FR-PROV-22).

    POSTs to the OpenJev shim's `/v1/systemone`. A separate class from `JevOpenRouterProvider`
    (user directive). Build identity comes from the vLLM server behind the shim, probed at run
    start and every `HARNESS_OPENJEV_BUILD_PROBE_EVERY` calls (FR-PROV-24); the shim itself
    echoes only the served name. The probe compares the served weights *name* with the
    `ModelRef`'s weights path, and any later change of the served identity; the digest is not
    verifiable through vLLM (test plan Q-26)."""

    _allow_remote_env = OPENJEV_ALLOW_REMOTE_ENV

    def __init__(self, *, base_url: str | None = None, vllm_url: str | None = None,
                 allow_remote: bool | None = None, **seams: Any) -> None:
        seams.setdefault("timeout_s", _env_positive_float(OPENJEV_TIMEOUT_S_ENV, 20.0))
        super().__init__(**seams)
        self._base_url = (base_url or os.environ.get(OPENJEV_BASE_URL_ENV) or DEFAULT_OPENJEV_BASE_URL).rstrip("/")
        self._check_loopback(self._base_url, allow_remote)
        self._vllm_url = (vllm_url or os.environ.get(OPENJEV_VLLM_URL_ENV) or DEFAULT_OPENJEV_VLLM_URL).rstrip("/")
        self._model_name = os.environ.get(OPENJEV_MODEL_NAME_ENV) or DEFAULT_OPENJEV_MODEL_NAME
        self._served_identity: str | None = None
        self._calls_since_probe = 0

    def decision_capabilities(self, model_ref: ModelRef) -> DecisionCapabilities:
        context = min(OPENJEV_MAX_CONTEXT_TOKENS,
                      _env_positive_int(OPENJEV_MAX_MODEL_LEN_ENV, OPENJEV_MAX_CONTEXT_TOKENS))
        return DecisionCapabilities(max_context_tokens=context, max_choice_options=OPENJEV_MAX_CHOICE_OPTIONS,
                                    max_questions=DECISION_MAX_QUESTIONS, cost_per_input_token=None,
                                    deterministic=True)

    def verify_build(self, model_ref: ModelRef) -> str:
        """Probe vLLM's `GET /v1/models` and check the served weights name matches the
        `ModelRef` (FR-PROV-24). Records the served identity; a later probe that differs raises
        `BuildChangedError`. Returns the identity."""
        if not _url_is_loopback(self._vllm_url) and not _env_flag(self._allow_remote_env):
            raise ConfigurationError(f"the OpenJev build-probe URL {self._vllm_url!r} is not loopback.")
        response = self._transport.send(HttpRequest("GET", f"{self._vllm_url}/models", {}, b""))
        if response.status != 200:
            raise ProviderUnavailableError(f"the OpenJev build probe got HTTP {response.status}")
        try:
            raw = response.body
            document = raw if isinstance(raw, dict) else json.loads(bytes(raw).decode("utf-8"))
            entry = document["data"][0]
            identity = str(entry.get("root") or entry["id"])
        except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise MalformedResponseError(f"the OpenJev build probe returned no model entry: {exc}") from exc
        if self._served_identity is not None and identity != self._served_identity:
            raise BuildChangedError(
                f"OpenJev's served weights changed mid-run: {self._served_identity!r} -> {identity!r}.")
        if not (_weights_names(identity) & _weights_names(model_ref.build_id)):
            raise BuildChangedError(
                f"OpenJev serves {identity!r}, but the run is configured for {model_ref.build_id!r} "
                f"(FR-PROV-24).")
        self._served_identity = identity
        self._calls_since_probe = 0
        return identity

    def decide(self, request: DecisionRequest, model_ref: ModelRef) -> Decision:
        if not isinstance(request, DecisionRequest):
            raise TypeError(f"decide takes a DecisionRequest, got {type(request).__name__}")
        every = _env_positive_int(OPENJEV_BUILD_PROBE_EVERY_ENV, 500)
        if self._served_identity is not None and self._calls_since_probe >= every:
            self.verify_build(model_ref)
        body = json.dumps({"model": self._model_name, "state": request.state,
                           "questions": decision_questions_document(request)},
                          ensure_ascii=False).encode("utf-8")
        decision = self._decide_http(request, model_ref, f"{self._base_url}/v1/systemone",
                                     {"Content-Type": "application/json"}, body,
                                     fallback_build=model_ref.build_id)
        self._calls_since_probe += 1
        # The shim echoes only the served name, so the (probe-verified) ModelRef build is the
        # identity every answer reports (FR-PROV-24).
        return dataclasses.replace(decision, resolved_build=model_ref.build_id)


OPENJEV_SMALL_BASE_URL_ENV = "HARNESS_OPENJEV_SMALL_BASE_URL"


DEFAULT_OPENJEV_SMALL_BASE_URL = "http://127.0.0.1:3001"


OPENJEV_SMALL_MODEL_NAME_ENV = "HARNESS_OPENJEV_SMALL_MODEL_NAME"


DEFAULT_OPENJEV_SMALL_MODEL_NAME = "openjev-small"


OPENJEV_SMALL_ALLOW_REMOTE_ENV = "HARNESS_OPENJEV_SMALL_ALLOW_REMOTE"


OPENJEV_SMALL_MAX_STATE_TOKENS_ENV = "HARNESS_OPENJEV_SMALL_MAX_STATE_TOKENS"


OPENJEV_SMALL_BUILD_PROBE_EVERY_ENV = "HARNESS_OPENJEV_SMALL_BUILD_PROBE_EVERY"


OPENJEV_SMALL_TIMEOUT_S_ENV = "HARNESS_OPENJEV_SMALL_TIMEOUT_S"


#: FR-PROV-32. Assumption: one ~8k-token encoder window minus the hypothesis and template
#: budget (test plan Q-42); the shim's 422 is the backstop when the estimate is optimistic.
OPENJEV_SMALL_MAX_STATE_TOKENS = 6_000


#: Each option is a forward pass, so option sets cost linearly (FR-PROV-32).
OPENJEV_SMALL_MAX_CHOICE_OPTIONS = 16


def _small_build_identity(build_id: str) -> tuple[str, str]:
    """`(subfolder, digest)` of an openjev-small build (FR-PROV-31, FR-CONF-27): the directory
    holding a generic `model.safetensors`, else the final path segment, and the `@sha256:` pin."""
    from aeh.conf import WEIGHTS_SUFFIXES

    path, _, digest = build_id.partition("@sha256:")
    parts = path.replace("\\", "/").rstrip("/").split("/")
    last = parts[-1]
    for suffix in WEIGHTS_SUFFIXES:
        if (last.lower().endswith(suffix) and last[: -len(suffix)].lower() in _GENERIC_WEIGHTS_STEMS
                and len(parts) > 1):
            last = parts[-2]
            break
    return last, digest.strip().lower()


class OpenJevSmallLocalProvider(_LoopbackDecisionProvider):
    """OpenJevSmall on loopback: the opt-in `edge-local` decision engine for machines too small
    to hold OpenJev beside the judge (FR-PROV-30…32, design §3.11).

    A separate class from `OpenJevLocalProvider` — neither subclasses the other — with its own
    base URL, allow-remote knob and one-window budget. Unlike OpenJev, the build **digest** is
    verified: the shim hashes the loaded `model.safetensors` and reports it at `GET /v1/build`
    (FR-PROV-36), probed at run start and every `HARNESS_OPENJEV_SMALL_BUILD_PROBE_EVERY` calls.
    The engine emits no confidence, so any `confidence` a response carries is dropped and every
    confidence is derived (CT-PROV-27)."""

    _allow_remote_env = OPENJEV_SMALL_ALLOW_REMOTE_ENV

    def __init__(self, *, base_url: str | None = None, allow_remote: bool | None = None,
                 **seams: Any) -> None:
        seams.setdefault("timeout_s", _env_positive_float(OPENJEV_SMALL_TIMEOUT_S_ENV, 60.0))
        super().__init__(**seams)
        self._base_url = (base_url or os.environ.get(OPENJEV_SMALL_BASE_URL_ENV)
                          or DEFAULT_OPENJEV_SMALL_BASE_URL).rstrip("/")
        self._check_loopback(self._base_url, allow_remote)
        self._model_name = os.environ.get(OPENJEV_SMALL_MODEL_NAME_ENV) or DEFAULT_OPENJEV_SMALL_MODEL_NAME
        self._verified: str | None = None
        self._calls_since_probe = 0

    def decision_capabilities(self, model_ref: ModelRef) -> DecisionCapabilities:
        return DecisionCapabilities(
            max_context_tokens=_env_positive_int(OPENJEV_SMALL_MAX_STATE_TOKENS_ENV, OPENJEV_SMALL_MAX_STATE_TOKENS),
            max_choice_options=OPENJEV_SMALL_MAX_CHOICE_OPTIONS, max_questions=DECISION_MAX_QUESTIONS,
            cost_per_input_token=None, deterministic=True)

    @staticmethod
    def resolved_build_for(model_ref: ModelRef) -> str:
        """`openjev-small:<subfolder>@sha256:<digest>` — what every answer reports (FR-PROV-31)."""
        subfolder, digest = _small_build_identity(model_ref.build_id)
        return f"openjev-small:{subfolder}@sha256:{digest}"

    def build_info(self) -> dict[str, str]:
        """The shim's `GET /v1/build` document (FR-PROV-36)."""
        response = self._transport.send(HttpRequest("GET", f"{self._base_url}/v1/build", {}, b""))
        if response.status != 200:
            raise ProviderUnavailableError(f"the openjev-small build probe got HTTP {response.status}")
        try:
            raw = response.body
            document = raw if isinstance(raw, dict) else json.loads(bytes(raw).decode("utf-8"))
            return {"subfolder": str(document["subfolder"]),
                    "weights_sha256": str(document["weights_sha256"]).lower(),
                    "device": str(document.get("device", ""))}
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise MalformedResponseError(f"the openjev-small build probe is malformed: {exc}") from exc

    def verify_build(self, model_ref: ModelRef, *, placement: str | None = None) -> str:
        """FR-PROV-31: the served `weights_sha256` and subfolder must equal the `ModelRef`'s,
        else `BuildChangedError` — the 2B build against a 4B ref included; nothing swaps builds.
        With `placement == "cpu"` (FR-CONF-28) the served device must be `cpu`, else
        `ConfigurationError`. Returns the resolved build."""
        info = self.build_info()
        subfolder, digest = _small_build_identity(model_ref.build_id)
        if info["subfolder"] != subfolder or info["weights_sha256"] != digest:
            raise BuildChangedError(
                f"openjev-small serves {info['subfolder']}@sha256:{info['weights_sha256']}, but the run "
                f"is configured for {subfolder}@sha256:{digest} (FR-PROV-31). A different build is "
                f"chosen only by naming it in configuration.")
        if placement == "cpu" and info["device"] != "cpu":
            raise ConfigurationError(
                f"openjev-small must run with placement 'cpu' on this hardware profile so the judge "
                f"keeps the accelerator, but the shim reports device {info['device']!r} (FR-CONF-28). "
                f"Restart it on CPU (OPENJEV_DEVICE=cpu).")
        resolved = self.resolved_build_for(model_ref)
        self._verified = resolved
        self._calls_since_probe = 0
        return resolved

    def _prepare_document(self, document: Any) -> Any:
        if isinstance(document, dict) and isinstance(document.get("answers"), dict):
            answers = {k: ({f: v for f, v in a.items() if f != "confidence"} if isinstance(a, dict) else a)
                       for k, a in document["answers"].items()}
            document = {**document, "answers": answers}
        return document

    def decide(self, request: DecisionRequest, model_ref: ModelRef) -> Decision:
        if not isinstance(request, DecisionRequest):
            raise TypeError(f"decide takes a DecisionRequest, got {type(request).__name__}")
        every = _env_positive_int(OPENJEV_SMALL_BUILD_PROBE_EVERY_ENV, 500)
        if self._verified is not None and self._calls_since_probe >= every:
            self.verify_build(model_ref)
        body = json.dumps({"model": self._model_name, "state": request.state,
                           "questions": decision_questions_document(request)},
                          ensure_ascii=False).encode("utf-8")
        expected = self.resolved_build_for(model_ref)
        decision = self._decide_http(request, model_ref, f"{self._base_url}/v1/systemone",
                                     {"Content-Type": "application/json"}, body, fallback_build=expected)
        self._calls_since_probe += 1
        if decision.resolved_build != expected:
            raise BuildChangedError(
                f"openjev-small answered as {decision.resolved_build!r}, but the run is configured for "
                f"{expected!r} (FR-PROV-31).")
        return decision
