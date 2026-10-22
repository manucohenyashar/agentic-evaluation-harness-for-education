"""TC-REG-20 (#819): T5b, a Jev-accepted ENG7 cell is final with the shipped one-judge config.

Console-clarity test plan §3.12 (→ TC-AGG-27). The live teacher test's symptom: with the shipped
`docs/live-tests/config/live-test.dev-ci.toml` (a one-judge panel, the Jev engine on), every cell
Jev settled confidently still read "not final". This case pins the fix from both ends:
- the shipped file, resolved verbatim with no `HARNESS_JEV_FINAL_ON_ACCEPT` in the environment,
  is a one-judge, engine-on run whose frozen rule is `jev_final_on_accept=True`;
- the ENG7 Jev-final seed's accepted decision cell, aggregated under that resolved rule, is
  stored `final` / `auto` with the gate as its confidence and no not-final reason.

The Results-banner half of T5b is TC-UI-32 (a browser case) and is not part of this issue.

Markers. `integration` (rung 3: a real store, the shipped package build and the shipped config
file).
"""

from __future__ import annotations

import pytest

from aeh.conf import CohortRef, effective_config, resolve_run_config
from aeh.store import open_store
from tests.support.clarity_world import JEV_GATE, STUDENTS, score_rows, seed_jev_final
from tests.support.eng7_sample import DEV_CI_CONFIG

pytestmark = pytest.mark.integration


def test_tc_reg_20_a_jev_accepted_eng7_cell_is_final_with_the_shipped_one_judge_config(
        tmp_path, monkeypatch) -> None:
    from aeh.agg import stored_not_final_reason
    from aeh.pipeline import cli

    for key in ("HARNESS_JEV_FINAL_ON_ACCEPT", "HARNESS_DECISION_ENGINE", "HARNESS_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    resolved = resolve_run_config(effective_config(cli._load_config_file(str(DEV_CI_CONFIG))),
                                  CohortRef(cohort_id="eng7-reg-20", consent_class="synthetic"))
    assert len(resolved.panel) == 1, "the shipped config is a one-judge panel"
    assert resolved.decision_engine is not None, "the shipped config runs the Jev engine"
    assert resolved.jev_final_on_accept is True

    store = open_store(tmp_path / "data")
    try:
        from aeh.orch import Orchestrator

        # The rule the aggregate hook reads is the run row's: a run created with the shipped
        # config must freeze `jev_final_on_accept=True` for the hook's run handle to read.
        shipped = resolve_run_config(
            effective_config(cli._load_config_file(str(DEV_CI_CONFIG))),
            CohortRef(cohort_id="eng7-clarity-synthetic", consent_class="synthetic"))
        seed = seed_jev_final(store, jev_final_on_accept=resolved.jev_final_on_accept)
        orch = Orchestrator(store)
        run_id = orch.create_run(seed.cohort_id, seed.package_version_id, shipped,
                                 run_id="run-reg-20-shipped")
        assert orch.run_handle(run_id).jev_final_on_accept is True
        rows = score_rows(store, seed)
    finally:
        store.close()
    for name in STUDENTS:
        row = rows[(name, "C1a")]
        assert (row["state"], row["routing"], row["judge_count"]) == ("final", "auto", 1), row
        assert row["confidence"] == pytest.approx(JEV_GATE)
        assert stored_not_final_reason(row) is None
