"""TS-141 (#615): M-CONF's per-profile engine default, the threshold's two configuration surfaces,
and the Q&A model. Operator-requirements test plan §5.2 (design delta §3.2, ADR-37).

| Case | Asserted | State |
|---|---|---|
| TC-CONF-35 | Knob unset: `cloud-hosted`/`dev-ci` → `jev` on `openrouter-jev`, `edge-local` → `off` (`decision_engine=None`) even with a local build configured; the choice is on `provider_config`, rehydrates identically, and the banner names it | written ahead (#616) |
| TC-CONF-36 | Explicit values win on every profile: `off` on `cloud-hosted` (cfg and environment); `jev` on `edge-local` via the explicit-config path; `jev` on `edge-local` without `HARNESS_JEV_BUILD` names the knob; `maybe` is refused naming the domain | green today (the rules are unchanged) |
| TC-CONF-37 | Config-file key `decision_confidence_threshold` beats the default, `HARNESS_JEV_CONFIDENCE_THRESHOLD` beats the file; out-of-domain file values refused (never clamped) naming knob, value and `[0.50, 1.00)`; banner `DECISION_GATE: jev > <t>`; `openjev-small` still 0.85 | written ahead (#616) |
| TC-CONF-38 | Q&A model: cloud profiles from `HARNESS_QA_MODEL` (default `panel[0]`), floating tags refused naming the knob; `edge-local` always `panel[0]` whatever the knob says; `provider_config.qa_model` rehydrates identically; banner `QA_ASSISTANT: <provider>:<build>` | written ahead (#616) |

**Interface choices the design leaves open, made here and named in the PR:**

- The config-file key `decision_confidence_threshold` sits as a **flat key in the profile's
  section** (`[profiles.cloud-hosted]`), parsed by `parse_config_document` and selected by
  `effective_config`. FR-CONF-32 says "under the engine settings"; no engine table exists in the
  file today, and new structural inputs take a plain `cfg` key (`sources.HARNESS_KEYS`' note).
- `HARNESS_QA_MODEL` is an OpenRouter build string (`vendor/model@pin`); the persisted
  `provider_config.qa_model` is a `ModelRef` mapping (the shape every other ref on the row takes),
  compared on provider, build and quantization — the role it carries is the implementation's.
- Every environment arm goes through `effective_config(cfg, environ=...)`: `resolve_run_config`
  never reads `os.environ`, so a `setenv`-then-resolve case would pass against any code. The
  environment reaching resolution only through the snapshot is the property under test.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest

from aeh.conf import (CohortRef, ConfigurationError, RunConfigError, effective_config,
                      format_profile_banner, parse_config_document, rehydrate_run_config,
                      resolve_run_config)
from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg

COHORT = CohortRef("c-ts141", "synthetic")
OR_BUILD = "openrouter/typesafe/jev-1.13@2026-09-01"
OJ_BUILD = "/models/openjev-FP8/model.safetensors@sha256:ab12"
SMALL_BUILD = "/models/openjev-small/qwen3.5-4b-nli-v5/model.safetensors@sha256:" + "cd" * 32
#: A pinned OpenRouter ref that is in no panel, so "came from the knob" and "came from panel[0]"
#: cannot be confused.
QA_REF = "vendor/qa-model@2026-09-01"

writtenahead = pytest.mark.writtenahead


# --- builders ----------------------------------------------------------------------------------

def _unset(cfg: dict[str, Any]) -> dict[str, Any]:
    cfg.pop("HARNESS_DECISION_ENGINE", None)
    return cfg


def _hosted(profile: str, **kw: Any) -> dict[str, Any]:
    return hosted_cfg(profile, panel=HOSTED_PANEL_3, HARNESS_JEV_BUILD=OR_BUILD, **kw)


def _edge(**kw: Any) -> dict[str, Any]:
    """`edge-local` with a local Jev build configured, so an `off` default is the knob's doing and
    never a missing build's."""
    return edge_cfg(panel=EDGE_PANEL_3, HARNESS_JEV_BUILD=OJ_BUILD, HARNESS_JEV_QUANTIZATION="fp8", **kw)


def _small(**kw: Any) -> dict[str, Any]:
    return edge_cfg(panel=EDGE_PANEL_3, HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="openjev-small",
                    HARNESS_JEV_BUILD=SMALL_BUILD, HARNESS_JEV_QUANTIZATION="bf16",
                    HARNESS_HARDWARE_PROFILE="unified-small", **kw)


def _round_trip(resolved: Any) -> tuple[dict[str, Any], Any]:
    row = resolved.to_persisted_dict()
    back = rehydrate_run_config({"backend_profile": row["backend_profile"], "panel_config": row["panel_config"],
                                 "provider_config": row["provider_config"]})
    return row, back


def _banner(resolved: Any) -> list[str]:
    return format_profile_banner(resolved, "file").splitlines()


def _with_file_section(cfg: dict[str, Any], profile: str, toml_section: str) -> dict[str, Any]:
    """`cfg` as a multi-profile config file whose `[profiles.<profile>]` section is real TOML."""
    document = parse_config_document(f"[profiles.{profile}]\n{toml_section}\n", "toml")
    return {**cfg, "profiles": document["profiles"]}


def _qa(row: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    provider_config = row["provider_config"]
    assert "qa_model" in provider_config, (
        "FR-CONF-30: the resolved Q&A model is recorded on provider_config under `qa_model`")
    qa = provider_config["qa_model"]
    assert isinstance(qa, Mapping), f"provider_config.qa_model should be a ModelRef mapping, got {qa!r}"
    return qa["provider"], qa["build_id"], qa.get("quantization")


def _ref(ref: Any) -> tuple[Any, Any, Any]:
    return ref.provider, ref.build_id, ref.quantization


# --- TC-CONF-35 --------------------------------------------------------------------------------

@writtenahead
@pytest.mark.parametrize("profile", ["cloud-hosted", "dev-ci"])
def test_tc_conf_35_unset_on_a_cloud_profile_resolves_jev_on_openrouter_jev(profile) -> None:
    resolved = resolve_run_config(_unset(_hosted(profile)), COHORT)
    engine = resolved.decision_engine
    assert engine is not None, f"FR-CONF-29: HARNESS_DECISION_ENGINE unset on {profile} defaults to jev"
    assert (engine.model.provider, engine.model.build_id, engine.confidence_threshold) == (
        "openrouter-jev", OR_BUILD, Decimal("0.80"))
    row, back = _round_trip(resolved)
    assert row["provider_config"]["decision_engine"]["model"]["provider"] == "openrouter-jev"
    assert back.decision_engine == engine and back.to_persisted_dict() == row
    assert f"DECISION_ENGINE: openrouter-jev:{OR_BUILD} threshold=0.80" in _banner(resolved)
    # The default is the resolver's, not the environment's: an empty snapshot gives the same.
    assert resolve_run_config(effective_config(_unset(_hosted(profile)), environ={}),
                              COHORT).decision_engine == engine


@writtenahead
def test_tc_conf_35_unset_on_edge_local_resolves_off_even_with_a_build_configured() -> None:
    resolved = resolve_run_config(_unset(_edge()), COHORT)
    assert resolved.decision_engine is None, "FR-CONF-29: edge-local defaults to off"
    row, back = _round_trip(resolved)
    assert "decision_engine" not in row["provider_config"], "off is recorded as the absent key (NFR-SYS-14)"
    assert back.decision_engine is None and back.to_persisted_dict() == row
    assert "DECISION_ENGINE: off" in _banner(resolved)


# --- TC-CONF-36 --------------------------------------------------------------------------------

def test_tc_conf_36_a_explicit_off_wins_on_cloud_hosted() -> None:
    assert resolve_run_config(_hosted("cloud-hosted", HARNESS_DECISION_ENGINE="off"), COHORT).decision_engine is None
    # And from the environment, over a file that says jev: the environment wins (FR-CONF-14).
    composed = effective_config(_hosted("cloud-hosted", HARNESS_DECISION_ENGINE="jev"),
                                environ={"HARNESS_DECISION_ENGINE": "off"})
    assert resolve_run_config(composed, COHORT).decision_engine is None


def test_tc_conf_36_b_jev_on_edge_local_resolves_through_the_explicit_path() -> None:
    engine = resolve_run_config(_edge(HARNESS_DECISION_ENGINE="jev"), COHORT).decision_engine
    assert engine is not None
    assert (engine.model.provider, engine.model.build_id, engine.model.quantization) == ("openjev", OJ_BUILD, "fp8")


def test_tc_conf_36_c_jev_on_edge_local_without_a_build_names_the_knob() -> None:
    cfg = _edge(HARNESS_DECISION_ENGINE="jev")
    cfg.pop("HARNESS_JEV_BUILD")
    with pytest.raises(ConfigurationError) as caught:
        resolve_run_config(cfg, COHORT)
    assert type(caught.value) is ConfigurationError
    assert "HARNESS_JEV_BUILD" in str(caught.value)


@pytest.mark.parametrize("profile", ["cloud-hosted", "dev-ci", "edge-local"])
def test_tc_conf_36_d_an_out_of_domain_engine_is_refused_naming_the_domain(profile) -> None:
    cfg = _edge(HARNESS_DECISION_ENGINE="maybe") if profile == "edge-local" else _hosted(
        profile, HARNESS_DECISION_ENGINE="maybe")
    with pytest.raises(ConfigurationError) as caught:
        resolve_run_config(cfg, COHORT)
    message = str(caught.value)
    assert "HARNESS_DECISION_ENGINE" in message and "'jev'" in message and "'off'" in message


# --- TC-CONF-37 --------------------------------------------------------------------------------

@writtenahead
def test_tc_conf_37_env_over_file_over_default() -> None:
    base = _hosted("cloud-hosted", HARNESS_DECISION_ENGINE="jev")
    default = resolve_run_config(effective_config(base, environ={}), COHORT)
    assert default.decision_engine.confidence_threshold == Decimal("0.80")
    assert "DECISION_GATE: jev > 0.80" in _banner(default)

    file_cfg = _with_file_section(base, "cloud-hosted", "decision_confidence_threshold = 0.9")
    from_file = resolve_run_config(effective_config(file_cfg, environ={}), COHORT)
    assert from_file.decision_engine.confidence_threshold == Decimal("0.9"), "the file beats the default"
    assert "DECISION_GATE: jev > 0.9" in _banner(from_file)

    from_env = resolve_run_config(effective_config(file_cfg, environ={"HARNESS_JEV_CONFIDENCE_THRESHOLD": "0.7"}),
                                  COHORT)
    assert from_env.decision_engine.confidence_threshold == Decimal("0.7"), "the environment beats the file"
    assert "DECISION_GATE: jev > 0.7" in _banner(from_env)
    assert "DECISION_GATE: jev > 0.9" not in _banner(from_env)

    # Frozen, recorded and rehydrated as the file gave it.
    row, back = _round_trip(from_file)
    assert row["provider_config"]["decision_engine"]["confidence_threshold"] == "0.9"
    assert back.decision_engine == from_file.decision_engine


@writtenahead
@pytest.mark.parametrize("value", ["0.4", "0.4999", "1.0", "1.5"])
def test_tc_conf_37_an_out_of_domain_file_value_is_refused_never_clamped(value) -> None:
    file_cfg = _with_file_section(_hosted("cloud-hosted", HARNESS_DECISION_ENGINE="jev"), "cloud-hosted",
                                  f"decision_confidence_threshold = {value}")
    with pytest.raises(ConfigurationError) as caught:
        resolve_run_config(effective_config(file_cfg, environ={}), COHORT)
    message = str(caught.value)
    assert "decision_confidence_threshold" in message or "HARNESS_JEV_CONFIDENCE_THRESHOLD" in message, message
    assert value in message and "[0.50, 1.00)" in message, message


@writtenahead
def test_tc_conf_37_openjev_small_keeps_its_085_default_and_the_file_still_overrides_it() -> None:
    unset = resolve_run_config(effective_config(_small(), environ={}), COHORT)
    assert unset.decision_engine.confidence_threshold == Decimal("0.85")
    assert "DECISION_GATE: jev > 0.85" in _banner(unset)
    from_file = resolve_run_config(effective_config(
        _with_file_section(_small(), "edge-local", "decision_confidence_threshold = 0.9"), environ={}), COHORT)
    assert from_file.decision_engine.confidence_threshold == Decimal("0.9")


# --- TC-CONF-38 --------------------------------------------------------------------------------

@writtenahead
@pytest.mark.parametrize("profile", ["cloud-hosted", "dev-ci"])
def test_tc_conf_38_a_cloud_unset_resolves_panel_0_and_the_knob_overrides(profile) -> None:
    unset = resolve_run_config(effective_config(_hosted(profile, HARNESS_DECISION_ENGINE="off"), environ={}), COHORT)
    assert _qa(unset.to_persisted_dict()) == _ref(HOSTED_PANEL_3[0]), "the default is panel[0], not any other judge"
    assert f"QA_ASSISTANT: openrouter:{HOSTED_PANEL_3[0].build_id}" in _banner(unset)

    knob = resolve_run_config(effective_config(_hosted(profile, HARNESS_DECISION_ENGINE="off"),
                                               environ={"HARNESS_QA_MODEL": QA_REF}), COHORT)
    assert _qa(knob.to_persisted_dict())[:2] == ("openrouter", QA_REF)
    assert f"QA_ASSISTANT: openrouter:{QA_REF}" in _banner(knob)


@writtenahead
@pytest.mark.parametrize("floating", ["vendor/model:free", "vendor/model:latest", "vendor/model@latest", "vendor/model"])
def test_tc_conf_38_b_a_floating_qa_model_is_refused_naming_the_knob(floating) -> None:
    composed = effective_config(_hosted("cloud-hosted", HARNESS_DECISION_ENGINE="off"),
                                environ={"HARNESS_QA_MODEL": floating})
    with pytest.raises(RunConfigError) as caught:
        resolve_run_config(composed, COHORT)
    assert "HARNESS_QA_MODEL" in str(caught.value)


@writtenahead
def test_tc_conf_38_c_edge_local_resolves_panel_0_whatever_the_knob_says() -> None:
    composed = effective_config(_edge(HARNESS_DECISION_ENGINE="off"), environ={"HARNESS_QA_MODEL": QA_REF})
    resolved = resolve_run_config(composed, COHORT)
    assert _qa(resolved.to_persisted_dict()) == _ref(EDGE_PANEL_3[0]), "edge-local has no QA knob (CT-CONF-22)"
    assert f"QA_ASSISTANT: ollama:{EDGE_PANEL_3[0].build_id}" in _banner(resolved)
    assert QA_REF not in format_profile_banner(resolved, "file")


@writtenahead
def test_tc_conf_38_d_qa_model_rehydrates_identically_on_both_profiles() -> None:
    for cfg, environ in ((_hosted("cloud-hosted", HARNESS_DECISION_ENGINE="off"), {"HARNESS_QA_MODEL": QA_REF}),
                         (_edge(HARNESS_DECISION_ENGINE="off"), {})):
        resolved = resolve_run_config(effective_config(cfg, environ=environ), COHORT)
        row, back = _round_trip(resolved)
        assert _qa(back.to_persisted_dict()) == _qa(row)
        assert back.to_persisted_dict() == row
        assert [line for line in _banner(back) if line.startswith("QA_ASSISTANT: ")] == [
            line for line in _banner(resolved) if line.startswith("QA_ASSISTANT: ")]
