# Live-test readiness: what works, what blocks, and the proof

*Read this before you schedule the first live teacher test. It is short on purpose: the verdict first, the evidence after.*

## The verdict

**The system cannot yet run a live grading test through OpenRouter using only its shipped commands.** Nothing is broken that would hurt a student; the system refuses safely at every point. But six separate gaps each stop a live run, and two more make the console do less than the teacher guide describes (it cannot show the teacher the papers for the blind sample, and it cannot record what the operator decided about a parked paper). They are listed below with the exact command that shows each one, so an engineer can reproduce it in a minute and a manager can see what has to be built.

What **does** work, checked by running it, and is enough to rehearse the whole operator and teacher side:

| Works today (verified) | How it was checked |
|---|---|
| `pip install ".[live-ingest]" Pillow`; the `aeh` command appears with `run`, `recover`, `console` (Pillow is needed to read PDFs and is not pulled in by the extra) | Fresh Python 3.13 environment; `aeh --help` |
| Starting the console, its 14 pages, and its safety refusals (unsafe data folder, network bind, cloud-hosted profile) | Started it and opened every page |
| Sending the control commands: success paths seen for `review-action`, `finalize-batch`, `amend-a-finalized-grade`, `export-import-package`, `correct-an-answer-key-after-a-run`, `pause-resume` (a request is queued), and the PDF upload; refusals seen for 8 more. Only the rubric read-back was not sent: it cannot succeed over the web (see B5). | Sent each to a running console over a finished practice run |
| Crash recovery: `aeh recover` releases stuck work; starting the console also resumes runs, when `HARNESS_PROFILE` matches the run's own | Ran `recover`; resume read from the code, not tried on a live run |
| The sample tests and answer sheets passing, or being parked by, the real intake checks (V0 to V4) | `verify_sample_materials.py`, 10 sheets, all as expected |
| The configuration for a dev-ci / OpenRouter run being accepted or refused with a clear reason | `check_config.py` |

## The blockers

Each has an ID that the other documents refer to. "Reproduce" commands were run for this document; the output shown is what they really printed.

### B1. No shipped path both calls OpenRouter and allows the console

The design says the console may run under the `edge-local` and `dev-ci` profiles, and that `dev-ci` is the profile that uses OpenRouter for development. The shipped launcher does not do that:

* **`dev-ci` replays recordings; it never calls OpenRouter.** `src/aeh/pipeline/runtime.py`, `_provider_for`: `dev-ci` → `RecordedFixtureProvider` (and it demands `HARNESS_FIXTURE_DIR`).
  Reproduce:
  ```
  HARNESS_PROFILE=dev-ci python -m aeh run --data-dir <folder> --cohort <c> --package-version <v> --config <dev-ci config>
  → aeh run: ValueError: the dev-ci profile records and replays through a fixture directory; set HARNESS_FIXTURE_DIR so the provider has somewhere to read
  ```
  **Two traps:** the profile summary the command prints first lists the OpenRouter model names, even though the replay provider is what runs; do not read it as proof that OpenRouter was called. And the command creates and starts the run *before* it fails, so it leaves a paused `dev-ci` run row in the data folder (use a throw-away folder when reproducing).
* **`cloud-hosted` is the only profile wired to OpenRouter, and it fails twice.**
  ```
  HARNESS_PROFILE=cloud-hosted python -m aeh run … 
  → aeh run: RetentionPolicyError: a cloud-hosted run cannot start: the orchestrator was given no provider able to verify zero-retention routing (FR-PROV-14) … nothing was created.

  HARNESS_PROFILE=cloud-hosted python -m aeh console …
  → aeh console: ConsoleBindRefused: the console refuses to start under the cloud-hosted profile: authN/authZ is none by design …
  ```
  The first is the privacy gate doing its job: the command builds the run without a provider that can answer "does OpenRouter keep this data?". The second is the console's deliberate refusal. Neither is a bug to bypass.
* **What is needed:** a launcher that builds the OpenRouter provider for `dev-ci` (with the consent gate still applying) and supplies the retention answer in a way the privacy owner approves. That is a design decision, not just code.

**Update (2026-10-03): resolved.** `aeh run` and the console's start-run, under `dev-ci`, now grade through OpenRouter (`_provider_for` in `src/aeh/pipeline/runtime.py`); `HARNESS_FIXTURE_DIR` set selects the recordings instead, as the test tier. `aeh run` binds the provider to the orchestrator before the run exists, so a `cloud-hosted` run passes its retention gate (see B6). The command now prints a `provider:` line naming what will answer, so the profile summary's model names can no longer be mistaken for proof that OpenRouter was called. The console still refuses `cloud-hosted`, on purpose: use `dev-ci`.

Found and fixed on the way: every run with a cost ceiling (all `dev-ci` and `cloud-hosted` runs) crashed on its first unit with `AttributeError: 'WorkUnit' object has no attribute 'tokens_in_per_call'`, because the orchestrator priced a work unit on a provider that prices a call plan. The launcher's provider now prices a unit as one call at `HARNESS_PIPE_UNIT_TOKENS_IN` / `_OUT` tokens (4000 / 1500). Cases `TC-PIPE-24` to `TC-PIPE-26`.

### B2. The request the OpenRouter provider sends is not the usual chat format (confirmed, fixed, and checked with real calls)

Captured by pointing the provider at a stand-in server on this machine (nothing left the machine):

```
POST /api/v1/chat/completions
{"model": "openrouter/qwen/qwen3-30b-a3b@2026-06-01",
 "prompt": {"fields": [["instruction", "Pick a band"], ["submission", "student text"]]},
 "temperature": 0.0}
```

Two things stand out. The model name is sent whole, including the `openrouter/` prefix and the `@2026-06-01` pin, where OpenRouter's documented model names are plain slugs such as `qwen/qwen3-30b-a3b`. And the body has a `prompt.fields` list rather than the `messages` list that the chat-completions endpoint is documented to expect. (The Jev decision provider, which is a different class, does strip the prefix and date: `_jev_wire_model` in `src/aeh/prov/jev_openrouter.py`.)
**Status: not confirmed.** This environment could not reach OpenRouter (the network policy blocked it), so this has never been tried against the real service. One real call with a throw-away prompt settles it. If OpenRouter rejects it, the provider needs a translation layer.

**Update (2026-10-02): the problem was confirmed by a real call, and the code is changed.** With a real key, a hand-made request (`"model": "qwen/qwen3-30b-a3b"` and a `messages` list) succeeded, and the same call through `OpenRouterProvider` failed with *"the response carries neither a choices list nor a text field"*: OpenRouter refused the body, and the provider read every 4xx other than 429 as a reply to parse, so OpenRouter's explanation was lost. The provider (`src/aeh/prov/live.py`) now:

* sends the standard chat shape: one `user` message per payload field, in order, the value verbatim and the field name in the message's `name`; the page image travels as an `image_url` part;
* sends OpenRouter the plain slug (`openrouter/qwen/qwen3-30b-a3b@2026-06-01` → `qwen/qwen3-30b-a3b`);
* names the status and OpenRouter's own message when a request is refused, with student text withheld. A refusal every paper would meet alike (401 bad key, 402 no credit, 404 unknown model) raises `ProviderUnavailableError` after one send, so a run pauses; during intake the page is quarantined instead, as before. Any other refusal (a paper too long for the model, a moderation flag) is that one paper's error: retried within the budget, then the paper quarantines and the run goes on;
* says why an answer is empty when a reasoning model spends its output allowance thinking (`content: null`, `finish_reason: "length"`). The same real call showed this with `max_tokens: 20` on `qwen/qwen3-30b-a3b`.

Regression cases `TC-PROV-60` to `TC-PROV-63`.

**Checked with a real call (2026-10-03).** `OpenRouterProvider().complete(...)` with `build_id="openrouter/qwen/qwen3-30b-a3b@2026-06-01"`, a one-field payload and `max_tokens=500` returned `Completion(text='ready', tokens_in=13, tokens_out=213, latency_ms=3230, resolved_build='qwen/qwen3-30b-a3b', cost=Decimal('0.00011245'))`. So the chat body with a `name`, the plain slug, the served build and OpenRouter's reported cost all work. `tokens_out=213` for a one-word answer is the model's reasoning: budget output generously for a reasoning model.

**Also checked with real calls (2026-10-03):**

* A three-field judge-style payload (`directive`, `criterion`, `submission`) to `qwen/qwen3-30b-a3b` returned `text='{"band": "met"}'`, `tokens_in=61`, `tokens_out=207`, cost `0.00011557`. Several `user` messages, each with a `name`, are accepted.
* An `instruction` plus an `image_png_base64` field (a generated PNG reading "The answer is 42") to `openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01` returned `text='The answer is 42'`, `resolved_build='qwen/qwen3-vl-8b-instruct'`, cost `0.000015353`. The image part reaches a vision model, and that model name exists at OpenRouter.

B2 is closed. Still not checked: real handwriting, and whether the model ignores or uses each field's `name`. Also not checked: many open models' chat templates drop `name`, so the model may see each field's value without its field name; the judge's and extractor's values carry their own labels (`criterion_id: …`), but some setup and synthesis values do not. Still open: the local server is sent the whole weights-path `build_id` as `model` (see the deployment tutorial, section 6.5).

### B3. Nothing creates a cohort, its consent class, or its roster

The consent rule (real student work may not go to a remote model without recorded authority) depends on the cohort's `consent_class`, and the intake's identity check (V3) depends on the roster. In the whole shipped source, the only code that writes a *cohort* row belongs to reference builders and drivers (`console/driver.py`, the headless driver; `grade/exports.py` and `grade/rollups.py`, which build reference data; `conform/suite.py`, the conformance suite), and **no code in `src/` writes a roster row at all**. There is no command or screen for "create a class, mark it synthetic, load the student IDs."
**Needed:** an operator way to create a cohort and load a roster.

**Update (2026-10-03): resolved.** `aeh cohort create --data-dir <folder> --cohort <id> --consent synthetic|consented|real --roster <file>` creates the cohort and its roster in one transaction (`src/aeh/orch/cohorts.py`; the roster file is read by `src/aeh/pipeline/rosters.py`); `aeh cohort add-students` and `aeh cohort show` extend and print it. The consent class is required, has no default and is never overwritten. Refused with nothing written: a cohort id that is not a safe, lower-case file name (or is a Windows device name), a cohort file already holding another cohort, an empty roster, a repeated reference, and one holding a space or an invisible character. The roster reader refuses a file it would otherwise misread (several columns and no `student_ref` header, a header-like first line, an empty `student_ref` cell) rather than drop or invent students. The orchestrator reads the stored class, so the consent gate acts on it (checked). Cases `TC-ORCH-59`, `TC-ORCH-60`. V3 matches the transcribed `Student:` line exactly, so an ID written or read differently (case, a Unicode hyphen, a trailing period) parks the paper in quarantine; it never goes to the wrong student. Not done: the creator's name is not recorded (the schema has no column for it, and adding one is a migration).

### B4. Uploaded scans are stored but never read

The console's `/upload` accepts a PDF and records it (verified: the reply says *"dispatched to the orchestrator's schedule"*). But no shipped code picks it up: the only callers of the reading step (`Ingestor.ingest_submission`) are the test worlds and the conformance suite. Checked: eight seconds after an upload, the cohort's database held the new upload row and no new submission or document.
**Needed:** the step that turns uploaded parts into read, checked papers.

**Update (2026-10-03): an operator path exists; console uploads are still not read.** `aeh ingest --data-dir <folder> --cohort <id> --package-version <version> --config <file> --assessment <test-paper.pdf> <answer-sheets folder or PDFs>` reads the test paper and every answer sheet (one PDF per student) with the page-reading model the configuration names, through V0–V4, and parks every paper that fails a check (`src/aeh/pipeline/intake.py`). Under `dev-ci` the pages go to OpenRouter with zero data retention enforced, and the consent gate refuses a `real` cohort before any page is sent. A re-run skips every scan already read into the cohort, so no paper is graded twice: a scan that never became a document (unreadable) is read again and leaves one more quarantined record, and a read cut off by Ctrl-C is parked in quarantine by the next `aeh ingest` (`TC-PIPE-32`). A folder where no sheet could be read exits 1 and names the likely cause (key, credit, model). Checked over the six physics sample sheets through the real provider's wire format against a stand-in OpenRouter (`TC-PIPE-30`, `TC-PIPE-31`): each lands as this guide's table says. **Not checked: a real vision model reading these pages** — whether it writes the region markup the intake checks parse is exactly what the first live run will show. Still open: the console's `/upload` stores each 4 MiB chunk as a separate blob and records only the first chunk, so an uploaded PDF over 4 MiB cannot be reassembled; reading uploads needs that fixed first. Page-reading calls are not counted against a run's cost ceiling (no run exists yet).

### B5. Building a package from the teacher's PDFs has no operator path

The design has the teacher upload the test, model answer and rubric and confirm a question list. Today the console's rubric read-back refuses when started by `aeh console` (it holds no model: *"this console holds no provider, no setup model reference or no cohort"*), and `set review window` refuses once a package is published. Package creation exists only as library calls. `verify_sample_materials.py` is a working example of them.
**Needed:** the setup flow, wired to a model, behind the console.

**Update (2026-10-03): an operator path exists; the teacher's on-screen flow does not yet.** `aeh package build --data-dir <folder> --spec <file.toml>` builds a package from a written spec and publishes it, through `M-PKG`'s own API (`src/aeh/pipeline/packages.py`): the question inventory with each question's text, options and model answer (a judge's criterion and question text come from it), the rubric lines with their bands, the multiple-choice keys, the grade boundaries, and the approver's name. `docs/live-tests/config/ps9-forces-01.package.toml` is the sample physics test written this way. Checked: that package plus a class from `aeh cohort create` carry the six physics sample sheets through the real intake gates exactly as this guide's table says, and a `dev-ci` run over it is created (case `TC-PIPE-29`). A spec that cannot be translated, an id that exists (ignoring case) and a rule `M-PKG` refuses each leave no package behind. The console's rubric read-back still holds no model, so building from the teacher's PDFs by reading them with a model (and S3/S4 confirmation on screen) remains open.

### B6. The privacy ("zero retention") check has no known answer format

`OpenRouterProvider.verify_retention` asks `GET {base}/retention/{model}` and treats anything other than an explicit yes as *no*. The code's own comment calls the answer format *"the open TBD"* (`FR-PROV-15`). Unless the provider is given a source of answers, a hosted run cannot start. This is part of B1 but needs its own decision.

**Update (2026-10-03): resolved by enforcement.** Every request to OpenRouter now carries `"provider": {"zdr": true, "data_collection": "deny"}`, so OpenRouter routes it only to a host that keeps no copy and does not train on it, or refuses it (`HTTP 404 ... No endpoints found matching your data policy`, which pauses the run). The launcher builds `OpenRouterProvider.enforcing_zero_retention()`, whose retention gate is answered by that rule rather than by the `GET /retention/<model>` lookup OpenRouter does not serve. Checked with real calls: both models in the shipped config have zero-retention hosts (`qwen/qwen3-30b-a3b` via DeepInfra, `qwen/qwen3-vl-8b-instruct` via Parasail). Case `TC-PROV-64`. Still not covered: the run-start gate itself sends no request, so a model with no zero-retention host is found at its first call (the run pauses there, having sent nothing to a retaining host), not before the run is created.

### B7. The console shows less than the guides promise

All 14 pages are read-only reports with no form, button, link or script (checked on all 14). Everything that changes something is a `curl` command, as the tutorial shows. Beyond that, on a real data folder:

* **S1, S3 and S4 do not read back the package.** `/packages` shows a placeholder card (*"Package pkg-unaddressed"*) unless you add `?package_version=<id>`, and then shows only its name and *"no validation data"*. `/setup/inventory` and `/setup/answer-keys` showed *"…read back from the package: 0"* on a folder with a published package, even with `?package_id=` added (S4 reads a package named `pkg-mconsole` in the code, `console/setup_screens.py`). So the teacher cannot see the question list or the keys on screen today.
* **S10 and S11 are one fixed sentence each** (`console/queues.py`). They list no papers. The blind-sample command needs the exact paper and rubric line that were drawn, and no page shows them, so **the blind sample cannot be done from the console** (a guessed pair was refused: *"is not in run … blind draw"*).
* **S8 shows each parked paper's ID and any stored image crop, but not the reason it was parked.**
* **S13 shows the narrative and *"C1: final"* per line, not the points or band.**
* **No page shows the run's cost, or the name given when finalizing or amending.** S12 and S7 still said *"No audit records yet."* after a finalize and an amend. (The *"actor as supplied by the form"* note is added only by the Python method, not by the web command.)
* **The drop-down lists** on the review (S9), rollup (S12), student (S13) and export (S14) pages are inert, and offer *met / partially met / not met*, which are not the rubric's real band names (an amendment with `not met` was refused for a line whose bands are *absent … comprehensive*).

This is workable for an operator who is walked through it. It is not what the teacher guide describes (*"you click…"*).
**Needed, if teachers are to operate it alone:** real controls, real band names, a package read-back, the blind-sample papers, and a cost and audit display.

### B8. Resolving a parked paper does not record the decision

`resolve-quarantine-item` takes only a paper ID and a word (`matched`, or anything else). It runs one update: `matched` sets the paper's status to `ok` and releases it; any other value, including a typo, closes it as unresolvable (INCOMPLETE grade, lines MISSING) and still answers `dispatched: true` (`console/effects.py`, `console/queries.py`). Nothing records **which student** a nameless paper belongs to, **which tick** a doubled mark was, or **which test** a wrong-test paper is for. For the three awkward sample sheets that means: the operator can release or close them, but cannot yet tell the system the answer.
**Needed:** fields for the operator's decision (student ID, corrected mark, correct test), stored and audited, and a refusal of any word other than the two allowed ones.

**Update (2026-10-03): the two refusals are in; recording the decision is not.** Any `resolution` other than `matched` or `unresolvable` (a typo, or none) is now refused and writes nothing, and `matched` is refused for a paper whose student the identity check (V3) did not match, because the release would grade it under `unknown`; such a paper is closed, or rescanned with the ID written on it and read in again with `aeh ingest` (cases `TC-CONSOLE-51`, `TC-CONSOLE-52`, over the sample sheets parked by the real intake checks). Still open, and a design decision rather than a fix: where the operator's decision (which student, which mark, which test) is stored and audited. The console's write surface for this action is exactly `submission.ingest_status` and `submission.quarantined` (FR-CONSOLE-32), a corrected mark would change an immutable document, and an audit record needs a migration; it belongs to `/detailed-design-generator`.

## A risk to plan around, not a blocker: right-test check can park good papers

The right-test gate (V4) compares the words in a student's answers with the words in the question. Its floor is `0.10` (`HARNESS_INGEST_V4_SEMANTIC_FLOOR`). If the page reader returns **only** the handwriting for each answer, most good papers score `0.00` to `0.04` and are **parked**. Reproduce it with `python docs/live-tests/sample-materials/verify_sample_materials.py --answers-only`: in that mode six of the seven good sheets are parked as `unmatched_assessment` (the seventh, `E7-001`, passes at `0.108`, just over the floor), and the two sheets that should have been `incomplete` also come out as `unmatched_assessment`. If the answer sheet reprints each question and the reader transcribes the page verbatim, the same papers score `0.24` to `0.93` and pass (the ten sample sheets, as an ideal reader would return them). So:

* print the question above each answer space, as the sample sheets do;
* expect good papers to land in quarantine on the first test if the reader drops the printed question, and treat that as information, not failure;
* the floor is a knob, but lowering it weakens the wrong-test check (the printed test name and the question layout still catch the wrong-test sheets).

## What was not checked, and why

| Not checked | Why | How to close it |
|---|---|---|
| That the two model names in the config exist at OpenRouter | **Closed (2026-10-03):** both answered real calls (`qwen/qwen3-30b-a3b`, `qwen/qwen3-vl-8b-instruct`) | — |
| That your key works and your account has credit | **Closed (2026-10-03):** real calls succeeded and were billed | — |
| B2 (the request shape) against the real service | **Closed (2026-10-03):** see B2 | — |
| How well a page-reading model reads handwriting | The sample sheets are typed | Add two or three hand-written, scanned sheets |
| Real cost and real run time | No live run was possible | Read them off the first run, using the cost ceiling as the guard |
| The Jev decision engine | Left off on purpose | Needs `pip install ".[jev-cloud]"` and a pinned Jev build; try it on a second test |
| The `accept-or-correct-rubric-read-back` command | It needs a model reference object, which a web form cannot supply, so it cannot succeed over the web (B5) | Fix with B5 |
| Resuming a paused run from the console | Only the request is queued; the worker stops when the run pauses, so a resume probably waits for the next console start (read from the code, not tried) | Try it once a live run exists |

## Suggested work, in order

These are descriptions for the issue backlog (this repository creates issues only through `/plan-to-issues`, so none were created here). Each is written as a goal that can be checked.

1. **Decide the privacy answer (B1/B6).** *Goal:* a written decision on how zero-retention is confirmed for OpenRouter, and who approves it. *The code now enforces zero retention per request (see B6). The written decision, and who approves it, is still for the privacy owner: the code cannot make that call.*
2. **One real OpenRouter call (B2).** *Goal:* a recorded result showing the provider's request is accepted, or the translation needed. *Done (see B2): real calls through the provider succeeded for a one-field call, a three-field judge-style call, and a page image to the vision model.*
3. **Operator cohort commands (B3).** *Goal:* create a cohort with a consent class and load a roster, from the command line or the console, with the change in the audit trail.
4. **Intake worker (B4).** *Goal:* after an upload, the paper is read, checked, and appears in the preflight and quarantine pages, with no engineer involved.
5. **Dev-ci launcher through OpenRouter (B1).** *Goal:* `aeh run` under `dev-ci` with a key calls OpenRouter, the consent gate still applies, and the summary says which provider ran. *Done (see B1).*
6. **Setup flow behind the console (B5).** *Goal:* a teacher can confirm questions and keys from the pages S3 and S4 without code.
7. **Console pages that show what the guides say (B7).** *Goal:* S1, S3 and S4 show the real package; S10 and S11 list the drawn papers; S8 shows why a paper was parked; S12 and S7 show cost and the finalizing name; the band drop-downs hold the rubric's own band names and submit.
8. **Record the operator's decision (B8).** *Goal:* resolving a parked paper stores the student, the mark or the test chosen, in the audit trail, and refuses an unknown word.

Items 1 to 5 and 8 are the minimum for a supervised live test with an engineer sitting beside the operator (without 8 the three awkward sheets can only be released or closed, not answered). Items 6 and 7 are what lets a teacher run it alone, and what makes the blind sample possible.
