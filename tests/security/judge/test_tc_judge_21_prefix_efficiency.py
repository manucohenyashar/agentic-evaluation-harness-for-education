"""The judge batch's invariant prefix is the shared-cache body its throughput assumes.

Case: `TC-JUDGE-21` (`NFR-JUDGE-01`, P1, **nightly**, Performance, rung 2, test plan
§5.10; the threshold is `PERF-04`, §6.4). Issue #84 (TS-32), paired with #81.

`NFR-JUDGE-01`: *"Roughly 1,500 of ~1,800 input tokens per call shall be shared prefix,
so that `cache_hit_rate` is high and the continuous-batching throughput assumption
holds."* One (judge, question, criterion) batch, 32 concurrent scoring calls — HLD §8.4's
reference concurrency, `PERF-04`'s load profile.

The prompt ordering that makes the prefix shared is `FR-JUDGE-07`'s: the submission
renders LAST inside the untrusted block, so every byte before the final field is
byte-identical across the batch (`FR-JUDGE-06`). The payloads below are the judge
template's REAL render — `prompt_fields` over hand-built whitelist requests that differ
only in their submission text — so a template change that moved per-submission material
into the prefix would break the precondition assertion before the server is even asked.

Environment: E3, a live local model server (Ollama or vLLM-MLX). Marked `live`, `slow`
and `integration`, so the fast tier never selects it and `pytest -q -m live` picks it up
nightly.

**This case has never been executed.** E3 does not exist in this repository —
`CLAUDE.md` states that all work runs locally and no model server is provisioned. It is
written now, against the shipped interface, so whoever stands E3 up inherits the
assertion rather than inventing one; the PR says so explicitly rather than letting a
`live`-marked test imply it was ever run.

Not marked `writtenahead`
--------------------------
The marker means *"excluded from `TEST_CMD` until its implementing issue closes"*, and
`writtenahead` tests are registered so the gate can announce when to unmark them.
Neither fits here: `live` already excludes this from the fast tier, and #81's landing
did **not** make the test runnable — it needs hardware, not code (the
`test_prefix_cache_stability.py` precedent, TC-PROV-22, verbatim).

Consequence worth stating: a bare `pytest -q` with no marker filter collects and runs
this file, so it appears in the full-suite failure count until E3 exists.
"""

from __future__ import annotations

import os
import statistics

import pytest

from tests.support.impl import JUDGE_MODULE, PROVIDER_MODULE, require

pytestmark = [pytest.mark.live, pytest.mark.slow, pytest.mark.integration]

CONF_MODULE = "aeh.conf"
ISSUE = "#81"

#: `PERF-04`'s load profile: *"32 concurrent scoring calls in one (judge, question,
#: criterion) batch"*. Env-gated because a box that cannot serve 32 concurrently would
#: report a false failure about prefix allocation when what it hit was a queue — the
#: constant is environment-sensitive, so it is a knob (`CLAUDE.md` seam 3).
CONCURRENCY = int(os.environ.get("HARNESS_PERF_CONCURRENCY", "32"))

#: HLD §8.4: about 1,500 of roughly 1,800 input tokens per scoring call are shared
#: prefix. The threshold below is deliberately well under the expected value so a slow
#: first call (the cache is cold) does not fail the case.
EXPECTED_PREFIX_TOKENS = 1_500
EXPECTED_TOKENS_IN = 1_800
MIN_CACHE_HIT_RATE = 0.5

#: The stability half: a high but varying `cached_prefix_tokens` is the signature of a
#: client reallocating the prefix per call — the metric then reports client behaviour
#: rather than prompt ordering (`NFR-PROV-02`'s twin requirement, same batch).
MAX_PREFIX_TOKEN_STDEV = 1.0


def _batch_payloads(count: int) -> list[Any]:
    """One (judge, question, criterion) batch, rendered by the REAL judge template:
    identical rubric bytes, one distinct submission per payload, the submission LAST."""
    from aeh.judge import (
        BandView,
        CriterionView,
        QuestionView,
        ScoringRequest,
        SubmissionView,
    )

    prompt_fields = require(JUDGE_MODULE, "prompt_fields", issue=ISSUE)
    bands = (
        BandView("emerging", 0, "the criterion is partly met"),
        BandView("secure", 1, "the criterion is met"),
    )
    # Filler rubric prose so the prefix has the magnitude NFR-JUDGE-01 assumes (~1,500
    # tokens of shared rubric and rules per call). Plain repeated prose: no numerals
    # beside mark vocabulary, so the prohibition's content scan would pass it too.
    filler = (
        " The marker weighs whether the reasoning names the opposing force, states "
        "its direction, and connects it to the observed equilibrium of the crate "
        "on the ramp, citing the relevant physical law in the candidate's own words."
    ) * 12
    criterion = CriterionView(
        criterion_id="C-01",
        text="States that friction opposes motion." + filler,
        bands=bands,
    )
    payloads = []
    for index in range(count):
        request = ScoringRequest(
            work_id=f"sha256:tc-judge-21-{index}",
            criterion=criterion,
            question=QuestionView(
                prompt_text="Explain why the crate does not slide.",
                reference_solution="Static friction balances the along-slope weight.",
            ),
            evidence=(),
            dependency_evidence=(),
            submission=SubmissionView(
                submission_id=f"SYN-{index:03d}", student_ref=f"ref-s{index:03d}"
            ),
            submission_text=(
                "The crate does not slide because static friction balances the "
                f"along-slope component of its weight (submission {index})."
                + " The ramp is at rest; no relative motion obtains. " * 40
            ),
        )
        payloads.append(prompt_fields(request))
    # The precondition the whole case rests on: every byte before the final field is
    # byte-identical across the batch (FR-JUDGE-06). If this fails, the metric below
    # measures a prompt that no longer shares its prefix.
    prefixes = {tuple(f[:-1]) for f in (p.fields for p in payloads)}
    assert len(prefixes) == 1, (
        "the judge batch's invariant prefix is NOT byte-identical across the batch — "
        "per-submission material reached a field before the submission (FR-JUDGE-06), "
        "so the cache_hit_rate below would measure prompt instability, not allocation"
    )
    return payloads


def test_tc_judge_21_the_judge_batch_shares_its_prefix_across_concurrent_calls():
    """TC-JUDGE-21 — 32 concurrent scoring calls in one batch; `cache_hit_rate` is
    consistent with ~1500/1800 shared prefix and `cached_prefix_tokens` is stable.

    Oracle: metric threshold, per `PERF-04`. Three assertions, and the last is RISK-23's
    whole detector:

    1. `cached_prefix_tokens` is non-zero — the prefix is being cached at all.
    2. `cache_hit_rate` is high — consistent with the design's 1500/1800 shared-prefix
       figure (`NFR-JUDGE-01`).
    3. `cached_prefix_tokens` is **stable** across the batch. A varying figure with the
       payloads byte-identical ahead of the submission means the client is reallocating
       the prefix per call — five times the wall clock with no error raised (RISK-23,
       rated High with detectability "only if the metric is watched").
    """
    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    LocalServerProvider, SamplingParams = require(
        PROVIDER_MODULE, "LocalServerProvider", "SamplingParams", issue=ISSUE
    )

    base_url = os.environ.get("LOCAL_INFERENCE_BASE_URL")
    if not base_url:
        pytest.fail(
            "TC-JUDGE-21 runs on E3 against a live local server; set "
            "LOCAL_INFERENCE_BASE_URL. Skipping would let a nightly tier report green "
            "without ever measuring the one signal RISK-23 has (test plan §4.6)."
        )

    from concurrent.futures import ThreadPoolExecutor

    provider = LocalServerProvider(base_url=base_url)
    model_ref = ModelRef(
        role="judge",
        provider="ollama",
        build_id=os.environ["HARNESS_PERF_BUILD_ID"],
        quantization=os.environ.get("HARNESS_PERF_QUANTIZATION", "q4"),
    )
    params = SamplingParams(temperature=0.0)  # judgment is a temperature-zero task
    payloads = _batch_payloads(CONCURRENCY)

    # One warm call first: the very first request populates the server's prefix cache,
    # and including it would measure the cold miss rather than the property under test.
    provider.complete(payloads[0], model_ref, params)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        completions = list(
            pool.map(lambda p: provider.complete(p, model_ref, params), payloads)
        )

    cached = [c.cached_prefix_tokens for c in completions]
    hit_rates = [
        c.cached_prefix_tokens / c.tokens_in for c in completions if c.tokens_in
    ]

    assert all(value > 0 for value in cached), (
        "cached_prefix_tokens is zero for at least one call in a batch that shares an "
        "invariant prefix: the prefix cache is not being hit at all. RISK-23 — five "
        "times the wall clock with no error raised."
    )
    assert statistics.mean(hit_rates) >= MIN_CACHE_HIT_RATE, (
        f"mean cache_hit_rate {statistics.mean(hit_rates):.3f} is below "
        f"{MIN_CACHE_HIT_RATE} against an expected "
        f"{EXPECTED_PREFIX_TOKENS}/{EXPECTED_TOKENS_IN}. Per HLD §9.7 a drop below the "
        f"run's historical band is a build failure, not a note (NFR-JUDGE-01)."
    )
    assert statistics.pstdev(cached) <= MAX_PREFIX_TOKEN_STDEV, (
        f"cached_prefix_tokens varies across the batch (stdev "
        f"{statistics.pstdev(cached):.2f}, values {sorted(set(cached))}). The payloads "
        f"are byte-identical ahead of the submission, so a varying figure means the "
        f"client is reallocating the prefix per call and the metric is reporting "
        f"client behaviour rather than prompt ordering (NFR-PROV-02, CT-PROV-12)."
    )
