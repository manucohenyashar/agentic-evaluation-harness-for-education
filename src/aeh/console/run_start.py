"""The run-start screen's data (FR-CONSOLE-43): the profile banner and the cost estimate
behind the one confirmation, with no row written — and the per-run configuration the
confirmation's start composes, shared by the preview and the effect that writes."""

from __future__ import annotations

import json
from typing import Any

from aeh.conf import (
    CONFIDENCE_THRESHOLD_FILE_KEY,
    RunConfigError,
    effective_config,
    format_profile_banner,
    profile_source,
    rehydrate_run_config,
    resolve_run_config,
    select_profile_config,
)


#: The composed key the run-start request's `profile` parameter sets. A console process
#: cannot run under `cloud-hosted` itself (CT-CONSOLE-05), so a hosted run is NAMED per
#: request rather than inherited from the console process's environment.
PROFILE_KEY = "HARNESS_PROFILE"


def compose_run_start_config(app: Any, params: Any) -> dict[str, Any]:
    """The configuration the run `params` names starts under: the server's effective
    configuration, composed again with the request's per-run choices applied — the same
    explicit settings every other path writes, never a console-private spelling.

    - `profile` sets `HARNESS_PROFILE`, so the named profile's own section is composed in
      (FR-CONF-13) — selected from the server's configuration FILE (`app.file_config`,
      whose `profiles` table is intact; the effective `run_config` is already flattened
      and can no longer name a section) — and is then written back onto the composition
      so the REQUEST's choice wins over a disagreeing environment (`HARNESS_PROFILE` in
      the process env would otherwise silently override a cloud-hosted run an operator
      asked for by name).
    - `decision_confidence_threshold` is FR-CONF-32's config-file key, read by M-CONF's
      own resolution — the environment knob still wins over it, and an out-of-domain
      value is refused by the same check every other path refuses with.

    Anything else the caller passes through is the composition it already was; no key
    here is invented for the console alone."""
    raw_profile = str(params.get("profile") or "").strip()
    base = getattr(app, "file_config", None)
    if base is None:
        base = dict(getattr(app, "run_config", None) or {})
    if raw_profile:
        # The section is forced to the request's choice, not left to the process
        # environment's: the run's profile is named per request (FR-CONSOLE-43).
        composed = effective_config(select_profile_config(base, raw_profile))
        composed[PROFILE_KEY] = raw_profile
    else:
        composed = effective_config(base)
    threshold = params.get("decision_confidence_threshold")
    if threshold is not None and str(threshold).strip():
        composed[CONFIDENCE_THRESHOLD_FILE_KEY] = threshold
    return composed


def compose_restart_config(app: Any, run_id: str) -> dict[str, Any]:
    """The configuration a stored run restarts under: its own frozen one (FR-CONF-15).

    A start that names an existing run and no profile of its own is a RESUME, not a fresh
    composition: the run's `run_config` column (#527) is the configuration it was frozen
    with, so it is rehydrated through M-CONF's own door and flattened back to the resolver's
    keys — the decision engine and its four gates included, and the engine's absence frozen
    as `HARNESS_DECISION_ENGINE: off` where a profile's default would otherwise add one —
    and `resolve_run_config` re-freezes those same values (re-checking the cohort's consent)
    rather than composing today's environment over them.

    Raises `ValueError` naming the gap when the run is unknown or carries no frozen
    configuration. Reads only rows the run's own cohort ledger already holds — no tier
    file is created by the look."""
    cohort_key = app._cohort_for_run(run_id)
    if cohort_key is None:
        raise ValueError(f"no cohort ledger holds run {run_id!r}")
    rows = list(app._store.cohort(cohort_key).query(
        "SELECT run_config FROM run WHERE run_id = :run_id", run_id=run_id))
    if not rows:
        raise ValueError(f"no run {run_id!r} is stored")
    raw = rows[0]["run_config"]
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(
            f"run {run_id!r} carries no frozen configuration to restart under")
    try:
        frozen = json.loads(raw)
    except ValueError as error:
        raise ValueError(
            f"run {run_id!r}'s frozen configuration is not JSON: {error}") from error
    config = rehydrate_run_config(frozen)
    flat: dict[str, Any] = {
        PROFILE_KEY: config.backend_profile,
        "panel": config.panel,
        "transcriber": config.transcriber,
        "off_panel_checker": config.off_panel_checker,
        "prompt_template_v": config.prompt_template_v,
        "HARNESS_CONCURRENCY": config.concurrency_ceiling,
        "hosted_prefix_token_ceiling": config.prefix_token_ceiling,
        # Frozen with the engine's setting, whichever way it goes: `off` is explicit so a
        # cloud profile's `jev` default cannot add an engine the run never had.
        "HARNESS_DECISION_ENGINE": "off" if config.decision_engine is None else "jev",
        "decision_model": None if config.decision_engine is None else config.decision_engine.model,
    }
    if config.hardware_profile is not None:
        flat["HARNESS_HARDWARE_PROFILE"] = config.hardware_profile
    if config.cost_ceiling is not None:
        flat["HARNESS_COST_CEILING"] = str(config.cost_ceiling)
    if config.cost_currency is not None:
        flat["HARNESS_COST_CURRENCY"] = config.cost_currency
    if config.retention_setting is not None:
        flat["retention_setting"] = config.retention_setting
    if config.qa_model is not None:
        flat["HARNESS_QA_MODEL"] = config.qa_model.build_id
    if config.decision_engine is not None:
        engine = config.decision_engine
        flat[CONFIDENCE_THRESHOLD_FILE_KEY] = str(engine.confidence_threshold)
        flat["HARNESS_JEV_CITE_THRESHOLD"] = str(engine.cite_threshold)
        flat["HARNESS_JEV_MAX_CITATION_QUESTIONS"] = engine.max_citation_questions
        flat["HARNESS_JEV_TOKEN_BYTES_RATIO"] = engine.token_bytes_ratio
    return flat


def run_start_preview_read(app: Any, query: Any) -> dict[str, Any]:
    """The `run start preview` read (FR-CONSOLE-43): the profile banner the run would
    show and the cost estimate behind the confirmation, for the run the query names.
    Writes NOTHING — the cohort and package version are guarded read-only, the plan is
    priced without inserting (`Orchestrator.preview_run_start`), and the estimate is the
    orchestrator's own figure, not a console arithmetic.

    The run's profile is named per request (`profile`): the console process cannot bind a
    `cloud-hosted` socket (CT-CONSOLE-05), so the composed configuration is the server's
    with the request's profile applied. The decision provider is resolved through
    `aeh.pipeline.background`'s module attribute — the same seam the confirmation's start
    resolves it through — so a preview and the started run are priced alike.

    Raises `ValueError` naming the gap when the query is incomplete or names a cohort or
    package version the store does not hold (an unknown version's open would CREATE its
    tier file, and a preview that created one would not be a read)."""
    run_id = str(query.get("run_id") or "").strip()
    cohort_id = str(query.get("cohort_id") or "")
    package_version = str(query.get("package_version") or "")
    profile = str(query.get("profile") or "").strip()

    if run_id and not profile:
        # The restart's preview (FR-CONF-15): a start that names the run and no profile
        # restarts under the run's own frozen configuration, so that is what the preview
        # prices — never today's composition. The run's cohort and package version are
        # read from the run's own row, over the cohort files that already exist.
        cohort_id = app._cohort_for_run(run_id) or ""
        if not cohort_id:
            raise ValueError(f"no cohort ledger holds run {run_id!r}; nothing to preview")
        rows = list(app._store.cohort(cohort_id).query(
            "SELECT package_version_id FROM run WHERE run_id = :run_id", run_id=run_id))
        if not rows:
            raise ValueError(f"no run {run_id!r} is stored; nothing to preview")
        package_version = str(rows[0]["package_version_id"])
        composed = compose_restart_config(app, run_id)
        profile_source_note = "the run's own frozen configuration (FR-CONF-15)"
    else:
        if not cohort_id or not package_version or not profile:
            raise ValueError(
                "run start preview names no cohort, package version or profile "
                "(FR-CONSOLE-43: a run's profile is named per request)"
            )
        if cohort_id not in app._cohort_keys():
            raise ValueError(f"no cohort {cohort_id!r} is stored; nothing to preview")
        if app._package_of(package_version) == "":
            raise ValueError(
                f"no package version {package_version!r} is stored; nothing to preview"
            )
        composed = compose_run_start_config(app, query)
        profile_source_note = profile_source(composed)

    from aeh.orch import Orchestrator
    from aeh.pipeline import background
    from aeh.pipeline.runtime import _provider_for

    try:
        run_config = resolve_run_config(
            composed, Orchestrator(app._store).cohort_ref(cohort_id))
        provider = _provider_for(run_config)
    except RunConfigError as refusal:
        # A profile the file holds no section for, or a malformed key (including one the
        # provider construction rejects), is the request's mistake — a 400-shaped refusal
        # naming the gap, not a crash.
        raise ValueError(str(refusal)) from refusal
    decision_provider = background._decision_provider_for_run(run_config, provider, None)
    orchestrator = Orchestrator(
        app._store, provider=provider, decision_provider=decision_provider)
    estimate = orchestrator.preview_run_start(cohort_id, package_version, run_config)
    banner = format_profile_banner(run_config, profile_source_note)
    return {"banner": banner, "estimate": None if estimate is None else str(estimate)}
