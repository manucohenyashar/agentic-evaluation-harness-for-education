"""`TC-INTEG-C16`, `C17` and `C18` — idempotence, the view surface, and the gate's latency
(§6.11.4, `CT-INTEG-16/17/18`).

| Case | Clause | The violation it catches |
|---|---|---|
| `C16` | a repeat `verify` on unchanged inputs writes nothing | `bump_retries` running unconditionally (V-3), or the review enqueue losing its `OR IGNORE` |
| `C17` | the extraction view is exactly five reads, each raising on fault | a view returning `()` on fault (fail-open), or growing a sixth read the gate starts depending on |
| `C18` | the gate's per-call cost | the document cache or the index removed |

**C16 snapshots three tables, not one.** `FR-INTEG-10`'s clause is "writes no additional
`work_unit`, `review_queue` or `run_metrics` row", and the shipped code records that
suppressing only the retry bump was *tried and measured*: the sufficiency route's repeat half
reads the bumped `attempts` back and inserts two escalation units, so a gate that deduped the
bump alone still wrote two `work_unit` rows. A one-table snapshot passes that.

**C17 is asserted against both views**, as the clause requires. `StoreExtractionView` is what
production reads; `LedgerEvidenceView` is the double the journeys drive. A double with a sixth
method is how the gate acquires a dependency that does not exist in production — the tests go
green and the shipped gate reads an attribute that is not there.

**C18 is `PERF-12`**, implemented in `tests/integration/integ/test_perf_12_verify_latency.py`
and cross-referenced here rather than duplicated: two files timing the same call would report
two numbers for one property, and the one nobody looked at would rot.

**Isolation: rung 2.**
"""

from __future__ import annotations

import inspect
import sqlite3
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.integ import IntegrityGate, StoreExtractionView
from aeh.store import Statement, open_store
from tests.support.integ_vocabulary import (
    Doc,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]

SUBMISSION = "SUB-101"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)
MARKDOWN = "The thesis is stated plainly, and the argument follows from it."

#: `CT-INTEG-17`'s declared surface — M-INTEG's *Requires* table, verbatim.
DECLARED_VIEW_READS = frozenset({
    "spans",
    "second_family_spans",
    "regions",
    "panel_sufficiency",
    "criterion_requires_citation",
})


def _real_span() -> Span:
    start = MARKDOWN.index("thesis")
    return Span(start, start + len("thesis"), "thesis")


def _hallucinated_span() -> Span:
    return Span(0, 6, "quorum")


def _scenario(tmp_data_dir, *, spans, panel: PanelFlags):
    store = open_store(tmp_data_dir)
    orchestrator, run_id, _version = seed_run(
        store, submissions=(SUBMISSION,), criteria=CRITERIA,
    )
    handle = store.cohort(ORCH_COHORT_ID)
    seed_document(
        handle, document_id_for(SUBMISSION), SUBMISSION, Doc(markdown=MARKDOWN).markdown,
        ORCH_COHORT_ID,
    )
    orchestrator.enumerate_units(run_id)
    gate = IntegrityGate(
        handle, store.blobs(), ExtractionView(spans=spans, panel=panel),
        ocr_conf_floor=0.70,
    )
    return store, handle, run_id, gate


def _snapshot(store: Any, handle: Any, run_id: str) -> dict[str, Any]:
    """The three tables `FR-INTEG-10`'s clause names, as full row sets.

    Rows rather than counts: a repeat that deleted one row and inserted another would keep
    every count identical while rewriting the ledger under the teacher.
    """
    work_units = [
        tuple(row) for row in handle.query(
            Statement(
                "SELECT work_id, status, attempts, origin FROM work_unit "
                "WHERE run_id = :r ORDER BY work_id"
            ),
            r=run_id,
        )
    ]
    review = [
        tuple(row) for row in handle.query(
            Statement(
                "SELECT queue_id, reason FROM review_queue WHERE submission_id = :s "
                "ORDER BY queue_id"
            ),
            s=SUBMISSION,
        )
    ]
    metrics = [
        tuple(row) for row in store.durable().query(
            Statement(
                "SELECT metric, value FROM run_metrics WHERE run_id = :r "
                "ORDER BY metric, value"
            ),
            r=run_id,
        )
    ]
    return {"work_unit": work_units, "review_queue": review, "run_metrics": metrics}


# --- TC-INTEG-C16 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,spans,panel",
    (
        ("verification-false", [_hallucinated_span()], PanelFlags((True, True, True))),
        ("sufficiency-insufficient", [_real_span()], PanelFlags((False, False, False))),
        ("passing", [_real_span()], PanelFlags((True, True, True))),
    ),
    ids=("verification-false", "sufficiency-insufficient", "passing"),
)
def test_tc_integ_c16_a_repeat_verify_leaves_all_three_tables_identical(
    tmp_data_dir, label, spans, panel
):
    """Snapshot after call 1, snapshot after call 2 on unchanged inputs: equal, `attempts`
    included.

    All three routes, and all three tables. The sufficiency route is the one that makes the
    multi-table snapshot necessary: its repeat half reads the bumped `attempts` back and
    inserts two escalation units, so a gate that suppressed only the bump still wrote two
    `work_unit` rows against a clause whose words are "writes no additional `work_unit`,
    `review_queue` or `run_metrics` row".
    """
    store, handle, run_id, gate = _scenario(tmp_data_dir, spans=spans, panel=panel)
    try:
        gate.verify(run_id, SUBMISSION, CRITERION)
        after_one = _snapshot(store, handle, run_id)

        gate.verify(run_id, SUBMISSION, CRITERION)
        after_two = _snapshot(store, handle, run_id)

        assert after_two == after_one, (
            f"{label}: the repeat call changed the ledger. "
            f"work_unit {len(after_one['work_unit'])}→{len(after_two['work_unit'])}, "
            f"review_queue {len(after_one['review_queue'])}→"
            f"{len(after_two['review_queue'])}, "
            f"run_metrics {len(after_one['run_metrics'])}→"
            f"{len(after_two['run_metrics'])}. An unchanged panel state routes nothing "
            "(CT-INTEG-16): three self-inflicted bumps quarantine a cell that failed no check"
        )
    finally:
        store.close()


# --- TC-INTEG-C17 --------------------------------------------------------------------------------


def _public_reads(view_type: type) -> frozenset[str]:
    return frozenset(
        name for name, member in inspect.getmembers(view_type, callable)
        if not name.startswith("_")
    )


@pytest.mark.parametrize("view_type", (StoreExtractionView,), ids=("StoreExtractionView",))
def test_tc_integ_c17_the_view_surface_is_exactly_the_five_declared_reads(view_type):
    """The public method set equals the five names — equality, not containment.

    A sixth read is how the gate acquires a dependency nobody declared: it appears on the
    double first, the tests go green, and the shipped view does not have it.
    """
    reads = _public_reads(view_type)

    assert reads == DECLARED_VIEW_READS, (
        f"{view_type.__name__} publishes {sorted(reads)}; M-INTEG's Requires surface is "
        f"{sorted(DECLARED_VIEW_READS)} (CT-INTEG-17)"
    )


def test_tc_integ_c17_the_journey_double_publishes_the_same_five_reads():
    """`LedgerEvidenceView` — the double the journeys drive — matches the shipped view.

    The clause says "against **both**", and this is the half that catches drift in the
    direction that matters: a double with an extra method lets a gate start depending on
    something production does not have, and every test stays green.
    """
    from tests.support.e2e_world import LedgerEvidenceView

    reads = _public_reads(LedgerEvidenceView)

    assert reads == DECLARED_VIEW_READS, (
        f"LedgerEvidenceView publishes {sorted(reads)} against the shipped view's "
        f"{sorted(DECLARED_VIEW_READS)}. A double that drifts from the surface it stands in "
        "for is how a gate acquires a dependency that does not exist in production"
    )


@pytest.mark.parametrize(
    "method_name,args",
    (
        ("spans", (SUBMISSION, CRITERION)),
        ("second_family_spans", (SUBMISSION, CRITERION)),
        ("regions", (document_id_for(SUBMISSION),)),
        ("panel_sufficiency", (SUBMISSION, CRITERION)),
    ),
)
def test_tc_integ_c17_each_backing_read_raises_rather_than_failing_open(
    tmp_data_dir, method_name, args
):
    """A faulted backing read raises; it never answers `()`.

    The fail-open direction is the one that cannot be detected downstream: `[]` tells the gate
    "measured, and there is nothing", which is the same value a student who cited nothing
    produces. `TC-INTEG-15` covers this at the FR level; the clause case is here because the
    surface set above is only a contract if every member of it holds the same property.
    """
    from aeh.pkg import PackageCatalog

    class _FaultingHandle:
        def __init__(self, real: Any) -> None:
            self._real = real

        def query(self, *a: Any, **kw: Any) -> Any:
            raise sqlite3.OperationalError("disk I/O error")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

    store = open_store(tmp_data_dir)
    try:
        _orchestrator, _run_id, version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        view = StoreExtractionView(
            _FaultingHandle(store.cohort(ORCH_COHORT_ID)), catalog, version
        )

        with pytest.raises(sqlite3.OperationalError):
            result = getattr(view, method_name)(*args)
            pytest.fail(
                f"{method_name} returned {result!r} on a faulted read instead of raising — "
                "the gate reads an empty result as 'measured, and there is nothing', which is "
                "the one lie it cannot detect (CT-INTEG-17, NFR-INTEG-03)"
            )
    finally:
        store.close()


# --- TC-INTEG-C18 --------------------------------------------------------------------------------


def test_tc_integ_c18_the_gate_latency_case_exists_and_is_gated():
    """`PERF-12` is this clause, and it lives in one place.

    Cross-referenced rather than duplicated: two files timing the same call would report two
    numbers for one property, and the one nobody looked at would rot. This asserts the case is
    present and still carries its threshold and its CI gate, so a deletion or a quiet
    un-gating is visible from the clause suite that depends on it.
    """
    import pathlib

    path = pathlib.Path("tests/integration/integ/test_perf_12_verify_latency.py")
    assert path.exists(), (
        f"{path} is gone; CT-INTEG-18's only case went with it (PERF-12)"
    )
    source = path.read_text(encoding="utf-8")
    assert "MEDIAN_BUDGET_MS = 2.0" in source, (
        "PERF-12 no longer declares the 2 ms budget CT-INTEG-18 names"
    )
    assert "HARNESS_PERF_GATE" in source, (
        "PERF-12 no longer reads the CI gate, so its threshold binds nowhere"
    )
