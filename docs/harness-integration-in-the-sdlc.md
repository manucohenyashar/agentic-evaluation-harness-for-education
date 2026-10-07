# How the test harness is built into the development process

*What it is, exactly where it is wired in, how its gates are called, what gives it authority, what it created and why, and how it grows itself.*

**Audience.** Engineers and reviewers who need to see the harness as part of the software life cycle rather than as a folder of tests. Every statement here points at a file, or at a command whose output was captured on this branch (`refactor`). Where something is inferred or not yet built, it says so.

**Companion documents.** [`harness-adoption.md`](harness-adoption.md) says *which* external harness ideas were adopted and why. [`design/test-plan.md`](design/test-plan.md) is the plan the tests implement. This document is the missing middle: the wiring.

---

## 1. The idea in one page

Most projects bolt tests on after the code. This project treats the **test harness and the application as one thing that grows together**, and arranges the development process so that neither can advance without the other:

1. **The design is written to be testable.** Every requirement has an ID (`FR-*`, `NFR-*`) and every module has a contract of promises its callers rely on (`CT-*`). A requirement that cannot be tested as written is a defect in the design.
2. **The test plan is derived from the design before any code exists**, and a script proves every requirement and every contract clause has at least one test case.
3. **The plan becomes a graph of issues**: for each module, a *story* (build it) and a paired *test* issue (verify it), with dependencies written in a form a script can read.
4. **Tests are written ahead of the code.** They start **red on purpose**, carry a marker that keeps them out of the main gate, and are registered in a table that notices when the code they wait for arrives.
5. **Every turn of work ends at a gate.** A hook refuses to let an agent finish while the test command fails. A second agent with no stake in the code reviews it against the issue's one-sentence goal.
6. **What goes wrong becomes new tests, and new design.** Reviewer disclosures, gap analyses and parked issues are written up, turned into design deltas, test-plan deltas and issues, and the loop runs again.

```
                 ┌──────────────────────────────────────────────────────────────┐
                 │                         LEARN                                │
                 │  reviewer disclosures · gap analysis · findings register     │
                 │  parked issues · red-by-design tests nobody owns             │
                 └───────────────┬──────────────────────────────▲───────────────┘
                                 │ design delta                 │ new findings
                                 ▼                              │
  HLD ─► detailed design ─► test plan ─► issues ─► dispatch ─► story ║ test (a pair)
        FR/NFR/CT IDs      TC IDs      Goal /       ready-      /fix-issue  /write-tests
        + seams designed   + risk      Traces to    issues.sh   (code)      (tests, red
          in               register    Depends on                           ahead of code)
              ▲                │            ▲                          │
              │  check_        │   trace-   │                          ▼
              └─ traceability ─┘   issues ──┘               ┌── GATE: TEST_CMD ──┐
                  (every ID has a case)                      │  Stop hook blocks  │
                                                             │  the turn if red   │
                                                             └────────┬───────────┘
                                                                      ▼
                                                  reviewer subagent vs the issue's Goal
                                                                      ▼
                                                       PR ─► merge ─► release gates
                                                                  (UAT, PERF, live, conformance)
```

**The point of the loop** is the last arrow: a merge is not the end. The thing that failed to catch a defect, or the requirement nobody had written down, is itself recorded and fed back into the design. That is what is meant by the harness building itself (section 7).

---

## 2. Where it is wired in

Every integration point, with the file, what it does, and when it fires. Nothing in this table is aspirational: each file exists on this branch.

### 2.1 Instructions the agent always sees

| File | What it integrates | Fires |
|---|---|---|
| [`CLAUDE.md`](../CLAUDE.md) | The rules that must hold with no skill running: **pipeline ownership** (one owner per artifact), **test authorship** (`/fix-issue` writes no tests; `/write-tests` does), issue format (`Goal:`, `Traces to:`, `Depends on:`), the working rules (plan first; show `TEST_CMD` output; run the `reviewer` before a PR; consult the advisor on hard calls), and the **four seams** every module must carry | Prepended to every request in the repository |

`CLAUDE.md` is deliberately small. Explanations live in the skills, loaded only when a skill runs; only rules that must hold for ad-hoc work stay in `CLAUDE.md`.

### 2.2 Settings and the verification gate

| File | What it integrates | Fires |
|---|---|---|
| [`.claude/settings.json`](../.claude/settings.json) | Sets `env.TEST_CMD = "./scripts/test.sh"`, `advisorModel = "opus"`, and registers one **Stop hook** | Loaded by Claude Code at session start |
| [`.claude/hooks/verify.sh`](../.claude/hooks/verify.sh) | The **verification gate**: on every attempt to end a turn it runs `TEST_CMD` and returns exit code 2 on failure, which feeds the last 100 lines of output back to the agent and keeps the turn going | Every time the agent tries to stop |
| [`scripts/test.sh`](../scripts/test.sh) | What `TEST_CMD` points at: the **fast tier** (`pytest -q -m "not integration and not live and not slow and not writtenahead"`). One portable string over a venv interpreter that lives at `.venv/Scripts/python` on Windows and `.venv/bin/python` elsewhere. With arguments it passes them straight to pytest (any other tier, or the honest full picture with no marker filter) | By the Stop hook, by `/fix-issue` and `/write-tests` step 3, and by hand |

The hook has three deliberate exceptions, so it does not punish ordinary work. All three were exercised for this document in a scratch git repository:

| Situation | `verify.sh` result | Evidence |
|---|---|---|
| Uncommitted changes, `TEST_CMD` fails | **exit 2**, prints *"Verification failed: '…' exited 1. Fix the failures below before finishing:"* plus the output | observed |
| Uncommitted changes, `TEST_CMD` passes | exit 0, turn may end | observed |
| Uncommitted changes, `TEST_CMD` empty | exit 0 with a warning that the gate is off | observed |
| Clean working tree (nothing to verify), even with a failing `TEST_CMD` | exit 0 | observed |

Claude Code itself caps consecutive blocks at 8 (stated in the hook's header), so a genuinely stuck loop cannot run forever.

### 2.3 The skills (the process, as code)

Each stage of the life cycle is owned by exactly one skill. Single ownership is what stops two stages producing the same artifact in incompatible shapes (`harness-adoption.md`, `README.md` "Single ownership").

| Skill | Stage | Owns | Harness integration inside it |
|---|---|---|---|
| [`detailed-design-generator`](../.claude/skills/detailed-design-generator/SKILL.md) | 1. Design | `FR-*`/`NFR-*`/`CT-*` IDs, `detailed-design.md` | Requires every requirement to be *independently testable as written*; defines the per-module **contract** (`CT-*`), which is what the contract suites later verify |
| [`create-test-plan`](../.claude/skills/create-test-plan/SKILL.md) | 2. Test plan | `TC-*` IDs, risk register, test-story sizing, `test-plan.md` | Risk-weights depth; derives **contract suites** and **blast-radius sets**; ends with a "confidence audit" (Phase 6) and runs [`scripts/check_traceability.py`](../.claude/skills/create-test-plan/scripts/check_traceability.py) on itself; states **what passing does not prove** |
| [`plan-to-issues`](../.claude/skills/plan-to-issues/SKILL.md) | 3. Backlog | GitHub issues, the dependency graph | Transcribes (never re-plans) stories and test stories; writes `Goal:`, `Traces to:`, `Depends on: #N`, and on test issues **`Written ahead of implementation: yes/no`** ([template](../.claude/skills/plan-to-issues/references/issue-templates.md)) |
| [`work-backlog`](../.claude/skills/work-backlog/SKILL.md) | 4. Dispatch | The claim labels | Runs `scripts/ready-issues.sh`, claims with `status:in-progress`, routes `type:story` to `/fix-issue` and `type:test` to `/write-tests`, releases to `status:in-review` or parks at `status:needs-attention` |
| [`fix-issue`](../.claude/skills/fix-issue/SKILL.md) | 5a. Implement | Implementation code | Plans against the **Goal** and the `TC-*` cases that will assert on the code; implements to the design's exact interface; **step 3 loops on `TEST_CMD` until green and shows the output**; step 4 invokes the `reviewer`; writes a regression test inline only for a defect fix with no `TC-*` coverage |
| [`write-tests`](../.claude/skills/write-tests/SKILL.md) | 5b. Test | Test code | Reads `Written ahead of implementation` to decide whether red is expected or a bug; one test per `TC-*`; honors the plan's isolation rung and oracle; checks order-independence; asks the reviewer *"would each test fail if the behavior it names were wrong?"* |
| [`harness-bootstrap`](../.claude/skills/harness-bootstrap/SKILL.md) | Method | (the co-evolution rule) | The four seams, the L0–L4 ladder, the metamorphic and flake-aware assertions, and the four-line discipline in section 7.2 |

### 2.4 The reviewer and the advisor

| File | Role |
|---|---|
| [`.claude/agents/reviewer.md`](../.claude/agents/reviewer.md) | An adversarial subagent restricted to `Read, Grep, Glob, Bash` (**no `Edit`, on purpose**) so it can only report. It reviews a diff against the issue's **Goal**, then acceptance criteria, then `Traces to`. For test diffs it asks whether each test would fail if the behavior were wrong. It is told to report only correctness gaps and to say plainly when it finds nothing. |
| `advisorModel: "opus"` in settings, and `CLAUDE.md` | A stronger model is consulted for ambiguous design calls, a bug that survived two fixes, and before declaring a large task done. |

### 2.5 Scripts that make the process mechanical

| Script | What it computes | Fails or skips when |
|---|---|---|
| [`scripts/ready-issues.sh`](../scripts/ready-issues.sh) | The set of open `type:story`/`type:test` issues whose `Depends on:` issues are all closed and that no one has claimed. Recomputed from GitHub on every call, stored nowhere. Output is JSON in issue-number order, a guarantee, because `/plan-to-issues` creates issues in topological order | Skips (with a reason on stderr) a malformed `Depends on:` line and anything labelled `status:needs-attention`, so a failing issue is not re-claimed in a loop |
| [`scripts/trace-issues.sh`](../scripts/trace-issues.sh) | Whether every `FR-*`/`TC-*` ID in the design and plan survived into the issue bodies, and every issue carries its required fields | Exit 1 on a gap, 2 if `gh`/`jq` are missing |
| [`check_traceability.py`](../.claude/skills/create-test-plan/scripts/check_traceability.py) | Requirements and contract clauses with no test case; IDs the plan invents; orphan and duplicate test cases | Exit 1 on any gap; `--contracts-only` is also a build gate (test plan §4.8 item 10) |

Between them: `check_traceability.py` proves **requirement → test**; `trace-issues.sh` proves **test → issue**; the PR and `Traces to:` carry **issue → code**. The whole chain `FR → TC → issue → PR` is checkable.

### 2.6 Python-side wiring

| File | Integration |
|---|---|
| [`pyproject.toml`](../pyproject.toml) | `--strict-markers` and the marker table (`integration`, `live`, `slow`, `browser`, `property`, `fuzz`, `e2e`, `contract`, `writtenahead`). A typo'd marker is an error, because **the marker is the tier selector** |
| [`requirements-dev.txt`](../requirements-dev.txt) | `pytest`, `pytest-randomly` (the suite runs **shuffled**: a test that only passes in file order has hidden shared state), `hypothesis`, `playwright` (the runtime libraries are `[project] dependencies` since ADR-36, so the dev install is `pip install -e . -r requirements-dev.txt`) |
| [`tests/conftest.py`](../tests/conftest.py) | The suite-wide guards in section 5.2 (network, environment, clock, hypothesis profiles), plus imports of all eleven modules that own a migration, so every store opens on a complete schema chain |
| [`.gitattributes`](../.gitattributes) | Pins `fixtures/**` to LF so content hashes survive a Windows checkout |
| [`.github/workflows/*.disabled`](../.github/workflows) | The CI variant, kept **inert on purpose**. All verification runs on the developer's machine; GitHub hosts the repository and the issue graph and runs nothing (`CLAUDE.md` "All work runs locally") |

---

## 3. The gates, and how each one is called

A **gate** here is a check that can stop work. They sit at different distances from the code, cheap and frequent at the near end, expensive and rare at the far end.

| # | Gate | Called by | When | Stops work when | Evidence on this branch |
|---|---|---|---|---|---|
| G1 | **Stop hook** (`verify.sh`) | Claude Code, automatically | Every attempt to end a turn with uncommitted changes | `TEST_CMD` exits non-zero | Behaviour table in 2.2, observed |
| G2 | **Fast tier** (`scripts/test.sh`) | G1; `/fix-issue` and `/write-tests` step 3; humans | Continuously | Any selected test fails | 2,899 of 4,305 tests selected; **2,889 passed**, 4 skipped, 4 failed + 2 errors (all six also fail on the pre-refactor commit, so nothing is caused by this branch); **509 s** on this sandbox |
| G3 | **Skill verify loop** | The agent, following `/fix-issue` §3 and `/write-tests` §3 | Before opening a PR | The agent cannot show passing output (or, for written-ahead tests, a *stated-reason* failure) | By construction; the PR must carry the output |
| G4 | **Adversarial review** | The agent, via the `reviewer` subagent (`/fix-issue` §4, `/write-tests` §4, `CLAUDE.md`) | Before a PR | A correctness gap against the Goal or acceptance criteria | 31 of the 168 commits visible in this clone are follow-ups titled `#N review: …` (an inference that these answer reviewer findings; the skills require exactly that) |
| G5 | **Advisor** | The agent, on triggers named in `CLAUDE.md` | Hard calls; before declaring a big task done | n/a (advice) | Settings key present |
| G6 | **Traceability** | `/create-test-plan` Phase 6; humans; build gate for `--contracts-only` | When the design or plan changes | A requirement or clause has no case, or the plan references an ID the design lacks | See 3.2 |
| G7 | **Issue-graph checks** | `ready-issues.sh` inside `/work-backlog`; `trace-issues.sh` after `/plan-to-issues` | Every dispatch; after issue creation | A dependency is open, a line is malformed, an ID was dropped | Scripts exist (need `gh`, not run here) |
| G8 | **Gates inside the suite** | Run by G2 like any test | Every run | See 3.3 | Part of the 2,889 |
| G9 | **Release-only gates** | Humans, at release or nightly | Not per commit | UAT sign-off, performance numbers, live conformance | Specified in `docs/uat/`, `docs/perf/`, test plan §4.7; **not run here** |

### 3.1 The fast tier is a deliberate choice, with one honest cost

`scripts/test.sh` runs everything that *should be green today* and excludes four classes:

* `integration`, `live`, `slow`: the heavier tiers, each with its own command in test-plan §4.7;
* **`writtenahead`**: tests that are red by design (section 4.3). Without this exclusion the Stop hook would block every turn from the first test story until the last implementing story, and people would learn to ignore it.

`pytest -q` with **no** marker filter is the honest full picture and is what a PR reports. On this branch that is 4,305 collected tests.

**Cost, stated plainly.** The hook runs the whole fast tier on any dirty working tree, including a docs-only edit. Test plan §4.7 budgets the tier at under 90 s; on this Linux sandbox it took 509 s. And because six tests fail on this machine regardless of the code, the gate is red here. Both facts come from environment drift (Python 3.13-only syntax in tests, `/tmp` being world-writable, a library-version-dependent recorded corpus), not from the application; they are the kind of finding section 7 feeds back.

### 3.2 Traceability: the correct invocation matters

Run exactly as the `README` shows, with the base design and plan only:

```
python .claude/skills/create-test-plan/scripts/check_traceability.py \
    --design docs/design/detailed-design.md --plan docs/design/test-plan.md
→ requirements: 489/489 traced   clauses: 330/330 traced   test cases: 975
→ FAIL: 2 IDs referenced by the plan but absent from the design: FR-INTEG-10, FR-ORCH-28
```

Run over the base design **and its three deltas** and their plans:

```
python .claude/skills/create-test-plan/scripts/check_traceability.py \
    --design docs/design/detailed-design.md docs/design/fix_gaps_detailed_design_plan.md \
             docs/design/jev_decision_engine_design_delta.md docs/design/closeout_design_delta.md \
    --plan   docs/design/test-plan.md docs/design/gap_fix_test_plan.md \
             docs/design/jev_test_plan.md docs/design/closeout_test_plan.md
→ requirements: 661/661 traced   clauses: 426/426 traced   test cases: 1,343
→ PASS (112 documented known gaps)
```

The two "unknown" IDs are defined in a delta (`closeout_design_delta.md` amends `FR-ORCH-28`). So the gate is green when pointed at the whole design, and the `README`'s single-pair command is now out of date. That is a small example of the harness's own documentation drifting, found by running it.

### 3.3 Gates that live inside the test suite

These are tests, so they run in G2, but each exists to **hold the process itself** rather than a feature:

| In-suite gate | File | What it forbids |
|---|---|---|
| Written-ahead registry | [`tests/unit/harness/test_harness.py`](../tests/unit/harness/test_harness.py) | A `writtenahead` test whose blocker has landed (so a P0 case cannot sit outside the gate forever); a marked test not in the registry; a registry entry naming a missing file; an unknown blocker kind |
| Corpus reproducibility | `tests/regression/test_corpora_are_reproducible.py` (runs `python -m harness.corpora.build --check`) | A hand-edited fixture, an edited generator not rebuilt, or a CRLF-mangled checkout. Observed: *"fixtures/ matches the generators"* |
| Baseline registry | `tests/regression/test_baseline_registry.py` | The registry drifting from test-plan §6.9: a golden-file failure would otherwise print a plausible reviewer who is not the one the plan names (it is drift detection, "green and not coverage") |
| Contract clause suites | `tests/contract/**` (1,750 tests) | A module changing a promise a named consumer relies on |
| Environment hygiene `TC-REG-10` | `tests/regression/test_reg_10_env_hygiene.py` + `conftest.py` hooks | Any test leaking a `HARNESS_*` variable |
| Migration chain pin | `COMPLETE_SCHEMA_VERSIONS` in `src/aeh/store/migrations.py`, asserted in `tests/contract/requires/test_req_store.py` | Opening a store on a truncated schema chain; a migration added without bumping its pin |
| Source censuses (`SEC-15`, write-set audits) | `tests/artifact/**`, `tests/support/sql_scan.py` | SQL built by string assembly; a write path outside the declared set; a second place that maps bands to points |
| Harness self-tests | `tests/unit/harness/` | The harness itself regressing (section 5.3) |

---

## 4. Why these gates give confidence in the code

Confidence is built by stacking checks that catch **different** classes of failure, so that no single blind spot is fatal. Here is the stack, what each layer rules out, and what it cannot.

### 4.1 Layer by layer

| Layer | Question it answers | Mechanism | Catches | Cannot catch |
|---|---|---|---|---|
| Design testability | Can this requirement be tested at all? | `FR-*` "independently testable as written"; `CT-*` contracts | Vague requirements before any code exists | A wrong requirement |
| Traceability | Is anything *untested*? | `check_traceability.py` (walks requirements, not cases, so a matrix that "looks complete" cannot hide a gap) | A requirement or clause with no case | A case that exists but asserts nothing |
| Written-ahead tests | Does the test fail *before* the code? | `writtenahead` + `require()` + registry | A test that was never seen to fail | — (it proves the red-to-green transition) |
| Contract suites | Is it still safe to depend on this module? | 330 base (426 with deltas) `CT-*` clauses, per-consumer `Requires` cases, double-conformance | A change that is correct locally but breaks a consumer | A consumer assumption nobody wrote down |
| Prohibition tests | Is a forbidden thing *impossible*? | Artifact assertions: import graphs, enumerated write sets, SQL-assembly census, prompt lints, rendered-HTML checks | The negative requirements (no numeral in a judge prompt, no path from absent evidence to a low band), which degrade no metric anyone watches | Behaviour outside the scanned shape |
| Fast tier on every dirty turn | Did this change break anything cheap to check? | G1 + G2 | Regressions within seconds to minutes | Anything only a heavier tier exercises |
| Isolation guards | Is a green result honest? | Socket guard, injected clock, seeded randomness, shuffled order, env snapshot | A test that passed because it reached the network, depended on order, or inherited a leaked setting | — |
| Adversarial review | Would a skeptic accept this against the Goal? | `reviewer` (read-only, different context from the author) | Misread requirements, weak assertions, scope creep, duplicated suites | A defect the reviewer shares the author's blind spot on |
| Release gates | Does the *assembled, real* system deliver? | UAT scripts, `PERF-10` on reference hardware, live conformance | What fixtures cannot: real handwriting, real latency, real model drift | — (these are the human and hardware gates) |

### 4.2 Three structural reasons the claim is credible

1. **The oracle is not the code.** The test plan names an oracle for every case (a golden file, a hand-computed constant, a property, a metamorphic relation) and refuses "verify the output is correct". Statistics reference values are hand-computed and committed, explicitly **not** produced by a library (§4.7), so a bug in a dependency cannot validate itself.
2. **Doubles are allowed in exactly one place.** The only model-boundary double is `RecordedFixtureProvider`, a **shipped** implementation keyed by a hash of the fully assembled request that raises rather than reaching the network (`CT-PROV-10`, `CT-PROV-15`). Everything else (SQLite, the blob store, the console) is real, because in this system the real thing is cheap. A passing test therefore exercised the real prompt-assembly path, and any prompt change fails loudly as `FixtureMissingError` instead of silently reusing a stale answer.
3. **A red check is never "fixed" by editing the check.** Test plan §4.10 and §6.9: a failing contract suite means a breaking change (major version, an argument against the clause, re-verification of every consumer) or a wrong clause; **18 safety-property clauses have no partial credit** and permanent `REG-CT-*` baselines; golden files name a reviewer and grounds for change. This is what stops the suite from eroding into "regenerate until green".

### 4.3 Worked evidence: the module-to-package refactor

The refactor under review is itself an example of the harness doing its job. Two commits, in this order:

1. `bb7dbd2` *"Make the source-reading tests package-aware before splitting modules"* changed **only tests**: `tests/support/source_tree.py` (read a module as one file or a package of files) and `tests/support/package_patching.py` (make `monkeypatch.setattr(aeh.<pkg>, …)` reach the package's own files). Its message records the proof: *"On the current one-file layout every changed test has the same outcome as on main (611 passed, the same 3 failed)"*.
2. `44b0e01` *"Split each aeh module into a package of smaller, related files"* then moved the code and re-pinned the `SEC-15` census.

Why the order matters: the source-reading tests would otherwise have gone **vacuous** (reading `src/aeh/judge.py` after it became a directory scans nothing and passes for the wrong reason). Hardening the gates first, proving them unchanged, then changing the code is the discipline the harness exists to enforce. The later equivalence check on this branch (identical pass and fail sets between the pre-refactor and post-refactor commits across 4,305 tests, plus an AST comparison of every function body) used the same suite as its instrument.

---

## 5. The test infrastructure and assets

### 5.1 Scale (measured on this branch)

| Asset | Size |
|---|---|
| Application source (`src/aeh/`, 20 packages) | ~70,000 lines |
| Test code (`tests/`) | ~197,000 lines in 627 test files; **2.8 lines of test per line of source** |
| Of which shared support library (`tests/support/`) | 52 files, ~18,000 lines |
| Collected tests | **4,305** (`pytest --collect-only`) |
| Generator and corpus code (`harness/`) | ~5,000 lines |
| Committed generated fixtures (`fixtures/`) | 1,237 files, 12 MB |
| Test cases in the plans | 1,343 `TC-*`, tracing 661 requirements and 426 contract clauses |

Tests by directory (each directory is a *level* in test-plan §4.1):

| Directory | Tests | Level |
|---|---|---|
| `tests/contract/` | 1,750 | Contract clause suites (`CT-*`) and `Requires` pairwise cases |
| `tests/unit/` | 1,107 | Pure functions and the harness's own self-tests |
| `tests/integration/` | 928 | Real SQLite, real neighbours, fixture provider |
| `tests/artifact/` | 217 | Static prohibition assertions |
| `tests/security/` | 124 | PII, loopback, parser, injection |
| `tests/regression/` | 51 | Golden baselines, corpus reproducibility |
| `tests/property/` | 44 | `hypothesis` properties and fuzz |
| `tests/e2e/` | 26 | Journeys over the assembled system |
| `tests/perf/`, `resilience/`, `uat/`, `smoke/`, `browser/` | 21 / 12 / 11 / 11 / 3 | Budgets, kill-and-resume, acceptance, smoke, real browser |

The marker, not the directory, selects a tier: contract 1,716 and integration 1,382 are marker counts that cross directories; 26 tests carry `writtenahead` today.

### 5.2 The support library (`tests/support/`), by job

| Job | Files (examples) | What it provides |
|---|---|---|
| **Honesty guards** | `guards.py`, `env_hygiene.py`, `clock.py` | A socket guard that raises **and records** every outbound attempt (so "no model call was made" is assertable even if a caller swallowed the exception); a `HARNESS_*` snapshot and restore around every test; `FrozenClock`, seeded randomness |
| **Observation doubles** | `store_spy.py`, `taxonomy.py`, `prov_contract.py` | A write-audit spy (a hook, not a store); a scripted provider that raises the real error taxonomy call by call |
| **Assembled worlds** | `e2e_world.py`, `pipe_world.py`, `console_world.py`, `orch_run.py`, `judge_run.py`, `det_vocabulary.py`, `run_scoped.py` | A real store, package, cohort, run and workers over a corpus, differing only at the model boundary. One drive code path is shared by every journey, "a second copy of the drive is a second place for it to be wrong" |
| **Vocabularies** | 14 `*_vocabulary.py` files (agg, calib, conform, console, det, extract, grade, integ, judge, review, stats, store, synth, …) | The assumed interface of each module, **named once**, transcribed from the design, because tests are written before the code exists and the design declares no signature for some surfaces |
| **Positive controls** | 7 `broken_*.py` files | Deliberately broken fixtures that prove each static rule *can* fail, "in both directions", so a scanner cannot rot into a rule that never fires |
| **Static scanners** | `import_graph.py`, `sql_scan.py`, `source_tree.py`, `doc_tables.py` | AST walkers (parse, not grep), so an f-string SQL fragment split across a `+` chain is still seen; a reader of the design's markdown tables as data |
| **The red-ahead seam** | `impl.py` | `require()`, `NotImplementedYet`, `WRITTEN_AHEAD_BLOCKERS`, `blocker_is_resolved` (section 5.4) |
| **Generators** | `fuzz_strategies.py`, `span_strategies.py`, `corpora.py`, `jev_corpora.py`, `roster.py` | `hypothesis` strategies (asserted before anything depends on them); corpus loaders; a synthetic roster plus the scan that must never find a real name |

### 5.3 The corpora and baselines (`harness/`, `fixtures/`)

| Asset | What it is | Reproducible how |
|---|---|---|
| `harness/corpora/*.py` | Generators: `synth` (350 submissions with known reference bands), `reference_package` (the 5-question, 15-criterion package), `dev_pipe` (3 submissions, escalation-shaped), `graphic`, `scan`, `stats`, `adv_inj` (injection twin pairs), `adv_pdf` + `pdf_writer.py` (malicious and malformed constructs, no third-party PDF library so digests are stable), `conform_set`, `jev`, `hand` | `python -m harness.corpora.build` writes `fixtures/`; **`--check` regenerates into a temp dir and diffs**; run as a test |
| `fixtures/F-*` | The generated corpora, content-addressed by sha256 | LF-pinned by `.gitattributes` |
| `fixtures/F-DEV-PIPE/recordings/` and the Jev sets | **Captured, not generated**: the model replies a complete run asks for | `python -m tests.support.pipe_world` re-records them |
| `fixtures/F-HAND/` | **A declaration only**: real handwriting is never committed (PII); `registry.json` states what it must contain and where a machine that has it keeps it | n/a |
| `fixtures/baselines/registry.json` | Which golden artifact, whose signature, on what grounds a change is accepted | `tests/regression/` |
| `harness/reference/metamorphic.skeleton.py` | Six metamorphic relations, kept as a **reference**, not wired in | n/a |
| `tools/openjev_small_shim/`, `tools/e4_openjev_small/run_gate.py` | A local decision-engine shim and the manual hardware gate (`PERF-17/18`) for the reference machine | Manual, on hardware |
| `docs/uat/`, `docs/perf/` | Human acceptance scripts and performance/air-gapped runbooks, whose headers must match test-plan rows (a test fails if a script drifts) | Manual, at release |

### 5.4 The written-ahead mechanism in detail

This is the piece that makes the harness safe to build before the code, so it is worth stating precisely.

* **The problem it solves** (`tests/support/impl.py` header): a module-level `from aeh.prov import …` in a test whose module does not exist yet raises a *collection error*, which looks identical whether the implementation is missing, the path is wrong, or the file has a typo, and which a later reader "fixes" by deleting the import.
* **`require("aeh.prov", …)`** imports **inside** the test body and, if the implementation is absent, raises `NotImplementedYet`, an `AssertionError` naming the module and the issue that will provide it. The test runs, fails for a *stated* reason, and **turns green the moment the implementation lands with no edit to the test**.
* **`@pytest.mark.writtenahead`** keeps such tests out of `TEST_CMD`, so the Stop hook stays green over the code that exists.
* **`WRITTEN_AHEAD_BLOCKERS`** is the table that stops this from becoming silent. Each entry maps an issue to *what the test is waiting on* in one of five forms: `module`, `path`, `symbol`, `symbols` (a conjunction), or `command` (an exit code), plus the tests to unmark. A gate test fails when a blocker resolves, **naming the tests to unmark**. The keying rule is spelled out in comments earned the hard way: key on the *implementation* name (e.g. `ContentAddressedBlobStore`), never on a Protocol the design already declares, "the same Protocol trap TS-56 measured".
* **State today:** 7 entries, 26 tests. At the start of the build every test story was in this state (test-plan §8.2: "every story below is written ahead"). The shrinking table is a literal progress bar for the build.
* **Unmark rule** (`CLAUDE.md`): when the implementing issue closes, remove the marker, **never the test**, and drop its registry entry.

### 5.5 The shape of a test run

A test starts under: the autouse **socket guard**, the **env snapshot**, `package_patching.install()`, a derandomized **hypothesis profile** (`default` 50 examples, `ci` 200, `nightly` 2,000 and not derandomized, the one tier whose job is to find new inputs), and **shuffled order** (`pytest-randomly`). It uses a real store in a per-test temp directory (which the store requires to be outside any world-writable folder). It ends with the env restored and the guard uninstalled. None of this is visible in an individual test, which is the point.

---

## 6. What caused each asset to exist

Every asset above answers a specific failure or constraint. This table is the causal record, with the source that states the cause.

| Asset | What caused it | Source |
|---|---|---|
| Socket guard (`guards.py`) | "Without the socket guard, half the P0 assertions in this plan ('and no model call is made') are unenforceable." It raises *and records* because a guard that only raises cannot tell "no call" from "call swallowed by `except Exception`" | test-plan §8.1; `guards.py` |
| `RecordedFixtureProvider` as a shipped class | The fast tier must need no live model and the ~23,000-call batch must not run per commit | `FR-CONFORM-07`, `CT-PROV-10/15`; test-plan §4.2 |
| Injected clock, seeded randomness, no `sleep` | Lease expiry, review windows and backoff cannot be tested by waiting; one sanctioned sleep (`TC-ORCH-09`, marker `slow`) | test-plan §4.6 |
| Shuffled order | "A suite that fails under shuffle has hidden shared state", a real defect in a system with a single writer thread and a work ledger | test-plan §4.6 |
| `writtenahead`, `require()`, the registry | Test stories land red before code (§8.2) **and** the Stop hook blocks on red; unmanaged, a P0 case could sit outside the gate indefinitely | `impl.py`; `scripts/test.sh` header |
| `scripts/test.sh` adding `and not writtenahead` | Test-plan §4.7's own string would block every turn until the last implementing story | `scripts/test.sh` comments |
| Corpus generators + `--check` | §8.1: corpora "generated from committed scripts so they are reproducible rather than archaeological"; a CRLF checkout changes every hash | `fixtures/README.md`; `build.py`; `.gitattributes` |
| `F-ADV-PDF` generated, never committed as binaries | Malicious PDFs should not live in the repo as files; a third-party writer would change digests on a routine dependency bump | `pdf_writer.py` header; test-plan §4.7 |
| `F-HAND` as a declaration only | Real handwriting is the one corpus with real student work (PII, Tier C) | `fixtures/README.md` |
| Benign twins in `F-ADV-INJ` | A defense claim needs proof the injection *changes nothing*: same band, same citation outcome, no lift in confidence | design-history v3.3.3 (R73) |
| `F-DEV-PIPE/recordings` | `M-PIPE` cases needed replies already on disk; a score request is keyed on the extracted evidence, so keys do not exist until a real run has produced them. Hence: drive once, keep what it recorded | `pipe_world.py` header (#435) |
| `pipe_world.pinned_uuid4` | Measured: 265 of 280 recordings were identical across two drives; the 15 that moved all contained an opaque submission id minted per ingest. Pinning the mint makes the corpus self-contained | `pipe_world.py` header |
| Contract suites written first (TS-58…TS-82) | "A contract is a specification that exists before the code": the module is then built against a red clause suite instead of prose that gets interpreted | test-plan §8.1/§8.2 |
| `--contracts-only` as a build gate | Contracts erode by accretion until "a green clause suite is worse than none" | test-plan §4.8 item 10 (RISK-40) |
| Prohibition (artifact) tests | The negative requirements degrade no metric anyone watches, so scattering them across modules is how they get half-covered | test-plan §4.1; HLD §12 |
| `sql_scan.py` / `SEC-15` | The behavioural probe cannot see SQL assembled by an f-string inside a declared statement; the scan parses source instead | `sql_scan.py` header |
| `env_hygiene.py` / `TC-REG-10` | Worlds wrote `HARNESS_*` knobs into `os.environ` and never restored them, which is "how TC-INGEST-02/25/28/39, ADV-07 and TC-ORCH-36 came to fail by test order" and why `test_ct_ingest_v4_halting` flaked | `test_reg_10_env_hygiene.py` header (#537) |
| `broken_*` fixtures | A static rule that has never failed is not known to work; each rule is proven in both directions | `broken_*` headers |
| `*_vocabulary.py` | Tests written ahead need an interface the design sometimes does not declare; naming it once means one place to change if the implementation differs | `extract_vocabulary.py`, `blast` test docstring |
| `COMPLETE_SCHEMA_VERSIONS` | An open on a truncated migration chain builds the base schema and the failure surfaces later as `no such column: parent_version_id`, far from its cause (#46, #94, #208, #234) | `CLAUDE.md` "Store opens require the full migration chain" |
| One SQL text per statement name (`StatementConflictError`) | Two modules registering different SQL under one name resolved to whichever imported last (TC-REG-07 was one such crash) | commit `34b774a` (#511) |
| `source_tree.py`, `package_patching.py` | The module-to-package refactor would otherwise make source-reading tests vacuous and monkeypatches miss callers | commit `bb7dbd2` |
| Baseline registry (`TC-REG-01…06`) | "Snapshot testing degrades into regenerate-until-green unless the reviewer and the grounds are named" | test-plan §6.9 |
| UAT scripts, `PERF-10`, `tools/e4_*` | Some facts cannot be tested in CI: whether a teacher finds a 30-minute queue worth it; whether an overnight batch completes on a 32 GB machine. "A green CI pipeline is no evidence" | `docs/uat/README.md`; README "Deployment profiles" |
| Disabled CI workflows | One place work can start; subscription billing instead of API billing; nothing runs on a push to a public repo | `.github/workflows/*.disabled` header; README "Why local-only" |

---

## 7. How the harness builds itself

"Builds itself" does **not** mean no human decides anything. It means that **each stage's output is the next stage's machine-readable input, and every failure leaves a record that becomes the next cycle's input.** The people decide; the process carries the state.

### 7.1 Seven self-feeding mechanisms

1. **IDs are the spine.** `/detailed-design-generator` mints `FR-*`/`NFR-*`/`CT-*`; `/create-test-plan` mints `TC-*` against them; `/plan-to-issues` copies both into issue bodies; `trace-issues.sh` verifies the copy. No stage invents another stage's identifiers, so a downstream stage can *read* the upstream artifact instead of being told about it.
2. **The graph schedules the work.** Readiness is `Depends on: #N` lines plus labels, recomputed on every `ready-issues.sh` call from GitHub's own state; closing a dependency makes its dependents eligible with no coordinator. `/work-backlog` plus `/goal` loops it: pick, claim, implement, release, repeat, bounded by a turn limit.
3. **Tests lead the code.** Contract and test stories depend only on test infrastructure, so they are scheduled *before* their module. Red tests wait in the registry; the code lands; the registry fires; the marker is removed. The suite grows to cover a module before the module exists.
4. **The co-evolution rule** (`CLAUDE.md`, `harness-bootstrap`): every new capability ships with its case; every new external dependency ships with its deterministic seam; every environment-sensitive constant becomes a knob in the same pass; every bug found later becomes a permanent case. Because "the agent that wrote the code is the wrong one to judge its own tests", the pair is merged together but authored separately.
5. **Disclosure is mandatory.** The reviewer and the test authors are told to report gaps they cannot fix in scope ("known and reported, not fixed"). Those disclosures land in PR bodies and a findings register.
6. **Findings become design.** `docs/findings-register.md` (compiled by the `/work-backlog` loop from reviewer disclosures) seeds defect stories. `docs/design-gap-analysis.md` is a systematic sweep across **all PRs, all issues, the live written-ahead registry, a DDL-vs-real-schema diff and a cross-reference of every ID against `src/` and `tests/`**. Its output feeds design deltas.
7. **Deltas close the loop.** Each delta is a design document, a matching test plan, and issues, produced by the *same* skills:

   | Delta | Trigger | Test plan |
   |---|---|---|
   | `fix_gaps_detailed_design_plan.md` | The gap analysis (e.g. GAP-06: no build system, scripts or dependency declarations) | `gap_fix_test_plan.md` |
   | `jev_decision_engine_design_delta.md` | A new capability (a decision engine) | `jev_test_plan.md` |
   | `closeout_design_delta.md` | A close-out of parked issues and merged-PR disclosures; its own header cites a classified full run (*"40 failed, 3961 passed"*) and the *"close-out test stories each found a real defect against a clause that already exists and wrote its case red, under `writtenahead`"* | `closeout_test_plan.md` |

   `check_traceability.py` over all eight documents passes (3.2), which is the proof that the deltas kept the chain intact.

### 7.2 One concrete trip around the loop (`#511`)

Visible in this clone's history:

1. A test (`TC-REG-07`) crashed because two modules had registered different SQL under one statement name.
2. It became issue **#511**, with a `Goal:` and `Traces to:` (`FR-STORE-16`).
3. `34b774a` **"Fixes #511: one SQL text per statement name, refused at import"** changed 9 source files and 1 test file in the same change: the registry now raises `StatementConflictError` naming both modules; eleven names were renamed on the minority side; no SQL text changed.
4. `32bae11` **"#511 review: a conflicting setdefault raises too"** is the reviewer-driven follow-up: a hole the first patch left.
5. `82ad185` **"Merge pull request #558"** landed it. Several later commits are titled *"Re-pin the SEC-15 census after rebasing onto main"* (14 such re-pin commits are visible): the census ratchet moved with the code.
6. The same defect class is now covered permanently by `tests/regression/test_statement_registry_resolution.py`.

The commit trailers show the author as an agent (`Co-Authored-By: Claude …`), consistent with the process being run by the skills described above.

### 7.3 The harness tests itself

* **`tests/unit/harness/`** tests the guard, clock, spy, fixture binding and the registry rules. The header says why: "shipping the socket guard untested would leave the one component every 'and no model call is made' assertion rests on unverified."
* **Positive controls** (`broken_*`) prove each static rule can fail.
* **The registry gate** fails when it is stale in either direction (a resolved blocker left in place; a marked test not registered).
* **Generators are asserted before anything depends on them** (`span_strategies.py`'s header).

---

## 8. Honest limits

Written the way the test plan writes its own (§7.3): what is *not* in place, so no one over-trusts the stack.

| Item | State |
|---|---|
| **Mutation testing** | Specified (test-plan §4.8 item 8: ≥ 85 % on four pure modules) and recommended in `harness-adoption.md` §5b, but **no mutation tooling is installed or wired**. The "would this test fail if the behavior were wrong?" check is the reviewer's judgment, not a measurement |
| **`harness.blast_radius`** | Cases `TC-BLAST-01/02` are written ahead and registered, but the module **does not exist and no story builds it**. The blast-radius command in test-plan §4.7 therefore cannot run |
| **The bug-sweep workflow** | `harness-adoption.md` §5a proposes adapting the kit's two-lens adversarial verify panel; it is **not in the repository** |
| **CI** | Disabled by design. Every gate runs only where a developer or agent runs it. A contributor who skips the session skips the Stop hook |
| **The gate's runtime and health on a fresh machine** | 509 s against a 90 s budget, and six tests fail here independent of the code (section 3.1). The Stop hook would block a dirty-tree turn on this machine until that is fixed |
| **Traceability command in `README`** | Lists only the base design and plan, which fails (3.2); the multi-document form passes |
| **Release gates** | UAT, `PERF-10`, live conformance and the air-gapped run are manual or nightly and were **not** run for this document |
| **What passing proves** | Per test-plan §7.2/§7.3: that the system meets its design on synthetic and recorded inputs, *not* that grading is accurate on real handwriting; grading quality (`NFR-SYS-08`) and any absolute κ are explicitly **not** release gates |
| **History** | This clone shows 168 commits from 28 September 2026; the earlier build is documented (e.g. the gap analysis counts 173 PRs and 178 issues by 14 September) but not visible in git here, so the causal links in section 6 for early assets rest on the documents and code comments, not on commit archaeology |

---

## 9. Reproduce the evidence

All commands are from the repository root with the project's venv (Python 3.13 for the tests) and `TMPDIR` set to a private folder (the store refuses `/tmp`).

```bash
# The gate, as the Stop hook runs it
./scripts/test.sh

# The honest full picture (no marker filter) and the tier counts
pytest -q --collect-only                       # 4,305 collected
pytest -q --collect-only -m contract           # 1,716
pytest -q --collect-only -m writtenahead       # 26

# Traceability over the whole design (passes) and over the base pair alone (fails)
python .claude/skills/create-test-plan/scripts/check_traceability.py \
  --design docs/design --plan docs/design                       # PASS: 661/661, 426/426
python .claude/skills/create-test-plan/scripts/check_traceability.py \
  --design docs/design/detailed-design.md --plan docs/design/test-plan.md   # FAIL: 2 unknown IDs

# Corpora match their generators
python -m harness.corpora.build --check        # "fixtures/ matches the generators"

# The Stop hook's behaviour, in a throw-away repo
S=$(mktemp -d ~/hooktest.XXXX); cd "$S"; git init -q; git commit -q --allow-empty -m init; echo x > f
TEST_CMD='exit 1' bash <repo>/.claude/hooks/verify.sh; echo "exit=$?"     # exit=2, with the message
```

---

## 10. One-paragraph summary

The harness is integrated at **every stage of the life cycle** rather than at the end: it shapes the design (testable requirements, contracts, four built-in seams), is derived from it (a traceable, risk-weighted plan, proven complete by script), becomes the backlog (paired story and test issues in a dependency graph), leads the code (tests written red, tracked in a registry that fires when the code arrives), polices every turn (a Stop hook that runs the fast tier, a read-only adversarial reviewer measured against a one-sentence goal), guards its own honesty (socket, clock, environment and order guards; positive controls; self-tests), and **feeds its failures back into the design** (disclosures, gap analyses, deltas). It was designed to build itself because each artifact is the machine-readable input of the next, and because the process makes silence expensive: a test that cannot fail, a blocker that quietly resolves, a baseline changed without a named reviewer, or a contract that erodes all fail a gate. What it does not yet do (mutation scoring, the blast-radius command, CI, and a fast gate on a fresh machine) is listed in section 8.
