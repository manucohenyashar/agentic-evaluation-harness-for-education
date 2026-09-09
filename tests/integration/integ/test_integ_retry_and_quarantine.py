"""`TC-INTEG-02` — a span failing verification is discarded and the extraction unit
retried; on repeated failure the unit quarantines rather than proceeding to scoring on
unverified evidence.

Test plan §5.9 (P0, `FR-INTEG-02`, Integration / rung 2 — real SQLite, real blob dir;
the model boundary is `RecordedFixtureProvider`'s seam, unexercised here because the
spans are injected). Written ahead of `#73` (test plan §8.2): every case fails only
through `NotImplementedYet` naming `#73`.

**Oracle: the exact state transition, on the real work ledger.** After each failing
verification the ledger shows the promised move — the rejected evidence is gone, a
fresh `extract` unit exists with its attempt count grown — and after the repeated
failure the unit is `quarantined`, with the criterion's score units never dispatchable.
*Who* performs the transition (the gate's routing request or the orchestrator wiring
consuming it) is #73/#74's to settle; the oracle is the ledger state, and the plan's
own wording ("the unit quarantines") is a state claim, not a call graph.

The extraction side rides `ExtractionView` (see `tests/support/integ_vocabulary.py`
for the full interface-assumptions table): `#68`'s span persistence is not landed, so
the spans are injected at the one seam design §3.9's *Requires* row says M-EXTRACT is
read through, and the view's payload is mutated between attempts to simulate the
extractor failing once, twice, then persistently.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    Doc,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

_SUBMISSIONS = ("SUB-101",)
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)

_MARKDOWN = "The student argues the thesis directly in the opening paragraph.\n"

#: FR-EXTRACT-08's ladder: a unit failing three times quarantines. The first two
#: failures retry; the third is the repeated failure.
RETRY_LIMIT = 3


def _verified_span(doc: Doc) -> Span:
    start = doc.markdown.index("thesis")
    return Span(start, start + len("thesis"), "thesis")


def _hallucinated_span() -> Span:
    """A span that looks like a quotation but is not in the document (RISK-01's shape)."""
    return Span(0, 6, "quorum")


def _units(store, run_id: str, submission_id: str, criterion_id: str, stage: str) -> list[dict]:
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT work_id, status, attempts FROM work_unit WHERE run_id = :r AND "
        "submission_id = :s AND criterion_id = :c AND stage = :st ORDER BY work_id",
        r=run_id,
        s=submission_id,
        c=criterion_id,
        st=stage,
    )


def _scenario(tmp_data_dir):
    """A real run (seed_run + enumerate), the document, and a view whose span payload
    the test mutates per attempt to simulate the extractor failing and recovering."""
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
    handle = store.cohort(ORCH_COHORT_ID)
    doc = Doc(markdown=_MARKDOWN)
    seed_document(handle, document_id_for("SUB-101"), "SUB-101", doc.markdown, ORCH_COHORT_ID)
    orch.enumerate_units(run_id)
    payload: list[Span] = []
    view = ExtractionView(spans=payload, panel=PanelFlags((True, True, True)))
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#73")
    gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=0.70)
    return store, handle, run_id, doc, payload, gate


def test_tc_integ_02_failing_span_is_discarded_and_the_unit_retried(tmp_data_dir):
    """`TC-INTEG-02`, attempts 1 and 2 — the failing span is discarded and the
    extraction unit retried: no evidence row carries the rejected span, and a fresh
    pending `extract` unit exists with its attempts grown."""
    store, handle, run_id, doc, payload, gate = _scenario(tmp_data_dir)
    payload[:] = [_hallucinated_span()]
    for attempt in (1, 2):
        signals = gate.verify(run_id, "SUB-101", "C1")
        assert signals.spans_verified is False, f"attempt {attempt}: the hallucinated span verified"
        extracted = _units(store, run_id, "SUB-101", "C1", "extract")
        done = [u for u in extracted if u["status"] == "done"]
        assert not done, (
            f"attempt {attempt}: a completed extract unit survives a failed verification "
            "— the span was discarded, and with it the unit's claim to be done"
        )
        retries = [u for u in extracted if u["status"] == "pending"]
        assert retries, f"attempt {attempt}: no re-extraction request in the ledger (FR-INTEG-02)"
        assert all(u["attempts"] == attempt for u in retries), (
            f"attempt {attempt}: the retry's attempt count is "
            f"{[u['attempts'] for u in retries]}, expected {attempt}"
        )
        # The discarded span left no evidence behind: nothing scores on a rejected span.
        rows = handle.query(
            "SELECT * FROM evidence WHERE work_id IN (SELECT work_id FROM work_unit "
            "WHERE run_id = :r AND submission_id = :s AND criterion_id = :c)",
            r=run_id, s="SUB-101", c="C1",
        )
        assert not rows, f"attempt {attempt}: evidence rows survive the discard"
    store.close()


def test_tc_integ_02_repeated_failure_quarantines_and_never_reaches_scoring(tmp_data_dir):
    """`TC-INTEG-02`, the third failure — the unit quarantines rather than proceeding
    to scoring on unverified evidence: `status = 'quarantined'`, no further re-extraction
    request, and the criterion's score units stay pending through a full lease pass."""
    store, handle, run_id, doc, payload, gate = _scenario(tmp_data_dir)
    payload[:] = [_hallucinated_span()]
    for _attempt in range(RETRY_LIMIT):
        gate.verify(run_id, "SUB-101", "C1")
    extracted = _units(store, run_id, "SUB-101", "C1", "extract")
    quarantined = [u for u in extracted if u["status"] == "quarantined"]
    assert quarantined, (
        f"three verification failures left statuses {[u['status'] for u in extracted]} "
        "— the repeated failure must quarantine, not retry forever and not proceed"
    )
    assert not [u for u in extracted if u["status"] == "pending"], (
        "a quarantined criterion still has a live re-extraction request — the ladder "
        "stops at the quarantine, it does not loop (FR-EXTRACT-08's shape)"
    )
    # The consequence the clause exists for: nothing scores on unverified evidence.
    leaseable = handle.query(
        "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r AND submission_id = :s "
        "AND criterion_id = :c AND stage = 'score' AND status = 'done'",
        r=run_id, s="SUB-101", c="C1",
    )
    assert leaseable[0]["n"] == 0, (
        "score units completed for a criterion whose extraction never verified — "
        "proceeding to scoring on unverified evidence is the exact outcome "
        "FR-INTEG-02 forbids"
    )
    store.close()


def test_tc_integ_02_recovered_extraction_verifies_and_releases_the_unit(tmp_data_dir):
    """The ladder's happy tail, pinning the state machine's exit — the extractor fails
    once, then succeeds: the retry verifies, and the unit is no longer pending. Without
    this case a gate that quarantines on first failure would pass the two cases above."""
    store, handle, run_id, doc, payload, gate = _scenario(tmp_data_dir)
    payload[:] = [_hallucinated_span()]
    signals = gate.verify(run_id, "SUB-101", "C1")
    assert signals.spans_verified is False
    payload[:] = [_verified_span(doc)]
    signals = gate.verify(run_id, "SUB-101", "C1")
    assert signals.spans_verified is True, (
        "the retried extraction's verified span did not verify — the ladder must end "
        "in release when the retry succeeds, not carry the first failure forward"
    )
    extracted = _units(store, run_id, "SUB-101", "C1", "extract")
    assert not [u for u in extracted if u["status"] == "quarantined"], (
        "one failure quarantined the unit — the ladder is three, and this is one"
    )
    store.close()
