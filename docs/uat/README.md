# User acceptance scripts

These are the procedures a teacher or an operator runs **at release**, against the release build,
on the machine the school will use. They are not run in CI. The pass or fail decision is a person's
judgement (test plan §4.3, *Human judgment*): no automated check can say whether a teacher finds a
review queue worth their thirty minutes.

Each script comes from one row of test plan §6.3 and repeats that row word for word in its
header. `tests/uat/acceptance/test_uat_scripts.py` fails if a script stops matching its row, drops
its sign-off criterion, or loses a required section. To change a scenario, change §6.3 first
(through `/create-test-plan`), then the script.

| Script | Role | Business goal |
|---|---|---|
| [UAT-01](UAT-01-overnight-grades.md) | Teacher | Grades arrive without me doing anything overnight |
| [UAT-04](UAT-04-review-budget.md) | Teacher | My 30 minutes are spent on the items that matter |
| [UAT-05](UAT-05-band-only-editing.md) | Teacher | Editing a band rather than a number is workable |
| [UAT-06](UAT-06-operator-quarantine.md) | Operator | Scanning problems are mine, marking decisions are the teacher's |
| [UAT-07](UAT-07-provisional-grades.md) | Teacher | A provisional grade is still a usable grade |
| [UAT-08](UAT-08-no-validation-data.md) | Teacher | The system tells me when it does not know |

`UAT-02` (setup time) and `UAT-03` (calibration time) are not in this folder. They have a
measurable ceiling, so their stories (TS-21, TS-45) implement them as timed suites under
`tests/uat/setup/` and `tests/uat/calib/`.

## How to run a script at release

1. **Copy, don't edit.** Copy the script into the release's records folder and fill in the copy.
   The files here stay blank templates, and the test fails if a sign-off record in this folder is
   filled in.
2. **Use the named data, not something close to it.** Five scripts (UAT-01, 04, 05, 06 and 07) need `F-HAND`:
   consented real student work, kept under Tier C handling rules (test plan §4.4), never committed
   and never sent to a remote provider. If `F-HAND` consent is not on file, those scripts cannot run. Record that
   as the outcome rather than substituting `F-SYNTH`. A synthetic cohort shows the pipeline works;
   it does not show that a teacher accepts it.
3. **The person in the Role column runs it.** An observer takes notes and does not help. Prompting
   the teacher ("try the button at the top") makes the result worthless, because whether they find
   it unaided is part of what is being tested.
4. **Record the answer whichever way it goes.** UAT-04 and UAT-05 each answer one of the HLD §11.9
   pilot questions. A teacher who says band-only editing is a constraint has not failed the script.
   That answer is the evidence version 2 is built from, so write it down in their words.
5. **Automated coverage runs first.** Each script lists the automated cases that check the
   machine-checkable half of its scenario. If one of them is red on the release build, stop: the
   teacher would be judging a known defect.
