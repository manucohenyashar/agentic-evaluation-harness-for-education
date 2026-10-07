"""TS-108 (#461): M-CONF's decision engine. Jev test plan §5 (M-CONF), §6.11.

| Case | Asserted |
|---|---|
| TC-CONF-24 | `HARNESS_DECISION_ENGINE`'s domain is closed, per profile (the absent-key arm moved to TC-CONF-35/C19 with FR-CONF-29); `off` gives `None`, `jev` a decision-role engine; every section of the reference config resolves with a pinned build, and `edge-local` names `unified-large` |
| TC-CONF-25 | The profile × provider binding table (three profiles × two providers: three accepts, three cross-pair refusals; the plan says "four" but the grid has three), `fixture` only under `HARNESS_FIXTURE_DIR` |
| TC-CONF-26 | Build pinning: two accepts, everything else `UnresolvedModelRefError` |
| TC-CONF-27 | Knob bounds refuse, never clamp; per-provider threshold defaults; frozen at resolution; rehydration round-trips, and a pre-delta row rehydrates to `None`; the config-file key `decision_confidence_threshold` resolves to the same `DecisionEngine` the env knob does (FR-CONF-32 arm, written ahead of #616) |
| TC-CONF-28 | `panel_build_ref` distinguishes every engine-on variant from each other and from engine-off |
| TC-CONF-29 | Residency, as re-specified by FR-CONF-28 (plan §5.0): `unified-small` and `discrete-gpu` refuse `openjev`, naming `unified-small` / `off`; `unified-large` resolves; `off` resolves anywhere |
| TC-CONF-30 | The consent gate refuses `cloud-hosted` + `jev` for a remote-forbidden cohort and names the decision engine; `edge-local` resolves |
| TC-CONF-31 | The exact banner line, on and off |
| TC-CONF-32 | Engine-off `ProfileSummary` JSON has no `decision_engine` substring; engine-on carries build and threshold |
| TC-CONF-C02 | The `decision_engine` iff (the 13-field set equality is pinned in `test_ct_conf_surface_and_shape.py`): `off` → `None`, `jev` → non-null, and a hand-built engine on an `off` config is refused by the type itself |
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

from aeh.conf import (BackendMismatchError, CohortRef, ConfigurationError, ConsentGateError,
                      DecisionEngine, UnresolvedModelRefError, compute_panel_build_ref,
                      format_profile_banner, parse_config_document, rehydrate_run_config,
                      resolve_run_config, select_profile_config)
from tests.support.conf_builders import edge_cfg, edge_panel, hosted_cfg, seed_credentials

COHORT = CohortRef("c-jev", "synthetic")
OR_BUILD = "openrouter/typesafe/jev-1.13@2026-09-01"
OJ_BUILD = "/models/openjev-FP8/model.safetensors@sha256:ab12"
SMALL_BUILD = "/models/openjev-small/qwen3.5-4b-nli-v5/model.safetensors@sha256:" + "cd" * 32


def _cfg(profile: str, **overrides):
    if profile == "edge-local":
        base = edge_cfg(HARNESS_JEV_BUILD=OJ_BUILD, HARNESS_JEV_QUANTIZATION="fp8")
    else:
        base = hosted_cfg(profile, HARNESS_JEV_BUILD=OR_BUILD)
    base.update(overrides)
    return base


# --- TC-CONF-24 --------------------------------------------------------------------------------

# The `None` (key absent) value that stood in this parametrization pinned FR-CONF-18's "no
# default" rule, which FR-CONF-29 / CT-CONF-19 v2.2 supersede (operator-requirements delta, #615):
# absence now resolves the per-profile default. That arm moved to TC-CONF-35 and the flipped
# TC-CONF-C19 (written ahead of #616); the closed domain stays pinned here.
@pytest.mark.parametrize("profile", ["edge-local", "cloud-hosted", "dev-ci"])
@pytest.mark.parametrize("value", ["", "JEV", "on"])
def test_tc_conf_24_the_engine_key_is_closed(profile, value) -> None:
    cfg = _cfg(profile)
    cfg["HARNESS_DECISION_ENGINE"] = value
    with pytest.raises(ConfigurationError) as caught:
        resolve_run_config(cfg, COHORT)
    assert "HARNESS_DECISION_ENGINE" in str(caught.value)


@pytest.mark.parametrize("profile", ["edge-local", "cloud-hosted", "dev-ci"])
def test_tc_conf_24_off_and_jev(profile) -> None:
    assert resolve_run_config(_cfg(profile, HARNESS_DECISION_ENGINE="off"), COHORT).decision_engine is None
    engine = resolve_run_config(_cfg(profile, HARNESS_DECISION_ENGINE="jev"), COHORT).decision_engine
    assert isinstance(engine, DecisionEngine) and engine.model.role == "decision"


def test_tc_conf_24_every_reference_config_section_resolves_with_jev(monkeypatch) -> None:
    seed_credentials(monkeypatch)
    text = (Path(__file__).resolve().parents[3] / "config" / "harness.example.toml").read_text(encoding="utf-8")
    document = parse_config_document(text, "toml")
    profiles = list(document["profiles"])
    assert set(profiles) >= {"edge-local", "cloud-hosted", "dev-ci"}
    for profile in profiles:
        section = select_profile_config(document, profile)
        assert section["HARNESS_DECISION_ENGINE"] == "jev", profile
        resolved = resolve_run_config(section, COHORT)
        assert resolved.decision_engine is not None and "@" in resolved.decision_engine.model.build_id
        if profile == "edge-local":
            assert section["HARNESS_HARDWARE_PROFILE"] == "unified-large"


# --- TC-CONF-25 --------------------------------------------------------------------------------

@pytest.mark.parametrize("profile, provider, ok", [
    ("edge-local", "openjev", True),
    ("cloud-hosted", "openrouter-jev", True),
    ("dev-ci", "openrouter-jev", True),
    ("edge-local", "openrouter-jev", False),
    ("cloud-hosted", "openjev", False),
    ("dev-ci", "openjev", False),
])
def test_tc_conf_25_the_binding_table(profile, provider, ok) -> None:
    build = OJ_BUILD if provider == "openjev" else OR_BUILD
    cfg = _cfg(profile, HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER=provider,
               HARNESS_JEV_BUILD=build, HARNESS_JEV_QUANTIZATION="fp8" if provider == "openjev" else None)
    if ok:
        assert resolve_run_config(cfg, COHORT).decision_engine.model.provider == provider
    else:
        with pytest.raises(BackendMismatchError):
            resolve_run_config(cfg, COHORT)


@pytest.mark.parametrize("profile", ["edge-local", "cloud-hosted", "dev-ci"])
def test_tc_conf_25_fixture_only_under_the_test_tier(profile, tmp_path) -> None:
    fixture = dict(HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="fixture",
                   HARNESS_JEV_BUILD=OJ_BUILD if profile == "edge-local" else OR_BUILD)
    with pytest.raises(ConfigurationError):
        resolve_run_config(_cfg(profile, **fixture), COHORT)
    resolved = resolve_run_config(_cfg(profile, **fixture, HARNESS_FIXTURE_DIR=str(tmp_path)), COHORT)
    assert resolved.decision_engine.model.provider == "fixture"


# --- TC-CONF-26 --------------------------------------------------------------------------------

@pytest.mark.parametrize("profile, build, quantization, ok", [
    ("edge-local", "/models/openjev-FP8/model.safetensors@sha256:ab12", "fp8", True),
    ("edge-local", "/models/openjev-FP8@sha256:ab12", "fp8", False),
    ("edge-local", "/models/openjev-FP8/model.safetensors@sha256:ab12", None, False),
    ("edge-local", "/models/openjev-FP8/model.safetensors", "fp8", False),
    ("cloud-hosted", "openrouter/typesafe/jev-1.13@2026-09-01", None, True),
    ("cloud-hosted", "openrouter/typesafe/jev-1.13", None, False),
    ("cloud-hosted", "~typesafe/jev-latest", None, False),
    ("edge-local", "/models/openjev:latest.gguf@sha256:ab", "fp8", False),
])
def test_tc_conf_26_build_pinning(profile, build, quantization, ok) -> None:
    cfg = _cfg(profile, HARNESS_DECISION_ENGINE="jev", HARNESS_JEV_BUILD=build,
               HARNESS_JEV_QUANTIZATION=quantization)
    if ok:
        assert resolve_run_config(cfg, COHORT).decision_engine.model.build_id == build
    else:
        with pytest.raises(UnresolvedModelRefError):
            resolve_run_config(cfg, COHORT)


# --- TC-CONF-27 --------------------------------------------------------------------------------

@pytest.mark.parametrize("key, value, expected", [
    ("HARNESS_JEV_CONFIDENCE_THRESHOLD", "0.50", Decimal("0.50")),
    ("HARNESS_JEV_CONFIDENCE_THRESHOLD", "0.4999", None),
    ("HARNESS_JEV_CONFIDENCE_THRESHOLD", "0.99", Decimal("0.99")),
    ("HARNESS_JEV_CONFIDENCE_THRESHOLD", "1.00", None),
    ("HARNESS_JEV_CONFIDENCE_THRESHOLD", "abc", None),
    ("HARNESS_JEV_CITE_THRESHOLD", "0", None),
    ("HARNESS_JEV_CITE_THRESHOLD", "1", None),
    ("HARNESS_JEV_MAX_CITATION_QUESTIONS", "0", None),
    ("HARNESS_JEV_MAX_CITATION_QUESTIONS", "27", None),
    ("HARNESS_JEV_MAX_CITATION_QUESTIONS", "1", 1),
    ("HARNESS_JEV_MAX_CITATION_QUESTIONS", "26", 26),
    ("HARNESS_JEV_TOKEN_BYTES_RATIO", "0", None),
    ("HARNESS_JEV_TOKEN_BYTES_RATIO", "9", None),
    ("HARNESS_JEV_TOKEN_BYTES_RATIO", "1", 1),
    ("HARNESS_JEV_TOKEN_BYTES_RATIO", "8", 8),
])
def test_tc_conf_27_knob_bounds_refuse_never_clamp(key, value, expected) -> None:
    field = {"HARNESS_JEV_CONFIDENCE_THRESHOLD": "confidence_threshold",
             "HARNESS_JEV_CITE_THRESHOLD": "cite_threshold",
             "HARNESS_JEV_MAX_CITATION_QUESTIONS": "max_citation_questions",
             "HARNESS_JEV_TOKEN_BYTES_RATIO": "token_bytes_ratio"}[key]
    cfg = _cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev", **{key: value})
    if expected is None:
        with pytest.raises(ConfigurationError):
            resolve_run_config(cfg, COHORT)
    else:
        assert getattr(resolve_run_config(cfg, COHORT).decision_engine, field) == expected


def test_tc_conf_27_defaults_per_provider_frozen_and_rehydrated(monkeypatch, tmp_path) -> None:
    engine = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev"), COHORT).decision_engine
    assert (engine.confidence_threshold, engine.cite_threshold, engine.max_citation_questions,
            engine.token_bytes_ratio) == (Decimal("0.80"), Decimal("0.50"), 16, 3)
    small = dict(HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="openjev-small",
                 HARNESS_JEV_BUILD=SMALL_BUILD, HARNESS_JEV_QUANTIZATION="bf16",
                 HARNESS_HARDWARE_PROFILE="unified-small")
    assert resolve_run_config(_cfg("edge-local", **small), COHORT).decision_engine.confidence_threshold == Decimal("0.85")
    assert resolve_run_config(_cfg("edge-local", **small, HARNESS_JEV_CONFIDENCE_THRESHOLD="0.80"),
                              COHORT).decision_engine.confidence_threshold == Decimal("0.80")
    assert resolve_run_config(_cfg("edge-local", HARNESS_DECISION_ENGINE="jev"),
                              COHORT).decision_engine.confidence_threshold == Decimal("0.80")
    fixture = resolve_run_config(_cfg("edge-local", HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="fixture",
                                      HARNESS_FIXTURE_DIR=str(tmp_path)), COHORT)
    assert fixture.decision_engine.confidence_threshold == Decimal("0.80")
    resolved = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev"), COHORT)
    monkeypatch.setenv("HARNESS_JEV_CONFIDENCE_THRESHOLD", "0.60")
    monkeypatch.setenv("HARNESS_JEV_TOKEN_BYTES_RATIO", "5")
    assert (resolved.decision_engine.confidence_threshold, resolved.decision_engine.token_bytes_ratio) == (
        Decimal("0.80"), 3), "the resolved object is frozen; the environment is not re-read"
    row = resolved.to_persisted_dict()
    back = rehydrate_run_config({"backend_profile": row["backend_profile"], "panel_config": row["panel_config"],
                                 "provider_config": row["provider_config"]})
    assert back.decision_engine == resolved.decision_engine
    pre = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="off"), COHORT).to_persisted_dict()
    assert "decision_engine" not in pre["provider_config"], "a pre-delta row carries no key"
    assert rehydrate_run_config({"backend_profile": pre["backend_profile"], "panel_config": pre["panel_config"],
                                 "provider_config": pre["provider_config"]}).decision_engine is None


def test_tc_conf_27_the_config_file_key_resolves_to_the_engine_the_env_knob_gives() -> None:
    """FR-CONF-32's extended arm (operator-requirements plan §5.0, #615): a TOML float in the profile
    section (`decision_confidence_threshold = 0.9`, a flat key — the placement is this suite's
    reading of "under the engine settings") resolves to the very `DecisionEngine`, and so the very
    work identity, that `HARNESS_JEV_CONFIDENCE_THRESHOLD=0.9` from the environment does. The
    precedence between the two is TC-CONF-37's."""
    from aeh.conf import effective_config

    base = _cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev")
    section = parse_config_document("[profiles.cloud-hosted]\ndecision_confidence_threshold = 0.9\n", "toml")
    from_file = resolve_run_config(effective_config({**base, "profiles": section["profiles"]}, environ={}), COHORT)
    from_env = resolve_run_config(effective_config(base, environ={"HARNESS_JEV_CONFIDENCE_THRESHOLD": "0.9"}), COHORT)
    assert from_env.decision_engine.confidence_threshold == Decimal("0.9")
    assert from_file.decision_engine == from_env.decision_engine
    assert from_file.panel_build_ref == from_env.panel_build_ref
    assert from_file.to_persisted_dict() == from_env.to_persisted_dict()


# --- TC-CONF-28 --------------------------------------------------------------------------------

def test_tc_conf_28_panel_build_ref_distinguishes_every_engine_variant() -> None:
    base = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev"), COHORT).decision_engine
    panel = edge_panel(3)
    variants = [
        base,
        dataclasses.replace(base, confidence_threshold=Decimal("0.85")),
        dataclasses.replace(base, model=dataclasses.replace(base.model, build_id="openrouter/typesafe/jev-1.13@2026-10-01")),
        dataclasses.replace(base, token_bytes_ratio=4),
    ]
    refs = [compute_panel_build_ref(panel, decision_engine=v) for v in variants]
    off = compute_panel_build_ref(panel)
    assert len(set(refs)) == 4 and off not in refs


# --- TC-CONF-29 (re-specified by FR-CONF-28) -----------------------------------------------------

def test_tc_conf_29_residency_as_re_specified() -> None:
    for hardware in ("unified-small", "discrete-gpu"):
        with pytest.raises(ConfigurationError) as caught:
            resolve_run_config(_cfg("edge-local", HARNESS_DECISION_ENGINE="jev", HARNESS_HARDWARE_PROFILE=hardware), COHORT)
        assert hardware in str(caught.value) and "HARNESS_DECISION_ENGINE=off" in str(caught.value)
        assert "openjev-small" in str(caught.value), "the refusal names the admitted alternative"
    assert resolve_run_config(_cfg("edge-local", HARNESS_DECISION_ENGINE="jev",
                                   HARNESS_HARDWARE_PROFILE="unified-large"), COHORT).decision_engine is not None
    assert resolve_run_config(_cfg("edge-local", HARNESS_DECISION_ENGINE="off",
                                   HARNESS_HARDWARE_PROFILE="unified-small"), COHORT).decision_engine is None


# --- TC-CONF-30 --------------------------------------------------------------------------------

def test_tc_conf_30_the_consent_gate_names_the_decision_engine() -> None:
    remote_forbidden = CohortRef("c-real", "real")
    with pytest.raises(ConsentGateError) as caught:
        resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev"), remote_forbidden)
    assert "decision engine" in str(caught.value).lower()
    assert resolve_run_config(_cfg("edge-local", HARNESS_DECISION_ENGINE="jev"), remote_forbidden).decision_engine


# --- TC-CONF-31 / TC-CONF-32 -------------------------------------------------------------------

def test_tc_conf_31_the_banner_line() -> None:
    on = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev"), COHORT)
    off = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="off"), COHORT)
    assert f"DECISION_ENGINE: openrouter-jev:{OR_BUILD} threshold=0.80" in format_profile_banner(on, "file").splitlines()
    assert "DECISION_ENGINE: off" in format_profile_banner(off, "file").splitlines()


def test_tc_conf_32_the_profile_summary() -> None:
    off = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="off"), COHORT)
    on = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev"), COHORT)
    assert "decision_engine" not in off.profile_summary().to_canonical_json()
    text = on.profile_summary().to_canonical_json()
    assert "decision_engine" in text and OR_BUILD in text and "0.80" in text


# --- TC-CONF-C02 (the decision_engine iff) --------------------------------------------------------

def test_tc_conf_c02_decision_engine_iff_in_both_directions() -> None:
    off = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="off"), COHORT)
    on = resolve_run_config(_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev"), COHORT)
    assert off.decision_engine is None and on.decision_engine is not None
    # 14 since #616: FR-CONF-30's `qa_model` joined `decision_engine` (CT-CONF-C02's design list).
    assert len(dataclasses.fields(off)) == 14
    with pytest.raises(ConfigurationError):
        dataclasses.replace(off, decision_engine=on.decision_engine)
    with pytest.raises(ConfigurationError):
        dataclasses.replace(on, decision_engine=None)
