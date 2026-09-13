"""`PERF-04` (issue #146, TS-53) — the prefix cache stays high and stable over ten minutes, and
never drops below the historical band.

Test plan §6.4: *"32 concurrent scoring calls in one (judge, question, criterion) batch | 10 min |
350 submissions | `cache_hit_rate`, `cached_prefix_tokens` | High and stable; a drop below the
run's historical band is a **build failure**, per HLD §9.7, not a note | E3"* (`NFR-JUDGE-01`,
`NFR-PROV-02`).

**What this adds over `TC-PROV-22` and `TC-JUDGE-21`.** Both send *one* 32-call batch and check an
absolute floor (a hit rate of at least 0.5) and that `cached_prefix_tokens` is stable inside the
batch. `PERF-04` names three things neither can see:

- **Duration.** Ten minutes of back-to-back batches across 350 submissions. Cache eviction, KV
  pressure and server-side reallocation show up over minutes, not in one batch.
- **Stability over time.** The per-batch hit rate must not drift. Every batch must stay within
  `STABILITY_DROP` of the run's median, and the batch-to-batch spread must stay under
  `STABILITY_STDEV`.
- **The historical band.** HLD §9.7 treats a drop below the run's historical band as a build
  failure with no error raised (RISK-23). The band has to come from this scenario's own history. A
  real run's `cache_hit_rate` covers different prompts and criteria, so comparing this probe to it
  would compare two workloads. Each run of this case therefore records its own rate, through the
  harness's `run_metrics` write (`Orchestrator.record_run_metrics`, `CT-ORCH-20`), under the metric
  `HISTORY_METRIC`. The history lives in the E3 box's data directory named by
  `HARNESS_PERF_HISTORY_DIR`, and an unset directory is a failure, the same policy as a missing
  server. The band's floor is the history's mean less three standard deviations, never below the
  absolute floor, so a noisy history cannot produce a band that never fires. Collapsed runs stay in
  the history, since a band that forgets them is flattered. With fewer than `MIN_HISTORY` earlier
  runs no band exists yet: the case says so in its report, asserts everything else, and records the
  run so the band builds up.

**Environment.** E3, a live local model server. Marked `live`, `slow` and `integration`, so the
fast tier never selects it. As with its siblings, a missing server is a failure, not a skip: a
nightly tier that skips the only detector RISK-23 has reports green without measuring anything
(test plan §4.6). **This case has never been executed.** No E3 server exists in this repository,
the same disclosure `TC-PROV-22` makes.

Knobs (seam rule 3): `HARNESS_PERF_04_SECONDS` (600), `HARNESS_PERF_CONCURRENCY` (32, shared with
the siblings), `HARNESS_PERF_HISTORY_DIR`. None of them moves a threshold.
"""

from __future__ import annotations

import os
import statistics
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.support.impl import PROVIDER_MODULE, require

pytestmark = [pytest.mark.live, pytest.mark.slow, pytest.mark.integration]

CONF_MODULE = "aeh.conf"
ISSUE = "#21"
ENVIRONMENT = "E3"

DURATION_S = int(os.environ.get("HARNESS_PERF_04_SECONDS", "600"))
CONCURRENCY = int(os.environ.get("HARNESS_PERF_CONCURRENCY", "32"))
#: `PERF-04`'s dataset: batches rotate through 350 submissions.
SUBMISSIONS = 350

#: "High": the siblings' absolute floor, so the three cases agree on what high means.
MIN_CACHE_HIT_RATE = 0.5
#: "Stable": no batch more than this far below the run's median hit rate...
STABILITY_DROP = 0.10
#: ...and a batch-to-batch spread under this.
STABILITY_STDEV = 0.05
#: Earlier runs needed before a historical band exists.
MIN_HISTORY = 3
BAND_SIGMAS = 3.0
#: The `run_metrics` name this scenario's own history is recorded under.
HISTORY_METRIC = "perf04_cache_hit_rate"


def _prefix() -> tuple[tuple[str, str], ...]:
    """Everything ahead of the submission in one (judge, question, criterion) batch.
    `FR-JUDGE-07` puts the submission last so this is byte-identical across the batch."""
    return (
        ("system", "You are scoring one criterion. Do not award numeric points."),
        ("rubric", "Bands: not met, partially met, met, exceeded." + " Guidance." * 200),
        ("criterion", "States that friction opposes motion."),
    )


def historical_band(history_dir: str | None) -> tuple[float | None, list[float]]:
    """The band's floor from this scenario's earlier runs (`run_metrics`, `HISTORY_METRIC`), and the
    history read. `None` when fewer than `MIN_HISTORY` runs are recorded. The floor is never below
    `MIN_CACHE_HIT_RATE`."""
    if not history_dir or not Path(history_dir).exists():
        return None, []
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ  # noqa: E401,F401
    import aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth  # noqa: E401,F401
    from aeh.store import open_store
    from tests.support.store_api import statement

    store = open_store(history_dir, read_only=True)
    try:
        rows = store.durable().query(statement(
            "SELECT value FROM run_metrics WHERE metric = :metric",
            issue="#146"), metric=HISTORY_METRIC)
    finally:
        store.close()
    history = [float(row[0]) for row in rows]
    if len(history) < MIN_HISTORY:
        return None, history
    floor = statistics.mean(history) - BAND_SIGMAS * statistics.pstdev(history)
    return max(floor, MIN_CACHE_HIT_RATE), history


def record_history(history_dir: str, run_rate: float) -> None:
    """Append this run's rate to the scenario's history, through the harness's metrics write."""
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ  # noqa: E401,F401
    import aeh.judge, aeh.pkg, aeh.review, aeh.synth  # noqa: E401,F401
    from aeh.orch import Orchestrator
    from aeh.store import open_store

    store = open_store(history_dir)
    try:
        Orchestrator(store).record_run_metrics(
            f"perf-04-{time.strftime('%Y%m%dT%H%M%S')}", {HISTORY_METRIC: run_rate})
    finally:
        store.close()


def test_perf_04_prefix_cache_is_high_stable_and_inside_its_historical_band_for_ten_minutes():
    """`PERF-04`: back-to-back 32-call batches for ten minutes. Every batch's hit rate is high,
    `cached_prefix_tokens` is stable within each batch, the per-batch rate does not drift, and the
    run's rate is not below the historical band."""
    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    LocalServerProvider, PromptPayload, SamplingParams = require(
        PROVIDER_MODULE, "LocalServerProvider", "PromptPayload", "SamplingParams", issue=ISSUE)

    base_url = os.environ.get("LOCAL_INFERENCE_BASE_URL")
    if not base_url or not os.environ.get("HARNESS_PERF_BUILD_ID"):
        pytest.fail(
            "PERF-04 runs on E3 against a live local server; set LOCAL_INFERENCE_BASE_URL and "
            "HARNESS_PERF_BUILD_ID. Skipping would let the nightly tier report green without "
            "measuring the one signal RISK-23 has (test plan §4.6)."
        )
    history_dir = os.environ.get("HARNESS_PERF_HISTORY_DIR")
    if not history_dir:
        pytest.fail(
            "PERF-04 compares the run against its historical band; set HARNESS_PERF_HISTORY_DIR "
            "to the E3 box's history directory. Without it the band is never checked, and the "
            "case would pass on a comparison that did not happen."
        )
    floor, history = historical_band(history_dir)

    provider = LocalServerProvider(base_url=base_url)
    model_ref = ModelRef(role="judge", provider="ollama",
                         build_id=os.environ["HARNESS_PERF_BUILD_ID"],
                         quantization=os.environ.get("HARNESS_PERF_QUANTIZATION", "q4"))
    params = SamplingParams(temperature=0.0)
    prefix = _prefix()

    def payload(index: int):
        return PromptPayload(
            fields=prefix + (("submission", f"Submission {index % SUBMISSIONS}: answer text."),))

    provider.complete(payload(0), model_ref, params)  # warm the cache; a cold miss is not the metric

    batch_rates: list[float] = []
    unstable_batches: list[tuple[int, list[int]]] = []
    tokens_in = cached_tokens = sent = 0
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        while time.perf_counter() - started < DURATION_S:
            batch = [payload(sent + offset) for offset in range(CONCURRENCY)]
            completions = list(pool.map(lambda p: provider.complete(p, model_ref, params), batch))
            sent += CONCURRENCY
            batch_in = sum(c.tokens_in for c in completions)
            batch_cached = sum(c.cached_prefix_tokens for c in completions)
            tokens_in += batch_in
            cached_tokens += batch_cached
            batch_rates.append(batch_cached / batch_in if batch_in else 0.0)
            prefixes = [c.cached_prefix_tokens for c in completions]
            if statistics.pstdev(prefixes) > 1.0:
                unstable_batches.append((len(batch_rates) - 1, sorted(set(prefixes))))
    elapsed = time.perf_counter() - started

    run_rate = cached_tokens / tokens_in if tokens_in else 0.0
    median = statistics.median(batch_rates) if batch_rates else 0.0
    report = (
        f"PERF-04 on {ENVIRONMENT} (not evidence about E4): {len(batch_rates)} batches of "
        f"{CONCURRENCY} over {elapsed:.0f}s; run cache_hit_rate {run_rate:.3f}; per-batch min "
        f"{min(batch_rates or [0]):.3f} median {median:.3f} stdev "
        f"{statistics.pstdev(batch_rates) if len(batch_rates) > 1 else 0:.3f}; historical band "
        f"floor {'not established' if floor is None else f'{floor:.3f}'} from {len(history)} "
        f"earlier run(s)"
    )
    print(report)
    record_history(history_dir, run_rate)

    assert elapsed >= DURATION_S and sent >= SUBMISSIONS, (
        f"fixture: the load did not run for {DURATION_S}s across {SUBMISSIONS} submissions. {report}"
    )
    problems = []
    low = [(i, r) for i, r in enumerate(batch_rates) if r < MIN_CACHE_HIT_RATE]
    if low:
        problems.append(f"{len(low)} batch(es) fell under the {MIN_CACHE_HIT_RATE} hit-rate floor, "
                        f"first at batch {low[0][0]} ({low[0][1]:.3f})")
    if unstable_batches:
        problems.append(f"cached_prefix_tokens varied within {len(unstable_batches)} batch(es), "
                        f"first {unstable_batches[0]}: the client is reallocating the prefix "
                        f"(NFR-PROV-02)")
    drifted = [(i, r) for i, r in enumerate(batch_rates) if r < median - STABILITY_DROP]
    if drifted or (len(batch_rates) > 1 and statistics.pstdev(batch_rates) > STABILITY_STDEV):
        problems.append(f"the hit rate was not stable over the run: {len(drifted)} batch(es) more "
                        f"than {STABILITY_DROP} under the median")
    if floor is not None and run_rate < floor:
        problems.append(f"the run's cache_hit_rate {run_rate:.3f} is below the historical band "
                        f"floor {floor:.3f}. Per HLD §9.7 that is a build failure, not a note: "
                        f"prefix ordering has regressed (RISK-23)")
    assert not problems, "\n".join(problems) + f"\n{report}"
