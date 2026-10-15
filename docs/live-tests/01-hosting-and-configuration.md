# Hosting and configuring the system for the first live teacher test

*For the person who sets up the machine. You need to be able to open a terminal and paste commands; you do not need to be a programmer.*

**Before you start:** read [`02-live-readiness-and-blockers.md`](02-live-readiness-and-blockers.md). The supervised OpenRouter test can be run through the documented terminal-and-console path; the remaining gaps and evidence limits for teacher-independent operation are listed there. Everything in this document that was *checked* says so; everything that is advice or could not be checked says that too.

---

## 1. The picture

```
   Teacher / operator's browser
            |   (same computer only: http://127.0.0.1:<port>)
            v
   +--------------------------------------------------+
   |  ONE computer                                      |
   |   - the console (a small web page, no login)       |
   |   - the grading engine                             |
   |   - the DATA FOLDER  (every package, paper, grade) |
   +--------------------------------------------------+
            |   outbound HTTPS only
            v
        OpenRouter  (page reading and judging models)
```

Three things follow from this and shape every choice below:

1. **It is one computer.** The console has no password, so it only listens on the machine itself and refuses anything else. There is no "put it on a server for everyone" option.
2. **Student work is on that computer's disk**, in the data folder. Treat that folder as a student record.
3. **Student work also goes to OpenRouter** while the run grades it. The system will only send a cohort marked `synthetic` or `consented` unless a named person overrides it (section 7).

## 2. Which profile? (the single most important choice)

A **profile** tells the system where its models run. There are three.

| Profile | Models run | Console allowed? | Sends student work off the machine? | Use for |
|---|---|---|---|---|
| `edge-local` | On a local model server on the same machine (default address `http://127.0.0.1:8080/v1`) | Yes | No | A school with no internet |
| `dev-ci` | OpenRouter. With `HARNESS_FIXTURE_DIR` set, recorded replays instead (the test tier) | Yes | Yes, consent rule applies | Development, the first live test, and offline rehearsal |
| `cloud-hosted` | OpenRouter | **No, refused** | Yes, consent rule and a privacy check apply | A hosted service with its own login (not built) |

**For the first live test with OpenRouter and the console, use `dev-ci`.** The shipped launcher calls OpenRouter under `dev-ci` and enforces the zero-retention policy on every request. Setting `HARNESS_FIXTURE_DIR` selects recorded replays instead; that is the deterministic test/rehearsal path. The console refuses `cloud-hosted` because that profile is intended for a separately authenticated hosted service, which this console is not.

## 3. The machine

| Item | What to provide | Status |
|---|---|---|
| Operating system | Windows, macOS or Linux. The project is developed on Windows and on Linux containers. | Linux checked |
| Python | **3.11 or newer** to run the system. (The project's own test suite needs 3.13; if your helper will run the tests, use 3.13.) | Checked: all 20 modules import and compile on 3.11, 3.12 and 3.13 |
| Memory and CPU | Modest. With OpenRouter nothing heavy runs locally. | Not measured on a 350-paper run |
| Disk | Room for the PDFs you load plus the page pictures the system keeps (kept by default, `HARNESS_INGEST_RETAIN_PAGE_RASTERS`). The practice data folder for three students is about 1 MB. | Real sizes not measured |
| Network | Outbound HTTPS to `openrouter.ai`. No inbound access needed or allowed. | Could not be tested from here |
| A browser | Any current one, on the same computer | Checked with Chromium |

## 4. Install

Open a terminal in the project folder (the folder that contains `pyproject.toml`).

```bash
python -m venv .venv
```

Activate it. **macOS / Linux:** `source .venv/bin/activate`. **Windows PowerShell:** `.venv\Scripts\Activate.ps1`. Your prompt now starts with `(.venv)`. You must activate it in every new terminal window.

```bash
pip install .
```

That one command is the whole install: it also downloads the libraries that read PDFs, decode the page pictures and talk to the Jev decision engine, so it needs internet access. There are no optional parts and nothing to add by hand. (A computer with no internet installs from a prepared folder instead; see section 4.1 of `docs/tutorials/deployment-tutorial.md`.)

Check it worked:

```bash
aeh --help
```

You should see `usage: aeh [-h] {run,recover,console,cohort,package,author,ingest,results} ...` with these eight top-level commands:

- `run`, `recover`, `console`
- `cohort` (create, show or extend a class roster)
- `package` (build or export a package)
- `author` (draft from teacher-authored documents, then review the draft)
- `ingest` (read test papers and answer sheets)
- `results` (show or export grades)

(`python -m aeh ...` does the same thing and always works, even if `aeh` is not on your PATH.) The install and this `aeh --help` output were checked in a clean environment; reading a PDF through it was checked with the sample-sheet script.

The Jev decision engine's library (a pinned `typesafe-sdk==0.7.2`) is already part of that install. The shipped configuration names a Jev build; the engine may be enabled or disabled by configuration. Before a live run, verify the setting and pinned model with the engineer. For a run with the engine off, set `HARNESS_DECISION_ENGINE=off` in the terminal — the terminal wins.

> **For the person who will also run the test suite**, not the operator: `pip install -e . -r requirements-dev.txt` instead, on Python 3.13, and set the temporary folder away from `/tmp` (the tests use the same safe-folder rule): `TMPDIR=$HOME/tmp-aeh`.

## 5. The data folder

* Choose a folder **inside your own home directory**, for example `~/aeh-data` (Windows: `C:\Users\<you>\aeh-data`).
* Do **not** use `/tmp` or any folder other accounts can write to. Checked: the system refuses with *"is not a safe data directory: /tmp is world-writable (mode 777) … Nothing was created."*
* The system creates the folder if it is missing and sets it to owner-only (checked: a `755` folder became `700`).
* What is inside: `packages/` (one file per test), `cohorts/` (one file per class: the student text and grades), `blobs/` (the uploaded PDFs and page pictures), `durable.sqlite` (the long-term record), `exports/` (package files you export). Do not edit any of it by hand.
* **Back it up by copying the whole folder while the console is stopped.** Advice, not checked: keep it out of folders that sync automatically to a consumer cloud service, because it holds student work.

## 6. OpenRouter: account, key, limits

1. Create an account at openrouter.ai and an API key. *(Advice, not checked here.)*
2. **Set a spending limit on the key or the account in OpenRouter's own dashboard.** The system's own cost ceiling (section 8) is a guard that checks an estimate before each call; it is not your bill. The provider code uses the cost OpenRouter reports in each reply when there is one, and otherwise fixed rates of $0.000001 per input token and $0.000002 per output token, which are **not** the models' real prices. So treat OpenRouter's limit as the real stop.
3. **Never write the key into a file.** The system reads it only from the environment variable `OPENROUTER_API_KEY`:

   macOS / Linux:  `export OPENROUTER_API_KEY="sk-or-..."`
   Windows PowerShell:  `$env:OPENROUTER_API_KEY = "sk-or-..."`

   It lasts for that terminal window only. Do the same in each window that starts the console or a run.
4. Confirm each model named in the configuration exists on openrouter.ai/models. **This was not checked** (OpenRouter could not be reached while writing this guide).

## 7. Who may be graded: the consent rule

For `dev-ci` and `cloud-hosted`, the system checks each cohort's **consent class** before any work leaves the machine:

| Cohort is marked | Result |
|---|---|
| `synthetic` (made-up practice papers) | Allowed |
| `consented` (the students or their guardians agreed) | Allowed |
| `real`, or not marked (treated as real) | **Refused**: *"cohort … has consent_class 'real', which is neither 'synthetic' nor 'consented', so its work may not be sent to a 'dev-ci' provider"* |

A named person can override the refusal for real work by setting `HARNESS_ALLOW_REMOTE_REAL_WORK` **and** `allow_remote_real_work_supplied_by` (a name) in the configuration. Without a name, the override is refused. **For the first test, use only the synthetic sample answer sheets and do not use this override.**

## 8. The configuration file

The ready-made file is [`config/live-test.dev-ci.toml`](config/live-test.dev-ci.toml). Read the comments in it; they explain every line. In short:

| Setting | What it does | Value in the file |
|---|---|---|
| `[profiles.dev-ci]` | The profile this section configures | `dev-ci` |
| `HARNESS_COST_CEILING`, `HARNESS_COST_CURRENCY` | Spend guard for one run. Required for `dev-ci` and `cloud-hosted`. Currency is a three-letter code such as `USD`. | `5`, `USD` |
| `HARNESS_JEV_BUILD` | The pinned build of the Jev decision engine, which pre-screens every rubric cell before the judge panel sees it. Must be a pinned build (`@<date>`), like the other model names. | `openrouter/typesafe/jev-1.13@2026-09-17` |
| `HARNESS_PROFILE` (top of the file) | Which profile this file selects when the terminal does not say. The terminal wins if both are set. | `dev-ci` |
| `[profiles.dev-ci.transcriber]` | The model that reads page images | the repository's example model, **unconfirmed** |
| `[[profiles.dev-ci.panel]]` | The judges. **Must be 1, 3 or 5** (an even panel cannot break a tie). | one judge, **unconfirmed** |
| `prompt_template_v` | The wording version the judges are given | `judge-prompt/3` |

Rules the system enforces, checked:

* Model names must be **pinned**: they must end in `@<a date or version>`, as the file's names do (`…@2026-06-01`). A name carrying a moving tag (`latest`, `stable`, `main`, `head`, `newest`) after `@` or `:` is refused, because a moving name does not say what actually answered. The system does not check that the name exists.
* `HARNESS_PROFILE` has **no default**. If it is not set in the environment or the file, a run fails with *"There is no default: a silent one would select a grader by accident."*
* **The environment wins over the file.** Setting `HARNESS_PROFILE` in the terminal overrides the file's choice. A run prints which one it used (*"HARNESS_PROFILE source: environment"* or *"config file"*).
* A run **keeps the profile it started with**. Resuming it under a different profile is refused, naming the profile it expects.

### Check the file before you use it

```bash
python docs/live-tests/sample-materials/check_config.py docs/live-tests/config/live-test.dev-ci.toml
```

Real output for the file as shipped (and no key set yet):

```
ACCEPTED
  profile ............ dev-ci   (from the config file; cohort consent class: synthetic)
  page reader ........ openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01
  judge 1 ............ openrouter/qwen/qwen3-30b-a3b@2026-06-01
  decision engine .... openrouter/typesafe/jev-1.13@2026-09-17
  cost ceiling ....... 5 USD
  concurrency ........ 8 calls at a time
  OPENROUTER_API_KEY . NOT SET in this terminal
```

It tells you where the profile came from. With no profile in the terminal and none in the file it refuses, exactly as a real run does (*"HARNESS_PROFILE must be one of … got None"*), because **there is no default profile**. Add the consent class as a third word to see what a real cohort would do: `… live-test.dev-ci.toml dev-ci real` prints `NOT ACCEPTED (ConsentGateError)`. This checker uses the system's own configuration code, sends nothing, writes nothing, and never prints your key. "ACCEPTED" means the file is well formed; it is not a go signal for the day.

## 9. Other settings you may need ("knobs")

All are optional. Production values are the defaults; they exist so a slower machine can adjust without changing code. Set them as environment variables in the terminal that starts the console or run. Each name and default below was read from the code.

| Variable | What it controls | Default |
|---|---|---|
| `CONSOLE_PORT` | The console's port | A free port, chosen each start, printed on start |
| `CONSOLE_BIND` | The console's address. Only loopback is accepted. | `127.0.0.1` |
| `HARNESS_CONCURRENCY` | How many model calls at once. On `edge-local` it can only **lower** the hardware's limit. On `dev-ci` and `cloud-hosted` it **sets** the limit (there is no hardware to cap it): `50` gives 50 at once, which OpenRouter's rate limits may refuse. | 8 on `dev-ci` / `cloud-hosted` |
| `HARNESS_RETRY_MAX` | Attempts per call (one first try plus retries) | 3 |
| `HARNESS_BACKOFF_BASE_MS` | Wait before the first retry, doubling after | 250 |
| `HARNESS_RETRY_AFTER_CEILING_S` | A "come back in N seconds" above this is treated as unusable | 120 |
| `HARNESS_PIPE_MAX_PASSES` | The most rounds a run may take before giving up | no limit (a run still stops after 3 rounds in a row with no headway) |
| `HARNESS_PIPE_PASS_SLEEP_MS` | Pause between rounds | 0 |
| `HARNESS_ORCH_MAX_ATTEMPTS` | Tries per unit of work | 3 |
| `HARNESS_ORCH_ESCALATION_BUDGET` | Share of cells allowed to widen to extra judges | 0.30 |
| `HARNESS_INGEST_DPI` | Resolution pages are rendered at for reading | 200 |
| `HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS` | Tries to read one page | 3 |
| `HARNESS_INGEST_OCR_CONF_FLOOR` | Reading confidence below which a paper is flagged `low_confidence_ocr` | 0.70 |
| `HARNESS_INGEST_V4_SEMANTIC_FLOOR` | How much a paper's words must overlap the test's questions (right-test check) | 0.10 |
| `HARNESS_INGEST_RETAIN_PAGE_RASTERS` | Keep the page pictures | on |
| `HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES` | Upload read size | 4 MiB |

A malformed value is refused with the variable's name in the message. Some are checked at the start (`HARNESS_PIPE_*`, the profile and cost settings); others are checked when first used (the `HARNESS_INGEST_*` and `HARNESS_CONSOLE_*` knobs, and the retry settings when the provider is built). So a typo can show up late: check the first minutes of a run.

## 10. Starting, stopping, and recovering

| Task | Command | Notes |
|---|---|---|
| Start the console | `python -m aeh console --data-dir ~/aeh-data --config docs/live-tests/config/live-test.dev-ci.toml` | Prints the port. Runs until Ctrl-C. On start-up it reclaims expired leases, resumes runs that were running (or paused with an unapplied queued Resume request), and settles completed runs' ungraded or non-final grades. It does not start pending runs or override an operator pause — see "What `recover` does" below. |
| Stop it | Ctrl-C | Closing the browser changes nothing |
| After a crash or restart | Start the console again (its start-up recovery does the same work as `recover`), or `python -m aeh recover --data-dir ~/aeh-data` | `recover` reclaims leases, resumes runs that were running (or paused with an unapplied queued Resume request), and settles completed runs' ungraded or non-final grades; it prints `leases_reclaimed`, `runs_resumed`, `runs_regraded` |
| Run one cohort from the command line | `python -m aeh run --data-dir ~/aeh-data --cohort <cohort> --package-version <version> --config <file>` | Exit code **0** finished, **3** not finished (paused or stopped; read what it printed), **1** error |

**Profile.** `aeh run` needs a profile. The console needs one too if you want it to start runs or resume them: the `start-run` command answered *"HARNESS_PROFILE must be one of … got None"* without one (checked), and on start-up the console resumes only runs whose frozen profile equals the one in use. The shipped config file names its profile itself, so passing `--config` is enough; otherwise set `HARNESS_PROFILE` in the terminal first. To merely *look* at a data folder, no profile is needed (checked). Note the practice folder's run froze `edge-local`, so to resume or restart it you would set `HARNESS_PROFILE=edge-local`.

**What `recover` does.** `aeh recover` reclaims expired leases, resumes runs that were running when the process stopped (and paused runs with an unapplied resume request), and re-computes grades for completed runs that still have ungraded or non-final work. It does not start runs that are still pending or override an operator pause. A run whose frozen profile differs from the current process profile remains paused, with the refusal recorded. A `run` exit code of **3** means the run did not complete (for example, it is paused or stopped for another reason): read the `status` and `pause_reason` it prints.

## 11. Security and privacy checklist

Tick each before the test.

- [ ] The data folder is in a home directory, not `/tmp`, and is owner-only.
- [ ] The machine is used by one person at a time, and is locked when unattended. (The console has no login: anyone at the keyboard can change grades.)
- [ ] `OPENROUTER_API_KEY` is only in the terminal environment: not in the config file, a script, or a chat message.
- [ ] A spending limit is set in OpenRouter's dashboard.
- [ ] Only `synthetic` cohorts will be graded. `HARNESS_ALLOW_REMOTE_REAL_WORK` is not set.
- [ ] The cost ceiling is set in the config file.
- [ ] The privacy owner has documented approval for sending the selected cohort and documents to an eligible zero-retention OpenRouter endpoint. The software requests zero retention on every call and refuses when no matching endpoint exists; this technical gate does not replace the school's approval.
- [ ] A backup of the data folder will be taken after the test, before anything is purged.
- [ ] Nobody will try to bind the console to a network address.

## 12. Quick reference: what the system refused during checking

| Situation | Real message | Fix |
|---|---|---|
| Data folder under `/tmp` | `InsecureLocationError: … is not a safe data directory: /tmp is world-writable` | A folder in your home directory |
| Console on a network address | `ConsoleBindRefused: … refuses a non-loopback bind` | Do not set `CONSOLE_BIND` |
| Console under `cloud-hosted` | `ConsoleBindRefused: … refuses to start under the cloud-hosted profile` | Use `dev-ci` or `edge-local` |
| Run with no profile | `ConfigurationError: HARNESS_PROFILE must be one of ('edge-local', 'cloud-hosted', 'dev-ci'), got None` | Set it |
| `cloud-hosted` console | `ConsoleBindRefused: … refuses to start under the cloud-hosted profile` | Use `dev-ci` or `edge-local` for this loopback-only, unauthenticated console |
| `dev-ci` run, no eligible zero-retention endpoint | `HTTP 404 … No endpoints found matching your data policy` | Check the selected model's eligible providers and the zero-retention request policy; do not weaken the privacy controls |
| `dev-ci` with `HARNESS_FIXTURE_DIR` set | Recorded request/reply fixtures are replayed; OpenRouter is not called | Use this for deterministic offline tests, not as evidence of a live model run |
| Real cohort on a remote profile | `ConsentGateError: … may not be sent to a 'dev-ci' provider` | Use a synthetic cohort |
