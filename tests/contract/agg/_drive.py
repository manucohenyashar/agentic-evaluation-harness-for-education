"""The compact rung-3 drive the `M-AGG` contract cases share (TS-69, issue #96).

The run-shaped world is `tests/support/orch_run.py`'s (built by #63); this file adds
the drive shape `tests/contract/orch/test_ct_orch_c17_sole_writership.py` proved —
seed, enumerate, start, the real extraction worker over the recorded fixture
provider, the real scoring workers over the panel — compressed to the one
submission × one open criterion shape the aggregation cases need, plus the two
readback helpers the completion-path cases stand on:

- `drive_scored_run` — a real run driven to a judged panel, `(orchestrator, run_id,
  version)` out. Every worker is real; the only stand-in is the recorded fixture
  provider's completions (§4.2: it IS the deterministic transport, not a fake).
- `stored_verdicts` — the pair's verdict rows read back from the ledger, as the
  verdict-shaped values `aggregate` consumes. `cited` defaults to True: the fixture's
  completions all cite the seeded span, and no shipped column records an uncited mark
  (the uncited mark rides M-INTEG's signals, not the verdict row) — disclosed here
  once, at the read.

Isolation: rung 3 — real store, real package, real workers; the drives write no
`criterion_score` row themselves, so the aggregation the cases time or audit is fed
from the ledger exactly as a consumer on the completion path would read it.
"""

from __future__ import annotations

from typing import Any, Sequence
from types import SimpleNamespace

from aeh.extract import ExtractionWorker
from aeh.extract import assemble_request, prompt_fields
from aeh.judge import ScoringWorker
from aeh.judge import prompt_fields as judge_prompt_fields
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
    seed_run,
)

#: The three-judge edge panel, as the orchestrator's own fixture resolves it.
PANEL_REFS = (EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3)

_WORKER_NAME = "w-agg-contract"

_NEEDLE = "The evidence supports the conclusion"

_EXTRACT_BUILD = "build-agg-contract-extract"


class Seam:
    """The transport the dispatch pass binds: every model call recorded, one
    completion back — the shipped orch contract cases' seam shape."""

    def __init__(self, build_id: str = "build-agg-contract-seam") -> None:
        self.calls = 0
        self._build_id = build_id

    def call(self, request: object) -> Completion:
        self.calls += 1
        return Completion(
            text="synthetic band: B",
            tokens_in=3,
            tokens_out=2,
            latency_ms=1,
            resolved_build=self._build_id,
            cached_prefix_tokens=0,
            cost=None,
        )


def spans(text: str = PLAIN_TRANSCRIPT) -> list[dict[str, object]]:
    """A span completion's spans over the fixture transcript — or over any text a
    case passes, which is how the hallucinated-span construction is built."""
    start = text.find(_NEEDLE)
    assert start >= 0, "fixture bug: the span needle is not in the transcript"
    return [{"start": start, "end": start + len(_NEEDLE), "text": _NEEDLE}]


def add_bands(store: Any, version: str, criterion_id: str,
              bands: Sequence[tuple[str, float]]) -> None:
    """The criterion's REAL band set, through the shipped catalog API — points
    non-decreasing in ordinal (CT-PKG-04)."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    for ordinal, (name, points) in enumerate(bands):
        catalog.add_band(version, criterion_id, ordinal, name, points, "the band")


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
                prompt_fields(request),
                ref,
                sampling_params(),
                span_completion(spans(), build_id=_EXTRACT_BUILD),
            )
            worker.process(unit)


def drive_score(orchestrator: Any, store: Any, provider: Any, *,
                band: str = "B", self_confidence: float = 0.9) -> None:
    """Drive every base score unit through the real scoring workers.

    Each verdict's persist marks its unit done, so the edge-local residency gate
    never stalls across the loop's lease calls."""
    refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
    for _ in range(32):
        batch = orchestrator.lease(_WORKER_NAME, STAGE_SCORE, 8)
        if not batch:
            break
        for unit in batch:
            judge_ref = refs_by_build[unit.judge]
            judge_worker = ScoringWorker(store, provider, judge_ref)
            request = judge_worker.assemble(unit)
            provider.record(
                judge_prompt_fields(request),
                judge_ref,
                sampling_params(),
                verdict_completion(band, self_confidence, build_id="build-agg-contract"),
            )
            result = judge_worker.dispatch(request, judge_ref)
            assert result.band == band, (
                "precondition: the judge's reply was not the verdict the fixture "
                "recorded"
            )
            judge_worker.persist(unit, result)


def drive_scored_run(
    store: Any,
    provider: Any,
    *,
    submissions: Sequence[str] = ("SYN-001",),
    criterion_specs: Sequence[dict[str, Any]] | None = None,
    bands: Sequence[tuple[str, float]] = (("A", 2.0), ("B", 4.0)),
    verdict_band: str = "B",
    transport: Any = None,
    escalation_budget: str | None = None,
    monkeypatch: Any = None,
) -> tuple[Any, str, str]:
    """The whole drive: seeded run, real workers, a judged run out.

    `criterion_specs` defaults to one open atomic criterion `C1` carrying
    `bands`' set; `verdict_band` is the band every recorded judge reply gives.
    The run is driven to every base unit judged; `progress()` completes it the
    dispatch loop's way (the deterministic walk and the pass-end flush are
    M-ORCH's own, so the completion path the cases read is the real one).
    """
    if criterion_specs is None:
        criterion_specs = [{
            "criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
            "band_count": len(tuple(bands)),
        }]
    if escalation_budget is not None and monkeypatch is not None:
        monkeypatch.setenv("HARNESS_ORCH_ESCALATION_BUDGET", escalation_budget)
    seam = transport if transport is not None else Seam()
    orchestrator, run_id, version = seed_run(
        store, submissions=submissions, criteria=criterion_specs, transport=seam,
    )
    for criterion_spec in criterion_specs:
        add_bands(store, version, criterion_spec["criterion_id"], bands)
    for submission_id in submissions:
        seed_document(store, submission_id)

    orchestrator.enumerate_units(run_id)
    assert orchestrator.start(run_id) == "running"

    drive_extract(orchestrator, store, provider)
    drive_score(orchestrator, store, provider, band=verdict_band)
    report = orchestrator.progress(run_id)
    for _ in range(64):
        if report.complete:
            break
        report = orchestrator.progress(run_id)
    assert report.complete, (
        "the drive never exhausted the run — a case reading the completion path "
        "from a partial drive would aggregate a panel the run never finished"
    )
    return orchestrator, run_id, version


def stored_verdicts(store: Any, run_id: str, submission_id: str,
                    criterion_id: str) -> list[SimpleNamespace]:
    """The pair's verdict rows, read back from the real ledger as the
    verdict-shaped values `aggregate` consumes (`band`, `ordinal`,
    `self_confidence`; `cited` True — the fixture's completions all cite, and
    no shipped column records an uncited mark, disclosed in the module
    docstring)."""
    handle = store.cohort(ORCH_COHORT_ID)
    rows = handle.query(
        "SELECT v.band, v.band_ordinal, v.self_confidence "
        "FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :r AND w.submission_id = :s AND w.criterion_id = :c "
        "ORDER BY v.work_id",
        r=run_id, s=submission_id, c=criterion_id,
    )
    return [
        SimpleNamespace(
            band=row["band"], ordinal=row["band_ordinal"],
            self_confidence=row["self_confidence"], cited=True,
        )
        for row in rows
    ]


def criterion_bands(store: Any, criterion_id: str) -> tuple:
    """The criterion's declared band set, read through the shipped catalog API —
    the static half of what a completion-path consumer aggregates against."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    return catalog.bands(criterion_id)
