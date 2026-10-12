# Test Plan: Console Redesign — the teacher runs the whole lifecycle in the browser

**Design input:** `docs/design/console_redesign_design_delta.md` v1.13-delta, applied over
`detailed-design.md` v1.4 + the gap, Jev, close-out, operator and authoring deltas; code
baseline `main` @ `e6dfb87`. **Status:** Draft, for review before `/plan-to-issues`.
**Version:** 1.13-plan-delta  **Date:** 2026-10-12  **Author:** `/create-test-plan`.

This plan claims: **if every test in here passes, a non-technical teacher can run the full
grading lifecycle in the browser — no terminal, no file format, no engineering vocabulary —
without breaking any console invariant the prior design documents guarantee.**

New requirement surface in the design delta: FR-AUTHOR-24…30, FR-CONSOLE-47…63 (47–52, 60
reads; 53–59, 61–63 actions), FR-UI-09…21, FR-CONF-34/35, FR-HELP-06, FR-PIPE-11;
NFR-AUTHOR-07, NFR-CONSOLE-10, NFR-UI-04; CT-AUTHOR-21…26, CT-CONSOLE-31…38, CT-UI-07…11,
CT-CONF-24; ADR-45…49. Everything else is regression territory — consumed through the
existing suites (named in §6.3), not re-specified here.

## 1. Risk register

Severity rules from the base plan: irreversibility and silent-wrongness outrank everything.
Contract clauses are scored low-detectability by default — a violation surfaces in a
*neighbour*, far from the change.

| Risk ID | Module / Requirement | Failure imagined concretely | Clause | Blast radius | Reversibility | Detectability | Severity | Test depth |
|---|---|---|---|---|---|---|---|---|
| RS-01 | M-AUTHOR intake (R5a) | A cp1252 `.txt` is read as UTF-8; every accented student name in the test paper is mojibake in the draft, and the teacher approves it | FR-AUTHOR-26 | Draft → published package → every grade downstream | Re-draftable | Silent (draft *looks* fine) | **Critical** | Unit matrix + fixture + journey |
| RS-02 | M-AUTHOR intake (R5a) | A `.docx` image (a diagram the questions reference) is dropped silently; questions grade against a figure students saw and the draft doesn't | FR-AUTHOR-25 | Grading correctness | Re-draftable | **Silent by default — only the warning stream prevents it** | **Critical** | Warning-stream assertions, not just success |
| RS-03 | M-AUTHOR re-draft (R5b) | Re-drafting after review loses the teacher's answers; they re-answer, or worse, approve a draft believing answers persisted | FR-AUTHOR-23 / 30 | Teacher trust, rework | Re-answerable | Loud when total, silent when *partial* | High | Carry-over across formats + provisional-flag assertions |
| RS-04 | M-CONSOLE authoring actions | A second write path to drafts bypasses `perform` (e.g. an upload endpoint that mutates draft files) — the census stays green, the invariant is dead | CT-CONSOLE-02/32 | Whole harness | — | Silent | **Critical** | Census + rows_written assertions on every authoring action |
| RS-05 | M-CONSOLE jobs | Progress rendering fabricates numbers (a percentage invented client-side), or per-student counts appear mid-run — the wizard lies about a live run | CT-CONSOLE-09 / CT-UI-08 | Teacher decisions (cancel? wait?) | — | Loud only when wrong badly | High | Seeded-run progress assertions at known batch counts |
| RS-06 | M-CONSOLE refusals | A refused action returns `detail` containing an HTTP status or traceback fragment; the teacher sees "the action answered status 503" all over again | CT-CONSOLE-33 | Every failure path | — | Loud but corrosive | High | Response-body text scan across the refusal matrix |
| RS-07 | M-CONF write path (R13) | A refused config edit half-writes the profile; the next console start fails to load config — the teacher's tool is down | CT-CONF-24 | Whole system startup | Reversible from backup | Silent until restart | **Critical** | Atomicity + byte-identical refusal cases |
| RS-08 | M-UI vocabulary (R0) | Raw `submission_id`/`criterion_id`/TOML fragment survives on one screen; the acceptance test's no-TOML assertion passes everywhere else and the teacher meets jargon exactly once | CT-CONSOLE-31 | Teacher-facing everything | — | Loud | High | Text scan over *every* teacher screen in the bundle, not a sample |
| RS-09 | M-UI override (R6) | Grade override posts without a reason, or overwrites instead of amending — the append-only grade history (CT-GRADE, #103) is violated through the UI | FR-UI-17 | Audit trail | Hard (audit broken) | Silent | **Critical** | Override flow + store-digest assertions on history rows |
| RS-10 | M-CONSOLE uploads | Teacher document bytes leak into a URL, a log line, or a store row | CT-CONSOLE-34 | Privacy | — | Silent | High | Request-log + log-capture + store scan |
| RS-11 | M-UI blind/sample-style controls | A selection change posts a mutation without confirm (the Phase-1 blind-sample defect, generalized) | CT-UI-09 | Grades, drafts | Reversible | Loud but harmful | High | Interaction matrix on every select/toggle |
| RS-12 | M-AUTHOR cancel | Canceling an authoring job half-writes the draft; the teacher's previous draft state is gone | CT-AUTHOR-24 / CT-CONSOLE-35 | Draft loss | Reversible only if intact-before | Silent | High | Cancel-at-boundary cases with a pre-existing draft |
| RS-13 | M-UI budgets | The two new libraries blow the FCP/transition budgets; the console is sluggish on classroom hardware | CT-UI-11 | Perceived quality | — | Loud (slow) | Medium | E6 budget assertions |
| RS-14 | M-HELP context | The Q&A context payload carries student text; answers quote it back | CT-UI-07 | Privacy | — | Silent | High | Context payload capture + no-egress oracle |
| RS-15 | Exports (R7) | Workbook export silently truncates (row cap) or writes formulas instead of values | FR-CONSOLE-58 | Delivered artefact | Reversible | Loud eventually | Medium | Read-back comparison against store digest |
| RS-16 | Intake determinism | Non-deterministic normalization (dict ordering, locale) breaks recording keys and replay | CT-AUTHOR-22 | E2E determinism | — | Loud in tests | Medium | Byte/double-run equality case |

Deliberately **low** depth (stated, not overlooked): the readable PDF export's *typography*
(only determinism and content presence are asserted — the writer is already battle-tested by
the corpora suite); the Settings page's *display* of non-editable rows (one presence case);
the Jobs page's cost figures (one format case — cost correctness belongs to M-PROV's ledger
suites, already shipped).

## 2. Test strategy

### 2.1 Levels and shape

This system is orchestration-over-a-store with a thin UI; per the base plan's shape, most
value is at rung 3 (real store) and E6 (real browser over the real console). The pyramid here:

- **E1 unit (rung 0–1)** — intake normalization (pure), config write path (file-system only),
  knob validation, refusal matrices. Many small cases, no I/O beyond temp dirs.
- **E1 integration (rung 3)** — console reads/actions against a real seeded store through
  `serve_console()`; the existing console-suite harness is the template.
- **E6 browser (rung 4)** — every SPA requirement and the acceptance journeys, Playwright
  sync API per `tests/support/spa.py` conventions; `RecordedFixtureProvider` replay, zero
  egress, browser request log as the no-egress oracle.
- **Nightly live** — the same journeys against the real provider; skip cleanly without the
  key (standing rule).

### 2.2 Mock-vs-real policy

- The **provider** is always the recorded transport in E1/E6 (`RecordedFixtureProvider`,
  CT-PROV-10) and real in the nightly variant. No double stands in for M-PROV in the browser
  suites — the whole point of the acceptance journey is that the real (recorded) service is
  driven from the UI.
- The **store is always real** (rung 3 minimum); no in-memory fake of M-STORE exists in
  console suites.
- The **browser is real** for all TC-UI/TC-E2E cases (no jsdom).
- `AuthoringService` is real in all suites; its inputs are fixture documents, its model calls
  recorded. A cancelled-observer double is used only to force cancellation timing (the double
  is the *test's* instrument, not a stand-in for the service).

### 2.3 Oracles

| Oracle class | Used by |
|---|---|
| Exact expected value (parsed structures, counts, teacher sentences) | intake, refusals, config, exports |
| Store digest / sqlite row inspection (the E6 `store_digest` convention) | override history, authoring writes nothing, class/cohort rows |
| Page text + accessible-name locators only (`tests/support/spa.py`) | every TC-UI/TC-E2E |
| Browser network-request log | no-egress guarantee on every browser case |
| Byte determinism (run twice, compare) | intake, PDF export, recording keys |
| Captured server logs | the never-leaks clauses (CT-CONSOLE-34) |

**Screenshots are never oracles** (standing convention); `console_baseline/` remains planning
evidence.

### 2.4 Test data

- **AF-14…AF-21** per the design delta §5.1: in-tree stdlib generator, `expected.toml`,
  byte-reproducible, census-pinned (the TC-AUTHOR-28 mechanism extended). AF-21 re-encodes
  AF-14's content as `.txt` for the cross-format carry-over.
- **Roster fixtures**: a 3-student roster (matching `console_world` seeds), a malformed-row
  CSV (duplicate name, missing column, empty row).
- **Rosters and student names are synthetic** (`ref-sub-c-ts48-*` world); no real names, no
  real student data anywhere in fixtures.
- **Recordings**: captured by the implementing stories via `RecordedFixtureProvider.record()`
  under `fixtures/F-AUTHOR/recordings/` — never fabricated (standing honesty rule); the
  recording-honesty census extends to the new journeys' keys.

### 2.5 Environments

E1 for unit/integration; E6 for all browser cases (headless msedge/chrome channels, skip
naming what's missing per convention); nightly live variant behind the key check; E5
(air-gapped weekly) inherits the console suites as-is since replay needs no network. The
chunked full-suite rule (memory) applies as always.

### 2.6 Determinism and flake policy

- Authoring model calls replay from recordings; keys are content-addressed (CT-AUTHOR-22's
  purity makes keys stable).
- Clock: elapsed-time assertions compare `finished_at − started_at` bounds, never wall-clock
  sleeps; polling waits use Playwright's expect-poll, not `sleep`.
- Charts and orderings render from store-ordered data; tests assert content, not pixel layout.
- Randomness: none new; fixture generators stay seeded.

### 2.7 Tooling

Pytest with the repo's markers (`browser`, `integration`, `writtenahead`, `live`, …);
`scripts/test.sh` fast tier; Playwright sync API; `openpyxl` read-back (a test-only import of
the new runtime dep — acceptable, it is the same pinned package). File naming
`test_<lowercase-id>_<slug>.py`, case names `test_<id>_<snake_sentence>` with `_a/_b/_c`
arms; docstrings carry TC/FR traces and the "Markers." paragraph.

### 2.8 Contract-verification policy

- **Provider owns the clause suite.** `CT-AUTHOR-21…26` → authoring clause suite
  (`tests/artifact/`, provider side); `CT-CONSOLE-31…38` → console clause suite;
  `CT-UI-07…11` → UI clause suite (E6); `CT-CONF-24` → config clause suite. Each runs on
  every change to its module.
- **Doubles**: none of the four modules gained a test double this round; the rule stays "any
  future double runs the same clause suite".
- **`Requires` rows become pair cases**: M-CONSOLE→M-AUTHOR (TC-CONSOLE-61/62 drive the real
  service), M-CONSOLE→M-CONF (TC-CONF-24 via the console action), M-UI→CT-CONSOLE-37/38
  (TC-UI-16 renders live job records incl. an unknown-state fixture).
- **Blast-radius rule for CI**: a change to `M-AUTHOR` re-runs its clause suite + the console
  authoring-action cases + the E6 authoring journeys; a change to `M-CONF` re-runs the config
  clause suite + TC-CONSOLE-70 + the Settings E6 case; a change to the SPA bundle rebuild
  re-runs the whole E6 family. (Command form: `pytest -q tests/unit/authoring tests/artifact
  tests/e2e -k author`-style selections already express this.)
- **Compatibility**: every clause in this plan is additive to v1.0 contracts; a red clause
  suite is a design conversation, never a test edit (standing rule).

### 2.9 Entry / exit criteria

Entry: AF-14…21 generator + census land (T1); design delta approved. Exit: 100 % of P0
(RS-01/02/04/05/07/08/09) cases green in E1+E6, no open Critical/High, clause suites green,
fast tier green excluding known-baseline failures (diff against `main`'s four long-standing
reds — never a green-blind run), and the full-lifecycle journey green in **all four source
formats**.

---

## 3. Test cases

Case format: **ID · requirement · level/isolation · input (concrete) · oracle · expected**.
Negative and boundary cases are marked. Every case names its oracle.

### 3.1 Intake tier (M-AUTHOR) — E1

- **TC-AUTHOR-32** (FR-AUTHOR-24 / CT-AUTHOR-21) — *representation is format-independent.*
  Unit, rung 0. Input: AF-21's paired documents (same content as `.docx` and `.txt`).
  Oracle: normalized block-text sequences are equal after heading-level normalization.
  Expected: equal blocks; `source_format` differs, nothing else does.
- **TC-AUTHOR-33** (FR-AUTHOR-25) — *`.docx` rubric table carried.* Input: AF-14.
  Oracle: parsed structure. Expected: ≥1 `table` block whose cells match the fixture's
  `expected.toml` table rows; headings at their levels.
- **TC-AUTHOR-34** (FR-AUTHOR-25, negative-by-design) — *image/equation named, not lost.*
  Input: AF-15. Oracle: warnings list. Expected: `image_not_carried` and
  `equation_not_carried` warnings, each naming the nearest heading/ordinal location; block
  text otherwise intact. **RS-02.**
- **TC-AUTHOR-35** (FR-AUTHOR-26) — *cp1252 detected.* Input: AF-16. Oracle: warnings + text.
  Expected: `encoding_fallback` naming Windows-1252; accented characters render correctly in
  block text. **RS-01.** Boundary arm (`_b`): UTF-8 `.txt` produces no fallback warning.
- **TC-AUTHOR-36** (FR-AUTHOR-26) — *structure inference warns.* Input: AF-17. Expected:
  `structure_guessed` warnings on inferred headings; draft still builds.
- **TC-AUTHOR-37** (FR-AUTHOR-28 / CT-AUTHOR-23) — *refusal matrix.* Seven arms, each an
  exact fixture: (a) AF-18 legacy `.doc` → the save-as-.docx sentence; (b) AF-19 renamed
  `.txt`→`.docx` → the rename sentence; (c) password-protected `.docx` → remove-password
  sentence; (d) AF-20 empty file → no-text sentence; (e) oversize file (knob lowered via
  `HARNESS_AUTHOR_DOC_MAX_BYTES=1024`) → split sentence; (f) `.rtf` → the three-formats
  sentence; (g) `.docx` with a `.pdf` extension (magic mismatch) → the what-it-really-is
  sentence. Oracle: exception/refusal type + exact teacher sentence + **no provider call
  made** (assert via a provider call-count double at rung 1) + **no draft artefacts on disk**
  (temp dir listing empty). **RS-01/RS-12 adjacent.**
- **TC-AUTHOR-38** (FR-AUTHOR-23 across formats / RS-03) — *carry-over survives a format
  change.* Journey at rung 2: draft from AF-14 (`.docx`), answer two placeholders via
  `review(draft, answers=[…])`, re-draft from AF-21's `.txt` twin. Expected: both answers
  carry with `provisional` flags awaiting re-confirm; the report names them as kept. Boundary
  arm: a re-draft from *edited* content (one question reworded) carries only the matching
  item.
- **TC-AUTHOR-39** (FR-AUTHOR-29) — *from-scratch skeleton.* Expected: empty draft (zero
  questions/criteria), report marked created-empty with the editor next-step sentence, no
  placeholders.
- **TC-AUTHOR-40** (FR-AUTHOR-30 / CT-AUTHOR-24/25 / RS-12) — *observer and cancel.* Arms:
  (a) observer sees every stage, `done` monotone per stage; (b) cancel between steps →
  `AuthoringCancelled`, temp-dir draft == the pre-cancel state byte-for-byte (a prior valid
  draft is placed there first); (c) cancel checked but never true → completes normally.
- **TC-AUTHOR-41** (CT-AUTHOR-22) — *purity.* Same fixture twice → identical
  `NormalizedDocument` (deep-equal), and equal again after a locale shuffle in-process.
- **TC-AUTHOR-42** (CT-AUTHOR-26) — *warnings leak at most a sentence.* Oracle: string scan.
  Expected: no warning `message`/`detail` contains more than 200 characters or the full
  document text; a fixture containing a long paragraph near an image asserts the truncation
  boundary.

### 3.2 Console reads and actions (M-CONSOLE) — E1 rung 3 unless noted

- **TC-CONSOLE-59** (FR-CONSOLE-48 / CT-CONSOLE-38) — *context read.* Seeded store with 2
  classes, 3 cohorts, 2 packages, 2 runs. Oracle: JSON shape + enums from the declared sets.
  Expected: every entity with `state` in the declared enum; empty collections are empty lists,
  not null.
- **TC-CONSOLE-60** (FR-CONSOLE-49) — *impact read.* Arms: (a) package used by 2 runs covering
  48 students → `{runs: 2, students: 48}`; (b) never-published draft → zeros; (c) unknown
  version → refused with teacher detail. Oracle: exact JSON.
- **TC-CONSOLE-61** (FR-CONSOLE-61/52, CT-CONSOLE-32) — *draft job end-to-end.* Real
  `AuthoringService` + recorded provider. Expected: action returns job id immediately; jobs
  read shows `kind='authoring_draft'`, progress fields advancing; final state `succeeded`;
  **`rows_written == 0`** and store digest unchanged (RS-04); replay (same request twice)
  → same draft, byte-identical, single job completing.
- **TC-CONSOLE-62** (FR-CONSOLE-55 / ADR-45) — *answer authoring review.* Expected: draft on
  disk rewritten in place per answer; second concurrent action on the same draft refused
  ("A review of this draft is already open"); answers persist across a full server restart
  (process killed, reopened — the survival requirement).
- **TC-CONSOLE-63** (FR-CONSOLE-56) — *structured edit.* Arms: (a) add MCQ option → change
  list names the question; (b) reorder criteria → list reflects order; (c) invalid edit
  (empty question text) refused with field-level teacher message, draft unchanged on disk.
- **TC-CONSOLE-64** (FR-CONSOLE-62 / FR-PKG-28) — *approve gate.* Arms: (a) draft with 2
  placeholders → refused, the FR-PKG-28 sentence + locations; (b) resolved draft → published
  version appears in catalog; (c) replay → idempotent (no second version).
- **TC-CONSOLE-65** (FR-CONSOLE-53/54/63) — *class and cohort.* Arms: (a) create class from
  pasted 3-student list → class ledger rows exist (store digest); (b) cohort-from-class →
  roster + consent copied, class intact and reusable (second cohort allowed); (c) roster
  import preview → parsed rows shown, malformed rows listed with row numbers and reasons,
  commit only after preview confirm.
- **TC-CONSOLE-66** (FR-CONSOLE-58 / RS-15) — *workbook export.* Oracle: read-back with
  openpyxl. Expected: every graded student row present, values not formulas, matches store
  digest counts; boundary: a run with zero graded papers exports with headers only and a
  teacher note.
- **TC-CONSOLE-67** (FR-CONSOLE-59) — *readable PDF deterministic.* Same package version
  exported twice → byte-identical; content includes question text and grading guide in
  teacher form; no TOML syntax in the extracted text.
- **TC-CONSOLE-68** (FR-CONSOLE-51) — *issues and logs.* Seeded run with an ingest issue, an
  escalation and a quarantine. Expected: three issue records in teacher language with next
  actions; logs read contains only store-held stage records (a stage with no records shows
  nothing, not an empty placeholder claim).
- **TC-CONSOLE-69** (FR-CONSOLE-47) — *parked read.* Mirrors quarantine rows exactly (count,
  reasons); resolve action still routes through the existing quarantine resolution.
- **TC-CONSOLE-70** (FR-CONSOLE-57 / CT-CONSOLE-35) — *cancel semantics.* Arms: (a) cancel an
  authoring job mid-draft → job `cancelled`, draft dir intact (TC-AUTHOR-40's store-side
  twin); (b) cancel a run → only `run_control` rows written (store digest restricted to
  control table), run pauses as CT-ORCH-13 promises; (c) cancel a finished job → refused
  ("already finished") with next action.
- **TC-CONSOLE-71** (CT-CONSOLE-33 / RS-06) — *refusal shape.* Drive every refusing arm of
  TC-CONSOLE-60/63/64/70 + `_RefreshRequired` staleness. Oracle: response-body text scan.
  Expected: every body has teacher `detail` + `next_action`; **no HTTP status code, exception
  class name, or traceback fragment appears** (`\d{3}` status patterns, `Traceback`,
  `Error:` prefixes scanned).
- **TC-CONSOLE-72** (CT-CONSOLE-34 / RS-10) — *documents never leak.* Upload a document whose
  text carries a sentinel string; run draft + preview + upload. Oracle: captured console logs,
  every request URL/log line the browser made, full store sqlite text scan. Expected: sentinel
  appears only inside blob staging and the draft artifacts, never in a URL, a log line, or a
  store row.
- **TC-CONSOLE-73** (CT-CONSOLE-36, FR-PIPE-11) — *knobs and startup.* Arms: (a) knob refusal
  messages name knob/value/domain (`0`, `200 MB`); (b) `aeh console` banner prints
  `http://127.0.0.1:<port>/` + next step; (c) `HARNESS_CONSOLE_AUTO_OPEN=0` suppresses
  browser-open (asserted via a patched opener), default opens in interactive mode;
  (d) `serve_console()` never opens a browser.
- **TC-CONSOLE-75** (FR-CONSOLE-56 / FR-AUTHOR-11) — *inline regression, the edit round-trip
  stays parseable* (PR #794's shipped-defect findings 1 and 5, fixed in the follow-up).
  Arms: (a) a draft whose `[grades]` boundary is still a sentinel takes a structured edit:
  the rewritten file renders the floor **quoted** with its `# PLACEHOLDER(...)` reason
  comment above it (`FR-AUTHOR-11`), `tomllib` parses the result, and the sentinel survives
  for the next pass; (b) a textless edit is refused with the field's own name closing the
  clause ("the edit carries no text"), not the doubled word the shipped shape emitted.
- **TC-CONSOLE-76** (FR-CONSOLE-56 / FR-CONSOLE-48) — *inline regression, the draft read
  projects the table the grammar names* (PR #794's shipped-defect finding 2, fixed in
  #793's merge; pinned here so it stays fixed). Expected: `authoring_draft_read`'s `items`
  carry exactly the ids of the draft file's `[[question]]` tables — the grammar's singular
  key — and `projected.items` equals that count; the shipped `questions` spelling shrank
  every editor list to zero.

### 3.3 Configuration write path (M-CONF) — E1 rung 0/1

- **TC-CONF-24** (FR-CONF-34 / CT-CONF-24 / RS-07) — *atomic validated writes.* Arms:
  (a) valid edit (model for one role + cost ceiling) → next load reflects exactly those keys;
  (b) invalid edit (unknown model name) → refusal with the loader's message, file
  **byte-identical** (hash before/after); (c) mid-write interruption simulated (write hook
  raises after temp file, before replace) → original file intact; (d) secret key named in
  `edits` → refused, nothing written.
- **TC-CONF-25** (FR-CONF-35) — *projection.* Expected: every setting present with teacher
  label + type + editable flag; the editable set == FR-CONF-34's subset exactly; secrets
  project as `configured: true`, never a value; no file key names appear anywhere in the
  projection strings.

### 3.4 Help context (M-HELP) — E1 + E6

- **TC-HELP-06** (FR-HELP-06) — *context-aware ask.* Arms: (a) ask with
  `{screen: 'wizard-stage-3', refs: [draft_id]}` → answer references the review stage; (b) the
  context payload never contains student text (RS-14 — capture the assembled provider prompt
  and scan it); (c) no-context ask byte-identical in behavior to today (recorded replay
  unchanged).

### 3.5 SPA screens (M-UI) — E6 browser

All use role/accessible-name locators only; loaded screen = `main` landmark + level-1
heading; `problems` accumulator + `_fail_with`; store digests where state is asserted.

- **TC-UI-08** (FR-UI-09) — *wizard stepper.* Arms seeded to hit each state: (a) fresh store →
  stage 1 next; (b) draft with 2 placeholders → stage 3 `needs attention` naming the count;
  (c) mid-run → stage 7 in-progress with criterion-batch counts; (d) graded run → stage 8
  done, NEXT = export. NEXT/IMPACT lines match the seeded facts (impact read numbers).
- **TC-UI-09** (FR-UI-10) — *context header.* Switch class → wizard rows re-derive; switch
  run → navigates to stage 7; assert **no POST occurred** during switching (request log).
- **TC-UI-10** (FR-UI-11) — *from documents.* Arms: (a) happy upload → preview shows outline
  + warnings before any commit; (b) AF-18 dropped → refusal card with next step, other file
  unaffected; (c) drafting job progress renders stage/done/total; cancel button present.
- **TC-UI-11** (FR-UI-12) — *review draft.* Arms: (a) placeholders listed with locations,
  approval blocked with the count; (b) answer one → it leaves the list, reload → still
  answered (survival in the browser); (c) re-draft confirm copy names carry-over in teacher
  language (RS-03).
- **TC-UI-12** (FR-UI-13) — *editor.* Arms: (a) add/edit/reorder via forms, validation next to
  field on invalid input; (b) save → change list in teacher language → confirm → applied;
  (c) edit a published package → impact banner with run/student counts (TC-CONSOLE-60's
  numbers rendered) + confirm; (d) from-scratch entry opens the same editor over an empty
  draft.
- **TC-UI-13** (FR-UI-14) — *state model.* Injected failures (job fails, stale read, upload
  refusal): failure renders as banner with what/why/**one-click retry or fix**; success
  actions toast; field errors inline. Assert template shape on each.
- **TC-UI-14** (FR-UI-15/16/17 / RS-09) — *results and override.* Arms: (a) overview: SVG
  distribution bars labelled with counts, flagged items link through; (b) drill-down:
  justification = score-reason + evidence quotes; Details expander holds judge trail +
  per-student log panel; (c) override: band select + **required reason**; refuse without
  reason; after confirm the store shows an appended amendment row, original intact (digest).
- **TC-UI-15** (FR-UI-18) — *issues and logs pages.* Seeded run's issues render as cards with
  next-step buttons that navigate correctly; logs timeline lists only the seeded stages.
- **TC-UI-16** (FR-UI-19 / RS-05) — *parked and jobs pages.* Arms: (a) parked cards with
  reasons + resolve/reupload; (b) jobs table renders live authoring job fields
  (CT-CONSOLE-37) incl. elapsed and cost format; (c) an unknown `state` value (injected) →
  neutral "needs attention" label, no error (CT-CONSOLE-38's SPA half); (d) progress shows
  exactly the server's counts — a seeded run with known batch counts renders "14 of 40" style
  figures and **never a per-student count or percentage** (RS-05).
- **TC-UI-17** (FR-UI-20) — *settings.* All projected settings visible; editable subset
  renders forms; a save round-trips through `update configuration`; secrets show
  "configured ✓" only; non-editable rows render values read-only.
- **TC-UI-18** (FR-UI-21) — *help everywhere.* Panel opens on each of the six secondary pages
  and the wizard; context ask answers about the current screen (TC-HELP-06's (a) from the
  browser); manuals link through.
- **TC-UI-19** (CT-UI-09 / RS-11) — *no confirm-free posts.* Walk every select/toggle
  introduced by this redesign (band selects, switchers, job rows, parked actions): change
  each → assert no mutation request until an explicit confirm/submit (request log). Includes
  the Phase-1 blind-sample defect's generalized regression.
- **TC-UI-20** (CT-UI-10) — *state rendering pairs.* Every StateBadge usage renders icon +
  text + colour; computed contrast of token pairs meets AA (a static token audit asserts the
  ratios; a browser arm asserts badge DOM shape).
- **TC-UI-21** (CT-UI-11 / RS-13) — *budgets.* FCP ≤ 2000 ms, transition ≤ 300 ms on the new
  bundle (existing E6 budget mechanism).

### 3.6 Vocabulary and the acceptance journeys — E6

- **TC-CONSOLE-74** (CT-CONSOLE-31 / NFR-CONSOLE-10 / RS-08) — *vocabulary scan, exhaustive.*
  Visit **every** teacher screen (16 SPA routes + the teacher-reachable server-rendered
  screens) and scan rendered text for: TOML/JSON/YAML syntax tokens, store path fragments,
  `pkg-`/`ref-sub-`/`CRIT-`/`Q\d` raw id patterns, HTTP status codes, module names
  (`M-`-prefixed), config key names. Oracle: the forbidden-term list maintained as a test
  constant mirroring §3.3.3's left column. Expected: zero hits. This is the R0 oracle.
- **TC-E2E-08** — *full lifecycle, single `.docx`.* Fresh store → create class (typed) →
  cohort → upload AF-14 → preview → draft (recorded) → placeholders answered → editor edit →
  approve → upload papers (world fixtures) → preflight → start run → progress → results →
  justification → override with reason → exports (CSV + workbook + readable PDF + backup).
  Asserts: every stage's wizard state flips; **no raw TOML/JSON on any visited screen**
  (TC-CONSOLE-74's list applied to the visited set); store digest matches the same journey's
  digest via the CLI path modulo authoring (the console-authored draft is
  CLI-indistinguishable, ADR-45).
- **TC-E2E-09** — same journey, single `.txt` (AF-17's shape; outline-guessing confirmed in
  review).
- **TC-E2E-10** — same journey, single PDF (existing authoring fixture family).
- **TC-E2E-11** — same journey, mixed pair (AF-21: `.docx` test + `.txt` memo).
- **TC-E2E-12** — *reload survival.* Mid-drafting and mid-review: reload at each; progress
  re-attaches from the server (RS-05's positive twin); answered placeholders survive;
  **server restart** between review answers also survives (TC-CONSOLE-62's browser twin).
- **TC-E2E-13** (nightly, `live`) — the four journeys against the real provider; skips
  cleanly without the key; asserts the same user-visible behavior; no recording write.

### 3.7 Requirement-level cases

- **TC-REQ-137** (R1) — *stage-state derivation table.* For each row of the design delta's
  derivation table (§3.3.4), a seeded store state whose derived wizard states are asserted
  exactly (spans reads + UI; the UI arms are TC-UI-08's, this is the derivation-matrix
  completeness case at rung 3).
- **TC-REQ-138** (R0) — *vocabulary map synchronization.* The forbidden-term test constant
  and the design's vocabulary-map left column are parsed from the design delta itself and
  asserted equal — the map cannot drift from the scan silently.
- **TC-REQ-139** (R3) — *progress honesty across a full run.* Replay a seeded run in the
  browser, snapshotting progress rendering at each stage: every rendered count matches the
  store's stage/criterion-batch facts at that moment; no percentage or student-count appears
  anywhere (RS-05's journey-level sweep).

---

## 4. Cross-cutting suites

### 4.1 Contract clause walk (every new clause → the case that fails if it is violated)

| Clause | Kind | Case that catches a violation |
|---|---|---|
| CT-AUTHOR-21 | data | TC-AUTHOR-32 (format-independence) |
| CT-AUTHOR-22 | behaviour | TC-AUTHOR-41 (purity/determinism — double-run equality) |
| CT-AUTHOR-23 | error | TC-AUTHOR-37 (refusal before provider call, no artefacts) |
| CT-AUTHOR-24 | behaviour | TC-AUTHOR-40b / TC-CONSOLE-70a (cancel leaves prior draft intact) |
| CT-AUTHOR-25 | observe | TC-AUTHOR-40a (observer stages + monotone `done`) |
| CT-AUTHOR-26 | security | TC-AUTHOR-42 (warning text bounded) |
| CT-CONSOLE-31 | security | TC-CONSOLE-74 (exhaustive screen scan — TC-REQ-138 keeps the term list honest) |
| CT-CONSOLE-32 | state | TC-CONSOLE-61 (rows_written == 0, digest unchanged, replay idempotent) |
| CT-CONSOLE-33 | error | TC-CONSOLE-71 (refusal-shape scan over every refusing arm) |
| CT-CONSOLE-34 | security | TC-CONSOLE-72 (sentinel scan over URLs/logs/store) |
| CT-CONSOLE-35 | behaviour | TC-CONSOLE-70a/b (cancel semantics both kinds) |
| CT-CONSOLE-36 | config | TC-CONSOLE-73a (knob defaults + refusal messages) |
| CT-CONSOLE-37 | observe | TC-UI-16b (SPA renders the exact job fields) |
| CT-CONSOLE-38 | data | TC-CONSOLE-59 + TC-UI-16c (declared enums; unknown → neutral label) |
| CT-UI-07 | security | TC-HELP-06b + TC-CONSOLE-72 (context payload + URL/storage scan) |
| CT-UI-08 | observe | TC-REQ-139 + TC-UI-16d (no fabricated counts) |
| CT-UI-09 | behaviour | TC-UI-19 (no confirm-free posts, interaction matrix) |
| CT-UI-10 | data | TC-UI-20 (icon+text+colour pairing, token contrast audit) |
| CT-UI-11 | perf | TC-UI-21 (budgets at stated load: full bundle, seeded store) |
| CT-CONF-24 | config/state | TC-CONF-24 (atomicity + byte-identical refusal) |

Clause-suite ownership per §2.8; the double-conformance rule has no doubles to bind this
round.

### 4.2 Regression sets (blast-radius)

- **Console invariant set** (runs on every console change): the existing CT-CONSOLE-01…30
  suites, plus TC-CONSOLE-71/72/74 as the new permanent members — the three clauses most
  likely to be eroded one small change at a time.
- **Authoring regression set**: existing TC-AUTHOR-01…31 suites plus the intake family;
  the CLI draft/review/re-draft flows must stay green **unmodified** (the existing authoring
  suites, TC-AUTHOR-01…31) — the console path adds, never changes, the terminal surface
  (NFR-CONSOLE-09).
- **Grade-integrity set**: every override/amendment case re-runs the append-only audit
  suites (#103's `grade_superseded_at_and_append_only`, `grade_audit_record_append_only`)
  — RS-09's tripwire.
- **Bundle rebuild set**: any SPA source change re-runs the byte-identity bundle gate and
  the full E6 family (the bundle is the product; source-only green proves nothing).

### 4.3 Property suites

- **Determinism property** (TC-AUTHOR-41 generalized): for each AF fixture, intake run twice
  → deep-equal output; 20 random doc orderings of AF-21's set → the *same* multiset of
  blocks and warnings (order-independent intake).
- **Refusal completeness property**: for every FR-AUTHOR-28 row, the emitted sentence is the
  teacher sentence from the design table — asserted by exact match, so copy drift fails.

---

## 5. Fixture inventory (delta)

| Fixture | Purpose | Used by |
|---|---|---|
| AF-14…AF-20 | intake matrix per design delta §5.1 | TC-AUTHOR-33…37, journeys |
| AF-21 (+ `.txt` twin of AF-14) | mixed-format set + cross-format carry-over | TC-AUTHOR-32/38, TC-E2E-11 |
| Roster CSVs (valid + malformed ×3) | class/cohort/roster actions | TC-CONSOLE-65 |
| Malformed/upload adversarial set (renamed, password-protected, empty, oversize) | refusal matrix | TC-AUTHOR-37 |
| Recording set for the four journeys | E6 replay | TC-E2E-08…12 (captured by implementing stories; honesty census extended) |

All generated by the in-tree stdlib generator; byte-reproducible; census-pinned (the
TC-AUTHOR-28 mechanism extended to the new fixtures). New recordings captured, never
fabricated — the corpus README documents the capture command per journey.

## 6. §8.2 — test-story table

Every `type:story` in the design delta has ≥1 `type:test` story here (RTM check at
`/plan-to-issues`). "Ahead" = written ahead of implementation, red by design with
`@pytest.mark.writtenahead` + `WRITTEN_AHEAD_BLOCKERS` registration (§8.2's red-by-design
rule; markers removed as implementing stories close, tests never deleted).

| Story | Title | TC IDs | Level | Depends on (stories) | Ahead |
|---|---|---|---|---|---|
| T1 | Intake corpus AF-14…21 + generator/census extension | TC-AUTHOR-32…38 (fixture halves), census | artifact | — | **yes** |
| T2 | Intake unit suite (representation, matrix, carry-over, cancel) | TC-AUTHOR-32…42 | unit | T1, S1/S2 | no |
| T3 | Console reads/actions suite (context→cancel, refusal shape, leak scan) | TC-CONSOLE-59…73 | integration (rung 3) | S3/S4/S5/S7/S8 | no |
| T4 | Config write-path suite | TC-CONF-24/25 | unit | S6 | no |
| T5 | Help context suite | TC-HELP-06 | unit+integration | S9 | no |
| T6 | SPA screens suite (wizard→help) | TC-UI-08…21 | browser (E6) | S10–S13, T2/T3 | no |
| T7 | Acceptance journeys per format + reload survival | TC-E2E-08…12 | browser (E6) | T6, recordings | no |
| T8 | Vocabulary + honesty sweeps (scan, derivation, progress truth) | TC-CONSOLE-74, TC-REQ-137…139 | browser+integration | T6 | no |
| T9 | Nightly live journeys | TC-E2E-13 | live | T7 | no |

Code stories (from the design delta, for the dependency graph):

| Story | Title | Traces to | Depends on |
|---|---|---|---|
| S1 | Intake tier: normalization + `.docx`/`.txt`/PDF unification + refusals | FR-AUTHOR-24…28, ADR-46 | — |
| S2 | AuthoringService observer/cancel/from-scratch | FR-AUTHOR-29/30 | S1 |
| S3 | Console reads: context, impact, issues, logs, parked, config, authoring | FR-CONSOLE-47…52/60 | — |
| S4 | Console authoring actions + jobs registry | FR-CONSOLE-55/56/61/62, ADR-45/47 | S2, S3 |
| S5 | Console class/cohort/roster actions | FR-CONSOLE-53/54/63, ADR-48 | S3 |
| S6 | M-CONF guided write path + projection | FR-CONF-34/35, CT-CONF-24 | — |
| S7 | Console exports: workbook + readable PDF (deps ADR-49) | FR-CONSOLE-58/59 | S3 |
| S8 | Startup URL + auto-open | FR-PIPE-11 | — |
| S9 | Help context-aware ask | FR-HELP-06 | — |
| S10 | SPA shell: sidebar, stepper, context header | FR-UI-09/10 | S3 |
| S11 | SPA authoring screens: upload/preview, review, editor | FR-UI-11/12/13 | S4, S10 |
| S12 | SPA state model + results + override | FR-UI-14…17 | S10 |
| S13 | SPA secondary pages + settings + help panel | FR-UI-18…21 | S3/S6/S10 |
| S14 | Bundle rebuild + parity census + dependency admission (ADR-49) | NFR-CONSOLE-10, CT-CONSOLE-31 | S10–S13 |

## 7. What passing this plan does not prove

- **The journeys prove the recorded path.** Live-model behavior (wording of model-drafted
  content, real latency) is only nightly-sampled (T9); a live failure mode the recordings
  never exercised can still exist.
- **Vocabulary-clean is screen-instantiated.** TC-CONSOLE-74 scans every current teacher
  screen; a future screen must be added to the walk by convention, not by enforcement —
  the census cannot catch a screen it was never taught.
- **Usability is not tested.** Nothing here proves a teacher *finds* the next action — only
  that the console states it. Phase-1's confusion list is a design input, not a test oracle.
- **Cost figures are format-checked, not verified.** The ledger's correctness belongs to
  M-PROV's existing suites; the Jobs page only proves display.
- **Performance is budget-level.** FCP/transition at seeded-store scale on the E6 runner;
  classroom-hardware throughput (NFR-AUTHOR-07's 20-document bound) is asserted at unit
  scale with `Assumption:` hardware, not measured on real classroom machines.
- **Known reds persist.** The fast tier still carries `main`'s four long-standing baseline
  failures; this plan's cases are green *on top of that baseline*, never instead of it —
  always diff failure sets against `main`.