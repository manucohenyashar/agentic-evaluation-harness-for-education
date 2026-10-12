# Detailed Design Delta: Console Redesign — the teacher runs the whole lifecycle in the browser

**Source:**
- The user's directive (2026-10-12): *"Plan a redesign of the teacher console so that a
  non-technical teacher can run the full grading lifecycle entirely in the browser — no
  engineer, no IDE, no hand-edited TOML/JSON/YAML."* The directive's eighteen requirement
  groups are restated and labelled R0 … R17 in §1.3; each is discharged by the design
  elements named against it.
- `docs/design/detailed-design.md` v1.4 (the "base design").
- `docs/design/fix_gaps_detailed_design_plan.md` v1.5.1-delta (the "gap delta").
- `docs/design/jev_decision_engine_design_delta.md` v1.8-delta (the "Jev delta").
- `docs/design/closeout_design_delta.md` v1.9.1-delta (the "close-out delta").
- `docs/design/operator_requirements_design_delta.md` v1.10-delta (the "operator delta").
- `docs/design/package_authoring_design_delta.md` v1.12-delta (the "authoring delta").
  This document applies on top of all six, in that order.

**Code baseline validated against:** `main` @ `e6dfb87`. Phase 1 evidence: every SPA route,
every server-rendered screen and the manuals were walked in a real browser against a seeded
store (screenshots and captured text under `console_baseline/`, planning artefact, not
committed); the SPA survey, the console API inventory, and the vocabulary inventory below
come from that walk and from the code at the baseline.

**Version:** 1.13-delta  **Date:** 2026-10-12  **Status:** Draft, for review before
`/create-test-plan`.  **Author:** `/detailed-design-generator`, delta mode.

## Revision history

| Version | Date | Change | Author |
|---|---|---|---|
| 1.13-delta | 2026-10-12 | **Console redesign.** <br>• **New `M-AUTHOR` intake tier** (amendment): every teacher document format — `.docx`, `.txt`, `.pdf` — normalizes into one internal representation before drafting (FR-AUTHOR-24…28); rejections are teacher-language refusals; the re-draft rule holds across formats. ADR-46. <br>• **`M-AUTHOR` becomes console-drivable**: the service gains a progress observer and a cancel flag, and the console drives `AuthoringService` directly (ADR-45, resolving the authoring delta's deferred open question). <br>• **`M-CONSOLE` grows the read surface the SPA needs** (context, jobs, issues, logs, parked documents, configuration, draft preview, impact) and **amends the enumerated control surface** with eleven new actions (draft, review answers, structured draft edit, approve-draft, class create/from-class, roster-file import, configuration update, workbook export, readable package export, cancel job). CT-CONSOLE-31…38. <br>• **`M-UI` becomes the wizard shell** (FR-UI-09…21): persistent stepper, context header, results viewer with justifications and overrides, the six secondary pages (configuration, issues, logs, parked, jobs, help-everywhere), vocabulary map, success/failure state model, hand-rolled SVG charts. <br>• **`M-CONF`** gains the console's guided configuration write path (FR-CONF-34/35, CT-CONF-24). <br>• **`M-HELP`** gains context-aware asking (FR-HELP-06). <br>• **New ADRs:** ADR-45 (authoring state stays file-backed; the console drives the library), ADR-46 (one normalization representation), ADR-47 (jobs are console-initiated work records, not pipeline state), ADR-48 (class and cohort: one ledger, two states), ADR-49 (new dependency policy: mammoth, charset-normalizer, openpyxl; everything else hand-rolled). <br>• **No store migration.** No new store table: classes are cohort ledgers in a roster-only state (ADR-48); authoring stays file-backed (ADR-45); the jobs registry is console memory. | `/detailed-design-generator` (user directive) |

---

## 1. Scope & purpose

This is a **delta**, not a replacement. The six prior documents specify a grading engine whose
console is a read view plus a small idempotent control surface. This one redesigns the console
*as the product*: the teacher who opens `http://localhost:<port>/` can run the whole lifecycle —
class, package from their own documents, review, approve, papers, grading, results, export —
without ever meeting the terminal, a file format, or an engineering word.

### 1.1 The one-sentence reading of the directive

Everything the pipeline can do, the console can drive; everything the teacher can say, the
console can accept in teacher language; and every stage the teacher is waiting on, the console
shows honestly — progress, failure, and the one next action — because a grading system a
teacher cannot operate is a system that does not exist for them.

### 1.2 What changes, what does not

**Changes:**

- **The SPA becomes the console.** Today the story is split between a thin SPA (nine
  destinations, four dead or read-only controls) and fourteen server-rendered HTML screens the
  SPA never links to. After this delta the SPA is the only teacher surface: the server-rendered
  screens remain as the operator/audit surfaces they are (S6 preflight, S7 monitor, S8
  quarantine triage stay server-rendered for the operator role), and every teacher journey —
  including the authoring screens that were "present-and-unavailable" (FR-CONSOLE-46) — is a
  SPA screen.
- **How a package is born.** From documents the teacher already has (`.docx`, `.txt`, `.pdf`,
  in any combination), through the console, with a structured editor for the draft and for
  from-scratch packages. The terminal authoring flow (`aeh author draft` / `aeh author review`)
  stays exactly as shipped — it is the debugging surface (NFR-CONSOLE-09) — but it is no
  longer the only path.
- **The console's control surface grows** from 19 to 30 enumerated actions (§3.2). Everything
  still goes through the one `perform` door; the census (CT-CONSOLE-02) still proves no
  undeclared write path exists.

**Stays the same.** The console invariants that make the design *safe* are consumed unchanged,
never weakened. Where the directive seems to press against one, the design states the
resolution rather than quietly bending:

- **Read view + control rows (CT-CONSOLE-01).** The console still holds no pipeline state and
  performs no inference. Authoring is the one new long-running console-initiated operation, and
  it changes no store row (ADR-45): the draft files are the state, exactly as the CLI leaves
  them, so a console-authored draft and a CLI-authored draft are indistinguishable downstream.
- **Loopback, no login (CT-CONSOLE-05, CT-CONSOLE-23).** *Decision confirmed with the user
  (2026-10-12):* the redesign keeps the deliberate no-authentication, loopback-only scope.
  R2's "multi-tenancy" means many classes, cohorts, packages and runs **in one store on one
  machine for one teacher** — a context switcher, not accounts. Authentication remains the
  named precondition for any hosted deployment (base design, "Deployment profiles").
- **Band selections, never a numeric score (CT-CONSOLE-08, CT-UI-05).** R6's "override a grade
  with a reason" is a band selection plus a reason field, riding the existing
  `amend a finalized grade` / `review action` actions. No numeric entry appears anywhere,
  including the new structured editor.
- **No per-student progress bar (CT-CONSOLE-09).** R3's "items done/total" is honest at the
  granularity the orchestrator actually works in: stage-level and (criterion, judge)-batch
  counts, never a per-student bar. The wizard's progress view renders what `ProgressReport`
  really carries, and the design says so in the vocabulary map ("Grading progress: 14 of 40
  grading points done") rather than pretending a per-student number exists.
- **Exactly two blocking screens (CT-CONSOLE-07).** The wizard renders the same two gates
  (question inventory, answer keys) as the two steps that cannot be skipped, plus the
  authoring placeholders — which are the same kind of blocking: a draft with placeholders
  cannot be approved, and the wizard says why and where.
- **Zero external origins, no browser storage of student text (CT-CONSOLE-06, CT-UI-01,
  CT-UI-03).** New libraries are bundled at build time and vendored like the SPA's font; no
  CDN reference, no storage addition, no student text in URLs or logs.
- **The single egress point (CT-PROV-15) and the recorded transport (CT-PROV-10).** Every
  authoring model call the console triggers rides `M-PROV`; with `HARNESS_FIXTURE_DIR` set the
  whole browser journey replays with no network, which is what the E2E acceptance test does.
- **Command parity (FR-CONSOLE-41).** Every new capability this delta adds to the console has
  a terminal counterpart or a debugging-only listing; the parity census is updated in the same
  change that adds the actions.

### 1.3 The directive's requirements, restated and labelled

| # | Requirement (from the directive) | Discharged by |
|---|---|---|
| R0 | No technical artefacts in front of the teacher: no TOML/JSON/YAML shown, edited or uploaded; forms and readable views for every structured object; a vocabulary map from internal term to teacher label | Vocabulary map (§3.3.3); CT-CONSOLE-31 (no schema vocabulary on any teacher surface); the editor reads/writes the draft through the service, never as text |
| R1 | Guided lifecycle wizard: persistent stepper over the nine stages, per-stage state, next action, return-and-edit, downstream impact | Wizard shell and stepper (§3.3.4); stage-state derivation (§3.3.5); impact read FR-CONSOLE-49 |
| R2 | Context & multi-tenancy: context header, switcher over classes/cohorts/packages/runs | Context header + `GET /api/v1/context` (FR-CONSOLE-48); scope decision: local, no login (§1.2) |
| R3 | Long-running operations: live progress (done/total, current item, elapsed, estimate), survives reload, cancel where safe; transport specified | Polling transport (§3.2.4); progress reads FR-CONSOLE-52; authoring observer FR-AUTHOR-26; cancel FR-CONSOLE-57 |
| R4 | Success/failure states: green/red with icon+text, plain-language why, one-click retry/fix; toast vs inline vs banner specified | State model (§3.3.7); FR-UI-14 |
| R5a | Create package from teacher documents: .docx/.txt/.pdf first-class; structure preserved or named; encoding detection; clear rejections; report in plain language | Intake normalization FR-AUTHOR-24…28; upload+preview FR-CONSOLE-50; report rendering FR-UI-11 |
| R5b | Review the draft in the console: placeholders blocking, plain-language answers, carry-over on re-draft | Review screen FR-UI-12; answers via `answer authoring review` (FR-CONSOLE-55); carry-over FR-AUTHOR-23 unchanged |
| R5c | Structured editor: add/edit/reorder/delete via forms; field-level validation; before/after diff; approved-package editing shows affected runs | Editor FR-UI-13; edit action FR-CONSOLE-56; impact read FR-CONSOLE-49 |
| R5d | Create from scratch with the same editor | Editor starts from an empty draft (FR-AUTHOR-29) |
| R6 | Results viewer: cohort overview, per-student drill-down, per-criterion justification in plain language, engineering detail expandable, log side panel, search/sort/filter, override with reason | Results screens FR-UI-15…17; justification from `agg` score reasons + evidence spans (FR-UI-16); override via existing amend action |
| R7 | Files: upload picker + drag-drop + preview before commit; export XLSX; export package as readable PDF + backup file; imports for every artefact | Upload preview FR-CONSOLE-50; workbook FR-CONSOLE-58; readable export FR-CONSOLE-59; backup = `.aehpkg` (exists); imports §3.2.3 |
| R8 | Help/Q&A on every screen, context-aware | Help panel FR-UI-21; context passing FR-HELP-06 |
| R9 | Startup prints a clickable URL + next step; optional auto-open with a disable flag | FR-PIPE-11 |
| R10 | Import existing packages and cohorts; an import option for every artefact | §3.2.3 — packages (`.aehpkg`), cohorts/classes (roster import), student submissions (papers upload); results deliberately refused (user-confirmed 2026-10-12) |
| R11 | Create a cohort from an existing class | `create cohort from class` FR-CONSOLE-54; ADR-48 |
| R12 | Create class and cohort by typing, no file import | `create class` FR-CONSOLE-53; the roster editor's paste path surfaced in the SPA |
| R13 | View and edit the configuration | Config page FR-UI-20; guided-form write path FR-CONF-34/35; config read FR-CONSOLE-60 |
| R14 | View errors and issues of the last run | Issues page FR-UI-18; issues read FR-CONSOLE-51 |
| R15 | View logs of the last run | Logs page FR-UI-18; logs read FR-CONSOLE-51 |
| R16 | View parked documents; reprocess after fix | Parked page FR-UI-19 — the teacher word for quarantine; reprocess rides `resolve quarantine item` + re-upload |
| R17 | View job status; cancel a job; per-job statistics | Jobs page FR-UI-19; jobs read FR-CONSOLE-52; cancel FR-CONSOLE-57 |

### 1.4 Conventions

- **IDs** continue from the highest ID in use across the six prior documents, `src/` and
  `tests/` at `e6dfb87`. They are append-only. First new IDs per module:

  | Module | First new FR | First new NFR | First new CT |
  |---|---|---|---|
  | M-AUTHOR (intake + service amendment) | FR-AUTHOR-24 | NFR-AUTHOR-07 | CT-AUTHOR-21 |
  | M-CONSOLE | FR-CONSOLE-47 | NFR-CONSOLE-10 | CT-CONSOLE-31 |
  | M-UI | FR-UI-09 | NFR-UI-04 | CT-UI-07 |
  | M-CONF | FR-CONF-34 | — | CT-CONF-24 |
  | M-HELP | FR-HELP-06 | — | — |
  | M-PIPE | FR-PIPE-11 | — | — |
  | ADRs | ADR-45 | | |

- **Migrations.** None. No store table is added (ADR-45, ADR-48): the Tier migration chains,
  `COMPLETE_SCHEMA_VERSIONS`, and the CLAUDE.md migration-chain paragraph are untouched.
- **Knobs** are named `HARNESS_*`, take the production value as default, and refuse invalid
  values with a message naming knob/value/domain (seam 3). New knobs:
  `HARNESS_AUTHOR_DOC_MAX_BYTES` (teacher document size ceiling), and the existing
  `HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES` extended to teacher documents.
- `Assumption:` marks any number or choice the prior documents do not supply.
- **User-confirmed decisions** (AskUserQuestion round, 2026-10-12): local no-login scope;
  configuration view-all + guided-form edit (never a raw TOML editor); typed student
  submissions stay out of scope (§6 open question); hand-rolled SVG charts (no chart library);
  results import refused — packages, cohorts/classes and student submissions are the
  importable artefacts (2026-10-12, §3.2.3). Review round (2026-10-12): readable package
  export stays PDF-only (no DOCX writer); per-job history stays console-memory (ADR-47 — the
  durations/costs are also recoverable from the run logs); light mode only (no dark mode this
  round).

---

## 2. Module inventory (delta)

| Module ID | Name | Responsibility in this delta (one sentence) | Type | Depends on |
|---|---|---|---|---|
| **M-AUTHOR** *(amended)* | Package Authoring | Gains the document-intake tier that normalizes `.docx`/`.txt`/`.pdf` into one internal representation, and the service surface (progress observer, cancel, empty-draft start) the console drives. | library | M-CONF, M-PROV, M-PKG (unchanged edges) |
| **M-CONSOLE** *(amended)* | Console API Server | Grows the JSON read surface the SPA needs, amends the enumerated control surface with the eleven new actions, owns the jobs registry and the startup URL. | service | M-STORE, M-ORCH, M-PKG, M-GRADE, M-REVIEW, M-INGEST, M-SETUP, M-CONF, M-AUTHOR *(new edge)*, M-HELP |
| **M-UI** *(amended)* | Console SPA | Becomes the wizard shell: stepper, context header, authoring screens, structured editor, results viewer, the six secondary pages, the vocabulary, the state model. | UI | M-CONSOLE (API), M-HELP (unchanged edges) |
| **M-CONF** *(amended)* | Deployment Profile & Run Configuration | Gains the validated, atomic configuration write path the console's guided forms use. | library | — |
| **M-HELP** *(amended)* | Manuals & Q&A | Gains context-aware asking: the question carries the screen context so answers can be about what is on it. | library | M-PROV |
| M-PIPE *(amended)* | Pipeline CLI & Composition | Gains the startup URL / auto-open behaviour on the `aeh console` path. | library | M-CONSOLE |

Unchanged and consumed as-is: `M-STORE`, `M-ORCH`, `M-PKG`, `M-GRADE`, `M-REVIEW`,
`M-INGEST`, `M-SETUP`, `M-SYNTH`, `M-STATS`, `M-PROV`, `M-DET`, `M-EXTRACT`, `M-INTEG`,
`M-AGG`, `M-JUDGE`, `M-CONFORM`, `M-CALIB`.

---

## 3. Per-module detailed design

### 3.1 `M-AUTHOR` — document intake and the console-drivable service *(amendment)*

The authoring delta gave `M-AUTHOR` a single format: PDF, with pypdf's text layer and a
profile transcriber for scanned pages (FR-AUTHOR-01). The console redesign makes the teacher's
*own* files — `.docx`, `.txt`, `.pdf`, in any mix — the primary input. Rather than adding three
parallel drafting paths, this delta adds one intake tier ahead of drafting, so the drafting
step always sees the same thing regardless of where the documents came from.

#### 3.1.1 The one internal representation (ADR-46)

**FR-AUTHOR-24** — *Every supported document format is normalized, in one step, into a single
internal document representation, and `AuthoringService.draft` consumes only that
representation.* The representation is an in-memory value type (not a file format, not a store
row — the draft files remain the only durable authoring artefact, ADR-45):

```
NormalizedDocument:
  source_name: str            # the teacher's filename, shown back to them
  source_format: 'docx' | 'txt' | 'pdf'
  source_sha256: str          # content fingerprint of the original bytes
  byte_size: int
  blocks: list[Block]         # the document's content, in order
  warnings: list[IntakeWarning]
  stats: {word_count, block_count, table_count, image_count}

Block:
  kind: 'heading' | 'paragraph' | 'list_item' | 'table' | 'image_ref'
  level: int | None           # heading level 1–6, where carried
  text: str                   # plain text; tables carry one row per line, cells tab-separated
  ordinal: int

IntakeWarning:
  code: 'image_not_carried' | 'equation_not_carried' | 'structure_guessed'
      | 'formatting_dropped' | 'encoding_fallback'
  message: str                # teacher language, names the location ("Figure near 'Question 3'")
  detail: str                 # operator detail, expandable in the console, never in a toast
```

The representation is deliberately small: it is what drafting needs (ordered text with
heading structure and tables), plus an honest account of what was *not* carried. Two
consequences are contractual:

- **Fingerprints become representation fingerprints.** FR-AUTHOR-23 carries review answers
  when an item's fingerprint matches across drafts. The fingerprint is defined over the
  normalized block text, not the source bytes — so re-drafting from a `.txt` export after
  answering a `.docx` draft still carries the answers wherever the content matches, and the
  cross-format re-draft rule holds without a special case.
- **The authoring report gains its honest source.** FR-AUTHOR-12's report already has a
  Documents section; with intake in place, the report's per-document entries render the
  `NormalizedDocument.warnings` — "what we understood from this file, and what we did not
  carry" — in the plain language the warnings already carry.

**FR-AUTHOR-25** — *`.docx` intake preserves document structure (headings, lists, tables) or
names, per location, anything it did not carry.* Implementation: `mammoth` (ADR-49) converts
the document to semantic HTML — headings map to heading blocks, lists to list items, tables to
table blocks — and returns a messages list for everything it could not convert (images,
text boxes, equations, tracked changes), which becomes `image_not_carried` /
`equation_not_carried` / `formatting_dropped` warnings with locations. The HTML is parsed to
blocks with the stdlib `html.parser`. Password-protected documents fail at the zip layer and
are refused per FR-AUTHOR-28.

Why `mammoth` over `python-docx` (the alternative the directive asked to be argued):
`python-docx` exposes the raw OOXML model, so heading structure must be re-derived from style
names (every template names them differently), tables and lists need manual traversal, and
there is no channel that says *what was not understood* — which is precisely the requirement.
`mammoth`'s whole job is lossy-with-a-message conversion, its messages are the warnings
stream, and it is pure Python with a small dependency footprint. Neither library carries
images or equations; both are honest about it, and the design treats a carried figure as a
warning plus a placeholder, never as silently dropped content.

**FR-AUTHOR-26** — *`.txt` intake detects the file's character encoding and infers document
structure, marking inferred structure with a warning.* Implementation: `charset-normalizer`
(ADR-49) detects the encoding (UTF-8 first, then the cp1252/latin-1 family, with the detected
name surfaced); an `encoding_fallback` warning fires when the detection is not UTF-8
("This file is not Unicode — we read it as Windows-1252; check that special characters look
right"). Line endings (CRLF/LF/CR) are normalized before block splitting. Structure inference
is best-effort and always warned: a non-blank line followed by a blank line, an ALL-CAPS line,
or a `1.` / `Q1` / `Question 3` numbered line becomes a heading candidate with
`structure_guessed` ("We guessed where the headings are — check the outline on the next
screen"). There is no styling to lean on in a text file, so the draft review step — not the
intake — is where a wrong guess gets fixed.

**FR-AUTHOR-27** — *`.pdf` intake rides the same normalization step, and its externally
visible behaviour is unchanged from FR-AUTHOR-01.* The existing pypdf text-layer extraction
and profile-transcriber path for scanned pages produce `paragraph`/`heading` blocks (headings
from the same heuristics as `.txt`) into the same representation. Recorded fixtures,
`expected.toml` outcomes, and the live-variant contract are untouched; new fixtures cover the
intake tier, not a changed PDF path.

**FR-AUTHOR-28** — *A file that cannot be used is refused with a teacher-language reason and a
next step, before any model call is made.* The refusal matrix (all decided by magic bytes and
cheap local checks — zero provider calls):

| Situation | Teacher-facing refusal |
|---|---|
| Legacy `.doc` (OLE magic `D0CF11E0`) | "This file was saved in an older Word format. Open it in Word and save it as .docx, then upload again." |
| Extension/format mismatch (e.g. a `.docx` that is really a `.txt`, or a renamed `.pdf`) | "This file isn't what its name says. Rename it to match what it actually is (.txt, .docx, or .pdf) and upload again." |
| Password-protected `.docx` | "This document is password-protected. Remove the password and upload it again." |
| Empty / no extractable text (0 bytes, or zero text blocks after normalization) | "We couldn't find any text in this file." (+ for images-only PDFs: "It looks like scanned pages only — we'll try to read them with the page reader." — which is the FR-AUTHOR-01 transcriber path, not a refusal) |
| Oversize (`> HARNESS_AUTHOR_DOC_MAX_BYTES`, default 10 MB `Assumption:`) | "This file is larger than 10 MB. Split it or remove pictures to get it under the limit." |
| Unsupported extension (`.rtf`, `.odt`, `.html`, …) | "We can read .docx, .txt and .pdf files. Save this as one of those and upload it again." |

**FR-AUTHOR-29** — *A package can be started from scratch: the service creates an empty draft
skeleton and the same report, marked as created empty.* `AuthoringService.draft_from_scratch(
output_dir, *, title)` writes the draft with zero questions and zero criteria, a report whose
Next step says "open it in the console and add questions and grading points", and no
placeholders. The console's structured editor (FR-UI-13) is the intended filling mechanism;
the CLI `aeh author draft --from-scratch` counterpart is added to the parity census.

#### 3.1.2 The service becomes console-drivable

**FR-AUTHOR-30** — *`AuthoringService` accepts an optional progress observer and a cooperative
cancel check, and reports progress in stage/item terms the console can render; cancel leaves
the previous draft state intact.* Signatures amend the authoring delta §3.5:

```
AuthoringService.draft(documents, output_dir, *, observer=None, cancel=None) -> DraftResult
AuthoringService.draft_from_scratch(output_dir, *, title, observer=None, cancel=None)
AuthoringService.review(draft_path, answers=None, *, observer=None, cancel=None) -> ReviewResult

AuthoringProgress = {stage: 'reading documents' | 'drafting' | 'reviewing' | 'writing draft',
                     done: int, total: int | None, current: str, attempt: int, attempts: int}
observer(progress: AuthoringProgress) -> None      # called between steps, never mid-step
cancel() -> bool                                   # checked at the same boundaries
```

Cancellation raises `AuthoringCancelled` at a step boundary; the draft directory is left
exactly as the last completed step left it (partial-step writes are avoided by writing each
artifact atomically), so a cancelled console authoring job leaves whatever draft existed
before, intact. The observer is also the console's only progress source — the service does
not log progress lines for the console to scrape.

*Non-goal, unchanged from the authoring delta:* the service still never talks to a store. The
console drives it; the orchestrator never sees authoring.

#### 3.1.3 Dependencies and knobs

- New runtime dependencies (ADR-49): `mammoth` (`.docx` → semantic HTML), `charset-normalizer`
  (`.txt` encoding detection). Both pure Python, both pinned with upper bounds in
  `pyproject.toml`, both admitted through the supply-chain suite in `tests/artifact/`.
- New knob: `HARNESS_AUTHOR_DOC_MAX_BYTES` (default 10 MB; refuse non-positive values and
  values above 100 MB with a message naming knob/value/domain, per seam 3).
- Existing knobs unchanged: `HARNESS_AUTHOR_ATTEMPTS`, `HARNESS_AUTHOR_TIMEOUT_S`,
  `HARNESS_AUTHOR_TRANSCRIBE` (auto/off) now also govern console-triggered authoring, since it
  is the same service.

#### 3.1.4 Contract (delta)

**Contract** (`CT-AUTHOR`, v1.1 — amended by this delta; base contract unchanged) · Stability: stable.

| ID | Kind | Clause (assertable) | Consumers |
|---|---|---|---|
| CT-AUTHOR-21 | data | `draft()` accepts any mix of `NormalizedDocument` sources regardless of `source_format`; the produced draft depends only on the normalized blocks and warnings, never on `source_format` | M-CONSOLE |
| CT-AUTHOR-22 | behaviour | Intake normalization is pure and deterministic: the same bytes produce the same `NormalizedDocument` on every call, with no I/O beyond reading the source file | M-CONSOLE, M-PROV (recording keys) |
| CT-AUTHOR-23 | error | A refusal (FR-AUTHOR-28) is raised before any provider call and leaves no draft artefacts on disk | M-CONSOLE |
| CT-AUTHOR-24 | behaviour | `cancel()` returning true stops the run at the next step boundary with `AuthoringCancelled`; completed artifacts up to that boundary are intact and valid | M-CONSOLE |
| CT-AUTHOR-25 | observe | `observer` is called at least once per progress stage and always with monotonically non-decreasing `done` within a stage | M-CONSOLE |
| CT-AUTHOR-26 | security | Intake never sends document content anywhere except through `M-PROV` prompts for drafting; warnings and messages never contain more than the surrounding sentence of document text | M-PROV |

*Requires* (added rows): M-CONSOLE relies on CT-AUTHOR-21/22/24 to drive the service from the
browser; M-AUTHOR relies on CT-CONF-04 (knob validation) for `HARNESS_AUTHOR_DOC_MAX_BYTES`.
*Compatibility:* additive — every existing call site (CLI, tests) keeps working with observer
and cancel defaulting to `None`; CT-AUTHOR-21's data clause is additive to v1.0's surface.

### 3.2 `M-CONSOLE` — the reads and actions the SPA needs *(amendment)*

The console today answers 24 reads and 19 enumerated actions, and its long-running story is
"the run" plus server-owned worker threads. This delta keeps every invariant (§1.2) and grows
the surface in the same shape: reads are pure store/service projections; actions go through
the `perform` door into `CONSOLE_WRITE_FIELDS` and `_apply_domain_effects`.

#### 3.2.1 New reads (all `GET /api/v1/…`, no-store, parameterized by context)

The table's rows carry seven new FRs: **FR-CONSOLE-47** (the parked-documents read, R16),
**FR-CONSOLE-48** (the context read, R2), **FR-CONSOLE-49** (the impact read, R1/R5c),
**FR-CONSOLE-50** (teacher-document upload, the intake preview, and the draft-structure
reads, R5a/R7), **FR-CONSOLE-51** (the issues and logs reads, R14/R15), **FR-CONSOLE-52**
(the jobs and per-job-statistics reads, R3/R17), and **FR-CONSOLE-60** (the configuration
projection, R13). The remaining detail in the table is the implementation shape of those
seven:

| Read | Purpose | Source of truth |
|---|---|---|
| `context` | Everything the switcher needs: classes, cohorts, packages (with per-stage wizard state), runs (with state and the stage each is at) — §3.3.5 defines the derivation | stores via existing per-entity reads, composed once |
| `impact?package_version=…` | Downstream consequences of editing an artefact: runs using a package version, students already graded under it, whether re-grading would be triggered | `M-ORCH`/`M-GRADE` rows |
| `jobs` / `jobs/{id}` | The console-initiated work registry (ADR-47): every job with state, progress, elapsed, cost where known; `jobs/{id}` adds per-job statistics (duration, cost, items graded for runs) | in-memory registry; run jobs mirror the run row |
| `issues?run_id=…` | The run's errors and warnings as teacher-language issue records: ingest problems, gate failures, judge escalations, quarantines, stage failures — each with what happened, what it affects, and the next step | existing store rows (ingest issues, stage/gate rows, quarantine, judge escalations); the console adds no persistence |
| `logs?run_id=…` | The run's stage-by-stage log records the store already holds; a log line that was never written to the store is not shown — the console does not capture stderr | store stage/event rows |
| `parked` | Quarantine, under its teacher name: parked papers with reason, the student they were matched to (or why not), and the available resolutions | quarantine rows |
| `config` | The configuration projection (FR-CONF-35): every setting with its teacher label, current value, whether it is editable, and its type for form rendering | resolved config, never the file |
| `authoring/preview` (POST) | What intake made of the uploaded documents *before* drafting: per-file NormalizedDocument summary (blocks, stats, warnings) and refusals — R7's "preview of what the system read" | `aeh.author.intake` (pure) |
| `authoring/draft` | The current draft under authoring, as structure (items, criteria, bands, placeholders with locations) — never as TOML text | draft files via `aeh.author` reads |

#### 3.2.2 New actions (the control surface grows from 19 to 30)

All eleven follow the existing pattern: declared in the runtime census, validated, idempotent
under replay (CT-CONSOLE-04), returning the outcome JSON `{action, dispatched, refused,
detail, rows_written}`. Authoring actions write **no store rows** (`rows_written` is 0 and
`ADR-45` explains why that is correct).

| Action | Behaviour | Notes |
|---|---|---|
| `draft package from documents` | Stage uploaded teacher documents as a job (ADR-47), run `AuthoringService.draft` with observer/cancel, return the job id immediately | The one new long-running console operation; job state is console memory, draft files are the state |
| `answer authoring review` | Answer one review item: reuses `AuthoringService.review(draft_path, answers=[answer])` — the per-answer call the authoring delta scripted for exactly this | FR-AUTHOR-16 rewrite-in-place means the draft on disk is always current; reload-safe |
| `edit draft package` | Apply a structured edit (add/edit/reorder/delete item or criterion) to the draft through `aeh.author`'s validate/persist path; returns a field-level change list | The console never sends TOML text; the editor's model is the draft structure read |
| `approve draft package` | Validate the draft (placeholders refuse with the FR-PKG-28 sentence), build the package, publish it into the catalog — one idempotent gate, not three | Builds on the existing `M-PKG` build + `M-SETUP` publish paths; refuses while placeholders remain, with locations |
| `create class` | Create a class ledger (ADR-48) with a typed/pasted student list | Reuses the roster editor's row model; same validation (names, duplicates) |
| `create cohort from class` | Copy a class ledger into a grading cohort (consent state carried) | ADR-48; a class may seed many cohorts |
| `import roster file` | Upload a CSV/TSV roster and preview its parsed rows before committing | Preview-before-commit per R7; malformed rows listed in teacher language |
| `update configuration` | Write the teacher-editable configuration subset through the M-CONF write path (FR-CONF-34) | Never writes secrets; never writes keys the projection marks non-editable |
| `export results workbook` | Export a run's results as `.xlsx` via `openpyxl` (ADR-49), alongside the existing CSV/PDF | Synchronous, returns the file like the existing exports |
| `export readable package` | Export the package as a deterministic, teacher-readable PDF (the existing stdlib deterministic writer — zero new dependencies) plus the `.aehpkg` backup | The `.aehpkg` re-import path already exists |
| `cancel job` | Cooperative cancel (CT-AUTHOR-24) for authoring jobs; the existing pause/resume control rows for runs | Safe by construction: no half-written artefacts |

#### 3.2.3 Imports (R10), stated as a policy rather than a screen

Every artefact a teacher can create in the console can also arrive from outside, and each has
exactly one import path. **Confirmed with the user (2026-10-12):** results are deliberately
*not* importable — grades enter the system only through the grading pipeline or an approved
amendment, and an imported results sheet would be a write path around every gate the design
exists to enforce. The export side is the only egress for results.

| Artefact | Import path |
|---|---|
| Package (the test) | the `.aehpkg` backup (exists) |
| Cohort / class | the roster file import (FR-CONSOLE-63) |
| Student submissions | the papers upload — the existing PDF scan staging path, multi-file, with the paper check naming rejections in plain language and parking what fails (the Parked page, §3.3.10); typed submissions stay out of scope (§6.1) |
| Results | **refused** (user-confirmed 2026-10-12) |

**Classes** are the ledger form of a cohort (ADR-48), so their import is the same roster
import targeting the class state.

#### 3.2.4 Long-running operations and transport (R3 decision)

**Polling, not SSE.** The console's entire runtime already runs on `useHubState` polling at
`CONSOLE_POLL_INTERVAL_MS` (default 3000 ms), and adding a second transport would split the
stale-read discipline (`_RefreshRequired`) across two mechanisms. Design:

- Authoring jobs (the only new long-running operation) are observed by polling `jobs` /
  `jobs/{id}` at the same interval; the server-side registry lives in console memory next to
  `_run_threads`, so **progress survives a browser reload** — the browser re-attaches, it does
  not own the state.
- Progress content is the `AuthoringProgress` the observer emitted: stage, done/total, current
  item, attempt x of y. Elapsed time is computed client-side from the job's `started_at`; no
  completion estimate is fabricated — the authoring delta's attempts model means a run may
  finish on attempt 1 or attempt 2, and a fake ETA would be a lie the wizard would have to
  walk back.
- Cancel appears wherever a cancel is *safe*: authoring jobs (cooperative, artefact-intact)
  and runs (the existing pause control). Synchronous actions — exports, edits, answers — are
  fast enough that they get a busy state, not a job row.
- **CT-CONSOLE-09's honesty holds in the new surface:** the jobs read exposes what the
  orchestrator actually knows (stage, criterion-batch counts for runs — never a per-student
  figure), and the SPA renders that, labelled in teacher terms ("Grading points: 14 of 40
  done").

#### 3.2.5 Startup (R9, discharged in M-PIPE)

`aeh console` prints, after the bind succeeds:

```
  Grading console:  http://127.0.0.1:7631/          ← clickable
  Next step:        create a class, then a test package — the home page walks you through it.
```

Auto-open of the default browser is **on** for interactive terminals and disabled with
`--no-open` or `HARNESS_CONSOLE_AUTO_OPEN=0`; `serve_console()` (the library/test path) never
opens a browser. NFR-CONSOLE-09's operator/teacher split is untouched: the operator banner
(log paths, data dir, config source) prints first, as today.

#### 3.2.6 Contract (delta)

**Contract** (`CT-CONSOLE`, v1.1 — amended by this delta; clauses CT-CONSOLE-01…30 unchanged) · Stability: stable.

| ID | Kind | Clause (assertable) | Consumers |
|---|---|---|---|
| CT-CONSOLE-31 | security | No teacher-facing surface — any SPA screen or server-rendered screen a teacher reaches — contains configuration-file syntax or identifiers (TOML/JSON/YAML fragments, key names, store paths, HTTP status codes, module names); assertable by text scan of the served bundle and screens | M-UI |
| CT-CONSOLE-32 | state | The three authoring actions write zero store rows and produce only draft-directory artefacts; re-running a draft job from the same documents and the same recorded fixtures leaves the draft byte-identical (FR-AUTHOR-15 idempotency) | M-ORCH, M-PKG |
| CT-CONSOLE-33 | error | Every refusal and every failed job returns a teacher-language `detail` plus a `next_action`; an HTTP status code, a traceback fragment, or a raw exception name never reaches a teacher-facing response body | M-UI |
| CT-CONSOLE-34 | security | Teacher document content never appears in a URL, a query string, the console's own log lines, or a store row; document bytes live in the content-addressed blob staging until the authoring job reads them | M-STORE, M-AUTHOR |
| CT-CONSOLE-35 | behaviour | `cancel job` on an authoring job stops it at a step boundary and leaves the draft directory exactly as the last completed step left it; `cancel job` on a run is the existing pause control and writes only `run_control` rows | M-ORCH |
| CT-CONSOLE-36 | config | `HARNESS_AUTHOR_DOC_MAX_BYTES` defaults to 10 MB; non-positive or >100 MB values are refused with a message naming knob/value/domain; the bound is enforced at upload, before intake | M-AUTHOR, M-UI |
| CT-CONSOLE-37 | observe | Job records expose stable fields the SPA renders: `job_id`, `kind`, `state` ∈ {queued, running, succeeded, failed, cancelled}, `progress.done`, `progress.total`, `progress.current`, `started_at`, `finished_at`, `cost_usd | null`, `error.detail`, `error.next_action` | M-UI |
| CT-CONSOLE-38 | data | The `context` read returns classes/cohorts/packages/runs each with a `state` from a declared enum; adding enum values is additive and the SPA maps unknown values to a neutral "needs attention" label rather than erroring | M-UI |

*Requires* (added rows): M-CONSOLE → CT-AUTHOR-21/22/23/24 (drives the service through the
library surface only, never the CLI), CT-CONF-24 (the `update configuration` action writes
only through the M-CONF write path). *Compatibility:* additive — eleven new enumerated actions
join the census (CT-CONSOLE-02's list is extended, the enumeration mechanism is unchanged);
every existing read/action keeps its shape, so no consumer re-verification is owed beyond the
SPA itself.

### 3.3 `M-UI` — the wizard shell *(amendment)*

The SPA today is nine thin screens under a 3×3 card grid, with raw IDs as page titles and
four dead or read-only controls. This delta replaces the shell and every screen; the design
direction below is binding, the wireframes are low-fi on purpose (they fix structure, not
pixels), and the vocabulary map is the deliverable the whole design leans on.

#### 3.3.1 Design direction

A **calm product tool**, closer to Linear's or Notion's settings than to a dashboard: warm
neutral surfaces, one accent colour reserved for primary actions and selection, generous
whitespace, one primary button per screen. The tool should disappear into the task — the
teacher should be able to predict where things are from the second week on (earned familiarity
over novelty). Nothing in the shell moves on page load; the only animation is 150–250 ms
transitions on hover, focus, and step advance, all killed under `prefers-reduced-motion`.

**Kept as-is because it is right:** hand-rolled CSS driven by `tokens.json` (zero UI
dependencies is a feature at localhost scale, and it keeps the no-CDN classroom rule trivial),
the self-hosted Inter font, the hash router. **Adopted, exactly two libraries** (ADR-49):
`lucide-react` 0.x for icons (replacing ad-hoc glyphs; icons are what makes "never colour
alone" affordable) and `@base-ui-components/react` 1.x for headless dialog, popover, select
and tooltip primitives (accessible behaviour without importing a styling system; React 19
native). Tables, forms, charts and layouts stay hand-rolled. Charts are hand-rolled SVG bars
(user decision): a distribution is a row of labelled bars, not a chart library.

Colour: `tokens.json` gains `success` / `warning` / `info` tokens beside the existing
`#1d4ed8` accent and warm neutrals; every state rendering pairs the colour with an icon and a
text label; contrast holds WCAG AA (4.5:1 body text, 3:1 large text and UI borders). Light
mode only in this delta — the token file makes dark mode a later, cheap change (§6).

#### 3.3.2 Screen inventory and navigation map

```
┌──────────────────────────────────────────────────────────────────────┐
│ Context header: [Class ▾] [Test package ▾] [Grading run ▾]      (?) │
├───────────────┬──────────────────────────────────────────────────────┤
│ ① Start       │                                                      │
│ ② Package     │                content area                          │
│ ③ Review      │   (wizard step rail on wizard screens)               │
│ ④ Approve     │                                                      │
│ ⑤ Papers      │                                                      │
│ ⑥ Reading     │                                                      │
│ ⑦ Grading     │                                                      │
│ ⑧ Results     │                                                      │
│ ⑨ Export      │                                                      │
├───────────────┤                                                      │
│ Classes       │                                                      │
│ Papers inbox  │                                                      │
│ Parked        │                                                      │
│ Jobs          │                                                      │
│ Issues · Logs │                                                      │
│ Settings · Help│                                                     │
└───────────────┴──────────────────────────────────────────────────────┘
```

| # | Route (hash) | Screen (FR) | Replaces |
|---|---|---|---|
| 1 | `/` | **Wizard home** — the stepper *is* the hub; nine stages as full-width rows with state, next action, and impact notes (FR-UI-09) | the 3×3 card grid |
| 2 | `/class` | **Classes & cohorts** — list, create class (paste names), create cohort from class, import roster file, roster editor (FR-UI-10 context header; actions FR-CONSOLE-53/54/63) | read-only ClassSetup + server-rendered roster editor |
| 3 | `/package` | **Packages** — list with state; new-package entry: *from documents*, *from scratch*, *import backup* | Packages screen |
| 4 | `/package/author` | **From documents** — upload → preview → drafting progress → report (FR-UI-11; FR-CONSOLE-50/61) | nothing (server `/packages/new` was CLI-bound) |
| 5 | `/package/review` | **Review draft** — placeholders blocking with locations, plain-language answering, outline check (FR-UI-12; FR-CONSOLE-55) | `aeh author review` CLI walk |
| 6 | `/package/edit` | **Editor** — structured forms for questions, MCQ keys, criteria, score levels; before/after change list (FR-UI-13; FR-CONSOLE-56) | hand-edited TOML |
| 7 | `/papers` | **Papers** — upload scans (picker + drag-drop, magic-byte filtered), preview before commit, link to parked (FR-CONSOLE-50) | Papers screen with the dead file input |
| 8 | `/run` | **Run** — preflight summary in teacher language, start/compose; pause/resume/cancel while running (FR-CONSOLE-52/57) | RunStart's restart-only control |
| 9 | `/results` | **Results overview** — distribution, per-question stats, flagged items (FR-UI-15) | Results table |
| 10 | `/results/students/{id}` | **Student drill-down** — per-criterion justification, expandable engineering detail, log side panel, override (FR-UI-16/17) | StudentDetail |
| 11 | `/issues` | **Issues** — the last run's errors and warnings, teacher language, with next steps (FR-UI-18) | nothing |
| 12 | `/logs` | **Logs** — stage-by-stage run log (FR-UI-18) | nothing |
| 13 | `/parked` | **Parked papers** — quarantine under its teacher name, with resolve/reprocess (FR-UI-19) | server-rendered quarantine |
| 14 | `/jobs` | **Jobs** — every operation with state, progress, duration, cost, cancel (FR-UI-19) | nothing |
| 15 | `/settings` | **Settings** — view everything; guided forms for the editable subset (FR-UI-20; FR-CONF-34/35) | nothing (config was display-only) |
| 16 | `/help` | **Help centre** — manuals index; the Q&A side panel is reachable from *every* screen (FR-UI-21) | Help screen |

The server-rendered screens keep their operator/audit roles (preflight, monitor, quarantine
triage, review window, blind sample, rollup, export gate); the SPA links to them as
"Open the detailed view" from the relevant wizard rows rather than duplicating them. The SPA
keeps the hash router; deep links stay shareable within the machine.

#### 3.3.3 The vocabulary map (R0)

Every teacher-visible string uses the right column. The left column is *forbidden* on
teacher-facing surfaces (CT-CONSOLE-31 makes it a text-scannable rule). This table is the
single source both the SPA copy and the test-plan's vocabulary scan import.

| Internal term (forbidden on teacher surfaces) | Teacher label |
|---|---|
| package | Test package |
| cohort | Class (when grading context) / Class list |
| class ledger | Class |
| run | Grading run |
| submission / submission_id | Paper / the student's name |
| ingest, ingestion | Reading the papers |
| ingest gate | Paper check |
| quarantine, quarantined | Parked |
| unmatched_assessment | Doesn't match the class list |
| criterion / criterion_id | Grading point |
| band | Score level |
| placeholder | Missing piece |
| authoring draft | Draft |
| authoring report | What we understood |
| transcriber | Page reader |
| judge / panel | Grader |
| escalation | Second opinion |
| decision engine | Decision engine |
| review window | Review period |
| blind sample | Spot-check |
| finalize / final | Approve final grades / Final |
| provisional | Not final yet |
| amend | Change a final grade |
| override | Change a final grade |
| narrative | Feedback |
| evidence_sum / general / bands | (never shown; the editor labels them "Checklist", "Teacher's own description", "Score levels") |
| TOML / config file / run_config | Settings |
| blob store / content-addressed | (never shown) |
| job | Job |
| state enums (queued/running/succeeded/failed/cancelled) | Queued / Running / Done / Failed / Cancelled |
| HTTP status codes, module names, store paths | (never shown) |

Two hard cases the map settles explicitly: **progress** ("Grading points: 14 of 40 done" —
the honest criterion-batch figure, never "students graded: …", which the system does not know
mid-run); and **cost** (always with currency and period — "$1.42 for this run", never a bare
number).

#### 3.3.4 The wizard shell and stepper (FR-UI-09)

```
 ① Create class      ✓ Done                    3 students
 ② Create package    ⚠ Needs attention   →     Draft has 2 missing pieces
 ③ Review draft      ● In progress             18 of 22 answered
 ④ Approve package   ○ Not started
 ⑤ Upload papers     ○ Not started
 ⑥ Reading papers    ○ Not started
 ⑦ Start grading     ○ Not started
 ⑧ Review results    ○ Not started
 ⑨ Export            ○ Not started
 ─────────────────────────────────────────────
 NEXT:  Review the draft — answer the 2 missing pieces, then check the outline.
 IMPACT: Nothing downstream yet.
```

Each stage row carries: state badge (Done ✓ / In progress ● / Not started ○ / Needs attention
⚠ / Failed ✕ / Queued ⏸), one line of teacher-language detail, and the **next action as a
button** that navigates to the step. The "Needs attention" and "Failed" states always name the
concrete blocker ("Draft has 2 missing pieces", not "incomplete"). Below the rows, one NEXT
line (the earliest actionable step) and one IMPACT line ("Nothing downstream yet", or "2
grading runs use this package — editing the grading guide means 24 papers need re-grading",
sourced from the impact read FR-CONSOLE-49).

States derive from data, not from clicks: the derivation table below is the contract between
the reads and the stepper (the test plan renders each row as a seeded-state browser case).

| Stage | State source | Done when |
|---|---|---|
| 1 Create class | `context`: class with roster ≥ 2 students | a class exists with at least two students |
| 2 Create package | `context`: draft or published package for the class | a draft or published package exists |
| 3 Review draft | `authoring/draft`: placeholder count, unanswered review items | no missing pieces, review walk complete |
| 4 Approve | package state | a published version exists |
| 5 Upload papers | papers read: uploaded count vs roster size | at least one paper per roster student, none parked |
| 6 Reading papers | paper check summary | no parked papers, checks pass |
| 7 Start grading | run state + jobs | a run has started |
| 8 Review results | run state: results present, review window state | grades finalized or review actions resolved |
| 9 Export | export history | an export exists |

Return-and-edit is structural, not special: every step row is navigable at any time; editing
an approved package routes through the editor's impact confirmation (FR-UI-13); changing
answer keys after grading surfaces the same "needs re-grading" impact line before saving.

#### 3.3.5 Context header and switcher (FR-UI-10)

The header renders the current context as three switchers (Class, Test package, Grading run)
backed by the `context` read; every switcher item carries its state badge. Switching context
navigates within it (choosing a run opens its wizard rows from stage 7); it never re-posts
anything. The header is rendered on every screen including the secondary pages; the stepper
collapses to a compact strip there. No login, no accounts (§1.2): the switcher is scope, not
identity.

#### 3.3.6 Package from documents (FR-UI-11)

Three screens in sequence. **Upload**: a dropzone (drag-drop + native picker, accept
`.docx/.txt/.pdf`, `HARNESS_AUTHOR_DOC_MAX_BYTES` enforced client-side with the same teacher
sentence), each file listed with per-file status (Reading / Understood / Refused with reason
and next step). **Preview** — "what we understood", *before* committing: per file, its outline
(headings as a tree), block/table counts, and every warning in plain language with location
("Figure near 'Question 3' was not carried — describe it in the question text"); the teacher
confirms, or removes a file and re-uploads. Refusals (FR-AUTHOR-28's matrix) render here with
their next step. **Drafting progress**: the job view (stage, done/total, attempt x of y,
elapsed) with cancel; on completion the **report** ("What we understood") renders the
authoring report's sections — documents, steps, items found, unresolved, next step — with
placeholders surfaced as "2 missing pieces, marked in the draft" and a single primary action
to continue to review.

#### 3.3.7 Review draft, and the editor (FR-UI-12, FR-UI-13)

**Review** renders the draft outline with every placeholder highlighted inline, blocking
approval while any remain; each one opens a plain-language answer form (the question the CLI
walk asks, in the console), answered one at a time through `answer authoring review`; the
draft on disk is rewritten per answer (FR-AUTHOR-16), so a reload or a context switch loses
nothing. "Re-draft from my documents" is offered with a confirm that names what happens to
answers (FR-AUTHOR-21…23 carry-over, stated in teacher language: "We'll re-read your files;
answers you already gave are kept where the content still matches, and we'll ask you to
confirm the kept ones").

**Editor**: forms for the draft structure — questions (text, type, MCQ options and keys),
grading points (criterion), score levels (band selections only — no numeric entry, ever), and
reorder via drag or move buttons; validation renders next to the field in the same vocabulary.
Saving shows a **before/after change list in teacher language** ("Changed: Question 3 — added
option D; Grading point 'Evidence from text' — score levels unchanged"), not a TOML diff; the
teacher confirms and the edit applies through `edit draft package`. Editing a **published**
package first shows the impact banner from FR-CONSOLE-49 and returns the package to
needs-approval state, listing the affected runs. **From scratch** (FR-AUTHOR-29) starts the
same editor over an empty draft.

#### 3.3.8 Success, failure, and progress states (FR-UI-14)

Three rendering tiers, chosen by what the message is *about*:

| Tier | Use for | Shape |
|---|---|---|
| **Toast** | Transient confirmation of a completed action ("Draft approved. 6 papers can be uploaded next.") | Top-right, auto-dismiss 5 s, ✓/✕ icon + text, never the only carrier of an error |
| **Inline** | Field-level validation, per-item status (a refused upload, an unanswered placeholder) | Next to the thing it is about; stays until resolved |
| **Banner** | Screen-level state: a failed job, a run failure, a park that blocks the next stage | Top of content area, persists until acted on; always names what failed, why, and renders the `next_action` as a button (FR-CONSOLE-33) |

Every failure rendering follows one sentence template: **what failed · why (plain language) ·
one click to retry or fix**. Retry re-dispatches the same idempotent action (CT-CONSOLE-04);
for authoring jobs, retry resumes from the documents as they are now (FR-AUTHOR-21), with the
carry-over confirm. Busy states are skeleton placeholders in content areas and progress bars
on jobs — never a spinner in mid-content, never a fabricated estimate.

#### 3.3.9 Results (FR-UI-15, FR-UI-16, FR-UI-17)

**Overview** (`/results`): distribution as hand-rolled SVG bars (score level on the x-axis,
count labelled on each bar — a chart is here a table with bars); per-question stats (mean
score level, most-missed items); flagged items (escalations, second opinions, low-confidence
verdicts) each linking to its student; search/sort/filter by student, score level, flag.
**Student drill-down** (`/results/students/{id}`): the paper's grade per grading point, each
with its **justification in plain language** — the aggregate's score-reason text plus the
evidence spans that grounded it, rendered as "What the paper shows" quotes; the feedback
narrative; and an expandable **Details** section carrying the engineering trail (judge
verdicts, per-judge outputs, the log side panel filtered to this student) — expandable, never
the default view. **Override**: on a finalized grade, "Change a final grade" opens a band
selection (the same bands, no numeric entry) plus a required reason field; it rides the
existing amend action and the grade's audit trail records who/when/why — rendered back to the
teacher as "Final grade changed from 'Proficient' to 'Developing' — reason recorded; the
original grade is kept in the history."

#### 3.3.10 The secondary pages (FR-UI-18, FR-UI-19, FR-UI-20)

**Issues** (`/issues`): the last run's issues read as a list of issue cards — what happened,
what it affects, next step as a button (jump to the student, re-run the paper check, resolve a
parked paper). Severity renders as icon+label, never colour alone. **Logs** (`/logs`): the
run's stage log as a timeline (stage, time, one-line summary, expandable detail); a filter box
and a "copy for support" button. **Parked** (`/parked`): each parked paper with its reason in
teacher language ("We couldn't read page 2", "Doesn't match the class list"), the resolution
actions the quarantine surface already offers, and re-upload. **Jobs** (`/jobs`): the jobs
read as a table — kind, state badge, progress, elapsed, cost, and cancel where safe; row
expand for per-job statistics (duration, cost, items graded for runs). **Settings**
(`/settings`): the configuration projection — every setting visible with its teacher label and
current value; the editable subset (models per action, cost ceiling, decision engine,
thresholds) renders as guided forms with validation, writing only through `update
configuration` (FR-CONF-34); secrets render as "configured ✓", never a value.

#### 3.3.11 Help on every screen (FR-UI-21)

A "?" in the header opens a side panel: the manuals index (existing M-HELP content), the
screen's own manual section, and the grounded Q&A box (FR-HELP-06) which sends the current
screen's context id with the question — so "what does needs attention mean here?" answers
about *this* screen. The context payload carries screen identity and object refs only — never
student names or paper text (CT-CONSOLE-34, CT-UI-07).

#### 3.3.12 Component list

`Stepper`, `ContextHeader`, `Switcher`, `StateBadge`, `StageRow`, `ProgressView` (jobs),
`FileDropzone`, `UploadList`, `PreviewOutline`, `ReportView`, `PlaceholderList`, `AnswerForm`,
`DraftEditor` (question/criterion/band forms), `ChangeList`, `ImpactBanner`, `ConfirmDialog`,
`RosterEditor`, `ResultsTable`, `DistributionBars` (SVG), `JustificationCard`,
`EvidenceQuote`, `DetailExpander`, `LogPanel`, `IssueCard`, `ParkedCard`, `JobsTable`,
`ConfigForm`, `HelpPanel`, `Toast`. Each is a hand-rolled component on the token CSS except
the Base-UI primitives underneath `ConfirmDialog`, `Switcher`, `HelpPanel` and `StateBadge`'s
tooltip.

#### 3.3.13 Accessibility and honesty clauses

**Contract** (`CT-UI`, v1.1 — amended; CT-UI-01…06 unchanged) · Stability: stable.

| ID | Kind | Clause (assertable) | Consumers |
|---|---|---|---|
| CT-UI-07 | security | Hash routes and query parameters carry only opaque refs and screen ids — never student names, paper text, or document content; browser storage is not used for any new state (CT-UI-01/03 extended to authoring) | M-CONSOLE |
| CT-UI-08 | observe | Every progress and state rendering derives from server-provided fields (CT-CONSOLE-37); the SPA never fabricates counts, percentages, or completion estimates | M-CONSOLE |
| CT-UI-09 | behaviour | Every destructive or consequence-bearing action (approve draft, edit published package, re-draft, override, cancel job) renders its impact and requires an explicit confirm; nothing posts as a side effect of a selection change | M-CONSOLE |
| CT-UI-10 | data | Every state rendering pairs colour with an icon and a text label, using only tokens from `tokens.json`; contrast meets WCAG AA (4.5:1 body, 3:1 large/UI) | — |
| CT-UI-11 | perf | First contentful paint ≤ 2000 ms and screen transition ≤ 300 ms budgets (CT-UI-06, E6 budgets) still hold with the new bundle and the two added libraries | M-CONSOLE |

*Requires*: M-UI → CT-CONSOLE-31/33/37/38 (the vocabulary, error-shape, job-field and
state-enum promises the screens render), CT-CONSOLE-52/57 (progress and cancel semantics).
*Compatibility:* additive at the API level; the shell replacement is breaking for the SPA's
own internal structure only — the committed bundle is rebuilt in the same change (the
bundle-vs-source byte-identity gate covers it).

### 3.4 `M-CONF` — the guided configuration write path *(amendment)*

Configuration is displayed by the console today and edited only in the file. R13 asks for
view-and-edit in the browser, and the user confirmed the shape: **view everything, edit a
guided subset, never a raw TOML editor.**

**FR-CONF-34** — *The configuration file can be written, atomically and fully validated,
through a library surface that accepts only the teacher-editable subset: the model per action
role, the cost ceiling, the decision engine choice, and the review-window thresholds.*
`update_profile_edits(profile_path, edits) -> UpdateResult` validates the edits with the same
rules and messages the config loader uses (CT-CONF-04's domain), re-reads the current file,
applies only the named keys, writes to a temporary file in the same directory and
`os.replace`s it (atomic on the platforms the harness supports). A validation failure writes
nothing: the file is byte-identical before and after a refused update. Secrets (API keys) and
non-teacher settings (transport, fixtures, knobs) are not writable through this surface; the
caller may not name them. The `update configuration` console action is the only caller in this
delta; the CLI gains no counterpart — the file itself remains the operator's editing surface.

**FR-CONF-35** — *The configuration projects into a view model for rendering: every setting
with its teacher label, current value, a type tag for form rendering, and an `editable` flag
that is false for everything outside FR-CONF-34's subset.* Secrets project as a boolean
"configured" state, never a value (CT-CONF-19's no-secret-emission rule extended to the
projection). The projection is what `/settings` renders and what the test plan's vocabulary
scan asserts against — no key name from the file ever appears in the projection.

**CT-CONF-24** (`config` / `state`) — *An accepted update leaves a file the loader parses
identically to intent (the next load reflects exactly the edited keys and nothing else); a
refused update leaves the file byte-identical; the write is atomic, so a reader never observes
a half-written profile.* Consumers: M-CONSOLE. Requires: CT-CONF-04 (validation), CT-CONF-19
(secrets never projected). Compatibility: additive — new library surface, no existing
behaviour changes.

### 3.5 `M-HELP` — context-aware asking *(amendment)*

**FR-HELP-06** — *The grounded Q&A accepts an optional screen context (screen id plus object
refs) with the question, and answers about that screen when the context is present.* The
existing `GET /api/v1/help/ask` request gains a `context` field: `{screen, refs}` — refs are
the same opaque ids the screens already render. The context joins the prompt as grounding
material alongside the manuals; the grounding rules are unchanged (answers cite their manual
sections; M-PROV carries every call; `RecordedFixtureProvider` replays them). A question
without context behaves exactly as today. No student text rides in the context (CT-UI-07).

### 3.6 `M-PIPE` — the startup URL *(amendment)*

**FR-PIPE-11** — *`aeh console` prints a clickable full URL and a one-line next step after the
bind succeeds, and opens the default browser unless disabled.* The bind already knows its
port; the banner gains `http://127.0.0.1:<port>/` and the next-step sentence (§3.2.5).
Auto-open is on for interactive runs and suppressed by `--no-open` or
`HARNESS_CONSOLE_AUTO_OPEN=0` (any of `0`, `false`, `off` — refused values fall back to the
default with a warning naming knob/value). `serve_console()` never opens a browser, so tests
and in-process drivers are unaffected. NFR-CONSOLE-09's operator banner prints first,
unchanged.

---

## 4. System-level design

### 4.1 Dependency graph (delta)

```
                 M-CONF ──────┐
                    │         │            M-HELP ──► M-PROV
                    ▼         ▼                 ▲
  ┌──────────────────────────────────────────────────────────┐
  │                      M-CONSOLE                           │
  │  reads: context · impact · jobs · issues · logs ·        │
  │         parked · config · authoring preview/draft        │
  │  actions: draft · answer review · edit draft · approve · │
  │           create class · cohort-from-class · roster ·    │
  │           update config · workbook · readable · cancel   │
  └──┬─────────┬─────────┬──────────┬─────────┬─────────────┘
     ▼         ▼         ▼          ▼         ▼
  M-STORE   M-ORCH    M-PKG      M-GRADE   M-AUTHOR ◄── M-PROV
     ▲                          M-REVIEW   (new edge)
     │                          M-INGEST      ▲
  M-UI (SPA) ─────────────────────────────────┘ (drives the library
    │                                           surface, never the CLI)
    └── M-HELP
```

One new edge: **M-CONSOLE → M-AUTHOR**. The console drives `AuthoringService` as a library —
the authoring delta's §3.5 decision, now taken (ADR-45). No other edge moved.

### 4.2 The two journeys, end to end

**Journey A — a package from the teacher's own documents.** The teacher uploads files
(`POST` staging → intake preview read shows what was understood, refusals surface with next
steps) → confirms → `draft package from documents` creates a job, the console thread drives
`AuthoringService.draft` through `M-PROV` (recorded in replay mode) → the observer's progress
renders from the jobs read → the report renders → the teacher answers placeholders one at a
time (`answer authoring review`, draft rewritten in place) → checks the outline in the editor
(`edit draft package` with the change list) → `approve draft package` validates, builds
(`M-PKG`), publishes (`M-SETUP`) → the wizard's stage 4 flips Done, stages 5–9 unlock. The
store changed exactly where the pipeline's own flows would have changed it: package version
rows and catalog state. Nothing else.

**Journey B — grading, in the browser.** Class from typed names (`create class`) or a file
(`import roster file`) → cohort from the class (`create cohort from class`) → papers uploaded
with preview → preflight rendered in teacher language → `start a grading run` (existing
action) → the run's job record mirrors the run row; progress renders at stage/criterion-batch
granularity (CT-CONSOLE-09 honoured, teacher-labelled) → pause/resume/cancel ride the
existing control rows → results overview and student drill-down render justifications and
evidence → overrides ride the amend action with a reason → exports: CSV/PDF (existing),
workbook (new), readable package PDF (new).

### 4.3 System NFRs (delta)

- **NFR-CONSOLE-10** — *Every teacher-facing surface is vocabulary-clean:* a text scan of the
  served SPA bundle and the server-rendered teacher screens finds no configuration-file
  syntax, store paths, HTTP status codes, or module identifiers (the CT-CONSOLE-31 clause,
  stated as the NFR the test plan measures).
- **NFR-UI-04** — *The teacher can complete the full lifecycle in the browser with the
  keyboard alone and a screen reader's landmark navigation:* every interactive control has an
  accessible name, focus order follows reading order, and state badges announce icon + label,
  not colour.
- **NFR-AUTHOR-07** — *Intake handles a classroom-sized document set* — `Assumption:` up to
  20 documents totalling 40 MB normalize in under 60 s on a laptop-class machine, with no
  provider call; the knob `HARNESS_AUTHOR_DOC_MAX_BYTES` bounds the per-file worst case.

### 4.4 Architecture decisions

**ADR-45 — Authoring state stays file-backed; the console drives the library.** The authoring
delta deferred one decision: where review answers live if a half-reviewed draft must survive a
browser change. Resolved: **they live in the draft**, exactly as the CLI leaves them.
`AuthoringService.review(draft_path, answers=[…])` rewrites the draft in place per answer
(FR-AUTHOR-16), so state survives reload, restart, even a different machine opening the same
data directory. No store rows, no console memory, no migration. The consequence the console
accepts: a draft being reviewed is *single-writer* — two browsers answering the same draft
would interleave rewrites — and the console enforces one active authoring job per draft
directory (a second `draft`/`answer` action on the same draft is refused with "A review of
this draft is already open"). Alternatives rejected: store-backed authoring state (a
migration plus a second source of truth that would drift from the CLI's files); console-memory
answers (lost on restart, violating the survival requirement outright).

**ADR-46 — One normalization representation for every teacher document format.** `.docx`,
`.txt`, and `.pdf` each map, in one intake step, into the `NormalizedDocument` model
(FR-AUTHOR-24); drafting consumes only that model. Rationale: three intake-aware drafting
paths would triple the placeholder/carry-over/report logic and make the cross-format re-draft
rule (FR-AUTHOR-23 across formats) impossible to state. The fingerprint amendment
(normalized-text fingerprints) follows from the representation. Alternative rejected:
converting `.docx`→PDF and reusing the PDF path — lossy twice, and it would put the transcriber
in the loop for documents whose text is already perfect.

**ADR-47 — Jobs are console-initiated work records, not pipeline state.** The jobs registry
lives in console memory next to `_run_threads`; run jobs mirror the run row; authoring jobs
mirror nothing. The console does not persist jobs, the orchestrator does not see them, and a
console restart drops finished-job history (running authoring jobs are recoverable: the draft
files are the state, so the page simply shows no active job and the wizard's stage rows derive
from the files). Rationale: the store's job-shaped state already exists — it is the run — and
inventing a durable job table would create a second lifecycle to keep consistent with the
run's. The cost, stated honestly: per-job *history* (durations, costs of past jobs) survives
only while the console process lives, and the test plan treats that as specified behaviour,
not a bug. Statistics the directive wants per job (duration, cost, items graded) come from the
live record plus, for runs, the store's own stage rows.

**ADR-48 — Class and cohort are one ledger in two states.** A "class" is a cohort ledger in a
roster-only state; "create cohort from class" copies the roster into a new grading cohort
carrying consent state, and a class may seed many cohorts. No new table, no migration. The
class/cohort distinction stays a console vocabulary distinction (R0's map) over one storage
concept, exactly as the roster editor and consent model already work. Alternative rejected:
a proper class entity — a migration plus dual bookkeeping for a distinction the grading
pipeline never consumes.

**ADR-49 — New dependency policy for this delta.** Exactly three new runtime dependencies,
each justified against the supply-chain suite: `mammoth` (`.docx` semantic conversion with a
message channel — no alternative offers the "name what was not carried" stream),
`charset-normalizer` (`.txt` encoding detection; actively maintained, MIT, the detection layer
`requests` itself uses), and `openpyxl` (workbook export; the only maintained pure-Python
xlsx writer). Everything else is hand-rolled: charts as SVG, the readable package export from
the existing deterministic stdlib PDF writer (no DOCX writer is added — the directive's
"PDF and/or DOCX" is satisfied by PDF; DOCX is recorded in §6 as a future option),
icons from `lucide-react` and primitives from `@base-ui-components/react` as **build-time**
SPA dependencies bundled into the committed asset, never runtime fetches (CT-CONSOLE-06). The
readable package export deliberately adds no DOCX writer (PDF-only; user-confirmed
2026-10-12). All six are pinned with upper bounds and admitted through the supply-chain suite
in `tests/artifact/` in the change that adds them.

### 4.5 Contract register (delta)

| Module | Contract | Version | Clause count | Stability | Consumed by |
|---|---|---|---|---|---|
| M-CONSOLE | CT-CONSOLE | v1.1 | 38 | stable | M-UI |
| M-UI | CT-UI | v1.1 | 11 | stable | — (top of the stack) |
| M-AUTHOR | CT-AUTHOR | v1.1 | 26 | stable | M-CONSOLE |
| M-CONF | CT-CONF | v1.1 | +1 | stable | M-CONSOLE |

Change classification: every clause added here is **additive** (new actions and reads appended
to an enumerated surface that stays runtime-verifiable; new fields alongside existing ones).
No clause of v1.0 changes meaning. A breaking change to any of the four would oblige a
contract version bump and re-verification of every named consumer — the test plan encodes
that as the clause suites.

### 4.6 Requirement-to-FR trace (R0–R17)

| Directive requirement | FRs that discharge it | CT clauses that hold it |
|---|---|---|
| R0 vocabulary | FR-UI-09…21 copy rules; vocabulary map §3.3.3 | CT-CONSOLE-31, CT-UI-10 |
| R1 wizard | FR-UI-09, FR-CONSOLE-48/49 | CT-CONSOLE-38, CT-UI-08 |
| R2 context | FR-UI-10, FR-CONSOLE-48 | CT-CONSOLE-38 |
| R3 long-running | FR-CONSOLE-52/57, FR-AUTHOR-30 | CT-CONSOLE-35/37, CT-UI-08, CT-AUTHOR-24/25 |
| R4 states | FR-UI-14 | CT-CONSOLE-33, CT-UI-09/10 |
| R5a from documents | FR-AUTHOR-24…28, FR-CONSOLE-50/61, FR-UI-11 | CT-AUTHOR-21/22/23/26, CT-CONSOLE-34/36 |
| R5b review draft | FR-UI-12, FR-CONSOLE-55, FR-AUTHOR-30 | CT-AUTHOR-24, CT-CONSOLE-32 |
| R5c editor | FR-UI-13, FR-CONSOLE-56/49 | CT-UI-09 |
| R5d from scratch | FR-AUTHOR-29 | CT-AUTHOR-21 |
| R6 results | FR-UI-15/16/17 | CT-UI-10 |
| R7 files | FR-CONSOLE-50/58/59 | CT-CONSOLE-34/36 |
| R8 help | FR-UI-21, FR-HELP-06 | CT-UI-07 |
| R9 startup URL | FR-PIPE-11 | — |
| R10 imports | §3.2.3 policy, FR-CONSOLE-63 | CT-CONSOLE-31 (surface enumeration) |
| R11 cohort from class | FR-CONSOLE-54 | ADR-48 |
| R12 typed class | FR-CONSOLE-53 | — |
| R13 configuration | FR-UI-20, FR-CONF-34/35, FR-CONSOLE-60 | CT-CONF-24 |
| R14 issues | FR-UI-18, FR-CONSOLE-51 | CT-CONSOLE-33 |
| R15 logs | FR-UI-18, FR-CONSOLE-51 | CT-CONSOLE-31 |
| R16 parked | FR-UI-19, FR-CONSOLE-47 | CT-CONSOLE-33 |
| R17 jobs | FR-UI-19, FR-CONSOLE-52/57 | CT-CONSOLE-35/37 |

---

## 5. Test fixtures and tiers (design input to `/create-test-plan`)

### 5.1 New intake fixtures (AF-14 … AF-20, continuing the authoring corpus)

Same corpus kind as AF-01…13: module inputs with `expected.toml`, stdlib-only in-tree
generator (`fixtures/F-AUTHOR/build_authoring_fixtures.py` gains the new cases), byte-for-byte
reproducible, census-pinned by the same mechanism. New cases:

| Fixture | Content | Expected outcome |
|---|---|---|
| AF-14 | `.docx` with a real rubric table | table carried as table blocks; drafting resolves |
| AF-15 | `.docx` with an image and an equation | `image_not_carried` + `equation_not_carried` warnings with locations; draft still builds |
| AF-16 | `.txt` in Windows-1252 | `encoding_fallback` warning names the detected encoding; special characters intact |
| AF-17 | `.txt` with no heading structure | `structure_guessed` warnings; draft builds, review asks to confirm the outline |
| AF-18 | legacy `.doc` (OLE header) | refused, FR-AUTHOR-28's teacher sentence, no provider call |
| AF-19 | `.txt` renamed to `.docx` (extension mismatch) | refused with the rename guidance |
| AF-20 | empty file (0 bytes) | refused with the no-text sentence |
| AF-21 | mixed set: `.docx` test + `.txt` grading memo | both normalized; draft consumes the pair; fingerprint carry-over exercised when re-drafting the same content as a single `.txt` |

AF-21 is the cross-format fixture: it re-uses AF-14's content in `.txt` form so the
answer-carry-over test can draft from one format, answer, re-draft from the other, and assert
the carries.

### 5.2 Tier policy (what runs where)

- **E1 (fast tier):** intake unit cases (every refusal row of FR-AUTHOR-28, encoding
  fallbacks, structure inference) against the fixture generator's outputs; config write-path
  unit cases (CT-CONF-24); the vocabulary/contract scans (CT-CONSOLE-31) against the *served
  bundle*; `M-CONF`/`M-AUTHOR` clause suites.
- **E6 (browser, every push):** the SPA screens — per-requirement Playwright cases plus the
  full-lifecycle acceptance journey, all over `RecordedFixtureProvider` (no network; the
  browser request log is the no-egress oracle). The acceptance journey runs once per source
  format: single `.docx`, single `.txt`, single PDF, and the mixed pair (AF-21's shape).
- **Nightly live variant:** the same journeys against the real provider, skipped cleanly
  without the key, per the standing live-test rules.
- **Store digests and page text** remain the oracles; screenshots stay planning evidence, not
  assertions.

---

## 6. Open questions

Resolved during review (2026-10-12), now recorded as decisions in §1.4: DOCX package export
declined (PDF-only); per-job history stays console-memory (ADR-47); dark mode not a
requirement this round.

1. **Typed student submissions** — declined for now (user decision, 2026-10-12): the intake
   tier is for teacher documents; student papers stay scanned-only. Revisit as its own
   directive; the normalization representation would carry it if taken up.
2. **Single-writer drafts** — ADR-45's consequence: one active authoring job per draft
   directory, enforced by refusal. If two-teacher concurrent authoring ever becomes a real
   workflow, it needs the same treatment runs got (control rows), which is out of this delta's
   scope.
3. **Multi-class grading** — R2's switcher scopes one class at a time; grading a run across
   several cohorts at once stays an orchestrator/operator flow (the compose path), rendered in
   the SPA's Run screen as an advanced action rather than a wizard stage. Confirm whether
   teachers need it in the wizard in a later round.