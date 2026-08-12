# Detailed Design Document Template

Use this structure for the Detailed Design document. Keep the ID scheme (`FR-<ModuleID>-##`, `NFR-<ModuleID>-##`) consistent - the test plan and backlog are built by walking these IDs.

## Document header

```
# Detailed Design: <System Name>
Source HLD: <filename / link>
Version: 1.0        Date: <date>        Status: Draft
Author: <who/what generated this>

## Revision history
| Version | Date | Change | Author |

## 1. Scope & purpose
One paragraph: what this document covers, what it doesn't (e.g. "excludes infrastructure/IaC, which stays in the deployment doc").

## 2. Module inventory
| Module ID | Name | Responsibility | Type | Depends on |
```

## 3. Per-module sections

Repeat this structure for every module in the inventory.

```markdown
### 3.N Module: <Name> (`<ModuleID>`)

**Responsibility**: One or two sentences. What this module owns. What it explicitly does not own (call out boundary decisions that could be ambiguous).

**Functional requirements**
| ID | Requirement | Notes |
|----|-------------|-------|
| FR-<ModuleID>-01 | The module shall ... | |

Each requirement is a single, testable statement - "shall accept X and return Y under condition Z," not "shall handle billing well."

**Interfaces**

For a service: table of endpoints.
| Method | Path | Request schema | Response schema | Errors |

For a library/internal module: function/class signatures with parameter types and return types.

Always state: who calls this (upstream consumers) and what this calls (downstream dependencies) - this feeds the dependency graph in Phase 3.

**Data structures & data model**
- Entities with fields, types, constraints (nullable, unique, default), and relationships. An ER-diagram-level description is enough; full DDL only if the HLD's tech stack is already fixed and it's genuinely useful.
- State model if the entity has a lifecycle (draft -> submitted -> approved, etc.) - list valid states and legal transitions.

**Data flow**
Short numbered narrative or Mermaid sequence diagram: request/event comes in -> validated -> transformed -> persisted/forwarded -> response/event out. Call out anything asynchronous, batched, or eventually-consistent explicitly - those are exactly the details that bite people at implementation time.

**Dependencies**
| Depends on | Direction | Nature (sync call / async event / shared DB / library) | Why |

**Non-functional requirements**
| ID | Category (ISO 25010) | Requirement |
|----|----------------------|-------------|
| NFR-<ModuleID>-01 | Performance efficiency | p95 latency < Xms at Y req/s |

Pull categories from `best-practices-checklist.md` - don't default to only performance and security if reliability, maintainability, or compatibility actually matter here.

**Performance requirements**
Concrete targets: latency, throughput, capacity, expected data volume, scaling approach (horizontal/vertical, stateless/stateful, caching strategy). Mark anything not sourced from the HLD as `Assumption:`.

**Security requirements**
- AuthN/AuthZ model (who/what can call this, how identity is established, how authorization is checked)
- Data classification (does this module touch PII / financial / health data?) and the handling that implies
- Encryption in transit / at rest
- Input validation and injection risks
- Secrets management (how does this module get its credentials - never hardcode this as an answer)
- Run through the STRIDE categories in the checklist for anything externally exposed or handling sensitive data

**Error handling & resilience**
Failure modes and what happens for each: retries (with backoff policy), timeouts, circuit breaking, idempotency guarantees, what the module does when a dependency is unavailable (fail fast? degrade? queue?).

**Observability**
What gets logged (and at what level), key metrics, tracing, and what conditions should page/alert someone.

**Configuration**
Externalized config values, environment variables, feature flags, and their defaults.

**Open questions / assumptions**
Anything in this section that wasn't in the HLD and had to be decided or guessed to write the design.
```

## 4. System-level view

```markdown
## 4. System-level design

### 4.1 Module dependency diagram
Mermaid graph built from every module's Dependencies table.

### 4.2 Key use-case flows
2-4 end-to-end sequence diagrams for the most important flows, showing which modules participate and in what order.

### 4.3 System-wide non-functional requirements
Availability target, compliance regime, disaster recovery (RPO/RTO), data retention - anything that's a property of the whole system rather than one module.

### 4.4 Architecture Decision Records
One ADR per significant decision the HLD left open. Use the ADR template in `best-practices-checklist.md`.
```

## Example (condensed) - one module, to show the level of detail expected

```markdown
### 3.2 Module: Auth Service (`M-AUTH`)

**Responsibility**: Issues and validates session tokens for all other services. Does not own user profile data (that's `M-PROFILE`).

**Functional requirements**
| ID | Requirement |
|----|-------------|
| FR-AUTH-01 | The module shall issue a signed JWT on successful credential validation, expiring in 15 minutes. |
| FR-AUTH-02 | The module shall reject expired or malformed tokens with HTTP 401. |

**Interfaces**
| Method | Path | Request | Response | Errors |
|--------|------|---------|----------|--------|
| POST | /auth/login | `{email, password}` | `{token, expires_at}` | 401 invalid credentials, 429 rate limited |

**Dependencies**: `M-PROFILE` (downstream consumer of tokens, no direct call), `Redis` (session blacklist, sync call), upstream: called by API gateway.

**Security requirements**: passwords hashed with bcrypt (cost 12); tokens signed with RS256, private key in secrets manager, never in config; rate limit 5 attempts/min/IP (brute-force mitigation, STRIDE: Spoofing).
```
