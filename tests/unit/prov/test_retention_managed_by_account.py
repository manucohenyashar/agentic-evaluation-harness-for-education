"""Regression cases for the owner decision of 2026-11-22 (no issue; no TC-* covered it).

"All models should not ask for zero retention as this policy is managed by my OpenRouter
account outside the system."

1. No request the harness sends to OpenRouter asks for zero retention: neither a completion
   (panel and escalation judges, the transcriber / page reader, extraction, synthesis, the
   authoring models, all through `OpenRouterProvider`) nor a Jev decision request carries `zdr`
   or `data_collection`. The Jev request keeps its upstream pin (`order`, `allow_fallbacks`),
   which is about which model answers, not about retention.
2. No OpenRouter-routed model is probed for, or refused over, zero retention: a `cloud-hosted`
   or `dev-ci` run whose panel judges, escalation judges and Jev engine have no retention
   confirmation starts, sends nothing at run start, records that retention is managed by the
   OpenRouter account (never as confirmed), and records no probe cost. The page reader's job
   is not refused either.
3. Local providers are unchanged: an `edge-local` run records none of this, and the local
   server still confirms its own models.

Supersedes FR-PROV-14/28/43/48, CT-PROV-09/30, FR-ORCH-40's retention half, FR-PIPE-12's
retention half and FR-CONSOLE-97's retention half for OpenRouter-routed models. R31 (only
synthetic data to remote providers, the consent gate) is a separate rule and is untouched.
Every case runs under the autouse network guard.
"""

from __future__ import annotations

import json

import pytest

from aeh.conf import CohortRef, ModelRef, resolve_run_config
from aeh.orch import Orchestrator
from aeh.prov import (
    HttpResponse,
    LocalServerProvider,
    OpenRouterProvider,
    PromptPayload,
    SamplingParams,
)
from aeh.store import open_store
from tests.support.conf_builders import (
    EDGE_PANEL_3,
    HOSTED_PANEL_3,
    HOSTED_TRANSCRIBER,
    edge_cfg,
    hosted_cfg,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package
from tests.support.prov_contract import CountingClock

ACCOUNT_MANAGED = "managed by the OpenRouter account"
JEV_BUILD = "openrouter/typesafe/jev-latest@2026-11-22"
_CRITERIA = ({"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},)
_SYNTHETIC = CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic")
_REF = ModelRef(role="judge", provider="openrouter",
                build_id="openrouter/qwen/qwen3-30b-a3b@2026-06-01", quantization=None)
_PAYLOAD = PromptPayload(fields=(("instruction", "Reply with the word ready"),))


class _NoNetwork:
    """A transport that must never be asked: nothing is probed at run start."""

    def __init__(self) -> None:
        self.requests: list = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        raise AssertionError(f"no request may leave at run start: {request.method} {request.url}")


class _Recording:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requests: list = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        return self.response


def _completion_ok() -> HttpResponse:
    return HttpResponse(200, {}, json.dumps({
        "model": "qwen/qwen3-30b-a3b",
        "choices": [{"finish_reason": "stop", "message": {"content": "ready"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.000001},
    }).encode("utf-8"))


def _unconfirming(transport=None) -> OpenRouterProvider:
    """An OpenRouter provider whose retention source confirms nothing."""
    return OpenRouterProvider(
        api_key="sk-or-test", base_url="https://openrouter.test/api/v1",
        transport=transport if transport is not None else _NoNetwork(),
        retention_answers=lambda _build: "retention: standard")


def _no_retention_keys(document: object) -> None:
    text = json.dumps(document)
    assert "zdr" not in text and "data_collection" not in text, text


# --- 1. no request asks for zero retention ------------------------------------------------------


def test_an_openrouter_completion_request_asks_for_no_retention_policy() -> None:
    transport = _Recording(_completion_ok())
    OpenRouterProvider(api_key="k", base_url="https://or.test/api/v1", transport=transport,
                       clock=CountingClock()).complete(_PAYLOAD, _REF, SamplingParams(temperature=0.0))
    (request,) = transport.requests
    _no_retention_keys(json.loads(request.body))


@pytest.mark.parametrize("profile", ["dev-ci", "cloud-hosted"])
def test_the_launchers_openrouter_provider_asks_for_no_retention_policy(profile, monkeypatch) -> None:
    from aeh.pipeline.runtime import _describe_provider, _provider_for

    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    provider = _provider_for(resolve_run_config(hosted_cfg(profile, panel=HOSTED_PANEL_3),
                                                _SYNTHETIC))
    inner = provider._inner
    assert isinstance(inner, OpenRouterProvider)
    transport = _Recording(_completion_ok())
    inner._transport, inner._api_key = transport, "k"
    inner.complete(_PAYLOAD, _REF, SamplingParams(temperature=0.0))
    _no_retention_keys(json.loads(transport.requests[0].body))
    assert ACCOUNT_MANAGED in _describe_provider(provider)
    assert "zero" not in _describe_provider(provider).lower()


def test_a_jev_decision_request_asks_for_no_retention_policy_and_keeps_its_upstream_pin() -> None:
    pytest.importorskip("typesafe_sdk")
    from aeh.prov import ChoiceQuestion, DecisionRequest, JevOpenRouterProvider
    from tests.support import jev_corpora

    body = {**{b["id"]: b for b in jev_corpora.wire_bodies()}["cloud-well-formed-reported"]["body"],
            "model": "typesafe/jev-1.13"}
    transport = _Recording(HttpResponse(200, {}, json.dumps(body).encode("utf-8")))
    ref = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-01", quantization=None)
    request = DecisionRequest(state="### criterion\nx\n\n### submission\ny", questions=(
        ChoiceQuestion("topic", "Which concept?", (("friction", "static friction"), ("normal", None))),))
    try:
        JevOpenRouterProvider(api_key="sk-or-test", transport=transport, session_id="R1").decide(
            request, ref)
    except Exception:  # noqa: BLE001 - only the request sent is under test here
        pass
    assert transport.requests, "the decision request was not sent"
    sent = json.loads(transport.requests[0].body)
    _no_retention_keys(sent)
    assert set(sent["provider"]) == {"order", "allow_fallbacks"}
    assert sent["provider"]["allow_fallbacks"] is False


# --- 2. no OpenRouter-routed model is probed or refused ------------------------------------------


def _created(store, provider, cfg, *, decision_provider=None, escalation=()):  # noqa: ANN001
    seed_cohort(store, ("S001",))
    version = seed_package(store, _CRITERIA)
    run_id = Orchestrator(store, provider=provider, decision_provider=decision_provider).create_run(
        ORCH_COHORT_ID, version, cfg, escalation_refs=escalation)
    return json.loads(store.cohort(ORCH_COHORT_ID).query(
        "SELECT provider_config FROM run WHERE run_id = :r", r=run_id)[0]["provider_config"])


@pytest.mark.parametrize("profile", ["dev-ci", "cloud-hosted"])
def test_a_remote_run_with_unconfirmed_retention_starts_and_records_the_account_note(
        tmp_data_dir, network_guard, profile) -> None:
    transport = _NoNetwork()
    escalation = (ModelRef(role="judge", provider="openrouter",
                           build_id="openrouter/escalation/judge-x@2026-06-01", quantization=None),)
    store = open_store(tmp_data_dir)
    try:
        recorded = _created(store, _unconfirming(transport),
                            resolve_run_config(hosted_cfg(profile, panel=HOSTED_PANEL_3), _SYNTHETIC),
                            escalation=escalation)
    finally:
        store.close()
    assert recorded["retention"] == ACCOUNT_MANAGED
    assert recorded["retention_account_managed"] == sorted(
        [ref.build_id for ref in HOSTED_PANEL_3] + [escalation[0].build_id])
    # Never recorded as confirmed, and nothing was probed, so no probe cost.
    assert "retention_verified" not in recorded
    assert "retention_probe_cost" not in recorded
    assert transport.requests == []
    network_guard.assert_no_network()


def test_a_cloud_hosted_run_with_a_jev_engine_records_it_as_account_managed(
        tmp_data_dir, network_guard) -> None:
    pytest.importorskip("typesafe_sdk")
    from aeh.pipeline.decision_engine import _decision_run_start_checks
    from aeh.prov import JevOpenRouterProvider

    cfg = resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3,
                                        HARNESS_DECISION_ENGINE="jev", HARNESS_JEV_BUILD=JEV_BUILD),
                             _SYNTHETIC)
    jev = JevOpenRouterProvider(api_key="sk-or-test", transport=_NoNetwork(),
                                retention_answers=lambda _b: "retention: standard")
    store = open_store(tmp_data_dir)
    try:
        recorded = _created(store, _unconfirming(), cfg, decision_provider=jev)
    finally:
        store.close()
    assert recorded["retention"] == ACCOUNT_MANAGED
    assert JEV_BUILD in recorded["retention_account_managed"]
    assert "retention_exempt" not in recorded and "retention_verified" not in recorded
    _decision_run_start_checks(cfg, jev)  # no raise
    network_guard.assert_no_network()


def test_a_cloud_hosted_run_needs_no_retention_seam_when_every_model_is_account_managed(
        tmp_data_dir) -> None:
    """A seam with no `verify_retention` used to refuse every `cloud-hosted` start."""

    class _PricingOnly:
        pass

    store = open_store(tmp_data_dir)
    try:
        recorded = _created(store, _PricingOnly(), resolve_run_config(
            hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3), _SYNTHETIC))
    finally:
        store.close()
    assert recorded["retention"] == ACCOUNT_MANAGED


def test_the_page_reader_is_not_probed_or_refused_on_a_remote_profile() -> None:
    from aeh.pipeline.background import ReadingSession

    transport = _NoNetwork()
    session = ReadingSession.__new__(ReadingSession)
    session.run_config = resolve_run_config(hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3),
                                            _SYNTHETIC)
    assert session.run_config.transcriber.build_id == HOSTED_TRANSCRIBER.build_id
    session._reader = _unconfirming(transport)
    assert session._verify_retention() is None, "nothing probed, so no probe cost"
    assert transport.requests == []
    # And the reader stays usable: no refusal was armed.
    assert not session._reader._retention_gate_failed


def test_the_openrouter_provider_reports_its_models_as_account_managed_without_asking() -> None:
    transport = _NoNetwork()
    report = _unconfirming(transport).verify_retention((_REF, HOSTED_TRANSCRIBER))
    assert report.confirmed == () and report.unconfirmed == ()
    assert report.exempt == (_REF, HOSTED_TRANSCRIBER)
    assert transport.requests == []


# --- 3. local providers are unchanged -----------------------------------------------------------


def test_an_edge_local_run_records_no_retention_note(tmp_data_dir, network_guard) -> None:
    store = open_store(tmp_data_dir)
    try:
        recorded = _created(store, LocalServerProvider(transport=_NoNetwork()),
                            resolve_run_config(edge_cfg(), _SYNTHETIC))
    finally:
        store.close()
    for key in ("retention", "retention_account_managed", "retention_verified",
                "retention_probe_cost", "retention_exempt"):
        assert key not in recorded, key
    assert LocalServerProvider(transport=_NoNetwork()).verify_retention(EDGE_PANEL_3).confirmed == EDGE_PANEL_3
    network_guard.assert_no_network()


def test_the_helper_names_openrouter_routed_models_only() -> None:
    from aeh.prov import retention_managed_by_account

    assert retention_managed_by_account(_REF)
    assert retention_managed_by_account(ModelRef(role="decision", provider="openrouter-jev",
                                                 build_id=JEV_BUILD, quantization=None))
    for local in (*EDGE_PANEL_3, ModelRef(role="decision", provider="openjev",
                                          build_id="/models/openjev/model.safetensors@sha256:" + "ab" * 32,
                                          quantization="fp8")):
        assert not retention_managed_by_account(local), local.provider
