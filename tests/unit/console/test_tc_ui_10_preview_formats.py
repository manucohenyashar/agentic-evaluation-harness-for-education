"""`TC-UI-10` arm (d) — the preview read carries the formats the upload invites.

The SPA's upload input advertises `.docx`, `.txt` and `.pdf` (`PackageAuthor.tsx`'s
`accept`, FR-UI-11 / FR-CONSOLE-50 / R5a), the library's intake normalizes all three
(`aeh.author.intake.normalize_document`), and the drafting job drafts all three —
but the console's preview read routed every non-PDF to the PDF-only extractor and
refused Word and text files with "arrive in a later update" (the defect the
`TC-E2E-08` and `TC-E2E-11` journeys hit before their first browser leg). This case
is that defect's regression: the preview read must answer `.docx` and `.txt` through
the same intake the draft job runs, project the same summary shape the SPA renders,
and leave a genuinely unreadable kind — `AF-18`'s legacy `.doc` — to the intake
matrix's own teacher sentence (`FR-AUTHOR-28`), never a console paraphrase of it.

Rung 0: real fixture bytes, no model call, no store, no browser — unmarked, so the
fast tier keeps the regression honest from its first commit.
"""

from __future__ import annotations

from aeh.console.authoring_reads import _preview_document
from tests.support.author_vocabulary import af


def _file(fixture: str, name: str) -> tuple[str, bytes]:
    path = af(fixture) / name
    return name, path.read_bytes()


def test_preview_read_accepts_the_docx_upload_and_projects_its_blocks() -> None:
    """AF-14's `.docx` previews like the draft job's own intake: blocks with kinds (the
    rubric table carried, `TC-AUTHOR-33`), the summary stats, the warning stream."""
    name, data = _file("AF-14", "hist7-rome-01-test-and-grading.docx")
    answer = _preview_document(name, data)
    assert answer["accepted"] is True, answer
    assert "refusal" not in answer
    assert answer["name"] == name
    assert answer["pages"] == 1
    blocks = answer["blocks"]
    assert blocks, "the .docx preview carries no blocks"
    for ordinal, block in enumerate(blocks):
        assert block["ordinal"] == ordinal
        assert block["page"] == 1
        assert block["text"].strip(), f"block {ordinal} carries no text: {block!r}"
        assert block["kind"] in {"heading", "paragraph", "list_item", "table", "image_ref"}
    stats = answer["stats"]
    assert stats["page_count"] == 1
    assert stats["block_count"] == len(blocks)
    assert stats["word_count"] > 0
    assert stats["table_count"] >= 1, (
        f"AF-14's rubric table is not carried: {stats!r} (TC-AUTHOR-33)")
    for warning in answer["warnings"]:
        assert warning["code"], warning
        assert warning["message"].strip(), warning


def test_preview_read_accepts_the_txt_upload() -> None:
    """AF-17's `.txt` previews through the same intake: one page, its text as blocks."""
    name, data = _file("AF-17", "hist6-great-fire-01-prose-test.txt")
    answer = _preview_document(name, data)
    assert answer["accepted"] is True, answer
    assert answer["pages"] == 1
    blocks = answer["blocks"]
    assert blocks, "the .txt preview carries no blocks"
    joined = "\n".join(block["text"] for block in blocks)
    assert "Great Fire" in joined, "the .txt preview lost the document's own text"
    assert answer["stats"]["word_count"] > 0
    assert answer["stats"]["table_count"] == 0


def test_preview_read_still_accepts_the_pdf_upload() -> None:
    """AF-01's `.pdf` previews unchanged: page-marked blocks from the text layer."""
    name, data = _file("AF-01", "hist7-rome-01-test-and-grading.pdf")
    answer = _preview_document(name, data)
    assert answer["accepted"] is True, answer
    blocks = answer["blocks"]
    assert blocks
    assert all(block["page"] >= 1 for block in blocks)
    assert answer["stats"]["page_count"] >= 1


def test_preview_read_leaves_the_unreadable_kind_to_the_intake_matrix() -> None:
    """AF-18's legacy `.doc` is refused with FR-AUTHOR-28's own sentence and its next
    step — the matrix row, not a console paraphrase (`TC-AUTHOR-37a`'s sentence)."""
    name, data = _file("AF-18", "geo6-mapwork-01-legacy.doc")
    answer = _preview_document(name, data)
    assert answer["accepted"] is False, answer
    refusal = answer["refusal"]
    assert "older Word format" in refusal["detail"], refusal
    assert ".docx" in refusal["detail"] + refusal["next_action"], refusal
