# Performance scenarios

Test plan §6.4 defines ten performance scenarios. Every result names the environment it came from,
and a number from E1 or E3 is **not** evidence about E4, the reference `edge-local` hardware.

This folder holds the runbooks for scenarios that cannot run in CI: they need the reference
machine, target models at target quantization, and the real serving stack. Everything else is an
automated test. `tests/perf/test_perf_scenarios.py` is the index. For every scenario it checks that
the thresholds in code match §6.4, that each holder runs in the tier its environment allows, and
that each runbook here still matches its row.

| Scenario | Env | How it is held |
|---|---|---|
| PERF-01 — full uniform-depth run | E4 | [Runbook](PERF-01-overnight-run.md); the hypothesis is recorded, not asserted |
| PERF-02 — cohort-scale ingestion | E4 | [Runbook](PERF-02-cohort-ingestion.md); `TC-INGEST-47` checks the shape on E1, ungated |
| PERF-03 — scheduling overhead | E1 | `TC-ORCH-30` |
| PERF-04 — prefix cache under a concurrent batch | E3 | `TC-PROV-22`, `TC-JUDGE-21`, and `tests/perf/test_perf_04_prefix_cache_band.py` for the 10-minute band (all `live`) |
| PERF-05 — sustained write load | E1 | `TC-STORE-17` at CI duration; `tests/perf/test_perf_05_sustained_writes.py` at the 60 s reference duration |
| PERF-06 — zero-model stages in a full run | E1 | `tests/perf/test_perf_06_zero_model_stages_full_run.py`; module halves `TC-INTEG-11`, `TC-AGG-20`, `TC-DET-11` |
| PERF-07 — grading and rollup | E1 | `TC-GRADE-20` |
| PERF-08 — queue and rollup render | E1 | `TC-REVIEW-18` (queue build and render), `TC-CONSOLE-33` (queue and rollup over a real store) |
| PERF-09 — 40,000-unit ledger and footprint | E1 | `TC-ORCH-33` |

## Release-time runbooks (TS-54)

| Scenario | Env | How it is held |
|---|---|---|
| PERF-10 — the `NFR-SYS-05` acceptance gate | E4 | [Runbook](PERF-10-release-gate.md): the ten-row HLD §8.5 gate table, one mid-run kill |
| RES-17 — no network interface | E5 | [Runbook](RES-17-air-gapped-run.md): the E2E tier and a live local run with networking off at the host |
| RES-18 — restart after an uncontrolled kill | E1, then E4 | `tests/resilience/test_res_18_restart_rpo_rto.py` on E1; confirmed on E4 in PERF-10's step 5 |

`tests/perf/test_release_gate_runbooks.py` checks these three against test plan §6.4 and §6.8.

## Running an E4 runbook

1. Run on the reference machine only. A run anywhere else is recorded as *not executed*, and the
   number it produced is thrown away rather than reported, because reporting it invites someone to
   read it as E4 evidence.
2. Copy the runbook into the release's records folder and fill in the copy. The files here stay
   blank templates, and the index test fails if a measurement is committed in this folder.
3. Take the numbers from `run_metrics`, the harness's own instrumentation (HLD §8.5: "the
   acceptance test is largely a matter of reading instrumentation the harness produces anyway").
   Take them from a stopwatch only where the runbook says so.
