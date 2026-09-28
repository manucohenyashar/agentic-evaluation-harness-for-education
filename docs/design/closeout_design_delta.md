# Detailed Design Delta: Backlog Close-out, the Decisions Parked Issues Waited On and the Gaps Merged PRs Disclosed

**Source:**
- The user's directive (2026-09-27): "remove irrelevant issues and close the remaining gaps … so we can see the whole picture". The user delegated every design decision this document takes, except two facts only they could supply: no reference hardware is available, and a teacher try-out comes after the gaps close (§1.1).
- `docs/design/detailed-design.md` v1.4 (the "base design").
- `docs/design/fix_gaps_detailed_design_plan.md` v1.5.1-delta (the "gap delta").
- `docs/design/jev_decision_engine_design_delta.md` v1.8-delta (the "Jev delta"). This document applies on top of all three.
- The parked issues #376, #433, #434 and #454, whose comments each asked for a design decision.
- The "known and reported, not fixed" sections of merged PRs #438, #439, #495, #496, #507 and #508, and the review findings recorded on #377, #378, #379, #380 and #389.
- The full non-live suite run on `main` @ `a0fded4` (2026-09-27): 40 failed, 3961 passed. §5 classifies every failure.

**Code baseline validated against:** `main` @ `a0fded4`, `src/aeh/*.py` (§8).

**Version:** 1.9-delta  **Date:** 2026-09-27  **Status:** Draft, for review before `/create-test-plan`.
**Author:** `/detailed-design-generator`, delta mode.

## Revision history

| Version | Date | Change | Author |
|---|---|---|---|
| 1.9-delta | 2026-09-27 | **Backlog close-out.** <br>• **Five decisions** that parked issues were waiting on (D1–D5, §2): override rate gets two names (ADR-30); FR-REVIEW-22's historical backfill is withdrawn (ADR-31); `decision_engine_noninferior` gets its own Package-tier column; D-3's multi-lineage proposal is made consistent with the V4 decision table; the stranded FR-PROV-15 edit of 2026-09-02 is adopted. <br>• **Twelve gaps** that merged PRs disclosed but no issue tracked (G1–G12, §3). Among them: escalation's anomaly and history limbs never fire in production; eleven statement names carry conflicting SQL; the mid-run cost ceiling ignores decision spend; the grade footer is a hard-coded constant that names neither the run's profile nor its engine. <br>• **§5 classifies every red test on `main`.** 25 are product defects against clauses that already exist, so they need stories rather than requirements. 10 are one test-support environment leak. The remaining 5 are stale fixtures, one nondeterministic test, one golden and one vacuous oracle, all to triage. <br>• **New IDs:** FR-PROV-15; FR-STATS-28/29; FR-REVIEW-23/24; FR-PKG-23; FR-INGEST-38; FR-STORE-16; FR-ORCH-41…44; FR-PIPE-15…18; FR-CONSOLE-40; CT-STATS-25/26; CT-REVIEW-24/25; CT-PKG-20; CT-INGEST-22; CT-STORE-19; CT-ORCH-31…34; CT-PIPE-10…13; CT-CONSOLE-29; ADR-30…34. <br>• **Amended:** FR-PROV-12, FR-STATS-24, FR-REVIEW-18/21/22, FR-INGEST-26, FR-ORCH-28/32/34, CT-STATS-09. <br>• **No ID is renumbered.** Every amendment is classified under base §4.7 in §7.2. | `/detailed-design-generator` |

---

## 1. Scope & purpose

This is a **delta**, not a replacement. It adds no new capability. It finishes the capabilities the three earlier documents specified, in two ways:

1. **It takes the decisions** that left four issues parked on `status:needs-attention`: #376/#396, #433, #434 and #454.
2. **It gives requirement text to gaps** that merged PRs disclosed in their "reported, not fixed" sections. Each of those is a place where the shipped system does less than the design implies, and no issue tracked it.

It also classifies every test that is red on `main` (§5). That is not design work, but the classification decides which failures need a requirement (§3), which need only a story against a clause that already exists (§5.1), and which are test-harness defects for `/create-test-plan` (§6).

**Out of scope:**
- Test cases (`/create-test-plan`) and issues (`/plan-to-issues`). §5 and §6 are inputs to those stages, not their output.
- Anything needing reference hardware or a person. Issue #157 now holds that release checklist, and nothing here changes it.
- Phase 3.5 exemplar paraphrases, which stay present-and-unavailable as FR-CONSOLE-34 states.

### 1.1 Facts supplied by the user (2026-09-27)

- **No reference hardware (E4, E7) is available.** Hardware-gated checks are recorded as *not verified*. Nothing in this delta depends on them.
- **A teacher try-out is wanted once the gaps here are closed.** That is why §3.4 (the grade footer) is in scope now: UAT-12 is the teacher-facing half of the Jev work, and the try-out cannot sign it off while the footer is a constant.

### 1.2 Conventions

- IDs continue from the highest existing number in any design document. For example, the highest FR-ORCH is FR-ORCH-40 (Jev delta), so this document starts at FR-ORCH-41. FR-PROV-15 is the one exception, filling a gap that was reserved and never written (D5).
- **Amended** rows quote the clause they change and state the delta. Nothing is silently reworded.
- `Assumption:` marks a value this document chose rather than found.
- Migration numbers continue the chains in CLAUDE.md: Package's next is **13**, and Durable's next is **12**.

---

## 2. Decisions (D1–D5)

### 2.1 D1: override rate means two things, so it gets two names (#433, ADR-30)

**The problem.** Three texts use "override rate" for different populations:

| Text | Population | Signature |
|---|---|---|
| FR-STATS-24 (gap delta) | not stated | `criterion_override_history(package_lineage, criterion_id)` |
| `aeh.stats` as shipped (`stats.py:4165`) | `origin == 'override'` over `admissible_labels()`: blind, judged, unseen-output labels | `criterion_override_history(criterion_id)` |
| FR-REVIEW-18's eighth input | "overrides ÷ judgments": every reviewed judgment | — |

Two more facts:
- #368 correctly withdrew a private second derivation from `aeh.review`, so `_StoredScoreRow.historical_override_rate` is `None` on every store-backed row.
- `REVIEW_OVERRIDE_MIN_N` (5) is read into `_calibration_knobs()` and consumed nowhere. So one override in four judgments reads as a 25% rate, which the constant's own comment forbids.

**Decision (ADR-30):**
- `criterion_override_history` stays the **validity** figure. Its population is the admissible blind labels, the population κ claims rest on.
- The review ranking reads a new, differently named **operational** figure, `criterion_disagreement_rate`. Its population is every reviewed judgment.
- The minimum-n rule applies to both figures, inside M-STATS. A population below the minimum is no-data, never a rate.

**Why not one figure:**
- Blind labels are a deliberately small sample (`REVIEW_BLIND_N = 15`). Feeding them to the ranking would leave the eighth input at no-data in production.
- Feeding operational labels to the validity figure would contaminate the κ population (CT-STATS-01).

| ID | Requirement | Notes |
|---|---|---|
| FR-STATS-24 (amended) | `criterion_override_history(criterion_id) -> CriterionOverrideHistory \| NoValidationData` is a member of a `ValidationStats` built over **one package lineage's** labels. The lineage is the instance's scope, so the `package_lineage` parameter the gap delta wrote is dropped. The population is `admissible_labels()` restricted to `criterion_id`. An override is a label with `origin == 'override'`. The figure is `CriterionOverrideHistory(criterion_id, n, override_count, override_rate)`. When `n` is below `HARNESS_REVIEW_OVERRIDE_MIN_N` (default 5, read at call time), it returns `NoValidationData(reason='below_min_n', n=n)`. With `n == 0` the reason stays `no_blind_labels`. | Amends the gap delta's D-5 signature to the shipped one, and adds the minimum-n rule |
| FR-STATS-28 | `criterion_disagreement_rate(criterion_id) -> CriterionDisagreement \| NoValidationData` is a `ValidationStats` member over **every** label for `criterion_id` whose `label_type` is `blind` or `operational` and that carries both `system_band` and `teacher_band`. Disagreement is `system_band != teacher_band`, equivalently `agreed = 0` (FR-REVIEW-21). The figure is `CriterionDisagreement(criterion_id, n, disagreements, rate)`. The same minimum-n rule and no-data reasons as FR-STATS-24 apply. A store-backed reader `stored_disagreement_rates(store, package_version_id) -> Mapping[str, CriterionDisagreement \| NoValidationData]` returns one entry per criterion of the version, read through M-STATS alone. | New. The recording rule is settled: `agreed` feeds FR-STATS-28, and `origin == 'override'` feeds FR-STATS-24. Each figure has one rule, and each rule is named here |
| FR-REVIEW-18 (amended: eighth input) | `historical_override_rate` on `_StoredScoreRow` is filled from FR-STATS-28's `stored_disagreement_rates` for the run's package version. A `NoValidationData` entry is carried as no-data, which FR-REVIEW-03's P(error) term already distinguishes from `0.0` (CT-STATS-09). `aeh.review` derives no rate of its own. | Replaces "Tier D `label` overrides ÷ judgments … below `HARNESS_REVIEW_OVERRIDE_MIN_N`": the rule moves to M-STATS |
| CT-STATS-09 (amended) | Criterion override history **and criterion disagreement rate** are exposed as escalation and ranking inputs. Each returns an explicit no-data value, never `0.0`, for a criterion with no data **or with fewer than the minimum-n labels**. | Additive: widens the clause to the second figure and states the minimum |

### 2.2 D2: FR-REVIEW-22's historical backfill is withdrawn (#434, ADR-31)

**The problem.** FR-REVIEW-22 says existing `label.cohort_id` rows are "rewritten by the migration through the durable→cohort run map where resolvable". Three facts make that impossible as written:
- Tier D holds no such map.
- A Durable migration cannot open cohort files (`CrossTierTransactionError`).
- The system is pre-release, so no historical rows exist anywhere outside test stores.

The forward half shipped in #368 and is pinned by TC-REVIEW-29.

| ID | Requirement | Notes |
|---|---|---|
| FR-REVIEW-22 (amended) | The `label.cohort_id` written by collection is the **cohort** id resolved from `run.cohort_id`, never the run id, and is `NULL` when it cannot be resolved. Rows written before this rule are **not** rewritten, and no migration or tool rewrites them. The purge precondition (`store.py`'s cohort purge gate) treats such a row as belonging to no purgeable cohort, so it fails **closed**: a cohort purge never passes because of a row whose cohort is unknown. | Option 1 of #434. Closes Q-16 ("what happens to an unresolvable row": it stays `NULL` and the gate fails closed) |

### 2.3 D3: the non-inferiority verdict gets its own column (#454)

**The problem.** NFR-STATS-06 says `validation_record` records `decision_engine_noninferior`. The Jev delta's Q-J6 assumed an existing JSON payload. But the record's only JSON columns (`weakest_per_population`, `surface_proxy_flags`) are keyed documents that consumers parse, so reusing either would break their readers. The measurement shipped in #489.

| ID | Requirement | Notes |
|---|---|---|
| FR-PKG-23 | Package migration **13**, `pkg_decision_engine_noninferior`, owned by `aeh.pkg`, adds `validation_record.decision_engine_noninferior TEXT NULL CHECK (decision_engine_noninferior IN ('true','false','insufficient_data'))`. `PackageCatalog.record_noninferiority(v, *, population_scope_id, backend_profile, panel_build_ref, scoring_model, verdict)` writes it on the row under the six-part key (FR-PKG-08). `validation_for` returns it as a field. `NULL` means *not measured*, which is distinct from `'insufficient_data'` (measured, too few labels). The `COMPLETE_SCHEMA_VERSIONS` Package pin moves 12 → 13 in the same change. | Resolves Q-J6 |
| FR-STATS-29 | `promote` writes `decision_engine_noninferior(agreement_by_engine(...))`'s verdict through FR-PKG-23 whenever the run froze a decision engine. It writes nothing for an engine-off run, so the column stays `NULL`, which is NFR-SYS-14's byte-identity for engine-off. M-STATS never switches engines (CT-CONF-14). | The persistence half of #454 |
| — | The operator console's validation surface renders the verdict as "Decision engine: not inferior / inferior / insufficient data (n per partition)". `NULL` renders nothing. | Consumer note on NFR-STATS-06. Covered by CT-CONSOLE-29's provenance rule (§3.9) |

### 2.4 D4: D-3's multi-lineage proposal, made consistent with the V4 table (#376, #396)

**The problem.** TC-INGEST-52 asks for a proposal over "3 lineages whose structural signal matches the submission". That cannot be produced, because:
- A proposal is built only on outcome `mismatch` (FR-INGEST-26).
- `mismatch` needs identifier **and** structural **and** semantic mismatch (TC-INGEST-25's table).
- With more than one assessment lineage head, the semantic signal is `absent` (`ingest.py:4800`), so the outcome can never be `mismatch`.

On top of that, the aggregate structural signal compares the submission with the **run's package** (its declared questions), not with any stored lineage.

**Resolution:**
- The aggregate signals keep comparing against the **run's package**, and the outcome table is unchanged.
- With several lineages, the semantic reference is the lineage **whose question inventory equals the package's declared inventory**, which is the paper the run is actually for. It is `absent` only when zero or several heads qualify.
- D-3's "every matching lineage" becomes the **candidate filter inside the proposal**, as a per-candidate structural match.

| ID | Requirement | Notes |
|---|---|---|
| FR-INGEST-38 | When the store holds more than one assessment lineage head, the aggregate semantic signal (FR-INGEST-25) compares against the head whose question inventory (its `element_kind` set, excluding `text` and `graphic`) equals the run's package-declared question set. It returns `absent` with a reason naming the count when zero or more than one head qualifies. With exactly one head, behaviour is unchanged. | Unblocks `mismatch` in multi-lineage stores without guessing |
| FR-INGEST-26 (amended: candidates) | A proposal is built only on `mismatch`, as today. Its `candidates` are the lineage heads whose **per-candidate structural signal matches the submission**: the candidate's question inventory equals the submission's (inventory affinity `== 1.0`; `Assumption:` equality, the same strictness FR-INGEST-25 applies to the package). They are ranked by a **per-candidate semantic value** `semantic = _v4_lexical_affinity(candidate.markdown, submission.markdown)` in `[0,1]`, descending, with ties broken by `assessment_document_id` ascending. Each candidate records `assessment_document_id`, `identifier`, `semantic` (never `absent` inside a candidate) and the existing `components`. A mismatch with no structurally matching head records a proposal with `candidates = []`. `uncertain` builds no proposal, which is unchanged. | D-3 as the design intended. TC-INGEST-39's "a second lineage builds no proposal" is re-specified by the test plan to the FR-INGEST-38 reading |
| CT-INGEST-22 | `data`: `assessment_match_proposal.candidates` is a JSON array ordered by `semantic` descending, then `assessment_document_id` ascending. Every element carries a numeric `semantic`, and the array holds only structurally matching heads. The array may be empty. It is never an assignment (CT-INGEST unchanged). | Consumers: `M-CONSOLE` (S8), `M-SETUP` |

### 2.5 D5: the stranded FR-PROV-15 edit is adopted

Branch `ts-07-import-graph-and-payload-assertions` holds two commits (0d834ad, 08a62ea, 2026-09-02) that revised the base design to "1.5" and never merged. Their substance is a requirement the code **already implements**: `JevOpenRouterProvider` and `OpenRouterProvider` take `transport`, `clock`, `retention_answers` and `on_dispatch` (`prov.py:1490`, `:642`), and `RunCounters` and `counters()` exist (`prov.py:931`, `:1337`). So the text is adopted, with no code change.

| ID | Requirement | Notes |
|---|---|---|
| FR-PROV-15 | Each live implementation takes its environment-facing dependencies as constructor arguments that default to the real ones: the HTTP `transport`, the `clock` that backoff and `Retry-After` waits are measured against, and the `retention_answers` source `verify_retention` reads. It behaves identically whether they are supplied or defaulted. It also accepts an optional `on_dispatch` observer, a no-op by default, invoked once per dispatched model call. | Adopted from 08a62ea. Writes down shipped behaviour |
| FR-PROV-12 (amended) | … exposed as a `RunCounters` value through a `counters()` accessor. The six counters are **not a partition**. Every attempt beyond the first increments `transport_retries`, whatever provoked it, HTTP 429 included. `rate_limited_calls` counts calls throttled at least once. `cache_hit_rate` is token-weighted (`cached_prefix_tokens / tokens_in`) in `[0,1]`. | Adopted from 08a62ea. Additive |

The branch's other edits (to `test-plan.md`, `harness-adoption.md` and tests) are superseded by later work on `main` and are **not** adopted. Once this delta merges, the branch is retired.

---

## 3. Gaps disclosed by merged PRs (G1–G12)

### 3.1 G1: escalation gets its production history and baseline (`M-PIPE`)

`pipeline.py:628` calls `should_escalate(score=…, criterion=…, history=None, baseline=None)`. Both inputs have producers that nothing wires in:
- `PackageCatalog.baseline_for(v, criterion_id, population_scope_id, backend_profile, panel_build_ref, scoring_model)` (`pkg.py:2620`, from #373), shaped for `baseline=`.
- M-STATS' override history (FR-STATS-24).

The consequence is stated in the module docstring: **the distributional-anomaly and override-history limbs never fire in production.**

| ID | Requirement | Notes |
|---|---|---|
| FR-PIPE-15 | Before the aggregate hook evaluates `should_escalate` for a cell, M-PIPE obtains two inputs through each owner's public surface. It executes no SQL itself (CT-PIPE-05). <br>(a) `baseline` = `PackageCatalog.baseline_for(...)` under the run's six-part key. Population scope and backend come from the frozen `RunConfig`, `panel_build_ref` from the run row, and `scoring_model` from the criterion. <br>(b) `history` = FR-STATS-24's figure for the criterion, from a `ValidationStats` built over the run's package lineage. <br>A `NoValidationData` from either owner is passed **as is**. Both are read once per run and cached for the run's lifetime. `Assumption:` a promotion landing mid-run is not seen until the next run, which keeps a run's escalation policy fixed. | Closes gap 1 of `pipeline.py`'s docstring |
| CT-PIPE-10 | `behaviour`: the escalation inputs are the owners' values or their `NoValidationData`, never `None`. A run on a package with a promoted baseline evaluates the anomaly limb. A run on a package without one skips it. | Consumers: `M-AGG` |

`should_escalate` must treat a `NoValidationData` history as no-data. That is the existing CT-STATS-09 / FR-AGG-08 rule, and TC-REQ-41 shows it is not met today. It is a defect against an existing clause (§5.1, row R12), not a new requirement.

### 3.2 G2: statement names are unique per SQL text (`M-STORE`, ADR-32)

**The problem.**
- `aeh.store.STATEMENTS` is **one dictionary object** shared, and written at import time, by `det`, `grade`, `ingest` and `pkg`.
- `extract`, `judge` and `synth` alias the orch and ingest dictionaries.
- Measured on `a0fded4`: **eleven** statement names carry two to four different SQL texts across the loaded dictionaries: `insert_audit_record`, `select_document`, `select_document_head`, `select_evidence`, `select_question_options`, `select_regions`, `select_roster`, `select_run` (four spellings), `select_score_units`, `select_work_unit` and `upsert_criterion_score`.
- A reader of the shared dictionary gets whichever module imported last. #438 already fixed one crash of exactly this kind (`select_document_head`, TC-REG-07), and eleven more are latent.

| ID | Requirement | Notes |
|---|---|---|
| FR-STORE-16 | Across every loaded `aeh` module, each statement name maps to exactly one SQL text. A module that needs a different statement uses a different name. The shared `aeh.store.STATEMENTS` registry refuses, at import, a registration that reuses an existing name with different SQL: it raises `StatementConflictError(ValueError)` naming both registering modules. A registration with byte-identical SQL is allowed, so it is idempotent. | Makes last-writer-wins impossible rather than merely detected |
| CT-STORE-19 | `behaviour`: a statement name resolves to the same SQL whatever the import order of the `aeh` modules. `error`: a conflicting registration raises `StatementConflictError` at import and leaves the registry unchanged. | Consumers: every module that declares statements |

The rename of the eleven existing conflicts is the implementation, and the rename shifts census lines (SEC-15). No SQL text changes, so no data changes.

### 3.3 G3: decision spend counts against the mid-run ceiling (`M-ORCH`, ADR-33)

**The problem.** FR-ORCH-15's accrual (`orch.py:4209-4290`) charges each claim with the provider seam's figure for the **LLM** call. With an engine on, the decision call at a decision seat is billed too (FR-PROV-29, CT-PROV-24), and the run-start estimate includes it (FR-ORCH-37). But the mid-run guard never sees it, so a cloud run can cross its ceiling by the decision spend (finding in #495).

| ID | Requirement | Notes |
|---|---|---|
| FR-ORCH-41 | When the run froze a decision engine, the claim of a **decision-seat** score unit (FR-JUDGE-23) accrues, in the same transaction as the claim, the LLM figure **plus** the decision provider's `estimate_cost` over `HARNESS_ORCH_DECISION_TOKENS_PER_SEAT` input tokens. That is the same per-seat figure FR-ORCH-37's estimate uses. The crossing rule (strict `>`) and the at-ceiling pause apply to the sum. With the engine off, or with no decision provider bound, the accrual is unchanged, which is NFR-SYS-14. | `Assumption:` charge the conservative 100%-fallback figure at claim time. Actual decision cost is reconciled into `actual_cost` at the flush (CT-PROV-24), not refunded to `cost_spend` |
| CT-ORCH-31 | `behaviour`: for an engine-on `cloud-hosted` run, `cost_spend` after N decision-seat claims equals Σ(LLM figure + decision per-seat figure). An engine-off run's `cost_spend` is byte-identical to before. | Consumers: `M-PIPE`, `M-CONSOLE` |

### 3.4 G4: the grade footer names the run that produced the grade (`M-CONSOLE`)

**The problem.**
- CT-CONSOLE-10 says any view showing a grade shows the package version, rubric version and backend profile that produced it.
- The console renders a **module constant**, `GRADE_PROVENANCE` (`console.py:902`: `'edge-local-q4'` and fixed versions), on every run. TC-REQ-82 fails on this.
- The Jev delta's FR-CONF-26 adds the decision engine to `ProfileSummary`, and UAT-12 needs the teacher to see "Jev, at build X" under the grade. Neither can happen while the footer is a constant.

| ID | Requirement | Notes |
|---|---|---|
| FR-CONSOLE-40 | Every view that shows a grade renders its provenance from **the run that produced it**. It shows the package version and rubric version from the run row, and the backend profile and panel from the run's persisted `ProfileSummary`. When that summary carries a decision engine (FR-CONF-26), it adds `decision engine <provider> <build>`. `GRADE_PROVENANCE` survives only as the storeless audit double's value. No Jev probability or confidence figure is rendered beside a student's criterion (UAT-12's negative half). | Makes CT-CONSOLE-10 true on a real store |
| CT-CONSOLE-29 | `data`: on a real store, the provenance line under a grade equals the run's own package version, rubric version, backend profile and, when present, decision engine and build. Two runs of different profiles render two different lines. `security`: the line carries no credential, key or endpoint URL. | Consumers: `M-CONF`, `M-GRADE`. Test anchor: TC-REQ-82, UAT-12 |

### 3.5 G5: `open_review(run_id)` takes a run id (`M-REVIEW`)

**The problem** (#439 finding 9). `open_review(data_dir, *, run_id, ...)` passes `cohort_ids=[run_id]` with no scope (`review.py:3431`):
- A real run id opens `store.cohort(<run id>)`, which **creates a stray cohort file**, and finds nothing.
- A cohort id serves whichever run of that cohort is newest, and between two unstarted runs the tiebreak is a uuid comparison.

| ID | Requirement | Notes |
|---|---|---|
| FR-REVIEW-24 | `open_review(data_dir, *, run_id, ...)` resolves `run_id` to its cohort through M-ORCH's run registry (`Orchestrator.run_handle`). It scopes the service to that run's rows only. A `run_id` no store holds raises `UnknownRunError(LookupError)` naming it, and **no file is created**. | |
| CT-REVIEW-24 | `behaviour`: `open_review(run_id=R)` serves exactly run R's flagged rows, whatever other runs share R's cohort. `state`: `open_review` never creates a cohort file. | Consumers: `M-CONSOLE` |

### 3.6 G6: recovery grades a complete run that has no grades (`M-PIPE`)

**The problem.** `_grades_all_final` (`pipeline.py:1063`) reads a run with **zero** grades as settled. `aeh recover` alone therefore leaves a run killed between `complete` and grading ungraded. Today only `run_to_completion`'s own `complete` branch saves it.

| ID | Requirement | Notes |
|---|---|---|
| FR-PIPE-16 | `recover` grades every run whose status is `complete` and which holds criterion scores but no current grade row (NFR-PIPE-01's killed-after-completion state), through `GradingService`. The grading is idempotent. A run with no criterion scores is not graded. | |
| CT-PIPE-11 | `behaviour`: after `recover`, no `complete` run holds criterion scores without grades. Recovering twice writes no second grade revision. | Consumers: `M-GRADE`, `M-CONSOLE` |

### 3.7 G7: every enumerated submission reaches synthesis (`M-ORCH`, `M-PIPE`)

**The problem.** `_submissions_of` (`pipeline.py:659`) unions the two judged stages' cells. A submission whose criteria are **all deterministic** has neither, so it is never offered to synthesis and gets no narrative. No accessor lists a run's submissions.

| ID | Requirement | Notes |
|---|---|---|
| FR-ORCH-42 | `Orchestrator.submissions(run_id) -> tuple[str, ...]` returns every submission the run enumerated, in enumeration order, whatever its criteria's evaluation modes. It is read-only. | New accessor. CT-PIPE-05 keeps SQL out of M-PIPE |
| FR-PIPE-17 | The synthesis hook offers every submission of FR-ORCH-42 to M-SYNTH, including those whose criteria are all deterministic. | |
| CT-ORCH-32 | `surface`/`behaviour`: `submissions(run_id)` covers every enumerated submission, deterministic-only ones included, and never includes another run's. | Consumers: `M-PIPE` |

### 3.8 G8: an even panel after quarantine gets a replacement arm (`M-ORCH`, `M-PIPE`, ADR-34)

**The problem.** A widened five-arm panel that loses one arm to quarantine leaves four verdicts. M-AGG correctly refuses an even panel (`EvenPanelError`, FR-PIPE-05), and M-PIPE pauses the **whole run** as a composition fault. One quarantined unit can stop a 350-student run.

| ID | Requirement | Notes |
|---|---|---|
| FR-ORCH-43 | When a cell's terminal verdict count is even and non-zero because units were quarantined, `enqueue_replacement_arm(tx, key)` inserts one further escalation arm (the next `escalation-arm-<k>`, never re-adding an arm the cell carries, FR-ORCH-39) so the panel returns to odd. It is subject to the escalation budget and the breaker exactly as FR-ORCH-13 is. It returns a report saying whether the arm was inserted or refused. | |
| FR-PIPE-18 | On an even terminal panel, the aggregate hook requests FR-ORCH-43's replacement arm and leaves the cell unaggregated. When the arm is refused (budget or breaker), the cell is written `ungradeable_by_panel` (an existing `criterion_score.state`) with `reason='even_panel_after_quarantine'` and routed to review. **The run does not pause.** `EvenPanelError` still pauses the run when it arises in any other way, since that indicates a defect. | Replaces the run-level pause for this case only |
| CT-PIPE-12 | `behaviour`: one quarantined arm in a widened panel never pauses the run. The cell either gains a replacement arm or is `ungradeable_by_panel`, and every other cell completes. | Consumers: `M-AGG`, `M-REVIEW` |
| CT-ORCH-33 | `behaviour`: a replacement arm is inserted at most once per cell per quarantine, is a new arm identity, and counts against the escalation budget. | Consumers: `M-PIPE` |

### 3.9 G9: declared error types, a deprecation signal and a wall-clock seam (`M-ORCH`)

| ID | Requirement | Notes |
|---|---|---|
| FR-ORCH-28 (amended: error) | `mark_cell_phase` refuses an undeclared phase, or a negative `units_consumed`, with `WorkLedgerError`, which remains a `ValueError` subclass so existing callers keep working. Today it raises a bare `ValueError` from a pre-check (#379 finding). | Additive for catchers of `ValueError` |
| FR-ORCH-34 (amended: deprecation) | Calling `enqueue_escalation` with the two-element key emits `DeprecationWarning` once per call site, as CT-ORCH-26's "deprecated" implies. Today `orch.py` contains no `warnings.warn`. | |
| FR-ORCH-44 | `Orchestrator(store, *, wall_clock: Callable[[], datetime] \| None = None, ...)`. When supplied, every wall-time read in M-ORCH goes through it, including `_run_wall_clock_ms` and lease wall expiries; it defaults to the real UTC clock. It is behaviour-neutral when defaulted (seam 3). | Lets TC-ORCH-46's hand-computed 9,000,000 ms be asserted at rung 2 |
| CT-ORCH-34 | `config`: `wall_clock` changes no outcome when defaulted. `run_metrics.run_wall_clock_ms` computed under an injected clock equals the injected elapsed time minus paused time. | Consumers: `M-PIPE`, `M-CONSOLE` |

M-INTEG's document-cache knob refusal stays a `ValueError` naming the knob. That is the knob convention M-PIPE's Q-14 also follows. The plan's `IntegrityError` names a type the design never declared, so the plan is corrected (§6), not the code.

### 3.10 G10: `assignment_type` stays unrecorded until a package can declare it (`M-REVIEW`)

**The problem.** FR-REVIEW-21 fills `label.assignment_type` "from the package's population scope declaration". No package schema declares one, so the column is `NULL` on every label and M-STATS' `assignment_type_not_recorded` is the only answer its partition can give (#439 finding 10).

| ID | Requirement | Notes |
|---|---|---|
| FR-REVIEW-21 (amended) | `assignment_type` is `NULL` until M-PKG declares an assignment type on the population scope. That is Phase 2 and out of scope here; M-PKG does not declare it in this delta. A `NULL` is *not recorded*, never a type. | Writes down the shipped behaviour. No story |

### 3.11 G11: the cache-collapse alert does not fire over an already-low history (`M-ORCH`)

The gap delta's Q-D3 was left open. The shipped `evaluate_alerts` fires for history `[0.4, 0.4, 0.4]` with a current value of `0.39`: σ over a flat history is 0, and nothing suppresses a history already below the floor.

| ID | Requirement | Notes |
|---|---|---|
| FR-ORCH-32 (amended: cache-collapse rule) | The cache-collapse alert fires only when (a) at least `HARNESS_ORCH_CACHE_MIN_HISTORY` (3) prior values exist, (b) the current rate is below both `mean − 3σ` and the floor `0.5`, **and** (c) the history mean is above the floor. A history already below the floor is a standing condition, not a collapse. | Resolves Q-D3 with the PERF-04 runbook's reading, which TC-ORCH-45 row 8 already pins as a question |

### 3.12 G12: M-REVIEW's label records the backend it was scored on (`M-REVIEW`)

**The problem.**
- CT-STATS-04 forbids pooling two backends into one agreement figure.
- The Durable `label` table has **no** `backend_profile` column, so stored labels cannot be split by backend.
- `agreement()` computes over every admissible label, so TC-REQ-73's edge-local figure counts 16 labels instead of 8.

The split needs a column, so this is a requirement, not only a defect.

| ID | Requirement | Notes |
|---|---|---|
| FR-REVIEW-23 | Durable migration **12**, `review_label_backend_profile`, owned by `aeh.review`, adds `label.backend_profile TEXT NULL`. `record_label` and `act` fill it from the run's frozen backend profile. A pre-migration row stays `NULL`, and CT-STATS-04 treats `NULL` as *not attributable*: it is excluded from every backend-scoped figure and counted in `exclusion_reasons` as `backend_not_recorded`. The Durable pin moves 11 → 12, and the CLAUDE.md migration paragraph is updated in the same change. | |
| CT-REVIEW-25 | `data`: every label written by M-REVIEW carries the `backend_profile` of the run it judged. | Consumers: `M-STATS` (CT-STATS-04) |

`agreement()` filtering by that column is the CT-STATS-04 defect fix (§5.1, row R13).

### 3.13 One absence type (`M-STATS`/`M-PKG`), and the remaining clauses named above

**The problem.** `aeh.pkg` and `aeh.stats` each define a `NoValidationData` class (TC-REQ-61, TC-REQ-83). An `isinstance` check against one module's type misses the other's, and TC-REQ-83 says so: "This needs a design ruling."

**Ruling:** there is one class, defined in the lower module, `aeh.pkg`, because `aeh.stats` already depends on `aeh.pkg` (`record_validation_baseline`). `aeh.stats.NoValidationData` **is** that object, re-exported, so identity holds.

| ID | Requirement | Notes |
|---|---|---|
| CT-STATS-26 | `data`: `aeh.stats.NoValidationData is aeh.pkg.NoValidationData`. Every absence value either module returns is an instance of that one class, with `reason` and `n` fields. | Consumers: `M-PKG`, `M-AGG`, `M-REVIEW`, `M-CONSOLE`, `M-PIPE` |
| CT-STATS-25 | `surface`: FR-STATS-28's `criterion_disagreement_rate` and `stored_disagreement_rates` exist as stated. `behaviour`: below the minimum n they return `NoValidationData(reason='below_min_n')`. | Consumers: `M-REVIEW` |
| CT-PKG-20 | `data`/`state`: `validation_record.decision_engine_noninferior` is `NULL` (not measured), `'true'`, `'false'` or `'insufficient_data'`, and only `record_noninferiority` writes it. | Consumers: `M-STATS`, `M-CONSOLE` |
| CT-PIPE-13 | `behaviour`: every enumerated submission, deterministic-only ones included, is offered to synthesis exactly once per run (FR-PIPE-17). | Consumers: `M-SYNTH` |

---

## 4. Module inventory (delta)

No module is added or removed. Dependency edges added:
- `M-PIPE` → `M-STATS` (FR-PIPE-15(b)).
- `M-PIPE` → `M-PKG` (FR-PIPE-15(a), already present).
- `M-REVIEW` → `M-STATS` for FR-STATS-28 (already present: CT-STATS-09).
- `M-REVIEW` → `M-ORCH` for `run_handle` (FR-REVIEW-24, new).

| Module | Requirements touched here |
|---|---|
| `M-PROV` | FR-PROV-15 (adopted), FR-PROV-12 (amended) |
| `M-STATS` | FR-STATS-24 (amended), FR-STATS-28, FR-STATS-29, CT-STATS-09 (amended), CT-STATS-25, CT-STATS-26 |
| `M-REVIEW` | FR-REVIEW-18/21/22 (amended), FR-REVIEW-23, FR-REVIEW-24, CT-REVIEW-24, CT-REVIEW-25 |
| `M-PKG` | FR-PKG-23, CT-PKG-20 |
| `M-INGEST` | FR-INGEST-26 (amended), FR-INGEST-38, CT-INGEST-22 |
| `M-STORE` | FR-STORE-16, CT-STORE-19 |
| `M-ORCH` | FR-ORCH-28/32/34 (amended), FR-ORCH-41…44, CT-ORCH-31…34 |
| `M-PIPE` | FR-PIPE-15…18, CT-PIPE-10…13 |
| `M-CONSOLE` | FR-CONSOLE-40, CT-CONSOLE-29 |

*Requires (new rows)*

| Consumer | Depends on | Clauses relied on | What it assumes |
|---|---|---|---|
| `M-PIPE` | `M-PKG` | CT-PKG-07 (keyed read), `baseline_for` | The six-part key reads exactly one baseline or `NoValidationData` |
| `M-PIPE` | `M-STATS` | CT-STATS-09 (amended), CT-STATS-26 | History is a figure or the single `NoValidationData`, never `0.0` for no data |
| `M-PIPE` | `M-ORCH` | CT-ORCH-32, CT-ORCH-33 | `submissions` is complete; a replacement arm is budgeted like any escalation |
| `M-REVIEW` | `M-STATS` | CT-STATS-25 | The eighth ranking input is M-STATS' figure or its no-data value |
| `M-REVIEW` | `M-ORCH` | `run_handle` (CT-ORCH run registry) | A run id resolves to exactly one cohort, or it is unknown |
| `M-STATS` | `M-REVIEW` | CT-REVIEW-25 | A label names its backend, or is `NULL` and excluded |
| `M-STATS` | `M-PKG` | CT-PKG-20 | The verdict column exists and only `record_noninferiority` writes it |
| `M-CONSOLE` | `M-CONF` | FR-CONF-26 (`ProfileSummary` engine) | The persisted summary carries the engine when on and omits it when off |
| every declaring module | `M-STORE` | CT-STORE-19 | A name resolves to one SQL text regardless of import order |

---

## 5. Every red test on `main` @ `a0fded4`, classified

Full non-live run: **40 failed**. Re-run in isolation: **10 of them pass**, and TC-REQ-29 fails 4 times in 6 even on a clean copy of `main`. Classification:

### 5.1 Product defects against clauses that already exist (stories, no new requirement)

Each row cites the failing case, the clause it proves broken, and the owning module. The "When written" note inside each test names the exact code site. `/plan-to-issues` groups these rows into defect stories, and the cases already exist, so no `type:test` issue is needed for them.

| Row | Failing case | Clause / requirement broken | Owner | Defect (from the test's own diagnosis) |
|---|---|---|---|---|
| R1 | TC-REQ-13 | CT-CONF-06, FR-CONF-15, FR-ORCH-16 | `M-ORCH`/`M-CONF` | The run row M-ORCH persists (`panel_config = {'arms': [...]}`, a `provider_config` without the refs' provider, quantization or transcriber) cannot be rehydrated by `rehydrate_run_config`. `resume` never compares the frozen run with the current configuration |
| R2 | TC-REQ-82 | CT-CONSOLE-10 | `M-CONSOLE` | Fixed `GRADE_PROVENANCE` footer. Fixed by FR-CONSOLE-40 (§3.4) |
| R3 | TC-REQ-86 | CT-SYNTH (score-claim flag), CT-REVIEW | `M-REVIEW` | Review shows a narrative M-SYNTH flagged. The item builder copies `row.narrative` and never reads `score_claim_flag` |
| R4 | TC-REQ-21 | CT-PKG-01/06 | `M-EXTRACT` | **`extract.assemble_request` builds `Criterion(text='', evidence_type='')` and reads no catalog**, so the extractor never sees the criterion it extracts evidence for. High severity: it degrades extraction quality silently |
| R5 | TC-REQ-61, TC-REQ-83 | CT-PKG-07/12, CT-STATS-26 (§3.13) | `M-PKG`/`M-STATS` | Two `NoValidationData` classes |
| R6 | TC-REQ-09 | CT-PKG-04 | `M-SETUP` | Setup carries its own copy of the catalog's band-count parity check (`% 2 != 0`) instead of relying on the catalog's refusal |
| R7 | TC-REQ-67 | CT-PROV-08 | `M-CALIB` | `back_translate` reads scripted sessions (`_OFF_PANEL_SESSIONS`) instead of calling an `InferenceProvider`, so an unavailable off-panel model can't surface as `OffPanelUnavailable` |
| R8 | TC-REQ-53 | CT-REVIEW (review reduces provisional), CT-GRADE | `M-REVIEW` | **`ReviewService.act` records a `criterion_score` entry in its audit but never updates the row**, so M-GRADE still counts a reviewed criterion as provisional. High severity: teacher reviews do not settle grades |
| R9 | TC-REQ-59 | CT-REVIEW-07 | `M-REVIEW` | Labels from the real flows are stored without both bands, so the blind population yields `NoValidationData` instead of an agreement figure. High severity: validity reporting is empty on real stores |
| R10 | TC-REQ-88 | CT-CONSOLE-07 | `M-CONSOLE` | `BLOCKING_SCREENS` is hard-coded rather than derived from M-SETUP's enumeration |
| R11 | TC-REQ-57 | FR-REVIEW-18 (amended), CT-STATS-09 | `M-REVIEW` | The eighth input is always `None`. Fixed by D1 (§2.1) |
| R12 | TC-REQ-41 | FR-AGG-08, CT-STATS-09 | `M-AGG` | `should_escalate` reads `override_rate` off a `NoValidationData`, finds it absent, and skips the no-data weight, so no data is routed like a zero |
| R13 | TC-REQ-73 | CT-STATS-04 | `M-STATS` | `agreement()` pools backends. Needs FR-REVIEW-23's column (§3.12), then a filter |
| R14 | TC-REQ-79 | CT-STATS-03/04, FR-CONSOLE-10 | `M-CONSOLE`/`M-STATS` | A figure with no population, backend or panel build renders as "scoped to this population and backend" |
| R15 | TC-CONSOLE-21, 22, 39, 02[finalize batch] | FR-CONSOLE-34 (#398), FR-CONSOLE-02/21/22 | `M-CONSOLE`, `M-GRADE` | #398's remaining scope: in-memory ledgers, unwired review action, and M-GRADE's second `finalize_batch` rewriting `run_metrics` |
| R16 | TC-CONSOLE-23 | FR-CONSOLE-23 | `M-CONSOLE` | The export gate reads its caller's argument, default 0, instead of the package's `contains_real_student_text`, and never reaches M-PKG's `ExportBlockedError` |
| R17 | TC-CONSOLE-24 | FR-CONSOLE-24 | `M-CONSOLE` | The rollup never reads the validation record, so it renders the absence sentence even when a record exists |
| R18 | TC-CONSOLE-11, 12 | FR-CONSOLE-11/12, invariant 7 | `M-CONSOLE` | **The teacher's review queue is empty on every real store**: the console reads `review_queue` by `run_id`/`rank_position`, columns the cohort table does not have, and swallows the error. It must read M-REVIEW's admitted population (FR-REVIEW-18), not the table M-GRADE also writes rescan rows into |
| R19 | TC-CONSOLE-29 | FR-CONSOLE-29 | `M-CONSOLE` | S8 renders a static placeholder image instead of the region's `crop_ref` |
| R20 | TC-CONSOLE-27 | FR-CONSOLE-27 | `M-CONSOLE` | The upload handler writes no record of what arrived, so S2 falls back to a hard-coded page order |

### 5.2 One test-support defect explains 10 failures (§6, finding T1)

TC-INGEST-02; TC-INGEST-25 [b], [d]; TC-INGEST-28 ×4; TC-INGEST-39; ADV-07; TC-ORCH-36. All pass in isolation. `tests/support/e2e_world.py` (`WORLD_ENV`: `HARNESS_INGEST_DPI=72`, `HARNESS_INGEST_V4_SEMANTIC_FLOOR=0.0`, `HARNESS_ORCH_RANDOM_ARM_RATE=0`) and `tests/support/pipe_world.py` (`HARNESS_ORCH_ESCALATION_BUDGET`) write `os.environ` directly when no `monkeypatch` is passed, and never restore it. Every later test in the process inherits the values. The three intermittent `test_ct_ingest_v4_halting` gate failures are the same leak.

### 5.3 To triage before classifying (§6)

| Case | Observation | Likely class |
|---|---|---|
| TC-REQ-14 ×2 | `progress()` does not raise the injected terminal error | Stale fixture: score units now need the `integrity_pre` phase (FR-ORCH-30, #362) before they dispatch |
| TC-REQ-29 | Extraction quarantine outcome varies run to run on untouched `main` (4/6 fail) | Nondeterministic test or product race. Must be resolved, not retried |
| TC-STORE-04 | Post-migration checksums differ from `fixtures/F-SCHEMA/post-migration-checksums.json` | A migration since the golden (Cohort 28/29, #484) changed data. Decide: re-bless consciously, or a data-changing migration defect |
| ADV-10 | "no probed page issued a query", so the trace half of the oracle swept nothing | Oracle made vacuous by a console change. Re-point it at pages that query |

---

## 6. Findings for `/create-test-plan` (test-side, no design change)

| # | Finding | Action for the plan |
|---|---|---|
| T1 | Test-support env leak (§5.2) | A regression case: every world builder restores `os.environ` (or refuses to run without `monkeypatch`), plus a process-level guard that fails a test which leaves a `HARNESS_*` variable changed |
| T2 | TC-INTEG-C12 and TC-INTEG-11 assert NFR-INTEG-01's 1% on a **small** drive and flake about 2 runs in 4 | NFR-INTEG-01 fixes the scale (PERF-06, full run), so re-specify both at PERF-06's scale under `slow`/`HARNESS_PERF_GATE`, or retire them into PERF-06 |
| T3 | #507's three hand-checked paths | Regression cases: SDK key refusal at client build → `ConfigurationError`; 408 retried; the per-attempt `decision_provider_unreported` flag |
| T4 | #470's automated gaps | SEC-19's roster-name arm (add display names to the corpus), ADV-15's blind-sample arm, TC-E2E-05's hand-computed α and confidence, and its review-queue check |
| T5 | TC-INTEG-17 arm (c) names an undeclared `IntegrityError` | Assert `ValueError` naming the knob (§3.9) |
| T6 | TC-PIPE-05 expects `state = 'provisional'` | The vocabulary is `provisional_unreviewed` |
| T7 | `StoreExtractionView`'s constructor is stated two ways (FR-PIPE-10 vs FR-INTEG-09) | The shipped signature is `(handle, catalog, package_version_id, run_id='')` |
| T8 | TC-ORCH-45 row 8 | Now pinned by FR-ORCH-32 (amended): no alert |
| T9 | TC-INGEST-39 (second lineage builds no proposal), TC-INGEST-52 | Re-specify both to FR-INGEST-38 and FR-INGEST-26 (amended) |
| T10 | TC-STATS-31 arms 2 and 4, `writtenahead` on #433 | Arm 2 is keyed to the M-STATS minimum-n rule (FR-STATS-24 amended); arm 4 to FR-REVIEW-18's wiring from FR-STATS-28. The single `#433` blocker probe should become two |
| T11 | Every §5.1 row whose case exists | No new case. The existing case is the acceptance test for its defect story |
| T12 | §5.3 | Triage outcomes become either a re-specified case or a defect row |

---

## 7. System-level (delta)

### 7.1 Architecture Decision Records

#### ADR-30: two override figures, two names
- **Context.** A validity population (blind) and an operational population (all reviews) were both called "override rate" (D1).
- **Decision.** `criterion_override_history` (blind, validity) and `criterion_disagreement_rate` (all reviews, ranking), both with the minimum-n rule, both in M-STATS.
- **Consequences.** The ranking gets a usable input in production. κ's population is untouched. No module derives a rate of its own.
- **Rejected alternatives:**
  - One figure over blind labels only: inert in production.
  - One figure over all labels: contaminates validity.

#### ADR-31: no historical `label.cohort_id` backfill
- **Context.** The map lives in cohort tiers a Durable migration cannot open. The system is pre-release, so no historical rows exist.
- **Decision.** Amend FR-REVIEW-22. Old rows stay `NULL`, and purge fails closed.
- **Rejected alternatives:**
  - A two-tier maintenance tool: work for rows that don't exist.
  - Carrying the map into Tier D: puts cohort identity into the pseudonymised tier (CT-STORE-09).

#### ADR-32: one SQL text per statement name, enforced at import
- **Context.** Eleven latent last-writer-wins conflicts.
- **Decision.** Refuse conflicting registration and rename the conflicts.
- **Rejected alternative:** a per-module namespace prefix on every name. It is a larger churn of every census line for the same guarantee.

#### ADR-33: charge decision spend at claim time with the conservative per-seat figure
- **Context.** The mid-run ceiling guard runs before the call, so the actual decision cost is unknown at claim time.
- **Decision.** Charge FR-ORCH-37's per-seat figure, the same one the start estimate uses.
- **Consequences.** A run may pause somewhat early. It never overshoots on decision spend.

#### ADR-34: an even panel after quarantine is a cell problem, not a run problem
- **Decision.** Add one replacement arm. If that is refused, mark the cell `ungradeable_by_panel` and route it to review.
- **Consequences.** One quarantined unit no longer halts a class. FR-PIPE-05's "never aggregate an even panel" still holds.

### 7.2 Amendment classification (base §4.7)

| Change | Class | Obligation |
|---|---|---|
| FR-STATS-24 signature and minimum n; CT-STATS-09 widened | Behavioural narrowing (below n becomes no-data) | Re-verify `M-AGG` and `M-REVIEW` (CT-STATS-09 consumers). TC-STATS-31 arm 2 is the anchor |
| CT-STATS-26 single absence type | **Additive**: the two classes become one object, so every existing `isinstance` check against either name keeps passing | TC-REQ-61/83 |
| FR-STORE-16 / CT-STORE-19 | Additive (a new refusal of a state that was always a defect) | SEC-15 census re-pin |
| FR-ORCH-41 / CT-ORCH-31 | Behavioural change on engine-on cloud runs only; engine-off byte-identical | TC-REG-08/09 stay green |
| FR-ORCH-28/34 amended | Additive (subclass; warning) | — |
| FR-PIPE-18 | Changes the observable outcome of one fault path, from run pause to cell `ungradeable_by_panel` | Re-verify `M-REVIEW` (routes the cell) |
| FR-INGEST-26/38 | Behavioural change in multi-lineage stores only | TC-INGEST-39/52 re-specified |
| FR-REVIEW-21/22 amended | Documentation of shipped behaviour | — |
| FR-PKG-23, FR-REVIEW-23 | Additive migrations | Package pin 12 → 13, Durable pin 11 → 12, and the CLAUDE.md migration paragraph |

### 7.3 Contract register (delta)

| Module | Contract | Clauses added | Version |
|---|---|---|---|
| `M-STATS` | CT-STATS | 25, 26 (+ 09 amended) | minor |
| `M-REVIEW` | CT-REVIEW | 24, 25 | minor |
| `M-PKG` | CT-PKG | 20 | minor |
| `M-INGEST` | CT-INGEST | 22 | minor |
| `M-STORE` | CT-STORE | 19 | minor |
| `M-ORCH` | CT-ORCH | 31–34 | minor |
| `M-PIPE` | CT-PIPE | 10–13 | minor |
| `M-CONSOLE` | CT-CONSOLE | 29 | minor |

### 7.4 Landing order (for `/plan-to-issues`)

1. **Test-support env leak (T1).** It removes 10 false reds and the gate's flakes first, so every later story has an honest signal.
2. **Foundations:** FR-STORE-16 (statement names), CT-STATS-26 (one absence type), FR-ORCH-28/34/44 (error type, warning, wall clock).
3. **Schema:** FR-PKG-23 (Package 13), FR-REVIEW-23 (Durable 12).
4. **High-severity defects:** §5.1 R4 (extraction gets its criterion), R8 (review settles scores), R9 (labels carry both bands), R18 (the teacher's queue reads the admitted population).
5. **M-STATS/M-REVIEW:** D1 (FR-STATS-24/28, FR-REVIEW-18), R12, R13, R14, FR-REVIEW-24.
6. **M-ORCH/M-PIPE:** FR-ORCH-41, FR-ORCH-42 with FR-PIPE-17, FR-ORCH-43 with FR-PIPE-18, FR-PIPE-15, FR-PIPE-16, R1.
7. **M-CONSOLE:** #398's remainder (R15), R16, R17, R19, R20, R10, FR-CONSOLE-40 (R2).
8. **M-INGEST:** FR-INGEST-38 with the FR-INGEST-26 amendment (#376).
9. **Remaining defects:** R3, R6, R7, and the §5.3 triage outcomes.

---

## 8. Validation log: assumptions checked against `src/aeh` @ `a0fded4`

| Claim | Checked at |
|---|---|
| `should_escalate` receives `history=None, baseline=None` | `pipeline.py:628-629` |
| `baseline_for` exists and is shaped for `baseline=` | `pkg.py:2620-2660` |
| `criterion_override_history` counts `origin == 'override'` over `admissible_labels()` with no minimum n | `stats.py:4165-4195` |
| `REVIEW_OVERRIDE_MIN_N` is consumed nowhere past `_calibration_knobs` | `review.py:474`, `:1274` |
| Semantic signal is `absent` with more than one lineage head | `ingest.py:4800-4803` |
| Assessment documents carry no package link | `store.py:1133` (`document`), `ingest.py:2003-2006` |
| Proposal candidates are all heads, ranked by a composite score | `ingest.py:4971-5020` |
| Eleven statement names with conflicting SQL; `store.STATEMENTS` shared by det/grade/ingest/pkg | Import-time scan of all 20 modules (§3.2) |
| Accrual charges only the provider seam's figure | `orch.py:4209-4290` |
| `GRADE_PROVENANCE` is a module constant | `console.py:902-910` |
| `open_review` passes `cohort_ids=[run_id]` | `review.py:3427-3432` |
| `_grades_all_final` reads zero grades as settled | `pipeline.py:1063-1078` |
| `_submissions_of` unions judged stages only | `pipeline.py:659-671` |
| FR-PROV-15's seams exist in code | `prov.py:642`, `:1490-1504`, `:931`, `:1337` |
| Environment leak in world builders | `tests/support/e2e_world.py:170-174, 562-565`, `pipe_world.py:227-231` |

---

## 9. Open questions

| ID | Question | Default taken |
|---|---|---|
| Q-C1 | Should FR-STATS-28 weight a label by `band_distance` rather than counting any disagreement? | No: a count, matching FR-REVIEW-03's P(error) reading. Revisit with Phase 2 data |
| Q-C2 | Should a promotion mid-run refresh escalation inputs (FR-PIPE-15)? | No: fixed per run, so a run's policy cannot drift |
| Q-C3 | Should FR-ORCH-41 refund the difference between the charged and the actual decision cost to `cost_spend`? | No: `cost_spend` is a guard, not a bill, and `actual_cost` carries the truth (ADR-33) |
| Q-C4 | TC-STORE-04's golden (§5.3): re-bless, or treat as a data-changing migration defect? | Triage decides. A re-bless must cite the migration that changed the data |

---

## Handoff

The design is stage 1 of 4. Next:

```bash
/create-test-plan docs/design/
```

The `CT-*` clauses added here (CT-STATS-25/26, CT-REVIEW-24/25, CT-PKG-20, CT-INGEST-22, CT-STORE-19, CT-ORCH-31…34, CT-PIPE-10…13, CT-CONSOLE-29) are the contract, integration and regression layer. Each clause is one assertion. Each new `Requires` row in §4 is one integration case between a named pair. §5.1's twenty rows already have their cases, so `/plan-to-issues` turns them into defect stories whose acceptance test is the existing case. `/create-test-plan` should take §6 as its reconciliation input.
