# Best-Practices Reference

Condensed cheat-sheets for the frameworks the process leans on. Consult the relevant section as you hit that part of the process - you don't need all of this loaded at once.

## Module decomposition (Phase 1)

**C4 model levels** - decide which level a module maps to so you don't mix granularities in one inventory:
- Context: the system as a black box and its external actors
- Container: independently deployable/runnable units (services, apps, databases) - this is usually the right level for "module" in this skill
- Component: major structural pieces inside one container
- Code: class/function level - too fine-grained for the Detailed Design's module inventory, appropriate inside a module's own Data Structures section

**DDD bounded-context heuristics** for drawing module boundaries: group by what changes together and is owned by the same team/concept, not by technical layer (don't make "database access" a module - that's a layer, not a bounded context). A module boundary is suspect if two modules constantly need the same transaction, or if renaming a field in one always forces a change in the other.

**SOLID**, applied at module level, not just class level:
- Single Responsibility - one reason to change
- Open/Closed - extend via new modules/interfaces, not by editing a module's core contract
- Liskov Substitution - if a module has multiple implementations (e.g. storage backends), they must be interchangeable
- Interface Segregation - don't make callers depend on interface methods they don't use
- Dependency Inversion - modules depend on abstractions of their dependencies, not concrete implementations, wherever that's practical

**Twelve-Factor App** - useful checklist for any module that's a deployable service: config in environment (not hardcoded), explicit declared dependencies, backing services treated as attached resources, stateless processes where possible, logs as event streams, dev/prod parity.

## Non-functional requirements (Phase 2)

**ISO/IEC 25010 quality categories** - use these so NFRs don't default to only "performance and security":
- Functional suitability (completeness, correctness, appropriateness)
- Performance efficiency (time behavior, resource use, capacity)
- Compatibility (co-existence, interoperability)
- Usability (only relevant for user-facing modules)
- Reliability (maturity, availability, fault tolerance, recoverability)
- Security (confidentiality, integrity, non-repudiation, accountability, authenticity)
- Maintainability (modularity, reusability, analyzability, testability)
- Portability (adaptability, installability)

Not every module needs every category populated - but scan the list before deciding a module "just doesn't have NFRs beyond performance."

## Module contracts (Phase 2b)

**Design by contract** gives the three clause shapes that matter and the question each answers:

- **Precondition** — what the caller must guarantee before calling. Answers: *whose fault is it when this is violated?* (the caller's; the module raises rather than coping).
- **Postcondition** — what the module guarantees on return, including on failure. Answers: *what may I now assume?*
- **Invariant** — what is true before and after every operation, including across failures. Answers: *what can I never observe, however I call this?*

A contract with only surface signatures is not a contract. Signatures are the least interesting part
because a compiler already checks them; the failures that reach production are in the parts no
compiler sees — nullability, ordering, idempotency, retryability, and what a failed call left behind.

**Consumer-driven contract testing** is the discipline the `Requires` table exists to enable. The
consumer states what it needs from the provider; the provider's suite proves it still provides it.
Two properties follow, and both are the point:

- A provider can refactor freely as long as every consumer's stated expectation still passes.
- A consumer cannot silently acquire a new dependency: using something the provider never promised
  shows up as a `Requires` row with no clause behind it.

**Hyrum's law** — with enough consumers, every observable behaviour of a system will be depended on,
regardless of what was promised. The design response is not to promise everything; it is to decide
deliberately for each observable behaviour whether it is promised, and to write the *non*-promises
down. "Iteration order is unspecified" is the clause that preserves your freedom to change it.

**Postel / tolerant reader**, applied carefully. Being liberal in what you accept is a contract
decision with a cost: every tolerated malformation becomes a de-facto promise you must keep. Prefer
strict acceptance with a named error (`error` clause) over silent coercion, and where you do coerce,
say so in a clause rather than leaving it as generosity a caller will come to rely on.

**Change classification.** Every contract change is exactly one of:

| Class | Examples | Obligation |
|---|---|---|
| Additive | New optional field, new operation, a new enum value consumers already handle via a default, a *tightened* performance bound | Minor version bump; consumers unaffected |
| Breaking | Removing or renaming anything; changing a type, unit, nullability, or enum domain; changing ordering, idempotency, or atomicity; making a non-retryable error retryable or vice versa; loosening a performance bound; renaming an observed signal | Major version bump; every module in the `Consumers` column re-verified |
| Clarifying | Writing down a behaviour that was already true but unstated | No version change, but it is now testable and must be tested |

The tricky ones are all in the second row's tail: loosening a perf bound and changing retryability
read like small edits and break callers exactly as thoroughly as deleting a method.

**What does not belong in a contract:** private helpers, internal table or column names no other
module reads, algorithm choice, log lines nobody alerts on, and anything phrased as an intention
("should be efficient") rather than an assertion. Each of these either freezes a decision that ought
to stay free, or cannot be tested — and an untestable clause in a contract is worse than no clause,
because it makes the suite look complete.

## Security (Phase 2)

**STRIDE threat categories** - run through these for any module handling sensitive data or exposed externally:
- **S**poofing identity
- **T**ampering with data
- **R**epudiation (can an action be denied/untraceable?)
- **I**nformation disclosure
- **D**enial of service
- **E**levation of privilege

**OWASP quick-reference** for security requirements and test cases: broken access control, cryptographic failures, injection, insecure design, security misconfiguration, vulnerable/outdated components, authentication failures, data integrity failures, logging/monitoring failures, server-side request forgery. When a module's Security Requirements section is thin, check it against this list rather than just writing "use HTTPS and validate input."

## Architecture Decision Records (Phase 3)

One ADR per significant decision the HLD left open:

```markdown
## ADR-<n>: <short title>
Status: Accepted
Context: What decision needed to be made and why (what did the HLD leave open?)
Decision: What was decided.
Consequences: What this makes easier, what it makes harder, what it forecloses.
Alternatives considered: Briefly, what else was on the table and why it lost.
```

## Testability (Phase 2, and the handoff to the test plan)

This skill doesn't write the test plan, but it decides whether one can be written. The check to apply to every requirement as you write it: **can you state the test that would fail if this were implemented wrong?** If not, the requirement is underspecified, and no amount of care at the test-plan stage recovers it — "the module shall handle billing well" yields a test case that asserts nothing.

Concretely, a testable requirement names the input condition, the action, and the observable outcome: "shall return HTTP 429 on the 6th login attempt from one IP within 60 seconds," not "shall be resistant to brute-force attacks."

The same check applies to every contract clause, and more sharply: a clause exists *to be* a
regression test. `FR-*` asks "does it do the job?"; `CT-*` asks "does it still keep the promise the
neighbours were built on?" Those are different suites with different lifetimes — the first is
written once when the module is built, the second runs on every change forever.

Test levels, design techniques, mock-vs-real policy, and the RTM are owned by `/create-test-plan` — see `.claude/skills/create-test-plan/references/`. Don't duplicate that guidance here; the two would drift.

## Backlog

Story shape, INVEST sizing, Gherkin acceptance criteria, and the GitHub issue body contract are owned by `/plan-to-issues` — see `.claude/skills/plan-to-issues/references/issue-templates.md`. This skill's contribution to the backlog is the **module dependency graph** from Phase 3, which is what orders it.
