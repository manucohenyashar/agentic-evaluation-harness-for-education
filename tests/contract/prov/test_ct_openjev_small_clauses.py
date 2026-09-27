"""TS-121 (#474): the OpenJevSmall clauses. Jev test plan §6.11.5.

| Case | Clause | Asserted |
|---|---|---|
| TC-PROV-C26 | behaviour | Local, single-window: loopback-only construction, a separate class, and an over-window request refused by the shim before any scoring, never windowed (the rung-3 socket census is SEC-22 in TS-120) |
| TC-PROV-C27 | data | Every answer type round-trips with `confidence_source == "derived"`; a shim that emits `confidence: 0.99` does not reach the caller |
| TC-PROV-C28 | security | No `aeh` module imports the shim or torch; importing `aeh.prov` in a fresh interpreter loads no torch |
| TC-CONF-C21 | behaviour | Property: `openjev` on `unified-small` is refused under 50 random configurations, never downgraded to `openjev-small` |
| TC-CONFORM-C16 | observe | The injection report names the three figures and the validation record carries `decision_engine_injection_robust` |
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from aeh.conf import CohortRef, ConfigurationError, resolve_run_config
from aeh.prov import (ChoiceQuestion, DecisionRequest, DecisionRequestRejectedError, HttpResponse, NoulQuestion,
                      OpenJevLocalProvider, OpenJevSmallLocalProvider, ScoreQuestion)
from tests.support.clock import FrozenClock
from tests.support.conf_builders import edge_cfg
from tests.unit.prov.test_ts120_openjev_small import REF, WINDOW, FakeScorer, ShimTransport, shim

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[3]


def test_tc_prov_c26_local_and_single_window() -> None:
    """Adversarial construction: re-enabling the vendor's windowing "for long answers" would score
    the over-window state window by window; here it is refused with no scorer call."""
    with pytest.raises(ConfigurationError):
        OpenJevSmallLocalProvider(base_url="http://127.0.0.1.example.com:3001")
    assert not issubclass(OpenJevSmallLocalProvider, OpenJevLocalProvider)
    scorer = FakeScorer()
    transport = ShimTransport(scorer)
    with pytest.raises(DecisionRequestRejectedError):
        OpenJevSmallLocalProvider(transport=transport, clock=FrozenClock()).decide(
            DecisionRequest(state="s" * (WINDOW * 3), questions=(NoulQuestion("ok", "Sufficient?"),)), REF)
    assert scorer.calls == [] and len(transport.requests) == 1
    source = (ROOT / "tools" / "openjev_small_shim" / "shim.py").read_text(encoding="utf-8")
    assert "_windows" not in source and "max(" not in source.split("def handle", 1)[1].split("\ndef ", 1)[0]


def test_tc_prov_c27_every_confidence_is_derived() -> None:
    request = DecisionRequest(state="s", questions=(
        ChoiceQuestion("topic", "Which?", (("a", None), ("b", None))),
        ScoreQuestion("band", "Band?", ("l0", "l1", "l2", "l3")),
        NoulQuestion("ok", "Met?")))

    class LyingTransport(ShimTransport):
        """A shim that starts emitting a made-up confidence."""

        def send(self, request):  # noqa: ANN001
            response = super().send(request)
            body = json.loads(response.body)
            for answer in body.get("answers", {}).values():
                answer["confidence"] = 0.99
            return HttpResponse(response.status, {}, json.dumps(body).encode())

    for transport in (ShimTransport(FakeScorer(default=0.4)), LyingTransport(FakeScorer(default=0.4))):
        decision = OpenJevSmallLocalProvider(transport=transport, clock=FrozenClock()).decide(request, REF)
        assert decision.answers["topic"].confidence_source == "derived"
        assert decision.answers["band"].confidence_source == "derived"
        assert decision.answers["band"].confidence != 0.99 and decision.answers["topic"].confidence != 0.99
        assert decision.answers["ok"].confidence == pytest.approx(abs(2 * decision.answers["ok"].p_true - 1))


def test_tc_prov_c28_torch_never_enters_the_harness() -> None:
    for path in (ROOT / "src" / "aeh").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+(tools|torch|transformers)\b", text, re.M), path.name
    code = "import sys; sys.path.insert(0, 'src'); import aeh, aeh.prov; print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert out.stdout.strip() == "False", out.stdout + out.stderr


def test_tc_conf_c21_never_downgraded_to_openjev_small() -> None:
    """Adversarial construction: a "helpful" resolver branch that downgrades to `openjev-small` with
    a warning would return a config here instead of refusing."""
    rng = random.Random(20260927)
    for _ in range(50):
        extras = {}
        if rng.random() < 0.5:
            extras["HARNESS_JEV_CONFIDENCE_THRESHOLD"] = str(Decimal(rng.randint(50, 99)) / 100)
        if rng.random() < 0.5:
            extras["HARNESS_JEV_MAX_CITATION_QUESTIONS"] = str(rng.randint(1, 26))
        if rng.random() < 0.5:
            extras["HARNESS_JEV_TOKEN_BYTES_RATIO"] = str(rng.randint(1, 8))
        if rng.random() < 0.5:
            extras["HARNESS_JEV_CITE_THRESHOLD"] = str(Decimal(rng.randint(1, 99)) / 100)
        cfg = edge_cfg(HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="openjev",
                       HARNESS_HARDWARE_PROFILE="unified-small", HARNESS_JEV_QUANTIZATION="fp8",
                       HARNESS_JEV_BUILD="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32, **extras)
        with pytest.raises(ConfigurationError):
            resolve_run_config(cfg, CohortRef("c", "synthetic"))


def test_tc_conform_c16_the_injection_report_names_its_figures(tmp_path) -> None:
    from aeh import conform
    from aeh.conf import DecisionEngine, ModelRef
    from aeh.prov import RecordedFixtureProvider
    from tests.support import jev_corpora

    engine = DecisionEngine(model=ModelRef(role="decision", provider="fixture",
                                           build_id="/models/jev/model.safetensors@sha256:" + "ab" * 32, quantization="bf16"),
                            confidence_threshold=Decimal("0.80"), cite_threshold=Decimal("0.50"),
                            max_citation_questions=16, token_bytes_ratio=3)
    jev_corpora.record_adv_decisions(tmp_path, engine)
    report = conform.run_injection_robustness(
        {"openjev-small": (RecordedFixtureProvider(fixture_dir=tmp_path), engine, "edge-local")},
        lambda request: 1, pairs=conform._injection_pairs_from("F-ADV-INJ-DECISION", None))
    figures = report.per_backend["openjev-small"]
    assert set(conform.DECISION_INJECTION_KEYS) <= set(figures)
    assert "decision_engine_injection_robust" in report.validation_records[0].figure
