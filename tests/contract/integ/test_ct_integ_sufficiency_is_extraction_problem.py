"""`CT-INTEG-08` — `evidence_sufficient = false` from **any** panel member is
recorded as an **extraction problem**: the unit re-extracts and, on repeat,
goes to a human. It is **never read as a low band** (`TC-INTEG-C08`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#74` (the
gate/routing half) and `#92` (the `M-AGG` consumer half).

The clause's load-bearing word is **any**: a majority rule here would silently
discard the signal, so the sweep runs every single-flag position — the judge
who flags alone in first, middle, and last seat — plus the unanimous-flag
case, and each must record the same extraction problem: `sufficiency_flag`
set, a re-extraction request in the ledger, no score. The repeat half is the
escalation: the same insufficiency again widens the panel (the shape `#60`'s
`enqueue_escalation` writes) rather than retrying forever — and still writes
no band. The prohibition is carried twice: statically (no statement of the
module names a band or writes a scored column, so no path from an
insufficiency flag to a band exists — including paths never exercised) and at
rung 3 (`aggregate` over an insufficiency-flagged outcome never routes `auto`).

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| escalation shape | score units beyond the panel's original three, the ledger shape the #76 suite (`test_integ_routing_and_sweeps.py`) reconciled for TC-INTEG-07's repeat; a widened panel is how the ledger already expresses "a human joins" |
| static limb | the band-id/scored-column scanner restated locally (no test-to-test imports in this suite); it is deliberately the same assertion C07's limb makes — two clauses forbid the same path from two directions, and each case owns its own oracle |
| retry discriminator | a NEW re-extraction request is a pending extract unit whose attempts grew (the #76 review's finding: "a pending row exists" passes a gate that wrote nothing) |
| `M-JUDGE` side | the panel flags arrive through `ExtractionView.panel_sufficiency` (CT-JUDGE-06's declared shape); M-JUDGE's own suite owns the flags' production |
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aeh.store import open_store
from tests.contract.integ._doubles import Criterion, OCR_FLOOR, unanimous_panel
from tests.support.impl import AGG_MODULE, INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    ExtractionView,
    PanelFlags,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.contract

_SUBMISSION = "SUB-C08"
_CRITERION = "C1"
_SUBMISSIONS = (_SUBMISSION,)
_CRITERIA = ({"criterion_id": _CRITERION, "kind": "open", "scoring_model": "holistic"},)
_MARKDOWN = "The student argues the thesis directly in the opening paragraph.\n"
_PANEL_SIZE = 3

BAND_IDS = frozenset({"B0", "B1", "B2", "B3"})
_FORBIDDEN_WRITE_COLUMNS = frozenset({"band", "points"})


def _module_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "src" / "aeh" / "integ.py"


# --- the oracle and its teeth ---------------------------------------------------------------


def _assert_insufficiency_is_recorded(signals, retries, score_rows) -> None:
    """The extraction-problem oracle: the flag is set — from ANY member, so a
    lone flagger suffices — a re-extraction request exists, and no score was
    written. `signals` here is whatever `verify()` returned; `retries` and
    `score_rows` are the ledger's reads."""
    assert signals.sufficiency_flag is True, (
        f"sufficiency_flag={signals.sufficiency_flag!r} — a false flag from ANY panel "
        "member must be recorded as an extraction problem (FR-INTEG-07); a majority "
        "rule silently discards the lone signal, which is the bug this clause exists for"
    )
    assert retries, (
        "an insufficiency flag with no re-extraction request behind it — recorded, "
        "but not acted on"
    )
    assert not score_rows, (
        "a criterion_score row exists after an insufficiency routing — the flag was "
        "read as a low band, the exact reading FR-INTEG-07 forbids"
    )


def test_tc_integ_c08_the_extraction_problem_oracle_has_teeth():
    """`TC-INTEG-C08`'s executable construction — the majority-rule mutant (a
    lone flagger read as sufficient) and the band-reading mutant go red on the
    oracle. Runs green now: it asserts the oracle's teeth, not the
    implementation."""
    from types import SimpleNamespace

    faithful = SimpleNamespace(sufficiency_flag=True)
    _assert_insufficiency_is_recorded(
        faithful, retries=[{"work_id": "w", "attempts": 1}], score_rows=[])
    majority_rule = SimpleNamespace(sufficiency_flag=False)  # one flagger outvoted
    with pytest.raises(AssertionError, match="majority rule"):
        _assert_insufficiency_is_recorded(
            majority_rule, retries=[{"work_id": "w", "attempts": 1}], score_rows=[])
    with pytest.raises(AssertionError, match="no re-extraction request"):
        _assert_insufficiency_is_recorded(faithful, retries=[], score_rows=[])
    with pytest.raises(AssertionError, match="read as a low band"):
        _assert_insufficiency_is_recorded(
            faithful, retries=[{"work_id": "w", "attempts": 1}],
            score_rows=[{"band": "B0"}])


def _assert_no_path_from_insufficiency_to_a_band(source: str, label: str) -> None:
    """The prohibition's static half: no band id named, no scored column
    written — a path from the flag to a band cannot exist in a module that can
    do neither (the plan's "no path from an insufficiency flag to a band or a
    points value", over the graph rather than over executed routes)."""
    literals: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(node.value)
    named = literals & BAND_IDS
    assert not named, (
        f"{label} names the band id(s) {sorted(named)} — the insufficiency flag's "
        "prohibition is a path claim, and a module that can spell a band has one"
    )
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            assert node.attr not in _FORBIDDEN_WRITE_COLUMNS, (
                f"{label} assigns .{node.attr} at line {node.lineno}"
            )


def test_tc_integ_c08_no_path_from_an_insufficiency_flag_to_a_band():
    """`TC-INTEG-C08` — the prohibition, statically: over `src/aeh/integ.py`'s
    statements no band id is ever named and no scored column is ever written,
    so there is no path from an insufficiency flag to a band or a points value
    — including the paths no FR case exercises."""
    require(INTEG_MODULE, issue="#74")  # the module file is the artifact under scan
    _assert_no_path_from_insufficiency_to_a_band(
        _module_path().read_text(encoding="utf-8"), "aeh.integ")


# --- the sweep: any panel member, every position ---------------------------------------------


def _scenario(tmp_data_dir, panel: PanelFlags) -> tuple:
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=_SUBMISSIONS,
                                      criteria=_CRITERIA)
    handle = store.cohort(ORCH_COHORT_ID)
    seed_document(handle, document_id_for(_SUBMISSION), _SUBMISSION, _MARKDOWN,
                  ORCH_COHORT_ID)
    orch.enumerate_units(run_id)
    view = ExtractionView(
        spans=(),  # the flags are the clause's subject; the spans limb is C06/C07's
        panel=panel,
        evidence_type_requires_citation=False,
    )
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=OCR_FLOOR)
    return handle, run_id, gate, store


def _retries(handle, run_id: str) -> list[dict]:
    return handle.query(
        "SELECT work_id, status, attempts FROM work_unit WHERE run_id = :r AND "
        "submission_id = :s AND criterion_id = :c AND stage = 'extract' "
        "AND status = 'pending' AND attempts >= 1",
        r=run_id, s=_SUBMISSION, c=_CRITERION,
    )


def _score_rows(handle) -> list[dict]:
    return handle.query(
        "SELECT * FROM criterion_score WHERE submission_id = :s AND criterion_id = :c",
        s=_SUBMISSION, c=_CRITERION,
    )


@pytest.mark.parametrize("panel", [
    PanelFlags((False, True, True)),
    PanelFlags((True, False, True)),
    PanelFlags((True, True, False)),
    PanelFlags((False, False, False)),
], ids=["first-alone", "middle-alone", "last-alone", "unanimous"])
def test_tc_integ_c08_a_lone_flagging_judge_is_recorded_as_an_extraction_problem(
        tmp_data_dir, panel):
    """`TC-INTEG-C08` — the sweep over `any`: every single-flag position, and
    the unanimous-flag case, each records the extraction problem — flag set,
    re-extraction requested, no score. A majority rule passes the unanimous
    case and fails every lone-judge one, which is why the sweep is
    positional."""
    handle, run_id, gate, store = _scenario(tmp_data_dir, panel)
    signals = gate.verify(run_id, _SUBMISSION, _CRITERION)
    _assert_insufficiency_is_recorded(signals, _retries(handle, run_id),
                                      _score_rows(handle))
    store.close()


def test_tc_integ_c08_repeated_insufficiency_goes_to_a_human_never_a_band(
        tmp_data_dir):
    """`TC-INTEG-C08` — the repeat half: the same insufficiency again widens
    the panel (score units beyond the original three, the ledger's escalation
    shape) and still writes no `criterion_score` row — a human queue and a
    verdict are mutually exclusive outcomes of the same signal."""
    handle, run_id, gate, store = _scenario(
        tmp_data_dir, PanelFlags((False, True, True)))
    gate.verify(run_id, _SUBMISSION, _CRITERION)
    gate.verify(run_id, _SUBMISSION, _CRITERION)
    score_units = handle.query(
        "SELECT work_id FROM work_unit WHERE run_id = :r AND submission_id = :s "
        "AND criterion_id = :c AND stage = 'score'",
        r=run_id, s=_SUBMISSION, c=_CRITERION,
    )
    assert len(score_units) > _PANEL_SIZE, (
        f"two insufficiency rounds left {len(score_units)} score units — the repeat "
        "must escalate to a human, and the escalation is the widened panel the "
        "ledger already knows how to express"
    )
    assert not _score_rows(handle), (
        "the escalation path wrote a band — a human queue and a verdict are mutually "
        "exclusive outcomes of the same signal"
    )
    store.close()


# --- the rung-3 consumer half ---------------------------------------------------------------


def test_tc_integ_c08_m_agg_never_scores_an_insufficiency_flag():
    """`TC-INTEG-C08`'s rung-3 half — `aggregate` over an insufficiency-flagged
    outcome: the routing is never `auto`. The flag is an extraction problem,
    and a consumer that turns it into a confident verdict has read it as a low
    band through the back door."""
    IntegritySignals = require(INTEG_MODULE, "IntegritySignals", issue="#74")
    aggregate = require(AGG_MODULE, "aggregate", issue="#92")
    insufficient = IntegritySignals(
        spans_verified=True, evidence_present=True, sufficiency_flag=True,
        ocr_overlap_risk=False, described_evidence=False,
        extractor_disagreement=None,
    )
    outcome = aggregate(unanimous_panel("B2"), Criterion(_CRITERION), insufficient)
    routing = getattr(outcome, "routing", None)
    assert routing != "auto", (
        f"M-AGG auto-scored an insufficiency-flagged outcome (routing={routing!r}) — "
        "the flag was read as a low band through the consumer (FR-INTEG-07)"
    )
