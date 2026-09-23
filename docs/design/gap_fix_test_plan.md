# Test Plan Delta: Closing the Design ↔ Implementation Gaps

**Source design (read in this order):**
1. `docs/design/detailed-design.md` v1.4 — the **base design**. Every module, requirement and clause it defines stands unless item 2 amends it.
2. `docs/design/fix_gaps_detailed_design_plan.md` v1.5.1-delta — the **delta**, applied on top of the base. It adds `M-PIPE`, appends `FR-*`/`NFR-*`/`CT-*` IDs to 14 modules, and amends a named set of base IDs (§2.2 table B).

**Base test plan:** `docs/design/test-plan.md` v1.2. This document is a **delta to that plan, not a replacement**. Every base section, case, corpus, environment and policy applies unless this document names it and says what changes.

**Version:** 1.3-delta  **Date:** 2026-09-14  **Status:** Draft
**Author:** `/create-test-plan`, delta mode, against the two design documents above
**Code baseline observed:** `src/aeh` and `tests/` at `origin/main` `e0ac5626`. The repository now has an implementation and a suite, which base plan §8.2's "neither `src/` nor `tests/` exists" paragraph predates.

---

## 1. Scope and the confidence claim

**In scope.**
- Every ID the delta **adds** — **60 requirements**:
  - `FR-PIPE-01…10`, `NFR-PIPE-01…03`;
  - `FR-ORCH-27…35`;
  - `FR-EXTRACT-11…13`, `FR-JUDGE-18…21`, `FR-INTEG-09…12`;
  - `FR-AGG-15…17`, `FR-DET-11`, `FR-GRADE-18`;
  - `FR-REVIEW-18…22`, `FR-STATS-20…24`, `FR-CALIB-15`;
  - `FR-INGEST-36/37`, `FR-PKG-22`, `FR-SETUP-17`;
  - `FR-CONSOLE-33…39`, `NFR-CONSOLE-08`, `FR-STORE-15`;
  - `FR-CONF-13…16`: switching harness profiles by environment variable (delta §3.15, added in design 1.5.1).
- Every clause the delta adds (**39 `CT-*` clauses**), and the **10 `Requires` rows** it adds.
- Every base ID the delta **amends** (§2.2 table B). The amended text replaces the base text, and the base case that verified it is re-specified here.
- **Reconciliation** of every existing base case the delta touches (§5.0). For each one this plan says whether it stays, is re-specified, is expected to turn green, or loses its `writtenahead` marker when the implementing story closes.

**Out of scope, deliberately.**
- **Untouched base cases.** Cases for requirements the delta does not touch are not restated; `test-plan.md` stays their home.
- **Issues and test code.** Issues belong to `/plan-to-issues`, test code to `/write-tests`.
- **The CT-CONFORM-14 statistic.** Design decision D-2 keeps the gate `UNAVAILABLE` until a statistic is ratified (design Q-D5). `TC-CONFORM-C14` already asserts exactly that and **stays unchanged** (§5.0). No case is invented for an undeclared threshold.
- **Documentation-only design items:** ADR-18 (adopt shipped schema names), D-4 (record the α/entropy/rounding conventions) and DOC-1. They change prose, not behaviour. Their one observable consequence, the F-SCHEMA goldens, is covered by `TC-STORE-04`'s re-specification.

**Confidence claim.**

> If every case in this delta passes, **together with the base plan**, we have evidence that the
> harness **runs as one pipeline**:
> - A cohort goes from enumerated units to stored evidence, verdicts, run-scoped `criterion_score`
>   rows and grades through the real stage doors, with no hand-written aggregation walk standing in
>   for the composition.
> - A crash at any hook boundary resumes to the same stored result.
> - A provider outage pauses the run rather than quarantining good work.
> - Scores from two runs of one cohort never contaminate each other's grades, review queue or console.
> - Every console action on a real store either performs its §11.8 effect or says it did not.
>
> On the contract side:
> - Each of the 39 new clauses has a case that goes red when the promise breaks.
> - The 12 safety-shaped clauses also have a named adversarial construction.
> - The two **breaking** changes (CT-AGG v2.0, CT-ORCH-26) are re-verified against every consumer in their Consumers columns.
>
> We do **not** have evidence of three things:
> - That the composed pipeline meets NFR-SYS-05's overnight budget on reference hardware. PERF-10,
>   run manually on E4, remains the only evidence.
> - That the Phase 2/3 items (FR-STATS-21, FR-CALIB-15, the D-3 amendment) work before their phase.
> - That FR-REVIEW-18's ranking inputs actually save teacher time. Those inputs are designed
>   defaults (design Q-D4), measured but not gated.
>
> §7.3 lists the rest.

---

## 2. System under test (delta)

### 2.1 Module inventory and testability (delta)

| Module ID | Change under test | Interfaces (delta) | Depends on (delta) | Testable in isolation? | Notes |
|---|---|---|---|---|---|
| **M-PIPE** (new) | Run composition, recovery, `python -m aeh` | `run_to_completion`, `recover`, `main`, `ProductionStageExecutor`, `StageTrace`, `RunResult`, `RecoveryReport` | every stage module, M-CONF | **No, by construction.** It composes real modules. Its unit layer is thin: argument parsing, exit-code mapping, trace shaping. Its value is at rung 3. | A rung-0 M-PIPE test would test a mock of the pipeline. `RecordedFixtureProvider` keeps rung 3 runnable on E1. |
| M-ORCH | Executor seam, `GovernedProvider`, `cell_phase`, `ready_cells`, taxonomy pauses, `validate_grade_policy`, `evaluate_alerts`, metrics, run-scoped escalation key | `StageExecutor`, `StageOutcome`, `GovernedProvider`, `mark_cell_phase`, `ready_cells`, `validate_grade_policy`, `evaluate_alerts` | + M-PIPE as consumer | Yes, with a real store. `evaluate_alerts` is pure (rung 0). | `TransportStageExecutor` is a new double (§4.9) |
| M-EXTRACT / M-JUDGE | Taxonomy errors are not strikes; `verdicts_for`; persisted latency and assessment; metrics | `extraction_metrics`, `verdicts_for` | — | Yes (rung 1–2, stub provider raising the taxonomy) | Changes the strike arithmetic behind base TC-EXTRACT-08 and TC-PROV-18 |
| M-INTEG | `StoreExtractionView`; `verify` idempotency; document cache; indexes | `StoreExtractionView(handle, catalog, package_version_id)` | + M-EXTRACT (read) | Yes, real store | `LedgerEvidenceView` (`tests/support/e2e_world.py`) becomes a double held to CT-INTEG-17 |
| M-AGG | `write_score`; run-scoped `criterion_score` rebuild; `aggregation_signals` | `write_score(tx, run_id, submission_id, score, signals)`, `aggregation_signals(handle, run_id)` | — | Yes; `aggregate` stays pure | **CT-AGG v2.0, breaking** |
| M-DET, M-GRADE | Run-scoped writes and reads | unchanged signatures | — | Yes, real store | Two-run fixtures are the whole technique |
| M-REVIEW | Stored ranking inputs; `scoring_model_for`; `review_queue` and `label` columns; `cohort_id` fix; knob rename | `ReviewService.scoring_model_for` | + M-PKG (read) | Yes, real store | |
| M-STATS | `judge_signals`, MVVP measurement drivers, strict admissibility predicate, JSONL export, override history | `judge_signals`, `measure_position_bias`, `measure_self_agreement`, `criterion_override_history` | — | Yes | FR-STATS-21 is Phase 2 |
| M-CALIB | Persisted dual-scored roster | `register_dual_scored_roster` | — | Yes, real durable tier | Phase 3 |
| M-INGEST | Per-kind cluster resolution; selection biconditional trigger | `resolve_cluster` (changed semantics) | — | Yes | |
| M-PKG / M-SETUP | `criterion.evaluation_mode` | column + `SCORING_MODELS` | — | Yes | Regenerates the TC-REG-02 baseline |
| M-CONSOLE | Real HTTP server; wired actions; service-backed screens; env-resolved profile; no swallowed read errors; too-few qualifier; current revision | HTTP routes, `ConsoleReadError`, `TOO_FEW_QUALIFIER` | + M-SETUP, M-REVIEW, M-GRADE, M-PIPE | Rung 2–3 over a real socket; rung 4 in the browser | Turns base TC-CONSOLE-05/33/34/37/40/41 green |
| M-STORE / packaging | `pyproject.toml` build system, script, extra, package data | `pip install .`, `aeh` script | — | Rung 0 (static) + rung 4 (clean venv) | |

**Testability finding, stated as a design observation.** `M-PIPE` is correctly untestable in isolation. As a result, its per-requirement cases (§5.1) and its clause cases (§6.11.1) run at the **same rung, against the same implementation**. What separates them is the question each answers (§4.9), not the level. That is unusual for this plan, so it is recorded here rather than disguised.

### 2.2 Requirements inventory (delta)

**Table A — requirements added by the delta (60).**

| Module | IDs | Phase (design §4.5 step) |
|---|---|---|
| M-PIPE | FR-PIPE-01, FR-PIPE-02, FR-PIPE-03, FR-PIPE-04, FR-PIPE-05, FR-PIPE-06, FR-PIPE-07, FR-PIPE-08, FR-PIPE-09, FR-PIPE-10, NFR-PIPE-01, NFR-PIPE-02, NFR-PIPE-03 | 1 (step 4) |
| M-ORCH | FR-ORCH-27, FR-ORCH-28, FR-ORCH-29, FR-ORCH-30, FR-ORCH-31, FR-ORCH-32, FR-ORCH-33, FR-ORCH-34, FR-ORCH-35 | 1 (steps 1, 2, 3, 6) |
| M-EXTRACT | FR-EXTRACT-11, FR-EXTRACT-12, FR-EXTRACT-13 | 1 |
| M-JUDGE | FR-JUDGE-18, FR-JUDGE-19, FR-JUDGE-20, FR-JUDGE-21 | 1 |
| M-INTEG | FR-INTEG-09, FR-INTEG-10, FR-INTEG-11, FR-INTEG-12 | 1 |
| M-AGG | FR-AGG-15, FR-AGG-16, FR-AGG-17 | 1 |
| M-DET | FR-DET-11 | 1 |
| M-GRADE | FR-GRADE-18 | 1 |
| M-REVIEW | FR-REVIEW-18, FR-REVIEW-19, FR-REVIEW-20, FR-REVIEW-21, FR-REVIEW-22 | 1 (FR-REVIEW-21's `assignment_type` consumer is Phase 2) |
| M-STATS | FR-STATS-20, FR-STATS-21, FR-STATS-22, FR-STATS-23, FR-STATS-24 | 1, except **FR-STATS-21: Phase 2** |
| M-CALIB | FR-CALIB-15 | **3** |
| M-INGEST | FR-INGEST-36, FR-INGEST-37 | 1 |
| M-PKG / M-SETUP | FR-PKG-22, FR-SETUP-17 | 1 |
| M-CONSOLE | FR-CONSOLE-33, FR-CONSOLE-34, FR-CONSOLE-35, FR-CONSOLE-36, FR-CONSOLE-37, FR-CONSOLE-38, FR-CONSOLE-39, NFR-CONSOLE-08 | 1 (FR-CONSOLE-34's paraphrase action: 3.5) |
| M-STORE | FR-STORE-15 | 1 |
| M-CONF | FR-CONF-13, FR-CONF-14, FR-CONF-15, FR-CONF-16 | 1 (landing step 1) |

`FR-STATS-24` comes from design decision D-5 rather than a §3 table row. It is listed here so it is not lost.

**Table B — base IDs the delta amends.** The amended text is authoritative. Each base case listed is re-specified in §5.0.

| Base ID | Amended by | What changes | Base case(s) re-specified |
|---|---|---|---|
| FR-AGG-13 | delta §3.5 | Stored integrity inputs are all six signals (adds `described_evidence`, `extractor_disagreement`) | TC-AGG-C15 residual closes → TC-AGG-24 |
| CT-ORCH-08 | CT-ORCH-26 | Escalation key becomes `(run_id, submission_id, criterion_id)`; the two-element form is deprecated | TC-ORCH-C08, TC-REQ-17, TC-REQ-40 |
| FR-REVIEW-02, NFR-REVIEW-05 | D-1 | Blind reserve = `min(REVIEW_BLIND_RESERVE_MINUTES, budget_minutes)`; floor of one shown item | TC-REVIEW-C01 → TC-REVIEW-30 |
| CT-CONFORM-14 | D-2 | Statistic and threshold undeclared; gate stays `UNAVAILABLE` | TC-CONFORM-C14 **unchanged** |
| FR-INGEST-26 | D-3 | Proposals list every matching lineage; semantic signal per candidate | TC-INGEST-39 → TC-INGEST-52 (later phase) |
| NFR-STATS-03 | FR-STATS-23 / ADR-19 | Export is JSON Lines, not Parquet/DuckDB | TC-STATS-30 |
| NFR-INTEG-01 | delta §3.4 | Acceptance form is gate time **excluding test-double reads** | PERF-06 |
| FR-PROV-07 strike consequence | CT-EXTRACT-16, CT-JUDGE-19 | Rate limit, outage and build change consume no strike | TC-EXTRACT-08, TC-PROV-18 |

### 2.3 Contract inventory (delta)

| Module | Contract | Ver | New clauses | Consumed by (added) | Clause suite |
|---|---|---|---|---|---|
| M-PIPE | CT-PIPE | 1.0 (new, provisional) | 7 | M-CONSOLE, operator | §6.11.1 |
| M-ORCH | CT-ORCH | 1.1 (**CT-ORCH-26 breaking**) | 7 | M-PIPE | §6.11.2 |
| M-EXTRACT | CT-EXTRACT | 1.1 (**behaviour change**) | 2 | M-PIPE | §6.11.3 |
| M-JUDGE | CT-JUDGE | 1.1 (**behaviour change**) | 2 | M-PIPE | §6.11.3 |
| M-INTEG | CT-INTEG | 1.1 | 3 | M-PIPE | §6.11.4 |
| M-AGG | CT-AGG | **2.0 (CT-AGG-20 breaking)** | 4 | M-PIPE | §6.11.5 |
| M-DET | CT-DET | 1.1 | 1 | — | §6.11.6 |
| M-GRADE | CT-GRADE | 1.1 | 1 | M-PIPE | §6.11.6 |
| M-REVIEW | CT-REVIEW | 1.1 | 3 | — | §6.11.7 |
| M-STATS | CT-STATS | 1.1 | 2 | — | §6.11.7 |
| M-CALIB | CT-CALIB | 1.1 | 1 | — | §6.11.8 |
| M-INGEST | CT-INGEST | 1.1 | 1 | — | §6.11.8 |
| M-PKG | CT-PKG | 1.1 | 1 | — | §6.11.8 |
| M-CONSOLE | CT-CONSOLE | 1.1 | 4 | — | §6.11.9 |
| M-CONF | CT-CONF | 1.1 | 2 | M-PIPE, M-CONSOLE | §6.11.10 |

**Clauses (39).** **S** marks the 12 safety-shaped clauses, which get an adversarial construction in §6.11, in block form or an expanded table row. **NP** marks the one non-promise.

| Clause | Kind | Promise (short) | Consumers | Flag |
|---|---|---|---|---|
| CT-PIPE-01 | surface | `run_to_completion`, `recover`, `main` exist; `python -m aeh` dispatches to `main` | M-CONSOLE, operator | |
| CT-PIPE-02 | behaviour | After `complete`: every admitted judged pair has one run-scoped score or a quarantined unit; every admitted submission has a current grade | M-GRADE, M-REVIEW, M-CONSOLE | |
| CT-PIPE-03 | behaviour | `run_to_completion` on a complete run writes nothing and returns the same status | operator | |
| CT-PIPE-04 | error | An outage or build change leaves the run `paused`, the reason names the error class, and nothing is quarantined by it | M-CONSOLE | |
| CT-PIPE-05 | state | `M-PIPE` executes no SQL | M-STORE, SEC-15 | **S** |
| CT-PIPE-06 | security | `M-PIPE` makes no model call itself | M-PROV | **S** |
| CT-PIPE-07 | behaviour | Post-processing order of ready cells within a pass is **not promised** | all | **NP** |
| CT-ORCH-22 | surface | With an executor bound, `extract`/`score` units reach `done` only through the worker (or `complete()` after deterministic `evaluate`) | M-PIPE | |
| CT-ORCH-23 | observe | `GovernedProvider.complete` accrues tokens, cost and build for every call, struck calls included | M-STATS, ops | |
| CT-ORCH-24 | state | `cell_phase` is written only by `mark_cell_phase`, idempotently | M-PIPE | |
| CT-ORCH-25 | error | `create_run` raises `PackageIntegrityError` naming every missing criterion, and writes no row | M-CONSOLE, M-PIPE | |
| CT-ORCH-26 | behaviour | The escalation key is run-scoped (amends CT-ORCH-08) | M-AGG, M-PIPE, M-INTEG | breaking |
| CT-ORCH-27 | observe | `ProgressReport.alerts` carries exactly the five named alerts | M-CONSOLE S7, ops | |
| CT-ORCH-28 | error | An outage or build change in dispatch leaves the run `paused`, the unit `pending` with `attempts` unchanged, and `progress()` returns | M-PIPE, M-CONSOLE | |
| CT-EXTRACT-16 | error | Taxonomy errors propagate from `process` with no evidence, no `fail()` and no attempt increment | M-ORCH, M-PIPE | **S** |
| CT-EXTRACT-17 | observe | `extraction_metrics` names are contract | M-STATS, ops | |
| CT-JUDGE-19 | error | Same as CT-EXTRACT-16, for `dispatch` | M-ORCH, M-PIPE | **S** |
| CT-JUDGE-20 | data | `verdicts_for` returns only the named run's cell verdicts, ordered by `work_id` | M-PIPE, M-AGG | |
| CT-INTEG-16 | behaviour | `verify` twice on unchanged inputs ≡ `verify` once | M-PIPE | |
| CT-INTEG-17 | surface | `StoreExtractionView` implements exactly the five reads; faults raise, never substitute | M-PIPE, test doubles | |
| CT-INTEG-18 | perf | Median `verify` ≤ 5 ms per cell (4 pages, ≤ 20 spans, E1) — amended 2026-09-23; was 2 ms, measured 2.87-3.10 ms | ops, PERF-06 | |
| CT-AGG-18 | state | M-AGG is the sole writer of judged score rows, M-DET of deterministic ones; M-SYNTH writes none | M-GRADE, M-REVIEW, M-STATS, M-CONSOLE | **S** |
| CT-AGG-19 | behaviour | `write_score` is idempotent on its key and uses only the caller's transaction; a raise rolls back the whole transaction | M-PIPE, M-ORCH | |
| CT-AGG-20 | data | Every score row names its run; no consumer reads scores without a run filter | all readers | **S**, breaking |
| CT-AGG-21 | observe | `aggregation_signals` names are contract | M-STATS, ops | |
| CT-DET-15 | state | Deterministic evaluation of run B never modifies run A's rows | M-GRADE, M-CONSOLE S12 | **S** |
| CT-GRADE-20 | behaviour | `compute_all(A)` is unchanged after run B's scores land | M-PIPE, M-CONSOLE | |
| CT-REVIEW-21 | behaviour | The store-form queue ranks larger `band_spread` first at equal cost | M-CONSOLE | |
| CT-REVIEW-22 | behaviour | At equal EV, holistic ranks above atomic in the store form | M-AGG (C09), M-CONSOLE | |
| CT-REVIEW-23 | data | `label.cohort_id` is a cohort id | M-STORE purge, M-STATS | |
| CT-STATS-22 | observe | `judge_signals` field names = `JUDGE_SIGNAL_FIELDS`; the alert name is contract | ops, M-CONSOLE | |
| CT-STATS-23 | behaviour | A NULL or absent `saw_system_output` never contributes to agreement | M-CONSOLE, M-PKG | **S** |
| CT-CALIB-17 | state | A registered roster survives restart, and `non_inferiority` gives an equal result | operator, M-CONSOLE | |
| CT-INGEST-21 | data | No path stores a resolved selection mark with a NULL selection; `IngestError` at the boundary | M-DET | **S** |
| CT-PKG-19 | data | `evaluation_mode` is non-null and in the two-value domain on every version, child and import | M-ORCH, M-DET, M-GRADE, M-STATS | |
| CT-CONSOLE-25 | surface | `GET /` returns 200 html; the stylesheet returns 200; unknown routes return 404 | browser, operator | |
| CT-CONSOLE-26 | state | Every Phase-1 action on a real store either causes its effect and reports `dispatched=True`, or reports `dispatched=False` with the refusal; never success over a swallowed exception | operator, M-ORCH, M-GRADE, M-REVIEW, M-SETUP | **S** |
| CT-CONSOLE-27 | security | With `HARNESS_PROFILE=cloud-hosted` in the environment, no socket is bound, whatever `cfg` says | operator | **S** |
| CT-CONSOLE-28 | error | A schema-level read failure renders a visible unreadable section, never a zero | teacher, operator | **S** |
| CT-CONF-15 | behaviour | The environment beats `cfg` and the file for every key it carries; `HARNESS_PROFILE` alone selects the profile's file section | M-PIPE, M-CONSOLE, operator | |
| CT-CONF-16 | behaviour | A profile switch never rebinds an existing run; the mismatched resumed run stays paused with both values named | M-ORCH, M-PIPE, M-CONSOLE | |

**`Requires` rows added by the delta.**

| Consumer | Provider | Clauses relied on | Verified by |
|---|---|---|---|
| M-PIPE | M-ORCH | CT-ORCH-03, CT-ORCH-22, CT-ORCH-23, CT-ORCH-24, CT-ORCH-25, CT-ORCH-26 | TC-REQ-90 |
| M-PIPE | M-EXTRACT | CT-EXTRACT-16 | TC-REQ-91 |
| M-PIPE | M-JUDGE | CT-JUDGE-19, CT-JUDGE-20 | TC-REQ-92 |
| M-PIPE | M-INTEG | CT-INTEG-16, CT-INTEG-17 | TC-REQ-93 |
| M-PIPE | M-AGG | CT-AGG-01, CT-AGG-18, CT-AGG-19 | TC-REQ-94 |
| M-PIPE | M-GRADE | CT-GRADE-14, CT-GRADE-20 | TC-REQ-95 |
| M-PIPE | M-SYNTH | CT-SYNTH-05 | TC-REQ-96 |
| M-CONSOLE | M-REVIEW | CT-REVIEW-04, CT-REVIEW-21, CT-REVIEW-22 | TC-REQ-97 |
| M-CONSOLE | M-SETUP | the CT-SETUP steps clauses (`steps()` enumerates blocking and optional steps) | TC-REQ-98 |
| M-CONSOLE | M-PIPE | CT-PIPE-01, CT-PIPE-04 | TC-REQ-99 |
| M-CONSOLE | M-CONF | CT-CONF-05 | TC-REQ-100 |

The delta's M-EXTRACT/M-JUDGE row is a single design row naming two providers. It is split in two because a pairwise case has exactly one provider, so the table has 11 cases for 10 design rows.

**Dependency edges with no clause behind them.** Walking delta §4.1's graph against the Requires tables finds three edges that no row covers:
- `M-PIPE → M-DET`: FR-PIPE-02 calls `DeterministicEvaluator.evaluate`.
- `M-PIPE → M-CONF`: FR-PIPE-08 resolves config through `environment_snapshot`.
- `M-REVIEW → M-PKG`: FR-REVIEW-18 reads `scoring_model`, weights and `distance_to_nearest_boundary`.

These are design findings (Q-24). Pairwise cases are still specified for them (TC-REQ-101, TC-REQ-102, TC-REQ-103), citing the base clauses the usage actually relies on, so the reliance is verified before any row names it.

### 2.4 Testability gaps and open questions

Numbering continues from base plan Q-13. Each question is addressed to the design author; the last column says how this plan handles it until then.

| ID | Requirement / area | Problem | Needed to make it testable | Plan's handling until answered |
|---|---|---|---|---|
| Q-14 | FR-PIPE-01/08, `HARNESS_PIPE_MAX_PASSES`, `HARNESS_PIPE_PASS_SLEEP_MS` | No `M-PIPE` error type is declared. Delta §1.1 says an invalid knob "raises the module error", but M-PIPE has no module error. | A named error, and whether the CLI maps it to exit 1 | TC-PIPE-14 asserts only that the error is raised before any row is written and that `main` exits 1; the type is not asserted |
| Q-15 | FR-CONSOLE-36 vs CT-CONSOLE-27 | **Resolved in design 1.5.1** by the user's decision: profiles switch by environment variable, and the environment takes precedence over `cfg` (delta §3.15). Original finding: **contradiction.** FR-CONSOLE-36's merge order `{**env, **CONSOLE_*, **(cfg or {})}` lets `cfg` override `HARNESS_PROFILE`, but CT-CONSOLE-27 binds no socket under a `cloud-hosted` environment "whatever `cfg` says". Both cannot hold when `cfg={"HARNESS_PROFILE": "local"}`. | Either the refusal reads the environment value before the merge, or the clause is narrowed | **The plan tests the clause**, because it is a safety property and must fail closed. TC-CONSOLE-C27 and SEC-16 include the cfg-overrides variant, which will be red against a literal reading of FR-CONSOLE-36. That red result opens a design conversation; it is not a test to relax (§4.9). |
| Q-16 | FR-REVIEW-22 migration | "Existing rows are rewritten … where resolvable" does not say what happens to rows that **cannot** be resolved | Keep them with NULL, keep the run id and flag them, or fail the migration | TC-REVIEW-29 asserts resolvable rows; its unresolvable variant is pending |
| Q-17 | FR-STATS-21 | `measure_self_agreement(…, runs=3)` requires "≥ 3" replications, but neither the behaviour nor the error type for `runs < 3` is specified | An error type or a clamp rule | TC-STATS-28's `runs=2` variant expects a raise, without asserting its type |
| Q-18 | FR-INTEG-11 | Content-hash re-verification "once per cached entry" means bytes swapped on disk after caching are **not** re-detected within one `IntegrityGate` instance. The design does not say whether that is acceptable. | Either a statement that the blob store is immutable within a run (then the window is accepted) or a re-verification rule | TC-INTEG-17 asserts the single read; §7.3 records the in-instance tamper window |
| Q-19 | CT-INTEG-18 | The perf clause is set on "E1", but E1 is any developer laptop or CI runner, not fixed hardware | A reference E1 runner spec, or a restatement as a ratio against a calibration loop | PERF-12 is a gated threshold on the CI runner only, with the machine recorded; it is informational elsewhere |
| Q-20 | FR-STATS-23 | The "documented schema" for the export is not given | The JSONL record schema | TC-STATS-30 asserts that the export is read-only, one file per administration, and self-consistent. The schema golden is authored once the design answers. |
| Q-21 | Delta §3.14: `validation_record.expected_mean/_sd/_histogram`, `document_region.question_id` | Two schema additions with behaviour but **no requirement ID** | IDs, or folding into FR-STATS-09 / FR-INGEST-10 text | TC-PKG-32 traces to FR-AGG-08 (the behaviour the baseline feeds); TC-INGEST-53 is cross-cutting |
| Q-22 | FR-CONSOLE-34, "set review window" | The door is described but not named, unlike every other row of the action map | The function name | TC-CONSOLE-44 asserts the effect (the stored `review_window_hours`), not a call |
| Q-23 | FR-PIPE-06 | The requirement says to "record both in the trace", but `StageTrace` has no failure field besides `quarantined` and `detail` | Where a synthesis failure is counted | TC-PIPE-06 asserts that `detail` names the failed submission and that `grades_computed` is unaffected |
| Q-25 | FR-CONSOLE-37 | The HTTP status of a page containing an unreadable view is unspecified (200 with the visible section, or 5xx) | A declared status | TC-CONSOLE-47 and TC-CONSOLE-C28 assert the visible section and the absence of a zero, not the status |
| Q-24 | Delta §4.1 graph | Edges `M-PIPE→M-DET`, `M-PIPE→M-CONF` and `M-REVIEW→M-PKG` have no `Requires` row | Rows citing the CT-DET, CT-CONF-05 and CT-PKG clauses | TC-REQ-101…103 verify the reliance against base clauses |

---

## 3. Risk register and depth allocation (delta)

Base §3's depth mapping (Critical / High / Medium / Low) applies unchanged. Risk IDs continue from RISK-40, and the `Clause` column follows base §3.1.

| Risk ID | Module / Req | Clause | Failure, stated concretely | Blast radius | Reversible? | Detectable in prod? | Severity | Depth assigned |
|---|---|---|---|---|---|---|---|---|
| RISK-41 | M-PIPE / M-ORCH — FR-PIPE-02, FR-ORCH-27 | CT-ORCH-22, CT-PIPE-02 | A unit is marked `done` without its evidence or verdict row: the executor seam reports success although the worker raised after the call. Downstream, the cell either aggregates over two verdicts that look like a legitimate panel, or its extraction reads as "student wrote nothing". | Every cell touched; grades built on missing work | No, once graded | **No** — the ledger says done | **Critical** | TC-PIPE-02, TC-ORCH-38, TC-ORCH-C22, TC-PIPE-C02, FUZZ-08, TC-E2E-02 re-based, TC-REQ-90 |
| RISK-42 | M-AGG / M-GRADE / M-REVIEW / M-CONSOLE — FR-AGG-16, FR-GRADE-18 | CT-AGG-20, CT-GRADE-20, CT-DET-15 | A cohort is re-run (after a key correction, or a second run after a pause). Run B's `criterion_score` rows overwrite or mix with run A's. A student's run-A grade silently changes to run B's band, or the rollup counts both. | Every student in a re-run cohort | Partly — while Tier C survives | **No** | **Critical** | TC-AGG-22, TC-DET-15, TC-GRADE-25, TC-AGG-C20, TC-DET-C15, TC-GRADE-C20, ADV-13, TC-REQ-95 |
| RISK-43 | M-AGG — FR-AGG-16 migration | CT-AGG-20 | The `criterion_score` rebuild loses rows, attributes rows to the wrong run in a multi-run store, or drops the `judge_count` CHECK so an even panel becomes storable | Every stored score in an upgraded installation | **No** — the old table is dropped | No | **Critical** | TC-AGG-22 (five variants), TC-STORE-04 re-specified, RES-21 |
| RISK-44 | M-EXTRACT / M-JUDGE — FR-EXTRACT-11, FR-JUDGE-19 | CT-EXTRACT-16, CT-JUDGE-19 | A 20-minute provider outage at 02:00 counts three strikes against every in-flight unit. Hundreds of valid units quarantine, and the morning shows a cohort full of "could not be scored" instead of a paused run. | A whole run | Yes — re-run | **Partly** — quarantines are visible, their cause is not | **High** | TC-EXTRACT-16, TC-JUDGE-26, TC-ORCH-43, TC-EXTRACT-C16, TC-JUDGE-C19, TC-ORCH-C28, RES-20 |
| RISK-45 | M-INTEG — FR-INTEG-10 | CT-INTEG-16 | M-PIPE calls `verify` post-extraction and again post-panel. The second call bumps the gate's own pending unit again, so an insufficiency route that should retry once quarantines after the first pass. | Every insufficient cell | Yes | No | **High** | TC-INTEG-16, TC-INTEG-C16, FUZZ-08, TC-REQ-93 |
| RISK-46 | M-ORCH — FR-ORCH-30 | CT-ORCH-22 | The `integrity_pre` gate is applied with no executor bound, so no score unit is ever claimable on the report-only and `transport=` paths. Base orchestrator suites go quietly empty rather than red, because "nothing leased" is a legal result. | The base M-ORCH suite; any report-only deployment | Yes | **No** in tests that assert on leased units only | **High** | TC-ORCH-42 (both arms), base M-ORCH regression set |
| RISK-47 | M-CONSOLE — FR-CONSOLE-34 | CT-CONSOLE-26 | The teacher clicks "finalize batch" and the page says done, but `finalize_batch` raised inside a suppressed block. Grades stay provisional, and the teacher sends them home as final. | A class's grades | Partly | **No** — the UI said success | **Critical** | TC-CONSOLE-44 (15-row sweep), TC-CONSOLE-C26, ADV-14, base TC-CONSOLE-02/39 over a real store |
| RISK-48 | M-CONSOLE — FR-CONSOLE-35/37 | CT-CONSOLE-28 | A screen queries a table that does not exist, swallows `OperationalError` and renders "0 items to review". The teacher reviews nothing and trusts a queue that was never read. | Review for a whole run | Yes | **No** — zero is a legal count | **High** | TC-CONSOLE-45, TC-CONSOLE-47, TC-CONSOLE-C28, TC-REQ-97 |
| RISK-49 | M-CONSOLE — FR-CONSOLE-36 | CT-CONSOLE-27 | `HARNESS_PROFILE=cloud-hosted` is set in the environment, but the console reads only `cfg`, so it binds a socket on a hosted machine and serves student records | Every student on that installation | **No** — disclosure | Partly | **High** | TC-CONSOLE-46, TC-CONSOLE-C27, SEC-16, base TC-CONSOLE-05 |
| RISK-50 | M-INGEST — FR-INGEST-36/37 | CT-INGEST-21 | An operator resolves an ambiguous tick, and the region becomes `resolved` with `selection = NULL`. M-DET scores the question as unanswered, so the student loses the mark for a scanner ambiguity the operator had fixed. This is RISK-03's shape, through a new door. | One student per resolution | No, once delivered | **No** | **Critical** | TC-INGEST-50, TC-INGEST-51, TC-INGEST-C21, FUZZ-09 |
| RISK-51 | M-STATS — FR-STATS-22 | CT-STATS-23 | A label whose `saw_system_output` was never recorded is admitted as blind, so operational labels enter κ and inflate it. This is RISK-07's shape. | Every validity figure for the package, at every importing school | **No** | **No** | **Critical** | TC-STATS-29, TC-STATS-C23, base TC-STATS-01 variant un-marked |
| RISK-52 | M-REVIEW — FR-REVIEW-18/19 | CT-REVIEW-21, CT-REVIEW-22 | The store-form queue ranks with every EV input at its default (`scoring_model="atomic"`, spread 0). Holistic and high-spread criteria sink below trivial ones within the teacher's limited minutes. | Review value for every run | Yes | No — the queue still looks ranked | **Medium** | TC-REVIEW-25, TC-REVIEW-26, TC-REVIEW-C21, TC-REVIEW-C22 |
| RISK-53 | M-ORCH — FR-ORCH-31 | CT-ORCH-25 | A grade policy references a deleted criterion; the run spends the night and then fails at grading | One night's run | Yes | Yes, in the morning | **Medium** | TC-ORCH-44, TC-ORCH-C25 |
| RISK-54 | M-ORCH / M-STATS / M-EXTRACT / M-AGG — FR-ORCH-32/33, FR-EXTRACT-12, FR-AGG-17, FR-STATS-20 | CT-ORCH-27, CT-EXTRACT-17, CT-AGG-21, CT-STATS-22 | Alerts or metrics are missing or misnamed. The cost ceiling is approached with no warning, and wall clock after a restart is measured from a fresh monotonic clock, so it under-reports. | Operations | Yes | Partly | **Medium** | TC-ORCH-45, TC-ORCH-46, TC-EXTRACT-17, TC-AGG-23, TC-STATS-27, OBS-12, OBS-13 |
| RISK-55 | M-PIPE — NFR-PIPE-01, FR-PIPE-07 | CT-PIPE-03 | A kill between `write_score` and `mark_cell_phase` makes recovery aggregate the cell again and enqueue a second escalation. Or `recover` fails to regrade a run whose review window lapsed while the machine was off, so its grades stay provisional forever. | A run | Yes | Partly | **High** | TC-PIPE-11 (kill at every hook boundary), TC-PIPE-07, TC-PIPE-C03, RES-19 |
| RISK-56 | M-INTEG — FR-INTEG-11/12 | CT-INTEG-18 | The document cache returns another submission's bytes (a `content_hash` key collision across runs), or the index goes unused and PERF-06 stays above its budget when measured at a small cohort (the scale trap, 2026-09-23) | Integrity verdicts for one cohort / the release gate | Yes | No for the first, yes for the second | **High** (collision) / Low (perf) | TC-INTEG-17, TC-INTEG-18, PERF-06, PERF-12 |
| RISK-57 | M-PKG / M-ORCH — FR-PKG-22, FR-ORCH-35 | CT-PKG-19 | A revision child or imported package loses `evaluation_mode` and defaults to `judged`, so MCQ items go to judges: extra cost, and a judged score where the key is deterministic | Every run on that package version | Yes | No | **High** | TC-PKG-31, TC-ORCH-48, TC-PKG-C19, TC-REG-02 regenerated |
| RISK-58 | Packaging — FR-STORE-15, NFR-PIPE-03 | — | `pip install .` omits `console_assets` or the `aeh` script. The installed console renders unstyled, or the command does not exist. | One installation | Yes | **Yes** | **Low** | TC-PIPE-12, TC-SMOKE-12, TC-STORE-26 — smoke-level, deliberately |
| RISK-59 | M-STATS / M-CALIB — FR-STATS-21, FR-CALIB-15 | CT-CALIB-17 | The Phase 2/3 measurement drivers are wrong | Future phases | Yes | — | **Low now** | One case each, scheduled with their phase |

---

## 4. Test strategy (delta)

**Applies unchanged from the base plan:**
- §4.1 levels and suite shape;
- §4.3 oracles;
- §4.5 environments (E1–E6);
- §4.6 determinism and flake policy (`FrozenClock`, seeded randomness, no sleeps except the base plan's single sanctioned one);
- §4.7 tooling (pytest markers, hypothesis, Playwright);
- §4.8 entry and exit criteria.

Only the differences are stated below.

### 4.1 Suite shape for the delta

The delta is **orchestration-heavy**: 23 of its 60 requirements are composition, wiring or run-scoping, and their defects are visible only where real modules meet. So the suite has a fat integration middle.

| Level | Share of delta cases | Why |
|---|---|---|
| Unit / rung 0–1 | ~25% | `evaluate_alerts`, the `ready_cells` decision table, the admissibility predicate, exit-code mapping, the qualifier, `pyproject` static checks |
| Integration with a real store and real modules (rung 2–3) | ~55% | M-PIPE, run-scoping, console on a real store, migrations, idempotency |
| E2E / browser (rung 4) | ~5% | TC-E2E-02 re-based, TC-E2E-04 (CLI, air-gapped); base browser cases turn green |
| Perf / resilience / security / adversarial / fuzz | ~15% | PERF-11…13, RES-19…21, SEC-16…18, ADV-13/14, FUZZ-08/09 |

### 4.2 Mock vs real policy (delta rows)

Base §4.2's one rule stands: doubles only at the model boundary, and elsewhere only for failure injection.

| Dependency | Doubled as | Used in | Companion real test | Contract test |
|---|---|---|---|---|
| Stage execution inside the dispatch pass | `TransportStageExecutor` (call-counting, test-only) | Base governor suites TC-ORCH-24, TC-ORCH-33, TC-ORCH-35 | TC-ORCH-39: the same ceiling assertion with `ProductionStageExecutor` over `RecordedFixtureProvider` | TC-ORCH-C23, run against both executors |
| Integrity extraction view | `LedgerEvidenceView` (`tests/support/e2e_world.py`) | Existing integrity and e2e suites, until migrated | TC-PIPE-10: differential against `StoreExtractionView` on one store | TC-INTEG-C17, run against both |
| Judged score writer | `grade_vocabulary.write_criterion_scores` and the `e2e_world` aggregation walk | Base grade, review and console suites that seed scores | TC-AGG-21, TC-PIPE-C02 | **Retired, not conformed.** A helper that writes `criterion_score` directly violates CT-AGG-18 by construction, so it cannot be held to the suite. Seeding helpers must call `aggregate` + `write_score`. TC-AGG-C18's census fails while any such helper remains. |
| Provider failures (outage, build change, 429) | Stub provider raising the taxonomy (F-TAXONOMY) | TC-EXTRACT-16, TC-JUDGE-26, TC-ORCH-43, RES-20 | Base plan's live-OpenRouter nightly case for FR-PROV-07 (real 429s) | Base CT-PROV suite |
| Console store | The storeless audit double (`_grade_ledger`, `_review_windows`, `_gate_outcomes`) | Base storeless console suites | TC-CONSOLE-44 (real store) | **Exempt** from CT-CONSOLE-26, which applies only to a real store (§4.9) |
| Process kill | Injected `SystemExit` at named hook boundaries (rung 3); a real `subprocess` kill (RES-19) | TC-PIPE-11 | RES-19, base RES-18 | — |

### 4.3 Oracles specific to the delta

- **Uninterrupted-run differential.** NFR-PIPE-01 and CT-PIPE-03 compare stored rows after kill + `recover` + `run_to_completion` against an uninterrupted run over the same fixtures.
  - Tables compared: `evidence`, `verdict`, `criterion_score`, `submission_grade`, `review_queue`.
  - Wall-clock columns (`recorded_at`, `acted_at`, `shown_at`, `latency_ms`) are projected out, and rows are ordered by primary key.
  - Equality is exact.
- **Two-run isolation.** Seed run A and snapshot its projected rows. Run B over the **same cohort** with different fixture bands. Assert A's snapshot is byte-identical. This is the only oracle that catches a missing `run_id` filter, because a single-run fixture passes with or without the filter.
- **Statement census.** CT-PIPE-05 and CT-AGG-18 need two checks together:
  - the SEC-15 `KNOWN_EXECUTE_SITES` census, which is static and misses a dynamic `getattr` call;
  - the `tests/support/store_spy.py` write audit, which is dynamic and misses paths no test exercises.
- **Query plan.** FR-INTEG-12 is asserted with `EXPLAIN QUERY PLAN` naming the index, not with timing.

### 4.4 Test data (delta)

| Corpus / fixture | Contents | Where used |
|---|---|---|
| **F-DEV-PIPE** | Drawn from F-DEV's generator: 3 submissions × 1 question × 3 criteria (2 judged, 1 MCQ-deterministic), with `F-RECORDED` responses for every extraction, panel call and narrative. One criterion's recorded panel bands are `(2,4,4)`, so `should_escalate` fires; the escalation calls are recorded too. | All M-PIPE cases, TC-SMOKE-12, TC-E2E-04 |
| **F-DEV-PIPE-TWO-RUN** | F-DEV-PIPE plus a second recorded response set whose bands differ on every judged criterion (`(1,1,1)` → `(3,3,3)`) | Every two-run isolation case |
| **F-SCHEMA additions** | Four databases: <br>• Cohort DB at version 19 with `criterion_score` rows and **one** run; <br>• Cohort DB at version 19 with **two** runs and rows; <br>• Cohort DB at version 19 with two runs and **no** rows; <br>• Package DB at version 10 with one `mcq` and one `open` criterion. <br>Plus one Durable DB at version 8 whose `label.cohort_id` values hold run ids. | TC-AGG-22, TC-PKG-31, TC-REVIEW-29, TC-STORE-04 |
| **F-TAXONOMY** | A scripted stub provider: call *n* raises `RateLimitedError(retry_after=0)`, `ProviderUnavailableError`, `BuildChangedError` or `ProviderError("500")`, or returns unparseable JSON, per a list | TC-EXTRACT-16, TC-JUDGE-26, TC-ORCH-43, RES-20 |

### 4.7 Tooling and execution (delta)

The marker scheme is unchanged. Two suites are added:

| Suite | Command | Runs in | Budget |
|---|---|---|---|
| Composition (M-PIPE, rung 3) | `pytest -q -m integration tests/integration/pipe tests/contract/pipe` | every push | < 3 min |
| Clean install | `pytest -q -m slow tests/smoke/test_smoke_install.py -k aeh_entrypoint` | nightly | < 5 min |

`TEST_CMD` stays `./scripts/test.sh` (`not integration and not live and not slow and not writtenahead`). Every delta case written ahead of its implementation carries `@pytest.mark.writtenahead` and a `WRITTEN_AHEAD_BLOCKERS` entry (§8.2).

### 4.9 Contract-verification policy (delta)

Base §4.10 applies in full:
- The **provider** owns its clause suite.
- Every double runs its provider's suite.
- Each `Requires` row becomes a rung-2+ pairwise case.
- The blast-radius rule selects suites from the Consumers columns.

**A red clause suite, and the declared-breaking carve-out.** Base §4.10's rule stands: a red clause case means the change is breaking or the clause is wrong, and it does **not** mean update the test. There is exactly one sanctioned route to changing an existing clause case: **the design records the clause as amended and bumps the contract version.** The delta does that for three clauses and no others.

| Amended clause | Contract version | Existing cases whose assertions change | Obligation |
|---|---|---|---|
| CT-ORCH-08's key → CT-ORCH-26 | CT-ORCH 1.1 | TC-ORCH-C08 (key shape), TC-REQ-17, TC-REQ-40 | Re-verify the M-AGG, M-PIPE and M-INTEG consumers (§6.12) |
| Unscoped `criterion_score` reads → CT-AGG-20 | CT-AGG 2.0 | Every CT-AGG-C case, and every M-GRADE, M-REVIEW, M-STATS or M-CONSOLE case, that seeds or reads `criterion_score` without `run_id` | Re-verify M-GRADE, M-REVIEW, M-STATS, M-CONSOLE, M-INTEG |
| Strike semantics → CT-EXTRACT-16 / CT-JUDGE-19 | CT-EXTRACT 1.1, CT-JUDGE 1.1 | TC-EXTRACT-08 (variant added); TC-PROV-18 (expected counters **re-derived by hand** from the new rule, not patched to match the new output) | Re-verify M-ORCH, M-PIPE |

Any other base clause case that goes red while the delta lands is **an implementation defect**, not a test to update.

**Double conformance for the delta's doubles.**

| Double | Stands in for | Clauses it cannot reproduce | Consequence, stated |
|---|---|---|---|
| `TransportStageExecutor` | `ProductionStageExecutor`, via `StageExecutor` | CT-ORCH-22's "done only through the worker's transaction" (it has no worker) | Governor suites using it prove counting and ceilings, never payload-before-done. TC-ORCH-38 and TC-PIPE-02 are the only cover for that. |
| `LedgerEvidenceView` | `StoreExtractionView` | None expected: it must pass TC-INTEG-C17 unchanged, including raising on a faulted read | A double that cannot raise on a faulted read hides CT-INTEG-01's fail-closed path in every integrity e2e case built on it. TC-INTEG-C17 then fails the double, not the suite. |
| Storeless console audit double | M-CONSOLE on a real store | All of CT-CONSOLE-26 | Storeless suites prove rendering and surface only; action effects are proven only by TC-CONSOLE-44 and TC-CONSOLE-C26 at rung 3 |

**Blast-radius rows** are in §6.12. `python -m harness.blast_radius` does not exist yet (base TS-82; `WRITTEN_AHEAD_BLOCKERS["#155 harness.blast_radius"]`). Until it does, §6.12 is the manual selection list a PR author runs.

---

## 5. Test cases

Numbering continues each module's sequence from the **higher** of the base plan's maximum and the maximum found in `tests/` at `e0ac5626`. The two agree for every module the delta touches: the only higher-looking IDs in `tests/` are a deliberately invented review-case literal inside a UAT meta-test and an adversarial ID in stale `.pyc` files, neither of which is an allocation. Rungs follow base §4.2: **0** pure / doubles · **1** in-memory fakes · **2** real dependency · **3** real neighbours · **4** full system. Priorities: **P0** release-gating · **P1** must pass before the phase ships · **P2** should pass.

### 5.0 Reconciliation of existing base cases

Walked from delta §5's "existing cases affected" column and checked against `tests/`. *Action* is one of:
- **unchanged** — the case stands as written;
- **re-specified** — the assertion changes, under §4.9's carve-out or an amended requirement;
- **re-based** — same assertion, over the real composition instead of a stand-in;
- **turns green** — no spec change; the implementation closes the gap;
- **un-mark** — remove `writtenahead` and the `WRITTEN_AHEAD_BLOCKERS` entry when the implementing story closes.

| Base case | Today (e0ac5626) | Delta driver | Action | Re-specification |
|---|---|---|---|---|
| TC-E2E-01 | Green, over stand-ins where scoring is involved | FR-PIPE-01 | re-based | Any scoring step runs through `run_to_completion`; the `e2e_world` aggregation walk is not called |
| TC-E2E-02 | Green over `tests/support/e2e_world.py:976-1180`'s hand-written aggregation walk | FR-PIPE-01…07, CT-PIPE-02 | **re-based** | The overnight run is `recover` + `run_to_completion` over F-SYNTH with `RecordedFixtureProvider`. Its assertions are unchanged, and one is added: CT-PIPE-02's invariant query returns zero violations. The kill variants use `recover`. The walk is deleted, not kept as a fallback. |
| TC-E2E-03 | Green over seeded scores | FR-AGG-15, CT-AGG-20 | re-based | Morning state is produced by TC-E2E-02's composed run, not seeded |
| TC-SMOKE-09 | Green over the transport seam | FR-PIPE-01 | re-based | "Enumerates, executes and completes" means `run_to_completion` returns `complete` and every done unit has its payload row |
| TC-SMOKE-10 | Green over seeded scores | FR-PIPE-06 | re-based | Grades come from the same composed run |
| TC-REQ-17 | Green, two-element key | CT-ORCH-26 | **re-specified** | The escalation key is `(run_id, submission_id, criterion_id)`. The induced-failure atomicity assertion stays. |
| TC-REQ-26 | Green over a seeded score | FR-AGG-15 | re-based | The score row is written by `write_score` inside the same transaction as the signals |
| TC-REQ-40 | Green, two-element key | CT-ORCH-26 | **re-specified** | As TC-REQ-17 |
| TC-REQ-50 | Green, `kind='mcq'` convention | FR-PKG-22, FR-ORCH-35 | **re-specified** | The separation is driven by `criterion.evaluation_mode`. Metamorphic check: a criterion with `kind='mcq'` and `evaluation_mode='judged'` rolls up as judged. |
| TC-REQ-77 | Green, with a recorded finding (the console queries a nonexistent `review_queue` shape) | FR-CONSOLE-35 | re-based | The console's S9 header figures come from `build_queue`; the blind-flow unreachability assertion is unchanged |
| TC-ORCH-C08 | Green, two-element key | CT-ORCH-26 | **re-specified** (§4.9) | Assert the three-element key. The deprecated two-element form resolves only when exactly one open run holds the pair, and raises `WorkLedgerError` otherwise. |
| TC-ORCH-24, TC-ORCH-33 | Green via `transport=` | FR-ORCH-27 | unchanged | They keep `TransportStageExecutor`; TC-ORCH-39 is their companion |
| TC-ORCH-35 | Green for the metrics shipped so far | FR-ORCH-33 | **re-specified** | The metric list gains `estimated_cost`, `cost_currency`, `retention_setting`, `resolved_builds` (JSON list) and `wall_clock_ms` with the paused-interval rule of TC-ORCH-46 |
| TC-ORCH-36 (alert rules) | `writtenahead` (`#66 TS-25 alert rules`) | FR-ORCH-32 | **un-mark** | None; TC-ORCH-45 adds the boundary table |
| TC-EXTRACT-08 | Green: three failures quarantine, no empty evidence row | FR-EXTRACT-11 | **re-specified** (§4.9) | Assertion kept. Variant added: three `RateLimitedError`s followed by one success produce **one** evidence row, `attempts = 0`, no quarantine. |
| TC-PROV-18 | Green; counters hand-counted under "every provider error strikes" | CT-EXTRACT-16 | **re-specified** (§4.9) | Hand-count again under the new rule: a 429 increments `rate_limited_calls` and `transport_retries` but not unit `attempts`. The expected values are recomputed from the programme of 200 calls **before** running the new code, and committed with the derivation in the test docstring. |
| TC-EXTRACT-C14 (metrics) | `writtenahead` (`#68 extraction contract metrics (TS-65)`) | FR-EXTRACT-12 | **un-mark** | None |
| TC-JUDGE-C16 (signal dimensionality) | `writtenahead` (`#148 judge_signals`) | FR-STATS-20 | **un-mark** | None |
| TC-AGG-C09 rung-3 half | `writtenahead` (`#96 c09 holistic ranks higher at rung 3`) | FR-REVIEW-18/19 | **un-mark** | None |
| TC-AGG-C15 | Green, with a disclosed per-cap residual (four stored flags) | FR-AGG-13 amended | re-specified | The residual note is removed; TC-AGG-24 asserts all six flags are stored |
| TC-GRADE-C15, run-start half | `writtenahead` (`#107 c15 … refused at run start`) | FR-ORCH-31 | **un-mark** | None |
| TC-STATS-01, null-flag variant | `writtenahead` (`#119 null saw_system_output`) | FR-STATS-22 | **un-mark** | None. Attribute-less label fixtures are updated in the same story to carry `saw_system_output=0` explicitly (delta §6 check 12). |
| TC-STATS-04, row 7 (too-few qualifier) | `writtenahead` (`#119 too-few headline qualifier`) | FR-CONSOLE-38 | **un-mark** | None |
| TC-REVIEW-C01 | Green under D-1's shipped behaviour | D-1 | re-specified | Its 5-minute arm asserts the D-1 rule. TC-REVIEW-30 carries the full boundary table. |
| TC-CONFORM-C14 | Green: asserts the gate is `UNAVAILABLE` | D-2 | **unchanged** | D-2 keeps the gate unavailable; no statistic is asserted |
| TC-INGEST-39 | Green; one lineage, ordering not exercised | D-3 | unchanged now | TC-INGEST-52 supersedes it when D-3 lands (design landing step 7) |
| TC-STORE-04 | Green against F-SCHEMA up to the current pins | FR-AGG-16, FR-PKG-22, FR-REVIEW-20/21, FR-EXTRACT-13, FR-JUDGE-20, FR-ORCH-28, FR-INTEG-12, FR-INGEST-37, §3.14 | **re-specified** | F-SCHEMA gains the §4.4 databases; post-migration checksum goldens are regenerated **only** with the pin bump named in the same PR |
| TC-REG-02 | Green | FR-PKG-22 | re-specified | The archive baseline is regenerated on its declared ground (schema-version bump); the diff must show only `evaluation_mode` additions |
| TC-REG-06 | Green | ADR-15 (hooks, not ledger stages) | **unchanged, and asserted unchanged** | The delta deliberately adds no stage to `work_id` inputs. A `work_id` diff while the delta lands is a defect. |
| TC-CONSOLE-05 | **Red** on `land-stacked-130-146-147` | FR-CONSOLE-36 | turns green | None |
| TC-CONSOLE-33 | **Red** on that branch (the screen reads a nonexistent table) | FR-CONSOLE-35/37 | turns green | None |
| TC-CONSOLE-34, TC-CONSOLE-37, TC-CONSOLE-40, TC-CONSOLE-41 | **Red** on that branch (no real server) | FR-CONSOLE-33 | turn green | None |
| TC-CONSOLE-02, TC-CONSOLE-39, TC-CONSOLE-C02, TC-CONSOLE-C03 | Green over the storeless double | FR-CONSOLE-34 | re-based | Each action sweep runs over a real store as well as the double (§4.9) |
| PERF-06 | **Red** on that branch: integrity 2.25% against 1% | FR-INTEG-11/12, NFR-INTEG-01 amended | re-specified, turns green | Measured as gate time excluding test-double reads, **on a full-scale run**; threshold stands at < 1% — measured 0.7516% there (2026-09-23). A small-cohort drive reads ~3.3% for the same per-call cost and is not evidence against it |
| RES-18 | Green over the seam | FR-PIPE-07 | re-based | The restart is `python -m aeh recover` in a fresh process |

The seven cases red on `land-stacked-130-146-147` (PERF-06, TC-CONSOLE-05, TC-CONSOLE-33, TC-CONSOLE-34, TC-CONSOLE-37, TC-CONSOLE-40, TC-CONSOLE-41) are **all** closed by delta implementation work: the console server and environment work that TS-90 tests, the console screens that TS-91 tests, and the integrity performance work that TS-86 tests. None of them needs a specification change.

### 5.1 Module: Run Composition & Process Entry (`M-PIPE`)

All M-PIPE cases use F-DEV-PIPE, a real temp data dir with all eleven migration contributors imported, `RecordedFixtureProvider` and `FrozenClock`, unless stated otherwise.

#### TC-PIPE-01 — `run_to_completion` drives a run to `complete` and reports every stage

| Field | Value |
|---|---|
| Requirements | FR-PIPE-01 |
| Risk | RISK-41 (Critical) |
| Level / type | Integration |
| Technique | State transition (`created → running → complete`; `→ paused`) |
| Isolation | Rung 3 |
| Priority | P0 |

**Preconditions:** run created and started for F-DEV-PIPE (3 submissions × 3 criteria).

**Steps:** call `run_to_completion(store, run_id, provider=fixture, run_config=cfg)`.

**Oracle:** exact values against the stored `run` row, plus a trace invariant.

**Expected result:**
- `RunResult.status == "complete"`, and equals `SELECT status FROM run`.
- `pause_reason is None`.
- `stages` contains exactly one entry per stage executed, in order of first execution: `extract`, `integrity_pre`, `deterministic`, `score`, `aggregate`, `synthesize`, `grade`.
- For `extract`: `units = 6`, `done = 6`, `quarantined = 0`.
- Every entry's `detail` is non-empty (seam 4).
- `grades_computed = 3`.

**Variants:**
- A run already `paused` by operator request → returns `status="paused"`, and nothing is written (row counts of all five §4.3 tables unchanged).
- `max_passes=1` → returns the stored non-terminal status. The trace covers only that pass, so there is no `grade` entry.
- A run id that does not exist → raises before any write; `main` exits 1 (Q-14).

**Automatable:** yes — `tests/integration/pipe/test_run_to_completion.py`

#### TC-PIPE-02 — No unit is `done` without its payload row

| Field | Value |
|---|---|
| Requirements | FR-PIPE-02 |
| Risk | RISK-41 (Critical) |
| Level / type | Integration, negative |
| Technique | Error guessing plus an invariant query |
| Isolation | Rung 3; fault injection at the worker boundary |
| Priority | P0 |

**Preconditions:** F-DEV-PIPE. A wrapping provider raises `RuntimeError("after-call")` **after** the recorded response is returned, on the second score call for submission `S2`, criterion `C1`.

**Steps:** `run_to_completion`, then run the invariant queries.
- For each stage `(extract → evidence, score → verdict, deterministic → criterion_score)`: count `done` units with no payload row for the same `(run, submission, criterion[, judge])`.

**Oracle:** invariant; all three counts are zero.

**Expected result:**
- The faulted unit is not `done`. It is either `pending` with `attempts = 1`, or quarantined after the strike ladder.
- The run completes with CT-PIPE-02 satisfied: the pair holds a quarantined unit.

**Variants:**
- Fault on an extract unit.
- Fault inside `DeterministicEvaluator.evaluate` → no `complete()` call, unit not done.
- No faults → invariant still zero.

**Automatable:** yes — `tests/integration/pipe/test_payload_before_done.py`

#### TC-PIPE-03 — `integrity_pre` runs exactly once, when a cell's extraction is terminal

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-PIPE-03 | FR-PIPE-03 | Cell `(R,S1,C1)` with 2 extract units: (a) both `done`; (b) one `done`, one `pending`; (c) one `done`, one `quarantined`; (d) case (a) run for a second pass | Rung 3, `IntegrityGate.verify` wrapped in a call-counting spy | (a) 1 call and a `cell_phase` row `integrity_pre`; (b) 0 calls, no row; (c) 1 call (quarantined is terminal); (d) still 1 call in total | Exact call count and row | P0 |

#### TC-PIPE-04 — Aggregation hook order, and one transaction for score + escalation + phase

| Field | Value |
|---|---|
| Requirements | FR-PIPE-04 |
| Risk | RISK-41, RISK-55 (Critical / High) |
| Level / type | Integration |
| Technique | Sequence assertion + induced failure (atomicity) |
| Isolation | Rung 3; spies record call order; a raising `write_score` is injected in the negative variant |
| Priority | P0 |

**Preconditions:** criterion `C2`'s recorded panel is `(2,4,4)`, so `should_escalate` is true.

**Steps:** `run_to_completion`, recording the order of `verify`, `verdicts_for`, `aggregate`, `write_score`, `should_escalate`, `enqueue_escalation` and `mark_cell_phase` for cell `(R,S1,C2)`.

**Oracle:** exact sequence; row presence.

**Expected result:**
- First pass, in order: `verify → verdicts_for → aggregate → write_score → should_escalate → enqueue_escalation → mark_cell_phase('aggregated', units_consumed=3)`.
- After the escalation's two extra verdicts land, a second aggregation of the same cell with `units_consumed=5`.
- Exactly one `criterion_score` row for the cell.
- The escalation units for the cell were enqueued exactly once.

**Variants:**
- **Atomicity:** `write_score` raises `sqlite3.IntegrityError` on the first attempt → no `criterion_score` row, no escalation units and no `aggregated` phase for the cell. The run pauses with `pause_reason` starting `composition fault: IntegrityError`.
- A cell whose `should_escalate` is false → no `enqueue_escalation` call; phase recorded with `units_consumed=3`.

**Automatable:** yes — `tests/integration/pipe/test_aggregate_hook.py`

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-PIPE-05 | FR-PIPE-05 | Cell with 3 score units; one quarantines after 3 strikes (`ProviderError("500")` ×3), so 2 verdicts remain | Rung 3, F-TAXONOMY for that judge | `aggregate` called with `fallback=True`. Stored row: `judge_count = 1`, `state = 'provisional'`. **No** row with `judge_count = 2` exists anywhere in the run. Variant: 1 of 3 quarantined but its re-request succeeded → 3 verdicts, `fallback=False` | Exact value + negative sweep | P0 |
| TC-PIPE-06 | FR-PIPE-06 | Complete run in which (a) all submissions are complete; (b) `S3` has an unscored criterion (quarantined); (c) the synthesis fixture for `S2` is missing (`FixtureMissingError`) | Rung 3 | (a) 3 narratives, 3 grades. (b) No narrative for `S3` (CT-SYNTH-05), and `S3` is still graded `incomplete`. (c) No narrative for `S2`, `grades_computed = 3`, and the `synthesize` stage `detail` names `S2` and `FixtureMissingError` (Q-23) | Exact rows + trace | P1 |
| TC-PIPE-07 | FR-PIPE-07 | (a) A leased unit whose lease expired at `T0+10 min`, clock at `T0+11 min`; (b) a `running` run with pending units after a simulated crash; (c) a `complete` run with `review_window_hours = 24`, grades provisional, clock advanced 25 h; (d) a clean store | Rung 3, `FrozenClock` | (a) `leases_reclaimed = 1` and the unit is `pending`. (b) `runs_resumed` contains the run. (c) `runs_regraded` contains the run and every grade is `final`. (d) All three report fields empty or zero, and no row changes. Boundary: clock at exactly 24 h → not regraded if base FR-GRADE-10's window is strict `>`; the case pins whichever operator FR-GRADE-10 declares | Exact report + rows | P0 |
| TC-PIPE-08 | FR-PIPE-08 | `python -m aeh run --data-dir D --cohort C --package-version V`, invoked through `main([...])` in-process and once via `subprocess` | Rung 3 (in-process), rung 4 (subprocess) | Exit **0** on `complete` with JSON on stdout parseable into the `RunResult` fields. Exit **3** when the fixture provider raises `ProviderUnavailableError` mid-run. Exit **1** for an unknown `--package-version`, with no `run` row created. With `HARNESS_PROFILE` set in the environment and absent from `--config`, the resolved profile equals the environment value, and `os.environ` is read only inside `conf.environment_snapshot` (static assertion: no `os.environ` in `aeh/pipeline.py`) | Exit code + stdout JSON + row counts + AST scan | P0 |
| TC-PIPE-09 | FR-PIPE-09 | (a) `python -m aeh recover --data-dir D` on a store with one expired lease; (b) `python -m aeh console --data-dir D` on the same store with `CONSOLE_PORT=0` | Rung 3 | (a) Prints a report with `leases_reclaimed: 1`; exit 0. (b) The lease is reclaimed **before** the socket accepts (the first `GET /` sees the unit `pending`), and the server answers `GET /` with 200 | Exact output + ordering via row state at first request | P1 |
| TC-PIPE-10 | FR-PIPE-10, FR-INTEG-09 | One store after extraction and panel for F-DEV-PIPE | Rung 2 | For every cell, the results of `spans`, `second_family_spans`, `regions`, `panel_sufficiency` and `criterion_requires_citation` from `StoreExtractionView(handle, catalog, pv)` **equal** those from `LedgerEvidenceView` | Differential | P0 |
| TC-PIPE-11 | NFR-PIPE-01 | For each hook boundary *k* in {after extract done, after `integrity_pre` recorded, after `write_score` before phase commit, after phase commit, after escalation enqueue, after synthesis of S1, after `compute_all` of 1 of 3}: raise `SystemExit` at *k*, then `recover` + `run_to_completion` in a fresh `Store` object | Rung 3 | The §4.3 projected tables are **equal** to the uninterrupted run's. No duplicate escalation units. `run_metrics` has no duplicated per-unit counts | Uninterrupted-run differential | P0 |
| TC-PIPE-12 | NFR-PIPE-03, FR-STORE-15 | A clean venv: `pip install <repo>` with no dev requirements, then `aeh --help`, `python -m aeh --help`, and `python -m aeh run` over F-DEV-PIPE | Rung 4, nightly, `slow` | Both entry points exit 0. The run completes. `import pypdf` fails in that venv (the core has no dependencies). `aeh/console_assets/console.css` exists in the installed package | Exit codes + file presence | P1 |
| TC-PIPE-13 | FR-PIPE-01 (error handling) | A hook raises `KeyError('C9')` from `verdicts_for` on one cell | Rung 3 | The run is `paused` with `pause_reason == "composition fault: KeyError: 'C9'"`. The `aggregate` stage `detail` names the cell. `run_to_completion` returns rather than raising. The exception is never swallowed into a `complete` status | Exact string + status | P0 |
| TC-PIPE-14 | FR-PIPE-01 (config) | `HARNESS_PIPE_MAX_PASSES` ∈ {`"0"`, `"-1"`, `"x"`, unset, `"2"`}; `HARNESS_PIPE_PASS_SLEEP_MS` ∈ {`"-5"`, `"0"`} | Rung 1 | Unset → unbounded. `"2"` → at most 2 passes. `"0"`, `"-1"`, `"x"` and `"-5"` raise before any row is written, and `main` exits 1 (type per Q-14). The knob is read at call time: changing the environment between two calls changes the pass bound | Exact behaviour | P1 |

### 5.2 Module: `M-ORCH` (delta)

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-ORCH-38 | FR-ORCH-27 | (a) `Orchestrator(store, executor=E)` with `E` a recording `StageExecutor`; (b) `executor=E, transport=T`; (c) `transport=T` only | Rung 2 | (a) `E.execute` is called once per leased model unit with a `GovernedProvider`, and `T.call` is never reached. (b) `ValueError` at construction, no row written. (c) Today's behaviour, byte-identical `run_metrics` to the base TC-ORCH-35 fixture | Exact calls + error | P0 |
| TC-ORCH-39 | FR-ORCH-27 | Concurrency ceiling 4, 40 score units, `ProductionStageExecutor` over a fixture provider with a 5 ms barrier per call | Rung 3 | Peak in-flight `GovernedProvider.complete` calls ≤ 4 and reaches 4; `peak_concurrency` metric = 4 | Concurrency spy + metric | P1 |
| TC-ORCH-40 | FR-ORCH-28 | `mark_cell_phase(tx, R,S,C,'integrity_pre',2)` twice; then `'aggregated',3`; then `'aggregated',5`; then `'bogus',1`; then purge cohort | Rung 2 | One row per (cell, phase); the `aggregated` row holds `units_consumed = 5`; `'bogus'` is rejected by CHECK and surfaces as `WorkLedgerError`; after purge, zero `cell_phase` rows | Exact rows | P0 |
| TC-ORCH-41 | FR-ORCH-29 | Decision table over one cell (rows below) | Rung 2 | See table | Exact tuple | P0 |
| TC-ORCH-42 | FR-ORCH-30 | Cell whose extraction is terminal but has **no** `integrity_pre` phase; one `score` unit pending. Arm A: executor bound. Arm B: no executor (report-only). Arm C: `transport=` only | Rung 2 | **A:** the score unit is not leased by `progress()`; after `mark_cell_phase(...,'integrity_pre',…)` it is. **B and C:** the score unit **is** leased without any phase row (the RISK-46 regression arm) | Exact lease state | P0 |
| TC-ORCH-43 | FR-ORCH-30 | F-TAXONOMY per arm: (a) `ProviderUnavailableError`; (b) `BuildChangedError`; (c) `RateLimitedError(retry_after=0)` ×2 then success | Rung 2, executor bound | (a, b) `progress()` **returns**; `run.status = 'paused'`; the pause cause names the class; the unit is `pending` with `attempts` unchanged (0); no further unit leased in that pass. (c) No pause; the unit completes with `attempts = 0`; `rate_limited_calls = 2` | Exact state | P0 |
| TC-ORCH-44 | FR-ORCH-31 | Grade policy for package version V referencing a criterion that V does not declare, per kind: (a) per-question rule; (b) gate criterion; (c) best-k member; (d) weight key; (e) all four at once, naming `C7`, `C8`, `C9`, `C10`; (f) a valid policy | Rung 2 | (a–d) `create_run` raises `PackageIntegrityError`, whose message contains the missing id. (e) The message contains **all four** ids. For every failing arm, zero `run` rows. (f) The run is created | Exact message + row count | P1 |
| TC-ORCH-45 | FR-ORCH-32 | Pure `evaluate_alerts` boundary table (below) | Rung 0 | See table | Exact alert names | P1 |
| TC-ORCH-46 | FR-ORCH-33 | `run.started_at = 2026-09-01T00:00:00Z`; `run_control` pause applied 01:00, resume applied 03:00; a second pause applied 04:30 with no resume; `FrozenClock` at 05:00; a **fresh** `Orchestrator` (new process-equivalent object) flushes metrics. Two resolved builds, `b1` then `b1` again then `b2` | Rung 2 | `wall_clock_ms = 9_000_000`: 5 h − 2 h − 0.5 h, with the open pause counted to now. `resolved_builds = ["b1","b2"]`. `estimated_cost` equals `run.cost_estimate`. `cost_currency` and `retention_setting` are present | Hand-computed value | P1 |
| TC-ORCH-47 | FR-ORCH-34 | (a) `enqueue_escalation(tx, (RA,S1,C1), …)`; (b) `(S1,C1)` with one open run RA; (c) `(S1,C1)` with open runs RA and RB | Rung 2 | (a) Units are enqueued for RA only. (b) Units are enqueued for RA, and a deprecation is recorded (warning). (c) `WorkLedgerError`, and the caller's transaction rolls back with zero escalation units | Exact rows | P0 |
| TC-ORCH-48 | FR-ORCH-35 | Package with `C1`: `kind='mcq'`, `evaluation_mode='judged'`; `C2`: `kind='open'`, `evaluation_mode='deterministic'` (with an answer key) | Rung 3 | Enumeration creates extract/score units for `C1` and a deterministic unit for `C2`. `separated_rollup`, M-STATS and M-DET follow the column. A source scan finds no `kind = 'mcq'` / `kind == "mcq"` predicate in `orch.py`, `grade.py`, `stats.py` or `det.py` | Metamorphic + static scan | P1 |

**TC-ORCH-41 decision table (`ready_cells`).**

| Row | Extract units | Score units | Phases | `ready_cells(R,'integrity_pre')` | `ready_cells(R,'aggregate')` |
|---|---|---|---|---|---|
| 1 | 2 done | none | none | contains cell | empty |
| 2 | 1 done, 1 pending | none | none | empty | empty |
| 3 | 2 done | 3 done | `integrity_pre` | empty | contains cell |
| 4 | 2 done | 2 done, 1 leased | `integrity_pre` | empty | empty |
| 5 | 2 done | 3 done | `integrity_pre`, `aggregated(3)` | empty | empty |
| 6 | 2 done | 5 done | `integrity_pre`, `aggregated(3)` | empty | contains cell |
| 7 | 2 quarantined | none | none | contains cell | empty |
| 8 | row 3, but for run RB | — | — | RA query excludes RB's cell | RA query excludes RB's cell |

**TC-ORCH-45 boundary table (`evaluate_alerts`).** Defaults: `HARNESS_ORCH_COST_WARNING_FRACTION=0.9`, `…CACHE_COLLAPSE_SIGMA=3.0`, `…FLOOR=0.5`, `…MIN_HISTORY=3`.

| Row | Input | Expected alerts |
|---|---|---|
| 1 | spend 89.99, ceiling 100 | none |
| 2 | spend 90.00, ceiling 100 | `orch_cost_near_ceiling` |
| 3 | one breaker row `tripped=1` | `orch_criterion_breaker_tripped` |
| 4 | escalation rate above the base budget by 0.001 / exactly at the budget | alert / no alert |
| 5 | `run.status='paused'` | `orch_run_paused` |
| 6 | cache history `[0.8,0.8]` (2 runs), current 0.1 | none (below min history) |
| 7 | history `[0.8,0.82,0.78]`, current 0.1 | `orch_cache_hit_rate_collapse` |
| 8 | history `[0.4,0.4,0.4]`, current 0.39 | none. The floor rule is read as "only fires when the current rate is below both the σ bound and 0.5 **and** the history mean was above the floor". The prefix-cache runbook's reading is pinned here and flagged as design Q-D3. |
| 9 | all conditions at once | the five names, exactly, as a set |
| 10 | `HARNESS_ORCH_COST_WARNING_FRACTION="1.5"` / `"x"` | raises `OrchestratorError` at call time |

### 5.3 Modules: `M-EXTRACT` and `M-JUDGE` (delta)

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-EXTRACT-16 | FR-EXTRACT-11 | `ExtractionWorker.process` over one unit, per error class from F-TAXONOMY: `RateLimitedError`, `ProviderUnavailableError`, `BuildChangedError`, and the contrasts `ProviderError("500")` and unparseable JSON (`ValueError`) | Rung 2 | **Taxonomy three:** the error propagates out of `process` as the same class; zero `evidence` rows; `attempts` unchanged; no `fail()` call (spy). **Contrasts:** `attempts = 1` after one call, no propagation; after the third, quarantined and no evidence row | Exact state + spy | P0 |
| TC-EXTRACT-17 | FR-EXTRACT-12 | Hand-built evidence for run R, criterion C1: units with span counts `[0, 2, 2, 5]`, latencies `[100, 200, 300, 400]` ms, no second family; criterion C2 with a second family where 1 of 4 disagrees | Rung 2 | C1: `spans_per_unit = {0:1, 2:2, 5:1}`, `empty_result_rate = 0.25`, `second_family_disagreement_rate is None` (not 0.0), `extraction_latency_p50_ms = 250`, `p95_ms = 385` (linear interpolation; the method is pinned in the test docstring). C2: rate `0.25`. Run RB's rows do not contribute | Hand-computed | P1 |
| TC-EXTRACT-18 | FR-EXTRACT-13 | `FrozenClock` advancing 250 ms during the successful call; a preceding failed attempt that took 900 ms | Rung 2 | `evidence.latency_ms = 250`; the failed attempt wrote no row | Exact value | P2 |
| TC-JUDGE-25 | FR-JUDGE-18 | Run RA with 3 verdicts for `(S1,C1)` inserted in `work_id` order `w3, w1, w2`; run RB with 3 verdicts for the same pair | Rung 2 | `verdicts_for(h, RA, S1, C1)` returns exactly RA's 3, ordered `w1, w2, w3`, each carrying band, `band_ordinal`, `cited_spans`, `evidence_sufficient`, `uncited` and `judge_id`. Feeding the tuple to `aggregate` succeeds with no adaptation. A nonexistent cell → empty tuple | Exact tuple | P0 |
| TC-JUDGE-26 | FR-JUDGE-19 | `ScoringWorker.dispatch`, per error class, as in TC-EXTRACT-16 | Rung 2 | As TC-EXTRACT-16, with `verdict` in place of `evidence`. The FR-JUDGE-10 re-request is **not** triggered by a taxonomy error | Exact state | P0 |
| TC-JUDGE-27 | FR-JUDGE-20 | `persist` of a verdict with `evidence_assessment="partial: two of three steps"` and a 320 ms call | Rung 2 | The stored row carries both values exactly; `evidence_assessment` NULL is stored as NULL, not `""` | Exact value | P1 |
| TC-JUDGE-28 | FR-JUDGE-21 | Judge J2 returns 3 contract-violating responses on C1 (they strike); J1 returns 1 | Rung 2 | `run_metrics` rows `judge_contract_violations` with dimensions `(C1,J2) = 3` and `(C1,J1) = 1`; a successful response writes none | Exact rows | P1 |

### 5.4 Module: `M-INTEG` (delta)

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-INTEG-15 | FR-INTEG-09 | `StoreExtractionView` with the underlying read of `evidence` failing (`sqlite3.OperationalError` injected); with a missing criterion | Rung 2 | Each read **raises**, never returns `()`, `None` or `False`. `IntegrityGate.verify` then takes CT-INTEG-01's fail-closed route (review item or retry), never a pass | Exception + route | P0 |
| TC-INTEG-16 | FR-INTEG-10 | Per route — (a) verification false; (b) sufficiency insufficient; (c) passing — call `verify(R,S,C)`: once; twice with unchanged panel state; then a third time after a new terminal score unit for the cell | Rung 2 | (a, b) After call 1: the gate's own pending extract unit has `attempts = 1`. After call 2: `attempts` is **still 1**, and `work_unit`, `review_queue` and `run_metrics` row counts are unchanged — this is the self-inflicted-bump case. After call 3: the route may run again, and `attempts = 2`. (c) No rows on any call | Exact counts | P0 |
| TC-INTEG-17 | FR-INTEG-11 | Blob reads counted by a spy. (a) 12 `verify` calls over 4 criteria of one submission; (b) `HARNESS_INTEG_DOCUMENT_CACHE_ENTRIES=2` with 3 submissions visited `S1,S2,S3,S1`; (c) knob `"0"`, `"-1"`, `"x"`; (d) two runs whose documents share a `content_hash` but belong to different submissions | Rung 2 | (a) 1 blob read and 1 hash verification. (b) 4 reads, because `S1` was evicted. (c) Each raises `IntegrityError` at call time. (d) Each verify reads its own submission's regions — the cache key includes `(run, content_hash)` — and no cross-submission bytes are served | Exact counts | P1 |
| TC-INTEG-18 | FR-INTEG-12 | `EXPLAIN QUERY PLAN` for `INTEG_STATEMENTS["read_document"]`, `count_units` and `max_retry_attempts` after migrations | Rung 2 | Plans name `idx_document_submission`, `idx_wu_cell` and `idx_wu_cell` respectively; none shows `SCAN work_unit` or `SCAN document` | Query plan text | P1 |

### 5.5 Module: `M-AGG` (delta)

#### TC-AGG-21 — `write_score` stores every field of the `CriterionScore` it is given

| Field | Value |
|---|---|
| Requirements | FR-AGG-15 |
| Risk | RISK-41, RISK-42 (Critical) |
| Level / type | Integration |
| Technique | Equivalence partitioning over the nullable signals |
| Isolation | Rung 2 |
| Priority | P0 |

**Preconditions:** verdicts with bands `(2,3,3)` on a 4-band criterion. `aggregate` yields `CriterionScore` `s`.

**Steps:** `write_score(tx, "RA", "S1", s, signals)` inside `with handle.transaction() as tx`, then read the row back.

**Oracle:** field-by-field equality with `s` and `signals`.

**Expected result:**
- The row is keyed `(RA,S1,C1)`, with `band = modal_band = s.modal_band`, `band_spread = 1`, and `points`, `judge_count = 3`, `agreement`, `confidence`, `confidence_base`, `routing` and `state` equal to `s`.
- All six integrity flags are stored.
- `caps_fired` is the JSON list `s` names (`[]` when none, never NULL).

**Variants:**
- `extractor_disagreement=None` → stored NULL, and a read distinguishes it from `0`.
- `described_evidence=False` → stored `0`.
- `write_score` called outside a transaction → raises, nothing written.
- A second call with an identical `s` → one row.
- A second call with a changed band → one row, updated.

**Automatable:** yes — `tests/integration/agg/test_write_score.py`

#### TC-AGG-22 — The `criterion_score` rebuild migration is lossless and fails loudly when attribution is ambiguous

| Field | Value |
|---|---|
| Requirements | FR-AGG-16 |
| Risk | RISK-43 (Critical, irreversible) |
| Level / type | Migration |
| Technique | Equivalence partitioning over store shapes (F-SCHEMA additions) |
| Isolation | Rung 2, real SQLite files |
| Priority | P0 |

**Steps:** open each F-SCHEMA Cohort DB with the full migration chain.

**Oracle:** checksum golden + exact error.

**Expected result:**

| Variant | Store at v19 | Expected |
|---|---|---|
| (a) | 1 run, 45 score rows | All 45 survive. `run_id` = that run. A checksum of `(submission_id, criterion_id, band, points, judge_count)` equals the pre-migration checksum. `band_spread = 0` and `modal_band = band` for migrated rows. |
| (b) | 2 runs, 45 rows | The open raises `MigrationError("criterion_score rows cannot be attributed to a run: 2 runs")`. The file is unchanged (byte-identical `criterion_score` table and `schema_version` still 19). |
| (c) | 2 runs, 0 rows | Migrates; the table has the new PK |
| (d) | after (a) | Inserting a `judge_count = 2` row fails the CHECK. Two rows differing only in `run_id` coexist. |
| (e) | after (a) | `COMPLETE_SCHEMA_VERSIONS` Cohort pin equals the new head, and `IncompleteMigrationChainError` fires if `aeh.agg` is not imported |

**Automatable:** yes — `tests/integration/store/test_agg_run_scoped_migration.py`

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-AGG-23 | FR-AGG-17 | Run R with 3 criteria: C1 bands `[1,1,2,3]` with spreads `[0,1,2,0]`, 1 of 4 escalated, 2 of 4 auto-accepted, cap `uncited_cap` fired twice | Rung 2 | `band_histogram(C1) = {1:2, 2:1, 3:1}`, `band_spread_distribution = {0:2, 1:1, 2:1}`, `escalation_rate = 0.25`, `auto_accept_rate = 0.5`, `caps_fired.uncited_cap = 2`; α distribution matches the F-STATS hand value; another run's rows excluded | Hand-computed | P1 |
| TC-AGG-24 | FR-AGG-13 (amended) | `write_score` with `described_evidence=True`, `extractor_disagreement=True` and each of the four base flags toggled one at a time | Rung 2 | All six columns stored. A cap keyed on `extractor_disagreement` recomputes from the stored row alone (`recompute_from_row(row) == s.confidence`), which closes the TC-AGG-C15 residual | Differential recompute | P1 |

### 5.6 Modules: `M-DET` and `M-GRADE` (delta)

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-DET-15 | FR-DET-11 | Run A evaluates MCQ `Q3` for S1 with key `B`, answer `B` (full points). Run B, same cohort, has key corrected to `C`; `rederive_for_key_change` is called for run B | Rung 2, two-run oracle | Run B's row: 0 points. Run A's row: **unchanged** (full points), and `band_spread = 0` on both. A call naming run A re-derives only A | Two-run isolation | P0 |
| TC-GRADE-25 | FR-GRADE-18 | F-DEV-PIPE-TWO-RUN: run A bands `(1,1,1)`, run B `(3,3,3)` on the same pairs; `compute_all(A)`; then B completes; `compute_all(A)` again; `rollup_findings(A)` | Rung 3 | A's totals are identical before and after B lands. A's findings contain no B-derived item. A source scan shows every `criterion_score` query in `grade.py` has a `run_id` predicate | Two-run isolation + static | P0 |

### 5.7 Module: `M-REVIEW` (delta)

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-REVIEW-25 | FR-REVIEW-18 | One queued score per input; stored values in the next column | Rung 2 | `_StoredScoreRow` fields equal the stored inputs (sweep table below). No field falls back to a literal default when the stored value exists | Exact value per field | P1 |
| TC-REVIEW-26 | FR-REVIEW-19 | Run R's package: C1 `holistic`, C2 `atomic_with_gate`; unknown `C9` | Rung 2 | `scoring_model_for("C1") == "holistic"`, `("C2") == "atomic_with_gate"`, `("C9")` raises `ReviewError`; the literal `"atomic"` no longer appears in `review.py`'s store form (static) | Exact + static | P1 |
| TC-REVIEW-27 | FR-REVIEW-20 | `build_queue(R, budget=10)` showing 4 items; `act` on item 2 with `override`, new band `3`, 7.5 points; existing writers in `grade.py` and `integ.py` each enqueue once | Rung 2 | Shown items carry `rank_score` (non-increasing with position), `est_seconds` and `shown_at = clock`. Item 2 carries `action='override'`, `new_band='3'`, `new_points=7.5` and `acted_at`. The grade and integ rows carry `run_id = R` | Exact rows | P1 |
| TC-REVIEW-28 | FR-REVIEW-21 | `record_label` with system band ordinal 1, teacher ordinal 3; package without a population scope; then one with scope `assignment_type='lab'`; then an agreeing label | Rung 2 | `band_distance = 2`, `agreed = 0`, `assignment_type` NULL, then `'lab'`. The agreeing label has `band_distance = 0`, `agreed = 1`. `package_version_id`, `system_points`, `teacher_points`, `panel_config` and `recorded_at` are all populated | Exact rows | P1 |
| TC-REVIEW-29 | FR-REVIEW-22 | New label collected under run `RA` of cohort `K1`; F-SCHEMA Durable v8 DB whose labels carry run ids `RA` (mapped to `K1`) | Rung 2 | New label `cohort_id = 'K1'`, never `'RA'`; the migrated resolvable rows are rewritten to `'K1'`. Unresolvable variant pending Q-16 | Exact rows | P1 |
| TC-REVIEW-30 | FR-REVIEW-02, NFR-REVIEW-05 (amended by D-1) | `REVIEW_BLIND_RESERVE_MINUTES = 5`; budgets 60, 5, 4 and 0.5 minutes; identical flagged population of 20 items at 45 s each | Rung 2 | Budget 60 → reserve 5, ranked minutes 55, **73** items fit but only 20 exist, so all 20 are shown with residual 0. Budget 5 → reserve 5, ranked minutes 0, the floor shows **1** item (top-ranked), and the residual states 19. Budget 4 → reserve 4 (min), floor 1 shown. Budget 0.5 → reserve 0.5, 1 shown. The ranking **order** of the shown prefix is identical at every budget (same first item). The header states the subtraction | Exact values + ordering invariant | P1 |
| TC-REVIEW-31 | FR-REVIEW-18 (knobs) | `HARNESS_REVIEW_EST_SECONDS_ATOMIC=30`; then only legacy `AEH_REVIEW_EST_SECONDS_ATOMIC=20`; then both set; then `"x"` | Rung 1 | 30; 20 (fallback); 30 (new name wins); `ReviewError` at call time | Exact | P2 |

**TC-REVIEW-25 sweep.**

| Input | Stored value | Expected field value |
|---|---|---|
| `panel_spread` | `criterion_score.band_spread = 2` | 2 |
| `adverse_integrity_signals` | flags: uncited=1, ocr_overlap=1, described=0, disagreement=NULL | 2 (NULL is not adverse) |
| `transcription_overlap` | `ocr_overlap_risk = 1` | True |
| `scoring_model` | criterion `holistic` in run's version | `"holistic"` |
| `criterion_weight` | grade policy weight 2.5 | 2.5 |
| `historical_override_rate` | 4 judgments, 1 override (n = 4 < 5) | `None` |
| `historical_override_rate` | 5 judgments, 2 overrides | 0.4 |
| `grade_boundary_delta` | total 69.5, nearest boundary 70 | 0.5 (from `distance_to_nearest_boundary`) |
| `est_seconds` | atomic / holistic, knobs unset | 45 / 90 |
| run filter | run RB has `band_spread = 3` for the same pair | R's row still reads 2 |

### 5.8 Module: `M-STATS` (delta)

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-STATS-27 | FR-STATS-20 | Verdict rows for C1: J1 10 verdicts (2 uncited, 1 insufficient), J2 10 (0 uncited). Violations C1: J1 = 3, J2 = 3, J3 = 0 (total 6, J1 share 0.5); then J1 = 4, J2 = 2 (share 0.667); then J1 = 4, J2 = 0 (total 4) | Rung 2 | J1 uncited rate 0.2 and insufficient rate 0.1. Alert `judge_contract_violations_concentrated`: **absent** at share 0.5 (strict `>`), **present** at 0.667 naming J1, **absent** at total 4 (< 5). Fields equal `JUDGE_SIGNAL_FIELDS` | Hand-computed | P1 |
| TC-STATS-28 | FR-STATS-21 (Phase 2) | 6 fixture judgments; recorded responses for the original order and 2 permutations (seeds 1, 2), where judge J2 changes band on 2 of 6 under permutation; `measure_self_agreement(runs=3)` with J1 identical all 3 times; `runs=2` | Rung 3 | `position_bias[J2] = 2/6`, `[J1] = 0`; self-agreement J1 = 1.0; `run_mvvp(measured_position_bias=…)` accepts the output unchanged; `runs=2` raises (Q-17) | Hand-computed | P2 |
| TC-STATS-29 | FR-STATS-22 | Labels: L1 `saw_system_output=0`; L2 `=1`; L3 `=None`; L4 attribute absent | Rung 0 | Admitted: {L1}. `excluded_count` includes L3 and L4 under reason `saw_system_output_unrecorded`, and L2 under the operational reason | Exact set | P0 |
| TC-STATS-30 | FR-STATS-23 | Two administrations A1 (40 labels), A2 (10) | Rung 2 | `exports/` holds exactly 2 `.jsonl` files; line counts 40 and 10; every line parses as JSON; export performs no write to any tier (write audit: zero writes); a second export of A1 is byte-identical; no Parquet/DuckDB import in `stats.py` | Exact + audit | P2 |
| TC-STATS-31 | FR-STATS-24 | Lineage P, criterion C1: no labels; 4 labels; 5 labels, 2 overrides | Rung 2 | `NoValidationData`; `NoValidationData` (below min n, same threshold as TC-REVIEW-25); `OverrideHistory(n=5, overrides=2, rate=0.4)`. `should_escalate`'s `history` argument and FR-REVIEW-18 both consume this exact object (spy) | Exact type + value | P1 |

### 5.9 Modules: `M-CALIB`, `M-INGEST`, `M-PKG`, `M-SETUP`, `M-STORE` (delta)

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-CALIB-20 | FR-CALIB-15 (Phase 3) | R₀ run with run-scoped scores for 12 papers × 2 criteria; `run_dual_scoring` R₁ bands; `register_dual_scored_roster(K, r0_version=v1, r1_version=v2, store)`; then a **new** `Store` object and cleared `_CLASS_ROSTERS` | Rung 2 | 24 `calib_roster` rows; `non_inferiority` before and after restart returns equal results; R₀ bands come from R₀'s run only (a second run R₀′ with different bands does not leak) | Differential | P2 |
| TC-INGEST-50 | FR-INGEST-36 | Decision table below | Rung 2 | See table | Exact rows + report | P0 |
| TC-INGEST-51 | FR-INGEST-37 | Direct `INSERT` and `UPDATE` of a `selection_mark` region to `resolved` with `selection = NULL`; same for a `transcribed_text` region | Rung 2 | Both `selection_mark` writes abort, and the module surfaces `IngestError`; the text region writes succeed | Exact error | P0 |
| TC-INGEST-52 | FR-INGEST-26 (amended by D-3) | Store with 3 lineages whose structural signal matches the submission; semantic similarity 0.2 / 0.6 / 0.9 | Rung 2 | The proposal lists all 3, ranked by semantic signal (0.9 first), with a per-candidate semantic value (none `absent`). **Written ahead; scheduled with design landing step 7** | Exact order | P2 |
| TC-INGEST-53 | cross-cutting (delta §3.14 `document_region.question_id`, Q-21) | Parse a 2-question page with one graphic after Q2's text | Rung 2 | Stored graphic region carries `question_id = 'Q2'`; a consumer reading ownership uses the column (source scan: no preceding-region inference in storage consumers) | Exact + static | P2 |
| TC-PKG-31 | FR-PKG-22 | F-SCHEMA Package v10 DB (`mcq` + `open`); then a revision child; then export + import | Rung 2 | After migration: `mcq` → `deterministic`, `open` → `judged`; inserting `evaluation_mode='llm'` fails CHECK; NULL fails NOT NULL; the child and the imported version carry identical values | Exact rows | P0 |
| TC-PKG-32 | FR-AGG-08 (baseline input; Q-21) | Promote an administration with judged band histogram `{1:10, 2:20, 3:10}` for C1 | Rung 2 | `validation_record.expected_mean = 2.0`, `expected_sd` = population SD 0.7071 (pinned in the docstring), `expected_histogram` JSON equal; `should_escalate`'s `baseline` for C1 is no longer no-data | Hand-computed | P2 |
| TC-SETUP-23 | FR-SETUP-17 | SetupService builds a package with one FR-SETUP-13 deterministic criterion and one open criterion | Rung 2 | Rows written with explicit `evaluation_mode` (a spy on the insert shows the column bound, not defaulted); `SCORING_MODELS == ("atomic", "atomic_with_gate", "holistic")` | Exact | P1 |
| TC-STORE-26 | FR-STORE-15 | `tomllib.load(pyproject.toml)` | Rung 0 | `[build-system].requires` contains `setuptools>=69`; `[project.scripts].aeh == "aeh.pipeline:main"`; `[project].dependencies == []`; `optional-dependencies.live-ingest` contains `pypdf>=6.0` and `pypdfium2>=4.0`; package data includes `aeh/console_assets/*` | Exact | P1 |

**TC-INGEST-50 decision table (`resolve_cluster`).** Question `Q3` declares options `A`–`D`.

| Row | Region kind | Resolution | Expected region state | Report |
|---|---|---|---|---|
| 1 | `transcribed_text` | `"2x + 3"` | content replaced; `selection_state` unchanged | — |
| 2 | `described_graphic` | `"arrow labelled F"` | content replaced; `selection_state` unchanged | — |
| 3 | `selection_mark` | `"C"` | `selection = 'C'`, `selection_state = 'resolved'`, set in one statement | — |
| 4 | `selection_mark` | `"E"` (undeclared) | stays `ambiguous`; `selection` NULL; content replaced | listed in `selection_unresolved` |
| 5 | `selection_mark` | `""` | stays `ambiguous` | listed |
| 6 | `selection_mark` | `"c"` (case) | stays `ambiguous` (exact option id match; flag if the design intends case-folding) | listed |
| 7 | mixed cluster of rows 1 + 3 + 4 | per row | each region per its row | only row 4's region listed |
| 8 | after row 3 | M-DET `evaluate` | the question scores against `C`, never as unanswered | — |

### 5.9b Module: `M-CONF` (delta) — switching harness profiles by environment variable

**Fixture F-PROFILES.** One TOML config file, plus a cohort with `consent_class='synthetic'`.
- **Shared:** `prompt_template_v = "p7"`.
- **`edge-local` section:** `HARNESS_HARDWARE_PROFILE="unified-small"`, a local panel.
- **`cloud-hosted` section:** `HARNESS_COST_CEILING=50`, `HARNESS_COST_CURRENCY="EUR"`, `retention_setting="zero"`, an OpenRouter panel.
- **`dev-ci` section:** `HARNESS_COST_CEILING=5`, `HARNESS_COST_CURRENCY="USD"`, a fixture panel.

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-CONF-20 | FR-CONF-13 | `select_profile_config(F-PROFILES, p)` for `p` in `edge-local`, `cloud-hosted`, `dev-ci`, `gpu-farm`; plus a file with no `profiles` table | Rung 0 | Each known `p` yields the shared keys plus exactly that section's keys, with `HARNESS_PROFILE == p` and no key from another section (for example, no `retention_setting` under `edge-local`). `gpu-farm` raises `ConfigurationError` naming `gpu-farm` and the three sections present. The single-profile file is returned unchanged. The function is pure: same inputs, equal output, and the input is not mutated. | Exact dict equality | P0 |
| TC-CONF-21 | FR-CONF-14 | `effective_config(F-PROFILES, environ=E)` over the matrix below, then `resolve_run_config` on the result | Rung 0 | See the matrix. `resolve_run_config` still reads no `os.environ`: a monkeypatched `os.environ` with a conflicting `HARNESS_PROFILE` has no effect when `environ=E` is passed. **In-process console variant:** a console started with `HARNESS_PROFILE=dev-ci`; then `os.environ["HARNESS_PROFILE"]="cloud-hosted"` and POST "start run". The console re-reads at action time, applies CT-CONSOLE-27 and refuses, and no run row is created. | Exact values | P0 |
| TC-CONF-22 | FR-CONF-15 | Run RA created and paused under `edge-local`; environment switched to `cloud-hosted`; `recover(store)`. Run RB created under `cloud-hosted`, with one expired lease. | Rung 3 | RA stays `paused`, and its pause reason contains both `'edge-local'` and `'cloud-hosted'`. RA's persisted `provider_config` is unchanged and none of its units are leased. RB's lease is reclaimed and RB resumes (`runs_resumed` contains RB only). `recover` does not raise. Variant: with the environment switched back to `edge-local`, RA resumes. | Exact state | P0 |
| TC-CONF-23 | FR-CONF-16 | `python -m aeh run` with the profile coming from (a) the environment, (b) the config file | Rung 3 | The start-up output block contains the `profile_summary()` fields, and `HARNESS_PROFILE source: environment` for (a) or `config file` for (b). No credential value appears in the output (base NFR-CONF-02 scan). | Exact text + negative scan | P1 |

**TC-CONF-21 matrix.**

| Row | Environment `E` | File top-level `HARNESS_PROFILE` | Expected |
|---|---|---|---|
| 1 | `{}` | `edge-local` | `edge-local`, with that section's keys |
| 2 | `{HARNESS_PROFILE: cloud-hosted}` | `edge-local` | `cloud-hosted`, with that section's keys (`retention_setting='zero'`, 50 EUR); resolves |
| 3 | `{HARNESS_PROFILE: dev-ci}` | absent | `dev-ci`; resolves |
| 4 | `{HARNESS_PROFILE: cloud-hosted, HARNESS_COST_CEILING: "80"}` | `edge-local` | `cloud-hosted` with ceiling **80**: the environment beats the section |
| 5 | `{}` | absent | `resolve_run_config` raises `ConfigurationError` (no default, FR-CONF-01) |
| 6 | `{HARNESS_PROFILE: EDGE-LOCAL}` | `edge-local` | Raises: the match is exact, and the environment is not silently dropped in favour of the file |
| 7 | `{CONSOLE_BIND: 0.0.0.0}` | `CONSOLE_BIND=127.0.0.1` | Effective bind `0.0.0.0` (the environment wins); the console then refuses (TC-CONSOLE-46 row 4) |

### 5.10 Module: `M-CONSOLE` (delta)

Unless stated otherwise, every case starts a real `ConsoleServer` on `127.0.0.1` port 0 over a real store. Requests use `http.client`; no browser is involved.

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-CONSOLE-43 | FR-CONSOLE-33 | Requests: <br>• `GET /`, `GET /assets/console.css`, `GET /nope`; <br>• `POST /actions/finalize-batch` (in `CONTROL_SURFACE_ACTIONS`) and `POST /actions/drop-tables` (not); <br>• `POST /upload` with a 12 MiB body; <br>• `terminate()`. | Rung 3 | <br>• `GET /` → 200, `text/html; charset=utf-8`. <br>• css → 200, `text/css`. <br>• unknown → 404. <br>• Every response carries `Cache-Control: no-store`. <br>• The undeclared slug → 404 with no store write (write audit). <br>• Upload → blob sha256 equals the body's, with no single read over 1 MiB (the read-size spy's maximum chunk is at most 1 MiB). <br>• After `terminate()` the port refuses connections and the server thread has joined. <br>• Static: `_CHILD_SCRIPT` is absent from `console.py`. | Exact HTTP + audit + static | P0 |
| TC-CONSOLE-44 | FR-CONSOLE-34 | Every row of the action sweep table below, each run twice on a real store: once where the owning door succeeds, once where it refuses. | Rung 3 | <br>• Success arm: the §11.8 effect row exists and `dispatched=True`. <br>• Refusal arm: `dispatched=False` and the refusal text equals the owning module's exception message. <br>• In neither arm does `dispatched=True` coexist with a missing effect. <br>• Static: no `contextlib.suppress(Exception)` around a door call in `console.py`. | Exact rows + message | P0 |
| TC-CONSOLE-45 | FR-CONSOLE-35 | A run with 20 flagged items and a budget of 10 minutes. Render S9, S10/S11, S3/S4/S5 and S2. | Rung 3 | <br>• S9's header figures (`flagged_total`, `shown`, `residual_provisional`, `reserved_for_blind_minutes`) equal `ReviewService.build_queue(R, 10)`'s fields exactly. <br>• S3 rows are editable (form fields present per HLD §11.5). <br>• A SQL scan of `console.py` finds none of the removed queries (`review_queue.rank_position`, `review_budget`, `package_file`, `setup_skip`, `sample_selection`, `blind_sample` tables). | Differential + static | P1 |
| TC-CONSOLE-46 | FR-CONSOLE-36 | Pairwise environment/cfg matrix, below. | Rung 2 | See the table below. | Exact bind/refusal | P0 |
| TC-CONSOLE-47 | FR-CONSOLE-37 | (a) Drop `review_queue` from the Cohort tier, then render S9. (b) Inject a non-schema fault (`ValueError`) in one per-ledger read of `_read_cohort_files`. | Rung 3 | (a) `ConsoleReadError` naming the query and tier. The page shows the section "this view could not be read" with **no** numeric count in that section (regex: no `\b0\b` inside the section). The HTTP status is not asserted (Q-25). (b) The page renders, and its build trace counts 1 skipped ledger. | Exact text + absence | P0 |
| TC-CONSOLE-48 | FR-CONSOLE-38 | An agreement figure with n = 29, then 30, then 31. Then `aeh.stats.STATS_MIN_N_FOR_HEADLINE` monkeypatched to 10 with n = 12. | Rung 1 | n = 29: text contains `too few to draw conclusions from`. n = 30 and 31: absent. Patched threshold, n = 12: absent (read at call time). | Exact string | P1 |
| TC-CONSOLE-49 | FR-CONSOLE-39 | Submission S1 in run R with revisions 1 (superseded, `is_current = 0`) and 2 (current, `is_current = 1`); the schema keeps exactly one current row per (run, submission) (`grade.py:785`). Revision 2 is written by `amend`, so the highest revision is also the current one; a variant flips `is_current` by direct fixture write to revision 1 to separate "current" from "highest". Call `grade_revision(revision=None)`, then `revision=1`. | Rung 2 | `None` → the `is_current = 1` row (revision 2, and revision 1 in the flipped variant, which catches a `MAX(revision)` implementation). `1` → revision 1's row. A second run RB with its own current revision is not returned for R. | Exact row | P1 |

**TC-CONSOLE-44 action sweep** (Phase-1 actions of the delta §3.13 map).

| # | Action | Success arm (effect asserted) | Refusal arm (induced) |
|---|---|---|---|
| 1 | approve question inventory | Inventory confirmation row via `confirm_inventory` | Inventory already confirmed for a locked version → the door's refusal |
| 2 | supply answer keys | Keys stored via `set_answer_keys` | Key for an undeclared option |
| 3 | accept/correct rubric read-back | Read-back confirmation stored | Correction naming an unknown criterion |
| 4 | set review window | Stored `review_window_hours = 48` on the run's version (Q-22) | Negative hours |
| 5 | start run | `run` row created; `run_to_completion` running on the server-owned thread (the response returns before completion, see PERF-13) | `validate_grade_policy` failure → `PackageIntegrityError` text, no run row |
| 6 | pause / resume | `run_control` rows | Resume on a completed run |
| 7 | resolve quarantine item | The existing effect | Stale item |
| 8 | review action | `ReviewService.act` effect: `review_queue.action`, label row | Acting on a superseded item |
| 9 | blind-sample submission | `blind_sample` session record | Sampling after the blind quota is exhausted |
| 10 | correct an answer key after a run | Existing effect plus re-derivation for **that** run only | Unknown question |
| 11 | finalize batch | All grades `final` via `finalize_batch` | Batch with an unresolved gate → refusal; grades stay provisional |
| 12 | amend a finalized grade | New revision via `amend`; the prior revision is unchanged | Amending a provisional grade |
| 13 | export/import package | Archive written / version imported | Import of a malformed archive |
| 14 | purge cohort | Tiers C and R emptied for the cohort | Purge before promotion → refusal |
| 15 | approve exemplar paraphrases | **Phase 3.5.** Renders present-and-unavailable naming 3.5 (FR-CONSOLE-25); `dispatched=False` | — |

**TC-CONSOLE-46 matrix.** The environment is set through `os.environ`; `cfg` is passed in.

| Row | Env `HARNESS_PROFILE` | Env `CONSOLE_BIND` | `cfg` | Expected |
|---|---|---|---|---|
| 1 | unset | unset | `{}` | Binds `127.0.0.1` |
| 2 | `cloud-hosted` | unset | `{}` | Refuses; no socket |
| 3 | `cloud-hosted` | unset | `{"HARNESS_PROFILE": "edge-local"}` | **Refuses; no socket** (CT-CONSOLE-27; consistent with FR-CONF-14 since design 1.5.1) |
| 4 | unset | `0.0.0.0` | `{}` | Refuses (loopback check on the resolved bind) |
| 5 | unset | `0.0.0.0` | `{"CONSOLE_BIND": "127.0.0.1"}` | **Refuses**: the environment wins over `cfg` (FR-CONF-14), so the effective bind is `0.0.0.0` |
| 6 | `edge-local` | `127.0.0.1` | `{"CONSOLE_PORT": 0}` | Binds; the ephemeral port is reported |
| 7 | `cloud-hosted` | `0.0.0.0` | `{}` | Refuses naming the profile (the profile check runs first) |

### 5.11 Non-functional (delta)

| Requirement | Verified by |
|---|---|
| NFR-PIPE-01 | TC-PIPE-11, RES-19 |
| NFR-PIPE-02 | PERF-11 |
| NFR-PIPE-03 | TC-PIPE-12, TC-SMOKE-12 |
| NFR-CONSOLE-08 | PERF-13, RES-19 |
| NFR-INTEG-01 (acceptance form amended) | PERF-06 |

---

## 6. Cross-cutting suites (delta)

### 6.1 Smoke suite

| ID | Req | Check | Blocks on failure |
|---|---|---|---|
| TC-SMOKE-09 | FR-PIPE-01 | Re-based (§5.0): `run_to_completion` over a three-unit run returns `complete`. | Everything downstream |
| TC-SMOKE-10 | FR-PIPE-06 | Re-based: the same run grades every submission. | Everything downstream |
| TC-SMOKE-12 | FR-PIPE-08, NFR-PIPE-03 | `python -m aeh run` over F-DEV-PIPE in a subprocess exits 0 within 60 s on E1, and its stdout JSON has `status == "complete"`. | Release |

### 6.2 System / E2E journeys

- **TC-E2E-02** (re-based, §5.0) is the composed overnight run. Its failure-path variant uses the kill variants through `recover`.
- **TC-E2E-04** is added: *the air-gapped command-line run*. It traces to NFR-SYS-01, whose acceptance form the delta makes demonstrable (delta §4.3).
  - **Where:** E5, networking disabled at the host.
  - **Steps:** `python -m aeh run` over F-SYNTH with `RecordedFixtureProvider`, the socket guard active, then `python -m aeh console` and `GET /`.
  - **Expected:** exit 0; every submission graded; the socket guard records zero outbound connection attempts; the console serves its page.
  - **Failure-path variant:** kill the process at 50% of units, run `python -m aeh recover`, rerun `run`. The §4.3 differential against the uninterrupted run is equal.

### 6.3 User acceptance tests

| UAT ID | Business goal | Role | Scenario (Given/When/Then) | Data | Sign-off criterion |
|---|---|---|---|---|---|
| UAT-09 | NFR-SYS-04, via FR-CONSOLE-34 | Teacher | **Given** a completed run, **when** I click "finalize batch" and one criterion still has an unresolved gate, **then** the page tells me finalization was refused and why, and no grade shows as final. | F-DEV-PIPE with one gate unresolved | A teacher who did not write the test reads the page and correctly says whether grades were finalized, 5 times out of 5 |
| UAT-10 | NFR-CONSOLE-08 | Teacher | **Given** a run started from the console, **when** I close the browser tab and reopen it 10 minutes later, **then** the run is still progressing or complete, and I did nothing to keep it alive. | F-SYNTH subset (50 submissions) | Run status advances with no browser open |

### 6.4 Performance scenarios

| Perf ID | NFR | Load profile | Duration | Dataset | Metric | Threshold | Environment |
|---|---|---|---|---|---|---|---|
| PERF-06 (re-specified) | NFR-INTEG-01 (amended), NFR-AGG-03, NFR-DET-01 | Full run, unchanged | Full run | `F-SYNTH` | Integrity gate time **excluding test-double reads**, as a share of run wall clock | < 1% (unchanged) | E1, and once on E4 |
| PERF-11 | NFR-PIPE-02 | 23,000 ledger units, fixture provider at 0 ms latency, M-PIPE hooks on vs a baseline that calls `progress()` alone | One run each | Synthetic ledger | Added composition time per unit | ≤ 0.25 ms/unit, i.e. 5% of NFR-ORCH-01's 5 ms | E1 CI runner |
| PERF-12 | CT-INTEG-18 | 1,000 `verify` calls on 4-page submissions with 20 spans each, warm cache | < 1 min | F-SYNTH subset | Median `verify` time | ≤ 2 ms. Gated on the CI runner only; the machine is recorded, and elsewhere the result is informational (Q-19). | E1 |
| PERF-13 | NFR-CONSOLE-08 | `POST /actions/start-run` for a 350-submission run | Single request ×20 | F-SYNTH | Response time | Every one of 20 < 1 s | E1 |

### 6.5 Security tests

| Sec ID | Trust boundary | Threat (STRIDE / OWASP) | Probe | Expected defense |
|---|---|---|---|---|
| SEC-16 | Process environment → console socket | Information disclosure | Run TC-CONSOLE-46 rows 2, 3 and 7 in a **subprocess**, with the environment set by the parent. Enumerate the child's listening sockets (`psutil.net_connections` or `netstat` parse). | Zero listening sockets owned by the child. The process exits non-zero with the refusal text. |
| SEC-17 | HTTP → store writes | Elevation of privilege (an undeclared write path) | For every slug in the set difference between `{route segments found by crawling /}` ∪ `{50 generated slugs}` and `CONTROL_SURFACE_ACTIONS`, send `POST /actions/<slug>` under the write audit. | 404 for each, and zero store writes |
| SEC-18 | `python -m aeh run` → network | Information disclosure (egress) | Run TC-SMOKE-12 under the base socket guard, with `HARNESS_PROFILE=edge-local`. AST scan of `aeh/pipeline.py` for imports of `http`, `urllib`, `socket`, `litellm` or any provider SDK. | Zero outbound attempts; zero forbidden imports (CT-PIPE-06, CT-PROV-15) |

### 6.6 Adversarial tests

| Adv ID | Requirement being attacked | Attacker goal | Input | Pass = correct handling **or** visible failure |
|---|---|---|---|---|
| ADV-13 | CT-AGG-20, FR-GRADE-18, FR-REVIEW-18 | Make run B's inflated scores show up in run A's grades, review queue, stats and console (a "re-run until I get a better mark" attack by an operator) | F-DEV-PIPE-TWO-RUN. Run B is a re-run after a key correction with all bands at the top. Then render S9/S12 for run A, `compute_all(A)`, `build_queue(A)` and `aggregation_signals(A)`. | Every run-A artifact is byte-identical to its pre-B snapshot, or the console refuses to render A. Run B's top bands appear in none of them. |
| ADV-14 | CT-CONSOLE-26 | Make the console report success for an action that did not happen | For each of the 14 Phase-1 actions, monkeypatch the owning door to raise `RuntimeError("x")` **after** partially writing (where the door takes a transaction, raise before commit), then POST the action. | `dispatched=False` with text containing `x`, and no partial effect row survives |

### 6.7 Fuzz and property-based tests

| ID | Target | Generator / corpus | Invariant or crash criterion | Examples per run | Seed policy |
|---|---|---|---|---|---|
| FUZZ-08 | FR-ORCH-29, FR-PIPE-04, FR-INTEG-10, CT-INTEG-16 | Hypothesis state machine over one run of 2 submissions × 2 criteria. Rules: a unit becomes terminal (done or quarantined); escalation adds 2 score units; `ready_cells` + M-PIPE hooks run; `verify` is called spuriously; `recover` runs. | At every step: (1) no cell has an `aggregated` phase whose `units_consumed` exceeds its terminal score units; (2) `criterion_score` has at most one row per cell; (3) escalation units per cell are ≤ 2 per escalation event; (4) no extract unit's `attempts` increases on a spurious `verify` with unchanged panel state. At the end, every cell with all score units terminal has `aggregated.units_consumed` equal to that count. | 200 (ci) / 5,000 (nightly) | Hypothesis database committed; a failing seed becomes a regression case |
| FUZZ-09 | FR-INGEST-36/37, CT-INGEST-21 | Random clusters of 1–6 regions of mixed kinds, with resolutions drawn from option ids, undeclared strings, `""` and unicode | Stored `selection_mark` regions satisfy `selection IS NOT NULL ⇔ selection_state = 'resolved'`; no uncaught exception other than `IngestError` | 500 / 10,000 | As FUZZ-08 |

### 6.8 Resilience and failure injection

| ID | Injected failure | Where | Promised behavior (design ref) | Assertion |
|---|---|---|---|---|
| RES-19 | `SIGKILL` of the `python -m aeh console` process 3 s after "start run", then `python -m aeh console` again | Console server + M-PIPE worker thread | NFR-CONSOLE-08, ADR-17, FR-PIPE-09 | After restart, `recover` resumes the run to `complete`. The §4.3 projected tables equal an uninterrupted run's. RPO ≤ 5 s of completed work (base RES-18 bound). |
| RES-20 | The provider returns `ProviderUnavailableError` for 10 minutes of simulated time (`FrozenClock`), then recovers | Mid-Sweep 2 on F-DEV-PIPE | CT-PIPE-04, CT-ORCH-28, FR-ORCH-16 | The run is `paused` within the pass that saw the error, zero units are quarantined, and `resume` → `complete` against the **same** provider (`provider_config` unchanged) |
| RES-21 | Process killed during the `agg_run_scoped_score` rebuild (between `CREATE TABLE criterion_score_new` and `DROP TABLE criterion_score`), simulated by a raising statement hook | Store open on the F-SCHEMA single-run DB | FR-AGG-16, base FR-STORE-02 (forward-only, atomic migrations) | On reopen, either the migration completed with all 45 rows or the file is still at v19 with all 45 rows. No state has zero rows, or both tables. |

### 6.9 Regression and baselines

Base §6.9 applies. For the delta:
- **Baselines regenerated on declared ground only:**
  - TC-REG-02, on the FR-PKG-22 schema bump;
  - TC-STORE-04's F-SCHEMA checksums, one per migration, each with its pin bump.
- **TC-REG-06 is asserted unchanged.**
- **Defect regressions written inline** under `CLAUDE.md`'s defect-fix exception now have plan rows here:
  - GAP-16 → TC-INGEST-50 rows 3–6;
  - GAP-20 → TC-CONSOLE-49;
  - V-3 → TC-INTEG-16's call-2 assertion;
  - V-1 → TC-EXTRACT-16 / TC-JUDGE-26;
  - the FR-ORCH-30 gating defect the design review caught → TC-ORCH-42 arms B and C.

### 6.10 Observability tests

| ID | Promised signal | Trigger | Assertion |
|---|---|---|---|
| OBS-12 | `ProgressReport.alerts` five names (CT-ORCH-27) | TC-ORCH-45 row 9 through `progress()` | Name set equality with the five literals |
| OBS-13 | `extraction_metrics`, `aggregation_signals`, `judge_signals` names (CT-EXTRACT-17, CT-AGG-21, CT-STATS-22) | The composed run from TC-PIPE-01 | Each emitted key set equals its declared literal list. A renamed key fails. |
| OBS-14 | `RunResult.stages[*].detail` is never a bare status (seam 4) | TC-PIPE-01, TC-PIPE-13 | Every `detail` tuple is non-empty, and no element equals `"ok"`, `"success"`, `"done"` or `""` |
| OBS-15 | `run_metrics` new names (FR-ORCH-33) | TC-ORCH-46 | `estimated_cost`, `cost_currency`, `retention_setting`, `resolved_builds` and `wall_clock_ms` are present under those exact names |

### 6.11 Contract suites — the delta's `CT-*` clause cases

`TC-<MODULE>-C<nn>` verifies `CT-<MODULE>-nn`. Columns follow base §6.11. **Breaks if** is the violation that turns the case red while every `FR-*` case stays green.

#### 6.11.1 `M-PIPE` — 7 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-PIPE-C01 | CT-PIPE-01 | surface | `inspect.signature` of `run_to_completion`, `recover` and `main` equals the delta's (parameter names, keyword-only markers, defaults). `python -m aeh --help` exits 0 via `aeh/__main__.py`. **Breaks if** someone renames `run_config` or moves the CLI into a script not reachable by `-m`. | 1 | Exact signature | P1 |
| TC-PIPE-C02 | CT-PIPE-02 | behaviour | After `complete` on F-DEV-PIPE with one induced quarantine, run the invariant query. For every admitted judged pair: `count(criterion_score for run) = 1` **xor** a quarantined extract/score unit exists. For every admitted submission: a current `submission_grade` row for the run. **Breaks if** synthesis or grading is moved to an asynchronous hook that `run_to_completion` does not await, or a quarantined cell also writes a score. | 3 | Invariant | P0 |
| TC-PIPE-C03 | CT-PIPE-03 | behaviour | Call `run_to_completion` again on the completed run under the write audit. Zero writes; `status` equal. **Breaks if** re-entry re-synthesizes or recomputes grades (a new `computed_at`). | 3 | Write audit | P0 |
| TC-PIPE-C04 | CT-PIPE-04 | error | `ProviderUnavailableError` and `BuildChangedError` arms: `RunResult.status == "paused"`, `pause_reason` contains the class name, and `SELECT count(*) FROM work_unit WHERE status='quarantined'` is unchanged from before the error. **Breaks if** M-PIPE catches the error and retries until strikes quarantine. | 3 | Exact | P0 |
| TC-PIPE-C05 | CT-PIPE-05 | state | Safety property — block below | 0 + 3 | Static census + write audit | P0 |
| TC-PIPE-C06 | CT-PIPE-06 | security | Safety property — block below | 0 + 3 | AST scan + call spy | P0 |
| TC-PIPE-C07 | CT-PIPE-07 | behaviour (**non-promise**) | Consumer sweep — block below | 3 | Differential across orders | P1 |

**TC-PIPE-C05 — M-PIPE executes no SQL (safety property).**
- **Rung 0:** AST scan of `aeh/pipeline.py` for `.execute(`, `.executemany(`, `sqlite3`, `Statement(`, and string literals matching `^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE)`. Assert none. Then assert that the SEC-15 `KNOWN_EXECUTE_SITES` census contains no `aeh.pipeline` entry.
- **Rung 3:** run TC-PIPE-01 under `store_spy`. Every executed statement's stack has an owning-module frame (`aeh.orch`, `aeh.agg`, …) below the `aeh.pipeline` frame, and no statement's innermost `aeh.*` frame is `aeh.pipeline`.
- **Adversarial construction:** add to `pipeline.py` a "fast path" `tx.execute("UPDATE work_unit SET status='done' …")` after aggregation, a plausible optimisation that skips `complete()`. Both rungs go red, while TC-PIPE-01 stays green.

**TC-PIPE-C06 — M-PIPE makes no model call itself (safety property).**
- **Rung 0:** AST scan shows `aeh/pipeline.py` imports no `aeh.prov` implementation class and no provider SDK or HTTP client, and calls no `.complete(` on anything except through `ProductionStageExecutor.execute`'s worker hand-off.
- **Rung 3:** wrap `RecordedFixtureProvider.complete` with a spy recording the calling frame. Every call's nearest `aeh.*` frame below the spy is `aeh.extract`, `aeh.judge` or `aeh.synth`; none is `aeh.pipeline`. Every call passed through `GovernedProvider` (its counter equals the spy's count).
- **Adversarial construction:** make `ProductionStageExecutor` call `provider.complete` directly to "save a hop" and pass the text to `persist`. The frame assertion and the governor-count equality both go red, and TC-ORCH-39's ceiling may still pass.

**TC-PIPE-C07 — ready-cell post-processing order is not promised (non-promise).**
- **Consumer sweep:** run F-DEV-PIPE three times with the ready-cell iteration order fixed, reversed, and shuffled under seed 7 (monkeypatched `ready_cells` result order).
- **Assert:** the §4.3 projected tables are equal across all three. M-GRADE totals, M-REVIEW `build_queue` order and M-CONSOLE S9 rows are identical.
- **Breaks if** any consumer starts depending on cell order, for example `rank_score` ties broken by insertion order or `review_queue` rowid used as rank.

#### 6.11.2 `M-ORCH` — 7 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-ORCH-C22 | CT-ORCH-22 | surface | With an executor whose `execute` returns `StageOutcome(status="done")` **without** calling the worker, assert the unit is **not** `done` in the ledger afterwards. The orchestrator does not mark it; only the worker's transaction or `complete()` after `evaluate` does. **Breaks if** the pool callback marks units done from the returned `StageOutcome`. | 2 | Exact state | P0 |
| TC-ORCH-C23 | CT-ORCH-23 | observe | Three calls through `GovernedProvider`: success, success, then a response the worker strikes. Tokens, cost and resolved builds equal the sum over all **three**. Run against `ProductionStageExecutor` and `TransportStageExecutor`. **Breaks if** accrual moves to after `persist`, so struck calls vanish from cost. | 2 | Hand-summed | P0 |
| TC-ORCH-C24 | CT-ORCH-24 | state | `mark_cell_phase` twice → one row. A static census shows `INSERT`/`UPDATE` on `cell_phase` only in `ORCH_STATEMENTS["mark_cell_phase"]`. **Breaks if** M-PIPE or M-INTEG writes the phase directly. | 0 + 2 | Census + row count | P1 |
| TC-ORCH-C25 | CT-ORCH-25 | error | TC-ORCH-44 arm (e): the exception type is `PackageIntegrityError`, it `isinstance` `PackageError`, all four ids are in the message, and zero rows are written in **every** tier (row-count snapshot). **Breaks if** the check moves after the run insert. | 2 | Exact | P1 |
| TC-ORCH-C26 | CT-ORCH-26 | behaviour | TC-ORCH-47 (a)–(c), plus: escalations for `(RA,S1,C1)` and `(RB,S1,C1)` coexist as distinct units. **Breaks if** the key drops `run_id`, so RB's escalation is swallowed as a duplicate of RA's. | 2 | Exact | P0 |
| TC-ORCH-C27 | CT-ORCH-27 | observe | OBS-12 through `progress()`. **Breaks if** an alert is renamed (`orch_cost_warning`) or a sixth is added without a contract bump. | 1 | Set equality | P1 |
| TC-ORCH-C28 | CT-ORCH-28 | error | TC-ORCH-43 (a) and (b): `progress()` returns a `ProgressReport` (no raise), `run.status='paused'`, the unit is `pending`, `attempts` is unchanged. **Breaks if** the exception propagates out of `progress()` (today's behaviour), or the unit is left `leased` until lease expiry. | 2 | Exact | P0 |

#### 6.11.3 `M-EXTRACT` and `M-JUDGE` — 4 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-EXTRACT-C16 | CT-EXTRACT-16 | error | Safety property — block below | 1 + 3 | Exact state | P0 |
| TC-EXTRACT-C17 | CT-EXTRACT-17 | observe | Key set of `extraction_metrics(...)` per criterion equals `{spans_per_unit, empty_result_rate, second_family_disagreement_rate, extraction_latency_p50_ms, extraction_latency_p95_ms}`. **Breaks if** a key is renamed or `None` is replaced by `0.0` for the not-run second family. | 2 | Set equality + None check | P1 |
| TC-JUDGE-C19 | CT-JUDGE-19 | error | Safety property — block below | 1 + 3 | Exact state | P0 |
| TC-JUDGE-C20 | CT-JUDGE-20 | data | TC-JUDGE-25, plus a metamorphic check: insert RB's verdicts **first**, then RA's; the RA result is unchanged. **Breaks if** the run filter is dropped or ordering falls back to rowid. | 2 | Exact tuple | P0 |

**TC-EXTRACT-C16 / TC-JUDGE-C19 — taxonomy errors consume no strike (safety properties).**
- **Rung 1:** TC-EXTRACT-16 / TC-JUDGE-26's taxonomy arms against a stub provider.
- **Rung 3:** RES-20's outage through M-PIPE. Zero quarantined units, and every unit's `attempts` is unchanged across the outage.
- **Adversarial construction:** "simplify" the worker to `except ProviderError as e: self._strike(unit, e); raise`, a plausible tidy-up that keeps propagation but restores the strike. Rung 1 goes red on `attempts`, while TC-ORCH-43's pause assertion still passes. The rung-1 attempts assertion is what catches it.

#### 6.11.4 `M-INTEG` — 3 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-INTEG-C16 | CT-INTEG-16 | behaviour | For each route, snapshot `work_unit`, `review_queue` and `run_metrics` after call 1, then again after call 2 on unchanged inputs. The snapshots are equal, including `attempts`. **Breaks if** `bump_retries` runs unconditionally (V-3), or the review enqueue loses its `OR IGNORE`. | 2 | Snapshot equality | P0 |
| TC-INTEG-C17 | CT-INTEG-17 | surface | Against **both** `StoreExtractionView` and `LedgerEvidenceView`: the public method set equals exactly the five names, and each read raises when its backing read faults. **Breaks if** a view returns `()` on fault (fail-open), or grows a sixth read the gate starts depending on. | 2 | Set equality + raise | P0 |
| TC-INTEG-C18 | CT-INTEG-18 | perf | PERF-12. **Breaks if** the document cache or the index is removed. | 2 | Threshold | P2 |

#### 6.11.5 `M-AGG` — 4 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-AGG-C18 | CT-AGG-18 | state | Safety property — block below | 0 + 3 | Census + audit | P0 |
| TC-AGG-C19 | CT-AGG-19 | behaviour | (a) Two identical `write_score` calls → one row. (b) Inside a transaction, `write_score` then a raising statement → zero rows after rollback. (c) Under the write audit, `write_score` opens no transaction of its own (no `BEGIN` from `aeh.agg`). **Breaks if** `write_score` commits internally "for safety". | 2 | Exact + audit | P0 |
| TC-AGG-C20 | CT-AGG-20 | data | Safety property — block below | 0 + 3 | Static scan + two-run | P0 |
| TC-AGG-C21 | CT-AGG-21 | observe | The key set of `aggregation_signals` per criterion equals the six declared names, with `caps_fired.<cap>` for each cap in `agg`'s cap registry. **Breaks if** a key is renamed or caps are collapsed into a single count. | 2 | Set equality | P1 |

**TC-AGG-C18 — sole judged-score writer (safety property).**
- **Rung 0:** static census of every `Statement` in every `*_STATEMENTS` registry. `INSERT`/`UPDATE`/`REPLACE` into `criterion_score` appears only in `AGG_STATEMENTS["upsert_criterion_score"]` (judged) and M-DET's upsert (deterministic). None appears in `aeh.synth`, `aeh.grade`, `aeh.review`, `aeh.console` or `aeh.pipeline`. The same scan over `tests/support/*.py` flags the seeding helpers named in §4.2; the case is red until they are retired.
- **Rung 3:** TC-PIPE-01 under the write audit. Every `criterion_score` write for a judged criterion originates in `aeh.agg`; every write for a deterministic criterion originates in `aeh.det`.
- **Adversarial construction:** have `GradingService.compute_all` "repair" a missing score by writing a `criterion_score` row with the provisional band. Rung 0 goes red; TC-GRADE cases that assert totals may stay green.

**TC-AGG-C20 — every score read is run-scoped (safety property, breaking).**
- **Rung 0:** SQL scan of every declared statement and every string literal in `aeh/*.py` that reads `criterion_score`. Each has a `run_id` predicate or join. The validated readers `grade.py:780/922/934`, `review.py:544-547/2640`, the console score reads and `det.py:645-653` are named in the failure message.
- **Rung 3:** ADV-13's two-run construction, asserted through M-GRADE, M-REVIEW, M-STATS and M-CONSOLE.
- **Adversarial construction:** add a console "latest score" helper `SELECT … FROM criterion_score WHERE submission_id=?` for a new screen. Rung 0 goes red, and every single-run console case stays green.

#### 6.11.6 `M-DET` and `M-GRADE` — 2 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-DET-C15 | CT-DET-15 | state | Safety property. **Rung 2:** TC-DET-15. **Rung 3:** the TC-PIPE-01 two-run form — run A complete, then run B with a key correction runs `run_to_completion`, and A's deterministic rows stay byte-identical. **Adversarial construction:** `rederive_for_key_change` resolves "the newest run" (today's `_newest_run`, `det.py:258`) when called from a console action on the older run, and rewrites the wrong run. Both rungs go red. | 2 + 3 | Two-run isolation | P0 |
| TC-GRADE-C20 | CT-GRADE-20 | behaviour | TC-GRADE-25 at the contract level: `compute_all(A)` returns an equal `SubmissionGrade` set before and after run B lands, compared field by field. **Breaks if** any grade read drops `run_id`. | 3 | Differential | P0 |

#### 6.11.7 `M-REVIEW` and `M-STATS` — 5 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-REVIEW-C21 | CT-REVIEW-21 | behaviour | Two queued scores identical except `band_spread` 0 vs 2 (equal cost, equal model), store form. The spread-2 row ranks first, and EV > 0 for both when each has one adverse input. **Breaks if** `panel_spread` is read from a default rather than the row. | 2 | Order | P1 |
| TC-REVIEW-C22 | CT-REVIEW-22 | behaviour | Two scores with equal EV inputs, one `holistic` and one `atomic`. Holistic ranks first. This is the rung-3 half of TC-AGG-C09. **Breaks if** `scoring_model` is hard-coded again. | 3 | Order | P1 |
| TC-REVIEW-C23 | CT-REVIEW-23 | data | Every `label.cohort_id` after collection and after migration is a key of the Cohort `cohort` table and not a key of `run`. The purge of cohort K removes K's labels' Tier-C links. **Breaks if** collection writes `run_id` again. | 2 | Set membership | P1 |
| TC-STATS-C22 | CT-STATS-22 | observe | `set(judge_signals(...).fields) == set(JUDGE_SIGNAL_FIELDS)` and the alert name is `judge_contract_violations_concentrated`. **Breaks if** a field is renamed. | 2 | Set equality | P1 |
| TC-STATS-C23 | CT-STATS-23 | behaviour | Safety property. **Rung 0:** TC-STATS-29. **Rung 3:** a store with 30 blind labels (`=0`) plus 30 labels whose flag is NULL and whose teacher band equals the system band. The κ that M-CONSOLE and M-PKG display equals the κ computed over the 30 blind labels alone (F-STATS hand value), and `n = 30`. **Adversarial construction:** restore the permissive predicate "for backward compatibility with pre-column labels". κ rises and n = 60; both rungs go red. | 0 + 3 | Hand value + n | P0 |

#### 6.11.8 `M-CALIB`, `M-INGEST`, `M-PKG` — 3 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-CALIB-C17 | CT-CALIB-17 | state | TC-CALIB-20's restart arm. **Breaks if** registration writes only the in-memory `_CLASS_ROSTERS`. | 2 | Differential | P2 |
| TC-INGEST-C21 | CT-INGEST-21 | data | Safety property. **Rung 2:** TC-INGEST-51 (the trigger) and TC-INGEST-50 rows 4–6 (the door). **Rung 3:** FUZZ-09's invariant over M-DET consumption. **Adversarial construction:** restore the single `update_region_content` statement for "all kinds" to simplify the door. The door arm goes red; the trigger then turns the write into `IngestError`, so the defence-in-depth arm also shows the error at the boundary rather than a stored NULL. | 2 + 3 | Biconditional | P0 |
| TC-PKG-C19 | CT-PKG-19 | data | For the base version, a revision child and an import: `SELECT count(*) FROM criterion WHERE evaluation_mode IS NULL OR evaluation_mode NOT IN ('judged','deterministic')` = 0. **Breaks if** `_REVISION_COPY_KEYS` omits the column, or export drops it. | 2 | Count | P0 |

#### 6.11.9 `M-CONSOLE` — 4 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-CONSOLE-C25 | CT-CONSOLE-25 | surface | TC-CONSOLE-43's three GETs over the real socket. **Breaks if** the server answers plain text (today's child) or a catch-all route returns 200. | 3 | Exact HTTP | P0 |
| TC-CONSOLE-C26 | CT-CONSOLE-26 | state | Safety property — block below | 3 | Effect row ⇔ `dispatched` | P0 |
| TC-CONSOLE-C27 | CT-CONSOLE-27 | security | Safety property — block below | 2 + 4 | Socket enumeration | P0 |
| TC-CONSOLE-C28 | CT-CONSOLE-28 | error | Safety property — block below | 3 | Absence of zero | P0 |

**TC-CONSOLE-C26 — no success over a swallowed exception (safety property).** Rung 3 runs TC-CONSOLE-44's sweep and ADV-14. The assertion is the biconditional `dispatched=True ⇔ effect row present`, over both arms of all 14 actions. **Adversarial construction:** wrap `perform` in `try: … except Exception: log; return ActionResult(dispatched=True)` "so the page never 500s". Every refusal arm goes red. Rendering cases stay green.

**TC-CONSOLE-C27 — cloud-hosted binds nothing (safety property).**
- **Rung 2:** TC-CONSOLE-46 rows 2, 3 and 7.
- **Rung 4:** SEC-16 in a subprocess.
- **Row 3 is the contract's teeth:** `cfg` naming a non-cloud profile must not unlock the socket. Design 1.5.1 resolved Q-15 in this direction (FR-CONF-14: the environment wins), so the case is consistent with FR-CONSOLE-36.
- **Adversarial construction:** read `HARNESS_PROFILE` from the merged dict, where `cfg` wins, "so tests can override the environment". Row 3 goes red.

**TC-CONSOLE-C28 — unreadable renders as unreadable, never zero (safety property).** TC-CONSOLE-47 (a), repeated for each service-backed screen (S2, S3, S9, S12) by dropping the table that screen's service reads. **Adversarial construction:** reintroduce `except sqlite3.OperationalError: return []` in a service adapter "for fresh stores with no runs yet". The S9 arm renders `0` and goes red.

#### 6.11.10 `M-CONF` — 2 clauses

| Case | Clause | Kind | What the case does, and the violation it catches | Rung | Oracle | Pri |
|---|---|---|---|---|---|---|
| TC-CONF-C15 | CT-CONF-15 | behaviour | Run TC-CONF-21 rows 2, 4 and 7 through **each** entry point (`main(["run", ...])`, `main(["recover", ...])`, `serve_console`), with a spy on `effective_config`. Each entry point calls it exactly once per resolution and yields the environment-selected profile. **Breaks if** any entry point merges `{**snapshot, **cfg}` (the file wins), or reads `HARNESS_PROFILE` from `cfg` before composing. **Adversarial construction:** keep the console's `cfg`-only read (today's `console.py:4167`) "for tests"; the `serve_console` arm of row 2 goes red. | 0 + 3 | Exact profile per entry point | P0 |
| TC-CONF-C16 | CT-CONF-16 | behaviour | TC-CONF-22. **Breaks if** `recover` rebinds the paused run to the environment's profile, resuming it on the wrong grader, or raises and abandons the other runs. | 3 | Exact state | P0 |

### 6.12 Blast-radius regression sets (delta rows)

This table adds to base §6.12. When the delta adds consumers to an existing row, they are appended to that row.

| Module changed | Suites that must re-run (delta additions) |
|---|---|
| M-PIPE (new) | §6.11.1 (TC-PIPE-C01…C07); M-CONSOLE integration and TC-REQ-99; TC-E2E-02, TC-E2E-04, TC-SMOKE-09, TC-SMOKE-10, TC-SMOKE-12 |
| M-ORCH | + §6.11.2 delta cases; + all M-PIPE cases; TC-REQ-90 |
| M-EXTRACT | + TC-EXTRACT-C16, TC-EXTRACT-C17; TC-REQ-91; RES-20 |
| M-JUDGE | + TC-JUDGE-C19, TC-JUDGE-C20; TC-REQ-92; RES-20 |
| M-INTEG | + TC-INTEG-C16…C18; TC-REQ-93; FUZZ-08; PERF-06 |
| M-AGG (**CT-AGG 2.0**) | + TC-AGG-C18…C21; TC-REQ-94; **the full integration suites of M-GRADE, M-REVIEW, M-STATS, M-CONSOLE and M-INTEG** (breaking change obligation); ADV-13 |
| M-DET | + TC-DET-C15; M-GRADE and M-CONSOLE S12 integration |
| M-GRADE | + TC-GRADE-C20; TC-REQ-95 |
| M-REVIEW | + TC-REVIEW-C21…C23; TC-REQ-97 |
| M-STATS | + TC-STATS-C22, TC-STATS-C23 |
| M-INGEST | + TC-INGEST-C21; FUZZ-09; M-DET integration |
| M-PKG | + TC-PKG-C19; TC-ORCH-48; TC-REG-02 |
| M-SETUP | + TC-REQ-98 |
| M-CONF | + TC-CONF-C15, TC-CONF-C16, TC-CONF-20, TC-CONF-21, TC-CONF-22, TC-CONF-23; TC-REQ-100, TC-REQ-102, TC-CONSOLE-46 |
| M-SYNTH | + TC-REQ-96 |
| M-CONSOLE | + TC-CONSOLE-C25…C28; SEC-16, SEC-17; ADV-14 |
| `pyproject.toml` / packaging | TC-STORE-26, TC-PIPE-12, TC-SMOKE-12 |

### 6.13 `Requires` pairwise integration cases (delta)

All run at rung 3 against the real provider unless marked.

| Case | Consumer | Provider | Clause(s) | Assertion | Rung |
|---|---|---|---|---|---|
| TC-REQ-90 | M-PIPE | M-ORCH | CT-ORCH-03, CT-ORCH-22, CT-ORCH-23, CT-ORCH-24, CT-ORCH-25, CT-ORCH-26 | M-PIPE's actual usage: it calls `resume` with no arguments and expects a no-op on a healthy run; binds an executor and never marks units itself; reads governed counters from `run_metrics`; writes phases only via `mark_cell_phase`; surfaces `PackageIntegrityError` from `create_run` as exit 1; passes three-element escalation keys. A recording proxy over the real `Orchestrator` shows no other entry points used. | 3 |
| TC-REQ-91 | M-PIPE | M-EXTRACT | CT-EXTRACT-16 | The executor lets a taxonomy error propagate to the dispatch pass (it does not catch and convert it), which is what CT-ORCH-28 needs. Real `ExtractionWorker`, F-TAXONOMY. | 3 |
| TC-REQ-92 | M-PIPE | M-JUDGE | CT-JUDGE-19, CT-JUDGE-20 | As TC-REQ-91 for `dispatch`. M-PIPE passes `verdicts_for`'s tuple to `aggregate` unmodified: no re-sort, no filter. | 3 |
| TC-REQ-93 | M-PIPE | M-INTEG | CT-INTEG-16, CT-INTEG-17 | M-PIPE constructs `IntegrityGate` with `StoreExtractionView` (not a test view), and its double call per cell leaves `attempts` as after one call | 3 |
| TC-REQ-94 | M-PIPE | M-AGG | CT-AGG-01, CT-AGG-18, CT-AGG-19 | M-PIPE calls `aggregate` outside any transaction (purity: no store handle passed), and `write_score` inside the same `tx` as `enqueue_escalation` and `mark_cell_phase`, asserted by rolling that `tx` back and finding none of the three | 3 |
| TC-REQ-95 | M-PIPE | M-GRADE | CT-GRADE-14, CT-GRADE-20 | M-PIPE never writes `submission_grade` (audit), and calls `compute_all(run_id)` with the run it drove, never another | 3 |
| TC-REQ-96 | M-PIPE | M-SYNTH | CT-SYNTH-05 | M-PIPE tolerates "no narrative for an incomplete submission" without treating it as a failure: the run completes and no stage `detail` reports an error for S3 in TC-PIPE-06 (b) | 3 |
| TC-REQ-97 | M-CONSOLE | M-REVIEW | CT-REVIEW-04, CT-REVIEW-21, CT-REVIEW-22 | The console renders `build_queue`'s order and header figures verbatim. Reordering in the console, e.g. by `rank_position`, is detected by comparing S9 row order to the service tuple. | 3 |
| TC-REQ-98 | M-CONSOLE | M-SETUP | the CT-SETUP steps clauses | S3/S4/S5 render exactly `steps()`'s blocking and optional steps, in its order, with blocking steps not skippable in the UI | 3 |
| TC-REQ-99 | M-CONSOLE | M-PIPE | CT-PIPE-01, CT-PIPE-04 | "Start run" calls `run_to_completion` on a server-owned thread, and S6/S7 show `paused` with the reason when CT-PIPE-04 fires | 3 |
| TC-REQ-100 | M-CONSOLE | M-CONF | CT-CONF-05 | The console's resolved config is obtained through `environment_snapshot` (spy), and `resolve_run_config` receives it inside `cfg`. `os.environ` does not appear in `console.py` (static). | 2 |
| TC-REQ-101 | M-PIPE | M-DET | base CT-DET clauses on `evaluate` (Q-24) | For deterministic units, M-PIPE calls `evaluate(run_id, submission_id, criterion_id)` and then `complete()`, and never writes a deterministic score itself | 3 |
| TC-REQ-102 | M-PIPE | M-CONF | CT-CONF-05 (Q-24) | `main` obtains the environment only via `environment_snapshot` | 2 |
| TC-REQ-103 | M-REVIEW | M-PKG | base CT-PKG clauses on criterion and grade-policy reads (Q-24) | `scoring_model`, weight and `distance_to_nearest_boundary` are read for the **run's** package version. With two versions differing in `scoring_model`, the queue for a run on v1 uses v1. | 3 |

---

## 7. Traceability, coverage and residual risk

### 7.1 Requirements traceability matrix (delta)

Built by walking delta §3 and the D-decisions in order, not by walking the cases. Status is **Not run** for every row: the code does not exist yet, so every case is written ahead.

| Requirement ID | Requirement (short) | Module | Test Case ID(s) | Level(s) | Priority |
|---|---|---|---|---|---|
| FR-PIPE-01 | `run_to_completion` drives to predicate or pause | M-PIPE | TC-PIPE-01, TC-PIPE-13, TC-PIPE-14, TC-SMOKE-09 | Integration(3), Unit | P0 |
| FR-PIPE-02 | Stage doors execute units; payload before done | M-PIPE | TC-PIPE-02, TC-PIPE-C02, TC-REQ-101 | Integration(3) | P0 |
| FR-PIPE-03 | `integrity_pre` once per terminal cell | M-PIPE | TC-PIPE-03 | Integration(3) | P0 |
| FR-PIPE-04 | Aggregation hook order, one transaction | M-PIPE | TC-PIPE-04, FUZZ-08, TC-REQ-94 | Integration(3), Property | P0 |
| FR-PIPE-05 | Two-verdict fallback | M-PIPE | TC-PIPE-05 | Integration(3) | P0 |
| FR-PIPE-06 | Synthesis then grading on completion | M-PIPE | TC-PIPE-06, TC-SMOKE-10, TC-REQ-96 | Integration(3) | P1 |
| FR-PIPE-07 | `recover` | M-PIPE | TC-PIPE-07, RES-18, RES-19 | Integration(3), Resilience | P0 |
| FR-PIPE-08 | `python -m aeh run` | M-PIPE | TC-PIPE-08, TC-SMOKE-12, TC-REQ-102, TC-E2E-04 | Integration(3), System(4) | P0 |
| FR-PIPE-09 | `recover` / `console` subcommands | M-PIPE | TC-PIPE-09, RES-19 | Integration(3) | P1 |
| FR-PIPE-10 | `StoreExtractionView` five reads | M-PIPE | TC-PIPE-10, TC-INTEG-C17 | Integration(2) | P0 |
| NFR-PIPE-01 | Kill + recover ≡ uninterrupted | M-PIPE | TC-PIPE-11, RES-19 | Integration(3), Resilience | P0 |
| NFR-PIPE-02 | Composition overhead < 5% of scheduling budget | M-PIPE | PERF-11 | Performance | P1 |
| NFR-PIPE-03 | Runs from a clean `pip install .` | M-PIPE | TC-PIPE-12, TC-SMOKE-12 | System(4) | P1 |
| FR-ORCH-27 | Executor seam, `GovernedProvider` | M-ORCH | TC-ORCH-38, TC-ORCH-39, TC-ORCH-C22, TC-ORCH-C23 | Integration(2,3) | P0 |
| FR-ORCH-28 | `cell_phase` table and index | M-ORCH | TC-ORCH-40, TC-ORCH-C24, TC-STORE-04 | Integration(2) | P0 |
| FR-ORCH-29 | `ready_cells` | M-ORCH | TC-ORCH-41, FUZZ-08 | Integration(2), Property | P0 |
| FR-ORCH-30 | Executor-only gate; taxonomy pauses | M-ORCH | TC-ORCH-42, TC-ORCH-43, TC-ORCH-C28, RES-20 | Integration(2) | P0 |
| FR-ORCH-31 | `validate_grade_policy` at `create_run` | M-ORCH | TC-ORCH-44, TC-ORCH-C25, TC-GRADE-C15 | Integration(2) | P1 |
| FR-ORCH-32 | `evaluate_alerts` five alerts | M-ORCH | TC-ORCH-45, TC-ORCH-36, TC-ORCH-C27, OBS-12 | Unit(0) | P1 |
| FR-ORCH-33 | Metrics additions; restart-safe wall clock | M-ORCH | TC-ORCH-46, TC-ORCH-35, OBS-15 | Integration(2) | P1 |
| FR-ORCH-34 | Run-scoped escalation key | M-ORCH | TC-ORCH-47, TC-ORCH-C26, TC-ORCH-C08, TC-REQ-17, TC-REQ-40 | Integration(2,3) | P0 |
| FR-ORCH-35 | Consumers read `evaluation_mode` | M-ORCH | TC-ORCH-48, TC-REQ-50 | Integration(3), static | P1 |
| FR-EXTRACT-11 | Taxonomy errors not strikes | M-EXTRACT | TC-EXTRACT-16, TC-EXTRACT-08, TC-EXTRACT-C16, TC-REQ-91 | Integration(1,2,3) | P0 |
| FR-EXTRACT-12 | `extraction_metrics` | M-EXTRACT | TC-EXTRACT-17, TC-EXTRACT-C14, TC-EXTRACT-C17, OBS-13 | Integration(2) | P1 |
| FR-EXTRACT-13 | `evidence.latency_ms` | M-EXTRACT | TC-EXTRACT-18 | Integration(2) | P2 |
| FR-JUDGE-18 | `verdicts_for` | M-JUDGE | TC-JUDGE-25, TC-JUDGE-C20, TC-REQ-92 | Integration(2) | P0 |
| FR-JUDGE-19 | Taxonomy errors not strikes | M-JUDGE | TC-JUDGE-26, TC-JUDGE-C19, TC-PROV-18 | Integration(1,2,3) | P0 |
| FR-JUDGE-20 | Persist `evidence_assessment`, `latency_ms` | M-JUDGE | TC-JUDGE-27, TC-STORE-04 | Integration(2) | P1 |
| FR-JUDGE-21 | Violation counts as inputs to `judge_signals` | M-JUDGE | TC-JUDGE-28, TC-JUDGE-C16 | Integration(2) | P1 |
| FR-INTEG-09 | Publish `StoreExtractionView` | M-INTEG | TC-INTEG-15, TC-PIPE-10, TC-INTEG-C17, TC-REQ-93 | Integration(2) | P0 |
| FR-INTEG-10 | `verify` idempotent per panel state | M-INTEG | TC-INTEG-16, TC-INTEG-C16, FUZZ-08 | Integration(2), Property | P0 |
| FR-INTEG-11 | Per-run document cache | M-INTEG | TC-INTEG-17, PERF-06, PERF-12 | Integration(2), Performance | P1 |
| FR-INTEG-12 | `idx_document_submission` | M-INTEG | TC-INTEG-18 | Integration(2) | P1 |
| NFR-INTEG-01 | < 1% run wall clock (acceptance form amended) | M-INTEG | PERF-06 | Performance | P1 |
| FR-AGG-13 | All six integrity inputs stored (amended) | M-AGG | TC-AGG-24, TC-AGG-C15 | Integration(2) | P1 |
| FR-AGG-15 | `write_score` | M-AGG | TC-AGG-21, TC-AGG-C19, TC-REQ-26, TC-REQ-94 | Integration(2) | P0 |
| FR-AGG-16 | Run-scoped `criterion_score` rebuild | M-AGG | TC-AGG-22, TC-AGG-C20, RES-21, TC-STORE-04, ADV-13 | Migration(2), Resilience, Adversarial | P0 |
| FR-AGG-17 | `aggregation_signals` | M-AGG | TC-AGG-23, TC-AGG-C21, OBS-13 | Integration(2) | P1 |
| FR-AGG-08 | Distributional-anomaly input has a baseline (§3.14 row, Q-21) | M-AGG | TC-PKG-32 | Integration(2) | P2 |
| FR-DET-11 | Run-scoped deterministic upsert and re-derivation | M-DET | TC-DET-15, TC-DET-C15 | Integration(2,3) | P0 |
| FR-GRADE-18 | Run-scoped grade reads and findings | M-GRADE | TC-GRADE-25, TC-GRADE-C20, TC-REQ-95 | Integration(3) | P0 |
| FR-REVIEW-18 | Stored EV inputs in the store form | M-REVIEW | TC-REVIEW-25, TC-REVIEW-31, TC-REVIEW-C21, TC-REQ-103, TC-AGG-C09 | Integration(1,2) | P1 |
| FR-REVIEW-19 | `scoring_model_for` | M-REVIEW | TC-REVIEW-26, TC-REVIEW-C22 | Integration(2,3) | P1 |
| FR-REVIEW-20 | `review_queue` columns | M-REVIEW | TC-REVIEW-27, TC-STORE-04 | Integration(2) | P1 |
| FR-REVIEW-21 | `label` columns | M-REVIEW | TC-REVIEW-28, TC-STORE-04 | Integration(2) | P1 |
| FR-REVIEW-22 | `label.cohort_id` is a cohort id | M-REVIEW | TC-REVIEW-29, TC-REVIEW-C23 | Integration(2) | P1 |
| FR-REVIEW-02 | Blind reserve before ranking (amended by D-1) | M-REVIEW | TC-REVIEW-30, TC-REVIEW-C01 | Integration(2) | P1 |
| NFR-REVIEW-05 | Honest degradation at any budget (amended by D-1) | M-REVIEW | TC-REVIEW-30, TC-REVIEW-C01 | Integration(2) | P1 |
| FR-STATS-20 | `judge_signals` + concentration alert | M-STATS | TC-STATS-27, TC-STATS-C22, TC-JUDGE-C16, OBS-13 | Integration(2) | P1 |
| FR-STATS-21 | Position bias / self-agreement drivers (Phase 2) | M-STATS | TC-STATS-28 | Integration(3) | P2 |
| FR-STATS-22 | Strict admissibility predicate | M-STATS | TC-STATS-29, TC-STATS-C23, TC-STATS-01 | Unit(0), Integration(3) | P0 |
| FR-STATS-23 | JSONL long-horizon export | M-STATS | TC-STATS-30 | Integration(2) | P2 |
| NFR-STATS-03 | Export amended to JSON Lines | M-STATS | TC-STATS-30 | Integration(2) | P2 |
| FR-STATS-24 | `criterion_override_history` (D-5) | M-STATS | TC-STATS-31 | Integration(2) | P1 |
| FR-CALIB-15 | Persisted dual-scored roster (Phase 3) | M-CALIB | TC-CALIB-20, TC-CALIB-C17 | Integration(2) | P2 |
| FR-INGEST-36 | Per-kind cluster resolution | M-INGEST | TC-INGEST-50, TC-INGEST-C21, FUZZ-09 | Integration(2), Property | P0 |
| FR-INGEST-37 | Biconditional trigger | M-INGEST | TC-INGEST-51, TC-INGEST-C21 | Integration(2) | P0 |
| FR-INGEST-26 | Multi-lineage proposals (amended by D-3) | M-INGEST | TC-INGEST-52 | Integration(2) | P2 |
| FR-PKG-22 | `criterion.evaluation_mode` | M-PKG | TC-PKG-31, TC-PKG-C19, TC-REG-02 | Migration(2) | P0 |
| FR-SETUP-17 | Setup writes the mode; `SCORING_MODELS` | M-SETUP | TC-SETUP-23 | Integration(2) | P1 |
| FR-CONSOLE-33 | Real HTTP server | M-CONSOLE | TC-CONSOLE-43, TC-CONSOLE-C25, TC-CONSOLE-34, TC-CONSOLE-40, TC-CONSOLE-41, SEC-17 | Integration(3), Browser(4) | P0 |
| FR-CONSOLE-34 | Actions wired to doors | M-CONSOLE | TC-CONSOLE-44, TC-CONSOLE-C26, ADV-14, UAT-09, TC-CONSOLE-02, TC-CONSOLE-39 | Integration(3), Adversarial, UAT | P0 |
| FR-CONSOLE-35 | Service-backed screens | M-CONSOLE | TC-CONSOLE-45, TC-REQ-97, TC-REQ-98, TC-CONSOLE-33 | Integration(3) | P1 |
| FR-CONSOLE-36 | Environment-resolved config | M-CONSOLE | TC-CONSOLE-46, TC-CONSOLE-C27, SEC-16, TC-REQ-100, TC-CONSOLE-05 | Integration(2), Security(4) | P0 |
| FR-CONSOLE-37 | No swallowed `OperationalError` | M-CONSOLE | TC-CONSOLE-47, TC-CONSOLE-C28 | Integration(3) | P0 |
| FR-CONSOLE-38 | Too-few qualifier | M-CONSOLE | TC-CONSOLE-48, TC-STATS-04 | Unit(1) | P1 |
| FR-CONSOLE-39 | Current revision | M-CONSOLE | TC-CONSOLE-49 | Integration(2) | P1 |
| NFR-CONSOLE-08 | Start run returns < 1 s; run survives console death | M-CONSOLE | PERF-13, RES-19, UAT-10, TC-REQ-99 | Performance, Resilience | P1 |
| FR-STORE-15 | `pyproject.toml` packaging | M-STORE | TC-STORE-26, TC-PIPE-12 | Unit(0), System(4) | P1 |
| FR-CONF-13 | Per-profile config sections | M-CONF | TC-CONF-20 | Unit(0) | P0 |
| FR-CONF-14 | `effective_config`: environment over file | M-CONF | TC-CONF-21, TC-CONF-C15, TC-CONSOLE-46 | Unit(0), Integration(3) | P0 |
| FR-CONF-15 | A profile switch never rebinds a resumed run | M-CONF | TC-CONF-22, TC-CONF-C16 | Integration(3) | P0 |
| FR-CONF-16 | Entry points print the profile and its source | M-CONF | TC-CONF-23 | Integration(3) | P1 |
| NFR-SYS-01 | No-network pipeline, acceptance form now demonstrable | system | TC-E2E-04, SEC-18 | System(4) | P0 |

**Coverage.** All 60 added requirements and the 7 amended base requirements have at least one case. Each has a negative or boundary variant, except FR-EXTRACT-13 (a single-value case, P2, deliberately). Of the rows, 21 are P0.

### 7.2 What passing this delta proves

1. **The pipeline is composed, not simulated.** TC-E2E-02 and TC-SMOKE-09/10 run through `run_to_completion` over the real stage doors, and TC-PIPE-C02's invariant holds over the result. No test-support aggregation walk remains in any e2e path (TC-AGG-C18's rung-0 census fails while one does).
2. **Composition is crash-safe at every hook boundary we named.** TC-PIPE-11 covers seven boundaries with an exact differential oracle. RES-19 covers a real `SIGKILL` of the served console.
3. **Run scoping holds against the attack most likely to break it.** ADV-13 and the two-run cases assert byte-identical run-A artifacts through M-DET, M-GRADE, M-REVIEW, M-STATS and M-CONSOLE, and TC-AGG-C20's static scan names every reader.
4. **Provider outages cost pauses, not work.** Taxonomy errors are asserted at the worker (rung 1), in the dispatch pass (rung 2) and through composition (rung 3).
5. **The console tells the truth on a real store.** The 14 Phase-1 actions are swept in both arms, with the biconditional effect ⇔ `dispatched`. Unreadable views never render zero. The cloud profile in the environment binds nothing, verified in a subprocess.
6. **Contract half.** 39 of 39 new clauses have a verifying case. The 12 safety-shaped clauses are verified at two rungs with an adversarial construction each. The one non-promise (CT-PIPE-07) has a three-order consumer sweep. All 11 added `Requires` cases run at rung 2+, plus 3 for the edges the design has no row for. The three contract amendments re-verify every named consumer (§6.12).

### 7.3 What it does not prove

1. **The overnight budget.** NFR-SYS-05 on E4 is still PERF-10 alone, run manually. PERF-11 bounds composition overhead on E1 only.
2. **E1 perf numbers are machine-dependent.** PERF-12 is gated on the CI runner only (Q-19).
3. **In-instance document tamper.** FR-INTEG-11 verifies the hash once per cached entry. Bytes swapped on disk during a run are not re-detected within one `IntegrityGate` instance (Q-18). The single-read assertion *proves* this window exists rather than closing it.
4. **Profile switching covers new runs and new processes.** A running console re-reads the process environment at action time, but an operator's shell cannot usually change a running process's environment, so in practice a switch is a restart. TC-CONF-21 proves the per-action re-read in-process; it cannot prove the shell updated the process.
5. **Phase 2/3 items** (FR-STATS-21, FR-CALIB-15, D-3) have one case each at P2, and they are verified against recorded fixtures, not live models.
6. **The review-ranking defaults** (45 s / 90 s, override min-n 5) are tested as configured values, not as good values (design Q-D4).
7. **Browser-level facts** remain the base's three cases (TC-CONSOLE-40/41 and the service-worker check). The new server is verified over `http.client` at rung 3, not in a browser, except where those three cases run.
8. **Doubles.**
   - `TransportStageExecutor` cannot reproduce CT-ORCH-22, so governor suites prove nothing about payload-before-done.
   - The storeless console double cannot reproduce CT-CONSOLE-26.
   - Both exemptions have named rung-3 cover (§4.9), and nothing else.
9. **Three dependency edges have no design clause** (Q-24). They are verified here against base clauses. If a later change weakens one of those base clauses, the consumer's reliance is not flagged by any delta Consumers column.
10. **Multi-run upgrades.** FR-AGG-16 refuses stores with multiple runs and score rows (TC-AGG-22 b). The plan proves the refusal; it does not prove any operator can recover such a store (design Q-D6).
11. **Migration of unresolvable label rows** (Q-16) is untested until the design answers.

### 7.4 Known gaps and compensating controls

| Gap | Why untestable (or untested) | Compensating control |
|---|---|---|
| NFR-SYS-05 on reference hardware with the composed pipeline | E4 is manual, once per release | PERF-10 with the composed pipeline, plus PERF-11 on every push as an early signal; `wall_clock_ms` (FR-ORCH-33) now survives restarts, so the release run's figure is trustworthy |
| Q-15 console profile precedence | Resolved (design 1.5.1) | TC-CONF-20, TC-CONF-21, TC-CONF-22, TC-CONF-23, TC-CONF-C15, TC-CONF-C16, TC-CONSOLE-C27, SEC-16 |
| Q-18 in-run tamper window | The design is silent | Blob store permissions (base FR-STORE owner-only) and the per-run cache lifetime bound the window to one gate instance; **accepted risk until answered** |
| Q-16 unresolvable legacy label rows | The design is silent | TC-REVIEW-29 covers resolvable rows; the migration is not scheduled until answered |
| Multi-run legacy stores (Q-D6) | By design, no automatic attribution | TC-AGG-22 (b) proves a loud, non-destructive refusal |
| FR-STATS-21, FR-CALIB-15, D-3 before their phase | Not yet due | Scheduled with their phase (§8.2 TS-100…TS-102) |

**Mechanical check.** Run it against both design documents, so that base IDs the plan cites resolve:

```bash
python .claude/skills/create-test-plan/scripts/check_traceability.py   --design docs/design/detailed-design.md docs/design/fix_gaps_detailed_design_plan.md   --plan docs/design/test-plan.md docs/design/gap_fix_test_plan.md
```

Against the delta alone (`--design docs/design/fix_gaps_detailed_design_plan.md --plan docs/design/gap_fix_test_plan.md`) every delta requirement and clause is covered. The only report is six base IDs this plan cites that the delta file does not mention (FR-INGEST-10, FR-STORE-02, NFR-AGG-03, NFR-DET-01, NFR-SYS-04, NFR-SYS-05). Each exists in the base design.

**Base-design IDs cited by the delta and covered in `test-plan.md`, not re-derived here.** The delta names these while specifying its own requirements. Their cases live in the base plan and are re-run by §6.12's blast-radius rows; they are listed so the traceability check does not report them as uncovered.

| Cited base ID | Where the delta cites it | Base-plan cases |
|---|---|---|
| FR-AGG-06 | FR-REVIEW-19 / CT-REVIEW-22 (holistic ranking) | TC-AGG-07 |
| FR-AGG-12 | FR-PIPE-05 (two-verdict fallback) | TC-AGG-12, RES-08 |
| FR-AGG-14 | CT-AGG-18 (M-SYNTH writes no score) | TC-AGG-16 |
| FR-CONSOLE-04 | FR-CONSOLE-33 (chunked upload) | TC-CONSOLE-04 |
| FR-CONSOLE-25 | FR-CONSOLE-34 (paraphrase action present-and-unavailable) | TC-CONSOLE-25 |
| FR-GRADE-01 | FR-PIPE-06 | TC-GRADE-01, TC-GRADE-24, TC-SMOKE-10 |
| FR-ORCH-01 | ADR-15 (no new `work_id` inputs) | TC-ORCH-01, TC-ORCH-34, FUZZ-06, TC-REG-06 |
| FR-ORCH-03 | NFR-PIPE-01, CT-PIPE-03 | TC-ORCH-03, TC-ORCH-04 |
| FR-ORCH-05 | FR-PIPE-03, FR-ORCH-30 (Sweep-2 gate) | TC-ORCH-06 |
| FR-ORCH-12 | FR-PIPE-01 (completion predicate) | TC-ORCH-22 |
| FR-ORCH-19 | ADR-14 (residency batching kept) | TC-ORCH-23, RES-13 |
| FR-ORCH-21 | ADR-14 (in-flight cap kept) | TC-ORCH-24 |
| FR-ORCH-22 | CT-PIPE-02 (admitted submissions) | TC-ORCH-25 |
| FR-ORCH-26 | FR-PIPE-05 | TC-ORCH-21, RES-08 |
| FR-REVIEW-03 | FR-REVIEW-18 (EV inputs) | TC-REVIEW-02, TC-REVIEW-03 |
| FR-STORE-08 | delta §1.1 (declared SQL only) | TC-STORE-15, SEC-15 |
| NFR-CONSOLE-02 | ADR-17 (no toolchain) | TC-CONSOLE-34 |
| NFR-CONSOLE-03 | NFR-CONSOLE-08, ADR-17 | TC-CONSOLE-35, RES-16 |
| CT-AGG-15 | FR-AGG-17 (emitter) | TC-AGG-C15 |
| CT-EXTRACT-14 | FR-EXTRACT-12 (emitter) | TC-EXTRACT-C14 |
| CT-GRADE-15 | FR-ORCH-31 | TC-GRADE-C15 |
| CT-INGEST-05 | FR-INGEST-37 (defence in depth) | TC-INGEST-C05 |
| CT-JUDGE-16 | FR-JUDGE-21, FR-STATS-20 (emitter) | TC-JUDGE-C16 |
| CT-PROV-10 | CT-PIPE (test double is `RecordedFixtureProvider`) | TC-PROV-C10 |
| CT-PROV-11 | ADR-14 (governed provider sees every call) | TC-PROV-C11 |
| CT-STATS-09 | D-5 (FR-STATS-24 gives it a requirement) | TC-STATS-C09 |

### 7.5 The strongest remaining risk, named out loud

**The most likely way this ships broken despite a green suite is that the composed run is green on F-DEV-PIPE and F-SYNTH, but on a real overnight run a cell's panel completes after the aggregation hook has already consumed a partial count.** For example, an escalation's third verdict lands in the same pass as `ready_cells` evaluation. The cell would then be aggregated twice, with a stale first score briefly visible to a console poll. FUZZ-08's state machine is built to find exactly that interleaving, but it runs on 2×2 cells with a synchronous executor, not under real pool concurrency.

**Mitigations:**
- FUZZ-08 at 5,000 examples nightly;
- TC-ORCH-39's concurrent executor, extended with a `ready_cells` probe between barriers;
- PERF-10's manual release run on E4, which exercises real concurrency;
- `cell_phase.units_consumed`, which makes a double aggregation visible in the ledger rather than silent.

### 7.6 Contract traceability matrix (delta)

| Clause | Kind | Verified by | Also run against | Consumers | Re-run on change to |
|---|---|---|---|---|---|
| CT-PIPE-01 | surface | TC-PIPE-C01, TC-REQ-99 | — | M-CONSOLE, operator | M-PIPE |
| CT-PIPE-02 | behaviour | TC-PIPE-C02, TC-E2E-02 | — | M-GRADE, M-REVIEW, M-CONSOLE | M-PIPE, M-ORCH, M-AGG, M-GRADE |
| CT-PIPE-03 | behaviour | TC-PIPE-C03, TC-PIPE-11 | — | operator | M-PIPE |
| CT-PIPE-04 | error | TC-PIPE-C04, RES-20, TC-REQ-99 | — | M-CONSOLE | M-PIPE, M-ORCH |
| CT-PIPE-05 | state | TC-PIPE-C05 | — | M-STORE, SEC-15 | M-PIPE |
| CT-PIPE-06 | security | TC-PIPE-C06, SEC-18 | — | M-PROV | M-PIPE |
| CT-PIPE-07 | behaviour (NP) | TC-PIPE-C07 | three iteration orders | all | M-PIPE, M-REVIEW, M-GRADE, M-CONSOLE |
| CT-ORCH-22 | surface | TC-ORCH-C22, TC-ORCH-38, TC-REQ-90 | — (`TransportStageExecutor` exempt, §4.9) | M-PIPE | M-ORCH |
| CT-ORCH-23 | observe | TC-ORCH-C23 | `TransportStageExecutor` | M-STATS, ops | M-ORCH |
| CT-ORCH-24 | state | TC-ORCH-C24, TC-REQ-90 | — | M-PIPE | M-ORCH |
| CT-ORCH-25 | error | TC-ORCH-C25, TC-REQ-90 | — | M-CONSOLE, M-PIPE | M-ORCH, M-PKG |
| CT-ORCH-26 | behaviour | TC-ORCH-C26, TC-ORCH-C08, TC-REQ-17, TC-REQ-40, TC-REQ-90 | — | M-AGG, M-PIPE, M-INTEG | M-ORCH |
| CT-ORCH-27 | observe | TC-ORCH-C27, OBS-12 | — | M-CONSOLE S7, ops | M-ORCH |
| CT-ORCH-28 | error | TC-ORCH-C28, RES-20 | — | M-PIPE, M-CONSOLE | M-ORCH, M-EXTRACT, M-JUDGE |
| CT-EXTRACT-16 | error | TC-EXTRACT-C16, TC-REQ-91 | stub provider | M-ORCH, M-PIPE | M-EXTRACT |
| CT-EXTRACT-17 | observe | TC-EXTRACT-C17, OBS-13 | — | M-STATS, ops | M-EXTRACT |
| CT-JUDGE-19 | error | TC-JUDGE-C19, TC-REQ-92 | stub provider | M-ORCH, M-PIPE | M-JUDGE |
| CT-JUDGE-20 | data | TC-JUDGE-C20, TC-REQ-92 | — | M-PIPE, M-AGG | M-JUDGE |
| CT-INTEG-16 | behaviour | TC-INTEG-C16, TC-REQ-93, FUZZ-08 | — | M-PIPE | M-INTEG |
| CT-INTEG-17 | surface | TC-INTEG-C17, TC-REQ-93 | `LedgerEvidenceView` | M-PIPE, test doubles | M-INTEG |
| CT-INTEG-18 | perf | TC-INTEG-C18, PERF-12 | — | ops, PERF-06 | M-INTEG |
| CT-AGG-18 | state | TC-AGG-C18, TC-REQ-94 | seeding helpers (census) | M-GRADE, M-REVIEW, M-STATS, M-CONSOLE | M-AGG, M-DET, M-SYNTH, M-GRADE |
| CT-AGG-19 | behaviour | TC-AGG-C19, TC-REQ-94 | — | M-PIPE, M-ORCH | M-AGG |
| CT-AGG-20 | data | TC-AGG-C20, ADV-13 | — | all readers | M-AGG and every reader |
| CT-AGG-21 | observe | TC-AGG-C21, OBS-13 | — | M-STATS, ops | M-AGG |
| CT-DET-15 | state | TC-DET-C15 | — | M-GRADE, M-CONSOLE S12 | M-DET |
| CT-GRADE-20 | behaviour | TC-GRADE-C20, TC-REQ-95 | — | M-PIPE, M-CONSOLE | M-GRADE |
| CT-REVIEW-21 | behaviour | TC-REVIEW-C21, TC-REQ-97 | — | M-CONSOLE | M-REVIEW |
| CT-REVIEW-22 | behaviour | TC-REVIEW-C22, TC-REQ-97 | — | M-AGG (C09), M-CONSOLE | M-REVIEW, M-PKG |
| CT-REVIEW-23 | data | TC-REVIEW-C23 | — | M-STORE purge, M-STATS | M-REVIEW |
| CT-STATS-22 | observe | TC-STATS-C22, OBS-13 | — | ops, M-CONSOLE | M-STATS |
| CT-STATS-23 | behaviour | TC-STATS-C23 | — | M-CONSOLE, M-PKG | M-STATS |
| CT-CALIB-17 | state | TC-CALIB-C17 | — | operator, M-CONSOLE | M-CALIB |
| CT-INGEST-21 | data | TC-INGEST-C21, FUZZ-09 | — | M-DET | M-INGEST |
| CT-PKG-19 | data | TC-PKG-C19 | — | M-ORCH, M-DET, M-GRADE, M-STATS | M-PKG |
| CT-CONSOLE-25 | surface | TC-CONSOLE-C25 | — | browser, operator | M-CONSOLE |
| CT-CONSOLE-26 | state | TC-CONSOLE-C26, ADV-14 | storeless double **exempt** | operator, M-ORCH, M-GRADE, M-REVIEW, M-SETUP | M-CONSOLE and every door owner |
| CT-CONSOLE-27 | security | TC-CONSOLE-C27, SEC-16 | — | operator | M-CONSOLE, M-CONF |
| CT-CONSOLE-28 | error | TC-CONSOLE-C28 | — | teacher, operator | M-CONSOLE, M-REVIEW, M-SETUP |
| CT-CONF-15 | behaviour | TC-CONF-C15 | every entry point | M-PIPE, M-CONSOLE, operator | M-CONF, M-PIPE, M-CONSOLE |
| CT-CONF-16 | behaviour | TC-CONF-C16 | — | M-ORCH, M-PIPE, M-CONSOLE | M-CONF, M-PIPE |
| CT-ORCH-08 (amended) | behaviour | TC-ORCH-C08 (re-specified) | — | base consumers + M-PIPE | M-ORCH |
| CT-CONFORM-14 (D-2) | behaviour | TC-CONFORM-C14 (unchanged) | — | base consumers | M-CONFORM |

**Clause coverage: 39 / 39 new clauses** have a provider-side case, and **30 / 39** are also exercised by a second, independent case (pairwise, cross-cutting or functional). The 9 without one are CT-PIPE-05, CT-PIPE-07, CT-DET-15, CT-REVIEW-23, CT-STATS-23, CT-CALIB-17, CT-PKG-19, CT-CONSOLE-25 and CT-CONSOLE-28. Five of those are safety properties verified at two rungs inside their clause case; the other four have no module consumer that exercises them.

---

## 8. Execution plan and backlog handoff

### 8.1 Sequencing

Test stories follow the design's landing order (delta §4.5) so each lands as a **pair** with its implementing story:
1. **Independent fixes:** TS-103 (profile switching), TS-87, TS-92, and the M-CONSOLE environment half of TS-90.
2. **Schema landing:** TS-88 and TS-95.
3. **Writers:** TS-86 and TS-94.
4. **Composition:** TS-83, TS-84, TS-93 and TS-97.
5. **Console:** TS-90 and TS-91.
6. **Review and stats:** TS-85's alert and metrics rows, and TS-89.
7. **Cross-cutting and journeys:** TS-96, TS-98 and TS-99.
8. **Phase 2/3:** TS-100, TS-101 and TS-102.

**Blocking prerequisites:**
- F-DEV-PIPE and F-DEV-PIPE-TWO-RUN recorded responses, recorded once against a live backend on synthetic input (base F-RECORDED rules).
- The four F-SCHEMA additions, generated by checking out `e0ac5626` and writing through its code.
- An E5 host for TC-E2E-04.

### 8.2 Test stories

**On the last column — the repository is no longer empty.** Base plan §8.2 predates the implementation. Every delta story tests code that **does not yet exist at `e0ac5626`**, so every story is `yes` and carries no dependency, so that the test track can run ahead of the code track. For `/write-tests`, three consequences follow:
- Each new test carries `@pytest.mark.writtenahead`.
- Each story adds a `WRITTEN_AHEAD_BLOCKERS` entry in `tests/support/impl.py`, keyed to its implementing issue once `/plan-to-issues` has numbered it. `/write-tests` owns that entry.
- A **re-specified** base case (§5.0) is edited in place and marked `writtenahead` until its implementing story closes. Its old assertion is not kept alongside, since two suites for one clause is the failure `CLAUDE.md` names.

**Stories that also carry green arms.** A `yes` story may rewrite a base case that is green today. It is `yes` because of its **new** arm only. The named green arms must stay green in the same PR, and `/write-tests` runs them unmarked to confirm that:

| Story | Case | Arm that must stay green (not `writtenahead`) |
|---|---|---|
| TS-87 | TC-EXTRACT-08 | Three failures quarantine; no empty evidence row |
| TS-87 | TC-PROV-18 | Every counter not affected by the 429 rule |
| TS-88 | TC-STORE-04 | Every pre-delta F-SCHEMA version |
| TS-89 | TC-REVIEW-C01 | Every budget arm other than the D-1 floor |
| TS-91 | TC-CONSOLE-02, TC-CONSOLE-39, TC-CONSOLE-C02, TC-CONSOLE-C03 | The storeless-double arm |
| TS-92 | TC-REG-02, TC-REQ-50 | The existing archive and rollup assertions |
| TS-95 | TC-AGG-C15 | The four flags already stored |

The marker goes on the new arm's test function or parametrization, never on the case as a whole.

**Naming the implementing story without blocking the schedule.** Each `WRITTEN_AHEAD_BLOCKERS` entry is keyed by its implementing issue number (the existing entries read `"#96 c09 …"`, `"#107 c15 …"`). `Depends on:` is `—` here, so `/plan-to-issues` should name the implementing `type:story` in the test issue's body under an `Implemented by:` line. It must not use `Depends on:`, which would take the test issue out of the ready set.

**Not stories:** the §5.0 *un-mark* and *turns green* rows. Those markers come off when the implementing issue closes, by the implementer, per `CLAUDE.md`. The seven cases red on `land-stacked-130-146-147` go green when the implementations behind TS-86, TS-90 and TS-91 land; no test story rewrites them.

| Story | Covers | Depends on | Written ahead of implementation? | Phase |
|---|---|---|---|---|
| TS-83 M-PIPE composition — integration | TC-PIPE-01, TC-PIPE-02, TC-PIPE-03, TC-PIPE-04, TC-PIPE-05, TC-PIPE-06, TC-PIPE-13, TC-PIPE-14 | — | yes | 1 |
| TS-84 M-PIPE recovery, CLI and packaging | TC-PIPE-07, TC-PIPE-08, TC-PIPE-09, TC-PIPE-10, TC-PIPE-11, TC-PIPE-12, TC-STORE-26, TC-SMOKE-12 | — | yes | 1 |
| TS-85 M-ORCH delta — executor seam, cell phases, pauses, policy check, alerts, metrics, keys | TC-ORCH-38, TC-ORCH-39, TC-ORCH-40, TC-ORCH-41, TC-ORCH-42, TC-ORCH-43, TC-ORCH-44, TC-ORCH-45, TC-ORCH-46, TC-ORCH-47, TC-ORCH-48, TC-ORCH-35 | — | yes | 1 |
| TS-86 M-INTEG delta — view, idempotency, cache, indexes, gate performance | TC-INTEG-15, TC-INTEG-16, TC-INTEG-17, TC-INTEG-18, PERF-06, PERF-12 | — | yes | 1 |
| TS-87 Workers — provider taxonomy, `verdicts_for`, persisted latency and assessment | TC-EXTRACT-16, TC-EXTRACT-17, TC-EXTRACT-18, TC-JUDGE-25, TC-JUDGE-26, TC-JUDGE-27, TC-JUDGE-28, TC-EXTRACT-08, TC-PROV-18 | — | yes | 1 |
| TS-88 Run-scoped scores — writer, migration, deterministic and grade reads | TC-AGG-21, TC-AGG-22, TC-AGG-23, TC-AGG-24, TC-DET-15, TC-GRADE-25, RES-21, TC-STORE-04 | — | yes | 1 |
| TS-89 M-REVIEW and M-STATS delta | TC-REVIEW-25, TC-REVIEW-26, TC-REVIEW-27, TC-REVIEW-28, TC-REVIEW-29, TC-REVIEW-30, TC-REVIEW-31, TC-STATS-27, TC-STATS-29, TC-STATS-30, TC-STATS-31, TC-REVIEW-C01 | — | yes | 1 |
| TS-90 M-CONSOLE server, environment, qualifier and revision | TC-CONSOLE-43, TC-CONSOLE-46, TC-CONSOLE-48, TC-CONSOLE-49, SEC-16, SEC-17 | — | yes | 1 |
| TS-91 M-CONSOLE actions and screens on a real store | TC-CONSOLE-44, TC-CONSOLE-45, TC-CONSOLE-47, TC-CONSOLE-02, TC-CONSOLE-39, TC-CONSOLE-C02, TC-CONSOLE-C03, UAT-09, UAT-10 | — | yes | 1 |
| TS-92 Ingestion resolution, `evaluation_mode`, setup and baselines | TC-INGEST-50, TC-INGEST-51, TC-INGEST-53, TC-PKG-31, TC-PKG-32, TC-SETUP-23, TC-REG-02, TC-REQ-50 | — | yes | 1 |
| TS-93 Clause suite CS-PIPE | TC-PIPE-C01, TC-PIPE-C02, TC-PIPE-C03, TC-PIPE-C04, TC-PIPE-C05, TC-PIPE-C06, TC-PIPE-C07 | — | yes | 1 |
| TS-94 Clause suites (delta) — M-ORCH, M-EXTRACT, M-JUDGE, M-INTEG | TC-ORCH-C22, TC-ORCH-C23, TC-ORCH-C24, TC-ORCH-C25, TC-ORCH-C26, TC-ORCH-C27, TC-ORCH-C28, TC-ORCH-C08, TC-EXTRACT-C16, TC-EXTRACT-C17, TC-JUDGE-C19, TC-JUDGE-C20, TC-INTEG-C16, TC-INTEG-C17, TC-INTEG-C18 | — | yes | 1 |
| TS-95 Clause suites (delta) — M-AGG v2.0, M-DET, M-GRADE | TC-AGG-C18, TC-AGG-C19, TC-AGG-C20, TC-AGG-C21, TC-AGG-C15, TC-DET-C15, TC-GRADE-C20 | — | yes | 1 |
| TS-96 Clause suites (delta) — M-REVIEW, M-STATS, M-INGEST, M-PKG, M-CONSOLE | TC-REVIEW-C21, TC-REVIEW-C22, TC-REVIEW-C23, TC-STATS-C22, TC-STATS-C23, TC-INGEST-C21, TC-PKG-C19, TC-CONSOLE-C25, TC-CONSOLE-C26, TC-CONSOLE-C27, TC-CONSOLE-C28 | — | yes | 1 |
| TS-97 `Requires` pairwise integration (delta) | TC-REQ-90, TC-REQ-91, TC-REQ-92, TC-REQ-93, TC-REQ-94, TC-REQ-95, TC-REQ-96, TC-REQ-97, TC-REQ-98, TC-REQ-99, TC-REQ-100, TC-REQ-101, TC-REQ-102, TC-REQ-103, TC-REQ-17, TC-REQ-40, TC-REQ-26, TC-REQ-77 | — | yes | 1 |
| TS-98 Journeys and smoke re-based on the composed pipeline, plus the air-gapped CLI journey | TC-E2E-01, TC-E2E-02, TC-E2E-03, TC-E2E-04, TC-SMOKE-09, TC-SMOKE-10, RES-18 | — | yes | 1 |
| TS-99 Cross-cutting delta — performance, resilience, security, adversarial, fuzz, observability | PERF-11, PERF-13, RES-19, RES-20, SEC-18, ADV-13, ADV-14, FUZZ-08, FUZZ-09, OBS-12, OBS-13, OBS-14, OBS-15 | — | yes | 1 |
| TS-100 MVVP measurement drivers | TC-STATS-28 | — | yes | 2 |
| TS-101 Persisted dual-scored roster | TC-CALIB-20, TC-CALIB-C17 | — | yes | 3 |
| TS-102 Multi-lineage assessment proposals (D-3) | TC-INGEST-52 | — | yes | 1 (design landing step 7) |
| TS-103 Switching harness profiles by environment variable | TC-CONF-20, TC-CONF-21, TC-CONF-22, TC-CONF-23, TC-CONF-C15, TC-CONF-C16 | — | yes | 1 |

**Sizing notes.**
- **TS-97** carries 18 cases, but each is one rung-3 assertion over fixtures the other stories build. It is kept whole because the base plan scheduled its `Requires` stories the same way (TS-78…TS-81).
- **TS-94** spans four modules, because each module contributes 2–7 clauses and the suites share the F-TAXONOMY fixture. If review finds it too large, split M-ORCH (8 cases) from the rest.

**What to run next.**

```bash
/plan-to-issues docs/design/
```

`docs/design/` now holds two design documents and two test plans. `/plan-to-issues` must read `detailed-design.md` + `fix_gaps_detailed_design_plan.md` as one design (base, then delta), and `test-plan.md` + this file as one plan (base, then delta). It must also use **this** §8.2 for the TS-83…TS-102 issues, without regenerating TS-00…TS-82, which already exist as issues.

---

## 9. Revision history

| Version | Date | Change | Author |
|---|---|---|---|
| 1.3.1-delta | 2026-09-14 | Design 1.5.1 resolved Q-15 by the user's decision that harness profiles switch by environment variable. Added: <br>• §5.9b TC-CONF-20…23; <br>• §6.11.10 TC-CONF-C15 and TC-CONF-C16; <br>• story TS-103; <br>• the matching RTM and contract rows. <br>TC-CONSOLE-C27 row 3 is no longer expected red. | `/create-test-plan` |
| 1.3-delta | 2026-09-14 | First delta plan, against design delta 1.5 applied on design v1.4. Adds: <br>• 91 cases: 14 M-PIPE, 11 M-ORCH, 7 worker, 4 M-INTEG, 4 M-AGG, 2 run-scoped read cases, 7 M-REVIEW, 5 M-STATS, 1 M-CALIB, 4 M-INGEST, 2 M-PKG, 1 M-SETUP, 1 M-STORE, 7 M-CONSOLE, 1 smoke, 1 E2E, 2 UAT, 3 performance, 3 resilience, 3 security, 2 adversarial, 2 fuzz and 4 observability cases; <br>• 39 clause cases (12 safety-shaped in block form, 1 non-promise sweep) and 14 pairwise cases (TC-REQ-90…103); <br>• RISK-41…59, Q-14…24, and stories TS-83…TS-102. <br>It re-specifies or re-bases 21 rows of base cases (§5.0), 3 of them under the declared-breaking carve-out (§4.9), and leaves TC-CONFORM-C14 and TC-REG-06 explicitly unchanged. <br>Raises four design findings: <br>• Q-15, a contradiction between FR-CONSOLE-36 and CT-CONSOLE-27; <br>• Q-14, no M-PIPE error type; <br>• Q-21, schema additions with no requirement IDs; <br>• Q-24, three dependency edges with no `Requires` row. | `/create-test-plan` |
