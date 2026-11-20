"""`TC-AGG-33` (issue #896, FR-AGG-21, CT-AGG-14, CT-AGG-01, RSV-05) — the aggregation constants
are frozen per run, across a pause and a resume.

Statistical-validity test plan §3.5 (story T3):

1. Start a fixture run with `HARNESS_AGG_HOLISTIC_MULTIPLIER=0.85`.
2. Pause after about half the cells and set the variable to `0.95`.
3. Resume.

Expected: every holistic cell's confidence uses 0.85, and the run row's frozen `run_config` records
all four `agg_*` values. (The unit arm — the environment changed during one `aggregate` call — is
`tests/unit/agg/test_tc_agg_33_aggregate_reads_only_its_config.py`.)

**The run.** F-DEV-PIPE replayed from its committed recordings through `run_to_completion`
(`pipe_world.replay_world`): C1 and C2 holistic (six cells), C3 multiple choice. The
configuration reaches the run the way every entry point composes it: `effective_config` lifts the
environment's `HARNESS_AGG_*` over the file (the world's `edge_cfg`) before `resolve_run_config`.

**The oracle.** A reference run of the same corpus, uninterrupted and at the default 0.95, gives
each holistic cell's α × 0.95; the frozen run must store exactly α × 0.85 for the same cell
(`confidence_base`, before caps). C1's panels are unanimous (α = 1.0), so its cells read exactly
0.85 and queue — at 0.95 they auto-accept, which is the visible failure.

**The pause.** The provider refuses every completion after the 38th (`ProviderUnavailableError`,
the RES-20 pattern): by then two of the six holistic cells are aggregated, and the rest — with the
widened 3 → 5 panels — are aggregated after the resume. The split is asserted, not assumed.

**What makes the resume discriminate.** The resumed drive is handed a run config **re-resolved
from the changed environment** (0.95), as TC-CONF-44 does: a hook that aggregated with the
bound config, or with the environment, instead of the run row's frozen values, would write 0.95
and route C1 `auto`.

**Isolation: rung 3** — the composed pipeline over a real store, every model answer a committed
recording keyed on its request. **Written ahead of implementation: no** — #865 (PR #928).

Markers. `integration`.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

import aeh.pipeline as pipeline
from aeh.conf import AGG_KEYS, CohortRef, effective_config, resolve_run_config
from aeh.orch import LEASE_SECONDS_ENV, Orchestrator
from aeh.pkg import PackageCatalog
from aeh.prov import ProviderUnavailableError
from aeh.store import open_store
from tests.support import pipe_world
from tests.support.conf_builders import edge_cfg

pytestmark = pytest.mark.integration

HOLISTIC_ENV = "HARNESS_AGG_HOLISTIC_MULTIPLIER"
#: Completions served before the outage: extraction (24) and part of the scoring stage.
AFTER_N_CALLS = 38
#: The four frozen values the run row must record (holistic multiplier from the environment).
FROZEN_RECORD = {"agg_auto_threshold_atomic": 0.80, "agg_auto_threshold_holistic": 0.90,
                 "agg_uncited_multiplier": 0.80, "agg_holistic_multiplier": 0.85}


class _OutageAfter:
    """Delegates the first `after` completions, then refuses until `ended` is set."""

    def __init__(self, inner: Any, after: int) -> None:
        self._inner = inner
        self._after = after
        self.served = 0
        self.refusals = 0
        self.ended = False

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        if not self.ended and self.served >= self._after:
            self.refusals += 1
            raise ProviderUnavailableError("TC-AGG-33's pause: the provider is down")
        self.served += 1
        return self._inner.complete(prompt, model_ref, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _agg_from_environment() -> dict[str, Any]:
    """The `HARNESS_AGG_*` keys as an entry point composes them (environment over file)."""
    return {key: value for key, value in effective_config({}).items() if key in AGG_KEYS}


def _run_row(store: Any, run_id: str) -> dict[str, Any]:
    return dict(store.cohort(pipe_world.PIPE_COHORT_ID).query(
        "SELECT run_config, provider_config, package_id, package_version_id FROM run "
        "WHERE run_id = :r", r=run_id)[0])


def _scores(store: Any, run_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    rows = store.cohort(pipe_world.PIPE_COHORT_ID).query(
        "SELECT submission_id, criterion_id, judge_count, confidence, confidence_base, routing "
        "FROM criterion_score WHERE run_id = :r AND COALESCE(judge_count, 0) > 0", r=run_id)
    return {(str(r["submission_id"]), str(r["criterion_id"])): dict(r) for r in rows}


def _holistic_ids(store: Any, row: dict[str, Any]) -> set[str]:
    catalog = PackageCatalog(store.package(row["package_id"]), package_id=row["package_id"])
    return {str(c["criterion_id"]) for c in catalog.criteria(row["package_version_id"])
            if c["scoring_model"] == "holistic"}


def _reference_run(root: Any, monkeypatch: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """The same corpus, uninterrupted, at the default constants (no `HARNESS_AGG_*` set)."""
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world._run_cfg_overrides = _agg_from_environment
    world.build_run()
    world.start_run()
    try:
        assert world.resolved.agg_knobs.holistic_multiplier == 0.95
        result = pipe_world.drive_composed(world)
        assert result.status == "complete", (result.status, result.pause_reason)
        return _scores(world.store, world.run_id)
    finally:
        world.store.close()


def test_tc_agg_33_holistic_cells_keep_the_frozen_multiplier_across_pause_and_resume(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(LEASE_SECONDS_ENV, "1")
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    for key in AGG_KEYS:
        monkeypatch.delenv(key, raising=False)
    reference = _reference_run(tmp_path / "reference", monkeypatch)
    monkeypatch.setenv(HOLISTIC_ENV, "0.85")

    root = tmp_path / "w"
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world._run_cfg_overrides = _agg_from_environment  # the entry points' composition
    world.build_run()
    world.start_run()
    run_id = world.run_id
    assert world.resolved.agg_knobs.holistic_multiplier == 0.85, world.resolved.agg_knobs
    frozen = _run_row(world.store, run_id)
    recorded = json.loads(frozen["run_config"])["provider_config"]
    assert {key: recorded.get(key) for key in FROZEN_RECORD} == FROZEN_RECORD, recorded
    holistic = _holistic_ids(world.store, frozen)
    assert holistic == {"C1", "C2"}, f"fixture check — F-DEV-PIPE's holistic criteria: {holistic}"

    outage = _OutageAfter(world.provider, AFTER_N_CALLS)
    world.provider = outage
    first = pipe_world.drive_composed(world)
    assert first.status == "paused", (first.status, first.pause_reason)
    assert outage.refusals >= 1
    paused = _scores(world.store, run_id)
    world.store.close()

    # The pause split the holistic cells: some aggregated before it, the rest after.
    holistic_before = {cell: row["judge_count"] for cell, row in paused.items()
                       if cell[1] in holistic}
    assert 0 < len(holistic_before) < 6, f"not a mid-run pause: {paused}"
    for cell in holistic_before:
        if cell[1] == "C1":
            assert paused[cell]["confidence"] == pytest.approx(0.85), paused[cell]

    # The operator changes the environment while the run sits paused, and the resumed drive is
    # handed a config re-resolved from it.
    monkeypatch.setenv(HOLISTIC_ENV, "0.95")
    changed = resolve_run_config(
        edge_cfg(panel=world.panel_refs, **_agg_from_environment()),
        CohortRef(cohort_id=world.cohort_id, consent_class="synthetic"))
    assert changed.agg_knobs.holistic_multiplier == 0.95, "precondition: the new env says 0.95"
    time.sleep(1.2)  # every lease held at the pause expires

    store = open_store(root)
    try:
        pipeline.recover(store)
        if Orchestrator(store).run_handle(run_id).status == "paused":
            Orchestrator(store).resume(run_id)
        outage.ended = True
        resumed = pipeline.run_to_completion(store, run_id, provider=outage,
                                             run_config=changed, **pipe_world.corpus_refs())
        assert resumed.status == "complete", (resumed.status, resumed.pause_reason)
        final = _scores(store, run_id)
        after = _run_row(store, run_id)
    finally:
        store.close()

    holistic_after = {cell: row for cell, row in final.items() if cell[1] in holistic}
    assert len(holistic_after) == 6, final
    aggregated_after_pause = [cell for cell, row in holistic_after.items()
                              if holistic_before.get(cell) != row["judge_count"]]
    assert aggregated_after_pause, "no holistic cell was aggregated after the resume"
    assert set(reference) == set(final), (sorted(reference), sorted(final))
    for cell, row in holistic_after.items():
        ref = reference[cell]
        assert row["judge_count"] == ref["judge_count"], (cell, row, ref)
        # The same panel's α, times the frozen 0.85 rather than the default 0.95.
        assert row["confidence_base"] == pytest.approx(ref["confidence_base"] / 0.95 * 0.85), (
            cell, row, ref)
        if cell[1] == "C1":
            # Unanimous: α = 1.0, so the confidence is the multiplier itself.
            assert row["confidence"] == pytest.approx(0.85), (cell, row)
            assert (ref["confidence"], ref["routing"]) == (pytest.approx(0.95), "auto"), ref
            assert row["routing"] == "queued", (
                f"{cell}: 0.85 is under the 0.90 bar — `auto` means 0.95 was used: {row}")
    assert after["run_config"] == frozen["run_config"], "the run row's frozen config moved"
    assert after["provider_config"] == frozen["provider_config"]
