"""`TC-INTEG-07` — a panel reporting `evidence_sufficient = false` is recorded as an
**extraction problem** (re-extract, on repeat to a human, never a low band) — and
`TC-INTEG-12` — the real sweep boundary: always-on checks run between the sweeps, the
sufficiency check runs again **after** scoring, and a consumer reading signals before
Sweep 2 completes sees `sufficiency_flag` in its conservative default.

Test plan §5.9 (07: P0, `FR-INTEG-07`, Integration / 2; 12: P1, `FR-INTEG-01/04`,
Integration / 3 — real neighbouring modules). Written ahead of `#74` (test plan §8.2):
every case fails only through `NotImplementedYet` naming `#74`.

**Routing is asserted on the ledger, name-agnostically** (the TS-24 precedent): a first
insufficiency leaves a fresh `extract` unit (re-extraction); a **repeat** insufficiency
widens the criterion's score units beyond the panel's original three — the escalation
shape §9.10 and `enqueue_escalation` (#60) produce, and the plan's own "on repeat, to a
human". The prohibition half is exact: no `criterion_score` row exists for the routed
criterion — "asserted by confirming no band is written".

**TC-INTEG-12's sequence** is asserted at the two instants the contract names
(CT-INTEG-11): after extraction and before any score unit completes, `verify()` reports
`sufficiency_flag = True` — the conservative default, "because a permissive default
here would let an unscored unit look sufficient" — and after the panel has answered,
the same call reports the panel's verdict. The sufficiency check therefore runs again
after scoring, and the two reads are distinguishable.

Interface assumed of `#74` (reconcile at landing): `IntegrityGate(handle, blobs, view,
ocr_conf_floor=...)` and `verify(run_id, submission_id, criterion_id)` — the full table
lives in `tests/support/integ_vocabulary.py`.
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
    seed_verdict,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

_SUBMISSIONS = ("SUB-201",)
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)
_PANEL_SIZE = 3

_MARKDOWN = "The response develops the claim with two cited details.\n"


def _cited_span(doc: Doc) -> tuple[Span, ...]:
    start = doc.markdown.index("claim")
    return (Span(start, start + len("claim"), "claim"),)


def _scenario(tmp_data_dir, panel: PanelFlags):
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
    handle = store.cohort(ORCH_COHORT_ID)
    doc = Doc(markdown=_MARKDOWN)
    seed_document(handle, document_id_for("SUB-201"), "SUB-201", doc.markdown, ORCH_COHORT_ID)
    orch.enumerate_units(run_id)
    view = ExtractionView(spans=_cited_span(doc), panel=panel)
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=0.70)
    return store, handle, run_id, gate


def _extract_units(store, run_id: str) -> list[dict]:
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT work_id, status, attempts FROM work_unit WHERE run_id = :r AND "
        "submission_id = :s AND criterion_id = :c AND stage = 'extract' ORDER BY work_id",
        r=run_id, s="SUB-201", c="C1",
    )


def _score_units(store, run_id: str) -> list[dict]:
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT work_id, status FROM work_unit WHERE run_id = :r AND "
        "submission_id = :s AND criterion_id = :c AND stage = 'score' ORDER BY work_id",
        r=run_id, s="SUB-201", c="C1",
    )


def _score_rows(store, run_id: str) -> list[dict]:
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT * FROM criterion_score WHERE submission_id = :s AND criterion_id = :c",
        s="SUB-201", c="C1",
    )


# --- TC-INTEG-07 ---------------------------------------------------------------------------

def test_tc_integ_07_one_insufficient_judge_routes_for_re_extraction(tmp_data_dir):
    """`TC-INTEG-07` (P0) — one judge of three reports `evidence_sufficient = false`:
    recorded as an extraction problem — `sufficiency_flag` set, a re-extraction request
    in the ledger — and **never** treated as a low band: no `criterion_score` row is
    written. A majority rule here would silently discard the signal (CT-INTEG-08's
    sweep)."""
    store, handle, run_id, gate = _scenario(
        tmp_data_dir, PanelFlags((True, False, True))
    )
    signals = gate.verify(run_id, "SUB-201", "C1")
    assert signals.sufficiency_flag is True, (
        "a single judge's insufficiency must set the flag — 'any panel member' is the "
        "declared rule (FR-INTEG-07), and unanimity's arithmetic does not apply"
    )
    # A NEW request, not the enumeration's original row: the original extract unit is
    # itself pending at attempts 0, so 'a pending row exists' passes a gate that wrote
    # nothing (review finding) — the route is the retry whose attempts grew.
    retries = [u for u in _extract_units(store, run_id)
               if u["status"] == "pending" and u["attempts"] >= 1]
    assert retries, "an insufficiency flag with no re-extraction request behind it"
    assert not _score_rows(store, run_id), (
        "a criterion_score row exists after an insufficiency routing — the flag was "
        "read as a low band, the exact reading FR-INTEG-07 forbids"
    )
    store.close()


def test_tc_integ_07_repeated_insufficiency_escalates_to_a_human(tmp_data_dir):
    """`TC-INTEG-07`'s repeat half — the same insufficiency again: the escalation shape
    appears (score units beyond the panel's original three, the shape #60's
    `enqueue_escalation` writes), still with no band written."""
    store, handle, run_id, gate = _scenario(
        tmp_data_dir, PanelFlags((False, False, True))
    )
    gate.verify(run_id, "SUB-201", "C1")
    gate.verify(run_id, "SUB-201", "C1")
    score_units = _score_units(store, run_id)
    assert len(score_units) > _PANEL_SIZE, (
        f"two insufficiency rounds left {len(score_units)} score units — the repeat "
        "must escalate to a human, and the escalation is the widened panel the ledger "
        "already knows how to express"
    )
    assert not _score_rows(store, run_id), (
        "the escalation path wrote a band — a human queue and a verdict are mutually "
        "exclusive outcomes of the same signal"
    )
    store.close()


def test_tc_integ_07_unanimous_sufficiency_writes_no_band_from_this_module(tmp_data_dir):
    """`TC-INTEG-07`'s control — a fully sufficient panel: no re-extraction request and
    still no `criterion_score` row, because the module *never* writes one (the score is
    M-AGG's artifact; FR-INTEG-08's write set has no band in it).

    Follow-up reconciliation (TS-66): this control runs BETWEEN the sweeps — scoring
    has produced no verdicts — so `sufficiency_flag` reads its conservative default
    (`True`, the adverse value), not the panel's final permissive value. The former
    `assert ... is False` here contradicted TC-INTEG-12's own conservative-default
    case on identical state; CT-INTEG-11 settles it. The control's subject — no
    routing and no band — is unchanged."""
    store, handle, run_id, gate = _scenario(
        tmp_data_dir, PanelFlags((True, True, True))
    )
    signals = gate.verify(run_id, "SUB-201", "C1")
    assert signals.sufficiency_flag is True, (
        "pre-scoring, the flag must read its conservative default (CT-INTEG-11) — a "
        "permissive value here lets an unscored unit look sufficient"
    )
    assert not [u for u in _extract_units(store, run_id) if u["status"] == "pending"], (
        "a sufficient panel routed for re-extraction — the routing fired without its "
        "condition"
    )
    assert not _score_rows(store, run_id), (
        "M-INTEG wrote a criterion_score row on the happy path — the write set is six "
        "signals and routing requests, never a band"
    )
    store.close()


# --- TC-INTEG-12 ---------------------------------------------------------------------------

def test_tc_integ_12_always_on_checks_run_between_the_sweeps(tmp_data_dir):
    """`TC-INTEG-12` (P1) — extraction complete, scoring not started: the always-on
    checks (verification, evidence presence, OCR intersection, described evidence) are
    computable and computed in that window, from real ledger state."""
    store, handle, run_id, gate = _scenario(
        tmp_data_dir, PanelFlags((True, True, True))
    )
    signals = gate.verify(run_id, "SUB-201", "C1")
    assert signals.spans_verified is True
    assert signals.evidence_present is True
    assert signals.ocr_overlap_risk is False
    assert signals.described_evidence is False
    store.close()


def test_tc_integ_12_sufficiency_reads_conservative_before_scoring_completes(tmp_data_dir):
    """`TC-INTEG-12` — the consumer-facing half of the sequence (CT-INTEG-11): a
    consumer reading signals before Sweep 2 completes sees `sufficiency_flag` in its
    conservative default — True, insufficient — not a permissive False that would let
    an unscored unit look sufficient."""
    store, handle, run_id, gate = _scenario(
        tmp_data_dir, PanelFlags((True, True, True))
    )
    # Sweep 2 has not run: no verdict exists for this criterion.
    verdicts = handle.query(
        "SELECT COUNT(*) AS n FROM verdict WHERE work_id IN (SELECT work_id FROM "
        "work_unit WHERE run_id = :r AND submission_id = :s AND criterion_id = :c)",
        r=run_id, s="SUB-201", c="C1",
    )
    assert verdicts[0]["n"] == 0
    signals = gate.verify(run_id, "SUB-201", "C1")
    assert signals.sufficiency_flag is True, (
        "before Sweep 2 completes the sufficiency signal read permissive — an unscored "
        "unit must not look sufficient (CT-INTEG-11's conservative default)"
    )
    store.close()


def test_tc_integ_12_sufficiency_reruns_after_scoring_and_reports_the_panel(tmp_data_dir):
    """`TC-INTEG-12` — the sufficiency check runs **again** after scoring, since it
    cannot be known before a judge answers: with the panel's verdicts in, the same call
    reports the panel's answer (False here) — distinguishable from the conservative
    default the boundary read returned above."""
    store, handle, run_id, gate = _scenario(
        tmp_data_dir, PanelFlags((True, True, True))
    )
    before = gate.verify(run_id, "SUB-201", "C1")
    assert before.sufficiency_flag is True  # the boundary's conservative default
    # Sweep 2 answers: the panel's verdicts exist (seeded through the real verdict
    # table via the shared helper, the shape M-JUDGE's rows take), and the view now
    # reports sufficiency.
    score_units = _score_units(store, run_id)[:_PANEL_SIZE]
    for i, unit in enumerate(score_units):
        seed_verdict(handle, f"v-integ-{i}", unit["work_id"], f"judge-{i}", "B2")
    after = gate.verify(run_id, "SUB-201", "C1")
    assert after.sufficiency_flag is False, (
        "after the panel answered, the sufficiency signal still reads the conservative "
        "default — the post-scoring rerun (FR-INTEG-07's data flow) did not happen"
    )
    store.close()
