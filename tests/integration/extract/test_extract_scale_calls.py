"""`TC-EXTRACT-11` — 350 students by 15 judged criteria is about 5,250 extraction
calls, and extraction does NOT multiply by panel size.
Test plan §5.8; `NFR-EXTRACT-01`.

Oracle — **exact call count**, composed of two halves:

- **Enumeration** (the 5,250): the full 350 × 15 package enumerates EXACTLY
  5,250 extract units — not 5,250 × 3. The same enumeration writes 15,750 score units
  (350 × 15 × the 3-judge panel), which is the differential: the panel depth
  multiplies the SCORE stage by exactly the panel depth and the EXTRACT stage by
  exactly one. "One call per extract unit" is the bridge from units to calls.
- **Call count** (the bridge, on a bounded slice): a counting provider stub drives the
  first 30 extract units (2 submissions × 15 criteria) under a 3-judge panel and under
  a 1-judge panel; each `process` makes EXACTLY one `complete` call and the count is
  the same at both depths — the per-unit call count does not multiply by panel.

The slice is bounded because recording 5,250 fixtures into a fixture provider would
measure fixture recording, not call count (disclosed stand-in: the stub returns one
canned reply for every request; the request-level contract is TC-EXTRACT-01's and
CT-PROV-05's, not this case's subject).

**Written ahead of #68** (`M-EXTRACT`) — the call-count half only: the enumeration
half runs GREEN against shipped `M-ORCH` (it requires nothing of `aeh.extract`), so it
carries no marker and guards the gate; the file is still registered in
`WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction suite (TS-26)"` because it carries the
marker (symbols conjunction; see `tests/support/extract_vocabulary.py`).

**Interface this case assumes of #68**: `ExtractionWorker(store, provider,
model_ref).process(unit)` — one `complete` call per unit is the one-call-per-unit
assumption; a worker that pre-warms, retries on success or calls per-judge fails the
count.

**Disclosed stand-ins.** Documents are seeded only for the submissions whose units are
actually driven (the rest are never processed); the canned reply is
`span_completion`'s disclosed stand-in. The stub is the provider boundary — the
RecordedFixtureProvider contract is exercised in the other cases of this suite.

**Isolation: rung 2/3** — real store, real Tier P package, real cohort ledger, real
enumeration; the model boundary is a counting stub.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import STAGE_EXTRACT, STAGE_SCORE, Orchestrator
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.extract_vocabulary import (
    EXTRACT_ISSUE,
    RESULT_TYPE,
    WORKER,
    extractor_ref,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package

pytestmark = pytest.mark.integration

ISSUE = EXTRACT_ISSUE

_STUDENTS = 350
_JUDGED = 15
_TOTAL_CALLS = _STUDENTS * _JUDGED

_CRITERIA = tuple(
    {"criterion_id": f"C{i:02d}", "kind": "open", "scoring_model": "holistic"}
    for i in range(1, _JUDGED + 1)
)

_SLICE_SUBMISSIONS = ("SYN-001", "SYN-002")


class _CountingProvider:
    """One canned reply for every request; counts `complete` calls — the number the
    oracle reads."""

    def __init__(self, spans: list[dict[str, Any]]) -> None:
        self._spans = spans
        self.calls = 0

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls += 1
        return span_completion(self._spans, build_id="extractor-build-scale")


def _resolved(panel: tuple) -> Any:
    return resolve_run_config(
        edge_cfg(panel=panel),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


def _seed_document(store: Any, submission_id: str, markdown: str) -> None:
    content_hash = store.blobs().put(markdown.encode("utf-8"))
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash) "
            "VALUES (:d, :s, :h)",
            d=f"doc-{submission_id}-1", s=submission_id, h=content_hash,
        )


def _stage_rows(store: Any, run_id: str) -> dict[str, int]:
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT stage, COUNT(*) AS n FROM work_unit WHERE run_id = :r "
        "GROUP BY stage",
        r=run_id,
    )
    return {row["stage"]: row["n"] for row in rows}


def test_tc_extract_11_enumeration_is_exactly_5250_extract_units(tmp_data_dir):
    """`TC-EXTRACT-11` (enumeration half) — 350 × 15 judged criteria enumerate exactly
    5,250 extract units while the score stage carries the panel's 15,750: the panel
    multiplies score by 3 and extract by exactly one."""
    store = open_store(tmp_data_dir)
    try:
        names = tuple(f"SYN-{i:03d}" for i in range(1, _STUDENTS + 1))
        seed_cohort(store, names)
        version = seed_package(store, _CRITERIA)
        orchestrator = Orchestrator(store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, version, _resolved(edge_panel(3))
        )
        orchestrator.enumerate_units(run_id)

        by_stage = _stage_rows(store, run_id)
        assert by_stage.get(STAGE_EXTRACT) == _TOTAL_CALLS, (
            f"expected exactly {_TOTAL_CALLS} extract units (350 × 15, no panel "
            f"multiplication), got {by_stage.get(STAGE_EXTRACT)}"
        )
        assert by_stage.get(STAGE_SCORE) == _TOTAL_CALLS * 3, (
            f"precondition for the differential: the 3-judge panel multiplies the "
            f"score stage to {_TOTAL_CALLS * 3}, got {by_stage.get(STAGE_SCORE)}"
        )
    finally:
        store.close()


def test_tc_extract_11_one_call_per_unit_at_any_panel_depth(tmp_data_dir):
    """`TC-EXTRACT-11` (call-count half) — driving 30 extract units makes exactly 30
    `complete` calls under a 3-judge panel and exactly 30 under a 1-judge panel: the
    per-unit call count does not multiply by panel size."""
    require(EXTRACT_MODULE, WORKER, RESULT_TYPE, issue=ISSUE)
    markdown = (
        "<untrusted_student_content>\n"
        "The crate accelerates at 2 m/s^2.\n"
        "</untrusted_student_content>"
    )
    counts: dict[str, int] = {}
    for panel_name, panel in (("panel3", edge_panel(3)), ("panel1", edge_panel(1))):
        store = open_store(tmp_data_dir / panel_name)
        try:
            seed_cohort(store, _SLICE_SUBMISSIONS)
            version = seed_package(store, _CRITERIA)
            for submission_id in _SLICE_SUBMISSIONS:
                _seed_document(store, submission_id, markdown)
            orchestrator = Orchestrator(store)
            run_id = orchestrator.create_run(ORCH_COHORT_ID, version, _resolved(panel))
            orchestrator.enumerate_units(run_id)
            n_units = store.cohort(ORCH_COHORT_ID).query(
                "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r "
                "AND stage = :st",
                r=run_id, st=STAGE_EXTRACT,
            )[0]["n"]
            assert n_units == 30, (
                f"precondition: expected the 30-unit slice (2 × 15), got {n_units}"
            )

            provider = _CountingProvider(
                [{"start": 0, "end": 10, "text": "The crate"}]
            )
            worker = require(EXTRACT_MODULE, WORKER, issue=ISSUE)
            model_ref = extractor_ref()
            for _i in range(n_units):
                unit = orchestrator.lease("w-scale", STAGE_EXTRACT, 1)[0]
                worker(store, provider, model_ref).process(unit)
            counts[panel_name] = provider.calls
        finally:
            store.close()

    assert counts == {"panel3": 30, "panel1": 30}, (
        f"the per-unit call count multiplied by panel depth: {counts}"
    )
