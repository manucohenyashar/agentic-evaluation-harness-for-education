# Live teacher test: start here

Everything needed to host, configure and run a live grading test of the system through OpenRouter, written for operators and teachers who are not programmers.

## The one-minute version

* **You can run a live test today, from the terminal.** The shipped commands create the class, publish the test, read the scanned answer sheets with a real page-reading model, and grade them with real judge models on OpenRouter. Every request asks OpenRouter for zero data retention. The steps are [below](#run-the-live-test-step-by-step).
* **Run it with an engineer beside you the first time.** The steps have each been checked against a stand-in for OpenRouter, and real OpenRouter calls have been made for each kind of request (2026-10-03), but **a whole test against real OpenRouter has not been run yet**. Your first run is that test, so some surprises are expected (see [what to watch for](#what-to-watch-for-on-the-first-run)).
* **The console can't run the test on its own yet.** It is for watching, reviewing, finalizing and exporting. Reading the uploaded papers, setting up a test on screen, and recording what the operator decides about a parked paper still need the terminal or are missing. The open gaps are listed in [`02-live-readiness-and-blockers.md`](02-live-readiness-and-blockers.md).
* **The two sample tests cover every kind of rubric line.** The physics test has multiple-choice keys and band lines. The English test has one line of each scoring method: an evidence checklist (`evidence_sum`), a band line (`bands`) and a line the teacher described in their own words (`general`). Run both to grade every rubric type.

## Run the live test, step by step

Windows PowerShell, from the project folder (the one that contains `pyproject.toml`). macOS and Linux use the same commands with `/` in paths and `export NAME=value` instead of `$env:NAME = "value"`. Allow about an hour. With the shipped models it should cost well under a dollar, but nobody has measured it yet.

### Before you start (once)

1. **Install** ([deployment tutorial, section 4](../tutorials/deployment-tutorial.md)):
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   python -m pip install .
   python -m aeh --help
   ```
   The last line should list `run, recover, console, cohort, package, ingest, results`.
2. **Get an OpenRouter key** at openrouter.ai, and **set a spending limit in OpenRouter's dashboard** (for example $5). That limit is the real stop: the system's own ceiling only checks an estimate.
3. **Look at the models** in [`config/live-test.dev-ci.toml`](config/live-test.dev-ci.toml). It ships with one page-reading model and one judge, both of which answered real zero-retention calls on 2026-10-03. If you change them, check the new ones on openrouter.ai/models first. Every line of that file is explained in its comments.

### Step 0: open a terminal and set it up (every new window)

```powershell
.venv\Scripts\Activate.ps1
$env:OPENROUTER_API_KEY = "sk-or-..."      # your key; never write it in a file
$D = "$HOME\aeh-live-1"                    # a NEW, empty data folder for this test
$CFG = "docs\live-tests\config\live-test.dev-ci.toml"
# A class of six is small: let every disagreement get more judges.
$env:HARNESS_ORCH_ESCALATION_BUDGET = "1.0"
# The shipped file has ONE judge: turn off the random extra-judge sample.
$env:HARNESS_ORCH_RANDOM_ARM_RATE = "0"
```

### Step 1: check everything offline (free, no network)

```powershell
python docs\live-tests\sample-materials\check_config.py $CFG
python docs\live-tests\sample-materials\verify_sample_materials.py
```

The first should print `ACCEPTED`, profile `dev-ci`, and `OPENROUTER_API_KEY . set`. The second should end with two `OK:` lines: every sample sheet behaves at intake as expected, and both packages build with every rubric method. If either one fails, stop here.

### Step 2: the physics test (multiple-choice keys and band lines)

```powershell
$P = "docs\live-tests\sample-materials\pdf\PS9-FORCES-01"

# 2a. The class: six made-up students, marked synthetic
python -m aeh cohort create --data-dir $D --cohort ps9-class --consent synthetic --roster docs\live-tests\config\ps9-roster.txt

# 2b. The test: questions, keys, rubric, grade boundaries. Keeps the printed version id in $V.
$V = (python -m aeh package build --data-dir $D --spec docs\live-tests\config\ps9-forces-01.package.toml | ConvertFrom-Json).package_version
$V                                          # should print PS9-FORCES-01@ and 12 characters

# 2c. Read the papers with the real page-reading model (this calls OpenRouter)
python -m aeh ingest --data-dir $D --cohort ps9-class --package-version $V --config $CFG `
  --assessment "$P\01-test-paper.pdf" "$P\answer-sheets"

# 2d. Grade them with the real judge (this calls OpenRouter)
python -m aeh run --data-dir $D --cohort ps9-class --package-version $V --config $CFG
```

**Expect at 2c:** three sheets `ok`, two `incomplete` (S9-004 has two ticks on one question; S9-006 has no name) and one `unmatched_assessment` (S9-005 is the wrong test). Those three are parked on purpose.
**Expect at 2d:** a line starting `provider: OpenRouter`, then a JSON result. Copy its `run_id`. `"status": "complete"` and exit code 0 mean the run finished — also read its `grades_final`: if some judge answers were refused, the marks are held provisional and `grades_final` is 0 even though the run finished (see the table below).

### Step 3: the English test (evidence checklist, bands, teacher's own words)

```powershell
$E = "docs\live-tests\sample-materials\pdf\ENG7-READ-01"
python -m aeh cohort create --data-dir $D --cohort eng7-class --consent synthetic --roster docs\live-tests\config\eng7-roster.txt
$VE = (python -m aeh package build --data-dir $D --spec docs\live-tests\config\eng7-read-01.package.toml | ConvertFrom-Json).package_version
$VE                                         # should print ENG7-READ-01@ and 12 characters
python -m aeh ingest --data-dir $D --cohort eng7-class --package-version $VE --config $CFG `
  --assessment "$E\01-test-paper.pdf" "$E\answer-sheets"
python -m aeh run --data-dir $D --cohort eng7-class --package-version $VE --config $CFG
```

**Expect:** all four sheets `ok` at intake, and a `complete` run. Copy this run's `run_id` too.

### Step 3b: a test from the teacher's own documents (the authoring walk)

The two sample tests above use packages this repository already ships. For the teacher's own test, the same `$D` and `$CFG` make the package from the teacher's documents: the draft reads them with the real page-reading model and works out the questions, rubric and grade boundaries; the teacher fills what it leaves open; the build publishes exactly as in 2b, and the class, the reading and the grading then run exactly as in 2a–2d with the teacher's package in `$V`. Allow a few minutes of model time for one document.

```powershell
# The teacher's test paper (PDF) -> a draft spec and an authoring report (this calls OpenRouter)
python -m aeh author draft --config $CFG --docs "path\to\teachers-test.pdf" --out $D\authoring

# Read the report it names, then walk the open items: one prompt per item,
# one answer per line. Enter on a blank line skips an item; Ctrl-Z then Enter
# (Ctrl-D on macOS/Linux) ends the walk early, keeping what you already answered.
python -m aeh author review --draft $D\authoring\<package-id>.package.draft.toml

# Publish it, exactly like 2b
$V = (python -m aeh package build --data-dir $D --spec $D\authoring\<package-id>.package.draft.toml | ConvertFrom-Json).package_version

# The class, exactly like 2a: a roster file, one student name per line
# (docs\live-tests\config\ps9-roster.txt shows the shape). synthetic is for
# made-up students only; real students need the consented path (see
# 01-hosting-and-configuration.md, the consent rule).
python -m aeh cohort create --data-dir $D --cohort teachers-class --consent synthetic --roster "path\to\roster.txt"

# Read the scanned sheets and grade them, exactly like 2c and 2d but with the
# teacher's package in $V and the teacher's class:
python -m aeh ingest --data-dir $D --cohort teachers-class --package-version $V --config $CFG `
  --assessment "path\to\teachers-test.pdf" "path\to\scanned-sheets"
python -m aeh run --data-dir $D --cohort teachers-class --package-version $V --config $CFG
```

**Expect at draft:** a summary line `Drafted <package-id>: N item(s) resolved, N placeholder(s) to fill, ...` naming the models used. The authoring report sits next to the draft (`<package-id>.authoring-report.md`) — read it before reviewing: it says what was resolved and what the draft left open.
**Expect at review:** one prompt per open item, ending with `The draft is ready` and the build command — that line is printed only when nothing is left open. The draft you reviewed is the same file the build takes.
**Expect at build:** the version id, exactly like 2b. A draft that still carries an open item is refused, naming the field and the reason (see the table below).

### Step 4: read the results

```powershell
# Totals and grades, per student and for the class
python -m aeh results show --data-dir $D --run <physics run_id>
python -m aeh results show --data-dir $D --run <english run_id>

# The English marks line by line, and the check that every C1 equals C1a + C1b
python docs\live-tests\sample-materials\show_criterion_marks.py --data-dir $D --cohort eng7-class --run <english run_id>

# The console, to look around, review and export (open the address it prints)
python -m aeh console --data-dir $D --config $CFG
```

Compare the marks with the expected ones in [`03-sample-tests-and-answer-sheets.md`](03-sample-tests-and-answer-sheets.md): the physics table in section 2, the English table in section 3. Multiple-choice marks and the C1 = C1a + C1b sums must be exact. A written line one band off is normal; two or more bands off is a finding. Record what you see on the record sheet in [`04-test-day-plan.md`](04-test-day-plan.md).

### If something goes wrong

| What you see | What it means, and what to do |
|---|---|
| `aeh ingest` ends with `no answer sheet could be read` (exit 1) | Almost always the model, not the scans: a wrong or missing key, no credit, or a model name OpenRouter doesn't know. The warnings above it say which. Fix it and run the same command again: sheets already read are skipped. |
| Good papers come out `unmatched_assessment` at intake | The page reader probably copied only the handwriting and dropped the printed questions. This is the most important finding the test can produce: write down each paper's status and keep the folder ([02, "A risk to plan around"](02-live-readiness-and-blockers.md)). |
| `aeh run` exits 3 | The run paused. Read `pause_reason` in what it printed (the cost ceiling, an OpenRouter refusal such as `No endpoints found matching your data policy`, …), fix what it names, and record the pause. Rerunning the same command does **not** carry a paused run on: `aeh run` starts only pending runs, and resuming a stored pause is not a terminal command yet (found on the 2026-10-12 live pass below). A run stopped mid-flight by a closed window or a sleeping machine is the case rerunning does pick up. |
| Many judge answers quarantined with "not the pinned order" | The judge model returns its answer fields in a different order than the system requires. Record it; it is a design question, not something to fix on the day. |
| The run fails or pauses over the decision engine (Jev) | A Jev call was refused, or the drafted rubric tripped a check the decision path makes (band names carrying numerals did this on the 2026-10-12 live pass — the run stops before any grading). Record it. Setting `$env:HARNESS_DECISION_ENGINE = "off"` keeps later runs off Jev; a run already paused over it stays paused until resumed (the row above). |
| `aeh run` reports `"status": "complete"` but `grades_final` is 0 | Some judge answers were refused, and the students' marks are held provisional rather than settled over a refused answer. The refusal lines are in the run's `stages` output and name the rule each one broke (on the 2026-10-12 live pass, judge citations failed the byte-exact document check — `FR-JUDGE-17`). Copy those lines into the record; do not read the provisional totals as settled marks. |
| `already exists` from `cohort create` or `package build` | Classes and packages are never overwritten. Use a new data folder (`$D`), or carry on with the one you already made. |
| `aeh author draft` exits 1, nothing written | The document step failed before anything could be written: usually the key, credit, or a model name OpenRouter doesn't know — the warnings above it say which. A draft that finished but left items open does **not** exit 1: it prints its report's name and the report says what is still open. |
| The draft says `N unresolved`, or its report names items still open | The model could not settle those items. The report (`<package-id>.authoring-report.md`) lists which and why. Answer them at review if the teacher can, or re-draft with a clearer document. Never build a draft that is not ready — the build refuses it (next row). |
| `aeh package build` refuses with `still carries the placeholder sentinel` | The draft was never reviewed, or an item was skipped at review. Run `aeh author review --draft` on the file the refusal names, answer the field it names, and build again. Nothing was published by the refused build. |

### What to watch for on the first run

These have mostly been seen once now (2026-10-12, the authoring walk below), so the open questions are narrower: whether the page-reading model's markup clears intake on scan-quality sheets (it did on a typed generated sheet), what a full class really costs and takes (one student cost about $0.15 and took about 6 minutes including the reading; a six-student class is still unmeasured), how often the judge's citations survive the byte-exact document check (on the pass below, one judge reply in four did — the refusals held the marks provisional), and whether the Jev decision engine answers (it has still never answered: the run stopped before dispatching to it). The full list is in [`02`](02-live-readiness-and-blockers.md).

## Read in this order

| # | Document | Read it if you are | What it gives you |
|---|---|---|---|
| 1 | [`02-live-readiness-and-blockers.md`](02-live-readiness-and-blockers.md) | Everyone, first | What works, the gaps that are still open, and the risks to plan around |
| 2 | [`01-hosting-and-configuration.md`](01-hosting-and-configuration.md) | Setting up the machine | Profiles, install, data folder, OpenRouter key and limits, the consent rule, every setting, a security checklist |
| 3 | [`../tutorials/deployment-tutorial.md`](../tutorials/deployment-tutorial.md) | The engineer beside the operator | The full command-line path (section 8), with what each command prints and every refusal explained |
| 4 | [`../tutorials/operating-tutorial.md`](../tutorials/operating-tutorial.md) | The operator and the teacher | How the console works, all its pages and commands, and the phases of the grading life cycle |
| 5 | [`03-sample-tests-and-answer-sheets.md`](03-sample-tests-and-answer-sheets.md) | Preparing the test | Two sample tests covering every rubric scoring method, rubrics, keys, ten answer sheets (including three awkward ones), expected results |
| 6 | [`04-test-day-plan.md`](04-test-day-plan.md) | Running the day | Stages, roles, timeline, record sheet, pass criteria, teacher questions |

## What is in the other folders

| Path | What it is |
|---|---|
| [`config/live-test.dev-ci.toml`](config/live-test.dev-ci.toml) | The configuration for the test, with every line explained: the `dev-ci` profile, the page-reading model, the judge, the cost ceiling, the Jev decision engine. |
| [`config/ps9-forces-01.package.toml`](config/ps9-forces-01.package.toml), [`config/eng7-read-01.package.toml`](config/eng7-read-01.package.toml) | The two package specs `aeh package build` publishes. Physics: multiple-choice keys and band lines. English: one line of each scoring method — evidence checklist (`evidence_sum`), `bands`, and the teacher's own words (`general`). Build both to grade every rubric type. |
| [`config/ps9-roster.txt`](config/ps9-roster.txt), [`config/eng7-roster.txt`](config/eng7-roster.txt) | The two class lists for `aeh cohort create --roster` |
| [`sample-materials/pdf/`](sample-materials/pdf/) | The sample PDFs (18 files): tests, model answers, rubrics, blank answer sheets, finished answer sheets |
| [`sample-materials/build_sample_materials.py`](sample-materials/build_sample_materials.py) | Rebuilds those PDFs, identically every time (standard library only) |
| [`sample-materials/verify_sample_materials.py`](sample-materials/verify_sample_materials.py) | Builds both packages from their specs, runs every sample sheet through the system's real intake checks, and checks that a run would grade every rubric method, with no network and no cost |
| [`sample-materials/check_config.py`](sample-materials/check_config.py) | Tells you whether a configuration file will be accepted, before you start anything |
| [`sample-materials/show_criterion_marks.py`](sample-materials/show_criterion_marks.py) | After a run: each student's mark per rubric line (a checklist with its items beneath), and a check that every checklist mark is the sum of its items |
| [`sample-materials/build_rehearsal_data.py`](sample-materials/build_rehearsal_data.py) | Builds a practice data folder (a finished run over three demo students, no network) to rehearse the console on. Needs the developer install (`pip install -e . -r requirements-dev.txt`). |
| [`../tutorials/images/`](../tutorials/images/) | Screenshots of the real console pages used in the tutorial |

## How this was checked

* **Against real OpenRouter (2026-10-12): the authoring walk (Step 3b), end to end.** `aeh author draft` read a one-page Year-7 fractions test paper and drafted `math7-fractions-01` with the config's models: the questions, the rubric and the grade boundaries it resolved itself, and the summary line and authoring report named what it left open. The review walk filled the rest (the teacher name and one model answer) and printed the build command only when the draft was ready; a premature build was refused naming the sentinel field. The build published, a generated answer sheet cleared every intake gate (`ok`, `v0`–`v4` match), and the run finished — recorded cost **about $0.15** for one student. Three of the four judge replies were refused by the byte-exact citation check (see the `grades_final` row above), so the marks stayed provisional; the one verdict that verified was applied. Two findings from the same pass are recorded in the table above: a stored pause does not resume on rerun, and the decision engine faulted before dispatch because the drafted band names carry numerals the decision request may not carry.
* **Against real OpenRouter (2026-10-03):** a one-field call, a judge-style three-field call, and a page image to the vision model, each answered through a zero-retention host by the models the config ships with.
* **Against a stand-in for OpenRouter on the same machine:** the command-line path through `cohort create`, `package build`, `ingest` and `run`, the request format, and the zero-retention fields on every request.
* **Offline, with no model:** both package specs build and publish, all ten sample sheets go through the real intake checks as the guide says, and a `dev-ci` run over each class would grade every rubric line of every method (`verify_sample_materials.py`). `show_criterion_marks.py` was checked against a graded run built by the repository's test fixtures.
* **Not yet checked:** the two sample classes end to end against real OpenRouter (the 2026-10-12 pass covered the authoring walk and a one-student run), a real model reading these tutorial pages, the Jev decision engine answering a real call (it has only ever faulted before dispatch), and real cost and run time for a full class. Those are what the first live test shows.
