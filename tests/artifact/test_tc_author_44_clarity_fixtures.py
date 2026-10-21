"""`TC-AUTHOR-44` (fixture half) — the clarity authoring fixtures AF-22 and AF-23 exist, are
the ENG7 test with only the rubric's grade policy changed, and are generated, not typed.

Traces: TC-AUTHOR-44 (FR-AUTHOR-31, FR-AUTHOR-32); `console_clarity_test_plan.md` §2.4, §6
story T1 (#812). The behaviour half — the exact questions and hints the draft asks — is
TC-AUTHOR-44 proper (story T9), which drafts against these fixtures.

**Byte reproducibility is pinned elsewhere, on purpose.** AF-22/AF-23 are written by
`fixtures/F-AUTHOR/build_authoring_fixtures.py` from the sample-materials generator's
`english_authoring_variants()`, so TC-AUTHOR-28's census (`test_the_corpus_rebuilds_byte_identical`,
which now counts AF-01..AF-23) re-runs the generator and byte-diffs them like every other
fixture. This file pins what that census cannot: that the bytes are the *ENG7 test*, and that
each rubric says exactly what its path needs it to say (AF-22: no grade table at all; AF-23:
*pass* named with no boundary).

**Oracle.** Byte equality with the shipped ENG7-READ-01 PDFs for the unchanged documents;
the rubric's text layer equals the shipped rubric's minus (AF-22) or with a replaced (AF-23)
grade-policy paragraph — a structural diff, so a variant that also dropped a rubric line fails.

Markers. The census cases are green: the fixtures are this story's deliverable. The two
fitness cases at the bottom — the draft assembler asks exactly the fixture's declared
placeholder, with an answer range the fixture's scripted answer satisfies — were
written ahead of #809 (FR-AUTHOR-31/32) and run unmarked since it landed.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

from tests.support.clarity_world import (AF22_DIR, AF23_DIR, ENG7_PASS, ENG7_TOTAL_MAX,
                                         REPO_ROOT, eng7_grade_gaps)

CASE = "TC-AUTHOR-44 (fixture half)"
SAMPLE_PDFS = REPO_ROOT / "docs" / "live-tests" / "sample-materials" / "pdf" / "ENG7-READ-01"
SAMPLE_GENERATOR = (REPO_ROOT / "docs" / "live-tests" / "sample-materials"
                    / "build_sample_materials.py")

UNCHANGED = ("01-test-paper.pdf", "02-model-answer.pdf", "04-blank-answer-sheet.pdf")
VARIANT_RUBRIC = {"AF-22": "03-rubric-no-grade-table.pdf",
                  "AF-23": "03-rubric-pass-no-boundary.pdf"}
FIXTURE_DIRS = {"AF-22": AF22_DIR, "AF-23": AF23_DIR}
DECLARED_PLACEHOLDER = {"AF-22": "grades", "AF-23": "grades pass"}

_TJ = re.compile(rb"\(((?:\\.|[^\\)])*)\) Tj")


def _pdf_lines(path: Path) -> list[str]:
    """The text layer of one sample-materials PDF (uncompressed literal strings), page
    footers dropped — the footer's page count is layout, not content."""
    lines = [re.sub(r"\\(.)", r"\1", m.group(1).decode("ascii"))
             for m in _TJ.finditer(path.read_bytes())]
    return [line for line in lines if not re.fullmatch(r"Page \d+ of \d+", line)]


def _expected(af: str) -> dict:
    return tomllib.loads((FIXTURE_DIRS[af] / "expected.toml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("af", ["AF-22", "AF-23"])
def test_tc_author_44_variant_is_the_four_eng7_pdfs(af: str) -> None:
    """The hand-in is the four ENG7 PDFs; all but the rubric are the shipped bytes."""
    expected = _expected(af)
    assert expected["documents"] == [UNCHANGED[0], UNCHANGED[1], VARIANT_RUBRIC[af],
                                     UNCHANGED[2]], f"{CASE}: {af}'s documents drifted"
    for name in UNCHANGED:
        assert (FIXTURE_DIRS[af] / name).read_bytes() == (SAMPLE_PDFS / name).read_bytes(), (
            f"{CASE}: {af}/{name} is not the shipped ENG7-READ-01 {name} — the variant must "
            f"differ from the real test in the rubric alone")


@pytest.mark.parametrize("af", ["AF-22", "AF-23"])
def test_tc_author_44_variant_declares_its_outcome_class(af: str) -> None:
    """One placeholder, the one the path needs; it publishes once answered with ENG7's 6."""
    expected = _expected(af)
    assert expected["af"] == af
    assert expected["outcome"] == "partial" and expected["build"] == "publishes"
    assert expected["placeholders"] == [DECLARED_PLACEHOLDER[af]], (
        f"{CASE}: {af} must declare exactly the {DECLARED_PLACEHOLDER[af]!r} gap "
        f"(no 'grades not yet': the lowest grade's floor is 0 and never asked, FR-AUTHOR-32)")
    answers = expected["review"]["answers"]
    assert answers[DECLARED_PLACEHOLDER[af]] == ENG7_PASS, (
        f"{CASE}: {af}'s scripted answer is not the shipped ENG7 pass mark ({ENG7_PASS})")
    assert answers["approved_by"], f"{CASE}: {af} scripts no approver"


def test_tc_author_44_af22_rubric_has_no_grade_table() -> None:
    """AF-22's rubric is the shipped rubric with the grade-policy section removed — nothing
    else removed, and no grade name or boundary left anywhere in it."""
    shipped = _pdf_lines(SAMPLE_PDFS / "03-rubric.pdf")
    variant = _pdf_lines(AF22_DIR / VARIANT_RUBRIC["AF-22"])
    cut = shipped.index("Grade policy (plain language)")
    assert variant == shipped[:cut], (
        f"{CASE}: AF-22's rubric is not the shipped rubric minus its grade policy")
    text = " ".join(variant).lower()
    for word in (r"\bpass\b", r"\bnot yet\b", r"grade policy", r"\bor more\b"):
        assert not re.search(word, text), f"{CASE}: AF-22's rubric still says {word!r}"


def test_tc_author_44_af23_rubric_names_pass_without_a_boundary() -> None:
    """AF-23's rubric names *pass* and *not yet*, states the total (8), and gives no number
    a student must reach: the only numbers in its grade policy are the line maxima."""
    shipped = _pdf_lines(SAMPLE_PDFS / "03-rubric.pdf")
    variant = _pdf_lines(AF23_DIR / VARIANT_RUBRIC["AF-23"])
    cut = shipped.index("Grade policy (plain language)")
    assert variant[:cut + 1] == shipped[:cut + 1], (
        f"{CASE}: AF-23's rubric changed more than its grade policy")
    policy = " ".join(variant[cut + 1:])
    assert "pass" in policy and "not yet" in policy, f"{CASE}: AF-23 does not name the grades"
    assert f"out of {ENG7_TOTAL_MAX} points" in policy, f"{CASE}: AF-23 states no total"
    without_maxima = re.sub(r"out of \d+|two 1-point|\bQ\d\b", "", policy)
    assert not re.search(r"\d", without_maxima), (
        f"{CASE}: AF-23's grade policy states a number beyond the line maxima — a boundary "
        f"for pass: {policy!r}")
    for phrase in ("or more", "at least", "or above"):
        assert phrase not in policy, f"{CASE}: AF-23 states a boundary ({phrase!r})"


def test_tc_author_44_variants_come_from_the_sample_generator() -> None:
    """The committed bytes are the sample-materials generator's output, not a hand copy."""
    spec = importlib.util.spec_from_file_location("build_sample_materials", SAMPLE_GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    variants = module.english_authoring_variants()
    assert set(variants) == {"AF-22", "AF-23"}
    for af, files in variants.items():
        for name, data in files.items():
            assert (FIXTURE_DIRS[af] / name).read_bytes() == data, (
                f"{CASE}: {af}/{name} differs from english_authoring_variants() — rebuild "
                f"with `python fixtures/F-AUTHOR/build_authoring_fixtures.py`")


# --- fitness for the path each fixture exists for (#809, FR-AUTHOR-31/32) ---------------

def test_tc_author_44_af22_drives_the_passing_score_question() -> None:
    """AF-22's documents state no grade table, so the draft asks exactly its declared gap,
    `grades`, typed as a whole number 1..8 — a range the fixture's scripted 6 is inside."""
    gaps = eng7_grade_gaps({})
    assert [gap.item_id for gap in gaps] == _expected("AF-22")["placeholders"]
    (gap,) = gaps
    assert gap.answer_kind == "whole_number", f"{CASE}: AF-22's gap is not a whole number"
    assert (gap.answer_min, gap.answer_max) == (1, ENG7_TOTAL_MAX), f"{CASE}: AF-22's range is not 1..8"
    assert gap.answer_min <= _expected("AF-22")["review"]["answers"]["grades"] <= gap.answer_max


@pytest.mark.parametrize("not_yet", [None, 0], ids=["not-yet-unstated", "not-yet-zero"])
def test_tc_author_44_af23_drives_the_lowest_score_for_pass_question(not_yet) -> None:
    """AF-23 names pass and not yet with no boundary: the draft asks `grades pass` only —
    never `grades not yet` (its floor is 0, filled in) — ranged 1..8 around the scripted 6."""
    gaps = eng7_grade_gaps({"pass": None, "not yet": not_yet})
    assert [gap.item_id for gap in gaps] == _expected("AF-23")["placeholders"], (
        f"{CASE}: AF-23 asks {[g.item_id for g in gaps]}, not its declared placeholder")
    (gap,) = gaps
    assert gap.answer_kind == "whole_number"
    assert (gap.answer_min, gap.answer_max) == (1, ENG7_TOTAL_MAX)
    assert gap.answer_min <= _expected("AF-23")["review"]["answers"]["grades pass"] <= gap.answer_max
