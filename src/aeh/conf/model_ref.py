"""`ModelRef`: a pinned model build identity, and the check that refuses floating tags."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .vocabulary import BuildForm, ModelRole
from .errors import ConfigurationError
from .frozen import _typeerror_on_mutation


# --- value objects -------------------------------------------------------------------------

#: A tag that floats — it names a moving target, so a `build_id` carrying one does not identify
#: what answered. `CT-CONF-C03`: "A ref carrying a floating tag (`:latest`) must fail."
FLOATING_TAGS: frozenset[str] = frozenset({"latest", "stable", "main", "head", "newest"})


#: What makes the left half of `<path>@sha256:<digest>` a *weights file* rather than a model
#: slug that happens to be pinned by digest. Without this, `openrouter/x@sha256:abcd` — a
#: perfectly pinned hosted build — would be read as an edge-local weights path and refused for
#: carrying no quantization. Additive: a new serving format adds a suffix here.
WEIGHTS_SUFFIXES: tuple[str, ...] = (".gguf", ".safetensors", ".bin", ".pt", ".mlx", ".npz")


_WEIGHTS_HASH_MARKER = "@sha256:"


#: The provider names served by a local OpenAI-compatible model server (FR-CONF-40). A block
#: naming one of these must say, in `served_as`, the name that server serves the model under:
#: the server addresses models by that name, never by the weights path in `build_id`. Lives in
#: `M-CONF` because the start check reads it; `M-PROV`'s provider factory reads the same set.
LOCAL_SERVER_PROVIDERS: frozenset[str] = frozenset({"local", "local-server", "ollama", "vllm-mlx"})


#: Case-insensitive on purpose: `sha256:AAAA` names the same build as `sha256:aaaa`, so
#: rejecting it as *unresolved* would be wrong. (Canonicalizing the case before it reaches
#: `panel_build_ref` is `FR-CONF-05`'s question, on issue #5.)
_HEX = re.compile(r"\A[0-9a-fA-F]+\Z")


_KNOWN_ROLES: frozenset[str] = frozenset(
    {"judge", "transcriber", "extractor", "off_panel", "synthesizer", "decision"}
)


#: ISO-4217 alpha: exactly three uppercase letters. See `_resolve_cost`.
_ISO_4217 = re.compile(r"\A[A-Z]{3}\Z")


#: C0 controls and DEL. Refused in every field that reaches `compute_panel_build_ref`, because
#: two of them are that function's separators — see `ModelRef.__post_init__`.
_CONTROL_CHARS: frozenset[str] = frozenset(chr(c) for c in (*range(0x20), 0x7F))


def _has_floating_tag(build_id: str) -> bool:
    """Whether `build_id` carries a floating tag such as `latest`, looking only where a tag can
    appear.

    A tag position is the `@pin` suffix, or a `:tag` on the final path/slug segment. Splitting
    on every `@` and `:` instead would reject `/models/main/llama.gguf@sha256:aa`, where `main`
    is a directory and not a tag — a false refusal of a fully-pinned weights build.
    """
    slug, at_sign, pin = build_id.rpartition("@")
    if at_sign and pin.strip().lower() in FLOATING_TAGS:
        return True
    stem = slug if at_sign else build_id
    final_segment = stem.replace("\\", "/").rsplit("/", 1)[-1]
    # A weights suffix is not part of the tag: `llama:latest.gguf` carries the tag `latest`.
    for suffix in WEIGHTS_SUFFIXES:
        if final_segment.lower().endswith(suffix):
            final_segment = final_segment[: -len(suffix)]
            break
    _, colon, tag = final_segment.rpartition(":")
    return bool(colon) and tag.strip().lower() in FLOATING_TAGS


@_typeerror_on_mutation
@dataclass(frozen=True)
class ModelRef:
    """A pinned model build: which model, exactly which build of it, and how it is served (design
    §3.1).

    More detail: `docs/code-notes/conf.md`, section `model_ref.py: ModelRef`.
    """

    role: ModelRole
    provider: str
    build_id: str
    quantization: str | None
    #: FR-CONF-40, ADR-61: the name a local model server serves this build under (for example
    #: `qwen3:30b-a3b-q4_K_M`). An **address**, not an identity: it is not hashed into
    #: `panel_build_ref` and not into a fixture's request key, exactly as a base URL is not, so
    #: renaming a model in the server is a config edit and not a new grader. None on a block
    #: whose provider is not a local server, where it is ignored. `compare=False` for the same
    #: reason: two refs to the same build are the same grader (equal, same hash) whatever the
    #: server calls it.
    served_as: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        """Check field types only; whether the build id is in a valid form is `build_form`'s job.

        `provider` and `build_id` are hashed into `panel_build_ref`, which `CT-CONF-07` makes a
        `package_validation` primary-key component. A `None` provider would be hashed as the
        literal string `"None"` and key a validation record to nothing.

        `provider` is checked for shape and not against the four names design §3.1 lists as
        examples: its Compatibility note makes a new provider an **additive** change, so an
        allowlist here would turn one into a breaking one.
        """
        if self.role not in _KNOWN_ROLES:
            raise ConfigurationError(
                f"ModelRef.role must be one of {sorted(_KNOWN_ROLES)}, got {self.role!r}."
            )
        for name in ("provider", "build_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ConfigurationError(
                    f"ModelRef.{name} must be a non-empty string, got "
                    f"{type(value).__name__}. It is hashed into panel_build_ref, which keys "
                    f"every package_validation row (CT-CONF-07)."
                )
        if self.quantization is not None and (
            not isinstance(self.quantization, str) or not self.quantization.strip()
        ):
            raise ConfigurationError(
                "ModelRef.quantization must be a non-empty string or None, got "
                f"{type(self.quantization).__name__}."
            )
        if self.served_as is not None and (
            not isinstance(self.served_as, str) or not self.served_as.strip()
            or any(ch in _CONTROL_CHARS for ch in self.served_as)
        ):
            raise ConfigurationError(
                "ModelRef.served_as must be a non-empty string without control characters, "
                f"or None, got {type(self.served_as).__name__}."
            )

        # Control characters are refused because `compute_panel_build_ref` joins these three
        # fields with `\x1f` and `\n`. Without this, a `provider` or `quantization` carrying a
        # separator makes the encoding **ambiguous**, and the hash stops being injective over
        # legal panels: a single `ModelRef` whose provider spells out two more records forges
        # the ref of a three-judge panel. Both are reachable through `resolve_run_config`, and
        # `RunConfig.__post_init__`'s `panel_build_ref == compute_panel_build_ref(panel)` check
        # cannot see it — it recomputes from the same ambiguous encoding.
        #
        # `CT-CONF-07` lets consumers use the ref as a `package_validation` primary-key
        # component, so a collision merges two distinct panels under one key: verbatim the
        # regression `TC-CONF-C07` exists to catch, arriving through the encoding rather than
        # through sorting.
        #
        # Refusing is the fix that keeps the formula **frozen**: no well-formed build identity
        # contains a control character, so no existing hash changes and #7's committed
        # reference literals stay valid. Length-prefixing would also close it and would
        # invalidate every stored key.
        for name in ("provider", "build_id", "quantization"):
            value = getattr(self, name)
            if isinstance(value, str) and any(ch in _CONTROL_CHARS for ch in value):
                raise ConfigurationError(
                    f"ModelRef.{name} contains a control character. These three fields are "
                    f"joined into panel_build_ref, so a separator inside one makes the "
                    f"encoding ambiguous and the key non-unique (CT-CONF-07)."
                )

    def build_form(self) -> BuildForm | None:
        """Which of the two pinned forms `build_id` takes, or None if neither."""
        if not isinstance(self.build_id, str):
            return None
        build_id = self.build_id.strip()
        if not build_id or any(ch.isspace() for ch in build_id):
            return None

        # Checked before the branch, not inside the hosted one: a weights path can carry a
        # floating tag too, and CT-CONF-C03 states the rule for every ref.
        if _has_floating_tag(build_id):
            return None

        if _WEIGHTS_HASH_MARKER in build_id:
            path, _, digest = build_id.partition(_WEIGHTS_HASH_MARKER)
            if path.lower().endswith(WEIGHTS_SUFFIXES):
                if not _HEX.match(digest):
                    return None
                # A weights build is identified by path + hash + quantization, all three.
                if not isinstance(self.quantization, str) or not self.quantization:
                    return None
                return "edge-weights"

        slug, at_sign, pin = build_id.rpartition("@")
        if not at_sign or not slug or not pin:
            return None
        # An empty `:`-segment means the pin was truncated — `x@sha256:` names a digest that
        # is not there, and a pin that identifies nothing is not a pin.
        if any(not segment for segment in pin.split(":")):
            return None
        return "provider-pinned"

    def is_resolved(self) -> bool:
        """Whether `build_id` alone identifies exactly which model answered (FR-CONF-03,
        CT-CONF-03)."""
        return self.build_form() is not None

    def is_local_server(self) -> bool:
        """Whether a local model server serves this build, so the block needs `served_as`
        (FR-CONF-40)."""
        return self.provider in LOCAL_SERVER_PROVIDERS


#: The four `ModelRef` identity fields, in the order the persisted row carries them. One
#: definition, used by both directions of the round trip, so `NFR-CONF-04`'s byte-identical
#: guarantee cannot be broken by the two halves disagreeing about a field name.
_REF_FIELDS: tuple[str, ...] = ("role", "provider", "build_id", "quantization")


#: The optional address field (FR-CONF-40). Kept out of `_REF_FIELDS` on purpose: it is written
#: only when set, so a frozen run config persisted before it existed — or one with no local
#: model — serializes byte-identically to what it always did, and a persisted row without it
#: rehydrates with None.
_SERVED_AS = "served_as"


def _ref_to_dict(ref: ModelRef) -> dict[str, Any]:
    table = {name: getattr(ref, name) for name in _REF_FIELDS}
    if ref.served_as is not None:
        table[_SERVED_AS] = ref.served_as
    return table


def _ref_identity(ref: ModelRef) -> dict[str, Any]:
    """The fields that say *which grader* a ref is: everything but the `served_as` address
    (ADR-61). Two refs equal here are the same build, however the server names it."""
    return {name: getattr(ref, name) for name in _REF_FIELDS}


def _ref_from_dict(raw: Any, what: str) -> ModelRef:
    if not isinstance(raw, Mapping):
        raise ConfigurationError(
            f"persisted {what} must be a mapping of {_REF_FIELDS}, got {type(raw).__name__}."
        )
    missing = [name for name in _REF_FIELDS if name not in raw]
    if missing:
        raise ConfigurationError(f"persisted {what} is missing {', '.join(missing)}.")
    return ModelRef(**{name: raw[name] for name in _REF_FIELDS},
                    served_as=raw.get(_SERVED_AS))


def _missing_served_as(what: str) -> ConfigurationError:
    """FR-CONF-40's refusal for a local block without `served_as`, naming the block and the
    fix. The build id is not echoed (NFR-CONF-02). ASCII only: the CLI prints it to a console
    whose code page may not carry an ellipsis."""
    return ConfigurationError(
        f"{what} names a local model but not the name the server serves it under; "
        f'add served_as = "..." with the name your model server lists the model under (for '
        f"Ollama, the name `ollama list` shows, tag included)."
    )


def _require_model_ref(value: Any, what: str, expected_role: str) -> ModelRef:
    if not isinstance(value, ModelRef):
        raise ConfigurationError(f"{what} must be a ModelRef, got {type(value).__name__}.")
    if value.role != expected_role:
        raise ConfigurationError(
            f"{what} must carry role {expected_role!r}, got {value.role!r}."
        )
    return value
