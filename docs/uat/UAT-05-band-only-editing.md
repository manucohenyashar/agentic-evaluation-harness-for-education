# UAT-05 — Editing a band rather than a number is workable

| Field | Value |
|---|---|
| UAT ID | UAT-05 |
| Req | FR-REVIEW-10, FR-CONSOLE-07 |
| Business goal | Editing a band rather than a number is workable |
| Role | Teacher |
| Scenario | **Given** a score the teacher disagrees with, **when** they change it, **then** they select a band with its descriptor and never type a number |
| Data | A run with disagreements |
| Sign-off criterion | The teacher can complete every correction they wanted to make; they report band-only editing as a relief or a constraint, recorded either way (HLD §11.9 question 3) |

## Who takes part

- **Teacher.** The class's own teacher. They sign off.
- **Observer.** Writes down each correction the teacher wants to make *before* they try it, then
  whether they managed it. The observer does not suggest a band.

## Data

- **A run with disagreements.** A completed run of the teacher's own class (`F-HAND`, Tier C
  handling), where a first pass through the queue or the rollup has turned up at least five scores
  the teacher disagrees with. The UAT-04 session usually produces them; note which items they are.
- **A correction list**, filled in by the teacher before the session: for each disagreement, what
  they think the score should be, in whatever form they naturally think of it (a mark, a band, a
  phrase).

## Preconditions

- The release build on the school's machine, `edge-local` profile.
- Every case under *Automated coverage* passes on this build.
- The teacher has not been told in advance that there is no number field. Whether they expect one is
  part of the result.

## Procedure

1. **Given** a score the teacher disagrees with, the teacher opens it from wherever they found it:
   the review queue (S9), the rollup (S12), or a student view (S13).
2. The teacher reads out the correction they want, from their list, before touching the control. The
   observer writes down whether it is phrased as a number or as a band.
3. **When** they change it, the teacher uses whatever control the screen offers.
4. **Then** the observer confirms the control is a choice of bands, each shown with its descriptor,
   and that the teacher never types a number. If the teacher looks for a number field, record how
   long they looked and what they said.
5. The teacher checks the saved grade: the band they chose, and the points that follow from it.
6. Repeat for every item on the correction list.
7. The teacher answers the pilot question: *was choosing a band instead of typing a number a relief
   or a constraint?* Record the answer in their words, whichever way it goes.

## Observations to record

- For each correction: wanted as a number or a band, completed or not, and if not, why not.
- Every correction the teacher wanted and could not express as a band. Each one is the exact case
  where band-only editing is a constraint.
- Time spent looking for a number field, if any.
- The teacher's answer to HLD §11.9 question 3 (band-only editing: relief or constraint), verbatim.

## Sign-off

Sign-off criterion: *The teacher can complete every correction they wanted to make; they report
band-only editing as a relief or a constraint, recorded either way (HLD §11.9 question 3)*.

| Record | Entry |
|---|---|
| Executed by |  |
| Observer |  |
| Date |  |
| Build |  |
| Profile |  |
| Verdict |  |
| Teacher's own words |  |
| HLD §11.9 question 3 answer |  |

The verdict depends only on the first half of the criterion: every correction completed. "A
constraint" is a recorded answer, not a failure. A correction the teacher could not express as any
band is a failure, and the record names it.

## Automated coverage

These cases check the machine-checkable half; run them first.

- `TC-REVIEW-10`: no interface accepts a numeric score, and points are derived from the chosen band.
- `TC-CONSOLE-07`: no numeric score entry field exists anywhere in the rendered console.
- `TC-CONSOLE-20`: every view that shows a band shows it as an editable band control.

No case can check whether a teacher's actual corrections fit the bands, or how the control feels to
use.
