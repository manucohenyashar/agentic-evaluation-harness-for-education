"""Rebuilding a stored run's configuration, and refusing a resume whose configuration changed."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import fields
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import BackendMismatchError, ConfigurationError
from .model_ref import ModelRef, _ref_from_dict, _ref_to_dict
from .decision_engine import DecisionEngine
from .checks import _echo
from .run_config import CohortRef, RunConfig
from .panel import compute_panel_build_ref
from .consent import _check_consent


#: The field names `CT-CONF-C02` asserts set equality against. Derived from the type rather than
#: written out, so it cannot drift from it — the contract case compares this against the design's
#: Interfaces list, which is the comparison that matters.
RUN_CONFIG_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(RunConfig))


# --- resume (FR-CONF-04, NFR-CONF-04, RISK-22) -----------------------------------------------


def rehydrate_run_config(
    run_row: Mapping[str, Any],
    cfg: Mapping[str, Any] | None = None,
    cohort: CohortRef | None = None,
) -> RunConfig:
    """Rebuild the `RunConfig` a stored run row was written from, or refuse.

    More detail: `docs/code-notes/conf.md`, section `rehydrate.py: rehydrate_run_config`.
    """
    if not isinstance(run_row, Mapping):
        raise ConfigurationError(
            f"run_row must be a Mapping, got {type(run_row).__name__}."
        )
    # #527: a row M-ORCH wrote carries the whole persisted config in `run_config` (its own
    # `panel_config`/`provider_config` columns keep the forms M-ORCH reads). Read from it when
    # present; a row that is already `to_persisted_dict()`-shaped is read as it stands.
    raw_run_config = run_row.get("run_config")
    if isinstance(raw_run_config, str) and raw_run_config.strip():
        try:
            raw_run_config = json.loads(raw_run_config)
        except ValueError:
            raise ConfigurationError("run row's run_config is not JSON.") from None
    if isinstance(raw_run_config, Mapping):
        run_row = raw_run_config
    panel_config = run_row.get("panel_config")
    provider_config = run_row.get("provider_config")
    for name, section in (("panel_config", panel_config), ("provider_config", provider_config)):
        if not isinstance(section, Mapping):
            raise ConfigurationError(
                f"run row is missing a usable {name}: got {type(section).__name__}."
            )

    backend_profile = run_row.get("backend_profile")
    raw_panel = panel_config.get("panel")
    if not isinstance(raw_panel, Sequence) or isinstance(raw_panel, (str, bytes)):
        raise ConfigurationError("persisted panel must be a sequence of model refs.")

    panel = tuple(_ref_from_dict(raw, f"panel[{i}]") for i, raw in enumerate(raw_panel))
    transcriber = _ref_from_dict(panel_config.get("transcriber"), "transcriber")
    raw_off_panel = panel_config.get("off_panel_checker")
    off_panel_checker = (
        None if raw_off_panel is None else _ref_from_dict(raw_off_panel, "off_panel_checker")
    )

    # Checked BEFORE construction, and raised as a mismatch rather than a configuration error.
    # `RunConfig.__post_init__` would otherwise reach this first and raise `ConfigurationError`,
    # but `TC-CONF-04`'s variant names `BackendMismatchError` for it -- and it is right to: a
    # stored ref that no longer matches its stored builds means the panel changed underneath a
    # run, which is RISK-22, not a malformed row.
    raw_engine = provider_config.get("decision_engine")
    decision_engine = None if raw_engine is None else DecisionEngine.from_dict(raw_engine)
    persisted_ref = panel_config.get("panel_build_ref")
    recomputed_ref = compute_panel_build_ref(panel, decision_engine)
    if persisted_ref != recomputed_ref:
        raise BackendMismatchError(
            f"the persisted panel_build_ref {persisted_ref!r} disagrees with the one recomputed "
            f"from the persisted builds ({recomputed_ref!r}). The panel on this run changed "
            f"after it started (FR-CONF-04, RISK-22)."
        )

    # The same checks the resolver applies, not a looser parse. A persisted `NaN` ceiling makes
    # every `spend > ceiling` comparison False -- unbounded spend on a resumed run, against R5
    # and FR-CONF-07 -- and a row is exactly where a hand-edit would put one.
    raw_ceiling = provider_config.get("cost_ceiling")
    if raw_ceiling is None:
        cost_ceiling = None
    else:
        try:
            cost_ceiling = Decimal(str(raw_ceiling))
        except InvalidOperation:
            raise ConfigurationError("persisted cost_ceiling is not a decimal number.") from None
        if not cost_ceiling.is_finite():
            raise ConfigurationError("persisted cost_ceiling must be finite.")
        if cost_ceiling < 0:
            raise ConfigurationError("persisted cost_ceiling must not be negative.")

    raw_currency = provider_config.get("cost_currency")
    if raw_currency is not None and (not isinstance(raw_currency, str) or not raw_currency.strip()):
        raise ConfigurationError("persisted cost_currency must be a non-empty string or absent.")

    config = RunConfig(
        backend_profile=backend_profile,  # type: ignore[arg-type]
        hardware_profile=provider_config.get("hardware_profile"),  # type: ignore[arg-type]
        panel=panel,
        transcriber=transcriber,
        off_panel_checker=off_panel_checker,
        prompt_template_v=panel_config.get("prompt_template_v"),  # type: ignore[arg-type]
        concurrency_ceiling=provider_config.get("concurrency_ceiling"),  # type: ignore[arg-type]
        prefix_token_ceiling=provider_config.get("prefix_token_ceiling"),  # type: ignore[arg-type]
        cost_ceiling=cost_ceiling,
        cost_currency=raw_currency,
        retention_setting=provider_config.get("retention_setting"),
        panel_build_ref=persisted_ref,  # type: ignore[arg-type]
        decision_engine=decision_engine,
    )

    if cfg is not None:
        _refuse_on_mismatch(config, cfg)
    if cohort is not None:
        _check_consent(cfg if cfg is not None else {}, cohort, config.backend_profile)
    return config


def _refuse_on_mismatch(persisted: RunConfig, cfg: Mapping[str, Any]) -> None:
    """Compare a rebuilt run configuration with the current one, and refuse on any difference.

    Compared: everything that decides **which grader this run is** — the backend, the ordered
    panel, the transcriber, the off-panel checker, the prompt template, and (on `edge-local`)
    the hardware profile, which sets the prefix ceiling and so decides what fits in the cached
    prefix. A changed *ceiling* is an operational tweak; a changed *build or template* is a
    different grader, and grading half a cohort with one and half with another is exactly
    RISK-22.

    **Absence is a refusal, not a pass.** An earlier version skipped each check when the key was
    missing or the wrong type, which meant `cfg = {"HARNESS_PROFILE": "cloud-hosted"}` compared
    one field and silently approved everything else — a guard that degrades to nearly vacuous on
    the Critical-risk path. This module refuses on absence everywhere else (`CT-CONF-11`,
    "absence raises"); passing `cfg` at all is a claim to be holding current configuration.
    """
    if not isinstance(cfg, Mapping):
        raise ConfigurationError(f"cfg must be a Mapping, got {type(cfg).__name__}.")

    if cfg.get("HARNESS_PROFILE") != persisted.backend_profile:
        raise BackendMismatchError(
            f"this run was started on backend_profile {persisted.backend_profile!r} and current "
            f"configuration says "
            f"{_echo('HARNESS_PROFILE', cfg.get('HARNESS_PROFILE'))}. A resumed run rebinds to "
            f"its persisted backend or refuses; it never switches (FR-CONF-04). A different "
            f"backend needs a different run."
        )

    current_panel = cfg.get("panel")
    if (
        isinstance(current_panel, (str, bytes))
        or not isinstance(current_panel, Sequence)
        or not all(isinstance(ref, ModelRef) for ref in current_panel)
    ):
        raise ConfigurationError(
            "current configuration must name a panel of ModelRefs to compare a resumed run "
            "against. Omitting it would let the comparison pass by default, which is the one "
            "outcome FR-CONF-04 must never produce."
        )
    current_ref = compute_panel_build_ref(tuple(current_panel))
    if current_ref != compute_panel_build_ref(persisted.panel):
        raise BackendMismatchError(
            f"this run was started with panel {compute_panel_build_ref(persisted.panel)!r} and current "
            f"configuration resolves to {current_ref!r}. Half a cohort graded by one panel and "
            f"half by another is what FR-CONF-04 exists to prevent (RISK-22)."
        )

    # The decision engine is part of which grader this run is (CT-CONF-14). A current config that
    # names an engine state must agree with the persisted one; its gate values are frozen on the
    # row and deliberately not re-compared (CT-CONF-18: an environment change after start does
    # not alter them). A config predating the key compares only when the run had an engine.
    wants = cfg.get("HARNESS_DECISION_ENGINE")
    had = persisted.decision_engine
    if wants is not None or had is not None:
        if (wants == "jev") != (had is not None):
            raise BackendMismatchError(
                f"this run was started with the decision engine "
                f"{'on' if had is not None else 'off'} and current configuration says "
                f"{_echo('HARNESS_DECISION_ENGINE', wants)} (FR-CONF-04, CT-CONF-14).")
        current_model = cfg.get("decision_model")
        current_build = (current_model.build_id if isinstance(current_model, ModelRef)
                         else cfg.get("HARNESS_JEV_BUILD"))
        if had is not None and current_build not in (None, had.model.build_id):
            raise BackendMismatchError(
                "this run was started with one decision build and current configuration names "
                "another (FR-CONF-04). Neither identity is echoed here (NFR-CONF-02).")

    # The transcriber and off-panel checker are compared by **full identity**, not by build_id
    # alone: the panel goes through `compute_panel_build_ref`, which mixes in provider and
    # quantization, and comparing these two more loosely would let a build_id served by a
    # different provider through on the one path nobody is watching.
    for what, mine, theirs in (
        ("transcriber", persisted.transcriber, cfg.get("transcriber")),
        ("off_panel_checker", persisted.off_panel_checker, cfg.get("off_panel_checker")),
    ):
        if mine is None and theirs is None:
            continue
        if what == "transcriber" and not isinstance(theirs, ModelRef):
            raise ConfigurationError(
                "current configuration must name a transcriber ModelRef to compare a resumed "
                "run against."
            )
        if (mine is None) != (theirs is None) or (
            mine is not None and _ref_to_dict(mine) != _ref_to_dict(theirs)
        ):
            raise BackendMismatchError(
                f"this run was started with one {what} and current configuration names another "
                f"(FR-CONF-04). Neither identity is echoed here (NFR-CONF-02); compare "
                f"run_row['panel_config'][{what!r}] with cfg[{what!r}]."
            )

    if cfg.get("prompt_template_v") != persisted.prompt_template_v:
        # Neither version echoed, for the same reason as `retention_setting` and `build_id`:
        # `prompt_template_v` is caller data, and `NFR-CONF-02` forbids a value that is not on
        # `_ECHOABLE_KEYS` reaching any message this module emits. Found by `TC-CONF-11`'s
        # per-refusal scan, which provokes each mismatch message separately.
        raise BackendMismatchError(
            "this run was started with one prompt_template_v and current configuration names "
            "another. A changed prompt template is a changed grader (FR-CONF-04, RISK-22). "
            "Neither version is echoed here (NFR-CONF-02); compare "
            "run_row['panel_config']['prompt_template_v'] with cfg['prompt_template_v']."
        )

    if cfg.get("HARNESS_HARDWARE_PROFILE") != persisted.hardware_profile and (
        persisted.hardware_profile is not None
        or cfg.get("HARNESS_HARDWARE_PROFILE") is not None
    ):
        # Only meaningful on edge-local, where it is non-null; elsewhere both sides are None.
        # It sets the prefix ceiling, so a change alters what fits in the cached prefix.
        raise BackendMismatchError(
            f"this run was started on hardware_profile {persisted.hardware_profile!r} and "
            f"current configuration says "
            f"{_echo('HARNESS_HARDWARE_PROFILE', cfg.get('HARNESS_HARDWARE_PROFILE'))} "
            f"(FR-CONF-04)."
        )
