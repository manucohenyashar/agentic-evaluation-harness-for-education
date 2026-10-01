# Sample tests and answer sheets for the first live test

*Two short tests, ready to use, with student answer sheets that behave like a real class: strong papers, middle papers, weak papers, and the awkward ones every teacher knows (the paper with no name, the wrong test, the doubled tick).*

Everything here is **made up**. The students do not exist, so these papers are marked `synthetic`, which is what lets them go to OpenRouter without anyone's consent (see [01, section 7](01-hosting-and-configuration.md)).

All files are in [`sample-materials/pdf/`](sample-materials/pdf/). They are produced by one script, and every claim below about what the intake does with them was checked by running them through the real intake rules.

---

## 1. What is in the box

```
sample-materials/pdf/
├── PS9-FORCES-01/                  Grade 9 Physical Science: Forces and Motion (10 marks)
│   ├── 01-test-paper.pdf           what the students sat
│   ├── 02-model-answer.pdf         the teacher's worked answers
│   ├── 03-rubric.pdf               the marking scheme, in statement form
│   ├── 04-blank-answer-sheet.pdf   a form to print and fill in BY HAND
│   └── answer-sheets/              six finished sheets (S9-001 … S9-006)
└── ENG7-READ-01/                   Grade 7 English: Reading Response (8 marks)
    ├── 01-test-paper.pdf
    ├── 02-model-answer.pdf
    ├── 03-rubric.pdf
    ├── 04-blank-answer-sheet.pdf
    └── answer-sheets/              four finished sheets (E7-001 … E7-004)
```

The four setup files per test are the ones the design says a teacher uploads: **test paper, model answer, rubric** (and, optionally, marked papers). The `answer-sheets/` are the "students" for the run.

**Honest limit:** the sheets are *typed*, not handwritten. A typed page is the easy case for a page-reading model. These sheets rehearse the paper trail (names, ticks, wrong tests, blanks), not handwriting. To test handwriting, print the `04-blank-answer-sheet.pdf`, have two or three people fill it in by pen, scan to PDF, and add those files next to these. Keep the two printed lines (`Assessment: …` and `Student: …`) legible.

## 2. Test 1: Grade 9 Physical Science, "Forces and Motion" (`PS9-FORCES-01`)

Time 25 minutes, 10 marks. Three multiple-choice questions, one written explanation, and one question that is half multiple choice, half explanation (the design's "circle the answer and explain" case).

| Question | What is asked | Answer key / best answer |
|---|---|---|
| **Q1** (MCQ) | A moving object has zero net force. What does it do next? | **C**: keeps moving at a steady speed |
| **Q2** (MCQ) | Which unit measures force? | **B**: newton |
| **Q3** (MCQ) | A 2 kg trolley accelerates at 3 m/s². What is the net force? | **C**: 6 N |
| **Q4** (written) | A book rests on a table. Using forces, explain why it is not accelerating. | Weight down and normal force up, equal, so net force zero |
| **Q5a** (MCQ) | A cyclist rides at steady speed. The forward force is ... the resistive force. | **B**: equal to |
| **Q5b** (written) | Explain your choice in (a). | Net force zero, linked to steady speed (Newton's first law) |

**Rubric lines** (the system calls them criteria). The written lines use four statement bands, best first, so the marker picks "which is true", not "how many out of 3":

| Line | Question | Kind | Points |
|---|---|---|---|
| C1, C2, C3, C5 | Q1, Q2, Q3, Q5a | Multiple choice: marked by key lookup, no judge involved | 1 each (0 or 1) |
| **C4** | Q4 | Written, four bands | Full 3 · Adequate 2 · Limited 1 · None 0 |
| **C6** | Q5b | Written, four bands | Full 3 · Adequate 2 · Limited 1 · None 0 |

The exact band wording (what *Full*, *Adequate*, *Limited*, *None* each require) is in `03-rubric.pdf`.

**Grade policy** (said in plain language, as the setup step asks): *the test total is out of 10; 8 or more is an A, 6 or more a B, 4 or more a C, 2 or more a D, below 2 an F.*

### The six answer sheets

"Expected" is what a careful teacher would mark by hand (the *reference marks*, used for your blind sample in [04](04-test-day-plan.md)); they are judgment calls and are **not** output of the system. The "intake" column was **checked**: it is what the real intake rules do with the sheet when the page is read well.

| Sheet | Student | Story | Q1 | Q2 | Q3 | Q4 | Q5a | Q5b | Expected total / grade | Intake (checked) |
|---|---|---|---|---|---|---|---|---|---|---|
| `S9-001-strong` | S9-001 | Everything right, full explanations | C ✓ | B ✓ | C ✓ | Full | B ✓ | Full | **10 / A** | admitted (`ok`) |
| `S9-002-middle` | S9-002 | One slip, two half answers | C ✓ | B ✓ | **B ✗** | Adequate (both forces, no "equal") | B ✓ | Adequate ("balanced", no link to steady speed) | **7 / B** | admitted |
| `S9-003-weak` | S9-003 | Thinks a moving object needs a constant push | **D ✗** | **A ✗** | C ✓ | Limited (gravity named, table "is strong") | **A ✗** | Limited (friction, no balance) | **3 / D** | admitted |
| `S9-004-doubled-mark-and-blank` | S9-004 | Two ticks on Q1; Q4 left empty | **A and C** | B ✓ | C ✓ | **none (blank)** | B ✓ | Full | **6 or 7 / B** once Q1 is decided | **parked**: `incomplete`, structure check (V2) fails |
| `S9-005-wrong-test` | S9-005 | Handed in the English answers against this test | n/a | n/a | n/a | n/a | n/a | n/a | n/a | **parked**: `unmatched_assessment`, right-test check (V4) mismatch: the page names `ENG7-READ-01` |
| `S9-006-no-name` | *(forgot to write it)* | A good paper with no name on it | C ✓ | B ✓ | C ✓ | Full | B ✓ | Full | **10 / A** once matched | **parked**: `incomplete`, identity check (V3) unmatched |

What each parked sheet is there to prove:

* **`S9-004`**: the system must not guess which tick the student meant, and must not treat a **blank answer** as a scanning error. The operator looks at the image crop on S8, if one was stored, and decides (B8 applies here too).
* **`S9-005`**: the "confident zero" trap. A paper for the wrong test would otherwise be scored 0 by every judge in agreement. The system must stop it before any judge sees it.
* **`S9-006`**: nobody is silently assigned a grade they did not earn. The operator decides. (Today the console can only *release* or *close* a parked paper; it cannot record *which student* it is. See blocker B8 in [02](02-live-readiness-and-blockers.md).)

**What you should see in the class view** after the operator has resolved the three parked sheets: three clean grades (A, B, D) from the admitted sheets, and the three resolved sheets graded or marked INCOMPLETE according to what the operator chose. Q3 shows two of three admitted students correct; Q1 shows one wrong option chosen (D), the "needs a constant push" misconception.

## 3. Test 2: Grade 7 English, "The Lighthouse Keeper" (`ENG7-READ-01`)

Time 20 minutes, 8 marks. A 150-word original passage and three constructed-response questions. No multiple choice, so the key-lookup path is not used here.

| Line | Question | Kind | What earns it |
|---|---|---|---|
| **C1** | Q1: who and what each evening | Yes/no | Names **Tomas** |
| **C2** | Q1 | Yes/no | Says he **lights the lamp** |
| **C3** | Q2: why keep the lamp burning | Four bands (3·2·1·0) | A reason **and** evidence from the passage |
| **C4** | Q3: how Tomas changes | Four bands (3·2·1·0) | Unsure → confident, with a detail that shows it |

Grade policy: *total out of 8; 6 or more is a "pass", below 6 is "not yet a pass".*

| Sheet | Student | Story | C1 | C2 | C3 | C4 | Expected total | Intake (checked) |
|---|---|---|---|---|---|---|---|---|
| `E7-001-strong` | E7-001 | Names him, gives a reason with evidence (the small boat), clear change | met | met | Full | Full | **8, pass** | admitted |
| `E7-002-middle` | E7-002 | Right idea, no evidence | met | met | Adequate | Adequate | **6, pass** | admitted |
| `E7-003-weak` | E7-003 | Retells, no reason, no change | not met | not met | Limited | Limited | **2, not yet** | admitted |
| `E7-004-mostly-blank` | E7-004 | Names "Tomas." and leaves Q2 and Q3 empty | met | not met | None | None | **1, not yet** | admitted |

`E7-004` matters because a blank answer is **a real non-answer, scored as one**. It is never a scanning problem and never a reason to park the paper.

## 4. The class list

The identity check (V3) matches the name on the page to the **roster**, so the roster must hold exactly these IDs before intake:

* `PS9-FORCES-01` cohort: `S9-001`, `S9-002`, `S9-003`, `S9-004`, `S9-005`, `S9-006`
* `ENG7-READ-01` cohort: `E7-001`, `E7-002`, `E7-003`, `E7-004`

Cohort IDs used by the check script are `coh-ps9-forces-01` and `coh-eng7-read-01`. Mark both `synthetic`. (Nothing in the shipped code creates a cohort for an operator or loads a roster. See blocker B3.) Note that `S9-006` is on the roster even though the page does not carry the name; that is the point.

## 5. The rules these sheets follow (and yours must too)

Each rule is there because a check in the code depends on it:

1. **Two header lines, each on its own line, at the top:** `Assessment: <the test's ID>` and `Student: <the student's ID>`. The page-reading prompt tells the model to copy exactly these lines first. The first must equal the package's ID (case and extra spaces ignored); the second must be on the roster.
2. **One test ID, used everywhere.** `PS9-FORCES-01` is the printed test name, the package ID and the cohort's test. Change one and the right-test check reads a mismatch.
3. **The package's ID is the test ID.** In the check script the package is created under that exact name.
4. **Reprint each question above its answer space.** The right-test check compares the answer's words with the question's words (floor 0.10). With the question reprinted and transcribed, the admitted sheets scored 0.24 to 0.93. With only the handwriting transcribed, six of the seven good sheets scored 0.00 to 0.04 and were parked (`verify_sample_materials.py --answers-only` reproduces it). See the risk in [02](02-live-readiness-and-blockers.md).
5. **Tick boxes for multiple choice, one per option, one tick per question.** Two ticks make the mark unreadable and the paper is parked, by design.
6. **PDF only**, starting with the `%PDF-` marker. The console refuses anything else (checked: HTTP 400).
7. **Do not put instructions after `Student:`.** Whatever follows it on that line is read as the name.

## 6. Rebuilding and checking the files

Both scripts use only the Python standard library to build, and the system's own code to check. Run from the project folder.

**Rebuild the PDFs** (identical bytes every time):

```bash
python docs/live-tests/sample-materials/build_sample_materials.py
```

**Check the sheets against the real intake rules** (no network, no model, no cost; writes into a temporary private folder under your home directory and deletes it):

```bash
python docs/live-tests/sample-materials/verify_sample_materials.py
```

Real output, trimmed:

```
== PS9-FORCES-01: 6 answer sheets
  S9-001-strong                      status=ok           v0=pass v1=pass v2=pass v3=pass v4=match
  S9-002-middle                      status=ok           v0=pass v1=pass v2=pass v3=pass v4=match
  S9-003-weak                        status=ok           v0=pass v1=pass v2=pass v3=pass v4=match
  S9-004-doubled-mark-and-blank      status=incomplete   v0=pass v1=pass v2=fail v3=pass v4=match
  S9-005-wrong-test                  status=unmatched_assessment v0=pass v1=pass v2=fail v3=pass v4=mismatch
  S9-006-no-name                     status=incomplete   v0=pass v1=pass v2=pass v3=unmatched v4=match
== ENG7-READ-01: 4 answer sheets
  E7-001-strong … E7-004-mostly-blank   status=ok  (all four)
OK: every sample sheet behaved at intake as the live-test guide says it will.
```

Add `-v` to also print the right-test signals for each sheet.

**What that check proves, and does not.** It proves the *files* fit the *rules*: the PDFs are sound and readable, the headers parse, the identity and right-test logic do what the table says, and the three awkward sheets are parked for the right reasons. It does **not** prove a live model reads these pages correctly: a scripted stand-in plays the page reader and returns the text an ideal reader would. Reading the pages is what the live test is for.

## 7. What the live test should show for these sheets

If the live run works, the **deterministic** parts are exact and you can check them to the mark:

* **Multiple-choice lines (C1, C2, C3, C5)** are marked by key lookup: no model decides them. S9-001 and S9-006 get 4 of 4; S9-002 gets 3 (missed Q3); S9-003 gets 1 (only Q3 right); S9-004 gets 3 so far (Q1 awaits the operator).
* **The three parked sheets** are parked, for the reasons in the table, with no grade invented.

The **judged** parts (the written lines C4, C6 on the physics test; C3, C4 on the English test; and the English yes/no lines) are what the system is being tested on. Compare them to the reference marks. The teacher guide's own warning applies: the middle bands are the hard ones, so treat a miss of one band as normal and a miss of two or more as a finding. The full scoring plan is in [04](04-test-day-plan.md).
