"""Where configuration comes from: the environment, config files, and the start-up banner."""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping
from typing import Any, Literal

from .errors import ConfigurationError
from .model_ref import ModelRef, _REF_FIELDS
from .checks import _echo
from .run_config import RunConfig


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


_TRUE_TOKENS = frozenset({"true", "1", "yes", "on"})


_FALSE_TOKENS = frozenset({"false", "0", "no", "off", ""})


#: The console's two socket keys (`FR-CONF-14`). Kept out of `HARNESS_KEYS`, which stays six and
#: is what the default snapshot lifts; `effective_config` asks for these explicitly.
CONSOLE_KEYS: tuple[str, ...] = ("CONSOLE_BIND", "CONSOLE_PORT")


#: The decision-engine keys (Jev design delta FR-CONF-18…21). Kept out of `HARNESS_KEYS` for the
#: same reason as `CONSOLE_KEYS`; `effective_config` lifts them, so an exported
#: `HARNESS_DECISION_ENGINE=off` overrides a config file's `jev` exactly as `HARNESS_PROFILE`
#: overrides the file's profile. None is a credential.
DECISION_KEYS: tuple[str, ...] = (
    "HARNESS_DECISION_ENGINE",
    "HARNESS_DECISION_PROVIDER",
    "HARNESS_JEV_BUILD",
    "HARNESS_JEV_QUANTIZATION",
    "HARNESS_JEV_CONFIDENCE_THRESHOLD",
    "HARNESS_JEV_CITE_THRESHOLD",
    "HARNESS_JEV_MAX_CITATION_QUESTIONS",
    "HARNESS_JEV_TOKEN_BYTES_RATIO",
    # FR-CONF-30: the Q&A assistant's model on the cloud profiles, lifted the same way.
    "HARNESS_QA_MODEL",
)


#: Where `HARNESS_PROFILE` came from, as `profile_source` reports it (`FR-CONF-16`).
PROFILE_SOURCE_ENVIRONMENT = "environment"


PROFILE_SOURCE_CONFIG_FILE = "config file"


def environment_snapshot(
    environ: Mapping[str, str] | None = None, *, include_console: bool = False,
    include_decision: bool = False,
) -> dict[str, str]:
    """Read the six `HARNESS_*` keys from the process environment, once, for a caller to merge into
    `cfg`.

    Deliberately **not** called by `resolve_run_config`. `NFR-CONF-01` and `CT-CONF-05` require
    resolution to be a pure function whose environment enters "only through the snapshot in
    `cfg`" — so the one function that reads `os.environ` is this one, and it is the caller's.

    `include_console=True` also lifts `CONSOLE_KEYS` — the console's bind and port, which
    `effective_config` composes under the same environment-wins rule (`FR-CONF-14`). The default
    snapshot is unchanged: exactly the `HARNESS_*` keys.
    """
    source = os.environ if environ is None else environ
    keys = HARNESS_KEYS + (CONSOLE_KEYS if include_console else ()) + (
        DECISION_KEYS if include_decision else ())
    return {key: source[key] for key in keys if key in source}


def parse_config_document(text: str, fmt: Literal["json", "toml"]) -> dict[str, Any]:
    """Parse the text of a config file into a mapping (FR-CONF-13).

    The caller reads the file — this module opens none (`NFR-CONF-01`) — and names the format,
    normally from the extension (`.json` → `"json"`, `.toml` → `"toml"`). A document whose top
    level is not a table raises `ConfigurationError`, as does a document that does not parse;
    the parser's message is not echoed, since a malformed line may hold a credential.

    A file can only spell a model as a table, so the `panel` entries, `transcriber` and
    `off_panel_checker` — at top level and in each `profiles` section — are built into
    `ModelRef`s here, which is what `resolve_run_config` requires. An absent `quantization`
    reads as `None` (TOML has no null).
    """
    if fmt == "json":
        try:
            parsed: Any = json.loads(text)
        except ValueError:
            raise ConfigurationError("the config file is not valid JSON.") from None
    elif fmt == "toml":
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            raise ConfigurationError("the config file is not valid TOML.") from None
    else:
        raise ConfigurationError(f"config format must be 'json' or 'toml', got {fmt!r}.")
    if not isinstance(parsed, dict):
        raise ConfigurationError("a config file's top level must be a table of keys.")
    parsed = _model_tables_to_refs(parsed, "the config file")
    sections = parsed.get("profiles")
    if isinstance(sections, dict):
        parsed["profiles"] = {
            name: _model_tables_to_refs(section, f"profile section {name!r}")
            if isinstance(section, dict)
            else section
            for name, section in sections.items()
        }
    return parsed


#: The `cfg` keys whose values `resolve_run_config` requires as `ModelRef`s. A file can only spell
#: them as tables, so `parse_config_document` builds the refs.
_FILE_MODEL_KEYS: tuple[str, ...] = ("transcriber", "off_panel_checker")


def _file_ref(raw: Any, what: str) -> ModelRef:
    """Build one `ModelRef` from a config-file table. TOML has no null, so a missing `quantization`
    means None (a provider-pinned build); the other three fields are required."""
    if not isinstance(raw, Mapping):
        raise ConfigurationError(
            f"{what} must be a table of {_REF_FIELDS}, got {type(raw).__name__}."
        )
    unknown = sorted(str(name) for name in raw if name not in _REF_FIELDS)
    if unknown:
        raise ConfigurationError(f"{what} has unknown keys: {', '.join(unknown)}.")
    missing = [name for name in _REF_FIELDS[:3] if name not in raw]
    if missing:
        raise ConfigurationError(f"{what} is missing {', '.join(missing)}.")
    return ModelRef(**{name: raw.get(name) for name in _REF_FIELDS})


def _model_tables_to_refs(table: dict[str, Any], where: str) -> dict[str, Any]:
    """The table with its `panel`, `transcriber` and `off_panel_checker` entries turned into
    `ModelRef`s. Everything else passes through for `resolve_run_config` to check."""
    converted = dict(table)
    panel = converted.get("panel")
    if isinstance(panel, list) and all(isinstance(entry, Mapping) for entry in panel):
        converted["panel"] = tuple(
            _file_ref(entry, f"{where}: panel[{index}]") for index, entry in enumerate(panel)
        )
    for key in _FILE_MODEL_KEYS:
        if isinstance(converted.get(key), Mapping):
            converted[key] = _file_ref(converted[key], f"{where}: {key}")
    return converted


def select_profile_config(file_cfg: Mapping[str, Any], profile: str | None) -> dict[str, Any]:
    """The configuration for one backend profile, taken from a file that holds several
    (FR-CONF-13).

    A file may declare a `profiles` table with one section per backend profile, next to shared
    top-level keys. The result is the shared keys overlaid by `profiles[profile]`, with
    `HARNESS_PROFILE` set to `profile` — one file serves every profile, so switching needs no
    file edit, only a different `HARNESS_PROFILE` (normally from the environment, see
    `effective_config`).

    A file with **no** `profiles` table is returned as an equal copy, so single-profile files
    keep working. Pure: the input is never mutated, and the same inputs give an equal result.

    With `profile=None` the shared keys are returned without a `HARNESS_PROFILE`, leaving the
    no-default refusal to `resolve_run_config` (`FR-CONF-01`).

    Raises `ConfigurationError` when the `profiles` table is malformed, when the selected
    profile has no section (naming the profile and the sections present), or when a section's
    own `HARNESS_PROFILE` names a different profile.
    """
    if not isinstance(file_cfg, Mapping):
        raise ConfigurationError(
            f"file_cfg must be a Mapping of configuration keys, got {type(file_cfg).__name__}."
        )
    if "profiles" not in file_cfg:
        return dict(file_cfg)

    sections = file_cfg["profiles"]
    if not isinstance(sections, Mapping) or not all(
        isinstance(name, str) and isinstance(section, Mapping)
        for name, section in sections.items()
    ):
        raise ConfigurationError(
            "the config file's `profiles` table must map each profile name to a table of keys."
        )
    present = ", ".join(repr(name) for name in sorted(sections)) or "none"
    shared = {key: value for key, value in file_cfg.items() if key != "profiles"}
    if profile is None:
        # No profile selected, so no section applies: the shared keys alone, still without a
        # `HARNESS_PROFILE`, so `resolve_run_config` raises its own no-default refusal
        # (`FR-CONF-01`) rather than this function inventing one.
        return shared
    if not isinstance(profile, str):
        raise ConfigurationError(
            f"HARNESS_PROFILE must be a string naming a profile section, got "
            f"{type(profile).__name__}; sections present: {present}."
        )
    if profile not in sections:
        raise ConfigurationError(
            f"the config file has no section for {_echo('HARNESS_PROFILE', profile)}; "
            f"sections present: {present}."
        )
    section = sections[profile]
    declared = section.get("HARNESS_PROFILE", profile)
    if declared != profile:
        raise ConfigurationError(
            f"the config file's section {profile!r} declares HARNESS_PROFILE "
            f"{_echo('HARNESS_PROFILE', declared)}; a section may only configure its own profile."
        )

    selected = shared
    selected.update(section)
    selected["HARNESS_PROFILE"] = profile
    return selected


def effective_config(
    cfg: Mapping[str, Any] | None = None, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Combine the config file and the environment into the configuration every entry point uses;
    the environment wins (FR-CONF-14, CT-CONF-15).

    1. `snapshot` = the `HARNESS_*` and `CONSOLE_*` keys from the environment;
    2. the profile is the environment's `HARNESS_PROFILE`, else `cfg`'s;
    3. `base` = `select_profile_config(cfg, profile)` — the profile's section of a multi-profile
       file, or `cfg` itself;
    4. the result is `{**base, **snapshot}`: **the environment wins** for every key it carries.

    So switching harness profiles is one environment variable: set `HARNESS_PROFILE` and start
    a new process (or create a new run from a console whose environment was updated), with no
    code or file change. `resolve_run_config` stays pure — it receives this composed dict. A
    resumed run is never rebound by a switch; see `resume_profile_conflict` (`FR-CONF-15`).

    `environ=None` reads the real environment through `environment_snapshot`, still the only
    reader of `os.environ`; pass a mapping to compose against a supplied one.
    """
    if cfg is not None and not isinstance(cfg, Mapping):
        raise ConfigurationError(f"cfg must be a Mapping, got {type(cfg).__name__}.")
    base_cfg: Mapping[str, Any] = cfg if cfg is not None else {}
    snapshot = environment_snapshot(environ, include_console=True, include_decision=True)
    profile = snapshot.get("HARNESS_PROFILE", base_cfg.get("HARNESS_PROFILE"))
    base = select_profile_config(base_cfg, profile)
    return {**base, **snapshot}


def profile_source(
    cfg: Mapping[str, Any] | None = None, environ: Mapping[str, str] | None = None
) -> str | None:
    """Where the effective `HARNESS_PROFILE` came from: `"environment"`, `"config file"`, or None
    when neither sets it (FR-CONF-16)."""
    if "HARNESS_PROFILE" in environment_snapshot(environ):
        return PROFILE_SOURCE_ENVIRONMENT
    if isinstance(cfg, Mapping) and cfg.get("HARNESS_PROFILE") is not None:
        return PROFILE_SOURCE_CONFIG_FILE
    return None


def format_profile_banner(config: RunConfig, source: str | None) -> str:
    """The lines an entry point prints at start-up (FR-CONF-16): the resolved profile summary and
    where `HARNESS_PROFILE` came from, so an operator can see which profile is in effect. It shows
    only build identities and names, nothing else from the environment (CT-CONF-10)."""
    summary = config.profile_summary()
    return (
        f"HARNESS_PROFILE: {summary.backend_profile}\n"
        f"HARNESS_PROFILE source: {source if source is not None else 'unset'}\n"
        f"{_decision_banner_lines(config)}\n"
        f"{_qa_banner_line(config)}\n"
        f"profile_summary: {summary.to_canonical_json()}"
    )


def _decision_banner_lines(config: RunConfig) -> str:
    """The start-up lines saying which engine grades (FR-CONF-25) and, when it is on, the gate
    that decides whether its verdict counts (FR-CONF-32)."""
    engine = config.decision_engine
    if engine is None:
        return "DECISION_ENGINE: off"
    return (f"DECISION_ENGINE: {engine.model.provider}:{engine.model.build_id} "
            f"threshold={engine.confidence_threshold}\n"
            f"DECISION_GATE: jev > {engine.confidence_threshold}")


def _qa_banner_line(config: RunConfig) -> str:
    """The start-up line naming the Q&A assistant's model (FR-CONF-30)."""
    model = config.assistant_model()
    return f"QA_ASSISTANT: {model.provider}:{model.build_id}"


def resume_profile_conflict(
    run_row: Mapping[str, Any], effective: Mapping[str, Any]
) -> str | None:
    """The pause reason when a run would resume under a different profile, or None (FR-CONF-15,
    CT-CONF-16).

    A switch never rebinds an existing run (`FR-CONF-04`): a run keeps the `backend_profile`
    persisted on its row. When the effective configuration now selects another profile, the
    caller (`recover`) leaves that run paused with this reason — naming both values — rather
    than raising and abandoning the other runs. `None` when the profiles agree or the effective
    configuration names none.
    """
    if not isinstance(run_row, Mapping) or not isinstance(effective, Mapping):
        raise ConfigurationError("run_row and effective must both be Mappings.")
    persisted = run_row.get("backend_profile")
    requested = effective.get("HARNESS_PROFILE")
    if requested is None or requested == persisted:
        return None
    run_id = run_row.get("run_id")
    which = f"run {run_id}" if isinstance(run_id, str) else "this run"
    return (
        f"{which} was created under {_echo('HARNESS_PROFILE', persisted)}; the environment now "
        f"selects {_echo('HARNESS_PROFILE', requested)}. A resumed run keeps its persisted "
        f"profile (FR-CONF-15): set HARNESS_PROFILE back to resume it, or start a new run."
    )


def parse_allow_remote_real_work(value: Any) -> bool:
    """Read `HARNESS_ALLOW_REMOTE_REAL_WORK`, which defaults to False (CT-CONF-11).

    The string `"false"` must not be truthy-coerced — a non-empty string is truthy in Python, so
    a bare `bool(value)` here would open the consent gate for every operator who set the key to
    turn the override *off*. The gate that consumes it is `_check_consent`; the parse is separate
    so a malformed value fails at resolution rather than silently reading as `True` later.
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
