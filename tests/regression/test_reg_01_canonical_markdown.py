"""The assembled Markdown for a fixture document does not move on its own.

Case: `TC-REG-01` (test plan §6.9), `FR-INGEST-04`, `FR-INGEST-06`, golden file.

§6.9's row states the baseline and, unusually for a test case, states who may change it:

    baseline  Canonical assembled Markdown per `F-SYNTH` and `F-GRAPHIC` document
    reviewer  The ingestion owner
    grounds   Accepted only alongside a deliberate transcription-prompt version bump or a
              stated assembly-rule change; never "the model changed its mind"

That last clause is the requirement. Transcription runs through a model, model output drifts,
and the cheap response to a drifted golden is to regenerate it — at which point the baseline
records whatever the model last did rather than what the module promised. So the failure
message here carries the reviewer and the grounds out of `fixtures/baselines/registry.json`,
and there is no helper anywhere in this repo that rewrites a golden in one call.

**Written ahead of implementation** (test plan §8.2). `assemble_canonical_markdown` is #37's
(`M-INGEST` assembly order and page provenance); the golden files are its output and are not
committed yet, for the reason `tests/support/baselines.py` gives. Remove the `writtenahead`
marker — never the test — when #37 closes, and record the baselines in that same PR.
"""

from __future__ import annotations

import pytest

from tests.support import corpora
from tests.support.baselines import assert_matches_golden, entry_for
from tests.support.impl import INGEST_MODULE, require

pytestmark = pytest.mark.writtenahead

ISSUE = "#37"
CASE = "TC-REG-01"


def _canonical_report(assemble, corpus: corpora.Corpus, tmp_path) -> bytes:
    """Every document in the corpus, assembled, in one reviewable artifact.

    One file per corpus rather than one per document, so the reviewer named in §6.9 reads a
    single diff. The per-document header carries what `FR-INGEST-04` and `FR-INGEST-06`
    actually promise — the content hash over the canonical Markdown, a non-null
    `transcriber_ref`, and *which* of the three permitted sources decided assembly order — so a
    change to any of them shows up in the same diff as a change to the prose.
    """
    sections: list[str] = []
    for member in corpus.members:
        pages = corpora.materialize_pages(member, tmp_path / corpus.name / member.id)
        assert pages, f"{member.id} materialized no pages, so there is nothing to assemble"
        document = assemble(pages)
        sections.append(
            "\n".join(
                (
                    f"## {member.id}",
                    f"content_hash: {document.content_hash}",
                    f"transcriber_ref: {document.transcriber_ref}",
                    # `FR-INGEST-06` records *which* source decided assembly order, and it names
                    # the field: `document.source_blobs`. Read under that name rather than a
                    # tidier invented one — the requirement is concrete here, and an implementer
                    # following it would otherwise hit an AttributeError instead of a diff.
                    f"source_blobs: {document.source_blobs}",
                    "",
                    document.canonical_markdown.rstrip("\n"),
                    "",
                )
            )
        )
    return ("\n".join(sections).rstrip("\n") + "\n").encode("utf-8")


def test_tc_reg_01_canonical_markdown_matches_its_baseline_for_every_fixture_document(tmp_path):
    """TC-REG-01 — assembled Markdown per `F-SYNTH` and `F-GRAPHIC` document.

    Oracle: golden file, byte for byte, per §4.3's table.
    """
    assemble = require(INGEST_MODULE, "assemble_canonical_markdown", issue=ISSUE)
    entry = entry_for(CASE)

    produced: dict[str, bytes] = {}
    for corpus_name, golden in (
        ("F-SYNTH", "TC-REG-01/F-SYNTH.canonical.md"),
        ("F-GRAPHIC", "TC-REG-01/F-GRAPHIC.canonical.md"),
    ):
        assert golden in entry.golden, (
            f"{golden} is not one of {CASE}'s registered baselines; the registry is what the "
            f"reviewer in §6.9 is reviewing."
        )
        corpus = corpora.load(corpus_name)
        produced[golden] = _canonical_report(assemble, corpus, tmp_path)

    # `FR-INGEST-04`: the content hash is unique over the canonical Markdown, so two documents
    # that assemble identically are a defect in assembly rather than a coincidence in the
    # corpus. Asserted before the golden comparison because a corpus that collapsed to one
    # document would make a byte-for-byte match against a stale golden meaningless.
    for golden, report in produced.items():
        hashes = [
            line.split(": ", 1)[1]
            for line in report.decode("utf-8").splitlines()
            if line.startswith("content_hash: ")
        ]
        assert len(hashes) == len(set(hashes)), (
            f"{golden}: {len(hashes) - len(set(hashes))} document(s) share a content_hash. "
            f"FR-INGEST-04 makes the hash unique over the canonical Markdown."
        )
        assert_matches_golden(CASE, golden, report)
