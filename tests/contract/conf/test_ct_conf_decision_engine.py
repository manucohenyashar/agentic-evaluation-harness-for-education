"""TS-113 (#466): the CT-CONF v2.0 decision-engine clauses. Jev test plan §6.11.2.

| Case | Clause | Asserted |
|---|---|---|
| TC-CONF-C17 | data | The profile/provider pairing and build pinning are held by the type: `dataclasses.replace` to a cloud engine on an edge config raises |
| TC-CONF-C18 | behaviour | Gate values frozen for the run: the resolved object and its rehydrated row keep threshold and token ratio under a changed environment; at rung 2 a seat dispatched with the rehydrated config after the change records threshold 0.8 and falls back at gate 0.70 |
| TC-CONF-C19 | config | The engine key has no default; per-provider threshold defaults; explicit values override; out-of-domain raises, never clamps |
| TC-CONF-C20 | behaviour | The engine-off `panel_build_ref` and `ProfileSummary` equal the fb12d1e goldens; every engine-on variant differs |
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import pytest

from aeh.conf import (BackendMismatchError, CohortRef, ConfigurationError, UnresolvedModelRefError, compute_panel_build_ref, rehydrate_run_config,
                      resolve_run_config)
from tests.support.conf_builders import edge_cfg, hosted_cfg

pytestmark = pytest.mark.contract

COHORT = CohortRef("c-ct-conf", "synthetic")
OR_BUILD = "openrouter/typesafe/jev-1.13@2026-09-01"
OJ_BUILD = "/models/openjev-FP8/model.safetensors@sha256:ab12"
SMALL_BUILD = "/models/openjev-small/qwen3.5-4b-nli-v5/model.safetensors@sha256:" + "cd" * 32
GOLDEN = Path(__file__).resolve().parents[2] / "regression" / "baselines" / "jev_engine_off.json"


def _edge(**kw):
    return edge_cfg(HARNESS_DECISION_ENGINE="jev", HARNESS_JEV_BUILD=OJ_BUILD, HARNESS_JEV_QUANTIZATION="fp8", **kw)


def _cloud(**kw):
    return hosted_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev", HARNESS_JEV_BUILD=OR_BUILD, **kw)


# --- TC-CONF-C17 -------------------------------------------------------------------------------

def test_tc_conf_c17_the_type_holds_the_pairing() -> None:
    edge = resolve_run_config(_edge(), COHORT)
    cloud_engine = resolve_run_config(_cloud(), COHORT).decision_engine
    with pytest.raises(BackendMismatchError):
        dataclasses.replace(edge, decision_engine=cloud_engine)
    unpinned = dataclasses.replace(edge.decision_engine,
                                   model=dataclasses.replace(edge.decision_engine.model, build_id="/models/x.gguf"))
    with pytest.raises((UnresolvedModelRefError, ConfigurationError)):
        dataclasses.replace(edge, decision_engine=unpinned)


# --- TC-CONF-C18 (safety property) -------------------------------------------------------------

def test_tc_conf_c18_gate_values_are_frozen_rung_0(monkeypatch) -> None:
    resolved = resolve_run_config(_cloud(), COHORT)
    row = resolved.to_persisted_dict()
    monkeypatch.setenv("HARNESS_JEV_CONFIDENCE_THRESHOLD", "0.60")
    monkeypatch.setenv("HARNESS_JEV_TOKEN_BYTES_RATIO", "5")
    back = rehydrate_run_config({"backend_profile": row["backend_profile"], "panel_config": row["panel_config"],
                                 "provider_config": row["provider_config"]})
    for engine in (resolved.decision_engine, back.decision_engine):
        assert (engine.confidence_threshold, engine.token_bytes_ratio) == (Decimal("0.80"), 3)


@pytest.mark.integration
def test_tc_conf_c18_after_a_resume_the_frozen_gate_still_decides(tmp_data_dir, make_fixture_provider, monkeypatch) -> None:
    """Adversarial construction (plan §6.11.2): a `gate_decision` that read the threshold from the
    environment would accept the 0.70 unit after the change to 0.60, and this goes red."""
    from aeh.judge import ScoringWorker
    from tests.integration.judge.test_ts110_decision_dispatch import (
        _Decider, _decision, _engine_config, _prescreen_rows, _record_llm, _seat_unit, _world)
    from tests.support.conf_builders import edge_panel

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        config = _engine_config(tmp_data_dir)
        row = config.to_persisted_dict()
        monkeypatch.setenv("HARNESS_JEV_CONFIDENCE_THRESHOLD", "0.60")
        monkeypatch.setenv("HARNESS_JEV_TOKEN_BYTES_RATIO", "8")
        resumed = rehydrate_run_config({"backend_profile": row["backend_profile"], "panel_config": row["panel_config"],
                                        "provider_config": row["provider_config"]})
        assert resumed.decision_engine.confidence_threshold == Decimal("0.80")
        unit = _seat_unit(units, refs)
        request = _record_llm(provider, store, unit, refs[0], world)
        spans = len(request.evidence)
        # (4·0.775 − 1)/3 = 0.70: above the changed 0.60, below the frozen 0.80.
        seventy = _Decider(lambda r: _decision([.075, .075, .775, .075], n_spans=spans))
        result = ScoringWorker(store, provider, refs[0], decision_provider=seventy,
                               run_config=resumed).dispatch(request, refs[0])
        assert result.scoring_engine == "llm" and result.prescreen_outcome == "below_gate"
        rows = _prescreen_rows(store, unit.work_id)
        assert rows[0]["threshold"] == pytest.approx(0.8) and rows[0]["gate_confidence"] == pytest.approx(0.70)
        # The token ratio is frozen too: a unit sized just over the window at ratio 3 stays
        # ineligible after the environment says 8.
        from aeh.judge import decision_eligibility
        from aeh.prov import DecisionCapabilities
        from tests.unit.judge.test_ts109_decision_logic import _request as scoring_request, _total_bytes
        caps = DecisionCapabilities(1000, 255, 64, None, True)  # 90% = 900 tokens
        base = _total_bytes(scoring_request(1, submission=""), resumed.decision_engine)
        oversize = scoring_request(1, submission="x" * (901 * 3 - base))
        assert decision_eligibility(oversize, resumed.decision_engine, caps).reason == "context"
    finally:
        store.close()


# --- TC-CONF-C19 -------------------------------------------------------------------------------

def test_tc_conf_c19_defaults_overrides_and_no_clamping() -> None:
    cfg = _cloud()
    cfg.pop("HARNESS_DECISION_ENGINE")
    with pytest.raises(ConfigurationError):
        resolve_run_config(cfg, COHORT)
    assert resolve_run_config(_cloud(), COHORT).decision_engine.confidence_threshold == Decimal("0.80")
    assert resolve_run_config(_edge(), COHORT).decision_engine.confidence_threshold == Decimal("0.80")
    small = edge_cfg(HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="openjev-small",
                     HARNESS_JEV_BUILD=SMALL_BUILD, HARNESS_JEV_QUANTIZATION="bf16",
                     HARNESS_HARDWARE_PROFILE="unified-small")
    assert resolve_run_config(small, COHORT).decision_engine.confidence_threshold == Decimal("0.85")
    assert resolve_run_config({**small, "HARNESS_JEV_CONFIDENCE_THRESHOLD": "0.9"},
                              COHORT).decision_engine.confidence_threshold == Decimal("0.9")
    assert resolve_run_config(_cloud(HARNESS_JEV_CONFIDENCE_THRESHOLD="0.95"),
                              COHORT).decision_engine.confidence_threshold == Decimal("0.95")
    with pytest.raises(ConfigurationError):
        resolve_run_config(_cloud(HARNESS_JEV_CONFIDENCE_THRESHOLD="0.4999"), COHORT)


# --- TC-CONF-C20 -------------------------------------------------------------------------------

def test_tc_conf_c20_engine_off_goldens_and_engine_on_distinctness() -> None:
    from tests.regression.jev_engine_off_capture import serialization_configs

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["serialization"]
    for name, cfg in serialization_configs().items():
        resolved = resolve_run_config(cfg, CohortRef(cohort_id="coh-dev-pipe", consent_class="synthetic"))
        assert compute_panel_build_ref(resolved.panel) == golden[name]["panel_build_ref"]
        assert resolved.profile_summary().to_canonical_json() == golden[name]["profile_summary"]
        assert "decision_engine" not in resolved.profile_summary().to_canonical_json()
    on = resolve_run_config(_cloud(), COHORT)
    refs = {compute_panel_build_ref(on.panel, decision_engine=e) for e in (
        on.decision_engine, dataclasses.replace(on.decision_engine, confidence_threshold=Decimal("0.85")),
        dataclasses.replace(on.decision_engine, token_bytes_ratio=4))}
    assert len(refs) == 3 and compute_panel_build_ref(on.panel) not in refs
