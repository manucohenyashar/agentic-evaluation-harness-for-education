"""TC-PROV-19 — the clause suite against a live local server on E3, nightly.

Case: `TC-PROV-19` (`NFR-PROV-01`, `FR-PROV-01`, P0, **nightly**, Integration-live, rung 2,
test plan §5.2 and §6.11.2). Issue #23 (TS-06).

`§6.11.2`: the whole clause suite is parametrized over the three implementations — the
fixture run is the fast tier, and **the live runs are nightly under the `live` marker, and
their failure is P0, not advisory**, because they are the only thing that can detect the
double drifting from the contract the real backend keeps (RISK-37).

What this file runs is the same caller the fast tier runs: the substitutability probe over
all four interface operations, plus the fixture differential — the live completion is
recorded into a `RecordedFixtureProvider` (the nightly `F-RECORDED` regeneration path) and
the replay must return it byte-identically. That is the differential the plan names:
*"the companion real test for every fixture-provider case in the fast tier."*

Environment: E3, a live local model server (Ollama / vLLM-MLX). This case has **never been
executed** — E3 does not exist in this repository (`CLAUDE.md`: all work runs locally, no
model server is provisioned). It is written against the design's interface so whoever stands
E3 up inherits the assertion rather than inventing one, exactly as `TC-PROV-22` did. Marked
`live`, `slow` and `integration`, so the fast tier never selects it.

Not marked `writtenahead` — the marker means "excluded from TEST_CMD until its implementing
issue closes", and the blocker here is hardware, not code (see TC-PROV-22's module
docstring for the full reasoning this file inherits).
"""

from __future__ import annotations

import dataclasses
import os
from decimal import Decimal

import pytest

from aeh.conf import ModelRef
from aeh.prov import CallPlan, PromptPayload, SamplingParams
from tests.support.prov_contract import payload as contract_payload

pytestmark = [pytest.mark.live, pytest.mark.slow, pytest.mark.integration]

ISSUE = "#23"


def _base_url() -> str:
    base_url = os.environ.get("LOCAL_INFERENCE_BASE_URL")
    if not base_url:
        pytest.fail(
            "TC-PROV-19 runs on E3 against a live local server; set "
            "LOCAL_INFERENCE_BASE_URL. Skipping would let the nightly tier report green "
            "without ever comparing the real backend to the double the whole fast tier "
            "runs on (RISK-37) — the one check that can catch the drift."
        )
    return base_url


def _live_provider():
    from aeh.prov import LocalServerProvider

    return LocalServerProvider(base_url=_base_url())


def _live_model_ref() -> ModelRef:
    return ModelRef(
        role="judge",
        provider="ollama",
        build_id=os.environ.get("HARNESS_LIVE_BUILD_ID", "local-model"),
        quantization=os.environ.get("HARNESS_LIVE_QUANTIZATION", "q4"),
    )


def test_tc_prov_19_the_clause_caller_runs_unchanged_against_the_live_server():
    """TC-PROV-19 — the same caller the fast tier runs, against the real E3 backend.

    The four interface operations answer exactly as the clause suite asserts they must:
    a fully-populated `Completion` (TC-PROV-01's shape), declared capabilities
    (`CT-PROV-04`), a pure estimate (`CT-PROV-09`), and a retention check that is
    confirmed by construction — local inference dispatches nothing off the machine.
    """
    provider = _live_provider()
    ref = _live_model_ref()
    params_ = SamplingParams(temperature=0.0)
    payload = contract_payload(PromptPayload)

    got = provider.complete(payload, ref, params_)
    for field_name in ("text", "tokens_in", "tokens_out", "latency_ms", "resolved_build",
                       "cached_prefix_tokens"):
        value = getattr(got, field_name)
        assert value is not None, (
            f"TC-PROV-19: Completion.{field_name} is None from the live server. The live "
            "backend must populate every non-nullable field the fast tier's double "
            "populates (CT-PROV-03) — a field the double fills and the real backend "
            "leaves null is exactly the RISK-37 drift the nightly exists to catch."
        )
    assert got.cost is None, (
        "TC-PROV-19: the edge-local backend billed nothing, so cost is null (CT-PROV-03)."
    )
    assert got.resolved_build, (
        "TC-PROV-19: resolved_build is empty. What actually answered is recorded into "
        "run_metrics (FR-PROV-04); an empty string answers nothing."
    )

    caps = provider.capabilities(ref)
    assert caps.max_concurrency >= 1 and isinstance(
        caps.deterministic_at_temperature_zero, bool)

    estimate = provider.estimate_cost(
        CallPlan(calls=350, tokens_in_per_call=1_800, tokens_out_per_call=12))
    assert estimate.tokens_in == 350 * 1_800 and estimate.tokens_out == 350 * 12
    assert estimate.cost == Decimal("0"), (
        "TC-PROV-19: the edge-local implementation declares zero per-token rates, so its "
        "estimate is zero — computed from the declared rates, never hardcoded."
    )

    retention = provider.verify_retention([ref])
    assert retention.all_confirmed, (
        "TC-PROV-19: local inference could not confirm zero-retention. Nothing leaves the "
        "machine on E3 — the gate refusing here means the implementation, not the backend, "
        "is wrong."
    )


def test_tc_prov_19_the_live_answer_replays_identically_through_the_fixture():
    """TC-PROV-19's differential: the live completion, recorded through the nightly
    regeneration path, replays byte-identically.

    `record()` refuses a non-null cost (CT-PROV-03 makes fixture cost null), so the
    regeneration path nulls it before recording — the same rule the plan gives `F-RECORDED`.
    The replayed completion must equal the live one it was recorded from: that equality is
    what lets every fast-tier case run against the double and mean the real backend.
    """
    provider = _live_provider()
    ref = _live_model_ref()
    params_ = SamplingParams(temperature=0.0)
    payload = contract_payload(PromptPayload)

    live = provider.complete(payload, ref, params_)

    from aeh.prov import RecordedFixtureProvider
    import tempfile

    fixture_dir = tempfile.mkdtemp(prefix="tc-prov-19-")
    fixtures = RecordedFixtureProvider(fixture_dir=fixture_dir)
    fixtures.record(payload, ref, params_, dataclasses.replace(live, cost=None))

    replayed = fixtures.complete(payload, ref, params_)
    assert replayed == dataclasses.replace(live, cost=None), (
        "TC-PROV-19: the recorded live answer does not replay identically. The fixture "
        "provider must return exactly what the real backend answered (TC-PROV-13's "
        "equality, now against reality) — any difference is RISK-37's drift, and the fast "
        "tier has been describing a system that does not exist."
    )


def test_tc_prov_19_the_counters_survive_a_small_live_batch():
    """TC-PROV-19's observability half: a small live batch accumulates real usage in the
    run counters, under the contract names — the same assertion the fast tier makes against
    programmed responses, now against measured usage."""
    provider = _live_provider()
    ref = _live_model_ref()
    params_ = SamplingParams(temperature=0.0)
    payload = contract_payload(PromptPayload)

    before = provider.counters
    for _ in range(2):
        provider.complete(payload, ref, params_)
    after = provider.counters

    assert after.tokens_in >= before.tokens_in + 1, (
        "TC-PROV-19: two live calls accumulated no input tokens. The counters are read by "
        "M-ORCH for persistence into run_metrics (CT-PROV-11); zero usage from real calls "
        "means the accounting, not the backend, is broken."
    )
    assert 0.0 <= after.cache_hit_rate <= 1.0, (
        "TC-PROV-19: cache_hit_rate is not a rate in [0,1] against live usage. The name "
        "and meaning are contract (CT-PROV-14) — it is RISK-23's only detector."
    )
