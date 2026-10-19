# Detailed Design Delta: Teacher Corrections — no teacher is ever stuck in the console

**Source:**
- The user's directive (2026-10-19): *"There should never be a situation where the teacher is
  stuck and needs help from a technical professional; all operations must be done inside the
  web UI. With adversarial thinking, find the scenarios that might not be normal but still
  require support. Think from the teacher's point of view."* — with the examples: the students
  of an existing class must be presented so the teacher can verify nobody is missing, and past
  test results must be reachable to answer questions about tests graded long ago.
- The user's follow-up (2026-10-19): *"When presenting a class you must show the students by
  name, not by student ids. The teacher knows the students by name."* — and: the ID may be
  appended after the name when two students share it, but the full name always comes first.
- `docs/design/console_redesign_design_delta.md` v1.13-delta (the "redesign delta"), on top of
  which this applies.

**Code baseline validated against:** `main` @ `8467e3a` (PR #803).
**Version:** 1.14-delta  **Date:** 2026-10-19  **Status:** Implemented on branch
`console-teacher-gaps`.

## Revision history

| Version | Date | Change | Author |
|---|---|---|---|
| 1.14-delta | 2026-10-19 | **Teacher corrections.** Five new control actions (FR-CONSOLE-64…68), two new reads (FR-CONSOLE-69's class check rides the class and papers reads; FR-CONSOLE-70's past tests is a new read), one intake rule (FR-INGEST-41), and the naming rule (FR-UI-22). No store migration. | User directive, implemented inline (precedent: PR #803's TC-CONSOLE-77…80) |

## 1. The stuck scenarios

Each row is a mistake a teacher (or whoever loads the papers) can make, or a question they will
be asked, that the console at `8467e3a` gave no way out of. "Stuck" means the only remedy was a
terminal, a database tool or an engineer.

| # | Scenario | What happened at `8467e3a` | Fix |
|---|---|---|---|
| S1 | A rescanned sheet (sharper, pages reordered) is uploaded | Intake skips only a byte-identical scan; the rescan was read as a **second paper**, matched the same student, and the run **graded the student twice** | FR-INGEST-41 |
| S2 | A student's name was typed wrong on the class list | Only adding students existed; the misspelt name stayed, and V3 could not match the paper | FR-CONSOLE-64 |
| S3 | A student was listed by mistake, twice, or has left | No removal; the student showed as "no paper yet" forever | FR-CONSOLE-65 |
| S4 | A paper was matched to the wrong student (similar names, a borrowed sheet) | B8's assignment moves only a *parked* paper | FR-CONSOLE-66 |
| S5 | The wrong file, another class's sheet, or the earlier of two scans was read in | No way to take a paper out; a re-upload was skipped as "already read" | FR-CONSOLE-67 |
| S6 | The wrong test paper was read for the class | "Already in for this class" — never replaceable; every sheet was checked against it | FR-CONSOLE-68 |
| S7 | "Is anyone missing?" | A per-row "no paper yet" with no count and no list | FR-CONSOLE-69 |
| S8 | "What did Dana get on the March test?" | The run switcher read *Grading run 1, 2, 3* — no class, test or date — and results named students by an opaque reference | FR-CONSOLE-70, FR-UI-22 |
| S9 | Delete a class that holds papers | The refusal said results must be "saved for validation", which no screen can do | FR-CONSOLE-69's deletability, FR-CONSOLE-67 |
| S10 | Students shown as references (`c7b-0003-…`) | The class, papers, results, parked, blind-sample and student screens led with the reference | FR-UI-22 |

## 2. Requirements

| ID | Requirement | Module |
|---|---|---|
| FR-CONSOLE-64 | The console shall correct a listed student's name in place (`rename student`), under the rule a new name meets. The student's reference does not change, so every paper already theirs stays theirs; papers read afterwards are matched against the corrected name. | M-CONSOLE → M-ORCH `rename_on_roster` |
| FR-CONSOLE-65 | The console shall take a student off a class list (`remove student`), refused while any paper in the class is theirs (it would be graded under nobody) and for a class's only student. | M-CONSOLE → M-ORCH `remove_from_roster` |
| FR-CONSOLE-66 | The console shall move a matched paper to the student it belongs to (`move paper to student`), under B8's rules: the student is on the list and has no other paper. A graded paper moves with its marks (grades are keyed on the paper). Every move is recorded in the decision trail with the student it came from. | M-CONSOLE → M-PIPE → M-INGEST `reassign_paper` |
| FR-CONSOLE-67 | The console shall remove a paper no grading run has touched (`remove paper`), with every row intake wrote for it, so the same or a better scan can be read again. A graded paper is refused, naming its run. | M-CONSOLE → M-STORE `discard_ungraded_paper` |
| FR-CONSOLE-68 | The console shall remove a class's test paper while no paper in the class is graded (`replace test paper`), optionally with every ungraded answer sheet so each is read again against the right test paper; the wrong-test breaker's count restarts. | M-CONSOLE → M-STORE `discard_test_paper` |
| FR-CONSOLE-69 | The class and papers reads shall state the check a teacher makes against their own list — how many students are listed, how many papers are read, and **by name** who has none — and the run-start screen shall name the students with no paper before a run starts. The class read states whether the class can be deleted outright and, if not, why, before the teacher asks. A paper filed under nobody, or parked as a second copy, is never listed as a student. | M-CONSOLE |
| FR-CONSOLE-70 | The console shall list every past grading run, newest first, with its class, test version, dates, state and each graded student's name, total and state (`GET /api/v1/past-tests`), filterable by class and findable by a student's name; each entry opens that run's results or the student's page. The run switcher names each run by class, test and date and offers the selected class's runs. | M-CONSOLE, M-UI |
| FR-INGEST-41 | Intake shall park a paper whose student already has a paper in the class (identity outcome `already_has_paper`, the parked flag set, the ladder's own diagnosis untouched), filed under that student, rather than read it in beside the first; M-ORCH's identity triage gives it no unit of any stage. The teacher keeps one of the two: remove the copy, or remove the earlier paper and give the copy to the student. A copy is never closed as unresolvable (that would grade it INCOMPLETE beside the real paper). | M-PIPE `ingest_files` → M-INGEST `park_second_paper` |
| FR-UI-22 | Every teacher-facing screen and message shall name a student by their full name — the way the teacher knows them. The internal reference is appended after the name only when two students on the same list share it, and stands alone only for a student with no name on the list. | M-UI, M-CONSOLE |

## 3. Design decisions

- **Where each door lives.** The class list is the base Tier C schema the orchestrator writes
  (`add_to_roster`), so renaming and removing a student are M-ORCH doors. Whose a paper is
  belongs to M-INGEST (B8's decision trail), so the move is M-INGEST's, reached through M-PIPE
  (the console's declared dependencies stop at M-PIPE for intake, `TC-CONSOLE-36`). **Removing
  a paper or the test paper is M-STORE's housekeeping**, beside `discard_empty_cohort`, because
  intake never deletes or rewrites a document it wrote (`CT-INGEST-02`) and must not read
  score-bearing tables (`CT-INGEST-09/17`) — the "is it graded?" check reads `work_unit`.
- **The second-copy rule is the intake command's, not the ladder's.** "This student already
  has a paper" is a fact about the class, not about the sheet. The V0–V4 ladder stays a pure
  reading of one paper (a re-read gives the same verdict, `CT-INGEST-12`); `ingest_files` —
  behind both `aeh ingest` and the papers screen — calls `park_second_paper` after each sheet.
- **Graded work is never removed.** A paper a run has touched is part of that run's record;
  only the purge removes it. Its corrections are moving it to the right student or amending a
  mark. A graded class is kept, and its results stay under Past tests — the delete control says
  so up front instead of refusing after the click.
- **Not changed, by design.** A class's consent class and name cannot be changed (the consent
  class decides whether work leaves the machine; the name is the ledger's file). While a class
  holds no paper it can be deleted and made again; with papers, they are removed first (FR-
  CONSOLE-67) and then the class is deleted.
- **No migration.** Every new write uses existing columns and tables; `v3_identity` has no
  CHECK, so `already_has_paper` needs none.

## 4. Known limits (not in this delta)

- A paper that arrives **after** a run (a late or absent student) is graded by starting a new
  run for the class, which grades every paper again; a run that grades only the papers not yet
  graded needs a run-scope column and is left for a later delta.
- A run started by mistake is paused (Jobs) rather than deleted; it stays listed under Past
  tests with its state.
