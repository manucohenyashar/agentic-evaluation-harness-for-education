# UAT-07 — A provisional grade is still a usable grade

| Field | Value |
|---|---|
| UAT ID | UAT-07 |
| Req | FR-GRADE-06, FR-GRADE-04 |
| Business goal | A provisional grade is still a usable grade |
| Role | Teacher |
| Scenario | **Given** grades with provisional inputs, **when** the teacher exports, **then** each grade is complete, marked provisional, and states its coverage |
| Data | A run with an exhausted review budget |
| Sign-off criterion | The teacher is willing to issue the provisional grades, or states specifically why not |

## Who takes part

- **Teacher.** The class's own teacher, who would actually issue these grades. They sign off.
- **Observer.** Records the teacher's decision and, if they would not issue, the specific reason.

## Data

- **A run with an exhausted review budget.** The run from UAT-04, after the teacher's 30 minutes are
  spent, with the unreviewed items left provisional. Otherwise use any completed run of the
  teacher's own class (`F-HAND`, Tier C handling) where the review budget ran out before the queue
  did. Note how many grades carry provisional inputs; there must be some.
- **The school's grade import format**, as in UAT-01.

## Preconditions

- The release build on the school's machine, `edge-local` profile.
- Every case under *Automated coverage* passes on this build.
- The class has been finalized, either by the teacher's action or by the review window lapsing, so
  the grades are the ones that would be issued.

## Procedure

1. **Given** grades with provisional inputs, the teacher opens the rollup (S12) and finds how many
   grades are marked provisional.
2. The teacher opens three provisional grades in the student view (S13): one they expect to be
   right, one close to a grade boundary, and one of their choosing.
3. For each, the teacher reads the coverage statement: how many criteria were scored automatically,
   reviewed, left provisional and missing, and whether the grade could cross a boundary.
4. **When** the teacher exports (the CSV, plus the per-student PDFs if the school uses them), they
   open the export.
5. **Then** the teacher checks every grade in the export has a value (none withheld or blank), that
   the provisional ones are marked provisional, and that each states its coverage.
6. The teacher answers: *would you issue these grades as they are?* If not, they say specifically
   what stops them: which grade, which criterion, which statement. "It doesn't feel right" is not
   specific; ask what would need to change.

## Observations to record

- The number of grades, and the number marked provisional.
- Any grade in the export that is blank, withheld, or not marked when it should be.
- Whether the coverage statement was understood without explanation, in the teacher's words.
- For boundary grades: whether "could cross" was read correctly.
- The decision to issue or not, and every specific reason given.

## Sign-off

Sign-off criterion: *The teacher is willing to issue the provisional grades, or states specifically
why not*.

| Record | Entry |
|---|---|
| Executed by |  |
| Observer |  |
| Date |  |
| Build |  |
| Profile |  |
| Verdict |  |
| Teacher's own words |  |
| Specific reasons not to issue |  |

The script passes when the teacher is willing to issue, or when they refuse and give a specific,
recorded reason. A refusal with a reason is evidence, not a failure. The script fails when the
teacher cannot say why they would not issue. A grade missing from the export, a provisional grade
not marked as provisional, or a grade that does not state its coverage is a defect against
`FR-GRADE-06` or `FR-GRADE-04`. File it, and do not ask the teacher to judge grades the build got
wrong.

## Automated coverage

These cases check the machine-checkable half; run them first.

- `TC-GRADE-08`: a grade with provisional inputs is issued, exportable and marked provisional, and
  nothing withholds it.
- `TC-GRADE-07`: no missing or unreviewed criterion is ever filled in with a substitute value.
- `TC-GRADE-05`: every grade's coverage counts add up and match a hand count.
- `OBS-09`: grades by state and the coverage distribution are reported.

No case can check whether a teacher will put their name to a provisional grade.
