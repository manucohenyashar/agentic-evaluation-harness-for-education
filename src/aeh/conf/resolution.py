"""`resolve_run_config`: turns the environment and config file into one frozen `RunConfig`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from .vocabulary import BACKEND_PROFILES, PANEL_SIZES
from .errors import BackendMismatchError, ConfigurationError, ConsentGateError
from .model_ref import _ISO_4217, ModelRef, _require_model_ref
from .hardware import (
    DEFAULT_HOSTED_CONCURRENCY,
    DEFAULT_HOSTED_PREFIX_TOKEN_CEILING,
    HARDWARE_PROFILES,
    HardwarePolicy,
)
from .decision_engine import (
    _bounded_int,
    _decimal_knob,
    DECISION_ENGINES,
    DECISION_PROVIDERS_BY_PROFILE,
    DecisionEngine,
    DEFAULT_CITE_THRESHOLD,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_MAX_CITATION_QUESTIONS,
    DEFAULT_TOKEN_BYTES_RATIO,
    FIXTURE_DECISION_PROVIDER,
    PROVIDER_DEFAULT_THRESHOLDS,
)
from .checks import (
    _check_resolved,
    _COST_BEARING_PROFILES,
    _echo,
    _positive_int,
    RETENTION_SETTINGS,
)
from .run_config import CohortRef, RunConfig
from .sources import parse_allow_remote_real_work
from .panel import compute_panel_build_ref
from .consent import _check_consent, REMOTE_PROFILES


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

    # An ISO-4217 alpha code: exactly three uppercase letters. Not decoration --
    # `HARNESS_COST_CURRENCY` was the **only** free-text field reaching `provider_config`, and
    # `FR-CONF-11` names "the serialized `provider_config` matches no credential pattern" as this
    # requirement's acceptance form. With this check every value in that dict is a validated
    # enum, an integer, a Decimal string or a currency code, so the property holds *structurally*
    # rather than by a scan happening not to find anything. Found by TC-CONF-11 planting a
    # sentinel there and watching it reach the run row.
    if not isinstance(raw_currency, str) or not _ISO_4217.match(raw_currency.strip()):
        raise ConfigurationError(
            "HARNESS_COST_CURRENCY must be a three-letter ISO-4217 code such as 'USD'. The "
            "supplied value is not echoed here (NFR-CONF-02)."
        )

    return ceiling, raw_currency.strip()


def _resolve_retention_setting(cfg: Mapping[str, Any], backend_profile: str) -> str | None:
    """`FR-CONF-12`, and `CT-CONF-02`'s "non-null for `cloud-hosted`".

    Required only on `cloud-hosted`. `dev-ci` also dispatches remotely and is still exempt,
    because the design scopes the requirement to `cloud-hosted` in both `FR-CONF-12` and
    `CT-CONF-02`; `dev-ci`'s protection is the consent gate above, which covers it.
    """
    raw = cfg.get("retention_setting")

    if backend_profile != "cloud-hosted":
        return None  # inapplicable keys are ignored, as elsewhere in this resolver

    if raw is None:
        raise ConfigurationError(
            "retention_setting is required for backend_profile 'cloud-hosted' (FR-CONF-12). "
            "Absence is not permission to use the provider's default: an unset value is how a "
            "run proceeds believing retention is off when it is not."
        )
    if raw not in RETENTION_SETTINGS:
        # The legal set, never the rejected value: `retention_setting` is caller data and
        # `NFR-CONF-02` forbids echoing it, the same rule `_ECHOABLE_KEYS` states for the
        # `HARNESS_*` keys.
        raise ConfigurationError(
            f"retention_setting must be one of {RETENTION_SETTINGS} (FR-CONF-12). The supplied "
            f"value is not echoed here; it is not one of them."
        )
    return raw


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

    `cohort` is read by the consent gate (`FR-CONF-08`), which runs last — see `_check_consent`.
    When that gate passes **because of an override**, `M-ORCH` must also call
    `consent_override_for(cfg, cohort)` and persist the record it returns: this module writes
    nothing (`CT-CONF-09`), so resolution alone leaves no audit trail of who authorised the
    remote dispatch of real student work.

    Config keys, all read from `cfg`:

    | key | required | meaning |
    |---|---|---|
    | `HARNESS_PROFILE` | always | `edge-local` \\| `cloud-hosted` \\| `dev-ci`. No default |
    | `HARNESS_HARDWARE_PROFILE` | iff `edge-local` | key into `HARDWARE_PROFILES` |
    | `HARNESS_COST_CEILING` / `_CURRENCY` | iff hosted | zero accepted, negative refused |
    | `HARNESS_CONCURRENCY` | no | clamps the derived ceiling **down**; never raises it |
    | `HARNESS_ALLOW_REMOTE_REAL_WORK` | no | defaults `False`; overrides the consent gate, and **requires** `allow_remote_real_work_supplied_by` |
    | `panel` | always | 1, 3 or 5 `ModelRef`s, each `role="judge"` |
    | `transcriber` | always | `ModelRef`, `role="transcriber"` |
    | `off_panel_checker` | no | `ModelRef`, `role="off_panel"` |
    | `prompt_template_v` | always | non-empty string |
    | `retention_setting` | **iff `cloud-hosted`** | one of `RETENTION_SETTINGS`; unset or unrecognized is refused (`FR-CONF-12`) |
    | `allow_remote_real_work_supplied_by` | iff the override is used | who authorised sending real work remotely; the override is refused without it |
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

    # Parsed here for its side effect of refusing a malformed value; the gate that acts on it
    # runs last, once the config is otherwise known good (FR-CONF-08).
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
    # On `edge-local` the ceiling comes from the hardware policy, and `cfg["hardware_profiles"]`
    # is its knob — swapping a whole coherent cell rather than one number, so `unified-large`
    # can never end up paired with a ceiling meant for a smaller box. A hosted backend has no
    # policy to derive from, so it gets its own knob rather than a constant with no way to
    # adjust it (`CLAUDE.md` seam 3).
    if policy is not None:
        prefix_token_ceiling = policy.prefix_token_ceiling
    else:
        prefix_token_ceiling = _positive_int(
            cfg.get("hosted_prefix_token_ceiling"),
            "hosted_prefix_token_ceiling",
            default=DEFAULT_HOSTED_PREFIX_TOKEN_CEILING,
        )

    retention_setting = _resolve_retention_setting(cfg, backend_profile)

    # 5b. The decision engine (Jev design delta FR-CONF-17…23), frozen here with its values.
    decision_engine = _resolve_decision_engine(cfg, backend_profile, policy, hardware_profile)
    if decision_engine is not None and backend_profile in REMOTE_PROFILES:
        # FR-CONF-24: a remote decision engine dispatches student work exactly as the panel
        # does, so the consent gate below covers it; name it in the refusal.
        try:
            _check_consent(cfg, cohort, backend_profile)
        except ConsentGateError as error:
            raise ConsentGateError(
                f"{error} The run's decision engine ({decision_engine.model.provider}) would also "
                f"send this cohort's work off the machine (FR-CONF-24).") from None

    # 6. The consent gate (FR-CONF-08), last because it is the only check that reads `cohort`:
    #    a malformed config reports the malformation, and a well-formed one gets an unambiguous
    #    consent verdict rather than one buried behind a typo.
    _check_consent(cfg, cohort, backend_profile)

    # 7. Nothing has been constructed until here, so no failure above leaves partial state.
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
        panel_build_ref=compute_panel_build_ref(panel, decision_engine),
        decision_engine=decision_engine,
    )


def _resolve_decision_engine(cfg: Mapping[str, Any], backend_profile: str,
                             policy: HardwarePolicy | None, hardware_profile: str | None) -> DecisionEngine | None:
    """FR-CONF-17…23. `HARNESS_DECISION_ENGINE` is required (`jev`/`off`), with no default.

    The model comes from `cfg["decision_model"]` (a `ModelRef`, or a table in a config file) or
    from `HARNESS_JEV_BUILD` + `HARNESS_DECISION_PROVIDER` (default: the backend's provider) +
    `HARNESS_JEV_QUANTIZATION`. The four gate values are read once, here (CT-CONF-18)."""
    raw = cfg.get("HARNESS_DECISION_ENGINE")
    if raw is None:
        raise ConfigurationError(
            "HARNESS_DECISION_ENGINE is required: 'jev' or 'off'. It has no default, because a "
            "default would choose the grading engine for you (FR-CONF-18, CT-CONF-11).")
    if raw not in DECISION_ENGINES:
        raise ConfigurationError(
            f"HARNESS_DECISION_ENGINE must be one of {DECISION_ENGINES}, got "
            f"{_echo('HARNESS_DECISION_ENGINE', raw)}.")
    if raw == "off":
        return None
    allowed = DECISION_PROVIDERS_BY_PROFILE[backend_profile]
    model = cfg.get("decision_model")
    if model is None:
        build = cfg.get("HARNESS_JEV_BUILD")
        if not isinstance(build, str) or not build.strip():
            raise ConfigurationError(
                "HARNESS_JEV_BUILD is required when HARNESS_DECISION_ENGINE is 'jev' (FR-CONF-20).")
        provider = cfg.get("HARNESS_DECISION_PROVIDER") or allowed[0]
        quantization = cfg.get("HARNESS_JEV_QUANTIZATION") or None
        try:
            model = ModelRef(role="decision", provider=provider, build_id=build.strip(), quantization=quantization)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"the decision model is malformed: {exc}") from None
    model = _require_model_ref(model, "decision_model", "decision")
    provider = model.provider
    if provider == FIXTURE_DECISION_PROVIDER:
        if not cfg.get("HARNESS_FIXTURE_DIR"):
            raise ConfigurationError(
                "the 'fixture' decision provider is accepted only under the test tier "
                "(HARNESS_FIXTURE_DIR set) (FR-CONF-19).")
    elif provider not in allowed:
        raise BackendMismatchError(
            f"decision provider {provider!r} is not bound to backend_profile {backend_profile!r}; "
            f"it admits {allowed} (FR-CONF-19).")
    _check_resolved(model, "decision_model", backend_profile)
    if policy is not None and provider != FIXTURE_DECISION_PROVIDER and provider not in policy.decision_coresident:
        alternatives = [f"'{name}'" for name in policy.decision_coresident] + ["HARNESS_DECISION_ENGINE=off"]
        raise ConfigurationError(
            f"hardware profile {hardware_profile!r} cannot hold decision provider {provider!r} "
            f"beside the judge (FR-CONF-23, FR-CONF-28). Admitted alternatives: {', '.join(alternatives)}.")
    default_threshold = Decimal(PROVIDER_DEFAULT_THRESHOLDS.get(provider, DEFAULT_CONFIDENCE_THRESHOLD))
    return DecisionEngine(
        model=model,
        confidence_threshold=_decimal_knob(cfg.get("HARNESS_JEV_CONFIDENCE_THRESHOLD"),
                                           "HARNESS_JEV_CONFIDENCE_THRESHOLD", default_threshold,
                                           Decimal("0.50"), Decimal("1.00"), high_inclusive=False),
        cite_threshold=_decimal_knob(cfg.get("HARNESS_JEV_CITE_THRESHOLD"), "HARNESS_JEV_CITE_THRESHOLD",
                                     Decimal(DEFAULT_CITE_THRESHOLD), Decimal("0"), Decimal("1"),
                                     high_inclusive=False, low_inclusive=False),
        max_citation_questions=_bounded_int(cfg.get("HARNESS_JEV_MAX_CITATION_QUESTIONS"),
                                            "HARNESS_JEV_MAX_CITATION_QUESTIONS",
                                            DEFAULT_MAX_CITATION_QUESTIONS, 1, 26),
        token_bytes_ratio=_bounded_int(cfg.get("HARNESS_JEV_TOKEN_BYTES_RATIO"),
                                       "HARNESS_JEV_TOKEN_BYTES_RATIO", DEFAULT_TOKEN_BYTES_RATIO, 1, 8),
    )
