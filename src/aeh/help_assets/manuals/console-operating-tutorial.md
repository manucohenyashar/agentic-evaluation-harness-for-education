# Operating the Grading System: A Tutorial for Operators and Teachers

*For people who are comfortable with a web browser and can follow a recipe in a terminal window, but are not programmers.*

This tutorial walks through the whole life of one test in the grading system: create the class, make the test package from your own documents, upload the papers, let the system grade them, review the result, finalize the grades, and tidy up. It is written for the first live teacher test, so every step says **who** does it, **what you will see**, and **what to type**.

> ### Read this box first
> Everything in this tutorial describes the console **as it is shipped today**. The console's main surface is a **single-page web app (the SPA)** that opens at the address the console prints. In it you can: make a class from a typed list or a class list file; draft a test package from your own documents (PDF, DOCX or TXT), preview what the system understood, watch the draft being made, answer the draft's open questions, edit it, and approve it into a published package; upload the test paper and the answer sheets and have them read through the five intake checks; start, pause and resume grading runs; mark a few example papers so the system can check it reads the rubric your way; mark the blind sample without seeing the system's marks and read how closely the marking matched yours; work the review queue; finalize the batch; amend a finalized grade with a recorded reason; read every result; and download the marks, a student's report and the test itself. **What still needs the terminal:** starting the console itself, with its key and settings (section 3.1). The terminal commands (`aeh cohort create`, `aeh ingest`, `aeh run`, `aeh results export`) remain for scripting and debugging. Every remaining gap, with proof, is in [`docs/live-tests/02-live-readiness-and-blockers.md`](../live-tests/02-live-readiness-and-blockers.md), and this tutorial's section 6 lists them in one place.
>
> Runs grade through OpenRouter under the `dev-ci` profile, with data retention governed by the operator's OpenRouter account privacy settings (the system does not request it); setting `HARNESS_FIXTURE_DIR` switches to recorded replays instead (offline rehearsal). The console refuses the `cloud-hosted` profile on purpose. The **practice data** in section 2 lets you rehearse everything the console can do, spending no money and sending nothing anywhere.

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

This builds a finished run over three demo students (Nadia Rahman, Oliver Grant and Sofia Mendes) in a private folder, `~/aeh-rehearsal`. When it ends it prints the three IDs you will use below:

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

This tutorial teaches the console first, on purpose: the teacher-facing grading day happens in the browser — class creation, package authoring, reading the papers, run control, review, blind sampling, finalization, amendments and the result downloads. The terminal remains for starting the console with its key and settings, for scripting, and for debugging. The console's Help screen lists every `aeh` command and where it is represented or why it remains CLI-only (the system keeps that inventory and fails a check if a new command appears without one). Section 7 is a selected guide to those commands, not a complete CLI reference.

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
| Set up a class | `/#/class` | Teacher | Every class and its students by name, with who has no paper yet; make a class (typed list or a class list file), add late students, correct a name, take a student off the list, delete a class |
| Set up a test package | `/#/package` | Teacher | The setup draft's steps, which ones block publishing, and the **Publish** control; for each published test, **Mark examples** and its record, *How well this test has been marked so far* |
| Author a package | `/#/package/author` | Teacher | Upload your documents, preview what was understood, start the draft job |
| Review the draft | `/#/package/review` | Teacher | The draft's open questions to answer, how each line will be marked (with **Change**), and each level's description; approve it when none remain |
| Your marked examples | `/#/package/examples` | Teacher | Optional: upload unmarked copies, mark them, **Check my examples**, see where the system read the rubric differently and answer its questions |
| Edit the draft | `/#/package/edit` | Teacher | Add, edit, reorder and delete questions and grading points |
| Load papers | `/#/papers` | Teacher/Operator | Upload the test paper and the answer sheets, read them through the five checks, and see each student's paper; give a paper to the right student, remove a paper, replace the wrong test paper |
| Start a run | `/#/run` | Teacher/Operator | Start a new grading run for the selected class and test version, priced, behind a confirmation |
| Run monitor | `/#/monitor` | Operator | The run's status and pause reason beside the orchestrator's own progress counts, and while answers are marked, where the run is (*Marking · question … line … of … · grader … of …*); it refreshes itself. When marking finishes: **Mark the sample** or **Skip and see results**; once no sample is waiting, **Check a few whole grades** or **See the results** |
| Review queue | `/#/review` | Teacher | The flagged answers worth your time for the minutes you have, in groups and one by one, with **Apply to all**, **Accept**, **Change** and **Skip** |
| Whole-grade sample | `/#/results/whole-grade` | Teacher | 10 to 15 students' complete grades, read end to end as each student will receive them; **Yes, they do**, **Open a student** or **Skip** |
| Blind sample | `/#/review/blind` | Teacher | The answers drawn for the blind sample, each with that question's own levels and nothing the system decided; **Finish** or skip, then your marks beside the system's |
| Results | `/#/results` | Teacher | Every student's grade, or its range while unchecked answers could move it (filter: *Could move a grade*); *How closely the marking matched yours*; the finalize control; the **Whole-grade sample** button; the amend form; the downloads (marks spreadsheet and CSV, a student's report, the test as a PDF and its backup); correcting an answer key; the review window |
| One student | `/#/results/students/{submission-id}` | Teacher | The narrative feedback first, then each line's band (or the grade's range), and the amend form |
| Past tests | `/#/past` | Teacher | Every test graded before, newest first, with its class, test and date; find a student by name across all of them; each test's record |
| Parked | `/#/parked` | Operator | Each parked paper with its reason, and the mark as scanned where the reading kept a picture of it; give it to a student, release or close it, keep one of two papers for one student, with a recorded note |
| Jobs | `/#/jobs` | Operator | Every job — drafts and runs — with progress, elapsed time and cost so far; a run offers Pause and Resume |
| Issues | `/#/issues` | Teacher | The run's findings that need a person, by severity |
| Logs | `/#/logs` | Engineer | The run's stage records, paged |
| Settings | `/#/settings` | Teacher/Engineer | The configuration as it stands; the editable subset as guided forms |
| System status | `/#/status` | Operator | Whether the store, the provider and the services behind the screens are answering; how the graders themselves measure up (the Jev block, the consistency check, the validation checks) |
| Help | `/#/help` | Everyone | The four manuals and the question box, which answers from them with citations |

**A second, quieter surface also exists.** The console still serves the older server-rendered pages S1–S14 at plain addresses (`/packages`, `/runs/{run}/rollup`, and so on — the full list is section 8). They are operator/audit pages, separate from the teacher-facing SPA. Some legacy grade pages render generic band controls, but they do not provide the SPA's guided workflows; this tutorial's steps happen in the SPA unless stated otherwise.

---

## 5. The test day, screen by screen

The whole day, class to download, as one walk over the sample tests: [`docs/live-tests/05-console-teacher-walk.md`](../live-tests/05-console-teacher-walk.md).

### 5.0 Make the class (teacher, once)

Open **Set up a class** (`/#/class`). Give the class a name (lower-case letters, digits, `-`, `_` or `.` — it becomes a file name), choose **whose work this is** — made-up practice work, work the students or their guardians agreed to, or real work without that agreement — and add the students: type or paste one per line (a spreadsheet's *first name, last name, optional ID* columns paste as they are), or **import a class list file**, which lists every student it found and every problem line, with its line number, before anything is written. **Make the class.**

The consent choice has no default and can never be changed afterwards: it decides whether the class's papers may go to a remote model at all. With one class stored, the console selects it everywhere; with several, choose one in the top bar's *Class* switcher.

**Check the class against your own list.** Each class lists its students **by name**, alphabetically, each with *paper read* or *no paper yet*, and a line above the list says how many students are listed, how many papers are in, and — by name — who has no paper yet. Students are always shown by their names; a student's ID appears after the name only when two students in the class share a name.

**Fix the list.** Under the class:

* **Correct name** fixes a misspelt name in place. The student keeps their papers, and papers read afterwards are matched against the corrected name.
* **Take off list** removes a student added by mistake (or twice, or who left). It is offered only for a student with no paper yet: move or remove their paper first (5.2).
* **Add students** adds late students, one per line.
* **Delete this class…** removes a class for good after you type its name. It is offered only for a class that holds no papers and no grading runs — a class made by mistake. A class with papers but no grading run yet can be emptied first (remove its papers on **Load papers**) and then deleted; once a grading run has been started for it, the class is kept. A graded class is kept: its results stay under **Past tests**, and the screen says so instead of offering the delete. (If a graded class is removed by other means while its blind sample is still open, the system refuses with *"Finish or skip the blind sample for <class>, then delete the class."*.)

### 5.1 Make the test package (teacher, once, 30 to 60 minutes)

Everything here happens on the package screens, and **drafting needs a configured profile** (section 3.1).

1. **Upload your documents.** Open `/#/package/author`. You can give the system the test paper, your model answer and your rubric — **PDF, DOCX or TXT**, up to 10 MB per document (the limit is adjustable; the deployment tutorial's knob table has it). Each file shows its own status as it is read: *Reading*, then *Understood*, or *Refused* with the reason and what to do next — a refused file never blocks the others.
2. **Preview what was understood.** Before anything is written, the screen shows what the console read from each document: pages, text blocks, words, tables and pictures, with the text in page order. A page with no text layer is named in the warnings, never silently dropped.
3. **Start the draft.** One confirmation and the draft runs as a background job. You can watch its stage, its progress count and the elapsed time on the same page or on the Jobs screen, and cancel it while it runs. Reload the page mid-draft and you are re-attached to the job — nothing is lost. (An empty draft you fill by hand is started the same way, with *from scratch*.)
4. **Review the draft.** The draft's open questions — a missing expected answer, an unclear rubric line — wait at `/#/package/review`. Answer each in place; the screen says how many pieces are missing. A change the draft needs but no question covers goes to the editor at `/#/package/edit`: add, edit, reorder or delete questions and grading points there.
   * **Every level must say what earns it.** A judged line's level with no description is an open question — *"What earns '<level>' on <question>? Say what the answer does, not how good it is."* — and the draft cannot be approved until each is answered. A description that leans on words such as *good*, *excellent*, *correct* or *clearly* gets a **Note** suggesting what the answer *does* instead; the note never blocks.
   * **How each line will be marked.** Each judged line reads *Marked as a simple check* (present or not; one grader decides unless graders disagree) or *Marked as an overall judgement* (three graders from the start; harder to accept without you), with *(chosen automatically)* when the system chose. Up to six such lines offer **Change** with the two choices; the rest are listed as staying as shown. A choice you make reads *(your choice)* and is kept when you approve.
5. **Approve.** When no question remains, the review screen's **Approve** control publishes the draft. Approval goes through the same package build gate `aeh package build` uses — a draft that would refuse is refused here too, with the reason, and nothing is written.
6. **Mark a few examples (optional, recommended).** Once the test is published, `/#/package` lists it under *Your marked examples*; **Mark examples** opens `/#/package/examples`. It checks one thing: whether the system reads your rubric the way you do. **Skip this step** is offered on every sub-step, and skipping marks the test with the rubric as written.
   1. **Upload unmarked copies** — 1 to 25 PDF answer sheets, one per student (10 to 15 recommended). A page with marks on it is refused by name (*"Page 2 of <file> has marks on it. Please upload an unmarked copy, and enter your marks in the form."*). The first upload asks whose papers these are; on an online model only made-up practice papers are sent.
   2. **Mark each paper** on the same kind of form as the blind sample, a level for every part, then **Save my marks for this paper**.
   3. **Check my examples** marks them with the rubric as written, as a background job with a clock; the screen states the cost, which counts toward the run cost limit.
   4. **See where the system read your rubric differently**: each difference side by side (*You:* / *The system:* and its reason), grouped by cause — *The rubric may be unclear* (a question follows), *The system misread a clear rule* (reported; the rubric is not changed), *Two similar answers were marked differently* (shown side by side; nothing changed). Then up to six questions: broaden, narrow or keep a level's description, or answer in your own words; tick *My students saw this rubric before the test* if they did.

   The step never shows a percentage or a count of matches, and says why: *"With a dozen papers you chose, a percentage would not tell you how accurate the marking is. That's what the blind sample is for."* Answers that change a description make a clarified rubric, which is not used until it passes two checks: an independent check of its wording, then a check on the next class — which is graded and delivered with the original rubric while the clarified one marks the same papers alongside. The step's screen, and the run start, say in one sentence where it stands; a set-aside rubric names why. The teacher guide, Step 5, explains the step in full.

A second route to a published package also exists: `/#/package` shows the setup draft's steps, names which steps **block** publishing, and offers **Publish the draft version** only when the draft is ready — the control is present but disabled over a blocked gate, so the screen never offers a publish the gates would refuse. Publishing locks the version and records you as the approver. This is the path for a package the operator set up directly rather than drafted from documents.

**Check it worked:** the wizard home's stage 2 shows *Done* once a package is published, and the run screens name the package version the run grades against.

*The terminal's `aeh package build --spec` remains a developer and system-emitted route (the deployment tutorial, section 8.2): a published version's spec file is an export the system writes, not something a teacher authors.*

### 5.2 Load the papers and start the run (teacher or operator)

**Reading the scans in.** Open **Load papers** (`/#/papers`) with the class selected. Choose the published test version the papers answer, the **test paper** (once per class — every answer sheet is checked against it) and the **answer sheets**, one PDF per student, each carrying the test name and the student's name or ID. The files you chose are listed; **Read the papers** asks for a confirmation (the pages go to the page reader in the console's settings) and then sends them. The console reads them on its own worker — you can leave the page — and a progress bar shows each file's outcome; the same work is on **Jobs** as *Reading the papers*. Every sheet goes through the five intake checks; a sheet that fails one waits on the Parked screen. Sending the same file again skips it, and a **rescan** of a student whose paper is already in (a sharper scan, the pages in the right order) is parked as *a second paper for that student* — never graded beside the first — so a student is never graded twice (5.4 says how to keep the right one). This is the same reading `aeh ingest` does from the terminal (deployment tutorial, section 8.3).

**The reading cost limit.** The confirmation before reading states the estimated cost (or that local models cost nothing). Reading stops at the reading cost limit — the run cost limit, unless the operator has set a separate reading limit — with the sentence *"Reading paused at the reading cost limit of …: the … file(s) read so far cost …. … file(s) wait unread. Press Resume to read up to … more; papers already read are kept and are not read again."* on **Load papers** and on **Jobs**. **Resume** carries on from the next unread file.

**Check who is missing.** The *Students* panel says how many of the listed students have a paper read and names those who have none yet, and lists every student by name with their paper's state. Papers not filed under a student (no name found, or parked) are listed below it.

**Fix a paper.** Beside each paper:

* **Not theirs? Give it to…** moves a paper the console filed under the wrong student (similar names, a borrowed sheet) to the student it belongs to — only students with no paper yet are offered. Marks it already has move with it, and the move is recorded.
* **Remove paper** takes out a paper that should not be here — the wrong file, another class's sheet, a blank page, the earlier of two scans — so the right scan can be uploaded and read. It is offered only for a paper no grading run has touched; a paper that is part of a run's record stays (correct its marks from Results, move it to the right student, or close it on Parked).
* **Wrong test paper? Replace it** (beside *The test paper*) removes the test paper read for this class, and the answer sheets already checked against it, so the right test paper and the sheets are read again with your next upload. It is offered only while nothing in the class has been graded.

**The five intake checks, in plain words:**

| Check | Plain meaning | Fails when |
|---|---|---|
| **v0 integrity** | The file is a sound PDF | Corrupt file, or too many blank pages |
| **v1 pages** | Every page is there | A page is missing or doubled |
| **v2 structure** | The paper has the questions the package expects, and every mark is readable | Wrong question layout, or a mark with two ticks / an unreadable tick |
| **v3 identity** | The student named on the page is on the class list | No name, or a name not on the roster |
| **v4 match** | The paper is the right test | The printed test name is different, or the answers share almost no words with the questions |

Papers with problems do **not** hold the run back: they wait on the Parked screen while the rest are graded.

**Start the run.** Open `/#/run` with the class selected, choose the test version and press **Start a new grading run**. If some students have no paper read yet, the screen names them first — they get no result from the run, so load their papers before starting if you have them. The confirmation says what will be graded, under which settings profile, and the estimated cost. A run that is still waiting to start shows its own **Start the run** control. Confirm, and the run starts on a worker the console owns and the console opens the run monitor. Recovery resumes eligible interrupted work at console startup; an intentionally paused run is resumed only when it has an unapplied queued Resume request.

**Watch it.** `/#/monitor` shows the run ID, status, any pause reason, and progress values supplied by the orchestrator (such as done, in-flight, pending and quarantined work). While answers are being marked, a line under the status says where the run is: *"Marking · question Q2 line 3 of 12 · grader 2 of 3"* (the question is named when the test gives the line one). There is deliberately no per-student progress figure, because the work is done by criterion, not by student. The screen refreshes itself every two seconds.

**Pause and resume.** The Jobs screen offers Pause and Resume controls for a run, behind a confirmation; each queues a request the orchestrator applies at a grading-point boundary. The SPA does not offer a run-cancel button. Cancellation is available for a drafting job from its authoring screen. Although a declared `cancel job` action exists, do not treat it as a documented run-cancel control: Jobs exposes Pause and Resume for runs.

**If the machine restarts**: start the console again, **under the same profile as the run** (3.1). Recovery reclaims expired leases and resumes a run that was running when interrupted. It does not start a pending run or override an operator pause. To resume a run paused intentionally, queue Resume in Jobs first; if the console itself was stopped, the queued resume lets recovery resume it on restart. Starting under a different profile leaves the run paused, with the refusal recorded. `python -m aeh recover --data-dir <folder>` runs recovery without starting a grading pass: it reclaims expired leases, resumes eligible runs, and settles completed runs that still have ungraded or non-final scores, printing its report. To drive a new grading pass, start the console or use `aeh run`.

**A run from the command line** is `python -m aeh run --data-dir <folder> --cohort <cohort> --package-version <version> --config <file>`. Its exit code: **0** finished, **3** *not finished* (paused, or stopped for another reason; read the `status` and `pause_reason` it prints), **1** an error, with the reason printed after `aeh run:`.

### 5.3 Review, finalize, amend (teacher)

Reviewing the results is optional; the review screen is not an action queue, and a grade can remain provisional if the review window is still open.

1. **The blind sample comes first.** Starting the run already said you would be asked to mark about 15 answers. When marking finishes, **Monitor run** (`/#/monitor`) shows *"Marking finished. Mark 15 answers yourself first, without seeing the system's marks (about 10 min), or skip and see the results."* with **Mark the sample** and **Skip and see results** (the count is the answers actually drawn; the minutes are the configured time). Skipping changes no mark; it only means no new evidence about how closely the marking matches yours.
2. **Mark the blind sample** at `/#/review/blind`. Each drawn answer shows the student's name and the question, the answer as text, **View the page** for the scanned page, and **that question's own levels** with their descriptions (a generic five-level scale only when the test's own levels cannot be read) — nothing preselected, nothing the system decided. Each choice is saved as a draft at once, *"N of M marked"* counts them, and you can change them until **Finish**; finishing with answers unmarked asks first, and only marked answers count. **Skip and see results** is here too. After Finish the screen shows *Your marks beside the system's*: *You:* beside *The system:* for each answer, differences first, each saying whether the system gave more or less credit. While the sample is open, the drawn answers' levels and points and those students' totals read *"Hidden until you mark your sample or skip it"* on Results and on the student's page; approving the grades does not close the sample. **The marks download (spreadsheet and CSV) carries every total, deliberately** — finish or skip the sample before opening it. Why the sample is done blind, why one class is "too few" and what "agreement beyond chance" means: the teacher guide, section 5.
3. **Read how closely the marking matched yours.** After Finish, `/#/results` carries the block *"How closely the marking matched yours"*: how many of your blind answers got the same level; per question, *agreement beyond chance* with the number of answers beside it; *"Too few answers to rely on yet (… of the 30 needed)."* while a question has fewer than 30; and the differences by student name, with **Review these** to open the comparison. It never shows a percentage or claims accuracy. Earlier classes' record of the same test follows on its own labelled line; the test's whole record, *"How well this test has been marked so far"*, is on `/#/package` and `/#/past`.

   *The statistics behind the figures.* The number is chance-corrected. The Results block uses **Cohen's κ** (you and the system, one answer at a time); **System status** uses **ordinal Krippendorff's α** when several graders or Jev are compared; the test's detailed validation record also carries **QWK** (quadratic weighted kappa), which counts a one-level miss as far less serious than a two-level miss. All three subtract the agreement chance alone would give: 1.00 is perfect, 0.00 is no better than chance, below 0 is worse; none is a percentage or an accuracy score. A question needs at least 30 blind answers before the figure is shown — below that the screen says *"too few"*. Rules of thumb, not pass marks: 0.6–0.8 substantial, above 0.8 near-perfect. Read the number with its answer count and the differences by student and question; let the evidence accumulate across classes on the same test version. The teacher guide, section 5, explains what to do with a low figure.
4. **Work the review queue** at `/#/review`. Type the minutes you have (*I have [30] minutes*, a whole number from 1 to 480) and press **Go**. The queue is not "every answer above a risk level": the flagged answers are ranked by what a check is worth — how likely the mark is wrong, times how much it would change, for the time the check takes — and the best that fit in your minutes are shown. The header says it in three sentences: *"<r> of those <b> minutes are reserved for the blind sample and spent there. These are the <s> highest-value answers of <f> flagged, in the other <b−r>. The remaining <p> stay provisional and in your queue."* Answers on one rubric line sharing one pattern come first, as a group: *"<n> students · <question> · <line> — all show the same pattern"*, the pattern in a sentence, three papers side by side, the levels with the current one marked, **Apply to all <n>** (one decision, one record per answer: *"<n> answers marked <level> as one decision; each is recorded on its own."*; an answer changed since the queue was shown is refused by name and the rest proceed) or **Review one by one** (the students, each linking to their own page). Each other answer shows its feedback, *What the paper shows*, the levels with the proposed one marked and *chosen by Grader 1, …* beside the graders' choices, **Accept**, **Change** or **Skip** (it stays provisional and in the queue), and *Flagged because:* — *panel disagreement*, *near a grade boundary*, *reading uncertain* or *this line is often changed*. The blind sample is never listed here; *Open the blind sample* links to it.
5. **Check a few whole grades** (optional) at `/#/results/whole-grade`, reached from Monitor's *Marking finished.* banner once no blind sample is waiting — finished, skipped or never drawn (**Check a few whole grades**), or from the **Whole-grade sample** button on Results. It shows 10 to 15 students' complete results — feedback first, then the total and grade, then each question's points and each line's level — *drawn from the answers the system accepted on its own, not the ones you reviewed*, and asks one question: *"Do these look like grades you would have given?"* **Yes, they do** records the answer; **Open a student** opens the student chosen in the list beside it; **Skip** states its cost on the screen: *"Skipping means nobody has read a whole paper's result end to end; the grades are delivered either way."* Neither answer changes a mark or counts as evidence of agreement. A run with too few grades accepted on their own draws fewer, and says so.
6. **Finalize.** On `/#/results`, a student whose unchecked answers could move their grade across a boundary shows a range instead of a grade — *"Total grade: 62–71 (B–C) until 3 answers are checked"* (in points when the test has no grade boundaries) — on Results and on their own page; the *Flag* filter's **Could move a grade** lists them. The **Approve all grades** confirmation counts what it accepts: *"Approve all grades for <class> — <test>? <n> answers you have not checked will be accepted as the AI graded them; <k> of them could move a student's grade. You can still change a grade afterward; the change is recorded."* Approving settles each grade at what the AI's marks add up to. The control stamps the run as delivered behind its confirmation (**Approve all**), naming you (the console has no accounts, so the recorded name is the console's operator label). If the package declared a review window, finalizing inside the window leaves the grades *provisional*; the system settles them when the window ends.
7. **Change a grade.** From the results screen or the student's own screen, use the grade control. For a grade not yet final, the console records a review action; changing a finalized grade requires **a reason**, creates a new revision and keeps the original. The student's screen shows the amendment history, including the reason and actor when recorded.
8. **Download.** The **Download the results** panel on `/#/results` saves the marks as a spreadsheet (`.xlsx`) or a CSV file, one student's report as a PDF, and the test itself as a readable PDF and as its backup file. *Marks version* 1 is every student's marks as first given; version 2 lists only the students whose final mark was changed. The same screen corrects a multiple-choice **answer key** found wrong after the run (the question's marks are worked out again for the class) and sets the **review window** (hours the grades stay open before finalizing settles them).
9. **Read the results.** `/#/results` shows each student's grade (or range, step 6), class distribution, per-criterion statistics and the lines most students missed; it does not show a multiple-choice distractor breakdown. Students are listed by name; the search box finds a student by name. Click a name to open that student's own page, where each line's feedback comes before its band. Results, the student's page, the whole-grade sample and the review queue each end with one line naming what produced the grades: *"Marked with <test> version <n> · settings <where it ran> · graders <how many>"* — for example *settings an online AI service* or *settings on this computer, nothing sent out*, and *graders three AI graders* — read from the settings the run was started with, so an older test opened from Past tests names what marked it then.
10. **Answer a question about an earlier test.** Open **Past tests** (`/#/past`). Every test graded before is listed newest first, with its class, the test version, the date and how many students were graded; choose a class to narrow the list. Each test's record — the blind answers its classes have collected — is shown there too. Type a student's name to see that student in every past test, with their total — click a line to open their page for that test, or a test to open its results. The top bar's *Grading run* switcher names each run the same way (class · test · date), the selected class's runs first.

### 5.4 Parked papers (operator)

Open `/#/parked`. Each waiting paper shows **why it was parked** — the check that stopped it and the note the check left — and, for a mark the reading kept a picture of (an unreadable or doubled tick, for example), that picture under *The mark as scanned*, so you can read the tick yourself before deciding; then the decisions available. Three decisions exist, each with an optional note:

* **Give it to a student.** For a paper with no name, or a name the class list does not match: choose the student it belongs to under *This paper belongs to* (only students with no paper yet are offered) and press **Give it to this student**. It is graded as theirs. A student who already has a paper cannot be given a second one.
* **Release** the paper to scoring. This is right when you have looked at the paper and the system's reading stands. For a doubled mark, the paper is scored on what the page reader read — write the tick you read in the note, and correct the mark on the student's result if it needs it.
* **Close** the paper as unresolvable. Closing never gives zero: the unscored lines are marked MISSING and the grade INCOMPLETE. For a wrong-test paper, note which test it is and upload it on the right class.

**A second paper for one student** (a rescan, or two sheets with one name) is parked with the student's name and the note that they already have a paper. Keep one of the two:

* **Keep the earlier paper (remove this scan)** removes the new scan; nothing else changes.
* **Use this scan instead** removes the earlier paper (offered only while it is not graded); then choose the student under *This paper belongs to* and press **Give it to this student**.

A second paper is never closed — closed, it would be graded INCOMPLETE beside the student's real paper.

Every decision asks for a confirmation before it is sent, and is recorded with your name, the time, the student and your note; the card shows the decisions already recorded. The system will **not** reassign a paper by itself.

### 5.5 The rest of the sidebar

* **Past tests** — every test graded before, by class, test and date; find a student by name across them (5.3, step 10).
* **Jobs** — every background job (drafts and runs) with its state, progress, duration and **cost so far** in dollars, or a dash while it has none. Pause or resume a run here. A drafting job can be cancelled from its authoring screen; Jobs does not offer run cancellation.
* **Issues** — the run's findings that need a person: second-opinion notes are labelled *Information*, every other known source *Needs attention*, with the words beside the icon, not colour alone.
* **Logs** — the run's stage records, paged; the page size is a knob (deployment tutorial, section 10).
* **Settings** — the configuration as it stands, every setting with its teacher label. The editable subset is guided forms behind their confirmation; everything else is read-only, which is the truth. A secret's row says whether one is configured and never shows a value, and no key name from the configuration file appears anywhere on the page.
* **System status** — whether the store, the model provider and the services behind the screens are answering, and how the graders themselves measure up against the teachers' blind marks. The **Jev** block says whether Jev's answers are final (*"Jev's answers are final when it is confident and one judge agrees (on)"* or *(off)*) and either *"Evidence so far: <k> of <n> blind answers needed."* or, once there are enough, each question's agreement beyond chance for Jev's answers beside the judges' alone — with a warning naming any question where Jev agreed less well. (Jev is the decision engine reached through OpenRouter's `typesafe/jev-latest` alias; deployment tutorial, section 7.5.) The **Consistency check** appears after the marking models change: the marked examples are marked again and the screen says how many moved to a different level — it compares the system with its own earlier marks, not with yours. **Validation checks** say when they last ran (after a test was published or the marking models changed), or that they were not run because they would cost more than the run cost limit. Nothing here is a percentage; below its minimum a figure reads *too few* with the count.
* **Help** — the four manuals (this tutorial, the teacher guide, the deployment tutorial and the test-day plan, served from the console itself), and a question box that answers from them with citations.

---

### 5.6 Fixing a mistake: where to go

| The mistake | Where to fix it |
|---|---|
| A student's name is misspelt | **Set up a class** → *Correct name* |
| A student is listed by mistake, twice, or has left | **Set up a class** → *Take off list* (move or remove their paper first) |
| A student is missing from the list | **Set up a class** → *Add students*, then give them their paper (Parked or Load papers) |
| A paper was filed under the wrong student | **Load papers** → *Not theirs? Give it to…* |
| The wrong file, or another class's paper, was read | **Load papers** → *Remove paper* (ungraded papers) |
| A sharper rescan of a sheet was uploaded | **Parked** → keep one of the two papers |
| The wrong test paper was read | **Load papers** → *Wrong test paper? Replace it* (before grading) |
| A class was made with the wrong name or consent choice | Remove its papers if any, delete the class, and make it again |
| A mark is wrong | **Results** → the student → change the grade (with a reason once final) |
| A multiple-choice answer key was wrong | **Results** → correct the answer key |
| "What did this student get on the last test?" | **Past tests** → type the student's name |

## 6. What is not in the console yet

Named plainly, so nobody meets them by surprise. Each is a known, tracked gap.

| Gap | What you do instead |
|---|---|
| **Starting the console** reads its environment once: the OpenRouter key and other environment settings cannot be changed from the browser. | The operator sets them before `aeh console` (section 3.1; the live-test walk's step 0). |
| **A late paper after the run.** A student who sat the test late is graded by a new run for the class, which grades every paper again. | Load the late paper on **Load papers**, then **Start a new grading run**; the new run's results include everyone. Past tests keeps both runs. |
| **Undoing a run started by mistake.** A run is never deleted. | Pause it on **Jobs**; it stays listed under Past tests with its state. Start the right run. |

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
| S9 Review queue | `/runs/{run}/review` | Legacy queue that can rank marks by expected value against a time budget. The SPA's review queue (`/#/review`) does the same with its *I have [ ] minutes* field and its own controls; use that. |
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
| No name written | `incomplete` | v3 identity | Work out whose it is. It **cannot be released** as `matched` (it would be graded under nobody): give it to the student on **Parked** (`assigned`), or have their full name written on the `Student:` line, rescan it, and read it in again from the Papers inbox |

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
| `HTTP 404 … No endpoints found matching your data policy` | No host allowed by the OpenRouter account's privacy settings serves that model | Choose another model, or review the account's privacy settings (deployment tutorial, 7.6) |
| `RetentionPolicyError: … zero-retention routing unconfirmed …` | A run used a model that is not served through OpenRouter and could not confirm zero retention (OpenRouter models are never checked: their retention is set by the OpenRouter account) | Use the shipped `dev-ci` setup |
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
2. Open `/#/review`. Type a number of minutes and press **Go**; read the header's numbers and the flagged answers shown.
3. Accept, change or skip one answer (or apply a group's level to all), and read the outcome the screen shows.
4. Open `/#/results`. Find a student, open their screen, and read the narrative and bands.
5. Press **Approve all grades** on the results screen. Read the outcome the screen shows.
6. Amend one final grade with a real band name and a reason, then open the student's screen again and read the revision back.
7. Open `/#/review/blind`. Confirm each drawn answer offers that question's own levels, with nothing preselected and no system mark shown, and that *"N of M marked"* counts your choices.
8. Open `/#/parked` (the practice folder has none — the screen says so) and `/#/jobs` (it has the run, with its cost and run controls).
9. Press Ctrl-C. Start the console again under the same profile. Everything is still there, and the finalized run remains settled.

If all nine work, you can operate the console as it ships today — and section 6 is the honest list of what still needs the terminal.
