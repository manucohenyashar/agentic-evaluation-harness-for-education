#!/usr/bin/env python3
"""Build the sample tests, rubrics, model answers and student answer sheets as PDFs.

Standard library only. Run it from anywhere:

    python docs/live-tests/sample-materials/build_sample_materials.py

It writes into `docs/live-tests/sample-materials/pdf/` (next to this file) and is byte-for-byte
reproducible: the same script always produces the same files, so a changed PDF in a review means
a changed script.

Everything the PDFs say is declared once, in the data below. `verify_sample_materials.py` imports
that same data, so the PDFs and the checks that exercise them cannot drift apart.

What these files are, honestly: TYPED pages. A page that was typed has a clean text layer and
rasterises sharply, which is the easy case for the page-reading model. They are a rehearsal of the
whole paper trail (headers, names, answer marks, a wrong-test paper, a missing name, a doubled
mark), not a test of handwriting. For the handwriting question, have two or three real people write
a sheet by hand and scan it, then add those files beside these.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "pdf"

# --------------------------------------------------------------------------------------------
# The two tests
# --------------------------------------------------------------------------------------------

PHYSICS_ID = "PS9-FORCES-01"
ENGLISH_ID = "ENG7-READ-01"

PHYSICS_TITLE = "Grade 9 Physical Science - Forces and Motion - Short Test"
ENGLISH_TITLE = "Grade 7 English - Reading Response - The Lighthouse Keeper"

# Multiple-choice questions: (question id, prompt, options, correct letter).
PHYSICS_MCQ = [
    ("Q1", "An object is moving at a steady speed in a straight line. The net force on it is zero. "
           "What will the object do next?",
     {"A": "Stop immediately", "B": "Slow down gradually",
      "C": "Keep moving at the same steady speed", "D": "Speed up"}, "C"),
    ("Q2", "Which unit is used to measure force?",
     {"A": "joule", "B": "newton", "C": "watt", "D": "pascal"}, "B"),
    ("Q3", "A 2 kg trolley accelerates at 3 m/s squared. What is the net force on it?",
     {"A": "1.5 N", "B": "5 N", "C": "6 N", "D": "9 N"}, "C"),
]

PHYSICS_Q4 = ("Q4", "A book rests on a table. Using forces, explain why the book is not accelerating.")

PHYSICS_Q5 = ("Q5", "A cyclist rides at a steady speed along a flat, straight road.",
              "(a) The forward force from the pedals is ... the total resistive force. "
              "Mark one letter.",
              {"A": "greater than", "B": "equal to", "C": "less than"}, "B",
              "(b) Explain your choice in (a).")

# Rubric lines for the physics test. Open lines use four statement bands, best first.
PHYSICS_RUBRIC = [
    ("C1", "Q1", "Multiple choice, answer key C", "1 mark, right or wrong. Marked by key lookup."),
    ("C2", "Q2", "Multiple choice, answer key B", "1 mark, right or wrong. Marked by key lookup."),
    ("C3", "Q3", "Multiple choice, answer key C", "1 mark, right or wrong. Marked by key lookup."),
    ("C4", "Q4", "Why the book is not accelerating", [
        ("Full (3)", "Names the weight (gravity) pulling down AND the normal (support) force pushing "
                     "up, AND says they are equal so the net force is zero."),
        ("Adequate (2)", "Names both forces, but does not say they are equal or that the net force "
                         "is zero."),
        ("Limited (1)", "Names only one force, or says the table or ground 'stops' the book without "
                        "naming forces."),
        ("None (0)", "No relevant force named, or a claim that contradicts the answer."),
    ]),
    ("C5", "Q5a", "Cyclist: forward force compared with resistive force, answer key B",
     "1 mark, right or wrong. Marked by key lookup."),
    ("C6", "Q5b", "Why the forces are equal", [
        ("Full (3)", "States that the net force is zero AND links this to the steady (constant) "
                     "speed, for example by Newton's first law."),
        ("Adequate (2)", "Says the forces balance or cancel, but does not link this to steady speed."),
        ("Limited (1)", "Mentions friction or the pedals, but gives no reason about balance or "
                        "steady speed."),
        ("None (0)", "No relevant reason, or a reason that contradicts the answer."),
    ]),
]

PHYSICS_MODEL_ANSWER = [
    "Q1: C. With zero net force an object keeps its velocity (Newton's first law).",
    "Q2: B. The newton (N) is the unit of force.",
    "Q3: C. F = m x a = 2 kg x 3 m/s squared = 6 N.",
    "Q4: Two forces act on the book: its weight (gravity), downward, and the normal force from the "
    "table, upward. They are equal in size and opposite in direction, so the net force on the book "
    "is zero. With zero net force there is no acceleration.",
    "Q5a: B. At a steady speed the forward force equals the total resistive force.",
    "Q5b: The cyclist's speed is not changing, so the acceleration is zero and the net force is zero. "
    "The forward force from the pedals therefore balances the resistive forces (air resistance and "
    "friction).",
]

PHYSICS_GRADE_POLICY = (
    "Each question's mark is the sum of its rubric lines. The test total is out of 10 points "
    "(four 1-point multiple-choice lines and two 3-point written lines). "
    "8 or more is an A, 6 or more is a B, 4 or more is a C, 2 or more is a D, below 2 is an F."
)

# English test.
ENGLISH_PASSAGE = [
    "Tomas kept the lighthouse on the rocky point at Grey Harbour. Every evening, as the sun",
    "slipped into the sea, he climbed the one hundred and twelve steps, wiped the great glass lens",
    "and lit the lamp. The big ships that once passed the point had stopped coming years ago,",
    "because a new road and a new port had been built far down the coast. Still, each night Tomas",
    "kept the lamp burning until dawn.",
    "",
    "One stormy night a small fishing boat appeared out of the dark, tossed by the waves. The",
    "fisherman saw the steady light, turned his boat toward it, and found the safe channel into the",
    "harbour. In the morning he walked up to the lighthouse and shook Tomas's hand without a word.",
    "From that day on, Tomas no longer wondered whether the lamp was worth lighting. He climbed the",
    "steps each evening a little taller than before.",
]

ENGLISH_QUESTIONS = [
    ("Q1", "Who is the main character, and what does he do every evening?"),
    ("Q2", "Why does Tomas keep the lamp burning even though the big ships no longer come? "
           "Use evidence from the passage."),
    ("Q3", "Write two or three sentences about how Tomas changes by the end of the passage."),
]

ENGLISH_RUBRIC = [
    ("C1", "Q1", "Names the main character", "Yes or no. Yes if the answer names Tomas."),
    ("C2", "Q1", "States the evening task", "Yes or no. Yes if the answer says he lights the lamp "
                                            "(climbing the steps or cleaning the lens may also be mentioned)."),
    ("C3", "Q2", "Why the lamp is kept burning", [
        ("Full (3)", "Gives a reason (someone might still need the light, such as a small boat) AND "
                     "supports it with evidence from the passage."),
        ("Adequate (2)", "Gives a sensible reason but with no evidence from the passage."),
        ("Limited (1)", "Repeats the passage ('he lights it every night') without a reason."),
        ("None (0)", "No relevant answer."),
    ]),
    ("C4", "Q3", "How Tomas changes", [
        ("Full (3)", "Says he starts unsure whether the work matters and ends confident it does, "
                     "and gives a detail that shows it (the taller climb, or no longer wondering)."),
        ("Adequate (2)", "Describes the change (unsure to confident, or sad to proud) but gives no detail."),
        ("Limited (1)", "Describes what happens in the story (the boat arrives) without describing a "
                        "change in Tomas."),
        ("None (0)", "No relevant answer."),
    ]),
]

ENGLISH_MODEL_ANSWER = [
    "Q1: The main character is Tomas. Every evening he climbs the steps, cleans the lens and lights "
    "the lamp.",
    "Q2: Someone might still need the light. Even though big ships stopped coming, a small fishing "
    "boat used the lamp on a stormy night to find the safe channel.",
    "Q3: At the start Tomas wonders whether lighting the lamp is worth it. After he saves the "
    "fisherman he is sure it is, and he climbs the steps 'a little taller than before'.",
]

# --------------------------------------------------------------------------------------------
# Student answer sheets
# --------------------------------------------------------------------------------------------
# Each sheet: file stem, header assessment id, student ref (None = the name line is left off),
# a one-line note on what the sheet is there to test, and the answers.
# MCQ answers: a list of circled letters (two letters = a doubled mark).
# Written answers: text, or "" for an empty answer space.

PHYSICS_SHEETS = [
    dict(stem="S9-001-strong", test=PHYSICS_ID, student="S9-001",
         note="Strong paper. Everything right, full written answers.",
         mcq={"Q1": ["C"], "Q2": ["B"], "Q3": ["C"], "Q5a": ["B"]},
         written={
             "Q4": "The book's weight pulls it down and the table pushes up on it with the normal "
                   "force. These two forces are equal and opposite so they cancel and the net force "
                   "is zero, so the book does not accelerate.",
             "Q5b": "The cyclist is going at a steady speed so the acceleration is zero. That means "
                    "the net force is zero, so the pedalling force is the same as the air resistance "
                    "and friction. This is Newton's first law."},
         reference_points=10),
    dict(stem="S9-002-middle", test=PHYSICS_ID, student="S9-002",
         note="Middle paper. One multiple-choice slip, two partial written answers.",
         mcq={"Q1": ["C"], "Q2": ["B"], "Q3": ["B"], "Q5a": ["B"]},
         written={
             "Q4": "Gravity is pulling the book down and the table is pushing it up with a force so "
                   "it stays where it is.",
             "Q5b": "The forces are balanced so they cancel each other out."},
         reference_points=7),
    dict(stem="S9-003-weak", test=PHYSICS_ID, student="S9-003",
         note="Weak paper. Common misconception that a moving object needs a constant forward push.",
         mcq={"Q1": ["D"], "Q2": ["A"], "Q3": ["C"], "Q5a": ["A"]},
         written={
             "Q4": "Gravity pulls the book down but the table is strong so it holds it up.",
             "Q5b": "You have to keep pedalling hard to keep going because of friction."},
         reference_points=3),
    dict(stem="S9-004-doubled-mark-and-blank", test=PHYSICS_ID, student="S9-004",
         note="Two marks circled on Q1 (a mark the reader cannot resolve) and Q4 left empty. "
              "Expect an operator quarantine item for Q1, never a guess.",
         mcq={"Q1": ["A", "C"], "Q2": ["B"], "Q3": ["C"], "Q5a": ["B"]},
         written={"Q4": "",
                  "Q5b": "The net force is zero because the speed is steady."},
         reference_points=None),
    dict(stem="S9-005-wrong-test", test=ENGLISH_ID, student="S9-005",
         note="A student handed in the English paper's answers against the physics test. "
              "The page names a different assessment: expect the match check to park it.",
         mcq={},
         written={
             "Q1": "The main character is Tomas and he lights the lamp every evening.",
             "Q2": "Because a boat might need it.",
             "Q3": "He feels better about his job at the end."},
         reference_points=None),
    dict(stem="S9-006-no-name", test=PHYSICS_ID, student=None,
         note="A good paper where the student forgot to write a name. The identity check cannot "
              "match it, so expect it to be parked for the operator to match by hand.",
         mcq={"Q1": ["C"], "Q2": ["B"], "Q3": ["C"], "Q5a": ["B"]},
         written={
             "Q4": "Gravity pulls it down and the table pushes up with the same force, so the "
                   "forces are balanced and the net force is zero. No net force means no "
                   "acceleration.",
             "Q5b": "Steady speed means no acceleration so the net force is zero and the forward "
                    "force equals the resistance."},
         reference_points=10),
]

ENGLISH_SHEETS = [
    dict(stem="E7-001-strong", test=ENGLISH_ID, student="E7-001",
         note="Strong paper. Names, reason with evidence, clear change.",
         mcq={},
         written={
             "Q1": "The main character is Tomas, the lighthouse keeper. Every evening he climbs the "
                   "steps and lights the lamp.",
             "Q2": "Someone might still need the light. A small fishing boat came out of the dark on "
                   "a stormy night and used the light to find the safe channel, even though the big "
                   "ships had stopped coming.",
             "Q3": "At first Tomas is not sure the lamp matters because no big ships come. After he "
                   "helps the fisherman he is sure it does, and he climbs the steps a little taller "
                   "than before."},
         reference_points=8),
    dict(stem="E7-002-middle", test=ENGLISH_ID, student="E7-002",
         note="Middle paper. Right idea, little evidence.",
         mcq={},
         written={
             "Q1": "Tomas lights the lamp every evening.",
             "Q2": "Because somebody might need it to be safe at night.",
             "Q3": "He was sad at the start and happy at the end."},
         reference_points=6),
    dict(stem="E7-003-weak", test=ENGLISH_ID, student="E7-003",
         note="Weak paper. Retells the passage, no reason, no change.",
         mcq={},
         written={
             "Q1": "A man in a lighthouse.",
             "Q2": "He lights it every night.",
             "Q3": "A boat came and the man shook his hand."},
         reference_points=2),
    dict(stem="E7-004-mostly-blank", test=ENGLISH_ID, student="E7-004",
         note="Mostly blank. A genuine non-answer must be scored as an answer that is not there, "
              "never as a scanning problem.",
         mcq={},
         written={"Q1": "Tomas.", "Q2": "", "Q3": ""},
         reference_points=1),
]

# --------------------------------------------------------------------------------------------
# A very small PDF writer (standard library only)
# --------------------------------------------------------------------------------------------

PAGE_W, PAGE_H = 612, 792
LEFT, TOP, BOTTOM = 54, 738, 60
WRAP = 92  # characters per line at 10.5 pt Helvetica / Courier


def _esc(text: str) -> bytes:
    text = text.encode("ascii", "replace").decode("ascii")
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("ascii")


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


class Doc:
    """Collects styled lines, paginates them, and renders a PDF."""

    FONTS = {"n": ("F1", 10.5, 14), "b": ("F2", 10.5, 14), "h": ("F2", 14, 20),
             "m": ("F3", 10.5, 14), "s": ("F1", 8.5, 12)}

    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def line(self, text: str = "", style: str = "n") -> None:
        self.items.append((style, text))

    def para(self, text: str, style: str = "n", indent: int = 0) -> None:
        for chunk in _wrap(text, WRAP - indent):
            self.items.append((style, " " * indent + chunk))

    def blank(self, n: int = 1) -> None:
        self.items.extend([("n", "")] * n)

    def render(self) -> bytes:
        pages: list[list[tuple[str, str]]] = [[]]
        y = TOP
        for style, text in self.items:
            lead = self.FONTS[style][2]
            if y - lead < BOTTOM:
                pages.append([])
                y = TOP
            pages[-1].append((style, text))
            y -= lead
        objs: dict[int, bytes] = {}
        objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        kids = []
        first = 6
        for i, page in enumerate(pages):
            content_no, page_no = first + 2 * i, first + 2 * i + 1
            body = bytearray()
            y = TOP
            for style, text in page:
                font, size, lead = self.FONTS[style]
                y -= lead
                if text:
                    body += (f"BT /{font} {size} Tf {LEFT} {y} Td (".encode("ascii")
                             + _esc(text) + b") Tj ET\n")
            footer = f"Page {i + 1} of {len(pages)}"
            body += f"BT /F1 8.5 Tf {PAGE_W // 2 - 24} 30 Td ({footer}) Tj ET\n".encode("ascii")
            data = bytes(body)
            objs[content_no] = (b"<< /Length " + str(len(data)).encode("ascii") + b" >>\nstream\n"
                                + data + b"\nendstream")
            objs[page_no] = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Contents {content_no} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> "
                f">> >>").encode("ascii")
            kids.append(f"{page_no} 0 R")
        objs[2] = (f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>").encode("ascii")
        objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        objs[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
        objs[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: dict[int, int] = {}
        for number in sorted(objs):
            offsets[number] = len(out)
            out += f"{number} 0 obj\n".encode("ascii") + objs[number] + b"\nendobj\n"
        size = max(objs) + 1
        xref = len(out)
        out += f"xref\n0 {size}\n".encode("ascii") + b"0000000000 65535 f \n"
        for number in range(1, size):
            if number in offsets:
                out += f"{offsets[number]:010d} 00000 n \n".encode("ascii")
            else:
                out += b"0000000000 65535 f \n"
        out += (f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode("ascii")
        return bytes(out)


# --------------------------------------------------------------------------------------------
# The documents
# --------------------------------------------------------------------------------------------

def _header(doc: Doc, test_id: str, title: str, student: str | None, sheet: bool) -> None:
    doc.line(f"Assessment: {test_id}", "b")
    if sheet:
        if student:
            doc.line(f"Student: {student}", "b")
    doc.line(title, "h")
    doc.blank()


def physics_test() -> Doc:
    d = Doc()
    _header(d, PHYSICS_ID, PHYSICS_TITLE, None, False)
    d.para("Time: 25 minutes. Total: 10 marks. Mark one letter for each multiple-choice question. "
           "Write your written answers in the spaces on the answer sheet.")
    d.blank()
    for qid, prompt, options, _key in PHYSICS_MCQ:
        d.para(f"{qid}. {prompt}", "b")
        for letter, text in options.items():
            d.line(f"    {letter}.  {text}")
        d.blank()
    d.para(f"{PHYSICS_Q4[0]}. {PHYSICS_Q4[1]}  [3 marks]", "b")
    d.blank(2)
    qid, stem, a_part, opts, _key, b_part = PHYSICS_Q5
    d.para(f"{qid}. {stem}", "b")
    d.para(a_part)
    for letter, text in opts.items():
        d.line(f"    {letter}.  {text}")
    d.para(b_part + "  [3 marks]")
    return d


def physics_rubric() -> Doc:
    d = Doc()
    _header(d, PHYSICS_ID, "Marking Rubric - " + PHYSICS_TITLE, None, False)
    _rubric_body(d, PHYSICS_RUBRIC)
    d.blank()
    d.line("Grade policy (plain language)", "b")
    d.para(PHYSICS_GRADE_POLICY)
    return d


def _rubric_body(d: Doc, rubric: list) -> None:
    for line in rubric:
        cid, qid, name, detail = line
        d.para(f"{cid}  ({qid})  {name}", "b")
        if isinstance(detail, str):
            d.para(detail, indent=4)
        else:
            for band, text in detail:
                d.para(f"{band}: {text}", indent=4)
        d.blank()


def physics_model_answer() -> Doc:
    d = Doc()
    _header(d, PHYSICS_ID, "Model Answer - " + PHYSICS_TITLE, None, False)
    for line in PHYSICS_MODEL_ANSWER:
        d.para(line)
        d.blank()
    return d


def english_test() -> Doc:
    d = Doc()
    _header(d, ENGLISH_ID, ENGLISH_TITLE, None, False)
    d.para("Time: 20 minutes. Read the passage, then answer all three questions in full sentences.")
    d.blank()
    d.line("The Lighthouse Keeper", "b")
    for line in ENGLISH_PASSAGE:
        d.line(line)
    d.blank()
    for qid, prompt in ENGLISH_QUESTIONS:
        d.para(f"{qid}. {prompt}", "b")
        d.blank()
    return d


def english_rubric() -> Doc:
    d = Doc()
    _header(d, ENGLISH_ID, "Marking Rubric - " + ENGLISH_TITLE, None, False)
    _rubric_body(d, ENGLISH_RUBRIC)
    d.line("Grade policy (plain language)", "b")
    d.para("The test total is out of 8 points (two 1-point yes/no lines and two 3-point written "
           "lines). 6 or more is a pass; below 6 is not yet a pass.")
    return d


def english_model_answer() -> Doc:
    d = Doc()
    _header(d, ENGLISH_ID, "Model Answer - " + ENGLISH_TITLE, None, False)
    for line in ENGLISH_MODEL_ANSWER:
        d.para(line)
        d.blank()
    return d


def mcq_row(letters: list[str], choices: str) -> str:
    return "   ".join(f"[{'X' if letter in letters else ' '}] {letter}" for letter in choices)


def answer_sheet(sheet: dict, *, blank: bool = False) -> Doc:
    """One student's answer sheet, booklet style: each question is reprinted, and the student's
    answer sits below it. The answers are typed in monospace, the way a handwritten answer would
    sit in an answer space. With `blank=True` the sheet is the empty form to print and fill in by
    hand: the test line is printed, the student line is left to write on, and each answer space is
    ruled."""
    d = Doc()
    test_id = sheet["test"]
    title = PHYSICS_TITLE if test_id == PHYSICS_ID else ENGLISH_TITLE
    if blank:
        d.line(f"Assessment: {test_id}", "b")
        d.line("Student: ____________________", "b")
        d.line("Answer Sheet - " + title, "h")
        d.para("Write your student ID on the Student line above, then answer in the spaces below.")
        d.blank()
    else:
        _header(d, test_id, "Answer Sheet - " + title, sheet["student"], True)

    def written(qid: str, prompt: str, label: str | None = None) -> None:
        d.para(f"{label or qid}. {prompt}", "b")
        answer = sheet["written"].get(qid, "")
        if blank:
            for _ in range(4):
                d.line("  " + "_" * 84, "m")
        elif answer:
            d.para(answer, "m", indent=2)
        else:
            d.line("  (no answer written)", "m")
        d.blank()

    if test_id == PHYSICS_ID or sheet["mcq"]:
        for qid, prompt, options, _key in PHYSICS_MCQ:
            d.para(f"{qid}. {prompt}", "b")
            d.line("     " + mcq_row(sheet["mcq"].get(qid, []), "".join(options)), "m")
            d.blank()
        written(PHYSICS_Q4[0], PHYSICS_Q4[1])
        qid, stem, a_part, _opts, _key, b_part = PHYSICS_Q5
        d.para(f"{qid}. {stem} {a_part}", "b")
        d.line("     " + mcq_row(sheet["mcq"].get("Q5a", []), "ABC"), "m")
        d.blank()
        written("Q5b", b_part, label="Q5")
    else:
        for qid, prompt in ENGLISH_QUESTIONS:
            written(qid, prompt)
    return d


def build_all() -> dict[str, bytes]:
    files: dict[str, bytes] = {
        f"{PHYSICS_ID}/01-test-paper.pdf": physics_test().render(),
        f"{PHYSICS_ID}/02-model-answer.pdf": physics_model_answer().render(),
        f"{PHYSICS_ID}/03-rubric.pdf": physics_rubric().render(),
        f"{ENGLISH_ID}/01-test-paper.pdf": english_test().render(),
        f"{ENGLISH_ID}/02-model-answer.pdf": english_model_answer().render(),
        f"{ENGLISH_ID}/03-rubric.pdf": english_rubric().render(),
    }
    files[f"{PHYSICS_ID}/04-blank-answer-sheet.pdf"] = answer_sheet(
        dict(test=PHYSICS_ID, student=None, mcq={}, written={}), blank=True).render()
    files[f"{ENGLISH_ID}/04-blank-answer-sheet.pdf"] = answer_sheet(
        dict(test=ENGLISH_ID, student=None, mcq={}, written={}), blank=True).render()
    for sheet in PHYSICS_SHEETS:
        files[f"{PHYSICS_ID}/answer-sheets/{sheet['stem']}.pdf"] = answer_sheet(sheet).render()
    for sheet in ENGLISH_SHEETS:
        files[f"{ENGLISH_ID}/answer-sheets/{sheet['stem']}.pdf"] = answer_sheet(sheet).render()
    return files


def main() -> int:
    files = build_all()
    for relative, data in sorted(files.items()):
        target = OUT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"wrote {target.relative_to(HERE.parent.parent.parent)}  ({len(data)} bytes)")
    print(f"{len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
