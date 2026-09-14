# UAT-08 — The system tells me when it does not know

| Field | Value |
|---|---|
| UAT ID | UAT-08 |
| Req | FR-CONSOLE-24, FR-STATS-11 |
| Business goal | The system tells me when it does not know |
| Role | Teacher |
| Scenario | **Given** a package never administered to this population, **when** the teacher opens it, **then** they see "no validation data for this population" rather than a number |
| Data | An imported package |
| Sign-off criterion | The teacher correctly describes what the system does and does not know about this package |

## Who takes part

- **Teacher.** Ideally one who did not write the package, as a teacher adopting a colleague's or
  another school's assessment would be. They sign off.
- **Observer.** Records the teacher's description and compares it with the reference answer below.
  The observer does not prompt.

## Data

- **An imported package.** A package exported from another school or class and imported here, carrying a validation record for *its* population and no record for this one. Note
  the populations and figures in its validation record before the session. The imported figure is
  exactly what must not be shown as this population's.
- **The reference answer**, written by the person preparing the data before the session. It states
  what the system knows (the package's rubric, and that it has agreement evidence for population X,
  with n) and what it does not (anything about how it performs for this population, because it has
  never been used here).

## Preconditions

- The release build on the school's machine, `edge-local` profile.
- Every case under *Automated coverage* passes on this build.
- The package has never been administered to this population on this machine: no runs, no labels.

## Procedure

1. **Given** the imported package, the teacher opens the Packages screen (S1).
2. **When** the teacher opens the package, the observer checks what appears where a validation
   figure would be.
3. **Then** they should see "no validation data for this population" and no agreement number. If
   any number appears in that position, including the imported population's figure, record it
   exactly and where it appears.
4. The teacher reads the package's manifest, the page shown before import (HLD §9.9), which lists the
   validation record against the population it belongs to. If this build shows the imported record
   somewhere else, use that screen and record where it was.
5. Without help, the teacher describes in their own words what the system knows about how well this
   package grades, and what it does not know.
6. The teacher says whether they would trust the package's grades for their own class on the
   strength of what they were shown, and why.

## Observations to record

- The exact text shown in the validation position on S1. The expected text is *no validation data
  for this population*.
- Any number shown anywhere on S1 for this package, and what it was labelled.
- The teacher's description, verbatim.
- The observer's comparison with the reference answer: matches, overclaims (believes the package is
  validated here), or underclaims (believes nothing is known at all).

## Sign-off

Sign-off criterion: *The teacher correctly describes what the system does and does not know about
this package*.

| Record | Entry |
|---|---|
| Executed by |  |
| Observer |  |
| Date |  |
| Build |  |
| Profile |  |
| Verdict |  |
| Teacher's own words |  |
| Matches the reference answer |  |

The verdict is pass only if the description matches the reference answer. An overclaim, where the
teacher believes the package is validated for their class, is a fail even if the screen text was
correct: the text failed to inform.

## Automated coverage

These cases check the machine-checkable half; run them first.

- `TC-CONSOLE-26`: S1 renders "no validation data for this population" for a package never
  administered to the current population, never a borrowed figure.
- `TC-CONSOLE-24`: with no blind labels, the agreement block renders "no new validation evidence for
  this administration", never a prior figure.
- `TC-STATS-08`: an administration with no blind labels returns "no new validation evidence for this
  administration" as a value, and the package's agreement figures do not advance.
- `TC-STATS-26`: blind coverage per administration is emitted, and skipping the blind sample raises
  an alert.
- `TC-PKG-10`: a validation lookup returns a typed `NoValidationData`, never a substitute figure
  (traced with this script to `R23`).
- `TC-STATS-05`: a validation lookup whose population (or any other scope part) has no data returns
  `NoValidationData`, never a substitute figure, `None` or zero.

**A traceability note for the test plan's owner.** §6.3 traces this scenario to `FR-CONSOLE-24` and
`FR-STATS-11`, which govern the *administration*-scoped sentence ("no new validation evidence for
this administration"). The sentence the scenario quotes, "no validation data for this population", is
`FR-CONSOLE-26`'s, and the test plan's RTM traces `R23` to `TC-CONSOLE-26` and `UAT-08`. This script
keeps §6.3's Req column word for word, and lists `TC-CONSOLE-26` under automated coverage because it
checks the sentence the teacher is shown. Separately, §7.1's row for `FR-STATS-11` does not list
`UAT-08`, although §6.3 traces `UAT-08` to it. Both are `/create-test-plan` decisions.
