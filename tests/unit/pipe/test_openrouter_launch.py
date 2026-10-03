"""Regression cases for launching a run on OpenRouter (TC-PIPE-24..26, TC-PROV-64).

Live-test blockers B1 and B6 (`docs/live-tests/02-live-readiness-and-blockers.md`): no shipped
command could grade through OpenRouter.

- TC-PIPE-24 (B1): `dev-ci` could only replay recordings and demanded `HARNESS_FIXTURE_DIR`.
  It now grades through OpenRouter, and replays only when `HARNESS_FIXTURE_DIR` is set.
- TC-PIPE-25: a run with a cost ceiling (every `dev-ci` and `cloud-hosted` run) priced each
  unit by calling `estimate_cost(unit)` on the real provider, which takes a `CallPlan`; the
  first claim raised `AttributeError`. The launcher's provider now prices a unit as one call.
- TC-PIPE-26 (B1): `aeh run` built the orchestrator with no provider, so a `cloud-hosted`
  run's retention gate refused every run ("given no provider able to verify ...").
- TC-PROV-64 (B6): the retention gate asked `GET <base>/retention/<model>`, which OpenRouter
  does not serve. The launcher's provider now sends `zdr: true` and `data_collection: "deny"`
  on every request, so OpenRouter routes student work only to a host that keeps none or
  refuses it, and the gate is answered by that enforcement.

Every case runs under the autouse network guard: nothing here may reach a network.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import Orchestrator, STAGE_DETERMINISTIC
from aeh.pipeline.runtime import _describe_provider, _provider_for
from aeh.prov import (
    HttpResponse,
    LocalServerProvider,
    OpenRouterProvider,
    PromptPayload,
    ProviderUnavailableError,
    RecordedFixtureProvider,
    RetryPolicy,
    SamplingParams,
)
from aeh.prov.live import ZERO_RETENTION_ROUTING
from aeh.store import open_store
from tests.support.conf_builders import HOSTED_PANEL_3, edge_cfg, hosted_cfg
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package
from tests.support.prov_contract import CountingClock

_CRITERIA = (
    {"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "M01", "kind": "mcq", "scoring_model": "deterministic"},
)
_SYNTHETIC = CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic")


def _resolved(profile: str):
    if profile == "edge-local":
        return resolve_run_config(edge_cfg(), _SYNTHETIC)
    return resolve_run_config(hosted_cfg(profile, panel=HOSTED_PANEL_3), _SYNTHETIC)


class _NoNetwork:
    """A transport that must never be asked: the retention gate answers without a request."""

    def __init__(self) -> None:
        self.requests: list = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        raise AssertionError(f"unexpected {request.method} {request.url}")


# --- TC-PIPE-24 -------------------------------------------------------------------------------


def test_tc_pipe_24_dev_ci_grades_through_openrouter_enforcing_zero_retention(monkeypatch):
    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    provider = _provider_for(_resolved("dev-ci"))
    inner = provider._inner
    assert isinstance(inner, OpenRouterProvider), type(inner)
    assert inner._routing() == ZERO_RETENTION_ROUTING
    assert _describe_provider(provider).startswith("OpenRouter at ")
    assert "zero data retention enforced" in _describe_provider(provider)


def test_tc_pipe_24_dev_ci_replays_only_when_the_fixture_dir_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(tmp_path))
    provider = _provider_for(_resolved("dev-ci"))
    assert isinstance(provider._inner, RecordedFixtureProvider)
    assert "(no network)" in _describe_provider(provider)


@pytest.mark.parametrize("profile, kind", [("cloud-hosted", OpenRouterProvider),
                                           ("edge-local", LocalServerProvider)])
def test_tc_pipe_24_the_other_profiles_keep_their_providers(profile, kind, monkeypatch):
    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    provider = _provider_for(_resolved(profile))
    assert isinstance(provider._inner, kind)
    if kind is OpenRouterProvider:
        assert provider._inner._routing() == ZERO_RETENTION_ROUTING


# --- TC-PIPE-25 -------------------------------------------------------------------------------


def _hosted_run(store, profile: str, provider):
    seed_cohort(store, ("S001", "S002"))
    version = seed_package(store, _CRITERIA)
    orchestrator = Orchestrator(store, provider=provider)
    run_id = orchestrator.create_run(ORCH_COHORT_ID, version, _resolved(profile))
    orchestrator.enumerate_units(run_id)
    orchestrator.start(run_id)
    return orchestrator, run_id


def test_tc_pipe_25_a_ceilinged_run_prices_each_unit_on_the_real_provider(
        tmp_data_dir, monkeypatch):
    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    provider = _provider_for(_resolved("dev-ci"))
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id = _hosted_run(store, "dev-ci", provider)
        leased = {}
        for stage in ("deterministic", "extract", "score"):
            while batch := orchestrator.lease("w-cost", stage, 4):
                for unit in batch:
                    leased.setdefault(stage, 0)
                    leased[stage] += 1
                    orchestrator.complete(unit.work_id)
        assert leased.get("extract") and leased.get("score"), leased
        row = dict(store.cohort(ORCH_COHORT_ID).query(
            "SELECT cost_estimate, cost_spend FROM run WHERE run_id = :r", r=run_id)[0])
    finally:
        store.close()
    # One model call per unit at 4000 in / 1500 out, at the provider's declared rates; a
    # deterministic unit makes no call and is not billed.
    per_unit = Decimal(4000) * Decimal("0.000001") + Decimal(1500) * Decimal("0.000002")
    model_units = leased["extract"] + leased["score"]
    assert Decimal(row["cost_spend"]) == per_unit * model_units, (row, leased)
    assert Decimal(row["cost_estimate"]) == per_unit * model_units, (row, leased)
    assert provider.estimate_cost(_FakeUnit(STAGE_DETERMINISTIC)) is None


def test_tc_pipe_25_the_unit_token_budget_is_a_knob(monkeypatch):
    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    monkeypatch.setenv("HARNESS_PIPE_UNIT_TOKENS_IN", "1000")
    monkeypatch.setenv("HARNESS_PIPE_UNIT_TOKENS_OUT", "0")
    provider = _provider_for(_resolved("dev-ci"))
    assert provider.estimate_cost(_FakeUnit("extract")) == _cost(Decimal("0.001"))


class _FakeUnit:
    def __init__(self, stage: str) -> None:
        self.stage = stage


def _cost(value: Decimal):
    """`estimate_cost` answers a `CostEstimate`; compare its `cost`."""
    class _Expected:
        def __eq__(self, other: object) -> bool:
            return getattr(other, "cost", None) == value

        def __repr__(self) -> str:
            return f"CostEstimate(cost={value})"
    return _Expected()


# --- TC-PIPE-26 -------------------------------------------------------------------------------


def test_tc_pipe_26_a_cloud_hosted_run_passes_the_retention_gate_with_the_launchers_provider(
        tmp_data_dir, monkeypatch, network_guard):
    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("S001",))
        version = seed_package(store, _CRITERIA)
        provider = _provider_for(_resolved("cloud-hosted"))
        run_id = Orchestrator(store, provider=provider).create_run(
            ORCH_COHORT_ID, version, _resolved("cloud-hosted"))
        row = dict(store.cohort(ORCH_COHORT_ID).query(
            "SELECT provider_config FROM run WHERE run_id = :r", r=run_id)[0])
    finally:
        store.close()
    recorded = json.loads(row["provider_config"])
    assert recorded["retention_verified"] == sorted(ref.build_id for ref in HOSTED_PANEL_3)
    network_guard.assert_no_network()


def test_tc_pipe_26_aeh_run_binds_the_provider_before_the_run_exists(
        tmp_data_dir, tmp_path, monkeypatch):
    """`aeh run` under `cloud-hosted`: the run is created (the gate passed), then driven. The
    drive is stubbed: this case is about what happens before the first model call."""
    from aeh.pipeline import cli

    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("S001",))
        version = seed_package(store, _CRITERIA)
    finally:
        store.close()
    config = tmp_path / "cloud.toml"
    config.write_text(_CLOUD_TOML, encoding="utf-8")
    driven = {}

    def _drive(store, run_id, *, provider, run_config, **_):  # noqa: ANN001
        driven.update(run_id=run_id, provider=provider)
        from aeh.pipeline.results import RunResult
        return RunResult(run_id=run_id, status="complete", stages=(), pause_reason=None,
                         grades_computed=0, grades_final=0)

    monkeypatch.setattr(cli, "run_to_completion", _drive)
    code = cli.main(["run", "--data-dir", str(tmp_data_dir), "--cohort", ORCH_COHORT_ID,
                     "--package-version", version, "--config", str(config)])
    assert code == 0
    assert isinstance(driven["provider"]._inner, OpenRouterProvider)


def test_tc_pipe_26_a_decision_model_is_answered_by_its_own_provider(tmp_data_dir, tmp_path,
                                                                   monkeypatch):
    """With the Jev engine on, the run-start gate must ask the decision provider about the
    decision model. Before the decision provider was bound, the gate fell back to the
    completion provider, whose enforcement answer "confirmed" a model it never dispatches to:
    the run was created and started, then failed, left `running`, with a retention record
    naming the Jev build. Now the refusal comes at `create_run` and nothing is created."""
    pytest.importorskip("typesafe_sdk")
    from aeh.pipeline import cli

    for key in ("HARNESS_FIXTURE_DIR", "HARNESS_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-dummy")
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("S001",))
        version = seed_package(store, _CRITERIA)
    finally:
        store.close()
    config = tmp_path / "cloud-jev.toml"
    config.write_text(_CLOUD_TOML.replace(
        'HARNESS_DECISION_ENGINE = "off"',
        'HARNESS_DECISION_ENGINE = "jev"\nHARNESS_JEV_BUILD = "openrouter/typesafe/jev-1.13@20260917"'),
        encoding="utf-8")
    code = cli.main(["run", "--data-dir", str(tmp_data_dir), "--cohort", ORCH_COHORT_ID,
                     "--package-version", version, "--config", str(config)])
    assert code == 1
    store = open_store(tmp_data_dir)
    try:
        assert list(Orchestrator(store).runs()) == [], (
            "TC-PIPE-26: a refused run must leave nothing behind")
    finally:
        store.close()


def test_tc_pipe_26_the_console_start_binds_the_launchers_provider(tmp_data_dir, monkeypatch):
    """The console's start-run builds the same provider `aeh run` does and hands it to the
    worker's drive."""
    from aeh.pipeline import background

    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("S001",))
        version = seed_package(store, _CRITERIA)
        driven = {}
        monkeypatch.setattr(background, "run_to_completion",
                            lambda store, run_id, **kw: driven.update(kw))
        _run_id, thread = background.start_run_in_background(
            store, cohort_id=ORCH_COHORT_ID, package_version_id=version,
            config=hosted_cfg("dev-ci", panel=HOSTED_PANEL_3))
        thread.join(timeout=30)
    finally:
        store.close()
    assert isinstance(driven["provider"]._inner, OpenRouterProvider)
    assert driven["provider"]._inner._routing() == ZERO_RETENTION_ROUTING
    assert "decision_provider" in driven


_CLOUD_TOML = """
HARNESS_PROFILE = "cloud-hosted"
prompt_template_v = "judge-prompt/2"
[profiles.cloud-hosted]
HARNESS_COST_CEILING = 5
HARNESS_COST_CURRENCY = "USD"
retention_setting = "zero-retention"
HARNESS_DECISION_ENGINE = "off"
[profiles.cloud-hosted.transcriber]
role = "transcriber"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01"
[[profiles.cloud-hosted.panel]]
role = "judge"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-30b-a3b@2026-06-01"
"""


# --- TC-PROV-64 -------------------------------------------------------------------------------


def _ok() -> HttpResponse:
    return HttpResponse(200, {}, json.dumps({
        "model": "qwen/qwen3-30b-a3b",
        "choices": [{"finish_reason": "stop", "message": {"content": "ready"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.000001},
    }).encode("utf-8"))


class _Recording:
    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.requests: list = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


_REF = __import__("aeh.conf", fromlist=["ModelRef"]).ModelRef(
    role="judge", provider="openrouter",
    build_id="openrouter/qwen/qwen3-30b-a3b@2026-06-01", quantization=None)
_PAYLOAD = PromptPayload(fields=(("instruction", "Reply with the word ready"),))


def test_tc_prov_64_every_request_carries_the_zero_retention_routing():
    transport = _Recording(_ok())
    OpenRouterProvider.enforcing_zero_retention(
        api_key="k", base_url="https://or.test/api/v1", transport=transport,
        clock=CountingClock()).complete(_PAYLOAD, _REF, SamplingParams(temperature=0.0))
    (request,) = transport.requests
    body = json.loads(request.body)
    assert body["provider"] == {"zdr": True, "data_collection": "deny"}


def test_tc_prov_64_the_gate_is_answered_by_the_enforcement_without_a_request():
    transport = _NoNetwork()
    provider = OpenRouterProvider.enforcing_zero_retention(
        api_key="k", base_url="https://or.test/api/v1", transport=transport)
    report = provider.verify_retention((_REF,))
    assert report.confirmed == (_REF,) and report.unconfirmed == ()
    assert transport.requests == []


def test_tc_prov_64_a_provider_built_without_the_routing_does_not_claim_it():
    transport = _Recording(_ok())
    provider = OpenRouterProvider(api_key="k", base_url="https://or.test/api/v1",
                                  transport=transport, clock=CountingClock(),
                                  zero_data_retention=False)
    provider.complete(_PAYLOAD, _REF, SamplingParams(temperature=0.0))
    assert "provider" not in json.loads(transport.requests[0].body)


def test_tc_prov_64_no_zero_retention_host_pauses_the_run_naming_the_policy():
    """What OpenRouter answers when no host serving the model keeps zero retention."""
    refusal = HttpResponse(404, {}, json.dumps({"error": {
        "message": "No endpoints found matching your data policy (Zero data retention).",
        "code": 404}}).encode("utf-8"))
    transport = _Recording(refusal)
    provider = OpenRouterProvider.enforcing_zero_retention(
        api_key="k", base_url="https://or.test/api/v1", transport=transport,
        clock=CountingClock(), policy=RetryPolicy(3, 1, 120.0))
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.complete(_PAYLOAD, _REF, SamplingParams(temperature=0.0))
    assert "data policy" in str(caught.value) and len(transport.requests) == 1
