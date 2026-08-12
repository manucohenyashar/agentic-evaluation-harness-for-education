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

Test levels, design techniques, mock-vs-real policy, and the RTM are owned by `/create-test-plan` — see `.claude/skills/create-test-plan/references/`. Don't duplicate that guidance here; the two would drift.

## Backlog

Story shape, INVEST sizing, Gherkin acceptance criteria, and the GitHub issue body contract are owned by `/plan-to-issues` — see `.claude/skills/plan-to-issues/references/issue-templates.md`. This skill's contribution to the backlog is the **module dependency graph** from Phase 3, which is what orders it.
