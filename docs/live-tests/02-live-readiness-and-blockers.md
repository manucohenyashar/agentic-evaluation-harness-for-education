# Live-test readiness: what is still open, and the proof

*Read this before you schedule the first live teacher test. This page lists only what is still unresolved. Blockers that were closed survive as one-line entries in the register below, so the documents and tests that cite their IDs still resolve; the detail lives in the repository's history and the cases named.*

## The verdict

**A supervised OpenRouter test can be run with the shipped commands, with an engineer beside the operator.** The code paths exist for `aeh cohort create`, package publication, `aeh ingest` (the V0–V4 intake checks), `aeh run`, and `aeh results show` / `export`. Real OpenRouter calls have verified the request formats, and the 2026-10-12 authoring walk drafted and published a teacher's package, ingested a generated sheet, and completed a one-student run. That is not an end-to-end live pass of both sample classes: the run exposed citation refusals that left grades provisional and a decision-engine failure before dispatch. Record those outcomes; do not describe the live test as passed.

The console is now the teacher-facing SPA for the whole day: class setup, package authoring, reading the papers, run control, review, blind sampling, finalization, amendments and the results downloads ([05](05-console-teacher-walk.md)). The remaining operator-facing gaps are precise: the console is started from a terminal with the key and settings, and parked-paper resolution does not record a selected student, mark or test. The browser path was checked offline on 2026-10-18, not yet against real OpenRouter. The older S1–S14 pages remain separate operator/audit reads, with their own limitations.

What is still open falls into three groups:

* **Teacher-independent operation:** the SPA does not record the operator's full parked-paper decision (B8), and the console's start needs the operator's terminal once.
* **What further live runs can settle:** handwriting, class-scale cost and speed, the Jev decision engine, judge citation reliability, and the observed behavior of pause/resume during a live run.
* **Other recorded gaps:** the creator of a cohort, the local model name, and whether the model uses each field's `name`.

## Closed blockers, kept for the citations

* **B1 — no shipped path both called OpenRouter and allowed the console. Closed 2026-10-03.** `aeh run` and the console's start-run grade through OpenRouter under `dev-ci` (`HARNESS_FIXTURE_DIR` set selects recordings, the test tier), the command prints a `provider:` line naming what will answer, and the console still refuses `cloud-hosted` on purpose. Cases `TC-PIPE-24` to `TC-PIPE-26` (`tests/unit/pipe/test_openrouter_launch.py`).
* **B2 — the request was not the usual chat format. Closed 2026-10-03.** The provider sends the standard chat shape, the plain slug, names refusals in OpenRouter's own words, and explains an empty answer from a reasoning model; checked with the real calls above. Cases `TC-PROV-60` to `TC-PROV-63`. Its leftovers are open gaps below.
* **B3 — nothing created a cohort, its consent class or its roster. Closed 2026-10-03.** `aeh cohort create`, `add-students` and `show`; cases `TC-ORCH-59`, `TC-ORCH-60`. Since 2026-10-18 the SPA's Classes screen creates a class (typed or from a class list file, previewed before it is written) and adds late students, through the same door.
* **B5 — the teacher's package-setup path did not exist. Closed by the console authoring flow.** The SPA now accepts PDF, DOCX and TXT source documents, drafts a package, presents unresolved items for review/editing, and publishes through the package build gate. `aeh package build --spec` remains the developer/system-emitted TOML-spec route; the legacy S3/S4 read-back limitations below apply only to those older pages, not to the SPA's authoring flow.
* **B6 — the privacy check had no known answer format. Closed 2026-10-03.** Every request carries `"provider": {"zdr": true, "data_collection": "deny"}`, so OpenRouter routes it only to a host that keeps no copy and does not train on it, or refuses it (`HTTP 404 ... No endpoints found matching your data policy`, which pauses the run). Case `TC-PROV-64`.

## The open gaps

### B4. SPA scan upload reaches intake — closed 2026-10-18, live use unverified

`aeh ingest` remains the operator's paper-reading path: the test paper once per class, and answer sheets through the intake checks, parking every paper that fails (`src/aeh/pipeline/intake.py`). Under `dev-ci`, page-reading requests go to OpenRouter with zero data retention enforced, and the consent gate refuses a `real` cohort before sending work. Re-running skips scans already read into the cohort. A read cut off by Ctrl-C is handled by the next `aeh ingest` (`TC-PIPE-32`). The 2026-10-12 live authoring pass cleared a generated typed sheet through intake; real handwritten pages and class-scale reading remain unverified.

Browser intake now exists. The SPA's Papers inbox uploads the test paper and the answer sheets; each upload asks to be read (`POST /api/v1/uploads?read=1`), is refused before a byte is stored when the class, the test version or the class's consent does not allow it, and is otherwise queued for a per-class reading job on the console's own worker. The job reassembles the staged chunks (so an upload over 4 MiB is read whole) and calls `ingest_files` — the `aeh ingest` door — so the page reader, the five checks, the skip of a sheet already read and the parking are the command's own. Progress is on the Papers inbox and the Jobs screen. Case `TC-CONSOLE-77` (`tests/unit/console/test_tc_console_77_papers_upload_reads.py`) drives it over the sample physics sheets through the real `OpenRouterProvider` to a stand-in OpenRouter.

Still true:

* Page-reading calls happen before a run exists, so they are not counted against a run's cost ceiling. OpenRouter's own spending limit remains the spending stop.
* The browser path has not been used against real OpenRouter yet; the first live use is a finding to record.

### Package setup: teacher flow shipped; legacy S3/S4 remain limited

The teacher's package path is the SPA authoring flow: upload the source documents as PDF, DOCX or TXT, preview the extracted content, start the draft job, resolve or edit open items, then approve and publish. Authoring requires a configured profile. The console's package screens do not use the old S3/S4 confirmation route. The terminal `aeh author draft` / `aeh author review` and `aeh package build --spec` paths remain available for operator, developer and system-emitted use.

The older server-rendered pages are a separate operator/audit surface. S3 can render a package's question inventory when addressed to that package; S4 is count-only for answer keys. Those limitations do not imply the teacher's SPA authoring path is missing. Class creation and browser intake, the gaps once listed here, shipped on 2026-10-18.

### B7. Distinguish the teacher SPA from the legacy S1–S14 pages

The console now has two different surfaces. The SPA is the teacher workflow, with controls for package authoring/approval, run start and monitoring, review, blind sampling, finalization, grade amendment, and parked-paper resolution. The server-rendered S1–S14 pages remain separate operator/audit reads; do not infer SPA limitations from them or describe all console pages as read-only.

Known limitations of the legacy pages include:

* **S1** needs a package-version address and shows a limited package card, not a teacher authoring flow. **S3** can list questions when addressed to the package. **S4** remains count-only for answer keys.
* **S10 and S11** are fixed explanatory text and do not show drawn submissions. The blind sample screen exists in the SPA at `/#/review/blind`, shows the drawn seats and offers each seat's own declared levels from the package; submissions outside the draw are refused.
* **S8** shows parked IDs and stored crops but not the reason; the SPA Parked screen shows the reason, match note and available release/close choices. Neither surface stores the selected student, mark or test (B8).
* **S13** remains limited compared with the SPA student-results view, which shows narrative feedback and band information.
* **S12 and S7** are not the cost view; the SPA Jobs screen displays each draft/run job's progress and cost so far. The SPA finalize and amend flows write through the enumerated controls; they are not the legacy pages' audit rendering.
* Legacy band selectors remain generic/inert; the SPA grade-amendment form and the SPA blind-sample screen both use the package's rubric levels.

**Still needed for teacher-independent operation:** a full parked-decision record (B8). The SPA supports the grading day end to end; the operator starts the console once.

### B8 (remaining). Resolving a parked paper still does not record the decision

`resolve-quarantine-item` now refuses any word other than `matched` or `unresolvable` (a typo no longer closes a paper by accident), and `matched` is refused for a paper whose student the identity check (V3) did not match — such a paper is closed, or rescanned with the ID written on it and read in again with `aeh ingest` (`TC-CONSOLE-51`, `TC-CONSOLE-52`, over the sample sheets parked by the real intake checks).

What is still missing is the record itself. Nothing stores **which student** a nameless paper belongs to, **which tick** a doubled mark was, or **which test** a wrong-test paper is for: the operator can release or close the three awkward sample sheets, but cannot tell the system the answer. The console's writable surface for this action is exactly `submission.ingest_status` and `submission.quarantined` (FR-CONSOLE-32); a corrected mark would change an immutable document, and an audit record needs a migration — so this is a design decision for `/detailed-design-generator`, not a quick fix.

## The small gaps, and what only a live run can settle

| Still open | What it is | How to close it |
|---|---|---|
| Real handwriting | The sample sheets are typed; no page-reading model has read a real scanned page | Add two or three hand-written, scanned sheets to the first live run |
| Whether the model uses each field's `name` | Many open models' chat templates drop it, so the model may see each field's value without its field name; the judge's and extractor's values carry their own labels (`criterion_id: …`), but some setup and synthesis values do not | One recorded comparison per model family on the first run |
| The local model server is sent the whole weights-path `build_id` as `model` | Servers such as Ollama, llama.cpp and vLLM usually want the name they serve the model under (deployment tutorial, section 6.5) | Decide and implement a mapping, or document the server requirement |
| A model with no zero-retention host is found at its first call, not at run start | The run-start privacy gate sends no request; the run pauses at the first call, having sent nothing to a retaining host | Read the first live run's behaviour; consider a pre-run check |
| The cohort's creator is not recorded | Only the time is stored | A schema migration, with the next cohort work |
| Resuming a paused run from the console | The SPA Jobs screen offers Pause and Resume controls; each queues a request for the orchestrator. A live pause/resume round trip has not yet been measured during the real OpenRouter run. | Exercise both controls during the next supervised live run and record the time to resume |
| The Jev decision engine | The config pins its build (`openrouter/typesafe/jev-1.13@2026-09-17`), but that pin has not answered a real call yet | The live acceptance (`TC-CONFORM-17/18`) exercises the Jev leg on the nightly; read the per-criterion accept/fallback rates and band agreement off its report |
| Real cost and real run time at class scale | One supervised one-student run happened on 2026-10-12; its integration record reports $0.154447, but the duration was not recorded in a durable run record. No class-scale run has happened. | Measure cost and elapsed time off the first supervised class run, using the cost ceiling as the guard |

## Found on the first live run (2026-10-09) and fixed: the page reader's markup parked every sheet

**What happened.** The first live physics intake (`gpt-6-luna` reading the six PS9 sheets) parked all six. The model read the pages correctly. Its markup, though, was not in the shape the intake checks read:
* it wrote one mark region per printed option (`[ ] A`, `[X] C`, …) with no `selection=`, so every tick was stored as unreadable;
* it left the written answers untagged;
* it called question 5's parts `Q5` instead of the package's `Q5a`/`Q5b`.

The prompt (v4) never asked for any of those, and the page request never named the package's question ids. Every stand-in for the model returned perfect markup whatever it was asked, so the offline check could not catch it.

**The fix** (`ingest-transcribe-v5`):
* The prompt states the rules: one mark region per multiple-choice question with `selection=<letter>`, and `question_id=` on every answer.
* Every page request names the package's questions and their option letters (`declared_questions`).
* The intake also reads a run of tick boxes written one per option as the single mark it describes: one ticked box is the answer, two or more is a double mark, none is blank. The stage detail records this as `folded_option_marks`.
* The stand-ins now check that each page request states the rules and names the questions.

**The second live run (v5)** confirmed the reader now writes exactly that markup. It also exposed a knock-on effect: the test paper's regions carry no question tags, so the right-test check fell back to comparing the whole test paper with only the sheet's *tagged answers*. Good sheets scored 0.02–0.07, under the 0.10 floor. That fallback now compares the whole sheet with the whole paper: good sheets score 0.28–0.35 and the wrong test 0.03.

On both runs the reader also **misread the printed test name on one sheet of six** (`S9-FORCES-01`, `PS9-FORCE-01`). The gate deliberately stays strict, so such a sheet parks as `uncertain` for the operator to confirm. Expect it, and record it as a reading error.

Regression cases: `TC-REG-15`, `TC-INGEST-56`, `TC-INGEST-57`. `TC-REG-15` includes a live case, run with a key set.

## Found on the third live run (2026-10-10) and fixed: inline headers, and reply formats nobody stated

* **Headers on the same line as their region marker.** On S9-005 the reader wrote `<!-- region: … -->Assessment: ENG7-READ-01<!-- /region -->`. The header readers only looked at the start of a line, so the sheet seemed to name no test and no student. It was parked as `incomplete` ("no student identity found") instead of `unmatched_assessment`. The same parse decides what is redacted, so the written name also reached a model unredacted. Both are fixed; the readers accept a marker on either side (`TC-INGEST-58`).
* **The extractor and the judge were never told the reply format.** The extraction prompt said only "Reply with the byte offsets…", and the live model answered in prose, so every written answer failed to extract and the run stalled with no grades. The judge prompt said "the reply fields in their pinned order" but never named them. Both prompts now state the exact JSON (`extract-prompt/3`, `judge-prompt/3`). The extract, judge and synthesis parsers also accept JSON wrapped in a code fence or after a sentence. Prose is still refused. Regression case: `TC-REG-16`.

**Result of a fresh live pass with both fixes (`Data\aeh-live-2`).** Intake gave exactly the guide's outcome (3 `ok`; S9-004, S9-006 `incomplete`; S9-005 `unmatched_assessment`). The run reached `complete`. S9-001 scored **10 / A** and S9-002 **7 / B**, both exactly as expected. S9-003 is missing its Q4 mark (2 so far, against the expected 3 / D).

**gpt-6-luna misreads identifiers often.** Over four live intakes it misread the printed test name on one or two sheets of six each time (`S9-FORCES-01`, `PS9-FORCE-01`, `P9-FORCES-01`), and once a written student ID (`PS9-002` for `S9-002`). The gates park each one for the operator rather than guess, which is correct, but it means extra operator work on every class. On the latest run two sheets of six were misread, so the live check `TC-REG-15` failed its one-in-six limit. Consider comparing reader models on this before the teacher test.

**Still open: model-counted byte offsets are not reliable.** The extractor now quotes the right passage, but the offsets it gives point a little earlier in the transcript, and the system derives the evidence text from the offsets. S9-003's Q4 was not graded because the judge cited a range that failed the exact-match check. A likely fix is to locate the quoted passage in the transcript instead of trusting the counted offsets. That is a design decision, still to be made. Re-run the live test in a **new** data folder: one that was already read skips its sheets and keeps the old transcripts.

## A risk to plan around, not a blocker: right-test check can park good papers

The right-test gate (V4) compares the words in a student's answers with the words in the question. Its floor is `0.10` (`HARNESS_INGEST_V4_SEMANTIC_FLOOR`). If the page reader returns **only** the handwriting for each answer, most good papers score `0.00` to `0.04` and are **parked**. Reproduce it with `python docs/live-tests/sample-materials/verify_sample_materials.py --answers-only`: in that mode six of the seven good sheets are parked as `unmatched_assessment` (the seventh, `E7-001`, passes at `0.108`, just over the floor), and the two sheets that should have been `incomplete` also come out as `unmatched_assessment`. If the answer sheet reprints each question and the reader transcribes the page verbatim, the same papers score `0.24` to `0.93` and pass (the ten sample sheets, as an ideal reader would return them). So:

* print the question above each answer space, as the sample sheets do;
* expect good papers to land in quarantine on the first test if the reader drops the printed question, and treat that as information, not failure;
* the floor is a knob, but lowering it weakens the wrong-test check (the printed test name and the question layout still catch the wrong-test sheets).

## Remaining work, in order

These are checkable goals for future backlog planning; issues are created only through `/plan-to-issues`.

1. **Record the operator's decision (B8).** *Goal:* resolving a parked paper stores the selected student, corrected mark or correct test in the audit trail where applicable.
2. **Live use of the console path.** *Goal:* run [05](05-console-teacher-walk.md) against real OpenRouter and record each step's outcome; browser scan intake, class setup and the downloads shipped on 2026-10-18 and were checked offline only.
3. **Live-operation evidence.** *Goal:* record a supervised live pause/resume cycle, class-scale cost and duration, handwriting intake, and Jev behavior; investigate the citation-verification refusals before treating the authoring walk as a successful live grading demonstration.

Item 1 is the remaining workflow gap for teacher-independent operation. Package authoring, run controls, review, blind sampling and finalization have shipped; do not re-list them as future console work.
