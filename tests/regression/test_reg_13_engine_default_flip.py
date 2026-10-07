"""TC-REG-13 (#615): FR-CONF-29's default flip, guarded both ways. Operator-requirements test plan §6.9.

| Arm | Asserted | State |
|---|---|---|
| (a) | The three-profile matrix with the knob unset — `jev`/`openrouter-jev` on `cloud-hosted` and `dev-ci`, `off` on `edge-local` — and, on the engine-off golden's own cloud config, removing the explicit `off` now changes the subject (engine on, a different `panel_build_ref`): the explicit pin is load-bearing | green (#616) |
| (b) | With `HARNESS_DECISION_ENGINE=off` explicit on the cloud profile, the engine-off differential subjects (CT-ORCH-30's serialization, CT-CONF-C20's work identity) hold byte-identically against the fb12d1e goldens; every engine-off differential fixture names the knob explicitly | green |
| (c) | The chunked full non-live tier's failure set equals `main`'s known-red baseline ∪ this delta's `writtenahead` set | **not automated here** — an execution-plan acceptance step (test plan §4 rule 6) run on #616's PR |

(b) compares the persisted row **exactly**, as the plan specifies. If #616 records `qa_model` on an
engine-off cloud row (FR-CONF-30 says it is recorded on every run), this arm and TC-ORCH-C30 /
TC-CONF-C20 go red together and the golden must be re-blessed deliberately, as #516 did — that
is a decision for #616, not one this suite pre-empts by projecting the key away.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeh.conf import CohortRef, compute_panel_build_ref, resolve_run_config
from tests.regression.jev_engine_off_capture import ENGINE_OFF, _serialization, serialization_configs
from tests.support.conf_builders import edge_cfg, hosted_cfg

GOLDEN = Path(__file__).resolve().parent / "baselines" / "jev_engine_off.json"
COHORT = CohortRef(cohort_id="coh-dev-pipe", consent_class="synthetic")
OR_BUILD = "openrouter/typesafe/jev-1.13@2026-09-01"
OJ_BUILD = "/models/openjev-FP8/model.safetensors@sha256:ab12"


def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["serialization"]


def test_tc_reg_13_a_the_three_profile_matrix_with_the_knob_unset() -> None:
    matrix = {
        "cloud-hosted": hosted_cfg("cloud-hosted", HARNESS_JEV_BUILD=OR_BUILD),
        "dev-ci": hosted_cfg("dev-ci", HARNESS_JEV_BUILD=OR_BUILD),
        "edge-local": edge_cfg(HARNESS_JEV_BUILD=OJ_BUILD, HARNESS_JEV_QUANTIZATION="fp8"),
    }
    got = {}
    for profile, cfg in matrix.items():
        cfg.pop("HARNESS_DECISION_ENGINE")
        engine = resolve_run_config(cfg, COHORT).decision_engine
        got[profile] = None if engine is None else engine.model.provider
    assert got == {"cloud-hosted": "openrouter-jev", "dev-ci": "openrouter-jev", "edge-local": None}


def test_tc_reg_13_a_dropping_the_explicit_off_changes_the_golden_subject() -> None:
    cfg = dict(serialization_configs()["cloud-hosted"], HARNESS_JEV_BUILD=OR_BUILD)
    cfg.pop("HARNESS_DECISION_ENGINE")
    resolved = resolve_run_config(cfg, COHORT)
    assert resolved.decision_engine is not None, "unset on cloud-hosted is now jev"
    assert resolved.panel_build_ref != _golden()["cloud-hosted"]["panel_build_ref"]


def test_tc_reg_13_b_every_engine_off_differential_fixture_names_the_knob() -> None:
    assert ENGINE_OFF == {"HARNESS_DECISION_ENGINE": "off"}
    for name, cfg in serialization_configs().items():
        assert cfg.get("HARNESS_DECISION_ENGINE") == "off", name
    # The builders every engine-off consumer starts from (PipeWorld / E2EWorld build on edge_cfg).
    for cfg in (hosted_cfg("cloud-hosted"), hosted_cfg("dev-ci"), edge_cfg()):
        assert cfg.get("HARNESS_DECISION_ENGINE") == "off", cfg["HARNESS_PROFILE"]


@pytest.mark.parametrize("name", ["cloud-hosted", "edge-local"])
def test_tc_reg_13_b_explicit_off_holds_the_engine_off_subjects_byte_identically(name) -> None:
    golden = _golden()[name]
    cfg = serialization_configs()[name]
    resolved = resolve_run_config(cfg, COHORT)
    assert resolved.decision_engine is None
    now = _serialization(cfg, COHORT)
    assert now["panel_build_ref"] == golden["panel_build_ref"] == compute_panel_build_ref(resolved.panel)
    assert now["profile_summary"] == golden["profile_summary"]
    assert now["panel_config_json"] == golden["panel_config_json"]
    assert now["persisted"] == golden["persisted"]
