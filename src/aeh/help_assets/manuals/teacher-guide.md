# How the Grading System Works — A Guide for Teachers

*You do not need any technical knowledge to read this. You give the system your test documents — PDF, DOCX or TXT — in the browser.*

---

## 1. What this system does, in one paragraph

The system can read submitted papers, assess rubric criteria, show evidence and feedback, and
produce grades for a grading run. A teacher can review results and change a grade; changing a
final grade requires a reason and preserves the previous revision. The teacher-facing console is
a browser app, but class creation and scan intake still use operator commands, and a successful
run does not by itself mean every grade is final. Results can remain provisional until finalized
or until any review window has elapsed.

---

## 2. The whole life cycle at a glance

There are two phases in the teacher's workflow; the operator also handles class setup and reading the scans.

```
  PHASE 1 - SET UP THE TEST (once, about 30-60 minutes of your time)
  You give the console:  the test  ·  your model answer  ·  your rubric  (PDF, DOCX or TXT)
  The system drafts the package from them; you answer what it left open and approve it.
  Two things block until you confirm: the question list  ·  the answer key for every
  multiple-choice question
  Not in this version: the questions about your own marking (see Step 5)
                              |
                              v
  PHASE 2 - GRADE THE PAPERS (every time the test is run)
  Someone scans the ~300 papers to PDF; the operator reads them in and starts the run.
  Grading then proceeds without you, but it does not start itself and it is not tied
  to a time of day.
  When the run completes: students whose papers passed intake get the grades, feedback and evidence the run could produce; a parked paper or refusal may leave some work ungraded or provisional.
  Review is optional. A blind sample, if you take one, is 10-20 minutes.
```

The important rule: **review is not a grading gate.** If you are ill, busy, or simply do nothing,
a completed grading run can still leave grades provisional; unresolved intake, judging or citation
problems can leave work ungraded or flagged. Review status is visible in the console, and export
availability does not make a provisional grade final.

---

## 3. Phase 1 — Setting up a test (you do this once)

In this version these steps happen on the console's package screens in the browser: you upload your documents, the system drafts the package from them, you answer what it left open, and you approve it (the operating tutorial, section 5.1, walks the screens). The steps below describe the same journey in the order you will meet it.

### Step 1 — Upload the test documents (PDF, DOCX or TXT)

| What you upload | Example | Must you? |
|---|---|---|
| **The test paper** | `physics-midterm-2026.pdf` | Yes |
| **Your model answer** | Your own worked solution | Yes |
| **Your rubric** | The marking scheme you already use | Yes |

Scanned, image-only PDFs are accepted as source documents; the page reader attempts to transcribe
them during drafting. A document can be several files (for example, a scanner split it into parts).
If extraction detects a page gap or duplicate, treat that as an intake problem to resolve before
using the document. The scanned *answer sheets* students hand in stay PDF-only — that is the
paper-reading path, not the authoring one.

A legacy upload page can store previously marked papers, but the current SPA has no such upload
control and the stored papers are not used to grade another student's work. The ambiguity questions
described in Step 5 are not in the SPA workflow.

### Step 2 — Approve the question list ⚠️ **This one blocks. Nothing happens until you confirm it.**

The authoring model proposes a question inventory based on the documents; the example below is
illustrative, not a promise of the exact wording or question types the current draft flow emits:

> *"I found 5 questions. Q1–Q3 are multiple choice with four options each. Q4 is an open question.
> Q5 asks the student to circle an answer and then explain it. Is that right?"*

Review and correct the proposed inventory in the draft review/editor before approval. The questions
the authoring model leaves open vary with the source documents; do not assume a fixed list or that
every proposal needs the same confirmation.

### Step 3 — Give the answer key for multiple-choice questions ⚠️ **This one blocks too.**

For each multiple-choice question, you type the correct option. The system will never guess this.
There is no honest way to guess which answer is correct.

Multiple-choice answers are then marked by simple lookup — no AI judgment is involved at all.

### Step 4 — Check how your rubric was understood (optional, about 5 minutes)

The system shows your rubric back to you in its own words, broken into separate marking lines.
You can correct it. If you skip this, it uses your rubric exactly as you wrote it.

It will also ask, for some lines, whether they can be split into smaller checks. Example:

> *"Your line 'shows appropriate working, 5 marks' — can this be marked as four separate checks,
> or does it only make sense judged as a whole?"*

If you are unsure, say so. The system then keeps the line whole. Keeping it whole is always the
safe option.

### Step 5 — Answer up to six questions about your own marking — ⏳ **not in this version**

The teacher app has no control for it today. The console's older optional-setup page names the
step as a surface that arrives in version 2, with nothing to work yet — the SPA's setup flow does
not show it at all. It is listed here rather than hidden so that you do not go looking for a step
you think you skipped by accident. **In this version the system will not tell you where your
rubric is ambiguous.**

What it will do when it arrives: use the papers you already marked to find places where your rubric
could be read two ways, and ask you to decide. It does **not** rewrite your rubric to match your
marks. A real example of what you will eventually see:

> Your rubric says *"shows appropriate work."*
> On **Maya's** paper you gave 4 out of 5: she wrote the correct equation but dropped a minus sign.
> On **Devon's** paper you gave 2 out of 5 for exactly the same pattern. Which did you mean?
>
> ○ Correct method with an arithmetic slip earns near-full credit
> ○ Arithmetic errors cap this mark regardless of method
> ○ It depends on something else *(tell us what)*

Whatever you choose becomes the new wording in the rubric. **You are the author of every change.**
The system only points at the ambiguity; it never decides what is being measured.

There will never be more than six of these questions. Until this step exists, the system grades with
your rubric exactly as you wrote it — which is also what happens if you skip the step once it does.

**What the system is never allowed to change:** your marks, your weights, the number of rubric
lines, or what a line is measuring. Those are locked. It may only make the *wording* clearer.

### Step 6 — How the final grade is calculated (part of the package, not a browser menu)

The rules that turn rubric marks into a final grade are part of the test package, written as a
structured policy from a fixed menu of rules — a weighted sum of the rubric lines, best-k-of-n or
drop-the-lowest over the lines, a gate (a named line must reach a minimum for the grade to
stand), a scale, a rounding mode, and a boundary table that says what each grade is. The rules
work on rubric lines (criteria), not on whole questions. The
policy travels with the package, and every grade records which policy version produced it.

In this version you do not pick these rules from a screen. The published package uses the default
(a plain sum of the rubric marks) unless the policy was set when the package was built, and changing
it is a package edit for the operator or engineer (the spec route in the deployment tutorial,
section 8.2), not a teacher control. If you want boundaries or special rules, agree them with the
operator once, before the package is published.

---

## 4. How to write a rubric that works well

Your existing rubric will work as it is. But if you want the best results, write each line as a
**statement about what the answer does**, not as a rating out of five.

**Weaker (a rating):** *"Explanation quality: 0–5 marks."*
Nobody, human or machine, marks this consistently. Everyone drifts towards 3.

**Stronger (statements):** four options, where the marker simply picks which one is true:

| Level | What the answer does |
|---|---|
| Best | States the conclusion, names the governing law, **and** deals with the edge case |
| Good | States the conclusion and names the law, but does not deal with the edge case |
| Weak | States the conclusion, with no law named |
| None | No conclusion, or a conclusion the student's own work contradicts |

This is checkable. The marker has to point at the sentence in the student's paper that proves it.

**Simplest and best of all:** a plain yes/no line — *"Correctly identifies the units"* — met or not
met. Use yes/no lines wherever partial credit is not genuinely part of what you are measuring.

You do not have to do any of this yourself. If you upload a 0–5 rubric, the system will propose a
version in this shape and ask you to approve it.

---

## 5. Phase 2 — Grading the other ~300 papers

### What happens without you

1. The papers are read in and the run is started (in this version: `aeh ingest` reads the scans
   and the console's Start-the-run control or `aeh run` starts it — see the operating tutorial).
2. Every page is read and turned into text. Diagrams, graphs, crossings-out and corrections written
   above a line are described, not thrown away.
3. Every paper is checked before marking: is it readable, are all the pages there, whose paper is
   it, and **is this even the right test?** Anything that fails goes to whoever does the scanning —
   not to you.
4. For each admitted paper, each rubric line the system can settle is marked one at a time by a
   panel of AI markers — one, three or five, as the package declares — working independently.
   They cannot see each other's marks, and they cannot see how the same student did on other
   questions. A parked paper or an unresolved scoring problem can leave work ungraded.
5. Each accepted mark must quote the exact words in the student's paper that justify it.
6. Eligible multiple-choice questions are checked against your key — no judgment involved.
7. The system applies your grade policy to work it can settle. A parked paper, unresolved judging or citation problem, or open review window can leave a student's work ungraded or provisional; a completed run does not guarantee every grade is final.

How long a class-scale run takes has not been measured yet — the live-test guide tracks what the
runs so far cost and took, and the first full-class run supplies the real figure. There is no
overnight schedule to rely on: the run finishes when it finishes, and you read its progress on the
monitor.

### What you can do when the run is ready — optional review

| Activity | Time | What it is for |
|---|---|---|
| **Review the flagged marks** | You choose | The run flags marks for review. The SPA review screen (`/#/review`) shows how many marks are flagged and how many grades are still provisional, and lists item identifiers and kinds. Open a student's result to read feedback or change a grade; the decision is recorded there. The SPA has no time-budget picker or group-decision control. |
| **Blind sample** | 10–20 min | The system draws 15–25 marks at random (submission/criterion seats), and you mark them at `/#/review/blind` **without seeing the system's marks**. Note: that screen currently offers generic B1–B5 labels, not the package's own band names, and cannot validly score custom-band packages — record it as blocked rather than inventing a mapping. This would otherwise be the honest measure of whether the system agrees with you. |
| **Whole-grade sample** | about 5 min | The system can draw 10–15 complete final grades for you to read through exactly as the student will see them — but no screen serves this in the current version, so it is not yet something you can do from the browser. |

If you do none of these, the run's available results remain visible; provisional or ungraded work
is still shown as such. Skipping the blind sample costs you one thing only: the system cannot
claim any new evidence about its own accuracy for this run, and it says so plainly rather than
quoting an old number at you.

The console does not show an apply-to-all review action. The review system can group matching items
in its queue, but that backend capability should not be read as an action in the teacher-facing SPA.

---

## 6. Exactly what you must approve, and what is optional

| What | When | Does it stop the grades? |
|---|---|---|
| Confirm the question list | Set-up, once | **Yes** |
| Give multiple-choice answer keys | Set-up, once | **Yes** |
| Approve how your rubric was read | Set-up, once | No — defaults to your rubric as written |
| Confirm which rubric lines can be split | Set-up, once | No — defaults to keeping them whole |
| Set how the final grade is calculated | Set-up, once (package edit, not a browser control) | No — defaults to a plain sum |
| Answer the ambiguity questions | ⏳ Not in this version | No |
| Review the flagged marks | Every run | **No** |
| Blind sample | Every run | **No** |
| Whole-grade sample | Every run | **No** |
| Finalize the batch | Every run | **No** — you press **Finalize** on the Results screen when you are satisfied; until then the grades sit ready to finalize |

Only two things block, both once, at set-up. After that, the answer is always no.

A scanning problem can keep one student's work out of grading — a missing page, an unreadable
mark, or a paper matched to the wrong test. Those issues are named for the operator to resolve;
a rescan is not a marking decision, so it need not land on your desk. Unresolved judging or
citation problems can also leave work ungraded or provisional, even when the run itself completes.

---

## 7. What you actually get

**For each student:**

- Short written feedback for each rubric line — shown first, because it is the part that helps.
- The exact quoted sentences from *their own paper* that the mark is based on.
- The mark itself, shown second, changeable from the student's screen. A change to a final grade
  needs a reason and is kept in the record beside the original.
- A flag on any mark the system was unsure about.
- The grade state calculated with the package's policy when work can be settled; a parked paper
  or unresolved judging/citation problem may leave work ungraded or provisional.
- Whether an available grade is final or still provisional.

**For the class:**

- **The mark distribution for every rubric line.** This is the most valuable thing the system
  produces, and you cannot get it any other way: *"210 of 300 students missed the same step in
  question 3."* You walk into the next lesson knowing exactly what to reteach, and to whom.
- For multiple-choice questions, the marks are checked against your key exactly. The per-question
  answer statistics are computed, but no screen shows the wrong-option breakdown yet.
- An agreement figure for the blind sample, when the sample was taken — how often you and the
  system agreed, with the count it is based on beside it. Skipping the sample means no figure, not
  an old one.
- Which papers were flagged, which you reviewed, and which are still provisional.
- Which version of the rubric produced these grades, so a disputed grade can be traced years later.

**What you will never see:** a single confident headline like *"AI accuracy: 94%."* That number is
misleading, and the system is deliberately built not to produce it.

---

## 8. Using the same test again next year

The package you approved is a versioned artefact: it keeps the test, the rubric as understood, the
answer keys and the grade policy under one version id. It can travel two ways, and neither is a
teacher screen: the operator's terminal route exports a spec file (`aeh package export --data-dir
<folder> --package-version <version> --spec out.toml`) that `aeh package build --spec` rebuilds
unchanged, so a later class can grade against the same package without re-drafting it; and the
console itself carries a package export/import action that writes the package as a `.aehpkg`
backup archive and imports one back (served beside the teacher-readable package PDF on the
console's API). The teacher app has no package-import or download screen; both routes are operator
work.

There is no before-run comparison against last year's marks in the teacher's workflow: no screen
draws a sample of papers and reports rubric drift before a run. The system's statistics code
carries an advisory drift check for reusing a package against earlier results, but no teacher
screen offers it — it is not part of the package-reuse path described above — and an adverse
drift finding would not block a run even where it is shown. If a teacher-facing drift check
comes, it is a later version.

---

## 9. Honest limits

- **This version grades faithfully against your rubric as written, and never tells you where that
  rubric is ambiguous.** That is the one thing described in this guide (Step 5) that the current
  release does not do. You will not find a control for it in the teacher app this release; the
  older optional-setup page only names it as a future version's surface.
- **Grades will be issued that no human has looked at.** That is the point — the alternative at 300
  students is no feedback at all. Every such grade is labelled as unreviewed, backed by quoted
  evidence, and changeable by you at any time.
- **Middle-of-the-road answers are the weak spot.** Clearly excellent and clearly wrong answers are
  easy. Partial credit is hard, and those are exactly the marks the run flags for review.
- **You remain responsible for the grades.** The system is an assistant that shows its working. It
  is not the marker of record. You can change any score at any time, and it keeps a record of that.
- **Poor scans hurt.** Bad handwriting and low-quality scans are treated as a *scanning* problem,
  never as a wrong answer. A student whose writing the scanner could not read has not answered
  incorrectly.
