# PERF-10 — The NFR-SYS-05 acceptance gate

| Field | Value |
|---|---|
| Perf ID | PERF-10 |
| NFR | NFR-SYS-05 |
| Load profile | **The release gate.** Full-pipeline acceptance run: 350 representative submissions in the real medium, a mixed-format paper, the real OCR stage, target models at target quantization, the real serving stack at target concurrency, real storage, and one deliberate mid-run kill |
| Duration | Overnight |
| Dataset | Real consented corpus |
| Metric | The HLD §8.5 gate table in full: wall clock within the window with margin; peak memory under the profile ceiling; aggregate throughput within range of projection; high prefix cache hit rate; model swap time in minutes not per criterion; no sustained thermal throttling; OCR triage time within the teacher-minute budget; units fail but the run completes; resume correct after kill; disk growth within free space |
| Threshold | All ten sub-criteria met |
| Env | **E4 only** — the design states that a green CI pipeline is no evidence for this gate, and this plan repeats it |

## What this is

This is the gate before any `edge-local` deployment (`NFR-SYS-05`). It is one overnight run of the
whole pipeline on the reference machine, with the real corpus, the real models and the real serving
stack, and one deliberate kill in the middle. It passes only when all ten rows of the gate table
below pass. No CI result stands in for it, including a green `PERF-01`..`PERF-09`: those are E1 and
E3 numbers.

The run also confirms `RES-18` on E4. `tests/resilience/test_res_18_restart_rpo_rto.py` measures it
on E1, and the kill in step 5 is where it is confirmed here.

## Who takes part

- **Release engineer.** Prepares the machine, starts the run, performs the kill, reads the metrics.
  Signs off.
- **Operator.** Handles the OCR triage queue in step 7, timed. Their time is the teacher-minute
  budget's input.
- **Witness.** A second person who confirms the kill and the resume were performed as written.

## Setup

- **Machine.** The reference `unified-small` `edge-local` machine, nothing else running, on its real
  storage. Record the model, memory, and free disk space before the run.
- **Models and serving.** Target panel builds at target quantization, resolved by build ID
  (`FR-CONF-03`). The target serving stack at the profile's target concurrency. Record each resolved
  build and the concurrency.
- **Corpus.** 350 representative submissions from `F-HAND` (consented real student work, Tier C
  handling, test plan §4.4), including at least one mixed-format paper. If consent is not on file,
  the gate cannot be run and the release is not gated. Record that; do not substitute a synthetic
  corpus.
- **Profile ceiling.** The memory ceiling and the continuous-batching throughput projection for this
  hardware profile (HLD §8.4, §8.5). Write both down before starting: the gate compares against
  them.
- **Monitoring.** Memory, thermal state and disk usage sampled for the whole run, from the operating
  system's own tools, at an interval of 60 s or less.

## Procedure

1. Record free disk space, then start from an empty data directory. Publish the package.
2. Upload the 350 submissions and start ingestion, which runs through the real OCR stage. Note the
   start time: the wall clock is measured from ingestion through synthesis (HLD §8.5).
3. When ingestion completes, start the run from pre-flight (S6).
4. Let the run reach about half its units done on the monitor (S7). Note the done count.
5. **The kill.** Kill the harness process uncontrolled (`kill -9`, or end task in the OS process
   manager, not a graceful stop), and note the time. Restart it immediately, running the resume
   (`Orchestrator.resume()` with no arguments, then the lease sweeper, which reclaims the killed
   worker's leases), and note the time. Record:
   - **RTO:** time from restart to the first unit leased again. It must be 1 minute or less.
   - **RPO:** take the completions the worker logged (work ID and time), not the monitor's done
     count. The monitor reads the same ledger, so it cannot show work that never reached it. Every
     unit the worker logged as done more than 5 seconds before the kill must be `done` in the ledger
     after restart. Completed work lost must be no more than the last 5 seconds' worth
     (`NFR-SYS-02`).
6. Leave the run to finish overnight. Do not touch the machine.
7. The operator works the OCR triage queue (S8) with a stopwatch, and records items triaged and
   minutes spent. From the ingest report, record the OCR failure rate and, separately, the
   unresolved-mark rate for the mixed-format paper (HLD §8.5 asks for both).
8. When the run completes, read `run_metrics` and the monitoring logs, and fill in the gate table.
   Check the ledger for duplicated and lost units: every enumerated unit `done` or recorded failed,
   no `work_id` completed twice.

## The gate table

Each row is HLD §8.5's gate. The source column says where the number comes from.

| # | Gate | Pass when | Source | Measured | Pass/fail |
|---|---|---|---|---|---|
| 1 | Wall clock within the window with margin | Ingestion through synthesis finishes inside the overnight window, with margin recorded | Start time noted in step 2 to the time synthesis finished (not `run_metrics.wall_clock_ms`, which restarts with the process after the step-5 kill) |  |  |
| 2 | Peak memory under the profile ceiling | Peak of weights plus KV cache stays under the profile's ceiling at target concurrency | OS memory log; `run_metrics.peak_concurrency` |  |  |
| 3 | Aggregate throughput within range of projection | Units per hour are within range of the continuous-batching projection | `run_metrics.total_units` over wall clock, against the projection |  |  |
| 4 | High prefix cache hit rate | `cache_hit_rate` is high; a low rate means prompt ordering regressed | `run_metrics.cache_hit_rate` |  |  |
| 5 | Model swap time in minutes not per criterion | Total swap time is minutes for the run | `run_metrics.model_swap_count`, `model_swap_duration_ms` |  |  |
| 6 | No sustained thermal throttling | No sustained throttling over the full run | OS thermal log |  |  |
| 7 | OCR triage time within the teacher-minute budget | The operator's triage minutes fit the budget (R9), not just the failure rate | Step 7 stopwatch; ingest report `ocr_failure_rate` and `unresolved_mark_rate` |  |  |
| 8 | Units fail but the run completes | Any failed units are recorded and the run reaches complete | Run status; ledger failed units; `run_metrics.quarantined_units` |  |  |
| 9 | Resume correct after kill | RTO ≤ 1 minute, RPO ≤ 5 s of completed work, no duplicated and no lost units | Step 5 record; step 8 ledger check |  |  |
| 10 | Disk growth within free space | Disk growth leaves the device's free space with margin | Free space before (step 1) and after |  |  |

## Sign-off

| Record | Entry |
|---|---|
| Executed by |  |
| Witness |  |
| Date |  |
| Build |  |
| Machine |  |
| Resolved model builds |  |
| Corpus and consent reference |  |
| RTO (RES-18 on E4) |  |
| RPO (RES-18 on E4) |  |
| OCR failure rate / unresolved-mark rate |  |
| Verdict |  |

**Verdict.** Pass only when all ten rows pass. A gate row with no measurement is a fail, not a
pass. A run on any machine other than the reference machine is *not executed*.
