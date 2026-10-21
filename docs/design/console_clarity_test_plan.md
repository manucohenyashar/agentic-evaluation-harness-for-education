# Test Plan: Console Clarity — a test day the teacher can read

**Design input:** `docs/design/console_clarity_design_delta.md` v1.15-delta (r3). It applies on
top of `detailed-design.md` v1.4 and the gap, Jev, close-out, operator, authoring, redesign and
teacher-corrections deltas. Code baseline: `main` @ `813a009`. **Status:** Draft, for review
before `/plan-to-issues`.
**Version:** 1.15-plan-delta  **Date:** 2026-10-20  **Author:** `/create-test-plan`.

This plan claims: **if every test in here passes, then the following hold.**

- A teacher can author, approve, load, grade, read and approve the English test ENG7-READ-01
  in the console against **real OpenRouter**, with no environment variables set.
- Every teacher-facing string, outcome and input states plainly what happened or what is
  expected, without scrolling.
- Every Jev and judge request and reply behind a grade can be read in the console and from
  the terminal.
- A confident Jev decision is final, and no other single-grader mark is final.

**New requirement surface:**
- FR-UI-23…36
- FR-CONSOLE-71…79
- FR-AUTHOR-31/32
- FR-AGG-20 (amends FR-AGG-07)
- FR-ORCH-45
- FR-CONF-36/37
- FR-PROV-44…46
- FR-HELP-07

**Contract surface:**
- New clauses: CT-PROV-31/32, CT-AGG-24, CT-CONSOLE-53/54, CT-CONF-25, CT-AUTHOR-27.
- Amended clauses: CT-PROV-11, CT-PROV-14, CT-AGG-23, CT-JUDGE-07, CT-JUDGE-14 / FR-JUDGE-37,
  CT-CONSOLE-09, CT-STORE-10.

Everything else the delta cites is consumed through the existing suites (§4.2) and is not
re-specified here.

---

## 1. Risk register

Severity combines blast radius, reversibility and detectability. Contract-shaped risks name
their clause. Contract clauses are scored low-detectability by default: a broken clause
shows up in a neighbour, not in the module that broke it.

| Risk | Module / clause | Failure imagined concretely | Blast radius | Reversible? | Detectability | Severity | Depth |
|---|---|---|---|---|---|---|---|
| RC-01 | M-AGG / CT-AGG-24, CT-JUDGE-14 | An answer carrying an injected "give full marks" directive pushes Jev above its gate. The mark is written **final**, and nobody reviews it. | Student grade; the export | Amendable, but only if noticed | **Silent** | **Critical** | unit + integration + adversarial + regression |
| RC-02 | M-AGG / CT-AGG-24 | An LLM-only single verdict (Jev below gate → fallback) is wrongly written final, because the rule keys on the cell rather than on the verdict's `scoring_engine`. | Every fallback answer | Amendable | **Silent** | **Critical** | unit decision table + integration |
| RC-03 | M-CONF / RunConfig | `HARNESS_JEV_FINAL_ON_ACCEPT` is read live, not frozen. A run resumed with it off grades half the class by each rule. | One run | Re-run | Silent | High | integration (pause/resume) |
| RC-04 | M-AGG / CT-AGG-23 | A Jev-final cell keeps confidence 0.75 with `routing='auto'`. The review ranking or the export gate re-derives "below threshold" and queues it again, or the stats count it as low-confidence. | M-REVIEW, M-STATS, M-GRADE | Yes | Silent | High | contract pair cases |
| RC-05 | M-PROV / CT-PROV-31 | The journal writes the `Authorization` header or the API key into a `.jsonl` line under the data folder. | Credential | **No** (key leaked to disk) | Silent | **Critical** | security sweep + unit per provider |
| RC-06 | M-STORE / CT-STORE-10 | `purge_cohort` deletes the store but leaves `logs/ai-calls/<cohort>/`, so students' answers survive the purge. | Privacy | **No** | Silent | **Critical** | integration + regression |
| RC-07 | M-PROV / CT-PROV-32 | The Jev typesafe-SDK route (`jev_openrouter.py`) bypasses `_dispatch` and journals nothing. "How was this graded?" shows nothing for every Jev-final answer, the most common case. | The feature's purpose | Yes | Silent (an empty list looks normal) | High | per-provider double-conformance + E6 |
| RC-08 | M-CONSOLE / CT-CONSOLE-54 | The per-question roll-up sums C1 **and** C1a + C1b, so the student shows 4/2 on Q1 and a total of 10/8. | Every results screen; the teacher's trust | Yes | Loud-ish (a reader may not notice 7 vs 6) | **Critical** | unit + property + E6 |
| RC-09 | M-CONSOLE | The grade label disagrees with the boundary table: 6/8 shows "not yet". | Pass/fail per student | Yes | Silent | High | unit boundaries 5/6/8 |
| RC-10 | M-UI / FR-UI-33 | After **Approve all grades**, the banner says "All grades are final" while question rows still read "Check" (`finalize_batch` settles `submission_grade` only). | Teacher decisions | Yes | Loud only if looked at | High | integration + E6 |
| RC-11 | M-AUTHOR / CT-AUTHOR-27 | The hint says "1 to 8" but the check accepts 0 or 9, or the lowest grade "not yet" is asked with min 1 and cannot be answered. | Published package | **No** (published versions never change) | Silent | **Critical** | boundary matrix, client + server |
| RC-12 | M-CONSOLE / CT-CONSOLE-53 | A new string carries "(FR-PKG-28)" or "@e34abeaceb0a" to the teacher. | Clarity | Yes | Loud | Medium | census (whole matrix) |
| RC-13 | M-UI / FR-UI-24 | An action outcome renders below the fold, so the teacher presses again (the original T2b). | Duplicate actions | Mostly | Loud to the teacher, silent to tests without a viewport oracle | High | viewport census over every action |
| RC-14 | M-CONF / CT-CONF-25 | The console's start-run ignores the config file's `orch_escalation_budget`, and a 4-student run stops with "no progress" (the original T0a). | Every console run | Yes | Loud | High | pair case CLI vs console |
| RC-15 | M-CONSOLE / FR-CONSOLE-71 | `teacher_text()` strips a meaningful parenthetical such as "(Q2)" or "(2 of 3)". | Clarity | Yes | Silent | Medium | unit table |
| RC-16 | M-PIPE / FR-CONSOLE-75 | A resumed run shows only its last pass's seconds, or a skipped stage shows "0 s". | Clarity | Yes | Silent | Medium | integration |
| RC-17 | M-UI / FR-UI-28 | The switcher still reads "Test package" for ENG7-READ-01. | Clarity | Yes | Loud | Low | single E6 case |
| RC-18 | M-CONSOLE / FR-UI-35 | The AI-calls read filters out `real` classes. The teacher of a real class cannot see how a mark was decided (§9 Q4). | Real deployments | Yes | Silent | High | integration with a `real` cohort |
| RC-19 | System | The live ENG7 walk fails against real OpenRouter (model reply shape, Jev build, cost ceiling), and the "clear run that just works" does not. | The release | Yes | Loud | **Critical** | live E2E + recorded twin |
| RC-20 | M-UI / FR-UI-36 | An input with no format line, or whose line disagrees with its validation, e.g. the cost limit accepts "abc". | Clarity, bad data | Yes | Silent | High | census over every input |

Depth rule: **Critical/High** risks get cases at two or more rungs and a regression entry
(§3.12). **Medium** risks get a unit case plus one integration path. **Low** (RC-17) gets one
E6 case, deliberately.

## 2. Test strategy

### 2.1 Levels and shape

This delta is mostly **presentation over existing data**, plus two behaviour changes: the
Jev-final rule and the call journal. The shape follows from that:

- **E1 unit (rung 0–1)** — `teacher_text()`, gap-question construction, the range and order
  checks, per-question roll-up, grade lookup, duration formatting, knob precedence,
  `CallRecord` construction and redaction, and the FR-AGG-20 decision table. Many small cases.
- **E1 integration (rung 3)** — console reads and actions against a real seeded store through
  `serve_console()`, plus the fixture pipeline with a journal sink installed. This is the
  existing console-suite harness.
- **E6 browser (rung 4)** — every FR-UI case, the viewport and input censuses, and the recorded
  ENG7 walk. Playwright per `tests/support/spa.py`, replaying `RecordedFixtureProvider`, with
  zero egress.
- **Live (marker `live`)** — the ENG7 walk (TC-E2E-14) against real OpenRouter. The key comes
  from `OPENROUTER_API_KEY`, which the operator loads from `.env-dev`. Without the key the case
  skips in milliseconds (`console_journeys.LIVE_KEY_ENV`).

### 2.2 Mock-vs-real policy

- **Provider:** `RecordedFixtureProvider` in E1/E6, and real OpenRouter in TC-E2E-14 only.
  Every journal clause runs against **all five** implementations (CT-PROV-32). The fixture
  provider is held to the same `CallRecord` shape as the live ones, so a journal test on the
  fast tier is not testing a fiction. Live providers are driven at rung 1 through their
  `Transport` seam with canned HTTP replies (the existing `tests/unit/prov` pattern). The Jev
  SDK route is driven through its `_sdk_response` seam.
- **Store:** always real (rung 3 minimum).
- **Browser:** always real for TC-UI/TC-E2E.
- **Journal sink:** real file sink in integration and E6. An in-memory list sink is allowed
  only in M-PROV unit cases, and it is the *test's* instrument (TC-PROV-65 asserts the file
  sink and the list sink receive identical records).

### 2.3 Oracles

| Oracle | Used by |
|---|---|
| Exact teacher sentence (string equality on the delta's quoted text) | gaps, approve outcomes, not-final reasons, banners, format lines |
| Regex census (FR-UI-23 patterns) over every API response and every SPA screen | TC-CONSOLE-87, TC-UI-24 |
| Element bounding box inside the 1280×720 viewport | TC-UI-25 (FR-UI-24) |
| Store row inspection (`criterion_score.state`, `routing`, `confidence`; `run_metrics`) | Jev-final, timings |
| Journal file content (parsed `.jsonl`), plus a byte scan for the key | journal cases |
| Arithmetic invariant: Σ question points = total; C1 = C1a + C1b, counted once | roll-up property |
| Filesystem existence after purge | TC-STORE-30 |
| Browser network log (no egress) | every E6 case |

Screenshots are never oracles (standing convention). The live walk's screenshots feed the
tutorial (FR-HELP-07), not an assertion.

### 2.4 Test data

- **ENG7 world:** the shipped `eng7-read-01.package.toml` (Q1 2, Q2 3, Q3 3; C1 = C1a + C1b;
  grades pass = 6, not yet = 0), the 4 sample answer sheets, and `eng7-roster.txt`.
- **ENG7 authoring documents:** the four ENG7 PDFs, plus a variant **AF-22** whose rubric
  omits the grade table (it drives the "What is the passing score?" path) and **AF-23**, whose
  rubric names *pass* without a boundary. They are generated in-tree by extending
  `build_sample_materials.py`, and are byte-reproducible and census-pinned (the authoring-corpus census
  mechanism).
- **Jev-final seed:** a cohort store with four cells per student:
  1. an accepted decision verdict (gate 0.91);
  2. an LLM-only single verdict;
  3. a three-judge agreeing panel;
  4. a breaker-tripped criterion.

  One cohort is seeded `synthetic` and one `real` (RC-18).
- **Adversarial:** the existing CT-JUDGE-14 injection set, with recorded `decide` answers.
- **Recordings:** the ENG7 walk's provider calls are **captured from the live run**
  (TC-E2E-14 with `record=True`) under `fixtures/F-CLARITY/recordings/`, never fabricated
  (the recording-honesty rule). TC-E2E-15 replays them.
- No real student data anywhere. Student names are the sample-materials names.

### 2.5 Environments

- **E1 and E6** run on the developer box.
- **Live** needs `OPENROUTER_API_KEY` exported from `.env-dev`, never echoed or committed, and
  a fresh data folder per run.
- The ceiling is the shipped config's **5 USD**. The live case asserts the run's cost stays
  under it and records the figure.
- **E5** (air-gapped) inherits the E1/E6 cases, because replay needs no network.

### 2.6 Determinism and flake policy

- **Clock:** duration logic is unit-tested with an injected clock (the run's clock seam). E6
  asserts the **format** of "Working — N s" and that N grows between two reads, never a
  wall-clock value.
- **Live variance:** TC-E2E-14 asserts *structure* — each step's sentence pattern, Σ = total,
  grade consistent with total, a journal record per graded cell. It never asserts a specific
  mark: model output is not reproducible (the base M-PROV non-promise on reproducibility).
- **Jev decisions** replay byte-identically from recordings in E1/E6.
- No new randomness. `orch_random_arm_rate = 0` in the shipped config removes the arm from
  the walk.

### 2.7 Tooling

- Pytest with the repo's markers (`browser`, `integration`, `live`, `writtenahead`), the
  `scripts/test.sh` fast tier, and the Playwright sync API.
- File naming `test_tc_<area>_<nn>_<slug>.py`. Docstrings carry the TC/FR traces and a
  "Markers." paragraph.
- No new framework.

### 2.8 Contract-verification policy

- **The provider side owns each clause suite**, and it runs on every change to the module:
  - `CT-PROV-11/14/31/32` → `tests/contract/prov/`
  - `CT-AGG-23/24` → `tests/contract/agg/`
  - `CT-JUDGE-07/14` → `tests/contract/judge/`
  - `CT-CONSOLE-09/53/54` → `tests/contract/console/`
  - `CT-CONF-25` → `tests/contract/conf/`
  - `CT-STORE-10` → `tests/contract/store/`
  - `CT-AUTHOR-27` → `tests/contract/author/`
- **Doubles:** `RecordedFixtureProvider` is the canonical M-PROV double. CT-PROV-31/32 run
  against it **and** against the four live implementations in one parametrized suite, in the
  same story.
- **`Requires` rows → pair cases (rung 2+):**
  - M-CONSOLE → M-PROV journal shape (TC-CONSOLE-95)
  - M-REVIEW / M-STATS / M-GRADE → CT-AGG-24's route and confidence (TC-AGG-29/30)
  - M-ORCH → CT-AGG-24 no-escalation (TC-ORCH-61); below-gate escalation unchanged (TC-ORCH-62)
  - M-CONSOLE → CT-CONF-25 (TC-CONF-41)
  - M-UI → CT-CONSOLE-53/54 (TC-UI-24, TC-UI-31)
- **Blast-radius rule for CI:**

  | Changed module | Re-run |
  |---|---|
  | M-AGG | the agg clause suite, plus `tests/**/review`, `tests/**/stats`, `tests/**/grade`, `tests/**/orch` |
  | M-PROV | the prov clause suite (all five implementations), plus the journal integration cases, plus the egress census |
  | M-CONSOLE | the console clause suite, plus the E6 family |
  | M-CONF | the conf clause suite, plus TC-CONF-41 |

- **Compatibility:** CT-AGG-23/24, CT-JUDGE-07/14 and CT-CONSOLE-09 are **breaking** (§4 of the
  delta). Every consumer named there re-verifies in the same PR as the change. A red clause
  suite is a design conversation, never a test edit.

### 2.9 Entry / exit criteria

**Entry:**
- The design delta has been reviewed.
- AF-22/23 and the Jev-final seed exist (story T1).

**Exit:**
- 100 % of P0 cases are green: RC-01/02/05/06/08/11/19's cases and the censuses.
- No open Critical or High defect.
- Every clause suite is green against every implementation.
- The fast tier is green on top of `main`'s known baseline reds (diffed, never green-blind).
- **TC-E2E-14 passes against real OpenRouter**, and its cost and stage timings are recorded in
  `docs/live-tests/02-live-readiness-and-blockers.md`.

---

## 3. Test cases

The format is: ID (traces) — *title*. Setup / input. **Oracle.** Expected. Level.

### 3.1 Configuration (M-CONF) — E1

- **TC-CONF-40** (FR-CONF-36, CT-CONF-25) — *knob precedence.* A decision table over
  {env set / unset} × {file key set / unset} for each knob:
  - (a) env `0.5`, file `1.0` → 0.5, source "environment";
  - (b) env unset, file `1.0` → 1.0, "config file";
  - (c) both unset → 0.30 / 0.07, "default";
  - (d) file `1.5` → refused naming the key and its range "[0, 1]";
  - (e) file `"abc"` → refused;
  - (f) file `0` for the rate → 0 (a boundary);
  - (g) file `1.0` for the budget → 1.0 (a boundary).

  **Oracle:** exact value and source. Rung 0.
- **TC-CONF-41** (FR-CONF-36, CT-CONF-25; pair M-CONSOLE→M-CONF) — *the same value reaches both
  run paths.* A config file with `orch_escalation_budget = 1.0` and `orch_random_arm_rate = 0`,
  no env. Start a fixture run (a) via `aeh run` and (b) via the console's start-run.
  **Oracle:** the run row and the start-up banner. Expected: both runs record 1.0 / 0, and
  neither pauses with "no progress" on the 4-student ENG7 fixture (RC-14 regression). Rung 3.
- **TC-CONF-42** (FR-CONF-37) — *the shipped files carry the values.* Parse
  `docs/live-tests/config/live-test.dev-ci.toml` and `config/harness.example.toml`'s dev-ci
  section. Expected: `orch_escalation_budget == 1.0` and `orch_random_arm_rate == 0`, each with
  a comment line above it. Also, the deployment and operating tutorials (docs and
  `help_assets/manuals`) contain no `HARNESS_ORCH_ESCALATION_BUDGET` /
  `HARNESS_ORCH_RANDOM_ARM_RATE` `$env:` line. Rung 0.
- **TC-CONF-43** (FR-CONF-36) — *`HARNESS_KEYS` stays six.* Assert `len(HARNESS_KEYS) == 6` and
  that neither new key is in it (guards the base plan's six-key sweep). Rung 0.

### 3.2 Jev-final and not-final reasons (M-AGG, M-ORCH, M-JUDGE) — E1

- **TC-AGG-27** (FR-AGG-20, CT-AGG-24, amends FR-AGG-07) — *the decision table.* Rows:

  | # | Verdicts | `scoring_engine` | Knob | Expected state / routing / reason |
  |---|---|---|---|---|
  | (a) | 1 | `decision` | true | `final` / `auto` |
  | (b) | 1 | `llm` | true | `provisional_unreviewed`, `one_grader_unsure` (RC-02) |
  | (c) | 1 | `decision` | false | `provisional_unreviewed` (FR-AGG-07 restored) |
  | (d) | 3 agreeing | `decision` + 2 `llm` | true | engine-blind result, unchanged |
  | (e) | 2 | both `decision` | — | `PanelCorrelationError` (the Jev delta's two-decision refusal, unchanged) |
  | (f) | breaker tripped | `decision` | true | `ungradeable_by_panel`, `graders_refused` (breaker precedence) |

  **Oracle:** exact fields. Rung 0.
- **TC-AGG-28** (FR-AGG-20, CT-AGG-23) — *confidence matches route.* Row (a) records
  `confidence` equal to the decision's gate value (0.91 in the seed), and that value is above
  `threshold`. Row (b) keeps the single-judge prior, which is at most 0.75. A property case:
  for any accepted decision with gate g in (threshold, 1], the recorded confidence is g.
  Rung 0 + Hypothesis.
- **TC-AGG-29** (CT-AGG-24; pair M-REVIEW→M-AGG) — *review does not requeue a Jev-final cell.*
  Seed row (a) and build the review queue. Expected: the cell is absent from the review items,
  and row (b)'s cell is present with reason `one_grader_unsure`. Rung 3.
- **TC-AGG-30** (CT-AGG-24; pairs M-STATS / M-GRADE→M-AGG) — *stats and the grade read the
  route.* After aggregation of the seed:
  - The grade for a student whose every cell is Jev-final is computed as final, with no
    provisional flag.
  - The low-confidence counts of `M-STATS` exclude Jev-final cells.
  - The export gate (`export_gate_outcome`) does not block on them.

  Rung 3.
- **TC-AGG-31** (FR-AGG-20) — *every not-final reason code is reachable.* Seed one cell per
  code — `one_grader_unsure`, `graders_disagree`, `evidence_not_found`, `quote_not_verified`,
  `more_graders_unavailable`, `graders_refused` — and assert the stored code. Also assert that
  a `final` cell carries no code. Rung 0/3.
- **TC-ORCH-61** (FR-ORCH-45; pair M-ORCH→CT-AGG-24) — *no escalation for a Jev-final cell.*
  With budget 1.0 and two escalation judges configured, run a fixture pass where cell X is
  Jev-final and cell Y is an LLM-only single verdict. Expected:
  - X has no escalation units and consumes no budget.
  - Y is escalated.
  - With `orch_random_arm_rate = 1.0`, X still receives a random-arm unit (CT-ORCH-15
    independence). Once the arm's verdicts land, X is re-aggregated by the ordinary panel
    rule (FR-ORCH-45's widening clause). With three agreeing recorded verdicts it is `final`
    with the panel's confidence, not the gate value. With one disagreeing verdict it is
    `provisional_unreviewed` with `graders_disagree`.

  Rung 3.
- **TC-ORCH-62** (FR-ORCH-45's "every other cell escalates exactly as before"; FR-AGG-08,
  FR-ORCH-10, FR-ORCH-14) — *below-gate cells escalate as they always did.* Setup:
  - a three-model panel from three families, plus two escalation judges, and budget 1.0;
  - recorded fixtures for one atomic and one holistic criterion;
  - the decision engine is configured, but its recorded `decide` answers are below the gate
    for every cell, and one cell's answer passes the gate but fails citation verification.

  The same fixture set is run twice, once with the engine **off**. **Oracle: differential.**
  Per cell, the two runs must match on:
  - the `should_escalate` decision and its reasons;
  - the escalation units enqueued, the judge identities and the order they were added;
  - the panel depth reached;
  - the budget consumed;
  - the final band, points, `state` and `routing`.

  Explicit arms:
  - (a) the atomic cell with a mid-scale band goes 1 → 3 judges, each a distinct model, and is
    scored by the median band;
  - (b) the holistic cell starts at three judges;
  - (c) a three-judge spread that still disagrees widens to five;
  - (d) a single confident LLM verdict at a scale edge, with a citation and no adverse signal,
    is **not** escalated and stays `provisional_unreviewed` / `one_grader_unsure`, exactly as
    with the engine off.

  Mutation check: make `enqueue_escalation` skip any cell whose seat ran the engine. Arms (a)
  and (c) go red. Rung 3.
- **TC-CONF-44** (FR-AGG-20, RC-03) — *the knob is frozen.* Start a run with
  `HARNESS_JEV_FINAL_ON_ACCEPT=true`, pause after half the cells, set it to `false`, and
  resume. Expected: every accepted-decision cell in the run is `final`, and the run row
  records `true`. Rung 3.
- **TC-JUDGE-46** (amended FR-JUDGE-37 / CT-JUDGE-14, CT-JUDGE-07; RC-01) — *injection cannot
  become final.* Run the CT-JUDGE-14 adversarial set through the decision path with
  `HARNESS_JEV_FINAL_ON_ACCEPT=true`. For each case, expected one of: (i) the recorded
  decision is below the gate, so it falls back and is not final; or (ii) citation verification
  fails, so it is below gate and not final. **No case yields `final`.** A mutation arm swaps
  in a recording that is above the gate with a forged citation, and asserts the citation
  check refuses it. This is the adversarial "plausible change" construction. Rung 3.

### 3.3 The call journal (M-PROV, callers, M-STORE) — E1

- **TC-PROV-65** (FR-PROV-44, CT-PROV-11, CT-PROV-32) — *one record per attempt, every
  implementation.* Parametrized over `OpenRouterProvider`, `LocalServerProvider`,
  `JevOpenRouterProvider` (SDK route), `OpenJevLocalProvider` and `RecordedFixtureProvider`.
  With a list sink installed, make one call: `complete()` on the three inference
  providers, and `decide()` on `JevOpenRouterProvider` and `OpenJevLocalProvider`. The
  fixture provider is exercised through both doors. Expected: exactly 1 record, with the FR-PROV-44
  field set present and typed. With no sink installed: zero records, and the provider writes
  no file (CT-PROV-11). Rung 1.
- **TC-PROV-66** (FR-PROV-44) — *retries are separate records.* The transport answers 429,
  then 500, then 200. Expected: 3 records sharing one `call_id`, with `attempt` = 1, 2, 3 and
  `outcome` = `retried`, `retried`, `ok`. A malformed final reply gives `outcome = malformed`
  and an `error` with the class name and no traceback. Rung 1.
- **TC-PROV-67** (FR-PROV-46, CT-PROV-31; RC-05) — *nothing secret is journaled.* Use the key
  `sk-or-TESTKEY-0123456789` and a page-reading call with a 3-page PNG payload. Byte-scan
  every journal line for:
  - the key, `Authorization`, `Bearer`, `HTTP-Referer`;
  - any base64 run over 200 characters.

  Expected: no hit. The image is recorded as a descriptor matching
  `^\[page image: page \d+ of \d+, \d+ KB, sha256 [0-9a-f]{4}`. Run over all five
  implementations. Rung 1. **Also added to the SEC-26 credential sweep.**
- **TC-PROV-68** (FR-PROV-45) — *call context.* Inside
  `call_context(kind="jev_decision", run_id="r1", work_id="w1", submission_id="s1",
  criterion_id="C2")`, a call's record carries those fields. A call outside any context
  records `kind = "unlabelled"`. Nested contexts restore the outer one on exit. Under a
  `ThreadPoolExecutor` of 8 workers, each setting its own context, every record carries its
  own worker's ids. Rung 0/1.
- **TC-PROV-69** (FR-PROV-45) — *no unlabelled call in a full pipeline.* Run the full fixture
  pipeline for ENG7 (intake, extract, judge with Jev on, synth) plus one drafting job and one
  help question. Expected:
  - zero `unlabelled` records;
  - each of the kinds `page_reading`, `package_drafting`, `answer_extraction`, `jev_decision`,
    `ai_judge` (via one below-gate cell), `feedback_writing` and `help_question` appears at
    least once.

  Rung 3.
- **TC-CONSOLE-93** (FR-CONSOLE-77) — *files land where specified.* After TC-PROV-69's run:
  - the class's calls are under `logs/ai-calls/<cohort_id>/<YYYY-MM-DD>.jsonl`;
  - the drafting calls are under `logs/ai-calls/_packages/<package_id>/`;
  - the help call is under `_help/`;
  - every line parses as JSON.

  The process-wide slot is installed once: both `python -m aeh run` and the console server
  journal without per-site injection. Rung 3.
- **TC-CONSOLE-94** (FR-CONSOLE-77) — *crash safety.* Append 3 records, then write half a 4th
  line (a simulated crash). The reader returns the 3 records and ignores the torn line. A
  fresh append afterwards starts on a new line and is readable. Two processes appending 500
  records each produce 1000 parseable lines. Rung 1.
- **TC-STORE-30** (FR-CONSOLE-77, CT-STORE-10; RC-06) — *purge removes the journal.* Seed a
  class with journal files and purge it. Expected:
  - `logs/ai-calls/<cohort_id>/` does not exist;
  - another class's folder and `_packages/` are untouched;
  - a purge that the store refuses leaves the folder in place (nothing half-deleted).

  Rung 3. **Regression entry.**

### 3.4 Teacher text and outcomes (M-CONSOLE) — E1 rung 3

- **TC-CONSOLE-87** (FR-UI-23, FR-CONSOLE-71, CT-CONSOLE-53; RC-12) — *the census.* Drive every
  read in the console API's route table and every action in `controls_payload()` against the
  existing `console_world` seed, plus an ENG7 package and draft the test builds inline, so
  the story needs no other story's fixture: success, refusal and job arms. Collect every string field. Expected: no match
  for `\b(FR|NFR|CT|TC|ADR|RS)-[A-Z0-9]+(-\d+)?\b`, `@[0-9a-f]{12}\b`, `\bpkg-`, a UUID, a
  path separator followed by `.sqlite`/`.toml`, or `\[\[`. ID fields (`*_id`) are exempt by
  name. Rung 3.
- **TC-CONSOLE-88** (FR-CONSOLE-71; RC-15) — *what `teacher_text()` does.* A table:

  | Input | Output |
  |---|---|
  | `"x (FR-AUTHOR-08)"` | `"x"` |
  | `"x (FR-PKG-28, CT-PKG-03)."` | `"x."` |
  | `"answer (Q2)"` | unchanged |
  | `"(2 of 3)"` | unchanged |
  | `"ENG7-READ-01@e34abeaceb0a"` with a stub `version_label` resolver returning "version 1" | `"ENG7-READ-01 version 1"` (the function is pure; the real resolver is TC-CONSOLE-89's) |
  | `""` | `""` |

  Applying it twice changes nothing more. Rung 0.
- **TC-CONSOLE-89** (FR-CONSOLE-74) — *version label.* Revisions 0, 1 and 5 read as
  "version 1", "version 2" and "version 6". The approval date is formatted "20 Oct 2026". An
  unknown version id gives a refusal that does not echo the id. Rung 3.
- **TC-CONSOLE-90** (FR-CONSOLE-72) — *package summary.* For an ENG7 draft with the approver
  and `pass` answered:
  - test name;
  - approver with `source = "your answer"`;
  - questions Q1/Q2/Q3 with points 2/3/3 and a total of 8;
  - the grade table pass 6 / not yet 0, with max 8;
  - rubric lines under their questions.

  With the approver unanswered, the summary carries "Not answered yet" for it. Rung 3.
- **TC-CONSOLE-91** (FR-CONSOLE-73) — *approve outcomes.*
  - (a) First approve → detail equals "Published ENG7-READ-01, version 1. Approved by Dana
    Teacher on 20 Oct 2026. Next: load the students' papers.", with `next` → Load papers.
  - (b) A second approve of the unchanged draft → `refused == False` and the detail starts
    "Already published —".
  - (c) Approve with a gap open → a refusal with what / why / next and no ID.

  Rung 3. **Regression for T2b.**
- **TC-CONSOLE-92** (FR-UI-25) — *every refusal has three parts.* Over the refusal arms of
  TC-CONSOLE-87's matrix: `what`, `why` and `next_action` are each non-empty and end in
  sentence punctuation. Students are named by name, never by `student_ref` (FR-UI-22). Rung 3.

### 3.5 Authoring questions (M-AUTHOR) — E1

- **TC-AUTHOR-44** (FR-AUTHOR-31/32) — *the fixed questions.*
  - AF-23 (pass named, no boundary) → the gaps are approver and `grades pass`. The questions
    equal "Who is approving this test? Type your name." and "What is the lowest total score
    that earns 'pass'?". The hint is "A whole number from 1 to 8. The test is out of 8
    points.".
  - AF-22 (no grade table) → "What is the passing score for this test?", hint "A whole number
    from 1 to 8. A student with this score or more passes."
  - "not yet" is **never** asked: its floor is 0 and filled in.
  - The engineering `reason` is present and never served in the teacher field.

  Rung 1.
- **TC-AUTHOR-45** (FR-AUTHOR-32, CT-AUTHOR-27; RC-11) — *the range boundaries, server side.*
  For `grades pass` (min 1, max 8), answers `0`, `1`, `8`, `9`, `6.5`, `"six"`, `""`, `-1`:
  - 1 and 8 are accepted;
  - every other answer is refused with exactly the gap's hint;
  - on a refusal the draft file is byte-identical (nothing written).

  Rung 1.
- **TC-AUTHOR-46** (FR-AUTHOR-32) — *floors must rise.* A three-grade table, A / B / not yet,
  with B = 4. For A: answer 4 is refused with "'A' must need more points than 'B' (4). Please
  enter a number from 5 to 8."; answer 5 is accepted. The hint's `lo` is derived (5). Rung 1.
- **TC-AUTHOR-47** (FR-AUTHOR-32) — *max follows the paper.* With Q2's points missing, the
  grade question is not offered until "How many points is question 2 worth?" is answered
  (range 1–100). After answering 3, the grade hint reads "from 1 to 8". After answering 5, it
  reads "from 1 to 10". Rung 1.
- **TC-AUTHOR-48** (FR-AUTHOR-32) — *the approver.* Answers `""` and an 81-character name are
  refused; 1 and 80 characters are accepted. Rung 1.

### 3.6 Timings (M-PIPE, M-CONSOLE) — E1

- **TC-PIPE-39** (FR-CONSOLE-75; RC-16) — *stage seconds.* With an injected clock advancing
  10 s in extract, 20 s in judge and 5 s in aggregate: `run_metrics` has
  `stage_seconds.extract = 10`, `judge = 20`, `aggregate = 5`, and no `synth` row when synth
  did not run. After pause and resume with 7 more judge seconds, `judge = 27`. Rung 3.
- **TC-CONSOLE-96** (FR-CONSOLE-75) — *timings in the results read.* `stage_timings` lists
  "Reading answers", "AI grading" and "Combining grades" in run order, with their seconds.
  An absent stage is not listed and never appears as 0. A job record has `started_at` and
  `finished_at` for both a drafting job and an intake job. Rung 3.

### 3.7 Results by question (M-CONSOLE) — E1

- **TC-CONSOLE-97** (FR-CONSOLE-76, CT-CONSOLE-54; RC-08) — *the roll-up.* ENG7 seed
  student A has C1a present (1), C1b present (1), C2 2 of 3 and C3 2 of 3. Expected:
  - `questions` = [Q1 2/2, Q2 2/3, Q3 2/3];
  - `total_points` 6, `total_max` 8, `grade` "pass".

  Student B has C1a 1 and C1b 0, so Q1 is 1/2. Rung 3. **Regression entry.**
- **TC-CONSOLE-98** (CT-CONSOLE-54) — *roll-up property.* Generate random band assignments
  over the ENG7 rubric. For every student, Σ `questions.points_awarded == total_points`,
  0 ≤ awarded ≤ max per question, and Q1 == C1a + C1b. Rung 0, Hypothesis 200 examples.
- **TC-CONSOLE-99** (FR-CONSOLE-76; RC-09) — *grade boundaries.* Totals 0, 5, 6 and 8 map to
  not yet, not yet, pass and pass. Rung 0.
- **TC-CONSOLE-100** (FR-CONSOLE-76) — *question stats.* With 4 students on Q2 at 3, 2, 2 and
  0: `mean_points` 1.75, `full_marks` 1, `zero_marks` 1, `graded` 4, `points_max` 3. A
  question with no graded answer has `graded` 0 and a null mean (not 0). The rounding arms
  for FR-UI-31's label formatter (rung 0):

  | Mean / max | Label |
  |---|---|
  | 1.75 / 3 | "1.8 / 3 (58%)" |
  | 2.25 / 3 | "2.3 / 3 (75%)" |
  | 1.5 / 2 | "1.5 / 2 (75%)" |
  | 0 / 3 | "0.0 / 3 (0%)" |
  | 3 / 3 | "3.0 / 3 (100%)" |
  | 0.125 / 1 | "0.1 / 1 (13%)" (half-up on the percentage) |

  Rung 0/3.
- **TC-CONSOLE-101** (FR-UI-33, RC-10) — *Approve all settles the questions too.* Seed one
  student with two `provisional_unreviewed` questions and finalize the batch. Expected:
  - every question in the results read is `final` and no `not_final_reason` remains;
  - the counter behind the banner is 0.

  With an open review window, the outcome is the deferral and the questions remain not
  final. Rung 3.

### 3.8 AI-call read and CLI (M-CONSOLE) — E1

- **TC-CONSOLE-95** (FR-CONSOLE-78, CT-PROV-32; pair M-CONSOLE→M-PROV) — *the read.* After
  TC-PROV-69's run:
  - `GET /api/v1/ai-calls?run_id=…` returns the records newest first, 50 per page;
  - filters `student=<name>`, `question_id=Q2`, `kind=jev_decision` and `outcome=ok` each
    narrow the list correctly;
  - each item has a teacher kind label from the FR-CONSOLE-78 set, the student's **name**,
    and `request`/`response` in full.

  It reads both a fixture-provider record and a canned live-provider record (the shape
  parity). Rung 3.
- **TC-CONSOLE-102** (FR-UI-35, CT-CONSOLE-09 amended; RC-18) — *real classes are not filtered.*
  The same read over the `real` seed cohort returns its Jev records. `/api/v1/logs` (Run
  steps) still carries no per-student figure (CT-CONSOLE-09's narrowed scope holds). The
  default filter, with no `kind` given and opened from the UI, is `jev_decision,ai_judge`.
  Rung 3.
- **TC-CONSOLE-103** (FR-CONSOLE-79) — *the CLI.*
  `python -m aeh logs ai-calls --data-dir D --run R --student "Tomas Reader" --question Q2`
  prints one summary line per call. `--full` adds the request and response under each.
  `--json` prints lines that parse to the same records. An unknown student prints "No AI
  calls match." and exits 0. A missing data folder exits 2 with a plain message. Rung 3.

### 3.9 SPA screens (M-UI) — E6 browser

- **TC-UI-24** (FR-UI-23, CT-CONSOLE-53) — *screen census.* Walk every SPA route on the ENG7
  world (extending TC-CONSOLE-74's walk). The visible text matches no FR-UI-23 pattern. On
  Results and Review, none of the words *finalize*, *batch*, *provisional* or *no-op* appear.
- **TC-UI-25** (FR-UI-24; RC-13) — *outcome visible without scrolling.* For every action in
  `controls_payload()` reachable in the SPA: scroll the button into view at 1280×720 and
  click. Expected:
  - the outcome banner's bounding box is inside the viewport;
  - a toast appears;
  - the button is disabled while the request is pending.

  This is a census: a new action without a banner fails.
- **TC-UI-26** (FR-UI-25) — *refusal shape on screen.* Trigger three refusals (approve with a
  gap open, delete a graded class, an out-of-range passing score). Each shows a what, a why
  and a next step as three visible sentences.
- **TC-UI-27** (FR-UI-36; RC-20) — *input census.* On every route, every `input`, `select` and
  `textarea` except `type=search`:
  - has a visible label;
  - has a non-empty element referenced by `aria-describedby`, the format line;
  - for each `whole_number` field, typing `min-1`, `max+1` and `abc` shows an inline error
    equal to "Please enter " + the format line's content, and the submit button is disabled
    with a reason.

  The format text equals the API-served hint (the same definition, checked by comparing to
  the read).
- **TC-UI-28** (FR-AUTHOR-31, FR-UI-36) — *the passing-score question on screen.* On AF-22:
  - the heading reads "A few questions before you approve" and the count "Question 1 of 2";
  - the field shows "A whole number from 1 to 8. …" beneath it and "e.g. 6" as placeholder;
  - entering 9 shows "Please enter a whole number from 1 to 8." at the field, nothing is
    sent (network log), and the typed value is kept.
- **TC-UI-29** (FR-UI-26, FR-UI-27) — *approve shows the whole package and its result.* Before
  approving, the page shows, in order: Test ENG7-READ-01, Approved by (your answer), Passing
  score 6 of 8, Questions with total 8, and How each question is scored. Approve is disabled
  with its reason while a piece is open. After approving:
  - the top banner shows FR-CONSOLE-73's sentence, inside the viewport;
  - the Approve button is gone and **Load papers** is present.

  Reloading the page keeps the approved state.
- **TC-UI-30** (FR-UI-28; RC-17) — *switcher names the package.* With ENG7-READ-01 published,
  the package switcher's option text is exactly "ENG7-READ-01". With two versions, it is
  "ENG7-READ-01 — version 2". A `pkg-` id still reads "Test package 1".
- **TC-UI-31** (FR-UI-30, FR-UI-31, CT-CONSOLE-54) — *results by question.* On the ENG7 seed:
  - each student row shows "Q1 · 2 / 2", "Q2 · 2 / 3", "Q3 · 2 / 3" and a column header
    "Total grade" with "6 / 8 — pass";
  - the overview has one bar per question, and a grade-count chart. With TC-CONSOLE-100's Q2
    marks (3, 2, 2, 0), the label is exactly "Q2 — average 1.8 / 3 (58%)";
  - no pooled rubric-level histogram is present.
- **TC-UI-32** (FR-UI-32, FR-UI-33) — *not-final explained and approvable.* On a seed with 2
  not-final questions:
  - the top banner reads "2 answers need your check before the grades are final." with
    **Check answers** and **Approve all grades**;
  - each "Check" badge's text equals the FR-UI-32 sentence for its code;
  - **Approve all grades** shows FR-UI-33's confirmation; confirming shows "All grades are
    final." and no "Check" badge remains.
- **TC-UI-33** (FR-UI-29) — *elapsed clock.* Start a recorded drafting job with a slowed
  replay seam. The page shows `Working — \d+ s`, and the number increases between two reads
  1.5 s apart. On finish it shows `Done in (\d+ s|\d+ min \d+ s)` in the banner. Results
  shows a "Time taken" row per stage. The duration formatter is unit-tested for 45 → "45 s",
  134 → "2 min 14 s" and 3900 → "1 h 5 min" (rung 0 arm).
- **TC-UI-34** (FR-UI-34, FR-UI-35) — *How was this graded?* From a student's detail page,
  click **How was this graded?** on Q2:
  - Logs opens on **AI calls**, filtered to that student, question and run;
  - expanding the Jev row shows "Question sent to Jev" and "Jev's answer" verbatim, plus
    "confidence 0.91, needed above 0.80 — accepted";
  - for a below-gate cell, "Question sent to the judge" and "The judge's answer" are shown;
  - each panel's Copy button puts the panel text on the clipboard.

  Repeat on the `real` cohort (RC-18).

### 3.10 Help and tutorial (M-HELP) — E1

- **TC-HELP-07** (FR-HELP-07) — *the logs tutorial ships.*
  - `docs/tutorials/logs-tutorial.md` exists and is byte-identical to
    `src/aeh/help_assets/manuals/logs-tutorial.md` (the mirror rule).
  - It is listed in the Help read.
  - It names Logs → AI calls, "How was this graded?" and `aeh logs ai-calls`, and states that
    the log is deleted with the class.
  - It contains no FR-UI-23 pattern.
  - Every image it references exists.

### 3.11 Acceptance journeys — the ENG7 walk

- **TC-E2E-14** (live; FR-CONF-36/37, FR-AUTHOR-31/32, FR-CONSOLE-72…79, FR-UI-23…36, FR-AGG-20,
  FR-PROV-44…46; RC-19) — *the real run.* Marker `live`; skips without
  `OPENROUTER_API_KEY`. The setup is a fresh data folder, the shipped `live-test.dev-ci.toml`,
  and **no** `HARNESS_ORCH_*` env. The class is created with consent **`synthetic`** (a `real`
  class is refused before any page is sent to a cloud model). Drive the delta's §7 steps 1–14
  through the SPA, with the last step via the CLI. Per step, assert the expected text is
  visible inside the 1280×720 viewport. The model drafts the package, so the text splits into
  two kinds:
  - **Exact** (system wording, fixed by the design):
    - "A few questions before you approve"
    - "Who is approving this test? Type your name."
    - FR-CONSOLE-73's "Published ENG7-READ-01, version 1. …"
    - the switcher text "ENG7-READ-01"
    - "Total grade"
    - FR-UI-32's six sentences
    - "All grades are final."
  - **Pattern** (depends on what the live draft found):
    - `Question \d+ of \d+`
    - `Working — \d+ s`
    - `Done in (\d+ s|\d+ min \d+ s)`
    - `Q\d · \d+ / \d+`
    - `\d+ / 8 — (pass|not yet)`
  - **Conditional.** The passing-score question is asserted only if the draft raised that gap.
    Any gap the draft raises must show a question ending in "?" and a format line, never an
    engineering reason. The answers are supplied from a table keyed by gap kind (the approver:
    a name; a grade floor: 6; points: from the package spec).

  Structural assertions:
  - 4 papers read and matched;
  - per student, Σ question points = total and the grade is consistent with total;
  - every judged cell has ≥ 1 journal record of kind `jev_decision` or `ai_judge`;
  - every Jev-final cell's journal shows the gate above 0.80;
  - every not-final cell has a reason sentence;
  - after **Approve all grades**, the page shows "All grades are final.";
  - the run's cost is under 5 USD;
  - **total spend across the whole walk** — the sum of the journal's `cost` over every kind,
    including drafting and page reading, which the run's ceiling does not cover — is recorded
    and asserted under 10 USD (Assumption: an envelope for 4 papers, to be tightened from the
    first recorded figure).

  It records each stage's duration, the Jev-final share and the cost in the live-readiness
  record, saves screenshots for FR-HELP-07, and with `record=True` writes the recordings
  TC-E2E-15 replays.
- **TC-E2E-15** (recorded twin of TC-E2E-14; FR-UI-23, FR-UI-24, FR-UI-36, FR-CONSOLE-76, FR-CONSOLE-78, FR-AGG-20) — the same 14 steps on `RecordedFixtureProvider`
  from TC-E2E-14's recordings, in E6, with zero egress (network log). It runs on every SPA
  change, so the walk stays green between live runs.

### 3.12 Regression entries (the teacher's report, pinned)

- **TC-REG-17** — T1: the authoring screen for an ENG7 draft with a missing grade boundary
  contains no "(FR-" and no "never invented". The question text is present (→ TC-AUTHOR-44,
  TC-UI-28).
- **TC-REG-18** — T2b: a second press on Approve neither refuses nor shows "@". (→ TC-CONSOLE-91)
- **TC-REG-19** — T3: the switcher reads ENG7-READ-01. (→ TC-UI-30)
- **TC-REG-20** — T5b: a Jev-accepted ENG7 cell is final with the shipped one-judge config, and
  the Results banner offers approval when anything is not final. (→ TC-AGG-27, TC-UI-32)
- **TC-REG-21** — T0a: the 4-student console run completes with the shipped config and no env.
  (→ TC-CONF-41)

Each is a thin case that asserts the original symptom is gone, kept even after the detailed
cases exist, so the report's exact defects stay pinned.

---

## 4. Cross-cutting suites

### 4.1 Contract clause walk (each clause → the case that fails if it is violated)

| Clause | Kind | Change | Verifying case(s) | Consumers | Suite |
|---|---|---|---|---|---|
| CT-PROV-11 | state | amended | TC-PROV-65 (no sink → no record, no file) | M-ORCH, M-CONSOLE | contract/prov |
| CT-PROV-14 | observe | amended | TC-PROV-65, TC-PROV-66 (field names, kinds) | ops, M-CONSOLE | contract/prov |
| CT-PROV-31 | security | new | TC-PROV-67 (×5 implementations), SEC-26 sweep | all | contract/prov, security |
| CT-PROV-32 | behaviour | new | TC-PROV-65 (×5), TC-CONSOLE-95 (read parity) | M-CONFORM, M-CONSOLE | contract/prov |
| CT-AGG-23 | behaviour | amended (breaking) | TC-AGG-27 row (d), TC-AGG-28 | M-GRADE, M-REVIEW, M-STATS | contract/agg |
| CT-AGG-24 | behaviour | new (breaking) | TC-AGG-27, TC-AGG-29, TC-AGG-30, TC-ORCH-61 | M-GRADE, M-REVIEW, M-STATS, M-ORCH, M-CONSOLE | contract/agg |
| CT-JUDGE-07 | behaviour | amended (breaking) | TC-AGG-27 rows (a)/(b), TC-JUDGE-46 | M-AGG, M-ORCH | contract/judge |
| CT-JUDGE-14 | security | amended (breaking) | TC-JUDGE-46 (incl. the mutation arm) | M-AGG, M-CONFORM | contract/judge |
| CT-CONSOLE-09 | security | amended (breaking) | TC-CONSOLE-102 | M-UI | contract/console |
| CT-CONSOLE-53 | data | new | TC-CONSOLE-87, TC-UI-24 | M-UI | contract/console |
| CT-CONSOLE-54 | data | new | TC-CONSOLE-97, TC-CONSOLE-98, TC-UI-31 | M-UI | contract/console |
| CT-CONF-25 | config | new | TC-CONF-40, TC-CONF-41 | M-ORCH, M-CONSOLE | contract/conf |
| CT-STORE-10 | state | amended | TC-STORE-30 | M-CONSOLE | contract/store |
| CT-AUTHOR-27 | behaviour | new | TC-AUTHOR-45, TC-UI-27 | M-CONSOLE, M-UI | contract/author |

**Mutation check per clause:**
- CT-AGG-24: make the rule key on the verdict count alone, ignoring `scoring_engine`.
  TC-AGG-27(b) goes red.
- CT-PROV-32: drop the journal call in the Jev SDK route. TC-PROV-65[Jev] goes red.
- CT-STORE-10: remove the `rmtree` from purge. TC-STORE-30 goes red.
- CT-CONSOLE-54: sum every criterion row. TC-CONSOLE-97 goes red.
- CT-CONF-25: drop the config read in `run_start.py`. TC-CONF-41(b) goes red.

### 4.2 Regression sets (blast radius) and referenced requirements

The delta cites these existing requirements without changing them. They stay covered by their
existing suites. This plan re-runs those suites, and adds no case for them:

- **Amended single-judge rule (FR-AGG-07):** now covered here by TC-AGG-27(c) (knob off) and
  TC-AGG-27(b). FR-JUDGE-37 is amended and covered by TC-JUDGE-46.
- **Unchanged and re-run:**
  - FR-AGG-19 and the two-decision refusal (agg suite);
  - FR-JUDGE-27/30 (judge suite);
  - CT-ORCH-15 / FR-ORCH-11 (orch suite; TC-ORCH-61 checks independence);
  - CT-PROV-01/02/13/16 (prov suite);
  - FR-UI-22 (TC-CONSOLE-92 re-asserts names);
  - CT-CONSOLE-33 (refusal suite);
  - FR-CONSOLE-22 (TC-CONSOLE-101's window arm);
  - FR-PKG-24 (the evidence_sum suite; TC-CONSOLE-97 consumes it);
  - FR-REVIEW-14 (blind sample suite);
  - FR-STORE-12, NFR-STORE-05 (store suite);
  - the base plan's six-key sweep (TC-CONF-43 duplicates its guard);
  - the console import-graph census (must stay green with the journal reader).

**CI blast-radius sets:**

| Changed module | Re-run |
|---|---|
| `M-AGG` | `pytest tests -k "agg or review or stats or grade or orch"` |
| `M-PROV` | `tests/unit/prov tests/contract/prov tests/security` plus TC-PROV-69, TC-CONSOLE-93/95 |
| `M-CONSOLE` | console unit/integration, plus `tests/browser/spa` |
| `M-AUTHOR` | the author suites, plus TC-UI-28/29 |
| `M-CONF` | the conf suites, plus TC-CONF-41 |

### 4.3 Property suites

- TC-CONSOLE-98 (roll-up)
- TC-AGG-28 (confidence = gate)
- TC-PROV-68 (thread-local context)
- A property arm of TC-CONSOLE-88: for any string `s` without an ID pattern,
  `teacher_text(s) == s`.

### 4.4 Security

TC-PROV-67 (no key or headers in the journal) joins the SEC-26 credential sweep. TC-STORE-30
covers the purge. TC-JUDGE-46 is the adversarial case for the narrowed safety property. No new
network surface: the AI-call read is behind the console's existing bind and access, and is
covered by the existing console access suite.

### 4.5 Performance

- No quantified NFR in the delta.
- TC-E2E-14 **records** each stage's duration and the run's cost. These replace the delta's
  §9 placeholders.
- The AI-call read is measured once on TC-E2E-14's journal (the count of records and the
  read's time). No pass/fail threshold is invented.

### 4.6 Suites skipped, deliberately

- **Load:** one teacher, one machine.
- **Fuzz:** the only new parsed inputs are numeric answers (covered by boundaries) and JSONL
  lines the system itself wrote (covered by the torn-line case).

---

## 5. Requirements traceability matrix

| Requirement | Test cases |
|---|---|
| FR-UI-23 | TC-CONSOLE-87, TC-UI-24, TC-REG-17 |
| FR-UI-24 | TC-UI-25, TC-UI-29 |
| FR-UI-25 | TC-CONSOLE-92, TC-UI-26 |
| FR-UI-26 | TC-UI-29 |
| FR-UI-27 | TC-UI-29, TC-REG-18 |
| FR-UI-28 | TC-UI-30, TC-REG-19 |
| FR-UI-29 | TC-UI-33 |
| FR-UI-30 | TC-UI-31 |
| FR-UI-31 | TC-UI-31 |
| FR-UI-32 | TC-UI-32 |
| FR-UI-33 | TC-UI-32, TC-CONSOLE-101 |
| FR-UI-34 | TC-UI-34 |
| FR-UI-35 | TC-UI-34, TC-CONSOLE-102 |
| FR-UI-36 | TC-UI-27, TC-UI-28 |
| FR-CONSOLE-71 | TC-CONSOLE-87, TC-CONSOLE-88 |
| FR-CONSOLE-72 | TC-CONSOLE-90 |
| FR-CONSOLE-73 | TC-CONSOLE-91, TC-REG-18 |
| FR-CONSOLE-74 | TC-CONSOLE-89 |
| FR-CONSOLE-75 | TC-PIPE-39, TC-CONSOLE-96 |
| FR-CONSOLE-76 | TC-CONSOLE-97, TC-CONSOLE-98, TC-CONSOLE-99, TC-CONSOLE-100 |
| FR-CONSOLE-77 | TC-CONSOLE-93, TC-CONSOLE-94, TC-STORE-30 |
| FR-CONSOLE-78 | TC-CONSOLE-95 |
| FR-CONSOLE-79 | TC-CONSOLE-103 |
| FR-AUTHOR-31 | TC-AUTHOR-44, TC-UI-28 |
| FR-AUTHOR-32 | TC-AUTHOR-44, TC-AUTHOR-45, TC-AUTHOR-46, TC-AUTHOR-47, TC-AUTHOR-48 |
| FR-AGG-20 | TC-AGG-27, TC-AGG-28, TC-AGG-31, TC-CONF-44, TC-REG-20 |
| FR-AGG-07 (amended) | TC-AGG-27 |
| FR-JUDGE-37 (amended) | TC-JUDGE-46 |
| FR-ORCH-45 | TC-ORCH-61, TC-ORCH-62 |
| FR-CONF-36 | TC-CONF-40, TC-CONF-41, TC-CONF-43, TC-REG-21 |
| FR-CONF-37 | TC-CONF-42 |
| FR-PROV-44 | TC-PROV-65, TC-PROV-66 |
| FR-PROV-45 | TC-PROV-68, TC-PROV-69 |
| FR-PROV-46 | TC-PROV-67 |
| FR-HELP-07 | TC-HELP-07 |
| (whole delta, live) | TC-E2E-14, TC-E2E-15 |

The contract matrix is §4.1.

---

## 6. §8.2 — test-story table

"Ahead" means written ahead of implementation: red by design, with
`@pytest.mark.writtenahead` and a `WRITTEN_AHEAD_BLOCKERS` entry. When the implementing story
closes, the marker is removed and the test kept. A `yes` story carries no dependency.

| Story | Title | Covers | Level | Depends on | Ahead |
|---|---|---|---|---|---|
| T1 | Clarity fixtures: AF-22/23, the Jev-final seed (synthetic + real), ENG7 world helpers | TC-AUTHOR-44 (fixture half), TC-CONSOLE-97 (seed half) | artifact | — | **yes** |
| T2 | Journal clause suite across all five providers | TC-PROV-65, TC-PROV-66, TC-PROV-67, TC-PROV-68 | contract | — | **yes** |
| T3 | Jev-final clause suite (agg/judge/orch) | TC-AGG-27, TC-AGG-28, TC-AGG-31, TC-JUDGE-46 | contract | — | **yes** |
| T4 | Teacher-text census and console clause cases | TC-CONSOLE-87, TC-CONSOLE-88, TC-CONSOLE-92 | contract + integration | — | **yes** |
| T5 | Config knob suite | TC-CONF-40, TC-CONF-41, TC-CONF-42, TC-CONF-43, TC-REG-21 | unit + integration | S1 | no |
| T6 | Jev-final integration pairs | TC-AGG-29, TC-AGG-30, TC-ORCH-61, TC-ORCH-62, TC-CONF-44, TC-REG-20 | integration | S2, T1 | no |
| T7 | Journal integration: files, crash safety, purge, full-pipeline kinds | TC-PROV-69, TC-CONSOLE-93, TC-CONSOLE-94, TC-STORE-30 | integration | S3 | no |
| T8 | AI-call read and CLI | TC-CONSOLE-95, TC-CONSOLE-102, TC-CONSOLE-103 | integration | S4, T7 | no |
| T9 | Authoring questions and approve reads | TC-AUTHOR-44, TC-AUTHOR-45, TC-AUTHOR-46, TC-AUTHOR-47, TC-AUTHOR-48, TC-CONSOLE-89, TC-CONSOLE-90, TC-CONSOLE-91, TC-REG-18 | unit + integration | S5, S6, T1 | no |
| T10 | Timings and results-by-question reads | TC-PIPE-39, TC-CONSOLE-96, TC-CONSOLE-97, TC-CONSOLE-98, TC-CONSOLE-99, TC-CONSOLE-100, TC-CONSOLE-101 | unit + integration | S7, S8, T1 | no |
| T11 | SPA clarity censuses (text, outcome viewport, refusal shape, inputs) | TC-UI-24, TC-UI-25, TC-UI-26, TC-UI-27 | browser | S9 | no |
| T12 | SPA authoring, approve and switcher | TC-UI-28, TC-UI-29, TC-UI-30, TC-REG-17, TC-REG-19 | browser | S10, T9 | no |
| T13 | SPA results, approval, timing and AI calls | TC-UI-31, TC-UI-32, TC-UI-33, TC-UI-34 | browser | S11, S12, T10, T8 | no |
| T14 | Live ENG7 walk against OpenRouter (captures recordings) | TC-E2E-14 | live | T5, T6, T8, T11, T12, T13 | no |
| T15 | Recorded ENG7 walk and logs tutorial | TC-E2E-15, TC-HELP-07 | browser | T14, S13 | no |

Code stories (from the design delta, for the dependency graph):

| Story | Title | Traces to | Depends on |
|---|---|---|---|
| S1 | Orchestration knobs read from the config file; shipped configs and tutorials updated | FR-CONF-36, FR-CONF-37, CT-CONF-25 | — |
| S2 | A confident Jev decision is final; not-final reason codes; no escalation for Jev-final; knob frozen in RunConfig | FR-AGG-20, FR-ORCH-45, CT-AGG-23, CT-AGG-24, CT-JUDGE-07, CT-JUDGE-14 | — |
| S3 | AI-call journal: CallRecord from all five providers, call context at callers, process-wide JSONL sink, purge | FR-PROV-44, FR-PROV-45, FR-PROV-46, FR-CONSOLE-77, CT-PROV-11, CT-PROV-14, CT-PROV-31, CT-PROV-32, CT-STORE-10 | — |
| S4 | AI-call read and `aeh logs ai-calls` | FR-CONSOLE-78, FR-CONSOLE-79, CT-CONSOLE-09 | S3 |
| S5 | Teacher-text boundary, version label, package summary and approve outcomes | FR-CONSOLE-71, FR-CONSOLE-72, FR-CONSOLE-73, FR-CONSOLE-74, CT-CONSOLE-53 | — |
| S6 | Authoring gaps as plain questions with typed, ranged answers | FR-AUTHOR-31, FR-AUTHOR-32, CT-AUTHOR-27 | — |
| S7 | Stage timings into run_metrics and the results read | FR-CONSOLE-75 | — |
| S8 | Results by question: points, total grade, grade name, question stats; Approve all settles questions | FR-CONSOLE-76, CT-CONSOLE-54 | S2 |
| S9 | SPA clarity shell: outcome banner, plain refusals, input format lines | FR-UI-23, FR-UI-24, FR-UI-25, FR-UI-36 | S5 |
| S10 | SPA authoring questions, package summary, approved state, package switcher name | FR-UI-26, FR-UI-27, FR-UI-28 | S5, S6, S9 |
| S11 | SPA results by question, per-question charts, not-final reasons, Approve all grades, elapsed clock | FR-UI-29, FR-UI-30, FR-UI-31, FR-UI-32, FR-UI-33 | S7, S8, S9 |
| S12 | SPA AI calls tab and "How was this graded?" | FR-UI-34, FR-UI-35 | S4, S9 |
| S13 | Logs tutorial (docs + help manuals), screenshots from the live walk | FR-HELP-07 | S12, T14 |

Suggested order, from the dependency graph:
1. S1, S2 and S3 in parallel; they make the run behave and record.
2. Then the reads: S4–S8.
3. Then the screens: S9–S12.
4. Then T14, the live walk.
5. Then S13 and T15.

---

## 7. What passing this plan does and does not prove

**It proves** that the console states every outcome, question, reason and format plainly
within the viewport, on every screen and action the censuses walk. It proves the per-question
arithmetic is right for every rubric method ENG7 uses, and that a Jev-final mark is final
while no other single-grader mark is. It proves every model call on every provider leaves a
readable, secret-free record that is deleted with its class. And through TC-E2E-14, it proves
the whole ENG7 day works once against real OpenRouter.

**Contract half:** all 14 new or amended clauses have a verifying case, and the 5 breaking ones
also have pair cases with each named consumer. The five live-provider journal cases run at
rung 1 against canned transports. Only TC-E2E-14 exercises a real provider, and it exercises
OpenRouter only. `LocalServerProvider` and `OpenJevLocalProvider` journaling are **verified
only against their transport seams**, not against a running local model (no E4/E7 hardware;
see the release-checklist memory).

**It does not prove:**
- **That Jev is right when it is confident.** ADR-50 accepts Jev's gate as sufficient.
  TC-JUDGE-46 proves the known injection set cannot pass, not that no injection can. The blind
  sample and the teacher's amendments are the compensating controls.
- **That a teacher finds things.** The censuses prove that text is present, plain and visible.
  They do not prove usability. A teacher try-out after this lands (memory: the try-out after
  gaps close) is the compensating step.
- **Live stability.** TC-E2E-14 is one run. Model output varies (the base M-PROV reproducibility non-promise), so a later live
  run may surface a reply shape the recordings never saw. It is re-run before the test day.
- **Census completeness for future screens.** TC-UI-24/25/27 walk the route table and
  `controls_payload()` as they stand. A screen or input added outside those registries is
  invisible to them.
- **Finalize semantics.** TC-CONSOLE-101 pins the required end state. The delta records that
  whether `finalize_batch` itself settles `criterion_score` is unverified. S8 decides that, and
  the case is written against the outcome, not the mechanism.
- **Performance.** There is no threshold, only recorded figures.

**Untested versus untestable.**
- *Untested, a scheduling choice:* local-model journaling against a running model (no E4/E7
  hardware yet); live runs beyond one.
- *Untestable here, managed in production:* Jev's real-world accuracy when confident, and
  whether teachers find things on screen. These are managed by the blind sample, the AI-call
  log and a teacher try-out.

**The most likely way this ships broken despite a green suite** is a live Jev reply or draft
shape that the single TC-E2E-14 run never produced. For example, a gap kind with no plain
question, which would show an engineering reason again, or a Jev response the journal records
but the AI-calls view cannot render. We mitigate it by re-running TC-E2E-14 before the test
day, and by FR-UI-23's census failing closed on any unrecognized gap text.

**Residual risk, and what compensates:**
- `HARNESS_JEV_FINAL_ON_ACCEPT=false` is a one-line rollback of the Jev-final rule.
- The AI-call log makes every Jev-final mark inspectable after the fact.
- The first real class's grades are reviewed by the teacher in full before export, a
  test-day plan step.

---

## 7a. Known gaps — IDs the delta cites but does not change

The delta names these IDs as context, as an example of a leaked string, or as an unchanged
dependency. They are not new surface, and this plan adds no case for them. Their coverage
lives in `docs/design/test-plan.md` and the earlier delta plans, and the §4.2 regression sets
re-run those suites.

| ID | Why the delta cites it | Covered by |
|---|---|---|
| FR-AUTHOR-08 | Quoted as the leaked "(FR-AUTHOR-08)" in T1. The never-invent rule itself is unchanged | Existing authoring suite. The leak is covered by TC-CONSOLE-87 / TC-REG-17 |
| FR-CONSOLE-02 | Quoted as the leaked "(FR-CONSOLE-02)" in `Results.tsx`. The no-op rule is unchanged | Existing console suite. The leak is covered by TC-UI-24 |
| FR-PKG-28, CT-PKG-03 | Quoted as an example ID list in `teacher_text()`'s table | Existing package suite. The scrub is covered by TC-CONSOLE-88 |
| FR-AGG-19 | Engine-blindness is narrowed by FR-AGG-20 and otherwise unchanged | Agg suite. The narrowing is covered by TC-AGG-27(d) |
| FR-ORCH-10, FR-ORCH-14 | The odd-panel ladder and budget admission are unchanged for every cell that is not Jev-final (FR-ORCH-45) | Orch suite. The "unchanged" claim is held differentially by TC-ORCH-62 |
| FR-JUDGE-27, FR-JUDGE-30 | The gate and the citation verification that make a Jev verdict "accepted" are unchanged | Jev judge suite. Relied on by TC-JUDGE-46 |
| FR-REVIEW-14 | The blind sample is unchanged and now includes Jev-final marks | Blind-sample suite |
| FR-STORE-12, NFR-STORE-05 | Pseudonymization and encryption at rest, which the journal inherits | Store suite. The journal's own secrets are covered by TC-PROV-67 |
| CT-CONSOLE-33 | The refusal shape that FR-UI-25 restates | Console refusal suite. Re-asserted by TC-CONSOLE-92 |
| CT-PROV-01 | The provider surface, deliberately unchanged (ADR-52) | Prov clause suite. TC-PROV-68 proves the context arrives without a surface change |
| CT-PROV-02 | Substitutability, extended to the journal by CT-PROV-32 | Prov clause suite. TC-PROV-65 runs all five |
| CT-PROV-13 | No credential in logs; requests carry `student_ref` only | Prov clause suite and SEC-26. Extended to the journal by TC-PROV-67 |

## 8. Handoff

```bash
/plan-to-issues docs/design/console_clarity_design_delta.md docs/design/console_clarity_test_plan.md
```

Name the two files. Passing the folder would also read `test-plan.md` and every earlier
delta plan, and could re-issue stories that have already shipped.

`/plan-to-issues` transcribes §6's two tables verbatim:
- the 13 code stories become `type:story` issues;
- the 15 test stories become `type:test` issues;
- T1–T4 are written ahead.
