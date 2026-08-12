---
name: detailed-design-generator
description: Converts a high-level design (HLD) or architecture document into an engineering-ready Detailed (Low-Level) Design document - the first stage of this repo's design-to-code pipeline. Breaks the system into modules and specifies requirements, interfaces (inputs/outputs), data structures and data flow, dependencies, performance and security requirements, and functional/non-functional requirements per module, with a stable FR-*/NFR-* ID scheme that the test plan and the issue backlog are then generated from. Use whenever the user shares or references an HLD, architecture doc, or system design and wants it turned into a detailed design, low-level design (LLD), or module specs. Also trigger on "flesh this design out", "break this into modules", or "make this ready for engineering / Claude Code", even without the words "detailed design".
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

What this skill still owns, and what everything downstream depends on, is the **`FR-*` / `NFR-*` ID scheme**. Get the requirements right, numbered, and independently testable, and the rest of the pipeline works. Get them vague and every downstream stage inherits the vagueness.

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
- **Open questions / assumptions** - anything you filled in rather than found in the HLD

Not every module needs deep treatment of every field - a stateless utility library doesn't need a data retention policy, and an internal batch job may not need an authn section. Use judgment; don't pad the document with boilerplate the module doesn't have. Do keep the requirement numbering and the section headings consistent across modules, since `/create-test-plan` and `/plan-to-issues` both work by walking these IDs in order - an inconsistent scheme here surfaces as missing coverage two stages later.

## Phase 3 - System-Level View

After the modules are individually specified, add a short system-level section:

- Module dependency diagram (Mermaid) built from the inventory table
- End-to-end sequence diagrams for the 2-4 most important use cases, showing which modules participate
- System-wide NFRs that don't belong to any one module (overall availability target, compliance regime, disaster recovery/RPO-RTO)
- Architecture Decision Records (ADR, one per significant decision the HLD left open and you had to resolve to write the detailed design) - format is in the checklist

## Self-Check Before Delivering

Before presenting the document, verify:

- Every module in the Phase 1 inventory has a full Phase 2 section
- Every requirement has a unique, stable `FR-<ModuleID>-NN` / `NFR-<ModuleID>-NN` ID
- **Every requirement is independently testable as written.** This is the check that matters most, because it is the one the next stage cannot fix. "The module shall handle billing well" produces a test case that asserts nothing and a story nobody can review. If you can't imagine the test, rewrite the requirement now.
- Every quantified NFR carries an actual number, or is explicitly marked `Assumption:` / `TBD` with an open question
- No requirement, interface, or NFR was invented without being labeled as an assumption
- The module dependency graph is complete, since `/plan-to-issues` uses it to order the backlog

If any of these fail, fix it before delivery rather than noting it as a caveat.

## Handoff

The design is stage 1 of 4. Say this explicitly when you deliver, so the flow continues rather than stopping at a document nobody acts on:

```bash
/create-test-plan docs/design/
```

That produces `test-plan.md` from these same requirement IDs — the risk register, the test cases, the mock-vs-real policy, and the test-story list. Then `/plan-to-issues docs/design/` turns both documents into GitHub issues, and the backlog flow takes over from there.

Do not produce a test plan or a story backlog yourself, even if the user asks for "the whole package" in one go. Run the next skill instead — it is one command, and the artifacts it produces are the ones the rest of the harness is built to consume.

## Output

Write `docs/design/detailed-design.md` - Markdown, in the repo, because this is a working engineering document that gets read, diffed, and edited, and because the next two stages read it from disk. `docs/design/` is the path the rest of the pipeline assumes; if you put it somewhere else, say where, since `/create-test-plan` and `/plan-to-issues` both take the path as an argument.

Only produce a Word document if the user explicitly asks for a `.docx` (use the `docx` skill for that) or clearly wants a stakeholder-facing deliverable rather than an engineering one - and write the Markdown as well in that case, since the pipeline cannot consume a `.docx`. Present the output file to the user when done; don't just describe it.

For genuinely large systems (a dozen-plus modules), split delivery: produce and share the module inventory and system-level view first, then work through the remaining modules in batches, so the user can redirect early if a module's scope looks wrong before you've written detailed specs for all of them.
