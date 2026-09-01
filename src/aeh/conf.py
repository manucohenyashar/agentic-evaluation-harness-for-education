"""`M-CONF` — Deployment Profile & Run Configuration (design §3.1).

Resolves the deployment profile into one immutable `RunConfig` before a run begins, so every
consumer reads one frozen answer to "which grader is this run" and none can change it. The module
is a **leaf**: it has no downstream dependency, writes nothing, and its resolution is a pure
function of `(cfg, cohort)`.

Scope of this file today
------------------------
`M-CONF` ships across three stories. This one is **issue #4** — `FR-CONF-01`, `-02`, `-03`, `-06`,
`-07`, `NFR-CONF-01`, `NFR-CONF-03`. Two things the design's Interfaces list are deliberately
**absent** rather than stubbed, because a stub would let a contract case pass vacuously:

| Absent | Lands in |
|---|---|
| `rehydrate_run_config`, `RunConfig.to_persisted_dict` | #6 — `TC-CONF-C01` asserts over *both* entry points |
| `RunConfig.profile_summary`, the run-start log line | #5 — `TC-CONF-C13` asserts *exactly one* log line |

Decisions this file fixes, that the design underdetermines
----------------------------------------------------------
Recorded here rather than in a commit message because `TS-03` (#7) and `TS-58` (#9) are written
**against whatever this module ships**, and a signature they have to guess is a suite that asserts
the wrong thing.

| Decision | Choice | Forced by |
|---|---|---|
| Exception taxonomy | Four **siblings** under `RunConfigError`; all four declared, two raised here | `TC-CONF-15` names four; siblings keep every "exact exception type" oracle discriminating |
| `is_resolved()` | Judges `build_id` by **form** only — no backend argument exists on `ModelRef` | `TC-CONF-03`: "`is_resolved()` agrees with the outcome in every case" |
| Backend cross-check | Lives in `resolve_run_config`, not in `is_resolved()` | `CT-CONF-C03`: "assert per backend what resolution *means*" |
| Mutation raises | `TypeError`, via `_typeerror_on_mutation` | `FR-CONF-02` says `TypeError`; `dataclasses.FrozenInstanceError` is an `AttributeError` |
| Residency + quantization | Public **data** in `HARDWARE_PROFILES`, not fields and not code paths | `CT-CONF-C02` pins `RunConfig` to 12 fields; `TC-CONF-14` forbids platform branches |
| `HARNESS_*` namespace | Stays at **exactly six** keys; structural inputs use plain keys | `TC-CONF-C11` sweeps "each of the six `HARNESS_*` keys" |
| `HARNESS_CONCURRENCY` | **Clamps down, never up**: `min(key, hardware ceiling)`; alone on a hosted backend | Precedence is unstated; a ceiling a variable can raise is not a ceiling |
| Inapplicable `HARNESS_*` keys | Ignored, not refused | `CT-CONF-02`'s iff constrains `RunConfig` fields; refusing would make `environment_snapshot` unusable |
| Where the iffs live | `RunConfig.__post_init__`, not only the resolver | An invariant enforced only by the function that builds the value is forgeable through `dataclasses.replace` |
| `edge-weights` vs `provider-pinned` | Told apart by `WEIGHTS_SUFFIXES`, not by `@sha256:` alone | Otherwise a digest-pinned hosted build reads as a weights path |
| `ModelRef` / `HardwarePolicy` validate on construction | Shape only, raising `ConfigurationError` | Both are caller-supplied and reach a primary key (`panel_build_ref`) or an arithmetic clamp; a bad one must not surface as a bare `TypeError` (`TC-CONF-15`) |
| A `RunConfig` literal must be **legal** | `__post_init__` refuses one violating `CT-CONF-02`/`-03`/`-07` | §3.1 says the type is "cheap to construct"; it does not say a value carrying none of its guarantees is a `RunConfig` |

The second of those changes an input class `TS-03` will meet: an empty or whitespace `build_id`,
or a `role` outside the four, now raises from the **constructor** rather than surfacing as an
unresolved ref out of `resolve_run_config`. `TC-CONF-03`'s listed inputs (a friendly name, a
GGUF path with no hash, a bare slug) are all still constructible and still refused by the
resolver, which is where that case looks.

Also unowned, and raised on the PR rather than silently absorbed: **`CT-CONF-14` appears in no
issue's `Traces to`.** #6 carries `FR-CONF-04/08/11/12` and `NFR-CONF-02/04`; the clause is on
none of them, yet `TC-CONF-C14` is a P0 safety property (design §4.7). The back doors this
module leaves open are listed in `_typeerror_on_mutation`, so whoever picks the clause up starts
from a written list rather than a search.

Credentials (`NFR-CONF-02`) never appear in an exception raised here: a message names the
offending **key**, and echoes a **value** only for the four non-credential `HARNESS_*` keys.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Literal

__all__ = [
    "BackendProfile",
    "BackendMismatchError",
    "CohortRef",
    "ConfigurationError",
    "ConsentGateError",
    "DEFAULT_HOSTED_CONCURRENCY",
    "DEFAULT_HOSTED_PREFIX_TOKEN_CEILING",
    "FLOATING_TAGS",
    "HARDWARE_PROFILES",
    "HARNESS_KEYS",
    "HardwarePolicy",
    "ModelRef",
    "PANEL_SIZES",
    "RUN_CONFIG_FIELDS",
    "RunConfig",
    "RunConfigError",
    "UnresolvedModelRefError",
    "WEIGHTS_SUFFIXES",
    "compute_panel_build_ref",
    "environment_snapshot",
    "hardware_policy_for",
    "parse_allow_remote_real_work",
    "resolve_run_config",
]


# --- types ---------------------------------------------------------------------------------

BackendProfile = Literal["edge-local", "cloud-hosted", "dev-ci"]
HardwareProfileName = Literal["unified-large", "unified-small", "discrete-gpu"]
ModelRole = Literal["judge", "transcriber", "extractor", "off_panel"]
BuildForm = Literal["edge-weights", "provider-pinned"]

BACKEND_PROFILES: tuple[str, ...] = ("edge-local", "cloud-hosted", "dev-ci")

#: `CT-CONF-02`: "`panel` has length 1, 3, or 5 — never even, never 0."
PANEL_SIZES: frozenset[int] = frozenset({1, 3, 5})


# --- errors --------------------------------------------------------------------------------


class RunConfigError(Exception):
    """Base for every `M-CONF` failure.

    A **neutral** base with four siblings under it, never a chain: if
    `UnresolvedModelRefError` subclassed `ConfigurationError`, every "exact exception type"
    oracle in test-plan §5.1 would pass against the wrong failure.

    `retryable` is a class attribute rather than documentation because `TC-CONF-C08` asserts it:
    all four are raised **before** the `run` row is written, so there is nothing to retry and
    nothing to clean up (`CT-CONF-08`).
    """

    retryable = False


class ConfigurationError(RunConfigError):
    """A required key is absent, unrecognized, or of the wrong shape (`FR-CONF-01`, `-06`, `-07`).

    Raised rather than defaulting. `CT-CONF-11`: "No key has a silent default that selects a
    backend — absence raises."
    """


class UnresolvedModelRefError(RunConfigError):
    """A `ModelRef` is not a resolved build identity, or is the wrong form for the backend.

    `FR-CONF-03`: a friendly name such as `"Llama 3.3 70B"` fails validation.
    """


class BackendMismatchError(RunConfigError):
    """A resumed run's persisted backend disagrees with current configuration (`FR-CONF-04`).

    Declared here so the taxonomy `CT-CONF-08` names is complete and `TC-CONF-15`'s invariant
    ("one of the four declared exception types") can be written. **Raised by issue #6**, which
    owns `rehydrate_run_config`.
    """


class ConsentGateError(RunConfigError):
    """A remote provider was bound for a cohort that is neither synthetic nor consented
    (`FR-CONF-08`, RISK-10).

    Declared here for the same reason as `BackendMismatchError`. **Raised by issue #6**, which
    owns the consent gate.
    """


# --- immutability --------------------------------------------------------------------------


def _typeerror_on_mutation(cls):
    """Make assignment, deletion and `replace` on a frozen value object raise `TypeError`.

    `FR-CONF-02` and `CT-CONF-04` both name `TypeError` specifically, and a plain
    `@dataclass(frozen=True)` raises `dataclasses.FrozenInstanceError` — which subclasses
    `AttributeError`, not `TypeError`. A `pytest.raises(TypeError)` written from the requirement
    would fail against a correct implementation.

    `__replace__` is closed too, which shuts `copy.replace` (Python 3.13+): a copy carrying a
    different `backend_profile` or `panel` is precisely the rebinding `CT-CONF-04` forbids and
    RISK-22 describes.

    `dataclasses.replace` does **not** route through `__replace__` — verified on CPython 3.14,
    where it calls `obj.__class__(**changes)` directly — so this decorator cannot see it. It is
    narrowed from the other end instead: `RunConfig.__post_init__` enforces `CT-CONF-02`,
    `CT-CONF-03` and `CT-CONF-07` on the *type*, so a replace that rebinds the backend, the
    hardware profile, either cost field, or the panel raises. Direct construction of a legal
    literal keeps working, which design §3.1's Compatibility note requires in as many words:
    *"Consumers test against a literal `RunConfig` value rather than a double — the type is
    frozen and cheap to construct."*

    Precisely what stays open, so nobody reads more into this than it does:

    - a *self-consistent* rebuild (`replace(cfg, backend_profile=…, hardware_profile=None,
      panel=<hosted builds>, cost_ceiling=…, cost_currency=…, panel_build_ref=…)`), which is
      indistinguishable from constructing the literal directly and so cannot be closed without
      forbidding both;
    - `replace(cfg, concurrency_ceiling=999)`, because the ceiling a config was resolved under
      depends on the hardware table used at resolution time, which the value does not carry;
    - pickle's `__setstate__` and a hand-edited `run` row.

    All three belong to `TC-CONF-C14`'s back-door sweep — see the module docstring's note on
    which issue owns that clause.

    The decorator is applied *after* `@dataclass(frozen=True)`, which is required: assigning
    `__setattr__` inside the class body makes the dataclass decorator itself raise. The
    generated `__init__` writes through `object.__setattr__`, so construction is unaffected.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError(
            f"{cls.__name__} is frozen: cannot assign to {name!r}. A consumer needing a "
            f"different value creates a new run (CT-CONF-04, CT-CONF-14)."
        )

    def __delattr__(self, name: str) -> None:
        raise TypeError(f"{cls.__name__} is frozen: cannot delete {name!r}.")

    def __replace__(self, /, **changes: Any):
        raise TypeError(
            f"{cls.__name__} does not support replace(): no operation returns a copy with a "
            f"different backend, panel or ceiling (CT-CONF-14)."
        )

    cls.__setattr__ = __setattr__
    cls.__delattr__ = __delattr__
    cls.__replace__ = __replace__
    return cls


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

_KNOWN_ROLES: frozenset[str] = frozenset({"judge", "transcriber", "extractor", "off_panel"})


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


@_typeerror_on_mutation
@dataclass(frozen=True)
class HardwarePolicy:
    """What an `edge-local` `hardware_profile` derives (`FR-CONF-06`).

    Data, never a code path: `NFR-CONF-03` and `TC-CONF-14` both forbid a `sys.platform` branch
    or a platform-conditional import, so residency and quantization exist only as values in
    `HARDWARE_PROFILES`.

    `residency_policy` is the set of roles permitted resident concurrently. It has no home on
    `RunConfig` — `CT-CONF-C02` asserts **exact set equality** over that type's 12 fields — so a
    consumer reads it from the table via `hardware_policy_for`.
    """

    residency_policy: tuple[str, ...]
    concurrency_ceiling: int
    quantization_target: str
    prefix_token_ceiling: int

    def __post_init__(self) -> None:
        """Type hygiene, for the same reason `ModelRef` has it: this type is caller-supplied
        through `cfg["hardware_profiles"]`, and `_resolve_concurrency` clamps against
        `concurrency_ceiling`. A string there would surface a bare `TypeError` out of
        `resolve_run_config`, which `TC-CONF-15`'s invariant forbids.
        """
        if not isinstance(self.residency_policy, tuple) or not all(
            isinstance(role, str) and role for role in self.residency_policy
        ):
            raise ConfigurationError(
                "HardwarePolicy.residency_policy must be a tuple of non-empty role names."
            )
        for name in ("concurrency_ceiling", "prefix_token_ceiling"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigurationError(
                    f"HardwarePolicy.{name} must be an integer of at least 1, got "
                    f"{type(value).__name__}."
                )
        if not isinstance(self.quantization_target, str) or not self.quantization_target.strip():
            raise ConfigurationError(
                "HardwarePolicy.quantization_target must be a non-empty string."
            )


@_typeerror_on_mutation
@dataclass(frozen=True)
class CohortRef:
    """The cohort a run grades. `consent_class` is ADR-5's column.

    The default is `"real"` and that is load-bearing: `TC-CONF-08` calls the undeclared-cohort
    row "the difference between a fail-closed and a fail-open design". The gate that reads it is
    `FR-CONF-08`, on issue #6; the default belongs here because this is where the type lives.
    """

    cohort_id: str
    consent_class: Literal["synthetic", "consented", "real"] = "real"


@_typeerror_on_mutation
@dataclass(frozen=True)
class RunConfig:
    """One frozen answer to "which grader is this run" (design §3.1 Interfaces).

    The field set is **exactly** these twelve. `CT-CONF-C02` asserts set equality rather than a
    subset, so adding a convenience field here breaks the contract suite by design — that is the
    clause working, not a broken test.

    Nullability, both directions (`CT-CONF-02`):

    | field | non-null iff |
    |---|---|
    | `hardware_profile` | `backend_profile == "edge-local"` |
    | `cost_ceiling`, `cost_currency` | `backend_profile in {"cloud-hosted", "dev-ci"}` |
    | `retention_setting` | `backend_profile == "cloud-hosted"` — enforced by issue #6 |

    No method returns a copy with a different backend or panel, and none will be added
    (`CT-CONF-14`, a safety property): a consumer needing a different backend creates a
    different run.
    """

    backend_profile: BackendProfile
    hardware_profile: HardwareProfileName | None
    panel: tuple[ModelRef, ...]
    transcriber: ModelRef
    off_panel_checker: ModelRef | None
    prompt_template_v: str
    concurrency_ceiling: int
    prefix_token_ceiling: int
    cost_ceiling: Decimal | None
    cost_currency: str | None
    retention_setting: str | None
    panel_build_ref: str

    def __post_init__(self) -> None:
        """`CT-CONF-02` and `CT-CONF-03`, enforced on the **type** rather than only in the
        resolver.

        This is what makes the invariants unforgeable. `dataclasses.replace` does not route
        through `__replace__` (see `_typeerror_on_mutation`), so without this a caller could
        take a resolved `edge-local` config and produce a `cloud-hosted` one still carrying
        `hardware_profile='unified-large'` and no cost ceiling — a value violating both of
        `CT-CONF-02`'s iffs at once, and one `resolve_run_config` can never return. An invariant
        that lives only in the function that happens to build the value is not an invariant.

        Deliberately **not** enforced here: `retention_setting` non-null for `cloud-hosted`.
        That is `FR-CONF-12`, on issue #6, and asserting it now would make its case pass before
        its code exists.
        """
        if self.backend_profile not in BACKEND_PROFILES:
            raise ConfigurationError(
                f"backend_profile must be one of {BACKEND_PROFILES}, got "
                f"{_echo('HARNESS_PROFILE', self.backend_profile)}."
            )

        # A `tuple` specifically, not any sequence, and that is deliberate: the design declares
        # `panel: tuple[ModelRef, ...]`, and a `list` field would make `CT-CONF-04`'s "consumers
        # may hold one for the life of a run without defensive copying" false — the object would
        # be frozen while its panel stayed mutable. `resolve_run_config` converts for callers;
        # a literal has to pass a tuple.
        if not isinstance(self.panel, tuple) or len(self.panel) not in PANEL_SIZES:
            raise ConfigurationError(
                f"panel must be a tuple of {sorted(PANEL_SIZES)} ModelRefs, got "
                f"{type(self.panel).__name__} of length "
                f"{len(self.panel) if isinstance(self.panel, Sequence) else '?'} (CT-CONF-02)."
            )
        for position, member in enumerate(self.panel):
            _require_model_ref(member, f"panel[{position}]", "judge")
        _require_model_ref(self.transcriber, "transcriber", "transcriber")
        if self.off_panel_checker is not None:
            _require_model_ref(self.off_panel_checker, "off_panel_checker", "off_panel")

        # The two iffs, both directions. Asserting only "required when" would let a stray
        # non-null through on the profile that has no use for it.
        edge = self.backend_profile == "edge-local"
        if edge != (self.hardware_profile is not None):
            raise ConfigurationError(
                f"hardware_profile is non-null iff backend_profile is 'edge-local' "
                f"(CT-CONF-02); got backend_profile={self.backend_profile!r}, "
                f"hardware_profile={self.hardware_profile!r}."
            )
        hosted = self.backend_profile in _COST_BEARING_PROFILES
        for name, value in (("cost_ceiling", self.cost_ceiling), ("cost_currency", self.cost_currency)):
            if hosted != (value is not None):
                raise ConfigurationError(
                    f"{name} is non-null iff backend_profile is cloud-hosted or dev-ci "
                    f"(CT-CONF-02); got backend_profile={self.backend_profile!r} and "
                    f"{name}={'set' if value is not None else 'None'}."
                )

        for name in ("concurrency_ceiling", "prefix_token_ceiling"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigurationError(
                    f"{name} must be an integer of at least 1, got {type(value).__name__}."
                )
        if not isinstance(self.prompt_template_v, str) or not self.prompt_template_v.strip():
            raise ConfigurationError("prompt_template_v must be a non-empty string.")

        # CT-CONF-03: every reachable ref is resolved, in the form this backend requires.
        for position, member in enumerate(self.panel):
            _check_resolved(member, f"panel[{position}]", self.backend_profile)
        _check_resolved(self.transcriber, "transcriber", self.backend_profile)
        if self.off_panel_checker is not None:
            _check_resolved(self.off_panel_checker, "off_panel_checker", self.backend_profile)

        # CT-CONF-07: the ref must be the hash **of this panel**. Without this, a replace that
        # reorders the panel keeps the old ref, and two distinct ordered panels share one key —
        # verbatim the regression `TC-CONF-C07` exists to catch, and `CT-CONF-07` licenses
        # consumers to use the ref as a `package_validation` primary-key component.
        #
        # It also gives issue #6 `TC-CONF-04`'s stated variant for nothing: "a persisted
        # `panel_build_ref` that disagrees with the one recomputed from the persisted builds".
        expected_ref = compute_panel_build_ref(self.panel)
        if self.panel_build_ref != expected_ref:
            raise ConfigurationError(
                f"panel_build_ref does not match this panel: carries "
                f"{self.panel_build_ref!r}, the ordered panel hashes to {expected_ref!r} "
                f"(CT-CONF-07)."
            )


# --- the hardware table --------------------------------------------------------------------

#: `FR-CONF-06`'s derivation, as data. Public because `TC-CONF-06`'s oracle is "exact value per
#: cell" and `RunConfig` carries no residency field to read it from. Override per-run through
#: `cfg["hardware_profiles"]` (`CLAUDE.md` code convention 3: the production value is the
#: default, the knob exists so another environment need not edit code).
#:
#: Prefix ceilings are design §3.1's recorded Assumption — the HLD gives "on the order of 1,500
#: to 2,000" without a per-profile assignment. Issue #5 owns `FR-CONF-10` and the env-gated knob.
#: A `MappingProxyType`, not a `dict`: it is exported *and* read as `resolve_run_config`'s
#: default table, so a mutable one would make resolution a function of process state —
#: `HARDWARE_PROFILES["unified-large"] = ...` between two calls would return two different
#: `RunConfig`s for identical inputs, which is exactly what `CT-CONF-05` and `NFR-CONF-01`
#: forbid. `TC-CONF-C05` perturbs the *environment* and would not catch it.
HARDWARE_PROFILES: Mapping[str, HardwarePolicy] = MappingProxyType({
    "unified-large": HardwarePolicy(
        residency_policy=("judge", "transcriber"),
        concurrency_ceiling=4,
        quantization_target="q4",
        prefix_token_ceiling=2000,
    ),
    "unified-small": HardwarePolicy(
        residency_policy=("judge",),
        concurrency_ceiling=2,
        quantization_target="q4",
        prefix_token_ceiling=1500,
    ),
    "discrete-gpu": HardwarePolicy(
        residency_policy=("judge",),
        concurrency_ceiling=3,
        quantization_target="q4",
        prefix_token_ceiling=1500,
    ),
})

#: Used only when `backend_profile` is `cloud-hosted` or `dev-ci`, where no `hardware_profile`
#: exists to derive from and `HARNESS_CONCURRENCY` was not supplied. A default is safe here:
#: `CT-CONF-11` forbids a silent default that *selects a backend*, which only `HARNESS_PROFILE`
#: does.
DEFAULT_HOSTED_CONCURRENCY = 8
DEFAULT_HOSTED_PREFIX_TOKEN_CEILING = 1500


def hardware_policy_for(
    config: RunConfig,
    table: Mapping[str, HardwarePolicy] = HARDWARE_PROFILES,
) -> HardwarePolicy | None:
    """The **declared** policy behind a resolved config, or `None` for a hosted backend.

    Declared, not effective, and the distinction is load-bearing: `TC-CONF-06`'s oracle is
    "exact value per cell", so this must return the table's row unchanged. The *effective*
    concurrency for a run is `RunConfig.concurrency_ceiling`, which `HARNESS_CONCURRENCY` may
    have lowered but can never raise (see `_resolve_concurrency`).

    **Pass the same `table` the config was resolved against.** `RunConfig` carries no reference
    to it — `CT-CONF-C02` pins the field set at twelve — so a config resolved with a
    `cfg["hardware_profiles"]` override and read back through the default table gets a row that
    was never applied, or `None` for a profile name the default table has never heard of.
    `config.concurrency_ceiling <= policy.concurrency_ceiling` holds when, and only when, the
    two tables agree.

    Reads the table; takes no argument that could rebind the run.
    """
    if config.hardware_profile is None:
        return None
    return table.get(config.hardware_profile)


# --- the environment seam ------------------------------------------------------------------

#: Exactly six, and it stays six: `TC-CONF-C11` sweeps "each of the six `HARNESS_*` keys". New
#: structural inputs take a plain `cfg` key instead of joining this namespace.
HARNESS_KEYS: tuple[str, ...] = (
    "HARNESS_PROFILE",
    "HARNESS_HARDWARE_PROFILE",
    "HARNESS_COST_CEILING",
    "HARNESS_COST_CURRENCY",
    "HARNESS_CONCURRENCY",
    "HARNESS_ALLOW_REMOTE_REAL_WORK",
)

#: Keys whose value is safe to echo in an exception message. Everything else is named by key
#: only — `NFR-CONF-02` forbids a credential reaching any message this module emits, and the
#: cheapest way to guarantee that is to never interpolate a value that is not on this list.
_ECHOABLE_KEYS = frozenset(
    {
        "HARNESS_PROFILE",
        "HARNESS_HARDWARE_PROFILE",
        "HARNESS_COST_CURRENCY",
        "HARNESS_CONCURRENCY",
        "HARNESS_ALLOW_REMOTE_REAL_WORK",
    }
)

_TRUE_TOKENS = frozenset({"true", "1", "yes", "on"})
_FALSE_TOKENS = frozenset({"false", "0", "no", "off", ""})


def environment_snapshot(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Take the six `HARNESS_*` keys out of the process environment, once, for a caller to merge
    into `cfg`.

    Deliberately **not** called by `resolve_run_config`. `NFR-CONF-01` and `CT-CONF-05` require
    resolution to be a pure function whose environment enters "only through the snapshot in
    `cfg`" — so the one function that reads `os.environ` is this one, and it is the caller's.
    """
    source = os.environ if environ is None else environ
    return {key: source[key] for key in HARNESS_KEYS if key in source}


def parse_allow_remote_real_work(value: Any) -> bool:
    """`HARNESS_ALLOW_REMOTE_REAL_WORK`, defaulting to `False` (`CT-CONF-11`).

    The string `"false"` must not be truthy-coerced — a non-empty string is truthy in Python, so
    a bare `bool(value)` here would open the consent gate for every operator who set the key to
    turn the override *off*. The gate that consumes this is issue #6; the parse lives here so a
    malformed value fails at resolution rather than silently reading as `True` later.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
    raise ConfigurationError(
        f"HARNESS_ALLOW_REMOTE_REAL_WORK is not a recognized boolean: "
        f"{_echo('HARNESS_ALLOW_REMOTE_REAL_WORK', value)}. Use 'true' or 'false'."
    )


# --- panel build ref -----------------------------------------------------------------------

_FIELD_SEP = "\x1f"
_REF_SEP = "\n"
_PANEL_BUILD_REF_PREFIX = "pbr:"
_PANEL_BUILD_REF_LENGTH = 32


def compute_panel_build_ref(panel: Sequence[ModelRef]) -> str:
    """A stable hash over the **ordered** panel (`FR-CONF-05`, `CT-CONF-07`).

    Canonical encoding, fixed here because it is a primary-key component of every
    `package_validation` row and `TC-CONF-05`'s oracle is an exact value against a committed
    reference hash — changing this formula invalidates every stored key:

        "pbr:" + sha256("\\n".join(f"{provider}\\x1f{build_id}\\x1f{quantization or ''}"))[:32]

    Iteration order is the panel's own and is **never** sorted. `CT-CONF-C07` names sorting as
    the exact regression to catch: two distinct panels would silently merge under one key.

    Issue #5 owns `FR-CONF-05` in full — the documented canonical ordering and the committed
    reference hash. It is computed here because `CT-CONF-C02` pins `RunConfig` to twelve fields,
    so the field cannot be deferred, and #5 depends on #4.
    """
    payload = _REF_SEP.join(
        f"{ref.provider}{_FIELD_SEP}{ref.build_id}{_FIELD_SEP}{ref.quantization or ''}"
        for ref in panel
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return _PANEL_BUILD_REF_PREFIX + digest[:_PANEL_BUILD_REF_LENGTH]


# --- resolution ----------------------------------------------------------------------------

_REQUIRED_BUILD_FORM: Mapping[str, BuildForm] = {
    "edge-local": "edge-weights",
    "cloud-hosted": "provider-pinned",
    "dev-ci": "provider-pinned",
}

_COST_BEARING_PROFILES = frozenset({"cloud-hosted", "dev-ci"})


def _echo(key: str, value: Any) -> str:
    """Render a value for an exception message, or hide it. See `_ECHOABLE_KEYS`."""
    return repr(value) if key in _ECHOABLE_KEYS else "<not shown>"


def _require_model_ref(value: Any, what: str, expected_role: str) -> ModelRef:
    if not isinstance(value, ModelRef):
        raise ConfigurationError(f"{what} must be a ModelRef, got {type(value).__name__}.")
    if value.role != expected_role:
        raise ConfigurationError(
            f"{what} must carry role {expected_role!r}, got {value.role!r}."
        )
    return value


def _check_resolved(ref: ModelRef, what: str, backend_profile: str) -> None:
    """`FR-CONF-03` plus the per-backend half of `CT-CONF-03`.

    `is_resolved()` answers "is this *a* resolved build". The backend then decides *which* form
    counts: a provider-pinned slug is a perfectly resolved identity and still wrong on
    `edge-local`, where nothing but a weights path can name what ran.
    """
    form = ref.build_form()
    if form is None:
        raise UnresolvedModelRefError(
            f"{what} is not a resolved build identity: build_id={ref.build_id!r}, "
            f"quantization={ref.quantization!r}. Expected a weights path plus quantization plus "
            f"hash, or a provider-pinned slug (FR-CONF-03)."
        )
    expected = _REQUIRED_BUILD_FORM[backend_profile]
    if form != expected:
        # Name the discriminator in the message. The commonest way to hit this is a weights
        # path whose extension is not in WEIGHTS_SUFFIXES — it reads as provider-pinned, and
        # "requires an edge-weights build" alone would send the reader hunting for a missing
        # hash they in fact supplied.
        raise UnresolvedModelRefError(
            f"{what} is a {form} build, but backend_profile {backend_profile!r} requires a "
            f"{expected} build (CT-CONF-03). build_id={ref.build_id!r}. The two forms are told "
            f"apart by WEIGHTS_SUFFIXES {WEIGHTS_SUFFIXES}: a path outside that list is read as "
            f"a provider-pinned slug."
        )


def _resolve_cost(cfg: Mapping[str, Any], backend_profile: str) -> tuple[Decimal | None, str | None]:
    """`FR-CONF-07`, and `CT-CONF-02`'s iff in both directions."""
    raw_ceiling = cfg.get("HARNESS_COST_CEILING")
    raw_currency = cfg.get("HARNESS_COST_CURRENCY")

    if backend_profile not in _COST_BEARING_PROFILES:
        # Inapplicable keys are ignored, not refused. `CT-CONF-02`'s iff constrains the
        # `RunConfig` *fields* — guaranteed by returning `None, None` here and re-checked in
        # `RunConfig.__post_init__` — not the `cfg` keys. Refusing on mere presence would make
        # `environment_snapshot()` a trap: it lifts all six `HARNESS_*` keys out of the
        # environment, so a `HARNESS_COST_CURRENCY` left exported from yesterday's cloud run
        # would make an `edge-local` run impossible to start.
        return None, None

    if raw_ceiling is None:
        raise ConfigurationError(
            f"HARNESS_COST_CEILING is required for backend_profile {backend_profile!r} "
            f"(FR-CONF-07)."
        )
    if raw_currency is None:
        raise ConfigurationError(
            f"HARNESS_COST_CURRENCY is required for backend_profile {backend_profile!r} "
            f"(FR-CONF-07)."
        )

    # `float` is refused rather than coerced: a ceiling is money, and binary floating point
    # cannot represent it exactly. Decimal, int and str all convert without loss.
    if isinstance(raw_ceiling, Decimal):
        ceiling = raw_ceiling
    elif isinstance(raw_ceiling, int) and not isinstance(raw_ceiling, bool):
        ceiling = Decimal(raw_ceiling)
    elif isinstance(raw_ceiling, str):
        try:
            ceiling = Decimal(raw_ceiling.strip())
        except InvalidOperation:
            raise ConfigurationError(
                "HARNESS_COST_CEILING is not a decimal number."
            ) from None
    else:
        raise ConfigurationError(
            f"HARNESS_COST_CEILING must be a Decimal, int or str, got "
            f"{type(raw_ceiling).__name__}. float is refused: a spend ceiling is money."
        )

    if not ceiling.is_finite():
        raise ConfigurationError("HARNESS_COST_CEILING must be finite.")
    # `is None` above and `< 0` here, never truthiness: Decimal("0") is falsy, and a zero
    # ceiling is a legitimate spend-nothing ceiling (TC-CONF-07).
    if ceiling < 0:
        raise ConfigurationError("HARNESS_COST_CEILING must not be negative.")

    if not isinstance(raw_currency, str) or not raw_currency.strip():
        raise ConfigurationError("HARNESS_COST_CURRENCY must be a non-empty string.")

    return ceiling, raw_currency.strip()


def _resolve_concurrency(cfg: Mapping[str, Any], policy: HardwarePolicy | None) -> int:
    """`HARNESS_CONCURRENCY` **clamps down**, never up.

    The design names the key and names the derivation without ordering them, so the precedence
    is a decision. It is clamping rather than overriding for two reasons that agree: `FR-CONF-06`
    calls the derived value a *ceiling*, and one an environment variable can raise is not a
    ceiling; and `CLAUDE.md` seam 3 exists "so a slower test box can adjust" — downward, which
    is the direction a slower box needs. Absent the key, the hardware ceiling stands; on a
    hosted backend there is no hardware to derive from, so the key stands alone over
    `DEFAULT_HOSTED_CONCURRENCY`.
    """
    raw = cfg.get("HARNESS_CONCURRENCY")
    if raw is None:
        return policy.concurrency_ceiling if policy is not None else DEFAULT_HOSTED_CONCURRENCY

    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ConfigurationError(
            f"HARNESS_CONCURRENCY must be a positive integer, got "
            f"{_echo('HARNESS_CONCURRENCY', raw)}."
        )
    try:
        concurrency = int(str(raw).strip())
    except ValueError:
        raise ConfigurationError(
            f"HARNESS_CONCURRENCY must be a positive integer, got "
            f"{_echo('HARNESS_CONCURRENCY', raw)}."
        ) from None
    if concurrency < 1:
        raise ConfigurationError(
            f"HARNESS_CONCURRENCY must be at least 1, got "
            f"{_echo('HARNESS_CONCURRENCY', raw)}."
        )
    if policy is not None:
        return min(concurrency, policy.concurrency_ceiling)
    return concurrency


def resolve_run_config(cfg: Mapping[str, Any], cohort: CohortRef) -> RunConfig:
    """Resolve `(cfg, cohort)` into one frozen `RunConfig`, or raise (design §3.1).

    Pure (`NFR-CONF-01`, `CT-CONF-05`): reads no `os.environ`, opens no file, makes no network
    call and no database read. The environment reaches it only through the snapshot the caller
    merged into `cfg` — see `environment_snapshot`. Same inputs, same result, including
    `panel_build_ref`.

    Writes nothing (`CT-CONF-09`). Every failure is raised **before** a `RunConfig` exists, so a
    failed resolution leaves no partial value to clean up (`CT-CONF-08`), and every failure is
    one of the four declared types — `TC-CONF-15`'s invariant is that no other exception escapes.

    `cohort` is accepted and not yet read: `FR-CONF-08`'s consent gate is issue #6. It is in the
    signature because the design puts it there and because #6 must not change this surface.

    Config keys, all read from `cfg`:

    | key | required | meaning |
    |---|---|---|
    | `HARNESS_PROFILE` | always | `edge-local` \\| `cloud-hosted` \\| `dev-ci`. No default |
    | `HARNESS_HARDWARE_PROFILE` | iff `edge-local` | key into `HARDWARE_PROFILES` |
    | `HARNESS_COST_CEILING` / `_CURRENCY` | iff hosted | zero accepted, negative refused |
    | `HARNESS_CONCURRENCY` | no | clamps the derived ceiling **down**; never raises it |
    | `HARNESS_ALLOW_REMOTE_REAL_WORK` | no | defaults `False`; consumed by #6 |
    | `panel` | always | 1, 3 or 5 `ModelRef`s, each `role="judge"` |
    | `transcriber` | always | `ModelRef`, `role="transcriber"` |
    | `off_panel_checker` | no | `ModelRef`, `role="off_panel"` |
    | `prompt_template_v` | always | non-empty string |
    | `retention_setting` | no | passed through; validated by #6 (`FR-CONF-12`) |
    | `hardware_profiles` | no | overrides `HARDWARE_PROFILES` for this call |
    """
    if not isinstance(cfg, Mapping):
        raise ConfigurationError(
            f"cfg must be a Mapping of configuration keys, got {type(cfg).__name__}."
        )
    if not isinstance(cohort, CohortRef):
        raise ConfigurationError(
            f"cohort must be a CohortRef, got {type(cohort).__name__}."
        )

    # 1. Backend profile. FR-CONF-01: absent or unrecognized raises rather than defaulting, and
    #    the comparison is exact — 'EDGE-LOCAL' and 'local' are both unrecognized.
    backend_profile = cfg.get("HARNESS_PROFILE")
    if not isinstance(backend_profile, str) or backend_profile not in BACKEND_PROFILES:
        raise ConfigurationError(
            f"HARNESS_PROFILE must be one of {BACKEND_PROFILES}, got "
            f"{_echo('HARNESS_PROFILE', backend_profile)}. There is no default: a silent one "
            f"would select a grader by accident (FR-CONF-01, CT-CONF-11)."
        )

    # `HARNESS_ALLOW_REMOTE_REAL_WORK` is parsed for its side effect of refusing a malformed
    # value. The gate that reads the result is FR-CONF-08, on issue #6.
    parse_allow_remote_real_work(cfg.get("HARNESS_ALLOW_REMOTE_REAL_WORK"))

    # 2. Hardware profile. FR-CONF-06 requires it for edge-local; CT-CONF-02's iff forbids it
    #    everywhere else, and asserting only the first direction would let a stray value through.
    table = cfg.get("hardware_profiles", HARDWARE_PROFILES)
    if not isinstance(table, Mapping):
        raise ConfigurationError(
            f"hardware_profiles must be a Mapping of name to HardwarePolicy, got "
            f"{type(table).__name__}."
        )
    raw_hardware = cfg.get("HARNESS_HARDWARE_PROFILE")
    policy: HardwarePolicy | None = None
    hardware_profile: str | None = None

    if backend_profile == "edge-local":
        if raw_hardware is None:
            raise ConfigurationError(
                "HARNESS_HARDWARE_PROFILE is required when HARNESS_PROFILE is 'edge-local': "
                "residency, concurrency and quantization derive from it (FR-CONF-06)."
            )
        if not isinstance(raw_hardware, str) or raw_hardware not in table:
            raise ConfigurationError(
                f"HARNESS_HARDWARE_PROFILE must be one of {tuple(table)}, got "
                f"{_echo('HARNESS_HARDWARE_PROFILE', raw_hardware)}."
            )
        policy = table[raw_hardware]
        if not isinstance(policy, HardwarePolicy):
            raise ConfigurationError(
                f"hardware_profiles[{raw_hardware!r}] must be a HardwarePolicy, got "
                f"{type(policy).__name__}."
            )
        hardware_profile = raw_hardware
    # On a hosted backend `HARNESS_HARDWARE_PROFILE` is simply inapplicable — there is no
    # residency to police — so it is ignored rather than refused, for the same reason as the
    # cost keys above. `hardware_profile` stays `None`, which is the half of `CT-CONF-02`'s iff
    # that actually constrains the type.

    # 3. Panel shape. CT-CONF-02: length 1, 3 or 5 — never even, never 0.
    raw_panel = cfg.get("panel")
    if isinstance(raw_panel, (str, bytes)) or not isinstance(raw_panel, Sequence):
        raise ConfigurationError(
            f"panel must be a sequence of ModelRef, got {type(raw_panel).__name__}."
        )
    panel = tuple(raw_panel)
    if len(panel) not in PANEL_SIZES:
        raise ConfigurationError(
            f"panel must hold {sorted(PANEL_SIZES)} judges, got {len(panel)}. An even panel "
            f"cannot break a tie and an empty one grades nothing (CT-CONF-02)."
        )
    for position, member in enumerate(panel):
        _require_model_ref(member, f"panel[{position}]", "judge")

    transcriber = _require_model_ref(cfg.get("transcriber"), "transcriber", "transcriber")

    raw_off_panel = cfg.get("off_panel_checker")
    off_panel_checker = (
        None
        if raw_off_panel is None
        else _require_model_ref(raw_off_panel, "off_panel_checker", "off_panel")
    )

    prompt_template_v = cfg.get("prompt_template_v")
    if not isinstance(prompt_template_v, str) or not prompt_template_v.strip():
        raise ConfigurationError("prompt_template_v must be a non-empty string.")

    # 4. Every reachable ModelRef is resolved, in the form this backend requires.
    for position, member in enumerate(panel):
        _check_resolved(member, f"panel[{position}]", backend_profile)
    _check_resolved(transcriber, "transcriber", backend_profile)
    if off_panel_checker is not None:
        _check_resolved(off_panel_checker, "off_panel_checker", backend_profile)

    # 5. Budgets and ceilings.
    cost_ceiling, cost_currency = _resolve_cost(cfg, backend_profile)
    concurrency_ceiling = _resolve_concurrency(cfg, policy)
    prefix_token_ceiling = (
        policy.prefix_token_ceiling if policy is not None else DEFAULT_HOSTED_PREFIX_TOKEN_CEILING
    )

    retention_setting = cfg.get("retention_setting")
    if retention_setting is not None and not isinstance(retention_setting, str):
        raise ConfigurationError(
            f"retention_setting must be a string, got {type(retention_setting).__name__}."
        )

    # 6. Nothing has been constructed until here, so no failure above leaves partial state.
    return RunConfig(
        backend_profile=backend_profile,  # type: ignore[arg-type]
        hardware_profile=hardware_profile,  # type: ignore[arg-type]
        panel=panel,
        transcriber=transcriber,
        off_panel_checker=off_panel_checker,
        prompt_template_v=prompt_template_v,
        concurrency_ceiling=concurrency_ceiling,
        prefix_token_ceiling=prefix_token_ceiling,
        cost_ceiling=cost_ceiling,
        cost_currency=cost_currency,
        retention_setting=retention_setting,
        panel_build_ref=compute_panel_build_ref(panel),
    )


#: The field names `CT-CONF-C02` asserts set equality against. Derived from the type rather than
#: written out, so it cannot drift from it — the contract case compares this against the design's
#: Interfaces list, which is the comparison that matters.
RUN_CONFIG_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(RunConfig))
