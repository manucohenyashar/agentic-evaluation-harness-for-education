# UAT-01 — Grades arrive without me doing anything overnight

| Field | Value |
|---|---|
| UAT ID | UAT-01 |
| Req | NFR-SYS-04, FR-GRADE-01 |
| Business goal | Grades arrive without me doing anything overnight |
| Role | Teacher |
| Scenario | **Given** a set-up package and 350 scanned submissions, **when** the operator starts a run in the evening and nobody touches the system, **then** in the morning every submission that passed ingestion has a complete, exportable grade with feedback |
| Data | 350 real-medium scans |
| Sign-off criterion | The teacher confirms a full set of grades exists and can be exported to the school's format, with no action having been taken |

## Who takes part

- **Teacher.** The person whose class the scans come from. They sign off.
- **Operator.** Starts the run in the evening and leaves. In a small school this may be the teacher;
  if so, record it, because HLD §11.9 question 5 asks whether that split holds.
- **Observer.** Writes down every time anyone touches the machine between starting the run and the
  next morning.

## Data

- **350 real-medium scans.** 350 submissions from `F-HAND` (consented real scanned handwriting, test
  plan §4.4), including at least one mixed-format paper, kept under Tier C handling rules.
- **A set-up package** for the same assessment, published, with setup finished beforehand. Setup
  time is UAT-02's concern, not this one's.
- **The school's grade import format.** Ask the teacher which one before the day, and have a blank
  copy to compare against.

## Preconditions

- The release build is installed on the school's machine, running the `edge-local` profile.
- Every case under *Automated coverage* passes on this build.
- The machine's sleep and update settings are how the school leaves them overnight. Do not change
  them for the test: a machine that sleeps at 22:00 is part of the scenario.

## Procedure

1. **Given** the published package and the 350 scans, the operator opens the console on the
   Packages screen (S1) and confirms the package is the published version. From the cohort's
   pre-flight screen (S6), they start the run in the evening, after school.
2. The operator checks that the run monitor (S7) shows the run as running, then leaves. The observer
   writes down the time.
3. **When** nobody touches the system overnight, the observer records any interaction at all: a key
   press, a dismissed dialog, a restart, anyone waking the machine. Any interaction voids the run
   for sign-off. Record it anyway, because it shows where the promise broke.
4. The next morning, before anything else is touched, the teacher opens the run's rollup (S12).
5. **Then** the teacher compares the grade lines with the submissions that passed ingestion. The
   cohort's pre-flight screen (S6) shows how many submissions were quarantined; those are the
   operator's work, not missing grades.
   Every other submission must have a grade.
6. The teacher opens three student views (S13) of their own choosing. Each must show a complete
   grade with written feedback, not a blank or a placeholder.
7. The teacher exports the grades (the CSV, plus the per-student PDFs if the school uses them),
   opens the export in the school's format, and judges whether it would import as it is.

## Observations to record

- The time the run started, the time the monitor says it finished, and the time the teacher first
  looked.
- Every interaction between the start and the morning. The expected answer is *none*.
- Submissions ingested, submissions quarantined, and grade lines on the rollup. Grade lines should
  equal ingested minus quarantined.
- Any grade that reads as incomplete, and which one.
- Whether the export needed editing before the school could use it, and what the edit was.
- Whether the teacher read the rollup's rubric findings that morning, or put them off (HLD §11.9
  question 6).

## Sign-off

Sign-off criterion: *The teacher confirms a full set of grades exists and can be exported to the
school's format, with no action having been taken*.

| Record | Entry |
|---|---|
| Executed by |  |
| Observer |  |
| Date |  |
| Build |  |
| Profile |  |
| Verdict |  |
| Teacher's own words |  |

A pass needs all three: a full set of grades, an export the school can use, and zero interactions.
If any one is missing, the verdict is fail and the record says which.

## Automated coverage

These cases check the machine-checkable half; run them first.

- `TC-E2E-02`: the overnight run completes and finalizes with zero teacher action.
- `TC-GRADE-01`: every submission in a 350-submission run gets a grade row with no per-student
  action.
- `TC-GRADE-24`: grades by state, coverage distribution and finalization path are emitted, so an
  incomplete overnight run is visible in the morning.
- `TC-GRADE-09`: the class finalizes in one batch action, with no per-student action (traced with
  this script to `R56`).
- `TC-SMOKE-10`: the smoke run produces a grade for every submission.

No case can check that a teacher, the next morning, accepts the result as a set of grades they would
use. That is what this script is for.
