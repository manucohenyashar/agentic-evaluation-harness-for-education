# PERF-01 — A full uniform-depth run fits the overnight window

| Field | Value |
|---|---|
| Perf ID | PERF-01 |
| NFR | NFR-ORCH-01, R10 |
| Load profile | A full uniform-depth run, continuous batching at the profile concurrency ceiling |
| Duration | To completion |
| Dataset | `F-SYNTH` 350 × 15 criteria (~23,000 units) |
| Metric | Wall clock |
| Threshold | Fits the overnight window with margin; ~1.7 h at uniform depth is the **hypothesis**, recorded not asserted |
| Env | E4 |

## What this measures

The wall clock of a full run with a uniform-depth panel, so every criterion gets the full panel
and no adaptive depth saves calls, while the serving stack batches at the profile's concurrency
ceiling. HLD §8.4's projection for this shape is about 1.7 hours. That figure is a hypothesis: this
run records the measured number beside it and does not pass or fail on it. The gate is the
overnight window, with margin.

## Setup

- **Machine.** The reference `unified-small` `edge-local` machine (E4), with no other workload.
  Record its model and memory.
- **Models.** The target panel builds at target quantization, resolved by build ID (`FR-CONF-03`).
  Record each resolved build.
- **Serving.** The target serving stack, with concurrency set to the profile ceiling. Record the
  ceiling.
- **Dataset.** `F-SYNTH` at full size: 350 submissions against the 15-criterion reference package,
  generated from the committed seed (`harness/corpora/synth.py`).
- **Panel depth.** Uniform: adaptive depth off, so the unit count is the ~23,000 of a full panel.
  Record the enumerated unit count from the run's cost estimate before dispatch.
- **Storage.** The machine's real disk, not a RAM disk.

## Procedure

1. Ingest the cohort and publish the package. Neither is timed here: ingestion is PERF-02.
2. Start the run from pre-flight (S6) and note the start time.
3. Leave the machine alone until the monitor (S7) reports the run complete. Do not wake, sleep or
   update it.
4. Read the run's `run_metrics`: `wall_clock_ms`, `total_units`, `peak_concurrency`,
   `cache_hit_rate`, `model_swap_count`, `model_swap_duration_ms`, `estimated_completion_s`.
5. Compare the wall clock with the overnight window the school uses. Record both, and the margin.

## Measurement record

| Record | Entry |
|---|---|
| Executed by |  |
| Date |  |
| Build |  |
| Machine |  |
| Resolved model builds |  |
| Concurrency ceiling |  |
| Enumerated units |  |
| Wall clock |  |
| Hypothesis (~1.7 h) against measured |  |
| Overnight window and margin |  |
| cache_hit_rate |  |
| Model swaps (count, total time) |  |
| Verdict |  |

**Verdict.** Pass when the run completes inside the overnight window with margin. The 1.7-hour
hypothesis is recorded beside the measurement and never decides the verdict. A run that fits the
window at three hours passes. A run that took 1.7 hours but did not complete fails.

## Why this is not in CI

E1 and E3 cannot produce this number (test plan §4.5). The concurrency ceiling, memory, thermals
and model residency are properties of the reference machine, and a CI run with the fixture provider
makes no model calls at all. The E1 cases that hold the orchestrator's share of this budget are
`TC-ORCH-30` (`PERF-03`, scheduling overhead) and `TC-ORCH-33` (`PERF-09`, the ledger at 40,000
units).
