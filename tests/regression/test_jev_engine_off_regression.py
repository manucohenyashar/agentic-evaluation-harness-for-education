"""TS-104 (#457): the engine-off regression anchor, TC-REG-08 and TC-REG-09.

NFR-SYS-14: with `HARNESS_DECISION_ENGINE=off` the harness behaves exactly as it did before
the Jev delta. `baselines/jev_engine_off.json` was captured from `fb12d1e` by
`jev_engine_off_capture.py` running in a `git worktree` there (Jev test plan §4.3; three
captures were byte-identical). Here the same capture runs at HEAD and is compared with it.

| Case | Asserted |
|---|---|
| TC-REG-08 | F-DEV-PIPE through `run_to_completion`, engine off. Every §4.3 artifact equals the golden: work ids; run row; profile summary; every fixture key the run hits, `decide` included (none at fb12d1e); no `decision_prescreen` row; the `evidence`, `verdict`, `criterion_score` and `submission_grade` rows; and the `RunResult` trace. The only permitted differences are NFR-SYS-14's two schema-level exceptions, `verdict.scoring_engine` and `verdict.engine_build`, which are projected out |
| TC-REG-09 | For a fixed 3-judge `cloud-hosted` config and a fixed `edge-local` config, each is byte-equal to the capture: `compute_panel_build_ref`, `ProfileSummary.to_canonical_json()`, `panel_config_json`, `to_persisted_dict()`, and the `panel_config` / `provider_config` the run row gets from `create_run`. The cloud row carries `retention_verified` |

TC-REG-09 goes red the moment any change adds `"decision_engine": null` to an engine-off
serialization, or reorders a key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.regression.jev_engine_off_capture import (
    ENGINE_OFF, _serialization, serialization_configs, snapshot)

GOLDEN = Path(__file__).resolve().parent / "baselines" / "jev_engine_off.json"

#: NFR-SYS-14's two permitted schema-level differences: verdict columns that exist only at HEAD
#: (`'llm'` and the judge build on every engine-off row).
_NEW_VERDICT_COLUMNS = ("scoring_engine", "engine_build")


def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _normalized(data: dict) -> dict:
    """The snapshot as JSON carries it, so tuples and lists compare alike."""
    return json.loads(json.dumps(data, sort_keys=True, default=str))


@pytest.fixture(scope="module")
def head_snapshot(tmp_path_factory) -> dict:
    return _normalized(snapshot(tmp_path_factory.mktemp("jev-engine-off")))


def test_tc_reg_08_engine_off_run_equals_the_fb12d1e_baseline(head_snapshot) -> None:
    golden = _golden()
    now = json.loads(json.dumps(head_snapshot))
    for row in now["tables"]["verdict"]:
        assert row.get("scoring_engine") == "llm", (
            f"an engine-off verdict carries scoring_engine={row.get('scoring_engine')!r}")
        for column in _NEW_VERDICT_COLUMNS:
            row.pop(column, None)
    now["tables"]["verdict"].sort(key=lambda r: json.dumps(r, sort_keys=True))
    for section in ("status", "work_ids", "run_row", "profile_summary", "fixture_keys", "trace",
                    "decision_prescreen_rows"):
        assert now[section] == golden[section], (
            f"TC-REG-08: engine-off {section} differs from the fb12d1e baseline (NFR-SYS-14)")
    for table, rows in golden["tables"].items():
        assert now["tables"][table] == rows, (
            f"TC-REG-08: engine-off {table} rows differ from the fb12d1e baseline (NFR-SYS-14)")


@pytest.mark.parametrize("config_name", ["cloud-hosted", "edge-local"])
def test_tc_reg_09_engine_off_serializations_are_byte_equal_to_fb12d1e(config_name) -> None:
    from aeh.conf import CohortRef

    golden = _golden()["serialization"][config_name]
    config = serialization_configs()[config_name]
    assert config["HARNESS_DECISION_ENGINE"] == ENGINE_OFF["HARNESS_DECISION_ENGINE"]
    now = _normalized(_serialization(config, CohortRef(cohort_id="coh-dev-pipe", consent_class="synthetic")))
    for key in ("panel_build_ref", "profile_summary", "panel_config_json", "persisted"):
        assert now[key] == golden[key], (
            f"TC-REG-09: {config_name} {key} is not byte-equal to its fb12d1e capture; an "
            f"engine-off serialization must not gain a decision_engine key or reorder one")


def test_tc_reg_09_engine_off_run_rows_are_byte_equal_to_fb12d1e(head_snapshot) -> None:
    """The run row `create_run` writes for each fixed config, captured in the same drive."""
    golden = _golden()["serialization"]
    for name in ("cloud-hosted", "edge-local"):
        assert head_snapshot["serialization"][name]["run_row"] == golden[name]["run_row"], (
            f"TC-REG-09: the {name} run row (panel_config / provider_config) is not byte-equal "
            f"to its fb12d1e capture")
    assert "retention_verified" in golden["cloud-hosted"]["run_row"]["provider_config"]
