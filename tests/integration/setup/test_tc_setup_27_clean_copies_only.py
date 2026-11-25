"""TC-SETUP-27 (issue #907; FR-SETUP-21, OQ-4): clean copies only.

Statistical-validity test plan §3.12, story T10. An example whose page 2 carries marking
annotations is refused with exactly *"Page 2 of <file> has marks on it. Please upload an unmarked
copy, and enter your marks in the form."*, and its clean twin is accepted.

**The fixture follows OQ-4's answer.** S15 (#885) answered OQ-4 with a deterministic check over
the stored transcript (`aeh.setup.marked_pages`, `CLEAN_COPY_CHECK = transcript-marks-v1`). The
transcription prompt was not changed. So the fixture is a two-page answer sheet whose page-2
*transcript* carries a mark, in each of two forms: a lone score (`3/5`) on its own line beside
the answer, and a tick (`✓`) after the answer. Its twin is the same two pages with only that
mark line removed. A precondition asserts the stored Markdown: two pages on `PAGE_BREAK`, with
the mark on page 2 only.

**Two code paths build this sentence, and both are covered.**

- (a) M-SETUP, `SetupService.add_marked_examples`, over a real `Ingestor` and real tiers
  (`tests/support/setup_harness.py`, rung 3). Only the transcriber is scripted, answering the
  two pages in order. `ingest_document` transcribes the sources sequentially, in blob order,
  and `order_hint` fixes the assembly. The refusal is the raised `MarkedExampleRefused`, and
  the refused upload stores nothing.
- (b) The console's `examples upload` (`aeh.calib.add_examples` with `clean_copy_check =
  marked_pages`), in the ENG7 examples world (`tests/support/eng7_examples.py`, a real console
  on loopback, rung 3). The uploads are real two-page PDFs, and the stand-in transcriber answers
  each (file, page) from the transcripts below. The refusal is the job's outcome sentence for
  that file, and the examples read lists only the clean twin.

Markers: `integration`.
"""

from __future__ import annotations

import io
import json

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.ingest import PAGE_BREAK

pytestmark = pytest.mark.integration

#: The exact refusal (FR-SETUP-21), for a file name.
REFUSAL = ("Page 2 of {file} has marks on it. Please upload an unmarked copy, and enter your "
           "marks in the form.")

#: The two forms of a marker's annotation on page 2: an awarded score, and a tick.
MARKS = {"lone-score": "3/5", "tick": "✓"}

# --- (a) M-SETUP --------------------------------------------------------------------------------

#: Page 1 and page 2 of the M-SETUP answer sheet (setup_harness's physics submission, split).
SETUP_PAGE_1 = ("Submission — Physics 102, student 2101\n\n"
                "Q1. Impulse is the net force acting over the contact time.\n")
SETUP_PAGE_2 = ("Q3. Starting from impulse, the range follows by eliminating the flight time.\n"
                "{mark}\n"
                "Q4. (A)\n")


def _setup_page_2(mark: str | None) -> str:
    text = SETUP_PAGE_2.format(mark=mark or "")
    return text.replace("\n\n", "\n") if mark is None else text


class _PagedTranscriber:
    """Answers the transcription calls in order, one transcript per page."""

    def __init__(self, pages: list[str]) -> None:
        self.pages = list(pages)

    def complete(self, prompt, model_ref, params):
        from aeh.prov import Completion

        return Completion(text=self.pages.pop(0), tokens_in=10, tokens_out=5, latency_ms=1,
                          resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None)


def _draft(tmp_data_dir, package_id: str):
    """TC-SETUP-26's chain: through the read back and the keys, a draft ready for examples."""
    from tests.support.setup_harness import ingest_document, stage_chain

    chain = stage_chain(tmp_data_dir, package_id=package_id)
    assessment = ingest_document(chain.store)
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(assessment)
    chain.service.confirm_inventory(proposal.proposal_id)
    chain.provider.replies = [json.dumps({"criteria": [
        {"criterion_id": "CRIT-MET", "question_id": "Q1", "kind": "open",
         "scoring_model": "holistic", "max_points": 4.0,
         "construct": "the response defines impulse as force acting over contact time"},
        {"criterion_id": "CRIT-TYPED", "question_id": "Q2", "kind": "open",
         "scoring_model": "holistic", "max_points": 5.0,
         "construct": "the response derives the range equation"},
    ]})]
    chain.service.read_back_rubric(rubric, assessment)
    chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})
    return chain


def _two_page_example(chain, name: str, page_2: str) -> str:
    """A really ingested two-page answer sheet (two one-page sources, in order)."""
    from tests.support.setup_harness import build_ingestor

    ingestor = build_ingestor(chain.store)
    ingestor._provider = _PagedTranscriber([SETUP_PAGE_1, page_2])
    blobs = chain.store.blobs()
    first = blobs.put(f"{name} page 1".encode())
    second = blobs.put(f"{name} page 2".encode())
    return str(ingestor.ingest_document([first, second], kind="submission",
                                        order_hint=[first, second],
                                        filenames={first: name, second: name}))


def _assert_two_pages_marked_on(chain, document_id: str, marked: bool, mark: str) -> None:
    """Precondition: the stored Markdown is two pages, the mark on page 2 alone (or nowhere)."""
    rows = chain.store.cohort("c-setup").query(
        "SELECT markdown FROM document WHERE document_id = :d", d=document_id)
    pages = str(rows[0]["markdown"]).split(PAGE_BREAK)
    assert len(pages) == 2, f"precondition: a two-page transcript, got {len(pages)} page(s)"
    assert mark not in pages[0]
    assert (mark in pages[1]) is marked, pages[1]


@pytest.mark.parametrize("kind", sorted(MARKS))
def test_tc_setup_27_a_m_setup_refuses_a_marked_page_2_and_accepts_its_clean_twin(
        tmp_data_dir, kind):
    from aeh.setup import MarkedExampleRefused

    mark = MARKS[kind]
    chain = _draft(tmp_data_dir, f"pkg-t27-{kind}")
    try:
        marked = _two_page_example(chain, "maya.pdf", _setup_page_2(mark))
        clean = _two_page_example(chain, "maya-clean.pdf", _setup_page_2(None))
        _assert_two_pages_marked_on(chain, marked, True, mark)
        _assert_two_pages_marked_on(chain, clean, False, mark)

        with pytest.raises(MarkedExampleRefused) as refused:
            chain.service.add_marked_examples({marked: "maya.pdf"})
        after_refusal = chain.service.marked_examples()
        step = chain.service.add_marked_examples({clean: "maya-clean.pdf"})
    finally:
        chain.store.close()

    assert str(refused.value) == REFUSAL.format(file="maya.pdf"), str(refused.value)
    assert after_refusal.examples == (), "the refused upload stored an example"
    assert dict(step.examples) == {clean: "maya-clean.pdf"}, step.examples
    assert step.clean_copy_check == "transcript-marks-v1"


# --- (b) the console's `examples upload` ----------------------------------------------------------


def _two_page_pdf(first: bytes, second: bytes) -> bytes:
    """A real two-page PDF: page 1 of `first`, then page 1 of `second`."""
    import pypdfium2 as pdfium

    out = pdfium.PdfDocument.new()
    for data in (first, second):
        out.import_pages(pdfium.PdfDocument(data), [0])
    buffer = io.BytesIO()
    out.save(buffer)
    return buffer.getvalue()


def _split_sheet(transcript: str, mark: str | None) -> tuple[str, str]:
    """E7-001's sheet transcript as two pages: Q1 and Q2 on page 1, Q3 on page 2. `mark` goes on
    its own line inside Q3's answer region, after the answer line."""
    head, q3 = transcript.split("\n## Q3\n", 1)
    if mark is not None:
        q3 = q3.replace("\n<!-- /region -->", f"\n{mark}\n<!-- /region -->", 1)
        assert mark in q3, "fixture: Q3 has no answer region to mark"
    return head, "## Q3\n" + q3


def test_tc_setup_27_b_console_upload_refuses_marked_page_2_and_accepts_the_clean_twin(
        tmp_path, monkeypatch, network_guard):
    pytest.importorskip("pypdfium2")
    from tests.support.eng7_examples import eng7_examples

    with eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch, network_guard) as world:
        sheets = world.sheets
        blobs = world.store().blobs()
        sheet_page = world.fake.pages[(blobs.put(sheets["E7-001-strong"]), 1)]
        # Distinct bytes per upload: page 2 is lifted from a different ENG7 sheet each time (the
        # stand-in transcriber answers from the transcripts registered here, never the pixels).
        files = {
            "E7-001-score.pdf": (_two_page_pdf(sheets["E7-001-strong"], sheets["E7-002-middle"]),
                                 MARKS["lone-score"]),
            "E7-001-tick.pdf": (_two_page_pdf(sheets["E7-001-strong"], sheets["E7-003-weak"]),
                                MARKS["tick"]),
            "E7-001-clean.pdf": (_two_page_pdf(sheets["E7-001-strong"],
                                               sheets["E7-004-mostly-blank"]), None),
        }
        pages_of = {}
        for name, (data, mark) in files.items():
            assert len({d for d, _ in files.values()}) == 3, "fixture: two uploads share bytes"
            page_1, page_2 = _split_sheet(sheet_page, mark)
            digest = blobs.put(data)
            world.fake.pages[(digest, 1)] = page_1
            world.fake.pages[(digest, 2)] = page_2
            pages_of[name] = (page_1, page_2)
        # The twin differs from each marked file only by the mark line on page 2.
        clean_2 = pages_of["E7-001-clean.pdf"][1]
        for name, mark in (("E7-001-score.pdf", "3/5"), ("E7-001-tick.pdf", "✓")):
            assert pages_of[name][1].replace(f"\n{mark}\n", "\n", 1) == clean_2, name

        outcome = world.dispatched("examples upload", package_version=world.package_version,
                                   consent="synthetic",
                                   test_paper={"name": "01-test-paper.pdf",
                                               "content_base64": _b64(world.test_paper)},
                                   documents=[{"name": name, "content_base64": _b64(data)}
                                              for name, (data, _) in files.items()])
        job = world.wait_job(outcome["job_id"])
        listed = [example["file_name"] for example in world.examples_read()["examples"]]

    assert job["state"] == "succeeded", job
    sentence = json.dumps(job, ensure_ascii=False)
    for name in ("E7-001-score.pdf", "E7-001-tick.pdf"):
        expected = f"{name} was not used: {REFUSAL.format(file=name)}"
        assert expected in sentence, f"{name}: no exact refusal in the job outcome {job}"
    assert "E7-001-clean.pdf was not used" not in sentence, job
    assert listed == ["E7-001-clean.pdf"], f"the examples read lists {listed}"


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode()
