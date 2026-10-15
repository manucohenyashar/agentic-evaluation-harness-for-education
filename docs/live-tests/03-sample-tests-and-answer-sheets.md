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
└── ENG7-READ-01/                   Grade 7 English: Reading Response (8 marks; every rubric method)
    ├── 01-test-paper.pdf
    ├── 02-model-answer.pdf
    ├── 03-rubric.pdf
    ├── 04-blank-answer-sheet.pdf
    └── answer-sheets/              four finished sheets (E7-001 … E7-004)
```

Beside them, [`config/`](config/) holds what the system is given for each test: the package spec it publishes (`ps9-forces-01.package.toml`, `eng7-read-01.package.toml`) and the class list (`ps9-roster.txt`, `eng7-roster.txt`). Between them, the two tests use every way the system can score a rubric line (section 4a).

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
| `S9-006-no-name` | *(forgot to write it)* | A good paper with no name on it | C ✓ | B ✓ | C ✓ | Full | B ✓ | Full | **10 / A** if identity is established by a corrected rescan | **parked**: `incomplete`, identity check (V3) unmatched |

What each parked sheet is there to prove:

* **`S9-004`**: the system must not guess which tick the student meant, and must not treat a **blank answer** as a scanning error. The operator looks at the image crop on S8, if one was stored, and decides (B8 applies here too).
* **`S9-005`**: the "confident zero" trap. A paper for the wrong test would otherwise be scored 0 by every judge in agreement. The system must stop it before any judge sees it.
* **`S9-006`**: nobody is silently assigned a grade they did not earn. Because V3 did not match an identity, `matched` release is refused. Close it as unresolvable, or add the student's ID to the sheet, rescan and read it again with `aeh ingest`. (The console still cannot record a manual student assignment; see B8 in [02](02-live-readiness-and-blockers.md).)

**What you should see in the class view** after the three parked sheets are handled: the three admitted sheets have grades (A, B, D). S9-004 may be released after an operator checks the mark, or closed as unresolvable; S9-005 should be closed or re-ingested under the correct package; S9-006 cannot be released as `matched` without an identity match, so close it or rescan after adding identity. Q3 shows two of the three initially admitted students correct; Q1 shows one wrong option chosen (D), the "needs a constant push" misconception.

## 3. Test 2: Grade 7 English, "The Lighthouse Keeper" (`ENG7-READ-01`): every rubric method

Time 20 minutes, 8 marks. A 150-word original passage and three constructed-response questions. No multiple choice, so the key-lookup path is not used here: the physics test covers it.

This test is the one that exercises **every way the system can compute a rubric line's score** (its *scoring method*, `score_method` in the package). Each question uses a different one:

| Line | Question | Scoring method | How the line's mark is computed | What a judge sees |
|---|---|---|---|---|
| **C1** | Q1: who and what each evening | **Evidence checklist** (`evidence_sum`) | The **sum** of its two items, out of 2. C1 itself is never judged | Nothing: C1 is a grouping record |
| ↳ **C1a** | Q1 | an item of C1 (two bands: *absent* 0 / *present* 1) | 1 if it names **Tomas** | the two bands of C1a |
| ↳ **C1b** | Q1 | an item of C1 (two bands: *absent* 0 / *present* 1) | 1 if it says he **lights the lamp** | the two bands of C1b |
| **C2** | Q2: why keep the lamp burning | **Bands** (`bands`, the default) | The points of the band awarded: *none* 0 · *limited* 1 · *adequate* 2 · *full* 3 | the four bands |
| **C3** | Q3: how Tomas changes | **In the teacher's own words** (`general`) | The teacher wrote, in prose, how to arrive at a mark; the system derived four bands from it and the teacher confirmed them: *none* 0 · *retell* 1 · *change* 2 · *evidenced* 3. From then on it grades exactly like a bands line | the four derived bands (never the teacher's prose) |

The rubric PDF (`03-rubric.pdf`) shows each line the way the teacher would write it: the checklist items for C1, the band statements for C2, and for C3 the teacher's own paragraph followed by the bands derived from it. The package spec, [`config/eng7-read-01.package.toml`](config/eng7-read-01.package.toml), carries the same lines in the system's vocabulary (`score_method`, `component_of`, `derivation_description`) and is what `aeh package build` publishes.

Grade policy: *total out of 8; 6 or more is a "pass", below 6 is "not yet a pass".*

| Sheet | Student | Story | C1a | C1b | **C1** (sum) | C2 | C3 | Expected total | Intake (checked) |
|---|---|---|---|---|---|---|---|---|---|
| `E7-001-strong` | E7-001 | Names him, gives a reason with evidence (the small boat), clear change | present | present | **2** | full | evidenced | **8, pass** | admitted |
| `E7-002-middle` | E7-002 | Right idea, no evidence | present | present | **2** | adequate | change | **6, pass** | admitted |
| `E7-003-weak` | E7-003 | Retells, no reason, no change | absent | absent | **0** | limited | retell | **2, not yet** | admitted |
| `E7-004-mostly-blank` | E7-004 | Names "Tomas." and leaves Q2 and Q3 empty | present | absent | **1** | none | none | **1, not yet** | admitted |

`E7-004` matters twice. A blank answer is **a real non-answer, scored as one**: never a scanning problem, never a reason to park the paper. And its C1 is a **partial checklist** (one item of two), the case that shows the evidence sum adding up item by item rather than picking one band for the whole question.

What each method is there to prove in the live run:

* **C1 (evidence checklist).** The run grades C1a and C1b, never C1 itself (the run's work list says *"1 composite criterion withheld from enumeration: ['C1']"*), and C1's mark is exactly C1a + C1b. If either item is still unscored, C1 has no mark yet; it is never filled in as a partial sum.
* **C2 (bands).** The classic case, the same as the physics written lines.
* **C3 (in the teacher's own words).** Grades exactly as a bands line would. The teacher's paragraph is stored with the package as a record of where the bands came from, and no model ever reads it.

## 4. The class list

The identity check (V3) matches the name on the page to the **roster**, so the roster must hold exactly these IDs before intake. Both lists ship as files, one entry per line, ready for `aeh cohort create --roster`:

* `PS9-FORCES-01` cohort: `S9-001` … `S9-006`, in [`config/ps9-roster.txt`](config/ps9-roster.txt)
* `ENG7-READ-01` cohort: `E7-001` … `E7-004`, in [`config/eng7-roster.txt`](config/eng7-roster.txt)

Cohort IDs used by the check script are `coh-ps9-forces-01` and `coh-eng7-read-01`; the deployment tutorial's walkthrough uses `ps9-class` and `eng7-class`. Mark both `synthetic`. Note that `S9-006` is on the roster even though the page does not carry the name; that is the point.

## 4a. The package specs

Each test has a package spec in [`config/`](config/), built and published with `aeh package build --spec`:

| Spec | Lines | Scoring methods it exercises |
|---|---|---|
| [`ps9-forces-01.package.toml`](config/ps9-forces-01.package.toml) | 4 multiple-choice keys, 2 four-band lines | key lookup, `bands` |
| [`eng7-read-01.package.toml`](config/eng7-read-01.package.toml) | 1 evidence checklist (2 items), 1 four-band line, 1 line in the teacher's own words | `evidence_sum`, `bands`, `general` |

**Run both to grade every kind of rubric line the system supports.** The comments in each file say what every field means.

## 5. The rules these sheets follow (and yours must too)

Each rule is there because a check in the code depends on it:

1. **Two header lines, each on its own line, at the top:** `Assessment: <the test's ID>` and `Student: <the student's ID>`. The page-reading prompt tells the model to copy exactly these lines first. The first must equal the package's ID (case and extra spaces ignored); the second must be on the roster.
2. **One test ID, used everywhere.** `PS9-FORCES-01` is the printed test name, the package ID and the cohort's test. Change one and the right-test check reads a mismatch.
3. **The package's ID is the test ID.** In the check script the package is created under that exact name.
4. **Reprint each question above its answer space.** The right-test check compares the answer's words with the question's words (floor 0.10). With the question reprinted and transcribed, the admitted sheets scored 0.24 to 0.93. With only the handwriting transcribed, six of the seven good sheets scored 0.00 to 0.04 and were parked (`verify_sample_materials.py --answers-only` reproduces it). See the risk in [02](02-live-readiness-and-blockers.md).
5. **Tick boxes for multiple choice, one per option, one tick per question.** Two ticks make the mark unreadable and the paper is parked, by design.
6. **Paper intake accepts PDF only**, starting with the `%PDF-` marker; this applies to the scanned test and answer sheets sent through `aeh ingest` (checked). It does not constrain package authoring: the SPA's package-authoring screen accepts PDF, DOCX and TXT source documents.
7. **Do not put instructions after `Student:`.** Whatever follows it on that line is read as the name.

## 6. Rebuilding and checking the files

Both scripts use only the Python standard library to build, and the system's own code to check. Run from the project folder.

**Rebuild the PDFs** (identical bytes every time):

```bash
python docs/live-tests/sample-materials/build_sample_materials.py
```

**Check the sheets and the packages against the real system code** (no network, no model, no key, no cost; writes into a temporary private folder under your home directory and deletes it). It builds both packages from the two spec files and both classes from the two roster files, exactly as the live run will, reads every sheet through the intake rules, and then creates (but never starts) a `dev-ci` run from `config/live-test.dev-ci.toml` over each class to list what would be graded:

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
  rubric methods:  C1=key, C2=key, C3=key, C4=bands, C5=key, C6=bands
  dev-ci run work: C1(deterministic), C2(deterministic), C3(deterministic), C4(extract+score), C5(deterministic), C6(extract+score)
  composites:      none declared
== ENG7-READ-01: 4 answer sheets
  E7-001-strong … E7-004-mostly-blank   status=ok  (all four)
  rubric methods:  C1=evidence_sum, C1a=aspect of C1, C1b=aspect of C1, C2=bands, C3=general
  dev-ci run work: C1a(extract+score), C1b(extract+score), C2(extract+score), C3(extract+score)
  composites:      1 composite criterion(a) withheld from enumeration (FR-JUDGE-38): ['C1']

OK: every sample sheet behaved at intake as the live-test guide says it will.
OK: the two packages carry every rubric method (key, bands, evidence_sum, general), and a run grades every line but the evidence-sum composite, which is its aspects' sum.
```

Add `-v` to also print the right-test signals for each sheet.

**What that check proves, and does not.** It proves the *files* fit the *rules*: the PDFs are sound and readable, the headers parse, the identity and right-test logic do what the table says, the three awkward sheets are parked for the right reasons, both package specs build and publish, and a run over them would grade every rubric line of every method (the multiple-choice keys by lookup, `deterministic`; every judged line by extraction and a judge, `extract+score`; the checklist C1 through its two items only). It does **not** prove a live model reads these pages correctly or picks the right band: a scripted stand-in plays the page reader and returns the text an ideal reader would, and the run is never started. Reading the pages and grading them is what the live test is for.

## 7. What the live test should show for these sheets

If the live run works, the **deterministic** parts are exact and you can check them to the mark:

* **Multiple-choice lines (C1, C2, C3, C5)** are marked by key lookup: no model decides them. S9-001 and S9-006 get 4 of 4; S9-002 gets 3 (missed Q3); S9-003 gets 1 (only Q3 right); S9-004 gets 3 so far (Q1 awaits the operator).
* **The three parked sheets** are parked, for the reasons in the table, with no grade invented.

The **judged** parts (the written lines C4, C6 on the physics test; the checklist items C1a, C1b and the lines C2, C3 on the English test) are what the system is being tested on. Compare them to the reference marks. The teacher guide's own warning applies: the middle bands are the hard ones, so treat a miss of one band as normal and a miss of two or more as a finding. The full scoring plan is in [04](04-test-day-plan.md).

One part of the English test is **deterministic once its items are judged**, and can be checked to the mark: **C1 must equal C1a + C1b** for every student, whatever the judges decided about each item. `aeh results show` prints only each student's total and grade, so the line-by-line view comes from a read-only helper, which also does this check and exits 1 if a sum is wrong:

```bash
python docs/live-tests/sample-materials/show_criterion_marks.py --data-dir <folder> --cohort eng7-class --run <run id>
```

```
E7-004  (sub-…)   total 1   grade not yet   state provisional
    C1                1 / 2    evidence sum of C1a + C1b
      C1a             1        present (final)
      C1b             0        absent (final)
    C2                0 / 3    none (final)
    C3                0 / 3    none (final)
```

(The shape of the output, with the expected marks for E7-004; checked against a graded run with a composite built by the repository's test fixtures, not yet against a live run.) A C1 that differs from the sum, or a C1 sent to a judge on its own, is a defect, not a judgment call.
