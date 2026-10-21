"""The F-AUTHOR authoring-fixture corpus: twenty-three teacher test descriptions (TC-AUTHOR-28).

Every authoring test replays against this corpus -- the fixture space M-AUTHOR is written
against, spanning the happy paths and the paths that need a human (test-plan §4.2). AF-01..AF-13
are the package-authoring delta's §5.1 matrix; AF-14..AF-21 are the console-redesign delta's
§5.1 intake matrix, built by #753 ahead of the intake tier (#754); AF-22/AF-23 are the
console-clarity variants of the ENG7 sample test (#812). One directory per fixture:

    fixtures/F-AUTHOR/AF-01 .. AF-23/   one or more teacher documents + an expected.toml
    fixtures/F-AUTHOR/adversarial/      the refusal-matrix files that are not fixture-shaped
                                        (password-wrapped, .rtf, a magic-byte mismatch)
    fixtures/F-AUTHOR/rosters/          the class/cohort roster CSVs (TC-CONSOLE-65's inputs)
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

import io
import random
import struct
import sys
import zipfile
import zlib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness.corpora import pdf_writer  # noqa: E402
from harness.corpora import scan as scan_module  # noqa: E402


def _sample_materials():
    """`docs/live-tests/sample-materials/build_sample_materials.py`, loaded by path.

    AF-22 and AF-23 are the ENG7 sample test with its rubric's grade policy changed, and the
    sample-materials generator is where the ENG7 documents are declared -- so they are rendered
    there (`english_authoring_variants`) and written here, never re-typed (test plan
    `console_clarity_test_plan.md` §2.4: "generated in-tree by extending
    build_sample_materials.py")."""
    import importlib.util

    path = _REPO_ROOT / "docs" / "live-tests" / "sample-materials" / "build_sample_materials.py"
    spec = importlib.util.spec_from_file_location("build_sample_materials", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The console-clarity variants (#812): file name -> bytes, per fixture, in hand-in order.
ENG7_VARIANTS = {af: dict(sorted(files.items()))
                 for af, files in _sample_materials().english_authoring_variants().items()}

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


# ---------------------------------------------------------------------------
# The console-redesign intake fixtures (AF-14..AF-21, #753)
#
# AF-01..AF-13 above are PDFs the package-authoring delta's §5.1 matrix needs. The
# console-redesign delta (§3.1.1, ADR-46) adds a document-intake tier with its own fixture
# matrix (§5.1): the tier normalizes .docx/.txt/.pdf into one representation, so this
# section builds real .docx packages (stdlib `zipfile`), plain-text files, and the
# refusal-matrix stand-ins -- deterministic bytes, stdlib only, no third-party docx writer.
# ---------------------------------------------------------------------------

#: FR-AUTHOR-28's refusal sentences, verbatim from the console-redesign delta's table. The
#: corpus states them in `expected.toml` so the intake tests assert what the design pins
#: (test plan §4.3's exact-match property), and the census re-pins them against these
#: constants -- copy drift fails the corpus, not a test's private literal. The oversize
#: arm has no fixture here (10 MB of bytes is not a fixture to commit); its tests generate
#: the oversize file through the `HARNESS_AUTHOR_DOC_MAX_BYTES` knob instead.
LEGACY_FORMAT_REFUSAL = ("This file was saved in an older Word format. Open it in Word and "
                         "save it as .docx, then upload again.")
MISMATCH_REFUSAL = ("This file isn't what its name says. Rename it to match what it actually "
                    "is (.txt, .docx, or .pdf) and upload again.")
PASSWORD_REFUSAL = ("This document is password-protected. Remove the password and upload it "
                    "again.")
EMPTY_REFUSAL = "We couldn't find any text in this file."
OVERSIZE_REFUSAL = ("This file is larger than 10 MB. Split it or remove pictures to get it "
                    "under the limit.")
UNSUPPORTED_REFUSAL = ("We can read .docx, .txt and .pdf files. Save this as one of those and "
                       "upload it again.")

#: AF-14's content model: the blocks a .docx reader sees, as (kind, ...) tuples --
#: ("heading", level, text), ("paragraph", text), ("table", rows). The .docx rendering and
#: the .txt twin (AF-21's third document) both derive from this one model, which is what
#: makes the twin content-identical to AF-14's docx text by construction rather than by
#: hope (TC-AUTHOR-32's format-independence, TC-AUTHOR-38's cross-format carry-over).
AF14_TABLE_ROWS: list[list[str]] = [
    ["Band", "What an answer at this band looks like"],
    ["4", "Accurate and complete, in the pupil's own words."],
    ["3", "Mostly accurate; one part missing or vague."],
    ["2", "Partly accurate; more wrong than right."],
    ["1", "Little or no correct content."],
]

AF14_BLOCKS: list[tuple] = [
    ("heading", 1, "HIST7-ROME-01 - YEAR 7 HISTORY TEST: THE ROMAN EMPIRE"),
    ("paragraph", "Answer all four questions. Write full sentences."),
    ("heading", 2, "Question 1 (4 marks)"),
    ("paragraph", "Why did the Roman army build roads across the empire?"),
    ("paragraph", "A correct answer mentions moving soldiers quickly, trade and supplies, "
                  "and spreading Roman control."),
    ("heading", 2, "Question 2 (4 marks)"),
    ("paragraph", "What was aqueduct water used for in Roman towns?"),
    ("paragraph", "A correct answer names drinking water, public baths and fountains."),
    ("heading", 2, "Question 3 (4 marks)"),
    ("paragraph", "Give two reasons the empire was split into East and West."),
    ("paragraph", "A correct answer says the empire had grown too large to rule from one "
                  "city, and that defence was easier with two capitals."),
    ("heading", 2, "Question 4 (4 marks)"),
    ("paragraph", "Name two things Roman towns built that we still use today, and say what "
                  "each was for."),
    ("paragraph", "A correct answer pairs a structure (roads, sewers, baths, walls) with its "
                  "purpose."),
    ("heading", 2, "How I grade this test (for the teacher marking after me)"),
    ("paragraph", "Every question is marked on a 4-band scale, out of 4; band 4 is the "
                  "highest and band 1 the lowest. No half marks."),
    ("table", AF14_TABLE_ROWS),
    ("heading", 2, "Grade boundaries (out of 16 points)"),
    ("paragraph", "A: 14-16. B: 10-13. C: 6-9. D: 0-5."),
]

#: AF-15's content model: the same shapes plus an image block (carried as a real PNG part
#: and referenced by a real `<w:drawing>`) and an equation block (a real OMML
#: `<m:oMath>` run). The intake tier must not lose either silently -- TC-AUTHOR-34 (RS-02):
#: each is *named*, per location, with the nearest heading, not dropped.
AF15_BLOCKS: list[tuple] = [
    ("heading", 1, "SCI7-FORCES-01 - YEAR 7 SCIENCE TEST: FORCES AND MOTION"),
    ("paragraph", "Look at the circuit diagram. What happens to the bulb when the switch is "
                  "opened, and why?"),
    ("image",),
    ("heading", 2, "Question 2 (3 marks)"),
    ("paragraph", "Write the equation that links force, mass and acceleration, and say what "
                  "each symbol stands for."),
    ("equation", "F = m × a"),
    ("heading", 2, "Grade boundaries (out of 6 points)"),
    ("paragraph", "A: 5-6. B: 4. C: 3. D: 0-2."),
]

#: AF-21's pair: a .docx test and its .txt marking memo, handed in together. Both normalize
#: through the same intake (TC-AUTHOR-32), and the fixture's third document is AF-14's
#: content re-encoded as .txt (the cross-format twin TC-AUTHOR-38's journey carries over).
AF21_TEST_BLOCKS: list[tuple] = [
    ("heading", 1, "MUS8-INSTRUMENTS-01 - YEAR 8 MUSIC TEST: INSTRUMENT FAMILIES"),
    ("paragraph", "Answer all three questions. Write full sentences."),
    ("heading", 2, "Question 1 (3 marks)"),
    ("paragraph", "Name the family each of these belongs to: oboe, tuba, timpani."),
    ("paragraph", "A correct answer names woodwind, brass and percussion respectively."),
    ("heading", 2, "Question 2 (3 marks)"),
    ("paragraph", "Give one way a violin makes a louder sound, and say why it works."),
    ("paragraph", "A correct answer says bowing or plucking harder makes bigger vibrations."),
    ("heading", 2, "Question 3 (3 marks)"),
    ("paragraph", "Why does a drum with a larger skin sound lower?"),
    ("paragraph", "A correct answer says the larger skin vibrates more slowly."),
    ("heading", 2, "Grade boundaries (out of 9 points)"),
    ("paragraph", "A: 8-9. B: 6-7. C: 4-5. D: 0-3."),
]

AF21_MEMO_TEXT = """\
MUS8-INSTRUMENTS-01 - MARKING MEMO (FOR THE TEACHER MARKING AFTER ME)

Every question is marked out of 3 on a 3-band scale.
Band 3: correct and in the pupil's own words.
Band 2: correct in part; the idea is there but muddled.
Band 1: something written, but not the idea asked for.
Band 1 is the lowest mark and band 3 the highest. No half marks.

GRADE BOUNDARIES (OUT OF 9 POINTS)
A: 8-9. B: 6-7. C: 4-5. D: 0-3.
"""

#: AF-16: a .txt saved by Word as cp1252 (the Windows code page a teacher's machine still
#: defaults to), so the accented words are single bytes the UTF-8 decoder mangles. The
#: intake must detect the encoding, read the words intact, and say so once
#: (encoding_fallback, TC-AUTHOR-35 / RS-01). Deliberately no blank lines: the whole file
#: is one paragraph, so the case cannot pass by accident of block splitting.
AF16_TEXT = """\
LANG7-FOOD-01 - year seven languages: this week's café vocabulary test
The class has spent the week on food words in French, and this short check asks for the
words that carry an accent, spelled correctly: café, crêpe, déjà, élève, hôtel, très, août
and génie. Each pupil wrote the words on cards with the meaning on the back, so the recall
is honest. Award one point for each correctly accented word, up to eight, and one further
point for the sentence about a favourite meal that every pupil was asked to write; a good
example reads "Le samedi, je mange une crêpe avec ma famille." Keep the accent in "crêpe" -
a missing accent is a spelling mistake here, not a near miss, because the accented form is
what the week practised.
"""

#: AF-17: a .txt with no heading structure at all -- questions live inside running prose.
#: The intake must still produce blocks, guess the outline, and warn (structure_guessed,
#: TC-AUTHOR-36); the review walk then asks the teacher to confirm it.
AF17_TEXT = """\
A year six history test about the Great Fire of London, written the way it will be read
out: there are no headings in this file, only running prose, and the questions are
sentences inside it.

The first question asks the pupils to name the year the Great Fire started and the bakery
it began in, on Pudding Lane. The second question asks for two reasons the fire spread so
quickly through the wooden houses. The third question asks what Samuel Pepys' diary tells
us that a painting of the fire cannot.

Marking: award two points per question where the answer names the thing asked for in the
pupil's own words, and nothing for a guess. Out of six points, an A is five or six, a B is
four, a C is two or three, and a D is less.
"""

#: AF-19: plain .txt bytes wearing a .docx name (the file a pupil's home setup produces
#: when "save as" keeps the old name). The intake reads the magic bytes, not the extension,
#: and refuses with the mismatch sentence (TC-AUTHOR-37b).
AF19_TEXT = """\
MATH6-TIMES-TABLES-01 - YEAR 6 MATHS: TIMES TABLES PRACTICE

Answer every question. No calculator.

7 x 8 =        6 x 9 =        12 x 4 =
11 x 7 =       9 x 6 =        8 x 8 =

Complete the sequence: 3, 6, 9, __, __, __.
"""

#: AF-18's single OLE stream. The intake refuses the file on its magic bytes before any of
#: this text is read, so the filler is deliberately not the text of any real test.
_LEGACY_DOC_STREAM = (
    "Legacy Word document filler. The intake refuses this file on its OLE magic before any "
    "of this text is read, so the filler is deliberately not the real text of any test. "
    "A teacher's old departmental folder is full of files exactly like this one: saved as "
    ".doc in 2009, still handed round, still refused at the door by a tier that reads only "
    "what the bytes say. "
)

#: The adversarial set's password-protected .docx: a real password-protected Office file is
#: a Compound File Binary container holding an EncryptedPackage stream, wearing the .docx
#: extension -- OLE bytes, not a zip. The stream here is the honest shape of that: the
#: 4-byte little-endian length prefix the real format carries, then filler.
_ENCRYPTED_PACKAGE_STREAM = (
    struct.pack("<I", 256)
    + b"Encrypted-package filler: a password-protected Office file stores its payload in an "
      b"EncryptedPackage stream inside a Compound File Binary container, so the bytes a "
      b"teacher uploads are OLE, not a zip. The intake refuses this on the magic before "
      b"trying to open a package it cannot decrypt. "
)

#: The adversarial .rtf: a real format a teacher does still save as, outside the three the
#: intake reads -- the unsupported-extension arm (TC-AUTHOR-37f), not a magic mismatch.
_RTF_TEXT = """\
{\\rtf1\\ansi\\deff0
{\\fonttbl{\\f0 Times New Roman;}}
\\f0\\fs24 HIST7-ROME-01 - YEAR 7 HISTORY TEST: THE ROMAN EMPIRE\\par
This reading list was saved as rich text. The intake reads .docx, .txt and .pdf files, so
this one is refused with the three-formats sentence before a word of it is read.\\par
}
"""

#: The adversarial magic-mismatch arm in the other direction: real PDF bytes under a .docx
#: name (a file saved through a PDF printer that kept the old extension). Rendered by the
#: same typed-PDF writer the AF-01..13 fixtures use, so the bytes are a genuine PDF.
_PDF_MAGIC_TEXT = """\
SCI5-GROUPING-01 - YEAR 5 SCIENCE TEST: GROUPING MATERIALS

This file was written as a PDF and given a .docx name. The intake reads the magic bytes,
not the extension, and refuses it with the rename sentence -- the same sentence AF-19's
.txt-in-a-.docx name earns, because both are the mismatch arm of the refusal table.
"""


def block_text(block: tuple) -> str:
    """One content-model block as the plain text a .txt rendering of it carries.

    The model is the single source of the .docx XML and of AF-21's .txt twin, so this
    function is also the contract TC-AUTHOR-32 checks: the docx's table block text is one
    row per line with tab-separated cells -- the same string the twin's table chunk carries.
    """
    kind = block[0]
    if kind == "heading":
        return block[2]
    if kind in ("paragraph", "equation"):
        return block[1]
    if kind == "table":
        return "\n".join("\t".join(row) for row in block[1])
    if kind == "image":
        return ""
    raise ValueError(f"unknown content-model block kind {kind!r}")


def blocks_to_plain_text(blocks: list[tuple]) -> str:
    """A content model as .txt: one block per line-group, a blank line between blocks.

    This is the shape the AF-21 twin is committed as, and the shape a plain-text intake
    splits on blank lines -- so the twin's block texts come out equal to the .docx's, which
    is the format-independence property TC-AUTHOR-32 and the cross-format carry-over
    TC-AUTHOR-38 both stand on.
    """
    return "\n\n".join(t for t in (block_text(b) for b in blocks) if t) + "\n"


def _png_bytes() -> bytes:
    """A tiny deterministic PNG: the figure AF-15's questions refer to.

    IHDR + one compressed IDAT + IEND, checksums via `zlib.crc32` -- stdlib only, and a
    two-tone image rather than a blank rectangle so a reader that decodes it sees a figure,
    not a placeholder.
    """
    width, height = 24, 16
    top, bottom = bytes((31, 73, 125)), bytes((192, 208, 224))
    rows = b"".join(b"\x00" + (top if y < height // 2 else bottom) * width
                    for y in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (len(payload).to_bytes(4, "big") + tag + payload
                + zlib.crc32(tag + payload).to_bytes(4, "big"))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


#: Fixed ZipInfo timestamps: a zip stores a local timestamp per member, so the default
#: ("now") would make the corpus unreproducible by construction. One shared epoch, ZIP_STORED
#: (no compression: deterministic, and the bytes are small), explicit create_system so the
#: same script produces identical bytes on any OS.
_ZIP_EPOCH = (2026, 1, 1, 0, 0, 0)


def _zip_parts(parts: list[tuple[str, bytes]]) -> bytes:
    """One OOXML package: a deterministically-ordered, stored (uncompressed) zip."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, data in parts:
            info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_W_DOCUMENT_OPEN = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document'
    ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    ' xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
    ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
    ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    ' xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<w:body>'
)
_W_DOCUMENT_CLOSE = (
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>'
)
_W_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)
_W_RELS_IMAGE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/image" Target="media/image1.png"/></Relationships>'
)
_W_IMAGE_PARAGRAPH = (
    '<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
    '<wp:extent cx="2286000" cy="1524000"/><wp:docPr id="1" name="Figure 1"/>'
    '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="Figure 1"/><pic:cNvPicPr/></pic:nvPicPr>'
    '<pic:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
    '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="2286000" cy="1524000"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
    '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
)
_W_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:style w:type="paragraph" w:styleId="Heading1">'
    '<w:name w:val="Heading 1"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
    '<w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading2">'
    '<w:name w:val="Heading 2"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:outlineLvl w:val="1"/></w:pPr>'
    '<w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>'
    '</w:styles>'
)


def _content_types(with_png: bool) -> str:
    png = '<Default Extension="png" ContentType="image/png"/>' if with_png else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            + png +
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '</Types>')


def _w_paragraph(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return (f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{_xml_escape(text)}</w:t></w:r></w:p>')


def _w_table(rows: list[list[str]]) -> str:
    trs = []
    for row in rows:
        tcs = "".join(
            f'<w:tc><w:p><w:r><w:t xml:space="preserve">{_xml_escape(cell)}</w:t></w:r></w:p>'
            '</w:tc>' for cell in row)
        trs.append(f"<w:tr>{tcs}</w:tr>")
    return ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
            + "".join(trs) + "</w:tbl>")


def _w_equation(text: str) -> str:
    return ('<w:p><m:oMath><m:r><m:t xml:space="preserve">'
            f'{_xml_escape(text)}</m:t></m:r></m:oMath></w:p>')


def _docx_document(blocks: list[tuple]) -> bytes:
    """A real .docx package over a content model: styles, a table, an image, an OMML equation.

    The heading paragraphs reference the style IDs this same package's styles.xml defines
    (`Heading1`/`Heading2` mapped to the names "Heading 1"/"Heading 2") -- a .docx reader
    matches heading styles by *name*, so a package that named the style differently would
    normalize every heading to a plain paragraph.
    """
    has_image = any(b[0] == "image" for b in blocks)
    parts: list[str] = []
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            parts.append(_w_paragraph(block[2], f"Heading{block[1]}"))
        elif kind == "paragraph":
            parts.append(_w_paragraph(block[1]))
        elif kind == "table":
            parts.append(_w_table(block[1]))
        elif kind == "image":
            parts.append(_W_IMAGE_PARAGRAPH)
        elif kind == "equation":
            parts.append(_w_equation(block[1]))
        else:
            raise ValueError(f"unknown content-model block kind {kind!r}")
    document_xml = _W_DOCUMENT_OPEN + "".join(parts) + _W_DOCUMENT_CLOSE
    zip_parts = [
        ("[Content_Types].xml", _content_types(has_image).encode("utf-8")),
        ("_rels/.rels", _W_ROOT_RELS.encode("utf-8")),
        ("word/document.xml", document_xml.encode("utf-8")),
        ("word/styles.xml", _W_STYLES.encode("utf-8")),
    ]
    if has_image:
        zip_parts.append(("word/_rels/document.xml.rels", _W_RELS_IMAGE.encode("utf-8")))
        zip_parts.append(("word/media/image1.png", _png_bytes()))
    return _zip_parts(zip_parts)


_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_CFB_FREE = 0xFFFFFFFF
_CFB_END = 0xFFFFFFFE
_CFB_FAT_SECT = 0xFFFFFFFD
_CFB_SECTOR = 512


def _cfb_document(streams: list[tuple[str, bytes]]) -> bytes:
    """A minimal Compound File Binary container holding the named streams.

    This is the honest shape of the two OLE-arm fixtures: a legacy `.doc` is a CFB whose
    payload lives in a `WordDocument` stream, and a password-protected Office file is a CFB
    holding an `EncryptedPackage` stream -- both refused on the same `D0 CF 11 E0 A1 B1 1A E1`
    magic, before any stream is read. The stand-in is deliberately minimal (one FAT sector,
    one directory sector, one data sector per stream, small streams in regular sectors): a
    structural validator would want a mini-FAT for sub-4096-byte streams, but the intake
    refuses these files on the magic long before container details matter, and the filler
    text inside says what the file stands in for.
    """
    assert 1 <= len(streams) <= 3, "the minimal directory holds a root plus at most 3 streams"
    streams = [(name, data.encode("utf-8") if isinstance(data, str) else data)
               for name, data in streams]

    # Sector 0: the FAT. Sector 1: the directory. Sectors 2..: one data sector per stream.
    fat = [_CFB_FAT_SECT, _CFB_END] + [_CFB_END] * len(streams)
    fat_bytes = struct.pack("<128I", *(fat + [_CFB_FREE] * (128 - len(fat))))

    def entry(name: str, kind: int, child: int, start: int, size: int) -> bytes:
        encoded = name.encode("utf-16-le") + b"\x00\x00"
        assert len(encoded) <= 64, f"CFB entry name too long: {name!r}"
        return (encoded + b"\x00" * (64 - len(encoded))
                + struct.pack("<HBBIII16sI8s8sIQ", len(encoded), kind, 1,
                              _CFB_FREE, _CFB_FREE, child, b"\x00" * 16, 0,
                              b"\x00" * 8, b"\x00" * 8, start, size))

    root = entry("Root Entry", 5, 1 if streams else _CFB_FREE, _CFB_END, 0)
    directory = root + b"".join(
        entry(name, 2, _CFB_FREE, 2 + index, len(data))
        for index, (name, data) in enumerate(streams))
    directory += b"\x00" * (_CFB_SECTOR - len(directory))
    assert len(directory) == _CFB_SECTOR

    data_sectors = b"".join(
        (data[:_CFB_SECTOR] + b"\x00" * _CFB_SECTOR)[:_CFB_SECTOR] for _, data in streams)

    header = b"".join([
        _CFB_MAGIC,
        b"\x00" * 16,                                    # CLSID
        struct.pack("<HHHH", 0x003E, 0x0003, 0xFFFE, 0x0009),  # minor, major, byte order,
                                                         # sector shift (512-byte sectors)
        struct.pack("<H", 0x0006),                       # mini sector shift (64 bytes)
        b"\x00" * 6,                                     # reserved
        struct.pack("<IIIIII", 0, 1, 1, 0, 0x00001000, _CFB_END),
        struct.pack("<II", 0, _CFB_END),                 # mini FAT count, first DIFAT sector
        struct.pack("<I", 0),                            # number of DIFAT sectors (none)
        struct.pack("<109I", 0, *([_CFB_FREE] * 108)),   # DIFAT: the FAT lives at sector 0
    ])
    assert len(header) == _CFB_SECTOR
    return header + fat_bytes + directory + data_sectors


#: The adversarial intake set (test plan §3.1, TC-AUTHOR-37's matrix): the refusal arms that
#: are not fixture-shaped enough for a numbered directory. Each entry states, in
#: `adversarial/expected.toml`, the FR-AUTHOR-28 sentence the intake must refuse it with.
ADVERSARIAL: dict = {
    "documents": [
        ("encrypted-test.docx", [("EncryptedPackage", _ENCRYPTED_PACKAGE_STREAM)], "cfb"),
        ("reading-list.rtf", _RTF_TEXT, "txt"),
        ("hist8-sources-01-test.docx", _PDF_MAGIC_TEXT, "pdf"),
    ],
}

#: `adversarial/expected.toml`: one `[[file]]` table per entry, naming the file and the exact
#: FR-AUTHOR-28 teacher sentence the intake refuses it with -- pinned in the corpus, not in a
#: test's private literal, so copy drift fails the census. The numbered refusal arms (legacy
#: .doc, renamed .docx, empty) live in the AF-18/19/20 directories; these are the arms whose
#: file shape belongs to no fixture directory.
ADVERSARIAL_EXPECTED = f"""\
# The adversarial intake set: the refusal-matrix arms whose file shape belongs to no numbered
# fixture (test plan §3.1, TC-AUTHOR-37). Each entry names a file in this directory and the
# exact FR-AUTHOR-28 teacher sentence the intake refuses it with.

[[file]]
name = "encrypted-test.docx"
looks_like = "a password-protected .docx: a Compound File Binary container holding an EncryptedPackage stream, wearing the .docx extension (that is what an encrypted docx actually is -- OLE bytes, not a zip)"
refusal = "{PASSWORD_REFUSAL}"

[[file]]
name = "reading-list.rtf"
looks_like = "rich text; .rtf is outside the three formats the intake reads"
refusal = "{UNSUPPORTED_REFUSAL}"

[[file]]
name = "hist8-sources-01-test.docx"
looks_like = "PDF magic bytes under a .docx name (saved through a PDF printer that kept the old extension)"
refusal = "{MISMATCH_REFUSAL}"
"""

#: The roster CSVs (TC-CONSOLE-65's inputs, and the intake tests' mixed-set context). The
#: names are the same synthetic stem style `tests/support/roster.py` generates -- never real
#: names, so the corpus cannot leak one. The valid roster carries the `console_world` seed
#: cohort's three students (`c-ts48`), so a case written against it needs no rewrite when the
#: console tests land. The malformed file carries one defect per shape that makes a roster
#: file suspect: a duplicated name (line 3 -- the roster reader accepts a shared name;
#: deciding that two refs are one student is the cohort layer's call, `aeh.orch.cohorts`),
#: a row with a ref but no name (line 4 -- refused by the reader, naming the line), a fully
#: blank row (skipped), and one valid row.
ROSTERS: list[tuple[str, str]] = [
    ("console-world-3-students.csv",
     "full_name,student_ref\n"
     "Alvenn Ashcombe,ref-sub-c-ts48-01\n"
     "Kestrile Larkspire,ref-sub-c-ts48-02\n"
     "Torvelle Whitmarsh,ref-sub-c-ts48-03\n"),
    ("console-world-malformed.csv",
     "full_name,student_ref\n"
     "Alvenn Ashcombe,ref-sub-c-ts48-01\n"
     "Alvenn Ashcombe,ref-sub-c-ts48-02\n"
     ",ref-sub-c-ts48-02\n"
     "\n"
     "Torvelle Whitmarsh,ref-sub-c-ts48-03\n"),
]


def _expected(af: str, description: str, documents: list[str], outcome: str,
              placeholders: list[str], build: str, notes: str,
              refusal: str | None = None, warnings: list[str] | None = None,
              formats: list[str] | None = None, table_rows: list[list[str]] | None = None,
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
    if refusal is not None:
        # FR-AUTHOR-28's exact teacher sentence (test plan §4.3: exact-match, so copy drift
        # fails). Present iff the outcome is `refused` -- an intake refusal, not a draft.
        lines.append(f'refusal = "{q(refusal)}"')
    if warnings is not None:
        # The IntakeWarning codes the outcome class requires to be present (§3.1.1's
        # vocabulary). Presence, not exhaustiveness: a reader may add codes the design's
        # table does not name.
        lines.append("warnings = [" + ", ".join(f'"{q(w)}"' for w in warnings) + "]")
    if formats is not None:
        # One source format per document, aligned with `documents` (§3.1.1's
        # NormalizedDocument.source_format domain: docx | txt | pdf).
        lines.append("format = [" + ", ".join(f'"{q(f)}"' for f in formats) + "]")
    if table_rows is not None:
        # AF-14 only: the rubric table's rows, carried verbatim so TC-AUTHOR-33 asserts the
        # normalized table blocks against what the fixture declares (json.dumps is TOML's
        # basic-string escaping, per _review_value).
        lines.append("table_rows = [" + ", ".join(_review_value(r) for r in table_rows) + "]")
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
}

AF12_ANSWERS = {
    "approved_by": REVIEW_TEACHER,
    "model_answer": ["Yesterday I ate bread and cheese.",
                     "This weekend I am going to the swimming pool."],
}


#: The corpus, in the design deltas' §5.1 order. Each `documents` entry pairs a filename
#: with its body and, for the intake fixtures, the writer that renders it: "pdf" (typed
#: pages, the default), "scan" (AF-10's ink pixels, via the fixture-level `scan` flag),
#: "docx" (a real OOXML package over a content model), "txt" / "txt-cp1252" (plain text in
#: the named encoding), "cfb" (an OLE container over named streams), "raw" (bytes written
#: verbatim), "empty" (zero bytes). `scan=True` renders the body as ink pixels instead of
#: typed text.
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
            ["geo7-mapwork-01-scanned-test.pdf"], "resolved", [], "publishes",
            "resolved via the transcriber path (FR-AUTHOR-02); the scan states grade D's "
            "boundary in words (BELOW 3 POINTS), not as a number, but D is the lowest "
            "grade, whose floor is always 0 and filled in, never asked (FR-AUTHOR-32)",
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
    # -- the console-redesign intake matrix (§3.1.1 / §5.1; #753, ahead of #754) -----------
    "AF-14": {
        "description": "one document; .docx with a real rubric table; happy path",
        "documents": [("hist7-rome-01-test-and-grading.docx", AF14_BLOCKS, "docx")],
        "expected": _expected(
            "AF-14", "one document; .docx with a real rubric table; happy path",
            ["hist7-rome-01-test-and-grading.docx"], "resolved", [], "publishes",
            "the rubric table is carried as table blocks, its cells matching table_rows "
            "(TC-AUTHOR-33); drafting resolves",
            formats=["docx"], table_rows=AF14_TABLE_ROWS,
            review_answers=dict(REVIEW_ANSWERS)),
    },
    "AF-15": {
        "description": "one document; .docx with an image and an OMML equation",
        "documents": [("sci7-forces-01-figure-test.docx", AF15_BLOCKS, "docx")],
        "expected": _expected(
            "AF-15", "one document; .docx with an image and an OMML equation",
            ["sci7-forces-01-figure-test.docx"], "resolved", [], "publishes",
            "the image and the equation are named per location, not lost (TC-AUTHOR-34, "
            "RS-02); the draft still builds",
            warnings=["image_not_carried", "equation_not_carried"], formats=["docx"],
            review_answers=dict(REVIEW_ANSWERS)),
    },
    "AF-16": {
        "description": "one document; .txt written cp1252 with accented words",
        "documents": [("lang7-food-01-cafe-vocabulary.txt", AF16_TEXT, "txt-cp1252")],
        "expected": _expected(
            "AF-16", "one document; .txt written cp1252 with accented words",
            ["lang7-food-01-cafe-vocabulary.txt"], "resolved", [], "publishes",
            "cp1252 detected and named, the accented words intact (TC-AUTHOR-35, RS-01)",
            warnings=["encoding_fallback"], formats=["txt"],
            review_answers=dict(REVIEW_ANSWERS)),
    },
    "AF-17": {
        "description": "one document; .txt with no heading structure",
        "documents": [("hist6-great-fire-01-prose-test.txt", AF17_TEXT, "txt")],
        "expected": _expected(
            "AF-17", "one document; .txt with no heading structure",
            ["hist6-great-fire-01-prose-test.txt"], "resolved", [], "publishes",
            "no headings, so the outline is guessed and warned; the review asks the teacher "
            "to confirm it (TC-AUTHOR-36)",
            warnings=["structure_guessed"], formats=["txt"],
            review_answers=dict(REVIEW_ANSWERS)),
    },
    "AF-18": {
        "description": "one document; legacy .doc (an OLE container)",
        "documents": [("geo6-mapwork-01-legacy.doc", [("WordDocument", _LEGACY_DOC_STREAM)],
                       "cfb")],
        "expected": _expected(
            "AF-18", "one document; legacy .doc (an OLE container)",
            ["geo6-mapwork-01-legacy.doc"], "refused", [], "refused",
            "refused on the OLE magic before any provider call (TC-AUTHOR-37a)",
            refusal=LEGACY_FORMAT_REFUSAL),
    },
    "AF-19": {
        "description": "one document; .txt bytes renamed .docx (magic mismatch)",
        "documents": [("math6-times-tables-01.docx", AF19_TEXT, "raw")],
        "expected": _expected(
            "AF-19", "one document; .txt bytes renamed .docx (magic mismatch)",
            ["math6-times-tables-01.docx"], "refused", [], "refused",
            "the bytes are plain text, the name says .docx: refused with the rename guidance "
            "(TC-AUTHOR-37b)",
            refusal=MISMATCH_REFUSAL),
    },
    "AF-20": {
        "description": "one document; zero-byte .docx (empty file)",
        "documents": [("sci5-grouping-01-empty.docx", None, "empty")],
        "expected": _expected(
            "AF-20", "one document; zero-byte .docx (empty file)",
            ["sci5-grouping-01-empty.docx"], "refused", [], "refused",
            "zero bytes; refused with the no-text sentence (TC-AUTHOR-37d)",
            refusal=EMPTY_REFUSAL),
    },
    "AF-21": {
        "description": "mixed set: .docx test + .txt memo, plus AF-14's content as .txt",
        "documents": [("mus8-instruments-01-test.docx", AF21_TEST_BLOCKS, "docx"),
                      ("mus8-instruments-01-marking-memo.txt", AF21_MEMO_TEXT, "txt"),
                      ("hist7-rome-01-test-and-grading.txt",
                       blocks_to_plain_text(AF14_BLOCKS), "txt")],
        "expected": _expected(
            "AF-21", "mixed set: .docx test + .txt memo, plus AF-14's content as .txt",
            ["mus8-instruments-01-test.docx", "mus8-instruments-01-marking-memo.txt",
             "hist7-rome-01-test-and-grading.txt"], "resolved", [], "publishes",
            "both formats normalize together, and the third document is AF-14's content "
            "re-encoded as .txt -- the cross-format twin TC-AUTHOR-32/TC-AUTHOR-38 assert "
            "against (TC-E2E-11's carry-over)",
            formats=["docx", "txt", "txt"], review_answers=dict(REVIEW_ANSWERS)),
    },
    # -- the console-clarity variants (console_clarity_test_plan.md §2.4; #812) --------------
    # The four ENG7-READ-01 PDFs with only the rubric's grade policy changed, rendered by the
    # sample-materials generator. Out of 8 points; the shipped package's answer is pass = 6.
    "AF-22": {
        "description": "the four ENG7 PDFs; the rubric omits the grade table",
        "documents": [(name, data, "raw") for name, data in ENG7_VARIANTS["AF-22"].items()],
        "expected": _expected(
            "AF-22", "the four ENG7 PDFs; the rubric omits the grade table",
            list(ENG7_VARIANTS["AF-22"]), "partial", ["grades"], "publishes",
            "no grade table at all: the [grades] gap is asked as 'What is the passing score "
            "for this test?' (whole number 1..8), and the answer builds pass / not yet = 0 "
            "(FR-AUTHOR-32, TC-AUTHOR-44, TC-UI-28)",
            formats=["pdf"] * 4,
            review_answers={"approved_by": REVIEW_TEACHER, "grades": 6}),
    },
    "AF-23": {
        "description": "the four ENG7 PDFs; the rubric names pass with no boundary",
        "documents": [(name, data, "raw") for name, data in ENG7_VARIANTS["AF-23"].items()],
        "expected": _expected(
            "AF-23", "the four ENG7 PDFs; the rubric names pass with no boundary",
            list(ENG7_VARIANTS["AF-23"]), "partial", ["grades pass"], "publishes",
            "the grades are named, pass has no boundary: the [grades pass] gap is asked as "
            "'What is the lowest total score that earns 'pass'?' (whole number 1..8); "
            "not yet is the lowest grade, floor 0, never asked (FR-AUTHOR-32, TC-AUTHOR-44)",
            formats=["pdf"] * 4,
            review_answers={"approved_by": REVIEW_TEACHER, "grades pass": 6}),
    },
}


def _document_bytes(af_id: str, spec: dict, writer: str, payload) -> bytes:
    """One document's bytes, by writer tag (see FIXTURES' comment for the tags)."""
    if writer == "pdf":
        return _typed_document(payload)
    if writer == "scan":
        return _scan_document(af_id, spec["scan_text"])
    if writer == "docx":
        return _docx_document(payload)
    if writer == "txt":
        return payload.encode("utf-8")
    if writer == "txt-cp1252":
        return payload.encode("cp1252")
    if writer == "cfb":
        return _cfb_document(payload)
    if writer == "raw":
        return payload if isinstance(payload, bytes) else payload.encode("utf-8")
    if writer == "empty":
        return b""
    raise ValueError(f"unknown fixture writer {writer!r}")


def build(root: Path = CORPUS_ROOT) -> None:
    """Write the whole corpus: fixture dirs, documents, expected.toml files, READMEs."""
    (root / "recordings").mkdir(parents=True, exist_ok=True)
    for af_id, spec in FIXTURES.items():
        fixture_dir = root / af_id
        fixture_dir.mkdir(exist_ok=True)
        for entry in spec["documents"]:
            filename, payload = entry[0], entry[1]
            writer = entry[2] if len(entry) > 2 else ("scan" if spec.get("scan") else "pdf")
            (fixture_dir / filename).write_bytes(
                _document_bytes(af_id, spec, writer, payload))
        (fixture_dir / "expected.toml").write_bytes(spec["expected"].encode("utf-8"))
    adversarial = root / "adversarial"
    adversarial.mkdir(exist_ok=True)
    for filename, payload, writer in ADVERSARIAL["documents"]:
        (adversarial / filename).write_bytes(
            _document_bytes("adversarial", {}, writer, payload))
    (adversarial / "expected.toml").write_bytes(ADVERSARIAL_EXPECTED.encode("utf-8"))
    rosters = root / "rosters"
    rosters.mkdir(exist_ok=True)
    for filename, text in ROSTERS:
        (rosters / filename).write_bytes(text.encode("utf-8"))
    (root / "recordings" / "README.md").write_bytes(_RECORDINGS_README.encode("utf-8"))
    (root / "README.md").write_bytes(_CORPUS_README.encode("utf-8"))


_CORPUS_README = """\
# fixtures/F-AUTHOR -- the authoring fixture corpus (TC-AUTHOR-28)

Twenty-three teacher test descriptions, `AF-01`..`AF-23`, one directory each: the documents a
teacher would hand a colleague, plus an `expected.toml` stating the **outcome class** the
tests assert -- which items resolve, which placeholder, whether the build publishes or is
refused. AF-01..AF-13 are the package-authoring delta's §5.1 matrix; AF-14..AF-21 are the
console-redesign delta's §5.1 intake matrix (built by #753 ahead of the intake tier, #754);
AF-22/AF-23 are the console-clarity variants of the ENG7 sample test (#812): its four PDFs,
rendered by `docs/live-tests/sample-materials/build_sample_materials.py`, with the rubric's
grade table left out (AF-22) or naming *pass* with no boundary (AF-23). Alongside the numbered fixtures sit the adversarial intake set (`adversarial/`) and the
roster CSVs (`rosters/`). The double-honesty rule (test-plan §4.2) lives in `recordings/`.

**Generated, not edited by hand.** Regenerate with:

    python fixtures/F-AUTHOR/build_authoring_fixtures.py

The generator is committed in this directory (the `build_sample_materials.py` pattern:
committed generator, committed outputs, stdlib only) and is byte-for-byte reproducible: a
changed PDF in a review means a changed script. The rendering itself is
`harness.corpora.pdf_writer.typed_document` (typed pages) and
`harness.corpora.scan.render_hand_page` (AF-10's scan); the intake fixtures' .docx packages,
OLE containers, and PNG part are built here with stdlib `zipfile`/`struct`/`zlib` over
deterministic content models -- nothing here reimplements the repo's readers.

This corpus is deliberately exempt from `python -m harness.corpora.build --check`
(`_IN_TREE_GENERATED_TREES` in `harness/corpora/build.py`): that check regenerates the
corpora its own module emits, and this corpus's generator lives here, not there. The pin is
TC-AUTHOR-28's census instead, which re-runs this script and diffs the bytes.

## expected.toml schema

| key | meaning |
|---|---|
| `af` | the fixture id, `AF-01`..`AF-23` |
| `description` | what the fixture exercises (§5.1's wording) |
| `documents` | the document filenames in this directory, in hand-in order |
| `outcome` | `resolved` (fully drafted), `partial` (named placeholders), `unresolved` (not converging after all attempts), `refused` (the intake refuses the hand-in, FR-AUTHOR-28) |
| `placeholders` | the placeholder fields the outcome class expects (empty when `resolved`) |
| `build` | `publishes` (once any placeholders are filled at review) or `refused` (FR-PKG-28's gate, or an intake refusal) |
| `refusal` | AF-18..AF-20 only: FR-AUTHOR-28's exact teacher sentence the intake refuses with (test plan §4.3: exact-match, so copy drift fails). Present iff `outcome = "refused"` |
| `warnings` | the `IntakeWarning` codes the outcome class requires to be present (§3.1.1's vocabulary: `image_not_carried`, `equation_not_carried`, `structure_guessed`, `formatting_dropped`, `encoding_fallback`). Presence, not exhaustiveness |
| `format` | one source format per document, aligned with `documents` (`docx` \\| `txt` \\| `pdf`, `NormalizedDocument.source_format`'s domain) |
| `table_rows` | AF-14 only: the rubric table's rows, carried verbatim for TC-AUTHOR-33's cell match |
| `retry_of` | AF-13 only: the fixture this re-drafts |
| `carry_over` | AF-13 only: the carry-over outcome class |
| `notes` | one line for a human |
| `[review.answers]` | the scripted review answers the publishing fixtures' drafts complete with (TC-REQ-136); item id = value, a list answers a repeated id one value per occurrence in document order. Refused fixtures (AF-09, AF-11, AF-18..AF-20) carry none |

## adversarial/ -- the refusal arms with no fixture directory

Three files whose shape belongs to no numbered fixture, each refused before any content is
read (test plan §3.1, TC-AUTHOR-37's matrix): a password-protected `.docx` (a Compound File
Binary container holding an `EncryptedPackage` stream -- what an encrypted docx actually
is), a `.rtf` (outside the three formats), and real PDF bytes under a `.docx` name. Their
`adversarial/expected.toml` is a different, smaller schema: one `[[file]]` table per entry
naming `name`, `looks_like`, and the exact `refusal` sentence.

## rosters/ -- class lists (TC-CONSOLE-65's inputs)

`console-world-3-students.csv` carries the `console_world` seed cohort's three students
(`c-ts48`, refs `ref-sub-c-ts48-01`..`03`), so a case written against it needs no rewrite
when the console tests land. `console-world-malformed.csv` carries the shapes that make a
roster file suspect: a duplicated name (legal to the reader -- deciding that two refs are
one student is the cohort layer's call), a row with a ref but no name (refused, naming
the line), a fully blank row (skipped), and one valid row. The names are synthetic
(`tests/support/roster.py`'s stem style) -- the corpus never carries a real name.

## What the intake fixtures do NOT carry

No recordings exist for AF-14..AF-21: the intake tier's prompts do not exist until #754
lands, and a recording captured before its prompt is a key no request will ever ask for.
The implementing stories capture them, once, from a live run (see `recordings/README.md`).
AF-22 and AF-23 carry none either: their drafting replies are captured from the live ENG7
walk (console-clarity TC-E2E-14, `record=True`), never fabricated, so the recorded
build-gate walk (TC-REQ-136) skips them until that capture lands.
The oversize refusal arm (FR-AUTHOR-28's 10 MB sentence) has no committed fixture either:
its tests generate the oversize file through the `HARNESS_AUTHOR_DOC_MAX_BYTES` knob.

The recorded tier replays exact content through `RecordedFixtureProvider`; the live tier
(`@live`, real OpenRouter) asserts these outcome classes -- **never exact wording**: two runs
of a real model agree on structure, not prose (CT-AUTHOR-17's non-promise). The one exact
wording the corpus does pin is the refusal table: FR-AUTHOR-28's sentences are the
teacher-facing copy the design table states verbatim, so a test asserts them exactly.
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

## The console-redesign capture pass (AF-14, AF-17, AF-21; issue #773)

The intake fixtures' recordings were captured on 2026-10-14 by the committed script
`scripts/capture_authoring_recordings.py`, one invocation per fixture, from a live
`dev-ci` run (the key comes from the operator's `Code/.env-dev`; no `HARNESS_FIXTURE_DIR`
is set — the boundary records every reply the live backend answers and nulls its cost,
CT-PROV-03). The commands, from the repository root:

    python scripts/capture_authoring_recordings.py \
        --docs fixtures/F-AUTHOR/AF-14/hist7-rome-01-test-and-grading.docx \
        --out %TEMP%\af14-capture      # TC-E2E-08's journey: 6 recording(s)
    python scripts/capture_authoring_recordings.py \
        --docs fixtures/F-AUTHOR/AF-17/hist6-great-fire-01-prose-test.txt \
        --out %TEMP%\af17-capture      # TC-E2E-09's journey: 5 recording(s)
    python scripts/capture_authoring_recordings.py \
        --docs fixtures/F-AUTHOR/AF-21/mus8-instruments-01-test.docx \
               fixtures/F-AUTHOR/AF-21/mus8-instruments-01-marking-memo.txt \
               fixtures/F-AUTHOR/AF-21/hist7-rome-01-test-and-grading.txt \
        --out %TEMP%\af21-capture      # TC-E2E-11's journey: 9 recording(s)

**The build pin is not the older qwen pin.** These recordings key on
`openai/gpt-6-luna@2026-06-01` (`tests.support.console_journeys.JOURNEY_AUTHORING_BUILD`),
the vendor-qualified build the live-test configuration moved to, minus the `openrouter/`
transport prefix the dev-ci chain carries inside its build ids. This account's guardrails
remove every Qwen endpoint at the zero-retention routing ("Model bloc", verified by
dispatch on 2026-10-14); the AF-01..13 recordings keep their qwen keys and the tests that
replay them keep the old constants — the two pins coexist, each key hashing the build it
was captured under. The journeys render the identical string through the shared module, so
a replay asks for exactly the keys captured here. A future canonical re-capture (keying on
dev-ci's full build id) would let these recordings also serve replays that ride the dev-ci
chain itself — TC-AUTHOR-38's capture guard (`tests/support/impl.py`'s
`_INTAKE_CAPTURE_PROBE`) is the check that fires when that lands.

**A disclosed capture divergence (finding, not a fix).** The captured chains for AF-17 and
AF-21 leave grade-boundary placeholders their `expected.toml` contracts do not declare
(`placeholders = []`): the capture model read AF-17's "a D is less" and AF-21's merged
grade tables as boundaries not numerically stated, and the extraction never invents one
(FR-AUTHOR-08). AF-14's capture satisfies its contract exactly. The journeys fill those
boundaries at the review walk — the teacher action that walk exists for — and disclose the
divergence in their docstrings; the corpus's generated `expected.toml` was left untouched
for the corpus owner to decide on.
"""


def main() -> int:
    build()
    print(f"wrote {len(FIXTURES)} fixtures, the adversarial set, {len(ROSTERS)} rosters, "
          f"and the READMEs under {CORPUS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())