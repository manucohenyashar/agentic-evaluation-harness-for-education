"""`CT-INTEG-07` — empty evidence on a citation-requiring criterion **routes**
and never auto-scores; there is **no path** by which absent evidence becomes a
lowest-band verdict (`TC-INTEG-C07`).

Case of test plan §6.11.9 (block form); TS-66 (issue #77). Written ahead of
`#74` (the gate half) and `#92` (the `M-AGG` consumer half). The design calls
this the single most consequential negative clause in the module, and the case
is built the way the plan spells it — four limbs, because the bug this clause
exists for (R13) is a *path*, not a value:

1. **Static, over the path graph** — no statement of the module maps an empty
   evidence state to any band or points value: the module never names a band
   id and never writes a scored column. Any lowest-band verdict must either
   name its band or write a scored column, so a module that can do neither has
   no path — including the routes no test ever exercises.
2. **The route, observed** — a citation-requiring criterion with empty
   evidence produces a routing record in the review queue (the plan's declared
   destination) and **no** `criterion_score` row. Asserted on absence, per the
   plan's oracle.
3. **The sweep** — the three ways evidence can be empty (never extracted /
   extracted but every span rejected / extracted for the wrong criterion) must
   route IDENTICALLY: a path that routes for one and scores for another is the
   realistic bug the plan names.
4. **The `M-AGG` consumer half (rung 3)** — `aggregate` over an
   empty-evidence outcome never comes back `auto`, whatever the panel says.
   The rung-4 `M-GRADE` half (the student receives no grade rather than a low
   one, `CT-GRADE-07` carrying it) is deferred with disclosure.

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| route destination | the review queue, plan step-2's declared shape — `review_queue(submission_id, criterion_id, reason)` is the landed schema. The `reason` string is deliberately unpinned (its wording is #74's); the queue row's existence and the score's absence are the oracle. #74 routing through the work ledger INSTEAD fails this case and forces the reconcile — that is the case working |
| "wrong criterion" fixture | a view whose span payload belongs to the other criterion id — `ExtractionView` is subclassed so `spans()` yields the payload only for the other criterion, the one way the seam can express the fixture without a second extraction family |
| adversarial construction | the plan's own (empty→lowest-band behind a default-off package flag) as a synthetic module under `tmp_path`, run through THIS case's static assertion — the construction is pedagogically defensible, which is exactly why the guard is a clause with executable teeth rather than a code review |
| band-id source | bands are per-assessment (`SETUP_MCQ_BAND_NAMES`, config §3.6), but `B0`..`B3` are the canonical band ids every landed surface writes and reads — the literals the static limb forbids. A band id carried from per-assessment setup would ride a write path C04's limb already forbids |
| `M-GRADE` half | deferred with disclosure: the module does not exist yet (its story is `#101`); `CT-GRADE-07`'s no-imputation rule carries the guarantee the rest of the way, and its own suite asserts it when it lands |
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
    Span,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.contract

_SUBMISSION = "SUB-C07"
_CRITERION = "C1"
_OTHER_CRITERION = "C2"
_SUBMISSIONS = (_SUBMISSION,)
_CRITERIA = (
    {"criterion_id": _CRITERION, "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": _OTHER_CRITERION, "kind": "open", "scoring_model": "holistic"},
)
_MARKDOWN = "The student argues the thesis directly in the opening paragraph.\n"

#: The canonical band ids. The static limb forbids the module from naming ANY
#: of them — "no path to a lowest-band verdict" starts with "no path to a
#: verdict at all" (FR-INTEG-08's write set has no band in it).
BAND_IDS = frozenset({"B0", "B1", "B2", "B3"})

_FORBIDDEN_WRITE_COLUMNS = frozenset({"band", "points"})


def _module_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "src" / "aeh" / "integ.py"


def _string_literals(source: str) -> set[str]:
    literals: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(node.value)
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    literals.add(part.value)
    return literals


# --- limb 1: the static path assertion ------------------------------------------------------


def _assert_no_path_from_empty_evidence_to_a_band(source: str, label: str) -> None:
    """The limb-1 oracle, factored out so the adversarial construction faces
    the SAME assertion the real module faces: no band id named anywhere, and
    no attribute store to a scored column."""
    named = _string_literals(source) & BAND_IDS
    assert not named, (
        f"{label} names the band id(s) {sorted(named)} — a module that can spell a "
        "band can write one, and CT-INTEG-07's guarantee is that NO path exists "
        "from absent evidence to a lowest-band verdict"
    )
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            assert node.attr not in _FORBIDDEN_WRITE_COLUMNS, (
                f"{label} assigns .{node.attr} at line {node.lineno} — a write path "
                "to a scored value"
            )


def test_tc_integ_c07_no_path_exists_from_empty_evidence_to_a_band():
    """`TC-INTEG-C07` step 1 — the static limb: over `src/aeh/integ.py`'s
    statements, no band id is ever named and no scored column is ever written.
    The guarantee covers routes no test exercises, which is why it is static;
    the scoring-module import prohibition is C04's limb and not repeated here."""
    require(INTEG_MODULE, issue="#74")  # the module file is the artifact under scan
    _assert_no_path_from_empty_evidence_to_a_band(
        _module_path().read_text(encoding="utf-8"), "aeh.integ")


def test_tc_integ_c07_the_static_limb_has_teeth():
    """`TC-INTEG-C07`'s executable construction — the plan's adversarial module
    (empty evidence mapped to the lowest band behind a default-off package
    flag) goes red on the SAME assertion the real module faces, and a faithful
    module passes. Runs green now: it asserts the limb's teeth, not the
    implementation."""
    violator = (
        "INTEG_SUBSTITUTE_LOWEST_BAND = '1'  # the plan's construction\n"
        "def route(signals):\n"
        "    if not signals.evidence_present and INTEG_SUBSTITUTE_LOWEST_BAND:\n"
        "        return 'B0'  # the student didn't address this criterion\n"
        "    return queue_review(signals)\n"
    )
    with pytest.raises(AssertionError, match="names the band id"):
        _assert_no_path_from_empty_evidence_to_a_band(
            violator, "the substitution mutant")
    faithful = (
        "def route(signals):\n"
        "    if not signals.evidence_present:\n"
        "        return queue_review(signals)\n"
        "    return None\n"
    )
    _assert_no_path_from_empty_evidence_to_a_band(faithful, "the faithful module")


# --- limbs 2 + 3: the route, observed, swept over the three empty evidences ------------------


def _assert_routes_and_never_scores(handle, label: str) -> None:
    """The step-2/3 oracle: a review-queue row exists for the criterion, and no
    `criterion_score` row does — asserted on absence, per the plan."""
    queued = handle.query(
        "SELECT queue_id, reason FROM review_queue WHERE submission_id = :s "
        "AND criterion_id = :c",
        s=_SUBMISSION, c=_CRITERION,
    )
    assert queued, (
        f"{label}: empty evidence produced no review-queue row — the outcome must be "
        "a routing decision, and silence is auto-scoring by another name"
    )
    scored = handle.query(
        "SELECT * FROM criterion_score WHERE submission_id = :s AND criterion_id = :c",
        s=_SUBMISSION, c=_CRITERION,
    )
    assert not scored, (
        f"{label}: a criterion_score row exists for empty evidence — absent evidence "
        "became a verdict, the exact path CT-INTEG-07 forbids (FR-INTEG-03, R13)"
    )


class _WrongCriterionView(ExtractionView):
    """The step-3 fixture: spans were extracted, but for the OTHER criterion —
    this criterion's evidence is empty, and the view says so."""

    def spans(self, submission_id: str, criterion_id: str) -> tuple:
        if criterion_id == _OTHER_CRITERION:
            return self._spans
        return ()


def _scenario(tmp_data_dir, view) -> tuple:
    """One empty-evidence scenario: real run, real document, the view under
    test, and a gate over the real ledger."""
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=_SUBMISSIONS,
                                      criteria=_CRITERIA)
    handle = store.cohort(ORCH_COHORT_ID)
    seed_document(handle, document_id_for(_SUBMISSION), _SUBMISSION, _MARKDOWN,
                  ORCH_COHORT_ID)
    orch.enumerate_units(run_id)
    return handle, run_id, _gate(store, view), store


def _gate(store, view):
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    return IntegrityGate(store.cohort(ORCH_COHORT_ID), store.blobs(), view,
                         ocr_conf_floor=OCR_FLOOR)


def test_tc_integ_c07_the_three_empty_evidences_route_identically(tmp_data_dir):
    """`TC-INTEG-C07` steps 2+3 — never extracted, extracted-then-all-rejected,
    and extracted-for-the-wrong-criterion all produce the SAME outcome: a
    review-queue row and no `criterion_score` row. A path that routes for one
    and scores for another is the realistic bug the plan names."""
    hallucinated = Span(0, 6, "quorum")  # text not in the document: all rejected
    start = _MARKDOWN.encode("utf-8").find(b"thesis")
    good = Span(start, start + len("thesis"), "thesis")
    scenarios = (
        ("never extracted", ExtractionView(panel=PanelFlags((True, True, True)))),
        ("all spans rejected",
         ExtractionView(spans=(hallucinated,), panel=PanelFlags((True, True, True)))),
        ("extracted for the wrong criterion",
         _WrongCriterionView(spans=(good,), panel=PanelFlags((True, True, True)))),
    )
    for label, view in scenarios:
        handle, run_id, gate, store = _scenario(tmp_data_dir / label.replace(" ", "-"),
                                                view)
        signals = gate.verify(run_id, _SUBMISSION, _CRITERION)
        assert signals.evidence_present is False, (
            f"{label}: empty evidence came out evidence_present"
        )
        _assert_routes_and_never_scores(handle, label)
        store.close()


def test_tc_integ_c07_m_agg_never_auto_scores_empty_evidence():
    """`TC-INTEG-C07`'s rung-3 consumer half — `aggregate` over an
    empty-evidence outcome and a fully sufficient, unanimous panel: the routing
    is never `auto`. The cap is what stops the panel's agreement from outrunning
    the evidence's absence."""
    IntegritySignals = require(INTEG_MODULE, "IntegritySignals", issue="#74")
    aggregate, auto_threshold = require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92")
    empty = IntegritySignals(
        spans_verified=True, evidence_present=False, sufficiency_flag=False,
        ocr_overlap_risk=False, described_evidence=False,
        extractor_disagreement=None,
    )
    outcome = aggregate(unanimous_panel("B2"), Criterion(_CRITERION), empty)
    routing = getattr(outcome, "routing", None)
    assert routing != "auto", (
        f"M-AGG auto-scored empty evidence (routing={routing!r}) over a unanimous "
        "panel — absent evidence became a verdict through the consumer, the path "
        "CT-INTEG-07 forbids regardless of where it hides"
    )
    confidence = getattr(outcome, "confidence", None)
    if confidence is not None:
        assert confidence < auto_threshold, (
            f"empty evidence reads confidence {confidence} at or above the "
            f"auto-accept threshold {auto_threshold} — the cap CT-INTEG-07 rides on "
            "is not enforced, and the routing prohibition above holds only by the "
            "outcome's good manners"
        )


# --- limb 4: the rung-4 half, deferred with disclosure --------------------------------------
#
# `TC-INTEG-C07` step 4 — "the student receives no grade for that criterion
# rather than a low one" — is `M-GRADE`'s artifact (its story is #101), and
# `CT-GRADE-07` ("nothing is ever substituted for a missing or unreviewed
# criterion") is the rule that carries it. M-GRADE does not exist yet; the
# case discloses the deferral rather than minting a name for a module that
# cannot be required. When #101 lands, its suite asserts the no-grade
# outcome; this file's limbs 1-3 remain the clause's enforcement above it.
