# The first live teacher test: plan, checklists, and the record sheet

*For the person running the day, and for the teacher taking part. Read [02](02-live-readiness-and-blockers.md) first.*

The plan has three stages. **Stage 0 is a local rehearsal. Stage 1 checks that the supervised test is safe and ready. Stage 2 is the test day itself.** The console now supports the whole teacher day: class setup, package authoring, reading the papers, run controls, review, blind sampling, finalization, amendment and the results downloads ([05](05-console-teacher-walk.md) walks it screen by screen). The operator still starts the console from a terminal with the key and settings, and that is the one terminal step. These are known limits, not claims that the test has passed.

| Stage | When | Needs engineering work? |
|---|---|---|
| 0. Rehearsal | Before the live run | No, after the practice folder is built |
| 1. Readiness gate | Before the test is scheduled | Yes: privacy approval, live configuration, budget guard, known workflow gaps and sample checks |
| 2. Test day | When Stage 1 is passed | Operator starts the console; teacher and operator work in the SPA ([05](05-console-teacher-walk.md)) |

The browser intake path (B4) and the recorded parked-paper decision (B8) shipped on 2026-10-18 and have been checked offline only, so a first live use of either is a finding to record, not a claim.

---

## What the test is for

Not to prove the system is accurate. One class of ten made-up sheets cannot do that. The test answers four narrower questions, in this order:

1. **Can it be run?** A non-engineer can start it, watch it, and finish it, using only these documents.
2. **Does it fail safely?** The three awkward sheets are parked for the right reasons, nothing is guessed, and nothing leaves the machine that should not.
3. **Is the deterministic part exact?** Multiple-choice marks match the key to the mark.
4. **Does the judged part look sensible to a teacher?** Written-answer bands are close to what the teacher would give, and the feedback is useful. This is a *first look*, not a measurement.

## Stage 0: Rehearsal (do this now, about 45 minutes)

Purpose: the operator and teacher learn the screens with nothing at stake.

- [ ] Machine set up per [01](01-hosting-and-configuration.md), sections 3 to 5. `aeh --help` works.
- [ ] `python docs/live-tests/sample-materials/check_config.py docs/live-tests/config/live-test.dev-ci.toml` prints `ACCEPTED`.
- [ ] `python docs/live-tests/sample-materials/verify_sample_materials.py` ends with `OK: every sample sheet behaved at intake as the live-test guide says it will.`
- [ ] An engineer has built the practice folder (`build_rehearsal_data.py`, see the [tutorial](../tutorials/operating-tutorial.md), section 2).
- [ ] The operator has done the **ten-minute rehearsal** (tutorial section 10) once without help.
- [ ] The teacher has opened `/#/review`, `/#/results` and a student result on the practice data, and can explain provisional vs final grades. S9/S12/S13 are legacy operator/audit pages, not the SPA's teacher workflow.
- [ ] Both have practised: stop the console with Ctrl-C, start it again under the same profile, and see that pages and grades remain. If practical, exercise Pause/Resume on a practice run; record that a real live pause/resume cycle remains unverified.

**Stage 0 passed when** the operator can do all of the above from the tutorial alone.

## Stage 1: Readiness gate

All must be true. Each line is a checkable goal, listed in 02.

- [ ] A written privacy decision authorizes the selected synthetic or consented test materials for the OpenRouter account whose privacy settings govern data retention (the operator sets them; the system does not request zero retention); that account setting does not replace school approval.
- [ ] A real, throw-away call to OpenRouter succeeds for each configured model, and the exact model names are checked against the service.
- [ ] The teacher can make a class marked *made-up practice work* on the Classes screen (typed or from `config/eng7-roster.txt`) and sees its students listed.
- [ ] Parked-paper handling is understood: the SPA shows each reason, gives a nameless paper to its student, releases or closes the others, and records every decision with its note.
- [ ] Scans uploaded on the Papers inbox are read, and the intake statuses match the expected sample outcomes (`aeh ingest` reads the same way from a terminal).
- [ ] `aeh run` under `dev-ci` with a key really calls OpenRouter, and the printed summary names the provider. The 2026-10-12 run was not a clean pass: citation refusals left grades provisional, and Jev faulted before dispatch. The citation refusal's cause was fixed after that run (quote-anchored citations, #918); a fresh live pass has not been recorded.
- [ ] An OpenRouter spending limit is set and `HARNESS_COST_CEILING` is configured. The Jobs screen shows job cost so far; use OpenRouter's dashboard for the actual account spend.
- [ ] Both packages (`PS9-FORCES-01`, `ENG7-READ-01`) are published from `config/ps9-forces-01.package.toml` and `config/eng7-read-01.package.toml`, with keys C, B, C and B for Q1, Q2, Q3 and Q5a, and the English package carrying one line of each rubric method (C1 evidence checklist with items C1a/C1b, C2 bands, C3 the teacher's own words).
- [ ] A backup of an empty data folder exists, so "start again" is one copy.

**Stage 1 passed when** the privacy and spend safeguards are approved, the sample materials pass their current intake check, and the console path (class, papers, run) has been rehearsed. This gate does not certify grade accuracy, resolve the live citation/Jev findings, or mean a terminal-free teacher UAT has passed.

## Stage 2: Test day

### Who

| Seat | Person | Job |
|---|---|---|
| Teacher | one person | Uses the SPA to make the class and the test, review, blind-score, finalize/amend and download, and answers the questionnaire. Does **not** touch the terminal. |
| Operator | one person | Runs the console (the one terminal step), watches jobs, reads scans on **Load papers**, and handles parked papers. The teacher can make the class in the SPA too. |
| Engineer | one person, beside the operator | Helps with configuration or failure diagnosis; writes down every intervention and does not characterize the test as terminal-free. |
| Observer | optional | Writes down what the teacher says and does, in their words. |

### Rules for the day

1. **Only the synthetic sample sheets.** No real student paper goes in. `HARNESS_ALLOW_REMOTE_REAL_WORK` stays unset.
2. **The ceiling is a stop.** The Jobs screen shows each job's estimated cost so far; watch the *actual* spend on OpenRouter's dashboard (the console's number is an estimate against the ceiling, not the bill). If it reaches half the ceiling before the physics run finishes, pause and look. Do not raise the ceiling mid-run.
3. **Do not fix what you see.** Record it. A fix mid-test makes the result about the fix.
4. **If something is surprising, stop and write it down before touching anything.**
5. **No numbers typed anywhere.** Marks are bands. If the teacher asks "can I just type 7", the answer is no, and that question goes on the record sheet.

### Timeline

| When | What | Who | Tag |
|---|---|---|---|
| T-1 day | Machine checks (Stage 0 list). Confirm the key is in the terminal that will start the console. Fresh data folder. | Operator | |
| T-0, 09:00 | Operator runs `check_config.py` and confirms `ACCEPTED`, starts the console with the approved config and settings ([05, step 0](05-console-teacher-walk.md#step-0-start-the-console-operator-the-one-terminal-step)), and opens the printed SPA URL. The teacher makes the physics class on the Classes screen ([05, step 1](05-console-teacher-walk.md#step-1-the-class-teacher)). | Operator + teacher | |
| 09:15 | Teacher authors the package from the test, model answer and rubric in `/#/package/author`; reviews/edits the draft and approves it. Confirm the resulting published package version. For a prebuilt sample package, use the documented spec path instead. | Teacher + operator | |
| 09:30 | Read the test paper and the six physics sheets on `/#/papers` ([05, step 3](05-console-teacher-walk.md#step-3-reading-the-papers-teacher-or-operator)); watch the reading job's progress there or on `/#/jobs`. | Operator | |
| 09:50 | Confirm the expected three parked items — Dalia Haddad (S9-004), Elif Demir (S9-005), Farah Nasser (S9-006) — and their reasons on the SPA Parked screen. | Operator | |
| 10:00 | **Parked-paper drill** ([05, step 3](05-console-teacher-walk.md#the-physics-class-the-parking-drill)). Dalia Haddad (S9-004): write the tick you read in the note and release it; correct the mark on the student's result if needed. Elif Demir (S9-005): close it, noting which test it is, and upload it on the right class. Farah Nasser (S9-006): *This paper belongs to* → Farah Nasser → **Give it to this student**. Each decision is recorded with your note. | Operator | |
| 10:20 | **Start the run** from `/#/run` and confirm the priced preview. Watch `/#/monitor` or `/#/jobs`; note the start time and job cost shown. | Operator | |
| 10:25 | **Recovery drill (if the run can safely be interrupted).** To test interruption recovery, stop the console with Ctrl-C while a run is running, then restart under the same profile; confirm that interrupted run resumes without repeated or missing work. This does not test recovery of an intentional pause: queue Resume in Jobs before stopping, and recovery resumes that paused run only if the request is still unapplied. `aeh recover` also reclaims leases and settles completed runs' ungraded or non-final grades. Recovery does not start pending runs or override an operator pause. Record each pause/resume cycle separately. | Operator | |
| ~10:45 | Record the run status, end time, Jobs-screen cost and OpenRouter dashboard spend. Do not treat `complete` as proof every grade is final; inspect `grades_final` and any refusal details. | Operator | |
| 11:00 | **Teacher's sitting**, 20 minutes: use `/#/review`, open two students from `/#/results`, and record what the SPA showed. The observer writes. | Teacher | |
| 11:25 | **Blind sample** at `/#/review/blind`: score the drawn submission/criterion seats without seeing system bands; each seat offers that question's own levels from the package. Record the teacher's independent marks for comparison. | Teacher | |
| 11:40 | **Finalize** from `/#/results`, then amend one final grade with a reason, and download the marks spreadsheet, the CSV and one student's report from the **Download the results** panel ([05, step 6](05-console-teacher-walk.md#step-6-download-the-results-teacher)). | Teacher | |
| 11:55 | Repeat the quick path for the English test (steps from 09:30, no quarantine expected). | Operator | |
| 12:30 | Questionnaire (below). Backup the data folder. Do **not** purge yet. | All | |

Times are a plan, not a measure. Writing down the real times is part of the result.

## The record sheet

Copy this table and fill it in. One row per sheet. Leave a cell blank rather than guessing it.

**Run facts**

| Item | Value |
|---|---|
| Date, machine, who sat where | |
| Profile and config file used | |
| Models used (page reader, judges), as the run summary printed them | |
| Which provider actually answered (OpenRouter, or recordings)? Read it from the run, not the summary | |
| Start time, end time | |
| Jobs-screen cost (estimate) and the cost on OpenRouter's own dashboard | |
| Number of times the engineer had to step in, and why | |
| Pull-the-plug drill: time to resume, anything lost? | |

**Per sheet**

| Sheet | Intake status (expected in 03) | Matches expectation? | MCQ marks right? (expected in 03) | Written bands: system / teacher | Within one band? | Feedback helpful? (teacher, 1 line) | Notes |
|---|---|---|---|---|---|---|---|
| Aisha Bello (S9-001) | ok | | 4 of 4 | C4: / C6: | | | |
| Daniel Kim (S9-002) | ok | | 3 of 4 | C4: / C6: | | | |
| Mateo Rossi (S9-003) | ok | | 1 of 4 | C4: / C6: | | | |
| Dalia Haddad (S9-004) | parked, `incomplete` | | 3 of 4 + Q1 by operator | C4 (none) / C6: | | | |
| Elif Demir (S9-005) | parked, `unmatched_assessment` | | n/a | n/a | | | |
| Farah Nasser (S9-006) | parked, `incomplete` | | 4 of 4 after the paper is given to Farah Nasser on Parked; otherwise unscored | C4: / C6: | | | |
| Ines Moreau (E7-001) | ok | | n/a | C1a: C1b: (C1 = sum?) C2: C3: | | | |
| Jonas Berg (E7-002) | ok | | n/a | C1a: C1b: (C1 = sum?) C2: C3: | | | |
| Keiko Tanaka (E7-003) | ok | | n/a | C1a: C1b: (C1 = sum?) C2: C3: | | | |
| Luis Ortega (E7-004) | ok | | n/a | C1a: C1b: (C1 = sum?) C2: C3: | | | |

The English lines use the three scoring methods ([03, section 3](03-sample-tests-and-answer-sheets.md)): C1 is an evidence checklist whose mark is the sum of items C1a and C1b, C2 is a band line, C3 a line the teacher described in their own words. Read them with `show_criterion_marks.py` (03, section 7).

## How to judge the result

These thresholds are **suggestions to agree before the day**, not rules of the system. They are readiness checks, not statistical ones; the section after the table explains the chance-corrected figures and what this test can and cannot establish.

| Question | Pass | If not |
|---|---|---|
| 1. Can it be run? | The operator finished every step using only the documents; the engineer stepped in at most for items already listed as blockers | List each step that failed |
| 2. Fails safely? | Exactly the three expected sheets parked, each for the expected reason; nothing graded for them before the operator acted; **zero** non-synthetic data sent | Any extra parked sheet is a finding (see the right-test risk in 02); any wrong grade for a parked sheet is a **serious** finding |
| 3. Deterministic exact? | Every multiple-choice mark equals the key, and every English C1 equals C1a + C1b (`show_criterion_marks.py` ends `OK`). No exceptions. | Any difference is a defect |
| 3a. Every rubric method graded? | The English run graded C1a, C1b, C2 and C3 for every admitted sheet, and never sent C1 itself to a judge; C3 (the teacher's own words) got a band like any band line | A method with no grades, or a judged C1, is a defect |
| 4. Judged part sensible? | At least 7 of 10 written bands within one band of the teacher's, and no gap of three bands | A pattern (all too high, all in the middle) matters more than the count |
| Recovery | If a run was running when interrupted, after a same-profile restart it resumes with no repeated or missing work. An intentionally paused run resumes only if an unapplied Resume request was queued; a pending run must not start. | Record exactly what was missing or which state differed from expectation |
| Audit | The finalize and amend succeeded (the replies said `dispatched: true`). No page shows the name the teacher gave, so ask an engineer to read it from the data folder, or record it as a gap | |
| Cost | Within the ceiling, read from OpenRouter's dashboard | If the run stopped early on the ceiling, record how far it got |

Remember what the numbers cannot say: ten sheets and two tests cannot show accuracy, and typed pages say nothing about handwriting.

## Statistical evaluation: what the figures mean

The live test is a readiness test, not an accuracy measurement. Ten sheets, and the blind sample
drawn from them, cannot estimate how often the marking is right; a per-question figure needs at
least 30 blind answers before the system shows one. The run's job is to show that the machinery
works and that the marks are plausible, not to produce a headline agreement number.

### What the system computes

| Statistic | Where you meet it | What it compares |
|---|---|---|
| **Cohen's κ** (kappa) | The *How closely the marking matched yours* block on Results | Two markers — the teacher and the system — one answer at a time |
| **Quadratic weighted kappa (QWK)** | The test's detailed validation record, for ordered rubric lines | Two markers, with a one-level miss counting far less than a two-level miss |
| **Ordinal Krippendorff's α** (alpha) | **System status**, where several graders or Jev are compared | More than two markers, on ordered levels |

All three subtract the agreement chance alone would produce. None is a percentage and none is an
accuracy score: they say how closely the markers' levels matched, not whether the right level was
chosen. The screens show the figure to two decimals, always beside the number of answers it rests
on. The system also computes QWK for ordered lines and keeps it in the detailed validation
record; it is not a second number on the Results block.

`tools/live_validity_check.py` prints the administration and package records for the sample
classes; their validity figures carry chance-corrected κ and QWK where the data supports them.
It marks the blind sample from `sample-materials/intended_bands.py`, the sample author's
intended bands — **not a teacher's marks** — so its figures are evidence of consistency with the
author's intent, not of accuracy with teachers. `tools/live_local_check.py` prints a readable
per-line band-agreement block (exact/adjacent, κ and ordinal α) for a local model server; it is a
developer consistency check over the pairs it has, not the teacher-facing 30-answer headline.

### How to read a figure

- **1.00** — perfect agreement; **0.00** — no better than chance; **below 0** — agreed less often
  than chance would give.
- Rules of thumb, not pass marks: about 0.6–0.8 is substantial agreement, above 0.8 is
  near-perfect. The system sets no pass/fail on κ, never turns the figure into a grade, and never
  changes a mark because of it.
- A figure is meaningful only with its answer count. Below 30 the screen says *"too few"* and
  withholds the number; record that, do not interpret it.
- Simple checks and overall judgements are reported separately and never pooled. Figures are
  scoped to the test version, population and backend they were measured on; never compare figures
  across different versions or settings.

### What to do on the day

1. **Mark the blind sample and finish it** (or skip it, and record that no new evidence was
   collected). The counting starts only when you mark without seeing the system's marks.
2. **Record each question's figure or "too few", with its answer count.** These sample classes
   hold six physics sheets and four English sheets, so in a fresh data folder no question can
   reach 30 in this run; every figure will read *"too few"*. That is the honest state, not a
   failure.
3. **Read the differences before the number.** Open the differences by student and question and
   note whether they cluster on one question (usually rubric ambiguity or a missing example) or
   scatter (usually the reading or the evidence extracted from the paper).
4. **Do not revise the rubric during the test.** Record what you saw; change the rubric afterwards,
   with enough answers to see a pattern, then collect a fresh sample.
5. **Use the validity tool for a fuller read, not as a pass/fail gate.** Its figures against the
   author's intended bands are consistency evidence; its dataset is the sample set, not a
   teacher's class.
6. **Do not report a percentage, a single class's figure as the test's accuracy, or a figure
   computed below 30 answers as a result.** The one thing the figures support is a statement about
   how closely the markers' levels matched, with the answer count beside it.

### What to put on the record sheet

For each question, write the figure (or *"too few"*), its answer count, and the differences you
inspected. If you ran `tools/live_validity_check.py`, file its report with the record. The pass
criteria in the table above remain the readiness criteria; κ is evidence about consistency, not a
pass/fail gate for this test.

## Questions for the teacher (ask, don't lead)

Ask these in this order, and write the answers in their words.

1. Before you used it: what did you expect it to do?
2. Looking at the review page: what did you understand it was asking you to do?
3. Was there anything you wanted to do and could not find how?
4. Did the feedback it wrote for a student say something you would be willing to hand to that student? For which sheet, and which not?
5. Where did you disagree with it, and how did you find out?
6. What would you need to see before you let it grade your own class?
7. Is there anything on the screen that worried you?

## After the day

- [ ] Backup the data folder (copy it whole, console stopped).
- [ ] Export both packages (`aeh package export --data-dir <folder> --package-version <version> --spec out.toml`), so the test package is saved.
- [ ] File the record sheet and the observer's notes with the date.
- [ ] Turn each finding into a line for the issue backlog. This repository creates issues only through `/plan-to-issues`; hand it the list.
- [ ] **Do not purge the cohort until you are sure.** The system refuses a purge until the cohort's evidence is saved for validation, and a purge cannot be undone.
- [ ] Revoke or rotate the OpenRouter key if it was typed on a shared machine.

## If you have to stop

Pause the run — from the SPA's Jobs screen, or the `pause-resume` action with `state=paused` — then press Ctrl-C, and write down what you saw. By design nothing is lost: the work already done is stored, and the run continues when the console is started again under the same profile. Restarting under a different profile leaves the run paused, with the refusal recorded. A run from the command line that exits with **3** has not completed (paused, or stopped for another reason; read the status it printed), and **1** means an error.
