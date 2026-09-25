"""`TS-86` (issue #380) — `TC-INTEG-16`: `verify` is idempotent on an unchanged panel state
(`FR-INTEG-10`).

| Route | Calls | Expected |
|---|---|---|
| (a) verification false | once; twice unchanged; a third after a new terminal score unit | after call 1 the gate's own pending extract unit has `attempts = 1`; after call 2 `attempts` is **still 1** and `work_unit`, `review_queue` and `run_metrics` row counts are unchanged; after call 3 the route may run again and `attempts = 2` |
| (b) sufficiency insufficient | as (a) | as (a) |
| (c) passing | as (a) | the plan says "no rows on any call"; what ships writes a pass record and always emits metrics, so this file asserts the clause's substance — **no retry and no review item, ever** — and reports the wording (see the route (c) case) |

**This is the self-inflicted-bump case.** The gate charges a retry when it routes. A composition
layer that verifies a cell, restarts, and verifies it again has changed nothing about the cell
— but a gate that re-routed would charge a second retry for it, and three of those quarantine a
cell whose evidence was never in doubt. The run then shows "could not be scored" for a cell
that failed no check: the gate ate its own retry budget.

**Why `attempts` and row counts together.** The clause's words are "writes no additional
`work_unit`, `review_queue` or `run_metrics` row", and the shipped code records that
suppressing only the bump was **tried and measured**: the sufficiency route's repeat half reads
the bumped `attempts` back and inserts two escalation units, so a gate that deduped the bump
alone still wrote two `work_unit` rows. Asserting `attempts` alone would pass against exactly
that half-fix, which is why all three counts are snapshotted.

**Call 3 is what stops the dedupe being a permanent gag.** Keying on the cell's terminal
`work_id` set rather than on a boolean is the point: an escalation's verdicts landing is new
evidence and the gate *should* look again. A test that only asserted "call 2 does nothing"
would pass against a gate that never routed a cell twice under any circumstances, which would
strand every widened panel.

**Route (c) is the control.** A passing cell writes nothing on any of the three calls, so the
"unchanged counts" assertions in (a) and (b) cannot be passing because the gate writes nothing
ever.

**Isolation: rung 2** — real store, real cohort ledger, real `IntegrityGate`; the extraction
view is `tests.support.integ_vocabulary.ExtractionView`, the sanctioned double of
`StoreExtractionView`'s five-method surface (`CT-INTEG-17`).
"""

from __future__ import annotations

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
from aeh.integ import IntegrityGate
from aeh.store import open_store
from tests.support.integ_vocabulary import (
    Doc,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "SUB-101"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)
MARKDOWN = "The thesis is stated plainly, and the argument follows from it."


def _real_span() -> Span:
    start = MARKDOWN.index("thesis")
    return Span(start, start + len("thesis"), "thesis")


def _hallucinated_span() -> Span:
    """Looks like a quotation, is not in the document — RISK-01's shape."""
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
    view = ExtractionView(spans=spans, panel=panel)
    gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=0.70)
    return store, handle, run_id, gate


def _panel_moved(handle: Any, run_id: str, ordinal: str) -> None:
    """A new terminal score unit — the cell's panel state has moved (`FR-INTEG-10`).

    Written directly and disclosedly, the same stand-in
    `tests/integration/integ/test_integ_retry_and_quarantine.py` uses: the production writer
    is `M-ORCH`'s, and what this case needs is the *state*, not the writer.
    """
    with handle.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO work_unit (work_id, submission_id, stage, status, "
            "run_id, criterion_id) VALUES (:w, :s, 'score', 'done', :r, :c)",
            w=f"w-panel-{SUBMISSION}-{CRITERION}-{ordinal}",
            s=SUBMISSION, r=run_id, c=CRITERION,
        )


def _counts(store: Any, handle: Any, run_id: str) -> dict[str, int]:
    """The three row counts `FR-INTEG-10`'s clause names, plus the gate's own attempts."""
    work_units = handle.query(
        "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r", r=run_id
    )[0]["n"]
    review = handle.query(
        "SELECT COUNT(*) AS n FROM review_queue WHERE submission_id = :s", s=SUBMISSION
    )[0]["n"]
    metrics = store.durable().query(
        "SELECT COUNT(*) AS n FROM run_metrics WHERE run_id = :r", r=run_id
    )[0]["n"]
    return {
        "work_unit": int(work_units),
        "review_queue": int(review),
        "run_metrics": int(metrics),
    }


def _attempts(handle: Any, run_id: str) -> int:
    """The gate's own pending extract unit's attempts, or 0 when it has none."""
    rows = handle.query(
        "SELECT MAX(attempts) AS a FROM work_unit WHERE run_id = :r AND "
        "submission_id = :s AND criterion_id = :c AND stage = 'extract' AND "
        "status = 'pending'",
        r=run_id, s=SUBMISSION, c=CRITERION,
    )
    return int(rows[0]["a"] or 0)


def _routing_arm(tmp_data_dir, *, spans, panel: PanelFlags, label: str) -> None:
    """Calls 1, 2 and 3 with the assertions routes (a) and (b) share."""
    store, handle, run_id, gate = _scenario(tmp_data_dir, spans=spans, panel=panel)
    try:
        gate.verify(run_id, SUBMISSION, CRITERION)
        after_one = _counts(store, handle, run_id)
        assert _attempts(handle, run_id) == 1, (
            f"{label}: after one call the gate's pending extract unit carries "
            f"{_attempts(handle, run_id)} attempt(s), not 1 — the route charges exactly one "
            "retry for the round it asked for"
        )

        gate.verify(run_id, SUBMISSION, CRITERION)
        assert _attempts(handle, run_id) == 1, (
            f"{label}: a repeat call on an UNCHANGED panel state charged a second retry "
            f"(attempts is now {_attempts(handle, run_id)}). Three of those quarantine a cell "
            "that failed no check — the gate eating its own retry budget (FR-INTEG-10)"
        )
        assert _counts(store, handle, run_id) == after_one, (
            f"{label}: the repeat call wrote rows. {after_one} became "
            f"{_counts(store, handle, run_id)}. The clause forbids an additional work_unit, "
            "review_queue or run_metrics row — suppressing only the retry bump was tried and "
            "still wrote two escalation units"
        )

        _panel_moved(handle, run_id, "a")
        gate.verify(run_id, SUBMISSION, CRITERION)
        assert _attempts(handle, run_id) == 2, (
            f"{label}: after a new terminal score unit the gate did not look again "
            f"(attempts is {_attempts(handle, run_id)}, not 2). Keying on panel STATE rather "
            "than on a boolean is what lets a widened panel be re-examined; a permanent gag "
            "would strand every escalation"
        )
    finally:
        store.close()


# --- TC-INTEG-16 ----------------------------------------------------------------------------


def test_tc_integ_16_route_a_failed_verification_routes_once_per_panel_state(tmp_data_dir):
    """Route (a) — the span does not appear in the document, so verification is false."""
    _routing_arm(
        tmp_data_dir,
        spans=[_hallucinated_span()],
        panel=PanelFlags((True, True, True)),
        label="route (a) verification false",
    )


def test_tc_integ_16_route_b_insufficient_panel_routes_once_per_panel_state(tmp_data_dir):
    """Route (b) — the spans verify, and the panel reports the evidence insufficient.

    The route whose repeat half inserts escalation units, which is why the row-count snapshot
    is part of the shared assertion rather than a flourish.
    """
    _routing_arm(
        tmp_data_dir,
        spans=[_real_span()],
        panel=PanelFlags((False, False, False)),
        label="route (b) sufficiency insufficient",
    )


def test_tc_integ_16_route_c_a_passing_cell_is_never_retried_or_queued(tmp_data_dir):
    """Route (c) — the control. A verified, sufficient cell is never charged a retry and never
    queued for review, across all three calls.

    **A divergence from the plan's wording, reported rather than asserted away.** The plan's
    row (c) says "No rows on any call". The shipped pass route writes exactly two things, and
    both are by design:

    * one gate-owned `work_unit` with `status='done'` — the record that the cell passed, and
      the row `mark_extract_done` pairs with. A pass that left no trace would be
      indistinguishable from a cell the gate never reached;
    * `run_metrics` rows, because `verify`'s own contract is "the metrics surface **always**
      emits" — a rate that appeared only on failures would make a healthy run look unmeasured.

    So what (c) is actually protecting is asserted directly: **zero retries and zero review
    items**, on a cell that passes. Those are the two things that cost a student a
    "could not be scored", and neither may happen to a cell that failed no check.
    """
    store, handle, run_id, gate = _scenario(
        tmp_data_dir, spans=[_real_span()], panel=PanelFlags((True, True, True)),
    )
    try:
        baseline = _counts(store, handle, run_id)

        signals = gate.verify(run_id, SUBMISSION, CRITERION)
        assert signals.spans_verified is True and signals.sufficiency_flag is True, (
            f"the control cell did not pass ({signals}), so it is not exercising route (c)"
        )
        assert _attempts(handle, run_id) == 0, (
            f"a passing cell was charged {_attempts(handle, run_id)} retry attempt(s) on "
            "call 1"
        )
        after_one = _counts(store, handle, run_id)
        assert after_one["review_queue"] == baseline["review_queue"], (
            "a passing cell was queued for review"
        )

        gate.verify(run_id, SUBMISSION, CRITERION)
        assert _counts(store, handle, run_id) == after_one, (
            f"the repeat call changed the ledger: {after_one} became "
            f"{_counts(store, handle, run_id)}. An unchanged panel state routes nothing, on "
            "the passing route as much as on the failing ones (FR-INTEG-10)"
        )
        assert _attempts(handle, run_id) == 0

        _panel_moved(handle, run_id, "a")
        gate.verify(run_id, SUBMISSION, CRITERION)
        assert _attempts(handle, run_id) == 0, (
            f"a passing cell was charged {_attempts(handle, run_id)} retry attempt(s) after "
            "its panel moved; looking again is right, charging for it is not"
        )
        assert _counts(store, handle, run_id)["review_queue"] == baseline["review_queue"], (
            "a passing cell was queued for review after its panel moved"
        )
    finally:
        store.close()


def test_tc_integ_16_the_passing_route_records_its_pass(tmp_data_dir):
    """The other half of route (c)'s divergence, pinned so it is a decision and not a drift.

    The pass route writes one gate-owned `done` extract unit. This asserts that it does —
    because if it stopped, route (c)'s "no retries, no review items" above would still pass
    while a passing cell became indistinguishable from one the gate never reached.
    """
    store, handle, run_id, gate = _scenario(
        tmp_data_dir, spans=[_real_span()], panel=PanelFlags((True, True, True)),
    )
    try:
        gate.verify(run_id, SUBMISSION, CRITERION)

        owned = handle.query(
            "SELECT status FROM work_unit WHERE run_id = :r AND work_id LIKE 'integ-unit-%'",
            r=run_id,
        )
        assert len(owned) == 1, (
            f"the passing route wrote {len(owned)} gate-owned unit(s), not one"
        )
        assert str(owned[0]["status"]) == "done", (
            f"the gate's own unit for a passing cell is {owned[0]['status']!r}, not 'done'"
        )
    finally:
        store.close()


def test_tc_integ_16_the_dedupe_survives_a_new_gate_instance(tmp_data_dir):
    """The restart half — a second `IntegrityGate` over the same store does not re-route.

    `FR-INTEG-10`'s key is recorded in `cell_phase`'s `integrity_post` row precisely "so the
    answer survives the process that computed it". An in-memory-only dedupe passes every case
    above and fails here, and a composition layer that verifies, restarts and verifies again
    is the ordinary shape of a resumed run — not an edge case.
    """
    store, handle, run_id, gate = _scenario(
        tmp_data_dir, spans=[_hallucinated_span()], panel=PanelFlags((True, True, True)),
    )
    try:
        gate.verify(run_id, SUBMISSION, CRITERION)
        after_one = _counts(store, handle, run_id)
        assert _attempts(handle, run_id) == 1

        fresh = IntegrityGate(
            handle, store.blobs(),
            ExtractionView(spans=[_hallucinated_span()], panel=PanelFlags((True, True, True))),
            ocr_conf_floor=0.70,
        )
        fresh.verify(run_id, SUBMISSION, CRITERION)

        assert _attempts(handle, run_id) == 1, (
            f"a fresh gate instance re-routed an unchanged cell (attempts is now "
            f"{_attempts(handle, run_id)}); the dedupe is in memory only, so every restart "
            "costs the cell another retry (FR-INTEG-10)"
        )
        assert _counts(store, handle, run_id) == after_one, (
            f"the fresh instance wrote rows: {after_one} became "
            f"{_counts(store, handle, run_id)}"
        )
    finally:
        store.close()
