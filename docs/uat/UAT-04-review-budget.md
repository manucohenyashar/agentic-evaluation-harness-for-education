# UAT-04 — My 30 minutes are spent on the items that matter

| Field | Value |
|---|---|
| UAT ID | UAT-04 |
| Req | FR-REVIEW-01, FR-REVIEW-04 |
| Business goal | My 30 minutes are spent on the items that matter |
| Role | Teacher |
| Scenario | **Given** 790 flagged items and a 30-minute budget, **when** the queue is built, **then** the teacher works top-down and the header tells them honestly what they did not see |
| Data | A completed run |
| Sign-off criterion | The teacher rates the shown items as worth reviewing, and reports the residual message as informative rather than alarming (HLD §11.9 question 4) |

## Who takes part

- **Teacher.** The class's own teacher, who knows the students' work. They sign off.
- **Observer.** Keeps time, writes down the teacher's rating of each item, and records what they say
  about the header. The observer does not explain the header: if it needs explaining, that is a
  result.

## Data

- **A completed run.** Use the run from UAT-01 over `F-HAND` if it exists, otherwise any completed
  run of the teacher's own class under Tier C handling rules. The run must have finished scoring and
  must not have been reviewed yet.
- **About 790 flagged items.** Note the actual flagged count before the session; the scenario's 790
  is the design's reference size (test plan §6.2). A run with far fewer, say under 200, cannot test
  whether a 30-minute budget chooses well, so record it as not executable rather than running it.
  Not executable is not a pass.
- **A rating sheet**: one line per item shown, with "worth reviewing / not worth reviewing" and a
  short reason.

## Preconditions

- The release build on the school's machine, `edge-local` profile.
- Every case under *Automated coverage* passes on this build.
- The teacher has thirty uninterrupted minutes. Interruptions distort both the rating and the
  budget.

## Procedure

1. **Given** the completed run and about 790 flagged items, the teacher opens the review queue (S9)
   for the run and states a budget of 30 minutes.
2. **When** the queue is built, the observer photographs or copies the header exactly as shown,
   before the teacher reads it aloud. It should state how many items were flagged, how many are
   shown, how many are left provisional, and the minutes set aside for the blind sample, taken off
   the 30 before anything was ranked.
3. The teacher reads the header aloud and says, in their own words, what it tells them. The observer
   writes it down verbatim and does not correct it.
4. **Then** the teacher works top-down: accepting, editing, or applying a group action, in the order
   shown, until the budget runs out or the queue ends. They do not skip ahead or search.
5. For every item they handle, the teacher says "worth reviewing" or "not worth reviewing" and why.
   The observer ticks the rating sheet.
6. When the budget is spent, the teacher rereads the header: the items they did not see, now left
   provisional. They answer the pilot question: *does this message build trust, or does it alarm
   you?* The observer records the answer in the teacher's words.
7. The teacher says whether they would have wanted to see any item they did not, and if so what
   kind: a criterion, a student, a risk level.

## Observations to record

- The header's exact text at the start and at the end.
- Items shown, items handled, and items rated worth reviewing, with the share that were worth it.
- Group actions used, and how many items each one covered (HLD §11.9 question 2).
- Minutes actually used against the 30 stated.
- The teacher's answer to HLD §11.9 question 4 (residual message: trust or alarm), verbatim.
- Whether the teacher asked for "show me everything above this risk level" instead of a minute
  budget (HLD §11.9 question 1).

## Sign-off

Sign-off criterion: *The teacher rates the shown items as worth reviewing, and reports the residual
message as informative rather than alarming (HLD §11.9 question 4)*.

| Record | Entry |
|---|---|
| Executed by |  |
| Observer |  |
| Date |  |
| Build |  |
| Profile |  |
| Verdict |  |
| Teacher's own words |  |
| HLD §11.9 question 4 answer |  |

The first half passes when the teacher rates most of the items they handled as worth reviewing,
with the share recorded. The second half passes when they call the residual message informative.
If the teacher finds the residual message alarming, the verdict is fail, and the recorded answer is
still the pilot's evidence. It is the input to version 2's queue header, so it must not be
softened into a pass.

## Automated coverage

These cases check the machine-checkable half; run them first.

- `TC-REVIEW-01`: the queue is sized by the stated minute budget, never a fixed percentage or a bare
  threshold.
- `TC-REVIEW-02`: items are ranked by expected value.
- `TC-CONSOLE-13`: the header states items flagged, shown and left provisional.
- `TC-REVIEW-23`: minutes used, items shown against flagged, and group-action share are recorded.

No case can check whether the items at the top are the ones a teacher thinks matter, or how the
header reads to the person it is written for.
