"""The composed F-SYNTH world: `SynthWorld` driven through `aeh.pipeline.run_to_completion`
instead of the hand drive (the #364/#365 composition; TS-98's re-base, issue #392).

The hand drive's legs (`drive_deterministic` ... `aggregate_walk` ... `finalize`) are the
stand-in this world replaces. What carries over unchanged is the WORLD: the same corpus,
package, cohort, quarantine population and three-judge edge panel; what changes is who
decides the passes — M-PIPE's composed hooks (`_integrity_pre_hook`, `_aggregate_hook`,
synthesis, grading) instead of the journeys' own scripts.

Disclosed shape (the deltas the composition forces, stated here once):

* **The provider composes replies on demand** (`PipeWorld._make_provider`'s
  `CaptureProvider`): `run_to_completion` hands units to the stage workers and the workers
  call the provider, so no reply is pre-recorded before dispatch — the boundary answers an
  extraction or a verdict the moment it is asked, from the corpus's own declarations
  (`F-DEV-PIPE`'s capture precedent).
* **The escalation baseline is recorded package evidence.** The hand walk read the
  design's Assumption distribution (`expected_distribution()`: mean 2.0, sd 0.5 over the
  four-band scale) as a caller argument. The composed escalation hook reads the run's
  package instead (`FR-PIPE-15`), so this world records that same Assumption distribution
  onto the published version through the shipped `record_validation_baseline` route —
  band histogram `emerging:1, developing:6, secure:1` (mean exactly 2.0, sd exactly 0.5)
  per open criterion, keyed to the run's own frozen `backend_profile` and
  `panel_build_ref`, read back off the run row this world builds. A world-shape
  declaration, made through the shipped writer — the same numbers the hand walk assumed.
* **The criterion breaker is off, through its env seam.** The hand walk's default
  argument (`breaker_rate="1.0"`) is this world's `HARNESS_ORCH_CRITERION_BREAKER_RATE`
  (seam 3's env-gated knob — the composed hook reads the knob at call time, and `1.0`
  means no cohort trips it). A journey that wants the breaker ON names its own rate.
* **The escalation budget is the corpus's** (`CORPUS_ESCALATION_BUDGET`, the same value
  the hand walk set): the composed dispatch defers widened pairs over it exactly as the
  hand drive's workers did.
* **`agg` configuration is the shipped default** (`CT-AGG-01`: the policy reads no
  configuration beyond the values passed in, and the composed hook passes none). The
  journeys that injected thresholds through the walk's `agg_config_kwargs` have no seam
  to inject through here — a journey re-based onto this world states its figures against
  the shipped policy or says so.
"""

from __future__ import annotations

import json
from typing import Any

from aeh.orch import CRITERION_BREAKER_MIN_N_ENV, CRITERION_BREAKER_RATE_ENV
from aeh.pkg.validation import record_validation_baseline

from tests.support import pipe_world
from tests.support.e2e_world import SynthWorld
from tests.support.env_hygiene import set_world_env

#: The design's Assumption distribution, as the package declares its bands: one judgement
#: at ordinal 1, six at ordinal 2, one at ordinal 3 — population mean exactly 2.0, sd
#: exactly 0.5, the figures the hand walk's `expected_distribution()` carried.
ASSUMPTION_HISTOGRAM = {"emerging": 1, "developing": 6, "secure": 1}

#: The breaker rate that never trips (`criterion_breaker_tripped` needs the window's
#: escalation share strictly above the rate) — the hand walk's default argument, through
#: the knob the composed hook reads.
BREAKER_OFF_RATE = "1.0"


class ComposedSynthWorld(SynthWorld):
    """F-SYNTH for the composed pipeline: the journeys' world, `run_to_completion`'s drive."""

    decision_engine = False
    uniform_panel_ordinal = None
    decision_outcomes: dict = {}
    _run_cfg_overrides = pipe_world.PipeWorld._run_cfg_overrides
    _make_provider = pipe_world.PipeWorld._make_provider

    #: The breaker rate this world's env carries. A journey wanting the trip overrides it.
    breaker_rate: str = BREAKER_OFF_RATE
    #: The breaker's window minimum, or None to leave the shipped default in place (the
    #: hand walk's own rule: it hands the knob only when the caller states one).
    breaker_min_n: str | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        monkeypatch = kwargs.get("monkeypatch")
        set_world_env(pipe_world.ESCALATION_BUDGET_ENV,
                      pipe_world.CORPUS_ESCALATION_BUDGET, monkeypatch)
        set_world_env(CRITERION_BREAKER_RATE_ENV, self.breaker_rate, monkeypatch)
        if self.breaker_min_n is not None:
            set_world_env(CRITERION_BREAKER_MIN_N_ENV, self.breaker_min_n, monkeypatch)
        super().__init__(*args, **kwargs)

    def build_run(self) -> str:
        """The run, then the recorded escalation baseline — keyed to what the run itself
        froze (`FR-CONF-07`'s row is the authority, not a rebuilt literal)."""
        run_id = super().build_run()
        row = self.handle.query(
            "SELECT backend_profile, provider_config FROM run WHERE run_id = :r",
            r=self.run_id)[0]
        panel_build_ref = json.loads(row["provider_config"])["panel_build_ref"]
        for criterion_id in self.open_ids:
            outcome = record_validation_baseline(
                self.data_dir,
                package_version_id=self.version,
                criterion_id=criterion_id,
                band_histogram=ASSUMPTION_HISTOGRAM,
                population_scope_id="",
                backend_profile=str(row["backend_profile"]),
                panel_build_ref=str(panel_build_ref),
                scoring_model="holistic",
            )
            assert outcome.recorded, (
                f"fixture bug: the recorded escalation baseline for {criterion_id} was "
                f"refused ({outcome.reason}) - the composed hook reads its escalation "
                "input from the package, and this world's Assumption distribution must "
                "be on it"
            )
        return run_id

    def drive(self, **overrides: Any) -> Any:
        """The composed drive: `run_to_completion` over this world, the corpus's model
        identities and this world's open criteria as the high-risk set."""
        return pipe_world.drive_composed(self, high_risk_criteria=self.open_ids,
                                         **overrides)