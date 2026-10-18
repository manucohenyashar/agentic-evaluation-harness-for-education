# The live teacher test, in the console

*The same live test as the [README's step-by-step](README.md#run-the-live-test-step-by-step), driven from the browser instead of the terminal: the teacher makes the class, makes the test, reads the papers, starts the grading run, reviews, finalizes and downloads the results without typing a command. Read [02](02-live-readiness-and-blockers.md) first, and use the record sheet in [04](04-test-day-plan.md).*

## What is different from the terminal walk

| Step | Terminal walk (README) | Console walk (this page) |
|---|---|---|
| Start | (no console needed until step 4) | **One terminal step:** the operator starts the console with the key and the settings |
| Class | `aeh cohort create … --roster` | **Classes** screen: name, whose work, the class list typed or imported from a file |
| Test package | `aeh package build --spec …` | **Set up a test package → From your documents**: the test paper, model answer and rubric drafted, reviewed and approved |
| Reading the papers | `aeh ingest …` | **Papers inbox**: choose the test paper and the answer sheets, confirm, watch them read |
| Grading | `aeh run …` | **Start a run**: choose the test version, confirm the priced start, watch it on **Monitor run** / **Jobs** |
| Results | `aeh results show`, `aeh results export` | **Results**: marks, each student, change a grade, finalize, and download the spreadsheet, CSV, a student's report or the test itself |

The reading and the grading go through exactly the same code as the terminal commands: the console's papers upload calls the same intake door `aeh ingest` uses (same page reader, same five checks, same parking), and its run start is the same run `aeh run` starts.

**Where this was checked, honestly.** The console path was driven end to end in a browser on 2026-10-18 against a stand-in for OpenRouter that answers each page with the sample script's transcript (the same stand-in `aeh ingest`'s own checks use): class from the typed list → the English sheets read (4 of 4 ready) → priced run start. The intake half is a permanent regression case (`TC-CONSOLE-77`). It has **not yet been run against real OpenRouter**; that is what this walk is for. Record it as a first run.

## Step 0: start the console (operator, the one terminal step)

Windows PowerShell, from the project folder:

```powershell
.venv\Scripts\Activate.ps1
$env:OPENROUTER_API_KEY = "sk-or-..."            # your key; never write it in a file
$env:HARNESS_ORCH_ESCALATION_BUDGET = "1.0"      # a small class: let every disagreement get more judges
$env:HARNESS_ORCH_RANDOM_ARM_RATE = "0"          # the shipped config has ONE judge: no random extra-judge sample
$D = "$HOME\aeh-console-1"                       # a NEW, empty data folder for this test
python -m aeh console --data-dir $D --config docs\live-tests\config\live-test.dev-ci.toml
```

It prints `provider for runs started here: OpenRouter …` and the console's address, and opens the browser. Leave this window open: closing it stops the console (the work already done is kept).

> **Why the two `HARNESS_ORCH_…` lines matter.** Without `HARNESS_ORCH_RANDOM_ARM_RATE = "0"`, starting the run is refused with *"the random-arm sample … gives some answers 3 judges, and this live run has 1 real judge model(s)"* — the refusal you get from `aeh run` too. These two are environment settings the console cannot change for you; set them before starting it. (Adding two `escalation_judge` models to the config file is the other way out; see the config file's comments.)

**Check:** the browser shows the home page with nine stages, and the top bar says *Class: None yet*.

## Step 1: the class (teacher)

Open **Classes** in the left sidebar (`/#/class`).

1. **Class name:** `eng7-class` (lower-case letters, digits, `-`, `_` or `.`).
2. **Whose work is this?** choose **made-up practice work**. This is the consent class; it can never be changed afterwards, and only made-up work may go to OpenRouter without consent ([01, the consent rule](01-hosting-and-configuration.md)).
3. **Students:** either
   * **Type or paste them** — one per line: `E7-001`, `E7-002`, `E7-003`, `E7-004`; or
   * **Import a class list file** — choose `docs\live-tests\config\eng7-roster.txt`. The screen lists the four students it found (and any problem line, with its line number) before anything is written.
4. **Make the class.**

**Expect:** *Class eng7-class is ready.* The class appears above the form with its four students, each *no paper yet*, and the top bar's *Class* switcher names it. The home page's stage 1 is *Done — 4 students.*

Late student? **Add students** under the class takes the same one-per-line list.

## Step 2: the test package (teacher)

### Route A — the teacher's path: from the test's own documents (default)

Open **Set up a test package → From your documents** (`/#/package/author`).

1. Upload the three documents from `docs\live-tests\sample-materials\pdf\ENG7-READ-01\`: `01-test-paper.pdf`, `02-model-answer.pdf`, `03-rubric.pdf`. Each shows *Understood* once its preview is read.
2. Start the draft. It runs as a job (this calls OpenRouter; allow a few minutes) — its progress is on the page and on **Jobs**.
3. Answer the open questions at **Review the draft** (`/#/package/review`); fix anything else in the editor (`/#/package/edit`).
4. **Approve.**

**Check before going on — this matters:** the published package's name must be **`ENG7-READ-01`**, the test code printed on every answer sheet. The papers' right-test check compares the two; a drafted package named anything else parks every sheet as the *wrong test*. If it is not, stop and record it (it is a finding about the drafting), then use Route B.

A drafted package's rubric is the model's reading of `03-rubric.pdf`, so its marks can differ from the expected-marks tables in [03](03-sample-tests-and-answer-sheets.md), which were written for the spec package. That difference is itself something to record.

### Route B — the exact sample package (operator, before the session)

When the session must reproduce [03](03-sample-tests-and-answer-sheets.md)'s expected marks exactly, the operator publishes the shipped package once, in the same terminal, **before** the teacher starts (stop the console with Ctrl-C, run this, start it again as in step 0):

```powershell
python -m aeh package build --data-dir $D --spec docs\live-tests\config\eng7-read-01.package.toml
```

Record it as an operator step. The teacher then sees the package as *Published* in the top bar and skips to step 3.

**Expect (either route):** the home page's stages 2–4 are *Done* and the top bar's package badge says *Published*.

## Step 3: reading the papers (teacher or operator)

Open **Papers inbox** (`/#/papers`).

1. **Test these papers answer:** the published version (`ENG7-READ-01@…`).
2. **The test paper (PDF):** `docs\live-tests\sample-materials\pdf\ENG7-READ-01\01-test-paper.pdf`. Needed once per class: every sheet is checked against it. (Afterwards the screen says *Already in for this class.*)
3. **Answer sheets:** select all four files in `…\ENG7-READ-01\answer-sheets\`. The list of files to read appears under the button.
4. **Read the papers**, then **Read them** in the confirmation (it says the files go to the page reader in the console's settings).

The files are sent one by one, then read on the console's own worker, so you can leave the page. A progress bar shows *N of 5 done* and the last file's outcome; the same job is on **Jobs** as *Reading the papers*. This calls OpenRouter once per page.

**Expect:** *5 file(s) done: 4 paper(s) ready to grade, 0 parked, 0 already read, 0 not read.* Every student says *paper read*. Home stages 5 and 6 are *Done*.

Sending a sheet again is harmless: it is reported *already read* and never graded twice.

### The physics class (the parking drill)

Repeat steps 1–3 for physics: class `ps9-class` from `docs\live-tests\config\ps9-roster.txt`, package `PS9-FORCES-01` (route A from `…\PS9-FORCES-01\`'s three documents, or route B with `ps9-forces-01.package.toml`), and the test paper plus the six sheets in `…\PS9-FORCES-01\answer-sheets\`.

**Expect:** *3 paper(s) ready to grade, 3 parked* — S9-004 (`incomplete`, a doubled tick), S9-005 (`unmatched assessment`, the wrong test), S9-006 (`incomplete`, no name). The screen links to **Parked**; do the parked-paper drill exactly as [04's 10:00 row](04-test-day-plan.md#timeline) describes. Releasing or closing still records no chosen student, mark or test (B8).

## Step 4: the grading run (teacher or operator)

Choose the class in the top bar if it is not already chosen, then open **Start a run** (`/#/run`).

1. **Test version:** the published version.
2. **Start a new grading run.** The confirmation says what will be graded, under which settings profile (`dev-ci`), and the **estimated cost**; *Technical details* holds the full settings banner for the engineer.
3. **Start.** The console opens **Monitor run**, which refreshes itself; **Jobs** shows the run's progress and cost so far.

**Expect:** the run moves to *complete* (the jobs page says *Done*). Watch OpenRouter's own dashboard for the real spend. If it pauses, the monitor names the reason — the [README's table](README.md#if-something-goes-wrong) explains each one; resume from **Jobs**.

## Step 5: review, blind sample, finalize, change a grade (teacher)

As in [04](04-test-day-plan.md), 11:00–11:40:

* **Review queue** (`/#/review`): what is flagged, and how many marks are still provisional.
* **Blind sample** (`/#/review/blind`): each drawn answer offers **that question's own levels** from the package (for example *Full, Adequate, Limited, None*), with nothing preselected and no system mark shown. Choose the level you would give.
* **Results** (`/#/results`): every student's total and grade; open a student for the feedback and each line's level. **Change a final grade** needs a reason and keeps the original. **Finalize the batch** stamps the run as delivered.

## Step 6: download the results (teacher)

Still on **Results**, the **Download the results** panel:

| Button | What you get |
|---|---|
| Marks spreadsheet (Excel) | The marks as an `.xlsx` workbook |
| Marks file (CSV) | The same marks as a CSV file |
| The chosen student's report (PDF) | The report of the student picked in *Student for the report* |
| The test and its grading guide (PDF) | The test package as a readable document |
| Backup of the test | The package's `.aehpkg` backup file (the console has no screen to import it yet) |

**Marks version** 1 is every student's marks as first given. Version 2 lists only the students whose final mark was changed (the change from step 5), with the changed mark.

**Expect:** each download opens or saves a file; the version-1 CSV has one row per student with the totals the Results screen first showed.

## What still needs a terminal or an engineer

| What | Why | Instead |
|---|---|---|
| Starting the console, with the key and the two `HARNESS_ORCH_…` settings | Environment settings are read when the console starts | Step 0, once |
| The exact sample package (route B) | Building from a spec file is a developer route | Route A, or the one `aeh package build` line |
| Recording which student / mark / test a parked paper really is (B8) | Needs a design decision and a store change | Write it on the record sheet |
| Importing a test's backup file, correcting an answer key after a run, setting a review window, purging a class | Enumerated console actions with no SPA screen yet | An engineer, through the console's API or the CLI |
| `show_criterion_marks.py` (C1 = C1a + C1b) | It is an engineer's check script | Run it after the session, as the README's step 4 says |

## If something goes wrong in the console

| What you see | What it means |
|---|---|
| *… was not accepted: no class named …* / *choose the published test …* | The upload was refused before anything was stored: pick the class in the top bar, and a published test version |
| *these papers cannot be read under this console's settings: …* | The class's consent does not allow the configured page reader (a `real` class on OpenRouter). Nothing was sent |
| *… not read — this class has no test paper yet* | Upload the test paper first, then the sheets |
| The reading job fails: *no file could be read* | Almost always the page reader: the key, the account's credit, or the model name. Fix it, restart the console, and upload again — sheets already read are skipped |
| Good sheets come out parked as the *wrong test* | Check the package name equals the printed test code (step 2's check), or the page reader dropped the printed questions ([02, "A risk to plan around"](02-live-readiness-and-blockers.md)) |
| Starting the run is refused naming `HARNESS_ORCH_RANDOM_ARM_RATE` | Step 0's settings were not set before the console started: stop it, set them, start it again |
| A run pauses | **Monitor run** names the reason; the README's table explains it; resume from **Jobs** |
