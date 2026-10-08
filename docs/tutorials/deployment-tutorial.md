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
> 2. **OpenRouter mode grades through OpenRouter, with zero data retention enforced on every request** (section 7.6). Use `dev-ci`: the console refuses `cloud-hosted` on purpose. The class, the package and the papers go in with the shipped commands of sections 8.1 to 8.3; what is still open sits on the console side — the teacher's setup flow, the pages, recording a parked-paper decision — and is listed in [`02-live-readiness-and-blockers.md`](../live-tests/02-live-readiness-and-blockers.md).
>
> So: you can follow every step here and get a correct setup. What still stands between this setup and a teacher running the live test alone is listed in the readiness document.

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

One framing fact for whoever writes the runbooks: **the console is the operator surface and the terminal is the debugging surface** (NFR-CONSOLE-09). The daily operation this tutorial sets up — start it, load papers, watch the run, sort out problems, export — happens in the browser; the `aeh` commands below are for installation, first bring-up and debugging, and the operating tutorial lists every one with the console screen that covers it (the system keeps that inventory and fails a check if a command appears without one, FR-CONSOLE-41).

## 2. The two modes at a glance

A **profile** tells the system where its models run. You pick exactly one for each run. There is **no default**: if you forget, the system stops and says so.

| | Local computer mode | OpenRouter mode (hosted) | OpenRouter mode (console) |
|---|---|---|---|
| Profile name | `edge-local` | `cloud-hosted` | `dev-ci` |
| Where models run | A model server on this computer | OpenRouter | OpenRouter (recordings instead when `HARNESS_FIXTURE_DIR` is set) |
| Console allowed? | Yes | **No** (refused) | Yes |
| Sends student work off the machine? | No | Yes, to zero-retention hosts only | Yes, to zero-retention hosts only |
| Costs money? | No | Yes | Yes |
| Needs | Model files, enough memory | OpenRouter key, internet | OpenRouter key, internet |
| Needs a cost limit in the file? | No | Yes | Yes |
| Needs `retention_setting` in the file? | No | Yes | No |
| Model names look like | A file path | A service name | A service name |
| Use it for | A school with no internet | A hosted service (not built yet) | The live test, with the console |

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

The one install command in section 4 brings every Python library the system uses with it. You do not install anything else by hand.

## 4. Install

Open a terminal in the project folder (the folder that contains `pyproject.toml`).

**Step 1: make a private Python environment.**

```bash
python -m venv .venv
```

**Step 2: switch it on.** You must do this in every new terminal window. Your prompt then starts with `(.venv)`.

* macOS / Linux: `source .venv/bin/activate`
* Windows PowerShell: `.venv\Scripts\Activate.ps1`

**Step 3: install the system.**

```bash
pip install .
```

On Windows, if `pip` itself fails to start (see the "Fatal error in launcher" row in section 13), the private environment is broken or was copied from another computer: redo Steps 1 and 2, or use `python -m pip install .`.

That one command is the whole install. It also downloads the libraries that read PDFs, decode page pictures and talk to the Jev decision engine in OpenRouter mode, so it needs internet access. There are no optional parts to add and nothing to name by hand. (No internet on the school computer? See section 4.1.)

**Step 4: check it worked.**

```bash
aeh --help
```

You should see (checked):

```
usage: aeh [-h] {run,recover,console,cohort,package,ingest,results} ...

Run, recover and serve the agentic evaluation harness.

positional arguments:
  {run,recover,console,cohort,package,ingest,results}
    run                 drive a cohort's run to completion
    recover             reclaim leases, resume and settle grades
    console             recover, then serve the operator console
    cohort              make a cohort (class) with its consent class and
                        roster, or show one
    package             build and publish a package (a test's questions,
                        rubric and keys)
    ingest              read the test paper and answer sheets (PDFs) through
                        the intake checks
    results             show a run's grades and rollup, or export the school-
                        facing set
```

`python -m aeh ...` does exactly the same thing and works even if the `aeh` command is not on your PATH.

**Two details people trip over (both checked):**

* The `--config` option belongs **after** the command word: `aeh console --data-dir ... --config ...`. Putting it first (`aeh --config x console ...`) fails with *"invalid choice: 'x'"*. The comment at the top of `config/harness.example.toml` shows it the wrong way round; ignore that line.
* `aeh recover` takes only `--data-dir` (its two other flags, `--extractor` and `--synthesizer`, pin developer build identities; an operator does not need them). It has no `--config`.

People who will also run the project's own test suite use `pip install -e . -r requirements-dev.txt` instead, on Python 3.13. An operator does not need it.

### 4.1 Installing on a computer with no internet (air gap)

`pip install .` fetches the system's libraries from the internet. If the school computer has no internet, build a *wheelhouse* (a folder of ready-made install files) on a computer that has it, carry the folder across, and install from it.

The connected computer must run the **same operating system, the same processor type (for example Intel/AMD or ARM) and the same Python version** as the school computer: some of the libraries ship a different file for each.

On the connected computer, in the project folder, with its own `.venv` switched on:

```bash
pip download . "setuptools>=69" -d wheelhouse
```

Copy the project folder, including the new `wheelhouse` folder but **not** its `.venv` folder (a private environment does not move between computers), to the school computer. There, do Steps 1 and 2 above, then install with no internet:

```bash
pip install --no-index --find-links wheelhouse .
```

`--no-index` tells pip not to look online; `--find-links wheelhouse` tells it to use the folder instead. `setuptools` is in the download because pip needs it to build the system itself. Then check with Step 4 as usual. **Not checked on a real air-gapped machine.**

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
| `HARNESS_DECISION_ENGINE` | `off` or `jev`. Default: `jev` on `cloud-hosted` and `dev-ci`, `off` on `edge-local`. `off` means the page reader and the judges do all the grading. | All |
| `HARNESS_JEV_CONFIDENCE_THRESHOLD` | Jev's confidence bar, 0.50 up to (not including) 1.00. Default 0.80 (0.85 for `openjev-small`). Also settable as `decision_confidence_threshold` in the profile's section of the config file; the environment wins. | All, with Jev on |
| `HARNESS_QA_MODEL` | The help assistant's model: a pinned OpenRouter build (`vendor/model@2026-09-01`). Default: the first judge. Ignored on `edge-local`, where the assistant is always the first judge. | `cloud-hosted`, `dev-ci` |
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

Now the model line itself, part by part. This is the one place where the configuration asks you to assemble a string by hand, so every part of it is explained here.

**The `build_id` has the form `<path to file>@sha256:<fingerprint>`, and the `quantization` line must also be set.** All three together — the path, the fingerprint and the quantization — are the build's identity: leave any one out and the string does not name a build.

| Part | Example | What it means | How to obtain it |
|---|---|---|---|
| The path | `/models/qwen3-30b-a3b-q4.gguf` | The model file on this computer | Copy the full path of the file you downloaded. It **must end in one of** `.gguf`, `.safetensors`, `.bin`, `.pt`, `.mlx` or `.npz`. That suffix decides how the whole string is read: a name ending like one of these is read as a local weights build, anything else as an OpenRouter-style name, and in local mode the other form is refused (checked: *"panel[0] is a provider-pinned build, but backend_profile 'edge-local' requires a edge-weights build"*) |
| `@sha256:` | `@sha256:` | The separator before the fingerprint | Type it literally, always exactly this. What follows it must be hexadecimal characters only (0-9, a-f); anything else is refused (checked: *"panel[0] is not a resolved build identity"*) |
| The fingerprint | 64 hex characters | The SHA-256 hash of the weights file | `sha256sum /models/qwen3-30b-a3b-q4.gguf` (macOS / Linux) or `Get-FileHash -Algorithm SHA256 C:\models\qwen3-30b-a3b-q4.gguf` (Windows PowerShell). **The system does not check the fingerprint against the file** — the checker accepted one of all zeros. Put the real one in anyway: it is how you can later prove which exact model graded a student |
| `quantization` (a separate line) | `q4` | How compressed the weights are | Any non-empty label works, but use the one the file's own name carries (`Q4_K_M` → `q4`), so the record later reads true. Missing or empty is refused |
| `provider` (a separate line) | `local` | How the model is served: `local`, `local-server`, `ollama` or `vllm-mlx` | All four use the same code. Use `local` unless you want the name to describe your server |

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
> A test against a stand-in server on this machine showed exactly what the system sends. It posts to `<address>/chat/completions` in the standard chat format, with one message per part of the prompt:
>
> ```json
> {"model": "/models/x-q4.gguf@sha256:0000...0000",
>  "messages": [{"role": "user", "name": "instruction", "content": "Pick a band"},
>               {"role": "user", "name": "submission", "content": "student text"}],
>  "temperature": 0.0}
> ```
>
> A page picture is sent as an image part (`"type": "image_url"` with a `data:image/png;base64,...` address), which is what vision models expect. One thing is still unusual: the `model` is the whole `build_id`, including the file path and the fingerprint. Servers such as Ollama, llama.cpp and vLLM usually want the name they serve the model under. **Whether your server accepts this as it is has not been checked.** Before a real test, send one real request and see. If the server refuses the model name, you will need to fix that; it is engineering work.

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
| The console starts under `edge-local` and serves pages | Whether a real server accepts the model name (6.5) |
| The request the system sends, and the address it uses | How fast or accurate the models are on your computer |
| `aeh run` under `edge-local` on a finished practice run succeeds (nothing needed a model) | Windows |

---

## 7. OpenRouter mode (`cloud-hosted` and `dev-ci`)

### 7.1 Which profile do I use?

* **`dev-ci`** is the profile for the live test: it grades through OpenRouter and the console runs under it. With `HARNESS_FIXTURE_DIR` set it replays recordings instead (the test tier).
* **`cloud-hosted`** also grades through OpenRouter, and `aeh run` works under it, but the console **refuses to start** under it (it has no login, so it must never be a hosted service). It is meant for a future hosted service with its own login.

So use `dev-ci`. The two files are almost the same; the differences are in the table in section 2.

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

* **`HARNESS_COST_CEILING`** is required for both profiles. **It counts estimates, not the bill.** Each model call is counted at the system's fixed price sheet before it is sent: about $0.007 a call with the default settings, while the real calls in 7.6 cost about $0.0001. So a ceiling of `5` stops a run after roughly 700 model calls, whatever OpenRouter actually charges; raise it if a run pauses on the ceiling, and keep OpenRouter's own spending limit (7.2) as the real stop. Without it: *"HARNESS_COST_CEILING is required for backend_profile 'cloud-hosted'"*. It must be a whole or decimal number, not negative. `5` is plenty for ten sample answer sheets. The environment can override it.
* **`retention_setting`** is required for `cloud-hosted` only. It must be `provider-default` or `zero-retention`. It *records* your choice. It does **not** make the privacy check pass (see 7.6). Leaving it out is refused: *"retention_setting is required for backend_profile 'cloud-hosted'"*.
* **Model names** are written `openrouter/<vendor>/<model>@<pin>`. The three parts mean different things and come from different places — the table under this list explains each one and how to obtain it. The `@...` part is required, and a moving tag such as `@latest` is refused. Do **not** give these a `quantization` line (the provider owns it).
* **Do the models exist?** Yes, for the two names in the shipped files: both answered real calls on 2026-10-03 (checked). How to confirm any model yourself is in the table below.
* **Judges:** one judge is the smallest test, but with one judge nobody can disagree, so the system cannot show agreement figures. For a real accuracy test, use **three** judges from different model families (add two more `[[profiles....panel]]` blocks). An even number such as two is refused: *"panel must hold [1, 3, 5] judges, got 2"*.
* **`HARNESS_CONCURRENCY`** sets how many calls run at once. The default is 8. Here it *sets* the number (it does not just lower it): `20` is accepted. OpenRouter's own rate limits may refuse a high number.

**The model string, part by part.** A model name such as `openrouter/qwen/qwen3-30b-a3b@2026-06-01` is three parts glued together, each with its own meaning and its own source:

| Part | Example | What it means | How to obtain it |
|---|---|---|---|
| `openrouter/` | `openrouter/` | The literal prefix that names the provider | Nothing to choose: always written exactly like this |
| `<vendor>/<model>` | `qwen/qwen3-30b-a3b` | OpenRouter's own slug — the one in the model page's address (`https://openrouter.ai/qwen/qwen3-30b-a3b`) | Copy it from the model's page, or list every slug the service knows with `curl -s https://openrouter.ai/api/v1/models` and read the `id` fields (no key needed). **Only this part is sent to OpenRouter** |
| `@<pin>` | `@2026-06-01` | The harness's own record of which version you meant. OpenRouter has no date pin: the checker accepts any non-empty pin that is not a moving tag, and the pin is stripped before a request is built | Choose the date you confirmed the model — a good source is the `created` field the model-list call above returns for that slug (it converts to a date), or simply the day you checked the model on openrouter.ai/models. Keep it stable afterwards, so later records read true |

**The pin is your record, not a version OpenRouter serves.** Because a request carries only `<vendor>/<model>`, OpenRouter may point that slug at an updated upstream model at any time; the pin does not prevent that. What a run actually used is recorded afterwards: each reply names the model that served it, and that record is what you later prove a student was graded by. The pin says what you *intended*; the reply says what *answered*; provenance needs both.

### 7.4 Who may be graded: the consent rule

Before any work leaves the machine, the system checks the class's **consent class** (checked):

| The class is marked | Result |
|---|---|
| `synthetic` (made-up practice papers) | Allowed |
| `consented` (students or guardians agreed) | Allowed |
| `real`, or not marked (counts as real) | **Refused**: *"cohort ... has consent_class 'real', which is neither 'synthetic' nor 'consented', so its work may not be sent to a 'dev-ci' provider"* |

A named person can override this by setting `HARNESS_ALLOW_REMOTE_REAL_WORK=true` **and**, in the file, `allow_remote_real_work_supplied_by = "<a name>"`. Without a name the override is refused (checked: *"allow_remote_real_work_supplied_by must name who authorised ... the gate still refuses"*). **For a first test, use only synthetic papers and do not use the override.**

### 7.5 The decision engine in OpenRouter mode (leave it off)

`HARNESS_DECISION_ENGINE = "jev"` needs a pinned build (its library already came with `pip install .`), for example (from `config/harness.example.toml`):

```toml
HARNESS_DECISION_ENGINE = "jev"
HARNESS_DECISION_PROVIDER = "openrouter-jev"
HARNESS_JEV_BUILD = "openrouter/typesafe/jev-1.13@20260917"
```

Its default address is `https://openrouter.ai/api/v1/systemone` (change with `HARNESS_JEV_OPENROUTER_URL`). The build id is written in the same shape as §7.3's model names, `openrouter/...@<pin>`: the same pin rules apply, and the `@...` part is your own record again — it is stripped before the request, not something the service knows. It sends student work off the machine too, so the consent rule covers it. **Not checked against the real service.** Keep it `off` for a first test.

### 7.6 What a run through OpenRouter does now (reproduced)

`aeh run` and the console's start-run, under `dev-ci`, now grade through OpenRouter. Reproduced on a throw-away copy of the practice data, with a dummy key and the address pointed at a dead port on this machine, so nothing left it:

```
OPENROUTER_API_KEY=sk-or-DUMMY OPENROUTER_BASE_URL=http://127.0.0.1:9/api/v1 \
  python -m aeh run --data-dir <folder> --cohort coh-dev-pipe \
  --package-version PKG-DEV-PIPE@64e2dd023c2e --config docs/live-tests/config/live-test.dev-ci.toml
HARNESS_PROFILE source: config file
provider: OpenRouter at http://127.0.0.1:9/api/v1 (zero data retention enforced)
...
"pause_reason": "ProviderUnavailableError: the provider did not answer within the retry budget ...",
"status": "paused"
```

The `provider:` line says what will really answer: OpenRouter, a local model server, or recordings. (Before, the command printed OpenRouter model names even when a replay was what ran.) A provider that does not answer pauses the run (exit code 3) rather than failing it; start it again once the cause is fixed.

**Privacy (zero data retention).** Every request to OpenRouter carries `"provider": {"zdr": true, "data_collection": "deny"}`. OpenRouter then sends the work only to a host that keeps no copy and does not train on it, or refuses the request (`HTTP 404 ... No endpoints found matching your data policy`), which pauses the run. Checked on 2026-10-03: both models in the shipped file have such hosts (`qwen/qwen3-30b-a3b` via DeepInfra, `qwen/qwen3-vl-8b-instruct` via Parasail). The `cloud-hosted` privacy check at run start is answered by this rule, so a `cloud-hosted` `aeh run` now starts. The consent rule (7.4) still decides first whether a class's work may leave the machine at all.

**Recordings.** Set `HARNESS_FIXTURE_DIR` and `dev-ci` replays recordings from that folder instead, with no network. That is the test tier; leave it unset for a real run.

**Still refused, on purpose.** The console will not start under `cloud-hosted` (it has no login):

```
aeh console: ConsoleBindRefused: the console refuses to start under the cloud-hosted profile: authN/authZ is none by design ...
```

Use `dev-ci` for the console.

**What still blocks a full live test.** Nothing blocks a *supervised* one: the command-line path of section 8 creates the class, builds the package and reads the scans. What is still missing is the console side that would let a teacher operate alone — the teacher's setup flow (B5), the pages the guides promise (B7), and recording a parked-paper decision (B8). See the readiness document.

**The request format (blocker B2) was changed and then checked with real calls (2026-10-03).** The first real call had failed: the system sent the whole `openrouter/<vendor>/<model>@<date>` name and a non-standard body, and OpenRouter refused it. The system now sends the plain name OpenRouter knows (`qwen/qwen3-30b-a3b`) and the standard chat format from section 6.5, with `Authorization: Bearer <key>`. A real call through the changed system succeeded (checked, 2026-10-03): it answered `ready`, reported `qwen/qwen3-30b-a3b` as the model that served it, and OpenRouter's cost of $0.00011245. Two more real calls also succeeded (checked): a judge-style request with three parts answered `{"band": "met"}`, and a page picture sent to `qwen/qwen3-vl-8b-instruct` was read back exactly ("The answer is 42"). So both model names in the shipped `dev-ci` file exist at OpenRouter. The model spent 213 output tokens to say one word, because it reasons first: leave the output cap generous for such models. A refused request now says why, in OpenRouter's words. A bad key, no credit or an unknown model (`HTTP 401`, `402`, `404`) stops the run, for example `HTTP 401 from the provider: the credentials were refused (for OpenRouter, check OPENROUTER_API_KEY)`. A refusal of one paper only (too long, flagged) sets that paper aside and the run goes on.

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

### 8.1 Create a class (a "cohort") and its student list

Every class you grade is a **cohort** with two things fixed when it is created:

* its **consent class**: `synthetic` (made-up practice papers), `consented` (the students or guardians agreed), or `real` (everything else). In OpenRouter mode only `synthetic` and `consented` classes may be graded (section 7.4). There is no default, and it can never be changed later.
* its **student list** (the roster): each student's **full name**, as they write it on their papers, and optionally a student ID. The intake check V3 reads the name the page reader transcribes after `Student:` and matches it to the list forgiving case, extra spaces, accents (`Chloé` = `Chloe`) and order (`Volkov Dmitri` = `Dmitri Volkov`); nothing else is guessed. A name that matches no one, or matches two students equally, waits in quarantine for the operator with the possible students listed. A student ID is never required and never enough on its own. If two students share a name, their papers wait in quarantine with both listed, for the operator to settle.

Write the list in a file, in one of two shapes:

* one full name per line (blank lines and lines starting with `#` are skipped), or
* a CSV whose first row names a `full_name` column, and optionally a `student_ref` column of IDs. Other columns are ignored, so a sheet exported from Excel works once that header is there. A student with no ID gets an internal reference made up for them.

```
full_name,student_ref
Ann Lee,S9-001
Bo Chen,S9-002
Cy Diaz,
```

The reader never guesses. These are refused, naming the line, and nothing is created: a CSV with a `student_ref` column but no `full_name` column (a list of IDs alone), a file with several columns but no `full_name` header, a first line that looks like a header such as `id` or `name` (it would become a student), and a row with an empty `full_name` cell (every student needs a name).

The class list stays in the class's own file; the identity check refers to students by their reference, and removes the written name before a paper's text is sent to a model to confirm which test it is. The marks export adds a `full_name` column, read from the class list when the export is made.

Then (checked):

```bash
python -m aeh cohort create --data-dir ~/aeh-data --cohort class-9a --consent synthetic --roster roster.csv
```

```json
{
  "cohort_id": "class-9a",
  "consent_class": "synthetic",
  "created_at": "2026-10-03T16:45:40.293426+00:00",
  "roster_size": 3
}
```

* `aeh cohort add-students --data-dir ... --cohort class-9a --roster more.csv` adds late students, in the same file shapes. An ID already on the list is refused, by name, and nothing is added.
* `aeh cohort show --data-dir ... --cohort class-9a` prints the class as above.
* The class ID becomes a file name, so it may hold only **lower-case** letters, digits, `.`, `_` and `-` (on Windows and macOS `Class-9A` and `class-9a` would be the same file), and may not be a Windows device name such as `con` or `nul`.
* Running `create` again for the same class is refused (*"already exists; it is never overwritten"*), and so is a repeated ID, or one holding a space or an invisible character. Every refusal writes nothing, and a mistyped ID or a bad file is refused before the data folder is touched.
* Creating a `real` class prints a reminder that OpenRouter mode will refuse it.

Not yet recorded: who created the class. Only the time is stored.

### 8.2 Build a package (the test, its rubric and keys)

A **package** is everything about one test: its questions, the rubric lines and their bands, the multiple-choice keys and the grade boundaries. Once built it is published and can never be changed. The spec file below is the **debugging/export path**, not the teacher's path (FR-PKG-27): the system creates the valid package file itself from what the teacher confirmed in setup, so a teacher never authors a spec. A published version's spec is a **system-emitted export** — `aeh package export --data-dir ~/aeh-data --package-version <version> --spec out.toml` writes it, and the `aeh package build --spec` command below accepts that export unchanged — and the command is kept so an engineer can build a package without the setup flow, as this tutorial does with the sample physics test. Write it as a TOML file; [`docs/live-tests/config/ps9-forces-01.package.toml`](../live-tests/config/ps9-forces-01.package.toml) is a complete example, the sample physics test. In short:

* `package`: the test's name **exactly as printed on the paper** (`Assessment: PS9-FORCES-01`). Intake's right-test check compares the two, ignoring case.
* `approved_by`: who approved the questions, keys and rubric.
* one `[[question]]` per question, in paper order: `id`, `type` (`mcq` or `open`), `points`, `text`, `options` for multiple choice, and `model_answer`. The judges are shown the text and the model answer, so write them in full.
* one `[[criterion]]` per rubric line: `id`, `question`, and either `key = "C"` (multiple choice; it must be one of the question's options) or `bands`, listed **worst to best**, an even number from 2 to 6, each with `name`, `points` and `descriptor`. The band names are the words a teacher later uses to change a mark. Every question needs at least one line, and a multiple-choice question needs a key, not bands.
* `[grades]`: the lowest total that earns each grade.

Then (checked):

```bash
python -m aeh package build --data-dir ~/aeh-data --spec docs/live-tests/config/ps9-forces-01.package.toml
```

```json
{
  "answer_keys": 4,
  "approved_by": "Sample-materials teacher",
  "criteria": 6,
  "grades": ["A", "B", "C", "D", "F"],
  "package_id": "PS9-FORCES-01",
  "package_version": "PS9-FORCES-01@8828fa5b16da",
  "questions": 6
}
```

Keep the `package_version` value: `aeh run` and the console's start-run need it. Building the same `package` again is refused (*"already exists. A built package is never changed"*); to correct a test, give the corrected spec a new `package` id. Because a built package can never be changed, the command checks the whole file before writing anything, and refuses with the reason (and nothing created, not even the data folder) when, for example: a key is not one of its question's options, a question has no rubric line, a band has no `points`, a judged line sits on a multiple-choice question, or a field has the wrong type. A rule the package itself enforces (for example an odd number of bands) also leaves nothing behind.

Checked: this package and a class created with `aeh cohort create` carry the six physics sample answer sheets through the real intake checks exactly as the live-test guide's table says.

### 8.3 Read the papers in (`aeh ingest`)

With the class created (8.1) and the package built (8.2), read the scans. You need the test paper once per class, and the answer sheets as **one PDF per student** (a folder of them is fine). Every sheet needs the test name and the student's ID written at the top, because the checks read both.

```bash
python -m aeh ingest --data-dir ~/aeh-data --cohort class-9a \
  --package-version PS9-FORCES-01@8828fa5b16da --config docs/live-tests/config/live-test.dev-ci.toml \
  --assessment 01-test-paper.pdf answer-sheets/
```

It prints the provider (`provider: OpenRouter at ... (zero data retention enforced)` under `dev-ci`), one line per sheet, then the whole result. Each sheet is read by the page-reading model in the configuration and goes through the five checks; a sheet that fails one waits in quarantine for the operator (the operating tutorial, Phase 2). Checked with a stand-in for OpenRouter over the six physics sample sheets: three `ok`, two `incomplete` (a doubled mark; no name), one `unmatched_assessment` (the wrong test). **Not checked: a real model reading real pages**; that is what the first live run shows.

* Running it again over the same folder skips every sheet already read (`skipped ... already read into this cohort`), so a paper is never graded twice. Add new sheets to the folder and run it again. A sheet that could not be read at all (status `unreadable`) *is* read again on a re-run, and each failed try leaves one more quarantined record in S8 to close as `unresolvable`; none of those is ever graded.
* Stopping it with Ctrl-C is safe. The next `aeh ingest` parks the paper that was being read when you stopped (`parked 1 paper(s) an earlier, cut-off read left behind`) in quarantine, where you close it, and reads that sheet again.
* If **no** sheet could be read, the command exits 1 with `no answer sheet could be read`. That is almost always the model, not the scans: a wrong or revoked `OPENROUTER_API_KEY`, no credit left, or a model name OpenRouter does not know. The warnings above that line say which. Fix it, close the quarantined records in S8, and run the command again.
* A `real` class is refused before any page is sent (the consent rule, 7.4).
* These page-reading calls cost money but are not counted against a run's cost ceiling: no run exists yet. OpenRouter's own limit (7.2) is the stop.
* The console's upload page still only stores files; it does not read them. Use this command.

### 8.4 A first live test, start to finish (Windows PowerShell)

This grades the sample physics test's six typed answer sheets through OpenRouter, using the files the repository ships. It costs well under a dollar. Run it in a new, empty data folder. Steps 1 to 4 were checked here with a stand-in for OpenRouter; **steps 4 and 5 against real OpenRouter have not been run yet**: they are the live test.

```powershell
# 0. Once per terminal window (section 4 and 7.2)
.venv\Scripts\Activate.ps1
$env:OPENROUTER_API_KEY = "sk-or-..."
$D = "$HOME\aeh-live-1"
$S = "docs\live-tests\sample-materials\pdf\PS9-FORCES-01"
# A class of six is small: let every disagreement get more judges (the 0.30 default is a share
# of all answers, and with six papers it stops the run with "no progress").
$env:HARNESS_ORCH_ESCALATION_BUDGET = "1.0"
# The shipped file has ONE judge. Turn off the random extra-judge sample (7% of answers get
# three judges, to measure the system), or add escalation judges to the file (see below).
$env:HARNESS_ORCH_RANDOM_ARM_RATE = "0"

# 1. The class: synthetic practice work, six students (8.1)
python -m aeh cohort create --data-dir $D --cohort ps9-class --consent synthetic --roster docs\live-tests\config\ps9-roster.txt

# 2. The package: questions, rubric, keys, grade boundaries (8.2). Copy package_version from the output.
python -m aeh package build --data-dir $D --spec docs\live-tests\config\ps9-forces-01.package.toml
$V = "PS9-FORCES-01@<the 12 characters it printed>"

# 3. Check the configuration (5.4)
python docs\live-tests\sample-materials\check_config.py docs\live-tests\config\live-test.dev-ci.toml

# 4. Read the papers in with the real page-reading model (8.3)
python -m aeh ingest --data-dir $D --cohort ps9-class --package-version $V `
  --config docs\live-tests\config\live-test.dev-ci.toml `
  --assessment "$S\01-test-paper.pdf" "$S\answer-sheets"

# 5. Grade them (section 8)
python -m aeh run --data-dir $D --cohort ps9-class --package-version $V `
  --config docs\live-tests\config\live-test.dev-ci.toml

# 6. Look at the results (the operating tutorial)
python -m aeh console --data-dir $D --config docs\live-tests\config\live-test.dev-ci.toml
```

What to expect, and what to record:

* **Step 4.** If the model writes the page markup the checks expect, the outcome is three `ok`, two `incomplete` (S9-004: a doubled mark; S9-006: no name) and one `unmatched_assessment` (S9-005: the wrong test), as the live-test guide says. If good papers are parked instead, that is the most important finding of the test: note each paper's status, and keep the folder.
* **Step 5.** Exit code 0 means every paper was graded. Exit code 3 means the run paused: read `pause_reason` in what it printed (for example the cost ceiling, 7.3, or an OpenRouter refusal, 7.6), fix it, and run the same command again; it continues where it stopped.
* **Extra judges.** When judges are unsure or disagree, the system adds two more judges to that answer, and one more if a judge call is lost. With one judge in the file and no extra models, it cannot: the answer keeps its score, marked provisional, and goes to teacher review (the run's output says `no real judge for seats 2-3`, and the score's state is `provisional_unreviewed`). To let it add judges, add `[[profiles.dev-ci.escalation_judge]]` tables to the configuration file, each a **different** model from the panel and from each other, checked on a zero-retention host first (7.6). For a one-judge panel, **two** are enough to leave the random sample on (drop the `HARNESS_ORCH_RANDOM_ARM_RATE` line); if the sample is on and there are fewer, `aeh run` refuses before starting and says how many to add. Each one more lets one more step happen instead of leaving the answer provisional; **five** cover every seat a one-judge run can ever need (a sampled answer starts with three judges, can widen to five, and can get one replacement).
* **Step 6.** Open `/runs/<run id>/rollup` and `/quarantine` (the operating tutorial, section 4). The parked papers can be released or closed there (section 5); the no-name paper can only be closed.

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
| `HARNESS_FIXTURE_DIR` | Set it and `dev-ci` replays recordings from this folder instead of calling OpenRouter | not set |
| `HARNESS_PIPE_UNIT_TOKENS_IN` / `HARNESS_PIPE_UNIT_TOKENS_OUT` | Tokens one model call is priced at, before it is sent, against the cost ceiling. The run's spend is the sum of these estimates, not OpenRouter's bill (see 7.3) | 4000 / 1500 |
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
| `HARNESS_JEV_BUILD is required when HARNESS_DECISION_ENGINE is 'jev'` | Jev is on (the default on `cloud-hosted` and `dev-ci`) but no Jev build is named | Add `HARNESS_JEV_BUILD`, or set `HARNESS_DECISION_ENGINE = "off"` |
| `decision_confidence_threshold must lie in [0.50, 1.00), got ...` (or `HARNESS_JEV_CONFIDENCE_THRESHOLD`) | The Jev threshold is out of range; it is refused, never rounded | Use a value from 0.50 up to (not including) 1.00 |
| `HARNESS_QA_MODEL is not a resolved build identity` | The Q&A model has a moving tag (`:free`, `@latest`) or no `@` pin | Pin it, e.g. `vendor/model@2026-09-01` |
| `panel[0] is a provider-pinned build, but ... 'edge-local' requires a edge-weights build` | An OpenRouter-style name in local mode | Use a file path ending `.gguf` (or another weights suffix), plus fingerprint and `quantization` |
| `panel[0] is not a resolved build identity` | Missing `@...` pin or fingerprint, a moving tag, or no `quantization` (local) | Pin the model (6.3, 7.3) |
| `panel must hold [1, 3, 5] judges, got 2` | Even panel | Use 1, 3 or 5 judges |
| `HARNESS_COST_CEILING is required for backend_profile ...` | OpenRouter profiles need a limit | Add the ceiling and the currency |
| `retention_setting is required for backend_profile 'cloud-hosted'` | Privacy choice not recorded | Add `retention_setting` |
| `ConsentGateError: cohort ... has consent_class 'real'` | Real work may not go to OpenRouter | Use a synthetic or consented class |
| `HTTP 404 ... No endpoints found matching your data policy` | No zero-retention host serves that model | Choose another model (7.6) |
| `OpenRouterProvider needs an API key` | Key not in this terminal | Set `OPENROUTER_API_KEY` (7.2) |
| `... froze backend profile 'X' and this process resolved 'Y'` | You tried to resume a run under another profile | Set `HARNESS_PROFILE` to the one it names |
| `InsecureLocationError` | Folder under `/tmp` | Use a folder in your home |
| `ConsoleBindRefused` | Cloud profile, or a network address | Section 8 |
| `Fatal error in launcher: Unable to create process using '...python.exe'` (Windows, when running `pip` or `aeh`) | The private environment is broken: it was copied from another computer or folder, or its Python has moved, so the commands inside it still point at the old location | Delete the `.venv` folder and redo Steps 1 to 3 of section 4; if `pip` alone still fails, use `python -m pip install .` |
| `aeh: error: argument command: invalid choice` | `--config` was put before the command | Put it after: `aeh console --data-dir ... --config ...` |

## 14. A short check for the whole setup

1. `aeh --help` shows `run`, `recover`, `console`, `cohort`, `package`, `ingest` and `results`.
2. `check_config.py` says `ACCEPTED` for your file.
3. The data folder is in your home folder.
4. For OpenRouter mode: `OPENROUTER_API_KEY` is set in this terminal, a spending limit exists, and the two model names are on openrouter.ai/models.
5. For local mode: the model server answers on the address you set, and one real request is accepted (6.5).
6. The rehearsal folder opens in the console, and the monitor page shows `status: complete`.

If you reach step 6, the system is installed and configured correctly, and the section-8 commands cover a supervised live test. What still stands between that and a teacher operating alone is in [`02-live-readiness-and-blockers.md`](../live-tests/02-live-readiness-and-blockers.md).
