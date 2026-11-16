"""The citation clause suite's world (#894, statistical-validity test plan §3.1/§3.2, story T1).

**The document.** Every case reads the REAL canonical document of the sample ENG7 class, produced
by ingesting the four answer sheets through the operator path (`tests/support/eng7_sample.py`'s
`ingest_eng7`: `aeh package build`, `aeh cohort create`, `aeh ingest`, with only the OpenRouter
transport stood in). The ingest runs once per test session (about four seconds) and its documents
are cached by student name. Nothing here hand-writes region markup: the `<!-- region: ... -->`
headers, the `question_id=` tags and the closes are what M-INGEST wrote.

**The judged unit (rung 1 + a real store).** `citation_world` seeds one judged unit over that
document: a real package version whose criterion names its question (so the worker resolves the
unit's answer region, ADR-63), a real cohort ledger with the document's bytes in the blob store,
an optional roster name (the pseudonymization boundary, #593), a real run, and the REAL
extraction leg, which offers exactly the evidence spans a case names. The judge's reply is the
controlled condition: recorded under the unit's exact request key in `RecordedFixtureProvider`
(the only egress, CT-PROV-15), then `ScoringWorker.dispatch` + `persist` and the stored verdict
row read back. No provider is reached and no reply here is a recording of a live model: replies
are built by each case from the rendered prompt or from the document's own bytes.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import pytest

from aeh.orch import STAGE_EXTRACT, STAGE_SCORE, Orchestrator
from tests.support.extract_vocabulary import extractor_ref, sampling_params, span_completion
from tests.support.judge_run import resolved, seed_judged_package, warm_judged_modules
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_document

#: The judged student: the strong paper, whose three answers are all present.
STUDENT = "E7-001"

#: C2's real band set, from the shipped `eng7-read-01.package.toml` (worst first).
C2_BANDS: tuple[tuple[str, float, str], ...] = (
    ("none", 0.0, "No relevant answer."),
    ("limited", 1.0, "Repeats the passage ('he lights it every night') without giving a reason."),
    ("adequate", 2.0, "Gives a sensible reason, but with no evidence from the passage."),
    ("full", 3.0, "Gives a reason (someone might still need the light, such as a small boat) AND "
                  "supports it with evidence from the passage."),
)

_SUBMISSION = "sub-e7-001"
_REF = "ref-sub-e7-001"  # `seed_cohort`'s student_ref for the submission

_CANONICAL: dict[str, str] = {}


def eng7_canonical(student: str = STUDENT) -> str:
    """The canonical document M-INGEST produced for `student`'s answer sheet (cached per session)."""
    if not _CANONICAL:
        _ingest_once()
    return _CANONICAL[student]


def _ingest_once() -> None:
    pytest.importorskip("pypdfium2")
    from aeh.store import open_store
    from tests.support.eng7_sample import (
        DEV_CI_CONFIG, ENG7_COHORT, forget_sample_modules, ingest_eng7)

    root = Path(tempfile.mkdtemp(prefix="aeh-citation-eng7-"))
    (root / "data").mkdir()
    (root / "work").mkdir()
    with pytest.MonkeyPatch.context() as monkeypatch:
        for key in ("HARNESS_PROFILE", "HARNESS_FIXTURE_DIR"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("HARNESS_DECISION_ENGINE", "off")
        try:
            ingest_eng7(root / "data", root / "work", monkeypatch, DEV_CI_CONFIG)
        finally:
            forget_sample_modules()
    store = open_store(root / "data")
    try:
        rows = store.cohort(ENG7_COHORT).query(
            "SELECT r.full_name AS name, d.markdown AS markdown FROM document d "
            "JOIN submission s ON s.submission_id = d.submission_id "
            "JOIN roster r ON r.student_ref = s.student_ref")
        for row in rows:
            _CANONICAL[row["name"]] = row["markdown"]
    finally:
        store.close()
    assert STUDENT in _CANONICAL, f"fixture bug: the ENG7 ingest produced {sorted(_CANONICAL)}"


def byte_span(doc: bytes, text: str, *, occurrence: int = 0) -> dict[str, Any]:
    """`{start, end, text}` over the `occurrence`-th byte-exact occurrence of `text` in `doc`."""
    needle = text.encode("utf-8")
    start = -1
    for _ in range(occurrence + 1):
        start = doc.find(needle, start + 1)
        assert start >= 0, f"fixture bug: {text!r} occurrence {occurrence} is not in the document"
    return {"start": start, "end": start + len(needle), "text": text}


def region_body(doc: bytes, question_id: str) -> tuple[int, int]:
    """The byte extent of the body of the region the document tags `question_id=<question_id>`,
    found by reading the bytes (not through `aeh.integ.answer_regions`, the code under test)."""
    tag = f"question_id={question_id} ".encode("utf-8")
    at = doc.find(tag)
    assert at >= 0, f"fixture bug: no region tagged {question_id}"
    start = doc.find(b"-->", at) + len(b"-->")
    end = doc.find(b"<!-- /region -->", start)
    return start, end


@dataclass
class CitationWorld:
    store: Any
    provider: Any
    orchestrator: Any
    run_id: str
    unit: Any
    judge: Any
    request: Any
    doc: bytes
    submission_id: str = _SUBMISSION
    student_ref: str = _REF

    def worker(self, *, provider: Any = None, **kwargs: Any) -> Any:
        from aeh.judge import ScoringWorker

        worker = ScoringWorker(self.store, provider or self.provider, self.judge, **kwargs)
        assert worker.assemble(self.unit) == self.request, "fixture bug: assembly is not pure"
        return worker

    def record(self, reply: Any, request: Any = None) -> None:
        """Record `reply` (a JSON-able mapping or the raw reply text) as the judge's answer to the
        unit's exact request."""
        from aeh.judge import prompt_fields
        from aeh.prov import Completion

        text = reply if isinstance(reply, str) else json.dumps(reply)
        self.provider.record(
            prompt_fields(request or self.request), self.judge, sampling_params(),
            Completion(text=text, tokens_in=0, tokens_out=0, latency_ms=0,
                       resolved_build=self.judge.build_id, cached_prefix_tokens=0, cost=None))

    def judge_and_store(self, reply: Any, **worker_kwargs: Any) -> Any:
        """Dispatch the unit against `reply` and persist the verdict; the stored row comes back.
        A refused reply raises out of `dispatch` and nothing is persisted."""
        self.record(reply)
        worker = self.worker(**worker_kwargs)
        result = worker.dispatch(self.request, self.judge)
        worker.persist(self.unit, result)
        return self.verdict_row()

    def verdict_rows(self) -> list[dict[str, Any]]:
        rows = self.store.cohort(ORCH_COHORT_ID).query(
            "SELECT v.* FROM verdict v WHERE v.work_id = :w", w=self.unit.work_id)
        return [dict(row) for row in rows]

    def verdict_row(self) -> dict[str, Any]:
        rows = self.verdict_rows()
        assert len(rows) == 1, f"expected one stored verdict, found {len(rows)}"
        row = rows[0]
        row["cited_spans"] = json.loads(row["cited_spans"] or "[]")
        return row


def citation_world(
    store: Any,
    provider: Any,
    *,
    offered: Sequence[dict[str, Any]] = (),
    criterion_id: str = "C2",
    question_id: str = "Q2",
    bands: tuple[tuple[str, float, str], ...] = C2_BANDS,
    roster_name: str | None = None,
    document: str | None = None,
    others: Sequence[tuple[str, str, Sequence[dict[str, Any]]]] = (),
) -> CitationWorld:
    """One judged unit over E7-001's real canonical document (or `document`), its extraction leg
    having offered exactly `offered` (spans over the document's own bytes). `others` adds further
    criteria of the same run as `(criterion_id, question_id, offered)`: units the case does not
    judge, whose evidence is offered to them and not to the judged unit. One judge (panel of one),
    so the judged unit is the decision seat when a decision engine is configured."""
    warm = warm_judged_modules()
    extract_assemble, extract_worker = warm["extract"]
    extract_prompt_fields = warm["extract_prompt_fields"]
    markdown = document if document is not None else eng7_canonical()
    specs = ((criterion_id, question_id, offered),) + tuple(others)
    version = seed_judged_package(
        store, bands=bands,
        criteria=tuple({"criterion_id": cid, "kind": "open", "scoring_model": "atomic",
                        "band_count": len(bands), "question_id": qid} for cid, qid, _ in specs))
    seed_cohort(store, [_SUBMISSION])
    if roster_name is not None:
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute("INSERT INTO roster (cohort_id, student_ref, full_name) VALUES (:c, :r, :n)",
                       c=ORCH_COHORT_ID, r=_REF, n=roster_name)
    seed_document(store, _SUBMISSION, markdown)
    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(ORCH_COHORT_ID, version, resolved(1))
    offered_by = {cid: spans for cid, _qid, spans in specs}
    extract_units = list(orchestrator.lease("w-extract-citation", STAGE_EXTRACT, 8))
    assert sorted(u.criterion_id for u in extract_units) == sorted(offered_by)
    for extract_unit in extract_units:
        extract_request = extract_assemble(extract_unit, store=store)
        spans = [dict(span, region_kind="transcribed_text")
                 for span in offered_by[extract_unit.criterion_id]]
        provider.record(extract_prompt_fields(extract_request), extractor_ref(), sampling_params(),
                        span_completion(spans, build_id="extractor-build-citation"))
        extract_worker(store, provider, extractor_ref()).process(extract_unit)
    from aeh.judge import ScoringWorker
    from tests.support.conf_builders import edge_panel

    (judge,) = edge_panel(1)
    units = list(orchestrator.lease("w-judge-citation", STAGE_SCORE, 8))
    unit = next((u for u in units if u.criterion_id == criterion_id), None)
    assert unit is not None, f"precondition: no score unit for {criterion_id} in {units!r}"
    request = ScoringWorker(store, provider, judge).assemble(unit)
    return CitationWorld(store=store, provider=provider, orchestrator=orchestrator, run_id=run_id,
                         unit=unit, judge=judge, request=request,
                         doc=markdown.encode("utf-8"))


__all__ = [
    "C2_BANDS", "CitationWorld", "STUDENT", "byte_span", "citation_world", "eng7_canonical",
    "region_body",
]
