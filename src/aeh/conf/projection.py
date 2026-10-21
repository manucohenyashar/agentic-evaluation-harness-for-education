"""The configuration projection (FR-CONF-35): every setting as a renderable view model.

`/settings` renders **this**, never the configuration file: every setting with its teacher
label, its current value as the configuration in force, a type tag for form rendering, and an
`editable` flag that is false for everything outside FR-CONF-34's subset. Secrets project as a
boolean "configured" state and never as a value (CT-CONF-19's no-secret-emission rule extended
to the projection), and no key name from the configuration file appears in any string the
projection emits — the vocabulary scan asserts both against these strings.

The values are read from the **composed** configuration the caller passes — what
`effective_config` produced, environment already over file — so what a teacher sees is what a
run would use, never the file's text (`FR-CONSOLE-60`: resolved config, never the file). The
readers are the resolver's own helpers (`_resolve_cost`, `resolve_qa_model`, …), so the
projection and the resolver cannot disagree about a value: there is one reading of each
setting, and both surfaces make it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .checks import RETENTION_SETTINGS, _echo, _positive_int
from .decision_engine import (
    DEFAULT_CITE_THRESHOLD,
    DEFAULT_MAX_CITATION_QUESTIONS,
    DEFAULT_TOKEN_BYTES_RATIO,
    DECISION_ENGINES,
    DECISION_PROVIDERS_BY_PROFILE,
    _bounded_int,
    _canonical_decimal,
    _decimal_knob,
    decision_engine_setting,
)
from .errors import ConfigurationError
from .hardware import DEFAULT_HOSTED_PREFIX_TOKEN_CEILING, HARDWARE_PROFILES
from .model_ref import ModelRef
from .orch_knobs import BUDGET_LABEL, SAMPLE_LABEL, resolve_orch_knobs
from .qa_model import resolve_qa_model
from .resolution import (
    _resolve_confidence_threshold,
    _resolve_concurrency,
    _resolve_cost,
    _resolve_retention_setting,
)
from .sources import _file_ref
from .vocabulary import BACKEND_PROFILES


#: FR-CONF-34's teacher-editable subset, as the projection's `setting` ids. This is the set
#: `update_profile_edits` accepts — the projection's `editable` flag and the write path's
#: allow-list are one list, so a setting cannot render as editable and refuse the edit (or the
#: reverse). The subset: the model per action role (the grader, the page reader, the Q&A
#: assistant, the decision engine's build), the cost ceiling, the decision engine choice, and
#: the decision engine's four review-window gates. Deliberately outside it: the second-opinion
#: checker (its identity is load-bearing for calibration records, CT-CALIB-08 — it is not a
#: per-action grading role), and every transport, fixture and knob setting.
EDITABLE_SETTINGS: tuple[str, ...] = (
    "grading_model",
    "page_reader_model",
    "qa_assistant_model",
    "decision_engine_model",
    "decision_engine",
    "decision_confidence_gate",
    "decision_citation_gate",
    "decision_citation_question_limit",
    "decision_token_bytes_ratio",
    "cost_ceiling",
)

_EDITABLE: frozenset[str] = frozenset(EDITABLE_SETTINGS)


#: The id that names the model provider's credential. `OPENROUTER_API_KEY` is the one secret
#: the harness reads (`prov/settings.py`); the projection carries it under this id, and only
#: ever as `configured`.
_MODEL_PROVIDER_KEY_ID = "model_provider_key"


@dataclass(frozen=True)
class SettingView:
    """One setting as `/settings` renders it.

    `value` is always a string — the value in force, empty when the setting does not apply to
    the configuration's profile (a machine profile on a hosted backend, a cost ceiling on
    `edge-local`). Model settings render the pinned identity in the same `provider|build_id[|
    quantization]` form the guided form accepts back, so what is shown is what can be edited.
    A secret's `value` is always the empty string; whether it is set arrives as `configured`.
    """

    setting: str
    label: str
    value: str
    type: str
    editable: bool
    choices: tuple[str, ...] = ()
    configured: bool | None = None


def _ref_of(entry: Any, what: str) -> ModelRef:
    """The entry as a `ModelRef`: already one, or a config-file model table converted through
    the same `_file_ref` rules the parser uses (`panel_profile._judge_refs`'s tolerance)."""
    if isinstance(entry, ModelRef):
        return entry
    if isinstance(entry, Mapping):
        return _file_ref(entry, what)
    raise ConfigurationError(f"{what} must be a model table, got {type(entry).__name__}.")


def _ref_text(ref: ModelRef) -> str:
    """The pinned identity as the form spells it: `provider|build_id[|quantization]` — the
    convention `HARNESS_EXTRACT_SECOND_FAMILY_MODEL` documents (`pipeline/runtime._parse_pin`)."""
    quantization = f"|{ref.quantization}" if ref.quantization else ""
    return f"{ref.provider}|{ref.build_id}{quantization}"


def _panel_refs(cfg: Mapping[str, Any]) -> tuple[ModelRef, ...]:
    raw = cfg.get("panel")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ConfigurationError(
            f"panel must be a sequence of model tables, got {type(raw).__name__}.")
    return tuple(_ref_of(member, f"panel[{position}]") for position, member in enumerate(raw))


def _decision_provider(cfg: Mapping[str, Any], backend_profile: str) -> str:
    """The decision provider in force: the declared one, else the backend's binding default —
    the same two lines `_resolve_decision_engine` reads it from."""
    return str(cfg.get("HARNESS_DECISION_PROVIDER") or DECISION_PROVIDERS_BY_PROFILE[backend_profile][0])


def _decision_model_text(cfg: Mapping[str, Any], backend_profile: str) -> str:
    raw = cfg.get("decision_model")
    if isinstance(raw, ModelRef):
        return _ref_text(raw)
    if isinstance(raw, Mapping):
        return _ref_text(_ref_of(raw, "decision_model"))
    build = cfg.get("HARNESS_JEV_BUILD")
    if build is None or (isinstance(build, str) and not build.strip()):
        return ""
    ref = ModelRef(
        role="decision",
        provider=_decision_provider(cfg, backend_profile),
        build_id=str(build).strip(),
        quantization=cfg.get("HARNESS_JEV_QUANTIZATION") or None,
    )
    return _ref_text(ref)


def _panel_text(refs: tuple[ModelRef, ...]) -> str:
    identities = {(ref.provider, ref.build_id, ref.quantization) for ref in refs}
    if len(identities) <= 1:
        return _ref_text(refs[0]) if refs else ""
    return "; ".join(_ref_text(ref) for ref in refs)


def _hardware_policy(cfg: Mapping[str, Any], backend_profile: str):
    if backend_profile != "edge-local":
        return None
    table = cfg.get("hardware_profiles", HARDWARE_PROFILES)
    raw = cfg.get("HARNESS_HARDWARE_PROFILE")
    if isinstance(raw, str) and raw in table:
        return table[raw]
    return None


def _decimal_text(raw: Any, default: str) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return _canonical_decimal(Decimal(default))
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise ConfigurationError(f"the value is not a decimal number: {raw!r}.") from None
    return _canonical_decimal(value)


def configuration_projection(
    cfg: Mapping[str, Any], *, secrets_configured: Mapping[str, bool] | None = None
) -> tuple[SettingView, ...]:
    """Every setting as a `SettingView`, in a fixed order (`FR-CONF-35`).

    `cfg` is the composed configuration — `effective_config`'s output, environment already over
    file — and the values are read through the resolver's own helpers, so this projection shows
    the configuration a run would freeze, not the file's text. Pure: no environment is read
    (the caller passes `secrets_configured` when it can answer it; without one a secret reads
    as not configured), and the input is never mutated.

    Raises `ConfigurationError` for a mapping that is not a valid composed configuration — the
    same refusal shape the run path raises, since the readers are the resolver's own.
    """
    backend_profile = cfg.get("HARNESS_PROFILE")
    if not isinstance(backend_profile, str) or backend_profile not in BACKEND_PROFILES:
        raise ConfigurationError(
            f"HARNESS_PROFILE must be one of {BACKEND_PROFILES}, got "
            f"{_echo('HARNESS_PROFILE', backend_profile)}."
        )
    panel = _panel_refs(cfg)
    transcriber = _ref_of(cfg.get("transcriber"), "transcriber")
    hardware = cfg.get("HARNESS_HARDWARE_PROFILE")
    cost_ceiling, cost_currency = _resolve_cost(cfg, backend_profile)
    retention = _resolve_retention_setting(cfg, backend_profile)
    policy = _hardware_policy(cfg, backend_profile)
    concurrency = _resolve_concurrency(cfg, policy)
    prefix_token_ceiling = (
        policy.prefix_token_ceiling if policy is not None
        else _positive_int(cfg.get("hosted_prefix_token_ceiling"), "hosted_prefix_token_ceiling",
                           DEFAULT_HOSTED_PREFIX_TOKEN_CEILING)
    )
    provider = _decision_provider(cfg, backend_profile)
    # FR-CONF-36: each knob with where it came from, in the banner's own teacher words.
    orch_knobs = resolve_orch_knobs(cfg)

    def configured(name: str) -> bool:
        return bool(secrets_configured.get(name, False)) if secrets_configured else False

    views: list[SettingView] = [
        SettingView("deployment_profile", "Deployment profile", str(backend_profile),
                    "choice", False, choices=BACKEND_PROFILES),
        SettingView("machine_profile", "Machine profile",
                    str(hardware) if hardware is not None else "", "text", False),
        SettingView("grading_model", "Grader model", _panel_text(panel), "text",
                    "grading_model" in _EDITABLE),
        SettingView("page_reader_model", "Page reader model", _ref_text(transcriber), "text",
                    "page_reader_model" in _EDITABLE),
        SettingView("qa_assistant_model", "Q&A assistant model",
                    _ref_text(resolve_qa_model(cfg, backend_profile, panel)), "text",
                    "qa_assistant_model" in _EDITABLE),
        SettingView("decision_engine", "Decision engine",
                    str(decision_engine_setting(cfg, backend_profile)), "choice",
                    "decision_engine" in _EDITABLE, choices=DECISION_ENGINES),
        SettingView("decision_engine_model", "Decision engine model",
                    _decision_model_text(cfg, backend_profile), "text",
                    "decision_engine_model" in _EDITABLE),
        SettingView(
            "decision_confidence_gate", "Decision confidence gate",
            _canonical_decimal(_resolve_confidence_threshold(cfg, provider)), "number",
            "decision_confidence_gate" in _EDITABLE),
        SettingView(
            "decision_citation_gate", "Decision citation gate",
            _decimal_text(cfg.get("HARNESS_JEV_CITE_THRESHOLD"), DEFAULT_CITE_THRESHOLD),
            "number", "decision_citation_gate" in _EDITABLE),
        SettingView(
            "decision_citation_question_limit", "Citation question limit",
            str(_bounded_int(cfg.get("HARNESS_JEV_MAX_CITATION_QUESTIONS"),
                             "HARNESS_JEV_MAX_CITATION_QUESTIONS",
                             DEFAULT_MAX_CITATION_QUESTIONS, 1, 26)),
            "number", "decision_citation_question_limit" in _EDITABLE),
        SettingView(
            "decision_token_bytes_ratio", "Token bytes ratio",
            str(_bounded_int(cfg.get("HARNESS_JEV_TOKEN_BYTES_RATIO"),
                             "HARNESS_JEV_TOKEN_BYTES_RATIO",
                             DEFAULT_TOKEN_BYTES_RATIO, 1, 8)),
            "number", "decision_token_bytes_ratio" in _EDITABLE),
        SettingView("cost_ceiling", "Cost ceiling",
                    _canonical_decimal(cost_ceiling) if cost_ceiling is not None else "",
                    "number", "cost_ceiling" in _EDITABLE),
        SettingView("cost_currency", "Cost currency",
                    cost_currency if cost_currency is not None else "", "text", False),
        SettingView("data_retention", "Data retention",
                    retention if retention is not None else "", "choice", False,
                    choices=RETENTION_SETTINGS),
        SettingView("concurrency_ceiling", "Concurrency ceiling", str(concurrency),
                    "number", False),
        SettingView("prefix_token_ceiling", "Prefix token ceiling", str(prefix_token_ceiling),
                    "number", False),
        SettingView("prompt_template", "Prompt template version",
                    str(cfg.get("prompt_template_v") or ""), "text", False),
        SettingView("second_opinion_budget", BUDGET_LABEL, orch_knobs.budget_text(),
                    "text", False),
        SettingView("random_extra_grader_sample", SAMPLE_LABEL, orch_knobs.sample_text(),
                    "text", False),
        SettingView(_MODEL_PROVIDER_KEY_ID, "Model provider key", "", "secret", False,
                    configured=configured(_MODEL_PROVIDER_KEY_ID)),
    ]
    return tuple(views)
