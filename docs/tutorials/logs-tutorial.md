# Reading the AI-call log: a short tutorial

*For the teacher. You need the console open in your browser. You do not need to be a
programmer and you never need to see a technical identifier.*

The grading system shows every AI call it made while grading: the question that was
asked and the answer that came back, exactly as they were sent and received. This
tutorial shows how to open that log, how to read one call, and how to get from a
student's grade to the call that produced it.

## What the log is

Every time the system asks an AI to do something — read a page, grade an answer, decide
a band — it writes the question and the answer into a log on this computer. The log is
for you: it is how you can see why a grade is what it is.

Two things to know about it:

* **The log holds students' answers.** The pages and answers you uploaded are in the
  calls it shows. It is on the machine that holds the console, behind the same access
  as every other screen.
* **The log is deleted with the class.** When you delete a class, its part of the log
  goes with it.

## Opening the log

Open **Logs** from the bar at the top. The Logs page has two tabs:

* **Run steps** — the run's own record: what each stage did, in order.
* **AI calls** — the AI-call log this tutorial is about.

Click **AI calls**. The list opens already filtered to the **grading calls** — the
decisions and the judgments that produced marks. Every other kind of call is also in
the log; use the **Which calls** filter to see them.

## Reading one call

Each row shows, on one line: what kind of call it was, the student and question it was
about, the model that answered, when it was made, how long it took, and what it cost.

Click a row to open it. An open row is headed by what was graded — the student's name
and the question, for example "Dana Levi — Q2" — and shows two panels:

* **Question sent to Jev** (or **Question sent to the judge**) — the exact question the
  AI was asked.
* **Jev's answer** (or **The judge's answer**) — the exact answer that came back.

Both panels are shown word for word — nothing is summarised or shortened. Each has its
own **Copy** button if you want to keep the text.

For a Jev decision, the answer panel also reads like this:

> Chose: adequate
> Chance: none 2%; limited 3%; adequate 4%; full 91%
> confidence 0.91, needed above 0.80 — accepted

That is the decision in full: the band it chose, how likely each band was, and whether
the answer was accepted on its own or sent to a judge instead. When the confidence was
not enough, the line ends "— not accepted", and the question went to the judge.

## From a student's grade to the call

On a student's page (open any student from **Results**), each question has a
**How was this graded?** link. Clicking it opens the AI-call log already filtered to
that student, that question and this run — the calls that produced that grade, in
order. No extra confirmation is needed, for any class.

## The same log from the command line

The same log can be read without the browser:

```
python -m aeh logs ai-calls --data-dir <data folder> --student "<name>" --full
```

You can narrow it with `--cohort`, `--package`, `--question`, `--kind` or `--outcome`,
and page through with `--json`. `--full` shows the question and the answer for every
call, the same two panels the browser shows.

## When something looks wrong

* **A grade surprises you** — read the call behind it, then use **Change the grade** on
  the student's page. Your change is recorded next to the original.
* **The answer repeats the student's words oddly, or misses their best line** — that is
  what the "Check" marks on the results page are for. Each one names its reason.
* **The log looks empty** — the calls belong to a run; choose the run from the switcher
  at the top, and check you are in the right class.
