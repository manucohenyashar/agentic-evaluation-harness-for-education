"""TC-CONF-C22 (#615): the CT-CONF-22 clause suite. Operator-requirements test plan §5.2, §6.11.

CT-CONF-22: `HARNESS_QA_MODEL` exists on the cloud profiles with the panel-first default; on
`edge-local` the Q&A model is `RunConfig.panel[0]` and no knob overrides it. The resolved value is
frozen for the run and rehydrated identically on resume. **Breaks if** the Q&A model is read at
call time or `edge-local` grows an override knob silently.

Written ahead of #616. The environment reaches resolution only through `effective_config`'s
snapshot, so every arm composes through it with an explicit `environ` — a `setenv` alone never
reaches `resolve_run_config` and would make the freeze arm pass against any implementation.
The persisted `qa_model` is read as a `ModelRef` mapping (provider, build, quantization); see
`tests/unit/conf/test_ts141_engine_default_and_qa_model.py` for the interface reading.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from aeh.conf import (CohortRef, RunConfigError, effective_config, format_profile_banner, rehydrate_run_config,
                      resolve_run_config)
from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

COHORT = CohortRef("c-ct-conf-22", "synthetic")
QA_A = "vendor/qa-model-a@2026-09-01"
QA_B = "vendor/qa-model-b@2026-10-01"


def _hosted(profile: str) -> dict[str, Any]:
    return hosted_cfg(profile, panel=HOSTED_PANEL_3, HARNESS_DECISION_ENGINE="off")


def _edge() -> dict[str, Any]:
    return edge_cfg(panel=EDGE_PANEL_3, HARNESS_DECISION_ENGINE="off")


def _resolve(cfg: dict[str, Any], environ: Mapping[str, str]) -> Any:
    return resolve_run_config(effective_config(cfg, environ=environ), COHORT)


def _qa(config: Any) -> tuple[Any, Any, Any]:
    provider_config = config.to_persisted_dict()["provider_config"]
    assert "qa_model" in provider_config, "CT-CONF-22: the resolved Q&A model is on provider_config"
    qa = provider_config["qa_model"]
    assert isinstance(qa, Mapping), qa
    return qa["provider"], qa["build_id"], qa.get("quantization")


def _rehydrate(config: Any) -> Any:
    row = config.to_persisted_dict()
    return rehydrate_run_config({"backend_profile": row["backend_profile"], "panel_config": row["panel_config"],
                                 "provider_config": row["provider_config"]})


def _qa_line(config: Any) -> list[str]:
    return [line for line in format_profile_banner(config, "file").splitlines() if line.startswith("QA_ASSISTANT: ")]


@pytest.mark.parametrize("profile", ["cloud-hosted", "dev-ci"])
def test_tc_conf_c22_the_cloud_matrix(profile) -> None:
    first = HOSTED_PANEL_3[0]
    assert _qa(_resolve(_hosted(profile), {})) == (first.provider, first.build_id, first.quantization)
    assert _qa(_resolve(_hosted(profile), {"HARNESS_QA_MODEL": QA_A}))[:2] == ("openrouter", QA_A)
    for floating in ("vendor/model:free", "vendor/model@latest"):
        with pytest.raises(RunConfigError) as caught:
            _resolve(_hosted(profile), {"HARNESS_QA_MODEL": floating})
        assert "HARNESS_QA_MODEL" in str(caught.value)


def test_tc_conf_c22_edge_local_has_no_override_knob() -> None:
    first = EDGE_PANEL_3[0]
    for environ in ({}, {"HARNESS_QA_MODEL": QA_A}):
        resolved = _resolve(_edge(), environ)
        assert _qa(resolved) == (first.provider, first.build_id, first.quantization), environ
        assert _qa_line(resolved) == [f"QA_ASSISTANT: {first.provider}:{first.build_id}"]


def test_tc_conf_c22_the_resolved_value_is_frozen_and_rehydrated(monkeypatch) -> None:
    started = _resolve(_hosted("cloud-hosted"), {"HARNESS_QA_MODEL": QA_A})
    assert _qa(started)[:2] == ("openrouter", QA_A)
    # Not vacuous: a fresh resolution under the changed environment does see the change.
    assert _qa(_resolve(_hosted("cloud-hosted"), {"HARNESS_QA_MODEL": QA_B}))[:2] == ("openrouter", QA_B)
    # Mid-run, the process environment says B; the started run and its rehydration still say A.
    monkeypatch.setenv("HARNESS_QA_MODEL", QA_B)
    resumed = _rehydrate(started)
    assert _qa(started)[:2] == _qa(resumed)[:2] == ("openrouter", QA_A)
    assert resumed.to_persisted_dict() == started.to_persisted_dict()
    assert _qa_line(resumed) == _qa_line(started) == [f"QA_ASSISTANT: openrouter:{QA_A}"]
