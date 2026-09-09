"""Shared doubles and fixtures for the `M-EXTRACT` contract suite (issue #72).

The suite behind `TC-EXTRACT-C01..C15` (test plan §6.11.8). The doubles carry the same
shapes the TS-26 integration/security suites pin — `ExtractionWorker(store, provider,
model_ref).process(unit)`, `RecordedFixtureProvider` as the only model boundary, the
`span_completion` reply format — because the clause cases hold at the same seams; what is
different is what each case *asserts*: the §6.11.8 clause text at contract strength, and
the clause-suite discriminator (*would this go red if the clause broke while every
`FR-EXTRACT-*` case stayed green?*).

**Red by design — the opposite polarity from the `M-INGEST` contract suite.** The ingest
suite's audit found shipped code green with disclosed gaps. Here `aeh.extract` does not
exist (`src/aeh` has no extract module; #68 owns it), so every case resolves the module
through `require()` inside the test body and fails with `NotImplementedYet` naming the
owning story. The oracles below are written to be *executable at #68's landing* — each
names the mutant that would turn it red while the FR cases stay green.

**Disclosures register**

- **D1 (reply format)** — **reused from TS-26**, not re-invented: `span_completion`
  (`tests/support/extract_vocabulary.py`) is the disclosed stand-in for the extractor's
  reply; the worker is free to parse whatever it likes as long as the spans come out.
- **D2 (assembly kwargs)** — **reused from TS-26**: `dependency_evidence=[...]` and
  `question={"prompt_text": ..., "reference_solution": ...}` are the two keyword inputs
  the §3.8 request shape needs that a shipped `WorkUnit` carries no source for; the
  vocabulary file already discloses both.
- **D3 (document seeding)** — **reused from TS-26**: the production writer of the
  canonical document is `M-INGEST`; seeding writes the `document` row and blob bytes
  directly (exactly the shipped DDL), with the markdown wrapped in `M-INGEST`'s real
  untrusted-content delimiters.
- **D4 (counting provider)** — **introduced here**: `CountingProvider` delegates every
  call to a real `RecordedFixtureProvider` and counts `complete()` calls, which is the
  instrument `CT-EXTRACT-11`'s exact-call-count oracle needs. The fixture provider
  contract itself is never doubled away — the delegate answers every call.
- **D5 (metric names)** — **introduced in the vocabulary file** (`METRICS_ACCESSOR`,
  `EXTRACT_METRIC_NAMES`): `CT-EXTRACT-14` names four metrics but no channel and no
  spelling; the channel is the `aeh.ingest` `run_aggregates` precedent, the names are the
  plan's words in snake case, and `empty_result_rate` is keyed per criterion.
- **D6 (rung-3 consumer surfaces)** — the consumer halves resolve the surfaces the
  sibling suites already key on, under the owning stories' issue numbers:
  `ScoringWorker(store, provider, judge_ref)` + the store-reading `assemble(unit)` for
  `M-JUDGE` (#78 — the `JUDGE_MODULE:ScoringWorker` registry precedent),
  `verify_span(doc, span)` / `IntegrityGate(handle, blobs, extraction_view)` for `M-INTEG`
  (#73/#74 — `tests/support/integ_vocabulary.py`'s table), and
  `synthesize(run_id, submission_id=...)` for `M-SYNTH` (#97 — the `RES-07` disclosure).
  No new consumer symbol is invented here.
- **D7 (paired fixtures)** — `CT-EXTRACT-13`'s twin differential reads the **landed**
  `fixtures/F-ADV-INJ` corpus (`FR-CONFORM-09`'s paired fixtures, generator
  `harness.corpora.adv_inj:twin_pairs`): each pair is one submission carrying an injection
  payload and one benign twin identical but for the payload. No `M-CONFORM` surface is
  required.
- **D8 (declared schemas)** — `RESULT_FIELDS` / `REQUEST_FIELDS` / `SPAN_FIELDS` in the
  vocabulary file are HLD §9.9 verbatim (plus design §3.8's `region_kind` per span), so
  the set-equality oracles of `CT-EXTRACT-02`/`-04` assert against a constant rather than
  a re-derivation.

Nothing here imports `aeh.extract`; resolution happens inside the test bodies via
`tests.support.impl.require`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from aeh.conf import CohortRef, resolve_run_config
from aeh.conf import ModelRef
from aeh.ingest import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.extract_vocabulary import (
    EXTRACT_ISSUE,
    TS26_EXTRACT_SYMBOLS,
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package

#: A field name or annotation that could carry a verdict, band, points, score,
#: confidence or quality — the judgment vocabulary `CT-EXTRACT-02` and `CT-EXTRACT-04`
#: sweep for (HLD `R19`: the extractor must not certify or grade its own output).
JUDGMENT_WORD = re.compile(
    r"band|points|scores?|confidence|quality|verdict|grade|certainty|rating",
    re.IGNORECASE,
)


def require_extract_surface(issue: str | None = None) -> tuple[Any, ...]:
    """Resolve the full assumed `aeh.extract` surface, or fail stating the blocker.

    Every contract case calls this first, so the suite resolves exactly the symbol set
    the registry entry `"#68 extraction contract suite (TS-65)"` names (or its
    consumer-superset siblings) — the registry cannot name a symbol the tests stopped
    using, and a missing module is a stated failure, never a collection error.
    """
    return require(EXTRACT_MODULE, *TS26_EXTRACT_SYMBOLS, issue=issue or EXTRACT_ISSUE)


def build_markdown(body: str) -> str:
    """A canonical artifact: `body` inside `M-INGEST`'s real untrusted-content delimiters."""
    return UNTRUSTED_OPEN + "\n" + body + "\n" + UNTRUSTED_CLOSE


def byte_span(markdown: str, needle: str) -> dict[str, Any]:
    """A canned span over `needle`, located by BYTE offset — what the test records into
    the fixture. The module under test must keep the coordinate system intact."""
    md_bytes = markdown.encode("utf-8")
    start = md_bytes.find(needle.encode("utf-8"))
    assert start >= 0, f"fixture bug: {needle!r} not in the document"
    return {"start": start, "end": start + len(needle.encode("utf-8")), "text": needle}


def seed_document(store: Any, submission_id: str, markdown: str, doc_id: str) -> str:
    """Seed the canonical artifact: markdown bytes into the blob store, a `document` row
    pointing at the hash. Disclosed stand-in D3 — the production writer is `M-INGEST`."""
    content_hash = store.blobs().put(markdown.encode("utf-8"))
    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash) "
            "VALUES (:d, :s, :h)",
            d=doc_id,
            s=submission_id,
            h=content_hash,
        )
    return content_hash


@dataclass
class World:
    """The seeded rung-2 world one contract case runs over."""

    store: Any
    provider: Any
    version: str
    submission_id: str = "SYN-001"
    doc_id: str = "doc-ct-1"
    markdown: str = ""

    def close(self) -> None:
        self.store.close()


def make_world(
    tmp_data_dir: Any,
    make_fixture_provider: Any,
    *,
    markdown: str,
    criteria: list[dict[str, Any]],
    submission_id: str = "SYN-001",
    doc_id: str = "doc-ct-1",
    package_id: str = "pkg-ct-extract",
) -> World:
    """Cohort + package + canonical document, once; runs are created over them."""
    store = open_store(tmp_data_dir)
    seed_cohort(store, (submission_id,))
    version = seed_package(store, criteria, package_id=package_id)
    seed_document(store, submission_id, markdown, doc_id)
    return World(
        store=store,
        provider=make_fixture_provider(),
        version=version,
        submission_id=submission_id,
        doc_id=doc_id,
        markdown=markdown,
    )


def resolved_config(panel: Any) -> Any:
    """A resolved `RunConfig` over `ORCH_COHORT_ID`.

    `panel` is a tuple of `ModelRef`s — or an already-built `edge_cfg` dict, so a
    case can override a config knob (the pinned `prompt_template_v`,
    `TC-EXTRACT-C12`) and still resolve through the same door."""
    cfg = panel if isinstance(panel, dict) else edge_cfg(panel=panel)
    return resolve_run_config(
        cfg,
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


def extract_once(
    world: World,
    *,
    panel: tuple | None = None,
    spans: list[dict[str, Any]],
    build_id: str,
    assemble_kwargs: dict[str, Any] | None = None,
    provider: Any = None,
    model_ref: ModelRef | None = None,
):
    """Create a run over the world, lease its extract unit, record the reply for the
    exact request the worker will make, and drive the worker once.

    Returns `(request, result, run_id, unit)`. `assemble_kwargs` carries the disclosed
    D2 kwargs (`dependency_evidence=`, `question=`) where the case's criterion needs
    them; `provider`/`model_ref` default to the world's; `panel` defaults to the
    three-judge edge panel.
    """
    AssembleRequest, Worker = require(EXTRACT_MODULE, "assemble_request", WORKER, issue=EXTRACT_ISSUE)
    PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue=EXTRACT_ISSUE)

    if panel is None:
        panel = edge_panel(3)

    orchestrator = Orchestrator(world.store)
    run_id = orchestrator.create_run(ORCH_COHORT_ID, world.version, resolved_config(panel))
    (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)

    # The lease resolves identities and leaves `submission_text=None` (M-ORCH), so
    # the assembler resolves the words from the world's store — the disclosed
    # `store=` keyword (`extract_vocabulary.py`) — unless the case passed its own
    # kwargs (the D2 `dependency_evidence=`/`question=`).
    kwargs: dict[str, Any] = {"store": world.store}
    kwargs.update(assemble_kwargs or {})
    request = AssembleRequest(unit, **kwargs)
    model_ref = model_ref or extractor_ref()
    (provider or world.provider).record(
        PromptFields(request), model_ref, sampling_params(),
        span_completion(spans, build_id=build_id),
    )
    result = Worker(world.store, provider or world.provider, model_ref).process(unit)
    return request, result, run_id, unit


def evidence_rows(
    store: Any, run_id: str, submission_id: str = "SYN-001", criterion_id: str = "C1"
) -> list[Any]:
    """The evidence row(s) for the run's (submission, criterion) extract unit, with the
    unit's judge column and the row's payload and build identity."""
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT e.evidence_id, e.work_id, e.payload, e.resolved_build, e.document_id, "
        "w.judge_id, w.status AS unit_status "
        "FROM evidence e JOIN work_unit w ON w.work_id = e.work_id "
        "WHERE w.run_id = :r AND w.submission_id = :s AND w.criterion_id = :c "
        "AND w.stage = :st",
        r=run_id,
        s=submission_id,
        c=criterion_id,
        st=STAGE_EXTRACT,
    )


def payload_bytes(value: Any) -> bytes:
    """Normalize an evidence payload to bytes; NULL is the failure mode, not a value."""
    if value is None:
        raise AssertionError("TC-EXTRACT: evidence payload is NULL — the row was written empty")
    if isinstance(value, bytes):
        return value
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    try:
        return json.dumps(value, sort_keys=True).encode("utf-8")
    except TypeError:
        # A rich assembled object (e.g. a dataclass request) renders through str(); the
        # oracles read containment and identity, not JSON syntax, so either form works.
        return str(value).encode("utf-8")


def judgment_fields(names: list[str]) -> list[str]:
    """The names in `names` that match the judgment vocabulary — expected empty."""
    return [n for n in names if JUDGMENT_WORD.search(n)]


@dataclass
class CountingProvider:
    """Delegating call counter over a real `RecordedFixtureProvider` (disclosure D4).

    Every `complete()` is forwarded unchanged and counted; `calls` records the
    `(model_ref, prompt)` pairs — the ref itself, not a projection of it, so
    `CT-EXTRACT-11` can assert the exact count and `CT-EXTRACT-06` that the two
    dispatched prompts came from refs differing in provider (two refs sharing a
    `build_id` differ only in the ref).
    """

    _inner: Any
    calls: list[tuple[Any, Any]] = field(default_factory=list)

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls.append((model_ref, prompt))
        return self._inner.complete(prompt, model_ref, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def count(self) -> int:
        return len(self.calls)
