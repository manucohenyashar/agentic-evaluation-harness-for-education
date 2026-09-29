"""PERF-11 (NFR-PIPE-02; TS-99 #393): M-PIPE's composition adds at most 0.25 ms per ledger unit
(5% of NFR-ORCH-01's 5 ms scheduling budget).

A composed run over F-SYNTH with a zero-latency, record-as-you-go provider (PipeWorld's
`CaptureProvider`, which composes every reply the drive asks for, as the F-DEV-PIPE and
F-JEV-SYNTH captures do). The composition hooks, `_integrity_pre_hook` and `_aggregate_hook` (the
work M-PIPE adds over a `progress()`-only drive), are timed with `perf_counter`, and their total
is divided by the run's ledger units.

Disclosed:
- **Size.** The plan names 23,000 units. `AEH_PERF11_SUBMISSIONS` sets the cohort size (default 40,
  about 3,500 units); F-SYNTH's full 350 submissions reach the plan's scale. The oracle is per unit,
  so the budget is the same at every size.
- **Baseline.** Instead of subtracting a `progress()`-only run (which scores nothing and so is not
  the same run), the hooks' own time is measured: it is exactly the time the composition adds.

**Written ahead, owned by no issue yet:** measured on this box, the hooks cost 3.9 ms per unit at
10 submissions (870 units) and 9.3 ms per unit at 40 (2,988 units): over the budget by 15-37x, and
GROWING with cohort size, so the composition's per-unit cost is not constant (the hooks re-read the
run's cells on every pass). At the plan's 23,000 units the gap would be wider still.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import aeh.pipeline as pipeline
from tests.support import pipe_world
from tests.support.e2e_world import SynthWorld

pytestmark = [pytest.mark.integration, pytest.mark.slow]

BUDGET_MS_PER_UNIT = 0.25


class _ComposedSynthWorld(SynthWorld):
    """F-SYNTH driven through `run_to_completion` with replies composed on demand."""

    decision_engine = False
    uniform_panel_ordinal = None
    decision_outcomes: dict = {}
    _run_cfg_overrides = pipe_world.PipeWorld._run_cfg_overrides
    _make_provider = pipe_world.PipeWorld._make_provider

    def __init__(self, data_dir, fixture_dir, *, monkeypatch, n_submissions):
        self._fixture_dir_for_cfg = str(fixture_dir)
        pipe_world.set_world_env(pipe_world.ESCALATION_BUDGET_ENV, pipe_world.CORPUS_ESCALATION_BUDGET,
                                 monkeypatch)
        super().__init__(data_dir, fixture_dir, n_submissions=n_submissions, quarantine_indices=(),
                         monkeypatch=monkeypatch)


@pytest.mark.writtenahead
def test_perf_11_composition_adds_at_most_a_quarter_millisecond_per_unit(tmp_path, monkeypatch):
    spent = {"s": 0.0}
    for name in ("_integrity_pre_hook", "_aggregate_hook"):
        real = getattr(pipeline, name)

        def timed(*args, _real=real, **kwargs):
            t0 = time.perf_counter()
            try:
                return _real(*args, **kwargs)
            finally:
                spent["s"] += time.perf_counter() - t0

        monkeypatch.setattr(pipeline, name, timed)
    root = tmp_path / "w"
    for sub in ("packages", "cohorts", "blobs"):
        (root / sub).mkdir(parents=True)
    (tmp_path / "fx").mkdir()
    size = int(os.environ.get("AEH_PERF11_SUBMISSIONS", "40"))
    world = _ComposedSynthWorld(root, tmp_path / "fx", monkeypatch=monkeypatch, n_submissions=size)
    try:
        world.build_run()
        world.start_run()
        result = pipe_world.drive_composed(world)
        units = int(world.handle.query("SELECT COUNT(*) FROM work_unit WHERE run_id = :r",
                                       r=world.run_id)[0][0])
    finally:
        world.store.close()
    assert result.status == "complete", result.pause_reason
    per_unit_ms = spent["s"] * 1000 / units
    assert per_unit_ms <= BUDGET_MS_PER_UNIT, (
        f"composition added {per_unit_ms:.3f} ms per unit over {units} units, above "
        f"{BUDGET_MS_PER_UNIT} ms (NFR-PIPE-02)")
