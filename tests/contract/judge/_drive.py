"""The compact rung-2/3 drive the `M-JUDGE` contract cases share (TS-67, issue #85).

The run-shaped world is `tests/support/orch_run.py`'s (built by #63); this file is
`tests/contract/agg/_drive.py`'s shape compressed to what the judge clauses need —
the judge cases drive finer than the aggregation ones, so the drive carries the
control points they assert over:

- `seed_world` / `drive_judged_run` — a real run driven to a judged panel,
  `(orchestrator, run_id, version)` out, with the verdict band, the panel's
  self-confidence and the citation choice as parameters. Every worker is real;
  the only stand-in is the recorded fixture provider's completions (§4.2: it IS
  the deterministic transport, not a fake).
- `offline_request` — a hand-built `ScoringRequest` for the rung-0 limbs that
  must control the rubric content directly (the two-sided numeral fixtures, the
  adversarial submissions), through the whitelist construction door.
- `RecordingTransport` — a provider double AT THE MODEL BOUNDARY (`§4.2` allows
  a stand-in here and nowhere else): every `complete` call recorded with the
  params the dispatch actually bound, a program of completions back. The
  non-promise cases (`TC-JUDGE-C17`) and the knob cases (`TC-JUDGE-C13`) need a
  boundary that reports what it was sent, which the fixture provider records
  only implicitly.
- `verdict_rows` — the verdict rows read back from the real ledger.

Isolation: rung 2/3 — real store, real package, real workers; the socket guard
is autouse. The drives write no `criterion_score` row themselves.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from aeh.extract import ExtractionWorker
from aeh.extract import assemble_request, prompt_fields as extract_prompt_fields
from aeh.judge import (
    BandView,
    CriterionView,
    ExemplarView,
    QuestionView,
    ScoringRequest,
    ScoringWorker,
    SubmissionView,
    prompt_fields as judge_prompt_fields,
)
from aeh.orch import STAGE_EXTRACT, STAGE_SCORE
from aeh.pkg import PackageCatalog
from aeh.prov import Completion
from tests.support.conf_builders import EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3
from tests.support.extract_vocabulary import (
    extractor_ref,
    sampling_params,
    span_completion,
    verdict_completion,
)
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    PLAIN_TRANSCRIPT,
    seed_document,
    seed_documents,
    seed_run,
)

#: The three-judge edge panel, as the orchestrator's own fixture resolves it.
PANEL_REFS = (EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3)

_WORKER_NAME = "w-judge-contract"

_EXTRACT_BUILD = "build-judge-contract-extract"

_JUDGE_BUILD = "build-judge-contract"

#: The declared band set the default criterion carries — EVEN in number
#: (CT-JUDGE-04's clause), descriptors riding beside the labels so the render's
#: bands field is the real rubric surface the numeral scan reads.
BANDS: tuple[tuple[str, float, str], ...] = (
    ("emerging", 2.0, "the criterion is partly met"),
    ("secure", 4.0, "the criterion is met"),
)

#: The needle the fixture transcript carries — a cited span's byte range is cut
#: from the canonical document so the grounding gate verifies it (`FR-JUDGE-17`).
NEEDLE = "The evidence supports the conclusion"


def spans(text: str = PLAIN_TRANSCRIPT) -> list[dict[str, object]]:
    """A span completion's spans over the fixture transcript — or over any text a
    case passes, which is how the forged-citation construction is built."""
    start = text.find(NEEDLE)
    assert start >= 0, "fixture bug: the span needle is not in the transcript"
    return [{"start": start, "end": start + len(NEEDLE), "text": NEEDLE}]


def add_bands(store: Any, version: str, criterion_id: str,
              bands: Sequence[tuple[str, float, str]]) -> None:
    """The criterion's REAL band set, through the shipped catalog API — the
    pairs arrive in ordinal order, even in number (`CT-JUDGE-04`)."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    for ordinal, (name, points, descriptor) in enumerate(bands):
        catalog.add_band(version, criterion_id, ordinal, name, points, descriptor)


def seed_world(
    store: Any,
    *,
    submissions: Sequence[str] = ("SYN-001",),
    criterion_specs: Sequence[dict[str, Any]] | None = None,
    bands: Sequence[tuple[str, float, str]] = BANDS,
    transport: Any = None,
    panel: Any = None,
    texts: Sequence[str] | None = None,
) -> tuple[Any, str, str]:
    """Cohort, package, documents, run — enumerated and started.

    `criterion_specs` defaults to one open atomic criterion `C1` carrying
    `bands`' set. The run is born `pending`; callers enumerate and start (the
    default here does both) or take over the lifecycle themselves. `texts` gives
    one document text PER submission (the sentinel/no-history cases); the
    default seeds `PLAIN_TRANSCRIPT` for every one.
    """
    if criterion_specs is None:
        criterion_specs = [{
            "criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
            "band_count": len(tuple(bands)),
        }]
    orchestrator, run_id, version = seed_run(
        store, submissions=submissions, criteria=criterion_specs, transport=transport,
        panel=panel,
    )
    for criterion_spec in criterion_specs:
        add_bands(store, version, criterion_spec["criterion_id"], bands)
    if texts is None:
        seed_documents(store, submissions)
    else:
        assert len(texts) == len(tuple(submissions)), (
            "fixture bug: one text per submission is required when `texts` is given"
        )
        for submission_id, text in zip(submissions, texts):
            seed_document(store, submission_id, text)
    orchestrator.enumerate_units(run_id)
    assert orchestrator.start(run_id) == "running", (
        "fixture bug: the seeded run did not start"
    )
    return orchestrator, run_id, version


def drive_extract(orchestrator: Any, store: Any, provider: Any) -> None:
    """Lease and process every extract unit of the run through the real worker."""
    ref = extractor_ref()
    worker = ExtractionWorker(store, provider, ref)
    while True:
        batch = orchestrator.lease(_WORKER_NAME, STAGE_EXTRACT, 8)
        if not batch:
            break
        for unit in batch:
            request = assemble_request(unit, store=store)
            provider.record(
                extract_prompt_fields(request),
                ref,
                sampling_params(),
                span_completion(spans(), build_id=_EXTRACT_BUILD),
            )
            worker.process(unit)


def drive_score(
    orchestrator: Any,
    store: Any,
    provider: Any,
    *,
    verdict_band: str = "secure",
    self_confidence: float = 0.9,
    cited: bool = True,
    completion_for: Callable[[Any, Any], Any] | None = None,
) -> int:
    """Drive every base score unit through the real scoring workers.

    Each verdict's persist marks its unit done, so the edge-local residency gate
    never stalls across the loop's lease calls. `completion_for(unit, judge_ref)`
    overrides the recorded completion for one unit (the varying-band and
    refusal-path programs); the default is `verdict_band` with `cited` spans over
    the fixture transcript. Returns the number of units judged.
    """
    refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
    judged = 0
    for _ in range(32):
        batch = orchestrator.lease(_WORKER_NAME, STAGE_SCORE, 8)
        if not batch:
            break
        for unit in batch:
            judge_ref = refs_by_build[unit.judge]
            judge_worker = ScoringWorker(store, provider, judge_ref)
            request = judge_worker.assemble(unit)
            if completion_for is not None:
                completion = completion_for(unit, judge_ref)
            else:
                completion = verdict_completion(
                    verdict_band, self_confidence,
                    build_id=_JUDGE_BUILD,
                    cited_spans=spans() if cited else None,
                )
            provider.record(judge_prompt_fields(request), judge_ref, sampling_params(), completion)
            result = judge_worker.dispatch(request, judge_ref)
            assert result.band, "precondition: the judged reply was refused"
            judge_worker.persist(unit, result)
            judged += 1
    return judged


def drive_score_captured(
    orchestrator: Any,
    store: Any,
    boundary: Any,
    *,
    verdict_band: str = "secure",
    self_confidence: float = 0.9,
    cited: bool = True,
    completion_for: Callable[[Any, Any], Any] | None = None,
    record: bool = True,
) -> tuple[int, list[tuple[Any, Any, Any]]]:
    """Drive EVERY base score unit through the real workers, capturing each unit's
    assembled request at the real dispatch boundary.

    The panel cases (`TC-JUDGE-C08`'s per-judge prefix identity,
    `TC-JUDGE-C18`'s pre/post verdict differential) need the request each unit was
    ACTUALLY dispatched with, over the full panel — which the residency-batched
    lease reaches only by judging and persisting each resident judge's batch before
    leasing the next (the handout refuses empty while held work is unfinished). The
    capture happens as each request is assembled, so a captured payload is the
    pre-dispatch render and the caller can re-assemble its unit AFTER the whole
    drive for the byte-identity differential: if assembly consulted any verdict,
    the re-assembly (every verdict then existing) would drift from the capture.

    `boundary` is the model boundary the workers dispatch through — the recorded
    fixture provider with `record=True` (completions recorded against the captured
    render before the dispatch replays it), or a transport double with
    `record=False` (the double is called by `dispatch` itself). Returns
    `(judged, captured)` with `captured` as `(unit, judge_ref, request)` triples in
    drive order — judge-major under the residency batching.
    """
    refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
    captured: list[tuple[Any, Any, Any]] = []
    judged = 0
    for _ in range(64):
        batch = orchestrator.lease(_WORKER_NAME, STAGE_SCORE, 8)
        if not batch:
            break
        for unit in batch:
            judge_ref = refs_by_build[unit.judge]
            judge_worker = ScoringWorker(store, boundary, judge_ref)
            request = judge_worker.assemble(unit)
            captured.append((unit, judge_ref, request))
            if completion_for is not None:
                completion = completion_for(unit, judge_ref)
            else:
                completion = verdict_completion(
                    verdict_band, self_confidence,
                    build_id=_JUDGE_BUILD,
                    cited_spans=spans() if cited else None,
                )
            if record:
                boundary.record(
                    judge_prompt_fields(request), judge_ref, sampling_params(),
                    completion,
                )
            result = judge_worker.dispatch(request, judge_ref)
            assert result.band, "precondition: the judged reply was refused"
            judge_worker.persist(unit, result)
            judged += 1
    return judged, captured


def lease_score_units(orchestrator: Any) -> list[Any]:
    """Lease and return the base score units reachable in consecutive handouts.

    The edge-local claim walk is residency-batched (`FR-ORCH-19`): one judge model
    stays resident, so a handout never mixes models and a handout refuses empty while
    the resident's held work is unfinished. For the atomic criteria the default runs
    seed (base depth 1 — every unit one judge) that is one handout carrying the whole
    run's score units; a caller needing the FULL panel (a `holistic` criterion's
    three-judge depth) drives `drive_score_captured` instead, which judges and
    persists each resident batch before leasing the next judge's.
    """
    units: list[Any] = []
    for _ in range(32):
        batch = orchestrator.lease(_WORKER_NAME, STAGE_SCORE, 8)
        if not batch:
            break
        units.extend(batch)
    return units


def judge_units(
    store: Any,
    provider: Any,
    units: Sequence[Any],
    *,
    verdict_band: str = "secure",
    self_confidence: float = 0.9,
    cited: bool = True,
    completion_for: Callable[[Any, Any], Any] | None = None,
    record: bool = True,
) -> int:
    """Judge PRE-LEASED score units through the real workers and persist each verdict.

    `record=True` is the fixture provider's flow (the completion is recorded against
    the assembled render's key before the dispatch that replays it); `record=False`
    is the transport-double flow — the double IS called by `dispatch` and records
    itself, so a fixture recording would be a second, dead path. Returns the judged
    count.
    """
    refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
    judged = 0
    for unit in units:
        judge_ref = refs_by_build[unit.judge]
        judge_worker = ScoringWorker(store, provider, judge_ref)
        request = judge_worker.assemble(unit)
        if completion_for is not None:
            completion = completion_for(unit, judge_ref)
        else:
            completion = verdict_completion(
                verdict_band, self_confidence,
                build_id=_JUDGE_BUILD,
                cited_spans=spans() if cited else None,
            )
        if record:
            provider.record(
                judge_prompt_fields(request), judge_ref, sampling_params(), completion
            )
        result = judge_worker.dispatch(request, judge_ref)
        assert result.band, "precondition: the judged reply was refused"
        judge_worker.persist(unit, result)
        judged += 1
    return judged


def drive_judged_run(
    store: Any,
    provider: Any,
    *,
    submissions: Sequence[str] = ("SYN-001",),
    criterion_specs: Sequence[dict[str, Any]] | None = None,
    bands: Sequence[tuple[str, float, str]] = BANDS,
    verdict_band: str = "secure",
    self_confidence: float = 0.9,
    cited: bool = True,
    transport: Any = None,
    panel: Any = None,
    completion_for: Callable[[Any, Any], Any] | None = None,
    texts: Sequence[str] | None = None,
) -> tuple[Any, str, str]:
    """The whole drive: seeded run, real workers, a judged run out.

    The run is driven to every base unit judged; `progress()` completes it the
    dispatch loop's way (the deterministic walk and the pass-end flush are
    M-ORCH's own, so the completion path the cases read is the real one).
    `texts` passes through to `seed_world` (one document text per submission).
    """
    if criterion_specs is None:
        criterion_specs = [{
            "criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
            "band_count": len(tuple(bands)),
        }]
    orchestrator, run_id, version = seed_world(
        store, submissions=submissions, criterion_specs=criterion_specs,
        bands=bands, transport=transport, panel=panel, texts=texts,
    )
    drive_extract(orchestrator, store, provider)
    judged = drive_score(
        orchestrator, store, provider,
        verdict_band=verdict_band, self_confidence=self_confidence, cited=cited,
        completion_for=completion_for,
    )
    assert judged > 0, "fixture bug: the drive judged no units"
    report = orchestrator.progress(run_id)
    for _ in range(64):
        if report.complete:
            break
        report = orchestrator.progress(run_id)
    assert report.complete, (
        "the drive never exhausted the run — a case reading the verdict rows "
        "from a partial drive would read a panel the run never finished"
    )
    return orchestrator, run_id, version


def verdict_rows(
    store: Any, run_id: str, submission_id: str, criterion_id: str,
    columns: str = "v.*",
) -> list[dict[str, Any]]:
    """The pair's verdict rows, read back from the real ledger as mappings."""
    handle = store.cohort(ORCH_COHORT_ID)
    rows = handle.query(
        f"SELECT {columns} FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :r AND w.submission_id = :s AND w.criterion_id = :c "
        "ORDER BY v.work_id",
        r=run_id, s=submission_id, c=criterion_id,
    )
    return [dict(row) for row in rows]


def offline_request(
    *,
    work_id: str = "sha256:judge-contract-offline",
    criterion_id: str = "C1",
    criterion_text: str = "States the claim and supports it with the passage.",
    bands: Sequence[tuple[str, int, str]] = (
        ("emerging", 0, "the criterion is partly met"),
        ("secure", 1, "the criterion is met"),
    ),
    exemplars: Sequence[tuple[str, str, str]] = (),
    question_prompt: str = "Explain why the crate does not slide.",
    reference_solution: str = "Static friction balances the along-slope weight.",
    submission_id: str = "SYN-001",
    student_ref: str = "ref-syn-001",
    submission_text: str = PLAIN_TRANSCRIPT,
    evidence: Sequence[dict[str, Any]] = (),
    dependency_evidence: Sequence[Any] = (),
) -> ScoringRequest:
    """A hand-built whitelist request through the construction door (rung 0).

    The rubric, exemplar and question materials are parameters precisely so the
    contract cases can plant their two-sided fixtures (a score numeral in a band
    descriptor, a legitimate content numeral in an exemplar) and drive them
    through the REAL render — `prompt_fields` over this request — rather than
    through a re-implementation of it.
    """
    return ScoringRequest(
        work_id=work_id,
        criterion=CriterionView(
            criterion_id=criterion_id,
            text=criterion_text,
            bands=tuple(BandView(band, ordinal, descriptor)
                        for band, ordinal, descriptor in bands),
            exemplars=tuple(
                ExemplarView(exemplar_id=exemplar_id, band=band, text=text)
                for exemplar_id, band, text in exemplars
            ),
        ),
        question=QuestionView(
            prompt_text=question_prompt, reference_solution=reference_solution
        ),
        evidence=tuple(evidence),
        dependency_evidence=tuple(dependency_evidence),
        submission=SubmissionView(submission_id=submission_id, student_ref=student_ref),
        submission_text=submission_text,
    )


class RecordingTransport:
    """A provider double at the model boundary, and only there (`§4.2`).

    Every `complete(payload, judge, params)` call is recorded — payload, judge
    ref and the `SamplingParams` dispatch actually sent — and one completion is
    handed back per the case's program: a fixed completion, a sequence played in
    order, or a per-call function. The fixture provider cannot serve here
    because the property under test lives in the params and the call COUNT the
    boundary receives, which its key-based replay collapses.
    """

    def __init__(self, program: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._program = program
        self._index = 0

    def complete(self, payload: Any, judge: Any, params: Any) -> Completion:
        self.calls.append({"payload": payload, "judge": judge, "params": params})
        if callable(self._program):
            completion = self._program(len(self.calls), payload)
        elif isinstance(self._program, (list, tuple)):
            index = min(len(self.calls) - 1, len(self._program) - 1)
            completion = self._program[index]
        else:
            completion = self._program
        assert isinstance(completion, Completion), (
            f"fixture bug: the transport program yielded {completion!r}"
        )
        return completion

    def payloads(self) -> list[Any]:
        return [call["payload"] for call in self.calls]

    def params(self) -> list[Any]:
        return [call["params"] for call in self.calls]


__all__ = [
    "BANDS",
    "NEEDLE",
    "PANEL_REFS",
    "RecordingTransport",
    "add_bands",
    "drive_extract",
    "drive_judged_run",
    "drive_score",
    "drive_score_captured",
    "judge_prompt_fields",
    "judge_units",
    "lease_score_units",
    "offline_request",
    "seed_world",
    "spans",
    "verdict_rows",
]