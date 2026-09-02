"""The invariant prefix is not reallocated per call.

Case: `TC-PROV-22` (`NFR-PROV-02`, P1, **nightly**, Performance, rung 2, test plan §5.2; the
threshold is `PERF-04`, §6.4). Issue #24 (TS-07).

`NFR-PROV-02`: *"The local implementation shall sustain the configured concurrency without
additional per-call allocation of the invariant prefix, so measured `cache_hit_rate` reflects
prompt ordering rather than client behaviour."*

What this case is really guarding is RISK-23, rated **High** with detectability *"only if the
metric is watched"*: prefix ordering is lost, `cache_hit_rate` collapses, and the run takes five
times longer **with no error raised**. The consequence is the overnight window — the run does
not finish by morning — and HLD §9.7 calls that a build failure rather than a curiosity. There
is no exception to catch and no assertion anywhere else in the suite that fires. This case, and
the metric it reads, are the whole detector.

Environment: E3, a live local model server (Ollama or vLLM-MLX). Marked `live`, `slow` and
`integration`, so the fast tier never selects it and `pytest -q -m live` picks it up nightly.

**This case has never been executed.** E3 does not exist in this repository — `CLAUDE.md` states
that all work runs locally and no model server is provisioned — and `LocalServerProvider` is
issue #21. It is written now, against the design's interface, so that whoever stands E3 up
inherits the assertion rather than inventing one; the PR says so explicitly rather than letting
a `live`-marked test imply it was ever run.

Not marked `writtenahead`
--------------------------
The marker means *"excluded from `TEST_CMD` until its implementing issue closes"*, and
`writtenahead` tests are registered so the gate can announce when to unmark them. Neither fits
here: `live` already excludes this from the fast tier, and #21 landing would **not** make the
test runnable — it needs hardware, not code. Registering it would fire the gate and tell
somebody to unmark a test that then fails for a reason nobody expects, which is how a gate
stops being believed.

Consequence worth stating: a bare `pytest -q` with no marker filter collects and runs this file,
so it appears in the full-suite failure count until E3 and #21 both exist.
"""

from __future__ import annotations

import os
import statistics

import pytest

from tests.support.impl import PROVIDER_MODULE, require

pytestmark = [pytest.mark.live, pytest.mark.slow, pytest.mark.integration]

CONF_MODULE = "aeh.conf"
ISSUE = "#21"

#: `PERF-04`'s load profile: *"32 concurrent scoring calls in one (judge, question, criterion)
#: batch"*, which is also HLD §8.4's reference concurrency. Env-gated because a box that cannot
#: serve 32 concurrently would report a false failure about prefix allocation when what it
#: actually hit was a queue — the constant is environment-sensitive, so it is a knob
#: (`CLAUDE.md` seam 3).
CONCURRENCY = int(os.environ.get("HARNESS_PERF_CONCURRENCY", "32"))

#: HLD §8.4: about 1,500 of roughly 1,800 input tokens per scoring call are shared prefix.
#: `TC-JUDGE-21` uses the same figures.
EXPECTED_PREFIX_TOKENS = 1_500
EXPECTED_TOKENS_IN = 1_800

#: The threshold. A batch sharing an invariant prefix should report a hit rate near
#: 1500/1800 = 0.83; anything below this is the collapse RISK-23 describes. Deliberately well
#: under the expected value so a slow first call (the cache is cold) does not fail the case.
MIN_CACHE_HIT_RATE = 0.5

#: The stability half, and the one that actually names `NFR-PROV-02`. A *high* hit rate with a
#: *varying* `cached_prefix_tokens` is the signature of the client reallocating the prefix per
#: call: the server still matches some of it, but the number moves with client behaviour rather
#: than with prompt ordering. Stability is what makes the metric mean what §9.7 reads it as.
MAX_PREFIX_TOKEN_STDEV = 1.0


def _invariant_prefix() -> tuple[tuple[str, str], ...]:
    """The shared prefix of a scoring batch: everything before the submission.

    `FR-JUDGE-07` / `FR-EXTRACT-04` put the submission **last** precisely so that everything
    ahead of it is byte-identical across a batch. That ordering is the thing whose effect this
    case measures.
    """
    return (
        ("system", "You are scoring one criterion. Do not award numeric points."),
        ("rubric", "Bands: not met, partially met, met, exceeded." + " Guidance." * 200),
        ("criterion", "States that friction opposes motion."),
    )


def test_tc_prov_22_the_invariant_prefix_is_not_reallocated_across_a_concurrent_batch():
    """TC-PROV-22 — 32 concurrent calls sharing one prefix; `cached_prefix_tokens` is non-zero
    and stable across the batch.

    Oracle: metric threshold, per `PERF-04`. Two assertions, and the second is the requirement:

    1. `cache_hit_rate` is high — the prefix is being cached at all.
    2. `cached_prefix_tokens` is **stable** across the batch. A high but varying figure is what
       a client that rebuilds the prefix per call produces: the server matches part of it each
       time, and the metric then reflects this module's allocation behaviour rather than the
       caller's prompt ordering. `NFR-PROV-02` and `CT-PROV-12` both say the metric must mean
       the latter, because §9.7 reads it as an alert on prompt ordering.

    Concurrency is the caller's (`CT-PROV-01`), so the batch is dispatched from a caller-owned
    pool here — a provider that started its own would fail `TC-PROV-C01`, not this case.
    """
    from concurrent.futures import ThreadPoolExecutor

    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    LocalServerProvider, PromptPayload, SamplingParams = require(
        PROVIDER_MODULE,
        "LocalServerProvider",
        "PromptPayload",
        "SamplingParams",
        issue=ISSUE,
    )

    base_url = os.environ.get("LOCAL_INFERENCE_BASE_URL")
    if not base_url:
        pytest.fail(
            "TC-PROV-22 runs on E3 against a live local server; set "
            "LOCAL_INFERENCE_BASE_URL. Skipping would let a nightly tier report green "
            "without ever measuring the one signal RISK-23 has (test plan §4.6)."
        )

    provider = LocalServerProvider(base_url=base_url)
    model_ref = ModelRef(
        role="judge",
        provider="ollama",
        build_id=os.environ["HARNESS_PERF_BUILD_ID"],
        quantization=os.environ.get("HARNESS_PERF_QUANTIZATION", "q4"),
    )
    params = SamplingParams(temperature=0.0)
    prefix = _invariant_prefix()

    payloads = [
        PromptPayload(fields=prefix + (("submission", f"Answer number {index}."),))
        for index in range(CONCURRENCY)
    ]

    # One warm call first: the very first request populates the server's prefix cache, and
    # including it would measure the cold miss rather than the property under test.
    provider.complete(payloads[0], model_ref, params)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        completions = list(pool.map(lambda p: provider.complete(p, model_ref, params), payloads))

    cached = [c.cached_prefix_tokens for c in completions]
    hit_rates = [c.cached_prefix_tokens / c.tokens_in for c in completions if c.tokens_in]

    assert all(value > 0 for value in cached), (
        "cached_prefix_tokens is zero for at least one call in a batch that shares an "
        "invariant prefix: the prefix cache is not being hit at all. RISK-23 — five times the "
        "wall clock with no error raised."
    )
    assert statistics.mean(hit_rates) >= MIN_CACHE_HIT_RATE, (
        f"mean cache_hit_rate {statistics.mean(hit_rates):.3f} is below {MIN_CACHE_HIT_RATE} "
        f"against an expected {EXPECTED_PREFIX_TOKENS}/{EXPECTED_TOKENS_IN}. Per HLD §9.7 a "
        f"drop below the run's historical band is a build failure, not a note."
    )
    assert statistics.pstdev(cached) <= MAX_PREFIX_TOKEN_STDEV, (
        f"cached_prefix_tokens varies across the batch (stdev "
        f"{statistics.pstdev(cached):.2f}, values {sorted(set(cached))}). The prefix is "
        f"byte-identical across these calls, so a varying figure means the client is "
        f"reallocating it per call and the metric is reporting client behaviour rather than "
        f"prompt ordering — exactly what NFR-PROV-02 and CT-PROV-12 forbid."
    )
