# Design ↔ Implementation Gap Analysis

**Baseline.** `origin/main` @ `e0ac5626` (2026-09-14). The unmerged branch `land-stacked-130-146-147` adds 20 test and runbook files and **no `src/` change**, so every code finding below holds on both.

**Design sources.** `docs/agentic-evaluation-harness-for-education.md` (HLD, including the §9 DDL) and `docs/design/detailed-design.md` (DD). Line numbers are `file:line` at the baseline.

**Other sources read.**
- All 173 PRs: bodies and their 9 conversation comments.
- All 178 issues: bodies and 205 comments.
- `docs/findings-register.md`.
- The live `WRITTEN_AHEAD_BLOCKERS` registry.

GitHub returned **zero inline review comments and zero PR reviews** for the repository (`/pulls/comments` is empty repo-wide). The `reviewer` subagent ran locally, so its findings live in the PR bodies.

**How candidates were found.**
1. Every disclosure, finding and "gap" section in PR bodies and PR/issue comments.
2. The ten live written-ahead blockers: tests that are red because a symbol is missing.
3. A mechanical diff of the HLD §9 DDL against the schema a fresh `open_store` actually builds, with all eleven migration contributors imported.
4. A cross-reference of all 745 `FR-*`/`NFR-*`/`CT-*` IDs against `src/` and `tests/`.
5. Targeted reads of the DD requirement rows each candidate touches.

**How each gap was checked.** An entry is listed as a gap only when all three of these hold:
- the design claim is cited with its line;
- the code evidence has a line reference, or comes from a probe I ran;
- the gap is confirmed still open at the baseline.

Candidates that failed that bar are in Appendix B (checked and rejected) or §G (plausible, still needs a probe).

**Out of scope.** No fixes were made and no issues were filed. Per `CLAUDE.md`, `/plan-to-issues` owns issue creation.

**Coverage limit.** This is not a line-by-line proof of all 745 requirements.
- The ID cross-reference found every ID cited somewhere except seven. Those seven were checked, and none is a separate gap:
  - `FR-INGEST-19` is enforced by V2 (`ingest.py:4042`, `:4058`).
  - Five NFRs are release gates or already satisfied.
  - NFR-SYS-01 is blocked by GAP-01.
- Independently, every HLD `R#` is traced to a DD row.
- The findings below are the ones the sources above surfaced and verification confirmed.

**Severity.**
- **Critical:** the system cannot do the thing the design exists for.
- **High:** a designed capability is absent or wrong on real data.
- **Medium:** a designed guarantee is partial.
- **Low:** a local defect, or the design and code disagree on naming or documentation.

**Phase rule.** Every DD requirement row carries a delivery phase (1, 2, 3 or 3.5). A gap against a Phase ≥ 2 requirement is **not yet due**, so its severity is capped at Low and marked "not yet due". The exception is when the gap is a defect in code that has already shipped and breaks a Phase-1 contract; GAP-16 is that case. The Phase column in the summary gives the phase of the requirement each gap is measured against.

---

## Summary

| ID | Sev | Phase | Module | Gap |
|---|---|---|---|---|
| GAP-01 | Critical | 1 | M-ORCH (system) | Nothing in production composes the overnight run: no code chains extraction persistence, integrity, judging persistence, aggregation, synthesis and grading. The one dispatch loop is reachable only through a `transport=` seam that no production caller binds, and it discards model answers. |
| GAP-02 | Critical | 1 | M-AGG | No production writer persists a judged `criterion_score`; `aggregate()` results are never stored. |
| GAP-03 | High | 1 | M-AGG / M-STORE / M-DET | `criterion_score` is not run-scoped (no `run_id`), so a later run silently overwrites an earlier run's scores. `band_spread` and the modal band are not stored. |
| GAP-04 | High | 1 (gate outcome: 3.5) | M-CONSOLE | On a real store, 10 of the 15 HLD §11.8 control actions do nothing (`dispatched=False`), although the owning module surface exists for every one. Amendment, review window and gate outcome live only in process memory. |
| GAP-05 | High | 1 | M-CONSOLE | S2, S5, S9, S10 and S11 query tables or columns that do not exist; the errors are swallowed. S9 shows "Flagged 0" over real flagged scores, and S3/S4 render only counts where HLD §11.5 specifies editable rows. |
| GAP-06 | High | 1 | M-ORCH / packaging | There is no process or restart entry point: nothing calls `resume()` or `sweep_expired_leases()`, and no console script exists. Runtime dependencies are undeclared. |
| GAP-07 | High | 1 (contract) | M-ORCH / M-GRADE | A grade policy that references a missing criterion is not refused at run start (CT-GRADE-15). |
| GAP-08 | Medium | 1 | M-REVIEW | Expected-value ranking inputs are not available from the store: every stored row scores EV = 0, and `scoring_model` is hard-coded `atomic`, so the holistic ranking never fires. |
| GAP-09 | Medium | 1 | M-ORCH | Two of the five designed run alerts do not exist (cost within 10% of ceiling, `cache_hit_rate` collapse), and no alert evaluator exists. |
| GAP-10 | Medium | 1 (contract) | M-AGG / M-EXTRACT / M-JUDGE | The per-criterion and per-judge observability signals contracted by CT-AGG-15, CT-EXTRACT-14 and CT-JUDGE-16 have no emitter. |
| GAP-11 | Medium | 1 (contract) | M-ORCH | `run_metrics` is short of CT-ORCH-20: no estimated cost, one resolved build rather than the set, and a wall clock that restarts with the process. |
| GAP-12 | Medium | 1 | M-SETUP / M-PKG | `criterion.evaluation_mode` does not exist; `kind='mcq'` stands in for it across four modules. |
| GAP-13 | Low (not yet due) | 2 | M-REVIEW / M-STATS | Tier D `label` lacks `assignment_type` and seven other HLD columns, so MVVP step 4 can never produce a per-type figure. |
| GAP-14 | Low (not yet due) | 2 | M-STATS | MVVP steps 2 and 3 are not performed by the module; it only echoes measurements a caller supplies. |
| GAP-15 | Low (not yet due) | 3 | M-CALIB | Dual-scoring roster registration exists only as a test seam; there is no production route. |
| GAP-16 | Medium | 2, but breaks Phase-1 CT-INGEST-05 | M-INGEST | The shipped operator cluster resolution writes `selection_state='resolved'` with a NULL `selection`. |
| GAP-17 | Low | 1 | M-CONSOLE | The agreement block never renders the "too few to draw conclusions from" qualifier below `STATS_MIN_N_FOR_HEADLINE`. |
| GAP-18 | Low | 1 (contract) | M-STATS | A NULL `saw_system_output` is treated as blind (admissible) instead of inadmissible. |
| GAP-19 | Low | 1 (optional) | M-STATS | The optional long-horizon export is JSON, not Parquet/DuckDB (NFR-STATS-03). |
| GAP-20 | Low | 1 | M-CONSOLE | On a real store, `grade_revision(revision=None)` reads revision 1 instead of the latest. |
| GAP-21 | Low | 1 | Schema (all tiers) | Remaining table and column divergences from the HLD §9 DDL not covered above (renames, dropped metadata columns). |
| GAP-22 | High | 1 | M-CONSOLE | The served console is a stub. The configured loopback socket never accepts connections, and a child process answers every request with plain-text `console page`. No HTTP route renders a screen, and the `/assets/console.css` every page links does not exist. |
| GAP-23 | Medium | 1 (security contract) | M-CONSOLE | `CONSOLE_BIND`/`CONSOLE_PORT` and the `cloud-hosted` refusal read only a caller-passed `cfg` dict, never the environment. On a cloud-hosted machine, `serve_console()` with no `cfg` starts. |
| GAP-24 | Medium | 1 | M-INTEG | PERF-06 measured the integrity gate at 2.25% of run wall clock on E1, against NFR-INTEG-01's < 1%. |
| D-1…D-6 | — | — | Design | Contradictions or TBDs inside the design that the code resolved by interpretation; each needs a design decision (§E). |
| DOC-1 | Low | — | Design | Public surfaces and knobs the code relies on that no design document names (§F). |

---

## A. Pipeline composition

### GAP-01 — Nothing in production composes the overnight run — Critical

**Design says.**
- DD §4.2.2 (`detailed-design.md:3111-3146`) specifies the overnight run as one chained flow:
  1. Sweep 1 (`M-EXTRACT`) writes evidence spans.
  2. `M-INTEG` verifies them.
  3. `M-DET` scores deterministic criteria.
  4. Sweep 2 (`M-JUDGE`) produces verdicts.
  5. `M-AGG` computes median band, points once, α and confidence, and returns escalations.
  6. `M-SYNTH` writes L1 then L2 narratives.
  7. `M-GRADE` "appl[ies the] grade policy to every submission automatically", and grades finalize "with zero teacher action overnight".
- Row requirements:
  - FR-JUDGE-11 (`:1635`): "persist one `verdict` row per work unit".
  - FR-GRADE-01 (`:2127`): "compute a `submission_grade` row for every submission in the run automatically".
  - FR-GRADE-10 (`:2136`): "Grades shall finalize automatically on run completion".
  - NFR-SYS-01 (`:3199`): "The full pipeline shall run to completion with no network interface available".
- `CLAUDE.md` seam 1: "The system runs end-to-end from code, returning a structured result plus a per-stage trace."

**Code does.**
- **No production code binds a transport.** The only production constructions of `Orchestrator` are `console.py:4481` (the deterministic-only demo driver) and `extract.py:858` (`Orchestrator(store)`), and neither passes `transport=`. The dispatch path below is therefore reachable only from tests.
- `Orchestrator.progress(run_id)` (`src/aeh/orch.py:4687`) is the only dispatch loop. With a transport bound it runs `_dispatch_pass` (`:4802`), and **even then it composes nothing**:
  - **Extract and score units:** `_run_model_batch` assembles the request, calls `self._transport.call(request)`, accrues token and cost counters in `_absorb_completion` (`:5013-5023`), then calls `self.complete(unit.work_id)` (`:4997`). **The answer is dropped.** No evidence row and no verdict row is written, and no integrity check runs.
  - **Deterministic units:** they are marked done with `self.complete(unit.work_id)` (`:4864`) without invoking `M-DET`, so no deterministic `criterion_score` is written from a run either.
- The stage implementations exist, but none has a production call site:
  - `ExtractionWorker.process` (`extract.py:860`)
  - `IntegrityGate.verify` (`integ.py:877`)
  - `ScoringWorker.dispatch`/`persist` (`judge.py:1698`, `:1794`)
  - `aggregate`/`should_escalate` (`agg.py:580`, `:1116`)
  - `SynthesisWorker.synthesize_submission` (`synth.py:886`)
  - `GradingService.compute_all` (`grade.py:1361`)
- The only exceptions are two console paths:
  - `console.py:4498-4500` is a synthetic, deterministic-only demo driver that seeds its own cohort.
  - `console.py:2406` is the answer-key correction.
- `Orchestrator._maybe_complete_run` does not trigger synthesis or grading.
- End-to-end journeys pass only because test support re-implements the composition. `tests/support/e2e_world.py:976-1180` holds the "aggregation walk" and its own `INSERT OR REPLACE` into `criterion_score`.

**Verification.**
- Read `_run_model_batch` and `_absorb_completion` in full.
- Ran repository-wide `grep` over `src/` for `.process(`, `.persist(`, `.dispatch(`, `.verify(`, `aggregate(`, `should_escalate(`, `synthesize_submission(` and `compute_all(`.
- Corroborated by disclosures:
  - PR #323 (TC-SMOKE-09/10): "no shipped module persists judged scores yet".
  - PRs #341, #342 and #343 (the TC-REQ-26 finding): "no `src` module persists M-AGG's score".
  - PR #339: "nothing in `src/` calls `resume()` or the sweeper".

**Impact.**
- No production path turns uploaded submissions into grades.
- The one dispatch loop that exists would spend model budget, mark every unit `done` and produce no evidence, verdicts, scores, narratives or grades.
- DD §4.2.2, FR-GRADE-01/10 and NFR-SYS-01 cannot be demonstrated outside test scaffolding.

**Architectural fork, to settle before any fix.** The design's Protocols put the model call **inside the stage workers**:
- `ScoringWorker.dispatch(req, judge) -> ScoringResult` and `persist(unit, res)` (DD §3.10, `detailed-design.md:1648-1651`);
- `ExtractionWorker.process(unit)` (`extract.py:860`).

At the same time, M-ORCH's shipped dispatch (#62, PR #288) puts the call in the orchestrator so that the concurrency governor, residency batching and rate-limit counters (FR-ORCH-19/21, CT-PROV-11) see every call. There are two readings:

- **Reading A (matches the DD Protocols).** Workers lease units, call the model, and persist. M-ORCH's `progress()` goes back to being a report and governor that workers consult: concurrency is a lease quota, and counters come from the workers' completions.
- **Reading B (matches the shipped governor).** The orchestrator calls the model, and the workers expose "validate and persist a completion I already hold" doors (the parse and validation half of `dispatch`, plus `persist`). This keeps FR-ORCH-21's in-flight cap exact, but needs a DD change to the M-JUDGE/M-EXTRACT Protocols.

Either reading must end with exactly one model call per unit. The design owner should pick one. The steps below are written for Reading B because it is closest to the shipped governor; under Reading A, the same persistence and aggregation steps move into the worker loop.

**What a fix needs.**
1. **A stage-handler step inside M-ORCH's dispatch (Reading B).** `_run_model_batch` must hand each successful answer to the owning stage's persistence door before `complete()`:
   - `extract`: parse and persist the evidence row with `ExtractionWorker`'s parse and insert path (`parse_spans` plus the evidence insert), reusing the already-assembled request.
   - `score`: parse the reply through the same validation door `ScoringWorker.dispatch` uses, so the response contract, strikes and FR-JUDGE-10's single re-request still apply, then call `ScoringWorker.persist(unit, result)`. Reconcile the worker's strike loop with the ledger's `fail()` so one malformed reply counts as one attempt (NFR-JUDGE-05).
   - `deterministic`: call `DeterministicEvaluator(store)` for that (submission, criterion) instead of a bare `complete()`.
   - **Keep one model call per unit.** The workers currently call the provider themselves, so either give each a "persist a completion I already hold" entry point, or let the orchestrator lend the worker its transport. Never call the model twice.
2. **Integrity after extraction.** When every extract unit of a (submission, criterion) is done, call `IntegrityGate.verify(run_id, submission_id, criterion_id)`. Its routing writes are already the gate's own.
3. **The aggregation step.** When a cell's panel is complete:
   - load its verdicts and call `aggregate(verdicts, criterion, signals)`;
   - persist the score (GAP-02);
   - evaluate `should_escalate` and, when it fires, call `enqueue_escalation` **in the same transaction** as the score write. DD §3.12 "Does not own" (`:1865-1867`) says: "the orchestrator inserts the units, in the same transaction".
   - Re-aggregate when the escalation's units complete, honouring FR-ORCH-26 / FR-AGG-12: with two surviving verdicts, discard the second and mark the result provisional.
4. **On the completion predicate (FR-ORCH-12)**, synthesize per submission (L1 then L2), then call `GradingService.compute_all(run_id)`, then apply FR-GRADE-10's automatic finalization. Record each stage in the result trace (seam 4).
5. **A headless driver**, for example `Orchestrator.run_to_completion(run_id) -> RunResult`. It loops dispatch until the predicate holds and returns a per-stage trace (seam 1). The console's "start run" action (GAP-04) and GAP-06's process entry point both call it.
6. **Tests.** This is `/write-tests`' change, not `/fix-issue`'s.
   - Retire the aggregation walk in `tests/support/e2e_world.py` and the `write_criterion_scores` stand-in in `tests/support/grade_vocabulary.py` in favour of the driver.
   - TC-E2E-01..03, TC-SMOKE-09/10 and TC-REQ-17/26/40 then exercise production composition.
7. **Traces to:** DD §4.2.2; FR-EXTRACT (evidence rows); FR-INTEG; FR-JUDGE-11; FR-AGG-02/11/13; FR-ORCH-12/26; FR-SYNTH; FR-GRADE-01/10; NFR-SYS-01; `CLAUDE.md` seams 1 and 4.

### GAP-02 — Judged criterion scores are never persisted — Critical

**Design says.**
- FR-AGG-02 (`detailed-design.md:1874`): "derive `criterion_score.points` … exactly once".
- FR-AGG-11 (`:1883`): "The module shall write `criterion_score.state`".
- FR-AGG-13 (`:1885`): "record the integrity inputs on the score row … so the confidence is reconstructible from stored data".
- FR-AGG-14 (`:1886`) makes the `criterion_score` write set M-AGG's, disjoint from M-SYNTH's.

**Code does.**
- The only `INTO criterion_score` statements in `src/` are M-DET's (`det.py:646`, `:688`).
- `agg.py` adds columns by migration (`agg.py:1374-1389`: `confidence`, `confidence_base` and the four integrity flags) but declares no insert or upsert statement.
- `aggregate()` is pure and returns an unpersisted score.
- `grade.py`, `review.py`, `stats.py` and `console.py` all read `criterion_score`, so for judged criteria they read nothing, or a test stand-in's rows.

**Verification.** `grep -n "INTO criterion_score" src/aeh/*.py` returns only `det.py`. No production code calls `aggregate`.

**Impact.**
- Judged criteria never reach grading, review, statistics or the console.
- Every real grade counts them as `criteria_missing`, giving an `incomplete` grade. That is FR-GRADE-07's rule firing for the wrong reason.

**What a fix needs.**
- A declared statement in `aeh.agg`, e.g. `AGG_STATEMENTS["upsert_criterion_score"]`. It is keyed by `(run_id, submission_id, criterion_id)` once GAP-03 lands, and writes:
  - `band` (median), `band_spread`, and `points` via `aeh.pkg.points_for_band`, the single band-to-points mapping (CT-PKG-05);
  - `judge_count`, `agreement`, `confidence`, `confidence_base`;
  - `spans_verified`, `evidence_present`, `sufficiency_flag`, `ocr_overlap_risk`;
  - `routing`, `state`.
- A `persist_score(tx, run_id, score)` helper that takes the caller's transaction, so GAP-01's escalation enqueue can share it.
- Add the new execute site to SEC-15's `KNOWN_EXECUTE_SITES` (`tests/artifact/test_store_query_surface.py` fails until it is listed).
- Keep FR-AGG-14's disjointness: M-SYNTH still has no path to `criterion_score`.
- **Traces to:** FR-AGG-02/11/13/14, CT-AGG-06/07, TC-REQ-26.

### GAP-03 — `criterion_score` is not run-scoped and drops `band_spread` — High

**Design says.**
- HLD §9.6 DDL (`agentic-evaluation-harness-for-education.md:2290-2327`) declares:
  - `run_id TEXT NOT NULL`
  - `band_spread INTEGER NOT NULL`
  - `PRIMARY KEY (run_id, submission_id, criterion_id)`
- FR-AGG-01 (`detailed-design.md:1873`): "shall record the modal band and `band_spread`".
- DD §3.12: "`criterion_score` per HLD §9.6".
- The grade ledger is run-scoped by ADR-9 (`:3347-3362`), and the shipped `submission_grade` follows it with PK `(run_id, submission_id, revision)`.

**Code does.**
- The shipped `criterion_score` (store migration 1 at `store.py:1168`, extended by det v9 and agg migrations) has PK `(submission_id, criterion_id)`, **no `run_id`**, and no `band_spread` or modal band column.
  - Probed columns: `submission_id, criterion_id, band, points, judge_count, agreement, state, routing, confidence, confidence_base, spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk`.
- M-DET's upsert is `ON CONFLICT (submission_id, criterion_id) DO UPDATE` (`det.py:645-653`). A second run over the same cohort therefore overwrites the first run's scores.
- `aggregate()` computes `modal_band` and `band_spread` (`agg.py:739-741`) but has no column to store them in.
- PR #308 disclosed the knock-on effect: "neither `criterion_score` nor `review_queue` carries a run id … the cohort is the finest scope the schema offers".

**Verification.** A probe opened a fresh store with all eleven migration contributors and read `PRAGMA table_info` and the primary-key order for `criterion_score` and `submission_grade`.

**Impact.**
- A re-run, a calibration dual-score or a second administration over one cohort destroys earlier scores.
- Run A's grade revisions then recompute from run B's scores.
- Rollup findings and the review queue cannot be run-scoped.
- FR-REVIEW-03's "panel spread" input is unavailable (GAP-08).

**What a fix needs.**
- **A cohort-tier migration** that rebuilds `criterion_score` with `run_id TEXT NOT NULL`, `band_spread INTEGER` (0 for deterministic rows), an optional `modal_band TEXT`, and PK `(run_id, submission_id, criterion_id)`.
  - Backfill `run_id` only where the cohort has exactly one run; otherwise refuse with a named error.
  - Bump `COMPLETE_SCHEMA_VERSIONS[Tier.COHORT]` in the same change (`CLAUDE.md` rule), regenerate the `F-SCHEMA` golden, and update the migration-chain paragraph in `CLAUDE.md`.
- **Update every reader and writer:**
  - the `det.py` upsert and re-derivation;
  - `grade.py` score reads, which must filter by `run_id`;
  - `review.py` store queries (`:544-547`, `:2640`);
  - `console.py` score reads;
  - `integ.py` routing reads;
  - direct seeding in `tests/support/*_vocabulary.py` (a `/write-tests` change).
- **Traces to:** HLD §9.6, FR-AGG-01, ADR-9, FR-ORCH-03.

---

## B. Console (M-CONSOLE)

### GAP-04 — Most control actions are not wired to their owning modules on a real store — High

**Design says.**
- FR-CONSOLE-01 (`detailed-design.md:2829`): "shall effect every change by writing a row the orchestrator reads".
- FR-CONSOLE-21 (`:2854`): "an amendment path shall exist … and shall write a new grade revision".
- FR-CONSOLE-22 (`:2855`): "A configured review window shall delay finalization".
- FR-CONSOLE-23 (`:2856`, Phase 3.5): the provenance gate's "outcome written to the validation record".
- FR-CONSOLE-25 (`:2858`): every §7.9 touchpoint "implemented or rendered as present-and-unavailable naming the version in which it arrives".
- FR-CONSOLE-32 (`:2870`): the write surface is exactly the enumerated control-surface actions.
- HLD §11.8 (`agentic-evaluation-harness-for-education.md:3343-3363`) gives each action's effect. For example:
  - "Approve question inventory — Writes `question` rows and locks them";
  - "Review action — Writes `review_queue.action`, `new_band`, `acted_at`; emits a `label`";
  - "Amend a finalized grade — Writes a new `submission_grade` revision and an `audit_record`".

**Code does.**
- `CONTROL_SURFACE_ACTIONS` (`console.py:387-403`) declares 15 actions.
- On a real store (`data_dir` set), `_write_rows_real` (`:2096`) handles only `pause/resume` itself. `_apply_domain_effects` (`:2133-2251`) handles only `purge cohort`, `finalize batch`, `resolve quarantine item` and `correct an answer key after a run`.
- **Every other action falls through** to `dispatched=False` with "no row the schema admits and no landed domain effect: the owning module performs this write when its story lands" (`:2247-2251`). That covers:
  - approve question inventory
  - supply answer keys
  - accept or correct rubric read-back
  - set review window
  - start run
  - review action
  - blind-sample submission
  - amend a finalized grade
  - approve exemplar paraphrases at export
  - export/import package
- The owning surfaces **exist** (each name checked):
  - `SetupService.confirm_inventory` (`setup.py:2076`), `set_answer_keys` (`:2379`) and `read_back_rubric` (`:2217`) (#50–#53);
  - `GradingService.amend` (`grade.py:1770`);
  - `ReviewService.act` (`review.py:1555`), `act_on_group` (`:1594`) and `blind_sample` (`:1716`);
  - `PackageCatalog.set_exemplar_provenance` (`pkg.py:2422`, the paraphrase-approval write);
  - `aeh.pkg.export_package` (`pkg.py:4360`);
  - `Orchestrator.create_run`/`start` (`orch.py:2189`, `:2571`);
  - `grade_policy.review_window_hours` (ADR-3, shipped column).
- FR-CONSOLE-23's export gate is Phase 3.5, so the "approve exemplar paraphrases" and gate-outcome rows are not yet due. The other eight actions are Phase 1.
- **In-memory-only paths:**
  - `amend_grade` (`console.py:2822-2861`) appends to `self._grade_ledger` and never calls `GradingService.amend`.
  - `set_review_window` (`:2871-2877`) stores `self._review_windows[run_id]`.
  - `record_gate_outcome` (`:2863-2869`) stores `self._gate_outcomes`.
  - None of these survive a restart, and none reaches the store.
- **A silent failure path:** `finalize_batch` wraps `GradingService.finalize_batch` in `contextlib.suppress(Exception)` (`:1965`) and then reports records with `finalized_at=None`, so a refused finalization looks settled.

**Verification.**
- Read `perform`, `_write_rows_real` and `_apply_domain_effects` in full.
- PR #309 disclosed "13 of 15 control actions violating `run_control`'s CHECK (now honest deferrals)"; three have since been wired by #127 and later PRs.

**Impact.** A teacher using the console against a real store cannot confirm setup, key answers, start a run, review, blind-score, amend or export. Each click reports "claims nothing". The teacher-facing half of the product is inert.

**What a fix needs.** Wire each action, one tier and one transaction per action, and keep FR-CONSOLE-02 idempotency. The console must not re-implement domain logic (CT-CONSOLE-21 / NFR-CONSOLE-05).

| Action | Owning call |
|---|---|
| approve question inventory | `SetupService.confirm_inventory(...)` |
| supply answer keys | `SetupService.set_answer_keys(...)` |
| accept or correct rubric read-back | `SetupService.read_back_rubric(...)` and its confirmation step |
| set review window | `aeh.pkg` grade-policy setter writing `review_window_hours` (ADR-3) |
| start run | `Orchestrator.create_run` + `start` (then GAP-01's driver) |
| review action | `ReviewService.act(...)` / `act_on_group(...)` (band only, FR-CONSOLE-07) |
| blind-sample submission | `ReviewService.blind_sample(...)` session record |
| amend a finalized grade | `GradingService.amend(...)`; `amend_grade` reads the resulting revision back from `submission_grade` |
| approve exemplar paraphrases at export (Phase 3.5) | `PackageCatalog.set_exemplar_provenance(...)` plus `package.contains_real_student_text` |
| export/import package | `aeh.pkg.export_package` / import |

- Persist the provenance gate outcome through M-PKG's validation record (FR-CONSOLE-23).
- Replace the `suppress(Exception)` in `finalize_batch` with the refusal-as-outcome pattern the other actions use.
- Where a real owner is genuinely Phase-2+, render present-and-unavailable **with the version named** (FR-CONSOLE-25) rather than the generic "when its story lands".
- Tests: TC-CONSOLE-02/39 and CT-CONSOLE-C02/C03 must drive a real store for each action (`/write-tests`).

### GAP-05 — Several screens read tables that do not exist, and failures are swallowed — High

**Design says.**
- FR-CONSOLE-13 (`:2846`): "The review queue header shall state items flagged, items shown, and items left provisional".
- FR-CONSOLE-19 (`:2852`): the blind reservation subtracted "before ranking".
- FR-CONSOLE-06 (`:2839`): S3/S4 are the two blocking screens.
- FR-CONSOLE-16 (`:2849`): the blind-sample flow.
- FR-CONSOLE-27 (`:2865`): S2 upload.
- HLD §11.5 (`agentic-evaluation-harness-for-education.md`):
  - S3 (`:3073-3089`) shows "What ingestion found, shown for correction": each question with its open/mcq/both control, add and remove controls, and "Confirm — this is my test".
  - S4 (`:3091-3093`) is "One row per MCQ question".
  - S9 (`:3194-3233`) has a header of the form "10 of those 30 are reserved for the blind sample … These are the 40 highest-value items of 790 flagged", plus group items and a band control per item.
  - S10/S11 (`:3235-3241`) are the whole-grade sample of 10–15 auto-accepted grades and the blind marking of 15 random papers.
- `CLAUDE.md` seam 4: no bare success over an empty result.

**Code does.** `_read_cohort_files` catches every exception per ledger and continues (`console.py:1365-1368`), so a bad query renders as "no rows".

| Screen | Query (file:line) | Probe result on a fresh full-chain store |
|---|---|---|
| S9 review queue | `SELECT … FROM review_queue WHERE run_id = :run_id ORDER BY rank_position` (`console.py:2486-2488`) | `OperationalError: no such column: run_id`. `review_queue` has only `queue_id, submission_id, criterion_id, reason` (`store.py:1196-1201`) |
| S9 budget | `_SELECT_REVIEW_BUDGET` … `FROM review_budget` (`console.py:586-589`) | `no such table: review_budget` (exists in no tier) |
| S2 upload | `SELECT path FROM package_file` (`:1529`) | no such table; the page falls back to placeholder names `scan-001.pdf…` (`:1533-1535`) |
| S5 optional | `SELECT setup_step, skipped FROM setup_skip` (`:1515`) | no such table |
| S10 sample | `SELECT submission_id FROM sample_selection` (`:1667-1669`) | no such table; static sentence only |
| S11 blind | `SELECT submission_id FROM blind_sample` (`:1676`) | no such table; static sentence only |
| S3 / S4 | read `question` and `criterion` and render only a **count** (`:1490-1512`) | no inventory items to confirm, no key-entry controls |

TC-CONSOLE-33 (landing-branch run, 2026-09-14) measured the timed queue at `{'flagged': 0, 'shown': 0, 'left_provisional': 0}` "for a run with 800 judged items queued". PR #344 (TC-REQ-77) independently observed "S9 header reads 'Flagged for review: 0' over a store with two provisional scores". PR #325 observed that `rank_position` exists in no migration.

**Verification.** A probe ran the S9 queries against a fresh store opened with all eleven contributors (errors quoted above) and listed every tier's tables for the other names.

**Impact.** On real data the teacher's queue is always empty, the blind flow collects nothing, and the setup screens cannot be completed. The swallowed exception turns a schema bug into an honest-looking zero, which is the seam-4 trap the repo's own conventions name.

**What a fix needs.**
- **S9:** render from M-REVIEW's built queue (`open_review(...)` at `review.py:2709`, `ReviewService.queue(run_id, budget_minutes)` at `review.py:1493`, plus its residual/header report of flagged, shown, left and the reservation) instead of raw SQL. CT-REVIEW-04 names the console as the consumer of that object. Drop `_SELECT_REVIEW_BUDGET`, or read the budget from the M-REVIEW session.
- **S10/S11:** drive `ReviewService` whole-grade sample and `blind_sample` sessions (`review.py:1716`), rendering `ReviewService.render_blind_flow(session_id)` (`review.py:1922`) for S11.
- **S3/S4/S5:** render `SetupService.steps()` and the proposal objects (questions with confirm controls; mcq criteria with key inputs; optional cards with skip state from `setup_step_record`).
- **S2:** list the uploaded blobs from the M-INGEST/blob store record rather than a nonexistent `package_file` table; remove the placeholder fallback.
- **`_read_cohort_files`:** stop swallowing `sqlite3.OperationalError`, or at least surface it in the page's build trace. A missing column is a defect, not an empty ledger.
- **Tests (`/write-tests`):** rung-3 cases must render each screen over a seeded real store and assert non-zero figures (TC-CONSOLE-27..31, TC-REVIEW-18).

---

### GAP-22 — The served console is a stub: no screen is reachable over HTTP — High

**Design says.**
- FR-CONSOLE-05 (`detailed-design.md:2833`) and NFR-CONSOLE-02 (`:2900`): the console "shall require no npm toolchain, no build step, and no network at render time".
- HLD §11.5–§11.7: the console is a local web application a teacher opens in a browser.
- FR-CONSOLE-18 (`:2851`): the page loads with zero requests to other origins, which presumes the page itself loads.

**Code does.**
- `ConsoleServer.__init__` (`console.py:4148-4192`) binds and `listen(4)`s the configured socket (`:4181-4183`) but **never calls `accept()`** on it.
- It then spawns a child running `_CHILD_SCRIPT` (`:4131-4145`). The child binds a *different* ephemeral loopback port and answers every request with `HTTP/1.0 200 OK`, `Content-Type: text/plain`, body `console page`. It never touches the store or `ConsoleApp.render`.
- `serve_console`/`start_console` (`:4215-4237`) return this object.
- Every page links `<link rel="stylesheet" href="/assets/console.css">` (`:663`), and no `console.css` exists anywhere in the repository (`find`).
- Screens render only headlessly, through `ConsoleApp.render(route)`.

**Verification.**
- Read the class.
- On the landing branch, the E1/E6 run of 2026-09-14 (1 h 33 m) failed four cases:
  - TC-CONSOLE-34: `GET /` "answered status=None … TimeoutError: timed out"; `GET /assets/console.css` timed out.
  - TC-CONSOLE-37/40/41 (Playwright): review, blind and student views each ended with "Page.goto: Timeout 5000ms exceeded".
- PR #336 disclosed the stub: "the killed process is the stub server, which holds nothing".

**Impact.** No teacher can use the console in a browser. Every browser-level invariant (FR-CONSOLE-16/17/18, SEC-10/12) is unverifiable, and NFR-CONSOLE-03's "killing the console changes nothing" is vacuously true.

**What a fix needs.**
- One HTTP server on the configured loopback socket, for example `http.server.ThreadingHTTPServer` from the standard library (no dependency, NFR-CONSOLE-02):
  - routes `GET` requests through `ConsoleApp.render(route, **query)` and returns `text/html; charset=utf-8`;
  - routes form `POST`s through `perform(action, **fields)` for the enumerated actions only (FR-CONSOLE-32);
  - streams uploads to the blob store (FR-CONSOLE-04);
  - sets `Cache-Control: no-store` on student views (FR-CONSOLE-17);
  - returns 404 for unknown routes instead of falling through to S1 (PR #325).
- Serve `/assets/console.css` from a packaged file, or inline the CSS and drop the link.
- Keep a child-process topology only if NFR-CONSOLE-03 needs it, and make the child the real server.
- Un-mark nothing: TC-CONSOLE-33/34/37/40/41 are already written and go green once this lands.

### GAP-23 — Console bind and profile refusal ignore the environment — Medium

**Design says.**
- CT-CONSOLE-05 (`detailed-design.md:2939`): the console "**refuses to start** when the deployment profile is `cloud-hosted` … The refusal is in code, not documentation".
- `console.py:147` declares `CONSOLE_BIND`, `CONSOLE_PORT` and `CONSOLE_POLL_INTERVAL_MS` as env-gated knobs (seam 3).

**Code does.**
- `ConsoleServer` checks `config.get("HARNESS_PROFILE")` and `config.get("CONSOLE_BIND")` only on the `cfg` dict argument (`console.py:4166-4173`). `serve_console`/`start_console` pass `cfg` through unchanged (`:4215-4237`), and no `os.environ` read exists on that path.
- TC-CONSOLE-05 (landing branch run) observed:
  - "with CONSOLE_BIND=::1 in the environment the console bound '127.0.0.1'";
  - "start_console() started a console … on a machine whose deployment profile is HARNESS_PROFILE=cloud-hosted".

**What a fix needs.**
- Resolve the effective config as the explicit `cfg`, else the environment, else the module defaults.
- Evaluate the `cloud-hosted` refusal against the resolved deployment profile (M-CONF's resolution of `HARNESS_PROFILE`), before any bind.
- Read `CONSOLE_BIND`/`CONSOLE_PORT` at call time.
- Keep the non-loopback refusal after the profile check (CT-CONSOLE-20).

### GAP-24 — Integrity verification exceeds its wall-clock budget — Medium

**Design says.** NFR-INTEG-01 (`detailed-design.md:1548`): "Span verification shall be O(total span bytes) with no model call, and shall add under 1% to run wall clock."

**Code does.** PERF-06 (`tests/perf/test_perf_06_zero_model_stages_full_run.py`, landing branch) measured the gate over a full 350-submission run on E1:
- run 5,378 s;
- verify 525.0 s over 8,184 calls, less 404.0 s inside the test double's evidence view, leaving 121.0 s of gate time;
- that is **2.25%** of the run, 14.8 ms per verify.

The test's own diagnosis names un-indexed reads: `count_units uses idx_wu_pairs on run_id only; the document read scans …`. PR #338 disclosed PERF-06 as red.

**Caveats.** This was measured on E1 (a CI/dev box), not the E4 target, and the denominator is a recorded-transport run with no model latency. On a real run the wall clock is dominated by inference, so the share would be smaller. The per-verify cost is still far above O(span bytes) expectations.

**What a fix needs.**
- Profile `IntegrityGate.verify` (`integ.py:877`).
- Add composite indexes for the per-cell unit count (`work_unit(run_id, submission_id, criterion_id, stage)`) and for the document/region reads the gate performs.
- Read each document's canonical bytes once per submission instead of once per criterion.
- Re-run PERF-06, and gate on E4 per the PERF-10 runbook.

## C. Orchestration, lifecycle and packaging

### GAP-06 — No process or restart entry point; runtime dependencies undeclared — High

**Design says.**
- HLD §9.10 (`agentic-evaluation-harness-for-education.md:2720`): "Resume is trivial. On restart, skip any unit with `status='done'`".
- FR-ORCH-04 (`detailed-design.md:1201`): "a sweeper shall return units whose lease has expired to `pending`".
- CT-ORCH-03 (`:1339`): "`resume()` takes no arguments, is safe to invoke when nothing is wrong".
- NFR-CONSOLE-03 (`:2901`): killing the console mid-run does not affect the run.
- NFR-SYS-06 (§4.3): container deployment is supported.

**Code does.**
- `Orchestrator.resume()` (`orch.py:2687`) and `sweep_expired_leases()` (`:3667`) exist. No module in `src/` calls either; the only mentions are docstrings (`orch.py:22`, `:3103`).
- No `__main__` module exists under `src/aeh/`, and `pyproject.toml` declares no `[project.scripts]`, no `[build-system]` and `dependencies = []`.
- `pypdf` and `pypdfium2`, which live ingestion needs, are listed only in `requirements-dev.txt:35`.
- PR #339 measured the consequence: calling `resume()` without the sweep "left 24 units stuck leased forever".

**Verification.** `grep` for `sweep_expired_leases`/`.resume(` call sites and `__main__`; read `pyproject.toml`.

**Impact.**
- After a crash or kill there is no supported way to recover a run. An operator must know to call two APIs in the right order.
- A clean install cannot run the pipeline or console without the dev requirements.

**What a fix needs.**
- An `aeh.orch.recover(store) -> RecoveryReport` that calls `sweep_expired_leases()` then `resume()` and reports both (seam 4).
- A process entry point, for example `python -m aeh run --data-dir …` and `python -m aeh console`, that calls `recover` on start and then GAP-01's driver.
- Add `[project.scripts]` and `[build-system]`, and move runtime dependencies (`pypdf`, `pypdfium2`) into `[project] dependencies` or an extra such as `live-ingest`.
- Keep `HARNESS_*` knobs env-read at call time.
- Tests: RES-18 and TC-E2E-02's kill variants should call the entry point rather than the two-call sequence they define themselves.

### GAP-07 — A grade policy that references a missing criterion is not refused at run start — High

**Design says.** CT-GRADE-15 (`detailed-design.md:2259`), consumers `M-ORCH`, `M-CONSOLE`: "A policy referencing a criterion that no longer exists is a package integrity failure raised at *run start*, not at grading time, so grading has no unrecoverable failure mode."

**Code does.**
- `Orchestrator.create_run` (`orch.py:2189`) validates retention only (`_verify_retention_at_start`, `:2230`, #156). Nothing reads `grade_policy` against the version's criteria, and `grep` finds no such check in `orch.py`, `grade.py` or `pkg.py`.
- The written-ahead test `tests/contract/grade/test_ct_grade_c15_error_discipline.py::test_tc_grade_c15_a_policy_referencing_a_missing_criterion_is_refused_at_run_start` is red on the missing `aeh.orch:validate_grade_policy` (registry entry `#107 c15`).

**Verification.** Read `create_run`; confirmed the symbol is absent by import probe.

**Impact.** A stale policy surfaces at grading time, after the overnight spend, which is exactly the failure mode the clause exists to prevent.

**What a fix needs.**
- `aeh.orch.validate_grade_policy(catalog, package_version_id)`: load the policy JSON (`grade_policy.policy`) and the version's criterion ids, and raise a named integrity error listing every referenced-but-absent criterion (per-question rules, gates, best-k members).
- Call it in `create_run` before the run insert, beside the retention check, and surface the refusal on the console's "start run" (GAP-04).
- Unmark the C15 test and drop the `#107 c15` `WRITTEN_AHEAD_BLOCKERS` entry in the same change (`CLAUDE.md` written-ahead rule).

### GAP-09 — Run alerts are incomplete and there is no alert evaluator — Medium

**Design says.** DD §3.7 Observability (`detailed-design.md:1320-1324`): "**Alerts:** escalation rate above budget; any criterion tripping the circuit breaker; cost within 10% of ceiling; `cache_hit_rate` collapse; a run paused for any reason."

**Code does.**
- `orch.py` records the sources for three of the five: breaker rows (`:1958`), escalation-budget state (`:1974`, `:4289`) and `pause_reason` (`:550`).
- No code computes "cost within 10% of ceiling" or a `cache_hit_rate` collapse; `grep` for the concept in `orch.py`/`console.py` returns nothing.
- There is no alert-evaluation function. TC-ORCH-36 (`tests/integration/orch/test_alert_rules.py`) is written ahead on the missing `aeh.orch:evaluate_alerts`.
- Other modules declare their alerts (`store.py:207-209`, `integ.py:251`, `conform.py:175-176`); M-ORCH declares none.

**What a fix needs.**
- A pure `evaluate_alerts(*, run_row, metrics, breaker_rows, budget_state, history) -> tuple[Alert, ...]` in `aeh.orch`, with named constants for the five alerts.
- A `HARNESS_ORCH_COST_WARNING_FRACTION` knob (default 0.9).
- A cache-collapse rule against a history band. PERF-04's runbook uses mean − 3σ over ≥ 3 runs with a 0.5 floor; the design gives no number, so the design owner must declare one (record it as an Assumption).
- Surface the result on S7.
- Unmark `test_alert_rules.py` and drop the `#66 TS-25 alert rules` entry.

### GAP-11 — `run_metrics` does not carry CT-ORCH-20's full set — Medium

**Design says.** CT-ORCH-20 (`detailed-design.md:1356`): "Writes `run_metrics` in full: total and escalated units, quarantined units, wall clock, tokens, `cache_hit_rate`, peak concurrency, retries, rate-limit counters, estimated and actual cost, resolved builds, model swap count and duration. These names are contract". HLD §9.7 DDL (`:2500`) also lists `cost_currency` and `retention_setting`.

**Code does.** `_flush_run_metrics` (`orch.py:5229-5279`) writes the following:

| Metric | Shipped state |
|---|---|
| `transport_retries`, `rate_limited_calls`, `rate_limit_wait_s` | present |
| `tokens_in`, `tokens_out`, `cache_hit_rate` | present |
| `total_units`, `escalated_units`, `quarantined_units`, `peak_concurrency` | present |
| `estimated_completion_s`, `actual_cost` | present |
| `model_swap_count`, `model_swap_duration_ms` | present |
| resolved builds | one `resolved_build`, **not the set** (the first answer's build only, `:5023`) |
| estimated cost | **absent** (only on `run.cost_estimate`) |
| `cost_currency`, `retention_setting` | **absent** |
| wall clock | `wall_clock_ms` from an in-memory `started_monotonic` (`:4797`, `:5266`), so it **restarts when a new Orchestrator process attaches** (PR #339) |

**What a fix needs.**
- Record `estimated_cost` at `start`.
- Record the resolved-build set as a JSON list (the EAV value column already stores TEXT, `:5275-5278`).
- Record `cost_currency` and `retention_setting` from the frozen config.
- Compute wall clock from `run.started_at` plus pause intervals rather than process monotonic time.
- Check every metric name against CT-ORCH-20's wording in a sweep test.

---

## D. Scoring, review, statistics and ingestion

### GAP-08 — Review ranking inputs are not available from the store — Medium

**Design says.**
- FR-REVIEW-03 (`detailed-design.md:2307`): rank by `(P(wrong) × impact) / est_seconds`. Impact combines criterion share and boundary proximity; P combines panel spread, adverse integrity signals, transcription overlap and historical override rate.
- FR-AGG-06 (`:1878`): holistic "shall rank higher in the review queue at equal expected value".
- HLD §9.6 `review_queue` DDL (`agentic-evaluation-harness-for-education.md:2380`) carries `run_id, rank_score, est_seconds, shown_at, action, new_band, new_points, acted_at`.

**Code does.**
- The store form reads `criterion_score` rows into `_StoredScoreRow` (`review.py:2665-2697`) and takes `panel_spread`, `adverse_integrity_signals`, `transcription_overlap`, `historical_override_rate`, `criterion_weight`, `grade_boundary_delta` and `est_seconds` from the row mapping.
  - **None of these columns exist**, so each defaults to None or 0, and `_expected_value` (`:1056-1059`) yields 0.0 for every row.
  - `self.scoring_model = "atomic"` is hard-coded (`:2697`), so the holistic tie-break (`:1174`, `:1299`) never fires.
- The written-ahead test `test_tc_agg_c09_a_holistic_criterion_ranks_higher_in_the_review_queue` is red on the missing `ReviewService.scoring_model_for`.
- Disclosed in PR #301 and PR #326 ("every rung-2 row scores expected value 0.0").

**Impact.** On real data the minute-budgeted queue ranks in storage order. The core FR-REVIEW-03 promise, the highest expected value per teacher minute, does not hold.

**What a fix needs.**
- Derive the inputs at queue build (M-REVIEW reads; it writes no score):
  - `band_spread` and integrity flags from `criterion_score` (after GAP-03);
  - `scoring_model` and criterion weight from Tier P `criterion` and `grade_policy`;
  - boundary proximity from `PackageCatalog.distance_to_nearest_boundary` (`pkg.py:2842`, FR-PKG-16);
  - historical override rate from Tier D `label`, aggregated by criterion and package version;
  - `est_seconds` from a knob default per `scoring_model`.
- Implement `ReviewService.scoring_model_for(criterion_id)` (or pass a catalog).
- Persist `rank_score` and `est_seconds` on `review_queue` per HLD, with a cohort migration adding `run_id, rank_score, est_seconds, shown_at, action, acted_at`.
- Unmark the c09 test and drop its registry entry.
- Knob prefix: `review.py` uses `AEH_REVIEW_*` (`:1067-1086`) while `CLAUDE.md`/findings-register convention is `HARNESS_`. Align during the fix.

### GAP-10 — Contracted per-criterion and per-judge observability signals have no emitter — Medium

**Design says.**
- CT-AGG-15 (`detailed-design.md:1982`): "Emits, per criterion: band histogram, `band_spread` distribution, ordinal α, escalation rate, auto-accept rate, and **the count of each hard cap fired**."
- CT-EXTRACT-14 (`:1463`): "spans-per-unit distribution, empty-result rate per criterion, second-family disagreement rate, and extraction latency."
- CT-JUDGE-16 (`:1722`): "per criterion and judge: uncited-verdict rate, `evidence_sufficient = false` rate, band histogram, contract-violation rate, latency, prefix cache hit rate."

**Code does.**
- A search of `src/` for the signal names (`caps_fired`, `auto_accept_rate`, `empty_result_rate`, `spans_per_unit`, `second_family_disagreement_rate`, `uncited_verdict_rate`, `contract_violation_rate`) finds nothing. The only band histogram is M-GRADE's rollup accessor (`grade.py:142`, `:607-644`), which is not these emitters.
- Written-ahead tests are red on the missing `aeh.stats:judge_signals` (`tests/contract/judge/test_ct_judge_c16_signal_dimensionality.py`) and `aeh.extract:extraction_metrics` (`tests/contract/extract/test_ct_extract_c14_extraction_metrics.py`).
- PR #340's OBS-07 gap: "nothing in the design or `src/` emits these signals".
- Partial prerequisite: `verdict` stores no latency column (HLD §9.6 `verdict.latency_ms`, see GAP-21).

**What a fix needs.**
- Three pure emitters reading stored rows:
  - `aeh.agg.aggregation_signals(handle, run_id)`, which needs a cap-fired record on the row or a recomputation via `recompute_confidence`;
  - `aeh.extract.extraction_metrics(handle, run_id)`;
  - `aeh.stats.judge_signals(handle, run_id)`, keyed per (criterion, judge).
- Write them through `Orchestrator.record_run_metrics` with `(criterion_id[, judge])` dimensions. The durable `run_metrics` already has `submission_id`/`criterion_id` columns; add `judge_id`.
- Persist verdict latency. Declare the concentrated-violation and unusual-cap-rate alerts.
- Unmark the two written-ahead files and drop their entries.

### GAP-12 — `criterion.evaluation_mode` does not exist — Medium

**Design says.**
- FR-SETUP-13 (`detailed-design.md:1056`) and CT-SETUP-07 (`:1147`): "create a criterion with `evaluation_mode = 'deterministic'`".
- HLD §9.5 `criterion` DDL (`agentic-evaluation-harness-for-education.md:1991`) carries `evaluation_mode`.
- FR-STATS-01 (`:2464`) filters labels on `evaluation_mode = 'judged'`.

**Code does.**
- The shipped `criterion` columns (probe) are `criterion_id, package_version_id, question_id, kind, max_points, band_count, scoring_model, construct_tag, answer_key, evidence_type, band_justification, multi_select, partial_credit`. There is **no `evaluation_mode`**.
- Every consumer substitutes `kind='mcq'`: `orch.py` enumeration (PR #217 and PR #251 interpretation 2), `grade.separated_rollup` (PR #308), and the smoke and requires suites.
- PR #343 (TC-REQ-50): "the column the row names does not exist … a design question".
- `atomic_with_gate` is stored in `scoring_model`, a value the read-back `SCORING_MODELS` validation does not list (PR #244).

**Impact.** Deterministic-ness is inferred from question shape. A future deterministic non-mcq criterion, or a judged mcq variant, cannot be expressed, and the Tier D label / audit `evaluation_mode` has no package-side source of truth.

**What a fix needs.**
- A package migration adding `evaluation_mode TEXT NOT NULL CHECK (evaluation_mode IN ('judged','deterministic'))`, backfilled from `kind` (`mcq` → deterministic).
- `SetupService` writes it (FR-SETUP-13); the revision copy carries it (`_REVISION_COPY_KEYS`); `export_package` includes it.
- Switch orch enumeration, det, grade rollup and stats to read the column.
- Add `atomic_with_gate` to the declared `SCORING_MODELS` vocabulary, or record the design's intent in DD §3.6.
- Regenerate TC-REG-02's archive baseline and F-SCHEMA; bump the Tier P pin.

### GAP-13 — Tier D `label` lacks `assignment_type` and other HLD columns — Low (not yet due: Phase 2)

**Design says.**
- FR-STATS-17 (`detailed-design.md:2480`, Phase 2): "report agreement separately per `assignment_type` and shall refuse to emit a figure spanning assignment types".
- HLD §9.7 `label` DDL (`agentic-evaluation-harness-for-education.md:2418`) includes `package_version_id, assignment_type, band_distance, system_points, teacher_points, agreed, panel_config, recorded_at`.

**Code does.**
- The shipped `label` (probe) has `label_id, run_id, student_ref, criterion_id, label_type, band, evaluation_mode, saw_system_output, routing, origin, review_seconds, system_band, teacher_band, actor, timestamp, score_id, review_queue_action, new_points, cohort_id`. It has **none** of the eight columns listed above.
- `run_mvvp` step 4 reads `getattr(label, "assignment_type", None)` and discloses `assignment_type_not_recorded` (PR #315).
- `review.py` writes labels with `cohort_id` carrying the run's id (PR #307).

**What a fix needs.**
- A durable migration adding the missing columns.
- M-REVIEW's label writer sets `assignment_type` from the package or population scope, `package_version_id` from the run, `panel_config` from the run's frozen snapshot, and `band_distance`/`agreed` computed on write.
- M-STATS step 4 reads the column.
- Decide in the design whether `cohort_id` is the cohort or the run, and fix the writer to match. Today it is the run id, which `purge_cohort` keys on as a cohort (PR #307).

### GAP-14 — MVVP steps 2 and 3 are not performed by the module — Low (not yet due: Phase 2)

**Design says.**
- FR-STATS-15 (`detailed-design.md:2478`, Phase 2): "The module shall re-score a held-out fixture subset with the exemplar order and the presentation order … permuted, and shall report the rate at which a judge's band changes".
- FR-STATS-16 (`:2479`): "run each fixture judgment at least three times".

**Code does.** `run_mvvp` accepts `measured_position_bias` and `measured_self_agreement` as caller-supplied arguments (`stats.py:1635`, `:1671`, `:1712`). Headless, step 2 is permanently "not measured" (PR #315: "the module's permanent headless state"). No code path performs the permuted re-score or the three replications.

**What a fix needs.**
- A live-tier protocol driver, for example `aeh.stats.measure_position_bias(store, provider, panel, fixture_set, *, seed)` and `measure_self_agreement(..., runs=3)`.
- It assembles requests through `ScoringWorker.assemble` with a permuted `HARNESS_JUDGE_EXEMPLAR_SEED` and presentation order, dispatches through the injected provider (`RecordedFixtureProvider` in the fast tier), and returns the per-judge rates `run_mvvp` already consumes.
- TC-STATS-16/17 (live) then call it instead of hand-supplied rates.

### GAP-15 — Dual-scoring roster registration has no production route — Low (not yet due: Phase 3)

**Design says.** FR-CALIB-08 (`detailed-design.md:2627`, Phase 3): "Before R₁ goes live the module shall dual-score R₀ and R₁ across the **full class**, and shall reject the revision when more than a declared threshold of the class shifts by a full band".

**Code does.** `run_dual_scoring` buys the R₁ bands, but joining them with R₀'s bands and registering the roster that `non_inferiority` reads is done only through test seams: `_CLASS_ROSTERS` and friends (`calib.py:2527`, `:2894`). The module docstring (`calib.py:230-245`) says: "in this build the registration route is the test seam … there is no later story to land a production registration route".

**What a fix needs.**
- A public `register_dual_scored_roster(cohort_id, r0_bands, r1_bands)`, or better, `run_dual_scoring` reading R₀'s stored `criterion_score` rows (after GAP-02/03) and registering the joined roster itself.
- Persist the roster in Tier P or D so the gate survives a restart.
- The contract suite (`tests/contract/calib`) switches from `_CLASS_ROSTERS` to the public route.

### GAP-16 — Operator cluster resolution breaks the selection biconditional — Medium (Phase-2 feature, shipped, breaks a Phase-1 contract)

**Design says.**
- CT-INGEST-05 (`detailed-design.md:980`): "For `selection_mark` regions, `selection` is populated **iff** `selection_state = 'resolved'`."
- FR-INGEST-20 (`:798`, Phase 2): "applying the resolution to every occurrence".

**Code does.** `resolve_cluster` (`ingest.py:3828-3860`) runs `update_region_content` (`:1857-1861`), which is `UPDATE document_region SET content = REPLACE(...), selection_state = 'resolved' WHERE region_id = :region_id`. That statement:
- stamps `resolved` on **every** region carrying the token, whatever its `region_kind`;
- never sets `selection`.

A `selection_mark` region stored `ambiguous` with an `<unresolved>` token therefore becomes `resolved` with `selection = NULL`, the exact form CT-INGEST-05 forbids and M-DET must never map. This was disclosed as a residual in PR #243 and never filed; `gh issue list` finds no owning issue.

**Verification.** Read the statement and its only caller.

**What a fix needs.**
- Split the statement.
  - Transcribed-text regions get content replacement only, with no `selection_state` write.
  - Selection-mark regions accept the resolution only as an option id that is valid for the declared question (validated against `question_option`), setting `selection` and `selection_state='resolved'` together. Otherwise leave the state `ambiguous`, recording the resolution text only.
- Add a CHECK or trigger: `NOT (region_kind='selection_mark' AND selection_state='resolved' AND selection IS NULL)`.
- Regression test per the `CLAUDE.md` defect exception, and a TC row in `test-plan.md`.

### GAP-17 — Agreement block omits the too-few qualifier — Low

**Design says.** DD §3.16 Configuration (`detailed-design.md:2541-2542`): "`STATS_MIN_N_FOR_HEADLINE` (Assumption: 30 — below this the figure renders with an explicit 'too few to draw conclusions from' qualifier, as HLD §11.5's S12 mock-up does at n=15)." The mock-up itself is at `agentic-evaluation-harness-for-education.md:3262`: "κ = 0.63, n = 15 — too few to draw conclusions from".

**Code does.**
- `render_agreement_block` (`console.py:3163-…`) renders κ/α with n and the degeneracy disclosure but never compares n with `STATS_MIN_N_FOR_HEADLINE` (`stats.py:326`).
- `grep -i "too few" src/aeh/console.py` is empty.
- The written-ahead test `test_tc_stats_04_row7_…` is red on `aeh.console:TOO_FEW_QUALIFIER`.

**What a fix needs.**
- Add `TOO_FEW_QUALIFIER` in `aeh.console`.
- Append it when `n < STATS_MIN_N_FOR_HEADLINE` (read through `aeh.stats` at call time).
- Unmark the test and drop the `#119 too-few` entry.

### GAP-18 — A NULL `saw_system_output` is admitted as blind — Low

**Design says.** CT-REVIEW-08 (`detailed-design.md:2403`): "`saw_system_output` is the field the entire validity argument rests on … A label with `saw_system_output = 1` is **not** admissible". The plan's variant (TC-STATS-01) requires a NULL flag to be treated as inadmissible, not blind.

**Code does.** The admissibility predicate uses `not getattr(label, "saw_system_output", 0)` (`stats.py:582`), so `None` and a missing attribute are both admitted. Tier D's column is `NOT NULL DEFAULT 1` and `record_label` validates 0/1, which **limits exposure to duck-typed or in-memory labels**. The written-ahead test is red on `SAW_SYSTEM_OUTPUT_NULL_IS_INADMISSIBLE`.

**What a fix needs.**
- Admit only `saw_system_output == 0` (strict, `is not None and int(...) == 0`).
- Count NULLs into `excluded_count`.
- Unmark the test and drop the entry.

### GAP-19 — Long-horizon statistics export is JSON, not Parquet/DuckDB — Low

**Design says.** NFR-STATS-03 (`detailed-design.md:2527`): "an optional read-only Parquet/DuckDB export supports longer horizons and never touches the scoring pipeline."

**Code does.** `stats.py:207-212` records a descope and writes one JSON document under `exports/` (PR #317).

**What a fix needs.** Either add an optional `pyarrow`/`duckdb` extra and writer, keeping the SEC-14 dependency review, or amend NFR-STATS-03. The requirement says "optional", so this is a design-owner decision.

### GAP-20 — `grade_revision(revision=None)` reads revision 1 on a real store — Low

**Design says.** FR-GRADE-09/12 (`detailed-design.md:2135`, `:2138`): revisions are append-only and exports name the revision. The console method's own contract says "`revision=None` reads the latest".

**Code does.** The store branch passes `revision=revision or 1` (`console.py:2808-2810`), so the latest amended revision is never returned by default. Disclosed as a carry-forward in PR #313.

**What a fix needs.** When `revision is None`, select `is_current = 1` (the partial unique index `uq_submission_grade_current` already exists).

### GAP-21 — Remaining schema divergences from HLD §9 — Low (individually)

The DD makes the HLD DDL normative ("per HLD §9.x" in each module's Data structures).

**Method.** This table was generated mechanically:
- a regex over the HLD `CREATE TABLE` blocks (column name followed by a SQL type);
- compared against `PRAGMA table_info` on a fresh store opened with all eleven migration contributors.

Only four rows were individually re-checked against the code, because they carry behaviour: `verdict.evidence_assessment`/`latency_ms`, `validation_record.expected_*`, `document_region.question_id` and `submission.document_id`. `evidence_assessment` was confirmed absent from `insert_verdict` (`judge.py:316-320`). Read the remaining rows as "the HLD column name is absent from the shipped table", not as confirmed missing behaviour; some are renames or representation changes. Entries already covered above are omitted.

| HLD table (line) | Shipped | Divergence |
|---|---|---|
| `criterion_band` (§9.5) | `band` | Renamed; columns equivalent (`band, ordinal, descriptor, points` + `package_version_id`). Document the rename. |
| `mcq_option` (§9.5) | `question_option` | Renamed, a disclosed divergence (PR #210); `text` → `label`. Document it. |
| `package_validation` (`:2088`) | `validation_record` (Tier P) | Renamed; lacks `override_rate, expected_mean, expected_sd, expected_histogram, last_updated`. The drift check (FR-STATS-09) and package baseline need `expected_*`. |
| `population_scope` (`:2077`) | — | **Table absent**; scope is free text on records (CT-PKG-17 declares that acceptable, but the HLD table and its dimensions are undeclared). |
| `package` | `package` | Lacks `title, subject, grade_level, language, origin_institution` (S1 cannot display them). |
| `package_version` | `package_version` | Lacks `version_label, approved_by, approved_at, gate_results, validated_panel, prompt_template_v, schema_version, published`. |
| `grade_policy` | `grade_policy(policy JSON, review_window_hours)` | Structured columns collapsed into JSON (representation choice; `approved_by`/`approved_at` absent). |
| `criterion` | `criterion` | Lacks `ordinal, text, decomposition_basis, is_gate` (plus `evaluation_mode`, GAP-12). |
| `criterion_dependency` | `(criterion_id, depends_on)` | Lacks `artifact_kind, rationale`. |
| `exemplar` | `exemplar` | Lacks `text, ordinal` (content in the blob). |
| `elicitation_history` | `elicitation_history` | Different column vocabulary (`question/answer_given` vs `question_asked/teacher_answer`), no `criterion_id`. |
| `cohort` | `cohort` | Lacks `package_version_id, institution, section_label, administered_at, student_count`. |
| `submission` | `submission` | Lacks `blob_hash, document_id, transcript_conf, layout_conf, has_equations, has_diagrams, page_complete, ingest_detail`. |
| `document` / `document_region` | shipped | `document` lacks `version, page_count`; `document_region` lacks `question_id, span_start, span_end, source_page_seq` (question ownership is inferred; PR #349). |
| `work_unit` (`:2235`) | shipped | Lacks `question_id` (residency batches order judge→question→criterion, FR-ORCH-07, by join). |
| `evidence` | shipped | Lacks `run_id, submission_id, criterion_id, extractor, created_at` (reached through `work_id`). |
| `verdict` (`:2266`) | shipped | Lacks `run_id, submission_id, criterion_id, evidence_assessment, latency_ms, created_at`. **`evidence_assessment` is validated (FR-JUDGE-10) but not persisted** (`judge.py:316-320`), so a verdict's inventory is not auditable later. |
| `submission_grade` | shipped | Lacks `raw_points, scaled_score` (only `total`). |
| `audit_record` | shipped | `audit_id` → `audit_record_id`; lacks `cited_spans`. |
| `criterion_stats` (`:2451`) | shipped | Lacks `band_histogram, band_entropy, interior_rate, mean_points, sd_points, escalation_rate, override_rate, panel_agreement, uncited_rate` (figures computed at read time, PR #308). |
| `mcq_item_stats` / `mcq_item_summary` | shipped | Lack `cohort_id, question_id` (version-keyed, PR #249). |
| `run_metrics` (`:2500`) | EAV `(run_id, metric, value, submission_id, criterion_id)` | Wide table → EAV (representation choice); missing names in GAP-11. |

**What a fix needs.** For each row, the design owner chooses one of two paths:
- **Adopt the shipped shape:** update HLD §9 and DD Data structures, and record renames and representation changes as ADRs.
- **Add the columns:** a migration per tier, a pin bump, and F-SCHEMA/TC-REG-02 golden regeneration.

The rows that carry behaviour, and should not be closed by a doc edit alone, are `verdict.evidence_assessment`/`latency_ms`, `validation_record.expected_*`, `document_region.question_id` and `submission.document_id`.

---

## E. Contradictions and TBDs inside the design (resolved by code interpretation)

These are not code defects. The code picked a reading, and the design owner (`/detailed-design-generator`) must ratify or change it.

| ID | Design conflict | What the code does | Decision needed |
|---|---|---|---|
| D-1 | NFR-REVIEW-05 (`:2369`) promises an honest queue "at 5 minutes", but FR-REVIEW-02 (`:2306`) subtracts `REVIEW_BLIND_RESERVE_MINUTES` (10) **before** ranking, leaving nothing. | Reserve capped at the budget (`min(reserve, budget)`, `console.py:2482-2484`; `review.py`), plus a floor of one shown item (PR #301, #311). | State the reserve rule when budget ≤ reserve. |
| D-2 | CT-CONFORM-14 (`:2791`): the score-distribution gate "is **not computable as written**" (TBD §4.6 item 2). | Implemented as an `UNAVAILABLE` gate that can never pass (PR #328). | Declare the statistic and threshold. |
| D-3 | FR-INGEST-26 (`:809`) allows ranked candidates for a mismatch, but ADR-7's semantic signal is `absent` whenever two assessment lineages exist, capping the outcome at `uncertain` (no proposal). | A proposal is only reachable with one candidate; TC-INGEST-39 was revised to that form (PR #208, #228). | Add a lineage-discriminating signal, or state that single-candidate proposals are the design. |
| D-4 | §3.12 records Krippendorff α's single-unit degeneracy as TBD. | A declared ordinal convention in `agg.py` (PR #284), with the entropy base in nats (PR #308) and half-up rounding (PR #279). | Record the conventions in DD §3.12/§3.14. |
| D-5 | CT-STATS-09 (criterion-override history) has no FR and no interface member (PR #171). | Tested against the absence; M-AGG ranks no-data first (PR #291). | Add an FR or drop the clause. |
| D-6 | FR-INGEST-14 does not define "different model family" or "load-bearing fact"; FR-EXTRACT-07 does not define family either. | Family = a different `(provider, build_id)` pair; load-bearing facts = number multiset plus a content-word Jaccard floor (`HARNESS_INGEST_SECOND_DESCRIPTION_MIN_SIMILARITY` = 0.35); graphic → preceding question region (PR #281, #349). | Ratify or define. |

---

## F. Design lags the code (DOC-1): undocumented surfaces and knobs

Consumers depend on these, but no design document names them (`grep` count in DD = 0). Each belongs in the owning module's Interfaces or Configuration block. None is a code defect.

| Surface | Where | Note |
|---|---|---|
| `open_store(data_dir, read_only=...)`, `Store.close` | `store.py` | The design's `Store` has no constructor or lifecycle (PR #176). |
| `STATEMENTS` registry, `Tx.execute(statement, **params)`, `enqueue_write(statement, **params)` form | `store.py:904-923` | DD names `WriteUnit`/`Tx` without defining them (PR #176, #178). |
| `lease_clock(store)`, `Lease`, `InvalidContentHashError`, `IncompleteMigrationChainError`, `COMPLETE_SCHEMA_VERSIONS` | `store.py` | PR #179, #283. |
| `RecordedFixtureProvider.record(...)`, `PromptPayload`/`SamplingParams` field sets | `prov.py` | The recording path is implied by test plan §4.4 but absent from §3.2 (PR #160). |
| `Orchestrator.record_run_metrics`, `provenance(work_id)`, `enumerate_units`, `EnumerationReport` | `orch.py` | PR #248, #347. |
| `evaluate_conformance_alerts`, the conform alert constants | `conform.py:175`, `:1862` | PR #321. |
| Knobs `HARNESS_SQLITE_BUSY_TIMEOUT_MS`, `HARNESS_SQLITE_BUSY_RETRIES`, `HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS`, `HARNESS_INGEST_RESOLUTION_FLOOR` (enforced in **px**, not the DPI the design names, PR #264), `HARNESS_INGEST_SECOND_DESCRIPTION_MIN_SIMILARITY`, `HARNESS_SETUP_PROPOSAL_ATTEMPTS`, `HARNESS_SETUP_READBACK_ATTEMPTS`, `HARNESS_JUDGE_EXEMPLAR_SEED`, `HARNESS_ORCH_LEASE_SECONDS`, `HARNESS_CALIB_CLASS_SIZE_CAP`, `AEH_REVIEW_*` weights | various | `CLAUDE.md` seam 3 sanctions them, but the design's Configuration blocks do not list them. |

---

## G. Plausible, needs a probe before filing

| Candidate | Source | Why it is not in the verified list |
|---|---|---|
| Requeue and OOM consequence writes attribute a batch to the *requested* run, so a multi-run store can invalidate another run's order cache. | PR #288, finding 2 | `_requeue_units(cohort, run_row["run_id"], …)` (`orch.py` `_run_model_batch`) matches the description, but no multi-run dispatch probe was run; every shipped case is single-run. |
| Console `export_grades` headless branch ignores `run_id`. | PR #313 | That branch is only reached with no store attached (`console.py:2776-2781`); on a real store the query filters by `run_id`. Likely harmless; confirm there is no real-store path. |
| Group label durability is partial (a mid-loop failure leaves earlier members durable; a retry double-marks them). | PR #307 | Needs a fault-injection probe on `ReviewService` group actions. |

---

## Appendix A — `docs/findings-register.md` re-verified at the baseline

Every "A" defect in the register (compiled 2026-09-08 at `8f26b65`) is **closed**. Nothing from the register carries into the gap list except D-3 (A13's design half).

| Register item | Status at `e0ac562` | Evidence |
|---|---|---|
| A1 V2 never reads declared set / selection_state | Fixed (#219) | `_absent_regions` called at `ingest.py:4079`; declared-state read `:2497` |
| A2 transcription 3-strike / zombie rows | Fixed (#220, PR #275) | `HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS` `ingest.py:189-190` |
| A3 malformed mark stored resolved/NULL | Fixed at ingest (#219) | No default to `resolved` (`ingest.py:2497`). **Operator path still open: GAP-16** |
| A4 `low_confidence_ocr` unreachable | Fixed (#221, PR #247) | Floor `ingest.py:332-336` |
| A5 aggregate emitters missing | Fixed for M-INGEST (PR #253) | `ocr_failure_rate` et al. `ingest.py:4260-4347`. **M-AGG/EXTRACT/JUDGE emitters still open: GAP-10** |
| A6 `work_unit` lacks `document_id` | Addressed by a join (#223, PR #347) | `Orchestrator.provenance`; the column is still absent (GAP-21) |
| A7 escapable V4 fence | Fixed (PR #240) | `_fence_untrusted_content` |
| A8 page rasters never persisted | Fixed (#226, PR #258) | `ingest.py:3085` `blobs.put(page.png)` |
| A9 purge FK abort / blobs never deleted | Fixed (#225, PR #241) | Purge order includes `unresolved_token, token_cluster` (`store.py:1516`) |
| A10 `PdfiumRasterizer.crop` missing | Fixed (#226) | `ingest.py:846` |
| A11 resolution floor dead | Fixed (#227, PR #264) | Read at `ingest.py:708` (px, see §F) |
| A12 ambiguous filenames silently ordered | Fixed (#227, PR #264) | Per PR; not re-probed |
| A13 two-candidate proposal unreachable | Plan reconciled (#228) | Design question remains: D-3 |
| A14 pypdfium2 undeclared / waiter state / masked gates | Fixed | `requirements-dev.txt:35`; PR #253. Runtime declaration still open: GAP-06 |
| A15 post-publish second root version | Fixed (#229, PR #254) | Per PR; not re-probed |
| A16 revision copy drops criterion fields | Fixed (#230, PR #280) | Per PR; not re-probed |
| A17 setup path skips bound checks | Fixed (#231, PR #271) | Per PR; not re-probed |
| B1 adversarial corpus variants | Done (#237, PR #351) | Built in-suite; F-ADV-PDF unchanged (plan decision) |
| C1 FR-INGEST-14 Phase 2 | Done (#233, PR #349) | `second_description_pass` |
| C3 TC-SETUP-12 evidence_type gate | Done (#232, PR #261) | — |

## Appendix B — Candidates checked and rejected (not gaps)

| Candidate | Why rejected |
|---|---|
| `aeh.stats:promote_cohort` missing, so TC-EXTRACT-14 purge is blocked | Promotion exists as `ValidationStats.promote` (`stats.py:2946`), which writes `criterion_stats` (`stats.py:942`) and claims labels. The name is a test-invented key; see Appendix C. |
| `JUDGE_PROMPT_TEMPLATE_V` absent (PR #286) | Landed: `judge.py:333` (`judge-prompt/2`). |
| Criterion-order randomization not implemented (PR #286) | FR-JUDGE-16 (`:1640`) forbids it. |
| `superseded_at` missing (PR #306) | Present on shipped `submission_grade` (#103). |
| `write_failures` not in `STORE_SIGNALS` (PR #178) | CT-STORE-17 (`:577`) names five signals, and write failures is not one of them. FR-STORE-10's disk-full halt is implemented (`store.py:398-417`). |
| Strip pass prunes only `/A`/`/AA`-reachable actions (PR #351) | FR-INGEST-33 (`:821`) allows either neutralization **or** quarantine for unremovable active content; survivors are refused as `unreadable` (fail-closed). |
| Nowhere-cited IDs NFR-GRADE-04, NFR-PROV-03, NFR-SYS-10, NFR-INGEST-03/06, NFR-SYS-01, FR-INGEST-19 | NFR-GRADE-04: `finalize_batch` is one action (`grade.py:1725`). NFR-SYS-10: `SchemaTooNewError` exists (`store.py:104`). FR-INGEST-19: V2 check (#219). NFR-INGEST-03/06 and NFR-SYS-01: release-gate or live-medium items; NFR-SYS-01 is blocked by GAP-01 rather than being a separate gap. |
| HLD requirements with no DD requirement | An independent trace found every HLD `R#` in a DD row (R6, R10 and R25 via §4.3 NFR-SYS rows). |
| Second-description pass, V4 fence, purge blobs, low-confidence OCR | Landed (Appendix A). |

## Appendix C — Test-side findings that are not code↔design gaps (for `/write-tests` / `/create-test-plan`)

- **Stale written-ahead keys.**
  - `#68 TC-EXTRACT-14 purge` waits on `aeh.stats:promote_cohort`, a name nothing will ship; promotion exists as `ValidationStats.promote`.
  - `#155` `harness.blast_radius` and the `check_traceability --contracts-only` command are test-plan §6.12 tooling with no implementing story.

  Neither is a design gap. Each needs re-keying or an owning story, or the test stays outside the gate forever.
- **Test double with the wrong signature.** `tests/support/conform_vocabulary.CountingProvider.complete(request, **kwargs)` does not match `complete(prompt, model_ref, params)`, so the "zero model calls" oracle in `tests/contract/conform/test_ct_conform_corpus.py` can never observe a call (PR #342).
- **Missing cases for shipped behaviour.**
  - M-SYNTH's L2 exclusion of score-claim-flagged L1 rows (PR #287).
  - TC-CALIB-11's configuration-time shared-build refusal and the `HARNESS_CALIB_CLASS_SIZE_CAP` knob (#139 comment).
  - The run-start retention wiring at M-ORCH level; RES-17/RES-18 (PR #346).
  - `synthesis_failure_rate` has no non-zero case (PR #274).
