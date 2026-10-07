# Test Plan Delta: Backlog Close-out

**Design under test:** `docs/design/closeout_design_delta.md` v1.9-delta, on top of `detailed-design.md` v1.4, `fix_gaps_detailed_design_plan.md` v1.5.1 and `jev_decision_engine_design_delta.md` v1.8.
**Plans this applies on top of:** `test-plan.md` v1.2, `gap_fix_test_plan.md` v1.3.1 and `jev_test_plan.md` v1.6-delta.
**Code baseline:** `main` @ `a0fded4`.
**Version:** 1.7-delta  **Date:** 2026-09-27  **Status:** Draft, for `/plan-to-issues`.
**Author:** `/create-test-plan`, delta mode.

---

## 1. Scope and the confidence claim

This delta plans the tests for design 1.9. It does three things:

1. **New cases for the new requirements and clauses**: D1–D5 and G1–G12 (design §2–§3).
2. **A reconciliation of existing cases** (§5.0). It covers the cases design 1.9 re-specifies, the cases found stale or vacuous (design §5.3), and the test-harness findings (design §6, T1–T12).
3. **Mapping the twenty defect rows of design §5.1 to cases that already exist.** Those rows need no new case. The existing red case *is* the acceptance test of the defect story `/plan-to-issues` creates for it (§5.9).

**The claim, if every case here passes:**
- The five decisions and twelve gaps are implemented as design 1.9 states.
- The twenty defects against existing clauses are fixed. Their cases are already written and are red today.
- The full non-live tier has no failure caused by test-support state leaking between tests.

**What it does not claim.** Anything on the #157 release checklist: hardware-gated performance, live OpenJev and OpenJevSmall, the container deployment, and the teacher try-out. None of it changes here.

---

## 2. System under test (delta)

### 2.1 Requirements inventory

| ID | Module | Kind | Testability note |
|---|---|---|---|
| FR-PROV-15 | M-PROV | adopted, shipped | Behaviour-neutral seams: injected vs defaulted must be indistinguishable |
| FR-PROV-12 (amended) | M-PROV | adopted, shipped | The non-partition rule is observable with a programmed 429 |
| FR-STATS-24 (amended) | M-STATS | new rule (min n) | Boundary at n = 4 / 5 |
| FR-STATS-28 | M-STATS | new | Population inclusion/exclusion, and the minimum n |
| FR-STATS-29 | M-STATS | new | Engine on vs off, plus NULL vs `insufficient_data` |
| FR-REVIEW-18 (amended) | M-REVIEW | new wiring | Rank must move with the input |
| FR-REVIEW-21 (amended) | M-REVIEW | documents shipped | Already pinned by TC-REVIEW-28's absence arm |
| FR-REVIEW-22 (amended) | M-REVIEW | documents shipped plus fail-closed | Purge gate on a pre-rule row |
| FR-REVIEW-23 | M-REVIEW | new migration | Durable 12 |
| FR-REVIEW-24 | M-REVIEW | defect-shaped new | Two runs, one cohort |
| FR-PKG-23 | M-PKG | new migration | Package 13, CHECK domain |
| FR-INGEST-26 (amended) | M-INGEST | new candidate rule | Ordering, empty array |
| FR-INGEST-38 | M-INGEST | new | 0 / 1 / 2 qualifying heads |
| FR-STORE-16 | M-STORE | new | Import order, conflict, identical re-registration |
| FR-ORCH-28 (amended) | M-ORCH | error type | `isinstance` both ways |
| FR-ORCH-32 (amended) | M-ORCH | alert rule | Q-D3 row |
| FR-ORCH-34 (amended) | M-ORCH | deprecation | Warning captured |
| FR-ORCH-41 | M-ORCH | new | Sum at the ceiling boundary |
| FR-ORCH-42 | M-ORCH | new accessor | Deterministic-only submission |
| FR-ORCH-43 | M-ORCH | new | Budget refusal |
| FR-ORCH-44 | M-ORCH | new seam | Exact wall-clock figure |
| FR-PIPE-15 | M-PIPE | new | Baseline present/absent, and history no-data |
| FR-PIPE-16 | M-PIPE | new | Killed after completion |
| FR-PIPE-17 | M-PIPE | new | All-deterministic package |
| FR-PIPE-18 | M-PIPE | new | Even panel after quarantine |
| FR-CONSOLE-40 | M-CONSOLE | new | Two runs, two profiles, engine line |

### 2.2 Contract inventory

| Clause | Kind | Consumers |
|---|---|---|
| CT-STATS-09 (amended) | surface | M-AGG, M-REVIEW |
| CT-STATS-25 | surface/behaviour | M-REVIEW |
| CT-STATS-26 | data | M-PKG, M-AGG, M-REVIEW, M-CONSOLE, M-PIPE |
| CT-REVIEW-24 | behaviour/state | M-CONSOLE |
| CT-REVIEW-25 | data | M-STATS |
| CT-PKG-20 | data/state | M-STATS, M-CONSOLE |
| CT-INGEST-22 | data | M-CONSOLE, M-SETUP |
| CT-STORE-19 | behaviour/error | every declaring module |
| CT-ORCH-31 | behaviour | M-PIPE, M-CONSOLE |
| CT-ORCH-32 | surface/behaviour | M-PIPE |
| CT-ORCH-33 | behaviour | M-PIPE |
| CT-ORCH-34 | config | M-PIPE, M-CONSOLE |
| CT-PIPE-10 | behaviour | M-AGG |
| CT-PIPE-11 | behaviour | M-GRADE, M-CONSOLE |
| CT-PIPE-12 | behaviour | M-AGG, M-REVIEW |
| CT-PIPE-13 | behaviour | M-SYNTH |
| CT-CONSOLE-29 | data/security | M-CONF, M-GRADE |

### 2.3 Open questions

| ID | Affects | Question | Default for this plan |
|---|---|---|---|
| Q-45 | FR-PIPE-15 | The design caches escalation inputs per run (Q-C2). Should a case pin that a mid-run promotion is **not** seen? | Yes: TC-PIPE-20 arm (d) pins it, so a later change to "refresh" is a visible design change |
| Q-46 | TC-STORE-04 | The golden differs. Re-bless or defect (design Q-C4)? | TS-128 triages it. A re-bless must name the migration in the commit |
| Q-47 | TC-REQ-29 | Nondeterministic on untouched `main`. Test race or product race? | TS-128 must find the root cause. A retry decorator is **not** an acceptable fix |

---

## 3. Risk register (delta)

| Risk | Where | Failure imagined concretely | Blast radius | Detectability | Severity | Depth |
|---|---|---|---|---|---|---|
| RISK-91 | Design §5.1 R4 (M-EXTRACT) | Every extraction request carries `text=''`, so the extractor guesses what evidence to look for and every judged score rests on the wrong spans | Every judged cell, every student | **Silent**: scores look plausible | Critical | Existing TC-REQ-21 at rung 2 is the acceptance test, and the E2E journeys re-run |
| RISK-92 | R8 (M-REVIEW) | A teacher reviews a criterion, the grade stays provisional and export shows the unreviewed band | Grades | Silent until a teacher notices their edit is missing | Critical | TC-REQ-53 |
| RISK-93 | R18 (M-CONSOLE) | The teacher's review queue is empty on every real store, so the teacher try-out finds nothing to review | Teacher workflow | Visible, but only on a real store | Critical | TC-CONSOLE-11/12 |
| RISK-94 | R9 (M-REVIEW) | Labels miss a band, so every agreement figure is `NoValidationData` and validity reporting is empty | Validity claims | Silent | High | TC-REQ-59 |
| RISK-95 | G2 / CT-STORE-19 | A module reads another module's `select_run` spelling because of import order; missing column → crash far from the cause | Any module | Silent until an import order changes | High | TC-STORE-28 (all modules, both import orders), TC-STORE-C19 |
| RISK-96 | G1 / CT-PIPE-10 | Escalation never uses the baseline in production, so outlier scores are never widened to 3 judges | Score quality | Silent | High | TC-PIPE-20, TC-PIPE-C10, TC-REQ-119/120 |
| RISK-97 | D1 / CT-STATS-09, -25 | The ranking reads the blind-only figure (always no-data), or validity reads operational labels (κ contaminated) | Review ranking, validity | Silent | High | TC-STATS-36/37, TC-REVIEW-32, TC-STATS-C25 |
| RISK-98 | G8 / CT-PIPE-12 | One quarantined arm pauses a 350-student run overnight | Whole run | Visible in the morning, too late | High | TC-PIPE-23, TC-ORCH-56, TC-PIPE-C12 |
| RISK-99 | G4 / CT-CONSOLE-29 | Every grade says `edge-local-q4` whatever produced it, so a teacher trusts the wrong provenance | Every grade view | Silent | High | TC-CONSOLE-50, TC-CONSOLE-C29, SEC-24 |
| RISK-100 | T1 (test support) | A world builder leaks `HARNESS_INGEST_V4_SEMANTIC_FLOOR=0.0`, so ingest cases fail or pass by test order and a real regression hides among false reds | The whole suite's honesty | Only under certain orders | High | TC-REG-10 |
| RISK-101 | G6 / CT-PIPE-11 | `aeh recover` after a kill leaves a complete run with no grades, so nothing is exported | One run | Visible | High | TC-PIPE-21, RES-25 |
| RISK-102 | G3 / CT-ORCH-31 | A cloud Jev run crosses its cost ceiling by the decision spend | Money | Visible on the bill | Medium | TC-ORCH-54, TC-ORCH-C31 |
| RISK-103 | G5 / CT-REVIEW-24 | `open_review(run_id)` creates a stray cohort file and serves a random run | Review | Silent | Medium | TC-REVIEW-35, TC-REVIEW-C24 |
| RISK-104 | G7 / CT-PIPE-13 | A multiple-choice-only paper gets no narrative | That student | Visible | Medium | TC-PIPE-22, TC-ORCH-55 |
| RISK-105 | D3 / CT-PKG-20 | The non-inferiority verdict is computed and thrown away | Engine governance | Silent | Medium | TC-PKG-33, TC-STATS-38 |
| RISK-106 | D4 / CT-INGEST-22 | A multi-lineage store never proposes, or proposes the wrong papers first | Setup | Visible to the operator | Low (Phase 2) | TC-INGEST-54/55, TC-INGEST-C22 |
| RISK-107 | G12 / CT-REVIEW-25 | Labels from two backends pool into one κ stamped with one backend | Validity | Silent | High | TC-REVIEW-34, TC-REVIEW-C25, TC-REQ-73 |

**Depth rule for this delta.** Every Critical and High risk gets a rung-2 case against a real store, plus a clause case in §6.11 that goes red on the plausible regression.

---

## 4. Strategy (delta)

The base plans' strategy stands. Four rules are specific to this delta:

1. **Defect rows get no new case** (§5.9). A red case that already names the defect is a better acceptance test than a fresh one, because it was written before anyone knew how the fix would look.
2. **Environment hygiene becomes a regression case** (TC-REG-10), because the leak it catches produced 10 false reds and the gate's only flakes. From this delta on, `tests/support` world builders take `monkeypatch` **or** restore what they set.
3. **Written ahead of implementation.** Every case against a design 1.9 requirement is `writtenahead`, keyed to its implementing story. Cases against shipped behaviour (FR-PROV-12/15, #507 regressions, T1–T12 re-specifications) are green on landing.
4. **Oracles.** Exact values wherever the design gives numbers (min n = 5, the 0.05 margin, and so on). Structural oracles for the import-order property: every permutation of two known-conflicting importers resolves identically.

**Mock vs real.** Every case in §5 is rung 2 (a real store) unless marked. A double never stands in for M-STATS, M-PKG or M-ORCH on the new clauses: those are the providers under test.

**Blast-radius rule (§6.12).** A change to a module re-runs its §6.11 clause suite plus the TC-REQ cases of every consumer named in §2.2.

---

## 5. Test cases

### 5.0 Reconciliation of existing cases

| Case | Today | Change | Why |
|---|---|---|---|
| TC-INGEST-39 | Green: "a second lineage builds no proposal" | **Re-specified**: with two lineage heads, one of whose inventory equals the package's, the semantic signal is computed against that head (FR-INGEST-38). With two qualifying heads it stays `absent`, and then no proposal | Design D4 |
| TC-INGEST-52 | Written in TS-102 (#396), unimplementable | **Re-specified**: the submission mismatches the run's package on identifier, structure and semantics. The store holds the package's own head plus three **other** heads whose inventory equals the submission's, with lexical affinity 0.2 / 0.6 / 0.9. Expected: outcome `mismatch`, and candidates `[0.9, 0.6, 0.2]` in that order, each with a numeric `semantic`. Stays in TS-102 | Design FR-INGEST-26 (amended) |
| TC-ORCH-45 row 8 | Asserted neither way | **Re-specified**: history `[0.4, 0.4, 0.4]`, current `0.39` → **no** cache-collapse alert. Row 8b: history `[0.8, 0.8, 0.8]`, current `0.39` → fires | FR-ORCH-32 (amended) |
| TC-ORCH-47 arm (b) | Not asserted | **Re-specified**: the two-element key emits `DeprecationWarning` (`pytest.warns`) | FR-ORCH-34 (amended) |
| TC-INTEG-17 arm (c) | Asserts the refusal's message | **Re-specified**: the type is `ValueError` naming `HARNESS_INTEG_DOCUMENT_CACHE_ENTRIES` | Design §3.9, T5 |
| TC-INTEG-11, TC-INTEG-C12 | Flaky, small drive | **The under-1% arms are retired into PERF-06** (`tests/perf/test_perf_06_zero_model_stages_full_run.py`, full-run scale). The cases' other arms (linearity, no model call, total verification) stay | NFR-INTEG-01 fixes the scale, T2 (retire option) |
| TC-PIPE-05 | Unwritten; expects `state = 'provisional'` | **Re-specified**: `provisional_unreviewed` | T6 |
| TC-STATS-31 arms 2 and 4 | `writtenahead` on one `#433` probe | **Re-keyed**: arm 2 to the FR-STATS-24 min-n story (probe: `below_min_n` in `aeh.stats`); arm 4 to the FR-REVIEW-18 wiring story (probe: `stored_disagreement_rates` in `aeh.review`) | T10 |
| TC-REVIEW-25, arm "`historical_override_rate is None`" | Green; pins an absence | **Re-specified** to TC-REVIEW-32's presence assertion, marked `writtenahead` on the FR-REVIEW-18 story in the same PR that adds TC-REVIEW-32. The absence pin is removed from the test, not deleted as a test | D1 makes the absence false |
| TC-REQ-14 | Red: `progress()` never raises | **Re-specified** fixture: mark `integrity_pre` for the seeded cells before `progress()` (FR-ORCH-30), so the score units reach the terminal seam. The oracle is unchanged | Stale fixture, design §5.3 |
| TC-REQ-29 | Intermittent on untouched `main` | **Triage** (TS-128): find the source of nondeterminism and fix it in the test or file a defect. No retry | Q-47 |
| TC-STORE-04 | Red: checksums differ | **Triage** (TS-128): re-bless citing the migration, or file a data-changing-migration defect | Q-46 |
| ADV-10 | Red: "no probed page issued a query" | **Re-specified**: probe the pages that do query (the S9/S12 grade views on a real store). The oracle must sweep at least one query | Vacuous oracle, design §5.3 |
| SEC-19 | Roster-name arm unwritten | **Arm added**: F-JEV-DECISIONS gains display names, and no roster name appears in any decision request or log | T4 |
| ADV-15 | Blind-sample arm unwritten | **Arm added**: the blind sample never shows a decision-engine band or confidence | T4 |
| TC-E2E-05 | α, confidence and queue arms unwritten | **Arms added**: hand-computed ordinal α over F-JEV-SYNTH's labels, the accepted verdicts' gate confidences, and the review queue's size | T4 |

### 5.1 M-PROV (shipped behaviour, written down)

| ID | Req | Preconditions / input | Rung | Expected | Oracle | P |
|---|---|---|---|---|---|---|
| TC-PROV-55 | FR-PROV-15 | `OpenRouterProvider` and `JevOpenRouterProvider`, each built twice: once with defaults, once with an injected programmed `Transport`, a `FrozenClock` and a `retention_answers` returning `"zero-retention"`. The same request goes through a transport that answers 429 then 200 | 1 | (a) The injected build produces the same result, the same counters and the same errors as a default build pointed at the same programmed responses. (b) `on_dispatch` is called exactly once per model call (1 for a call answered 429 then 200: FR-PROV-15 observes the call, not each attempt). (c) Backoff sleeps are measured on the injected clock, so the test takes < 1 s real time | Differential + exact count | P1 |
| TC-PROV-56 | FR-PROV-12 (amended) | A call that gets 429, 429, then 200. A second call that gets 200. Token usage: in 1000, cached prefix 400; then in 500, cached 0 | 1 | `transport_retries == 2`; `rate_limited_calls == 1` (not 2: calls throttled at least once); `cache_hit_rate == 400/1500` | Exact | P1 |
| TC-PROV-57 | FR-PROV-41 (#507) | `JevOpenRouterProvider(api_key="sk or with space")` and `api_key="   "`, SDK installed | 1 | `ConfigurationError` at construction or first `decide`, never a `typesafe_sdk` exception type, with 0 sends | Type + count | P1 |
| TC-PROV-58 | FR-PROV-41 (#507) | Programmed transport: 408, then 200 | 1 | `decide` returns; 2 sends; `transport_retries == 1`; no pause | Exact | P1 |
| TC-PROV-59 | FR-PROV-43 (#507) | Attempt 1: 200 with a body lacking `provider` that then fails validation (no `answers`), so it reaches the routing check and is retried. Attempt 2: 200 with `provider` present and pinned (a 503 never reaches the routing check, so it cannot tell a per-attempt flag from a sticky one) | 1 | `decision_provider_unreported == 0`: the flag is per attempt, so a failed attempt's absence does not count. Swap the order (first 200 without `provider`) → `1` | Exact | P1 |

### 5.2 M-STATS

| ID | Req | Preconditions / input | Rung | Expected | Oracle | P |
|---|---|---|---|---|---|---|
| TC-STATS-36 | FR-STATS-24 (amended) | A `ValidationStats` over one lineage. C1 has 4 admissible blind labels (1 override). C2 has 5 (1 override). C3 has 0. C4 has 5 blind plus 10 operational (0 overrides among the blind) | 0 | C1 → `NoValidationData(reason='below_min_n', n=4)`. C2 → `override_rate == 0.2`, `n == 5`. C3 → `reason='no_blind_labels', n=0`. C4 → `n == 5`, rate `0.0`: operational labels are excluded. With `HARNESS_REVIEW_OVERRIDE_MIN_N=4` set **between calls**, C1 → `0.25` (read at call time) | Exact | P0 |
| TC-STATS-37 | FR-STATS-28 | C1 has 3 blind plus 3 operational labels with both bands, 2 of them disagreeing, and 2 more labels missing `teacher_band`. C2 has 4 labels with both bands | 2 | C1: `n == 6` (both-band labels only), `disagreements == 2`, `rate == 1/3`. C2 → `below_min_n`. `stored_disagreement_rates(store, v)` returns one entry per criterion of `v`, equal to the in-memory figures. A static scan finds no `system_band !=` comparison anywhere in `src/aeh/review.py` | Exact + static scan | P0 |
| TC-STATS-38 | FR-STATS-29 | `promote` over F-STATS-JEV. (a) An engine-on run with α_decision 0.70 and α_llm 0.74 at 60 labels each. (b) The same with 59 decision labels. (c) An engine-off run | 2 | (a) `validation_record.decision_engine_noninferior == 'true'`. (b) `'insufficient_data'`. (c) `NULL`, byte-identical to before for every other column | Exact | P1 |

### 5.3 M-REVIEW

| ID | Req | Preconditions / input | Rung | Expected | Oracle | P |
|---|---|---|---|---|---|---|
| TC-REVIEW-32 | FR-REVIEW-18 (amended) | A store-backed queue, two criteria identical except the stored disagreement rate: C-HI at 0.6 over 10 labels, C-LO at 0.0 over 10. A third, C-NONE, has 2 labels | 2 | `historical_override_rate`: C-HI 0.6, C-LO 0.0, C-NONE no-data (not `0.0`). C-HI ranks above C-LO. Removing the input (mutation) makes the two ranks equal | Exact + mutation | P0 |
| TC-REVIEW-33 | FR-REVIEW-22 (amended) | A Durable `label` row written with `cohort_id = 'run-XYZ'` (the pre-rule shape) for cohort `c-1`, whose other rows are purgeable | 2 | The purge of `c-1` fails closed (the precondition is not met), naming the unattributable label. No code path rewrites the row. A fresh label for an unresolvable run stores `NULL` | Exact | P1 |
| TC-REVIEW-34 | FR-REVIEW-23 | A Durable store opened at chain 11, then migrated to 12. Labels recorded from an `edge-local` run and a `cloud-hosted` run. One pre-migration row | 2 | The column exists. Labels carry `'edge-local'` / `'cloud-hosted'`. The pre-migration row is `NULL`. `exclusion_reasons()` counts it under `backend_not_recorded`. `COMPLETE_SCHEMA_VERSIONS['durable'] == 12` | Exact | P0 |
| TC-REVIEW-35 | FR-REVIEW-24 | Runs `R1` and `R2` in cohort `c-1` with different flagged rows. `open_review(run_id=R1)`, `open_review(run_id=R2)`, `open_review(run_id='run-nope')` | 2 | Each service holds only its own run's rows. The unknown run raises `UnknownRunError` naming `run-nope`, and the data dir's file listing is unchanged (no `run-nope` cohort file) | Exact + file listing | P0 |
| TC-REVIEW-36 | FR-REVIEW-09 (regression, #398) | Two `review_service_over` services over one store, opened one after the other (the console builds one per request), each record an `edit` label | 2 | Both labels land, with distinct `label_id`s. Before #398 the per-instance counter minted `label-0001` twice and the second insert failed on the primary key | Exact | P0 |
| TC-REVIEW-37 | FR-STATS-24 (regression, #525 item 3) | Two packages `pkg-alpha` and `pkg-beta` each declaring `C1`. Five collected labels (`record_label(data_dir=, label=)`) naming `pkg-alpha`'s version, one of them an override | 2 | Every stored `label` row carries the package the label names (never NULL). `stored_override_histories` gives `pkg-alpha`'s `C1` n=5 / 1 override / 0.2 and `pkg-beta`'s `C1` `no_blind_labels` with n=0 — reviews of one package do not count for another sharing only the criterion name | Exact | P0 |

### 5.4 M-PKG

| ID | Req | Preconditions / input | Rung | Expected | Oracle | P |
|---|---|---|---|---|---|---|
| TC-PKG-33 | FR-PKG-23 | A Package tier at 12, migrated to 13. `record_noninferiority(v, …, verdict=x)` for x in `'true'`, `'false'`, `'insufficient_data'`, `'maybe'`, `None` | 2 | The three domain values round-trip through `validation_for`. `'maybe'` raises `sqlite3.IntegrityError` (CHECK) and leaves the row unchanged. An unwritten row reads `None`, distinct from `'insufficient_data'`. The Package pin is 13. The CLAUDE.md migration paragraph names `pkg_decision_engine_noninferior` (artifact check) | Exact | P1 |

### 5.5 M-INGEST

| ID | Req | Preconditions / input | Rung | Expected | Oracle | P |
|---|---|---|---|---|---|---|
| TC-INGEST-54 | FR-INGEST-38 | Package declaring questions {q1, q2, q3}. Stores holding: (a) one head {q1, q2, q3}; (b) heads {q1, q2, q3} and {q4, q5}; (c) two heads both {q1, q2, q3}; (d) heads {q4} and {q5} | 2 | (a) Unchanged from today. (b) The semantic signal is computed against the {q1, q2, q3} head (not `absent`). (c) `absent`, reason naming 2 qualifying heads. (d) `absent`, reason naming 0 | Exact | P2 |
| TC-INGEST-55 | FR-INGEST-26 (amended) | A mismatching submission with inventory {q7, q8}. (a) No stored head matches {q7, q8}. (b) Two matching heads with equal lexical affinity 0.5, ids `doc-b` and `doc-a` | 2 | (a) The proposal is written with `candidates == []`. (b) The order is `doc-a`, `doc-b` (ties by id ascending). Every candidate has a numeric `semantic`. A non-matching head is never listed | Exact | P2 |

### 5.6 M-STORE

| ID | Req | Preconditions / input | Rung | Expected | Oracle | P |
|---|---|---|---|---|---|---|
| TC-STORE-28 | FR-STORE-16 | (a) In a subprocess, import all 20 `aeh` modules in alphabetical order, then again in reverse. (b) Register `select_run` with different SQL into `aeh.store.STATEMENTS`. (c) Re-register an existing name with byte-identical SQL | 1 (subprocess) | (a) Every statement name maps to the same SQL text in both orders, and no name has two texts across any loaded dictionary: the scan from design §3.2 returns 0. (b) `StatementConflictError` naming both modules, with the registry unchanged. (c) No error | Exact + scan | P0 |

### 5.7 M-ORCH

| ID | Req | Preconditions / input | Rung | Expected | Oracle | P |
|---|---|---|---|---|---|---|
| TC-ORCH-54 | FR-ORCH-41 | A `cloud-hosted` run with an engine. LLM figure 0.002 per unit; decision per-seat figure `1500 × 0.042e-6 = 0.000063`. Ceiling `0.0100`. Claims of decision-seat score units. The engine-off twin run has the same ceiling | 2 | After 4 seat claims, `cost_spend == 4 × 0.002063 = 0.008252`. The 5th claim would reach 0.010315 > 0.0100, so it is **refused** and the run pauses naming spend 0.008252 and the remaining count. The engine-off twin admits the 5th claim (spend reaches exactly 0.0100, strict `>`) and then pauses at the ceiling. The engine-off `cost_spend` equals the pre-change figure byte for byte | Exact (Decimal) | P0 |
| TC-ORCH-55 | FR-ORCH-42 | A run over a package with C1 open and C2 MCQ. Submissions S1 (both criteria) and S2 (a package variant with only C2). A second run R2 in the same cohort | 2 | `submissions(R1) == ('S1', 'S2')` in enumeration order. R2's submissions are excluded. The call writes nothing (row counts unchanged) | Exact | P1 |
| TC-ORCH-56 | FR-ORCH-43 | A widened five-arm cell with one arm quarantined (4 terminal verdicts). (a) Budget available. (b) Escalation budget exhausted. (c) The cell already carries `escalation-arm-5` | 2 | (a) One `escalation-arm-6` unit is inserted; the report says `inserted`. (b) Nothing is inserted; the report says `refused` with the budget reason. (c) Never re-adds an arm the cell carries. Called twice for the same quarantine → a single insert | Exact | P0 |
| TC-ORCH-57 | FR-ORCH-44 | `Orchestrator(store, wall_clock=fake)`. The run starts at 09:00, pauses 10:00–10:30, and completes at 12:00 | 2 | `run_metrics.run_wall_clock_ms == 9_000_000` (3 h minus 30 min). The same run with `wall_clock` defaulted produces the same row set (values aside) | Exact | P1 |
| TC-ORCH-58 | FR-ORCH-28 (amended) | `mark_cell_phase(..., phase='bogus')` and `units_consumed=-1` | 1 | Raises `WorkLedgerError`, which `isinstance(e, ValueError)` also accepts. No `cell_phase` row is written | Type + state | P1 |

### 5.8 M-PIPE

| ID | Req | Preconditions / input | Rung | Expected | Oracle | P |
|---|---|---|---|---|---|---|
| TC-PIPE-20 | FR-PIPE-15 | F-DEV-PIPE. (a) The package version is promoted with a baseline `mean=2.0, sd=0.5` for C1 under the run's key. (b) No baseline. (c) A lineage with 6 blind labels on C1, 4 of them overrides. (d) A baseline promoted **mid-run** | 3 | (a) A C1 cell at ordinal 5 escalates with the reason "distributional anomaly". (b) Not for that reason, and `should_escalate` received a `NoValidationData` (spy), never `None`. (c) The escalation reason includes override history. (d) The mid-run promotion is not seen until the next run (Q-45). `aeh/pipeline.py` still executes no SQL (CT-PIPE-05 artifact check) | Exact + spy | P0 |
| TC-PIPE-21 | FR-PIPE-16 | F-DEV-PIPE run to `complete`, then `submission_grade` rows deleted (the killed-after-completion state). (b) A `complete` run with no criterion scores | 2 | `recover` → every submission has a current grade. A second `recover` writes no new revision. (b) Is not graded | Exact | P0 |
| TC-PIPE-22 | FR-PIPE-17 | A package whose only criteria are MCQ-deterministic, 2 submissions | 3 | M-SYNTH is offered both submissions exactly once each (spy), and each gets a narrative row | Exact | P1 |
| TC-PIPE-23 | FR-PIPE-18 | F-DEV-PIPE with a widened panel and one arm programmed to quarantine. (a) Budget available. (b) Budget exhausted. (c) An even panel produced any other way (a double returning 2 verdicts with no quarantine) | 3 | (a) A replacement arm runs and the cell aggregates over 5 verdicts. (b) The cell is `ungradeable_by_panel` with reason `even_panel_after_quarantine` and routed to review; **run status `complete`**; every other cell is final. (c) The run pauses as before | Exact | P0 |
| RES-25 | FR-PIPE-16, NFR-PIPE-01 | Kill the process (subprocess, `SIGKILL`/`TerminateProcess`) between `complete` and grading, then run `python -m aeh recover --data-dir D` | 3 | Exit 0, and every submission graded | Exact | P1 |

### 5.8.1 M-CONSOLE

| ID | Req | Preconditions / input | Rung | Expected | Oracle | P |
|---|---|---|---|---|---|---|
| TC-CONSOLE-50 | FR-CONSOLE-40 | Store with run A (`edge-local`, package v1, engine off) and run B (`cloud-hosted`, package v2, `openrouter-jev` build `typesafe/jev-1.13@2026-09-17`). Render S9, S12, S13 and S14 for a grade of each | 2 | A's pages show v1, its rubric version and `edge-local`, with no engine line. B's show v2 and `cloud-hosted`, plus `decision engine openrouter-jev typesafe/jev-1.13@2026-09-17`. No page shows `edge-local-q4` for B. No Jev confidence figure appears beside any criterion. The storeless double still renders `GRADE_PROVENANCE` | Exact | P0 |

### 5.9 Design §5.1 defect rows: acceptance cases that already exist

`/plan-to-issues` creates one story per row group (design §7.4). No new case is written. The story closes when its listed cases pass at the integration tier.

| Row | Existing acceptance case(s) | Tier |
|---|---|---|
| R1 | TC-REQ-13 | contract/requires |
| R2 | TC-REQ-82 (+ TC-CONSOLE-50 here) | contract/requires |
| R3 | TC-REQ-86 | contract/requires |
| R4 | TC-REQ-21 | contract/requires |
| R5 | TC-REQ-61, TC-REQ-83 (+ TC-STATS-C26) | contract/requires |
| R6 | TC-REQ-09 | contract/requires |
| R7 | TC-REQ-67 | contract/requires |
| R8 | TC-REQ-53 | contract/requires |
| R9 | TC-REQ-59 | contract/requires |
| R10 | TC-REQ-88 | contract/requires |
| R11 | TC-REQ-57 (+ TC-REVIEW-32) | contract/requires |
| R12 | TC-REQ-41 | contract/requires |
| R13 | TC-REQ-73 (after TC-REVIEW-34) | contract/requires |
| R14 | TC-REQ-79 | contract/requires |
| R15 | TC-CONSOLE-21, TC-CONSOLE-22, TC-CONSOLE-39, TC-CONSOLE-02 | integration/console (#398, #385) |
| R16 | TC-CONSOLE-23 | integration/console |
| R17 | TC-CONSOLE-24 | integration/console |
| R18 | TC-CONSOLE-11, TC-CONSOLE-12 | integration/console |
| R19 | TC-CONSOLE-29 | integration/console |
| R20 | TC-CONSOLE-27 | integration/console |

---

## 6. Cross-cutting suites (delta)

### 6.3 User acceptance
No new UAT. UAT-09…12 are the teacher try-out on #157. Their precondition is that R15–R20, FR-CONSOLE-40 and RISK-93 are closed: a try-out over an empty queue signs off nothing.

### 6.5 Security

| ID | Req | Probe | Expected |
|---|---|---|---|
| SEC-24 | CT-CONSOLE-29 | Render every grade view for a `cloud-hosted` Jev run with `OPENROUTER_API_KEY=sk-or-SENTINEL` in the environment and a non-default `HARNESS_JEV_OPENROUTER_URL` | Neither the sentinel, `sk-or-`, nor the URL appears in any page byte. The provenance line contains the engine and build only |

### 6.9 Regression

| ID | Req | Case | Expected |
|---|---|---|---|
| TC-REG-10 | T1 (test-support hygiene; guards CT-PIPE-05/seam 3 tests from cross-talk) | (a) Build each `tests/support` world (`SynthWorld`, `replay_world`, `jev_replay_world`) **without** `monkeypatch` inside a test, then assert that `os.environ` after the test equals `os.environ` before it for every `HARNESS_*` key. (b) An autouse session guard compares `HARNESS_*` before and after every test and fails the leaking test by name | (a) No key changed. (b) The guard is green over the full non-live tier, and TC-INGEST-02/25/28/39, ADV-07 and TC-ORCH-36 pass in full-suite order. The 3 `test_ct_ingest_v4_halting` cases pass 10 consecutive full gate runs |
| TC-REG-11 | NFR-PROV-08, FR-JUDGE-17 (#593; design 1.9.1 §5.4 R21) | The stored document holds `Weight acts down. Signed, Zelda Quartermaine. Again, Zelda Quartermaine.`; the unit's roster name is `Zelda Quartermaine`, its ref `P-0001`. Cite one span over the whole document through `_refuse_unverified_citations`: (a) the pseudonymized text; (b) the document's own text; (c) two different refs; (d) another byte changed; (e) text shorter than the offsets hold; (f) the name `Zelda` only; (g) no name known. Plus: `ScoringWorker.assemble` remembers the unit's name by `work_id` | (a) and (b) verify. (c)–(g) raise `MalformedResponseError`. The worker returns the name for its own `work_id` and None for another |
| TC-REG-12 | CT-PIPE-06, ADR-14, FR-ORCH-15, CT-ORCH-20 (#596; design 1.9.1 §5.4 R22) | Composed F-DEV-PIPE run. (a) Sum `tokens_out` over every completion the provider returns, synthesis included. (b) On the completed run, freeze `cost_ceiling = 1.0` with spend 0, then `charge_post_dispatch` 0.6 and 0.4, asking `post_dispatch_ceiling_reached` after each. (c) Make the ceiling read as reached after the first synthesized submission. (d) No stubs: freeze `cost_ceiling = 0.025`, estimate dispatch units at 0, and price each synthesizer completion at 0.01 | (a) `run_metrics.tokens_out` equals the sum. (b) Spend is 1.0; the first ask returns None, the second names the spend and ceiling. (c) Exactly one submission is charged, the synthesize stage says "synthesis stopped before", and the run is `complete` with grades computed. (d) `cost_spend` grows by exactly the priced synthesis calls, reaches the ceiling, synthesis says "synthesis stopped before", and the run is `complete` with grades computed |

### 6.11 Contract suites (delta)

| Case | Clause | Kind | Assertion (breaks if…) | Rung | P |
|---|---|---|---|---|---|
| TC-STATS-C25 | CT-STATS-25 | surface/behaviour | `criterion_disagreement_rate` and `stored_disagreement_rates` exist with the stated signatures. 4 labels → `below_min_n`. **Breaks if** the minimum moves into `aeh.review` or a 4-label rate is returned | 0 | P0 |
| TC-STATS-C26 | CT-STATS-26 | data | `aeh.stats.NoValidationData is aeh.pkg.NoValidationData`. Every absence value from `baseline_for`, `validation_for`, `criterion_override_history`, `criterion_disagreement_rate` and `agreement` is an instance with `reason` and `n`. **Breaks if** either module redefines the class | 0 | P0 |
| TC-STATS-C09 (amended) | CT-STATS-09 (amended) | surface | Both figures return no-data, not `0.0`, for n = 0 and n = 4 | 0 | P0 |
| TC-REVIEW-C24 | CT-REVIEW-24 | behaviour/state | As TC-REVIEW-35, plus: a data dir holding only `durable.sqlite` still holds only that after `open_review` on an unknown run | 2 | P0 |
| TC-REVIEW-C25 | CT-REVIEW-25 | data | Every label written by `record_label` and `act` carries the run's backend. **Breaks if** a write path omits it (both paths exercised) | 2 | P0 |
| TC-PKG-C20 | CT-PKG-20 | data/state | Domain as TC-PKG-33. A static scan: the only `UPDATE`/`INSERT` touching `decision_engine_noninferior` is `record_noninferiority`'s statement | 1 | P1 |
| TC-INGEST-C22 | CT-INGEST-22 | data | `candidates` is a JSON array sorted by (`-semantic`, `assessment_document_id`) with numeric `semantic` on every element. Asserted over three generated stores (property: 50 random affinity sets, seeded) | 2 | P2 |
| TC-STORE-C19 | CT-STORE-19 | behaviour/error | Import-order independence (both orders) and conflict refusal with the registry unchanged, as TC-STORE-28 (a)–(b), run as the provider's clause suite | 1 | P0 |
| TC-ORCH-C31 | CT-ORCH-31 | behaviour | Engine-on `cost_spend` equals Σ(LLM + seat figure). The engine-off `cost_spend` for the same claims equals the pre-change value. **Breaks if** the seat figure is charged to a non-seat unit (arm 2 claims a non-seat unit and asserts no decision part) | 2 | P0 |
| TC-ORCH-C32 | CT-ORCH-32 | surface/behaviour | `submissions` includes a deterministic-only submission and excludes another run's | 2 | P1 |
| TC-ORCH-C33 | CT-ORCH-33 | behaviour | At most one replacement per cell per quarantine; a new arm identity; the budget counter increments by 1 | 2 | P0 |
| TC-ORCH-C34 | CT-ORCH-34 | config | Defaulted `wall_clock` gives the same outcomes as today's run (row set equality). An injected clock gives the exact figure | 2 | P1 |
| TC-PIPE-C10 | CT-PIPE-10 | behaviour | The escalation inputs are never `None` (spy over a full F-DEV-PIPE run). The anomaly limb is evaluated iff a baseline is stored | 3 | P0 |
| TC-PIPE-C11 | CT-PIPE-11 | behaviour | After `recover`, no `complete` run holds scores without grades, and a double recover writes one revision | 2 | P0 |
| TC-PIPE-C12 | CT-PIPE-12 | behaviour | One quarantined arm never pauses the run (both budget states) | 3 | P0 |
| TC-PIPE-C13 | CT-PIPE-13 | behaviour | Each enumerated submission is offered to synthesis exactly once (a counter spy over a mixed package) | 3 | P1 |
| TC-CONSOLE-C29 | CT-CONSOLE-29 | data/security | Two runs with different profiles, one with Jev, render two different provenance lines, each equal to its run's. The Jev line names provider and build. There is no credential, key or URL (SEC-24's sentinel sweep). There is no confidence figure beside a criterion | 2 | P0 |

### 6.12 Blast-radius rows (delta)

| Change to | Re-run |
|---|---|
| `M-STATS` | TC-STATS-C09, C25, C26, TC-REQ-41, TC-REQ-57, TC-REQ-73, TC-REQ-79, TC-REQ-120, TC-REQ-121, TC-REQ-123 |
| `M-REVIEW` | TC-REVIEW-C24, C25, TC-REQ-53, TC-REQ-59, TC-REQ-86, TC-REQ-124, TC-REQ-125 |
| `M-PKG` | TC-PKG-C20, TC-REQ-119, TC-REQ-126 |
| `M-ORCH` | TC-ORCH-C31…C34, TC-REQ-122 |
| `M-PIPE` | TC-PIPE-C10…C13 |
| `M-STORE` | TC-STORE-C19, TC-REQ-127, SEC-15 census |
| `M-CONSOLE` | TC-CONSOLE-C29, SEC-24, TC-REQ-82, TC-REQ-88 |
| `M-INGEST` | TC-INGEST-C22 |

### 6.13 `Requires` pairwise cases (design §4, one per row)

| Case | Consumer → provider | Clause | Rung | Assertion |
|---|---|---|---|---|
| TC-REQ-119 | M-PIPE → M-PKG | CT-PKG-07, `baseline_for` | 2 | M-PIPE's escalation receives exactly the baseline stored under the run's six-part key. A baseline stored under a different `backend_profile` is **not** used |
| TC-REQ-120 | M-PIPE → M-STATS | CT-STATS-09 (amended), CT-STATS-26 | 2 | A lineage with 3 labels hands M-AGG a `NoValidationData`. M-AGG applies the no-data weight, not the zero path |
| TC-REQ-121 | M-REVIEW → M-STATS | CT-STATS-25 | 2 | The review row's eighth input equals `stored_disagreement_rates` for the same version, for every criterion |
| TC-REQ-122 | M-PIPE → M-ORCH | CT-ORCH-32, CT-ORCH-33 | 3 | Synthesis is offered exactly `submissions(run_id)`. A replacement arm's budget use shows in the orchestrator's budget report |
| TC-REQ-123 | M-STATS → M-REVIEW | CT-REVIEW-25 | 2 | Agreement over labels written by M-REVIEW from two backends yields two figures of n = 8 each, never one of 16 |
| TC-REQ-124 | M-REVIEW → M-ORCH | run registry (`run_handle`) | 2 | `open_review` resolves the cohort through `run_handle`. An orchestrator reporting run R in cohort C2 routes the service to C2 |
| TC-REQ-125 | M-CONSOLE → M-CONF | FR-CONF-26 | 2 | The console's engine line equals `ProfileSummary`'s engine. For an engine-off run there is no engine line |
| TC-REQ-126 | M-STATS → M-PKG | CT-PKG-20 | 2 | `promote`'s verdict is readable back through `validation_for` under the same key |
| TC-REQ-127 | every declaring module → M-STORE | CT-STORE-19 | 1 | For each module owning statements, its reads resolve to its own SQL under both import orders (a subprocess per order) |

---

## 7. Traceability and residual risk

### 7.1 Requirements traceability (delta)

| Requirement | Cases |
|---|---|
| FR-PROV-15 | TC-PROV-55 |
| FR-PROV-12 | TC-PROV-56 |
| FR-STATS-24 | TC-STATS-36, TC-STATS-31 |
| FR-STATS-28 | TC-STATS-37, TC-STATS-C25 |
| FR-STATS-29 | TC-STATS-38, TC-REQ-126 |
| FR-REVIEW-18 | TC-REVIEW-32, TC-REQ-57, TC-REQ-121 |
| FR-REVIEW-21 | TC-REVIEW-28 (absence arm, unchanged) |
| FR-REVIEW-22 | TC-REVIEW-33, TC-REVIEW-29 |
| FR-REVIEW-23 | TC-REVIEW-34, TC-REVIEW-C25 |
| FR-REVIEW-24 | TC-REVIEW-35, TC-REVIEW-C24, TC-REQ-124 |
| FR-REVIEW-09 (regression) | TC-REVIEW-36 |
| FR-PKG-23 | TC-PKG-33, TC-PKG-C20 |
| FR-INGEST-26 | TC-INGEST-52, TC-INGEST-55, TC-INGEST-C22 |
| FR-INGEST-38 | TC-INGEST-54, TC-INGEST-39 |
| FR-STORE-16 | TC-STORE-28, TC-STORE-C19, TC-REQ-127 |
| FR-ORCH-28 | TC-ORCH-58 |
| FR-ORCH-32 | TC-ORCH-45 |
| FR-ORCH-34 | TC-ORCH-47 |
| FR-ORCH-41 | TC-ORCH-54, TC-ORCH-C31 |
| FR-ORCH-42 | TC-ORCH-55, TC-ORCH-C32 |
| FR-ORCH-43 | TC-ORCH-56, TC-ORCH-C33 |
| FR-ORCH-44 | TC-ORCH-57, TC-ORCH-C34 |
| FR-PIPE-15 | TC-PIPE-20, TC-PIPE-C10, TC-REQ-119, TC-REQ-120 |
| FR-PIPE-16 | TC-PIPE-21, RES-25, TC-PIPE-C11 |
| FR-PIPE-17 | TC-PIPE-22, TC-PIPE-C13, TC-REQ-122 |
| FR-PIPE-18 | TC-PIPE-23, TC-PIPE-C12 |
| FR-CONSOLE-40 | TC-CONSOLE-50, TC-CONSOLE-C29, SEC-24, TC-REQ-82, TC-REQ-125 |

### 7.2 Contract traceability (delta)

| Clause | Cases | Consumers |
|---|---|---|
| CT-STATS-09 | TC-STATS-C09, TC-STATS-36, TC-REQ-120 | M-AGG, M-REVIEW |
| CT-STATS-25 | TC-STATS-C25, TC-REQ-121 | M-REVIEW |
| CT-STATS-26 | TC-STATS-C26, TC-REQ-61, TC-REQ-83, TC-REQ-120 | M-PKG, M-AGG, M-REVIEW, M-CONSOLE, M-PIPE |
| CT-REVIEW-24 | TC-REVIEW-C24, TC-REVIEW-35, TC-REQ-124 | M-CONSOLE |
| CT-REVIEW-25 | TC-REVIEW-C25, TC-REQ-123 | M-STATS |
| CT-PKG-20 | TC-PKG-C20, TC-REQ-126 | M-STATS, M-CONSOLE |
| CT-INGEST-22 | TC-INGEST-C22 | M-CONSOLE, M-SETUP |
| CT-STORE-19 | TC-STORE-C19, TC-REQ-127 | all declaring modules |
| CT-ORCH-31 | TC-ORCH-C31 | M-PIPE, M-CONSOLE |
| CT-ORCH-32 | TC-ORCH-C32, TC-REQ-122 | M-PIPE |
| CT-ORCH-33 | TC-ORCH-C33, TC-REQ-122 | M-PIPE |
| CT-ORCH-34 | TC-ORCH-C34 | M-PIPE, M-CONSOLE |
| CT-PIPE-10 | TC-PIPE-C10 | M-AGG |
| CT-PIPE-11 | TC-PIPE-C11 | M-GRADE, M-CONSOLE |
| CT-PIPE-12 | TC-PIPE-C12 | M-AGG, M-REVIEW |
| CT-PIPE-13 | TC-PIPE-C13 | M-SYNTH |
| CT-CONSOLE-29 | TC-CONSOLE-C29, SEC-24 | M-CONF, M-GRADE |

### 7.3 What passing proves
- **Built right:** every design 1.9 requirement has a rung-2 or rung-3 case with an exact oracle (§7.1, 26 of 26).
- **Safe to change:** every new clause has a case that goes red on the named plausible regression (17 of 17), and every new `Requires` row has a pairwise case (9 of 9).
- **Defects closed:** the twenty design §5.1 rows are closed when their existing cases are green.
- **Honest signal:** the suite's results no longer depend on test order (TC-REG-10).

### 7.4 What it does not prove
- The design §5.3 triage items (TC-REQ-29, TC-STORE-04) until TS-128 resolves them. Until then, a green TC-REQ-29 proves nothing.
- That the operational disagreement figure is a *good* ranking signal. It proves only that the figure is the one the design names and that it moves the rank (Q-C1).
- Anything on #157: hardware, live local engines, the container deployment and the teacher try-out.
- FR-INGEST-26's per-candidate "structural match" is inventory **equality** (an `Assumption:` in the design). Near-matching papers are never proposed, and nothing here measures whether that is too strict.

### 7.5 Residual risk and compensation
The strongest remaining risk is **RISK-91** (extraction without the criterion text): it silently lowers the quality of every judged score produced so far. Compensation: after the R4 story lands, re-capture F-DEV-PIPE and F-JEV-DECISIONS through the fixed extractor and compare their bands. A band shift is expected, and is itself evidence of the defect's reach.

---

## 8. Execution plan and backlog handoff

### 8.1 Sequencing
Follow design §7.4. **TS-126 first**: until the environment leak is gone, a red integration case cannot be trusted either way.

### 8.2 Test stories

"Written ahead" follows the code: cases against design 1.9's new requirements are `yes` (no dependency, `writtenahead` plus a `WRITTEN_AHEAD_BLOCKERS` entry keyed to the implementing story). Cases against shipped behaviour are `no`. The §5.9 defect rows get **no** test story.

| Story | Covers | Depends on | Written ahead of implementation? | Phase |
|---|---|---|---|---|
| TS-126 Test-support environment isolation and the gate's timing flakes | TC-REG-10, TC-INTEG-11, TC-INTEG-C12 | — | no | 1 |
| TS-127 M-PROV shipped seams, counters and the #507 regression cases | TC-PROV-55, TC-PROV-56, TC-PROV-57, TC-PROV-58, TC-PROV-59 | — | no | 1 |
| TS-128 Triage and re-specification of stale, vacuous and nondeterministic cases | TC-REQ-14, TC-REQ-29, TC-STORE-04, ADV-10, TC-PIPE-05, TC-INTEG-17 | — | no | 1 |
| TS-129 Jev journey arms left open by TS-117 | SEC-19, ADV-15, TC-E2E-05 | — | no | 1 |
| TS-130 M-STATS and M-REVIEW: override and disagreement figures, the backend column, run-scoped review, the purge rule | TC-STATS-36, TC-STATS-37, TC-STATS-31, TC-REVIEW-25, TC-REVIEW-32, TC-REVIEW-33, TC-REVIEW-34, TC-REVIEW-35, TC-REVIEW-37 | — | yes | 1 |
| TS-131 M-PKG non-inferiority column and M-STATS persistence | TC-PKG-33, TC-STATS-38 | — | yes | 2 |
| TS-132 M-STORE: one SQL text per statement name | TC-STORE-28 | — | yes | 1 |
| TS-133 M-ORCH: decision spend, submissions, replacement arm, wall clock, error type, alert floor, deprecation | TC-ORCH-54, TC-ORCH-55, TC-ORCH-56, TC-ORCH-57, TC-ORCH-58, TC-ORCH-45, TC-ORCH-47 | — | yes | 1 |
| TS-134 M-PIPE: escalation inputs, recovery grading, synthesis coverage, even panel | TC-PIPE-20, TC-PIPE-21, TC-PIPE-22, TC-PIPE-23, RES-25 | — | yes | 1 |
| TS-135 M-CONSOLE grade provenance from the run | TC-CONSOLE-50, SEC-24 | — | yes | 1 |
| TS-136 M-INGEST multi-lineage semantic reference and candidates | TC-INGEST-39, TC-INGEST-54, TC-INGEST-55 | — | yes | 2 |
| TS-137 Clause suites (1.9): M-STATS, M-REVIEW, M-PKG, M-INGEST, M-STORE | TC-STATS-C09, TC-STATS-C25, TC-STATS-C26, TC-REVIEW-C24, TC-REVIEW-C25, TC-PKG-C20, TC-INGEST-C22, TC-STORE-C19 | — | yes | 1 |
| TS-138 Clause suites (1.9): M-ORCH, M-PIPE, M-CONSOLE | TC-ORCH-C31, TC-ORCH-C32, TC-ORCH-C33, TC-ORCH-C34, TC-PIPE-C10, TC-PIPE-C11, TC-PIPE-C12, TC-PIPE-C13, TC-CONSOLE-C29 | — | yes | 1 |
| TS-139 `Requires` pairwise (1.9) | TC-REQ-119, TC-REQ-120, TC-REQ-121, TC-REQ-122, TC-REQ-123, TC-REQ-124, TC-REQ-125, TC-REQ-126, TC-REQ-127 | — | yes | 1 |

**Notes for `/plan-to-issues`:**
- TC-INGEST-52 stays with TS-102 (#396), re-specified here (§5.0). Don't duplicate it into TS-136.
- The open test issues #377, #378, #385, #387, #390, #391, #392 and #393 keep their scope. This plan adds none of their cases.
- Each §5.9 row group becomes a **code** story whose acceptance cases are the listed existing cases. Those stories trace to the design's R-rows and to the existing TC IDs.

---

## 9. Revision history

| Version | Date | Change |
|---|---|---|
| 1.7-delta | 2026-09-27 | Test plan for design 1.9 (backlog close-out). 26 requirements and 17 clauses covered. 9 pairwise cases, 17 reconciliation entries, 20 defect rows mapped to existing cases, and 14 test stories (TS-126…TS-139). |
