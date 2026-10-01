"""Run-level setup for the decision engine, and the summary of what it decided."""

from __future__ import annotations

from typing import Any

from aeh.orch import STAGE_SCORE

from .results import StageTrace


def _engine_tag(run_config: Any, result: Any) -> str:
    """Which engine produced a score, added only when a decision engine is configured. With the
    engine off, output is byte-for-byte what it was before (FR-PIPE-14, NFR-SYS-14)."""
    if getattr(run_config, "decision_engine", None) is None:
        return ""
    if getattr(result, "scoring_engine", "llm") == "decision":
        return " [decision]"
    outcome = getattr(result, "prescreen_outcome", None)
    return f" [llm; prescreen={outcome}]" if outcome else " [llm]"


def _decision_provider_for_run(run_config: Any, provider: Any, decision_provider: Any) -> Any:
    """The decision provider for the run's frozen engine: the one passed in, else the fixture
    recordings already bound as `provider` for the `fixture` engine, else `decision_provider_for`,
    the only way to build one (FR-PIPE-11, CT-PROV-22). None when the engine is off; an engine-off
    run builds nothing (CT-PIPE-09)."""
    engine = getattr(run_config, "decision_engine", None)
    if engine is None:
        return None
    if decision_provider is not None:
        return decision_provider
    from aeh.prov import decision_provider_for

    if engine.model.provider == "fixture" and getattr(provider, "fixture_dir", None) is not None:
        # Still through the one construction path, pointed at the recordings already bound.
        return decision_provider_for(engine.model, fixture_dir=provider.fixture_dir)
    return decision_provider_for(engine.model)


def _decision_run_start_checks(run_config: Any, decision_provider: Any) -> None:
    """Before the first lease, confirm the cloud decision model's retention setting, or probe a
    local engine's served build (FR-PIPE-12). A failure raises out of `run_to_completion` before
    anything is dispatched."""
    engine = getattr(run_config, "decision_engine", None)
    if engine is None or decision_provider is None:
        return
    if getattr(run_config, "backend_profile", None) == "cloud-hosted":
        report = decision_provider.verify_retention((engine.model,))
        confirmed = {ref.build_id for ref in getattr(report, "confirmed", ())}
        if engine.model.build_id not in confirmed or getattr(report, "unconfirmed", ()):
            from aeh.prov import RetentionPolicyError

            raise RetentionPolicyError(
                f"zero-retention routing unconfirmed for the decision model "
                f"{engine.model.provider}:{engine.model.build_id}; nothing was dispatched "
                f"(FR-PIPE-12, FR-PROV-28).")
    verify_build = getattr(decision_provider, "verify_build", None)
    if callable(verify_build):
        # FR-CONF-28: placement `cpu` obliges the served device to be `cpu`.
        from aeh.conf import hardware_policy_for

        policy = hardware_policy_for(run_config)
        placement = None if policy is None else policy.decision_coresident.get(engine.model.provider)
        if placement == "cpu":
            verify_build(engine.model, placement=placement)
        else:
            verify_build(engine.model)


def _decision_summary(handle: Any, run_id: str) -> StageTrace:
    """The run's decision-engine outcome mix for the scoring stage (FR-PIPE-13, CT-PIPE-08)."""
    from aeh.judge import decision_engine_metrics

    m = decision_engine_metrics(handle.cohort, run_id)
    summary = {
        "decision_prescreens": m.decision_prescreens,
        "decision_accepted": m.decision_accepted,
        "decision_below_gate": m.decision_below_gate,
        "decision_ineligible": m.decision_ineligible,
        "decision_ineligible_reasons": dict(m.decision_ineligible_reasons),
        "decision_rejected": m.decision_rejected,
        "decision_malformed": m.decision_malformed,
        "decision_accepted_rate": m.decision_accepted_rate,
        "decision_fallback_rate": m.decision_fallback_rate,
        "decision_latency_p50_ms": m.decision_latency_p50_ms,
        "decision_latency_p95_ms": m.decision_latency_p95_ms,
        "decision_fallback_rate_high": m.decision_fallback_rate_high,
        "decision_requests_rejected": m.decision_requests_rejected,
    }
    return StageTrace(
        STAGE_SCORE, units=m.decision_prescreens, done=m.decision_accepted,
        detail=(f"decision engine: {m.decision_prescreens} pre-screen(s), "
                f"{m.decision_accepted} accepted, fallback rate {m.decision_fallback_rate}",),
        metrics=summary,
    )
