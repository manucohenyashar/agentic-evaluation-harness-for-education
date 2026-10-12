"""`TC-AUTHOR-32..38` — the intake corpus's expected outcomes, against the §3.1.1 intake tier.

**Written ahead of #754** (the intake tier): `aeh.author` exists (#690) but carries no intake
surface, so every case below fails with `NotImplementedYet` naming #754 — the stated red,
never a collection error. `scripts/test.sh` filters the `writtenahead` marker out of the fast
tier; the `"#754 intake tier"` registry entry in `tests/support/impl.py` tells whoever lands
#754 to re-check this file green and then unmark (remove the marker, never the test).

The fixture corpus AF-14..21 is #753's deliverable and is pinned GREEN by the TC-AUTHOR-28
census (`tests/artifact/test_tc_author_28_authoring_fixture_corpus.py`): the corpus is the
fixture story's artifact, so the census asserts it is what the console-redesign design delta
§5.1 requires of it. These are the corpus's **fixture halves** of TC-AUTHOR-32..38: each case
normalizes one fixture through the intake tier the design delta §3.1.1 declares (ADR-46: one
`NormalizedDocument` per file; `Block`s and `IntakeWarning`s) and asserts the outcome class
the fixture's `expected.toml` states — the same shape the AF-01..13 outcome tests use (#710's
tier). The rest of the console-redesign test plan's intake row is not this file: the
representation/purity cases and the oversize knob arm (10 MB of bytes is not a committed
fixture; its file is knob-generated) are TS-2's, and TC-AUTHOR-38's recorded cross-format
carry-over journey needs recordings — its fixture half (the twin content identity) is the
census's `test_af21_carries_af14s_text_as_a_txt_twin`.

The surface names resolve through `tests/support/intake_vocabulary.py`, one place (the
`extract_vocabulary` precedent): the three §3.1.1-declared types are design-named; the entry
function (`normalize_document`) and the refusal exception (`IntakeRefused`) are that file's
disclosed bets, and the rename is one line there if #754 spells them differently.

Every case runs headless in-process under the autouse socket guard — the intake refuses by
magic bytes and parses bytes it already has, so FR-AUTHOR-28's refusals make zero provider
calls and the normalizations make none either (the four seams, headless driver).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from tests.support.impl import require
from tests.support.intake_vocabulary import (
    INTAKE_ENTRY,
    INTAKE_ISSUE,
    INTAKE_MODULE,
    INTAKE_REFUSAL,
    INTAKE_SURFACE,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS = REPO_ROOT / "fixtures" / "F-AUTHOR"

CASE = "TC-AUTHOR-32..38"


def _expected(af_id: str) -> dict:
    return tomllib.loads((CORPUS / af_id / "expected.toml").read_text(encoding="utf-8"))


def _intake() -> tuple:
    """The §3.1.1 intake surface, resolved inside the case body (`tests.support.impl`).

    A missing symbol is `NotImplementedYet` naming #754 — the stated red, at the first line
    of the case that needs it, never a collection error and never an import-time failure.
    """
    return require(INTAKE_MODULE, *INTAKE_SURFACE, INTAKE_ENTRY, INTAKE_REFUSAL,
                   issue=INTAKE_ISSUE)


def _normalize(path: Path):
    (_, _, _, normalize_document, _) = _intake()
    return normalize_document(path)


@pytest.mark.writtenahead
def test_tc_author_33_af14_rubric_table_is_carried() -> None:
    """`TC-AUTHOR-33` (FR-AUTHOR-25): AF-14's .docx rubric table is carried as table blocks.

    The oracle is the fixture's own declaration: the carried table's cells must match
    `expected.toml`'s `table_rows`, and the heading structure (level 1 title, level 2
    questions) must survive as typed blocks — a table flattened to prose, or headings
    normalized away, is the loss TC-AUTHOR-33 exists to catch.
    """
    expected = _expected("AF-14")
    document = _normalize(CORPUS / "AF-14" / expected["documents"][0])
    assert document.source_format == "docx", (
        f"{CASE}: AF-14 normalized to format {document.source_format!r}"
    )
    tables = [block for block in document.blocks if block.kind == "table"]
    assert tables, f"{CASE}: AF-14's rubric table was not carried as a table block"
    rows = [[cell.strip() for cell in row.split("\t")] for row in tables[0].text.split("\n")]
    assert rows == expected["table_rows"], (
        f"{CASE}: the carried table's cells do not match AF-14's table_rows"
    )
    headings = {block.text: block.level for block in document.blocks if block.kind == "heading"}
    assert headings["HIST7-ROME-01 - YEAR 7 HISTORY TEST: THE ROMAN EMPIRE"] == 1, (
        f"{CASE}: AF-14's title is not a level-1 heading block"
    )
    assert headings["Question 1 (4 marks)"] == 2, (
        f"{CASE}: AF-14's question heading is not a level-2 heading block"
    )


@pytest.mark.writtenahead
def test_tc_author_34_af15_image_and_equation_named_not_lost() -> None:
    """`TC-AUTHOR-34` (RS-02): AF-15's image and equation are *named*, not lost.

    Each required warning must be present (the corpus's `warnings` list is presence, not
    exhaustiveness), and each must name its location — the nearest heading or the ordinal,
    per §3.1.1's "naming the nearest heading/ordinal location". The prose around the losses
    must survive: a warning is not a licence to drop the questions themselves.
    """
    expected = _expected("AF-15")
    document = _normalize(CORPUS / "AF-15" / expected["documents"][0])
    codes = [warning.code for warning in document.warnings]
    for code in expected["warnings"]:
        assert code in codes, (
            f"{CASE}: the {code} warning is absent — the item was lost silently"
        )
    heading_texts = [block.text for block in document.blocks if block.kind == "heading"]
    for code in expected["warnings"]:
        warning = next(w for w in document.warnings if w.code == code)
        assert warning.message.strip(), (
            f"{CASE}: the {code} warning's message is empty"
        )
        located = (any(heading in warning.message for heading in heading_texts)
                   or re.search(r"\b\d+\b", warning.message))
        assert located, (
            f"{CASE}: the {code} warning names no location (heading or ordinal)"
        )
    joined = "\n".join(block.text for block in document.blocks if block.text)
    assert "What happens to the bulb when the switch is opened" in joined, (
        f"{CASE}: AF-15's first question did not survive the image's warning"
    )
    assert ("force, mass and acceleration" in joined or "F = m × a" in joined), (
        f"{CASE}: AF-15's equation question did not survive the equation's warning"
    )


@pytest.mark.writtenahead
def test_tc_author_35_af16_cp1252_encoding_fallback() -> None:
    """`TC-AUTHOR-35` (RS-01): AF-16's cp1252 bytes are read, and the fallback is named.

    Exactly one `encoding_fallback` warning whose message names the encoding actually used
    (Windows-1252, the design's own wording), and the accented words must survive intact —
    mojibake here would mean the bytes were decoded as UTF-8 with replacement, the failure
    RS-01 is about.
    """
    expected = _expected("AF-16")
    document = _normalize(CORPUS / "AF-16" / expected["documents"][0])
    assert document.source_format == "txt"
    fallbacks = [w for w in document.warnings if w.code == "encoding_fallback"]
    assert len(fallbacks) == 1, (
        f"{CASE}: exactly one encoding_fallback warning is required, got {len(fallbacks)}"
    )
    assert "windows-1252" in fallbacks[0].message.lower(), (
        f"{CASE}: the fallback warning does not name Windows-1252"
    )
    text = "\n".join(block.text for block in document.blocks if block.text)
    for word in ("café", "crêpe", "déjà", "élève", "hôtel", "très", "août", "génie"):
        assert word in text, f"{CASE}: the accented word {word!r} did not survive"


@pytest.mark.writtenahead
def test_tc_author_36_af17_structure_guessed() -> None:
    """`TC-AUTHOR-36`: AF-17's heading-less prose normalizes, and admits the guess.

    The file has no headings, so the outline is inferred (blank-line-separated blocks); the
    tier must warn `structure_guessed` rather than present a guessed outline as read, and
    the prose itself must survive as paragraph blocks — the review walk then asks the
    teacher to confirm it.
    """
    expected = _expected("AF-17")
    document = _normalize(CORPUS / "AF-17" / expected["documents"][0])
    assert document.source_format == "txt"
    codes = [warning.code for warning in document.warnings]
    assert "structure_guessed" in codes, (
        f"{CASE}: a heading-less file must warn that its outline is guessed"
    )
    paragraphs = [block for block in document.blocks if block.kind == "paragraph"]
    assert len(paragraphs) >= 3, (
        f"{CASE}: the running prose did not survive as paragraph blocks"
    )
    joined = "\n".join(block.text for block in document.blocks)
    assert "Pudding Lane" in joined and "Great Fire" in joined, (
        f"{CASE}: AF-17's questions did not survive"
    )


#: TC-AUTHOR-37's fixture-backed arms: the three numbered refusal fixtures plus the three
#: adversarial files. The oversize arm is absent on purpose — its file is knob-generated
#: (TS-2's), not committed. Sentences come from the corpus's own declarations, so this
#: suite and the census read the same pin.
ADVERSARIAL_MANIFEST = tomllib.loads(
    (CORPUS / "adversarial" / "expected.toml").read_text(encoding="utf-8"))["file"]


def _refusal_arms() -> list[tuple[str, str, str]]:
    arms: list[tuple[str, str, str]] = []
    for af_id in ("AF-18", "AF-19", "AF-20"):
        expected = _expected(af_id)
        arms.append((af_id, expected["documents"][0], expected["refusal"]))
    for entry in ADVERSARIAL_MANIFEST:
        arms.append(("adversarial", entry["name"], entry["refusal"]))
    return arms


REFUSAL_ARMS = _refusal_arms()


@pytest.mark.writtenahead
@pytest.mark.parametrize(("fixture_dir", "name", "sentence"), REFUSAL_ARMS,
                         ids=[f"{directory}-{name}" for directory, name, _ in REFUSAL_ARMS])
def test_tc_author_37_refusal_matrix_fixture_arms(fixture_dir: str, name: str,
                                                  sentence: str) -> None:
    """`TC-AUTHOR-37` (FR-AUTHOR-28 / CT-AUTHOR-23): each fixture-backed arm is refused with
    the exact teacher sentence its corpus entry carries.

    The sentences are pinned in the corpus (and re-pinned against the design table by the
    census's `test_the_refusal_sentences_are_the_design_tables`), so the assertion here is
    exact-match by the test plan §4.3's refusal-completeness property: paraphrase drift is a
    failure, and a raise of the wrong exception class or a refusal that names no sentence is
    too.
    """
    (_, _, _, _, IntakeRefused) = _intake()
    with pytest.raises(IntakeRefused) as raised:
        _normalize(CORPUS / fixture_dir / name)
    assert sentence in str(raised.value), (
        f"{CASE}: {fixture_dir}/{name} was refused, but not with the sentence the design "
        f"table pins (the corpus carries it in expected.toml)"
    )


@pytest.mark.writtenahead
def test_tc_author_32_af21_formats_normalize_identically() -> None:
    """`TC-AUTHOR-32` (FR-AUTHOR-24 / CT-AUTHOR-21): the same content, .docx and .txt.

    AF-21's third document is AF-14's content re-encoded as .txt (the census proves the twin
    content-identical by construction); here the *normalized* outputs must agree — the same
    block texts out of both formats, each reporting its own `source_format`.
    """
    af14 = _expected("AF-14")
    af21 = _expected("AF-21")
    document_docx = _normalize(CORPUS / "AF-14" / af14["documents"][0])
    document_txt = _normalize(CORPUS / "AF-21" / af21["documents"][-1])
    assert document_docx.source_format == "docx"
    assert document_txt.source_format == "txt"
    assert [block.text for block in document_docx.blocks] == \
        [block.text for block in document_txt.blocks], (
        f"{CASE}: the cross-format pair's normalized block texts differ — the formats are "
        f"not independent after all"
    )


@pytest.mark.writtenahead
def test_af21_mixed_pair_normalizes_both_documents() -> None:
    """AF-21's mixed set: every document normalizes, each reporting its own format.

    The fixture half of the mixed-set clause (TC-AUTHOR-38's context, TC-E2E-11's carry-over
    journey's entry): a .docx test and a .txt memo handed in together must both produce
    blocks under the one representation, with `format` aligned to `documents` as the corpus
    declares it.
    """
    expected = _expected("AF-21")
    assert len(expected["format"]) == len(expected["documents"])
    for name, source_format in zip(expected["documents"], expected["format"]):
        document = _normalize(CORPUS / "AF-21" / name)
        assert document.source_format == source_format, (
            f"AF-21: {name} normalized to format {document.source_format!r}"
        )
        assert document.blocks, f"AF-21: {name} normalized to no blocks"
