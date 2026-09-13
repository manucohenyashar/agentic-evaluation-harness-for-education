# UAT-06 — Scanning problems are mine, marking decisions are the teacher's

| Field | Value |
|---|---|
| UAT ID | UAT-06 |
| Req | FR-INGEST-30, FR-CONSOLE-11 |
| Business goal | Scanning problems are mine, marking decisions are the teacher's |
| Role | Operator |
| Scenario | **Given** 9 quarantined submissions, **when** the operator opens quarantine, **then** they see only ingestion problems with the page image, and can resolve or close each as unresolvable |
| Data | A cohort with real scan failures |
| Sign-off criterion | The operator resolves every item without needing a marking judgement; no quarantine item ever appears in the teacher's queue |

## Who takes part

- **Operator.** The person who scans and uploads, ideally not a subject teacher, so any marking
  judgement they are asked for shows up clearly. They sign off.
- **Teacher.** Opens the review queue before and after quarantine is cleared, to check the second
  half of the criterion.
- **Observer.** Writes down, for each item, what the operator had to decide and whether it needed
  subject knowledge.

## Data

- **A cohort with real scan failures.** Real scans from `F-HAND` (Tier C handling), uploaded as they
  came off the school's scanner, where ingestion quarantined 9 submissions. Keep the failures real:
  a skewed page, a missing page, an unreadable name, a torn corner. Do not manufacture failures by
  editing files. If the cohort quarantines a different number, record the number and continue; the
  9 is the scenario's reference size.
- **A failure list**, drawn up before the session by someone other than the operator: what is
  actually wrong with each quarantined submission.

## Preconditions

- The release build on the school's machine, `edge-local` profile.
- Every case under *Automated coverage* passes on this build.
- The cohort has been ingested and the run has been scored, so the teacher's queue exists to check
  against.

## Procedure

1. **Given** 9 quarantined submissions, the operator opens the cohort's pre-flight screen (S6) and
   notes how many submissions it shows in quarantine. The run monitor (S7) counts quarantined
   *work units*, not submissions, so its number is not the one to compare.
2. **When** the operator opens quarantine (S8), the observer checks each item shows the page image,
   or the crop that failed, and names an ingestion problem: an unreadable page, a missing page, an
   identity it could not match, a mark it could not read.
3. Before anything is resolved, the teacher opens the review queue (S9) for the same run and looks
   for each of the 9 quarantined students' submissions. None of them may appear there. Checking now
   matters: a submission resolved later is re-scored and can then join the queue as an ordinary
   review item, which is correct and not a quarantine item.
4. **Then** for each item, the operator decides without help whether they can fix it (rescan,
   re-upload, match the right student) and either resolves it or closes it as unresolvable.
5. After each item, the observer asks: *did you need to know the subject, or how it should be
   marked, to decide that?* Record the answer.
6. Any item that asks the operator how many marks, which band, or whether an answer is right is a
   marking judgement. Record it exactly as shown.
7. When quarantine is empty, the teacher reopens the review queue. Any of the 9 that now appears
   must appear as an ordinary review item of a re-scored submission, never with its ingestion
   problem or its page-image triage.

## Observations to record

- The quarantined-submission count on pre-flight (S6), and the number of submissions on the
  quarantine screen. They must match.
- For each item: the problem shown, whether the page image was there, resolved or closed as
  unresolvable, and whether it needed a marking judgement.
- Whether any item on the failure list was missing from quarantine, or shown with a different
  problem.
- Any quarantine item the teacher found in the review queue. The expected answer is *none*.
- Whether the operator and the teacher were the same person (HLD §11.9 question 5).

## Sign-off

Sign-off criterion: *The operator resolves every item without needing a marking judgement; no
quarantine item ever appears in the teacher's queue*.

| Record | Entry |
|---|---|
| Executed by |  |
| Observer |  |
| Date |  |
| Build |  |
| Profile |  |
| Verdict |  |
| Operator's own words |  |

A pass needs every item resolved or closed with no marking judgement asked of the operator, and no
quarantine item in the teacher's queue. One marking question on the operator's screen is a fail.

## Automated coverage

These cases check the machine-checkable half; run them first.

- `TC-INGEST-30`: all nine quarantined submissions reach the operator surface and zero reach the
  teacher's review queue, checked against the queue itself.
- `TC-CONSOLE-11`: quarantine and review have separate routes and counts, and no quarantine item can
  be reached from the review queue.
- `TC-REVIEW-06`: quarantine, blind-sample and random-arm items are never rendered in the review
  queue.

"No quarantine item ever appears in the teacher's queue" is machine-checkable, and those cases
check it. The script repeats it on real scans because a real failure can take a shape the fixtures
did not. What no case can check is whether the operator's decisions actually needed a marking
judgement.
