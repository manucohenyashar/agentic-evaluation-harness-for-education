# PERF-02 — Cohort ingestion takes the same order of magnitude as scoring

| Field | Value |
|---|---|
| Perf ID | PERF-02 |
| NFR | NFR-INGEST-01 |
| Load profile | Fully parallel ingestion at the concurrency ceiling |
| Duration | To completion |
| Dataset | 350 submissions × ~4 pages (~1,400 VLM calls) |
| Metric | Wall clock |
| Threshold | Same order of magnitude as the scoring pass; **measured, not estimated** |
| Env | E4 |

## What this measures

The wall clock to ingest a 350-submission cohort, about 1,400 transcription calls, with ingestion
fully parallel at the profile's concurrency ceiling. The threshold compares two measurements from
the same machine: ingestion against the scoring pass. Neither `NFR-INGEST-01` nor HLD §8.5 puts a
number on "same order of magnitude". **This runbook's reading**, pending the plan owner's
confirmation: ingestion takes at most ten times the scoring pass. There is no lower bound, because
the design's concern runs one way (ingestion must not dominate the night), and a fast ingestion is
not a failure. The scoring figure has to be
measured too: an estimate from HLD §8.4's projection does not count (`NFR-INGEST-01`: "measured
rather than estimated").

## Setup

- **Machine, models and serving.** As in PERF-01: the reference `unified-small` machine, the target
  transcription build at target quantization, and concurrency at the profile ceiling. Record all
  three.
- **Dataset.** 350 scanned submissions of about four pages each. Use the real medium where it is
  available (`F-HAND`, under Tier C handling). Otherwise use `F-SCAN`, the committed image-bearing
  corpus, and record which one was used. Transcription cost depends on the pixels, so a text-only
  corpus measures the wrong thing.
- **The scoring pass to compare against.** The scoring pass of a full run of the same cohort on the
  same machine: PERF-01's run if it used this cohort, otherwise a run started straight after this
  ingestion.

## Procedure

1. Start from an empty data directory with the package published.
2. Upload the cohort and start ingestion. Note the time the first page is dispatched.
3. When ingestion reports complete, note the time. Record the number of pages transcribed, the
   number of transcription calls, and the ingest statuses (ok, flagged, quarantined).
4. Run the scoring pass over the ingested cohort and read its wall clock from `run_metrics`
   (`wall_clock_ms`), excluding ingestion.
5. Compute the ratio of ingestion wall clock to scoring wall clock.

## Measurement record

| Record | Entry |
|---|---|
| Executed by |  |
| Date |  |
| Build |  |
| Machine |  |
| Transcription build and quantization |  |
| Concurrency ceiling |  |
| Corpus used |  |
| Pages transcribed / transcription calls |  |
| Ingestion wall clock |  |
| Scoring pass wall clock (measured) |  |
| Ratio, ingestion to scoring |  |
| Verdict |  |

**Verdict.** Pass when both wall clocks were measured on this machine in this session and the
ratio is at most 10. A scoring figure taken from an estimate, or from another machine, makes
the run *not executed* rather than a pass.

## Why this is not in CI

`TC-INGEST-47` runs the same cohort shape on E1 (350 submissions, four pages each, 1,400 scripted
transcription calls). It asserts the shape exactly and prints the wall clock, but gates nothing: a
scripted transcriber on a CI box measures the machine, not the reference hardware's VLM.
