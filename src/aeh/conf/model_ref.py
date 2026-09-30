"""`ModelRef`: a pinned model build identity, and the check that refuses floating tags."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
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
    """Whether `build_id` carries a floating tag, checked in **tag positions only**.

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
    """A pinned build identity. Design §3.1 Interfaces.

    `build_id` takes one of two forms, and `is_resolved()` judges it by form alone — there is no
    backend argument on this type, so the per-backend rule ("weights path for `edge-local`,
    pinned slug otherwise") lives in `resolve_run_config`.

    | `build_id` | `quantization` | form | resolved |
    |---|---|---|---|
    | `/models/llama-3.3-70b.gguf@sha256:aaaa` | `"q4"` | edge-weights | yes |
    | `/models/llama-3.3-70b.gguf@sha256:aaaa` | `None` | — | no — `FR-CONF-03` wants path **plus quantization plus** hash |
    | `/models/llama-3.3-70b.gguf` | `"q4"` | — | no — no weights hash |
    | `/models/llama:latest.gguf@sha256:aaaa` | `"q4"` | — | no — floating tag, on either form |
    | `openrouter/llama-3.3-70b-instruct@2024-12-06` | any | provider-pinned | yes |
    | `openrouter/llama-3.3-70b-instruct` | any | — | no — a bare slug is not pinned |
    | `llama3.3:latest@2024-12-06` | any | — | no — floating tag |
    | `Llama 3.3 70B` | any | — | no — a friendly name (`FR-CONF-03`, verbatim) |

    The two forms are told apart by `WEIGHTS_SUFFIXES`, not by the presence of `@sha256:`
    alone: a hosted build pinned by content digest (`openrouter/x@sha256:abcd`) is
    provider-pinned, not a weights path.

    The digest is required to be hex and non-empty, but **not** 64 characters: the repository
    already commits `sha256:aaaa` as a legal judge build
    (`tests/unit/prov/test_recorded_fixture_provider.py`). Verifying that a digest matches the
    bytes on disk belongs to `M-STORE`, not here — this module never opens a file.
    """

    role: ModelRole
    provider: str
    build_id: str
    quantization: str | None

    def __post_init__(self) -> None:
        """Type hygiene only — never form, which is `build_form`'s question.

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
        """Which of the two resolved forms `build_id` takes, or `None` if it takes neither."""
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
        """`FR-CONF-03` / `CT-CONF-03`: `build_id` is sufficient to identify what answered."""
        return self.build_form() is not None


#: The four `ModelRef` fields, in the order the persisted row carries them. One definition, used
#: by both directions of the round trip, so `NFR-CONF-04`'s byte-identical guarantee cannot be
#: broken by the two halves disagreeing about a field name.
_REF_FIELDS: tuple[str, ...] = ("role", "provider", "build_id", "quantization")


def _ref_to_dict(ref: ModelRef) -> dict[str, Any]:
    return {name: getattr(ref, name) for name in _REF_FIELDS}


def _ref_from_dict(raw: Any, what: str) -> ModelRef:
    if not isinstance(raw, Mapping):
        raise ConfigurationError(
            f"persisted {what} must be a mapping of {_REF_FIELDS}, got {type(raw).__name__}."
        )
    missing = [name for name in _REF_FIELDS if name not in raw]
    if missing:
        raise ConfigurationError(f"persisted {what} is missing {', '.join(missing)}.")
    return ModelRef(**{name: raw[name] for name in _REF_FIELDS})


def _require_model_ref(value: Any, what: str, expected_role: str) -> ModelRef:
    if not isinstance(value, ModelRef):
        raise ConfigurationError(f"{what} must be a ModelRef, got {type(value).__name__}.")
    if value.role != expected_role:
        raise ConfigurationError(
            f"{what} must carry role {expected_role!r}, got {value.role!r}."
        )
    return value
