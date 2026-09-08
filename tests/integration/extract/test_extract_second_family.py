"""`TC-EXTRACT-07` — a criterion on the injected high-risk list runs extraction a
SECOND time with a different model family, and both span sets are persisted for
`M-INTEG` to compare.
Test plan §5.8; `FR-EXTRACT-07`, `CT-EXTRACT-10`. P1, **Phase 2** — the mechanism is
issue #69's; the suite keys this file on `#69`, not `#68`.

Oracles — **exact value**:
- the flagged criterion sees TWO extraction calls — the small extractor and the
  second-family model, whose model references differ (different build; `ModelRef`
  carries no `family` field, so family is carried by the build/provider pair —
  disclosed);
- BOTH span sets reach the persisted evidence payload, distinguishable, each complete
  with its spans — persisted `for comparison`, not merged;
- the payload carries NO reconciliation: no winner, no selection, no agreement score —
  "this module never picks a winner" (`CT-EXTRACT-10`), so `M-INTEG` owns the compare;
- the differential: an UNFLAGGED criterion in the same run sees exactly ONE call and a
  single span set — the second family multiplies flagged work only.

**Written ahead of #69** (`FR-EXTRACT-07`'s Phase 2). Registered in
`WRITTEN_AHEAD_BLOCKERS` under `"#69 second family (TS-26)"` (symbols conjunction —
`ExtractionWorker` and `second_family_model`; until BOTH resolve, the case is red).

**Interface this case assumes of #68/#69**, listed so it is reconciled deliberately:

| Name | Status |
|---|---|
| `ExtractionWorker(store, provider, model_ref)` | **assumed here** (#68's driver, as everywhere in the suite) |
| `second_family_model` | **invented in `extract_vocabulary`** — the different-family `ModelRef` #69 runs flagged criteria with |
| `ExtractionWorker(..., second_family_model=..., high_risk_criteria=...)` | **assumed here** — the injected high-risk list (Q-12 applies to the LIST, not the mechanism: the list's contents are operator policy, so the case injects its own) and the second ref, as constructor seams |
| the persisted payload carries both span sets | **assumed here** — `evidence` is keyed `(run, submission, criterion)` with no judge dimension (`CT-EXTRACT-03`), so a second row per family would need a new key dimension; one payload carrying both sets is the disclosed bet |

**Disclosed stand-ins.** The provider is a two-model counting stub (one reply per
model reference) — the RecordedFixtureProvider contract is exercised in the suite's
other cases, and here the interesting fact is which model was asked, per call, which
the stub reads off directly. The replies are `span_completion`'s disclosed stand-in;
the second set's distinct spans are the fixture, since a merge in the worker would be
invisible if both replies were identical.

**Isolation: rung 2** — real store, real ledger, real blob directory; the model
boundary is the counting stub.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.ingest import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.extract_vocabulary import (
    RESULT_TYPE,
    SECOND_FAMILY_ISSUE,
    SECOND_FAMILY_MODEL,
    WORKER,
    extractor_ref,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, require

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = SECOND_FAMILY_ISSUE

#: The high-risk list is INJECTED (Q-12 applies to the list, not the mechanism): this
#: case injects its own — C1 flagged, C2 not, in the same run.
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
)

_MARKDOWN = (
    UNTRUSTED_OPEN
    + "\n"
    + "The crate accelerates at 2 m/s^2.\n"
    + UNTRUSTED_CLOSE
)

_PRIMARY_SPANS = [{"start": 0, "end": 10, "text": "The crate"}]
_SECOND_SPANS = [{"start": 31, "end": 35, "text": "2 m/s"}]


class _TwoModelProvider:
    """One reply per model reference; counts calls and remembers which model each was
    addressed to — the facts the oracle reads."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (build_id, reply text)

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        spans = (
            _PRIMARY_SPANS if model_ref.build_id.endswith("primary")
            else _SECOND_SPANS
        )
        self.calls.append((model_ref.build_id, json.dumps({"spans": spans})))
        return span_completion(spans, build_id=model_ref.build_id)


def _resolved() -> Any:
    return resolve_run_config(
        edge_cfg(panel=edge_panel(3)),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


def _payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, memoryview):
        payload = bytes(payload)
    if isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload).decode("utf-8")
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert isinstance(payload, dict), f"unparsable evidence payload: {payload!r}"
    return payload


def _process(store: Any, provider: Any, unit: Any, worker: Any, refs: dict[str, Any],
             high_risk: tuple[str, ...]) -> None:
    kwargs = dict(second_family_model=refs["second"],
                  high_risk_criteria=high_risk)
    worker(store, provider, refs["primary"], **kwargs).process(unit)


def test_tc_extract_07_both_span_sets_persisted_no_winner(tmp_data_dir):
    """`TC-EXTRACT-07` — the flagged criterion: two calls to two different model
    references, both span sets in the evidence payload, and no reconciliation key."""
    require(EXTRACT_MODULE, WORKER, SECOND_FAMILY_MODEL, RESULT_TYPE, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("SYN-001",))
        version = seed_package(store, (_CRITERIA[0],))  # flagged criterion only
        content_hash = store.blobs().put(_MARKDOWN.encode("utf-8"))
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute(
                "INSERT INTO document (document_id, submission_id, content_hash) "
                "VALUES (:d, :s, :h)",
                d="doc-syn001-1", s="SYN-001", h=content_hash,
            )
        orchestrator = Orchestrator(store)
        run_id = orchestrator.create_run(ORCH_COHORT_ID, version, _resolved())
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)

        provider = _TwoModelProvider()
        refs = {
            "primary": extractor_ref(build_id="/models/qwen3-30b.gguf@primary"),
            "second": require(EXTRACT_MODULE, SECOND_FAMILY_MODEL, issue=ISSUE),
        }
        _process(store, provider, unit, require(EXTRACT_MODULE, WORKER, issue=ISSUE),
                 refs, high_risk=("C1",))

        # Two calls, two DIFFERENT model references — a second extraction with a
        # different family actually happened.
        assert len(provider.calls) == 2, (
            f"a flagged criterion must extract twice, saw {len(provider.calls)} calls"
        )
        assert provider.calls[0][0] != provider.calls[1][0], (
            f"both calls hit the same model reference: "
            f"{[c[0] for c in provider.calls]}"
        )

        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT payload FROM evidence WHERE work_id = :w", w=unit.work_id
        )
        assert len(rows) == 1, "flagged criterion: exactly one evidence row"
        payload = _payload(rows[0]["payload"])
        serialized = json.dumps(payload, sort_keys=True)
        # BOTH sets persisted, distinguishable, for M-INTEG to compare.
        for span_text, label in (
            (_PRIMARY_SPANS[0]["text"], "primary"),
            (_SECOND_SPANS[0]["text"], "second family"),
        ):
            assert span_text in serialized, (
                f"the {label} span set did not reach the persisted evidence payload"
            )
        # Never picks a winner: no reconciliation key anywhere in the payload.
        banned = ("winner", "selected", "chosen", "agreement", "final_spans")
        offenders = [key for key in payload if any(b in key.lower() for b in banned)]
        assert not offenders, (
            f"the extract module reconciled: {offenders} — CT-EXTRACT-10 leaves the "
            f"compare to M-INTEG"
        )
    finally:
        store.close()


def test_tc_extract_07_unflagged_criterion_extracts_once(tmp_data_dir):
    """`TC-EXTRACT-07` differential — an unflagged criterion in the same run sees
    exactly ONE call and one span set: the second family multiplies flagged work
    only."""
    require(EXTRACT_MODULE, WORKER, SECOND_FAMILY_MODEL, RESULT_TYPE, issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("SYN-001",))
        version = seed_package(store, (_CRITERIA[1],))  # unflagged criterion only
        content_hash = store.blobs().put(_MARKDOWN.encode("utf-8"))
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute(
                "INSERT INTO document (document_id, submission_id, content_hash) "
                "VALUES (:d, :s, :h)",
                d="doc-syn001-1", s="SYN-001", h=content_hash,
            )
        orchestrator = Orchestrator(store)
        run_id = orchestrator.create_run(ORCH_COHORT_ID, version, _resolved())
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)

        provider = _TwoModelProvider()
        refs = {
            "primary": extractor_ref(build_id="/models/qwen3-30b.gguf@primary"),
            "second": require(EXTRACT_MODULE, SECOND_FAMILY_MODEL, issue=ISSUE),
        }
        _process(store, provider, unit, require(EXTRACT_MODULE, WORKER, issue=ISSUE),
                 refs, high_risk=("C1",))  # C2 is NOT on the list

        assert len(provider.calls) == 1, (
            f"an unflagged criterion must extract ONCE, saw {len(provider.calls)} calls"
        )
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT payload FROM evidence WHERE work_id = :w", w=unit.work_id
        )
        assert len(rows) == 1
        payload = _payload(rows[0]["payload"])
        serialized = json.dumps(payload, sort_keys=True)
        assert _PRIMARY_SPANS[0]["text"] in serialized
        assert _SECOND_SPANS[0]["text"] not in serialized, (
            "the unflagged criterion's evidence carries a second-family set it never "
            "extracted"
        )
    finally:
        store.close()
