"""The pre-start plan an orchestrator can price without writing a row (FR-CONSOLE-43)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from .run_records import panel_config_json


#: The run id a preview plans with. The random-arm draw is seeded from the run id
#: (`run_random_arm_seed`) and the real one is minted at `create_run`, so a pre-start
#: plan must name a placeholder; see `preview_run_start`'s docstring for what that means
#: for the figure's exactness.
PREVIEW_RUN_ID = "run-preview"


class RunPreviewMixin:
    """Prices the run `create_run` would start, before the run row exists.

    The console's run-start screen (FR-CONSOLE-43) shows the cost estimate behind its one
    confirmation, and the estimate the orchestrator owns is `_run_cost_estimate` — which
    reads the run's ledger rows, which do not exist before the run does. Rather than a
    second pricing path, this mixin plans the run's units through the same enumeration
    code `enumerate_units` plans with (`EnumerationMixin._planned_units`) and prices the
    plan through the same arithmetic `_run_cost_estimate` sums with
    (`CostsMixin._plan_cost_estimate`); only the insert between the two is left out. The
    confirmation then starts a run whose ledger the same enumeration fills — the estimate
    and the spend are one method apart, not two implementations.
    """

    def preview_run_start(self, cohort_id: str, package_version: str, cfg: Any) -> Decimal | None:
        """The estimate for the run `create_run(cohort_id, package_version, cfg)` would
        start: its planned units, priced by this orchestrator's provider and decision
        provider (FR-ORCH-15's sum). None when the plan is empty or no provider seam is
        bound — the started run's estimate would be absent in both cases.

        Writes nothing: the plan is computed from the cohort's stored rows and the
        package's declared criteria, and the only tier files this touches are opens of
        files that already exist — a caller that must not create anything checks the
        cohort and package version before calling (an unknown version's `_catalog` open
        would create its file).

        The random-arm sample (`FR-ORCH-11`) is planned at the configured rate, but the
        draw is seeded from the run id, which is minted at `create_run` — so the
        pre-start figure prices the draw of the placeholder id (`PREVIEW_RUN_ID`). The
        figure is exact for a run with the sample off and an estimate for a sampled one;
        the banner carries it as an estimate either way."""
        package_id = self._package_id_for(package_version)
        panel_config = panel_config_json(
            getattr(cfg, "panel", ()),
            decision_engine=getattr(cfg, "decision_engine", None),
        )
        row = {
            "run_id": PREVIEW_RUN_ID,
            "cohort_id": cohort_id,
            "package_id": package_id,
            "package_version_id": package_version,
            "panel_config": panel_config,
            "prompt_template_v": getattr(cfg, "prompt_template_v", None),
        }
        plan = self._planned_units(row)
        return self._plan_cost_estimate(
            [params for _work_id, params in plan.computed],
            panel_record=json.loads(panel_config),
        )
