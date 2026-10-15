# UAT-13 — The whole workflow without a terminal

| Field | Value |
|---|---|
| ID | UAT-13 |
| Req | NFR-SYS-17 |
| Preconditions / input | The deployment-tutorial walkthrough performed with the terminal closed after `pip install .`, on the reference machine, by a non-technical operator |
| Rung | 4 |
| Expected | Every step of install, configure, set-up, run, monitor, review, export and help completes without a terminal; every place the walkthrough would have needed one is a defect against this plan |
| Oracle | Checklist sign-off |
| P | P1 |

**Status against the shipped build (2026-10-14).** This script states the target the
operator-requirements plan carries; it has not been executed, and no pass is claimed. The
shipped console now covers package authoring, run control, review, blind sampling,
finalization and amendment in the browser, but the steps below still describe controls
that do not exist yet: starting and stopping the console without a terminal (steps 4 and
13), the class setup of step 6, the browser scan intake of step 7, and the export download
of step 11. On today's build those need `python -m aeh console` (started and stopped from
a terminal), `aeh cohort create`, `aeh ingest` and `aeh results export` — terminal steps,
each recorded as a defect against the terminal-closed criterion rather than worked around.
Execute the script as written and record the defects; that is the honest reading of
NFR-SYS-17 today.

## Who takes part

- **Operator.** A non-technical adult who is comfortable with a web browser and can follow a
  recipe, but has never used a terminal or a code editor: a teacher from another subject, an
  office administrator, or the pilot's own operator. They sign off.
- **Observer.** Someone who can read the checklist and keep time, and who writes down, for every
  step, whether the operator needed the terminal — before they are asked. The observer is not
  the operator.
- **Teacher.** The pilot's teacher, for the roster-against-roster review (step 10). They confirm
  every exported name is the right child's work.

## Data

- **The deployment tutorial**, `docs/tutorials/deployment-tutorial.md`, and the operating
  tutorial it points to, `docs/tutorials/operating-tutorial.md`, as committed in this build.
- **The shipped sample materials**, `docs/live-tests/sample-materials/`: the sample package and
  the synthetic sample answer sheets. Substitute nothing: the walkthrough proves the shipped
  path, not a hand-prepared one.
- **The reference machine** the browser cases measure on (E6's box): the machine, profile and
  build are recorded in the sign-off table so the sign-off names what actually walked.

## Preconditions

- The release build on the reference machine; nothing has been started on it yet.
- Every case under *Automated coverage* passes on this build — including `TC-E2E-06`, the same
  journey checked by machine.

  **Current precondition status:** not met. `TC-E2E-06` currently fails its written-ahead phrase
  gate because the bundle lacks "check that the console service is running"
  (`tests/browser/spa/test_tc_e2e_06_teachers_day.py:120`). This does not count as a UAT pass;
  do not weaken or alter the gate as part of this walkthrough.
- The operator can access the OpenRouter API key through the school's approved secret-handling
  method and can enter it directly into the terminal environment before the terminal is closed
  (§7.2 of the tutorial). Do not put the key in a sticky note, personal notes, a file or a chat;
  the system reads it only from the environment variable.
- The observer has a printed copy of this script and the record table below.

## Procedure

1. **Install.** Follow the tutorial's install section exactly: create the environment, then
   `pip install .` (one manual install step — the last line the tutorial asks the terminal for).
   The observer notes every line the tutorial asks for that a non-technical reader could not
   have typed from the page alone.
2. **Close the terminal.** The operator closes the terminal window on the observer's count, and
   it stays closed for the rest of the walkthrough. From here, anything the operator needs a
   terminal for is a defect against this plan, not a user error.
3. **Configure.** The profile and the API key were entered before the terminal closed
   (Preconditions: §7.2 of the tutorial's configuration section — the one terminal step the
   tutorial asks for, recorded as such). From here the operator configures nothing else by
   hand: any file, environment variable or command the rest of the walkthrough would have
   them open or type is recorded, and any step a page cannot complete is marked a defect.
4. **Start the console.** The operator opens the console page the tutorial names and reaches
   the hub in the browser. The console has no shipped desktop launcher: starting it requires a
   terminal command, so record that as a defect against the terminal-closed criterion. The address
   bar shows the loopback URL printed at startup, `http://127.0.0.1:<port>/`; nothing outside
   the machine is contacted.
5. **Set up.** The teacher opens `/#/package/author`, uploads the test, model answer and rubric
   documents, checks the document reading, starts a draft, answers the draft's open questions,
   edits anything else needed, and approves the package. The observer records anywhere the screen
   showed a number to type, a file to name, or a message that only a programmer could act on.
   *(Shipped build: this documents-to-draft-to-approval route is the SPA's package authoring
   flow. Do not expect the old S3/S4 read-back pages to be part of it; a prebuilt setup draft
   can also be published from `/#/package` when its gates are clear.)*
6. **Set up the class.** On the roster editor the operator pastes the class list — names
   only, no IDs — and sets the consent class. The editor refuses a row with an empty name and
   says so in plain words; the observer records how the refusal read.
   *(Shipped build: no roster-editor surface exists on any screen yet — class creation and
   roster loading are `aeh cohort create --roster`, a terminal step. Record the step as a
   defect against the terminal-closed criterion, and record the refusal wording the CLI
   prints for an empty name.)*
7. **Load papers.** The operator loads the scanned answer sheets on the papers screen and
   sees each sheet matched to a student by the rostered full name on its `Student:` line; a
   student ID is optional. The observer records any sheet that needed a terminal, a filename
   trick, or a manual ID assignment.
   *(Shipped build: the SPA's papers file inputs are not wired and the upload API only stores
   files — reading scans is `aeh ingest`, a terminal step. Record it as a defect.)*
8. **Run.** On the run-start screen the operator reads the banner (profile, panel builds,
   engine) and the estimate, then confirms. The confirmation is a dialog that names what it does.
   **Monitor.** The operator watches the monitor screen (the existing run monitor's
   data through the API) to the end of the run; a paused run
   must show a plain-words reason and a next step. The observer records any moment the run's
   state was not readable from the page.
9. **Review.** The teacher opens `/#/review` to read the flagged-item and provisional-grade
   summary, then opens students from `/#/results` to read their feedback or amend a grade. The
   teacher may open the blind sample at `/#/review/blind`; that screen currently offers
   generic B1–B5 labels rather than the package's own band names, so a valid in-console
   blind scoring is not possible for custom-band packages — record it as blocked,
   then finalizes on `/#/results`; amending a final grade requires a reason. No numeric score
   entry appears anywhere. *(Shipped build: the SPA Review screen is a summary/list, not an action
   queue; it has no inline accept/edit or group-decision control.)*
10. **Review the roster against the export (RISK-110).** Before anything leaves the machine, the
    roster-against-roster review: the teacher reads the roster the class screen shows against the
    names on the per-student exports, child by child: the work the system graded for a name is
    that child's paper. This
    is the pilot's first name-based cohort, and this step is the compensation the plan carries
    for a grade landing on the wrong child's record — one swapped name is a fail, not a footnote.
11. **Export.** The operator exports the results (the marks CSV and the per-student PDFs) and
    reads one PDF back to confirm it opens. *(Shipped build: the SPA has no download
    control — the export is `aeh results export` or the console's exporter API reads.
    Record which route was used; if it was the CLI, record it as a defect
    against the terminal-closed criterion.)*
12. **Ask for help.** The operator opens the help screen, asks one question in their own words
    (for example, "how do I send the grades home?"), and reads the answer. The observer records
    whether the answer helped and cited where it came from — and whether anything it asked the
    operator to do needed the terminal.
13. **Close the console.** The operator stops the console the way the tutorial says and closes
    the browser. *(Shipped build: the console is a terminal process stopped with Ctrl-C —
    stopping it needs the terminal again. Record it as a defect against the terminal-closed
    criterion.)* The observer confirms the day's data sits in the one data folder the tutorial
    named.

## Observations to record

- For each procedure step — install, configure, package setup, class setup, papers, run,
  monitor, review, export and help — whether it completed with the terminal closed. Any step
  where it would not have is a defect against this plan; record exactly what the screen asked
  for at that moment.
- Every place a TOML file, an environment variable, an ID column or a command line appeared in
  the operator's path, whether or not the step could be completed another way.
- The words the system used at each blocking gate and each refusal, and whether a non-technical
  reader could act on them.
- The help question asked, the answer given, and the observer's judgement of whether it would
  have resolved the question without a terminal.
- Anything the walkthrough would have needed that was not on any screen: record it even if the
  operator found a way around it.
- Whether the operator was, in fact, non-technical (they say so in their own words at sign-off).

## Sign-off

Sign-off criterion: *Every step of install, configure, set-up, run, monitor, review, export and
help completes without a terminal; every place the walkthrough would have needed one is a defect
against this plan* — signed as a checklist: each step above gets a pass, a fail, or a defect
note.

| Record | Entry |
|---|---|
| Executed by |  |
| Observer |  |
| Date |  |
| Build |  |
| Profile |  |
| Machine (the reference box) |  |
| Steps completed without the terminal |  |
| Defects named (step and what was asked) |  |
| Roster-against-roster check done (step 10) |  |
| Verdict |  |
| Operator's own words |  |

A pass needs every step above completed with the terminal closed, the roster-against-roster
check done and clear, and zero defects named. One terminal-requiring step is a fail of the
criterion — it is exactly the thing this walkthrough exists to catch, so record it rather than
working around it.

## Automated coverage

These cases check the machine-checkable half; run them first.

- `TC-E2E-06`: the same journey driven twice — once entirely through the SPA in a browser, once
  through the CLI's leaves — writes identical stores (the differential). It proves every step
  the walkthrough walks exists and works with no terminal; what it cannot prove is that a
  non-technical operator can find and follow them, which is the judgement this script exists to
  record.
