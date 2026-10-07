# The first live teacher test: plan, checklists, and the record sheet

*For the person running the day, and for the teacher taking part. Read [02](02-live-readiness-and-blockers.md) first.*

The plan has three stages. **Stage 0 you can do today. Stage 1 is the gate: the live test does not start until it is passed. Stage 2 is the test day itself.**

| Stage | When | Needs engineering work? |
|---|---|---|
| 0. Rehearsal | Now | No |
| 1. Readiness gate | Before the test is scheduled | Yes: blockers B1 to B4, B6 and B8 |
| 2. Test day | When Stage 1 is passed | Only for the engineer's seat beside you |

Tags like **[B4]** mean "this step needs blocker B4 closed". Steps without a tag work today.

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
- [ ] The operator has done the **ten-minute rehearsal** (tutorial section 8) once without help.
- [ ] The teacher has read pages S9, S12 and S13 on the practice data and can say, in their own words, what *Flagged / Shown / Left provisional* mean.
- [ ] Both have practised: stop the console with Ctrl-C, start it again, and see that the pages and grades are still there. (Pausing and resuming a *live* run has not been tried; see the tutorial, Phase 3.)

**Stage 0 passed when** the operator can do all of the above from the tutorial alone.

## Stage 1: Readiness gate

All must be true. Each line is a checkable goal, listed in 02.

- [ ] **[B1/B6]** A written decision on how zero-retention is confirmed for OpenRouter, signed by whoever owns student-data privacy.
- [ ] **[B2]** One real, throw-away call to OpenRouter was accepted (or the provider was changed until it was). The two model names are confirmed at openrouter.ai/models.
- [ ] **[B3]** A cohort can be created, marked `synthetic`, and given a roster, with the change recorded.
- [ ] **[B8]** Resolving a parked paper records the operator's decision (which student, which mark, which test). Until then the quarantine drill can only release or close a paper.
- [ ] **[B4]** Uploading `S9-001-strong.pdf` leads, with no engineer typing, to a read paper that appears in the preflight page.
- [ ] **[B1]** `aeh run` under `dev-ci` with a key really calls OpenRouter, and the printed summary says which provider ran.
- [ ] An OpenRouter spending limit is set. `HARNESS_COST_CEILING` is set to a number you are comfortable losing. (No console page shows the run's spend, so OpenRouter's dashboard is where you watch it, or an engineer reads it from the data folder.)
- [ ] Both packages (`PS9-FORCES-01`, `ENG7-READ-01`) are published, with keys C, B, C and B for Q1, Q2, Q3 and Q5a.
- [ ] A backup of an empty data folder exists, so "start again" is one copy.

**Stage 1 passed when** an engineer, **without help from the people who built the system**, takes the sample files to a finished run and a screen the teacher can read. Until then, do not schedule the test.

## Stage 2: Test day

### Who

| Seat | Person | Job |
|---|---|---|
| Teacher | one person | Reviews, finalizes, answers the questionnaire. Does **not** touch the terminal. |
| Operator | one person | Runs the console, uploads, watches, sorts quarantine. |
| Engineer | one person, beside the operator | Does nothing unless something stops. Writes down every time they had to step in. |
| Observer | optional | Writes down what the teacher says and does, in their words. |

### Rules for the day

1. **Only the synthetic sample sheets.** No real student paper goes in. `HARNESS_ALLOW_REMOTE_REAL_WORK` stays unset.
2. **The ceiling is a stop.** Watch the spend on OpenRouter's dashboard (the console does not show it). If it reaches half the ceiling before the physics run finishes, pause and look. Do not raise the ceiling mid-run.
3. **Do not fix what you see.** Record it. A fix mid-test makes the result about the fix.
4. **If something is surprising, stop and write it down before touching anything.**
5. **No numbers typed anywhere.** Marks are bands. If the teacher asks "can I just type 7", the answer is no, and that question goes on the record sheet.

### Timeline

| When | What | Who | Tag |
|---|---|---|---|
| T-1 day | Machine checks (Stage 0 list). Confirm the key is in the terminal that will start the console. Fresh data folder. | Operator | |
| T-0, 09:00 | Open the terminal. `check_config.py` says `ACCEPTED`. Start the console on a fixed port. Open `/packages`. | Operator | |
| 09:15 | Packages published. The engineer reads the question list and the answer keys out of the package to the teacher (or prints them), and the teacher says whether they match their paper. (The S3 and S4 pages do not show them today; B7.) | Teacher + engineer | B5 |
| 09:30 | Create the cohort and roster for physics. Upload the six physics sheets, one command each (tutorial §6, phase 2). Open S2 and confirm all six parts appear, in order. | Operator | B3, B4 |
| 09:50 | Open **S6 preflight**. Read it out loud. Open **S8 quarantine**. Expect exactly three items (S9-004, S9-005, S9-006). | Operator | B4 |
| 10:00 | **Quarantine drill.** Look at the three items on S8 (it lists each paper's ID and any crop, not the reason; the reasons are in the table in 03). Release S9-006 (`resolution=matched`) and close S9-005 as unresolvable. S9-004: look at the paper itself and decide Q1. **Today the command only releases or closes a paper; it cannot record which student, which tick or which test (B8).** Spell the word exactly: anything other than `matched` closes the paper as unresolvable. | Operator | B8 |
| 10:20 | **Start the run** (`start-run`). Open S7, press F5 every few minutes. Note the start time. | Operator | B1 |
| 10:25 | **Pull-the-plug drill.** Press Ctrl-C in the console's terminal. Start it again **with the same profile the run started under** (`HARNESS_PROFILE`, or the config file's own line). Confirm the run carries on and watch S7. Note how long it took to be back. (`aeh recover` alone only releases stuck work; it does not finish the run.) | Operator | |
| ~10:45 | Run status `complete` on S7. Note the end time and, from OpenRouter's dashboard, the cost. | Operator | |
| 11:00 | **Teacher's sitting**, 20 minutes, using only the tutorial's phase 4: read S9, act on at least three items, open S13 for two students. The observer writes. | Teacher | |
| 11:25 | *Blind sample: **not possible from the console today** (S11 lists no papers; B7). Instead, have the teacher mark the physics papers by hand from the printed sheets before seeing any system mark, and fill in the "teacher" column of the record sheet. This is the reference that the comparison uses.* | Teacher | |
| 11:40 | **Finalize** (S12). Then **amend** one band (use a real band name from the rubric PDF). Then **export** the package (S14). | Teacher | |
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
| Cost on OpenRouter's own dashboard (the console shows none) | |
| Number of times the engineer had to step in, and why | |
| Pull-the-plug drill: time to resume, anything lost? | |

**Per sheet**

| Sheet | Intake status (expected in 03) | Matches expectation? | MCQ marks right? (expected in 03) | Written bands: system / teacher | Within one band? | Feedback helpful? (teacher, 1 line) | Notes |
|---|---|---|---|---|---|---|---|
| S9-001 | ok | | 4 of 4 | C4: / C6: | | | |
| S9-002 | ok | | 3 of 4 | C4: / C6: | | | |
| S9-003 | ok | | 1 of 4 | C4: / C6: | | | |
| S9-004 | parked, `incomplete` | | 3 of 4 + Q1 by operator | C4 (none) / C6: | | | |
| S9-005 | parked, `unmatched_assessment` | | n/a | n/a | | | |
| S9-006 | parked, `incomplete` | | 4 of 4 once matched | C4: / C6: | | | |
| E7-001 | ok | | n/a | C1: C2: C3: C4: | | | |
| E7-002 | ok | | n/a | C1: C2: C3: C4: | | | |
| E7-003 | ok | | n/a | C1: C2: C3: C4: | | | |
| E7-004 | ok | | n/a | C1: C2: C3: C4: | | | |

## How to judge the result

These thresholds are **suggestions to agree before the day**, not rules of the system.

| Question | Pass | If not |
|---|---|---|
| 1. Can it be run? | The operator finished every step using only the documents; the engineer stepped in at most for items already listed as blockers | List each step that failed |
| 2. Fails safely? | Exactly the three expected sheets parked, each for the expected reason; nothing graded for them before the operator acted; **zero** non-synthetic data sent | Any extra parked sheet is a finding (see the right-test risk in 02); any wrong grade for a parked sheet is a **serious** finding |
| 3. Deterministic exact? | Every multiple-choice mark equals the key. No exceptions. | Any difference is a defect |
| 4. Judged part sensible? | At least 7 of 10 written bands within one band of the teacher's, and no gap of three bands | A pattern (all too high, all in the middle) matters more than the count |
| Recovery | After Ctrl-C and restart the run finished, with no repeated or missing work | Record exactly what was missing |
| Audit | The finalize and amend succeeded (the replies said `dispatched: true`). No page shows the name the teacher gave, so ask an engineer to read it from the data folder, or record it as a gap | |
| Cost | Within the ceiling, read from OpenRouter's dashboard | If the run stopped early on the ceiling, record how far it got |

Remember what the numbers cannot say: ten sheets and two tests cannot show accuracy, and typed pages say nothing about handwriting.

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
- [ ] Export both packages (`export-import-package`), so the tuned test is saved.
- [ ] File the record sheet and the observer's notes with the date.
- [ ] Turn each finding into a line for the issue backlog. This repository creates issues only through `/plan-to-issues`; hand it the list.
- [ ] **Do not purge the cohort until you are sure.** The system refuses a purge until the cohort's evidence is saved for validation, and a purge cannot be undone.
- [ ] Revoke or rotate the OpenRouter key if it was typed on a shared machine.

## If you have to stop

Pause the run (`pause-resume` with `state=paused`), press Ctrl-C, and write down what you saw. By design nothing is lost: the work already done is stored, and the run continues when the console is started again under the same profile. A run from the command line that exits with **3** has not completed (paused, or stopped for another reason; read the status it printed), and **1** means an error.
