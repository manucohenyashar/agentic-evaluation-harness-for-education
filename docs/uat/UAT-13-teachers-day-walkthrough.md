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
- An OpenRouter API key in a sticky note or the operator's own notes — entering it is the one
  step the tutorial deliberately does ask the terminal for, and it happens BEFORE the terminal
  is closed (§7.2 of the tutorial: the system reads the key only from the environment variable;
  it is never written to a file the build ships).
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
4. **Start the console.** The operator opens the console page the tutorial names (double-click,
   or the one launcher the tutorial gives) and reaches the hub in the browser. The address bar
   shows `http://localhost:<port>`; nothing outside the machine is contacted.
5. **Set up.** The operator walks the package-setup screen: picks or builds the test's
   package, confirms the question inventory, keys the deterministic criteria, and reads back the
   rubric methods — one `general` criterion derived from bands and one `evidence_sum` composite
   must both appear in the read-back, since the sample package carries both methods. The
   observer records anywhere the screen showed a number to type, a file to name, or a message
   that only a programmer could act on.
6. **Set up the class.** On the roster editor the operator pastes the class list — names
   only, no IDs — and sets the consent class. The editor refuses a row with an empty name and
   says so in plain words; the observer records how the refusal read.
7. **Load papers.** The operator loads the scanned answer sheets on the papers screen and
   sees each sheet matched to a student by the name on its `Student:` line. The observer records
   any sheet that needed a terminal, a filename trick, or an ID to place.
8. **Run.** On the run-start screen the operator reads the banner (profile, panel builds,
   engine) and the estimate, then confirms. The confirmation is a dialog that names what it does.
   **Monitor.** The operator watches the monitor screen (the existing run monitor's
   data through the API) to the end of the run; a paused run
   must show a plain-words reason and a next step. The observer records any moment the run's
   state was not readable from the page.
9. **Review.** The operator opens the review queue (the existing queue's rules, FR-CONSOLE-16/19/20),
   works the flagged items in band-only
   controls, and finalizes the batch. No numeric score entry appears anywhere.
10. **Review the roster against the export (RISK-110).** Before anything leaves the machine, the
    roster-against-roster review: the teacher reads the roster the class screen shows against the
    names on the per-student exports, child by child: the work the system graded for a name is
    that child's paper. This
    is the pilot's first name-based cohort, and this step is the compensation the plan carries
    for a grade landing on the wrong child's record — one swapped name is a fail, not a footnote.
11. **Export.** The operator exports the results (the marks CSV and the per-student PDFs) and
    reads one PDF back to confirm it opens.
12. **Ask for help.** The operator opens the help screen, asks one question in their own words
    (for example, "how do I send the grades home?"), and reads the answer. The observer records
    whether the answer helped and cited where it came from — and whether anything it asked the
    operator to do needed the terminal.
13. **Close the console.** The operator stops the console the way the tutorial says and closes
    the browser. The observer confirms the day's data sits in the one data folder the tutorial
    named.

## Observations to record

- For each of the eight steps above — install, configure, set-up (package and class), papers,
  run, monitor, review, export, help — whether it completed with the terminal closed. Any step
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
