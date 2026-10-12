"""The F-AUTHOR authoring-fixture corpus: thirteen teacher test descriptions (TC-AUTHOR-28).

Every authoring test replays against this corpus -- the fixture space M-AUTHOR is written
against, spanning the happy paths and the paths that need a human (test-plan §4.2). The
fixture set is the design delta's §5.1 matrix, one directory per fixture:

    fixtures/F-AUTHOR/AF-01 .. AF-13/   one or more teacher PDFs + an expected.toml
    fixtures/F-AUTHOR/recordings/      the model replies a run asks for (captured, not
                                       generated -- see that directory's README.md)

`expected.toml` states the *outcome class* the tests assert -- which items resolve, which
placeholder, whether the build publishes or is refused -- never exact wording: two runs of a
real model agree on structure, not prose (CT-AUTHOR-17's non-promise).

This is the `docs/live-tests/sample-materials/build_sample_materials.py` pattern: a committed
generator, committed outputs, byte-for-byte reproducible -- "the same script always produces
the same files, so a changed PDF in a review means a changed script". The rendering is NOT
reimplemented here: the typed pages are `harness.corpora.pdf_writer.typed_document` and the
one scanned fixture is `harness.corpora.scan.render_hand_page` over the committed glyph
table, both already byte-deterministic with stdlib only. The harness package is importable
because the script bootstraps the repo root onto `sys.path` -- it is a corpus generator that
lives beside its outputs, the one place the `harness/corpora/build.py` tree does not reach
(`_IN_TREE_GENERATED_TREES` exempts it from `--check`; TC-AUTHOR-28's census pins it instead
by re-running this script and diffing bytes).

Run it from anywhere:  python fixtures/F-AUTHOR/build_authoring_fixtures.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness.corpora import pdf_writer  # noqa: E402
from harness.corpora import scan as scan_module  # noqa: E402

#: Where the corpus is written. The script lives inside the corpus directory, so the default
#: root is the directory above this file -- the same tree a fresh clone checks out.
CORPUS_ROOT = Path(__file__).resolve().parent

#: Typed pages are wrapped to this column and cut at this many lines before a new page starts:
#: `typed_document` draws lines from y=752 downward with a 14 pt leading, so ~51 lines fit
#: above the bottom margin and 46 leaves the margin visibly clear.
WRAP_COLUMNS = 85
LINES_PER_PAGE = 46

#: Per-fixture seeds for the scan renderer. One seed per scanned page, fixed constants so the
#: committed bytes are a function of the data below and of nothing else (§4.6: assignment, not
#: luck).
SCAN_SEEDS = {"AF-10": 20261011}


def _wrap(text: str, width: int = WRAP_COLUMNS) -> list[str]:
    """Wrap one paragraph to `width` columns, breaking on spaces -- never mid-word."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if len(candidate) > width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def _typed_document(text: str) -> bytes:
    """One document's PDF: its text wrapped, cut into pages, rendered as typed paper."""
    lines = _wrap(text)
    pages = ["\n".join(lines[i:i + LINES_PER_PAGE])
             for i in range(0, len(lines), LINES_PER_PAGE)]
    return pdf_writer.typed_document(pages)


def _scan_document(af_id: str, text: str) -> bytes:
    """One scanned PDF: the text exists only as ink pixels -- no text layer to shortcut.

    The page assembly follows `scan._submission_pdf`'s object shape (catalog 1, page tree 2,
    font 3, then per page its content stream, the page and its image XObject) with a neutral
    form header: a teacher test description is a photocopy of a typed-then-photocopied sheet,
    not a consent-bearing submission booklet, so the F-SCAN consent header would be a lie
    about what the document is.
    """
    body_lines = _wrap(text.upper(), scan_module.CHARS_PER_LINE)
    page_specs = []
    for index in range(0, len(body_lines), 24):
        page_text = "\n".join(body_lines[index:index + 24])
        page_specs.append(scan_module.render_hand_page(
            page_text, legibility="legible", rng=random.Random(SCAN_SEEDS[af_id] + index)))
    number = 3
    page_bodies: list[pdf_writer.PdfObject] = []
    kids: list[bytes] = []
    for page_no, packed in enumerate(page_specs, start=1):
        number += 1
        content_number = number
        header = (
            b"BT /F1 11 Tf 36 750 Td (AF-10 - scanned test description) Tj ET\n"
            b"BT /F1 8 Tf 36 736 Td (Page " + str(page_no).encode("ascii") + b" of "
            + str(len(page_specs)).encode("ascii") + b" - photocopy, no text layer) Tj ET\n"
            b"q 540 0 0 640 36 40 cm /Im0 Do Q\n"
        )
        page_bodies.append(pdf_writer.stream_object(content_number, b"<< >>", header))
        number += 1
        image_number = number
        page_bodies.append(pdf_writer.image_object(
            image_number, scan_module.BODY_WIDTH, scan_module.BODY_HEIGHT, packed))
        number += 1
        page_number = number
        kids.append(str(page_number).encode("ascii") + b" 0 R")
        page_bodies.append(pdf_writer.PdfObject(
            page_number,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents "
            + str(content_number).encode("ascii") + b" 0 R /Resources << /Font << /F1 3 0 R >>"
            b" /XObject << /Im0 " + str(image_number).encode("ascii") + b" 0 R >> >> >>",
        ))
    objects = [
        pdf_writer.PdfObject(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        pdf_writer.PdfObject(2, b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count "
                             + str(len(page_specs)).encode("ascii") + b" >>"),
        pdf_writer.PdfObject(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        *page_bodies,
    ]
    return pdf_writer.build_pdf(objects)


# --- the fixture set (design delta §5.1) ------------------------------------------------------
#
# Every fixture's `expected` block is the outcome class the recorded and live tiers assert.
# The schema is documented in fixtures/F-AUTHOR/README.md; the census (TC-AUTHOR-28) loads
# each one with tomllib and refuses anything outside it.

AF01_TEST = """\
HIST7-ROME-01 - YEAR 7 HISTORY TEST: THE ROMAN EMPIRE

Answer all four questions. Write full sentences.

QUESTION 1 (4 MARKS)
Why did the Roman army build roads across the empire?
A correct answer mentions moving soldiers quickly, trade and supplies,
and spreading Roman control.

QUESTION 2 (4 MARKS)
What was aqueduct water used for in Roman towns?
A correct answer names drinking water, public baths and fountains.

QUESTION 3 (4 MARKS)
Give two reasons the empire was split into East and West.
A correct answer says the empire had grown too large to rule from one
city, and that defence was easier with two capitals.

QUESTION 4 (4 MARKS)
Name two things Roman towns built that we still use today, and say
what each was for.
A correct answer pairs a structure (roads, sewers, baths, walls) with
its purpose.

HOW I GRADE THIS TEST (FOR THE TEACHER MARKING AFTER ME)
Every question is marked on a 4-band scale, out of 4.
Band 4: accurate and complete, in the pupil's own words.
Band 3: mostly accurate; one part missing or vague.
Band 2: partly accurate; more wrong than right.
Band 1: little or no correct content.
Band 1 is the lowest mark and band 4 the highest. No half marks.

GRADE BOUNDARIES (OUT OF 16 POINTS)
A: 14-16. B: 10-13. C: 6-9. D: 0-5.
"""

AF02_PAPER = """\
GEO8-CLIMATE-01 - YEAR 8 GEOGRAPHY TEST: WORLD CLIMATE ZONES

Answer all three questions.

QUESTION 1 (4 MARKS)
Describe the weather a place on the equator has through the year.
A correct answer says hot all year and heavy rain most months.

QUESTION 2 (4 MARKS)
Why is the Sahara Desert dry? Give two reasons.
A correct answer says it is far from the sea, and that dry winds
blow across it most of the year.

QUESTION 3 (4 MARKS)
What is the difference between weather and climate?
A correct answer says weather is what happens day to day, climate is
the pattern over many years.
"""

AF02_MEMO = """\
GEO8-CLIMATE-01 - MARKING MEMO (FOR THE COVER TEACHER)

Every question is marked out of 4 on a 4-band scale.
Band 4: complete and accurate.
Band 3: one element missing.
Band 2: partially correct.
Band 1: incorrect or blank.
Band 1 is the lowest mark. No half marks.

GRADE BOUNDARIES (OUT OF 12 POINTS)
A: 11-12. B: 8-10. C: 5-7. D: 0-4.
"""

AF03_TEST = """\
SCI7-CELLS-01 - YEAR 7 SCIENCE TEST: CELLS (MULTIPLE CHOICE)

Circle one letter for each question. One mark each. No partial credit.

1. Which part of the cell controls its activities?
   A) cytoplasm  B) nucleus  C) cell wall  D) vacuole

2. Which part is found only in plant cells?
   A) nucleus  B) membrane  C) chloroplast  D) ribosome

3. What does the mitochondrion do?
   A) releases energy  B) stores water  C) makes protein  D) holds DNA

4. Which part stops a plant cell from bursting?
   A) cell wall  B) nucleus  C) chloroplast  D) cytoplasm

5. What is respiration?
   A) making food  B) releasing energy from food  C) taking in water
   D) removing waste

ANSWERS: 1-B, 2-C, 3-A, 4-D, 5-B

Total: 5 points.
GRADE BOUNDARIES: A: 5. B: 4. C: 3. D: 0-2.
"""

AF04_TEST = """\
ENG7-POETRY-01 - YEAR 7 ENGLISH: READING A POEM

Read the poem "The Sea" (handout). Then answer question 1.

QUESTION 1 (6 MARKS)
How does the poet make the sea feel alive? Use two quotations.

HOW I GRADE THIS ONE (MY OWN WORDS - FOR WHOEVER COVERS MY LESSONS)
I am not looking for a checklist here. Give the mark you would give
a thoughtful 12-year-old.
A top answer (band 4) picks two quotations that genuinely carry the
sea's moods, says something about the poet's word choices, and reads
like the pupil actually thought about it.
A good answer (band 3) picks usable quotations and says something
sensible about them, even if it is a bit flat.
A middle answer (band 2) quotes but mostly describes the story of the
poem rather than the language.
A weak answer (band 1) is a summary with no quotations, or quotations
with nothing said about them.
Band 1 is the lowest. No half marks.

GRADE BOUNDARIES (SINGLE CRITERION, OUT OF 6)
A: 5-6. B: 4. C: 2-3. D: 0-1.
"""

AF05_TEST = """\
HIST8-SOURCES-01 - YEAR 8 HISTORY: WORKING WITH SOURCES

QUESTION 1 (4 MARKS)
Look at Source A (the 1842 poster). What can a historian learn from it?
Award 1 point if the answer names the kind of source it is (a poster).
Award 1 point if the answer gives a date or dates it mentions.
Award 1 point if the answer quotes or points at specific words or
images in the source.
Award 1 point if the answer says one thing the source cannot tell us.

QUESTION 2 (4 MARKS)
Look at Source B (the mill owner's letter). Do the same:
1 point for naming the kind of source (a letter).
1 point for a date or dates.
1 point for quoting or pointing at specific words.
1 point for one thing it cannot tell us.

HOW I GRADE (FOR THE COVER TEACHER)
Each point is all-or-nothing: the thing is there or it is not.
The score is the points added up; there are no bands.

GRADE BOUNDARIES (OUT OF 8 POINTS)
A: 7-8. B: 5-6. C: 3-4. D: 0-2.
"""

AF06_PAPER = """\
GEO8-RIVERS-01 - YEAR 8 GEOGRAPHY TEST: RIVERS

Answer all four questions.

QUESTION 1 (3 MARKS)
Name the three stages of a river's course.
A correct answer names upper, middle and lower course.

QUESTION 2 (3 MARKS)
How does a waterfall wear itself back?
A correct answer says the soft rock under the hard rock is worn away
and the lip collapses.

QUESTION 3 (3 MARKS)
What is a meander and how does an oxbow lake form?
A correct answer describes the bend widening until the neck breaks.

QUESTION 4 (3 MARKS)
Why do rivers flood after long rain?
A correct answer says the ground is saturated and cannot soak up more.
"""

AF06_MEMO = """\
GEO8-RIVERS-01 - MARKING MEMO

QUESTION 1: mark out of 3 on a 3-band scale.
Band 3: all three stages named. Band 2: two named. Band 1: one or none.
Band 1 is the lowest.

QUESTION 2: mark out of 3 on a 3-band scale.
Band 3: the soft-rock-under-hard-rock idea, clearly told.
Band 2: erosion mentioned but the mechanism is vague.
Band 1: little or no correct content.

QUESTION 3: mark out of 3 on a 3-band scale.
Band 3: meander described and the neck-break story complete.
Band 2: one of the two halves right. Band 1: little or none.

GRADE BOUNDARIES (OUT OF 12 POINTS)
A: 10-12. B: 7-9. C: 4-6. D: 0-3.
"""

AF07_TEST = """\
MATH7-FRACTIONS-01 - YEAR 7 MATHS TEST: FRACTIONS

Show your working on every question.

QUESTION 1 (2 MARKS)
Work out: 2/3 + 1/4.

QUESTION 2 (2 MARKS)
Work out: 3/5 of 45.

QUESTION 3 (2 MARKS)
Simplify: 12/18.

QUESTION 4 (2 MARKS)
Put in order, smallest first: 2/5, 1/2, 7/10.

HOW I GRADE THIS TEST
Each question is marked out of 2 on a 2-band scale.
Band 2: correct answer with the method shown.
Band 1: wrong answer, or right answer with no working.
Band 1 is the lowest mark.

GRADE BOUNDARIES (OUT OF 8 POINTS)
A: 7-8. B: 5-6. C: 3-4. D: 0-2.
"""

AF08_TEST = """\
SCI6-CIRCUITS-01 - YEAR 6 SCIENCE TEST: CIRCUITS (MULTIPLE CHOICE)

Circle one letter for each question.

1. What does a circuit need to work?
   A) a gap  B) a complete loop  C) two batteries  D) a switch

2. Which material lets electricity through?
   A) plastic  B) wood  C) copper  D) glass

3. What does a switch do?
   A) stores electricity  B) makes the bulb brighter  C) breaks or
   completes the loop  D) slows the current

4. What happens to two bulbs in a series circuit when one is removed?
   A) both stay lit  B) both go out  C) the other gets brighter
   D) nothing changes

5. Which symbol stands for a bulb in a circuit diagram?
   A) a zigzag line  B) a circle with a cross  C) two parallel lines
   D) a triangle

ANSWERS: 1-B, 2-C, 4-B

Total: 5 points.
GRADE BOUNDARIES: A: 5. B: 4. C: 3. D: 0-2.
"""

AF09_TEST = """\
ENG8-ESSAY-01 - YEAR 8 ENGLISH: THE CHARLOTTE ESSAY

QUESTION 1 (10 MARKS)
How does the writer make Charlotte's arrival feel tense? Write one
paragraph.

HOW I GRADE THIS (PLEASE READ CAREFULLY BEFORE MARKING)
Mark the essay out of 10 on a 5-band scale. Band 5 is the best.
Band 5: tension techniques named with quotations and effect.
Band 4: techniques named, one quotation.
Band 3: some technique, mostly retelling.
Band 2: retelling only.
Band 1: barely relevant.

Actually, marking out of 10 makes the bands awkward - mark it out of
8 instead, on a 4-band scale, band 4 best, band 1 lowest.

GRADE BOUNDARIES (OUT OF 10 POINTS)
A: 8-10. B: 6-7. C: 4-5. D: 0-3.

Also: A starts at 12 points, not 8 - I keep changing my mind, use
whichever seems right when you mark it. And the bands should probably
be four, not five - or was it six? Please just use the standard set.
"""

AF11_TEST = """\
MATH8-ALGEBRA-01 - YEAR 8 MATHS TEST: ALGEBRA BASICS

Show your working.

QUESTION 1 (3 MARKS)
Simplify: 4a + 3a - a.

QUESTION 2 (3 MARKS)
Expand: 3(x + 4).

QUESTION 3 (3 MARKS)
Solve: 2x + 5 = 17.

QUESTION 4 (3 MARKS)
Factorise: 6x + 9.

HOW I GRADE THIS TEST
Each question is marked out of 3 on a 3-band scale.
Band 3: correct, method shown. Band 2: method right, slip in the
arithmetic. Band 1: wrong or blank.
Band 1 is the lowest mark.

TOTAL: 12 POINTS.
(GRADE BOUNDARIES: STILL TO DECIDE - THE DEPARTMENT HAS NOT AGREED
THE CUT-OFFS FOR THIS ONE YET. LEAVE THE GRADES OUT FOR NOW.)
"""

AF12_TEST = """\
LANG7-VOCAB-01 - YEAR 7 LANGUAGES TEST: VOCABULARY

SECTION A - CIRCLE THE RIGHT WORD (1 MARK EACH)

1. Which word means "dog"?  A) chat  B) chien  C) cheval  D) oiseau
2. Which word means "house"?  A) maison  B) mere  C) main  D) matin
3. Which word means "to eat"?  A) boire  B) dormir  C) manger  D) jouer

ANSWERS: 1-B, 2-A, 3-C

SECTION B - WRITE ONE SENTENCE (4 MARKS EACH)

4. Write a sentence saying what you ate yesterday.
   Band 4: correct verb tense and at least two food words.
   Band 3: verb tense right, one food word.
   Band 2: food words but the tense is wrong.
   Band 1: not a sentence, or unrelated.
   Band 1 is the lowest.

5. Write a sentence saying where you are going this weekend.
   Band 4: correct aller form and a place.
   Band 3: aller right, place vague.
   Band 2: place but aller wrong.
   Band 1: not a sentence, or unrelated.

GRADE BOUNDARIES (OUT OF 11 POINTS)
A: 9-11. B: 7-8. C: 4-6. D: 0-3.
"""

AF13_TEST = """\
HIST7-ROME-01 - YEAR 7 HISTORY TEST: THE ROMAN EMPIRE (SECOND DRAFT)

Answer all four questions. Write full sentences.

QUESTION 1 (4 MARKS)
Why did the Roman army build roads across the empire?
A correct answer mentions moving soldiers quickly, trade and supplies,
and spreading Roman control.

QUESTION 2 (4 MARKS)
What was aqueduct water used for in Roman towns?
A correct answer names drinking water, public baths and fountains.

QUESTION 3 (4 MARKS)
Why did Roman towns have public baths? Give two reasons.
A correct answer says bathing was a social habit and that the baths
showed the town's wealth and Roman identity.

QUESTION 4 (4 MARKS)
Name two things Roman towns built that we still use today, and say
what each was for.
A correct answer pairs a structure (roads, sewers, baths, walls) with
its purpose.
"""

AF13_MEMO = """\
HIST7-ROME-01 - GRADING NOTES (SECOND DRAFT - FOR THE COVER TEACHER)

Every question is marked on a 4-band scale, out of 4.
Band 4: accurate and complete, in the pupil's own words.
Band 3: mostly accurate; one part missing or vague.
Band 2: partly accurate; more wrong than right.
Band 1: little or no correct content.
Band 1 is the lowest mark and band 4 the highest. No half marks.

GRADE BOUNDARIES (OUT OF 16 POINTS)
A: 14-16. B: 10-13. C: 6-9. D: 0-5.
"""


def _expected(af: str, description: str, documents: list[str], outcome: str,
              placeholders: list[str], build: str, notes: str,
              retry_of: str | None = None, carry_over: str | None = None,
              review_answers: dict | None = None) -> str:
    """One fixture's expected.toml, as text -- the outcome class the tests assert."""
    def q(value: str) -> str:
        # TOML basic strings: backslash and quote must be escaped or the line breaks the
        # document -- AF-12's quoted description was the first value to prove it.
        return value.replace("\\", "\\\\").replace('"', '\\"')

    lines = [
        f'af = "{q(af)}"',
        f'description = "{q(description)}"',
        "documents = [" + ", ".join(f'"{q(d)}"' for d in documents) + "]",
        f'outcome = "{q(outcome)}"',
        "placeholders = [" + ", ".join(f'"{q(p)}"' for p in placeholders) + "]",
        f'build = "{q(build)}"',
    ]
    if retry_of is not None:
        lines.append(f'retry_of = "{q(retry_of)}"')
    if carry_over is not None:
        lines.append(f'carry_over = "{q(carry_over)}"')
    lines.append(f'notes = "{q(notes)}"')
    if review_answers:
        # The scripted review answers TC-REQ-136 drives every fixture's draft with (the
        # corpus contract the case bets on). A list value answers a repeated item id one
        # value per occurrence, in document order (AF-08's two unkeyed `key` items).
        lines.append("")
        lines.append("[review.answers]")
        for item, value in review_answers.items():
            if isinstance(value, list):
                rendered = "[" + ", ".join(_review_value(v) for v in value) + "]"
            else:
                rendered = _review_value(value)
            lines.append(f'{_review_value(item)} = {rendered}')
    return "\n".join(lines) + "\n"


def _review_value(value) -> str:
    """One [review.answers] value as TOML: json.dumps is `_toml_str`'s escaping, so a
    multi-line band set (AF-06's) stays a single valid basic string."""
    import json
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


#: The approving teacher every fixture's `approved_by` placeholder is scripted with -- the
#: same plain-language value the review-walk cases use.
REVIEW_TEACHER = "Sample-materials teacher"

#: The scripted review answers each publishing fixture's draft is completed with
#: (TC-REQ-136 drives every fixture's draft with these). Grounded in each document, not
#: invented: AF-06's band set answers the question its memo misses in the paper's own
#: framing; AF-07's model answer is the paper's worked division; AF-08's keys come from the
#: paper's ANSWERS line (items 3 and 5); AF-10's grade-D boundary is the scan's "BELOW 3
#: POINTS" -- below 3 means 0; AF-12's two judged sentences answer its two writing prompts.
#: The refused fixtures AF-09/AF-11 carry none -- their drafts never complete.
REVIEW_ANSWERS = {
    "approved_by": REVIEW_TEACHER,
}

AF06_ANSWERS = {
    "approved_by": REVIEW_TEACHER,
    "criterion Q4": "Band 1: little or no correct content (1 points);\n"
                    "Band 2: the ground is saturated and cannot soak up more (3 points)",
}

AF07_ANSWERS = {
    "approved_by": REVIEW_TEACHER,
    "model_answer": "2/3, by dividing the top and the bottom by 6.",
}

AF08_ANSWERS = {
    "approved_by": REVIEW_TEACHER,
    "key": ["C", "B"],
}

AF10_ANSWERS = {
    "approved_by": REVIEW_TEACHER,
    "grades D": 0,
}

AF12_ANSWERS = {
    "approved_by": REVIEW_TEACHER,
    "model_answer": ["Yesterday I ate bread and cheese.",
                     "This weekend I am going to the swimming pool."],
}


#: The corpus, in the design delta's §5.1 order. `documents` pairs filenames with their
#: body text; `scan=True` renders the body as ink pixels instead of typed text.
FIXTURES: dict[str, dict] = {
    "AF-01": {
        "description": "single document; bands throughout; happy path",
        "documents": [("hist7-rome-01-test-and-grading.pdf", AF01_TEST)],
        "expected": _expected(
            "AF-01", "single document; bands throughout; happy path",
            ["hist7-rome-01-test-and-grading.pdf"], "resolved", [], "publishes",
            "every criterion resolves to bands; zero placeholders",
            review_answers=dict(REVIEW_ANSWERS)),
    },
    "AF-02": {
        "description": "two documents: test paper + rubric memo; happy path",
        "documents": [("geo8-climate-01-test-paper.pdf", AF02_PAPER),
                      ("geo8-climate-01-marking-memo.pdf", AF02_MEMO)],
        "expected": _expected(
            "AF-02", "two documents: test paper + rubric memo; happy path",
            ["geo8-climate-01-test-paper.pdf", "geo8-climate-01-marking-memo.pdf"],
            "resolved", [], "publishes",
            "the rubric memo carries every question's grading",
            review_answers=dict(REVIEW_ANSWERS)),
    },
    "AF-03": {
        "description": "one document; MCQ section with the key stated",
        "documents": [("sci7-cells-01-mcq-test.pdf", AF03_TEST)],
        "expected": _expected(
            "AF-03", "one document; MCQ section with the key stated",
            ["sci7-cells-01-mcq-test.pdf"], "resolved", [], "publishes",
            "mcq lines with key in options, fully resolved",
            review_answers=dict(REVIEW_ANSWERS)),
    },
    "AF-04": {
        "description": "one document; grading in the teacher's own words",
        "documents": [("eng7-poetry-01-test.pdf", AF04_TEST)],
        "expected": _expected(
            "AF-04", "one document; grading in the teacher's own words",
            ["eng7-poetry-01-test.pdf"], "resolved", [], "publishes",
            "general criterion: derivation_description verbatim, derived bands",
            review_answers=dict(REVIEW_ANSWERS)),
    },
    "AF-05": {
        "description": "one document; evidence-checklist wording",
        "documents": [("hist8-sources-01-test.pdf", AF05_TEST)],
        "expected": _expected(
            "AF-05", "one document; evidence-checklist wording",
            ["hist8-sources-01-test.pdf"], "resolved", [], "publishes",
            "evidence_sum composite of binary aspect criteria",
            review_answers=dict(REVIEW_ANSWERS)),
    },
    "AF-06": {
        "description": "two documents; the rubric memo misses one question",
        "documents": [("geo8-rivers-01-test-paper.pdf", AF06_PAPER),
                      ("geo8-rivers-01-marking-memo.pdf", AF06_MEMO)],
        "expected": _expected(
            "AF-06", "two documents; the rubric memo misses one question",
            ["geo8-rivers-01-test-paper.pdf", "geo8-rivers-01-marking-memo.pdf"],
            "partial", ["criterion Q4"], "publishes",
            "Q4's criterion placeholders; Q1-Q3 resolve from the memo",
            review_answers=dict(AF06_ANSWERS)),
    },
    "AF-07": {
        "description": "one document; no model answers given",
        "documents": [("math7-fractions-01-test.pdf", AF07_TEST)],
        "expected": _expected(
            "AF-07", "one document; no model answers given",
            ["math7-fractions-01-test.pdf"], "partial", ["model_answer"],
            "publishes",
            "model_answer placeholders; the review walk completes to ready",
            review_answers=dict(AF07_ANSWERS)),
    },
    "AF-08": {
        "description": "one document; the MCQ key is only partly stated",
        "documents": [("sci6-circuits-01-mcq-test.pdf", AF08_TEST)],
        "expected": _expected(
            "AF-08", "one document; the MCQ key is only partly stated",
            ["sci6-circuits-01-mcq-test.pdf"], "partial", ["key"],
            "publishes",
            "key placeholders for the unkeyed items (3 and 5)",
            review_answers=dict(AF08_ANSWERS)),
    },
    "AF-09": {
        "description": "one document; contradictory grading description",
        "documents": [("eng8-essay-01-test-and-grading.pdf", AF09_TEST)],
        "expected": _expected(
            "AF-09", "one document; contradictory grading description",
            ["eng8-essay-01-test-and-grading.pdf"], "unresolved",
            ["criterion Q1", "model_answer", "grades A"], "refused",
            "the memo's contradiction is quoted verbatim with bands null, so the "
            "derivation-without-bands rejection exhausts the budget (the capture's "
            "honest class); the contested grade-A boundary and the unstated model "
            "answer stand as their own placeholders"),
    },
    "AF-10": {
        "description": "one document; scan-style, no text layer",
        "documents": [("geo7-mapwork-01-scanned-test.pdf", None)],
        "scan": True,
        "scan_text": """\
GEO7-MAPWORK-01 - GRID REFERENCES AND SCALE

QUESTION 1 (2 MARKS)
LOOK AT MAP SHEET 3. GIVE THE 6-FIGURE GRID REFERENCE OF THE CHURCH.

QUESTION 2 (2 MARKS)
MEASURE THE LENGTH OF THE RIVER FROM THE BRIDGE TO THE SEA, IN KM.
USE THE SCALE LINE.

QUESTION 3 (2 MARKS)
WHAT IS THE BEARING OF THE LIGHTHOUSE FROM THE HARBOUR?

HOW I GRADE THIS TEST
EACH QUESTION IS MARKED OUT OF 2 ON A 2-BAND SCALE.
BAND 2: THE ANSWER IS CORRECT, WITH THE METHOD SHOWN.
BAND 1: THE ANSWER IS WRONG OR THE METHOD IS MISSING.
BAND 1 IS THE LOWEST MARK.
TOTAL: 6 POINTS.
GRADE A: 5-6 POINTS. GRADE B: 4 POINTS. GRADE C: 3 POINTS.
GRADE D: BELOW 3 POINTS.

MODEL ANSWERS
Q1: 436218. Q2: ABOUT 12 KM. Q3: ABOUT 045 DEGREES.
""",
        "expected": _expected(
            "AF-10", "one document; scan-style, no text layer",
            ["geo7-mapwork-01-scanned-test.pdf"], "partial", ["grades D"], "publishes",
            "resolved via the transcriber path (FR-AUTHOR-02); the scan states grade D's "
            "boundary in words (BELOW 3 POINTS), not as a number, so FR-AUTHOR-08's "
            "never-invent rule leaves a per-grade placeholder (the capture's honest class)",
            review_answers=dict(AF10_ANSWERS)),
    },
    "AF-11": {
        "description": "one document; no grade boundaries stated",
        "documents": [("math8-algebra-01-test.pdf", AF11_TEST)],
        "expected": _expected(
            "AF-11", "one document; no grade boundaries stated",
            ["math8-algebra-01-test.pdf"], "partial", ["grades"], "refused",
            "[grades] placeholder; the build is refused until it is filled (FR-PKG-28)"),
    },
    "AF-12": {
        "description": 'one document; "circle the answer and explain"',
        "documents": [("lang7-vocab-01-test.pdf", AF12_TEST)],
        "expected": _expected(
            "AF-12", 'one document; "circle the answer and explain"',
            ["lang7-vocab-01-test.pdf"], "partial", ["model_answer"], "publishes",
            "mixed mcq and judged lines; the judged lines state no expected solution, "
            "so they carry the FR-AUTHOR-06 model_answer gap (a bands set does not "
            "determine a model answer)",
            review_answers=dict(AF12_ANSWERS)),
    },
    "AF-13": {
        "description": "AF-01's test reworded plus an edited grading memo; the re-draft flow",
        "documents": [("hist7-rome-01-test-second-draft.pdf", AF13_TEST),
                      ("hist7-rome-01-grading-notes-second-draft.pdf", AF13_MEMO)],
        "expected": _expected(
            "AF-13", "AF-01's test reworded plus an edited grading memo; the re-draft flow",
            ["hist7-rome-01-test-second-draft.pdf",
             "hist7-rome-01-grading-notes-second-draft.pdf"],
            "partial", [], "publishes",
            "the changed item's carried answers drop with a named reason; "
            "the unchanged items carry over, provisional until review confirms",
            retry_of="AF-01", carry_over="changed-item-dropped-unchanged-carried",
            review_answers=dict(REVIEW_ANSWERS)),
    },
}


def build(root: Path = CORPUS_ROOT) -> None:
    """Write the whole corpus: fixture dirs, PDFs, expected.toml files, READMEs."""
    (root / "recordings").mkdir(parents=True, exist_ok=True)
    for af_id, spec in FIXTURES.items():
        fixture_dir = root / af_id
        fixture_dir.mkdir(exist_ok=True)
        for filename, body in spec["documents"]:
            if spec.get("scan"):
                pdf_bytes = _scan_document(af_id, spec["scan_text"])
            else:
                pdf_bytes = _typed_document(body)
            (fixture_dir / filename).write_bytes(pdf_bytes)
        (fixture_dir / "expected.toml").write_bytes(spec["expected"].encode("utf-8"))
    (root / "recordings" / "README.md").write_bytes(_RECORDINGS_README.encode("utf-8"))
    (root / "README.md").write_bytes(_CORPUS_README.encode("utf-8"))


_CORPUS_README = """\
# fixtures/F-AUTHOR -- the authoring fixture corpus (TC-AUTHOR-28)

Thirteen teacher test descriptions, `AF-01`..`AF-13`, one directory each: the documents a
teacher would hand a colleague, plus an `expected.toml` stating the **outcome class** the
tests assert -- which items resolve, which placeholder, whether the build publishes or is
refused. The matrix is design delta §5.1; the double-honesty rule (test-plan §4.2) lives in
`recordings/`.

**Generated, not edited by hand.** Regenerate with:

    python fixtures/F-AUTHOR/build_authoring_fixtures.py

The generator is committed in this directory (the `build_sample_materials.py` pattern:
committed generator, committed outputs, stdlib only) and is byte-for-byte reproducible: a
changed PDF in a review means a changed script. The rendering itself is
`harness.corpora.pdf_writer.typed_document` (typed pages) and
`harness.corpora.scan.render_hand_page` (AF-10's scan) -- nothing here reimplements it.

This corpus is deliberately exempt from `python -m harness.corpora.build --check`
(`_IN_TREE_GENERATED_TREES` in `harness/corpora/build.py`): that check regenerates the
corpora its own module emits, and this corpus's generator lives here, not there. The pin is
TC-AUTHOR-28's census instead, which re-runs this script and diffs the bytes.

## expected.toml schema

| key | meaning |
|---|---|
| `af` | the fixture id, `AF-01`..`AF-13` |
| `description` | what the fixture exercises (§5.1's wording) |
| `documents` | the PDF filenames in this directory, in hand-in order |
| `outcome` | `resolved` (fully drafted), `partial` (named placeholders), `unresolved` (not converging after all attempts) |
| `placeholders` | the placeholder fields the outcome class expects (empty when `resolved`) |
| `build` | `publishes` (once any placeholders are filled at review) or `refused` (FR-PKG-28's gate) |
| `retry_of` | AF-13 only: the fixture this re-drafts |
| `carry_over` | AF-13 only: the carry-over outcome class |
| `notes` | one line for a human |
| `[review.answers]` | the scripted review answers the publishing fixtures' drafts complete with (TC-REQ-136); item id = value, a list answers a repeated id one value per occurrence in document order. Refused fixtures (AF-09, AF-11) carry none |

The recorded tier replays exact content through `RecordedFixtureProvider`; the live tier
(`@live`, real OpenRouter) asserts these outcome classes -- **never exact wording**: two runs
of a real model agree on structure, not prose (CT-AUTHOR-17's non-promise).
"""

_RECORDINGS_README = """\
# fixtures/F-AUTHOR/recordings -- captured, not generated

The model replies a complete authoring run asks for, in the single-tree shape the other
recording corpora use (`F-DEV-PIPE/recordings/`): one JSON document per `request_key`, named
`sha256-<hex>.json`, schema `aeh.prov/fixture/1`, written by `RecordedFixtureProvider`'s
`record()` half during a real run with `HARNESS_FIXTURE_DIR` pointing at this directory.
Coverage.json indexes the same keys in the `sha256:...` form; the files are written with a
dash (`sha256-<hex>.json`) because a colon is not legal in a filename on Windows.

The keys are sha256 over the assembled request, **including the prompt templates -- so they
do not exist until M-AUTHOR's prompts exist**. A recording captured before its prompt is a
key that no request will ever ask for. They are captured by the implementing stories
(#690 onward), once, from a live run.

Alongside the recordings sits `coverage.json`, written by the same capture pass:

    {"fallback_exercises": ["sha256:...", ...], "placeholder_exercises": ["sha256:...", ...]}

It names the recordings that exercise the two paths the double-honesty rule (test-plan §4.2)
demands: a **failing head-of-chain reply** (the fallback path must not need a live flake to
be exercised) and the **placeholder path** (an unresolved item). TC-AUTHOR-28's honesty
census refuses a corpus whose recordings replay successes only.
"""


def main() -> int:
    build()
    print(f"wrote {len(FIXTURES)} fixtures + READMEs under {CORPUS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())