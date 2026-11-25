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
  Optional, recommended: mark a few example papers yourself (see Step 5)
                              |
                              v
  PHASE 2 - GRADE THE PAPERS (every time the test is run)
  Someone scans the ~300 papers to PDF; the operator reads them in and starts the run.
  Grading then proceeds without you, but it does not start itself and it is not tied
  to a time of day.
  When the run completes: students whose papers passed intake get the grades, feedback and evidence the run could produce; a parked paper or refusal may leave some work ungraded or provisional.
  Review is optional. When marking finishes you are offered a blind sample first: about
  15 answers you mark without seeing the system's marks, 10-20 minutes. You can skip it.
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

Papers you mark yourself come later, in Step 5, once the test is published: you upload
*unmarked* copies there and enter your marks on a form. They are used only to check how the
system reads your rubric — never to grade another student's work.

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

**How each line will be marked.** On the draft review screen (`/#/package/review`) every line
you mark by judgement says how the system will mark it:

- *Marked as a simple check* — present or not; one grader decides unless graders disagree.
- *Marked as an overall judgement* — three graders from the start; harder to accept without you.

Beside a choice the system made on its own it says *(chosen automatically)*. For up to six such
lines it offers **Change**, with the two choices above; whichever you pick (even the one already
shown) becomes your choice when you approve the draft, and the line then reads *(your choice)*
instead. Any further lines are listed under the
outline as *"chosen automatically and stays as shown"* rather than asked, so the questions never
take more than a few minutes. If you are unsure, leave a line as shown.

**Every level must say what earns it.** A level that is only a name ("Good", "B3") leaves the
markers guessing, so the draft cannot be approved while any level of a judged line has no
description. Where your documents give none, the review screen asks, in this shape:

> *"What earns 'Good' on question 2? Say what the answer does, not how good it is."*

Your one-sentence answer becomes that level's description. If a description you wrote leans on
words like *good*, *excellent*, *correct* or *clearly*, the screen adds a **Note** suggesting you
say what the answer *does* instead (for example *"names the law and applies it to the case"*).
The note never blocks approval.

### Step 5 — Mark a few examples yourself (optional, recommended)

**What the marked examples are for.** They check one thing: whether the system reads your rubric
the way you do. You mark a handful of papers, the system marks the same papers with your rubric
as written, and the screen shows you every place where the two of you chose a different level —
so an unclear line in your rubric is found *before* it marks a whole class.

**Where.** Once the test is published, open **Set up a test package** (`/#/package`); under
*Your marked examples* press **Mark examples** beside the test. That opens
`/#/package/examples`, which walks four sub-steps and offers **Skip this step** on every one of
them until the step is done.

1. **Upload unmarked copies** — 1 to 25 PDF answer sheets, one per student (10 to 15 is
   recommended). They must be *clean* copies: a page with your marks on it is refused, by name —
   *"Page 2 of maya.pdf has marks on it. Please upload an unmarked copy, and enter your marks in
   the form."* The first upload also asks whose papers these are; on an online model only
   made-up practice papers are sent.
2. **Mark each paper** — on a form like the blind sample's: each answer, and the levels with
   their descriptions. Choose a level for every part, then **Save my marks for this paper**. The
   system never sees your marks while it marks.
3. **Check my examples** — the system marks the papers with your rubric as written. It runs in
   the background with a clock; the screen says what it cost, and it counts toward the run cost
   limit.
4. **See where the system read your rubric differently** — each difference side by side (the
   answer, *You:* your level, *The system:* its level and its reason), grouped by cause:
   - *The rubric may be unclear* — a question below asks how you meant it.
   - *The system misread a clear rule* — reported; your rubric is not changed.
   - *Two similar answers were marked differently* — both are shown side by side; nothing is
     changed.

Then come the **questions about your rubric** — at most six, each with examples from your papers:
should the description of a level be broadened, narrowed or kept as it is, or put in your own
words. Tick *My students saw this rubric before the test* if they did: the rubric is then not
changed for this class, and your answers apply to the next one.

**Why the examples never give a percentage.** Nothing on this step counts how often you and the
system matched, and that is deliberate. The screen says why: *"With a dozen papers you chose, a
percentage would not tell you how accurate the marking is. That's what the blind sample is
for."* A dozen papers is far too few, and papers you picked yourself are not a fair draw of the
class. The examples find *where* your rubric is read differently; the blind sample (section 5)
is the only place the system measures how closely its marking matches yours.

**What happens to your answers.** Answers that change a description make a *clarified version*
of your rubric. It is not used straight away: it must pass two checks first.

- An independent check of the wording: if it finds an answer your original and your clarified
  rubric would mark differently — so the change could alter what the test measures — the
  clarified version is set aside.
- A check on your next class: that class is graded **and delivered** with your original rubric,
  while the clarified version marks the same papers alongside. If it moves no more marks than
  your school allows, your following class is graded with it; otherwise it is set aside.

Either way the examples screen tells you where it stands in one sentence (for example *"Your
clarified rubric is checked on your next class before it is used"*), starting a run says so too,
and a class already graded keeps every mark it was given. **You are the author of every change.** The system only points at the
difference; it never decides what is being measured.

**If you skip.** Your test is marked with your rubric exactly as you wrote it. If questions were
already shown when you skip, the parts they were about are recorded as possibly unclear.

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

1. The papers are read in and the run is started (in this version: the console's Papers inbox
   reads the uploaded scans and its Start a run screen starts the run — see the operating
   tutorial; `aeh ingest` and `aeh run` do the same from a terminal).
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
monitor. While the answers are being marked, **Monitor run** (`/#/monitor`) says where the run
is, in one line such as *"Marking · question Q2 line 3 of 12 · grader 2 of 3"*: which rubric line
of how many is being marked (with its question, when the test names one), and by which of the
graders. It never shows a figure per student,
because the marking goes line by line across the whole class, not student by student.

### What you can do when the run is ready — optional review

| Activity | Time | What it is for |
|---|---|---|
| **Blind sample** | 10–20 min | Offered first, when marking finishes. The system draws about 15 answers at random and you mark them at `/#/review/blind` **without seeing the system's marks**, on each question's own levels. It is the only honest measure of how closely the marking matches yours — see the next section. |
| **Review the flagged marks** | You choose | The review queue (`/#/review`): you say how many minutes you have, and it shows the flagged answers most worth checking in that time — see *The review queue* below. |
| **Whole-grade sample** | about 5 min | 10 to 15 students' complete grades, drawn for you to read end to end exactly as each student will receive them, at `/#/results/whole-grade` — see *The whole-grade sample* below. |

If you do none of these, the run's available results remain visible; provisional or ungraded work
is still shown as such.

### The blind sample: what it is, and why it is done blind

**Where you meet it.** Starting a run already tells you that you will be asked to mark about 15
answers yourself. When marking finishes, **Monitor run** (`/#/monitor`) shows: *"Marking
finished. Mark 15 answers yourself first, without seeing the system's marks (about 10 min), or
skip and see the results."* with two buttons, **Mark the sample** and **Skip and see results**.
The sample is also one click away from the review queue (*Open the blind sample*) and from
Results.

**On the blind sample screen** (`/#/review/blind`) each drawn answer shows the student's name and
the question, the student's answer as text, **View the page** to open the scanned page, and the
question's own levels, each with its description. Nothing is preselected and nothing the system
decided about the answer is shown. Your choice is saved as you make it (*"N of M marked"* keeps
count), and you can change it until you press **Finish**. Finishing with answers still unmarked
asks first: only the ones you marked count. After **Finish** your marks can't be changed, and the
screen shows *Your marks beside the system's*: for each answer you marked, *You:* your level
beside *The system:* its level, the differences first, each saying whether the system gave more
or less credit than you. **See the results** opens Results.

**While the sample is open, the drawn marks stay hidden.** On Results and on a student's page,
the drawn answers' levels and points, and those students' totals, read *"Hidden until you mark
your sample or skip it"*, with a **Mark the sample** link. They come back as soon as you finish
or skip. Approving the grades on Results does not finish the sample — the confirmation says so,
and you can still mark it afterwards. If the grades' review window ends first, the sample closes
with the answers you marked by then.

> **One thing the screens cannot hide.** The marks download on Results (the spreadsheet and the
> CSV) carries every total, on purpose. If you open it while your sample is open, you have seen
> the marks — so finish or skip the sample first.

**Why marking without seeing the system's marks matters.** Once you have seen a mark, it pulls
your own judgement towards it — everyone's does, it is how reading works. A comparison made
after seeing the system's level measures how persuasive the system is, not how good its marking
is. Marked blind, your level is your own, so where you and the system differ is real
information.

**Why one class is "too few".** A figure for one question needs at least 30 blind answers before
it means much: with fewer, a couple of answers either way swings it a long way. One class's
sample is about 15 answers spread over all the questions, so a single class almost never gets
there, and the screens say so in words — *"Too few answers to rely on yet (12 of the 30
needed)."* That is not a failure; it is the honest state of the evidence. The answers add up:
every class that sits the same version of the test and marks its sample adds to that test's
record, *"How well this test has been marked so far"* (on **Set up a test package**, `/#/package`,
and on **Past tests**, `/#/past`), until each question has enough.

**What "agreement beyond chance" means.** Two markers who chose levels at random would still
match sometimes — often, when most answers sit at one level. *Agreement beyond chance* takes
that luck out: **1.00** means you and the system chose the same level every time, **0.00** means
you matched no more often than luck alone would give, and a figure below 0 means less often
than that. It is a figure between −1 and 1, never a percentage, and it is always shown with the
number of answers it rests on. Below 30 answers a question's figure is shown with *"too few"*
beside it; once it has 30, if every answer sat at one level the figure cannot be worked out, and
the screen says that instead of showing a number.

**What skipping costs.** **Skip and see results** changes no mark: your class is graded either
way, and Results opens at once. What you give up is evidence. Results then says *"You skipped
the blind sample for this class, so there is no new evidence about accuracy."*, the test's
record lists your class as *the blind sample was skipped*, and none of the figures — this
test's, or the ones on **System status** (`/#/status`) — get any closer to having enough
answers. The system never fills the gap with an older number.

### Reading how closely the marking matched yours

After you finish the sample, **Results** (`/#/results`) carries a block headed **"How closely the
marking matched yours"**:

- *"On the 15 answers you marked without seeing the system's marks, it gave the same level on
  11."* — a plain count, never a percentage.
- One line per question: *"Q1 (simple checks): agreement beyond chance 0.62 — 6 answers"*, with
  the number of answers beside every figure. Simple checks and overall judgements are never
  added together.
- While any question has fewer than 30 answers: *"Too few answers to rely on yet (… of the 30
  needed)."*
- Where the system differed, by student name and question, and whether it gave more or less
  credit than you — with **Review these**, which opens the side-by-side comparison.
- When earlier classes took the same test, their record follows on its own labelled line,
  never mixed into this class's figures.

Nothing in the block, or anywhere else, claims the marking is "accurate": it says how closely the
system's levels matched yours on the answers you marked, and how many answers that rests on.

### The review queue: the minutes you have, not a risk level

**Where.** **Review** (`/#/review`), or **Check answers** on Results. At the top: *I have [30]
minutes* and **Go**. Type how many minutes you can give it today — a whole number from 1 to 480 —
and press **Go**; the queue is rebuilt for that time.

**Why it asks for minutes.** A queue of "every answer above some risk level" has no end you can
plan for: on a hard test it can be hundreds of answers, and the ones that matter most sit among
the ones that hardly matter. So the system works the other way round. It ranks every flagged
answer by how much your check is worth — how likely the mark is to be wrong, times how much it
would change, for the time it takes you to check — and shows the best ones that fit in your
minutes. Nothing is dropped: the answers that do not fit stay provisional and stay in your queue
for another day, and the header says how many. The header reads, for example:

> *"10 of those 30 minutes are reserved for the blind sample and spent there. These are the 14
> highest-value answers of 63 flagged, in the other 20. The remaining 49 stay provisional and in
> your queue."*

The blind sample's minutes come off the top first, because it is the only measure of how well
the marking matches yours. The blind sample itself is never listed in this queue; *Open the blind
sample* takes you to its own screen.

**Groups: one decision for answers that look alike.** When several answers on the same rubric
line show the same pattern, they come as one card at the top: *"6 students · Q3 · line C3a — all
show the same pattern"*, a sentence describing the pattern, three of the papers side by side, and
the levels with the proposed one marked. Choose a level and press **Apply to all 6**: the screen
answers *"6 answers marked Good as one decision; each is recorded on its own."* — every answer
gets its own record, exactly as if you had marked them one at a time. If one of those answers
changed after the queue was shown, it is refused by name and the rest go ahead. **Review one by
one** lists the students instead, each linking to that student's own page.

**Single answers.** Every other answer shows, in this order: its feedback, *What the paper shows*
(the words the graders quoted), the levels — the proposed one marked *(proposed)*, and beside a
level which graders chose it (*chosen by Grader 1, Grader 2*) — then **Accept**, **Change** or
**Skip**, and finally *Flagged because:* with the reason in words: *panel disagreement*, *near a
grade boundary*, *reading uncertain* or *this line is often changed*. There is no confidence
number anywhere on the screen. **Skip** changes nothing: the answer stays provisional and in your
queue.

### Why a grade may show as a range, and what approving does to it

While some of a student's answers are still unchecked, their grade is not settled. If checking
those answers could move the student across a grade boundary, Results and the student's page show
a range instead of a single figure — for example *"Total grade: 62–71 (B–C) until 3 answers are
checked"*, or *"62–71 points until 3 answers are checked"* when the test has no grade boundaries.
A student whose unchecked answers could not change their grade simply shows the grade. To find
the students whose grade could move, choose **Could move a grade** in the *Flag* filter on
Results; checking their answers in the review queue is the quickest way to settle them.

**Approving.** **Approve all grades** on Results asks first, and the question counts what you are
about to accept: *"Approve all grades for 10a — physics-midterm? 49 answers you have not checked
will be accepted as the AI graded them; 7 of them could move a student's grade. You can still
change a grade afterward; the change is recorded."* Approving accepts every unchecked answer as
the AI marked it, so each student's grade is settled at the figure the system's own marks add up
to — the range only showed how far that figure could have moved if you had checked. (If the test
has a review window, the grades stay provisional until the window ends; section 6.)

### The whole-grade sample

The review queue shows single answers. The whole-grade sample shows something the queue cannot:
a few students' **complete** results, read end to end exactly as each student will receive them.

**Where you meet it.** Once the blind sample is finished or skipped, **Monitor run**
(`/#/monitor`) shows *Marking finished.* with **Check a few whole grades** and **See the
results**; Results also carries a **Whole-grade sample** button. Both open
`/#/results/whole-grade`.

**What it shows.** 10 to 15 students, drawn from the answers the system accepted on its own, not
the ones you reviewed — the screen says so. For each student: the feedback first, then the total
and grade, then every question's points with the level of each rubric line. If fewer grades were
accepted on their own, the screen says how many it could draw instead.

**The one question.** *"Do these look like grades you would have given?"*

- **Yes, they do** — records your answer (*"Recorded: these look like grades you would have
  given."*).
- **Open a student** — choose a student from the list beside it, and their own page opens, where
  you can change a mark.
- **Skip** — the screen says the cost before you press it: *"Skipping means nobody has read a
  whole paper's result end to end; the grades are delivered either way."*

Neither answer changes a mark, and neither counts toward the agreement figures: this is a check
that the results read sensibly as a whole, not a measurement. While your blind sample is still
open, the drawn students' hidden marks stay hidden here too.

### The line under every grade

Every screen that shows a grade — Results, a student's page, the whole-grade sample and the review
queue — ends with one line naming what produced it, for example:

> *"Marked with physics-midterm version 2 · settings an online AI service · graders three AI
> graders"*

That is the test and its version, where the marking ran (*an online AI service*, or *on this
computer, nothing sent out*), and how many AI graders marked each answer. It is read from the
settings the run was started with, not today's settings, so a test from last term opened from
**Past tests** still names what marked it then. If a disputed grade comes back years later, this
line says which version of the test and which graders produced it.

### When the marking runs on this computer

A school can run the whole system on one computer with the AI models on that computer too, so
that no student work leaves it. The operator sets this up (the deployment tutorial, section 6);
for you, the screens are the same. Three things tell you it is in use: the line under every grade
reads *settings on this computer, nothing sent out*; the confirmation before **Load papers** reads
the scans says *no cost: local models*; and nothing is sent to OpenRouter.

On that computer a separate program, a *model server*, holds the AI models and answers the
system's requests. Each model is recorded twice: by the exact model file that marked your class
(that is what makes a grade traceable later), and by `served_as` — the name the model server
lists that model under, which is the name the system asks the server for. If the operator renames
a model in the server, only `served_as` changes; the record of which file marked your class does
not.

---

## 6. Exactly what you must approve, and what is optional

| What | When | Does it stop the grades? |
|---|---|---|
| Confirm the question list | Set-up, once | **Yes** |
| Give multiple-choice answer keys | Set-up, once | **Yes** |
| Approve how your rubric was read | Set-up, once | No — defaults to your rubric as written |
| Say what earns each level of a judged line | Set-up, once | **Yes**, for a level with no description — the draft cannot be approved until each says what earns it |
| Change how a line is marked (simple check or overall judgement) | Set-up, once | No — defaults to the choice shown |
| Set how the final grade is calculated | Set-up, once (package edit, not a browser control) | No — defaults to a plain sum |
| Mark examples and answer the questions about your rubric | Once per published test | No — skipping marks with your rubric as written |
| Review the flagged marks | Every run | **No** |
| Blind sample | Every run | **No** |
| Whole-grade sample | Every run | **No** |
| Finalize the batch | Every run | **No** — you press **Approve all grades** on the Results screen when you are satisfied; its confirmation says how many unchecked answers it accepts and how many of those could move a grade (section 5); until then the grades sit ready to finalize |

Only set-up questions block, all of them once: the question list, the answer keys, and a
description for any level that has none. After that, the answer is always no.

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
  needs a reason and is kept in the record beside the original. While unchecked answers could
  still move the grade across a boundary, it shows as a range (section 5).
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
- When you marked the blind sample: the block **"How closely the marking matched yours"** on
  Results (`/#/results`) — how many of your blind answers got the same level, *agreement beyond
  chance* for each question with the number of answers beside it, *"too few"* below 30, and the
  differences by student name (section 5). Skipping the sample means no new figure, never an old
  one in its place.
- For the test itself: **"How well this test has been marked so far"**, on **Set up a test
  package** (`/#/package`) and **Past tests** (`/#/past`) — the blind answers collected across
  every class that took this version, each class's contribution with its date, and per-question
  figures once there are enough.
- Which papers were flagged, which you reviewed, and which are still provisional.
- Which version of the rubric produced these grades, so a disputed grade can be traced years later
  — on screen, the line under every grade names the test version, where the marking ran and the
  graders (section 5).

**What you will never see:** a single confident headline like *"AI accuracy: 94%."* That number is
misleading, and the system is deliberately built not to produce it. Even your marked examples
(Step 5) give no percentage: a dozen papers you chose cannot say how accurate the marking is.

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

- **The system finds where your rubric may be unclear only if you mark examples** (Step 5). Skip
  that step and it grades faithfully against your rubric as written, unclear lines included.
- **One class is too few to measure the marking.** A class's blind sample is about 15 answers;
  each question needs 30 before its figure means much. Expect *"too few"* for your first classes,
  and let the test's record build up across classes.
- **The blind sample is only as blind as you keep it.** The screens hide the drawn marks until
  you finish or skip, but the marks download carries every total. Finish or skip first.
- **Where student work goes.** When the system marks with online models, the papers' text is
  sent to them through OpenRouter. How long it may be kept there is governed by the privacy
  settings of your operator's OpenRouter account; the system does not ask for zero retention
  itself. Ask your operator how the account is set. When the marking runs on this computer
  instead (section 5), nothing is sent out at all.
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
