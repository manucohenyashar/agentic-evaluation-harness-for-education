"""Runs frozen under a changed grader configuration, for Validity T14 (issue #911): TC-STATS-45's
trigger arms and TC-CALIB-25.

A real console run's row stores its graders in the shapes M-ORCH writes: `panel_config` is the
canonical `{"arms": [...]}` work-identity string, `provider_config` the flat provider record, the
template in its own column, and the whole frozen `RunConfig` in `run_config`. A case that wrote
some other shape into the row would test the trigger check against a row no run ever has. So the
rows here are made by M-ORCH itself: the console's effective configuration is resolved exactly as
`start run` resolves it, one FR-STATS-19 dimension (or the decision engine) is changed on the
resolved `RunConfig`, and `Orchestrator.create_run` writes a `pending` run under it. The run is
never driven: the trigger check reads only its frozen row.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

#: The trigger dimensions and the change that moves each, on a resolved `RunConfig`.
Change = Callable[[Any], Any]


def _rebuilt(cfg: Any, **changes: Any) -> Any:
    """`cfg` with `changes`, its `panel_build_ref` recomputed from the panel and engine the way
    the resolver computes it (CT-CONF-07 refuses a stale one)."""
    from aeh.conf.panel import compute_panel_build_ref

    panel = changes.get("panel", cfg.panel)
    engine = changes.get("decision_engine", cfg.decision_engine)
    return dataclasses.replace(cfg, **changes,
                               panel_build_ref=compute_panel_build_ref(panel, engine))


def _with_build(ref: Any, suffix: str) -> Any:
    return dataclasses.replace(ref, build_id=f"{ref.build_id}{suffix}")


def change_panel_member(cfg: Any) -> Any:
    """Swap the last panel judge for another build."""
    panel = tuple(cfg.panel[:-1]) + (_with_build(cfg.panel[-1], "-swapped"),)
    return _rebuilt(cfg, panel=panel)


def change_model_build(cfg: Any) -> Any:
    """A new build of the transcriber (a grading build that is no panel member)."""
    return dataclasses.replace(cfg, transcriber=_with_build(cfg.transcriber, "-next"))


def change_quantization(cfg: Any) -> Any:
    """The transcriber's quantization, its build unchanged."""
    return dataclasses.replace(
        cfg, transcriber=dataclasses.replace(cfg.transcriber, quantization="q4-tc"))


def change_prompt_template(cfg: Any) -> Any:
    return dataclasses.replace(cfg, prompt_template_v=f"{cfg.prompt_template_v}-next")


def swap_in_decision_engine(cfg: Any) -> Any:
    from aeh.conf import DecisionEngine, ModelRef

    engine = DecisionEngine(
        model=ModelRef(role="decision", provider="openrouter-jev",
                       build_id="openrouter/typesafe/jev-tc@2026-11-20", quantization=None),
        confidence_threshold=Decimal("0.80"), cite_threshold=Decimal("0.50"),
        max_citation_questions=16, token_bytes_ratio=3)
    return _rebuilt(cfg, decision_engine=engine)


def console_run_config(app: Any, cohort_id: str) -> Any:
    """The console's effective configuration resolved as its `start run` resolves it."""
    from aeh.conf import CohortRef, resolve_run_config

    return resolve_run_config(app.run_config, CohortRef(cohort_id, "synthetic"))


def frozen_run(data_dir: Path | str, cohort_id: str, package_version: str, cfg: Any) -> str:
    """A `pending` run of the class, created by M-ORCH under `cfg`; returns its id."""
    from aeh.orch import Orchestrator
    from aeh.store import open_store

    store = open_store(data_dir)
    try:
        return Orchestrator(store).create_run(cohort_id, package_version, cfg)
    finally:
        store.close()


__all__ = [
    "change_model_build",
    "change_panel_member",
    "change_prompt_template",
    "change_quantization",
    "console_run_config",
    "frozen_run",
    "swap_in_decision_engine",
]
