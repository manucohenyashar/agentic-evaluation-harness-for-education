"""The TS-31 integration suite's rung-2 world: a judged run through the REAL boundary.

The TS-26/TS-27 suites (``test_judge_band_forcing.py`` and its siblings) each carry a
private copy of the same world builder — seeded documents, a banded package, an
extraction leg, then score units dispatched against ``RecordedFixtureProvider``. The
TS-31 cases (#83) need that world SIX times, with different replies per (submission,
judge) and different knobs, so the shared copy lives here: ONE place to reconcile the
fixture shape, the disclosure written once, and a rename is one edit.

What the world is, mechanically — all through shipped implementations:

- a real store (``open_store`` on the case's tmp dir), with migrations warmed by the
  caller (import both owning modules BEFORE ``open_store`` — the TS-27 ordering rule);
- a REAL Tier P package version with its declared band set written through
  ``PackageCatalog.add_band`` (``FR-PKG-06``), plus optional exemplars via
  ``add_exemplar`` with real blob hashes (``FR-JUDGE-08``'s rubric channel);
- a REAL cohort ledger (``seed_cohort``/``seed_document`` — the disclosed M-INGEST
  bypass the TS-26/TS-27 suites share: bytes into the blob store, one ``document`` row
  naming the content hash);
- a REAL run (``seed_run``-shaped) over the declared package and a resolved
  edge-local config, with the panel the case asks for;
- the REAL extraction leg: extract units leased, one recorded ``span_completion`` per
  submission (spans over the document's own byte offsets), ``ExtractWorker.process``
  — so the Sweep-2 gate releases score units the way a real run does;
- the REAL judge leg: score units leased (one per submission, criterion and panel
  member), each assembled through ``ScoringWorker.assemble``, its reply recorded under
  the unit's own judge ref, ``dispatch`` + ``persist`` per unit, and the orchestrator
  told ``complete`` per accepted unit (failed units are left for the caller —
  ``TC-JUDGE-18``'s fail cycles drive them).

The replies are the controlled condition: ``reply_for(submission_id, judge_build_id)``
returns the ``Completion`` that judge answers that submission with, and the world
records it under the exact ``(payload, judge ref, params)`` key dispatch would
otherwise miss on. The model boundary stays ``RecordedFixtureProvider`` — the only
egress (``CT-PROV-15``) — and nothing here reaches the network.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Sequence

from aeh.ingest import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, STAGE_SCORE, Orchestrator
from aeh.pkg import PackageCatalog
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.extract_vocabulary import (
    ASSEMBLE,
    EXTRACT_ISSUE,
    JUDGE_ISSUE,
    PROMPT_FIELDS,
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
    verdict_completion,
)
from tests.support.impl import EXTRACT_MODULE, JUDGE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_document, seed_package

#: The declared set every world carries — two bands, distinct ordinals and
#: descriptors, through the real M-PKG API (`FR-PKG-06`). The top band is the control.
JUDGE_RUN_BANDS = (
    ("emerging", 0.0, "the criterion is partly met"),
    ("secure", 10.0, "the criterion is met"),
)
DECLARED_NAMES = [band for band, _points, _descriptor in JUDGE_RUN_BANDS]
CONTROL_BAND = "secure"
CONTROL_CONFIDENCE = 0.62

#: The criterion every world judges by default — one open holistic criterion, its
#: `band_count` matching the declared set.
DEFAULT_CRITERIA: tuple[dict[str, Any], ...] = (
    {
        "criterion_id": "C1",
        "kind": "open",
        "scoring_model": "holistic",
        "band_count": len(JUDGE_RUN_BANDS),
    },
)


def canonical_document(text: str) -> str:
    """One page fenced in `M-INGEST`'s real delimiters — the canonical artifact the
    extraction spans and the citation gate both resolve against."""
    return UNTRUSTED_OPEN + "\n" + text + "\n" + UNTRUSTED_CLOSE


def byte_span(text: str, needle: str) -> dict[str, Any]:
    """A span dict over `needle`'s exact bytes in `text` — coordinates the citation
    gate verifies True (`aeh.integ.verify_span`'s own shape)."""
    raw = text.encode("utf-8")
    start = raw.find(needle.encode("utf-8"))
    assert start >= 0, f"fixture bug: {needle!r} not in the document"
    return {"start": start, "end": start + len(needle.encode("utf-8")), "text": needle}


def default_pages(submission_id: str) -> tuple[str, str]:
    """The two lines every default submission's document carries — also the needles
    the default spans are cut over."""
    return (
        f"Submission {submission_id} opens the argument with its cited evidence.",
        f"Submission {submission_id} closes with the caveats the panel reads.",
    )


def warm_judged_modules() -> dict[str, Any]:
    """Resolve both owning modules' surfaces through `require`. Called BEFORE
    `open_store` this warms the migration chains (the TS-27 ordering rule)."""
    ExtractAssemble, ExtractWorker = require(
        EXTRACT_MODULE, ASSEMBLE, WORKER, issue=EXTRACT_ISSUE
    )
    ExtractPromptFields = require(EXTRACT_MODULE, PROMPT_FIELDS, issue=EXTRACT_ISSUE)
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue=JUDGE_ISSUE)
    JudgePromptFields = require(JUDGE_MODULE, PROMPT_FIELDS, issue=JUDGE_ISSUE)
    return {
        "extract": (ExtractAssemble, ExtractWorker),
        "extract_prompt_fields": ExtractPromptFields,
        "judge": ScoringWorker,
        "judge_prompt_fields": JudgePromptFields,
    }


def seed_judged_package(
    store: Any,
    *,
    criteria: Sequence[dict[str, Any]] = DEFAULT_CRITERIA,
    bands: tuple[tuple[str, float, str], ...] = JUDGE_RUN_BANDS,
    package_id: str = "pkg-orch",
    exemplars: Sequence[tuple[str, str]] = (),
) -> str:
    """A judged package version: the criteria specs seeded, every criterion's band set
    declared, and — when given — exemplars written as real blobs and anchored per
    criterion (`FR-JUDGE-08`'s rubric channel, through the shipped `add_exemplar`).

    Returns the version id.
    """
    version = seed_package(store, tuple(criteria), package_id=package_id)
    catalog = PackageCatalog(
        store.package(package_id), package_id=package_id, blobs=store.blobs()
    )
    for spec in criteria:
        for ordinal, (band, points, descriptor) in enumerate(bands):
            catalog.add_band(
                version, spec["criterion_id"], ordinal, band, points, descriptor
            )
    for index, (criterion_id, band) in enumerate(exemplars):
        exemplar_id = f"ex-{index:02d}"
        blob_hash = store.blobs().put(
            f"Exemplar {exemplar_id} for {criterion_id}: worked material showing "
            f"what band {band!r} looks like, with the cited spans marked."
            .encode("utf-8")
        )
        catalog.add_exemplar(
            version, exemplar_id, criterion_id, band, blob_hash=blob_hash
        )
    return version


def judge_world(
    store: Any,
    provider: Any,
    *,
    submissions: Sequence[str],
    panel: int = 1,
    reply_for: Callable[[str, str], Any] | None = None,
    criteria: Sequence[dict[str, Any]] = DEFAULT_CRITERIA,
    bands: tuple[tuple[str, float, str], ...] = JUDGE_RUN_BANDS,
    package_id: str = "pkg-orch",
    exemplars: Sequence[tuple[str, str]] = (),
    extract_worker_id: str = "w-extract-tj31",
    judge_worker_id: str = "w-judge-tj31",
    judge_leg: bool = True,
) -> dict[str, Any]:
    """One judged run through the full boundary — the shared TS-31 world.

    Seeds everything (package with declared bands, cohort, documents, run), runs the
    REAL extraction leg, and — unless ``judge_leg=False`` — leases every score unit
    the panel enumerates and drives ``assemble`` → ``dispatch`` → ``persist`` per
    unit, recording each judge's reply under its exact request key first. Every
    exception is RECORDED, not swallowed — a refusal is a pass form here, and the
    caller's assertions decide what the recorded refusals mean.
    ``orchestrator.complete(work_id)`` is called for every unit whose dispatch
    succeeded; failed units are left for the caller's fail cycles.

    The default reply (``reply_for=None``) is the control reply: the control band at
    the control confidence, citing the extracted spans. The world also records, per
    ``(submission_id, judge build)``, the scripted completion's ``latency_ms`` and
    ``cached_prefix_tokens`` — the provider-reported figures the per-(criterion,
    judge) signal census reads (`TC-JUDGE-24`).

    Returns a dict of everything the row and census assertions read:
    ``orchestrator``, ``run_id``, ``version``, ``judges`` (the panel's refs by build
    id), ``score_units``/``requests``/``results``/``failures``/``replies`` keyed
    ``(submission_id, judge build)``, ``strikes`` (provider calls per unit's
    dispatch), ``documents`` and ``spans``.
    """
    warm = warm_judged_modules()
    ExtractAssemble, ExtractWorker = warm["extract"]
    ExtractPromptFields = warm["extract_prompt_fields"]
    ScoringWorker, JudgePromptFields = warm["judge"], warm["judge_prompt_fields"]

    version = seed_judged_package(
        store, criteria=criteria, bands=bands, package_id=package_id, exemplars=exemplars
    )
    cohort_id = seed_cohort(store, list(submissions))
    documents: dict[str, str] = {}
    spans: dict[str, list[dict[str, Any]]] = {}
    for submission_id in submissions:
        pages = default_pages(submission_id)
        markdown = canonical_document("\n".join(pages))
        documents[submission_id] = markdown
        seed_document(store, submission_id, markdown)
        spans[submission_id] = [byte_span(markdown, needle) for needle in pages]

    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(ORCH_COHORT_ID, version, resolved(panel))

    model_ref = extractor_ref()
    extract_units = list(
        orchestrator.lease(extract_worker_id, STAGE_EXTRACT, len(submissions))
    )
    assert len(extract_units) == len(submissions), (
        f"precondition: leased {len(extract_units)} extract units for "
        f"{len(submissions)} submissions"
    )
    for unit in extract_units:
        request = ExtractAssemble(unit, store=store)
        provider.record(
            ExtractPromptFields(request),
            extractor_ref(),
            sampling_params(),
            span_completion(spans[unit.submission_id], build_id="extractor-build-tj31"),
        )
        ExtractWorker(store, provider, extractor_ref()).process(unit)

    world = {
        "orchestrator": orchestrator,
        "run_id": run_id,
        "version": version,
        "cohort_id": cohort_id,
        "documents": documents,
        "spans": spans,
        "judges": {},
        "score_units": {},
        "requests": {},
        "results": {},
        "failures": {},
        "replies": {},
        "strikes": {},
    }
    if not judge_leg:
        return world

    # The judge leg: one unit per (submission, criterion, panel member). The reply is
    # the controlled condition — recorded under the unit's exact request key — and a
    # counting wrapper credits every provider call the dispatches make, per judge,
    # because a strike count is the census's contract-violation signal's numerator.
    judges = {ref.build_id: ref for ref in edge_panel(panel)}
    world["judges"] = judges
    counting = _CountingProvider(provider)
    while True:
        batch = list(orchestrator.lease(judge_worker_id, STAGE_SCORE, 64))
        if not batch:
            break
        for unit in batch:
            key = (unit.submission_id, unit.judge)
            world["score_units"][key] = unit
            ref = judges.get(unit.judge)
            assert ref is not None, (
                f"fixture bug: unit {unit.work_id} names judge {unit.judge!r}, which "
                f"the configured panel does not carry"
            )
            request = ScoringWorker(store, provider, ref).assemble(unit)
            world["requests"][key] = request
            completion = (
                reply_for(*key) if reply_for else _control_reply(spans[unit.submission_id])
            )
            assert completion is not None, (
                f"fixture bug: no reply scripted for {key} — the fixture key would "
                f"miss and the dispatch would refuse on a missing recording"
            )
            world["replies"][key] = completion
            provider.record(JudgePromptFields(request), ref, sampling_params(), completion)
            worker = ScoringWorker(store, counting, ref)
            before = len(counting.calls)
            try:
                result = worker.dispatch(request, ref)
                worker.persist(unit, result)
                world["results"][key] = result
                orchestrator.complete(unit.work_id)
            except Exception as exc:  # a refusal IS a pass form — recorded
                world["failures"][key] = exc
            world["strikes"][key] = len(counting.calls) - before
    return world


class _CountingProvider:
    """A transport-seam wrapper that credits every `complete` call to the judge it was
    addressed by — the per-(criterion, judge) strike counts the census reads. The
    fixture recording and lookup still go through the inner provider."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def complete(self, payload, model_ref, params):
        build_id = getattr(model_ref, "build_id", None)
        self.calls.append(build_id if isinstance(build_id, str) else str(model_ref))
        return self._inner.complete(payload, model_ref, params)


def _control_reply(spans: list[dict[str, Any]]):
    """The default legal reply: the control band at the control confidence, citing
    the extracted spans."""
    return verdict_completion(
        CONTROL_BAND, CONTROL_CONFIDENCE, build_id="judge-build-tj31", cited_spans=spans
    )


def resolved(panel: int = 1):
    """The resolved run config over `edge_panel(panel)` — `orch_cfg`'s reading."""
    from aeh.conf import CohortRef, resolve_run_config

    return resolve_run_config(
        edge_cfg(panel=edge_panel(panel)),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


# --- the reads the row and census assertions use ------------------------------------------------


def verdict_rows(store: Any, work_id: str, cohort_id: str = ORCH_COHORT_ID) -> list[Any]:
    """The verdict rows for one work unit, with the response columns included."""
    return store.cohort(cohort_id).query(
        "SELECT verdict_id, work_id, judge_id, band, band_ordinal, self_confidence, "
        "cited_spans, evidence_sufficient, uncited FROM verdict WHERE work_id = :w",
        w=work_id,
    )


def verdict_columns(store: Any, cohort_id: str = ORCH_COHORT_ID) -> list[str]:
    """The verdict table's LIVE column names, read off the store that answered."""
    rows = store.cohort(cohort_id).query("PRAGMA table_info(verdict)")
    return [row["name"] for row in rows]


def work_unit_row(store: Any, work_id: str) -> Any:
    """One work unit's ledger row (status, attempts, last_error)."""
    from aeh.judge import JUDGE_STATEMENTS  # noqa: PLC0415 — the select names the shape

    return store.cohort(ORCH_COHORT_ID).query(
        JUDGE_STATEMENTS["select_work_unit"], work_id=work_id
    )[0]


def reply_text(
    band: str,
    confidence: float,
    *,
    build_id: str,
    cited_spans: list[dict[str, Any]] | None = None,
    assessment: str = "the cited spans support the band",
    evidence_sufficient: bool = True,
    latency_ms: int = 0,
    cached_prefix_tokens: int = 0,
) -> Any:
    """A judge reply `Completion` in the pinned five-field order — the
    `verdict_completion` stand-in, re-declared here so the TS-31 files build replies
    from one place. `latency_ms` and `cached_prefix_tokens` carry the provider-reported
    figures the per-(criterion, judge) census reads (`TC-JUDGE-24`)."""
    from aeh.prov import Completion

    reply = {
        "cited_spans": list(cited_spans or []),
        "evidence_assessment": assessment,
        "evidence_sufficient": evidence_sufficient,
        "band": band,
        "self_confidence": confidence,
    }
    return Completion(
        text=json.dumps(reply),  # insertion order IS the contract (FR-JUDGE-09)
        tokens_in=0,
        tokens_out=0,
        latency_ms=latency_ms,
        resolved_build=build_id,
        cached_prefix_tokens=cached_prefix_tokens,
        cost=None,
    )


def malformed_reply(text: str, *, build_id: str, latency_ms: int = 0) -> Any:
    """A `Completion` carrying the given text verbatim — the wire form of a reply
    that breaks the contract in a way `verdict_completion` cannot spell."""
    from aeh.prov import Completion

    return Completion(
        text=text,
        tokens_in=0,
        tokens_out=0,
        latency_ms=latency_ms,
        resolved_build=build_id,
        cached_prefix_tokens=0,
        cost=None,
    )


def permuted_reply(
    band: str,
    confidence: float,
    *,
    build_id: str,
    order: tuple[str, ...] = (
        "band",
        "self_confidence",
        "cited_spans",
        "evidence_assessment",
        "evidence_sufficient",
    ),
    latency_ms: int = 0,
    cached_prefix_tokens: int = 0,
) -> Any:
    """A `Completion` whose reply carries the five fields in `order`'s sequence — a
    permuted reply, the contract violation the response contract refuses."""
    from aeh.prov import Completion

    reply = {
        "cited_spans": [],
        "evidence_assessment": "the cited spans support the band",
        "evidence_sufficient": True,
        "band": band,
        "self_confidence": confidence,
    }
    return Completion(
        text=json.dumps({name: reply[name] for name in order}),
        tokens_in=0,
        tokens_out=0,
        latency_ms=latency_ms,
        resolved_build=build_id,
        cached_prefix_tokens=cached_prefix_tokens,
        cost=None,
    )