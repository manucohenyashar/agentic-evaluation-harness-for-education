"""M-CONF: the deployment profile and the frozen configuration of a run (design §3.1).

Configuration comes from six `HARNESS_*` environment keys and an optional config file. It is
resolved once, when a run starts, into a frozen `RunConfig`: the backend profile, the pinned
build of every model (panel judges, transcriber, off-panel checker), concurrency, cost and
retention settings, and the decision engine. Floating model tags are refused; every build must
be pinned. A remote provider is refused for real student work unless consent is recorded. A
resumed run is compared with the current configuration and refused on any mismatch.

Files:
    vocabulary.py      the backend profiles, model roles and panel sizes
    errors.py          the errors this package raises
    frozen.py          making value objects refuse mutation
    model_ref.py       `ModelRef`, a pinned build identity, and the floating-tag check
    hardware.py        edge hardware profiles and the policy each implies
    decision_engine.py `DecisionEngine` and its defaults and bounds
    checks.py          checks shared by `RunConfig` and its resolution
    run_config.py      `RunConfig`, `CohortRef` and the profile summary shown to people
    sources.py         reading the environment and config files, and the start-up banner
    panel.py           the stable hash over the ordered judge panel
    consent.py         the consent gate for remote providers
    resolution.py      `resolve_run_config`: environment and file in, one frozen `RunConfig` out
    rehydrate.py       rebuilding a stored run's config and refusing a mismatched resume
    audit_log.py       the one structured log line a run start emits

Detailed design notes (the full original module description): `docs/code-notes/conf.md`.
"""

from __future__ import annotations

from .vocabulary import (
    BACKEND_PROFILES,
    BackendProfile,
    BuildForm,
    HardwareProfileName,
    ModelRole,
    PANEL_SIZES,
)
from .errors import (
    BackendMismatchError,
    ConfigurationError,
    ConsentGateError,
    RunConfigError,
    UnresolvedModelRefError,
)
from . import frozen  # noqa: F401  (imported for its registrations)
from .model_ref import FLOATING_TAGS, ModelRef, WEIGHTS_SUFFIXES
from .hardware import (
    DEFAULT_HOSTED_CONCURRENCY,
    DEFAULT_HOSTED_PREFIX_TOKEN_CEILING,
    hardware_policy_for,
    HARDWARE_PROFILES,
    HardwarePolicy,
)
from .decision_engine import (
    _canonical_decimal,
    CONFIDENCE_THRESHOLD_ENV_KEY,
    CONFIDENCE_THRESHOLD_FILE_KEY,
    DEFAULT_DECISION_ENGINE_BY_PROFILE,
    DECISION_ENGINES,
    DECISION_PLACEMENTS,
    DECISION_PROVIDERS_BY_PROFILE,
    DecisionEngine,
    DEFAULT_CITE_THRESHOLD,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_MAX_CITATION_QUESTIONS,
    DEFAULT_TOKEN_BYTES_RATIO,
    FIXTURE_DECISION_PROVIDER,
    PROVIDER_DEFAULT_THRESHOLDS,
    PROVIDER_MANAGED,
)
from .checks import RETENTION_SETTINGS
from .run_config import BuildSummary, CohortRef, ProfileSummary, RunConfig
from .sources import (
    CONSOLE_KEYS,
    DECISION_KEYS,
    effective_config,
    environment_snapshot,
    format_profile_banner,
    HARNESS_KEYS,
    parse_allow_remote_real_work,
    parse_config_document,
    profile_source,
    PROFILE_SOURCE_CONFIG_FILE,
    PROFILE_SOURCE_ENVIRONMENT,
    resume_profile_conflict,
    select_profile_config,
)
from .panel import compute_panel_build_ref
from .consent import consent_override_for, CONSENTED_CLASSES, ConsentOverride, REMOTE_PROFILES
from .qa_model import QA_MODEL_KEY
from .resolution import resolve_run_config
from .rehydrate import rehydrate_run_config, RUN_CONFIG_FIELDS
from .audit_log import log_run_start, LOGGER_NAME, RUN_START_EVENT


__all__ = [
    "BackendMismatchError",
    "BackendProfile",
    "BuildSummary",
    "CohortRef",
    "compute_panel_build_ref",
    "ConfigurationError",
    "consent_override_for",
    "CONSOLE_KEYS",
    "effective_config",
    "format_profile_banner",
    "parse_config_document",
    "PROFILE_SOURCE_CONFIG_FILE",
    "PROFILE_SOURCE_ENVIRONMENT",
    "profile_source",
    "resume_profile_conflict",
    "select_profile_config",
    "CONSENTED_CLASSES",
    "ConsentGateError",
    "ConsentOverride",
    "DEFAULT_HOSTED_CONCURRENCY",
    "DEFAULT_HOSTED_PREFIX_TOKEN_CEILING",
    "environment_snapshot",
    "FLOATING_TAGS",
    "hardware_policy_for",
    "HARDWARE_PROFILES",
    "HardwarePolicy",
    "HARNESS_KEYS",
    "log_run_start",
    "LOGGER_NAME",
    "ModelRef",
    "PANEL_SIZES",
    "parse_allow_remote_real_work",
    "ProfileSummary",
    "PROVIDER_MANAGED",
    "rehydrate_run_config",
    "REMOTE_PROFILES",
    "resolve_run_config",
    "RETENTION_SETTINGS",
    "RUN_CONFIG_FIELDS",
    "RUN_START_EVENT",
    "RunConfig",
    "RunConfigError",
    "UnresolvedModelRefError",
    "WEIGHTS_SUFFIXES",
]
