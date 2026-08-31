# Quality Bar

Read this before delivering. It has three parts: the anti-patterns that make a test plan
look thorough while proving nothing, the self-check to run against the finished document,
and how to write the confidence audit honestly.

---

## Part 1 - Anti-patterns

### In the plan itself

**Activity lists instead of tests.** "Perform integration testing on the ingestion module"
is a task assignment, not a test. If a case doesn't name an input, an oracle, and an
expected result, it can't be implemented from the plan and it can't be argued with.

**Uniform coverage.** Every module getting the same treatment means risk was never
assessed. The tell is a plan where the trivial config loader and the scoring engine have
similar case counts.

**Happy paths only.** Roughly the majority of production defects live in error handling,
boundaries, and unexpected input. A plan whose cases are all "valid input produces valid
output" tests that the feature exists, not that it's correct.

**Untestable pass criteria.** "System performs adequately", "output is reasonable",
"handles errors gracefully". If two competent people could disagree about whether it passed,
it isn't a criterion yet. Replace with a number, a specific state, or a named error type.

**Copy-pasted strategy.** A strategy section that would be unchanged if pasted into a
different project's plan carries no information. Every choice should point at something in
*this* design.

**The RTM built backwards.** Walking your test cases and noting what they cover always
produces a complete-looking matrix. Walk the requirements instead; the empty rows are the
output.

**Coverage percentage as the goal.** A line-coverage target is satisfiable by tests that
assert nothing, and teams reliably discover this. Use coverage to find untested code, then
ask whether that code matters.

**Silence about what isn't covered.** A plan with no Known Gaps section is either
incomplete or dishonest, and readers who notice will discount the rest of it.

**Contracts inventoried but not verified.** A plan that lists the design's `CT-*` clauses in its
system-under-test section and then never traces them has done the expensive half of the work and
skipped the half that pays. The tell is a traceability matrix with `FR-*` rows only.

**Contract cases that would survive the violation.** The commonest way this tier goes wrong: a case
nominally traced to a clause about async writes that would pass just as well if the write were made
synchronous. It is testing the same code, not the same promise. The `Breaks if` field exists to make
this checkable — if the named change leaves the case green, the case is mislabeled.

**Non-promises left untested.** Every clause saying "this is not guaranteed" with no case that makes
the unpromised thing vary. Nothing fails, so nothing looks wrong, and meanwhile consumers quietly
acquire dependencies on the freedom the design deliberately kept. Discovered years later as
"we can't change that, it'll break everything".

**Doubles exempt from the contract.** A fake that stands in for a contracted module across two
hundred tests but never runs that module's clause suite. Every one of those tests is asserting
against a fiction, and the plan reads as though they aren't.

### In the tests the plan specifies

**Assertion-free tests.** Code that executes the system and asserts nothing, or asserts only
that no exception was thrown. Passes forever, including when the answer is wrong.

**Testing the mock.** Asserting that your code called your double, when the double's
behavior was defined by the same person writing the test. Assert on outcomes and state.

**Tests coupled to implementation.** Asserting on private methods, call order that doesn't
matter, or internal structure. These fail on every refactor and pass through every behavior
change - the exact inverse of what a test should do.

**Shared mutable state between tests.** Tests that pass in order and fail when shuffled.
The suite is hiding a real defect: something isn't as isolated as it looks.

**Sleep-based synchronization.** `sleep(2)` is a bet on machine speed that is lost in CI,
under load, and on a slower laptop. Wait on the condition.

**Snapshot tests as a substitute for thinking.** Golden files are fine when someone reviews
the diff. When the workflow is "regenerate until green", the baseline records the bug.

**One giant E2E per feature.** Slow, flaky, and when it fails it tells you a feature is
broken somewhere. Push detail down to the cheapest level that can catch it.

**Randomness without a recorded seed.** An unreproducible failure gets closed as flaky, and
the bug ships.

**Tests that only run on the author's machine.** Absolute paths, a hand-populated dev
database, an env var nobody documented. If the plan doesn't specify hermetic setup, this is
what gets built.

## Part 2 - Self-check before delivery

Work through these against the finished document. Fix what fails rather than noting it as a
caveat - the traceability *is* the deliverable.

**Completeness**
- [ ] Every module in the design has test cases; none were skipped for being "simple"
- [ ] Every `FR-*` and `NFR-*` appears in the RTM with at least one test case, or in Known
      Gaps with a compensating control
- [ ] Every test case traces back to at least one requirement, or is justified as
      cross-cutting (smoke, resilience, observability)
- [ ] Every quantified NFR has a performance or capacity scenario with a numeric threshold
- [ ] Every failure mode named in the design's error-handling sections has a resilience case
- [ ] Every state machine has both legal-transition and illegal-transition cases
- [ ] Every `CT-*` clause has at least one case, or a Known Gaps entry with a compensating control
- [ ] Every `Requires` row in the design has a pairwise integration case at rung 2+
- [ ] Every non-promise clause has a case that makes the unpromised thing vary
- [ ] Every double standing in for a contracted module runs that module's clause suite, or its
      exemption is recorded with the consequence stated
- [ ] Every dependency edge in the design's graph has a clause behind it, or is reported as a
      design finding
- [ ] `check_traceability.py` runs clean (requirements **and** clauses)

**Depth**
- [ ] Every requirement has at least one negative and one boundary case
- [ ] Critical and High risk items have cases at more than one isolation rung
- [ ] Adversarial cases exist for anything producing a judgment, score, or decision
- [ ] Fuzz or property cases exist for every parser, decoder, and validator
- [ ] The concurrency, ordering, and retry-idempotency cases exist where the design implies
      them

**Rigor**
- [ ] Every case names its oracle; none say "verify the output is correct"
- [ ] Every case names its isolation rung
- [ ] Every contract case names the change it would catch (`Breaks if`), and that change would
      actually turn it red — spot-check the safety-property clauses, where it matters most
- [ ] The plan says what a red clause suite means (breaking change or wrong clause), and says
      explicitly that it does not mean update the test
- [ ] The blast-radius rule is written as a command wired into CI, not as an intention
- [ ] Every mocked dependency has a named companion test against the real thing, or a Known
      Gaps entry
- [ ] Test data uses concrete values, not descriptions of values
- [ ] Pass/fail criteria are checkable by someone who didn't write the plan
- [ ] Priorities are assigned and the exit criteria reference them

**Usability**
- [ ] A developer could implement any given case without asking a follow-up question
- [ ] Test stories are sized to one PR each and carry their dependency line
- [ ] Commands for running each suite are stated and match the repo's actual tooling
- [ ] The document's ID scheme matches the design's, so cross-referencing works

**Honesty**
- [ ] §7.2 (what passing proves) is a claim someone could disagree with, not a platitude
- [ ] §7.3 (what it doesn't prove) is specific and non-empty
- [ ] Assumptions introduced by the plan are labeled as assumptions
- [ ] Requirements that couldn't be tested are reported as design findings, not quietly
      dropped

## Part 3 - Writing the confidence audit

The last section is the one that determines whether the plan is trusted for the right
reasons. Three moves make it real:

**Be specific about the evidence, not the effort.** "412 test cases across 9 modules" says
nothing about correctness. "Every scoring path is verified against exact expected values at
rung 0, and the aggregation is verified against a real database at rung 2; the model's
judgment quality is verified only statistically against a 200-item labeled set" tells a
reader exactly how much to believe.

**Name the strongest remaining risk out loud.** Every system has one. If the plan doesn't
name it, the reader assumes you didn't find it. Naming it, with its compensating control,
is what makes the rest of the document credible.

**Distinguish "untested" from "untestable".** Untested is a scheduling decision and can be
fixed. Untestable-in-this-environment (production traffic shape, real hardware at scale,
genuine user behavior) is a permanent property that has to be managed in production instead
- through canary deploys, monitoring, feature flags, or human review of the first N runs.
Say which is which, because they call for completely different responses.

A useful closing sentence to aim for: *"The most likely way this ships broken despite a
green suite is X, which we mitigate by Y."* If you can't complete that sentence, the audit
isn't finished.
