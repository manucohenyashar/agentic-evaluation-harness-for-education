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

### B2. The request the OpenRouter provider sends is not the usual chat format (confirmed, fixed, and checked with one real call)

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

**Still not checked:** a request with several `user` messages (every real prompt has 4 to 8 fields), and the image part the page reader sends. Also not checked: many open models' chat templates drop `name`, so the model may see each field's value without its field name; the judge's and extractor's values carry their own labels (`criterion_id: …`), but some setup and synthesis values do not. Still open: the local server is sent the whole weights-path `build_id` as `model` (see the deployment tutorial, section 6.5).

### B3. Nothing creates a cohort, its consent class, or its roster

The consent rule (real student work may not go to a remote model without recorded authority) depends on the cohort's `consent_class`, and the intake's identity check (V3) depends on the roster. In the whole shipped source, the only code that writes a *cohort* row belongs to reference builders and drivers (`console/driver.py`, the headless driver; `grade/exports.py` and `grade/rollups.py`, which build reference data; `conform/suite.py`, the conformance suite), and **no code in `src/` writes a roster row at all**. There is no command or screen for "create a class, mark it synthetic, load the student IDs."
**Needed:** an operator way to create a cohort and load a roster.

### B4. Uploaded scans are stored but never read

The console's `/upload` accepts a PDF and records it (verified: the reply says *"dispatched to the orchestrator's schedule"*). But no shipped code picks it up: the only callers of the reading step (`Ingestor.ingest_submission`) are the test worlds and the conformance suite. Checked: eight seconds after an upload, the cohort's database held the new upload row and no new submission or document.
**Needed:** the step that turns uploaded parts into read, checked papers.

### B5. Building a package from the teacher's PDFs has no operator path

The design has the teacher upload the test, model answer and rubric and confirm a question list. Today the console's rubric read-back refuses when started by `aeh console` (it holds no model: *"this console holds no provider, no setup model reference or no cohort"*), and `set review window` refuses once a package is published. Package creation exists only as library calls. `verify_sample_materials.py` is a working example of them.
**Needed:** the setup flow, wired to a model, behind the console.

### B6. The privacy ("zero retention") check has no known answer format

`OpenRouterProvider.verify_retention` asks `GET {base}/retention/{model}` and treats anything other than an explicit yes as *no*. The code's own comment calls the answer format *"the open TBD"* (`FR-PROV-15`). Unless the provider is given a source of answers, a hosted run cannot start. This is part of B1 but needs its own decision.

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

## A risk to plan around, not a blocker: right-test check can park good papers

The right-test gate (V4) compares the words in a student's answers with the words in the question. Its floor is `0.10` (`HARNESS_INGEST_V4_SEMANTIC_FLOOR`). If the page reader returns **only** the handwriting for each answer, most good papers score `0.00` to `0.04` and are **parked**. Reproduce it with `python docs/live-tests/sample-materials/verify_sample_materials.py --answers-only`: in that mode six of the seven good sheets are parked as `unmatched_assessment` (the seventh, `E7-001`, passes at `0.108`, just over the floor), and the two sheets that should have been `incomplete` also come out as `unmatched_assessment`. If the answer sheet reprints each question and the reader transcribes the page verbatim, the same papers score `0.24` to `0.93` and pass (the ten sample sheets, as an ideal reader would return them). So:

* print the question above each answer space, as the sample sheets do;
* expect good papers to land in quarantine on the first test if the reader drops the printed question, and treat that as information, not failure;
* the floor is a knob, but lowering it weakens the wrong-test check (the printed test name and the question layout still catch the wrong-test sheets).

## What was not checked, and why

| Not checked | Why | How to close it |
|---|---|---|
| That the two model names in the config exist at OpenRouter | OpenRouter could not be reached from here | Look each up at openrouter.ai/models |
| That your key works and your account has credit | Same | One small real call |
| B2 (the request shape) against the real service | Same | One real call with a throw-away prompt |
| How well a page-reading model reads handwriting | The sample sheets are typed | Add two or three hand-written, scanned sheets |
| Real cost and real run time | No live run was possible | Read them off the first run, using the cost ceiling as the guard |
| The Jev decision engine | Left off on purpose | Needs `pip install ".[jev-cloud]"` and a pinned Jev build; try it on a second test |
| The `accept-or-correct-rubric-read-back` command | It needs a model reference object, which a web form cannot supply, so it cannot succeed over the web (B5) | Fix with B5 |
| Resuming a paused run from the console | Only the request is queued; the worker stops when the run pauses, so a resume probably waits for the next console start (read from the code, not tried) | Try it once a live run exists |

## Suggested work, in order

These are descriptions for the issue backlog (this repository creates issues only through `/plan-to-issues`, so none were created here). Each is written as a goal that can be checked.

1. **Decide the privacy answer (B1/B6).** *Goal:* a written decision on how zero-retention is confirmed for OpenRouter, and who approves it.
2. **One real OpenRouter call (B2).** *Goal:* a recorded result showing the provider's request is accepted, or the translation needed. *Done for a text call (see B2): one real call through the provider succeeded. Several fields in one request, and the image part, still need a real call.*
3. **Operator cohort commands (B3).** *Goal:* create a cohort with a consent class and load a roster, from the command line or the console, with the change in the audit trail.
4. **Intake worker (B4).** *Goal:* after an upload, the paper is read, checked, and appears in the preflight and quarantine pages, with no engineer involved.
5. **Dev-ci launcher through OpenRouter (B1).** *Goal:* `aeh run` under `dev-ci` with a key calls OpenRouter, the consent gate still applies, and the summary says which provider ran.
6. **Setup flow behind the console (B5).** *Goal:* a teacher can confirm questions and keys from the pages S3 and S4 without code.
7. **Console pages that show what the guides say (B7).** *Goal:* S1, S3 and S4 show the real package; S10 and S11 list the drawn papers; S8 shows why a paper was parked; S12 and S7 show cost and the finalizing name; the band drop-downs hold the rubric's own band names and submit.
8. **Record the operator's decision (B8).** *Goal:* resolving a parked paper stores the student, the mark or the test chosen, in the audit trail, and refuses an unknown word.

Items 1 to 5 and 8 are the minimum for a supervised live test with an engineer sitting beside the operator (without 8 the three awkward sheets can only be released or closed, not answered). Items 6 and 7 are what lets a teacher run it alone, and what makes the blind sample possible.
