"""Replaying the live ENG7 extractor replies through the real extraction worker (#895,
statistical-validity test plan §3.3 / §3.17, story T2).

**The data.** `tests/regression/data/sv11_live_extractions.json` holds every
`answer_extraction` call of the 2026-11-13 live walk (runs A and B, the ENG7 sample class graded
through OpenRouter), with each model reply copied verbatim, and the canonical documents those
replies addressed. Nothing in it is hand-written. Each run extracted every (submission,
criterion) unit twice, so a run splits into two *passes* of sixteen units.

**The replay (rung 3 data, rung 1 transport).** `replay_pass` seeds one real store per pass: a
package version whose criteria name their questions as the live package pinned them (so the
worker resolves each unit's answer region through `unit_question_id`, ADR-63), a cohort whose
documents are the live canonical bytes, and a run. Each extraction unit's reply is recorded
VERBATIM under the unit's exact request key in `RecordedFixtureProvider` (the only egress,
CT-PROV-15), and `ExtractionWorker.process` runs. What comes back is read off the stored
`evidence` rows, never off the worker's return value.

**The independent oracle.** `answer_bodies` and `question_body` find region extents by reading
the bytes (the `tests/support/citation_world.region_body` approach), not through
`aeh.integ.answer_regions` or `aeh.extract.spans`, the code under test.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

from aeh.orch import STAGE_EXTRACT, Orchestrator
from tests.support.extract_vocabulary import extractor_ref, sampling_params
from tests.support.judge_run import JUDGE_RUN_BANDS, resolved, seed_judged_package, warm_judged_modules
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_document

LIVE_EXTRACTIONS = json.loads(
    (Path(__file__).resolve().parents[1] / "regression" / "data" / "sv11_live_extractions.json")
    .read_text(encoding="utf-8"))

#: The live package's criterion -> question map, as both runs pinned it.
CRITERION_QUESTIONS: dict[str, str] = LIVE_EXTRACTIONS["criterion_questions"]

#: The second-family extractor the spy arm flags a criterion for (a different provider/build).
SECOND_FAMILY = extractor_ref(build_id="/models/other-family.gguf@sha256:ffff", provider="other")

_OPEN = b"<!-- region:"
_CLOSE = b"<!-- /region -->"


def live_documents(run: str) -> dict[str, str]:
    """`submission_id -> canonical markdown` for one live run (`"A"` or `"B"`)."""
    return {d["submission_id"]: d["markdown"] for d in LIVE_EXTRACTIONS["runs"][run]["documents"]}


def live_students(run: str) -> dict[str, str]:
    """`submission_id -> student name` (E7-001 ... E7-004) for one live run."""
    return {d["submission_id"]: d["student"] for d in LIVE_EXTRACTIONS["runs"][run]["documents"]}


def live_passes(run: str) -> list[dict[tuple[str, str], str]]:
    """The run's calls split into passes: pass n holds the n-th reply each (submission,
    criterion) unit received, in log order."""
    passes: list[dict[tuple[str, str], str]] = []
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for call in LIVE_EXTRACTIONS["runs"][run]["calls"]:
        key = (call["submission_id"], call["criterion_id"])
        index = seen[key]
        seen[key] += 1
        while len(passes) <= index:
            passes.append({})
        passes[index][key] = call["response"]
    return passes


def answer_bodies(doc: bytes) -> list[tuple[int, int]]:
    """Every region's answer text, by reading the bytes: from just after the opening marker's
    `-->` to just before the closing `<!-- /region -->`."""
    bodies = []
    at = doc.find(_OPEN)
    while at >= 0:
        start = doc.find(b"-->", at) + len(b"-->")
        end = doc.find(_CLOSE, start)
        assert start >= len(b"-->") and end >= 0, "fixture bug: an unclosed region"
        bodies.append((start, end))
        at = doc.find(_OPEN, end)
    return bodies


def question_body(doc: bytes, question_id: str) -> tuple[int, int]:
    """The answer text of the region tagged `question_id=<question_id>` (exactly one)."""
    tags = [m.start() for m in re.finditer(rb"question_id=" + question_id.encode() + rb"[ \-]", doc)]
    assert len(tags) == 1, f"fixture bug: {len(tags)} regions tagged {question_id}"
    start = doc.find(b"-->", tags[0]) + len(b"-->")
    return start, doc.find(_CLOSE, start)


def _completion(text: str, build_id: str) -> Any:
    from aeh.prov import Completion

    return Completion(text=text, tokens_in=0, tokens_out=0, latency_ms=0,
                      resolved_build=build_id, cached_prefix_tokens=0, cost=None)


def replay_pass(
    store: Any,
    provider: Any,
    documents: dict[str, str],
    replies: dict[tuple[str, str], str],
    *,
    criterion_questions: dict[str, str] = CRITERION_QUESTIONS,
    high_risk: Sequence[str] = (),
) -> dict[tuple[str, str], list[dict[str, Any]] | None]:
    """Run every (submission, criterion) unit in `replies` through the real extraction worker,
    each answering with its reply text verbatim. Returns, per unit, the spans its stored
    `evidence` row carries, or None when no evidence row was stored (the reply refused)."""
    warm = warm_judged_modules()
    extract_assemble, extract_worker = warm["extract"]
    extract_prompt_fields = warm["extract_prompt_fields"]
    criteria = sorted({criterion for _sub, criterion in replies})
    version = seed_judged_package(store, criteria=tuple(
        {"criterion_id": cid, "kind": "open", "scoring_model": "atomic",
         "band_count": len(JUDGE_RUN_BANDS), "question_id": criterion_questions[cid]}
        for cid in criteria))
    submissions = sorted(documents)
    seed_cohort(store, submissions)
    for submission_id in submissions:
        seed_document(store, submission_id, documents[submission_id])
    orchestrator = Orchestrator(store)
    orchestrator.create_run(ORCH_COHORT_ID, version, resolved(1))
    units = list(orchestrator.lease("w-extract-replay", STAGE_EXTRACT, 4 * len(replies) + 8))
    assert sorted((u.submission_id, u.criterion_id) for u in units) == sorted(replies), (
        "fixture bug: the run's extraction units are not the replayed ones")
    worker = extract_worker(store, provider, extractor_ref(),
                            second_family_model=SECOND_FAMILY, high_risk_criteria=tuple(high_risk))
    by_work: dict[str, tuple[str, str]] = {}
    for unit in units:
        key = (unit.submission_id, unit.criterion_id)
        by_work[unit.work_id] = key
        fields = extract_prompt_fields(extract_assemble(unit, store=store))
        provider.record(fields, extractor_ref(), sampling_params(),
                        _completion(replies[key], "extractor-build-replay"))
        if unit.criterion_id in high_risk:
            provider.record(fields, SECOND_FAMILY, sampling_params(),
                            _completion(replies[key], "second-family-build-replay"))
        worker.process(unit)
    stored: dict[tuple[str, str], list[dict[str, Any]] | None] = {key: None for key in replies}
    for row in store.cohort(ORCH_COHORT_ID).query("SELECT work_id, payload FROM evidence"):
        payload = row["payload"]
        payload = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        stored[by_work[row["work_id"]]] = json.loads(payload)["spans"]
    return stored


__all__ = [
    "CRITERION_QUESTIONS", "LIVE_EXTRACTIONS", "SECOND_FAMILY", "answer_bodies", "live_documents",
    "live_passes", "live_students", "question_body", "replay_pass",
]
