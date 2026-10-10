# Live-test readiness: what is still open, and the proof

*Read this before you schedule the first live teacher test. This page lists only what is still unresolved. Blockers that were closed survive as one-line entries in the register below, so the documents and tests that cite their IDs still resolve; the detail lives in the repository's history and the cases named.*

## The verdict

**A supervised live grading test through OpenRouter can be run today with the shipped commands, with an engineer beside the operator.** The whole command-line path exists and was exercised: `aeh cohort create` makes the class with its consent class and roster, `aeh package build` builds and publishes the test, `aeh ingest` reads the scans through the real intake checks (V0–V4), `aeh run` grades through OpenRouter with zero data retention enforced on every request, and `aeh results show` / `export` read the grades back. The provider's request format was checked with real OpenRouter calls (2026-10-03): a one-field call, a judge-style three-field call, and a page image to the vision model all succeeded.

What is still open falls into three groups:

* **The console is behind the guides** — a teacher cannot yet operate it alone (B4's remainder, B5's remainder, B7, B8's remainder).
* **What only a real live run can settle** — handwriting, real cost and speed, the Jev decision engine, resume-from-console.
* **Three small recorded-decision gaps** — the creator of a cohort, the local model name, the field `name` question.

## Closed blockers, kept for the citations

* **B1 — no shipped path both called OpenRouter and allowed the console. Closed 2026-10-03.** `aeh run` and the console's start-run grade through OpenRouter under `dev-ci` (`HARNESS_FIXTURE_DIR` set selects recordings, the test tier), the command prints a `provider:` line naming what will answer, and the console still refuses `cloud-hosted` on purpose. Cases `TC-PIPE-24` to `TC-PIPE-26` (`tests/unit/pipe/test_openrouter_launch.py`).
* **B2 — the request was not the usual chat format. Closed 2026-10-03.** The provider sends the standard chat shape, the plain slug, names refusals in OpenRouter's own words, and explains an empty answer from a reasoning model; checked with the real calls above. Cases `TC-PROV-60` to `TC-PROV-63`. Its leftovers are open gaps below.
* **B3 — nothing created a cohort, its consent class or its roster. Closed 2026-10-03.** `aeh cohort create`, `add-students` and `show`; cases `TC-ORCH-59`, `TC-ORCH-60`. One leftover below.
* **B6 — the privacy check had no known answer format. Closed 2026-10-03.** Every request carries `"provider": {"zdr": true, "data_collection": "deny"}`, so OpenRouter routes it only to a host that keeps no copy and does not train on it, or refuses it (`HTTP 404 ... No endpoints found matching your data policy`, which pauses the run). Case `TC-PROV-64`. One leftover below.

## The open gaps

### B4 (remaining). Console uploads are stored but never read

`aeh ingest` is the operator's way to read papers: the test paper once per class, the answer sheets as one PDF per student, through the intake checks, parking every paper that fails a check (`src/aeh/pipeline/intake.py`). Under `dev-ci` the pages go to OpenRouter with zero data retention enforced, and the consent gate refuses a `real` cohort before any page is sent. A re-run skips every scan already read into the cohort, so no paper is graded twice; a read cut off by Ctrl-C is parked in quarantine by the next `aeh ingest` (`TC-PIPE-32`). Checked over the six physics sample sheets against a stand-in OpenRouter (`TC-PIPE-30`, `TC-PIPE-31`); **not checked: a real vision model reading real pages** — whether it writes the region markup the checks parse is what the first live run shows.

What is still missing is the console side:

* **The `/upload` page stores files and stops there.** Nothing shipped reads an upload; the intake step runs only from `aeh ingest`.
* **An upload over 4 MiB cannot even be reassembled.** Each 4 MiB chunk is stored as a separate blob and only the first chunk is recorded.
* Page-reading calls cost money but are not counted against a run's cost ceiling (no run exists yet); OpenRouter's own spending limit is the stop.

**Needed:** an upload flows into the same intake checks with no engineer and no terminal.

### B5 (remaining). The teacher's setup flow does not exist; the spec path does

`aeh package build --data-dir <folder> --spec <file.toml>` builds and publishes a package from a written TOML spec (`src/aeh/pipeline/packages.py`; the sample physics test, [`ps9-forces-01.package.toml`](config/ps9-forces-01.package.toml), was written that way), and `aeh package export` writes a published version's spec back out. Checked: that package plus a class from `aeh cohort create` carry the six physics sample sheets through the real intake gates exactly as the sample-materials guide's table says, and a `dev-ci` run over it is created (`TC-PIPE-29`).

What is still missing is the teacher's path:

* **No screen confirms questions, keys or rubric with the teacher.** S3 and S4 read back nothing on a real folder (they are part of B7).
* **The `accept-or-correct-rubric-read-back` command cannot succeed over the web:** it needs a model reference object, which a web form cannot supply, so a teacher's confirm-with-a-model flow has no wire.

**Needed:** the setup flow — the teacher uploads the test, model answer and rubric, a model reads them, the teacher confirms on screen — wired to a model, behind the console.

### B7. The console shows and accepts less than the guides promise

All 14 pages are read-only reports with no form, button, link or script (checked on all 14). Everything that changes something is a `curl` command, as the tutorial shows. Beyond that, on a real data folder:

* **S1, S3 and S4 do not read back the package.** `/packages` shows a placeholder card (*"Package pkg-unaddressed"*) unless you add `?package_version=<id>`, and then shows only its name and *"no validation data"*. `/setup/inventory` and `/setup/answer-keys` showed *"…read back from the package: 0"* on a folder with a published package, even with `?package_id=` added (S4 reads a package named `pkg-mconsole` in the code, `console/setup_screens.py`). So the teacher cannot see the question list or the keys on screen today.
* **S10 and S11 are one fixed sentence each** (`console/queues.py`). They list no papers. The blind-sample command needs the exact paper and rubric line that were drawn, and no page shows them, so **the blind sample cannot be done from the console** (a guessed pair was refused: *"is not in run … blind draw"*).
* **S8 shows each parked paper's ID and any stored image crop, but not the reason it was parked.**
* **S13 shows the narrative and *"C1: final"* per line, not the points or band.**
* **No page shows the run's cost, or the name given when finalizing or amending.** S12 and S7 still said *"No audit records yet."* after a finalize and an amend. (The *"actor as supplied by the form"* note is added only by the Python method, not by the web command.)
* **The drop-down lists** on the review (S9), rollup (S12), student (S13) and export (S14) pages are inert, and offer *met / partially met / not met*, which are not the rubric's real band names (an amendment with `not met` was refused for a line whose bands are *absent … comprehensive*).

This is workable for an operator who is walked through it. It is not what the teacher guide describes (*"you click…"*).
**Needed, if teachers are to operate it alone:** real controls, real band names, a package read-back, the blind-sample papers, and a cost and audit display.

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
| Resuming a paused run from the console | Only the request is queued; the worker stops when the run pauses, so a resume probably waits for the next console start (read from the code, not tried) | Try it once a live run exists |
| The Jev decision engine | The config pins its build (`openrouter/typesafe/jev-1.13@2026-09-17`), but that pin has not answered a real call yet | The live acceptance (`TC-CONFORM-17/18`) exercises the Jev leg on the nightly; read the per-criterion accept/fallback rates and band agreement off its report |
| Real cost and real run time | No live run has happened | Read them off the first run, using the cost ceiling as the guard |

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

## Suggested work, in order

These are descriptions for the issue backlog (this repository creates issues only through `/plan-to-issues`, so none were created here). Each is written as a goal that can be checked.

1. **The written zero-retention decision (B6's residue).** *Goal:* a written decision on how zero-retention is confirmed for OpenRouter, and who approves it. The code enforces it on every request; the written decision, and who signs it, is still the privacy owner's call.
2. **Console upload path (B4).** *Goal:* after an upload, the paper is reassembled, read and checked, and appears in the preflight and quarantine pages, with no engineer involved.
3. **Teacher's setup flow (B5).** *Goal:* a teacher confirms questions and keys on S3 and S4 without code.
4. **Console pages that show what the guides say (B7).** *Goal:* S1, S3 and S4 show the real package; S10 and S11 list the drawn papers; S8 shows why a paper was parked; S12 and S7 show cost and the finalizing name; the band drop-downs hold the rubric's own band names and submit.
5. **Record the operator's decision (B8).** *Goal:* resolving a parked paper stores the student, the mark or the test chosen, in the audit trail.

Items 2 to 5 are what lets a teacher run a live test alone. Until then an engineer drives the terminal — the deployment tutorial's section 8 is that path — and the console is the screen for watching, reviewing and exporting.
