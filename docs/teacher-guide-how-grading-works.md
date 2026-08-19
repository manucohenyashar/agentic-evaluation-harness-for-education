# How the Grading System Works — A Guide for Teachers

*You do not need any technical knowledge to read this. Everything you give the system is a PDF.*

---

## 1. What this system does, in one paragraph

You have 300 students. Marking their papers properly would take you many hours, so today you either
mark them quickly and badly, or you stop setting the kind of questions that are worth marking.
This system reads every paper, marks it against **your** rubric, writes short written feedback for
each rubric line, and gives you a final grade for every student. You set it up once. After that,
every paper is graded automatically overnight. **You keep the final word on every score, always.**

---

## 2. The whole life cycle at a glance

There are only two phases.

```
  PHASE 1 - SET UP THE TEST (once, about 30-60 minutes of your time)
  You upload:  the test  ·  your model answer  ·  your rubric  ·  10-15 papers you already marked
  You approve: the question list  ·  the answer key for any multiple-choice questions
  You choose (optional): answer a few questions about your marking, say how the grade is calculated
                              |
                              v
  PHASE 2 - GRADE THE REST (every time you run the test, 0 minutes required)
  Someone scans the ~300 papers to PDF and starts the run. It runs overnight.
  Next morning: every student has a grade, feedback and evidence.
  You then spend as long as YOU choose (30 minutes is normal) reviewing the most important items.
```

The important rule: **after set-up, nothing waits for you.** If you are ill, busy, or simply do
nothing, all 300 students still get a complete grade the next morning.

---

## 3. Phase 1 — Setting up a test (you do this once)

### Step 1 — Upload four things, all as PDF

| What you upload | Example | Must you? |
|---|---|---|
| **The test paper** | `physics-midterm-2026.pdf` | Yes |
| **Your model answer** | Your own worked solution | Yes |
| **Your rubric** | The marking scheme you already use | Yes |
| **10–15 papers you have already marked** | Scans of papers with your marks on them | Strongly recommended |

Handwritten and scanned is fine — that is what the system is built for. A document can be several
PDF files (a scanner that splits, a continuation sheet handed in separately); the system puts them
back in order and tells you if a page is missing or was scanned twice.

Those 10–15 already-marked papers are the most valuable thing you give it. They are how the system
learns *your* standard. It never changes your marks on them. It uses them only to find places where
your rubric can be read in two different ways.

### Step 2 — Approve the question list ⚠️ **This one blocks. Nothing happens until you confirm it.**

The system reads your test and shows you what it found:

> *"I found 5 questions. Q1–Q3 are multiple choice with four options each. Q4 is an open question.
> Q5 asks the student to circle an answer and then explain it. Is that right?"*

You correct anything wrong and confirm. This takes about a minute. It has to be right, because a
test the system has misunderstood cannot be marked.

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

### Step 5 — Answer up to six questions about your own marking (optional, about 5 minutes)

This is where the system uses the papers you already marked. It does **not** rewrite your rubric to
match your marks. It finds places where your rubric could be read two ways, and asks you to decide.
A real example of what you will see:

> Your rubric says *"shows appropriate work."*
> On **Maya's** paper you gave 4 out of 5: she wrote the correct equation but dropped a minus sign.
> On **Devon's** paper you gave 2 out of 5 for exactly the same pattern. Which did you mean?
>
> ○ Correct method with an arithmetic slip earns near-full credit
> ○ Arithmetic errors cap this mark regardless of method
> ○ It depends on something else *(tell us what)*

Whatever you choose becomes the new wording in the rubric. **You are the author of every change.**
The system only points at the ambiguity; it never decides what is being measured.

There will never be more than six of these questions. If you skip them, the system grades with your
rubric exactly as written, and it is more cautious about the lines it knows are ambiguous.

**What the system is never allowed to change:** your marks, your weights, the number of rubric
lines, or what a line is measuring. Those are locked. It may only make the *wording* clearer.

### Step 6 — Say how the final grade is calculated (optional, about 5 minutes)

You describe this in plain language, by picking from a short menu. You never write a formula.
Here is a finished grade policy, shown back to you exactly like this for approval:

> *"Each question's mark is the sum of its rubric lines. Question 4 scores zero if the safety
> analysis is missing. The test total is the sum of the questions, scaled to 100 and rounded to one
> decimal place. 80 and above is an A, 70 is a B, 60 is a C, 50 is a D, below that is an F."*

You can also say things like *"drop the lowest question"* or *"question 2 is worth double"*.

If you skip this, the system simply adds everything up and reports raw points with no letter grades.
It is worth the five minutes, mainly because **grade boundaries decide which students the system
asks you to look at first.**

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

1. Someone scans the papers and starts the run in the evening.
2. Every page is read and turned into text. Diagrams, graphs, crossings-out and corrections written
   above a line are described, not thrown away.
3. Every paper is checked before marking: is it readable, are all the pages there, whose paper is
   it, and **is this even the right test?** Anything that fails goes to whoever does the scanning —
   not to you.
4. Every rubric line on every paper is marked, one line at a time, by up to three different AI
   markers working independently. They cannot see each other's marks, and they cannot see how the
   same student did on other questions.
5. Each mark must quote the exact words in the student's paper that justify it.
6. Multiple-choice questions are checked against your key — no judgment involved.
7. The system applies your grade policy and produces a final grade for every student.

The run takes a few hours for 300 papers. Results are ready in the morning.

### What you can do next morning — all of it optional

| Activity | Time | What it is for |
|---|---|---|
| **The review queue** | You choose — say 30 min | The system ranks every uncertain mark by how much it could change a student's grade, and fills exactly the time you gave it. It tells you honestly: *"These are the 40 most important items out of 790. The other 750 are marked provisional and stay in your queue."* |
| **Blind sample** | 10–20 min | You mark 15 random papers yourself **without seeing the system's marks**. This is the only honest measure of whether the system agrees with you. |
| **Whole-grade sample** | about 5 min | You read 10–15 complete finished grades, exactly as the student will see them, and check they look like grades you would have given. |

If you do none of these, the grades are still delivered. Skipping the blind sample costs you one
thing only: the system cannot claim any new evidence about its own accuracy for this run, and it
says so plainly rather than quoting an old number at you.

If 210 students all made the same mistake on question 3, you review that pattern **once** and apply
your decision to all 210. You never click through 210 near-identical items.

---

## 6. Exactly what you must approve, and what is optional

| What | When | Does it stop the grades? |
|---|---|---|
| Confirm the question list | Set-up, once | **Yes** |
| Give multiple-choice answer keys | Set-up, once | **Yes** |
| Approve how your rubric was read | Set-up, once | No — defaults to your rubric as written |
| Confirm which rubric lines can be split | Set-up, once | No — defaults to keeping them whole |
| Describe how the final grade is calculated | Set-up, once | No — defaults to a plain sum |
| Answer the ambiguity questions | Set-up, once | No |
| Mark 10–15 calibration papers | Set-up, once | No |
| Work the review queue | Every run | **No** |
| Blind sample | Every run | **No** |
| Whole-grade sample | Every run | **No** |
| Finalise the batch | Every run | **No** — happens by itself |

Only two things block, both once, at set-up. After that, the answer is always no.

The one thing that can hold up a *single* student's grade is a scanning problem — a missing page, an
unreadable mark, a paper matched to the wrong test. Those are named specifically and go to whoever
handles scanning. A rescan is not a marking decision, so it never lands on your desk.

---

## 7. What you actually get

**For each student:**

- Short written feedback for each rubric line — shown first, because it is the part that helps.
- The exact quoted sentences from *their own paper* that the mark is based on.
- The mark itself, shown second, changeable in one click.
- A flag on any mark the system was unsure about.
- A final grade, calculated with your grade policy.
- If an unreviewed uncertain mark could push them over a grade boundary, the grade is shown as a
  **range** until you look at it. Otherwise it is simply the grade.

**For the class:**

- **The mark distribution for every rubric line.** This is the most valuable thing the system
  produces, and you cannot get it any other way: *"210 of 300 students missed the same step in
  question 3."* You walk into the next lesson knowing exactly what to reteach, and to whom.
- For multiple-choice questions: which wrong option the class chose, question by question.
- An honest agreement figure — how often the system agreed with you on the blind sample, with the
  number of papers it is based on printed right next to it.
- Which papers were flagged, which you reviewed, and which are still provisional.
- Which version of the rubric produced these grades, so a disputed grade can be traced years later.

**What you will never see:** a single confident headline like *"AI accuracy: 94%."* That number is
misleading, and the system is deliberately built not to produce it.

---

## 8. Using the same test again next year

Everything you did in Phase 1 is saved as a single file — the test, your tuned rubric, your grade
policy, your decisions and the reasons for them. Next year, or at another school, you load that file
and grade a new group with **no set-up at all**. The file can be copied onto a USB stick; no
internet connection is needed.

Before the new run, the system marks about 25 papers and compares them with last year: *"Rubric
lines 2 and 7 look different in this group; everything else matches."* That is advice, not a gate.
You can ignore it and run anyway.

---

## 9. Honest limits

- **Grades will be issued that no human has looked at.** That is the point — the alternative at 300
  students is no feedback at all. Every such grade is labelled as unreviewed, backed by quoted
  evidence, and changeable by you at any time.
- **Middle-of-the-road answers are the weak spot.** Clearly excellent and clearly wrong answers are
  easy. Partial credit is hard, and those are exactly the items pushed to the top of your review
  queue.
- **You remain responsible for the grades.** The system is an assistant that shows its working. It
  is not the marker of record. You can change any score at any time, and it keeps a record of that.
- **Poor scans hurt.** Bad handwriting and low-quality scans are treated as a *scanning* problem,
  never as a wrong answer. A student whose writing the scanner could not read has not answered
  incorrectly.
