"""The run-start screen's data (FR-CONSOLE-43): the profile banner and the cost estimate
behind the one confirmation, with no row written — and the per-run configuration the
confirmation's start composes, shared by the preview and the effect that writes."""

from __future__ import annotations

from typing import Any

from aeh.conf import (
    CONFIDENCE_THRESHOLD_FILE_KEY,
    RunConfigError,
    effective_config,
    format_profile_banner,
    profile_source,
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
    cohort_id = str(query.get("cohort_id") or "")
    package_version = str(query.get("package_version") or "")
    profile = str(query.get("profile") or "").strip()
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
    banner = format_profile_banner(run_config, profile_source(composed))
    return {"banner": banner, "estimate": None if estimate is None else str(estimate)}
