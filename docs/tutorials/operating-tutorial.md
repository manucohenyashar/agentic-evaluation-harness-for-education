# Operating the Grading System: A Tutorial for Operators and Teachers

*For people who are comfortable with a web browser and can follow a recipe in a terminal window, but are not programmers.*

This tutorial walks through the whole life of one test in the grading system: create the class, make the test package from your own documents, upload the papers, let the system grade them, review the result, finalize the grades, and tidy up. It is written for the first live teacher test, so every step says **who** does it, **what you will see**, and **what to type**.

> ### Read this box first
> Everything in this tutorial describes the console **as it is shipped today**. The console's main surface is a **single-page web app (the SPA)** that opens at the address the console prints. In it you can: make a class from a typed list or a class list file; draft a test package from your own documents (PDF, DOCX or TXT), preview what the system understood, watch the draft being made, answer the draft's open questions, edit it, and approve it into a published package; upload the test paper and the answer sheets and have them read through the five intake checks; start, pause and resume grading runs; read the review screen's flagged counts; score the blind sample on each question's own levels; finalize the batch; amend a finalized grade with a recorded reason; read every result; and download the marks, a student's report and the test itself. **What still needs the terminal:** starting the console itself, with its key and settings (section 3.1). The terminal commands (`aeh cohort create`, `aeh ingest`, `aeh run`, `aeh results export`) remain for scripting and debugging. Every remaining gap, with proof, is in [`docs/live-tests/02-live-readiness-and-blockers.md`](../live-tests/02-live-readiness-and-blockers.md), and this tutorial's section 6 lists them in one place.
>
> Runs grade through OpenRouter under the `dev-ci` profile, with zero data retention requested on every call; setting `HARNESS_FIXTURE_DIR` switches to recorded replays instead (offline rehearsal). The console refuses the `cloud-hosted` profile on purpose. The **practice data** in section 2 lets you rehearse everything the console can do, spending no money and sending nothing anywhere.

---

## 1. The people and the words

### The three roles

| Role | Who | What they do |
|---|---|---|
| **Teacher** | The person whose class is being graded | Uploads their test documents to make the package, answers the draft's questions, reviews the system's marks, finalizes grades. Can be the same person as the operator in a small school. |
| **Operator** | Whoever runs the machine and handles scanning | Starts the console, reads the scans in, watches the run, sorts out papers the system could not match. |
| **Engineer** | A technical helper | Does the steps marked **⚠ Engineer step**, until those become one-click. |

### The words you will meet

| Word | Plain meaning |
|---|---|
| **Test / assessment** | The paper the students sat. It has an ID printed on it, such as `PS9-FORCES-01`. |
| **Package** | Everything about one test, stored as one unit: the questions, the rubric, the answer keys, the grade policy. Once published it is locked. |
| **Class** | A list of students (the **roster**), kept on its own. A grading **cohort** is made from a class and carries a **consent class**: `synthetic` (made-up practice papers), `consented`, or `real`. |
| **Draft** | The package before it is approved. The system writes a first draft from your documents, you answer its open questions and edit it, then approving publishes it. |
| **Run** | One grading pass over one cohort with one package. It can take hours and survives the browser being closed. |
| **Job** | A piece of work the console does in the background — making a draft, or a grading run — listed on the Jobs screen with its progress and its cost so far. |
| **Criterion / rubric line** | One thing being marked, for example "names both forces". Each question has one or more. |
| **Band** | One of the written descriptions a rubric line can earn, such as *adequate*. Judges choose a band; points follow from it. There are no numbers to type anywhere. |
| **Provisional** | A grade nobody has looked at yet, honestly labelled. It is still a complete grade. |
| **Parked (quarantine)** | Where a paper waits when the system could not be sure whose it is, whether it is the right test, or whether a mark is readable. The system never guesses; the operator decides. |
| **Finalize** | Stamp the batch as delivered. |
| **Amend** | Change one band on a finalized grade. This writes a *new revision* and keeps the original, with the reason and who gave it. |

---

## 2. Before anything else: a practice folder

Do this once, on the machine you will use. It is the safe way to learn every screen, and it spends no money and sends nothing anywhere.

**⚠ Engineer step** (a few minutes, once):

```bash
python docs/live-tests/sample-materials/build_rehearsal_data.py
```

This builds a finished run over three demo students in a private folder, `~/aeh-rehearsal`. When it ends it prints the three IDs you will use below:

```
run id ............ run-dev-pipe
cohort id ......... coh-dev-pipe
package version ... PKG-DEV-PIPE@64e2dd023c2e
```

Use the values it prints for you. The three demo students are not the sample answer sheets in `docs/live-tests/`; they exist so that every screen has something on it.

---

## 3. Start the console, and stop it

The **console** is the system's web page. It runs on the same computer you are sitting at and, by default, can only be reached from that computer. That is deliberate: it has no login, so it refuses to listen on a non-loopback address. A remote operator can use the supported secure-tunnel setup in section 3.4.

### The console is the teacher surface; the terminal is for setup and debugging

This tutorial teaches the console first, on purpose: most of the teacher-facing grading-day workflow happens in the browser. The terminal remains the setup and operator surface for tasks the SPA does not yet support — creating the class, reading scans and exporting results — as well as for debugging. The console's Help screen lists every `aeh` command and where it is represented or why it remains CLI-only (the system keeps that inventory and fails a check if a new command appears without one). Section 7 is a selected guide to those commands, not a complete CLI reference.

### 3.1 Start it

Open a terminal in the project folder, activate the project's Python environment, and run:

```bash
python -m aeh console --data-dir ~/aeh-rehearsal
```

(On Windows PowerShell, use `$HOME\aeh-rehearsal` for the folder.) You will see the banner (checked):

```
provider for runs started here: edge-local (local models: http://127.0.0.1:9000/v1)
console listening on port 8765 (pid 1016); Ctrl-C to stop
  Grading console:  http://127.0.0.1:8765/
  Next step:        create a class, then a test package — the home page walks you through it.
```

* The `provider` line prints only when a profile is set (see below), and names the backend any run started from this console will call — the same line `aeh run` prints, so a stray `HARNESS_FIXTURE_DIR` shows up here before you spend anything. (The address in the transcript is a rehearsal's configured `LOCAL_INFERENCE_BASE_URL`; the shipped default for `edge-local` is `http://127.0.0.1:8080/v1`.)
* **The port number is different every time** unless you choose one. To choose it, set `CONSOLE_PORT` first (`export CONSOLE_PORT=8765` on macOS/Linux, `$env:CONSOLE_PORT = "8765"` on Windows PowerShell).
* The default browser then opens at the printed `Grading console:` address — that is the SPA. If you are running the console over SSH or on a machine without a browser, add `--no-open` (or set `HARNESS_CONSOLE_AUTO_OPEN=0`) and open the address yourself.
* The window must stay open: this command runs until you press **Ctrl-C**.

Starting the console also runs recovery: it reclaims expired leases, resumes runs that were running when interrupted and paused runs with an unapplied queued Resume request, and settles completed runs with ungraded or non-final scores. It does not start pending runs or override an operator pause. A run frozen under a different profile stays paused and records the refusal.

**Profile.** To merely look at a data folder you need no profile. The console needs one to start runs, to resume them, and **to draft packages from your documents**: without one, drafting answers *"no backend profile is configured for authoring, and a draft cannot run without one. Set the profile in the configuration, then start again."* (read from the code). Pass `--config <file>` with a file that names one (the shipped `docs/live-tests/config/live-test.dev-ci.toml` does), or set `HARNESS_PROFILE` in the terminal. Without one, starting a run answers *"HARNESS_PROFILE must be one of … got None"* (checked). On start-up the console resumes only runs whose own frozen profile equals the one in use; the practice run froze `edge-local`.

### 3.2 Where the data lives

`--data-dir` is the system's whole memory: every package, every student's text, every grade. Facts about it, all checked:

* It must **not** be under `/tmp` or any folder other people's accounts can write to. The system refuses with *"is not a safe data directory … Choose a directory outside the world-writable tree (e.g. under the operator's home)"*. Use a folder in your own home directory.
* If the folder does not exist, it is created. It is locked so only you can open it (owner-only permissions), even if you made it wider.
* Back it up like a student record: copy the whole folder while the console is stopped.

### 3.3 Stop it

Press **Ctrl-C** in the terminal. Closing the browser does **not** stop anything, and a run keeps going when the browser is closed. If the computer is switched off while a run is running, start the console again **under the same profile**: startup recovery reclaims expired leases and resumes that interrupted run. It also settles completed runs that still have ungraded or non-final scores. Recovery does not start pending runs or override an operator pause; to resume an intentionally paused run after a restart, queue Resume in Jobs before stopping the console. (This restart behaviour is read from the code and covered by the project's own tests; it was not tried on a live run.) Leave a run interrupted while it is running if you are rehearsing crash recovery.

### 3.4 Someone else needs to look at it

The console cannot be opened to the network, by design. If a teacher at another desk must use it, the supported route is for them to connect to *your* computer over a secure tunnel (for example `ssh -L 8765:127.0.0.1:8765 you@the-machine`) and then open `http://127.0.0.1:8765` on their own screen. Never try to make it listen on `0.0.0.0` or a network address: it refuses (*"the console refuses a non-loopback bind … an unauthenticated student-record system runs on one machine, loopback only"*).

---

## 4. How the console works

The console's home page is a **wizard**: nine stages, in order, each with its own state (*Done*, *In progress*, *Not started*, *Needs attention*). A step strip keeps the stages visible, and the secondary sidebar links to operator and teacher screens.

The nine stages, in the words the console uses:

| # | Stage | Where it happens |
|---|---|---|
| 1 | Create the class | The Classes screen (section 5.0) |
| 2 | Create the test package | The package screens (section 5.1) |
| 3 | Review the draft | The draft review screen (section 5.1) |
| 4 | Approve the package | The draft review screen's approve control (section 5.1) |
| 5 | Upload the papers | The Load papers screen (section 5.2) |
| 6 | Reading the papers | Load papers reads what you upload (section 5.2) |
| 7 | Start the grading run | The run screens (section 5.2) |
| 8 | Review the results | The review and results screens (section 5.3) |
| 9 | Export the results | The Results screen's downloads (section 5.3) |

Beneath the stage strip, a fixed sidebar links every screen by name — **Set up a class, Set up a test package, Load papers, Start a run, Monitor run, Review, Results** — and the secondary screens: **Parked, Jobs, Issues, Logs, Settings, System status, Manuals & help**. **Parked** is stage 5's neighbourhood: papers the system could not place wait there.

### 4.1 The screen map

The SPA's addresses carry a `#`. Replace `{...}` with your own IDs. The current class, package and run ride along in the address, so a bookmark or a shared link opens the same view.

| Screen | Address | Who | What it does |
|---|---|---|---|
| Wizard home | `/#/` | Teacher | The nine stages, each with its state, and the next action for each |
| Set up a class | `/#/class` | Teacher | Every class and its students; make a class (typed list or a class list file), add late students, delete a class |
| Set up a test package | `/#/package` | Teacher | The setup draft's steps, which ones block publishing, and the **Publish** control |
| Author a package | `/#/package/author` | Teacher | Upload your documents, preview what was understood, start the draft job |
| Review the draft | `/#/package/review` | Teacher | The draft's open questions to answer; approve it when none remain |
| Edit the draft | `/#/package/edit` | Teacher | Add, edit, reorder and delete questions and grading points |
| Load papers | `/#/papers` | Teacher/Operator | Upload the test paper and the answer sheets, read them through the five checks, and see each student's paper |
| Start a run | `/#/run` | Teacher/Operator | Start a new grading run for the selected class and test version, priced, behind a confirmation |
| Run monitor | `/#/monitor` | Operator | The run's status and pause reason beside the orchestrator's own progress counts; it refreshes itself |
| Review queue | `/#/review` | Teacher | The flagged answers that await review, and how many provisional answers remain outside the queue |
| Blind sample | `/#/review/blind` | Teacher | The papers drawn for the blind sample, each offering that question's own levels from the package |
| Results | `/#/results` | Teacher | Every student's grade; the finalize control; the amend form; the downloads (marks spreadsheet and CSV, a student's report, the test as a PDF and its backup); correcting an answer key; the review window |
| One student | `/#/results/students/{submission-id}` | Teacher | The narrative feedback, each line's band, and the amend form |
| Parked | `/#/parked` | Operator | Each parked paper with its reason; give it to a student, release or close it, with a recorded note |
| Jobs | `/#/jobs` | Operator | Every job — drafts and runs — with progress, elapsed time and cost so far; a run offers Pause and Resume |
| Issues | `/#/issues` | Teacher | The run's findings that need a person, by severity |
| Logs | `/#/logs` | Engineer | The run's stage records, paged |
| Settings | `/#/settings` | Teacher/Engineer | The configuration as it stands; the editable subset as guided forms |
| System status | `/#/status` | Operator | Whether the store, the provider and the services behind the screens are answering |
| Help | `/#/help` | Everyone | The four manuals and the question box, which answers from them with citations |

**A second, quieter surface also exists.** The console still serves the older server-rendered pages S1–S14 at plain addresses (`/packages`, `/runs/{run}/rollup`, and so on — the full list is section 8). They are operator/audit pages, separate from the teacher-facing SPA. Some legacy grade pages render generic band controls, but they do not provide the SPA's guided workflows; this tutorial's steps happen in the SPA unless stated otherwise.

---

## 5. The test day, screen by screen

The whole day, class to download, as one walk over the sample tests: [`docs/live-tests/05-console-teacher-walk.md`](../live-tests/05-console-teacher-walk.md).

### 5.0 Make the class (teacher, once)

Open **Set up a class** (`/#/class`). Give the class a name (lower-case letters, digits, `-`, `_` or `.` — it becomes a file name), choose **whose work this is** — made-up practice work, work the students or their guardians agreed to, or real work without that agreement — and add the students: type or paste one per line (a spreadsheet's *first name, last name, optional ID* columns paste as they are), or **import a class list file**, which lists every student it found and every problem line, with its line number, before anything is written. **Make the class.**

The consent choice has no default and can never be changed afterwards: it decides whether the class's papers may go to a remote model at all. A late student is added with **Add students** under the class. **Delete this class…** removes a class for good after you type its name; it is refused while the class's evidence has not been saved for validation. With one class stored, the console selects it everywhere; with several, choose one in the top bar's *Class* switcher.

### 5.1 Make the test package (teacher, once, 30 to 60 minutes)

Everything here happens on the package screens, and **drafting needs a configured profile** (section 3.1).

1. **Upload your documents.** Open `/#/package/author`. You can give the system the test paper, your model answer and your rubric — **PDF, DOCX or TXT**, up to 10 MB per document (the limit is adjustable; the deployment tutorial's knob table has it). Each file shows its own status as it is read: *Reading*, then *Understood*, or *Refused* with the reason and what to do next — a refused file never blocks the others.
2. **Preview what was understood.** Before anything is written, the screen shows what the console read from each document: pages, text blocks, words, tables and pictures, with the text in page order. A page with no text layer is named in the warnings, never silently dropped.
3. **Start the draft.** One confirmation and the draft runs as a background job. You can watch its stage, its progress count and the elapsed time on the same page or on the Jobs screen, and cancel it while it runs. Reload the page mid-draft and you are re-attached to the job — nothing is lost. (An empty draft you fill by hand is started the same way, with *from scratch*.)
4. **Review the draft.** The draft's open questions — a missing expected answer, an unclear rubric line — wait at `/#/package/review`. Answer each in place; the screen says how many pieces are missing. A change the draft needs but no question covers goes to the editor at `/#/package/edit`: add, edit, reorder or delete questions and grading points there.
5. **Approve.** When no question remains, the review screen's **Approve** control publishes the draft. Approval goes through the same package build gate `aeh package build` uses — a draft that would refuse is refused here too, with the reason, and nothing is written.

A second route to a published package also exists: `/#/package` shows the setup draft's steps, names which steps **block** publishing, and offers **Publish the draft version** only when the draft is ready — the control is present but disabled over a blocked gate, so the screen never offers a publish the gates would refuse. Publishing locks the version and records you as the approver. This is the path for a package the operator set up directly rather than drafted from documents.

**Check it worked:** the wizard home's stage 2 shows *Done* once a package is published, and the run screens name the package version the run grades against.

*The terminal's `aeh package build --spec` remains a developer and system-emitted route (the deployment tutorial, section 8.2): a published version's spec file is an export the system writes, not something a teacher authors.*

### 5.2 Load the papers and start the run (teacher or operator)

**Reading the scans in.** Open **Load papers** (`/#/papers`) with the class selected. Choose the published test version the papers answer, the **test paper** (once per class — every answer sheet is checked against it) and the **answer sheets**, one PDF per student, each carrying the test name and the student's name or ID. The files you chose are listed; **Read the papers** asks for a confirmation (the pages go to the page reader in the console's settings) and then sends them. The console reads them on its own worker — you can leave the page — and a progress bar shows each file's outcome; the same work is on **Jobs** as *Reading the papers*. Every sheet goes through the five intake checks; a sheet that fails one waits on the Parked screen. Sending a sheet again skips it, so a paper is never graded twice. This is the same reading `aeh ingest` does from the terminal (deployment tutorial, section 8.3).

**The five intake checks, in plain words:**

| Check | Plain meaning | Fails when |
|---|---|---|
| **v0 integrity** | The file is a sound PDF | Corrupt file, or too many blank pages |
| **v1 pages** | Every page is there | A page is missing or doubled |
| **v2 structure** | The paper has the questions the package expects, and every mark is readable | Wrong question layout, or a mark with two ticks / an unreadable tick |
| **v3 identity** | The student named on the page is on the class list | No name, or a name not on the roster |
| **v4 match** | The paper is the right test | The printed test name is different, or the answers share almost no words with the questions |

Papers with problems do **not** hold the run back: they wait on the Parked screen while the rest are graded.

**Start the run.** Open `/#/run` with the class selected, choose the test version and press **Start a new grading run**. The confirmation says what will be graded, under which settings profile, and the estimated cost. A run that is still waiting to start shows its own **Start the run** control. Confirm, and the run starts on a worker the console owns and the console opens the run monitor. Recovery resumes eligible interrupted work at console startup; an intentionally paused run is resumed only when it has an unapplied queued Resume request.

**Watch it.** `/#/monitor` shows the run ID, status, any pause reason, and progress values supplied by the orchestrator (such as done, in-flight, pending and quarantined work). There is deliberately no per-student progress figure, because the work is done by criterion, not by student. The screen refreshes itself every two seconds.

**Pause and resume.** The Jobs screen offers Pause and Resume controls for a run, behind a confirmation; each queues a request the orchestrator applies at a grading-point boundary. The SPA does not offer a run-cancel button. Cancellation is available for a drafting job from its authoring screen. Although a declared `cancel job` action exists, do not treat it as a documented run-cancel control: Jobs exposes Pause and Resume for runs.

**If the machine restarts**: start the console again, **under the same profile as the run** (3.1). Recovery reclaims expired leases and resumes a run that was running when interrupted. It does not start a pending run or override an operator pause. To resume a run paused intentionally, queue Resume in Jobs first; if the console itself was stopped, the queued resume lets recovery resume it on restart. Starting under a different profile leaves the run paused, with the refusal recorded. `python -m aeh recover --data-dir <folder>` runs recovery without starting a grading pass: it reclaims expired leases, resumes eligible runs, and settles completed runs that still have ungraded or non-final scores, printing its report. To drive a new grading pass, start the console or use `aeh run`.

**A run from the command line** is `python -m aeh run --data-dir <folder> --cohort <cohort> --package-version <version> --config <file>`. Its exit code: **0** finished, **3** *not finished* (paused, or stopped for another reason; read the `status` and `pause_reason` it prints), **1** an error, with the reason printed after `aeh run:`.

### 5.3 Review, finalize, amend (teacher)

Reviewing the results is optional; the review screen is not an action queue, and a grade can remain provisional if the review window is still open.

1. **Read the review summary** at `/#/review`. It shows counts of flagged marks and grades that remain provisional, and lists item identifiers and kinds with a link to the blind sample. It does not show evidence narratives or proposed bands, and it has no accept/edit or group-action control. To read a student's feedback or change a grade, open that student from Results.
2. **Blind-sample screen** at `/#/review/blind`. The sampled submission/criterion seats are listed, each offering **that question's own levels** from the package (the generic B1–B5 scale only when the package cannot be read), with nothing preselected and no system mark shown. Choose the level you would give. A submission not drawn for the sample is refused: *"is not in run … blind draw"*.
3. **Finalize.** On `/#/results`, the **Finalize the batch** control stamps the run as delivered behind its confirmation, naming you (the console has no accounts, so the recorded name is the console's operator label). If the package declared a review window, finalizing inside the window leaves the grades *provisional*; the system settles them when the window ends.
4. **Change a grade.** From the results screen or the student's own screen, use the grade control. For a grade not yet final, the console records a review action; changing a finalized grade requires **a reason**, creates a new revision and keeps the original. The student's screen shows the amendment history, including the reason and actor when recorded.
5. **Download.** The **Download the results** panel on `/#/results` saves the marks as a spreadsheet (`.xlsx`) or a CSV file, one student's report as a PDF, and the test itself as a readable PDF and as its backup file. *Marks version* 1 is every student's marks as first given; version 2 lists only the students whose final mark was changed. The same screen corrects a multiple-choice **answer key** found wrong after the run (the question's marks are worked out again for the class) and sets the **review window** (hours the grades stay open before finalizing settles them).
6. **Read the results.** `/#/results` shows each student's grade, class distribution, per-criterion statistics and the lines most students missed; it does not show a grade range or multiple-choice distractor breakdown. `/#/results/students/{submission-id}` opens one student — use the submission ID the results screen shows (it looks like `sub-22a56dc63714`), **not** the student's own ID.

### 5.4 Parked papers (operator)

Open `/#/parked`. Each waiting paper shows **why it was parked** — the check that stopped it and the note the check left — and the decisions available (checked: the practice data's parked read carries the reason and the resolutions). Two decisions exist:

* **Release** the paper to scoring. This is right when you have looked at the paper and the system's reading stands.
* **Close** the paper as unresolvable. Closing never gives zero: the unscored lines are marked MISSING and the grade INCOMPLETE. A no-name paper can only be closed — releasing it is refused, because it would be graded under nobody (the refusal says to close it or rescan it).

Every decision asks for a confirmation before it is sent.

**What a decision does not record.** A release or a close records only that: it does not record which student you decided the paper belongs to, or the mark you decided by hand (blocker B8). For a doubled mark, the released paper is scored on what the page reader read, not on your decision — write your decision on the record sheet. The system will **not** reassign a paper by itself.

### 5.5 The rest of the sidebar

* **Jobs** — every background job (drafts and runs) with its state, progress, duration and **cost so far** in dollars, or a dash while it has none. Pause or resume a run here. A drafting job can be cancelled from its authoring screen; Jobs does not offer run cancellation.
* **Issues** — the run's findings that need a person: second-opinion notes are labelled *Information*, every other known source *Needs attention*, with the words beside the icon, not colour alone.
* **Logs** — the run's stage records, paged; the page size is a knob (deployment tutorial, section 10).
* **Settings** — the configuration as it stands, every setting with its teacher label. The editable subset is guided forms behind their confirmation; everything else is read-only, which is the truth. A secret's row says whether one is configured and never shows a value, and no key name from the configuration file appears anywhere on the page.
* **System status** — whether the store, the model provider and the services behind the screens are answering.
* **Help** — the four manuals (this tutorial, the teacher guide, the deployment tutorial and the test-day plan, served from the console itself), and a question box that answers from them with citations.

---

## 6. What is not in the console yet

Named plainly, so nobody meets them by surprise. Each is a known, tracked gap.

| Gap | What you do instead |
|---|---|
| **Starting the console** reads its environment once: the OpenRouter key and settings such as `HARNESS_ORCH_RANDOM_ARM_RATE` cannot be changed from the browser. | The operator sets them before `aeh console` (section 3.1; the live-test walk's step 0). |
| **A parked decision records no student, mark or test.** Release and close are the only outcomes, and neither stores which student the paper belongs to or the mark you decided by hand (blocker B8). | Write the decision on the record sheet; rescan a paper and upload it again in the Papers inbox when the fix is on the paper itself. |
| **The ambiguity questions are not in the SPA flow.** The SPA does not show this step. On the legacy `/setup/optional` page, its card is present but marked unavailable/arriving in version 2 (Phase 4); it is not a teacher-facing SPA control. | Nothing to do; the drafts' own review questions cover what blocks approval. |

Nothing here hides a failure: every screen that would need a missing capability either does not offer the control or says so in its own words.

---

## 7. Selected commands, and where they live

The console keeps a parity inventory (`NFR-CONSOLE-09`): every `aeh` command is either represented in the console or listed in its debugging-only help with a reason. That inventory is generated from the CLI and served on the Help screen and at `GET /api/v1/cli-help`. The table below is a selected guide to commands relevant to the teacher and operator journeys in this tutorial, not an exhaustive CLI listing. Some authoring descriptions in the generated inventory are known to be stale (`TC-CONSOLE-58` pins that wording), so use the actual shipped controls and the notes below rather than treating those descriptions as current.

| Command | What it is for | Where you do it instead |
|---|---|---|
| `aeh run` | Drive a cohort's run to completion from the terminal | The console's **Start the run** control (section 5.2) |
| `aeh recover` | Reclaim expired leases, resume eligible interrupted runs, and settle completed runs with ungraded or non-final scores | The console runs recovery on start; the **Recover** control on Issues runs it while the console is open |
| `aeh console` | Start the console server itself | The console is already running |
| `aeh cohort create` | Create a class/cohort and load its roster from a file | The Classes screen (section 5.0): a typed list or a class list file |
| `aeh cohort add-students` | Add late students to a cohort's roster | **Add students** under the class on the Classes screen |
| `aeh cohort show` | Print a cohort's consent class and roster size | The Classes screen shows the same read |
| `aeh package build` | Build and publish a package from a spec file | The console's **Approve** (section 5.1) goes through the same build gate; the spec path is a developer/export route |
| `aeh package export` | Write a published version's spec TOML for rebuilding or diffing | The Results screen downloads the test as a readable PDF and as its `.aehpkg` backup; the spec TOML stays a developer file |
| `aeh author draft` | Turn teacher-authored documents into a draft package spec + report | The console's author screen does the same through a job, with progress (section 5.1) |
| `aeh author review` | Walk a draft's unresolved items to resolution in the terminal | The console's draft review screen answers the same items (section 5.1) |
| `aeh ingest` | Read scanned papers through the intake checks | The Papers inbox (section 5.2) reads uploads through the same intake |
| `aeh results show` | Print per-student records and the class rollup as JSON | The Results screens answer the same reads (section 5.3) |
| `aeh results export` | Write the marks CSV and one PDF per student | The Results screen's downloads (section 5.3) |

The SPA also has a structured draft **editor** and a guided **configuration write** on the Settings screen. The console's control inventory also includes actions not exposed as ordinary standalone buttons on these screens; use each screen's documented controls rather than treating every API action as a teacher-facing control.

> A known quirk, recorded as a finding: the console's own inventory still lists the authoring screens as "future console work" — the screens have since shipped (section 5.1 is them). The inventory's rule is that a stale row fails a check, so expect the listing to be corrected in code rather than trusted here.

---

## 8. The server-rendered pages (operator and audit surfaces)

The SPA is the working surface; these older pages remain for operator reads and audit. Each was a screen in the pre-redesign console and is still served at its address. What each shows today:

| Page | Address | What it shows today |
|---|---|---|
| S1 Packages | `/packages?package_version={version}` | A card for the package you name. With no `?package_version=` it shows a placeholder card (*"Package pkg-unaddressed"*). It shows the name and *"no validation data for this population"*, not the contents. |
| S2 Upload | `/packages/new?cohort_id={cohort}` | Accepted format, and the uploaded files in page order |
| S3 Question inventory | `/setup/inventory?package_id={package}` | The question list read back from a stored package (it prints *"Questions read back from the package: {count}"* and lists them); blocking for a run |
| S4 Answer keys | `/setup/answer-keys` | Meant to show the keys to supply; it still prints *"Answer keys read back from the package: 0"* — the keys are not read back on this page yet |
| S5 Optional setup | `/setup/optional` | Five optional cards, each skippable, each saying what skipping costs |
| S6 Preflight | `/cohorts/{cohort}/preflight` | The five intake checks, and whether "start run" is available |
| S7 Run monitor | `/runs/{run}/monitor` | Work counts by stage, criterion and judge; the run's status |
| S8 Quarantine | `/quarantine` | Each waiting paper's ID (*"… — parked for operator triage"*) and any stored image crop. It does **not** say why the paper was parked — the SPA's Parked screen does |
| S9 Review queue | `/runs/{run}/review` | Legacy queue that can rank marks by expected value against a time budget. This is not the SPA's `/#/review` summary/list; the SPA has no time-budget picker. |
| S10 Whole-grade sample | `/runs/{run}/sample` | One fixed sentence about the sample; it lists no grades |
| S11 Blind sample | `/runs/{run}/blind` | One fixed sentence about the blind sample; the sample itself is done on the SPA's blind screen |
| S12 Class rollup | `/runs/{run}/rollup` | Every student's grade, and the finalize step |
| S13 Student detail | `/students/{submission-id}` | A limited legacy detail page; it renders generic band controls, not the rubric's actual bands, and is not the SPA's student-results view |
| S14 Export gate | `/packages/{package-version}/export-gate` | The decision to export a package |

Two facts about these pages:

* **The legacy pages are not the SPA controls.** Their generic band selectors do not offer the SPA's teacher workflow. Use the SPA's Results and student-detail screens to read results and change grades; the amendment form lists the package's rubric band names. The SPA's blind-sample screen offers each question's own levels from the package.
* **S13 takes the system's submission ID** (looks like `sub-22a56dc63714`), **not** the student's own ID. Using the student's ID (for example `P-0001`) opens a page that says *"No scores are settled for this submission."* The SPA's student screen is reached from the results screen, which hands over the right ID.

**S8's sample problems, as the checks decide them** (verified for the sample files):

| Sample sheet | Status the system gives | Which check | What you do |
|---|---|---|---|
| Two ticks on Q1 | `incomplete` | v2 structure | Look at the paper and decide the tick yourself, then release it on the SPA's Parked screen, or close it |
| Wrong test (names another test) | `unmatched_assessment` | v4 match | Find which test it really belongs to. Release it **only** if it really is this test (for example the name was miswritten): a released paper is graded against *this* package. If it belongs to another test, close it and read it in under the right package from that class's Papers inbox |
| No name written | `incomplete` | v3 identity | Work out whose it is. It **cannot be released** (it would be graded under nobody): close it, or have the student's ID written on it, rescan it, and read it in again from the Papers inbox |

---

## 9. When something goes wrong

Every message below is the system's real wording.

| You see | It means | Do this |
|---|---|---|
| `InsecureLocationError: … is not a safe data directory: /tmp is world-writable` | The data folder is somewhere other users can reach | Choose a folder in your own home directory |
| `ConsoleBindRefused: … refuses a non-loopback bind` | Something asked the console to listen to the network | Remove `CONSOLE_BIND`; use a tunnel (3.4) |
| `ConsoleBindRefused: … refuses to start under the cloud-hosted profile` | `HARNESS_PROFILE` is `cloud-hosted` | Use `dev-ci` or `edge-local` for the console |
| `ConfigurationError: HARNESS_PROFILE must be one of ('edge-local', 'cloud-hosted', 'dev-ci'), got None` | A run was started with no profile | Set `HARNESS_PROFILE`, or choose one in the config file |
| *"no backend profile is configured for authoring …"* | Drafting was started with no profile | Set the profile (3.1) and start the draft again |
| `ConsentGateError: cohort … has consent_class 'real' … may not be sent to a 'dev-ci' provider` | Real student work is not allowed to leave the machine without recorded authority | Use a `synthetic` or `consented` cohort, or supply the override with a named person |
| `HTTP 404 … No endpoints found matching your data policy` | No host that keeps zero data serves that model on OpenRouter | Choose another model (deployment tutorial, 7.6) |
| `RetentionPolicyError: … zero-retention routing unconfirmed …` | A run was started on a provider that cannot confirm zero retention for every model (for example the Jev decision model) | Use the shipped `dev-ci` setup; leave the decision engine `off` |
| An action answers `404 not found` | The action is not one of the console's declared actions | The SPA only sends declared actions; if you were crafting a request, check the spelling against the console's own action list |
| `"refused": true … refresh_required` | The screen was out of date | Refresh and try again |
| `…is already complete; nothing was started` | You tried to start a run twice | Nothing to do |
| `M-PKG refused the band '…'` | That band name does not exist for that rubric line | Use a real one — the SPA's pickers list them (section 5.3) |
| Page says `No scores are settled for this submission` | You used the student's ID | Use the `sub-…` ID from the results screen |
| `aeh run` exits with **3** | The run did not finish (paused, or stopped for another reason) | Read the `status` and `pause_reason` it printed. Fix the cause, then resume through the console's Jobs screen or queue the appropriate Resume request. Rerunning `aeh run` does not resume a paused run; it starts pending runs. |

---

## 10. The ten-minute rehearsal

With the practice folder from section 2 and the console running:

1. Open the wizard home. Confirm the class and package stages reflect the practice data and the run's stage shows *Done*.
2. Open `/#/review`. Read the flagged-mark and provisional-grade counts, and the listed item identifiers and kinds.
3. Follow an item to Results or a student detail. Review the feedback there; the Review list itself has no accept/edit action.
4. Open `/#/results`. Find a student, open their screen, and read the narrative and bands.
5. Finalize the batch from the results screen. Read the outcome the screen shows.
6. Amend one final grade with a real band name and a reason, then open the student's screen again and read the revision back.
7. Open `/#/review/blind`. Confirm each drawn answer offers that question's own levels, with nothing preselected and no system mark shown.
8. Open `/#/parked` (the practice folder has none — the screen says so) and `/#/jobs` (it has the run, with its cost and run controls).
9. Press Ctrl-C. Start the console again under the same profile. Everything is still there, and the finalized run remains settled.

If all nine work, you can operate the console as it ships today — and section 6 is the honest list of what still needs the terminal.
