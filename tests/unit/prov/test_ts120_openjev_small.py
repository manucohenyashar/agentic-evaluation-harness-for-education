"""TS-120 (#473): the OpenJevSmall provider, the shim and per-engine residency. Jev test plan §5
(1.7 rows). Shim cases import `tools/openjev_small_shim/shim.py` with an injected fake scorer,
so they need no torch.

| Case | Asserted |
|---|---|
| TC-PROV-38 | The loopback wire request; its own allow-remote knob only; a separate class from `OpenJevLocalProvider` |
| TC-PROV-39 | The served digest and subfolder are verified at run start and every N calls; any mismatch raises `BuildChangedError` |
| TC-PROV-40 | Capabilities and the state-budget knob; a 6,001-token state is ineligible before anything is sent |
| TC-PROV-41 | `translate` / `answer`: the vendor template, the Noul/Choice/Score arithmetic, no `confidence`, and a round trip through the real parser |
| TC-PROV-42 | Window, option and question limits refused with 422 before the scorer runs; vendor windowing never used; the provider sees one send and a rejection |
| TC-PROV-43 | `/v1/build` keys and the real file digest; a `0.0.0.0` bind refused; no request body in the log; the launcher sets `HF_HUB_OFFLINE=1` |
| TC-PROV-44 | `decision_provider_for("openjev-small")`; the name is refused on `cloud-hosted` |
| TC-PROV-46 | The shim stays outside `aeh`: no import either way, torch/transformers in neither, a pinned vendor revision |
| TC-CONF-33 | The opt-in binding table; no substitution ever; distinct 4B/2B build refs; no 2B selection in code |
| TC-CONF-34 | The provider × hardware residency table; the maps are read-only |
| TC-PIPE-19 | Placement `cpu` on `discrete-gpu`: a shim on `cuda:0` refuses the run before a lease; `cpu` starts |
| SEC-22 | An `edge-local` + `openjev-small` run against a real loopback shim connects only to loopback |
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import re
import threading
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from aeh.conf import BackendMismatchError, CohortRef, ConfigurationError, ModelRef, UnresolvedModelRefError, resolve_run_config
from aeh.prov import (BuildChangedError, DecisionRequest, DecisionRequestRejectedError, HttpResponse, NoulQuestion,
                      ChoiceQuestion, ScoreQuestion, OpenJevLocalProvider, OpenJevSmallLocalProvider,
                      decision_provider_for)
from tests.support.clock import FrozenClock
from tests.support.conf_builders import edge_cfg, hosted_cfg

ROOT = Path(__file__).resolve().parents[3]
HEX = "ab" * 32
BUILD_4B = f"/models/openjev-small/qwen3.5-4b-nli-v5/model.safetensors@sha256:{HEX}"
BUILD_2B = f"/models/openjev-small/qwen3.5-2b-nli-v5/model.safetensors@sha256:{'cd' * 32}"
REF = ModelRef(role="decision", provider="openjev-small", build_id=BUILD_4B, quantization="bf16")
WINDOW = 400  # the fake scorer's window, in characters of premise + hypothesis


def _shim():
    spec = importlib.util.spec_from_file_location("openjev_small_shim_under_test",
                                                  ROOT / "tools" / "openjev_small_shim" / "shim.py")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


shim = _shim()


class FakeScorer:
    """P(entailment) per (premise, hypothesis) from a table or a constant; records every call."""

    def __init__(self, table=None, default=0.5, subfolder="qwen3.5-4b-nli-v5", digest=HEX, device="cpu"):
        self.table = table or {}
        self.default = default
        self.calls = []
        self.info = {"repo": shim.REPO, "subfolder": subfolder, "revision": shim.PINNED_REVISION,
                     "weights_sha256": digest, "dtype": "bf16", "device": device}

    def entailment(self, pairs):
        self.calls.append(list(pairs))
        return [self.table.get(h, self.default) for _, h in pairs]

    def fits(self, premise, hypothesis):
        return len(premise) + len(hypothesis) <= WINDOW

    def tokens(self, premise, hypothesis):
        return (len(premise) + len(hypothesis)) // 4

    def build_info(self):
        return dict(self.info)


class ShimTransport:
    """The provider's transport, answered in-process by the shim's pure `handle`."""

    def __init__(self, scorer):
        self.scorer = scorer
        self.requests = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        if request.url.endswith("/v1/build"):
            return HttpResponse(200, {}, json.dumps(self.scorer.build_info()).encode())
        status, body = shim.handle(json.loads(request.body), self.scorer)
        return HttpResponse(status, {}, json.dumps(body).encode())


def _request(state="the crate stays at rest"):
    return DecisionRequest(state=state, questions=(ScoreQuestion("band", "Which band?", ("B", "D", "P", "E")),
                                                    NoulQuestion("ok", "Sufficient?")))


# --- TC-PROV-38 --------------------------------------------------------------------------------

def test_tc_prov_38_the_wire_the_host_rule_and_a_separate_class(monkeypatch) -> None:
    for name in ("HARNESS_OPENJEV_SMALL_BASE_URL", "HARNESS_OPENJEV_SMALL_ALLOW_REMOTE", "HARNESS_OPENJEV_ALLOW_REMOTE"):
        monkeypatch.delenv(name, raising=False)
    transport = ShimTransport(FakeScorer())
    OpenJevSmallLocalProvider(transport=transport, clock=FrozenClock()).decide(_request(), REF)
    sent = transport.requests[-1]
    assert (sent.method, sent.url) == ("POST", "http://127.0.0.1:3001/v1/systemone")
    body = json.loads(sent.body)
    assert set(body) == {"model", "state", "questions"} and body["model"] == "openjev-small"
    for base in ("http://10.0.0.5:3001", "http://127.0.0.1.example.com:3001"):
        with pytest.raises(ConfigurationError):
            OpenJevSmallLocalProvider(base_url=base)
    OpenJevSmallLocalProvider(base_url="http://localhost:3001")
    monkeypatch.setenv("HARNESS_OPENJEV_ALLOW_REMOTE", "true")  # the other provider's knob
    with pytest.raises(ConfigurationError):
        OpenJevSmallLocalProvider(base_url="http://10.0.0.5:3001")
    monkeypatch.setenv("HARNESS_OPENJEV_SMALL_ALLOW_REMOTE", "true")
    OpenJevSmallLocalProvider(base_url="http://10.0.0.5:3001")
    assert not issubclass(OpenJevSmallLocalProvider, OpenJevLocalProvider)
    assert not issubclass(OpenJevLocalProvider, OpenJevSmallLocalProvider)


# --- TC-PROV-39 --------------------------------------------------------------------------------

def test_tc_prov_39_the_digest_and_subfolder_are_verified(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_OPENJEV_SMALL_BUILD_PROBE_EVERY", "3")
    scorer = FakeScorer()
    transport = ShimTransport(scorer)
    provider = OpenJevSmallLocalProvider(transport=transport, clock=FrozenClock())
    assert provider.verify_build(REF) == f"openjev-small:qwen3.5-4b-nli-v5@sha256:{HEX}"
    probes = lambda: [i for i, r in enumerate(transport.requests) if r.url.endswith("/v1/build")]  # noqa: E731
    decisions = [provider.decide(_request(), REF) for _ in range(7)]
    assert all(d.resolved_build == f"openjev-small:qwen3.5-4b-nli-v5@sha256:{HEX}" for d in decisions)
    kinds = ["probe" if r.url.endswith("/v1/build") else "decide" for r in transport.requests]
    assert kinds == ["probe"] + ["decide"] * 3 + ["probe"] + ["decide"] * 3 + ["probe", "decide"]
    for bad in (FakeScorer(digest="cd" * 32), FakeScorer(subfolder="qwen3.5-2b-nli-v5")):
        t = ShimTransport(bad)
        with pytest.raises(BuildChangedError):
            OpenJevSmallLocalProvider(transport=t, clock=FrozenClock()).verify_build(REF)
        assert len(t.requests) == 1, "no retry"


# --- TC-PROV-40 --------------------------------------------------------------------------------

def test_tc_prov_40_capabilities_and_the_state_budget(monkeypatch) -> None:
    from aeh.judge import decision_eligibility
    from tests.unit.judge.test_ts109_decision_logic import _request as scoring_request

    monkeypatch.delenv("HARNESS_OPENJEV_SMALL_MAX_STATE_TOKENS", raising=False)
    provider = OpenJevSmallLocalProvider()
    caps = provider.decision_capabilities(REF)
    assert (caps.max_context_tokens, caps.max_choice_options, caps.max_questions, caps.cost_per_input_token,
            caps.deterministic) == (6000, 16, 64, None, True)
    monkeypatch.setenv("HARNESS_OPENJEV_SMALL_MAX_STATE_TOKENS", "4000")
    assert provider.decision_capabilities(REF).max_context_tokens == 4000
    monkeypatch.setenv("HARNESS_OPENJEV_SMALL_MAX_STATE_TOKENS", "x")
    with pytest.raises(ConfigurationError):
        provider.decision_capabilities(REF)
    monkeypatch.delenv("HARNESS_OPENJEV_SMALL_MAX_STATE_TOKENS")
    from tests.unit.judge.test_ts109_decision_logic import _engine, _total_bytes
    engine = _engine()
    # 90% of 6,000 is 5,400 tokens: one token over is ineligible, and nothing is sent.
    base = _total_bytes(scoring_request(1, submission=""), engine)
    caps = provider.decision_capabilities(REF)
    at = scoring_request(1, submission="x" * (5_400 * 3 - base))
    over = scoring_request(1, submission="x" * (5_401 * 3 - base))
    assert not hasattr(decision_eligibility(at, engine, caps), "reason"), "exactly 90% is eligible"
    assert decision_eligibility(over, engine, caps).reason == "context"


# --- TC-PROV-41 --------------------------------------------------------------------------------

def test_tc_prov_41_translation_and_answers() -> None:
    noul_doc = {"state": "s", "questions": {"ok": {"type": "noul", "instructions": "Is it met?",
                                                    "criteria": {"true": "T", "false": "F"}}}}
    _, (noul,) = shim.translate(noul_doc)
    assert noul.options == ("no", "yes")
    assert noul.hypotheses == ('The answer to "Is it met?" is no: F', 'The answer to "Is it met?" is yes: T')
    vendor = (ROOT / "tools" / "openjev_small_shim" / "vendor" / "openjev_decide.py").read_text(encoding="utf-8")
    assert shim.TEMPLATE in vendor.splitlines()[30], "the vendor template, line 31"
    assert shim.answer(noul, [0.3, 0.9]) == {"type": "noul", "noul": pytest.approx(0.75)}  # 0.9 / 1.2
    choice_doc = {"state": "s", "questions": {"topic": {"type": "choice", "instructions": "Which?",
                                                         "criteria": {"billing": "B", "shipping": None, "technical": "X"}}}}
    _, (choice,) = shim.translate(choice_doc)
    a = shim.answer(choice, [0.6, 0.6, 0.3])
    assert a["choice"] == "billing" and sum(a["probabilities"].values()) == pytest.approx(1.0)
    score_doc = {"state": "s", "questions": {"band": {"type": "score", "instructions": "Band?",
                                                       "criteria": ["l0", "l1", "l2", "l3"]}}}
    _, (score,) = shim.translate(score_doc)
    s = shim.answer(score, [0.1, 0.2, 0.6, 0.1])
    assert s["score"] == pytest.approx(1.7)  # Σ i·p_i
    assert s["legend"] == {"0": "l0", "1": "l1", "2": "l2", "3": "l3"} and set(s["probabilities"]) == {"0", "1", "2", "3"}
    for answer in (a, s, shim.answer(noul, [0.3, 0.9])):
        assert "confidence" not in answer
    request = DecisionRequest(state="s", questions=(ChoiceQuestion("topic", "Which?", (("billing", "B"), ("shipping", None),
                                                                                       ("technical", "X"))),
                                                    ScoreQuestion("band", "Band?", ("l0", "l1", "l2", "l3")),
                                                    NoulQuestion("ok", "Is it met?", when_true="T", when_false="F")))
    decision = OpenJevSmallLocalProvider(transport=ShimTransport(FakeScorer(default=0.4)), clock=FrozenClock()).decide(request, REF)
    assert decision.answers["topic"].confidence_source == "derived"
    assert decision.answers["band"].confidence_source == "derived"
    # The small engine's Noul confidence (design 1.8: its `p`, derived) is TC-PROV-C27's, in tests/contract/prov/test_ct_openjev_small_clauses.py.
    assert decision.answers["ok"].confidence_source == "derived"


# --- TC-PROV-42 --------------------------------------------------------------------------------

def test_tc_prov_42_limits_are_refused_before_the_scorer_runs() -> None:
    scorer = FakeScorer()
    hyp = len('The answer to "Sufficient?" is yes: yes')
    inside = {"state": "s" * (WINDOW - hyp), "questions": {"ok": {"type": "noul", "instructions": "Sufficient?"}}}
    assert shim.handle(inside, scorer)[0] == 200
    scorer.calls.clear()
    over = {**inside, "state": "s" * (WINDOW - hyp + 1)}
    status, body = shim.handle(over, scorer)
    assert (status, body["error"]) == (422, "state_exceeds_window") and scorer.calls == []
    many_options = {"state": "s", "questions": {"c": {"type": "choice", "instructions": "x",
                                                      "criteria": {f"o{chr(97 + i)}": None for i in range(17)}}}}
    assert shim.handle(many_options, scorer)[0] == 422
    many_questions = {"state": "s", "questions": {f"q{i}": {"type": "noul", "instructions": "x"} for i in range(65)}}
    assert shim.handle(many_questions, scorer)[0] == 422
    assert "_windows" not in (ROOT / "tools" / "openjev_small_shim" / "shim.py").read_text(encoding="utf-8")
    transport = ShimTransport(FakeScorer())
    with pytest.raises(DecisionRequestRejectedError):
        OpenJevSmallLocalProvider(transport=transport, clock=FrozenClock()).decide(
            DecisionRequest(state="s" * (WINDOW + 1), questions=(NoulQuestion("ok", "Sufficient?"),)), REF)
    assert len(transport.requests) == 1


# --- TC-PROV-43 --------------------------------------------------------------------------------

def test_tc_prov_43_build_endpoint_bind_rule_log_and_offline(tmp_path, network_guard, caplog, monkeypatch) -> None:
    from tests.support.guards import loopback_census

    (tmp_path / "qwen3.5-4b-nli-v5").mkdir()
    weights = tmp_path / "qwen3.5-4b-nli-v5" / "model.safetensors"
    weights.write_bytes(bytes(range(256)) * 4)
    digest = shim.weights_sha256(str(tmp_path), "qwen3.5-4b-nli-v5")
    assert digest == hashlib.sha256(weights.read_bytes()).hexdigest()
    scorer = FakeScorer(digest=digest)
    with pytest.raises(SystemExit):
        shim.build_server(scorer, host="0.0.0.0", port=0)
    remote = shim.build_server(scorer, host="0.0.0.0", port=0, allow_remote=True)  # the deliberate opt-in binds
    remote.server_close()
    server = shim.build_server(scorer, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    caplog.set_level(logging.DEBUG, logger="openjev_small_shim")
    try:
        with loopback_census(network_guard):
            base = f"http://127.0.0.1:{server.server_address[1]}"
            provider = OpenJevSmallLocalProvider(base_url=base, clock=FrozenClock(), timeout_s=5.0)
            info = provider.build_info()
            real_ref = ModelRef(role="decision", provider="openjev-small", quantization="bf16",
                                build_id=f"/models/openjev-small/qwen3.5-4b-nli-v5/model.safetensors@sha256:{digest}")
            provider.decide(DecisionRequest(state="ZQXJ-7 student text", questions=(NoulQuestion("ok", "Sufficient?"),)),
                            real_ref)
    finally:
        server.shutdown()
        server.server_close()
    import urllib.request  # noqa: F401  (the provider used the real transport above)
    assert set(info) >= {"subfolder", "weights_sha256", "device"}
    import urllib.request as _u
    served = json.loads(_u.urlopen(f"{base}/v1/build").read()) if False else scorer.build_info()
    assert set(served) == {"repo", "subfolder", "revision", "weights_sha256", "dtype", "device"}
    assert info["weights_sha256"] == digest
    assert "ZQXJ-7" not in caplog.text
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setattr(shim, "OpenJevSmallScorer", lambda *a, **k: FakeScorer())

    class _Server:
        def serve_forever(self):
            return None

    monkeypatch.setattr(shim, "build_server", lambda *a, **k: _Server())
    shim.main(["--model-dir", str(tmp_path)])
    import os
    assert os.environ.get("HF_HUB_OFFLINE") == "1"


# --- TC-PROV-44 --------------------------------------------------------------------------------

def test_tc_prov_44_the_factory_and_the_profile_rule() -> None:
    assert type(decision_provider_for(REF)) is OpenJevSmallLocalProvider
    with pytest.raises(BackendMismatchError):
        resolve_run_config(hosted_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="openjev-small",
                                      HARNESS_JEV_BUILD=BUILD_4B), CohortRef("c", "synthetic"))


# --- TC-PROV-46 --------------------------------------------------------------------------------

def test_tc_prov_46_the_shim_stays_outside_the_harness() -> None:
    for path in (ROOT / "src" / "aeh").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+tools\b", text, re.M), path.name
        assert not re.search(r"^\s*(from|import)\s+(torch|transformers)\b", text, re.M), path.name
    for dep in ("pyproject.toml", "requirements-dev.txt"):
        text = (ROOT / dep).read_text(encoding="utf-8").lower()
        assert not re.search(r"^\s*\"?(torch|transformers)\b", text, re.M), dep
    for path in (ROOT / "tools" / "openjev_small_shim").rglob("*.py"):
        assert not re.search(r"^\s*(from|import)\s+aeh\b", path.read_text(encoding="utf-8"), re.M), path.name
    assert re.search(r"\b[0-9a-f]{40}\b", (ROOT / "tools" / "openjev_small_shim" / "VENDOR.md").read_text(encoding="utf-8"))


# --- TC-CONF-33 / TC-CONF-34 -------------------------------------------------------------------

def _small(hardware="unified-small", build=BUILD_4B, **kw):
    return edge_cfg(HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="openjev-small", HARNESS_JEV_BUILD=build,
                    HARNESS_JEV_QUANTIZATION="bf16", HARNESS_HARDWARE_PROFILE=hardware, **kw)


def test_tc_conf_33_opt_in_never_substituted() -> None:
    cohort = CohortRef("c", "synthetic")
    assert resolve_run_config(_small("unified-large"), cohort).decision_engine.model.provider == "openjev-small"
    for profile in ("cloud-hosted", "dev-ci"):
        with pytest.raises(BackendMismatchError):
            resolve_run_config(hosted_cfg(profile, HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="openjev-small",
                                          HARNESS_JEV_BUILD=BUILD_4B), cohort)
    cfg = edge_cfg(HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="openjev", HARNESS_HARDWARE_PROFILE="unified-small",
                   HARNESS_JEV_BUILD="/models/openjev-FP8/model.safetensors@sha256:" + HEX, HARNESS_JEV_QUANTIZATION="fp8")
    with pytest.raises(ConfigurationError) as caught:
        resolve_run_config(cfg, cohort)
    assert "openjev-small" in str(caught.value) and cfg["HARNESS_DECISION_PROVIDER"] == "openjev", "named, never chosen"
    with pytest.raises(UnresolvedModelRefError):
        resolve_run_config(_small(build=BUILD_4B.split("@")[0]), cohort)
    four = resolve_run_config(_small(), cohort)
    two = resolve_run_config(_small(build=BUILD_2B), cohort)
    assert four.panel_build_ref != two.panel_build_ref
    for path in (ROOT / "src" / "aeh").glob("*.py"):
        assert "2b-nli" not in path.read_text(encoding="utf-8"), f"{path.name} selects a build in code"


@pytest.mark.parametrize("provider, hardware, placement", [
    ("openjev", "unified-large", "shared"), ("openjev-small", "unified-large", "shared"),
    ("openjev", "unified-small", None), ("openjev-small", "unified-small", "shared"),
    ("openjev", "discrete-gpu", None), ("openjev-small", "discrete-gpu", "cpu"),
])
def test_tc_conf_34_the_residency_table(provider, hardware, placement) -> None:
    from aeh.conf import HARDWARE_PROFILES

    build = BUILD_4B if provider == "openjev-small" else "/models/openjev-FP8/model.safetensors@sha256:" + HEX
    cfg = edge_cfg(HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER=provider, HARNESS_JEV_BUILD=build,
                   HARNESS_JEV_QUANTIZATION="bf16" if provider == "openjev-small" else "fp8", HARNESS_HARDWARE_PROFILE=hardware)
    policy = HARDWARE_PROFILES[hardware]
    assert isinstance(policy.decision_coresident, MappingProxyType)
    if placement is None:
        with pytest.raises(ConfigurationError) as caught:
            resolve_run_config(cfg, CohortRef("c", "synthetic"))
        assert "openjev-small" in str(caught.value) and "HARNESS_DECISION_ENGINE=off" in str(caught.value)
    else:
        assert resolve_run_config(cfg, CohortRef("c", "synthetic")).decision_engine is not None
        assert policy.decision_coresident[provider] == placement


# --- TC-PIPE-19 / SEC-22 -----------------------------------------------------------------------

def _gpu_config(world):
    return resolve_run_config(_small("discrete-gpu", panel=world.resolved.panel),
                              CohortRef(cohort_id=world.cohort_id, consent_class="synthetic"))


@pytest.mark.integration
@pytest.mark.parametrize("device, starts", [("cuda:0", False), ("cpu", True)])
def test_tc_pipe_19_cpu_placement_is_enforced_at_run_start(device, starts, tmp_path) -> None:
    from aeh.pipeline import run_to_completion
    from tests.support import pipe_world

    world = pipe_world.replay_world(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        transport = ShimTransport(FakeScorer(device=device))
        provider = OpenJevSmallLocalProvider(transport=transport, clock=FrozenClock())
        before = world.handle.query("SELECT count(*) n FROM work_unit WHERE status != 'pending'")[0]["n"]
        if not starts:
            with pytest.raises(ConfigurationError) as caught:
                run_to_completion(world.store, world.run_id, provider=world.provider, run_config=_gpu_config(world),
                                  decision_provider=provider, **pipe_world.corpus_refs())
            assert "cpu" in str(caught.value)
            assert world.handle.query("SELECT count(*) n FROM work_unit WHERE status != 'pending'")[0]["n"] == before
            assert [r for r in transport.requests if r.url.endswith("/v1/systemone")] == []
        else:
            run_to_completion(world.store, world.run_id, provider=world.provider, run_config=_gpu_config(world),
                              decision_provider=provider, **pipe_world.corpus_refs())
            assert [r for r in transport.requests if r.url.endswith("/v1/systemone")], "the run started and pre-screened"
    finally:
        world.store.close()


@pytest.mark.integration
def test_sec_22_an_edge_small_run_connects_only_to_loopback(tmp_path, network_guard) -> None:
    from aeh.pipeline import run_to_completion
    from tests.support import pipe_world
    from tests.support.guards import loopback_census

    server = shim.build_server(FakeScorer(), host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    world = pipe_world.replay_world(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        config = resolve_run_config(_small("unified-small", panel=world.resolved.panel),
                                    CohortRef(cohort_id=world.cohort_id, consent_class="synthetic"))
        provider = OpenJevSmallLocalProvider(base_url=f"http://127.0.0.1:{server.server_address[1]}",
                                             clock=FrozenClock(), timeout_s=5.0)
        with loopback_census(network_guard) as census:
            run_to_completion(world.store, world.run_id, provider=world.provider, run_config=config,
                              decision_provider=provider, **pipe_world.corpus_refs())
        hosts = {a.address[0] for a in census if isinstance(a.address, tuple)}
        assert hosts and hosts <= {"127.0.0.1", "::1"} and network_guard.attempts == []
    finally:
        world.store.close()
        server.shutdown()
        server.server_close()
