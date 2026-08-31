---
name: create-test-plan
description: Turns a detailed design / low-level design document into a comprehensive, traceable test plan - test strategy, risk-weighted coverage, and fully specified test cases across unit, integration (mocked and against real modules), contract, smoke, system/E2E, user acceptance, performance, security, adversarial, fuzz/property-based, resilience, and regression testing, tied to a requirements traceability matrix and an explicit statement of what passing the suite does and does not prove. Where the design defines module contracts (CT-* clauses), it also produces the contract-verification suite that fails when a module breaks a promise its callers depend on, plus the per-consumer integration tests and blast-radius regression sets derived from them. Use whenever the user has a detailed design, LLD, module spec, architecture doc, or requirements document and wants tests planned for it - triggers include "write a test plan", "how should we test this", "what tests do we need", "test strategy", "QA plan", "verification plan", "test the module contracts", "make sure changes don't break other modules", "make sure this implementation is correct", or asking for test coverage of a design. Also use before implementation starts when the user wants tests specified ahead of code (TDD), and when an existing test plan needs to be deepened or audited for gaps.
---

# Create Test Plan

A test plan is an argument. It claims: *if every test in here passes, the implementation
satisfies the design.* Most test plans fail as arguments - they list activities ("unit test
the modules, then do integration testing") without ever showing that the activities, taken
together, would actually catch a violation of the design. A reader can't tell what passing
proves.

This skill produces a plan that holds up as an argument. Three properties do that work:

- **Traceable** - every requirement in the design maps to named test cases, and every test
  case maps back to a requirement. Gaps are visible instead of implied.
- **Risk-weighted** - depth is spent where a defect would actually hurt. Uniform coverage
  is a way of not deciding, and it reliably under-tests the dangerous parts while
  over-testing the trivial ones.
- **Honest** - it ends by stating what passing does *not* prove. A plan that claims total
  confidence is the one that gets trusted right up until the incident.

A plan built only from `FR-*`/`NFR-*` makes a narrower argument than it appears to. It proves
each module does its job **today**; it does not prove that a module still keeps the promises its
callers were built on **tomorrow**. That second claim is what a module contract carries, and where
the design defines one — `CT-*` clauses, per `/detailed-design-generator` Phase 2b — verifying it is
part of this skill's job, not an optional extra tier. The distinction runs through every phase below:

| | `FR-*` / `NFR-*` cases | `CT-*` cases |
|---|---|---|
| Prove | the module was built right | the module is still safe to depend on |
| Fail when | the module is wrong | the module is *different* in a way a named consumer relied on |
| Run | while the module is being built | on every change to that module, forever |
| Derived from | a requirement | a clause, plus the `Consumers` and `Requires` tables around it |

If the design has no `CT-*` scheme, say so once and plan from the interfaces and invariants
instead — but check first, because a contract that exists and goes unverified is the most
expensive kind to have written.

Read the reference files as you reach the phase that needs them, not all at once:

| File | Read it during |
|---|---|
| `references/test-design-techniques.md` | Phase 3 - deriving concrete cases from a requirement |
| `references/test-types-catalog.md` | Phase 2 and 4 - choosing levels, mock-vs-real policy, per-type case design |
| `references/test-plan-template.md` | Phase 5 - assembling the document |
| `references/quality-bar.md` | Phase 6 - self-check before delivery |

## Phase 0 - Read the design, all of it

Locate the design input: a path in `$ARGUMENTS`, a folder (recurse into it - designs are
often split across files), an attached document, or a link (fetch it). Read every document
fully before planning anything. Planning tests from a skim produces a plan that tests the
headings.

While reading, build the following inventory. You are extracting the things that can be
wrong, which is a different reading than the one you'd do to implement it:

- **Modules** and their IDs, responsibilities, and stated non-responsibilities
- **Requirements** - every `FR-*` / `NFR-*` (or whatever ID scheme the doc uses; if it has
  none, assign one and say so, because the traceability matrix needs stable handles)
- **Contract clauses** - every `CT-*`, with three things copied verbatim, because all three
  become test structure:
  - the **clause kind** (`surface`, `data`, `behaviour`, `error`, `state`, `perf`, `config`,
    `observe`, `security`) — it determines the technique, and Phase 3 has a recipe per kind
  - the **`Consumers`** column — that is the blast radius, already computed. It tells you which
    integration suites re-run when this module changes, so you never have to guess at it
  - the **`Requires`** tables — each row is a *specific pair* of modules and a *specific clause*
    one relies on from the other. Each row is an integration test with its subject already named,
    which is the rarest thing in test planning and should not be wasted
- **Non-promise clauses** — clauses stating something is deliberately *not* guaranteed
  ("iteration order is unspecified", "output is not reproducible", "`None` means not measured").
  These are the highest-value clauses in the document and the ones a plan skips by reflex.
  A non-promise is tested by proving **no consumer depends on it** — see Phase 3.
- **Interfaces** - signatures, endpoints, schemas, status/error codes. These are the
  contracts tests assert against, so copy the actual parameter names and types rather than
  paraphrasing.
- **Data structures, invariants and state models** - state machines are a gift: legal and
  illegal transitions are test cases you can enumerate mechanically
- **Data flows**, especially anything asynchronous, batched, retried, or eventually
  consistent
- **Dependency graph** - who calls whom, sync vs async, shared stores. This determines what
  can be tested in isolation and what needs a real counterpart.
- **Failure modes and resilience behavior** the design promises (retries, timeouts,
  idempotency, degradation)
- **Quantified NFRs** - latency, throughput, capacity, availability. Unquantified ones
  ("should be fast") are untestable as written; flag them rather than inventing a number.
- **Gaps and ambiguities** - anything you can't test because the design doesn't say what
  correct looks like. Collect these; they go in the plan's open-questions section and are
  often the most valuable output, because an untestable requirement is usually an
  underspecified one.

Note the tech stack and the existing test setup if there is a codebase: framework, fixture
conventions, `TEST_CMD` in `.claude/settings.json`. A plan that proposes a second test
framework alongside the one already in use will not get implemented.

**Scope check.** If the design covers more than roughly 8 modules, produce Phases 1-2 (risk
register and strategy) and show them before writing out hundreds of test cases. Test-case
detail is expensive to produce and expensive to redirect; strategy is cheap to correct.

## Phase 1 - Risk analysis, which decides where depth goes

For each module, and for individual requirements where they differ sharply from their
module, score:

- **Blast radius** - what else breaks or is corrupted when this is wrong
- **Reversibility** - can the damage be undone? Irreversible actions (money moved, data
  deleted, a grade written to a student record, an email sent) rank above anything
  recoverable
- **Detectability** - would a defect here be obvious in production, or silent? Silent
  wrongness - a scoring function that returns plausible-looking wrong numbers - is the most
  dangerous category and the one most worth heavy testing
- **Complexity / novelty** - branch-heavy logic, concurrency, new algorithms, anything
  where the design itself expresses uncertainty
- **Churn** - code expected to change often needs regression protection more than stable
  code

Produce a risk register: `Risk ID | Module/Requirement | Failure imagined concretely | Blast
radius | Reversibility | Detectability | Severity (Critical/High/Medium/Low) | Test depth
assigned`. Write the failure as a specific scenario, not a category - "OCR silently returns
empty text for a legible page and the student is scored zero" beats "OCR errors".

Then allocate depth explicitly, and say so in the plan:

- **Critical/High** - multiple levels (unit + integration + system), negative and boundary
  cases, adversarial and fuzz where inputs are attacker- or user-controlled, and an
  explicit regression case once a defect is found
- **Medium** - unit coverage of the logic plus one integration path
- **Low** - covered incidentally by smoke or a single happy-path case; say that it's
  deliberate rather than leaving it looking like an oversight

This register is what makes the plan defensible when someone asks "why so many tests here
and so few there".

**Contracts make two of these columns cheap and one of them mandatory.**

- **Blast radius stops being a judgement call.** A clause's `Consumers` column is the answer,
  already computed by the design. Use it literally — "`CT-STORE-02` is consumed by 13 modules" is
  a better severity input than any adjective. A contract register (if the design has one) ranks
  the modules by consumer count; the top of that list is where depth goes.
- **Detectability is usually *bad* for contract violations, which is the whole point.** A broken
  `FR-*` typically shows up as a failing feature. A broken `CT-*` shows up as a *neighbour*
  misbehaving, weeks later, in a module nobody changed. Score contract clauses as low-detectability
  by default and make the plan say why.
- **Clauses the design flags as safety properties are Critical, not negotiable.** Where the design
  marks a set of clauses as structural mitigations — the ones whose violation "degrades no metric
  anyone is watching" — every one of them gets a case at more than one rung plus an explicit
  regression entry. These are exactly the clauses that a plausible-looking refactor removes and
  every functional test survives.

Add a `Clause` column to the register where a risk is contract-shaped, so the depth allocation
points at the clause rather than at the module in general.

## Phase 2 - Test strategy

Write the strategy *for this system*, deriving each choice from something in the design.
Generic strategy sections are the tell of a plan nobody will follow. Consult
`references/test-types-catalog.md` here.

Decide and justify:

1. **Which levels apply and the shape of the suite.** The classic pyramid (many unit, fewer
   integration, fewest E2E) is a good default for logic-heavy systems, but a system that is
   mostly orchestration between services gets most of its value from integration tests and a
   thin unit layer. Derive the shape from the design's coupling profile and state it.
2. **Mock-vs-real policy** - the decision that most often silently invalidates a suite.
   State where test doubles are allowed, and pair every mocked dependency with a named test
   that exercises the real thing. See the isolation ladder in the catalog.
3. **Test oracles** - for each class of test, how does the test know the right answer?
   Exact expected value, invariant/property, differential comparison against a reference,
   metamorphic relation, golden file, or human judgment. Any test case whose oracle is
   "verify the output is correct" is not yet a test case.
4. **Test data strategy** - fixtures and factories, synthetic vs anonymized production-like
   data, the adversarial corpus, and how PII or student/customer data is handled if the
   design touches any.
5. **Environments** - what runs on a laptop, what needs containers, what needs real
   hardware or third-party sandboxes, and which suites run in CI on every push vs nightly.
6. **Determinism and flake policy** - control of clock, randomness, ordering, concurrency,
   network. If the system contains nondeterministic components (model inference, sampling,
   distributed timing), say how they're pinned or how statistical assertions are framed -
   the catalog has a section on this.
7. **Tooling** - frameworks, runners, fuzzers, load tools, coverage measurement, and how
   the suites are invoked. Reuse what the repo already has.
8. **Entry and exit criteria** - what must be true to start testing, and the concrete gate
   for release. Exit criteria are pass/fail statements ("100% of P0 cases pass, no open
   Critical or High defects, performance suite meets NFR-*"), not aspirations
   ("adequate coverage").
9. **Contract-verification policy** - where the design defines `CT-*`, this is its own decision
   and the one that determines whether the contracts do any work. Four parts:
   - **Which side runs the clause suite.** Default: the **provider** owns it, and it runs on every
     change to the provider. A clause suite that lives with the consumer proves the consumer's
     belief, not the provider's behaviour — which is how a mocked suite stays green while
     production breaks.
   - **Where doubles are held to the contract.** Every test double standing in for a module with
     a contract must pass that module's clause suite. State this as a rule with named suites:
     the double and the real implementation run the *same* cases. A fake that doesn't honour the
     contract makes every test above it a fiction, and it is the single most common way a large
     mocked suite becomes worthless.
   - **What a `Requires` row becomes.** Each row is one integration case at rung 2+ asserting that
     the consumer's actual usage matches the clause it names. Say whether these run per-pair or as
     one suite per provider.
   - **The blast-radius rule for CI.** Changing module X re-runs X's clause suite plus the
     integration cases of every module in X's `Consumers` column. Write the rule down as a
     command, not an intention — if it isn't wired into CI, the contracts are documentation.

   State the compatibility policy the design declares (additive vs breaking) and how the suite
   enforces it: additive changes leave the clause suite green, breaking changes turn it red, and a
   red clause suite is a design conversation rather than a test to update. That last sentence is
   the one to write explicitly, because the default reflex on a red test is to change the test.

## Phase 3 - Derive the test cases

Walk the requirements in order. For each one, use the techniques in
`references/test-design-techniques.md` rather than free-associating: equivalence
partitioning and boundary values on every input domain, decision tables for
multi-condition logic, state-transition coverage for anything with a lifecycle, pairwise
combination for configuration matrices, and deliberate error guessing informed by the
design's own failure modes.

Two rules earn their keep here:

- **Every requirement gets at least one negative case and one boundary case.** Happy-path
  coverage tells you the feature exists; it doesn't tell you it's correct. Most production
  defects live in the branches nobody wrote a test for.
- **Every test case names its oracle and its isolation level.** "TC-X: verify the parser
  handles malformed input" is a title, not a test. What input, what exact expected outcome,
  with which dependencies real and which stubbed.

Specify each case in the format given in `references/test-plan-template.md` §5. Use
concrete values - `quantity = 0`, `quantity = -1`, `quantity = 2^31`, not "invalid
quantities" - because concrete values are what make a case implementable without going back
to the design, and the whole point is that someone (a developer, or `/write-tests`) can
build this without asking follow-up questions.

### Then walk the contract clauses

Every `CT-*` clause gets **at least one case that fails if the clause is violated**. That sentence
is the whole specification, and it is stricter than it sounds: a case that passes both before and
after the promise is broken has verified nothing. For each clause, ask *what would a plausible
future change do here, and would this case go red?* If the answer is no, the case is testing
something adjacent to the clause rather than the clause.

Clauses were written as assertions precisely so this step is mechanical. The technique follows from
the kind — `references/test-design-techniques.md` §13 has the full recipes:

| Kind | The case that catches a violation |
|---|---|
| `surface` | Call it as specified; assert the signature and the sync/async character. Include the "does it block until durable" question — that one is invisible in a signature and breaks callers hardest. |
| `data` | One case per field for type, nullability, unit, and enum domain. Then the distinctions the clause insists on: *empty vs absent*, *null vs zero*, *not-measured vs measured-false*. Collapsing one of those is a real change that no signature check catches. |
| `behaviour` | Idempotency (call twice, assert one effect), ordering (assert the promised order, and for a non-promise assert the caller tolerates any), purity (same input, same output, no I/O), atomicity (fail mid-operation, assert all-or-nothing). |
| `error` | One case per named error: provoke it, assert the *type*, assert the retryability the clause claims, and assert the state left behind. The state assertion is the one that gets skipped and the one that matters — "did the failed call leave a partial write". |
| `state` | Assert what it writes. Then assert what it **does not** write: a negative case proving no other module's rows changed. Write-ownership violations are silent by construction. |
| `perf` | The bound *at the stated load*, as a threshold, in the environment the clause names. A perf clause without its load figure is untestable — flag it back to the design rather than inventing one. |
| `config` | Default value, and the externally-visible behaviour change when it moves. If the clause says a key is safe to change at runtime, test that; if it says it is not, test that changing it is refused. |
| `observe` | The signal is emitted, **under the exact name**, with the promised semantics. Renaming a metric takes a dashboard and an alert with it, and nothing else in the suite notices. |
| `security` | The negative case: the field never appears, the data never persists, the call never leaves. Assert over the artifact — the assembled payload, the log line, the stored row — not over intent. |

Three case types are specific to contracts and are the reason this section exists:

- **Non-promise cases.** A clause saying something is *not* guaranteed is verified by proving no
  consumer depends on it. Make the unpromised thing vary — return results in a different order,
  return different text for identical input, return `None` where a value was allowed — and assert
  every consumer in the `Consumers` column still behaves correctly. This is the case that keeps a
  refactor legal, and it is the one nobody writes.
- **Pairwise `Requires` cases.** One per row: consumer C uses provider P through clause
  `CT-P-nn`, at rung 2+, against the real P. This is what proves the assumption C was built on is
  the promise P actually makes. A `Requires` row with no case is an unverified assumption
  wearing a citation.
- **Double-conformance cases.** The same clause suite, run against the double. Name the suite once
  and reference it from both sides rather than writing the cases twice.

Where the design flags clauses as safety properties, those get an adversarial case as well: not
"does it hold" but "can I construct a plausible change that breaks it while every `FR-*` case stays
green". If you can, that construction *is* the test.

## Phase 4 - The cross-cutting suites

Per-requirement cases cover the design's functional claims. These suites cover the things
that are true of the system as a whole, and they're where most plans thin out. Design each
one deliberately using `references/test-types-catalog.md`:

- **Contract suites** - one per module with a `CT-*` contract: every clause, run against the real
  implementation *and* against every double that stands in for it. This suite is the regression
  spine of the whole plan, so give it its own subsection rather than folding it into integration
- **Blast-radius regression sets** - per module, the named set of suites that re-run when it
  changes, taken from its `Consumers` column. This is what turns 300 clauses into a CI rule
- **Integration against mocks** and **integration against real modules** - both, with the
  contract tests that keep the mocks honest, and one case per `Requires` row
- **Smoke** - the small set that answers "is this build worth testing further", runnable in
  minutes
- **System / E2E** - the 2-5 user journeys from the design's key flows, no more; E2E tests
  are expensive and flaky in proportion to their number
- **User acceptance** - written in the user's language against the design's business goals,
  with a real acceptance criterion someone non-technical can sign off on
- **Performance** - one scenario per quantified NFR, with load profile, duration, and
  pass/fail threshold
- **Security** - concrete probes tied to the design's threat model and trust boundaries,
  not "penetration test the app"
- **Adversarial** - abuse cases written from the perspective of someone trying to make the
  system produce a wrong result, which is a different exercise from security testing and
  catches different bugs
- **Fuzz / property-based** - for parsers, decoders, input validators, and any invariant
  the design states
- **Resilience** - dependency down, slow, or returning garbage; partial failure; restart
  mid-run if the design claims resumability
- **Regression** - the policy that every fixed defect gains a test, plus the baseline suite
- **Observability** - if the design promises logs, metrics, or alerts, those are
  requirements and they get test cases too; untested telemetry is reliably broken telemetry

Skip a suite when the system genuinely doesn't warrant it, but say you skipped it and why.
Silence reads as an oversight; a one-line justification reads as a decision.

## Phase 5 - Traceability and assembly

Build the requirements traceability matrix by walking every requirement ID from Phase 0 -
not by walking your test cases, which only proves the tests you wrote are traced to
something. Every requirement needs at least one test case ID or an explicit entry in Known
Gaps explaining why it can't be tested and what compensates for that.

**Contracts get their own matrix**, because they answer a different question. The RTM asks "was
what the design asked for built"; the contract matrix asks "what breaks if this module changes",
and it carries the consumer list so a reader can see the blast radius without cross-referencing.
Every `CT-*` clause gets a row: clause, kind, verifying case(s), consumers, and the suite the
consumers' cases live in. A clause with no case is a promise nobody is holding the module to.

Verify mechanically rather than by eye:

```bash
python .claude/skills/create-test-plan/scripts/check_traceability.py --design <design-doc-or-dir> --plan <test-plan.md>
```

It reports uncovered requirements **and uncovered contract clauses** separately, plus orphan test
cases and duplicate IDs, and exits non-zero if any gap exists. Run it, fix what it finds, and
re-run until clean. Two flags matter when a design uses contracts:

- `--contracts-only` reports just the clause coverage, which is the fast check while writing §6.11
- `--no-contracts` drops `CT-*` from the requirement set, for a design that has no contract scheme
  or when you are deliberately deferring the contract suite and have said so in Known Gaps

Assemble the document using `references/test-plan-template.md` and write it to
`docs/design/test-plan.md`, alongside the design it traces to - this is a working
engineering document that gets diffed and edited, and the next two stages read it from
disk. Produce a `.docx` only if the user asks for one, and write the Markdown as well in
that case, since the pipeline cannot consume a `.docx`.

## Phase 6 - The confidence audit

This is what separates a plan that gives real confidence from one that gives the feeling of
it. Before delivering, work through `references/quality-bar.md` and then write the plan's
final section answering three questions plainly:

1. **What does passing this suite prove?** State it as a claim someone could disagree with.
   Where contracts exist, this splits in two and both halves should be stated: *these modules do
   what the design asked*, and *these modules can be changed without breaking the named consumers*.
   The second claim is only as strong as the clause coverage, so give the figure.
2. **What does it not prove?** Untested requirements, unreproducible conditions
   (production traffic patterns, real hardware, scale), assumptions baked into the mocks,
   anything whose oracle is weak. Add the contract-specific honest remainder: clauses verified
   only against a double, `Requires` rows with no rung-2 case, and any dependency edge in the
   design's graph with no clause behind it — that last one is a module relying on something
   nobody promised, and it is a design finding as much as a testing gap.
3. **What's the residual risk, and what compensates?** Canary release, monitoring and
   alerting, feature flag, manual review of the first N runs, rollback plan.

If you find yourself unable to write a specific answer to (2), that's a signal the plan is
overstating itself - go find the gap, because it exists.

## Handing off to the harness

This skill is stage 2 of a four-stage pipeline (see `CLAUDE.md`):

```
/detailed-design-generator → detailed-design.md
/create-test-plan          → test-plan.md          ← you are here
/plan-to-issues            → GitHub issues
/fix-issue | /write-tests  → PRs
```

Write the plan to `docs/design/test-plan.md`, alongside the design it traces to — that is
where `/plan-to-issues` and `scripts/trace-issues.sh` look for it.

**§8.2's test-story table is the actual handoff, and `/plan-to-issues` transcribes it
verbatim rather than re-deriving it.** That is deliberate: sizing test work belongs here,
where the test cases and their cost are visible, not at the issue-creation stage where it
would be guessed a second time. Four columns, all required:

| Column | Becomes | Why it must be here |
|---|---|---|
| Story title | Issue title | — |
| Covers | The issue's `Traces to:` line (explicit TC IDs, no `..` ranges) | Keeps the RTM alive past the GitHub boundary; `trace-issues.sh` checks it |
| Depends on | `Depends on: #N` once the number exists | The dependency graph the dispatcher schedules from |
| Written ahead of implementation? | The issue field of the same name | Tells `/write-tests` whether a red suite is expected or a bug |

Size each story to one reviewable PR — typically one module at one test level ("Unit tests
for the extraction module"), listing the TC IDs it covers. A story spanning 40 cases across
six modules cannot be reviewed in one sitting and will be split by someone with less
context than you have now.

**Contract suites make good stories and should be scheduled early.** One story per module's clause
suite, written **ahead of implementation** — mark the column `yes`. A contract is a specification
that exists before the code, so its suite can be written first, and doing so is what makes the
contract real rather than aspirational: the module is then built against a red suite that goes
green, instead of against prose that gets interpreted. Two consequences worth putting in the plan:
a `yes` story must carry no dependency, and the double-conformance cases belong in the *same* story
as the clause suite, since they are the same cases pointed at a different implementation.

The last column is the one most easily left implicit and the one that breaks things when it
is. `/write-tests` behaves differently depending on it — expecting green in one mode and red
in the other — and it will not guess correctly from the absence of a dependency line alone.

When the plan is written, say what to run next:

```bash
/plan-to-issues docs/design/
```
