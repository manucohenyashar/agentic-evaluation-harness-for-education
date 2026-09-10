"""`CT-INTEG-11` — the timing split: the always-on checks (FR-INTEG-01..05)
run **between** the sweeps; the sufficiency flag (FR-INTEG-07) can only be
computed **after** scoring, and a consumer reading signals before Sweep 2
completes sees it in its **conservative default**, not its final value
(`TC-INTEG-C11`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#74`.

The clause's consumer-facing half is the case's spine, and it is a
differential on the LEDGER's scoring state with the extraction side held
identical: the same view carrying a unanimous-sufficient panel, read at two
instants. Before Sweep 2 completes (no verdict rows, score units not done)
the sufficiency flag is its conservative default — `True`, the adverse value:
an unscored unit must not look sufficient — even though the "final" value the
view carries is permissive. After verdicts exist, the flag is finally
computed, and the permissive value may appear. A gate that consumes the
panel's flags the moment they are handed to it fails the first limb, and a
gate stuck at the default fails the second — the clause forbids both.

The always-on half pins the other side of the split: at the SAME pre-scoring
instant, the always-on signals are computed for real (a verified span reads
verified, clean regions read unflagged) — the timing split is about the
sufficiency flag only, and a gate that conservatively defaults EVERYTHING
would make the between-sweeps window useless to M-ORCH.

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| the instant | "before Sweep 2 completes" is ledger-observable: extract units exist, no `verdict` rows exist for the criterion, and the criterion's score units are not done. The gate reads that state through its handle; the view's panel flags ride along unread until the instant passes |
| conservative default | `True` (flagged/insufficient) — the adverse value, per the #75 file's fail-closed mapping and FR-INTEG-07's semantics (the flag SET is the adverse reading); a permissive default is the exact bug the plan's wording names ("a permissive default here would let an unscored unit look sufficient") |
| post-scoring source | the second instant seeds `verdict` rows onto the criterion's score units; whether `#74` reads the panel's final flags from the view once scoring is visible, or from the verdicts themselves, is `#74`'s to settle — the differential is on the ledger state, and the post limb asserts only that the flag is finally COMPUTED (not stuck at default) |
| `M-ORCH` consumer | the clause's other consumer; the between-sweeps window's USE is the escalation ladder's (#60's), and TC-INTEG-12's integration suite owns the sweep wiring — this case owns the instant |
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.integ._doubles import OCR_FLOOR, byte_span
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    ExtractionView,
    PanelFlags,
    document_id_for,
    seed_document,
    seed_verdict,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.contract

_SUBMISSION = "SUB-C11"
_CRITERION = "C1"
_SUBMISSIONS = (_SUBMISSION,)
_CRITERIA = ({"criterion_id": _CRITERION, "kind": "open", "scoring_model": "holistic"},)
_MARKDOWN = "The student argues the thesis directly in the opening paragraph.\n"


# --- the checker and its teeth --------------------------------------------------------------


def _assert_conservative_before_scoring(pre_scoring, post_scoring) -> None:
    """The timing oracle: before Sweep 2 completes the flag is the conservative
    default (`True`) — never the permissive final value the view carries; after
    scoring it is finally computed (a permissive final value may appear)."""
    assert pre_scoring.sufficiency_flag is True, (
        f"pre-scoring sufficiency_flag={pre_scoring.sufficiency_flag!r} — a consumer "
        "reading signals before Sweep 2 completes must see the CONSERVATIVE default, "
        "not the final value; a permissive default here lets an unscored unit look "
        "sufficient (CT-INTEG-11)"
    )
    # The construction's panel is unanimous-sufficient, so a COMPUTED flag is
    # permissive: post=True means the gate is stuck at the default.
    assert post_scoring.sufficiency_flag is False, (
        "the flag never computed after scoring — stuck at the default, the opposite "
        "violation: the clause says it CAN be computed once scoring completes"
    )


def test_tc_integ_c11_the_timing_oracle_has_teeth():
    """`TC-INTEG-C11`'s executable construction — the eager gate (reads the
    permissive final value before scoring) and the stuck gate (never computes)
    both go red. Runs green now: it asserts the oracle's teeth, not the
    implementation."""
    from types import SimpleNamespace

    faithful_pre = SimpleNamespace(sufficiency_flag=True)   # conservative default
    faithful_post = SimpleNamespace(sufficiency_flag=False)  # finally computed
    _assert_conservative_before_scoring(faithful_pre, faithful_post)
    eager = SimpleNamespace(sufficiency_flag=False)  # read the final value early
    with pytest.raises(AssertionError, match="CONSERVATIVE default"):
        _assert_conservative_before_scoring(eager, faithful_post)
    stuck = SimpleNamespace(sufficiency_flag=True)  # never computes
    with pytest.raises(AssertionError, match="never computed"):
        _assert_conservative_before_scoring(stuck, stuck)


# --- the differential, over the real ledger --------------------------------------------------


def _scenario(tmp_data_dir, verdicts: bool) -> tuple:
    """A real run and a unanimous-sufficient view, read at one of the two
    instants: `verdicts=False` is before Sweep 2 completes (no verdict rows);
    `verdicts=True` seeds verdicts onto the criterion's score units."""
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=_SUBMISSIONS,
                                      criteria=_CRITERIA)
    handle = store.cohort(ORCH_COHORT_ID)
    seed_document(handle, document_id_for(_SUBMISSION), _SUBMISSION, _MARKDOWN,
                  ORCH_COHORT_ID)
    orch.enumerate_units(run_id)
    span = byte_span(_MARKDOWN, "thesis")
    view = ExtractionView(spans=(span,), regions=(),
                          panel=PanelFlags((True, True, True)))
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=OCR_FLOOR)
    if verdicts:
        score_units = handle.query(
            "SELECT work_id FROM work_unit WHERE run_id = :r AND submission_id = :s "
            "AND criterion_id = :c AND stage = 'score' ORDER BY work_id LIMIT 3",
            r=run_id, s=_SUBMISSION, c=_CRITERION,
        )
        for i, unit in enumerate(score_units):
            seed_verdict(handle, f"v-c11-{i}", unit["work_id"], f"judge-{i}", "B2")
    return handle, run_id, gate, store


def test_tc_integ_c11_before_sweep_two_the_flag_is_its_conservative_default(
        tmp_data_dir):
    """`TC-INTEG-C11` — the exact instant, read: extraction's payload is in the
    view, scoring has produced no verdicts — the consumer's `sufficiency_flag`
    is `True`, the conservative default, NOT the unanimous-sufficient final
    value the view carries."""
    handle, run_id, gate, store = _scenario(tmp_data_dir, verdicts=False)
    verdict_rows = handle.query(
        "SELECT COUNT(*) AS n FROM verdict WHERE work_id IN (SELECT work_id FROM "
        "work_unit WHERE run_id = :r AND submission_id = :s AND criterion_id = :c)",
        r=run_id, s=_SUBMISSION, c=_CRITERION,
    )
    assert verdict_rows[0]["n"] == 0, (
        "the pre-scoring instant was not constructed — verdicts already exist"
    )
    signals = gate.verify(run_id, _SUBMISSION, _CRITERION)
    assert signals.sufficiency_flag is True, (
        f"pre-scoring sufficiency_flag={signals.sufficiency_flag!r} — the view "
        "carries a unanimous-sufficient panel, and the clause requires the consumer "
        "to see the conservative default until scoring completes"
    )
    # The always-on half of the split: at the SAME instant, the always-on
    # checks are computed for real, not defaulted.
    assert signals.spans_verified is True, (
        "the always-on checks were defaulted with the flag — the timing split is "
        "about sufficiency only; the always-on checks run between the sweeps"
    )
    assert signals.evidence_present is True
    assert signals.ocr_overlap_risk is False
    assert signals.described_evidence is False
    store.close()


def test_tc_integ_c11_after_scoring_the_flag_is_finally_computed(tmp_data_dir):
    """`TC-INTEG-C11` — the second instant: verdicts exist for the criterion,
    and the same gate now computes the flag (the unanimous-sufficient panel
    reads permissive). A gate stuck at the conservative default fails here —
    the clause says the flag CAN be computed after scoring, not never."""
    handle, run_id, gate, store = _scenario(tmp_data_dir, verdicts=True)
    verdict_rows = handle.query(
        "SELECT COUNT(*) AS n FROM verdict WHERE work_id IN (SELECT work_id FROM "
        "work_unit WHERE run_id = :r AND submission_id = :s AND criterion_id = :c)",
        r=run_id, s=_SUBMISSION, c=_CRITERION,
    )
    assert verdict_rows[0]["n"] >= 3, (
        "the post-scoring instant was not constructed — no verdicts to read"
    )
    signals = gate.verify(run_id, _SUBMISSION, _CRITERION)
    assert signals.sufficiency_flag is not True, (
        f"post-scoring sufficiency_flag={signals.sufficiency_flag!r} — the flag is "
        "stuck at its conservative default after scoring completed; the clause says "
        "it is computed once scoring is done"
    )
    store.close()


def test_tc_integ_c11_the_two_instants_differ_on_the_same_view(tmp_data_dir):
    """`TC-INTEG-C11`'s differential — the extraction side held identical (same
    view, same unanimous-sufficient payload), only the ledger's scoring state
    changes, and the consumer-visible flag changes with it: conservative before,
    computed after. A gate whose flag does not depend on the scoring state
    fails one limb or the other."""
    pre = _scenario(tmp_data_dir / "pre", verdicts=False)
    post = _scenario(tmp_data_dir / "post", verdicts=True)
    pre_signals = pre[2].verify(pre[1], _SUBMISSION, _CRITERION)
    post_signals = post[2].verify(post[1], _SUBMISSION, _CRITERION)
    _assert_conservative_before_scoring(pre_signals, post_signals)
    pre[3].close()
    post[3].close()
