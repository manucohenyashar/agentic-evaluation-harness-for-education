# Test Types Catalog

One section per test type: what it's for, what it must not be used for, how to design cases
for it, and the pass criteria that make it meaningful. Read the sections relevant to the
system in hand - a batch pipeline with no UI doesn't need the E2E browser guidance, and a
library with no network doesn't need resilience testing.

Contents:
1. The isolation ladder - mocks vs real, decided once
2. Unit tests
3. Integration tests against test doubles
4. Integration tests against real modules
5. Contract tests
6. Smoke tests
7. System / end-to-end tests
8. User acceptance tests
9. Performance tests
10. Security tests
11. Adversarial tests
12. Fuzz and property-based tests
13. Resilience and failure-injection tests
14. Regression tests
15. Observability tests
16. Data and migration tests
17. Testing nondeterministic components

---

## 1. The isolation ladder - mocks vs real, decided once

Every test sits somewhere on a ladder from "everything faked" to "everything real". Higher
rungs give stronger evidence and cost more in speed and flakiness. State this policy once
in the strategy section, then have every test case name its rung, so a reader can see at a
glance how much of the suite is actually exercising real code.

| Rung | Dependencies | Evidence it gives | Cost |
|---|---|---|---|
| 0 | All doubles | The unit's own logic is right | Milliseconds, zero flake |
| 1 | In-memory fakes (fake repo, in-process queue) | Logic + its use of a realistic interface | Fast, low flake |
| 2 | Containerized real dependency (real Postgres, real Redis, local model server) | The integration actually works: SQL is valid, serialization round-trips | Seconds, some setup |
| 3 | Real neighboring modules, external services stubbed at the boundary | The modules compose as designed | Slow |
| 4 | Full system, real everything, sandbox accounts | The deployed thing works | Slowest, flakiest |

**Test double vocabulary**, so the plan is unambiguous about what's being asked for:
*dummy* (passed but unused), *stub* (returns canned answers), *spy* (records calls for later
assertion), *mock* (pre-programmed with expectations that it verifies), *fake* (a working
lightweight implementation - in-memory DB, local filesystem stand-in).

**The rules that keep a mocked suite honest.** These exist because the failure mode of
heavy mocking isn't a failing test - it's a suite that stays green while production breaks:

- **Mock at architectural boundaries you own the contract for**, not at arbitrary internal
  seams. Mocking a module's internal helper couples the test to today's implementation, so
  the test fails on every refactor and passes through every behavior change - exactly
  backwards.
- **Never mock what you don't own** without pinning it. A hand-written stub of a third-party
  API encodes your *belief* about that API. Beliefs drift. Pin it with a contract test (§5)
  or a recorded-response fixture regenerated on a schedule against the live service.
- **Every mocked dependency needs a named companion test at rung 2 or higher.** If module A
  is only ever tested against a fake of module B, nothing in the suite proves A and B agree.
  In the plan, this is a column: each mocked-integration case names the real-dependency case
  that validates the same interaction. A mock without a companion is a gap, and it should
  appear in Known Gaps if you're accepting it deliberately.
- **Don't assert on the mock instead of the outcome.** `expect(repo.save).toHaveBeenCalled()`
  asserts that your code called your fake, which is true by construction. Assert on the
  resulting state or the returned value wherever one exists; reserve call-verification for
  cases where the call *is* the observable effect (an email was sent, an event was
  published).
- **Fakes need their own tests.** An in-memory repository used across a hundred tests is
  production-critical infrastructure. Run the same conformance suite against the fake and
  the real implementation - that suite is the definition of the interface. Where the design
  defines `CT-*` clauses, that suite already exists and is already written down: it is the
  provider's clause suite, pointed at the fake (§5.3).

## 2. Unit tests

**Scope**: one function, class, or module, at rung 0-1. No network, no disk, no clock, no
randomness that isn't seeded.

**Design**: this is where §1-§7 of the techniques reference does most of its work -
partitions, boundaries, decision tables, invariants. Aim for one behavior per test with a
name that states the behavior (`rejects_submission_with_score_above_maximum`), so a failure
report is readable without opening the file.

**Pass criteria**: deterministic, order-independent (a suite that fails when shuffled has
hidden shared state, which is a real defect the suite is hiding), and fast enough to run on
every save.

**What unit tests do not prove**: that the pieces fit together, that the SQL is valid, that
the serialization matches, or that the config is right. Say so in the confidence audit,
because a high unit-coverage number is the most commonly overclaimed evidence in software.

## 3. Integration tests against test doubles

**Scope**: two or more modules composed, with external boundaries faked - rung 1.

**Use for**: wiring and contract-shape errors (wrong field name, wrong call order, missing
error propagation), and for exercising failure paths that are hard to provoke with a real
dependency - timeouts, 500s, malformed responses, partial writes. This is the *right* place
for doubles: a fake can produce a connection reset on demand and a real database will not.

**Design**: one case per interaction described in the design's data-flow section, plus one
per failure mode listed in its error-handling section. The error paths are the reason this
tier exists; if the plan's mocked-integration cases are all happy paths, the tier is
redundant with rung 2 and should be cut.

## 4. Integration tests against real modules

**Scope**: real neighboring modules and real infrastructure in containers - rung 2-3.

**Use for**: everything the doubles can't tell you. Schema and migration correctness, query
validity, transaction and isolation behavior, serialization round-trips, connection
handling, real timeouts, actual concurrency.

**Design**: start from the design's dependency table and cover each edge with at least one
real-dependency case. Include the concurrency cases here - two writers on the same row, a
consumer and producer racing - since they're meaningless against a fake.

**Pass criteria**: hermetic (each test creates and tears down its own data; no dependence on
what a previous test left behind), and reproducible on a clean machine from one command.
Test containers per suite beat a shared long-lived dev database, which accumulates state
until tests pass only on the machine where they were written.

## 5. Contract tests

**Scope**: the agreement between a consumer and a provider, verified from both sides. Where the
design defines module contracts (`CT-*` clauses with `Consumers` and `Requires` tables), this tier
is not optional and it is not small — it is the suite that makes every *other* module safe to
change.

**What it is for, stated precisely.** Unit and integration tests answer "is this module correct".
A contract test answers a different question: **"is this module still the thing its callers were
built against"**. Those come apart constantly. A module can be refactored into something better by
every internal measure and still break four neighbours, because the neighbours depended on an
ordering, a nullability, a retryability, or a write that nobody wrote down. Where the design *has*
written them down, each one is a clause, and each clause is a test.

**The defining property of a good contract case**: it goes red when the promise breaks, and stays
green through every change that keeps it. A case that passes both before and after the violation is
not a contract test regardless of what it is called. When designing one, name the plausible future
change it is meant to catch — "someone makes this return sorted results", "someone adds a fallback
provider", "someone makes this write synchronous" — and check the case would actually fail.

### 5.1 Designing from clause kinds

One or more cases per clause, technique chosen by kind. `test-design-techniques.md` §13 has the
full recipes; the short form:

| Kind | Case shape | The violation it catches |
|---|---|---|
| `surface` | Call as specified; assert signature, sync/async, and whether it blocks until durable | An async call quietly made sync, or the reverse |
| `data` | Per field: type, nullability, unit, enum domain. Then the insisted-on distinctions: empty vs absent, null vs zero, not-measured vs measured-false | A collapsed distinction — invisible to type checks, fatal downstream |
| `behaviour` | Idempotency (twice → one effect), ordering, purity, determinism, atomicity under mid-operation failure | A retry that double-writes; an order callers indexed into |
| `error` | Per named error: provoke, assert type, assert retryability, **assert state left behind** | A failed call that left a partial write; a non-retryable error made retryable |
| `state` | Assert what it writes, **and a negative case that no other module's rows changed** | Two modules writing the same row |
| `perf` | The bound at the stated load, as a numeric threshold, in the named environment | An O(n²) fine at 100 and not at 10,000 |
| `config` | Default value; behaviour change when it moves; runtime-changeability as claimed | A default changed under a caller who relied on it |
| `observe` | Signal emitted under the exact name with the promised semantics | A renamed metric that takes an alert with it |
| `security` | Negative assertion over the artifact: payload, log line, stored row | A credential in a log; a field that escaped |

**`perf` clauses deserve a note.** They are contract clauses, not just NFR scenarios: a *loosened*
performance bound breaks callers as thoroughly as a deleted method, and it is the change most
likely to be waved through because nothing failed. If the plan has a perf clause with no threshold
or no stated load, it is untestable — send it back to the design rather than inventing a number.

### 5.2 The three case types unique to this tier

**Provider-side clause suite.** Every clause of module P, run against the real P, owned by P, run on
every change to P. This is the default home for clause cases. A clause suite that lives with the
consumer proves the consumer's *belief* about P, which is exactly the thing that drifts.

**Pairwise `Requires` cases.** Each `Requires` row names a consumer, a provider, and the specific
clause relied on. That is a test with its subject pre-written: at rung 2+, against the real
provider, assert the consumer's actual usage matches the clause. A `Requires` row with no case is
an unverified assumption wearing a citation, and it is where integration bugs hide even in
well-tested systems.

**Non-promise cases** — the ones nobody writes, and the ones that keep refactoring legal. A clause
saying something is *not* guaranteed is verified by making the unpromised thing vary and asserting
every consumer still works:

- Order unspecified → return results shuffled; consumers must still pass
- Output not reproducible → return different text for identical input; consumers must not diff it
- `None` means not-measured → return `None`; the consumer must not read it as false
- Timing unspecified → deliver the same unit twice; the worker must be idempotent

Without these, the *absence* of a promise gets depended on anyway, and the first person to exercise
the freedom the design deliberately kept discovers it is gone.

### 5.3 Doubles must pass the contract

**Every test double standing in for a module with a contract runs that module's clause suite.**
This is the rule that keeps a large mocked suite from becoming decorative, and it upgrades §1's
"fakes need their own tests" from good practice to a mechanical check: the clause suite *is* the
definition of the interface, so pointing it at the fake is not extra work, it is the same cases
with a different constructor.

Where the double cannot reproduce a clause, that is a finding, not a shrug — say which clause,
and either fix the double or record in Known Gaps that everything tested against it is untested
for that clause. The classic example: an in-memory store that commits synchronously, standing in
for one whose contract says writes are asynchronous. Every "read back what I just wrote" bug in
the system is invisible against that double.

### 5.4 Running them: the blast-radius rule

The point of the `Consumers` column is that it converts into a CI rule:

> Changing module X runs X's clause suite, plus the integration cases of every module in X's
> `Consumers` column.

Write it as a command, not an intention. Contracts that are not wired into CI are documentation,
and documentation does not go red.

**When a clause suite fails, the default response is wrong.** The reflex on a red test is to update
the test. Here that is exactly backwards: a red clause suite means either the change is breaking —
in which case it needs a contract version bump and every named consumer re-verified — or the clause
was wrong, which is a design conversation. State this in the plan in those words, because the reflex
is strong and the failure it produces is silent.

**Compatibility policy.** State which changes are additive-safe (clause suite stays green: new
optional field, new operation, tightened perf bound), which are breaking (suite goes red: removed
or renamed anything, changed type/nullability/enum domain, changed ordering or idempotency or
atomicity, changed retryability, **loosened** perf bound, renamed observed signal), and what a
breaking change obliges. Version the contract, keep the clause suite versioned with it, and do not
let over-broad clauses accumulate — a contract that pins more than consumers actually use makes the
provider unable to evolve, which is the opposite failure and just as real.

## 6. Smoke tests

**Scope**: a handful of shallow checks answering one question - is this build worth testing
further, or is it fundamentally broken?

**Design**: the app starts; config loads and required env/secrets are present; each
dependency answers a health check; one trivial end-to-end operation succeeds; the version
endpoint reports the version you just deployed. Five to fifteen checks, under a couple of
minutes total.

**Pass criteria**: any failure stops the pipeline or triggers rollback. The value is in
running it in *every* environment including production after deploy - a smoke suite that
only runs in CI misses exactly the class of problem it exists to catch, which is
environment-specific misconfiguration.

## 7. System / end-to-end tests

**Scope**: the whole system, real everything, exercised the way a user or caller uses it -
rung 4.

**Design**: the design document's key use-case flows, chosen at 2-5 journeys. Cover the
critical path and the critical failure path (payment declined, upload fails mid-way,
session expires), not every permutation - permutations belong in lower tiers where they're
cheap and stable.

**Pass criteria and hygiene**: E2E suites decay through flakiness faster than any other
tier, so the plan should state the countermeasures up front - wait on conditions rather than
sleeping, use stable selectors/IDs rather than text or layout, isolate test data per run,
and treat a flaky E2E test as a P1 defect rather than a nuisance to retry. A suite people
re-run until it's green provides no signal at all, and the plan should say that explicitly
because it's the failure everyone tolerates.

## 8. User acceptance tests

**Scope**: does the system do the job the user actually has? Distinct from system tests,
which ask whether it does what the spec says - a system can satisfy every requirement and
still be unusable, and UAT is the only tier that catches that.

**Design**: written in the user's vocabulary, traced to the design's business goals rather
than its FR IDs, with acceptance criteria a non-engineer can evaluate. Given/When/Then works
well. Include the realistic messy path, not the demo path: the actual scale (350
submissions, not 3), real-world-shaped input (blurry scans, inconsistent formatting), and
the recovery workflow for when the user does something wrong.

**Specify per case**: who runs it (role, not name), what data they use, what they observe,
and what constitutes sign-off. Also specify the *time budget* if the design implies one -
"the teacher can review the flagged queue in under 30 minutes" is an acceptance criterion,
and often the one that decides whether the system gets used.

## 9. Performance tests

**Scope**: one scenario per quantified NFR. If an NFR isn't quantified it can't be tested;
flag it back to the design rather than inventing a threshold.

**Types, which answer different questions**: *load* (expected peak - does it meet target),
*stress* (past peak - how does it degrade, and does it degrade or collapse), *soak*
(sustained hours - memory leaks, connection exhaustion, log-disk growth), *spike* (sudden
surge - queueing and autoscaling behavior), *volume* (large data - does it still work at
10x the rows).

**Each scenario states**: load profile (concurrency, arrival rate, ramp), duration, dataset
size and shape, environment (and how it differs from production - a result from a laptop is
not evidence about a server), metrics collected (p50/p95/p99, throughput, error rate,
resource utilization), and the pass/fail threshold as a number.

Measure percentiles, not averages: an average hides the tail where the user experience
actually lives. And for batch systems, total wall-clock for a realistic full run is usually
the number that matters more than per-item latency.

## 10. Security tests

**Scope**: the design's trust boundaries and threat model. Concrete probes, never "do a
penetration test".

**Derive cases from STRIDE and OWASP**, one per applicable item at each boundary:

- **Authentication**: bypass attempts, expired/forged/none-algorithm tokens, credential
  stuffing resistance, rate limiting
- **Authorization**: horizontal (another user's ID in the path) and vertical (a normal user
  hitting an admin route) privilege escalation, and the same checks on every non-UI entry
  point - authorization enforced only in the UI is the classic finding
- **Injection**: SQL, command, template, path traversal, and prompt injection wherever
  untrusted text reaches a model or an interpreter
- **Data exposure**: secrets in logs or error messages, PII in traces and analytics,
  over-broad API responses, verbose stack traces in production
- **Crypto and secrets**: TLS enforced, no hardcoded credentials, key rotation possible
- **Supply chain**: dependency vulnerability scan with a documented severity threshold
- **Denial of service**: unbounded input, zip bombs, expensive regex, unpaginated queries

For a local/offline system, adapt rather than skip: the threat model becomes file
permissions, data at rest, multi-user access on a shared machine, and what leaves the
device - which is a genuinely different (and testable) list from an internet-facing service.

## 11. Adversarial tests

**Scope**: making the system produce a *confidently wrong* result. Overlaps with security
but the goal is different - not access, but incorrectness that passes unnoticed. For any
system whose output informs a decision, this tier catches the failures that matter most and
is the one most often missing entirely.

**Design** by inverting each requirement into an attacker goal (see techniques §9), and by
targeting the system's own confidence mechanisms:

- Inputs engineered to look high-quality while being wrong - fluent, well-structured,
  confidently phrased nonsense
- Inputs that exploit the system's shortcuts: keyword matching, length heuristics,
  formatting cues, position bias
- Inputs that game the routing: making a wrong answer look certain, or a right answer look
  uncertain, so that review budget is spent in the wrong place
- Instruction injection embedded in data the system processes
- Boundary-of-competence inputs: out-of-domain content, blank submissions, submissions in
  the wrong language, adversarially near-duplicate items

**Pass criteria**: the system either handles it correctly or *fails visibly* - flags low
confidence, routes to review, returns an error. Silent wrongness is the failure. Write this
into the pass criterion explicitly, because "the system didn't crash" is not a pass here.

## 12. Fuzz and property-based tests

**Scope**: generated inputs searching for crashes and invariant violations, rather than
hand-picked inputs checking specific behavior.

**Fuzz** anything that parses untrusted bytes or text: file parsers, decoders, deserializers,
protocol handlers, OCR/ingest pipelines, config loaders. Structure-aware fuzzing (a grammar
for the format) reaches far deeper than random bytes. Seed the corpus with real-world
examples plus every bug-triggering input ever found, and keep the corpus in the repo - it's
a durable asset.

**Property-based** testing generates inputs and checks the invariants from techniques §7.
Specify per property: the generator (what input space, what distribution), the invariant,
the number of examples per run, and the shrinking expectation (a failing case must be
minimized to be actionable).

**Pass criteria**: no crash, no hang, no unhandled exception outside the documented error
type, no invariant violation, and memory/time bounded. Record the seed on every failure so
it's reproducible - an unreproducible fuzz failure is a rumor. In CI, run a bounded number
of examples for speed and a longer campaign nightly.

## 13. Resilience and failure-injection tests

**Scope**: whether the system behaves as the design's error-handling section claims when
something breaks. That section is a set of promises; this tier tests them.

**Injections**: dependency unavailable, dependency slow (past and just under the timeout),
dependency returns malformed or truncated data, dependency returns success but doesn't
persist, network partition, process killed mid-operation, disk full, out of memory, clock
jump.

**Assert on the promised behavior specifically**: retries happen the stated number of times
with the stated backoff and *stop*; timeouts fire at the stated duration; the circuit
breaker opens and later recovers; idempotency means a retried operation doesn't double-write;
degradation is the documented degradation rather than an unhandled exception; and for
anything claiming resumability, a kill-and-restart mid-run resumes without redoing or
skipping completed work. That last one deserves its own case per checkpoint boundary - it's
where resumable systems are actually broken.

## 14. Regression tests

**Scope**: preventing the return of defects and the silent drift of behavior.

**Policy to state in the plan**: every defect fixed gains a test that fails against the
unfixed code and passes after - written *before* the fix where practical, since a test not
observed failing is a test not known to work. Name the test after the defect so its purpose
survives.

**Baselines**: for anything with large structured output, keep golden files under version
control and review the diff on change deliberately. Snapshot testing degrades into
"regenerate until green" unless the plan says who reviews baseline changes and on what
grounds - so say it.

**Where contracts exist, the clause suites (§5) are the regression spine** and should be named as
such here rather than treated as a separate concern. The distinction is worth keeping straight:
a defect-regression test records something that *went wrong once*, and accumulates reactively; a
clause suite records something that *must never change*, and exists from the first commit. A plan
with a strong defect-regression policy and no clause suite is protected against every bug it has
already had, and against none of the ones a refactor is about to introduce.

## 15. Observability tests

If the design promises logs, metrics, traces, or alerts, those are requirements and get
test cases. Untested telemetry breaks silently and is discovered during the incident it was
supposed to help with.

Test: the required fields are present and correctly typed in emitted events; correlation IDs
propagate across module boundaries; error paths actually log at error level; metrics
increment on the events they claim to count; alert rules fire against a synthetic breach of
their condition; and no secret or PII appears in any of it (this one belongs to both this
section and §10).

## 16. Data and migration tests

Where the design includes persistence or schema evolution: migrations apply cleanly to a
copy of realistic data, are reversible or explicitly one-way (say which), and are safe to
run against a live system if the design claims zero-downtime deploys. Test data integrity
constraints by attempting to violate them. Test backup and restore by actually restoring -
an untested backup is a hypothesis.

## 17. Testing nondeterministic components

For components whose output isn't a fixed function of the input - model inference, sampling,
concurrent scheduling, anything with a temperature parameter. Ordinary equality assertions
either flake or get weakened into meaninglessness, so the plan needs a different frame:

- **Pin what can be pinned**: seeds, temperature 0 where supported, model version and
  weights hash, tokenizer version, prompt template version. Then a change in output is a
  signal rather than noise. Record the pinned versions in the plan; "the model" is not a
  reproducible dependency.
- **Separate the deterministic scaffolding from the nondeterministic core**, and test it at
  rung 0: prompt construction, response parsing, retry logic, schema validation, aggregation
  arithmetic, routing thresholds. This is usually the majority of the code and it is fully
  testable with a stubbed model. Wrong-output bugs live here more often than in the model.
- **Use a frozen fixture set** of recorded model responses for the default suite, so it runs
  offline, fast, and deterministically - and a separate, slower suite that hits the real
  model to catch drift between fixtures and reality (this is the §1 companion-test rule
  applied to models).
- **Assert statistically, with the sample size and threshold written down**: "agreement with
  the human-labeled set ≥ 0.75 Cohen's κ over the 200-item calibration set" is a test;
  "output is reasonable" is not. State what happens on a borderline result - re-run policy,
  or fail.
- **Use metamorphic relations** (techniques §8) for cases where no ground truth exists.
- **Guard against regression with a held-out evaluation set** the implementation is never
  tuned on, and treat a drop past a stated threshold as a build failure. Keep a separate
  smaller set for development, or the held-out set stops being held out.
- **Test the confidence signal itself**, not just the output: if the design routes
  low-confidence results to a human, the useful property is that confidence correlates with
  correctness. A system that's confidently wrong fails this even when its accuracy looks
  fine, and nothing else in the suite will catch it.
