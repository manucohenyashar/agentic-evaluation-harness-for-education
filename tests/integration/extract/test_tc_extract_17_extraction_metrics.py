"""`TS-87` (issue #381) — `TC-EXTRACT-17`, `extraction_metrics` over hand-built evidence.

Gap-fix test plan §5 (`FR-EXTRACT-12`, P1, rung 2):

    Hand-built evidence for run R, criterion C1: units with span counts `[0, 2, 2, 5]`,
    latencies `[100, 200, 300, 400]` ms, no second family; criterion C2 with a second family
    where 1 of 4 disagrees.
    C1: `spans_per_unit = {0:1, 2:2, 5:1}`, `empty_result_rate = 0.25`,
    `second_family_disagreement_rate is None` (not 0.0), `extraction_latency_p50_ms = 250`,
    `p95_ms = 385`. C2: rate `0.25`. Run RB's rows do not contribute. Oracle: hand-computed.

**The percentile method, pinned.** Linear interpolation between closest ranks (NumPy's default,
`statistics.quantiles(..., method="inclusive")`): the value at rank `q·(n−1)` over the sorted
sample. For `[100, 200, 300, 400]`: p50 → rank 1.5 → `200 + 0.5·100 = 250`; p95 → rank 2.85 →
`300 + 0.85·100 = 385`.

**"Disagrees"** is read as the second family's span set differing from the primary's for the
same unit — the comparison `M-INTEG`'s `extractor_disagreement` makes. Three C2 units carry an
identical second-family span set, one a different one: 1/4.

**Hand-built rows.** `work_unit` and `evidence` rows are written directly (the disclosed test
scaffolding precedent of `tests/support/orch_run.py`): the evidence payload is the shape
`ExtractionWorker.process` writes (`{"spans": [...], "second_family": {...}}`), and
`latency_ms` is #361's column (FR-EXTRACT-13). Run RB's rows sit in the same cohort file with
wildly different values, so any leak moves every figure.

**Written ahead of implementation: yes** — keyed on `aeh.extract:extraction_metrics` (#371).

**Interface assumed:**

| Name | Assumption |
|---|---|
| `extraction_metrics(handle, run_id)` | returns an object whose `spans_per_unit`, `empty_result_rate` and `second_family_disagreement_rate` are per-criterion mappings (FR-EXTRACT-12: "per criterion") |
| latency | `extraction_latency_p50_ms` / `extraction_latency_p95_ms` per-criterion mappings — `CT-EXTRACT-17`'s contract names |

**Reconciled with `TC-EXTRACT-C14`** in this PR: that case was written ahead under a whole-run
reading (`second_family_disagreement_rate is None`, one `extraction_latency` name). The delta's
per-criterion rule and `CT-EXTRACT-17`'s five names supersede it, so its assertions and the shared
`EXTRACT_METRIC_NAMES` now read the same surface as this case — otherwise one of the two could
never pass once #371 lands. The plan's §4.7 lists C14 as "un-mark, no change"; that row is a plan
finding.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aeh.store import open_store
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort

pytestmark = pytest.mark.integration

ISSUE = "#371"
RUN_R = "run-tc-extract-17-r"
RUN_RB = "run-tc-extract-17-rb"
SUBMISSIONS = ("S1", "S2", "S3", "S4")


def _spans(count: int, *, offset: int = 0) -> list[dict[str, Any]]:
    return [
        {"start": offset + 10 * i, "end": offset + 10 * i + 5, "text": "abcde",
         "region_kind": "transcribed_text"}
        for i in range(count)
    ]


def _seed(store: Any) -> list[tuple[Any, ...]]:
    """The work units for both runs; returns the evidence rows to insert once the column exists."""
    seed_cohort(store, SUBMISSIONS)
    evidence: list[tuple[Any, ...]] = []
    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        def unit(run_id: str, submission: str, criterion: str) -> str:
            work_id = f"w-{run_id[-2:]}-{submission}-{criterion}"
            tx.execute(
                "INSERT INTO work_unit (work_id, submission_id, stage, status, run_id, "
                "criterion_id) VALUES (:w, :s, 'extract', 'done', :r, :c)",
                w=work_id, s=submission, r=run_id, c=criterion,
            )
            return work_id

        # Run R, C1: span counts [0, 2, 2, 5], latencies [100, 200, 300, 400], no second family.
        for submission, count, latency in zip(SUBMISSIONS, (0, 2, 2, 5), (100, 200, 300, 400)):
            evidence.append((unit(RUN_R, submission, "C1"), {"spans": _spans(count)}, latency))
        # Run R, C2: two spans each, a second family on every unit; S4's disagrees.
        for submission in SUBMISSIONS:
            second = _spans(2, offset=500) if submission == "S4" else _spans(2)
            payload = {"spans": _spans(2),
                       "second_family": {"resolved_build": "second-build", "spans": second}}
            evidence.append((unit(RUN_R, submission, "C2"), payload, 150))
        # Run RB: values that would move every figure if they leaked.
        for submission in SUBMISSIONS[:2]:
            evidence.append((unit(RUN_RB, submission, "C1"), {"spans": _spans(9)}, 9_000))
            payload = {"spans": _spans(1),
                       "second_family": {"resolved_build": "second-build",
                                         "spans": _spans(3, offset=900)}}
            evidence.append((unit(RUN_RB, submission, "C2"), payload, 9_000))
    return evidence


def _insert_evidence(store: Any, evidence: list[tuple[Any, ...]]) -> None:
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        for work_id, payload, latency in evidence:
            tx.execute(
                "INSERT INTO evidence (evidence_id, work_id, document_id, payload, "
                "resolved_build, latency_ms) VALUES (:e, :w, NULL, :p, 'extractor-build', :l)",
                e=work_id, w=work_id, p=json.dumps(payload, sort_keys=True).encode("utf-8"),
                l=latency,
            )


def _latency(metrics: Any, criterion: str) -> tuple[Any, Any]:
    return (metrics.extraction_latency_p50_ms[criterion],
            metrics.extraction_latency_p95_ms[criterion])


@pytest.mark.writtenahead
def test_tc_extract_17_extraction_metrics_match_the_hand_computed_values(tmp_data_dir):
    """`TC-EXTRACT-17` — every figure hand-computed; RB contributes nothing."""
    store = open_store(tmp_data_dir)
    try:
        evidence = _seed(store)
        extraction_metrics = require(EXTRACT_MODULE, "extraction_metrics", issue=ISSUE)
        _insert_evidence(store, evidence)

        metrics = extraction_metrics(store.cohort(ORCH_COHORT_ID), RUN_R)

        assert dict(metrics.spans_per_unit["C1"]) == {0: 1, 2: 2, 5: 1}, (
            f"C1 spans_per_unit = {metrics.spans_per_unit['C1']!r}"
        )
        assert metrics.empty_result_rate["C1"] == 0.25
        assert metrics.second_family_disagreement_rate["C1"] is None, (
            f"C1 ran no second family, so its disagreement rate is None, not "
            f"{metrics.second_family_disagreement_rate['C1']!r} (a zero would lie)"
        )
        p50, p95 = _latency(metrics, "C1")
        assert p50 == 250, f"C1 latency p50 = {p50!r}, hand-computed 250"
        assert p95 == pytest.approx(385), f"C1 latency p95 = {p95!r}, hand-computed 385 (linear interpolation)"

        assert metrics.second_family_disagreement_rate["C2"] == 0.25, (
            f"C2 disagreement rate = {metrics.second_family_disagreement_rate['C2']!r}; "
            f"1 of 4 second-family span sets differs"
        )
        assert dict(metrics.spans_per_unit["C2"]) == {2: 4}, "run RB's C2 rows leaked"
        assert metrics.empty_result_rate["C2"] == 0.0
    finally:
        store.close()
