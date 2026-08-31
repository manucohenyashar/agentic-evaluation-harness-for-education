---
name: detailed-design-generator
description: Converts a high-level design (HLD) or architecture document into an engineering-ready Detailed (Low-Level) Design document - the first stage of this repo's design-to-code pipeline. Breaks the system into modules and specifies requirements, interfaces (inputs/outputs), data structures and data flow, dependencies, performance and security requirements, and functional/non-functional requirements per module, plus an explicit per-module contract (CT-*) stating everything outside callers may rely on, with a stable FR-*/NFR-*/CT-* ID scheme that the test plan and the issue backlog are then generated from. Use whenever the user shares or references an HLD, architecture doc, or system design and wants it turned into a detailed design, low-level design (LLD), module specs, or module contracts/interface contracts. Also trigger on "flesh this design out", "break this into modules", "define the module contracts", or "make this ready for engineering / Claude Code", even without the words "detailed design".
---

# Detailed Design Generator

Turns a high-level design (HLD) into a **Detailed Design Document**: one section per module, engineering-grade detail, with a stable requirement ID scheme.

**This skill owns the design and nothing else.** It is stage 1 of a four-stage pipeline (see `CLAUDE.md`):

```
/detailed-design-generator → detailed-design.md   ← you are here
/create-test-plan          → test-plan.md
/plan-to-issues            → GitHub issues
/fix-issue | /write-tests  → PRs
```

Earlier versions of this skill also produced a test plan and a story backlog. They no longer do, and the reason is worth stating so nobody adds them back: `/create-test-plan` and `/plan-to-issues` produce those artifacts with more depth and, crucially, as the *single* owner of each. Two skills producing a backlog produced two incompatible backlogs from one design, with different story IDs and different granularity, and the second one silently discarded the first. One owner per artifact is what keeps the traceability chain intact.

What this skill still owns, and what everything downstream depends on, is the **`FR-*` / `NFR-*` / `CT-*` ID scheme**. Get the requirements right, numbered, and independently testable, and the rest of the pipeline works. Get them vague and every downstream stage inherits the vagueness.

`CT-*` is the **module contract**: the subset of a module's design that other modules are entitled to
rely on, stated as assertions and given stable IDs. It is what makes a regression suite possible. A
test written against a `FR-*` proves the module does what it was asked to do; a test written against a
`CT-*` proves the module still keeps the promise its callers were built on. Phase 2b defines it.

Read `references/detailed-design-template.md` and `references/best-practices-checklist.md` before producing output.

## Phase 0 - Intake

Locate the HLD (uploaded file, pasted text, or a link the user gives you - fetch it). Read it fully before doing anything else. While reading, extract:

- Business goals, actors, and system context (who/what talks to this system)
- The components, services, or layers the HLD already names, even loosely
- Tech stack, platform, and hard constraints already decided
- Any quality attributes mentioned (SLAs, compliance regime, expected scale)
- Existing diagrams or interface sketches

HLDs are, almost by definition, incomplete - that's what makes them "high level." You will hit gaps (no mention of auth, no latency targets, no data retention policy). Don't silently invent numbers to fill them. Two honest options: propose a reasonable default and label it clearly as an assumption ("Assumption: p95 < 300ms, not specified in HLD - confirm with stakeholder"), or mark it `TBD` and flag it in an Open Questions section. Either is fine; making up a number and presenting it as if it came from the HLD is not - it will get built to a spec nobody actually asked for.

**Scope check for large systems**: if the HLD implies more than roughly 6-8 modules, or its priorities aren't clear, do the module decomposition (Phase 1) and show the user the module inventory before writing full detailed designs for all of them. A wrong guess here wastes a lot of downstream work. For a small-to-medium system, or when scope is obvious, just proceed straight through all phases.

## Phase 1 - Module Decomposition

Decompose the system using the HLD's own boundaries as the starting point, refined with the C4 model and DDD bounded-context thinking from `references/best-practices-checklist.md`. A module should have a single, statable responsibility - if you can't summarize what it owns in one sentence, it's probably two modules pretending to be one, or a slice of something bigger.

Produce a **Module Inventory** table: `Module ID | Name | Responsibility (one sentence) | Type (service / library / UI / data store / job / integration) | Depends on`. Assign each module a short stable ID (e.g. `M-AUTH`, `M-BILLING`) - this ID prefixes every requirement, test case, and story tied to that module.

## Phase 2 - Per-Module Detailed Design

For each module, fill out the template in `references/detailed-design-template.md`. Work through modules one at a time rather than trying to hold the whole system in your head at once - build the document section by section, the same way you'd build any long technical document.

Every module section needs, at minimum:

- **Responsibility & scope** - what it owns, what it explicitly does not own
- **Functional requirements** - numbered (`FR-<ModuleID>-01`, ...), each one independently testable
- **Interfaces** - inputs and outputs: API contracts (method, path, request/response schema, status/error codes) or function signatures if it's a library; who calls this module and what it calls
- **Data structures & data model** - entities, fields, types, constraints, relationships; state model if the module has one
- **Data flow** - how data moves through the module step by step; a short sequence description (Mermaid is fine) for any non-trivial flow
- **Dependencies** - other modules, external services, libraries, and any version constraints; note which are upstream (this module needs them) vs. downstream (they need this module)
- **Non-functional requirements** (`NFR-<ModuleID>-01`, ...) - pull from the ISO 25010 categories in the checklist so you don't just default to "performance and security" and skip reliability, maintainability, or portability when they matter
- **Performance requirements** - concrete targets where the HLD or reasonable defaults support them (latency, throughput, capacity, scaling approach), assumptions flagged as such
- **Security requirements** - authn/authz model, data classification, encryption in transit/at rest, input validation, secrets handling; run the module through the STRIDE checklist for anything handling sensitive data or exposed externally
- **Error handling & resilience** - failure modes, retries, timeouts, idempotency, what happens when a dependency is down
- **Observability** - what gets logged/measured/traced, and what would page someone
- **Configuration** - externalized config, environment variables, feature flags
- **Contract** (`CT-<ModuleID>-NN`) - the binding, externally-visible subset of all of the above. Phase 2b below; it is not optional and it is not a summary.
- **Open questions / assumptions** - anything you filled in rather than found in the HLD

Not every module needs deep treatment of every field - a stateless utility library doesn't need a data retention policy, and an internal batch job may not need an authn section. Use judgment; don't pad the document with boilerplate the module doesn't have. Do keep the requirement numbering and the section headings consistent across modules, since `/create-test-plan` and `/plan-to-issues` both work by walking these IDs in order - an inconsistent scheme here surfaces as missing coverage two stages later.

## Phase 2b - The Module Contract

Every module gets a contract, and the contract is the point of the whole document. The rest of a
module section tells an implementer what to build. The contract tells **everyone else** what they may
depend on — and, by omission, what they may not. Without it, "don't break other modules" is a hope
enforced by whoever happens to remember; with it, it is a test suite.

The failure this prevents is specific and common. A module is refactored, its own unit tests pass,
and three sibling modules break — because they relied on a return being sorted, an error being
retryable, a write landing before the call returned, or a field never being null. None of those was
ever written down, so none was ever tested, so nothing failed until integration. The contract's job
is to make each of those a numbered, assertable clause **before** anyone writes code against it.

### What a contract is, and is not

A contract is a **promise about observable behaviour at the module boundary**. It is not a summary of
the section above it and it must not restate internals.

The test: *if this were changed, would code outside the module have to change, or silently start
being wrong?* Yes → it belongs in the contract. No → it is an implementation detail and putting it in
the contract is actively harmful, because it freezes a decision nobody needs frozen and the
regression suite will then fight every legitimate refactor.

Two corollaries worth stating, because both get violated by default:

- **Under-specify and callers depend on it anyway.** Anything observable will eventually be depended
  on whether promised or not (Hyrum's law). So promise it deliberately, or state explicitly that it
  is *not* promised — "iteration order is unspecified" is a real clause and it is the clause that
  lets you change the order later.
- **Over-specify and the contract becomes the design.** A clause naming a private helper, an internal
  table, or an algorithm nobody can observe is a clause that will be broken by correct work.

### Clause kinds — the completeness checklist

Walk all nine for every module. Most modules will have clauses in six or seven of them; a kind with
genuinely nothing to say is skipped, not padded. Missing kinds are where integration bugs live —
`error`, `state`, and `perf` are the three that get forgotten and the three that hurt most.

| Kind | What it pins down | Typical omission that costs someone a day |
|---|---|---|
| `surface` | Operations that exist: name, parameters, types, return type, sync/async, endpoint + method | Whether the call blocks until the write is durable |
| `data` | Types crossing the boundary: fields, types, nullability, enum domains, ranges, units, encoding, ordering | Nullability, and what "empty" means versus "absent" |
| `behaviour` | Preconditions, postconditions, invariants, idempotency, ordering, determinism, atomicity, purity | Whether calling twice is safe |
| `error` | Every failure a caller can see: name/code, when raised, whether retryable, what state it leaves behind | Whether a failed call left a partial write |
| `state` | Persistent side effects: what this module writes, what others may read, what only it may write | Two modules writing the same row |
| `perf` | Measurable bounds *with the load they hold at*: latency, throughput, capacity, complexity, memory | An O(n²) that was fine at 100 and isn't at 10,000 |
| `config` | Config that changes externally-visible behaviour: key, default, effect, whether it is safe to change at runtime | A default changing under a caller who relied on it |
| `observe` | Signals others consume by name: metric/log/event names and their semantics | A renamed metric taking a dashboard or an alert with it |
| `security` | Promises about what never crosses the boundary: fields never emitted, data never persisted, calls never made | A credential appearing in a log line |

Write each clause as a **single assertable statement in the present tense** — the thing a test
asserts, not an intention. "`resolve()` returns criteria ordered by ordinal ascending; the order is
part of the contract" is a clause. "Ordering should be sensible" is not. If you cannot picture the
assertion, the clause is not finished.

### Contract block format

Place it at the end of the module section, after Configuration and before Open questions. Full
template and a worked example are in `references/detailed-design-template.md`. Four parts:

1. **Header** — `**Contract** (`CT-<ModuleID>`, v1.0) · Stability: stable | provisional | internal`,
   plus one sentence naming the module's boundary in words.
2. **Clause table** — `| ID | Kind | Clause (assertable) | Consumers |`. IDs are
   `CT-<ModuleID>-NN`, append-only in exactly the way `FR-*` is: withdraw by leaving a gap, never
   renumber. `Consumers` names the modules that rely on the clause — that column *is* the blast
   radius, and it is what turns "I changed `M-AGG`" into "so re-run the `M-GRADE`, `M-REVIEW` and
   `M-STATS` integration suites."
3. **Requires** — `| Depends on | Clauses relied on | What this module assumes |`. The other
   direction, and the one that catches assumptions nobody wrote down. Every entry names clause IDs
   belonging to the *dependency*. If a module assumes something no clause of its dependency states,
   you have found a real gap: add the clause to the dependency, or the assumption is unfounded.
4. **Compatibility** — one or two lines: what is additive here, what is breaking, and what a
   breaking change obliges (new contract version, and every consumer in the Consumers column
   re-verified). Where a module has a canonical test double or fixture that consumers use in place
   of the real thing, name it and say what it must reproduce — a fake that doesn't honour the
   contract makes every integration test that uses it a lie.

### Consistency rules

- A contract clause **may not contradict** an `FR-*`/`NFR-*` in the same section. Where a clause
  restates a requirement's externally-visible consequence, cite the requirement in the clause text
  rather than paraphrasing it into a second, drifting version.
- Every `Consumers` entry must be a module that actually depends on this one per the Phase 1
  inventory, and every dependency in that inventory must appear in some `Requires` row. The two
  tables and the dependency graph are three views of one fact and must agree.
- Anything a module explicitly does *not* promise, but a reader would reasonably assume, gets a
  clause saying so. Non-promises are contract content.

## Phase 3 - System-Level View

After the modules are individually specified, add a short system-level section:

- Module dependency diagram (Mermaid) built from the inventory table
- End-to-end sequence diagrams for the 2-4 most important use cases, showing which modules participate
- System-wide NFRs that don't belong to any one module (overall availability target, compliance regime, disaster recovery/RPO-RTO)
- Architecture Decision Records (ADR, one per significant decision the HLD left open and you had to resolve to write the detailed design) - format is in the checklist
- A **contract register**: one row per module giving its contract ID, version, stability, clause count, and the modules that consume it. It is the index a change lands against — "what breaks if I change `M-X`" should be answerable from this table alone. State alongside it the change-classification rules (what counts as additive, what counts as breaking) and the obligation a breaking change carries, so the rule lives in one place rather than being restated per module.

## Self-Check Before Delivering

Before presenting the document, verify:

- Every module in the Phase 1 inventory has a full Phase 2 section
- Every requirement has a unique, stable `FR-<ModuleID>-NN` / `NFR-<ModuleID>-NN` ID
- **Every requirement is independently testable as written.** This is the check that matters most, because it is the one the next stage cannot fix. "The module shall handle billing well" produces a test case that asserts nothing and a story nobody can review. If you can't imagine the test, rewrite the requirement now.
- Every quantified NFR carries an actual number, or is explicitly marked `Assumption:` / `TBD` with an open question
- No requirement, interface, or NFR was invented without being labeled as an assumption
- The module dependency graph is complete, since `/plan-to-issues` uses it to order the backlog
- **Every module has a contract block**, with clauses covering every kind that applies to it. Check the three that get skipped: does it say what happens on failure (`error`), what it writes (`state`), and what it costs (`perf`)?
- **Every contract clause is an assertion, not an intention**, and states something *observable from outside the module*. A clause naming an internal function or table is a defect — remove it or restate it as the boundary effect it causes.
- **The Consumers column and the Requires tables agree with the dependency graph**, in both directions. A dependency edge with no clause behind it means somebody is relying on something nobody promised; find what it is and promise it, or remove the edge.
- **No contract clause contradicts an `FR-*`/`NFR-*`** in the same section
- Contract IDs are unique and append-only, exactly as `FR-*`/`NFR-*` are

If any of these fail, fix it before delivery rather than noting it as a caveat.

## Handoff

The design is stage 1 of 4. Say this explicitly when you deliver, so the flow continues rather than stopping at a document nobody acts on:

```bash
/create-test-plan docs/design/
```

That produces `test-plan.md` from these same requirement IDs — the risk register, the test cases, the mock-vs-real policy, and the test-story list. Then `/plan-to-issues docs/design/` turns both documents into GitHub issues, and the backlog flow takes over from there.

Say one thing about the contracts when you hand off, because it changes what the next stage produces:
the `CT-*` clauses are the **contract, integration and regression** layer of the test plan. Each
clause is one assertion; each `Requires` row is one integration test between a specific pair of
modules; the `Consumers` column is which suites re-run when a module changes. `FR-*` coverage proves
the module was built right, `CT-*` coverage is what keeps it right afterwards — a test plan that
traces only `FR-*` will test every module and still let a refactor break its neighbours.

Do not produce a test plan or a story backlog yourself, even if the user asks for "the whole package" in one go. Run the next skill instead — it is one command, and the artifacts it produces are the ones the rest of the harness is built to consume.

## Output

Write `docs/design/detailed-design.md` - Markdown, in the repo, because this is a working engineering document that gets read, diffed, and edited, and because the next two stages read it from disk. `docs/design/` is the path the rest of the pipeline assumes; if you put it somewhere else, say where, since `/create-test-plan` and `/plan-to-issues` both take the path as an argument.

Only produce a Word document if the user explicitly asks for a `.docx` (use the `docx` skill for that) or clearly wants a stakeholder-facing deliverable rather than an engineering one - and write the Markdown as well in that case, since the pipeline cannot consume a `.docx`. Present the output file to the user when done; don't just describe it.

For genuinely large systems (a dozen-plus modules), split delivery: produce and share the module inventory and system-level view first, then work through the remaining modules in batches, so the user can redirect early if a module's scope looks wrong before you've written detailed specs for all of them.
