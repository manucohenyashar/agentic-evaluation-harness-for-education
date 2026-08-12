# Test Plan Template

The output structure. Follows the IEEE 829 / ISTQB shape, reorganized so the document reads
as an argument for correctness rather than a list of activities: understand the system,
rank the risk, decide the strategy, specify the tests, prove the coverage, state the
residual risk.

Keep the section numbering stable - the traceability checker, `/plan-to-issues`, and anyone
diffing two versions of the plan all rely on it. Drop a section only when it genuinely
doesn't apply, and leave a one-line note saying why rather than deleting the heading
silently.

---

````markdown
# Test Plan: <System Name>

Source design: <file(s) + version/date>
Version: 1.0    Date: <date>    Status: Draft
Author: <who/what generated this>

## 1. Scope and the confidence claim

**In scope**: what this plan covers (modules, versions, interfaces).
**Out of scope**: what it deliberately doesn't, and where that's covered instead.

**Confidence claim** - one paragraph, stated plainly so it can be argued with:

> If every test case in this plan passes, we have evidence that <specific claim about what
> is verified>. We do not have evidence about <the honest remainder>. Section 7 details
> both.

Writing this first, before the test cases, keeps the plan pointed at a goal. Revise it at
the end once the cases exist.

## 2. System under test

### 2.1 Module inventory and testability

| Module ID | Responsibility | Interfaces | Depends on | Testable in isolation? | Notes |
|---|---|---|---|---|---|

"Testable in isolation" is a design finding as much as a test-planning one: a module that
can't be tested without three real dependencies has a seam problem, and saying so here is
often the most useful sentence in the document.

### 2.2 Requirements inventory

Every `FR-*` / `NFR-*` from the design, with the module that owns it. If the design has no
ID scheme, assign one here and note the assignment - the traceability matrix needs stable
handles.

### 2.3 Testability gaps and open questions

| ID | Requirement / area | Problem | Needed to make it testable |
|---|---|---|---|
| Q-01 | NFR-ING-02 "ingestion should be fast" | No quantified target | A latency/throughput number and the load it applies at |

Requirements that can't be tested as written belong here, not silently in the gaps section
at the end. Each one is a question for the design author.

## 3. Risk register and depth allocation

| Risk ID | Module / Req | Failure, stated concretely | Blast radius | Reversible? | Detectable in prod? | Severity | Depth assigned |
|---|---|---|---|---|---|---|---|
| RISK-01 | M-SCORE / FR-SCORE-03 | Returns a plausible but wrong score; no signal it's wrong | Student's recorded grade | No | No | Critical | Unit + integration (real) + adversarial + statistical eval + regression baseline |

Use `RISK-nn` for risk IDs rather than `R-nn`, since some designs use `R1`/`R12` for
requirements and the traceability checker would otherwise confuse the two.

Severity drives depth. State the mapping being used (e.g. Critical → all levels plus
adversarial and property tests; Low → smoke coverage only) so the allocation is a visible
decision rather than an accident.

## 4. Test strategy

### 4.1 Levels and suite shape

| Level | Applies | Rationale (tied to this design) | Approx. share |
|---|---|---|---|
| Unit | Yes | ... | 60% |
| Integration (doubles) | Yes | ... | 15% |
| Integration (real) | Yes | ... | 15% |
| System / E2E | Yes | 3 journeys only, from design §4.2 | 5% |
| Performance | Yes | NFR-* quantify latency and throughput | 2% |
| Security / adversarial | Yes | Untrusted input reaches the model | 3% |

State the shape you chose and why it fits this system - a pyramid for logic-heavy code, a
fatter integration middle for orchestration-heavy code.

### 4.2 Mock vs real policy

The isolation ladder (rungs 0-4), where doubles are permitted, and the rule that every
mocked dependency has a named companion test against the real thing.

| Dependency | Doubled as | Used in | Companion real test | Contract test |
|---|---|---|---|---|
| Model server | Recorded-response fixture | TC-SCORE-01..12 | TC-SCORE-40 (live model, nightly) | n/a |
| Storage | In-memory fake | TC-ING-03..09 | TC-ING-20 (containerized real) | Conformance suite CS-01 |

A row with an empty companion column is a gap - either add one or record it in §7.

### 4.3 Test oracles

Per test class, how correctness is determined: exact value, invariant, differential,
metamorphic, golden file, statistical, human. Name the oracle for anything that isn't an
exact expected value, and say why an exact value isn't available.

### 4.4 Test data

Fixtures and factories, synthetic vs anonymized real data, the adversarial corpus, the
held-out evaluation set (and how it's kept held out), data volumes for performance runs,
and the handling rules for any regulated or personal data.

### 4.5 Environments

| Environment | Purpose | Composition | Differences from production that matter |
|---|---|---|---|

### 4.6 Determinism and flake policy

How clock, randomness, ordering, concurrency, and network are controlled; how
nondeterministic components are pinned (seed, model version, temperature); what happens
when a test flakes - the quarantine rule and the deadline for fixing or deleting it. A
retry-until-green policy stated out loud is at least honest; an unstated one is how suites
die.

### 4.7 Tooling and execution

Frameworks and runners, fuzzers, load tools, coverage and mutation tooling, and the exact
commands for each suite. Match what the repo already uses.

| Suite | Command | Runs in CI | Duration budget |
|---|---|---|---|
| Unit | `<TEST_CMD> -- unit` | every push | < 60s |
| Integration (real) | `<cmd>` | every push | < 8 min |
| Fuzz campaign | `<cmd>` | nightly | 30 min |

### 4.8 Entry and exit criteria

**Entry**: what must be true before testing starts.
**Exit / release gate**: concrete and checkable, e.g. 100% of P0 cases pass; ≥95% of P1;
no open Critical or High defect; performance suite meets every NFR threshold; adversarial
suite shows no silent-wrongness case; mutation score on Critical modules ≥ X%.

## 5. Test cases

Grouped by module, then by level. Every case uses this shape - the fields exist so that
someone can implement the test without going back to the design:

### 5.N Module: <Name> (`<ModuleID>`)

#### TC-<ModuleID>-01 - <behavior being verified, stated as a claim>

| Field | Value |
|---|---|
| Requirements | FR-<ModuleID>-01 |
| Risk | RISK-03 (High) |
| Level / type | Unit |
| Technique | Boundary value analysis |
| Isolation | Rung 0 - clock stubbed, no I/O |
| Priority | P0 |

**Preconditions / fixtures**: <exact state and data the test starts from>

**Steps**:
1. <concrete action with concrete values>
2. ...

**Oracle**: <how correctness is determined - exact expected value, invariant, etc.>

**Expected result**: <the specific, checkable outcome, including error type/message/code
where relevant>

**Variants**: <edge and negative cases derived from the same requirement, as a short list
rather than separate near-duplicate case blocks>

**Automatable**: yes - `<suite/file it belongs in>`

For dense tables of simple cases (a partition sweep, a state-transition matrix), a table is
clearer than repeated blocks - keep one row per case with the same columns:

| TC ID | Req | Input | Isolation | Expected | Oracle | Pri |
|---|---|---|---|---|---|---|

Use the full block form for anything with non-trivial setup or a non-obvious oracle, and
the table form for sweeps. Both are fine; mixing them deliberately keeps the document
readable.

## 6. Cross-cutting suites

One subsection each, omitting with a one-line justification any that don't apply:

### 6.1 Smoke suite
The checks, their order, the total time budget, and what a failure blocks.

### 6.2 System / E2E journeys
2-5 journeys traced to the design's key flows, each with the failure-path variant.

### 6.3 User acceptance tests
| UAT ID | Business goal | Role | Scenario (Given/When/Then) | Data | Sign-off criterion |
|---|---|---|---|---|---|

### 6.4 Performance scenarios
| Perf ID | NFR | Load profile | Duration | Dataset | Metric | Threshold | Environment |
|---|---|---|---|---|---|---|---|

### 6.5 Security tests
| Sec ID | Trust boundary | Threat (STRIDE / OWASP) | Probe | Expected defense |
|---|---|---|---|---|

### 6.6 Adversarial tests
| Adv ID | Requirement being attacked | Attacker goal | Input | Pass = correct handling **or** visible failure |
|---|---|---|---|---|

### 6.7 Fuzz and property-based tests
| ID | Target | Generator / corpus | Invariant or crash criterion | Examples per run | Seed policy |
|---|---|---|---|---|---|

### 6.8 Resilience / failure injection
| ID | Injected failure | Where | Promised behavior (design ref) | Assertion |
|---|---|---|---|---|

### 6.9 Regression and baselines
The policy, the baseline artifacts, and who reviews baseline changes.

### 6.10 Observability tests
| ID | Promised signal | Trigger | Assertion |
|---|---|---|---|

## 7. Traceability, coverage and residual risk

### 7.1 Requirements traceability matrix

Built by walking every requirement from §2.2 in order - not by walking the test cases.

| Requirement ID | Requirement (short) | Module | Test Case ID(s) | Level(s) | Priority | Status |
|---|---|---|---|---|---|---|
| FR-AUTH-01 | Issue JWT on valid login | M-AUTH | TC-AUTH-01, TC-AUTH-02, TC-AUTH-15 | Unit, Integration(real) | P0 | Not run |

Verify mechanically:
`python .claude/skills/create-test-plan/scripts/check_traceability.py --design <design> --plan <this file>`

### 7.2 What passing this suite proves
The confidence claim from §1, now specific: which requirements are verified, at which
isolation level, with which oracle strength.

### 7.3 What it does not prove
Untested requirements, conditions not reproducible in test (production traffic shape, real
hardware, true scale), assumptions baked into every double, requirements covered only by
weak oracles, and anything verified only at rung 0.

### 7.4 Known gaps and compensating controls

| Gap | Why untestable | Compensating control |
|---|---|---|
| NFR-SYS-02: 8-hour batch on production hardware | No target hardware in CI | Scaled 1/10 run in CI + one manual full run per release + runtime duration alerting |

A gap with a compensating control is a managed risk. A gap without one is an accepted risk
and should say so in those words, so that accepting it is a decision someone made.

## 8. Execution plan and backlog handoff

### 8.1 Sequencing
What gets built first - normally the fixtures and harness, then P0 unit, then integration,
then the rest. Note anything that blocks: environments to provision, data to obtain,
credentials to arrange.

### 8.2 Test stories

Sized so one story is one reviewable PR. Consumed by `/plan-to-issues` → `type:test`
issues → `/write-tests`.

| Story | Covers | Depends on | Written ahead of implementation? |
|---|---|---|---|
| Unit tests for score aggregation | TC-SCORE-01, TC-SCORE-02, … TC-SCORE-09 | Implement score aggregation | no |
| Property tests for the response parser | TC-PARSE-20, TC-PARSE-21, TC-PARSE-22 | — | yes — written against the design's interface |

`/plan-to-issues` transcribes this table directly, so the column names and values matter:

- **Covers** lists TC IDs **explicitly**. Ranges like `TC-SCORE-01..09` are fine in prose
  elsewhere but not here, because they become the issue's `Traces to:` line and
  `scripts/trace-issues.sh` matches IDs literally — a range reads as two IDs and the seven
  in between look uncovered.
- **Depends on** becomes the literal `Depends on: #N` line once issue numbers exist. Use
  `—` for none rather than the word "none".
- **Written ahead of implementation?** is `yes`/`no`, and tells `/write-tests` whether a red
  suite is expected or a bug. A `yes` story must have no dependency — that is what makes it
  schedulable immediately and lets the test track run in parallel with the code track.

## 9. Revision history

| Version | Date | Change | Author |
|---|---|---|---|
````
