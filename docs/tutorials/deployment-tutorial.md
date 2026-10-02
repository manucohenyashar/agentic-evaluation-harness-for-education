# Deploying and Configuring the Grading System: A Tutorial

*For the person who sets up the machine. You need to be able to open a terminal and paste commands. You do not need to be a programmer.*

This tutorial shows how to **install** the system, **configure** it, and **start** it. It covers both ways the system can work:

* **Local computer mode** (the system calls this profile `edge-local`). The AI models run on the same computer as the system. Nothing leaves the building.
* **OpenRouter mode** (the system calls these profiles `cloud-hosted` and `dev-ci`). The AI models run on OpenRouter, a service on the internet. Student work is sent there.

For how to *use* the system once it is running (the pages, the commands, grading a test), read the [operating tutorial](operating-tutorial.md). For the longer technical background, see [`docs/live-tests/01-hosting-and-configuration.md`](../live-tests/01-hosting-and-configuration.md).

> ### Read this box first
> Everything below was **checked against the code** and, where it says "checked", **run** on a Linux machine with Python 3.11. Things that could not be checked are labelled **not checked**. Two facts decide what you can do today:
>
> 1. **Local computer mode is the only mode that can run the console and grade at the same time.** But the system has **not been tried against a real local model server**. The way it talks to the server may not match what common servers (Ollama, llama.cpp, vLLM) expect. See section 6.5.
> 2. **OpenRouter mode can be set up and checked, but a live grading run cannot start yet.** `dev-ci` only replays recordings. `cloud-hosted` is the only profile that calls OpenRouter, but the console refuses it, and `aeh run` stops at the privacy check. Both refusals were reproduced and are shown in section 7.6. They are listed as blockers B1, B2 and B6 in [`02-live-readiness-and-blockers.md`](../live-tests/02-live-readiness-and-blockers.md).
>
> So: you can follow every step here and get a correct setup. Whether a live run then works depends on the open blockers.

---

## 1. The big picture

```
   Browser (same computer only: http://127.0.0.1:<port>)
            |
            v
   +----------------------------------------------------+
   |  ONE computer                                       |
   |   - the console   (a small web page, no password)   |
   |   - the grading engine                              |
   |   - the DATA FOLDER (every package, paper, grade)   |
   +----------------------------------------------------+
        |                                  |
        | Local mode: a model server       | OpenRouter mode: HTTPS out
        | on THIS computer                 | to openrouter.ai
        v                                  v
   http://127.0.0.1:8080/v1            https://openrouter.ai/api/v1
```

Three facts shape every choice:

1. **It is one computer.** The console has no password, so it only listens on the machine itself. It refuses anything else. There is no "put it on a server for everyone" option.
2. **Student work sits on that computer's disk**, in the data folder. Treat the folder as a student record.
3. **In OpenRouter mode, student work also goes to OpenRouter.** The system has a consent rule for this (section 7.4).

## 2. The two modes at a glance

A **profile** tells the system where its models run. You pick exactly one for each run. There is **no default**: if you forget, the system stops and says so.

| | Local computer mode | OpenRouter mode (live) | OpenRouter mode (practice) |
|---|---|---|---|
| Profile name | `edge-local` | `cloud-hosted` | `dev-ci` |
| Where models run | A model server on this computer | OpenRouter | **Recordings only today** (no network) |
| Console allowed? | Yes | **No** (refused) | Yes |
| Sends student work off the machine? | No | Yes | Intended yes; today no |
| Costs money? | No | Yes | No today |
| Needs | Model files, enough memory | OpenRouter key, internet | A folder of recordings (`HARNESS_FIXTURE_DIR`) |
| Needs a cost limit in the file? | No | Yes | Yes |
| Needs `retention_setting` in the file? | No | Yes | No |
| Model names look like | A file path | A service name | A service name |
| Use it for | A school with no internet | A hosted service (not built yet) | Practice and development |

All of the above was read from the code and checked with the configuration checker (section 5.4).

## 3. What you need

| Item | What to provide | Status |
|---|---|---|
| Operating system | Windows, macOS or Linux | Linux checked |
| Python | **3.11 or newer** | Checked on 3.11 |
| A browser | Any current one, on the same computer | Not checked here (pages were fetched with `curl`) |
| Disk space | Room for the PDFs you load, plus page pictures the system keeps. The practice folder for three students is about 1 MB. | Real sizes not measured |
| **Local mode only:** model files and a model server | See section 6 | Not checked with a real server |
| **OpenRouter mode only:** an OpenRouter account and key, and outbound HTTPS to `openrouter.ai` | See section 7 | Not checked (no network access to OpenRouter here) |

The system's own core has **no** extra Python libraries. Reading PDFs needs three (section 4).

## 4. Install

Open a terminal in the project folder (the folder that contains `pyproject.toml`).

**Step 1: make a private Python environment.**

```bash
python -m venv .venv
```

**Step 2: switch it on.** You must do this in every new terminal window. Your prompt then starts with `(.venv)`.

* macOS / Linux: `source .venv/bin/activate`
* Windows PowerShell: `.venv\Scripts\Activate.ps1`

**Step 3: install the system and the PDF readers.**

```bash
pip install ".[live-ingest]" Pillow
```

* `live-ingest` adds the two libraries that read PDFs (`pypdf` and `pypdfium2`).
* `Pillow` is a third one the page-picture step needs. The project's `live-ingest` list does not include it, so you name it yourself. Without it, reading a PDF stops with an error that mentions `PIL` (reported by an earlier audit; not re-checked here).

**Step 4: check it worked.**

```bash
aeh --help
```

You should see (checked):

```
usage: aeh [-h] {run,recover,console} ...

Run, recover and serve the agentic evaluation harness.

positional arguments:
  {run,recover,console}
    run                 drive a cohort's run to completion
    recover             reclaim leases, resume and settle grades
    console             recover, then serve the operator console
```

`python -m aeh ...` does exactly the same thing and works even if the `aeh` command is not on your PATH.

**Two details people trip over (both checked):**

* The `--config` option belongs **after** the command word: `aeh console --data-dir ... --config ...`. Putting it first (`aeh --config x console ...`) fails with *"invalid choice: 'x'"*. The comment at the top of `config/harness.example.toml` shows it the wrong way round; ignore that line.
* `aeh recover` takes only `--data-dir`. It has no `--config`.

**Optional extras.** Leave both off for a first test:

* `pip install ".[jev-cloud]"` adds the Jev decision engine's library (OpenRouter mode only).
* People who will also run the project's own test suite use `pip install -r requirements-dev.txt` instead, on Python 3.13.

## 5. The data folder and the configuration file

### 5.1 The data folder

The data folder is the system's whole memory. Choose one **inside your own home folder**, for example `~/aeh-data` (Windows: `$HOME\aeh-data`).

* Do **not** use `/tmp` or any folder other accounts can write to. Checked: the system refuses with *"is not a safe data directory: /tmp is world-writable (mode 777) ... Nothing was created."*
* If the folder does not exist, the system creates it and makes it owner-only. (Checked on Linux. Not checked on Windows.)
* Inside you will see `packages/`, `cohorts/`, `blobs/`, `durable.sqlite`, and later `exports/`. Never edit these by hand.
* **Back it up** by copying the whole folder while the console is stopped. Keep it out of folders that sync to a public cloud service.

### 5.2 How the configuration file works

You pass one file with `--config`. It can hold a section for each profile, so one file can serve all modes. These rules are enforced (checked):

1. **`HARNESS_PROFILE` picks the section.** It can be set in the terminal or at the top of the file. **The terminal wins.** If the file has no section for the chosen profile, the system says so: *"the config file has no section for 'dev-ci'; sections present: 'edge-local'."*
2. **The environment wins over the file** for these settings: `HARNESS_PROFILE`, `HARNESS_HARDWARE_PROFILE`, `HARNESS_COST_CEILING`, `HARNESS_COST_CURRENCY`, `HARNESS_CONCURRENCY`, `HARNESS_ALLOW_REMOTE_REAL_WORK`, `CONSOLE_BIND`, `CONSOLE_PORT`, and the decision-engine settings (`HARNESS_DECISION_ENGINE`, `HARNESS_DECISION_PROVIDER`, `HARNESS_JEV_BUILD`, `HARNESS_JEV_QUANTIZATION`, and three `HARNESS_JEV_...` limits).
3. **Some settings can only live in the file:** `prompt_template_v`, the `transcriber` and `panel` models, `retention_setting`, and `allow_remote_real_work_supplied_by`.
4. A run **keeps the profile it started with.** Resuming it under another profile is refused, and the message names the profile it expects.
5. Model tables are written like this: `role`, `provider`, `build_id`, and (local mode only) `quantization`.

### 5.3 The settings in plain words

| Setting | What it means | Needed for |
|---|---|---|
| `HARNESS_PROFILE` | Which mode: `edge-local`, `cloud-hosted` or `dev-ci`. No default. | All |
| `prompt_template_v` | The version of the wording given to the judges. Use `judge-prompt/2`, as the shipped files do. | All |
| `HARNESS_DECISION_ENGINE` | `off` or `jev`. **No default.** `off` means the page reader and the judges do all the grading. Start with `off`. | All |
| `[profiles.<name>.transcriber]` | The model that reads the page pictures | All |
| `[[profiles.<name>.panel]]` | The judges. **You must list 1, 3 or 5** (an even number cannot break a tie). | All |
| `HARNESS_HARDWARE_PROFILE` | `unified-large`, `unified-small` or `discrete-gpu`. Sets how many model calls run at once. | Local only |
| `HARNESS_COST_CEILING` and `HARNESS_COST_CURRENCY` | A spending guard for one run. The currency is a three-letter code such as `USD`. | OpenRouter only |
| `retention_setting` | `provider-default` or `zero-retention`. This *records* your privacy choice. | `cloud-hosted` only |

Settings that do not apply to your mode are ignored, not refused. A leftover `HARNESS_COST_CURRENCY` from yesterday will not stop a local run (read from the code).

### 5.4 Check a file before you use it

The project has a checker that uses the system's own configuration code. It sends nothing and writes nothing. It never prints your key; it only says whether one is set.

```bash
python docs/live-tests/sample-materials/check_config.py <config-file> [profile] [consent-class]
```

Real output for the local-mode example in section 6.3:

```
ACCEPTED
  profile ............ edge-local   (from the config file; cohort consent class: synthetic)
  page reader ........ /models/qwen3-vl-8b-instruct-q4.gguf@sha256:0000...0000
  judge 1 ............ /models/qwen3-30b-a3b-q4.gguf@sha256:0000...0000
  decision engine .... off
  cost ceiling ....... None None
  concurrency ........ 4 calls at a time
  OPENROUTER_API_KEY . NOT SET in this terminal
```

"ACCEPTED" only means the file is well formed. It is not a go signal. It cannot tell you whether a model file exists, whether a model name exists at OpenRouter, or whether your key works.

---

## 6. Local computer mode (`edge-local`)

Nothing leaves the machine. There is no cost limit and no consent rule, because there is nothing to consent to.

### 6.1 What you need to prepare

1. **Model files** on the computer. Each judge and the page reader is a model *file*, such as a `.gguf` file.
2. **A model server** running on this computer that serves them. By default the system looks for it at `http://127.0.0.1:8080/v1`.

Both are your job. This project ships no model server for the page reader and the judges. (A small helper for the optional decision engine is in `tools/openjev_small_shim`; leave that off for now.)

### 6.2 The hardware profile

`HARNESS_HARDWARE_PROFILE` is **required** in local mode. Without it the system stops: *"HARNESS_HARDWARE_PROFILE is required when HARNESS_PROFILE is 'edge-local'"* (checked). Pick the one that matches the computer. The number is how many model calls may run at the same time (read from the code, and checked for `unified-large`):

| Profile | What it is | Calls at a time |
|---|---|---|
| `unified-large` | A computer where the processor and graphics share a large memory (for example an Apple-silicon Mac with plenty of memory). The page reader and the judge can both stay loaded. | 4 |
| `unified-small` | The same kind of computer with less memory. Only the judge stays loaded at once. | 2 |
| `discrete-gpu` | A computer with a separate graphics card. Only the judge stays loaded. | 3 |

`HARNESS_CONCURRENCY` can only **lower** this number, never raise it (checked: setting 9 on `unified-large` still gives 4).

### 6.3 A worked example

Save this as `~/aeh-config/edge-local.toml` (any folder you like). It is accepted by the checker (checked).

```toml
HARNESS_PROFILE = "edge-local"
prompt_template_v = "judge-prompt/2"

[profiles.edge-local]
HARNESS_HARDWARE_PROFILE = "unified-large"
HARNESS_DECISION_ENGINE = "off"

# The model that reads page pictures.
[profiles.edge-local.transcriber]
role = "transcriber"
provider = "local"
build_id = "/models/qwen3-vl-8b-instruct-q4.gguf@sha256:<64 hex characters>"
quantization = "q4"

# The judges. List 1, 3 or 5 of these blocks.
[[profiles.edge-local.panel]]
role = "judge"
provider = "local"
build_id = "/models/qwen3-30b-a3b-q4.gguf@sha256:<64 hex characters>"
quantization = "q4"
```

Now the rules for the model lines.

**`build_id` must name a file, its fingerprint, and the `quantization` must be set.** It has the form `<path to file>@sha256:<fingerprint>`.

* The file name must end in `.gguf`, `.safetensors`, `.bin`, `.pt`, `.mlx` or `.npz`. A name that does not end like one of these is read as an OpenRouter name and refused in local mode (checked: *"panel[0] is a provider-pinned build, but backend_profile 'edge-local' requires a edge-weights build"*).
* A missing fingerprint is refused (checked: *"panel[0] is not a resolved build identity"*).
* The fingerprint is the file's SHA-256 hash, written as hex characters. Get the real one with:

  * macOS / Linux: `sha256sum /models/qwen3-30b-a3b-q4.gguf`
  * Windows PowerShell: `Get-FileHash -Algorithm SHA256 C:\models\qwen3-30b-a3b-q4.gguf`

  **The system does not check the fingerprint against the file.** The checker accepted a fingerprint of all zeros. That is why you must put the real one in: it is how you can later prove which exact model graded a student.
* `quantization` is a short label such as `q4`. It must not be empty.

**`provider`** can be `local`, `local-server`, `ollama` or `vllm-mlx`. All four use the same code. Use `local` unless you want the name to describe your server.

**On Windows**, write the path with forward slashes (`C:/models/x.gguf@sha256:...`) or in single quotes (`'C:\models\x.gguf@sha256:...'`). Both were accepted by the checker. In double quotes a backslash is a special character in TOML.

**Do not use a moving tag.** A name ending in `latest`, `stable`, `main`, `head` or `newest` (after `@` or `:`) is refused, because it does not say which model really answered.

### 6.4 The decision engine: leave it off

`HARNESS_DECISION_ENGINE = "off"` is the simple choice. The `jev` engine in local mode needs extra servers on ports 3000 and 8000 and a pinned model build, and it only fits on `unified-large` (the other two hardware profiles allow only the smaller `openjev-small` helper). If you want it later, `config/harness.example.toml` shows the settings. Try it on a second test, not the first.

### 6.5 Where the model server is, and one big warning

Set `LOCAL_INFERENCE_BASE_URL` in the terminal if your server is not at the default `http://127.0.0.1:8080/v1`:

* macOS / Linux: `export LOCAL_INFERENCE_BASE_URL="http://127.0.0.1:9000/v1"`
* Windows PowerShell: `$env:LOCAL_INFERENCE_BASE_URL = "http://127.0.0.1:9000/v1"`

The address must **end in `/v1`**. The system adds `/chat/completions` to it (checked). It sends **no** password or key to a local server (checked).

> **Warning: not tried against a real server.**
> A test against a stand-in server on this machine showed exactly what the system sends. It posts to `<address>/chat/completions` with a body like this:
>
> ```json
> {"model": "/models/x-q4.gguf@sha256:0000...0000",
>  "prompt": {"fields": [["instruction", "Pick a band"], ["submission", "student text"]]},
>  "temperature": 0.0}
> ```
>
> Two things in it are unusual. The `model` is the whole `build_id`, including the file path and the fingerprint. And the body has a `prompt` with `fields`, not the `messages` list that servers such as Ollama, llama.cpp and vLLM normally expect. The system's design says a translation layer (LiteLLM) sits in front of the model server on a real deployment. **Whether your server accepts this as it is has not been checked.** Before a real test, send one real request and see. If the server refuses it, you will need that translation layer; that is engineering work. This is the same open question as B2 in the readiness document.

### 6.6 Start it

```bash
python -m aeh console --data-dir ~/aeh-data --config ~/aeh-config/edge-local.toml
```

Windows PowerShell: `python -m aeh console --data-dir $HOME\aeh-data --config $HOME\aeh-config\edge-local.toml`

You will see one line (checked):

```
console listening on port 8765 (pid 1016); Ctrl-C to stop
```

The port is different every time unless you choose one. To choose, set `CONSOLE_PORT` first (`export CONSOLE_PORT=8765`, or in PowerShell `$env:CONSOLE_PORT = "8765"`). Then open `http://127.0.0.1:8765`. The command keeps running; press **Ctrl-C** to stop it.

Checked: with this file the console started and `/runs/run-dev-pipe/monitor` returned the page (HTTP 200) on the practice data from section 9.

**What was and was not checked in local mode:**

| Checked | Not checked |
|---|---|
| The file is accepted; wrong forms are refused with a clear reason | A run that really calls a local model |
| The console starts under `edge-local` and serves pages | Whether a real server accepts the request format (6.5) |
| The request the system sends, and the address it uses | How fast or accurate the models are on your computer |
| `aeh run` under `edge-local` on a finished practice run succeeds (nothing needed a model) | Windows |

---

## 7. OpenRouter mode (`cloud-hosted` and `dev-ci`)

### 7.1 Which profile do I use?

* **`cloud-hosted`** is the only profile that is wired to call OpenRouter. But the console **refuses to start** under it (it has no login, so it must never be a hosted service), and a run stops at the privacy check (section 7.6). It is meant for a future hosted service with its own login.
* **`dev-ci`** is the profile the design intends for development and for the first live test with the console. It sends work to OpenRouter in the design. **In the code today it replays recordings and never calls OpenRouter.**

So, for development, use `dev-ci`. For the day the blockers are closed, the `cloud-hosted` example below is ready. The two files are almost the same; the differences are in the table in section 2. Today neither one can run a live grading pass (7.6).

### 7.2 Get an OpenRouter key

1. Create an account at openrouter.ai and make an API key. *(Not checked here.)*
2. **Set a spending limit** in OpenRouter's own dashboard. This is the real stop. The system's cost ceiling (7.3) only checks an *estimate* before each call. For the real cost the system uses the figure OpenRouter reports in each reply (read from the code). If a reply has none, it uses fixed rates of $0.000001 per input token and $0.000002 per output token (checked with a stand-in server: 3 tokens in and 2 out gave $0.000007). Those fixed rates are **not** the models' real prices.
3. **Never write the key in a file.** The system reads it only from the environment variable `OPENROUTER_API_KEY`. It lasts for that terminal window only, so set it in each window that starts the console or a run:

   * macOS / Linux: `export OPENROUTER_API_KEY="sk-or-..."`
   * Windows PowerShell: `$env:OPENROUTER_API_KEY = "sk-or-..."`

   If the key is missing, the first call fails with *"OpenRouterProvider needs an API key: pass api_key= or set OPENROUTER_API_KEY"* (checked).
4. The address defaults to `https://openrouter.ai/api/v1`. You can change it with `OPENROUTER_BASE_URL`. You normally will not.

### 7.3 The configuration files

**`dev-ci`** (the shipped file for the first live test is [`docs/live-tests/config/live-test.dev-ci.toml`](../live-tests/config/live-test.dev-ci.toml); it is accepted by the checker, checked):

```toml
HARNESS_PROFILE = "dev-ci"
prompt_template_v = "judge-prompt/2"

[profiles.dev-ci]
HARNESS_COST_CEILING = 5
HARNESS_COST_CURRENCY = "USD"
HARNESS_DECISION_ENGINE = "off"

[profiles.dev-ci.transcriber]
role = "transcriber"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01"

[[profiles.dev-ci.panel]]
role = "judge"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-30b-a3b@2026-06-01"
```

**`cloud-hosted`** (a file I wrote for this tutorial; it is accepted by the checker, checked). It adds one line, `retention_setting`:

```toml
HARNESS_PROFILE = "cloud-hosted"
prompt_template_v = "judge-prompt/2"

[profiles.cloud-hosted]
HARNESS_COST_CEILING = 5
HARNESS_COST_CURRENCY = "USD"
retention_setting = "zero-retention"
HARNESS_DECISION_ENGINE = "off"

[profiles.cloud-hosted.transcriber]
role = "transcriber"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01"

[[profiles.cloud-hosted.panel]]
role = "judge"
provider = "openrouter"
build_id = "openrouter/qwen/qwen3-30b-a3b@2026-06-01"
```

What each part means, and the rules (all checked unless said):

* **`HARNESS_COST_CEILING`** is required for both profiles. Without it: *"HARNESS_COST_CEILING is required for backend_profile 'cloud-hosted'"*. It must be a whole or decimal number, not negative. `5` is plenty for ten sample answer sheets. The environment can override it.
* **`retention_setting`** is required for `cloud-hosted` only. It must be `provider-default` or `zero-retention`. It *records* your choice. It does **not** make the privacy check pass (see 7.6). Leaving it out is refused: *"retention_setting is required for backend_profile 'cloud-hosted'"*.
* **Model names** are written `openrouter/<vendor>/<model>@<date or version>`. The `@...` part is required: it pins the exact version. A moving tag such as `@latest` is refused. Do **not** give these a `quantization` line (the provider owns it).
* **Do the models exist?** The two names are copied from the project's example file. **They have not been checked against OpenRouter's list.** Open openrouter.ai/models and confirm each one before the test.
* **Judges:** one judge is the smallest test, but with one judge nobody can disagree, so the system cannot show agreement figures. For a real accuracy test, use **three** judges from different model families (add two more `[[profiles....panel]]` blocks). An even number such as two is refused: *"panel must hold [1, 3, 5] judges, got 2"*.
* **`HARNESS_CONCURRENCY`** sets how many calls run at once. The default is 8. Here it *sets* the number (it does not just lower it): `20` is accepted. OpenRouter's own rate limits may refuse a high number.

### 7.4 Who may be graded: the consent rule

Before any work leaves the machine, the system checks the class's **consent class** (checked):

| The class is marked | Result |
|---|---|
| `synthetic` (made-up practice papers) | Allowed |
| `consented` (students or guardians agreed) | Allowed |
| `real`, or not marked (counts as real) | **Refused**: *"cohort ... has consent_class 'real', which is neither 'synthetic' nor 'consented', so its work may not be sent to a 'dev-ci' provider"* |

A named person can override this by setting `HARNESS_ALLOW_REMOTE_REAL_WORK=true` **and**, in the file, `allow_remote_real_work_supplied_by = "<a name>"`. Without a name the override is refused (checked: *"allow_remote_real_work_supplied_by must name who authorised ... the gate still refuses"*). **For a first test, use only synthetic papers and do not use the override.**

### 7.5 The decision engine in OpenRouter mode (leave it off)

`HARNESS_DECISION_ENGINE = "jev"` needs `pip install ".[jev-cloud]"` and a pinned build, for example (from `config/harness.example.toml`):

```toml
HARNESS_DECISION_ENGINE = "jev"
HARNESS_DECISION_PROVIDER = "openrouter-jev"
HARNESS_JEV_BUILD = "openrouter/typesafe/jev-1.13@20260917"
```

Its default address is `https://openrouter.ai/api/v1/systemone` (change with `HARNESS_JEV_OPENROUTER_URL`). It sends student work off the machine too, so the consent rule covers it. **Not checked against the real service.** Keep it `off` for a first test.

### 7.6 What stops a live run today (reproduced)

Both of these were run for this tutorial, on a throw-away copy of the practice data, with a dummy key and no network. The messages are the system's own words.

**`cloud-hosted`, `aeh run`: stops at the privacy check.**

```
OPENROUTER_API_KEY=sk-or-DUMMY python -m aeh run --data-dir <folder> --cohort coh-dev-pipe \
    --package-version PKG-DEV-PIPE@64e2dd023c2e --config cloud-hosted.toml
aeh run: RetentionPolicyError: a cloud-hosted run cannot start: the orchestrator was given no provider able to verify zero-retention routing (FR-PROV-14), so retention for the 1 panel members is unconfirmed and nothing was created.
```

The system will not send student work to a service unless it can confirm that the service keeps no copy. The command today gives the run no way to ask. Even if it did, the check asks OpenRouter at `GET <address>/retention/<model>` and treats anything other than a clear *yes*, *true*, *confirmed* or *zero-retention* as *no*. The code's own comment calls the answer format an open question. This is blocker B6.

**`cloud-hosted`, `aeh console`: refused on purpose.**

```
aeh console: ConsoleBindRefused: the console refuses to start under the cloud-hosted profile: authN/authZ is none by design ...
```

**`dev-ci`, `aeh run`: needs recordings, does not call OpenRouter.**

```
aeh run: ValueError: the dev-ci profile records and replays through a fixture directory; set HARNESS_FIXTURE_DIR so the provider has somewhere to read
```

Note that the command prints the OpenRouter model names *first*, even though a replay is what would run. Do not read that as proof OpenRouter was called.

Also not confirmed (blocker B2): the request to OpenRouter has the same unusual shape as in section 6.5, with the whole `openrouter/<vendor>/<model>@<date>` name as `model`. OpenRouter's documented names are plain, such as `qwen/qwen3-30b-a3b`. A stand-in server showed the system sends `Authorization: Bearer <key>` and the body above. One real call would settle whether OpenRouter accepts it.

---

## 8. Start, stop, recover

| Task | Command | Notes |
|---|---|---|
| Start the console | `python -m aeh console --data-dir ~/aeh-data --config <file>` | Prints the port. Runs until Ctrl-C. First it releases stuck work, then resumes running runs. |
| Stop it | Ctrl-C | Closing the browser changes nothing. |
| After a crash or power cut | Start the console again (with the same profile) | Or `python -m aeh recover --data-dir ~/aeh-data`, which releases stuck work only and prints a report. |
| Run one class from the command line | `python -m aeh run --data-dir ~/aeh-data --cohort <cohort> --package-version <version> --config <file>` | Exit code **0** finished, **3** not finished (paused or stopped), **1** an error. |

**About profiles when starting.**

* To merely **look** at a data folder, no profile is needed.
* To let the console **start or resume runs**, or to use `aeh run`, a profile must be set: through `--config` or `HARNESS_PROFILE`. Without one: *"HARNESS_PROFILE must be one of ('edge-local', 'cloud-hosted', 'dev-ci'), got None"*.
* On start the console resumes only runs whose frozen profile is the one in use.
* The practice folder's run froze `edge-local`, so use the local-mode file to work with it.

**About `aeh run` printing.** It first prints `HARNESS_PROFILE source: environment` or `config file`, so you can see which one won.

**Safety refusals** (checked). The console will not start if:

| Situation | Message begins | Fix |
|---|---|---|
| Data folder under `/tmp` | `InsecureLocationError: ... not a safe data directory` | Use a folder in your home |
| Someone set `CONSOLE_BIND=0.0.0.0` | `ConsoleBindRefused: ... refuses a non-loopback bind` | Remove `CONSOLE_BIND` |
| Profile is `cloud-hosted` | `ConsoleBindRefused: ... refuses to start under the cloud-hosted profile` | Use `edge-local` or `dev-ci` |

If a teacher at another desk must see the console, they connect to *your* computer over a secure tunnel (for example `ssh -L 8765:127.0.0.1:8765 you@the-machine`) and open `http://127.0.0.1:8765` on their own screen. Never try to open the console to the network.

## 9. Practice first: the rehearsal folder

The practice data lets you start the console and see every page with no money spent and nothing sent anywhere. Run it once:

```bash
python docs/live-tests/sample-materials/build_rehearsal_data.py
```

It builds `~/aeh-rehearsal` and prints the IDs to use. Checked output:

```
run id ............ run-dev-pipe
cohort id ......... coh-dev-pipe
package version ... PKG-DEV-PIPE@64e2dd023c2e
```

**On Linux, one trap (checked).** The script builds in a temporary folder. On Linux that is `/tmp`, which the system refuses (5.1), and it stops with `InsecureLocationError`. Point the temporary folder into your home first:

```bash
mkdir -p ~/tmp-aeh
TMPDIR=~/tmp-aeh python docs/live-tests/sample-materials/build_rehearsal_data.py
```

Then start the console on it with your local-mode file:

```bash
python -m aeh console --data-dir ~/aeh-rehearsal --config ~/aeh-config/edge-local.toml
```

Now follow the [operating tutorial](operating-tutorial.md).

## 10. Other settings ("knobs")

All are optional. The default is the production value. They exist so a slower computer can adjust without changing code. Set them in the terminal that starts the console or run. Names and defaults were read from the code.

| Variable | What it controls | Default |
|---|---|---|
| `CONSOLE_PORT` | The console's port | A free port, chosen each start |
| `CONSOLE_BIND` | The console's address. Only loopback is accepted. | `127.0.0.1` |
| `HARNESS_CONCURRENCY` | Calls at once (see 6.2 and 7.3) | Hardware limit (local); 8 (OpenRouter) |
| `LOCAL_INFERENCE_BASE_URL` | Local model server address | `http://127.0.0.1:8080/v1` |
| `OPENROUTER_API_KEY` | Your key (never in a file) | none |
| `OPENROUTER_BASE_URL` | OpenRouter address | `https://openrouter.ai/api/v1` |
| `HARNESS_FIXTURE_DIR` | Folder of recordings for `dev-ci` | none (required for `dev-ci`) |
| `HARNESS_RETRY_MAX` | Tries per call (first try plus retries) | 3 |
| `HARNESS_BACKOFF_BASE_MS` | Wait before the first retry; doubles after | 250 |
| `HARNESS_RETRY_AFTER_CEILING_S` | A "come back in N seconds" above this counts as unusable | 120 |
| `HARNESS_PIPE_MAX_PASSES` | Most rounds a run may take | no limit (a run still stops after 3 rounds with no headway) |
| `HARNESS_PIPE_PASS_SLEEP_MS` | Pause between rounds | 0 |
| `HARNESS_ORCH_MAX_ATTEMPTS` | Tries per unit of work | 3 |
| `HARNESS_ORCH_ESCALATION_BUDGET` | Share of cells allowed to widen to extra judges | 0.30 |
| `HARNESS_INGEST_DPI` | Resolution pages are drawn at for reading | 200 |
| `HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS` | Tries to read one page | 3 |
| `HARNESS_INGEST_OCR_CONF_FLOOR` | Reading confidence below which a paper is flagged | 0.70 |
| `HARNESS_INGEST_V4_SEMANTIC_FLOOR` | How much a paper's words must overlap the test's questions | 0.10 |
| `HARNESS_INGEST_RETAIN_PAGE_RASTERS` | Keep the page pictures | on |
| `HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES` | Upload read size | 4 MiB |

A wrong value is refused with the variable's name in the message. Some are checked at the start; others only when first used. So a typo can show up late: watch the first minutes of a run.

## 11. Switching between modes

* One file can hold several sections (`[profiles.edge-local]`, `[profiles.dev-ci]`, and so on). Choose with `HARNESS_PROFILE` in the terminal. No file edit is needed.
* A run **keeps the profile it started with.** A switch never moves an existing run. To grade the same class in another mode, start a new run.

## 12. Security and privacy checklist

Tick each before a test.

- [ ] The data folder is in a home folder, not `/tmp`, and is owner-only.
- [ ] One person uses the machine at a time, and it is locked when unattended. The console has no login: anyone at the keyboard can change grades.
- [ ] Nobody will try to open the console to the network.
- [ ] **OpenRouter mode:** `OPENROUTER_API_KEY` is only in the terminal. It is not in a config file, a script or a chat message.
- [ ] **OpenRouter mode:** a spending limit is set in OpenRouter's dashboard, and the cost ceiling is in the file.
- [ ] **OpenRouter mode:** only `synthetic` classes will be graded, and `HARNESS_ALLOW_REMOTE_REAL_WORK` is not set.
- [ ] **Local mode:** the real SHA-256 fingerprint of each model file is in the file.
- [ ] A backup of the data folder will be taken after the test, before anything is purged.

## 13. When something goes wrong

Every message is the system's real wording (checked unless said).

| You see | It means | Do this |
|---|---|---|
| `HARNESS_PROFILE must be one of (...), got None` | No profile chosen | Set `HARNESS_PROFILE`, or put it at the top of the file |
| `the config file has no section for 'X'` | The file has no section for that profile | Add the section, or choose another profile |
| `HARNESS_HARDWARE_PROFILE is required when HARNESS_PROFILE is 'edge-local'` | Local mode needs the hardware profile | Add it (6.2) |
| `HARNESS_DECISION_ENGINE is required: 'jev' or 'off'` | No default | Add `HARNESS_DECISION_ENGINE = "off"` |
| `panel[0] is a provider-pinned build, but ... 'edge-local' requires a edge-weights build` | An OpenRouter-style name in local mode | Use a file path ending `.gguf` (or another weights suffix), plus fingerprint and `quantization` |
| `panel[0] is not a resolved build identity` | Missing `@...` pin or fingerprint, a moving tag, or no `quantization` (local) | Pin the model (6.3, 7.3) |
| `panel must hold [1, 3, 5] judges, got 2` | Even panel | Use 1, 3 or 5 judges |
| `HARNESS_COST_CEILING is required for backend_profile ...` | OpenRouter profiles need a limit | Add the ceiling and the currency |
| `retention_setting is required for backend_profile 'cloud-hosted'` | Privacy choice not recorded | Add `retention_setting` |
| `ConsentGateError: cohort ... has consent_class 'real'` | Real work may not go to OpenRouter | Use a synthetic or consented class |
| `RetentionPolicyError: a cloud-hosted run cannot start ...` | Privacy check cannot be answered | Blocker B6 (7.6) |
| `ValueError: the dev-ci profile records and replays ...; set HARNESS_FIXTURE_DIR` | `dev-ci` replays recordings | Set the folder, or see 7.6 |
| `OpenRouterProvider needs an API key` | Key not in this terminal | Set `OPENROUTER_API_KEY` (7.2) |
| `... froze backend profile 'X' and this process resolved 'Y'` | You tried to resume a run under another profile | Set `HARNESS_PROFILE` to the one it names |
| `InsecureLocationError` | Folder under `/tmp` | Use a folder in your home |
| `ConsoleBindRefused` | Cloud profile, or a network address | Section 8 |
| `aeh: error: argument command: invalid choice` | `--config` was put before the command | Put it after: `aeh console --data-dir ... --config ...` |

## 14. A short check for the whole setup

1. `aeh --help` shows `run`, `recover` and `console`.
2. `check_config.py` says `ACCEPTED` for your file.
3. The data folder is in your home folder.
4. For OpenRouter mode: `OPENROUTER_API_KEY` is set in this terminal, a spending limit exists, and the two model names are on openrouter.ai/models.
5. For local mode: the model server answers on the address you set, and one real request is accepted (6.5).
6. The rehearsal folder opens in the console, and the monitor page shows `status: complete`.

If you reach step 6, the system is installed and configured correctly. Whether a **live** run then works depends on the blockers in [`02-live-readiness-and-blockers.md`](../live-tests/02-live-readiness-and-blockers.md).
